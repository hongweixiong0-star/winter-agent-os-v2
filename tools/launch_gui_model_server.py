"""Start (or stop) the machine's single local GUI model server.

Operator directive 2026-09-30: the runtime's one local model is UI-Venus-2-9B Q4_K_M, served
by llama.cpp, and it must be **resident** -- loading a 9B model once per AUTO round is
forbidden, so this is a long-lived process and the runtime only ever speaks HTTP to it.

Why these arguments, and not someone else's
-------------------------------------------
Every number below was measured on this machine (RTX 4060 Laptop, 8188 MiB VRAM, MuMu and MAA
sharing the same GPU) on 2026-09-30 rather than copied from a launch guide:

``-ngl 30`` (of 33 layers)
    Chosen from the offload curve below, at the operator's instruction to push offload up after
    the first conservative pick (-ngl 16) was measured.  **More offload is not monotonically
    faster here, and full offload is the worst configuration measured.**  Real UNKNOWN packets,
    ``-c 32768``, f16 KV, n=3:

        -ngl   VRAM free idle/peak   latency p50   RAM peak
         16      1524-1818 MiB        25459 ms        --
         20       763-952  MiB        23347 ms     24.5 GB
         24       244-258  MiB        16878 ms     24.9 GB   <- fastest
         26       869/807  MiB        18209 ms     28.0 GB
         28       657/492  MiB        18902 ms     28.5 GB
         30       265/213  MiB        17041 ms     28.5 GB
         31       250/170  MiB        21011 ms        --
         32       242/112  MiB        21183 ms        --
         33 (all) 132/70   MiB        39935 ms     26.6 GB   <- collapse, 2.3x slower
         99 (->33) 161/88  MiB        59325 ms     27.3 GB

    All ten cells launched, answered, and reported **no CUDA OOM**; 33 layers is not a failure,
    it is a slowdown -- with 70 MiB left, WDDM pages the overflow to system RAM and the GPU waits
    on it.  The knee is one layer wide (32 layers = 21183 ms, 33 layers = 39935 ms), so the
    usable floor is roughly 100-200 MiB of free VRAM.  ``-ngl 30`` sits at 265/213 MiB with a
    p50 within 3% of the fastest cell.  ``tools/profile_device_impact.py`` additionally shows
    that MAA capture p95 rises with offload (21.0 ms at 16, against a 21.3 ms no-model baseline,
    up to 29.8-31.9 ms at 24), so the two measurements pull in opposite directions and the
    chosen value is a deliberate compromise rather than an optimum of either one.

``--mmproj`` on the GPU (i.e. no ``--no-mmproj-offload``)
    The single biggest win.  With the vision tower on the CPU, prompt processing ran at
    **62 tok/s** and one screenshot took **20.5 s**.  On the GPU it is **521 tok/s** and the
    same request is ~4 s.  The projector is ~0.9 GB; paying for it out of VRAM was the right
    trade because the alternative is a call that is slower than the model it replaced.

``-ctk f16 -ctv f16``
    Not the flag that was expected to matter.  UI-Venus-2 is a **hybrid linear-attention** model,
    so at ``n_ctx 32768`` llama.cpp reports ``CPU KV buffer = 272.00 MiB`` and ``CUDA0 KV buffer
    = 272.00 MiB`` plus a 23.03 MiB recurrent-state buffer -- about 570 MiB in total, not the
    multi-gigabyte f16/q8_0 gap that a uniformly-attention model of this size would have.  The
    A/B in ``tools/profile_gui_model_context.py`` therefore found q8_0 buying **91 MiB** of
    VRAM at -ngl 24 while losing on both latency (p50 19.7 s vs 16.9 s) and capture tail (p95
    31.9 ms vs 29.8 ms), so the "q8_0 unless it has side effects" rule has nothing to act on and
    the safer f16 is kept.  **32K is nearly free here.**

``--image-min-tokens 1024 --image-max-tokens 1024``
    llama.cpp warns on load that "Qwen-VL models require at minimum 1024 image tokens to
    function correctly on grounding tasks".  Grounding is the only thing this model is used
    for, so the floor is not optional.  It is also what
    ``context_budget.IMAGE_TOKENS`` charges the frame, so the two numbers have to move
    together.

``-c 32768 -np 1``
    The context the directive fixes, in one slot: one planner step at a time, so the whole
    window belongs to the request in flight instead of being split four ways.  The budget
    module then reserves 4096 of it for the reply, so the prompt is fitted to 28672 -- the
    window is a ceiling, not a target.

Removing a 9B model from VRAM per round
---------------------------------------
Nothing here reloads the model.  ``--stop`` is for a deliberate restart (a repin, a config
change); the normal state is that this process is already up when the runtime asks.

The VRAM ledger, and why 32K did *not* force a smaller ``-ngl``
---------------------------------------------------------------
Measured on 2026-09-30.  The per-process number is not available on Windows (WDDM), so every
figure here is a difference against a stopped server with nvidia-smi, game and MAA running:

    MuMu + desktop + panel, no model           1907 MiB
    model resident, -ngl 24, 8K, q8_0          7432 MiB   -> 5525 MiB for the server
    card total                                 8188 MiB   -> ~6281 MiB usable by the server

The plan assumed 32K would add 1536 MiB at q8_0 (3584 MiB at f16) of KV, and that this would
have to be paid for out of the layers.  The ``-lv 4`` buffer ledger from llama.cpp says
otherwise, at ``-ngl 16 -c 32768``::

    offloaded 16/33 layers
    CPU_Mapped model buffer   2814.61 MiB
    CUDA0 model buffer        2811.89 MiB
    CPU KV buffer              272.00 MiB
    CUDA0 KV buffer            272.00 MiB
    CUDA0 RS buffer             23.03 MiB     <- recurrent state, hybrid linear attention
    CUDA0 compute buffer       315.38 / 248.10 MiB
    CUDA_Host compute buffer    56.38 MiB
    n_ctx_train            262144

The KV cache does not scale the way a uniform-attention model's would, because most of this
model's layers are linear attention and carry a fixed-size recurrent state instead of a growing
cache.  So growing the window from 8K to 32K costs almost nothing in VRAM, and ``-ngl`` stayed a
free parameter that the context never constrained -- it was settled by the offload curve above,
not by the window.  Note that the ledger was captured at ``-ngl 16``; the per-layer split scales
with the value in use.  ``profile_gui_model_context.py`` reproduces the sweep and the ladder.
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
#: ``start`` and ``stop`` both reach for ``winter_agent_v2.winproc``, and running this file as a
#: script puts ``tools/`` -- not the project root -- at the head of ``sys.path``, so the import
#: failed with ``ModuleNotFoundError`` and ``--stop`` silently did nothing while the resident
#: model kept holding its VRAM.  Measured 2026-09-30.  The same two lines every other tool in
#: this directory uses.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.context_budget import MAX_MODEL_CONTEXT  # noqa: E402

#: Where the model files were placed.  Outside the repo on purpose: ~7 GB of weights are not
#: source, and keeping them out means no ignore rule has to be trusted to keep them uncommitted.
MODEL_DIR = Path("E:/winter_models/ui-venus-2-9b")
SERVER_EXE = Path("E:/winter_models/llama.cpp/llama-server.exe")
LOG_PATH = Path("E:/winter_models/llama.cpp/server.log")

WEIGHTS = MODEL_DIR / "UI-Venus-2-9B-Q4_K_M.gguf"
MMPROJ = MODEL_DIR / "mmproj-UI-Venus-2-9B-f16.gguf"

HOST = "127.0.0.1"
PORT = 18080
ALIAS = "UI-Venus-2-9B"

#: Layers offloaded to the GPU.  Chosen from the offload curve in the module docstring: full
#: offload (33) collapses to 2.3x slower, and 30 is the highest value whose p50 is still within
#: 3% of the fastest cell while leaving real VRAM headroom.
GPU_LAYERS = 30

#: The context the directive fixes.  Taken from the budget module rather than written again --
#: the manager is what reserves the reply space inside this number, so a second literal here
#: would be a second source of truth for the one quantity the two must agree on exactly.
CONTEXT = MAX_MODEL_CONTEXT

#: KV cache type.  The A/B in ``profile_gui_model_context.py`` was run expecting q8_0 to win on
#: VRAM and found it instead bought **91 MiB** while losing on latency and on the capture tail:
#: this model is hybrid linear-attention, so the cache is ~570 MiB either way and there is no
#: saving worth a quantisation.  The directive allows q8_0 only on proof of no side effects, so
#: f16 is kept.
KV_TYPE = "f16"


@dataclass(frozen=True)
class ServerProfile:
    """One launch configuration, so the sweep and the production default are the same shape.

    ``profile_gui_model_context.py`` builds these to A/B KV types and offload levels; the
    default here is what production runs.  Keeping the args in a value rather than inline in
    ``start`` is what makes "the profile that was measured" and "the profile that is running"
    the same object instead of two lists that have to be kept in step by eye.
    """

    gpu_layers: int = GPU_LAYERS
    context: int = CONTEXT
    kv_type: str = KV_TYPE
    port: int = PORT

    def server_args(self) -> list[str]:
        return [
            "-m", str(WEIGHTS),
            "--mmproj", str(MMPROJ),
            "-ngl", str(self.gpu_layers),
            "-c", str(self.context),
            "-np", "1",
            "-b", "512", "-ub", "512",
            "-ctk", self.kv_type, "-ctv", self.kv_type,
            "-fa", "on",
            "--image-min-tokens", "1024",
            "--image-max-tokens", "1024",
            "--host", HOST,
            "--port", str(self.port),
            "--alias", ALIAS,
            "--jinja",
        ]

    def to_row(self) -> dict[str, object]:
        return {
            "gpu_layers": self.gpu_layers,
            "context": self.context,
            "kv_type": self.kv_type,
            "port": self.port,
        }


def _port_in_use(port: int = PORT) -> bool:
    try:
        with socket.create_connection((HOST, port), timeout=1.0):
            return True
    except OSError:
        return False


def _health(port: int = PORT, timeout: float = 180.0) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://{HOST}:{port}/health", timeout=5) as response:
                body = json.loads(response.read().decode("utf-8", "replace"))
                if str(body.get("status")) == "ok":
                    return body
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            pass
        time.sleep(2.0)
    return None


def _props(port: int = PORT) -> dict:
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/props", timeout=10) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return {}


def start(profile: ServerProfile | None = None) -> int:
    profile = profile or ServerProfile()
    for path in (SERVER_EXE, WEIGHTS, MMPROJ):
        if not path.exists():
            print(f"MISSING: {path}")
            return 2
    if _port_in_use(profile.port):
        print(f"already listening on {HOST}:{profile.port}; not starting a second server")
        return _report(profile)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log = LOG_PATH.open("w", encoding="utf-8")
    # Two flags, two jobs.  CREATE_NEW_PROCESS_GROUP keeps the server off this console's Ctrl-C
    # group so a keystroke here cannot kill the resident model; the project's one hidden-window
    # decision (``winproc.hidden_kwargs``) supplies CREATE_NO_WINDOW plus the STARTUPINFO pair so
    # starting the model does not flash a console over the game.  The operator asked for one
    # decision about consoles, not one per tool.
    from winter_agent_v2.winproc import hidden_kwargs

    process = subprocess.Popen(
        [str(SERVER_EXE), *profile.server_args()],
        stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        creationflags=(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                       | int(hidden_kwargs().get("creationflags", 0))),
    )
    print(f"started llama-server pid={process.pid} profile={json.dumps(profile.to_row())}")
    if _health(profile.port) is None:
        print("FAILED: no healthy /health within the wait window; see", LOG_PATH)
        return 3
    return _report(profile)


def _report(profile: ServerProfile | None = None) -> int:
    profile = profile or ServerProfile()
    props = _props(profile.port)
    modalities = props.get("modalities") if isinstance(props.get("modalities"), dict) else {}
    settings = props.get("default_generation_settings") or {}
    report = {
        "endpoint": f"http://{HOST}:{profile.port}",
        "model_path": props.get("model_path"),
        "n_ctx": settings.get("n_ctx"),
        "context_requested": profile.context,
        "gpu_layers": profile.gpu_layers,
        "kv_cache_type": profile.kv_type,
        "multimodal_projector_loaded": bool(modalities.get("vision")),
        "modalities": modalities,
        "resident": True,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    # A window that came up short of what was asked for is a hard failure rather than a note:
    # every budget decision downstream is made against ``MAX_MODEL_CONTEXT``, and running with
    # less would put the prompt over the real wall while the ledger still said 32768.
    if report["n_ctx"] and int(report["n_ctx"]) != int(profile.context):
        print(f"FAILED: server reports n_ctx={report['n_ctx']}, "
              f"requested {profile.context}")
        return 5
    return 0 if report["multimodal_projector_loaded"] else 4


def stop() -> int:
    """Stop the resident server through the project's one hidden-window runner.

    ``taskkill`` spawned with a bare ``subprocess.run`` pops a console over the game, which is
    exactly what ``winproc`` exists to prevent -- and ``tools/check_wiring.py`` refuses it.  This
    tool is run from the panel and from a terminal, so the rule applies to it like any other.
    """
    from winter_agent_v2 import winproc

    result = winproc.run(["taskkill", "/F", "/IM", "llama-server.exe"], timeout=20.0)
    print((result.stdout or result.stderr or "").strip() or "no llama-server process")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stop", action="store_true", help="stop the resident server")
    parser.add_argument("--status", action="store_true", help="report health and exit")
    # Overrides exist for ``tools/profile_gui_model_context.py``'s sweep and for a deliberate
    # experiment; the defaults above are production, and nothing in the runtime passes them.
    parser.add_argument("--gpu-layers", type=int, default=GPU_LAYERS,
                        help=f"layers to offload (default {GPU_LAYERS})")
    parser.add_argument("--context", type=int, default=CONTEXT,
                        help=f"context window (default {CONTEXT})")
    parser.add_argument("--kv", default=KV_TYPE, choices=("q8_0", "f16"),
                        help=f"KV cache type (default {KV_TYPE})")
    args = parser.parse_args()
    profile = ServerProfile(gpu_layers=args.gpu_layers, context=args.context, kv_type=args.kv)
    if args.stop:
        return stop()
    if args.status:
        if not _port_in_use(profile.port):
            print(f"DOWN: nothing listening on {HOST}:{profile.port}")
            return 1
        return _report(profile)
    return start(profile)


if __name__ == "__main__":
    sys.exit(main())
