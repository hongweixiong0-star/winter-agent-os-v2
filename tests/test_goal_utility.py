"""Utility AI on the goal board: the terms, their bounds, and the one invariant.

The invariant is the point of this file.  ``goal_library.best`` documents a measured
failure -- an earlier attempt to re-tier the board broke the sweep rotation and made
``CLEAR_INTEL`` unreachable.  So the dynamic layer is additive and every term is
bounded inside a gap the catalogue already has.  If a future change raises a ceiling
past the gap between routine work and a real claim, ``test_no_combination_can_re_tier
_the_board`` fails and says why -- which is cheaper than discovering it from a live run
that stops collecting its dailies.

The other three properties worth pinning:

* no invented experience -- a route with no measured attempts scores zero, not a guess
  (operator §四.8);
* ``fairness`` must not read ``overdue_ratio``, because the sweep tickets already price
  their own staleness and reading it twice would re-rank the rotation;
* ``rank`` filters nothing but "no skills" and "-inf": eligibility belongs to the
  capability gate, and a second gate here could only make the agent more conservative
  (§六).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from winter_agent_v2.goal_library import GoalState, GoalStatus, GoalLibrary
from winter_agent_v2.goal_utility import (
    FAIRNESS_AGE_BONUS,
    FAIRNESS_OVERDUE_MINUTES,
    HISTORY_BONUS,
    HISTORY_MIN_ATTEMPTS,
    REPEAT_FAILURE_PENALTY,
    REPEAT_FAILURE_SATURATES_AT,
    RESOURCE_FIT_BONUS,
    GoalFairness,
    RouteFact,
    append_decision,
    blocked_until,
    decision_row,
    entry,
    fact_for_skill,
    fairness_bonus,
    history_bonus,
    load,
    load_routes,
    rank,
    repeat_failure_penalty,
    resource_fit,
    save,
    utility,
)

NOW = datetime(2026, 9, 21, 16, 0, tzinfo=timezone.utc)

#: The real price scale, taken from goal_library: gathering is 70, a claimable routine
#: is 250, the stamina goal measured 2450.  The invariant below is stated against 70 and
#: 250 because those are the two the rotation was designed between.
ROUTINE_PRICE = 70.0
CLAIM_PRICE = 250.0

BEAST = RouteFact(
    route="INTEL_BEAST", name="情报·打野", success_rate=0.889, attempts=54,
    cost_per_success=11.3, availability="AVAILABLE",
    skills=("DISPATCH_INTEL_BEAST", "OPEN_INTEL"),
)
THIN = RouteFact(
    route="THIN", name="证据很少", success_rate=1.0, attempts=HISTORY_MIN_ATTEMPTS - 1,
    cost_per_success=None, availability="AVAILABLE", skills=("THIN_SKILL",),
)


class _World:
    """The two things ``resource_fit`` asks of a WorldState."""

    def __init__(self, stamina=None, idle=None):
        self.stamina = {} if stamina is None else {"current": stamina}
        self.idle_marches = idle


def goal(goal_id="AVOID_STAMINA_WASTE", status=GoalStatus.READY, **over) -> GoalState:
    base = dict(development_value=ROUTINE_PRICE, available_skills=("DISPATCH_INTEL_BEAST",))
    base.update(over)
    return GoalState(goal_id, status, **base)


# ------------------------------------------------------------- route facts


def test_the_measured_route_card_is_read() -> None:
    facts = load_routes()
    if not facts:
        pytest.skip("knowledge/strategy/stamina_routes.json absent on this machine")
    beast = fact_for_skill(facts, "DISPATCH_INTEL_BEAST")
    assert beast is not None, "the beast dispatch skill is on the card's own wired list"
    assert 0.0 < beast.success_rate <= 1.0
    assert beast.attempts > 0
    assert beast.cost_per_success is None or beast.cost_per_success > 0


def test_a_missing_or_broken_card_is_an_empty_ledger(tmp_path) -> None:
    assert load_routes(tmp_path / "absent.json") == ()
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert load_routes(broken) == ()


def test_an_unknown_skill_maps_to_no_route() -> None:
    assert fact_for_skill((BEAST,), "NOT_ON_THE_CARD") is None


# ---------------------------------------------------------------- history


def test_a_route_with_no_measured_attempts_contributes_nothing() -> None:
    """§四.8: no invented experience.  Five attempts is the floor, four is not."""
    assert history_bonus((THIN,), ("THIN_SKILL",)) == 0.0
    real = history_bonus((BEAST,), ("DISPATCH_INTEL_BEAST",))
    assert 0.0 < real <= HISTORY_BONUS


def test_a_better_measured_rate_is_worth_more() -> None:
    weak = RouteFact("W", "w", 0.4, 54, 1.0, "AVAILABLE", ("SKILL",))
    strong = RouteFact("S", "s", 0.9, 54, 1.0, "AVAILABLE", ("SKILL",))
    assert history_bonus((strong,), ("SKILL",)) > history_bonus((weak,), ("SKILL",))


def test_history_never_exceeds_its_ceiling() -> None:
    perfect = RouteFact("P", "p", 1.0, 5000, 1.0, "AVAILABLE", ("SKILL",))
    assert history_bonus((perfect,), ("SKILL",)) <= HISTORY_BONUS


# --------------------------------------------------------------- resource


def test_a_non_route_goal_gets_no_resource_adjustment() -> None:
    """Zero means "no adjustment", not "needs nothing" -- the difference is the point."""
    assert resource_fit(_World(stamina=400, idle=2), ("SOME_OTHER_SKILL",), (BEAST,)) == 0.0


def test_a_stamina_route_is_worth_more_when_there_is_stamina_and_a_free_march() -> None:
    rich = resource_fit(_World(stamina=400, idle=2), ("DISPATCH_INTEL_BEAST",), (BEAST,))
    assert 0.0 < rich <= RESOURCE_FIT_BONUS


def test_a_stamina_route_at_the_floor_is_penalised_not_merely_unbonused() -> None:
    assert resource_fit(_World(stamina=30, idle=2), ("DISPATCH_INTEL_BEAST",), (BEAST,)) == -RESOURCE_FIT_BONUS


def test_no_free_march_penalises_a_stamina_route() -> None:
    assert resource_fit(_World(stamina=400, idle=0), ("DISPATCH_INTEL_BEAST",), (BEAST,)) == -RESOURCE_FIT_BONUS


def test_an_unreadable_stamina_leaves_the_route_alone() -> None:
    assert resource_fit(_World(stamina=None, idle=2), ("DISPATCH_INTEL_BEAST",), (BEAST,)) == 0.0


# -------------------------------------------------------------- fairness


def test_a_never_selected_goal_gets_no_fairness_credit() -> None:
    assert fairness_bonus(None, None, now=NOW) == 0.0
    assert fairness_bonus(GoalFairness(goal_id="G"), None, now=NOW) == 0.0


def test_fairness_only_starts_after_the_grace_window() -> None:
    inside = GoalFairness(goal_id="G", last_selected_at=(NOW - timedelta(minutes=5)).isoformat())
    assert fairness_bonus(inside, None, now=NOW) == 0.0
    outside = GoalFairness(goal_id="G", last_selected_at=(NOW - timedelta(minutes=90)).isoformat())
    assert fairness_bonus(outside, None, now=NOW) > 0.0


def test_fairness_grows_with_the_wait_and_stays_under_its_ceiling() -> None:
    waits = [60, 180, 720, 100_000]
    values = []
    for minutes in waits:
        row = GoalFairness(goal_id="G", last_selected_at=(NOW - timedelta(minutes=minutes)).isoformat())
        values.append(fairness_bonus(row, None, now=NOW))
    assert values == sorted(values), "a longer wait must never be worth less"
    assert max(values) < FAIRNESS_AGE_BONUS, "the ceiling is asymptotic, never reached"


def test_fairness_does_not_read_the_overdue_ratio() -> None:
    """The double-count guard: the sweep tickets already price their own staleness.

    ``_sweep_value`` adds ``SWEEP_AGE_BONUS * ratio/(1+ratio)`` to the catalogue price,
    so a fairness term reading the same ratio would charge for the same lateness twice
    and quietly re-rank the rotation this project measured its way into.
    """
    row = GoalFairness(goal_id="G")  # never selected
    evidence = {"overdue_ratio": 9.0, "overdue": True}
    assert fairness_bonus(row, evidence, now=NOW) == 0.0


def test_an_unparseable_timestamp_is_simply_no_credit() -> None:
    assert fairness_bonus(GoalFairness(goal_id="G", last_selected_at="not a date"), None, now=NOW) == 0.0


# ------------------------------------------------------- repeat failure


def test_no_streak_is_no_penalty() -> None:
    assert repeat_failure_penalty(None) == 0.0
    assert repeat_failure_penalty(GoalFairness(goal_id="G")) == 0.0


def test_the_penalty_saturates_and_never_bans() -> None:
    values = [
        repeat_failure_penalty(GoalFairness(goal_id="G", no_progress_streak=streak))
        for streak in range(1, 12)
    ]
    # Non-increasing: a longer streak must never cost less.  Expressed as the reverse
    # sort rather than the forward one because the penalty is negative -- written the
    # other way first, and the assertion failed on its own arithmetic, not on the code.
    assert values == sorted(values, reverse=True), "a longer streak must never cost less"
    assert values[-1] == -REPEAT_FAILURE_PENALTY
    assert repeat_failure_penalty(
        GoalFairness(goal_id="G", no_progress_streak=REPEAT_FAILURE_SATURATES_AT)
    ) == -REPEAT_FAILURE_PENALTY


# --------------------------------------------------------------- utility


def test_the_catalogue_price_is_never_recomputed() -> None:
    """The base term is the goal's own ``priority``, copied, not derived again."""
    target = goal(development_value=123.0)
    assert utility(target).base == pytest.approx(target.priority)
    assert target.priority == pytest.approx(123.0)


