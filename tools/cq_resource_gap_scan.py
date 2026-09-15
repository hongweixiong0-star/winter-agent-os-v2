"""Are there INDEPENDENT frames showing the resource strip anchored on a tab that
has no template (BEAST / GIANT_BEAST / SAWMILL)?

The fix options are: add cell templates, or derive the offset from the known
order alone.  Which is available depends on evidence, and the work order forbids
using a template cropped from itself as its own proof -- so the question is
whether a second, independent frame shows the same tab.

Scans only frames that the corpus already associates with resource-panel skills,
so this stays bounded.  Read-only.
"""
from __future__ import annotations

import json
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402
from winter_agent_v2.vision import (  # noqa: E402
    SemanticWorldVision,
    _cell_signature,
    _cell_template_signature,
    _signature_distance,
)

SKILLS = {"SEARCH_RESOURCE", "SELECT_RESOURCE", "SUBMIT_RESOURCE_SEARCH", "RESOURCE_DYNAMIC"}


def main() -> None:
    vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    semantic = vision.semantic

    rows = [
        json.loads(ln)
        for ln in (ROOT / "learning/episodes.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    frames: list[tuple[str, str]] = []
    for r in rows:
        if r.get("skill") not in SKILLS:
            continue
        for key in ("before_screenshot", "after_screenshot"):
            rel = r.get(key) or ""
            if rel:
                p = ROOT / rel
                if p.exists():
                    frames.append((rel, r.get("skill")))
    print("candidate frames from resource-panel episodes:", len(frames))

    # Deduplicate by path, keep order.
    seen = set()
    unique = []
    for rel, skill in frames:
        if rel in seen:
            continue
        seen.add(rel)
        unique.append((rel, skill))
    print("unique frames:", len(unique))

    print()
    print("%-6s %-8s %-14s %s" % ("left", "visible", "best", "frame"))
    print("-" * 110)
    summary = Counter()
    unknown_cells = []
    for rel, _skill in unique:
        path = ROOT / rel
        left_px, fully_visible = semantic.selected_tab_left(path)
        if left_px < 0 or not fully_visible:
            summary["no_bracket_or_clipped"] += 1
            continue
        with Image.open(path) as opened:
            image = opened.convert("RGB")
            width, height = image.size
            y0, y1 = semantic._tab_band_rows(height)
            cell_px = round(semantic.resource_tab_cell * width)
            x0, x1 = round(left_px), round(left_px) + cell_px
            if x0 < 0 or x1 > width:
                summary["cell_clipped"] += 1
                continue
            probe = image.crop((x0, y0, x1, y1))
        probe_signature = _cell_signature(probe)
        best = None
        for resource, paths in semantic.resource_tab_cell_templates.items():
            for tpl in paths:
                sig = _cell_template_signature(pathlib.Path(tpl))
                if sig is None:
                    continue
                value = _signature_distance(probe_signature, sig)
                best = (value, resource) if best is None or value < best[0] else best
        if best is None:
            summary["no_templates"] += 1
            continue
        matched = best[0] <= semantic.resource_tab_max_distance
        summary["matched_a_known_tab" if matched else "anchored_on_an_UNTEMPLATED_tab"] += 1
        if not matched:
            unknown_cells.append((rel, left_px, best[0], best[1], path))
        print("%-6.0f %-8s %-14s %s" % (left_px, fully_visible, "%s %.1f" % (best[1], best[0]), rel[-70:]))

    print()
    print("=== summary ===")
    for k, v in summary.most_common():
        print("   %-32s %d" % (k, v))

    print()
    print("=== frames anchored on a tab with no template (the coverage gap) ===")
    print("   count:", len(unknown_cells))
    for rel, left_px, dist, near, path in unknown_cells:
        print("   left=%-6.0f nearest=%-6s %.1f  %s" % (left_px, near, dist, rel))

    if unknown_cells:
        out = ROOT / "dataset/probe_output/resource_anchor_20260916/untemplated"
        out.mkdir(parents=True, exist_ok=True)
        for i, (rel, left_px, _d, _n, path) in enumerate(unknown_cells):
            with Image.open(path) as opened:
                image = opened.convert("RGB")
                width, height = image.size
                y0, y1 = semantic._tab_band_rows(height)
                cell_px = round(semantic.resource_tab_cell * width)
                x0 = round(left_px)
                crop = image.crop((x0, y0, x0 + cell_px, y1))
            crop.save(out / ("cell_%02d_left%d.png" % (i, round(left_px))))
        print("   wrote", len(unknown_cells), "crops to", out)


if __name__ == "__main__":
    main()
