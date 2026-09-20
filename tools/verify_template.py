"""Verify one semantic's template against live frames, with a drawn overlay.

Why this exists (2026-09-14): the BTN_HERO_FIGHT template had been cropped
103 px too high, onto the hero-portrait row.  Because a template always
matches its own crop at distance 0, every automated check passed while the
tap landed on the wrong control - three live runs, a seven-point sweep and a
90 s watch were all misled.  A template only proves it is right when it is
checked with (a) an independent signal, (b) a drawn overlay a human (or a
vision model) can look at, and (c) negative-control frames.

Usage (project venv):

    E:/无尽冬日智能体/.venv/Scripts/python.exe tools/verify_template.py SEMANTIC frame1.png [frame2.png ...]

Writes an annotated copy next to each frame as <stem>_verify.png and prints
the match distance plus the overlay coordinates.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

MANIFEST = ROOT / "dataset/candidate/template_manifest.json"


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    semantic = sys.argv[1]
    frames = [Path(p) for p in sys.argv[2:]]
    records = json.loads(MANIFEST.read_text(encoding="utf-8"))["records"]
    rows = [r for r in records if r["semantic"] == semantic]
    if not rows:
        print(f"no records for semantic {semantic!r}")
        return 2
    print(f"records for {semantic}: {len(rows)}")
    for row in rows:
        print(f"  roi={row['roi_norm']} matcher={row.get('matcher', 'phash')} max_distance={row.get('max_distance', 'default')}")
        print(f"  template={row['template_path']}")
        print(f"  provenance={row.get('provenance', '(none)')}")

    vision = SemanticWorldVision(MANIFEST)
    for frame in frames:
        if not frame.is_file():
            print(f"missing frame: {frame}")
            continue
        match = vision.semantic.find(frame, semantic)
        with Image.open(frame) as image:
            annotated = image.convert("RGB")
        draw = ImageDraw.Draw(annotated)
        if match is None:
            print(f"{frame.name}: NO MATCH (every candidate above threshold)")
        else:
            roi = match.roi
            width, height = annotated.size
            box = (
                round(roi["x_norm"] * width),
                round(roi["y_norm"] * height),
                round((roi["x_norm"] + roi["w_norm"]) * width),
                round((roi["y_norm"] + roi["h_norm"]) * height),
            )
            cx = round(match.center_norm[0] * width)
            cy = round(match.center_norm[1] * height)
            draw.rectangle(box, outline=(0, 255, 0), width=3)
            draw.ellipse((cx - 14, cy - 14, cx + 14, cy + 14), outline=(255, 0, 0), width=4)
            draw.text((cx + 18, cy - 8), f"{semantic} d={match.distance}", fill=(255, 0, 0))
            print(f"{frame.name}: distance={match.distance} roi={roi} overlay=({cx},{cy})")
        out = frame.with_name(frame.stem + "_verify.png")
        annotated.save(out)
        print(f"  overlay written: {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    print("\nCHECK THE OVERLAY: the red circle must sit on the control you intend to tap.")
    print("A distance of 0 alone proves nothing - it is what a wrong crop also reports.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
