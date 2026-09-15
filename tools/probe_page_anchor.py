"""Measure one or more page-anchor semantics across a corpus of live frames.

Why this exists
---------------
A page branch in ``vision.py`` is only as good as the separation of its anchor
template.  The 2026-09-15 formation-page defect happened because
``PAGE_ALLIANCE`` (a *title strip* whose text is 联盟) matched the 出征 title of
the beast formation page at distance 8 while the correct, purpose-built anchor
``PAGE_BEAST_MARCH`` matched at distance 0 -- but ``PAGE_BEAST_MARCH`` was an
orphan template that no branch ever referenced.

Before wiring an orphan anchor into the classifier we have to prove it separates:
it must hit the intended page and must NOT hit unrelated pages (especially the
page whose branch we are putting it in front of).

This tool is read-only.  It prints, per semantic, the distance distribution over
the corpus and the frames that would match at a given threshold.

Usage
-----
    python tools/probe_page_anchor.py PAGE_BEAST_MARCH STATUS_VICTORY_ASSURED \
        --corpus dataset/raw --threshold 8 --top 15
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402

from winter_agent_v2.image_hash import hamming, phash  # noqa: E402

MANIFEST = Path(__file__).resolve().parents[1] / "dataset" / "candidate" / "template_manifest.json"


def load_records() -> list[dict]:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return payload["records"]


def distance_for(image_path: Path, row: dict) -> int | None:
    roi = row["roi_norm"]
    template_path = Path(row["template_path"])
    if not template_path.exists():
        return None
    try:
        with Image.open(image_path) as image:
            width, height = image.size
            bounds = (
                round(roi["x_norm"] * width),
                round(roi["y_norm"] * height),
                round((roi["x_norm"] + roi["w_norm"]) * width),
                round((roi["y_norm"] + roi["h_norm"]) * height),
            )
            probe = phash(image.crop(bounds))
        with Image.open(template_path) as template:
            target = phash(template)
    except Exception:
        return None
    return hamming(probe, target)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("semantics", nargs="+")
    parser.add_argument("--corpus", default="dataset/raw")
    parser.add_argument("--threshold", type=int, default=8)
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--limit", type=int, default=0, help="0 = no limit")
    args = parser.parse_args()

    corpus = Path(args.corpus)
    if not corpus.is_absolute():
        corpus = Path(__file__).resolve().parents[1] / corpus
    frames = sorted(corpus.rglob("*.png"))
    if args.limit:
        frames = frames[: args.limit]
    print(f"corpus={corpus} frames={len(frames)} threshold={args.threshold}")

    records = load_records()
    for semantic in args.semantics:
        rows = [row for row in records if row.get("semantic") == semantic]
        if not rows:
            print(f"\n=== {semantic}: NOT IN MANIFEST ===")
            continue
        print(f"\n=== {semantic}: {len(rows)} reviewed template(s) ===")
        for row in rows:
            print(f"    {row['template_id']}  roi={row['roi_norm']}  src={row.get('source')}")

        scored: list[tuple[int, str]] = []
        skipped = 0
        for frame in frames:
            best: int | None = None
            for row in rows:
                value = distance_for(frame, row)
                if value is None:
                    skipped += 1
                    continue
                if best is None or value < best:
                    best = value
            if best is not None:
                scored.append((best, str(frame.relative_to(Path(__file__).resolve().parents[1]))))

        scored.sort()
        hits = [item for item in scored if item[0] <= args.threshold]
        print(f"    measured={len(scored)} unreadable={skipped}")
        print(f"    would match at <= {args.threshold}: {len(hits)} frame(s)")
        for distance, name in scored[: args.top]:
            marker = "MATCH" if distance <= args.threshold else "     "
            print(f"    {marker} d={distance:3d}  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
