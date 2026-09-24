"""Validate a registered icon crop against the real corpus: positives must match, terrain must not.

The geometric gate was refuted by this same corpus (see ``tools/calibrate_icon_label_gate.py``),
so what is measured here is the replacement: the project's own crop, matched by the project's own
matcher on the current frame, inside a window derived from the label's own box.

Two questions, both answered with numbers rather than a claim:

1. **Recall.**  On the frames where the label was really drawn (the positives in the corpus), how
   often does the crop match, and with what score?
2. **Specificity.**  On the same frames, does the same crop match somewhere *else* -- a different
   row of the HUD, a town name, the terrain -- when searched over a much wider window?  A crop that
   matches everywhere is a crop that identifies nothing.

Read-only.

Usage:
    python tools/validate_icon_template.py --label 登录好礼
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CORPUS = ROOT / "dataset/truth_audit/icon_label_controls/samples.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="登录好礼")
    parser.add_argument("--corpus", type=Path, default=CORPUS)
    parser.add_argument("--limit", type=int, default=80, help="how many positive frames to test")
    parser.add_argument("--config", default=str(ROOT / "config/v2.json"))
    args = parser.parse_args()

    from winter_agent_v2 import ui_collection
    from winter_agent_v2.matchers import match_ccoeff
    from winter_agent_v2.ocr import read_frame_size

    registry = ui_collection.load_control_registry()
    record = registry.get(args.label)
    if not record:
        print(f"{args.label!r} is not in {ui_collection.ICON_CONTROL_REGISTRY}")
        return 2
    template = ROOT / str(record["template_path"])
    if not template.is_file():
        print(f"template missing: {template}")
        return 3
    print(f"label    : {args.label}")
    print(f"template : {template} ({template.stat().st_size} bytes)")
    print(f"threshold: {ui_collection.MIN_TEMPLATE_SCORE}")

    hits = json.loads(args.corpus.read_text(encoding="utf-8")).get("hits") or []
    frames: dict[str, dict] = {}
    for row in hits:
        if str(row["text"]) == args.label:
            frames.setdefault(str(row["frame"]), row)
    ordered = sorted(frames.items())[: args.limit]
    print(f"positive frames in the corpus: {len(frames)}; testing {len(ordered)}")

    matched: list[float] = []
    missed: list[str] = []
    for frame, row in ordered:
        if not Path(frame).is_file():
            continue
        size = read_frame_size(frame)
        if not size:
            continue
        resolved = ui_collection.registered_icon_region(
            frame, row["label_box"], template_path=template, frame=size
        )
        if resolved is None:
            missed.append(Path(frame).name)
            continue
        matched.append(float(resolved["confidence"]))
    print()
    if matched:
        print(f"RECALL  : matched {len(matched)}/{len(ordered)} = "
              f"{len(matched) / max(len(ordered), 1):.1%}")
        print(f"score   : min/median/max = {min(matched):.3f}/{statistics.median(matched):.3f}/{max(matched):.3f}")
    else:
        print("RECALL  : 0 matched")
    if missed:
        print(f"missed  : {len(missed)} -> {missed[:4]}")

    # Specificity: the same crop, searched over the whole frame on a frame from the corpus.
    print()
    print("specificity (whole-frame search, top match per frame):")
    for frame, row in ordered[:3]:
        if not Path(frame).is_file():
            continue
        size = read_frame_size(frame)
        if not size:
            continue
        whole = {"x_norm": 0.0, "y_norm": 0.0, "w_norm": 1.0, "h_norm": 1.0}
        found = match_ccoeff(Path(frame), template, whole, margin=0)
        if found is None:
            print(f"  {Path(frame).name[:40]}: no match")
            continue
        bx, by, bw, bh = found.bounds
        width, height = int(size[0]), int(size[1])
        print(f"  {Path(frame).name[:40]}: score={found.score:.3f} "
              f"at x={bx / width:.3f} y={by / height:.3f} "
              f"(label at x={row['label_box']['x_norm']:.3f} y={row['label_box']['y_norm']:.3f})")
    return 0 if matched else 5


if __name__ == "__main__":
    raise SystemExit(main())
