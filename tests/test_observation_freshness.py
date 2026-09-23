"""Observation freshness: a reading taken once must outlive the frame it was taken in.

The operator's §四/§五.  Before this, a reading existed only inside the frame that produced it,
so the next run either re-opened every panel or -- as it actually behaved -- opened none and
reported them all as 未读取.  The store keeps the last reading per domain with its timestamp, and
``discover()`` reuses it while it is fresh.

What these tests defend
-----------------------
* §五 "已获得且未过期的观察结果可以复用": a fresh reading is acted on without re-opening the page.
* §五 "过期结果必须重新观察": a stale one becomes a visit ticket again.
* §五 "不能每一轮都打开所有页面" -- that is the TTL's job, and it is per domain, because a mail
  badge can appear at any moment while a research queue cannot beat its own timer.
* A reading taken now always beats one taken earlier.
* An unreadable store means "nothing is fresh" (one wasted visit), never a crash and never
  "everything is fresh" (a panel that is never looked at again).
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import observation_store as store  # noqa: E402
from winter_agent_v2.goal_library import PANEL_ROUTINES, GoalLibrary, GoalStatus  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402

NOW = datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc)
MAIL = next(r for r in PANEL_ROUTINES if r.goal_id == "MAIL_ROUTINE")

#: The mail entry read PRESENT, which since 2026-09-23 is the condition for ``MAIL_ROUTINE`` to exist
#: at all (§一: 无红点，就没有这个 Goal).  A fixture about *freshness* has to state what the entry said,
#: or it would be asserting the existence of a goal the rule deliberately withholds; the rule itself
#: is tested in ``test_entry_badges.py``.  One place, so the two files that need it cannot drift.
ENTRY_READABLE = {"BTN_OPEN_MAIL": {"state": "PRESENT", "goal": "MAIL_ROUTINE"}}


def goals(world: WorldState, observations=None):
    """``observations`` accepts a bare reading for brevity and wraps it as a fresh record."""
    if not world.red_dots:
        world = replace(world, red_dots=dict(ENTRY_READABLE))
    shaped = None
    if observations is not None:
        shaped = {
            domain: (value if isinstance(value, Mapping) and "reading" in value
                     else {"reading": value, "overdue": False, "overdue_ratio": 0.0})
            for domain, value in observations.items()
        }
    return {g.goal_id: g for g in GoalLibrary().discover(world, observations=shaped)}


def test_a_fresh_reading_is_reused_without_reopening_the_panel():
    """§五: the claim can be made from what was already seen."""
    observations = {"mail": {"status": "CLAIMABLE"}}
    goal = goals(WorldState(page=Page.MAP), observations)["MAIL_ROUTINE"]
    assert goal.status is GoalStatus.READY
    assert goal.evidence["reused"] is True
    assert goal.available_skills == MAIL.work_skills


def test_a_fresh_reading_that_says_done_keeps_the_goal_complete():
    observations = {"mail": {"status": "CLAIMED"}}
    goal = goals(WorldState(page=Page.MAP), observations)["MAIL_ROUTINE"]
    assert goal.status is GoalStatus.COMPLETE
    assert goal.evidence["reused"] is True


def test_a_reading_taken_now_beats_one_taken_earlier():
    """A live reading is the newest thing we know; the stored one must not shadow it."""
    world = WorldState(page=Page.MAP, mail={"status": "CLAIMED"})
    goal = goals(world, {"mail": {"status": "CLAIMABLE"}})["MAIL_ROUTINE"]
    assert goal.status is GoalStatus.COMPLETE
    assert goal.evidence["reused"] is False


def test_nothing_fresh_means_a_visit_ticket():
    goal = goals(WorldState(page=Page.MAP), {})["MAIL_ROUTINE"]
    assert goal.status is GoalStatus.DISCOVERED
    assert goal.available_skills == (MAIL.entry_skill,)


def test_the_ttl_filters_a_stale_reading_out(tmp_path: Path):
    """§五: an expired result must be re-observed, not reused."""
    path = tmp_path / "obs.json"
    store.record("mail", {"status": "CLAIMABLE"}, now=NOW - timedelta(seconds=store.ttl_seconds("mail") + 60), path=path)
    loaded = store.load(path)
    assert store.as_discovery_input(loaded, NOW) == {}, "a stale reading must not be offered"
    # ... and inside its TTL the same record is offered.
    store.record("mail", {"status": "CLAIMABLE"}, now=NOW - timedelta(seconds=10), path=path)
    assert store.as_discovery_input(store.load(path), NOW)["mail"] == {"status": "CLAIMABLE"}


def test_ttls_are_per_domain_because_the_reasons_differ():
    assert store.ttl_seconds("alliance") < store.ttl_seconds("exploration")
    assert store.ttl_seconds("something_new") == store.FALLBACK_TTL_SECONDS


def test_the_store_round_trips_a_reading(tmp_path: Path):
    path = tmp_path / "obs.json"
    store.record("daily", {"status": "CLAIMABLE"}, now=NOW, path=path)
    loaded = store.load(path)
    assert loaded["daily"].reading == {"status": "CLAIMABLE"}
    assert loaded["daily"].next_check_at() > NOW.isoformat()


def test_an_empty_reading_is_recorded_too(tmp_path: Path):
    """"We looked and it said nothing" must stop the next run from looking again."""
    path = tmp_path / "obs.json"
    store.record("mail", {}, now=NOW, path=path)
    loaded = store.load(path)
    assert "mail" in loaded
    assert store.as_discovery_input(loaded, NOW)["mail"] == {}
    # ... and the engine reads that as OBSERVED_UNKNOWN, not as a visit ticket: re-opening a
    # panel that has just reported nothing cannot resolve anything.
    goal = goals(WorldState(page=Page.MAP), {"mail": {}})["MAIL_ROUTINE"]
    assert goal.status is GoalStatus.UNKNOWN
    assert goal.evidence["reused"] is True
    # ... and the engine reads that as OBSERVED_UNKNOWN, not as a visit ticket: re-opening a
    # panel that has just reported nothing cannot resolve anything.
    goal = goals(WorldState(page=Page.MAP), {"mail": {}})["MAIL_ROUTINE"]
    assert goal.status is GoalStatus.UNKNOWN
    assert goal.evidence["reused"] is True


def test_a_broken_store_means_nothing_is_fresh(tmp_path: Path):
    """The safe direction: one wasted visit, never "this panel is fresh for ever"."""
    path = tmp_path / "obs.json"
    path.write_text("{not json", encoding="utf-8")
    assert store.load(path) == {}
    assert store.as_discovery_input(store.load(path), NOW) == {}
    # ... and recording over a corrupt file repairs it rather than raising.
    store.record("mail", {"status": "CLAIMED"}, now=NOW, path=path)
    assert json.loads(path.read_text(encoding="utf-8"))["domains"]["mail"]["reading"] == {"status": "CLAIMED"}


def test_a_due_routine_outranks_routine_work_but_never_a_real_claim():
    """The acceptance invariant, measured against the live priorities.

    Before this, every routine was worth a flat 20 against 2450 for the stamina goal and 70 for
    gathering, so ``best()`` chose them on every run and no panel was ever swept: the state
    existed and nothing selected it.  A due routine must win against ordinary routine work --
    otherwise the sweep simply never happens -- and must lose against anything that actually
    pays, or the sweep would eat the work it exists to find.
    """
    world = WorldState(page=Page.MAP, march_used=2, march_max=3)
    overdue = goals(world, {"mail": {"reading": {}, "overdue": True, "overdue_ratio": 2.0}})
    sweep = overdue["MAIL_ROUTINE"]
    assert sweep.status is GoalStatus.DISCOVERED
    assert sweep.priority > overdue["KEEP_MARCHES_PRODUCTIVE"].priority, (
        "an overdue panel must be looked at instead of another routine round"
    )
    claimable = goals(world, {"daily": {"status": "CLAIMABLE"}})["DAILY_ACTIVITY_TARGET"]
    assert claimable.priority > sweep.priority, (
        "a panel with something to claim must outrank a panel that merely needs looking at"
    )
    assert sweep.priority < 250.0, "the sweep ceiling must stay under a real claim"


def test_never_checked_is_due_immediately():
    """The first sweep has to happen: a never-read panel outranks routine work from the start."""
    world = WorldState(page=Page.MAP, march_used=2, march_max=3)
    gs = goals(world, {})
    assert gs["MAIL_ROUTINE"].status is GoalStatus.DISCOVERED
    assert gs["MAIL_ROUTINE"].priority > gs["KEEP_MARCHES_PRODUCTIVE"].priority


def test_an_overdue_reading_is_not_reused_as_state():
    """§五: an expired result must be re-observed, so it may not decide the goal's state."""
    stale = {"mail": {"reading": {"status": "CLAIMED"}, "overdue": True, "overdue_ratio": 3.0}}
    goal = goals(WorldState(page=Page.MAP), stale)["MAIL_ROUTINE"]
    assert goal.status is GoalStatus.DISCOVERED, "a stale reading must not read as COMPLETE"
    assert goal.evidence["overdue"] is True
    assert goal.evidence["reused"] is False
    assert goal.evidence["reading"] == {"status": "CLAIMED"}, "kept as evidence, not as state"


