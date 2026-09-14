"""A/B the two matchers on real frames, positives versus negative controls.

Run inside the project venv (needs PIL/opencv/numpy via rapidocr):

    E:/dongri-mumu-bot/.venv/Scripts/python.exe tools/ab_matcher.py

For each semantic we measure the phash hamming distance (current matcher,
lower is better) and the OpenCV ccoeff score (candidate, higher is better)
on frames where the control is present and on frames where it is absent.
The candidate only becomes the default if the score gap between positives
and negatives is clearly wider than the hamming gap.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.image_hash import hamming, phash  # noqa: E402
from winter_agent_v2.matchers import match_ccoeff  # noqa: E402
from PIL import Image  # noqa: E402

TRUTH = ROOT / "dataset/truth_audit"

CASES = [
    {
        "semantic": "BTN_HERO_FIGHT",
        "positives": [
            TRUTH / "hero_fight_final_20260914/00_before.png",
            TRUTH / "fight_why_20260914/20_now.png",
        ],
        "negatives": [
            TRUTH / "hero_fight_final_20260914/01_after_2.5s.png",  # victory screen
            TRUTH / "fight_why_20260914/10_map.png",                # world map
        ],
    },
    {
        "semantic": "POPUP_HERO_BATTLE_VICTORY",
        "positives": [
            TRUTH / "hero_fight_final_20260914/01_after_2.5s.png",
        ],
        "negatives": [
            TRUTH / "hero_fight_final_20260914/00_before.png",
            TRUTH / "fight_why_20260914/10_map.png",
        ],
    },
]


def phash_distance(image_path: Path, row: dict) -> int | None:
    roi = row["roi_norm"]
    with Image.open(image_path) as image:
        width, height = image.size
        bounds = (
            round(roi["x_norm"] * width),
            round(roi["y_norm"] * height),
            round((roi["x_norm"] + roi["w_norm"]) * width),
            round((roi["y_norm"] + roi["h_norm"]) * height),
        )
        with Image.open(row["template_path"]) as template:
            return hamming(phash(image.crop(bounds)), phash(template))


def main() -> int:
    manifest = json.loads((ROOT / "dataset/candidate/template_manifest.json").read_text(encoding="utf-8"))
    records = {row["semantic"]: row for row in manifest["records"]}
    report = {}
    for case in CASES:
        row = records.get(case["semantic"])
        if row is None:
            print(f"missing record: {case['semantic']}")
            continue
        template_path = ROOT / row["template_path"]
        print(f"\n=== {case['semantic']} ===")
        measured = {"positive": {"phash": [], "ccoeff": []}, "negative": {"phash": [], "ccoeff": []}}
        for kind, frames in (("positive", case["positives"]), ("negative", case["negatives"])):
            for frame in frames:
                if not frame.is_file():
                    print(f"  ({kind}) missing frame {frame.name}")
                    continue
                h = phash_distance(frame, row)
                m = match_ccoeff(frame, template_path, row["roi_norm"])
                measured[kind]["phash"].append(h)
                measured[kind]["ccoeff"].append(round(m.score, 3) if m else None)
                print(f"  {kind:8s} {frame.name:44s} phash={h:3d}  ccoeff={None if m is None else round(m.score, 3)}")
        pos_h = [v for v in measured["positive"]["phash"] if v is not None]
        neg_h = [v for v in measured["negative"]["phash"] if v is not None]
        pos_c = [v for v in measured["positive"]["ccoeff"] if v is not None]
        neg_c = [v for v in measured["negative"]["ccoeff"] if v is not None]
        if pos_h and neg_h and pos_c and neg_c:
            h_gap = min(neg_h) - max(pos_h)
            c_gap = min(pos_c) - max(neg_c)
            print(f"  separation: phash gap={h_gap} (want >0)  ccoeff gap={c_gap:+.3f} (want >0)")
            report[case["semantic"]] = {
                "phash_gap": h_gap,
                "ccoeff_gap": round(c_gap, 4),
                "verdict": "ccoeff clearer" if c_gap > 0 and (h_gap <= 0 or c_gap >= 0.15) else "keep phash",
            }
    print("\n=== VERDICT ===")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    out = ROOT / "evidence" / "ab_matcher_20260914.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote", out.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
