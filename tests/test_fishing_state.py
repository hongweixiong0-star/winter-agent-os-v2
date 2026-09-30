"""FISHING POLICY V2 §1/§2/§13/§14 — the bait budget, the run ledger and the forecast.

The directive's acceptance list is a list of *zeros*::

    NORMAL_BAIT_SPECIAL_USED = 0
    GEMS_SPENT = 0
    REAL_MONEY_SPENT = 0
    NORMAL_BAIT_WASTED_BY_CAP = 0
    NORMAL_BAIT_LEFT_AT_EVENT_END ≈ 0

and a list of things that must *grow*: ``TOTAL_EVENT_POINTS`` and
``POINTS_PER_NORMAL_BAIT``.  A zero that is only ever asserted in prose cannot be
distinguished from a zero nobody measured, so the counters these tests pin are the ones that
are computed from observations.

Three properties carry most of the weight, and each has its own failure mode:

* **``None`` is not ``0``.**  "the score was not readable" and "the bait was spent and the
  score did not move" are different findings (§13 exists to catch the second).  Collapsing
  them would turn an unmeasured run into a silent success.
* **The waste counter is exact, not estimated.**  A regeneration instant counts as wasted only
  when the counter demonstrably sat at cap across it -- which is only knowable when the
  previous observation saw cap *and* no run was recorded in between.
* **A deadline is never guessed.**  §15's endgame needs an event end and a real run duration;
  missing either reports ``known=False`` rather than inventing a margin, because a guessed
  deadline spends real bait.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.fishing_state import (  # noqa: E402
    BaitPressure,
    FishingRun,
    FishingState,
    KPI_BAIT_REMAINING,
    KPI_BAIT_USED,
    KPI_BAIT_WASTED,
    KPI_BEST_DEPTH,
    KPI_BEST_POINTS_PER_BAIT,
    KPI_POINTS_PER_BAIT_AVG,
    KPI_POINTS_PER_BAIT_P50,
    KPI_TOTAL_POINTS,
    RoleFishingState,
    verify_run,
)

NOW = datetime(2026, 9, 30, 10, 0, tzinfo=timezone.utc)
HOUR = 3600.0

#: The real first live run, verbatim from ``learning/fishing_runs.jsonl`` (2026-09-29).  It was
#: written before this schema existed, so reading it back is the compatibility test.
LEGACY_ROW = {
    "id": "FISHING_RUN_20260929T231017",
    "role": "ROLE_A (session role)",
    "bait": {"before": 6, "after": 5, "decreased": True},
    "points": {"before": 0, "after": 190},
    "depth_m": 54,
    "control": {"duration_s": 25.047, "loop_hz_median": 21.28},
    "verifier": {"MINIGAME_STARTED": True, "CONTROL_SESSION_RAN": True, "RESULT_PAGE": True},
    "level": "FISHING RUN L4",
}


def _run(**overrides) -> FishingRun:
    base = dict(
        run_id="R1", role_key="ROLE_A", at=NOW, bait_cost=1,
        points_before=0, points_after=100, depth_m=50, fish_caught=4,
        collision_count=1, duration_s=40.0, control_hz=20.0,
    )
    base.update(overrides)
    return FishingRun(**base)


# ------------------------------------------------------------------ the real row


class TestTheRowThatAlreadyExists:
    def test_the_first_live_run_reads_back_with_its_cost_and_efficiency(self) -> None:
        run = FishingRun.from_mapping(LEGACY_ROW)
        assert run.role_key == "ROLE_A", "free text role must resolve to the real key"
        assert run.bait_cost == 1, "cost is derived from before/after, not assumed"
        assert run.points_gain == 190
        assert run.points_per_bait == 190.0
        assert run.depth_m == 54
        assert run.duration_s == pytest.approx(25.047)

    def test_a_treasure_lane_row_is_flagged_as_a_policy_breach(self) -> None:
        run = FishingRun.from_mapping({**LEGACY_ROW, "level": "TREASURE_RUN L1"})
        assert run.lane == "TREASURE"
        assert run.special_resource_used == ["TREASURE"]

    def test_a_normal_row_reports_no_special_resource(self) -> None:
        assert FishingRun.from_mapping(LEGACY_ROW).special_resource_used == []


# ----------------------------------------------------------- none is not zero


class TestAnUnmeasuredRunIsNotAnEmptyOne:
    def test_missing_readings_give_no_efficiency_rather_than_zero(self) -> None:
        run = _run(points_after=None)
        assert run.points_gain is None
        assert run.points_per_bait is None
        assert run.zero_score_run is False

    def test_a_spend_with_no_score_is_a_zero_score_run(self) -> None:
        run = _run(points_before=190, points_after=190)
        assert run.points_gain == 0
        assert run.points_per_bait == 0.0
        assert run.zero_score_run is True

    def test_a_score_cannot_be_negative_but_losing_points_is_still_a_zero_score_run(self) -> None:
        assert _run(points_before=200, points_after=150).zero_score_run is True

    def test_a_run_that_cost_nothing_is_not_a_zero_score_run(self) -> None:
        """No bait left the budget, so nothing was lost -- it is a free look, not a failure."""
        assert _run(bait_cost=0, points_before=0, points_after=0).zero_score_run is False


# ------------------------------------------------------------------ §13 verifier


class TestTheFiveSignalsOfAFinishedLevel:
    def _verdict(self, **overrides):
        base = dict(bait_before=5, bait_after=4, points_before=190, points_after=380,
                    started=True, control_ran=True, result_page=True)
        base.update(overrides)
        return verify_run(**base)

    def test_all_five_present_completes_and_reports_efficiency(self) -> None:
        verdict = self._verdict()
        assert verdict["status"] == "COMPLETE"
        assert verdict["missing"] == []
        assert verdict["points_per_bait"] == 190.0
        assert verdict["failure_analysis_required"] is False

    @pytest.mark.parametrize("field, signal", [
        ("started", "MINIGAME_STARTED"),
        ("control_ran", "CONTROL_SESSION_RAN"),
        ("result_page", "RESULT_PAGE"),
    ])
    def test_a_missing_signal_is_incomplete_and_named(self, field: str, signal: str) -> None:
        verdict = self._verdict(**{field: False})
        assert verdict["status"] == "INCOMPLETE"
        assert verdict["missing"] == [signal]

    def test_a_level_that_ran_but_earned_nothing_requires_failure_analysis(self) -> None:
        """§13: bait down, points not up -> ZERO_SCORE_RUN -> Failure Analysis."""
        verdict = self._verdict(points_after=190)
        assert verdict["status"] == "ZERO_SCORE_RUN"
        assert verdict["failure_analysis_required"] is True
        assert verdict["points_per_bait"] == 0.0

    def test_bait_that_did_not_decrease_is_incomplete_not_a_success(self) -> None:
        verdict = self._verdict(bait_after=5)
        assert verdict["status"] == "INCOMPLETE"
        assert "NORMAL_BAIT_DECREASED" in verdict["missing"]

    def test_unreadable_points_are_incomplete_rather_than_a_zero_score_run(self) -> None:
        """The distinction §13's own wording turns on: no reading is not a bad result."""
        verdict = self._verdict(points_before=None, points_after=None)
        assert verdict["status"] == "INCOMPLETE"
        assert "POINTS_READ" in verdict["missing"]
        assert verdict["failure_analysis_required"] is False


