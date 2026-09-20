"""Read-only: what page is the live client on right now, and how does it read?

Why this exists (2026-09-15)
---------------------------
Twice this session the cheapest way to unblock a diagnosis was "look at what
the client is actually showing" -- once when a ``--goal ALLIANCE`` run kept
safe-stopping (the client was parked on the intel board by the hourly
automation) and once when a ``BEAST_HUNT`` failure had to be attributed to a
page misroute rather than to the action.

The production stack can already answer that, but every previous probe
re-implemented the wiring, and a wrong guess about the module layout
(``winter_agent_v2.adb`` does not exist -- it is ``winter_agent_v2.device``)
cost a round trip.  This is the one-liner version.

It captures exactly one frame, classifies it through the full production
``HybridVision`` (template layer merged with OCR), prints the structured
fields, and keeps the frame with provenance under
``dataset/raw/control_panel/probe/``.

Read-only
---------
It never taps anything.  It is safe to run at any time, including while
another loop owns the device (it only reads one screencap).

Usage
-----
    "E:/无尽冬日智能体/.venv/Scripts/python.exe" tools/probe_live_page.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "dataset" / "raw" / "control_panel" / "probe"
STAMP = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

# Structured fields worth printing, in the order a human reads them.  Every
# WorldState field is available; these are the ones that have ever mattered for
# a diagnosis.  Anything empty is skipped so the output stays short.
FIELDS = (
    "popup", "beast", "intel", "alliance", "daily", "mail", "research",
    "training", "building", "exploration", "stamina", "rally", "hospital",
    "rewards", "attempts", "hero_troop", "resource_target",
)


def build():
    sys.path.insert(0, str(ROOT))
    from winter_agent_v2.device import ADBDevice
    from winter_agent_v2.ocr import (
        HybridVision,
        OCRService,
        RapidOCRBackend,
        ResilientOCRBackend,
    )
    from winter_agent_v2.vision import SemanticWorldVision

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    device = ADBDevice(
        Path(config["device"]["adb_path"]),
        config["device"]["serial"],
        production=True,
    )
    device.resolve_connection()
    template = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    ocr = OCRService(
        ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"])))
    )
    return device, HybridVision(template, ocr)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    device, hybrid = build()

    frame = OUT_DIR / f"live_page_{STAMP}.png"
    device.screenshot(frame)
    state = hybrid.observe(frame)

    print(f"frame      : {frame}")
    print(f"page       : {state.page}")
    print(f"confidence : {state.confidence}")
    print(
        "marches    : "
        f"{[m.value if hasattr(m, 'value') else m for m in state.marches]} "
        f"used={state.march_used} max={state.march_max} "
        f"idle={state.normal_idle_slots}"
    )
    for name in FIELDS:
        value = getattr(state, name, None)
        if value:
            print(f"{name:<11}: {json.dumps(value, ensure_ascii=False, default=str)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
