"""Decide whether an orphan page anchor is safe to wire into the classifier.

For a candidate anchor pair (a page title strip plus a status line) this tool
answers the only question that matters before editing ``vision.py``:

    For every live frame where the candidate anchor matches, what does the
    CURRENT production classifier say the page is?

If the answer is always "already that page", wiring the anchor in is a
no-behaviour-change stabilisation (the anchor is simply more stable than the
button template that currently wins).  If some frames currently report a
DIFFERENT page, that is the real behavioural change and every one of those
frames must be reviewed by hand before the patch lands -- and if any of them is
the page whose branch the new anchor would be placed in front of, the patch is
wrong and must be redesigned.

Read-only.  Nothing here writes to the project.

Usage
-----
    python tools/probe_anchor_decision.py --anchor PAGE_BEAST_MARCH \
        --anchor STATUS_VICTORY_ASSURED --corpus dataset/raw
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from winter_agent_v2.image_hash import hamming, phash  # noqa: E402
from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--anchor", action="append", default=[])
    parser.add_argument("--corpus", default="dataset/raw")
    parser.add_argument("--threshold", type=int, default=8)
    parser.add_argument("--dump", default="")
    args = parser.parse_args()

    corpus = Path(args.corpus)
    if not corpus.is_absolute():
        corpus = ROOT / corpus
    frames = sorted(corpus.rglob("*.png"))

    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records = payload["records"]
    by_semantic: dict[str, list[dict]] = defaultdict(list)
    for row in records:
        by_semantic[row["semantic"]].append(row)

    for anchor in args.anchor:
        if anchor not in by_semantic:
            print(f"{anchor}: NOT IN MANIFEST")
            return 1

    def distance(frame: Path, row: dict) -> int | None:
        template_path = Path(row["template_path"])
        if not template_path.exists():
            return None
        roi = row["roi_norm"]
        try:
            with Image.open(frame) as image:
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

    hits: dict[Path, dict[str, int]] = {}
    for frame in frames:
        per_anchor: dict[str, int] = {}
        for anchor in args.anchor:
            best = min(
                (value for row in by_semantic[anchor] if (value := distance(frame, row)) is not None),
                default=None,
            )
            if best is not None and best <= args.threshold:
                per_anchor[anchor] = best
        if per_anchor:
            hits[frame] = per_anchor

    print(f"corpus={corpus} frames={len(frames)} threshold={args.threshold}")
    print(f"frames where any anchor matched: {len(hits)}")

    if not hits:
        return 0

    vision = SemanticWorldVision(MANIFEST, max_distance=8)
    observed: dict[Path, str] = {}
    for frame in hits:
        try:
            state = vision.observe(frame)
            observed[frame] = state.page.value
        except Exception as exc:  # pragma: no cover - diagnostic only
            observed[frame] = f"ERROR:{type(exc).__name__}"

    current = Counter(observed.values())
    print("\ncurrent production page over those frames:")
    for page, count in current.most_common():
        print(f"    {count:4d}  {page}")

    print("\nper current page -> frames (up to 6 shown each):")
    grouped: dict[str, list[Path]] = defaultdict(list)
    for frame, page in observed.items():
        grouped[page].append(frame)
    for page, items in sorted(grouped.items(), key=lambda item: -len(item[1])):
        print(f"  [{page}] {len(items)}")
        for frame in sorted(items)[:6]:
            print(f"      {frame.relative_to(ROOT)}  anchors={hits[frame]}")

    if args.dump:
        target = Path(args.dump)
        if not target.is_absolute():
            target = ROOT / target
        target.write_text(
            json.dumps(
                [
                    {
                        "frame": str(frame.relative_to(ROOT)),
                        "current_page": observed[frame],
                        "anchors": hits[frame],
                    }
                    for frame in sorted(hits)
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nwrote {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
