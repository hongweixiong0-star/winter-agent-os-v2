"""What does the march counter actually read on a real MAP frame?

The gather workflow cannot start because `march_used` is None on genuine world-map
frames while `march_max` is read fine (live: CHECK_MARCH / MARCH_COUNT_NOT_READ,
2026-09-15T12:59:36Z, before and after both None).  Before changing anything,
look at what the counter ROI contains and what OCR returns from it.

Read-only.
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402
from winter_agent_v2.ocr import (  # noqa: E402
    MARCH_COUNT_ROI,
    HybridVision,
    OCRService,
    RapidOCRBackend,
    ResilientOCRBackend,
    parse_stamina_number,
    read_march_count,
)
from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

FRAMES = [
    "dataset/evidence/maa_live/state_maa_20260915T124440.png",
    "dataset/raw/control_panel/probe/live_page_20260915_133152.png",
    "dataset/raw/live_runtime/live_runtime_step_001_before_20260915T125843883794.png",
]


def main() -> None:
    print("MARCH_COUNT_ROI =", json.dumps(MARCH_COUNT_ROI, ensure_ascii=False))
    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    template = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    ocr_service = OCRService(
        ResilientOCRBackend(RapidOCRBackend(pathlib.Path(config["ocr"]["module_path"])))
    )
    vision = HybridVision(template, ocr_service)

    out = ROOT / "dataset/probe_output/march_count_20260915"
    out.mkdir(parents=True, exist_ok=True)

    for rel in FRAMES:
        p = ROOT / rel
        print()
        print("=" * 78)
        if not p.exists():
            print("MISSING", rel)
            continue
        print(rel)
        state = vision.observe(p)
        print("  page=%s conf=%.2f march_used=%s march_max=%s marches=%s"
              % (state.page.value, state.confidence, state.march_used, state.march_max,
                 [str(m) for m in state.marches]))
        # read_march_count takes TEXT, not a path -- the production call site
        # passes `recognize(...).text`, so pass the same thing here.
        print("  read_march_count(text) ->", read_march_count(ocr_service.recognize(p, MARCH_COUNT_ROI).text))

        with Image.open(p) as im:
            w, h = im.size
            x0 = round(MARCH_COUNT_ROI["x_norm"] * w)
            y0 = round(MARCH_COUNT_ROI["y_norm"] * h)
            x1 = round((MARCH_COUNT_ROI["x_norm"] + MARCH_COUNT_ROI["w_norm"]) * w)
            y1 = round((MARCH_COUNT_ROI["y_norm"] + MARCH_COUNT_ROI["h_norm"]) * h)
            print("  ROI bounds on %dx%d -> %s" % (w, h, (x0, y0, x1, y1)))
            crop = im.crop((x0, y0, x1, y1))
            scaled = crop.resize(((x1 - x0) * 6, (y1 - y0) * 6), Image.NEAREST)
            dst = out / ("%s_marchcount.png" % p.stem[:40])
            scaled.save(dst)
            print("  wrote", dst.name)

        tokens = ocr_service.recognize(p, MARCH_COUNT_ROI).tokens
        print("  OCR tokens in that ROI: %s"
              % [(t.text, round(t.confidence, 2)) for t in tokens])


if __name__ == "__main__":
    main()
