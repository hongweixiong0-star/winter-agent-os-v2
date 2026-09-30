"""Start (or stop) the machine's single local GUI model server.

Operator directive 2026-09-30: the runtime's one local model is UI-Venus-2-9B Q4_K_M, served
by llama.cpp, and it must be **resident** -- loading a 9B model once per AUTO round is
forbidden, so this is a long-lived process and the runtime only ever speaks HTTP to it.

Why these arguments, and not someone else's
-------------------------------------------
Every number below was measured on this machine (RTX 4060 Laptop, 8188 MiB VRAM, MuMu and MAA
sharing the same GPU) on 2026-09-30 rather than copied from a launch guide:

``-ngl 24`` (of 32 layers)
    Full offload measured **453 MiB free**, which is not enough headroom for the Android
    emulator's own rendering.  24 layers lands at ~1080 MiB free, and the 8 CPU-resident
    layers cost less than the headroom is worth.

``--mmproj`` on the GPU (i.e. no ``--no-mmproj-offload``)
    The single biggest win.  With the vision tower on the CPU, prompt processing ran at
    **62 tok/s** and one screenshot took **20.5 s**.  On the GPU it is **521 tok/s** and the
    same request is ~4 s.  The projector is ~0.9 GB; paying for it out of VRAM was the right
    trade because the alternative is a call that is slower than the model it replaced.

``-ctk q8_0 -ctv q8_0``
    32 layers x 4 KV heads x 256 dim at 8192 context is ~1.07 GB in f16 and ~0.57 GB in q8_0.
    Halving the cache buys the projector's VRAM back.

``--image-min-tokens 1024 --image-max-tokens 1024``
    llama.cpp warns on load that "Qwen-VL models require at minimum 1024 image tokens to
    function correctly on grounding tasks".  Grounding is the only thing this model is used
    for, so the floor is not optional.

``-c 8192 -np 1``
    The context budget the directive fixes, in one slot: one planner step at a time, so the
    whole window belongs to the request in flight instead of being split four ways.

Removing a 9B model from VRAM per round
---------------------------------------
Nothing here reloads the model.  ``--stop`` is for a deliberate restart (a repin, a config
change); the normal state is that this process is already up when the runtime asks.
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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

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

GPU_LAYERS = 24
CONTEXT = 8192


def _server_args() -> list[str]:
    return [
        "-m", str(WEIGHTS),
        "--mmproj", str(MMPROJ),
        "-ngl", str(GPU_LAYERS),
        "-c", str(CONTEXT),
        "-np", "1",
        "-b", "512", "-ub", "512",
        "-ctk", "q8_0", "-ctv", "q8_0",
        "-fa", "on",
        "--image-min-tokens", "1024",
        "--image-max-tokens", "1024",
        "--host", HOST,
        "--port", str(PORT),
        "--alias", ALIAS,
        "--jinja",
    ]


def _port_in_use() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=1.0):
            return True
    except OSError:
        return False


def _health(timeout: float = 180.0) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://{HOST}:{PORT}/health", timeout=5) as response:
                body = json.loads(response.read().decode("utf-8", "replace"))
                if str(body.get("status")) == "ok":
                    return body
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            pass
        time.sleep(2.0)
    return None


def _props() -> dict:
    try:
        with urllib.request.urlopen(f"http://{HOST}:{PORT}/props", timeout=10) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return {}


def start() -> int:
    for path in (SERVER_EXE, WEIGHTS, MMPROJ):
        if not path.exists():
            print(f"MISSING: {path}")
            return 2
    if _port_in_use():
        print(f"already listening on {HOST}:{PORT}; not starting a second server")
        return _report()
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log = LOG_PATH.open("w", encoding="utf-8")
    # Two flags, two jobs.  CREATE_NEW_PROCESS_GROUP keeps the server off this console's Ctrl-C
    # group so a keystroke here cannot kill the resident model; the project's one hidden-window
    # decision (``winproc.hidden_kwargs``) supplies CREATE_NO_WINDOW plus the STARTUPINFO pair so
    # starting the model does not flash a console over the game.  The operator asked for one
    # decision about consoles, not one per tool.
    from winter_agent_v2.winproc import hidden_kwargs

    process = subprocess.Popen(
        [str(SERVER_EXE), *_server_args()],
        stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        creationflags=(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                       | int(hidden_kwargs().get("creationflags", 0))),
    )
    print(f"started llama-server pid={process.pid}")
    if _health() is None:
        print("FAILED: no healthy /health within the wait window; see", LOG_PATH)
        return 3
    return _report()


def _report() -> int:
    props = _props()
    modalities = props.get("modalities") if isinstance(props.get("modalities"), dict) else {}
    report = {
        "endpoint": f"http://{HOST}:{PORT}",
        "model_path": props.get("model_path"),
        "n_ctx": (props.get("default_generation_settings") or {}).get("n_ctx"),
        "multimodal_projector_loaded": bool(modalities.get("vision")),
        "modalities": modalities,
        "resident": True,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
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
    args = parser.parse_args()
    if args.stop:
        return stop()
    if args.status:
        if not _port_in_use():
            print(f"DOWN: nothing listening on {HOST}:{PORT}")
            return 1
        return _report()
    return start()


if __name__ == "__main__":
    sys.exit(main())
