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
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import observation_store as store  # noqa: E402
from winter_agent_v2.goal_library import PANEL_ROUTINES, GoalLibrary, GoalStatus  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402

NOW = datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc)
MAIL = next(r for r in PANEL_ROUTINES if r.goal_id == "MAIL_ROUTINE")


def goals(world: WorldState, observations=None):
    return {g.goal_id: g for g in GoalLibrary().discover(world, observations=observations)}


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