def test_an_infinite_priority_carries_no_dynamic_terms() -> None:
    done = goal(status=GoalStatus.COMPLETE)
    breakdown = utility(done, world=_World(400, 2), facts=(BEAST,))
    assert breakdown.base == float("-inf")
    assert breakdown.dynamic == 0.0


def test_the_breakdown_names_the_terms_that_moved() -> None:
    target = goal()
    quiet = utility(target)
    assert quiet.why() == "catalogue price only"
    busy = utility(
        target, world=_World(stamina=400, idle=2), facts=(BEAST,),
        row=GoalFairness(goal_id=target.goal_id,
                         last_selected_at=(NOW - timedelta(hours=3)).isoformat(),
                         no_progress_streak=2),
        now=NOW,
    )
    assert "fairness" in busy.why() and "resource" in busy.why()
    assert "repeat-failure" in busy.why()
    assert busy.total == pytest.approx(
        busy.base + busy.fairness + busy.resource + busy.history + busy.repeat_failure
    )


# ------------------------------------------------------------- the invariant


def test_no_combination_can_re_tier_the_board() -> None:
    """Every positive term together must still not lift routine work over a claim.

    This is the whole safety argument for an additive utility layer on a board whose
    prices are load-bearing.  If a ceiling is raised past ``CLAIM_PRICE - ROUTINE_PRICE``
    the layer can re-tier the board, which is the failure the project already measured
    once (a tier that forced READY first made CLEAR_INTEL unreachable).
    """
    ceiling = FAIRNESS_AGE_BONUS + RESOURCE_FIT_BONUS + HISTORY_BONUS
    assert ceiling < CLAIM_PRICE - ROUTINE_PRICE, (
        f"dynamic ceiling {ceiling} reaches the gap between routine work "
        f"({ROUTINE_PRICE}) and a claim ({CLAIM_PRICE}); the layer could re-tier the board"
    )


