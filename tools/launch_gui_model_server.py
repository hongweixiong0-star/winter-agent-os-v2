"""Start (or stop) the machine's single local GUI model server.

Operator directive 2026-10-08: the runtime's one local model is **Qwen3.6-35B-A3B (Q3_K_M)**
with the mainline mmproj, served by llama.cpp on ``127.0.0.1:18080`` -- it replaces
UI-Venus-2-9B Q4_K_M.  It must be **resident**: loading a 35B MoE once per AUTO round is
forbidden, so this is a long-lived process and the runtime only ever speaks HTTP to it.

Why the profile below looks different from the UI-Venus one
-----------------------------------------------------------
Qwen3.6-35B-A3B is a sparse MoE (3B active of 35B), so the experts go to the CPU
(``-cmoe``) and only the non-expert tensors are offloaded (``-ngl 99``).  Every offload
number further down was measured for the 9B *dense* UI-Venus and is kept only as the record
of how that model was tuned; it no longer describes this launch.  Measured 2026-10-08 on
this machine for the profile that runs now (``-cmoe -ngl 99 -c 32768``, f16 KV,
Q3_K_M + mmproj-F16): about 4.1 GB of 8.2 GB VRAM and about 13.8 GB of 32 GB RAM resident,
and ``tools/probe_gui_model_multimodal.py`` reports ``screenshot_input_verified=true``.
The Q3_K_M quant is the one that pairs with a mainline mmproj: the Ollama-format Q4_K_M
GGUF is refused by mainline llama.cpp (``rope.dimension_sections`` length 3 where 4 is
expected) and its vision metadata is not recognised.

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
MODEL_DIR = Path("E:/winter_models/qwen3.6-35b-a3b")
SERVER_EXE = Path("E:/winter_models/llama.cpp/llama-server.exe")
LOG_PATH = Path("E:/winter_models/llama.cpp/server.log")

WEIGHTS = MODEL_DIR / "Qwen3.6-35B-A3B-Q3_K_M.gguf"
MMPROJ = MODEL_DIR / "mmproj-F16.gguf"

HOST = "127.0.0.1"
PORT = 18080
ALIAS = "Qwen3.6-35B-A3B"

#: Layers offloaded to the GPU.  Chosen from the offload curve in the module docstring: full
#: offload (33) collapses to 2.3x slower, and 30 is the highest value whose p50 is still within
#: 3% of the fastest cell while leaving real VRAM headroom.
GPU_LAYERS = 99

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
    #: How many layers' MoE expert tensors stay in CPU RAM.  ``None`` means "all of them", which
    #: is ``-cmoe`` and is what production runs.
    #:
    #: **The obvious hypothesis was tested and refuted.**  Prompt evaluation is the cost here --
    #: the server's own timings put 5,500-7,800-token prompts at 89-162 tok/s (28-74 s of a 32-80 s
    #: call) against 17-25 tok/s for generation (4.4-6.8 s) -- and with every expert in RAM, each
    #: micro-batch runs its expert FFN on the 8-core CPU.  Moving expert layers to the GPU looked
    #: like the one lever that attacks that directly, and it would spend exactly the resource that
    #: is spare (3,253 MiB of 8,188 MiB free with the model resident and the game running).  It
    #: does not work: same four packets, one restart per row, ``-b/-ub 2048/1024``:
    #:
    #:     cpu_moe_layers   prompt tok/s   generation tok/s   VRAM free at peak
    #:     None (all CPU)      176.6            26.1             3,433 MiB
    #:     28 (5 on GPU)       177.7            21.6             3,415 MiB
    #:
    #: No gain on the half it was aimed at, a loss on the other half, and it buys no VRAM back
    #: either.  So the wall is not the CPU's expert arithmetic, and the spare VRAM is not the
    #: constraint it looked like.  Kept as a knob because a future model may behave differently,
    #: and kept documented because "use the headroom" is a hypothesis that has now been measured
    #: once -- the next account should not re-run it by intuition.
    cpu_moe_layers: int | None = None
    #: Logical and physical batch sizes.  Production ran 512/512, inherited from the UI-Venus era
    #: along with the offload curve; re-measured for this model on 2026-10-08 because the docstring
    #: above already warns that those numbers describe the old launch.
    #:
    #: These are launch-time parameters, not per-request ones: llama.cpp fixes them when the
    #: server starts, and they are *upper bounds* rather than fixed workloads -- a prompt is split
    #: into ``ubatch``-sized chunks, so a 3,000-token request under ``-ub 4096`` runs as one chunk
    #: where under ``-ub 512`` it runs as six.  That is also why the two halves of a call want
    #: opposite things, and the measured table shows both: prompt evaluation (one long chunk)
    #: improves with a bigger ubatch, generation (many single-token steps) gets slower.
    #:
    #: Measured in place on the running server, same four real packets (prompt p50 5,008 tokens),
    #: three repeats per profile, prompt and generation rates read from llama-server's own log:
    #:
    #:     -b/-ub        prompt tok/s (3 runs)      generation tok/s   free VRAM
    #:      512/512       142.6 / 133.7 / 129.7        22.3-24.9        3,496 MiB
    #:     2048/1024      204.6 / 163.6 / 164.4          --            3,471 MiB
    #:     2048/2048      244.8 (1 run)                24.7            3,336 MiB
    #:     4096/4096      294.7 / 189.9 / 188.6        22.4-24.3       2,710 MiB   <- this profile
    #:     8192/8192      295.2 (1 run)                23.8            1,663 MiB   <- no further gain
    #:    16384/16384     -- could not fit --                            169 MiB   <- refused
    #:
    #: The knee is 4,096: 8,192 measures no faster (295.2 against 298.8) while costing a gigabyte
    #: of VRAM, and 16,384 leaves 169 MiB, which the operator's own floor of 300 MiB rejects.
    #: Prompt throughput roughly doubles (133.7 -> 189.9 medians, 298.8 when the GPU is otherwise
    #: idle); generation gives up about 8%.  The spread across repeats is contention from MuMu and
    #: MAA sharing the card, not measurement error, so the medians are what to read.
    #:
    #: **The quality half, and its honest size.**  Twelve calls per profile over the same four
    #: cases, parsed with the production contract:
    #:
    #:     512/512    parsed 9/12  ->  3 distinct cases: DEFER, DEFER, OBSERVE
    #:     2048/1024  parsed 6/12  ->  2 distinct cases: DEFER, DEFER
    #:     4096/4096  parsed 6/12  ->  2 distinct cases: DEFER, DEFER
    #:
    #: Every failure in every profile is the *same* content refusal,
    #: ``PLAN_TARGET_IS_NOT_A_CONTROL`` -- the model naming a printed label -- and reply lengths
    #: are healthy throughout (289-579 chars).  So the reply contract is intact and nothing here
    #: damages the shape of the answer.  But the repeats are byte-identical within a profile, which
    #: means the twelve calls are really *four* independent observations: 3/4 against 2/4 is not
    #: evidence, and this is recorded as an open question rather than a result.  The production
    #: arbiter is the rate of that same refusal in ``learning/local_planner_steps.jsonl``, measured
    #: at **58/322 = 18%** before this change; if it rises materially, go back to ``-b/-ub 512/512``.
    batch: int = 4096
    ubatch: int = 4096

    def server_args(self) -> list[str]:
        moe_args = (["-cmoe"] if self.cpu_moe_layers is None
                    else ["--n-cpu-moe", str(int(self.cpu_moe_layers))])
        return [
            "-m", str(WEIGHTS),
            "--mmproj", str(MMPROJ),
            "-ngl", str(self.gpu_layers),
            *moe_args,
            "-c", str(self.context),
            "-np", "1",
            "-b", str(self.batch), "-ub", str(self.ubatch),
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
            "cpu_moe_layers": self.cpu_moe_layers,
            "batch": self.batch,
            "ubatch": self.ubatch,
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