def test_a_due_routine_outranks_routine_work_but_never_a_real_claim():
    """The acceptance invariant, measured against the live priorities.

    Before this, every routine was worth a flat 20 against 2450 for the stamina goal and 70 for
    gathering, so ``best()`` chose them on every run and no panel was ever swept: the state
    existed and nothing selected it.  A due routine must win against ordinary routine work --
    otherwise the sweep simply never happens -- and must lose against anything that actually
    pays, or the sweep would eat the work it exists to find.
    """
    world = WorldState(page=Page.MAP, march_used=2, march_max=3)
    overdue = goals(world, {"mail": {"reading": {}, "overdue": True, "overdue_ratio": 2.0}})
    sweep = overdue["MAIL_ROUTINE"]
    assert sweep.status is GoalStatus.DISCOVERED
    assert sweep.priority > overdue["KEEP_MARCHES_PRODUCTIVE"].priority, (
        "an overdue panel must be looked at instead of another routine round"
    )
    claimable = goals(world, {"daily": {"status": "CLAIMABLE"}})["DAILY_ACTIVITY_TARGET"]
    assert claimable.priority > sweep.priority, (
        "a panel with something to claim must outrank a panel that merely needs looking at"
    )
    assert sweep.priority < 250.0, "the sweep ceiling must stay under a real claim"