# ------------------------------------------------------- §2 the bait budget


class TestTheBaitCounter:
    def state(self, **overrides) -> RoleFishingState:
        base = dict(
            role_key="ROLE_A", normal_bait_current=4, bait_cap=10,
            regen_seconds=3 * HOUR, event_end_at=NOW + timedelta(hours=30),
        )
        base.update(overrides)
        return RoleFishingState(**base)

    def test_below_cap_is_normal_pressure(self) -> None:
        assert self.state().pressure(NOW) is BaitPressure.NORMAL

    def test_at_cap_is_cap_full_so_the_next_tick_is_wasted(self) -> None:
        """§2: bait == cap must be handled at high priority or recovery is lost."""
        assert self.state(normal_bait_current=10).pressure(NOW) is BaitPressure.CAP_FULL

    def test_zero_bait_is_not_unknown(self) -> None:
        assert self.state(normal_bait_current=0).pressure(NOW) is BaitPressure.NO_BAIT

    def test_an_unread_role_is_unknown_never_zero_and_never_another_roles_number(self) -> None:
        assert self.state(normal_bait_current=None, bait_cap=None).pressure(NOW) is BaitPressure.UNKNOWN

    def test_remaining_regeneration_opportunities_counts_the_ticks_before_the_event_ends(self) -> None:
        role = self.state(normal_bait_current=1, event_end_at=NOW + timedelta(hours=10))
        assert role.remaining_regeneration_opportunities(NOW) == 3

    def test_regeneration_cannot_exceed_the_cap(self) -> None:
        role = self.state(normal_bait_current=9, event_end_at=NOW + timedelta(hours=30))
        assert role.bait_gainable_by_end(NOW) == 1

    def test_what_can_still_be_spent_is_current_plus_what_will_arrive(self) -> None:
        role = self.state(normal_bait_current=4, event_end_at=NOW + timedelta(hours=9))
        assert role.bait_available_until_end(NOW) == 7

    def test_with_no_event_end_the_projection_is_unknown_rather_than_infinite(self) -> None:
        role = self.state(event_end_at=None)
        assert role.bait_available_until_end(NOW) is None
        assert role.projected_bait_at_end(NOW) is None


