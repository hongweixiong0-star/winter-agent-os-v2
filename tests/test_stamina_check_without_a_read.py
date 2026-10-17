"""A genuine 0-stamina frame must not lose the free gift.

Measured live 2026-09-15T04:03:02Z (``dataset/raw/live_free_gift_claim_20260915b/
..._step_002_before_...png``): the previous run's Hero Journey fight had spent
the last 10 stamina, so the map gauge genuinely read **0** -- and the production
ROI read returned *zero tokens*, leaving ``stamina={}``.  Two gates then read
that empty dict as "do not touch the gauge":

* RuleBrain's map branch required ``stamina.current is not None`` before opening
  the free-stamina panel, so the run skipped the check and opened an intel pin
  instead -- on the very frame where the free +150 gift mattered most; and
* LiveRuntime refused to resolve the ``HUD_STAMINA_GAUGE`` tap target, so the
  decision could not have been executed even if the brain had made it.

The number is not what either gate needs.  ``tools/probe_stamina_zero.py`` shows
the OCR cannot read a lone 0 at any padding or scale (best confidence 0.73, and
it flips between '0' and 'O'), and ``tools/probe_map_gauge_unreadable.py`` shows
the pill *is* drawn on those frames (2 of 6 MAP frames unreadable, both a clean
HUD showing 0).  Whether the gift is claimable is decided by the panel's own
template, not by the gauge, so "should we look" does not depend on the number.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from winter_agent_v2 import event_schedule
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.runtime import LiveRuntime


class FakeMatch:
    center_norm = (0.84, 0.50)


class FakeSemantic:
    def find(self, _path, _semantic):
        return FakeMatch()

    semantic = property(lambda self: self)
    resource_tab_band = (0.0, 1.0)
    resource_level_minus = (0.5, 0.5)
    resource_tab_offset = None
    stamina_gauge_center = (49.0 / 720.0, 110.0 / 1280.0)

    def resource_cell_center_norm(self, _resource):
        return (0.5, 0.5)

    def resource_tab_swipe_for(self, _resource):
        return 0.0


class FakeVision:
    def __init__(self, states):
        self.states = iter(states)

    def observe(self, _path):
        return next(self.states)


class FakeDevice:
    def __init__(self):
        self.taps = []
        self.backs = []

    def screenshot(self, path):
        path.touch()
        return path

    def status(self):
        return type("Status", (), {"connected": True, "resolution": (720, 1280)})()

    def tap(self, x, y):
        self.taps.append((x, y))

    def press_back(self):
        self.backs.append(len(self.taps))

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        self.taps.append(("swipe", x1, y1, x2, y2))


def world_map(stamina=None, search_open=False):
    return WorldState(
        page=Page.MAP,
        march_used=1,
        march_max=6,
        stamina=dict(stamina or {}),
        resource_search_open=search_open,
        confidence=0.99,
    )


def stamina_panel(free=False, current=0):
    return WorldState(
        page=Page.POPUP,
        popup="GET_MORE_STAMINA",
        stamina={"current": current, "max": 200, "source": "STAMINA_PANEL", "free_claim_available": free},
        confidence=0.99,
    )


class TheEmptyGaugeDoesNotSkipTheCheckTests(unittest.TestCase):
    """The brain half."""

    def _decide(self, world, **kwargs):
        kwargs.setdefault("claim_free_stamina", True)
        brain = RuleBrain(current_goal="INTEL", **kwargs)
        return brain, brain.decide(world, None)

    def test_an_unreadable_gauge_still_opens_the_free_stamina_panel(self):
        # This is the 04:03:02Z frame: MAP, gauge present, number unreadable.
        for stamina in (None, {}, {"source": "MAP_HUD"}):
            with self.subTest(stamina=stamina):
                _brain, decision = self._decide(world_map(stamina))
                self.assertEqual(decision.skill, "OPEN_STAMINA_SOURCES")
                self.assertEqual(decision.reason, "free_stamina_gift_not_yet_checked_this_run")

    def test_a_zero_reading_also_opens_it(self):
        # If the read ever does return 0 it must behave the same way: 0 is a
        # value, not a missing read.
        _brain, decision = self._decide(world_map({"current": 0, "source": "MAP_HUD"}))
        self.assertEqual(decision.skill, "OPEN_STAMINA_SOURCES")

    def test_the_check_is_still_once_per_run(self):
        brain, first = self._decide(world_map({}))
        self.assertEqual(first.skill, "OPEN_STAMINA_SOURCES")
        second = brain.decide(world_map({}), None)
        self.assertNotEqual(second.skill, "OPEN_STAMINA_SOURCES")

    def test_the_operator_directive_still_gates_it(self):
        _brain, decision = self._decide(world_map({}), claim_free_stamina=False)
        self.assertNotEqual(decision.skill, "OPEN_STAMINA_SOURCES")

    def test_an_open_resource_search_panel_still_blocks_it(self):
        # The gauge is behind the search panel there, so the tap would miss.
        _brain, decision = self._decide(world_map({}, search_open=True))
        self.assertNotEqual(decision.skill, "OPEN_STAMINA_SOURCES")


class TheGaugeIsTappableWithoutANumberTests(unittest.TestCase):
    """The runtime half: the decision must also be executable.

    The runtime ranks a goal board before the brain decides (``run()`` ->
    ``goal_library.rank`` -> ``_sync_brain_goal``), so what the brain is asked here is
    whatever the board put first.  On a MAP frame with no *calendar* entry drawn, that board
    can offer one thing this test does not mean to exercise: ``DISCOVER_EVENT_CALENDAR``
    priced at 300+450+250, reachable through ``OPEN_HOME`` -- but only while
    ``event_schedule.calendar_scan_due()`` answers True.  That predicate is a **clock over
    stored observations**, so on a machine whose ``learning/timed_event_schedule.json`` has
    no read for this scope it answers True and the maintenance hop outranks the gauge
    (measured 2026-10-17 after a clean checkout: ``[utility] chose DISCOVER_EVENT_CALENDAR
    (1000; catalogue price only)`` and the first step came back ``OPEN_HOME``).

    That is the scheduler behaving correctly on a state this test never stated, so the state
    is stated here instead of inherited: the run starts from "today's calendar read is
    already done", which is what the claim "the gauge is the next thing to do" presupposes.
    The board then has no calendar hop to offer and the step under test is the one measured.
    """

    def _finished_calendar_read(self, path: Path) -> None:
        """One grid row, drawn and opened, observed a minute ago -- so the read is not due.

        All four halves of ``calendar_scan_due`` have to answer False for that, and this row
        is the smallest honest shape that does: ``observed_at`` inside the 24 h interval, a
        ``tap_norm`` that is already ``details_observed`` (so nothing is pending), and no
        ``ACTIVITY_STRIP`` record at all (a missing strip is explicitly *not* staleness --
        see ``strip_read_stale_against_grid``), which leaves nothing advertised-but-unread.
        """
        event_schedule.record_calendar_snapshot(
            role_id="",
            path=path,
            observed_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            observation={
                "recognized": True,
                "kind": "CALENDAR_GRID",
                "source": "LIVE_CLIENT_OCR",
                "entries": [{
                    "event_id": "ICEBOUND_TREASURE",
                    "display_name": "ICEBOUND_TREASURE",
                    "tap_norm": [0.5, 0.4],
                    "details_observed": True,
                    "occurrence_key": "ICEBOUND_TREASURE|10/02|10/06",
                }],
            },
        )

    def _run(self, states, **kwargs):
        device = FakeDevice()
        with TemporaryDirectory() as temp:
            schedule_path = Path(temp) / "timed_event_schedule.json"
            self._finished_calendar_read(schedule_path)
            with mock.patch.object(event_schedule, "STATE_PATH", schedule_path):
                run = LiveRuntime(
                    device=device,
                    vision=FakeVision(list(states)),
                    semantic_vision=FakeSemantic(),
                    capture_dir=Path(temp),
                    brain=RuleBrain(current_goal="INTEL", claim_free_stamina=True),
                    sleeper=lambda _seconds: None,
                    observation_retries=0,
                    **kwargs,
                ).run(max_actions=1, allowed_skills={"OPEN_STAMINA_SOURCES"})
        return run, device

    def test_the_gauge_is_tapped_when_the_number_was_not_read(self):
        run, device = self._run([world_map({}), stamina_panel(free=False)])
        self.assertEqual(run.steps[0].decision.skill, "OPEN_STAMINA_SOURCES")
        self.assertTrue(run.steps[0].execution.executed)
        self.assertEqual(device.taps, [(49, 110)])

    def test_the_gauge_is_still_refused_off_the_map(self):
        # HOME is not the map: the pill is not at the measured spot, so the
        # decision must not be executed.  The brain picks OPEN_MAP instead and
        # that skill is not in the allow-list, so nothing is tapped at all.
        run, device = self._run([WorldState(page=Page.HOME, confidence=0.99), WorldState(page=Page.HOME, confidence=0.99)])
        self.assertEqual(device.taps, [])
        self.assertNotEqual(run.steps[0].decision.skill, "OPEN_STAMINA_SOURCES")

    def test_the_gauge_is_still_refused_while_the_search_panel_is_open(self):
        run, device = self._run(
            [world_map({}, search_open=True), world_map({}, search_open=True)]
        )
        self.assertEqual(device.taps, [])
        self.assertNotEqual(run.steps[0].decision.skill, "OPEN_STAMINA_SOURCES")


if __name__ == "__main__":
    unittest.main()