def test_a_starved_low_priced_goal_can_beat_a_healthy_one() -> None:
    """§八E: fairness must actually be able to move the order, or it is decoration."""
    stale = goal("NEGLECTED", development_value=ROUTINE_PRICE - 5)
    fresh = goal("FAVOURED", development_value=ROUTINE_PRICE)
    ledger = {
        "NEGLECTED": GoalFairness(goal_id="NEGLECTED",
                                  last_selected_at=(NOW - timedelta(hours=6)).isoformat()),
        "FAVOURED": GoalFairness(goal_id="FAVOURED", last_selected_at=NOW.isoformat()),
    }
    order = [item.goal_id for item, _ in rank((fresh, stale), ledger=ledger, now=NOW)]
    assert order == ["NEGLECTED", "FAVOURED"]


def test_repeat_failure_drops_a_candidate_without_removing_it() -> None:
    """§四.5: it loses the order, it does not leave the board."""
    tired = goal("TIRED", development_value=ROUTINE_PRICE)
    healthy = goal("HEALTHY", development_value=ROUTINE_PRICE - 20)
    ledger = {"TIRED": GoalFairness(goal_id="TIRED", no_progress_streak=9)}
    order = [item.goal_id for item, _ in rank((tired, healthy), ledger=ledger, now=NOW)]
    assert order == ["HEALTHY", "TIRED"]
    board = [item.goal_id for item, _ in rank((tired,), ledger=ledger, now=NOW)]
    assert board == ["TIRED"], "a penalised goal is still on the board"


# ----------------------------------------------------------------- rank


def test_rank_ignores_goals_with_nothing_to_run() -> None:
    silent = GoalState("SILENT", GoalStatus.READY, development_value=999.0, available_skills=())
    ranked = rank((silent, goal()))
    assert [item.goal_id for item, _ in ranked] == ["AVOID_STAMINA_WASTE"]