class TestBaitWastedByCap:
    def test_a_tick_that_passed_while_the_counter_sat_full_is_counted(self) -> None:
        store = FishingState(Path("/dev/null"), Path("/dev/null"))
        role = store.observe("ROLE_A", bait_current=10, bait_cap=10, regen_seconds=3 * HOUR,
                             now=NOW)
        assert role.bait_wasted_by_cap == 0, "the first observation has nothing to compare"
        role = store.observe("ROLE_A", bait_current=10, bait_cap=10, now=NOW + timedelta(hours=7))
        assert role.bait_wasted_by_cap == 2, "two recovery instants produced nothing"

    def test_a_spend_in_between_is_not_counted_as_waste(self) -> None:
        """If the counter was drawn down, the instant it refilled was not wasted."""
        store = FishingState(Path("/dev/null"), Path("/dev/null"))
        store.observe("ROLE_A", bait_current=10, bait_cap=10, regen_seconds=3 * HOUR, now=NOW)
        store.record_run(_run(at=NOW + timedelta(hours=1), bait_cost=1,
                              points_before=0, points_after=50))
        role = store.role("ROLE_A")
        role.normal_bait_current = 8
        role.observed_bait = 8
        role.observed_at = NOW + timedelta(hours=1)
        store.observe("ROLE_A", bait_current=9, bait_cap=9, now=NOW + timedelta(hours=7))
        assert role.bait_wasted_by_cap == 0

    def test_below_cap_never_counts_waste(self) -> None:
        store = FishingState(Path("/dev/null"), Path("/dev/null"))
        store.observe("ROLE_A", bait_current=3, bait_cap=10, regen_seconds=3 * HOUR, now=NOW)
        role = store.observe("ROLE_A", bait_current=5, bait_cap=10, now=NOW + timedelta(hours=9))
        assert role.bait_wasted_by_cap == 0


