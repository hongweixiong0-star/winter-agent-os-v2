"""What does the production observation actually say about the gather-formation page?

The verifier refused DISPATCH_MARCH with STALE_OR_ROLE_UNSCOPED_FORMATION, and seven of its eight
sub-conditions hold on the failing frame -- the only one that fails is
``formation.resource_type ("WOOD") == before.resource_target ("MEAT")``.  Nothing else in the
episode ever read WOOD: ``resource_target`` is MEAT from step 7 to step 20.  So the question is
where that WOOD came from, and the only way to answer it is to ask the production reader.

This runs the real observation on the archived frames and prints what it says, plus what the
formation annotator would freeze from it.

    .venv/Scripts/python.exe _wb1002_16_reader.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

EPISODE = "20261002_172120_360764"
RUN = ROOT / "dataset/raw/control_panel/runtime_auto" / EPISODE
STEPS = {
    "14 CLEAR_GATHER_HEROES": "step_014_before_20261002T092400233843.png",
    "15 CLEAR_GATHER_HEROES": "step_015_before_20261002T092403120112.png",
    "16 DISPATCH_MARCH (refused)": "step_016_before_20261002T092406618948.png",
    "20 CLEAR_GATHER_HEROES": "step_020_before_20261002T092508199992.png",
}


def episode_rows():
    path = ROOT / "learning" / "episodes.jsonl"
    rows = []
    with path.open("rb") as stream:
        for line in stream:
            line = line.strip()
            if line.startswith(b"{"):
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("episode_id") == EPISODE:
                    rows.append(row)
    return sorted(rows, key=lambda r: r.get("step_id") or 0)


def main() -> int:
    from winter_agent_v2.ocr import (HybridVision, OCRService, RapidOCRBackend,
                                     ResilientOCRBackend)
    from winter_agent_v2.vision import SemanticWorldVision

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    vision = HybridVision(
        SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json"),
        OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"])))),
    )

    rows = {r.get("step_id"): r for r in episode_rows()}
    print(f"episode {EPISODE}")
    print()
    for label, name in STEPS.items():
        frame = RUN / f"{EPISODE}_{name}"
        step_id = int(label.split()[0])
        row = rows.get(step_id) or {}
        sb = row.get("state_before") or {}
        frozen = ((sb.get("hero_troop") or {}).get("gather_formation") or {})
        print(f"== {label}")
        print(f"   frame exists            : {frame.is_file()}")
        if frame.is_file():
            observed = vision.observe(frame)
            print(f"   observed.page           : {observed.page.value}")
            print(f"   observed.resource_target: {observed.resource_target!r}")
            print(f"   observed.resource_avail : {observed.resource_available!r}")
        else:
            print("   (frame missing; the ledger path differs)")
        print(f"   ledger before.target    : {sb.get('resource_target')!r}")
        print(f"   frozen formation.restype: {frozen.get('resource_type')!r}")
        print(f"   the verifier compares   : {frozen.get('resource_type')!r} == {sb.get('resource_target')!r}"
              f"  -> {str(frozen.get('resource_type') or '').upper() == str(sb.get('resource_target') or '').upper()}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
