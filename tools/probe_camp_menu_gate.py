"""Measure the two populations for the focused-camp menu crop, over the corpus.

Why this exists (2026-09-17).  `BTN_OPEN_TRAINING_FROM_CAMP` is what makes
`world.training.menu_open` true, and the brain turns that straight into
`OPEN_INFANTRY_TRAINING`, whose action is a tap at this semantic's ROI.  A false
positive here does not merely mislabel a frame -- it sends a tap into the middle of
whatever city happens to be drawn.

The semantic's threshold was tuned on 2026-09-08 for the old crop:

    animated hand/glow changes the selected-camp menu (positives 12-16);
    live Home frames without the menu measured >=20          -> threshold 17

On 2026-09-17 the live loop showed that the old crop only matched 3 of the 7 frames
of one run (d = 4/8/16 the rest MISS), which cost `NAVIGATE_INFANTRY_CAMP` its whole
refresh budget (~21 s) and made the loop re-walk the route.  The replacement crop is
the 300x300 block centred on the 训练 button.  Measured by hand on that run it sits at
0..8 on all seven frames -- but at 16 on a plain HOME frame, i.e. **inside** the old
threshold of 17.  So the crop and the threshold have to be decided together, from
measurement, which is what this script does: it reports both populations over the
whole corpus so the new threshold can be read off the gap rather than guessed.

Read-only.  Reports, per candidate crop:

  * the distance histogram over every corpus frame;
  * how many frames pass at each candidate threshold;
  * which of them are frames that should pass (the archived camp-focus frames) and
    which are not.

Usage
-----
    python tools/probe_camp_menu_gate.py
    python tools/probe_camp_menu_gate.py --json out_camp_gate.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from winter_agent_v2.image_hash import hamming, phash  # noqa: E402

EVIDENCE = ROOT / "dataset" / "truth_audit" / "power_route_20260917"
RUNTIME = ROOT / "dataset" / "raw" / "live_runtime"

REFERENCE = EVIDENCE / "power_route_hop3_20260916_233330_01_after_tap_605_653.png"

# Crop centred on the 训练 button of the focused-camp menu.
CANDIDATES = {
    "camp_menu_300": (376, 705, 676, 1005),
    "camp_menu_280": (386, 715, 666, 995),
}

# Frames that MUST match: every observation of the focused-camp menu in the run.
POSITIVES = [
    REFERENCE,
    RUNTIME / "live_runtime_step_003_after_20260916T234118663280.png",
    RUNTIME / "live_runtime_step_003_after_refresh_1_20260916T234129053654.png",
    RUNTIME / "live_runtime_step_003_after_refresh_2_20260916T234139411099.png",
    RUNTIME / "live_runtime_step_004_before_20260916T234141630421.png",
    RUNTIME / "live_runtime_step_006_after_20260916T234157375117.png",
    RUNTIME / "live_runtime_step_007_before_20260916T234159601034.png",
    ROOT / "dataset" / "raw" / "live_20260908_training_menu_current.png",
]

THRESHOLDS = (8, 10, 12, 14, 17)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    corpus = sorted((ROOT / "dataset" / "raw").rglob("*.png"))
    if not corpus:
        raise SystemExit("no corpus frames under dataset/raw")

    report: dict = {"corpus_frames": len(corpus), "candidates": {}}
    positive_paths = {str(p) for p in POSITIVES}

    for name, box in CANDIDATES.items():
        with Image.open(REFERENCE) as image:
            reference = phash(image.convert("RGB").crop(box))
        histogram: Counter[int] = Counter()
        hits_by_threshold: dict[int, list[str]] = {t: [] for t in THRESHOLDS}
        positive_distances: dict[str, int] = {}
        scanned = 0
        for frame in corpus:
            try:
                with Image.open(frame) as image:
                    image = image.convert("RGB")
                    if image.size != (720, 1280):
                        continue
                    distance = hamming(phash(image.crop(box)), reference)
            except Exception:
                continue
            scanned += 1
            histogram[distance] += 1
            rel = frame.relative_to(ROOT).as_posix()
            for threshold in THRESHOLDS:
                if distance <= threshold:
                    hits_by_threshold[threshold].append(rel)
            if str(frame) in positive_paths:
                positive_distances[rel] = distance

        print("=" * 78)
        print(f"{name}  box={box}  scanned={scanned} frames (720x1280 only)")
        print("  positives (must match):")
        worst_positive = 0
        for path, distance in sorted(positive_distances.items(), key=lambda kv: -kv[1]):
            worst_positive = max(worst_positive, distance)
            print(f"    d={distance:<3} {path}")
        missing = [p for p in sorted(positive_paths)
                   if Path(p).relative_to(ROOT).as_posix() not in positive_distances]
        for path in missing:
            print(f"    NOT SCANNED  {Path(path).relative_to(ROOT).as_posix()}")
        print(f"  worst positive distance: {worst_positive}")
        print("  distance histogram:")
        for distance in sorted(histogram):
            bar = "#" * min(60, histogram[distance])
            print(f"    d={distance:<3} {histogram[distance]:>5}  {bar}")
        print("  frames passing per threshold:")
        for threshold in THRESHOLDS:
            hits = hits_by_threshold[threshold]
            non_positive = [h for h in hits if str(ROOT / h) not in positive_paths]
            print(f"    <={threshold:<3} {len(hits):>5}   non-positive: {len(non_positive)}")
            for entry in non_positive[:6]:
                print(f"          {entry}")
        report["candidates"][name] = {
            "box": list(box),
            "scanned": scanned,
            "worst_positive_distance": worst_positive,
            "positive_distances": positive_distances,
            "histogram": {str(k): v for k, v in sorted(histogram.items())},
            "passing": {str(t): len(hits_by_threshold[t]) for t in THRESHOLDS},
            "non_positive_passers": {str(t): [h for h in hits_by_threshold[t]
                                              if str(ROOT / h) not in positive_paths][:40]
                                     for t in THRESHOLDS},
        }

    if args.json is not None:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        print(f"\nwritten -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