def test_rank_drops_the_unschedulable_statuses() -> None:
    ranked = rank((
        goal(status=GoalStatus.COMPLETE),
        goal(status=GoalStatus.BLOCKED),
        goal(status=GoalStatus.UNKNOWN),
        goal("KEEP_ME"),
    ))
    assert [item.goal_id for item, _ in ranked] == ["KEEP_ME"]


def test_rank_is_stable_on_ties() -> None:
    board = (goal("A", development_value=70.0), goal("B", development_value=70.0))
    assert [item.goal_id for item, _ in rank(board)] == ["A", "B"]


def test_the_library_delegates_without_world_and_keeps_the_old_answer() -> None:
    library = GoalLibrary()
    board = (goal("A", development_value=70.0), goal("B", development_value=90.0))
    assert library.best(board).goal_id == "B", "no dynamic inputs -> the catalogue price"


def test_the_library_uses_the_dynamic_layer_when_it_is_given_one() -> None:
    library = GoalLibrary()
    stale = goal("A", development_value=70.0)
    fresh = goal("B", development_value=90.0)
    ledger = {"A": GoalFairness(goal_id="A",
                                last_selected_at=(NOW - timedelta(hours=6)).isoformat())}
    assert library.best((stale, fresh), fairness=ledger, now=NOW).goal_id == "A"


# -------------------------------------------------------- retry window


def test_the_retry_window_is_reported_not_enforced() -> None:
    """§五's ``next_check_at`` answers "when", it does not decide "whether".

    Eligibility is the capability gate's, and a second window here could only extend a
    block -- which §六 forbids ("Utility AI 不得把 V2 变得更加保守").
    """
    windowed = GoalFairness(goal_id="G", retry_after=(NOW + timedelta(minutes=10)).isoformat())
    assert blocked_until(windowed, NOW) is True
    lapsed = GoalFairness(goal_id="G", retry_after=(NOW - timedelta(minutes=10)).isoformat())
    assert blocked_until(lapsed, NOW) is False
    assert blocked_until(GoalFairness(goal_id="G"), NOW) is False
    # ...and a goal inside its window is still ranked, because the gate decides.
    inside = GoalFairness(goal_id="AVOID_STAMINA_WASTE",
                          retry_after=(NOW + timedelta(minutes=10)).isoformat())
    assert [item.goal_id for item, _ in rank((goal(),), ledger={"AVOID_STAMINA_WASTE": inside}, now=NOW)] \
        == ["AVOID_STAMINA_WASTE"]


# ------------------------------------------------------------- the log


def test_a_decision_row_carries_the_whole_board_and_the_gap() -> None:
    board = rank((goal("A", development_value=70.0), goal("B", development_value=90.0)))
    row = decision_row(role_id="1171757165", page="MAP", ranked=board,
                       chosen="B", runner_up="A", reason="catalogue price only", now=NOW)
    assert row["chosen"] == "B"
    assert row["runner_up"] == "A"
    assert {item["goal_id"] for item in row["board"]} == {"A", "B"}
    assert row["board"][0]["status"] == "READY"
    for item in row["board"]:
        assert {"base", "fairness", "resource", "history", "repeat_failure", "total"} <= set(item)


def test_the_log_appends_and_stays_bounded(tmp_path) -> None:
    path = tmp_path / "decisions.jsonl"
    for index in range(5):
        append_decision({"chosen": f"G{index}"}, path, limit=3)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert "G4" in lines[-1]


def test_logging_never_raises_on_an_unwritable_path(tmp_path) -> None:
    append_decision({"chosen": "G"}, tmp_path)  # a directory, not a file


# ------------------------------------------------------------- the store


def test_fairness_round_trips(tmp_path) -> None:
    path = tmp_path / "fairness.json"
    ledger = {"G": GoalFairness(goal_id="G", offered=4, selected=1, no_progress_streak=2,
                                last_block_reason="repair budget exhausted",
                                retry_after=(NOW + timedelta(minutes=30)).isoformat())}
    save(ledger, path)
    again = load(path)
    assert again["G"].offered == 4
    assert again["G"].no_progress_streak == 2
    assert again["G"].last_block_reason == "repair budget exhausted"


def test_a_missing_or_broken_store_is_empty(tmp_path) -> None:
    assert load(tmp_path / "absent.json") == {}
    broken = tmp_path / "broken.json"
    broken.write_text("[]", encoding="utf-8")
    assert load(broken) == {}


def test_entry_creates_on_first_sight() -> None:
    ledger: dict[str, GoalFairness] = {}
    assert entry(ledger, "NEW").goal_id == "NEW"
    assert entry(ledger, "NEW") is ledger["NEW"], "and is the same row next time"
