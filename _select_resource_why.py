"""Why can SELECT_RESOURCE not resolve RESOURCE_DYNAMIC?

The resolver is one line: `resource_cell_center_norm(resource)`, which needs `resource_tab_offset`.
This measures, on the failing steps' own before-frames, whether that offset exists -- and, if not,
whether the panel's printed resource labels were readable anyway.  Read-only.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from winter_agent_v2.ocr import (  # noqa: E402
    OCRService, RapidOCRBackend, ResilientOCRBackend, read_resource_tab_labels,
)
from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

RUNS = ROOT / "dataset/raw/control_panel/runtime_auto"
P = ROOT / "learning" / "episodes.jsonl"

config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
world_vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
semantic = world_vision.semantic
ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))

size = P.stat().st_size
with P.open("rb") as f:
    f.seek(max(0, size - 25_000_000))
    blob = f.read().decode("utf-8", "replace")

picked, seen = [], set()
for line in blob.splitlines():
    line = line.strip()
    if not line.startswith("{"):
        continue
    try:
        r = json.loads(line)
    except json.JSONDecodeError:
        continue
    if r.get("skill") not in ("SELECT_RESOURCE", "SELECT_BEAST_TARGET_MAMMOTH"):
        continue
    if r.get("result") != "FAILURE":
        continue
    shot = str(r.get("before_screenshot") or "")
    ep = str(r.get("episode_id") or "")
    if not shot or ep in seen:
        continue
    path = RUNS / ep / Path(shot.replace("\\", "/")).name
    if not path.exists():
        continue
    seen.add(ep)
    picked.append((r, path))
    if len(picked) >= 4:
        break

print("frames measured:", len(picked))
for r, path in picked:
    print("=" * 96)
    sb = r.get("state_before") or {}
    print("%s %s | step %s | %s" % (str(r.get("recorded_at"))[11:19], r.get("skill"),
                                    r.get("step_id"), str(r.get("decision_reason"))[:60]))
    print("   state_before: page=%s tab=%s lvl=%s search_open=%s" % (
        sb.get("page"), sb.get("resource_selected_tab"), sb.get("resource_level"),
        sb.get("resource_search_open")))
    # the geometry path the resolver actually uses
    sel = semantic.selected_resource(path)
    print("   semantic.selected_resource ->", sel)
    print("   semantic.resource_tab_offset ->", semantic.resource_tab_offset)
    cell = None
    for name in ("MEAT", "WOOD", "COAL", "IRON"):
        got = semantic.resource_cell_center_norm(name)
        if got:
            cell = (name, got)
            break
    print("   resource_cell_center_norm (first non-None of MEAT/WOOD/COAL/IRON) ->", cell)
    print("   anchored_tab_kind ->", semantic.anchored_tab_kind(path))
    labels = read_resource_tab_labels(path, ocr)
    print("   read_resource_tab_labels -> %s" % (
        {k: (round(v[0], 4), round(v[1], 4)) for k, v in labels.items()} or "{}"))
