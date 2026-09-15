"""Read-only probe: is stamina measurable on the Hero Journey camp panel?

The camp panel is a *map overlay*: the world-map HUD stays on screen, so the
stamina gauge sits at the same place it does on ``Page.MAP``.  ``HybridVision``
however only OCR-enriches stamina on ``Page.MAP`` / ``Page.RESOURCE_DETAIL``,
and the camp panel classifies as ``Page.EXPLORATION`` -- so the brain never
learns the stamina while standing on a fight it may not be able to afford.

This probe measures, per frame:

* the template page + ``exploration.stamina_cost_displayed``
* the raw tokens of ``HUD_STAMINA_ROI``
* ``parse_stamina_number`` on those tokens
* the green gauge pixel count
* what production ``HybridVision.observe`` reports

Usage::

    python tools/probe_camp_panel_stamina.py                 # archived live frames
    python tools/probe_camp_panel_stamina.py --corpus        # whole dataset/raw
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from winter_agent_v2.ocr import (  # noqa: E402
    HUD_STAMINA_ROI,
    HybridVision,
    OCRService,
    RapidOCRBackend,
    ResilientOCRBackend,
    gauge_green_pixels,
    parse_stamina_number,
    read_hud_stamina,
)
from winter_agent_v2.vision import Page, SemanticWorldVision  # noqa: E402

ARCHIVE = ROOT / "dataset" / "truth_audit" / "stamina_check_live_20260915"


def build_stack() -> tuple[SemanticWorldVision, OCRService, HybridVision]:
    """Same stack ``tools/run_live.py`` builds, so the reading is comparable."""
    config = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
    backend = ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"])))
    template = SemanticWorldVision(ROOT / "dataset" / "candidate" / "template_manifest.json")
    ocr = OCRService(backend)
    return template, ocr, HybridVision(template, ocr)


def roi_box(image_path: Path) -> tuple[int, int, int, int]:
    with Image.open(image_path) as source:
        width, height = source.size
    return (
        int(HUD_STAMINA_ROI["x_norm"] * width),
        int(HUD_STAMINA_ROI["y_norm"] * height),
        int((HUD_STAMINA_ROI["x_norm"] + HUD_STAMINA_ROI["w_norm"]) * width),
        int((HUD_STAMINA_ROI["y_norm"] + HUD_STAMINA_ROI["h_norm"]) * height),
    )


def measure(frame: Path, template, ocr: OCRService, production: HybridVision) -> dict:
    state = template.observe(frame)
    tokens = ocr.recognize(frame, HUD_STAMINA_ROI).tokens
    reading = parse_stamina_number(tokens)
    # The MAP branch falls back to a whole-frame pass gated on the same ROI, so
    # measure whether that fallback would rescue the frames the ROI read misses.
    with Image.open(frame) as source:
        width, height = source.size
    full_tokens = ocr.recognize(frame).tokens
    fallback = read_hud_stamina(full_tokens, width, height)
    observed = production.observe(frame)
    return {
        "frame": frame.name,
        "page": state.page.value,
        "cost": state.exploration.get("stamina_cost_displayed"),
        "roi_box": roi_box(frame),
        "tokens": [(t.text.strip(), round(t.confidence, 3)) for t in tokens],
        "reading": reading,
        "fallback": fallback,
        "green_pixels": gauge_green_pixels(frame),
        "observe_page": observed.page.value,
        "observe_stamina": dict(observed.stamina),
    }


def report(rows: list[dict]) -> None:
    readable = 0
    rescued = 0
    for row in rows:
        hit = row["reading"] is not None
        readable += 1 if hit else 0
        rescued += 1 if (not hit and row["fallback"] is not None) else 0
        print(f"\n== {row['frame']}")
        print(f"   template page   : {row['page']}   cost={row['cost']}")
        print(f"   HUD_STAMINA_ROI : {row['roi_box']}  green_px={row['green_pixels']}")
        print(f"   roi tokens      : {row['tokens']}")
        print(f"   -> reading      : {row['reading']}   full-frame fallback: {row['fallback']}")
        print(f"   production      : page={row['observe_page']} stamina={row['observe_stamina']}")
    print(f"\n=== ROI readable on {readable}/{len(rows)} probed frames; full-frame fallback rescues {rescued} more")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", action="store_true", help="scan all of dataset/raw")
    parser.add_argument("--frame", action="append", default=[], help="explicit frame path")
    parser.add_argument("--frames-file", type=Path, default=None, help="one frame path per line")
    args = parser.parse_args()

    template, ocr, production = build_stack()

    if args.frames_file is not None:
        frames = [
            Path(line.strip())
            for line in args.frames_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        rows = [measure(frame, template, ocr, production) for frame in frames]
        report(rows)
        unreadable = [row["frame"] for row in rows if row["reading"] is None]
        print(f"\nunreadable camp panels: {len(unreadable)}")
        for name in unreadable:
            print(f"   {name}")
        return 0

    if args.frame:
        frames = [Path(item) for item in args.frame]
        rows = [measure(frame, template, ocr, production) for frame in frames]
        report(rows)
        return 0

    if args.corpus:
        # Two passes: a cheap template pass over the whole corpus to find the
        # camp panels, then the (expensive) ROI OCR only on those.  Measuring
        # every frame would make the gate cost minutes for no extra evidence.
        everything = sorted((ROOT / "dataset" / "raw").rglob("*.png"))
        camp: list[Path] = []
        for index, frame in enumerate(everything, 1):
            state = template.observe(frame)
            if state.page is Page.EXPLORATION and state.exploration.get("stamina_cost_displayed") is not None:
                camp.append(frame)
            if index % 400 == 0:
                print(f"  ... scanned {index}/{len(everything)}, camp panels so far {len(camp)}", flush=True)
        print(f"\ncorpus: {len(everything)} frames, {len(camp)} Hero Journey camp panels", flush=True)
        rows = [measure(frame, template, ocr, production) for frame in camp]
        report(rows)
        unreadable = [row["frame"] for row in rows if row["reading"] is None]
        print(f"\nunreadable camp panels: {len(unreadable)}")
        for name in unreadable:
            print(f"   {name}")
        return 0

    frames = sorted(ARCHIVE.glob("*.png"))
    rows = [measure(frame, template, ocr, production) for frame in frames]
    report(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
