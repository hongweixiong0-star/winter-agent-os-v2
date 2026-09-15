"""Validate the anchor search against the archived beast-first-offset frames.

tests/test_resource_tab_anchor.py already archives frames where the panel sits at
the beast-first scroll offset, and currently asserts they must be REFUSED.  That
refusal is what leaves resource_tab_offset None and stops the executor from
tapping or scrolling anything -- so the question is whether the new evidence-based
resolution identifies them correctly, with enough support to be trusted.

Prints what the new code says and how strongly, so the answer is measured rather
than assumed.  Read-only.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402
from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

FRAMES = [
    ("beast_first", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_003_search_panel.png"),
    ("after_tap_meat", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_004_tab_tap_MEAT.png"),
    ("after_tap_wood", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_005_tab_tap_WOOD.png"),
    ("after_tap_coal", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_006_tab_tap_COAL.png"),
    ("after_tap_iron", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_007_tab_tap_IRON.png"),
]


def main() -> None:
    vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    s = vision.semantic

    print("%-16s %-26s %-10s %-8s %s" % ("label", "selected_resource", "offset", "support", "margin"))
    print("-" * 96)
    for label, rel in FRAMES:
        p = ROOT / rel
        if not p.exists():
            print("%-16s MISSING %s" % (label, rel))
            continue
        match = s.selected_resource(p)
        roi = match.roi if match else {}
        print(
            "%-16s %-26s %-10s %-8s %s"
            % (
                label,
                match.semantic if match else "None",
                s.resource_tab_offset,
                roi.get("supporting_reviewed_tabs", "-"),
                roi.get("support_margin", "-"),
            )
        )

    print()
    print("=== full candidate table for the beast-first frame ===")
    p = ROOT / FRAMES[0][1]
    if p.exists():
        with Image.open(p) as opened:
            image = opened.convert("RGB")
            width, height = image.size
            print("  accepted anchor candidates:", s.candidate_tab_lefts_from(image))
            for support, margin, left, anchored in s._supported_offsets(image, width, height):
                print("   left=%-7.1f anchored=%-12s support=%d margin=%.2f" % (left, anchored, support, margin))


if __name__ == "__main__":
    main()
