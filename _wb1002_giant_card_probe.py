"""Read-only: was a polar-terror card actually drawn on the failing step's after frames?

The registered verifier says GIANT_BEAST_SEARCH_NOT_PROVEN because
``after.beast_search_result`` was empty.  Either the client drew no card (the search found
nothing) or it drew one and the reader missed it.  This runs the production vision on every
observation the failing step took and prints what it reads.

Writes nothing, touches no device.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from winter_agent_v2.ocr import HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend  # noqa: E402
from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

RUNS = ROOT / "dataset/raw/control_panel/runtime_auto"
CASES = [
    ("FAIL 07:21:39 step002", "20261002_152022_241791"),
    ("FAIL 07:11:45 step002", "20261002_151004_848112"),
]
# the ok case, for contrast
OK_RUN = "20261002_145359_378193"

config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
world_vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))
vision = HybridVision(world_vision, ocr)


def report(label: str, run: str, frames):
    print("=" * 96)
    print(label, run)
    for name in frames:
        path = RUNS / run / name
        if not path.exists():
            print("   missing", name)
            continue
        state = vision.observe(path)
        card = dict(state.beast_search_result or {})
        print("   %s" % name)
        print("      search_open=%-5s selected_tab=%-12s kinds=%s level=%s" % (
            state.resource_search_open, state.resource_selected_tab,
            tuple(state.resource_tab_kinds), state.resource_level))
        print("      beast_search_submitted=%-5s card=%s" % (
            state.beast_search_submitted, json.dumps(card, ensure_ascii=False)[:220]))
        print("      page=%-8s beast=%s" % (
            state.page, json.dumps(dict(state.beast or {}), ensure_ascii=False)[:160]))


def frames_of(run: str, prefix: str):
    d = RUNS / run
    out = [p.name for p in sorted(d.glob(f"*{prefix}*")) if p.suffix == ".png"]
    return out


for label, run in CASES:
    names = frames_of(run, "step_002")
    report(label, run, [n for n in names if "session_observe_after" in n or "session_bear" in n])

ok_names = [n for n in frames_of(OK_RUN, "step_002") if "session_observe_after" in n or "session_bear" in n]
report("OK 06:55:20 step002", OK_RUN, ok_names)
