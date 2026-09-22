"""Who emits OPEN_HOME when no goal asks for it?  Answered on the frame it failed on.

Measured 2026-09-23, from the episode stream: `OPEN_HOME` has 7 emit sites in ``brain.py`` and every
one of them is gated on a named goal (MAIL / EXPLORATION / DAILY / ALLIANCE / RESEARCH / TRAIN /
HOME).  Yet a run whose committed goal was ``AUTO_DISCOVERY`` issued **eight** of them in a row
(21:22:27 - 21:27:57), every one standing on a map whose own reading says ``resource_search_open`` --
the panel that covers the 城镇 door, which is the mechanism #101 measured and the guard commit
c522bc9 was written for.  So either a guard did not fire, or something else emitted the step.

This tool settles which, on one of those frames and without a device: rebuild the world with the
production vision, then ask the production brain for the same frame under each goal the runtime could
have been carrying.  The reason string in the answer names the branch, and the branch that answers
``first_ready_p0_skill`` is the registry fallback -- the one place a skill can be issued without any
goal asking for it.

Read-only.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EPISODES = ROOT / "learning/episodes.jsonl"
#: The first failure of the burst, and its own episode record says page=MAP + search panel open.
DEFAULT_STAMP = "20260922T212227"  # placeholder; the tool finds the frame from the episode stream


def _frames_to_try(limit: int) -> list[dict]:
    """OPEN_HOME failures whose own reading says the search panel is open, NEWEST first.

    Newest, not oldest: the question is what the code emits *now*, and the first matches in the file
    are the oldest ones -- measured, those two frames are from 09-18 and 09-20 and predate both the
    guard and the fallback's current shape.  (Written the other way first and caught by reading the
    dates off the output.)
    """
    out: list[dict] = []
    seen: set[str] = set()
    with EPISODES.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(row.get("skill")) != "OPEN_HOME" or str(row.get("result")) == "SUCCESS":
                continue
            state = row.get("state_before") or {}
            if not state.get("resource_search_open"):
                continue
            frame = str(row.get("before_screenshot") or "")
            if not frame or frame in seen or not Path(frame).exists():
                continue
            seen.add(frame)
            out.append({
                "frame": frame,
                "recorded_at": str(row.get("recorded_at")),
                "goal_recorded": str(row.get("goal_id")),
                "failure_type": str(row.get("failure_type")),
            })
    out.reverse()  # the file is chronological: reverse, then take the newest ``limit``
    return out[:limit]


def _vision():
    from winter_agent_v2.ocr import HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend
    from winter_agent_v2.vision import SemanticWorldVision

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    template = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))
    return HybridVision(template, ocr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=2)
    parser.add_argument("--out", type=Path,
                        default=ROOT / "dataset/truth_audit/open_home_fallback_20260923/report.json")
    args = parser.parse_args()

    from winter_agent_v2.brain import RuleBrain
    from winter_agent_v2.skills import v2_registry

    picks = _frames_to_try(args.frames)
    if not picks:
        print("no OPEN_HOME failure on a frame whose reading has the search panel open -- nothing to do")
        return 0
    vision = _vision()
    registry = v2_registry()
    print(f"registry skills ready on a map with the search panel open:")
    report = {"frames": []}
    for pick in picks:
        frame = Path(pick["frame"])
        world = vision.observe(frame)
        ready = [skill.id for skill in registry.ready(world)]
        print(f"\n{pick['recorded_at']}  {frame.name}")
        print(f"  recorded goal={pick['goal_recorded']} failure={pick['failure_type']}")
        print(f"  re-read page={getattr(world.page, 'value', world.page)} "
              f"search_open={world.resource_search_open} confidence={world.confidence}")
        print(f"  skills the registry calls ready here: {ready}")
        answers = {}
        # The second variable: the runtime marks the search exhausted once a search has been tried,
        # and that is what stops the brain from asking for SELECT_RESOURCE again.  With the search
        # exhausted and no goal-specific branch matching, whatever the registry fallback picks is the
        # step that gets issued -- which is the state the burst's eight identical failures live in.
        variables = [
            ("goal", {}),
            ("goal + search exhausted", {"resource_search_exhausted": True}),
            ("goal + search exhausted + resource_target", {"resource_search_exhausted": True,
                                                          "resource_target": "WOOD"}),
        ]
        for label, patch in variables:
            for goal in ("AUTO_DISCOVERY", "", "HOME", "DAILY_ACTIVITY_TARGET"):
                frame_world = replace(world, **patch) if patch else world
                brain = RuleBrain()
                brain.current_goal = goal
                decision = brain.decide(frame_world, registry)
                key = f"{label} | current_goal={goal or '(none)'}"
                answers[key] = {
                    "skill": decision.skill, "reason": decision.reason,
                    "expected": decision.expected_result,
                }
                print(f"  {label:<42} goal={goal or '(none)':<22} -> {decision.skill:<16} {decision.reason}")
        report["frames"].append({**pick, "ready": ready, "answers_by_goal": answers})

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
