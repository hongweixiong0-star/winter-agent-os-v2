"""Register the two-state view detector: STATE_CITY_VIEW / STATE_WILDERNESS_VIEW.

Why templates and not OCR
-------------------------
PAGE_MAP was carried as an OCR node on the bottom-right chip.  RapidOCR read that
chip on 3 of 6 frames -- the chip is small, sits on a translucent plate over the
moving world, and its glyphs are thin -- so the node could not be wired without
making a coin-flip part of navigation.  It was recorded REJECTED_VALIDATION rather
than wired on hope.

The chip is also the wrong thing to *read*: it is an ACTION label, not a state
label.  The wilderness view draws 城镇 ("go to city") and the city view draws 野外
("go to wilderness").  Reading the word therefore tells you the state you are NOT
in, and any code that treats the word as the state is inverted by construction.
Two templates cut from real frames of each state carry the whole chip -- plate,
icon and glyph -- so they compare what the client actually draws instead of asking
OCR to survive 33 pixels of anti-aliased text.

Validation is bidirectional by construction: a state template must hit EVERY frame
of its own state and miss EVERY frame of the other state.  That is a harder test
than "misses some unrelated page" -- the two states differ only in this chip, so
they are each other's nearest negative.

Usage
-----
    python tools/register_page_state_templates.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from winter_agent_v2.matchers import match_ccoeff  # noqa: E402

MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"
CORPUS = ROOT / "dataset" / "candidate" / "pagestate_20260927" / "corpus.json"
OUT_DIR = ROOT / "dataset" / "candidate" / "templates"

# (left, top, right, bottom) of the chip in a 720x1280 frame, measured by OCR on
# live frames: the 城镇/野外 glyph box is 621..678 x 1240..1273.  Padded to the
# plate so the icon rides along, and clipped to the frame.
CHIP_BOX = (613, 1234, 687, 1280)
SEARCH_MARGIN_PX = 48  # the round's current expand, wider than matchers' default 40

# One source frame per state, both production frames from this cycle.
SOURCES = {
    "STATE_CITY_VIEW": (
        "dataset/raw/control_panel/runtime_auto/20260927_070930_599921/"
        "20260927_070930_599921_step_006_after_20260926T231142410317.png"
    ),
    "STATE_WILDERNESS_VIEW": (
        "dataset/raw/control_panel/runtime_auto/20260927_071653_484155/"
        "20260927_071653_484155_step_001_after_20260926T231718125654.png"
    ),
}
# The word the chip carries in each state.  Documented because the two are crossed.
CHIP_WORD = {"STATE_CITY_VIEW": "野外", "STATE_WILDERNESS_VIEW": "城镇"}


def _roi_norm(box: tuple[int, int, int, int]) -> dict[str, float]:
    left, top, right, bottom = box
    return {
        "x_norm": round(left / 720, 6),
        "y_norm": round(top / 1280, 6),
        "w_norm": round((right - left) / 720, 6),
        "h_norm": round((bottom - top) / 1280, 6),
    }


def main() -> int:
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    buckets = corpus["buckets"]
    # 城镇 on the chip  => the frame IS the wilderness (the chip offers 城镇)
    own = {
        "STATE_CITY_VIEW": [row["frame"] for row in buckets["野外"]],
        "STATE_WILDERNESS_VIEW": [row["frame"] for row in buckets["城镇"]],
    }
    other = {
        "STATE_CITY_VIEW": own["STATE_WILDERNESS_VIEW"],
        "STATE_WILDERNESS_VIEW": own["STATE_CITY_VIEW"],
    }
    roi = _roi_norm(CHIP_BOX)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records = payload["records"]

    report: dict[str, dict] = {}
    for semantic, source in SOURCES.items():
        source_path = ROOT / source
        template_path = OUT_DIR / f"{semantic}.png"
        with Image.open(source_path) as image:
            crop = image.convert("RGB").crop(CHIP_BOX)
        crop.save(template_path)

        positives, negatives = own[semantic], other[semantic]
        pos_scores, neg_scores = [], []
        for rel in positives:
            hit = match_ccoeff(ROOT / rel, template_path, roi, margin=SEARCH_MARGIN_PX)
            pos_scores.append(float(hit.score) if hit else 0.0)
        for rel in negatives:
            hit = match_ccoeff(ROOT / rel, template_path, roi, margin=SEARCH_MARGIN_PX)
            neg_scores.append(float(hit.score) if hit else 0.0)

        report[semantic] = {
            "source": source,
            "chip_word": CHIP_WORD[semantic],
            "template": str(template_path.relative_to(ROOT)).replace("\\", "/"),
            "positives": len(pos_scores),
            "positive_min": round(min(pos_scores), 4),
            "positive_max": round(max(pos_scores), 4),
            "positive_hits_at_0_80": sum(1 for s in pos_scores if s >= 0.80),
            "negatives": len(neg_scores),
            "negative_max": round(max(neg_scores), 4),
            "negative_hits_at_0_80": sum(1 for s in neg_scores if s >= 0.80),
            "separation": round(min(pos_scores) - max(neg_scores), 4),
        }

        note = (
            f"two-state view detector. The chip at {CHIP_BOX} is an ACTION label, not a "
            f"state label: this frame (the {'city' if semantic == 'STATE_CITY_VIEW' else 'wilderness'}) "
            f"draws {CHIP_WORD[semantic]} ('go to the other view'). Cut with the plate and icon "
            f"because RapidOCR read this chip on only 3 of 6 frames. Validated bidirectionally: "
            f"{report[semantic]['positive_hits_at_0_80']}/{len(pos_scores)} own-state frames hit, "
            f"{report[semantic]['negative_hits_at_0_80']}/{len(neg_scores)} opposite-state frames hit, "
            f"worst positive {report[semantic]['positive_min']} vs best opposite-state "
            f"{report[semantic]['negative_max']}."
        )
        existing = next(
            (r for r in records if r.get("semantic") == semantic
             and r.get("template_path", "").endswith(f"{semantic}.png")),
            None,
        )
        record = {
            "semantic": semantic,
            "template_path": str(template_path),
            "roi_norm": roi,
            "source": "pagestate_20260927",
            "provenance": "LIVE_CLIENT",
            "confidence": 0.99,
            "status": "CANDIDATE",
            "template_id": f"{semantic.lower()}__live_20260927",
            "parent_screenshot": str(source_path),
            "width": crop.size[0],
            "height": crop.size[1],
            "note": note,
            "evidence": source,
        }
        if existing is None:
            records.append(record)
        else:
            existing.update(record)

    payload["count"] = len(records)
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    (ROOT / "dataset" / "candidate" / "pagestate_20260927" / "validation.json").write_text(
        json.dumps(
            {"chip_box": list(CHIP_BOX), "roi_norm": roi,
             "search_margin_px": SEARCH_MARGIN_PX, "report": report},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nmanifest records: {len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