class TestTheEndgame:
    def state(self, **overrides) -> RoleFishingState:
        base = dict(role_key="ROLE_A", normal_bait_current=5, bait_cap=10,
                    regen_seconds=3 * HOUR, event_end_at=NOW + timedelta(hours=4))
        base.update(overrides)
        return RoleFishingState(**base)

    def test_without_a_measured_run_duration_the_endgame_is_unknown(self) -> None:
        verdict = self.state().endgame(NOW, seconds_per_run=None)
        assert verdict["known"] is False
        assert verdict["active"] is False

    def test_without_an_event_end_the_endgame_is_unknown(self) -> None:
        verdict = self.state(event_end_at=None).endgame(NOW, seconds_per_run=30.0)
        assert verdict["known"] is False

    def test_a_window_shorter_than_the_remaining_work_is_an_endgame(self) -> None:
        """6 bait to spend, 60 s each, 10 min margin = 16 min needed; 4 h left is plenty."""
        comfortable = self.state(event_end_at=NOW + timedelta(hours=4))
        assert comfortable.endgame(NOW, seconds_per_run=60.0)["active"] is False
        # Two bait recoveries in ten minutes: not enough time to spend the rest.
        tight = self.state(normal_bait_current=10,
                           event_end_at=NOW + timedelta(minutes=10))
        verdict = tight.endgame(NOW, seconds_per_run=120.0)
        assert verdict["active"] is True
        assert verdict["reason"] == "WINDOW_SHORTER_THAN_BAIT_LEFT"

    def test_the_endgame_outranks_the_full_counter(self) -> None:
        """§15 raises priority as the event closes; §2's cap matters less at that point."""
        role = self.state(normal_bait_current=10, event_end_at=NOW + timedelta(minutes=5))
        assert role.pressure(NOW, seconds_per_run=200.0) is BaitPressure.ENDGAME


# ----------------------------------------------------- §1/§14/§16 arithmetic


class TestTheEventArithmetic:
    def store(self, tmp_path: Path) -> FishingState:
        return FishingState(tmp_path / "state.json", tmp_path / "runs.jsonl")

    def test_totals_are_the_sum_of_the_runs_that_have_the_reading(self, tmp_path) -> None:
        store = self.store(tmp_path)
        for i, (before, after) in enumerate([(0, 100), (100, 250), (250, 400)]):
            store.record_run(_run(run_id=f"R{i}", at=NOW, points_before=before,
                                  points_after=after, depth_m=40 + i))
        kpis = store.kpis("ROLE_A")
        assert kpis[KPI_BAIT_USED] == 3
        assert kpis[KPI_TOTAL_POINTS] == 400
        assert kpis[KPI_POINTS_PER_BAIT_AVG] == pytest.approx(400 / 3)
        assert kpis[KPI_POINTS_PER_BAIT_P50] == 150
        assert kpis[KPI_BEST_POINTS_PER_BAIT] == 150
        assert kpis[KPI_BEST_DEPTH] == 42
        assert kpis["runs_with_efficiency"] == 3

    def test_a_run_without_the_reading_does_not_dilute_the_average(self, tmp_path) -> None:
        """The count travels with the average, so 1-of-2 cannot look like 2-of-2."""
        store = self.store(tmp_path)
        store.record_run(_run(run_id="good", points_before=0, points_after=200))
        store.record_run(_run(run_id="unreadable", points_before=None, points_after=None))
        kpis = store.kpis("ROLE_A")
        assert kpis[KPI_POINTS_PER_BAIT_AVG] == 200.0
        assert kpis["runs"] == 2
        assert kpis["runs_with_efficiency"] == 1

    def test_a_special_lane_run_cannot_inflate_the_normal_bait_figure(self, tmp_path) -> None:
        """The metric the policy protects must be computed on normal bait only."""
        store = self.store(tmp_path)
        store.record_run(_run(run_id="normal", points_before=0, points_after=100))
        store.record_run(_run(run_id="treasure", lane="TREASURE",
                              points_before=100, points_after=100000))
        kpis = store.kpis("ROLE_A")
        assert kpis[KPI_BAIT_USED] == 1
        assert kpis[KPI_POINTS_PER_BAIT_AVG] == 100.0
        assert store.points_per_bait_rolling("ROLE_A") == 100.0

    def test_zero_score_runs_are_counted_for_failure_analysis(self, tmp_path) -> None:
        store = self.store(tmp_path)
        store.record_run(_run(run_id="ok", points_before=0, points_after=90,
                              verifier={"status": "COMPLETE"}))
        store.record_run(_run(run_id="bad", points_before=90, points_after=90,
                              verifier={"status": "ZERO_SCORE_RUN"}))
        assert store.kpis("ROLE_A")["zero_score_runs"] == 1

    def test_the_forecast_names_every_input_it_used(self, tmp_path) -> None:
        store = self.store(tmp_path)
        store.record_run(_run(points_before=0, points_after=100, duration_s=30.0))
        store.observe("ROLE_A", bait_current=4, bait_cap=10, regen_seconds=3 * HOUR,
                      event_end_at=NOW + timedelta(hours=9), points_total=100, now=NOW)
        forecast = store.expected_final_points("ROLE_A", NOW)
        assert forecast["known"] is True
        assert forecast["bait_available"] == 7
        assert forecast["expected_final_points"] == pytest.approx(100 + 7 * 100.0)

    def test_a_forecast_without_a_measured_efficiency_reports_unknown(self, tmp_path) -> None:
        """§14's figure moves real priority, so it must not be built on a guess."""
        store = self.store(tmp_path)
        store.observe("ROLE_A", bait_current=4, bait_cap=10, regen_seconds=3 * HOUR,
                      event_end_at=NOW + timedelta(hours=9), points_total=100, now=NOW)
        forecast = store.expected_final_points("ROLE_A", NOW)
        assert forecast["known"] is False
        assert forecast["expected_final_points"] is None

    def test_seconds_per_run_is_a_median_of_real_durations(self, tmp_path) -> None:
        store = self.store(tmp_path)
        for duration in (20.0, 30.0, 40.0):
            store.record_run(_run(run_id=f"d{duration}", duration_s=duration))
        assert store.seconds_per_run("ROLE_A") == 30.0

    def test_seconds_per_run_is_unknown_with_no_runs(self, tmp_path) -> None:
        assert self.store(tmp_path).seconds_per_run("ROLE_A") is None


