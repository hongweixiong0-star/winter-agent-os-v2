"""Replay the ordinary-control resolver on the frames it failed on -- one variable at a time.

``TRY_ORDINARY_CONTROL`` is the largest single contributor to recent failures (31 of 69 attempts
failed, every one ``SEMANTIC_TARGET_NOT_VERIFIED``, 20 of them on frames whose own reading *does*
carry a collapsed 快捷面板 handle).  A resolver that answers "this frame names no control" on a frame
that visibly draws one is either reading wrong or refusing for a reason it does not report, and the
two are told apart by replaying it:

    A. with the run's state as the first attempt sees it          (nothing used yet)
    B. with ``(HOME, QUICK_PANEL_HANDLE)`` already used this run   (what a second attempt sees)

Everything else is held equal -- same frame, same record-rebuilt world, same goal.  The world is
rebuilt from the episode's own ``state_before`` (production evidence), and the resolver is the
production one (``LiveRuntime._ordinary_control_candidate``), constructed the way the test suite
constructs it, so nothing here re-implements a reader.

Read-only: no device, no writes outside the report.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EPISODES = ROOT / "learning/episodes.jsonl"
HANDLE_ENTRY = "QUICK_PANEL_HANDLE"


def _episodes(skill: str) -> list[dict]:
    rows, skipped = [], 0
    with EPISODES.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if str(row.get("skill")) == skill:
                rows.append(row)
    if skipped:
        print(f"note: {skipped} malformed line(s) skipped (a live runtime appends to this file)")
    rows.sort(key=lambda row: str(row.get("recorded_at")))
    return rows


def _world_from_record(record: dict):
    """The world the runtime stood on, rebuilt from what the episode recorded.

    Only the fields the classification actually wrote are kept, and ``page`` is converted back to the
    enum.  A field the record does not carry keeps its dataclass default -- the same value a frame
    that never read it would have produced.
    """
    from winter_agent_v2.models import Page, WorldState

    known = {f.name for f in fields(WorldState)}
    payload = {key: value for key, value in record.items() if key in known}
    page = payload.get("page")
    if isinstance(page, str):
        try:
            payload["page"] = Page(page)
        except ValueError:
            payload["page"] = Page.UNKNOWN
    if isinstance(payload.get("red_dots"), dict):
        payload["red_dots"] = payload["red_dots"]
    return WorldState(**payload)


def _runtime(goal: str, goal_id: str, ocr):
    from winter_agent_v2.runtime import LiveRuntime

    runtime = object.__new__(LiveRuntime)
    runtime.vision = SimpleNamespace(ocr=ocr)
    runtime.semantic_vision = SimpleNamespace(ocr=None)
    runtime._control_ledger = {}
    runtime._printed_reads = []
    runtime._printed_printed = set()
    runtime._printed_boxes = {}
    runtime.MAX_ORDINARY_ATTEMPTS = 2
    runtime._ordinary_attempts = 0
    runtime._ordinary_tried = set()
    runtime._ordinary_last = None
    runtime._l1_context = None
    runtime._l1_frame_hint = ""
    runtime._ui_candidates = None
    runtime._transitions = None
    runtime.brain = SimpleNamespace(current_goal=goal, goal_id=goal_id, ordinary_scan_exhausted=False)
    runtime.capture_dir = Path("dataset/raw/control_panel/runtime_auto/replay_stub")
    return runtime


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill", default="TRY_ORDINARY_CONTROL")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "dataset/truth_audit/ordinary_control_failures_20260923/resolution.json")
    args = parser.parse_args()

    from winter_agent_v2 import control_experience
    from winter_agent_v2.goal_library import route_for
    from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))

    rows = _episodes(args.skill)
    print(f"episodes of {args.skill}: {len(rows)}")
    print()

    report = {"skill": args.skill, "frames": []}
    tally: Counter[tuple] = Counter()

    for row in rows:
        path = Path(str(row.get("before_screenshot") or ""))
        if not path.exists():
            tally[("MISSING_FRAME", str(row.get("result")))] += 1
            continue
        state = row.get("state_before") or {}
        world = _world_from_record(state)
        page = control_experience.label(world.page)
        recorded_goal = str(row.get("goal_id") or "")
        # Production puts the route in current_goal and the concrete goal in goal_id; an episode
        # records only the committed goal, so the route is derived from it where it can be.
        route = route_for(recorded_goal) or recorded_goal

        first = _runtime(route, recorded_goal, ocr)
        point_first = first._ordinary_control_candidate(world, path)
        second = _runtime(route, recorded_goal, ocr)
        second._ordinary_tried = {(page, HANDLE_ENTRY)}
        second._ordinary_attempts = 1
        point_second = second._ordinary_control_candidate(world, path)

        entry = {
            "recorded_at": str(row.get("recorded_at")),
            "result": str(row.get("result")),
            "goal_recorded": recorded_goal,
            "page_recorded": page,
            "panel_open_at_record": (state.get("quick_panel") or {}).get("open")
            if isinstance(state.get("quick_panel"), dict) else None,
            "handle_on_frame": isinstance((state.get("quick_panel") or {}).get("handle"), dict)
            if isinstance(state.get("quick_panel"), dict) else False,
            "point_as_first_attempt": point_first,
            "semantic_as_first_attempt": (first._ordinary_last or {}).get("semantic"),
            "source_as_first_attempt": (first._ordinary_last or {}).get("source"),
            "point_after_the_handle_was_used": point_second,
            "declined_reason_after_the_handle_was_used": (
                (second._ordinary_declined or {}).get("reason")
            ),
            # What the episode would have said *before* this change, and what it says now.  The
            # executor's own string is what the runtime used to record; the named refusal is what it
            # records when the resolver declined for its own reason.
            "failure_type_recorded_by_the_executor": "SEMANTIC_TARGET_NOT_VERIFIED",
            "failure_type_now": second._failure_type_from(
                SimpleNamespace(executed=False, error="SEMANTIC_TARGET_NOT_VERIFIED")
            ),
            "scan_exhausted_after_second": bool(second.brain.ordinary_scan_exhausted),
            "frame": str(path),
        }
        report["frames"].append(entry)
        tally[(entry["result"], entry["handle_on_frame"],
               point_first is not None, point_second is not None)] += 1

    print("result / handle_on_frame / point_as_first / point_after_used :")
    for key, count in sorted(tally.items(), key=lambda item: -item[1]):
        print(f"  {count:>3}  {key}")
    print()
    named = Counter(
        entry["declined_reason_after_the_handle_was_used"] for entry in report["frames"]
    )
    print(f"the refusal the runtime now names, over the whole corpus: {dict(named)}")
    print(f"the string the executor would have given instead          : "
          f"SEMANTIC_TARGET_NOT_VERIFIED")
    print()
    by_recorded: dict[str, Counter] = defaultdict(Counter)
    for entry in report["frames"]:
        by_recorded[entry["result"]][
            ("point" if entry["point_as_first_attempt"] else "no-point")
            + "|"
            + ("point" if entry["point_after_the_handle_was_used"] else "no-point")
        ] += 1
        print(f"  {entry['recorded_at'][11:19]} {entry['result']:<7} panel={entry['panel_open_at_record']} "
              f"1st={entry['point_as_first_attempt']} 2nd={entry['point_after_the_handle_was_used']} "
              f"src={entry['source_as_first_attempt']} goal={entry['goal_recorded']}")
    print()
    for outcome, counter in sorted(by_recorded.items()):
        print(f"  {outcome}: {dict(counter)}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