def test_never_checked_is_due_immediately():
    """The first sweep has to happen: a never-read panel outranks routine work from the start."""
    world = WorldState(page=Page.MAP, march_used=2, march_max=3)
    gs = goals(world, {})
    assert gs["MAIL_ROUTINE"].status is GoalStatus.DISCOVERED
    assert gs["MAIL_ROUTINE"].priority > gs["KEEP_MARCHES_PRODUCTIVE"].priority


def test_an_overdue_reading_is_not_reused_as_state():
    """§五: an expired result must be re-observed, so it may not decide the goal's state."""
    stale = {"mail": {"reading": {"status": "CLAIMED"}, "overdue": True, "overdue_ratio": 3.0}}
    goal = goals(WorldState(page=Page.MAP), stale)["MAIL_ROUTINE"]
    assert goal.status is GoalStatus.DISCOVERED, "a stale reading must not read as COMPLETE"
    assert goal.evidence["overdue"] is True
    assert goal.evidence["reused"] is False
    assert goal.evidence["reading"] == {"status": "CLAIMED"}, "kept as evidence, not as state"


def test_a_reading_keeps_the_frame_it_was_taken_from():
    """A reading that cannot be traced to a picture cannot be audited.

    Measured 2026-09-19: the store held ``stamina.current = 0`` for a window in which no frame
    had been saved and no episode had been recorded, because the run that read it observed a
    frame and then stopped without executing a step.  So "stamina is zero" could be neither
    confirmed nor refused from the artifacts -- and ``AVOID_STAMINA_WASTE`` reads that number to
    decide whether anything is left to spend, which makes an unauditable reading here a way for
    the goal to look satisfied while nothing has been spent.
    """
    import json
    from tempfile import TemporaryDirectory

    from winter_agent_v2 import observation_store

    with TemporaryDirectory() as temp:
        path = Path(temp) / "observation_state.json"
        frame = Path(temp) / "step_001_before.png"
        observation_store.record("stamina", {"current": 0, "max": 200}, path=path, frame=frame)

        entry = json.loads(path.read_text(encoding="utf-8"))["domains"]["stamina"]
        assert entry["frame"] == str(frame), "the reading must name its own evidence"
        assert entry["reading"]["current"] == 0

        # A caller with no frame records no pointer rather than inventing one.
        observation_store.record("mail", {"status": "CLAIMED"}, path=path)
        entry = json.loads(path.read_text(encoding="utf-8"))["domains"]["mail"]
        assert "frame" not in entry, "absent means the caller had none, not that one was made up"


def test_a_reading_without_a_frame_gains_no_invented_provenance():
    """``checked_at`` is when the reading was written; ``frame`` is what it was read from.

    If the two were ever derived from each other, a re-stamped stale reading would look as fresh
    as a real one -- which is the failure the pointer exists to make visible.
    """
    import json
    from tempfile import TemporaryDirectory

    from winter_agent_v2 import observation_store

    with TemporaryDirectory() as temp:
        path = Path(temp) / "observation_state.json"
        observation_store.record("intel", {"pins": 5}, path=path)
        entry = json.loads(path.read_text(encoding="utf-8"))["domains"]["intel"]
        assert set(entry) == {"checked_at", "reading"}, f"got {sorted(entry)}"


def test_the_runtime_threads_the_frame_into_every_observation_write():
    """A pointer that is never filled is the same as not having one."""
    import re

    source = (Path(__file__).resolve().parents[1] / "winter_agent_v2/runtime.py").read_text(
        encoding="utf-8")
    calls = re.findall(r"self\._record_goals\((before|after)([^)]*)\)", source)
    assert len(calls) >= 5, f"the call sites moved; this guard needs updating (found {len(calls)})"
    missing = [f"_record_goals({world}{rest})" for world, rest in calls if "frame=" not in rest]
    assert not missing, f"observation writes with no frame pointer: {missing}"
