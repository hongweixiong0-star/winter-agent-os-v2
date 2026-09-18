"""Does SCAN_MAP_FOR_BEAST actually pan the world map?

Why this exists (2026-09-18)
---------------------------
The escalation ``SPEND_STAMINA_ON_BEAST|NO_GOAL_PROGRESS|SCAN_MAP_FOR_BEAST``
reported 3 consecutive ``AVOID_STAMINA_WASTE`` runs in which every step passed
its own verifier and no part of the goal advanced.  ``SCAN_MAP_FOR_BEAST`` is a
bounded viewport pan whose verifier only asserts "still on a readable MAP
page", so the one thing nobody had measured is the thing the skill is *for*:
whether the gesture moves the camera at all.

This probe answers exactly that, with the production stack:

    frame A -> production Executor runs the real SCAN_MAP_FOR_BEAST action
            -> frame B -> best-fit translation between the two map regions

It is a *probe*, not a route: it performs the single gesture the skill
declares, reads the shift with the same SSD search the rest of the project
uses for drift, and keeps both frames with provenance.  It does not dispatch a
march, does not tap a target and does not spend stamina.

Read the result as:
  * ``best_shift (dy=0, dx=0)`` and a small residual -> the map did NOT move;
    the "scan" cannot bring an off-screen beast into view.
  * a non-zero best shift -> the map DID move, and the number is the pan size.

Usage
-----
    "E:/dongri-mumu-bot/.venv/Scripts/python.exe" tools/probe_beast_scan_pan.py
    "E:/dongri-mumu-bot/.venv/Scripts/python.exe" tools/probe_beast_scan_pan.py --backend maa
    "E:/dongri-mumu-bot/.venv/Scripts/python.exe" tools/probe_beast_scan_pan.py --duration 1500

``--backend`` exists because the first live measurement (2026-09-18) showed the
ADB gesture reports success and moves nothing, while MaaFramework drives MuMu's
native input channel.  The A/B has to be the same gesture, or the difference
cannot be attributed.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "dataset" / "raw" / "control_panel" / "probe"
STAMP = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

# The exact atomic action the registry declares for SCAN_MAP_FOR_BEAST.
SWIPE_TARGET = "0.50,0.62,0.50,0.30"
SWIPE_DURATION_MS = 600


def build(backend: str = "adb"):
    from winter_agent_v2.device import ADBDevice
    from winter_agent_v2.executor import Executor
    from winter_agent_v2.ocr import (
        HybridVision,
        OCRService,
        RapidOCRBackend,
        ResilientOCRBackend,
    )
    from winter_agent_v2.policy import SafetyPolicy
    from winter_agent_v2.vision import SemanticWorldVision

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    adb_path = Path(config["device"]["adb_path"])
    serial = config["device"]["serial"]
    if backend == "maa":
        from winter_agent_v2.maa_executor import MaaExecutorAdapter

        device = MaaExecutorAdapter(adb_path=adb_path, serial=serial, production=True)
        device.resolve_connection()
    else:
        device = ADBDevice(adb_path, serial, production=True)
        device.resolve_connection()
    template = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    ocr = OCRService(
        ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"])))
    )
    executor = Executor(production=True, dry_run=False, device=device,
                        policy=SafetyPolicy(), backend=backend.upper())
    return device, HybridVision(template, ocr), executor


def best_translation(a, b, *, x0, x1, y0, y1, radius=400, step=4):
    """Smallest mean |A - B shifted by (dy, dx)| -> the camera displacement.

    The first live run saturated at a +/-160 px window (best score landed on the
    boundary), so the window is wide enough to contain a whole gesture: the
    declared swipe travels 0.32 * 1280 = 410 px, so a real pan has to be visible
    inside +/-400 px.
    """
    import numpy as np

    h, w = a.shape
    band_a = a[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
    band_b = b[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
    best = None
    for dy in range(-radius, radius + 1, step):
        for dx in range(-radius, radius + 1, step):
            if dy >= 0:
                ay, by = band_a[dy:, :], band_b[:band_a.shape[0] - dy, :]
            else:
                ay, by = band_a[:dy, :], band_b[-dy:, :]
            if dx >= 0:
                ax, bx = ay[:, dx:], by[:, :ay.shape[1] - dx]
            else:
                ax, bx = ay[:, :dx], by[:, -dx:]
            if ax.shape[0] < 80 or ax.shape[1] < 80:
                continue
            score = float(np.abs(ax.astype("float32") - bx.astype("float32")).mean())
            if best is None or score < best[0]:
                best = (score, dy, dx)
    return best


def main() -> int:
    import numpy as np
    from PIL import Image

    from winter_agent_v2.models import Action

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("adb", "maa"), default="adb")
    parser.add_argument("--duration", type=int, default=SWIPE_DURATION_MS)
    parser.add_argument("--target", default=SWIPE_TARGET)
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    device, vision, executor = build(args.backend)

    tag = f"{args.backend}{args.duration}"
    before_frame = OUT_DIR / f"beast_scan_pan_{STAMP}_{tag}_before.png"
    after_frame = OUT_DIR / f"beast_scan_pan_{STAMP}_{tag}_after.png"

    device.screenshot(before_frame)
    before = vision.observe(before_frame)

    result = executor.execute(Action("SWIPE", args.target,
                                     payload={"duration_ms": args.duration}))

    device.screenshot(after_frame)
    after = vision.observe(after_frame)

    a = np.asarray(Image.open(before_frame).convert("L"), dtype=np.int16)
    b = np.asarray(Image.open(after_frame).convert("L"), dtype=np.int16)
    shift = best_translation(a, b, x0=0.06, x1=0.95, y0=0.20, y1=0.65)

    report = {
        "probe": "SCAN_MAP_FOR_BEAST viewport-pan measurement",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "backend": args.backend,
        "action": {"kind": "SWIPE", "target": args.target,
                   "payload": {"duration_ms": args.duration}},
        "executed": result.executed,
        "execution_error": result.error,
        "executor_backend": result.backend,
        "page_before": before.page.value,
        "page_after": after.page.value,
        "before_frame": str(before_frame),
        "after_frame": str(after_frame),
        "best_shift": {"residual": round(shift[0], 3), "dy_px": shift[1], "dx_px": shift[2]},
        "viewport_moved": abs(shift[1]) > 4 or abs(shift[2]) > 4,
    }
    report_path = OUT_DIR / f"beast_scan_pan_{STAMP}_{tag}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"frames    : {before_frame.name} -> {after_frame.name}")
    print(f"backend   : {args.backend} duration_ms={args.duration}")
    print(f"executed  : {result.executed} backend={result.backend} error={result.error}")
    print(f"page      : {before.page.value} -> {after.page.value}")
    print(f"best shift: dy={shift[1]}px dx={shift[2]}px residual={shift[0]:.3f}")
    print(f"RESULT    : viewport_moved={report['viewport_moved']}")
    print(f"report    : {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