class TestRolesAreNeverMixed:
    def test_role_b_is_unknown_until_it_is_read(self, tmp_path) -> None:
        store = FishingState(tmp_path / "state.json", tmp_path / "runs.jsonl")
        store.observe("ROLE_A", bait_current=5, bait_cap=10, now=NOW)
        assert store.role("ROLE_B").normal_bait_current is None
        assert store.role("ROLE_B").state_is_read is False
        assert store.role("ROLE_B").pressure(NOW) is BaitPressure.UNKNOWN

    def test_a_run_only_moves_its_own_roles_totals(self, tmp_path) -> None:
        store = FishingState(tmp_path / "state.json", tmp_path / "runs.jsonl")
        store.observe("ROLE_A", bait_current=5, bait_cap=10, now=NOW)
        store.observe("ROLE_B", bait_current=3, bait_cap=10, now=NOW)
        store.record_run(_run(role_key="ROLE_A", bait_cost=1,
                              points_before=0, points_after=100))
        assert store.kpis("ROLE_A")[KPI_BAIT_USED] == 1
        assert store.kpis("ROLE_B")[KPI_BAIT_USED] == 0
        assert store.role("ROLE_B").normal_bait_current == 3


class TestTheFileSurvives:
    def test_a_round_trip_preserves_unknown_keys_and_the_numbers(self, tmp_path) -> None:
        path = tmp_path / "state.json"
        path.write_text(json.dumps({
            "schema_version": 1,
            "note": "kept",
            "roles": {"ROLE_A": {"role_id": "1", "bait_current": 5, "bait_cap": 10,
                                 "free_special_attempts": "UNKNOWN"}},
            "an_operators_field": {"do": "not erase me"},
        }), encoding="utf-8")
        store = FishingState.load(path, tmp_path / "runs.jsonl")
        store.observe("ROLE_A", bait_current=6, now=NOW)
        store.save()

        after = json.loads(path.read_text(encoding="utf-8"))
        assert after["an_operators_field"] == {"do": "not erase me"}
        assert after["roles"]["ROLE_A"]["free_special_attempts"] == "UNKNOWN"
        assert after["roles"]["ROLE_A"]["normal_bait_current"] == 6
        assert after["policy"] == "NORMAL_BAIT_ONLY"

    def test_a_corrupt_file_loads_as_unknown_rather_than_raising(self, tmp_path) -> None:
        path = tmp_path / "state.json"
        path.write_text("{ not json at all", encoding="utf-8")
        store = FishingState.load(path, tmp_path / "runs.jsonl")
        assert store.roles == {}
        assert store.role("ROLE_A").pressure(NOW) is BaitPressure.UNKNOWN

    def test_a_corrupt_ledger_line_is_skipped_and_the_rest_still_reads(self, tmp_path) -> None:
        ledger = tmp_path / "runs.jsonl"
        ledger.write_text(
            json.dumps(LEGACY_ROW) + "\n" + "{ broken\n" + json.dumps(_run().to_mapping()) + "\n",
            encoding="utf-8",
        )
        store = FishingState(tmp_path / "state.json", ledger)
        assert store.run_count() == 2

    def test_a_naive_timestamp_is_refused_rather_than_assumed(self, tmp_path) -> None:
        """A local time cannot drive an unattended wake, so it is not a time we act on."""
        store = FishingState(tmp_path / "state.json", tmp_path / "runs.jsonl")
        role = store.observe("ROLE_A", event_end_at="2026-10-01T24:00", now=NOW)
        assert role.event_end_at is None
        role = store.observe("ROLE_A", event_end_at="2026-10-01T00:00:00+08:00", now=NOW)
        assert role.event_end_at is not None


