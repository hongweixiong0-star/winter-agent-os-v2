"""Count MAP frames whose gauge is unreadable, and crop them for eyeballing.

The question this answers
------------------------
``LiveRuntime`` refuses to tap the map gauge unless the gauge was *read* on that
frame (``runtime.py``: "Refuse unless the gauge was actually read on this frame,
so a popup or a loading screen can never absorb the tap").  But ``before.page is
Page.MAP`` already rules out a popup or a loading screen, so the two conditions
may not be testing the same thing: one asks "is the map on screen", the other
asks "could we read the number".

Measured live 2026-09-15T04:03:02Z the gauge genuinely showed **0** and the ROI
read returned zero tokens, so the run skipped the free-stamina check on the
frame where the free gift mattered most.  ``tools/probe_stamina_zero.py`` showed
no padding or scale lifts that ``0`` above 0.73 confidence, so "read it better"
is not available.

Before relaxing any gate, count the cases: how many MAP frames have no readable
gauge, and is the gauge actually drawn on them?  Writes crops to
``dataset/probe_output/map_gauge_unreadable/`` for visual review.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.ocr import (  # noqa: E402
    HybridVision,
    OCRService,
    RapidOCRBackend,
    ResilientOCRBackend,
)
from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

OUT = ROOT / "dataset" / "probe_output" / "map_gauge_unreadable"
DIRS = (
    "dataset/raw/live_free_gift_claim_20260915",
    "dataset/raw/live_free_gift_claim_20260915b",
    "dataset/raw/live_free_gift_claim_20260915b_extra",
)


def build() -> HybridVision:
    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    backend = ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"])))
    return HybridVision(
        SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json"),
        OCRService(backend),
    )


def main() -> int:
    vision = build()
    frames: list[Path] = []
    for name in DIRS:
        frames.extend(sorted((ROOT / name).glob("*.png")))
    if not frames:
        print("no frames found")
        return 1
    print(f"{len(frames)} frames")

    maps = 0
    unreadable = 0
    OUT.mkdir(parents=True, exist_ok=True)
    for path in frames:
        state = vision.observe(path)
        if state.page.value != "MAP":
            continue
        maps += 1
        if state.stamina.get("current") is not None:
            continue
        unreadable += 1
        with Image.open(path) as source:
            image = source.convert("RGB")
        # The gauge's own neighbourhood, wide enough to judge by eye.
        image.crop((0, 60, 240, 150)).resize((240 * 3, 90 * 3), Image.NEAREST).save(
            OUT / f"{path.stem[-40:]}.png"
        )
        print(f"   MAP without a gauge read: {path.name}")

    print(f"MAP frames={maps}  gauge unreadable={unreadable}")
    if unreadable:
        print(f"crops written to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
