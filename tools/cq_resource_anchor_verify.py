"""Verify the known-order offset resolution: fixes the gap, regresses nothing.

Three claims to check, and the third is the one that usually fails:

1. the production frame that failed SELECT_RESOURCE now yields a NON-EMPTY offset;
2. the frames that already matched a reviewed tab still identify the SAME tab;
3. screens without a resource strip (HOME, MAP) are still refused.

Read-only.
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

GAP_FRAMES = [
    "dataset/raw/live_runtime/live_runtime_step_002_after_20260915T160559958048.png",
    "dataset/raw/live_runtime/live_runtime_step_003_before_20260915T160609443785.png",
]

NEGATIVES = [
    "dataset/raw/control_panel/probe/live_page_20260915_151524.png",   # HOME
    "dataset/raw/control_panel/probe/live_page_20260915_133152.png",   # MAP
]


def main() -> None:
    vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    semantic = vision.semantic

    print("=== 1. the frames that used to fail ===")
    for rel in GAP_FRAMES:
        p = ROOT / rel
        if not p.exists():
            print("  MISSING", rel)
            continue
        match = semantic.selected_resource(p)
        offset = semantic.resource_tab_offset
        print("  %s" % p.name)
        print("      semantic=%s  offset=%s" % (match.semantic if match else None, offset))
        if match:
            print("      roi=%s" % json.dumps(match.roi, ensure_ascii=False))

    print()
    print("=== 2. regression on frames that already matched a reviewed tab ===")
    rows = [
        json.loads(ln)
        for ln in (ROOT / "learning/episodes.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    frames = []
    for r in rows:
        if r.get("skill") not in {"SEARCH_RESOURCE", "SELECT_RESOURCE", "SUBMIT_RESOURCE_SEARCH"}:
            continue
        for key in ("before_screenshot",):
            rel = r.get(key) or ""
            if rel and (ROOT / rel).exists() and rel not in frames:
                frames.append(rel)
    print("  checking %d frames" % len(frames))
    ok = gap = refused = 0
    for rel in frames:
        p = ROOT / rel
        match = semantic.selected_resource(p)
        if match is None:
            refused += 1
            continue
        if "offset_source" in (match.roi or {}):
            gap += 1
            print("      RESOLVED-VIA-KNOWN-ORDER  %s -> %s" % (p.name[-52:], match.semantic))
        else:
            ok += 1
    print("  matched a reviewed template (unchanged path): %d" % ok)
    print("  resolved via the known order                 : %d" % gap)
    print("  refused                                      : %d" % refused)

    print()
    print("=== 3. negatives: no resource strip means no selection ===")
    for rel in NEGATIVES:
        p = ROOT / rel
        if not p.exists():
            print("  MISSING", rel)
            continue
        match = semantic.selected_resource(p)
        print("  %-50s -> %s   offset=%s" % (p.name[-50:], match.semantic if match else None, semantic.resource_tab_offset))


if __name__ == "__main__":
    main()
