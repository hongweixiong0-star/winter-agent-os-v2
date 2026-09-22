"""Replay the red-dot priority term over real frames: one variable, both directions.

Operator directive 2026-09-23 §二② makes the client's dot a priority signal.  A priority signal is
only real if it can change an order, so this tool measures the change in the one way the project
accepts as evidence of cause: **the same frame, the same code, one variable switched** -- the dot
ledger is emptied on the "before" side and left alone on the "after" side.  Nothing else differs:
same goals, same observations, same fairness ledger (none), same route facts (none).

Frames come from production episodes whose own record says ``page=HOME``, preferring the ones whose
ledger actually carries a PRESENT dot on an entry that is *entitled* to rank
(``entry_badges.dot_varies``).  The world is rebuilt from the picture with the production vision
(``SemanticWorldVision`` + RapidOCR), so the reading is derived from the frame rather than trusted
from the record -- the record is used only to choose which frames to look at.

Output: a JSON report plus a README in ``--out``, and a summary on stdout.  No device, no writes
outside the output directory.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EPISODES = ROOT / "learning/episodes.jsonl"


def _home_frames_with_a_present_dot(limit: int) -> list[dict]:
    """Production HOME frames whose recorded ledger shows a dot, newest first, deduplicated."""
    return _home_frames(limit, want_lit=True)


def _home_frames_without_a_present_dot(limit: int) -> list[dict]:
    """Production HOME frames that carry a ledger but no rankable dot -- the negative control.

    Without these, "the order changed" on a dotted frame is not evidence that the dot is what
    changed it: the term could be firing on something else.  On these frames the two sides of the
    A/B must agree exactly, and the tool says so out loud.
    """
    return _home_frames(limit, want_lit=False)


def _home_frames(limit: int, *, want_lit: bool) -> list[dict]:
    """Existing HOME before-frames whose own record carries a red-dot ledger, newest first."""
    from winter_agent_v2.entry_badges import PRESENT, dot_varies

    wanted: dict[str, dict] = {}
    with EPISODES.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            state = row.get("state_before")
            if not isinstance(state, dict):
                continue
            page = state.get("page")
            page = str(page.get("value") if isinstance(page, dict) else page or "")
            if page != "HOME":
                continue
            dots = state.get("red_dots")
            if not isinstance(dots, dict) or not dots:
                continue
            lit = [name for name, record in dots.items()
                   if isinstance(record, dict)
                   and str(record.get("state") or "") == PRESENT
                   and dot_varies(str(name))]
            if bool(lit) is not want_lit:
                continue
            frame = str(row.get("before_screenshot") or "")
            if not frame or frame in wanted or not Path(frame).exists():
                continue
            wanted[frame] = {
                "frame": frame,
                "recorded_at": str(row.get("recorded_at") or ""),
                "recorded_lit_entries": sorted(lit),
                "recorded_skill": str(row.get("skill") or ""),
                "recorded_goal": str(row.get("goal_id") or ""),
            }
            if len(wanted) >= limit:
                break
    return list(wanted.values())


def _vision():
    from winter_agent_v2.ocr import HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend
    from winter_agent_v2.vision import SemanticWorldVision

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    template = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))
    return HybridVision(template, ocr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=6, help="dotted production frames to replay")
    parser.add_argument("--negatives", type=int, default=3,
                        help="undotted production frames to replay as a negative control")
    parser.add_argument("--out", type=Path, default=ROOT / "dataset/truth_audit/red_dot_priority_20260923")
    args = parser.parse_args()

    from winter_agent_v2.entry_badges import dots_pointing_at
    from winter_agent_v2.goal_library import GoalLibrary

    picks = [dict(pick, selected_by="record_showed_a_dot")
             for pick in _home_frames_with_a_present_dot(args.frames)]
    picks += [dict(pick, selected_by="record_showed_no_dot")
              for pick in _home_frames_without_a_present_dot(args.negatives)]
    if not picks:
        print("no production HOME frame carries a red-dot ledger -- nothing to replay")
        return 0

    vision = _vision()
    library = GoalLibrary()
    report = {
        "read_me": (
            "受控 A/B：同一帧、同一代码，只切红点这一个变量（before=把这个世界的 red_dots 清空，"
            "after=保留）。before 侧就是改动前的行为，因为那时没有任何一层读 red_dots 来排序。"
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "frames": [],
    }

    changed = 0
    for pick in picks:
        frame = Path(pick["frame"])
        world = vision.observe(frame)
        lit = dots_pointing_at(world.red_dots)
        goals = library.discover(world)
        after_board = library.rank(goals, world)
        before_board = library.rank(goals, replace(world, red_dots={}))
        before_ids = [str(goal.goal_id) for goal, _ in before_board]
        after_ids = [str(goal.goal_id) for goal, _ in after_board]
        flipped = before_ids != after_ids
        changed += 1 if flipped else 0
        terms = {
            str(goal.goal_id): breakdown.as_row()
            for goal, breakdown in after_board
            if breakdown.red_dot
        }
        entry = {
            **pick,
            # The group the picture puts this frame in, not the group its record did.  The two
            # disagree on the frames written before the panel row's badge window was moved out of
            # the button's left third (issue #98): the record of those frames says ABSENT for a row
            # whose own dot is plainly drawn to the right.  The picture decides, because the
            # picture is what the term is computed from.
            "control": "dotted" if lit else "undotted",
            "page": str(getattr(world.page, "value", world.page)),
            "read_lit_goals": {goal: list(entries) for goal, entries in lit.items()},
            "board_before": before_ids,
            "board_after": after_ids,
            "order_changed": flipped,
            "red_dot_terms": terms,
            "runner_up_gap_before": (
                round(before_board[0][1].total - before_board[1][1].total, 1)
                if len(before_board) > 1 else None
            ),
            "runner_up_gap_after": (
                round(after_board[0][1].total - after_board[1][1].total, 1)
                if len(after_board) > 1 else None
            ),
        }
        report["frames"].append(entry)
        print(f"[{entry['control']} / {entry['selected_by']}] {frame.name}")
        print(f"   read dots -> {json.dumps(lit, ensure_ascii=False)}")
        print(f"   board before: {before_ids[:5]}")
        print(f"   board after : {after_ids[:5]}")
        print(f"   order changed: {flipped}")
        for goal_id, row in terms.items():
            print(f"   term {goal_id}: +{row['red_dot']} on {row['red_dot_on']} "
                  f"(base {row['base']} -> total {row['total']})")

    dotted = [f for f in report["frames"] if f["control"] == "dotted"]
    undotted = [f for f in report["frames"] if f["control"] == "undotted"]
    report["summary"] = {
        "frames": len(report["frames"]),
        "frames_with_a_rankable_dot": len(dotted),
        "dotted_frames_where_the_order_changed": sum(1 for f in dotted if f["order_changed"]),
        # The negative control is the frames the *picture* shows no rankable dot on.  On those the
        # two sides of the A/B have nothing to differ about, so a change there would mean the term
        # is firing on something other than the dot -- which is the only way this replay can be
        # wrong in its own favour.
        "negative_control_frames": len(undotted),
        "negative_control_frames_where_the_order_changed": sum(
            1 for f in undotted if f["order_changed"]),
        "records_that_understated_the_dot": sum(
            1 for f in report["frames"]
            if f["selected_by"] == "record_showed_no_dot" and f["control"] == "dotted"),
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "replay.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print()
    print(f"summary: {json.dumps(report['summary'], ensure_ascii=False)}")
    print(f"wrote {args.out / 'replay.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
