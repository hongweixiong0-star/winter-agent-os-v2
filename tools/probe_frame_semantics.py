"""Print the raw template distance matrix for a few frames x a few semantics.

``vision.py`` classifies a page by trying anchors in source order and taking the
first one that is within its threshold.  When a page is misclassified, the useful
question is never "what did it return" but "which anchors were within threshold,
in what order, and how far was the anchor that *should* have won".

``tools/probe_page_anchor.py`` answers that over a whole corpus for a few
semantics.  This tool answers it for a few frames across many semantics, which is
what you want when a single episode regressed and you need to see the exact
competition on that one frame.

It re-implements nothing: it reads the same manifest records and the same
``phash``/``hamming`` pair that ``SemanticROIVision.find`` uses, and it also
honours the same per-semantic threshold table.

Usage
-----
    python tools/probe_frame_semantics.py --semantic PAGE_BEAST_MARCH \
        --semantic STATUS_VICTORY_ASSURED --semantic PAGE_ALLIANCE \
        --frame path/to/after.png --frame path/to/other.png

    # or: let it discover the frames of an episode id
    python tools/probe_frame_semantics.py --episode intel_pins_20260915_000822_nav_01 \
        --semantic PAGE_BEAST_MARCH --semantic PAGE_ALLIANCE
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from winter_agent_v2.image_hash import hamming, phash  # noqa: E402
from winter_agent_v2.vision import SemanticROIVision  # noqa: E402

MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"
EPISODES = ROOT / "learning" / "episodes.jsonl"


def episode_frames(episode_id: str) -> list[Path]:
    frames: list[Path] = []
    for line in EPISODES.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except Exception:
            continue
        if record.get("episode_id") != episode_id:
            continue
        for key in ("before_screenshot", "after_screenshot"):
            value = record.get(key)
            if value:
                path = Path(value)
                if not path.is_absolute():
                    path = ROOT / path
                if path.exists():
                    frames.append(path)
    # De-duplicate while keeping order.
    seen: set[Path] = set()
    unique: list[Path] = []
    for frame in frames:
        if frame not in seen:
            seen.add(frame)
            unique.append(frame)
    return unique


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--semantic", action="append", default=[])
    parser.add_argument("--frame", action="append", default=[])
    parser.add_argument("--episode", action="append", default=[])
    parser.add_argument("--manifest", default=str(MANIFEST))
    parser.add_argument("--max-distance", type=int, default=8)
    args = parser.parse_args()

    frames = [Path(item) if Path(item).is_absolute() else ROOT / item for item in args.frame]
    for episode_id in args.episode:
        frames.extend(episode_frames(episode_id))
    frames = [frame for frame in frames if frame.exists()]
    if not frames:
        print("no frames resolved")
        return 1

    vision = SemanticROIVision(Path(args.manifest), max_distance=args.max_distance)
    records = vision.records

    semantics = args.semantic or sorted({row["semantic"] for row in records})
    print(f"manifest={args.manifest} records={len(records)} frames={len(frames)}")
    print(f"default max_distance={args.max_distance}")

    for frame in frames:
        print(f"\n=== {frame.relative_to(ROOT)} ===")
        rows: list[tuple[int, str, bool]] = []
        for semantic in semantics:
            candidates = [row for row in records if row["semantic"] == semantic]
            best: int | None = None
            for row in candidates:
                template_path = Path(row["template_path"])
                if not template_path.exists():
                    continue
                roi = row["roi_norm"]
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
                distance = hamming(probe, target)
                if best is None or distance < best:
                    best = distance
            if best is None:
                print(f"    {semantic:38s} (no usable template)")
                continue
            threshold = vision.semantic_max_distance.get(semantic, vision.max_distance)
            rows.append((best, semantic, best <= threshold))
        for distance, semantic, matched in sorted(rows):
            marker = "MATCH" if matched else "  .  "
            print(f"    {marker} d={distance:3d}  {semantic}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
