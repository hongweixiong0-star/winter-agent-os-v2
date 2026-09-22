"""Replay a recorded run's decisions through the production brain, frame by frame.

Read-only: no device, no clicks, no writes outside the report directory.

Why a replay rather than a live run.  A decision-layer question ("who chose this hop, and why")
cannot be answered from ``episodes.jsonl`` alone when the reason is not recorded, and the runtime's
own log only keeps the most recent run.  The frames *are* recorded, the world can be rebuilt from
them by the production vision, and the brain is a deterministic function of (world, registry, its own
run-scoped counters) -- so the decision chain can be reconstructed exactly, provided the frames are
fed in order into **one** brain instance per run, which this tool does.

Two things this tool deliberately does NOT do:

* it does not re-derive ``best_goal`` from the scheduler.  Whether a goal is selectable depends on
  the machine's own ledgers (observation store, capability gate, streaks), and a replay that guessed
  them would be measuring the guess.  ``_step_goal(None)`` is recorded as ``AUTO_DISCOVERY`` in the
  episode stream, so a run whose every step carries that id is a run in which the scheduler offered
  nothing -- which is exactly the state this tool is about.
* it does not claim a reproduction of a step it cannot reproduce.  Each step is reported with the
  recorded skill beside the replayed one, and the summary counts the agreement.

Usage:
    python tools/replay_run_decisions.py                       # the pure-navigation runs, 16:00Z on
    python tools/replay_run_decisions.py --hours 8 --limit 4
    python tools/replay_run_decisions.py --all-runs --limit 6
    python tools/replay_run_decisions.py --run 20260923_062948_568906

Every run is replayed twice, with and without
``LiveRuntime._stop_instead_of_looking_again``, so the summary reads as an A/B over frames rather
than as an opinion about the guard.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.models import Page  # noqa: E402  (needs ROOT on sys.path first)

EPISODES = ROOT / "learning/episodes.jsonl"
DEFAULT_OUT = ROOT / "dataset/truth_audit/nav_pingpong_20260923"

#: Skills that only move the client between pages.  A run made entirely of these observed nothing
#: and changed nothing: it spent the device to look at two screens and come back.
NAVIGATION_SKILLS = frozenset({
    "OPEN_MAP", "OPEN_HOME", "CHECK_MARCH", "SAFE_STOP", "WAIT_FOR_CAMP_MENU", "CLOSE_POPUP", "BACK",
})


def _rows() -> list[dict]:
    out = []
    with EPISODES.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _stamp(row: dict) -> float | None:
    text = row.get("recorded_at")
    if not text or text == "None":
        return None
    try:
        return datetime.fromisoformat(str(text)).timestamp()
    except ValueError:
        return None


def _page(state: dict | None) -> str:
    page = (state or {}).get("page")
    return str(page.get("value") if isinstance(page, dict) else page or "")


def _runs_newest_first(rows: list[dict], *, since: float, churn_only: bool) -> list[tuple[str, list[dict]]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        run_id = str(row.get("episode_id") or "")
        if not run_id.startswith("2026"):  # legacy aggregates and the synthetic 'live_runtime' bucket
            continue
        if (_stamp(row) or 0) < since:
            continue
        grouped[run_id].append(row)
    picked = []
    for run_id, steps in grouped.items():
        steps.sort(key=lambda r: (_stamp(r) or 0))
        if churn_only and not all(str(s.get("skill")) in NAVIGATION_SKILLS for s in steps):
            continue
        picked.append((run_id, steps))
    picked.sort(key=lambda item: _stamp(item[1][-1]) or 0, reverse=True)
    return picked


def _vision():
    """The production reader, exactly as ``run_live`` builds it."""
    from winter_agent_v2.ocr import HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend
    from winter_agent_v2.vision import SemanticWorldVision

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))
    return HybridVision(SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json"), ocr)


def _bare_runtime():
    """The runtime state a decision reads, without a device.

    Built the way ``tests/test_capability_gate.py`` builds it.  ``_deferral_replan`` and
    ``_stop_instead_of_looking_again`` between them read five attributes (``_replan_attempted``,
    ``_barren_pages``, ``registry``, ``brain``, and the world) and nothing else, so a bare instance
    answers exactly what the production instance would -- and one instance per run is what makes the
    run-scoped counters faithful.
    """
    from winter_agent_v2.runtime import LiveRuntime
    from winter_agent_v2.skills import v2_registry

    runtime = object.__new__(LiveRuntime)
    runtime._replan_attempted = False
    runtime._barren_pages = set()
    runtime.registry = v2_registry()
    runtime.brain = SimpleNamespace(current_goal=None)
    return runtime


DEFERRED = [SimpleNamespace(capability="SPEND_STAMINA_ON_BEAST", goal_id="AVOID_STAMINA_WASTE")]


def _chain(steps, worlds, registry, *, guard: bool) -> list[dict]:
    """The decision chain the runtime's own loop would produce on these frames.

    One brain and one bare runtime per run, fed in order, because both carry run-scoped state
    (``ordinary_attempts``, ``_replan_attempted``, ``_barren_pages``) -- replaying them through a
    fresh instance each step would replay the first step every time.
    """
    from winter_agent_v2.brain import RuleBrain

    brain = RuleBrain()
    runtime = _bare_runtime()
    out = []
    for step, world in zip(steps, worlds):
        row = {
            "at": str(step.get("recorded_at"))[11:19],
            "step_id": step.get("step_id"),
            "recorded_skill": str(step.get("skill")),
            "recorded_result": str(step.get("result")),
            "recorded_goal": str(step.get("goal_id")),
            "page_before": _page(step.get("state_before")),
            "page_after": _page(step.get("state_after")),
            "frame_present": world is not None,
        }
        if world is None:
            out.append(row)
            continue
        # The run's every step is labelled AUTO_DISCOVERY, i.e. ``_step_goal(None)``: the scheduler
        # offered nothing, so no route was ever committed and ``best_goal`` is None throughout.
        best_goal = None
        brain.current_goal = None
        leave = None
        if world.page in (Page.TRAINING, Page.RESEARCH):
            leave = brain.leave_terminal_page(world)
        if leave is None:
            leave = runtime._deferral_replan(world, DEFERRED, best_goal)
        decision = leave if leave is not None else brain.decide(world, registry)
        row.update({
            "page_now": world.page.value,
            "known": bool(world.known),
            "resource_search_open": bool(world.resource_search_open),
            "brain_skill": decision.skill,
            "brain_reason": decision.reason,
            "who_decided": "brain.decide" if leave is None else "runtime",
        })
        if guard:
            guarded = runtime._stop_instead_of_looking_again(world, decision, best_goal)
            row["guard_fired"] = guarded.skill != decision.skill
            if row["guard_fired"]:
                row["guard_reason"] = guarded.reason
            decision = guarded
        row["emitted_skill"] = decision.skill
        row["emitted_reason"] = decision.reason
        out.append(row)
        if guard and row.get("guard_fired"):
            # The run ends here, so there is nothing to decide on the frames after it.
            break
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=None, help="how far back to read (default: since 16:00Z)")
    parser.add_argument("--run", action="append", default=[], help="only these run ids (repeatable)")
    parser.add_argument("--limit", type=int, default=12, help="how many runs to replay")
    parser.add_argument("--all-runs", action="store_true",
                        help="replay every run in the window, not only the pure-navigation ones")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    from winter_agent_v2.skills import v2_registry

    if args.hours is None:
        since = datetime(2026, 9, 22, 16, 0, tzinfo=timezone.utc).timestamp()
    else:
        since = (datetime.now(timezone.utc) - timedelta(hours=args.hours)).timestamp()

    rows = _rows()
    if args.run:
        wanted = set(args.run)
        picked = [(rid, steps) for rid, steps in _runs_newest_first(rows, since=0, churn_only=False)
                  if rid in wanted]
    else:
        picked = _runs_newest_first(rows, since=since, churn_only=not args.all_runs)[: args.limit]
    if not picked:
        print("no run matched -- nothing to replay")
        return 0

    vision = _vision()
    registry = v2_registry()
    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "since": datetime.fromtimestamp(since, tz=timezone.utc).isoformat(),
        "navigation_skills": sorted(NAVIGATION_SKILLS),
        "runs": [],
    }
    agree = disagree = 0
    steps_before = steps_after = 0
    runs_stopped_earlier = 0

    for run_id, steps in picked:
        worlds = []
        missing = 0
        for step in steps:
            frame = Path(str(step.get("before_screenshot") or ""))
            world = vision.observe(frame) if frame.exists() else None
            if world is None:
                missing += 1
            worlds.append(world)

        before = _chain(steps, worlds, registry, guard=False)
        after = _chain(steps, worlds, registry, guard=True)
        entry = {"run_id": run_id, "missing_frames": missing, "before": before, "after": after}
        report["runs"].append(entry)

        for row in before:
            if not row["frame_present"]:
                continue
            if row["emitted_skill"] == row["recorded_skill"]:
                agree += 1
            else:
                disagree += 1
        steps_before += len(before)
        steps_after += len(after)
        if len(after) < len(before):
            runs_stopped_earlier += 1

        print(f"=== run {run_id}  ({len(steps)} recorded steps)")
        for row in before:
            if not row["frame_present"]:
                print(f"  {row['at']} #{row['step_id']}  FRAME MISSING  recorded={row['recorded_skill']}")
                continue
            mark = "==" if row["emitted_skill"] == row["recorded_skill"] else "!="
            print(f"  {row['at']} #{str(row['step_id']).ljust(3)} {row['page_before']}->{row['page_after']:<9}"
                  f" recorded={row['recorded_skill']:<20} {mark} replayed={row['emitted_skill']:<20}"
                  f" by {row['who_decided']}")
            print(f"        reason={row['emitted_reason']}")
        if len(after) < len(before):
            print(f"  -> with the guard the run ends at step {len(after)} instead of {len(before)}:")
            for row in after:
                print(f"     {row['at']} #{row['step_id']} {row['emitted_skill']:<20} {row['emitted_reason']}")
                if row.get("guard_fired"):
                    print(f"        (the refused decision was {row['brain_skill']} / {row['brain_reason']})")
        print()

    report["summary"] = {
        "runs_replayed": len(report["runs"]),
        "steps_replayed": agree + disagree,
        "steps_agreeing_with_the_stream": agree,
        "steps_disagreeing": disagree,
        "steps_before_the_guard": steps_before,
        "steps_with_the_guard": steps_after,
        "runs_that_end_earlier": runs_stopped_earlier,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("summary:", json.dumps(report["summary"], ensure_ascii=False))
    print("wrote", args.out / "replay.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
