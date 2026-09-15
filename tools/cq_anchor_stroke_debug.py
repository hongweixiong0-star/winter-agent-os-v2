"""Debug: which stroke pairs does selected_tab_left see, and where is the real bracket?

The frame shows the white bracket on 冰原巨兽 (third visible cell, roughly x 235-390)
while selected_tab_left returned left_px=2.0.  If that is what happened, the bug is
in the anchor detector, not in template coverage -- the opposite of the work
order's hypothesis, so it needs measuring rather than asserting.

Read-only.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402
from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

FRAMES = [
    ROOT / "dataset/raw/live_runtime/live_runtime_step_003_before_20260915T233727132656.png",
    ROOT / "dataset/raw/live_runtime/live_runtime_step_001_before_20260915T233739598714.png",
]


def main() -> None:
    vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    s = vision.semantic
    print("resource_tab_cell  = %.6f  (%.1f px at 720)" % (s.resource_tab_cell, s.resource_tab_cell * 720))
    print("resource_tab_pitch = %.6f  (%.1f px at 720)" % (s.resource_tab_pitch, s.resource_tab_pitch * 720))
    print("resource_tab_band  = %s -> rows %s" % (s.resource_tab_band, s._tab_band_rows(1280)))
    print("pair window accepted: 130..175 px apart")
    print()

    for frame in FRAMES:
        if not frame.exists():
            print("MISSING", frame)
            continue
        print("=" * 92)
        print(frame.name)
        with Image.open(frame) as opened:
            image = opened.convert("RGB")
            width, height = image.size
            strokes = s._bracket_strokes(image)
        print("  %d candidate strokes (centre_x, stroke_width):" % len(strokes))
        for centre, sw in strokes:
            print("     x=%7.1f  w=%.0f" % (centre, sw))
        print()
        print("  stroke pairs within the accepted window:")
        for i, (a, _) in enumerate(strokes):
            for b, _ in strokes[i + 1:]:
                gap = b - a
                if 130 <= gap <= 175:
                    print("     left=%.1f  right=%.1f  gap=%.1f  <-- WOULD BE ACCEPTED" % (a, b, gap))
        left, fv = s.selected_tab_left(frame)
        print()
        print("  selected_tab_left -> left_px=%.1f fully_visible=%s" % (left, fv))
        match = s.selected_resource(frame)
        print("  selected_resource -> %s  offset=%s" % (match, s.resource_tab_offset))


if __name__ == "__main__":
    main()