# --------------------------------------------------------- §16 the console view


class TestTheConsoleShowsTheBaitBudget:
    """§16's display rules, tested as functions -- no Tk window is needed to render a string.

    The section asks for two things at once and they are one requirement: show the bait and the
    points, and do not show special mode as pending work.  A display that quietly omitted a
    pressure value, or presented an eleven-hour-old reading as the next recovery, would satisfy
    the letter of the first half while making the second half unreadable.
    """

    def test_a_future_instant_reads_as_a_countdown(self) -> None:
        from tools.control_panel import ControlPanel

        soon = (datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)).isoformat()
        rendered = ControlPanel._fishing_countdown(soon)
        assert "小时" in rendered and "后" in rendered

    def test_a_past_instant_says_it_is_already_due(self) -> None:
        from tools.control_panel import ControlPanel

        assert ControlPanel._fishing_countdown("2020-01-01T00:00:00+00:00") == "已到"

    @pytest.mark.parametrize("value", [None, "", "2026-09-30T13:00", "not a time"])
    def test_an_unusable_instant_says_unread_rather_than_blank(self, value) -> None:
        from tools.control_panel import ControlPanel

        assert ControlPanel._fishing_countdown(value) == "未读取"

    def test_a_missing_number_is_a_dash_not_a_zero(self) -> None:
        """A zero would read as a measured zero, which is a different claim."""
        from tools.control_panel import ControlPanel

        assert ControlPanel._fishing_number(None) == "—"
        assert ControlPanel._fishing_number(0) == "0"

    def test_a_stale_reading_asks_to_be_re_read(self) -> None:
        from tools.control_panel import ControlPanel

        stale = {
            "observed_at": (datetime.now(timezone.utc) - timedelta(hours=11)).isoformat(),
            "regen_seconds": 3 * 3600,
            "next_bait_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        }
        rendered = ControlPanel._fishing_next_recovery(stale)
        assert "待重读" in rendered

    def test_a_fresh_reading_gives_the_countdown(self) -> None:
        from tools.control_panel import ControlPanel

        fresh = {
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "regen_seconds": 3 * 3600,
            "next_bait_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        }
        assert "后" in ControlPanel._fishing_next_recovery(fresh)

    def test_an_unread_role_never_borrows_a_number(self) -> None:
        from tools.control_panel import ControlPanel

        assert ControlPanel._fishing_next_recovery({"observed_at": None}) == "未读取"

    def test_every_pressure_state_has_a_label(self) -> None:
        """A new ``BaitPressure`` member must not be able to reach the console unnamed."""
        from tools.control_panel import ControlPanel

        for member in BaitPressure:
            assert member.value in ControlPanel.FISHING_PRESSURE_ZH, (
                f"{member.value} would be rendered as a raw enum value"
            )

    def test_the_console_reads_the_same_metric_names_the_report_uses(self) -> None:
        from tools.control_panel import ControlPanel

        shown = {metric for metric, _label in ControlPanel.FISHING_KPI_FIELDS}
        assert {
            KPI_BAIT_USED, KPI_BAIT_WASTED, KPI_BAIT_REMAINING, KPI_TOTAL_POINTS,
            KPI_POINTS_PER_BAIT_AVG, KPI_POINTS_PER_BAIT_P50, KPI_BEST_POINTS_PER_BAIT,
            KPI_BEST_DEPTH,
        } <= shown


# --------------------------------------------------------- §16 the console view


class TestTheConsoleShowsTheBaitBudget:
    """§16's display rules, tested as functions -- no Tk window is needed to render a string.

    The section asks for two things at once and they are one requirement: show the bait and the
    points, and do not show special mode as pending work.  A display that quietly omitted a
    pressure value, or presented an eleven-hour-old reading as the next recovery, would satisfy
    the letter of the first half while making the second half unreadable.
    """

    def test_a_future_instant_reads_as_a_countdown(self) -> None:
        from tools.control_panel import ControlPanel

        soon = (datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)).isoformat()
        rendered = ControlPanel._fishing_countdown(soon)
        assert "小时" in rendered and "后" in rendered

    def test_a_past_instant_says_it_is_already_due(self) -> None:
        from tools.control_panel import ControlPanel

        assert ControlPanel._fishing_countdown("2020-01-01T00:00:00+00:00") == "已到"

    @pytest.mark.parametrize("value", [None, "", "2026-09-30T13:00", "not a time"])
    def test_an_unusable_instant_says_unread_rather_than_blank(self, value) -> None:
        from tools.control_panel import ControlPanel

        assert ControlPanel._fishing_countdown(value) == "未读取"

    def test_a_missing_number_is_a_dash_not_a_zero(self) -> None:
        """A zero would read as a measured zero, which is a different claim."""
        from tools.control_panel import ControlPanel

        assert ControlPanel._fishing_number(None) == "—"
        assert ControlPanel._fishing_number(0) == "0"

    def test_a_stale_reading_asks_to_be_re_read(self) -> None:
        from tools.control_panel import ControlPanel

        stale = {
            "observed_at": (datetime.now(timezone.utc) - timedelta(hours=11)).isoformat(),
            "regen_seconds": 3 * 3600,
            "next_bait_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        }
        rendered = ControlPanel._fishing_next_recovery(stale)
        assert "待重读" in rendered

    def test_a_fresh_reading_gives_the_countdown(self) -> None:
        from tools.control_panel import ControlPanel

        fresh = {
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "regen_seconds": 3 * 3600,
            "next_bait_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        }
        assert "后" in ControlPanel._fishing_next_recovery(fresh)

    def test_an_unread_role_never_borrows_a_number(self) -> None:
        from tools.control_panel import ControlPanel

        assert ControlPanel._fishing_next_recovery({"observed_at": None}) == "未读取"

    def test_every_pressure_state_has_a_label(self) -> None:
        """A new ``BaitPressure`` member must not be able to reach the console unnamed."""
        from tools.control_panel import ControlPanel

        for member in BaitPressure:
            assert member.value in ControlPanel.FISHING_PRESSURE_ZH, (
                f"{member.value} would be rendered as a raw enum value"
            )

    def test_the_console_reads_the_same_metric_names_the_report_uses(self) -> None:
        from tools.control_panel import ControlPanel

        shown = {metric for metric, _label in ControlPanel.FISHING_KPI_FIELDS}
        assert {
            KPI_BAIT_USED, KPI_BAIT_WASTED, KPI_BAIT_REMAINING, KPI_TOTAL_POINTS,
            KPI_POINTS_PER_BAIT_AVG, KPI_POINTS_PER_BAIT_P50, KPI_BEST_POINTS_PER_BAIT,
            KPI_BEST_DEPTH,
        } <= shown
