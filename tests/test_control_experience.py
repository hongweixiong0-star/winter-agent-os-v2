"""Per-control action experience: the eight change kinds, and the safety edges.

This pins the parts of ``winter_agent_v2/control_experience.py`` the rest of the
agent will lean on.  The two that matter most:

* ``classify_change`` must answer the operator's §六 list from the *states*, and
  must keep ``NO_OP`` and ``UNKNOWN`` apart -- "the tap was issued and nothing
  moved" is a finding about the control, "we could not tell" is a finding about
  the reading, and collapsing them would let a failed observation retire a
  control that was never actually tried.
* ``explorable_risk`` must refuse anything it does not positively recognise.
  An unknown price is not a low price; the paid and the irreversible stay out of
  trial-and-error (``00_MASTER_RULES.md`` §8, operator §九).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from winter_agent_v2.control_experience import (
    CHANGE_KINDS,
    ControlExperience,
    candidates,
    classify_change,
    control_key,
    explorable_risk,
    known_outcomes,
    l1_for,
    l1_reusable,
    load,
    register_l1,
    record_outcome,
    reusable_on_this_screen,
    save,
)

NOW = datetime(2026, 9, 21, 15, 0, tzinfo=timezone.utc)


def _state(**over: object) -> dict:
    base = {"page": "HOME", "popup": "", "marches": ["IDLE"]}
    base.update(over)
    return base


# ---------------------------------------------------------- classify_change


def test_a_page_move_is_a_page_change() -> None:
    assert classify_change(_state(page="HOME"), _state(page="ALLIANCE")) == "PAGE_CHANGED"


def test_a_popup_appearing_and_leaving_are_two_different_facts() -> None:
    assert classify_change(_state(), _state(popup="GET_MORE_STAMINA")) == "POPUP_OPENED"
    assert classify_change(_state(popup="GET_MORE_STAMINA"), _state()) == "POPUP_CLOSED"


def test_a_resource_that_went_down_is_a_spend_not_a_number_change() -> None:
    lower = _state(stamina={"current": 350})
    higher = _state(stamina={"current": 410})
    assert classify_change(higher, lower) == "RESOURCE_SPENT"
    assert classify_change(lower, higher) == "NUMBER_CHANGED"


def test_a_queue_countdown_moving_is_a_timer_not_a_queue_change() -> None:
    before = _state(queues={"training": {"remaining": 600, "state": "RUNNING"}})
    after = _state(queues={"training": {"remaining": 540, "state": "RUNNING"}})
    assert classify_change(before, after) == "TIMER_CHANGED"


def test_a_queue_appearing_is_a_queue_change_not_a_timer() -> None:
    before = _state(queues={"training": {"remaining": 600}})
    after = _state(queues={"training": {"remaining": 600}, "research": {"remaining": 60}})
    assert classify_change(before, after) == "QUEUE_CHANGED"


def test_marches_moving_is_a_queue_change() -> None:
    assert classify_change(_state(marches=["MARCHING"]), _state(marches=["IDLE"])) == "QUEUE_CHANGED"


def test_a_goal_table_moving_is_a_progress_change() -> None:
    before = _state(goals={"KEEP_TRAINING_PRODUCTIVE": "DISCOVERED"})
    after = _state(goals={"KEEP_TRAINING_PRODUCTIVE": "READY"})
    assert classify_change(before, after) == "PROGRESS_CHANGED"


def test_an_identical_frame_is_a_no_op_and_not_unknown() -> None:
    assert classify_change(_state(), _state()) == "NO_OP"


def test_an_unreadable_state_is_unknown_and_not_a_no_op() -> None:
    assert classify_change(None, _state()) == "UNKNOWN"
    assert classify_change(_state(), {}) == "UNKNOWN"
    assert classify_change(None, None) == "UNKNOWN"


def test_every_answer_is_one_of_the_declared_kinds() -> None:
    pairs = [
        (_state(), _state(page="MAP")),
        (_state(), _state()),
        (None, None),
        (_state(stamina={"current": 5}), _state(stamina={"current": 9})),
    ]
    for before, after in pairs:
        assert classify_change(before, after) in CHANGE_KINDS


# ------------------------------------------------------------ risk policy


def test_ordinary_risks_are_explorable() -> None:
    for risk in ("LOW", "T1", "T2", "LOW_RESOURCE_SPEND", "MEDIUM_STAMINA_SPEND"):
        assert explorable_risk(risk), risk


def test_paid_and_irreversible_are_never_explorable() -> None:
    for risk in ("REAL_MONEY", "REAL_MONEY_PURCHASE", "T4", "ACCOUNT_DELETE", "IRREVERSIBLE"):
        assert not explorable_risk(risk), risk


def test_an_unknown_risk_is_refused() -> None:
    for risk in ("", None, "SOMETHING_NEW", "MEDIUM"):
        assert not explorable_risk(risk), risk


# --------------------------------------------------------- record_outcome


def _control(**over: object) -> ControlExperience:
    base = dict(page="HOME", control="BTN_OPEN_ALLIANCE", position_norm=(0.5, 0.9),
                read_from_frame="frame_a.png", risk="LOW",
                hypotheses=("OPENS_ALLIANCE", "CLAIMS_REWARD"))
    base.update(over)
    return ControlExperience(**base)  # type: ignore[arg-type]


def test_a_real_change_settles_the_hypotheses() -> None:
    control = _control()
    record_outcome(control, change="PAGE_CHANGED", result_name="OPEN_ALLIANCE",
                   before=_state(), after=_state(page="ALLIANCE"),
                   frame="frame_b.png", now=NOW)
    assert control.attempts == 1
    assert control.known_result == "OPEN_ALLIANCE"
    assert control.known_change == "PAGE_CHANGED"
    assert control.hypotheses == ()
    assert control.read_from_frame == "frame_b.png"


def test_a_no_op_keeps_the_hypotheses_and_the_hope() -> None:
    control = _control()
    record_outcome(control, change="NO_OP", before=_state(), after=_state(), now=NOW)
    assert control.attempts == 1
    assert control.known_result == ""
    assert control.hypotheses != ()


def test_reading_without_tapping_does_not_count_as_an_attempt() -> None:
    control = _control()
    record_outcome(control, change="NO_OP", clicked=False, now=NOW)
    assert control.attempts == 0
    assert control.last_result == "NO_OP"


def test_a_spend_is_recorded_with_its_before_and_after() -> None:
    control = _control()
    record_outcome(control, change="RESOURCE_SPENT",
                   before=_state(stamina={"current": 410}),
                   after=_state(stamina={"current": 395}), now=NOW)
    assert control.cost_seen["current"] == {"amount": 15, "before": 410, "after": 395}


def test_an_unrecognised_change_string_is_unknown() -> None:
    control = _control()
    record_outcome(control, change="SOMETHING_ELSE", now=NOW)
    assert control.last_result == "UNKNOWN"


def test_three_no_ops_retire_a_control_for_automatic_repetition() -> None:
    control = _control()
    for cycle in range(3):
        record_outcome(control, change="NO_OP", now=NOW + timedelta(minutes=cycle))
    assert control.sterile


def test_a_control_that_once_worked_is_never_sterile() -> None:
    control = _control()
    record_outcome(control, change="PAGE_CHANGED", result_name="OPEN_ALLIANCE", now=NOW)
    for cycle in range(5):
        record_outcome(control, change="NO_OP", now=NOW + timedelta(minutes=cycle))
    assert not control.sterile


# ------------------------------------------------------------- selection


def _ledger() -> dict[str, ControlExperience]:
    return {
        control_key("HOME", "A"): _control(control="A", attempts=0),
        control_key("HOME", "B"): _control(control="B", attempts=0),
        control_key("HOME", "NO_POS"): _control(control="NO_POS", position_norm=None),
        control_key("HOME", "REFUSED"): _control(control="REFUSED", refused_reason="REAL_MONEY"),
        control_key("HOME", "IN_COOLDOWN"): _control(
            control="IN_COOLDOWN", cooldown_seconds=600,
            last_at=(NOW - timedelta(seconds=30)).isoformat()),
        control_key("MAP", "ELSEWHERE"): _control(page="MAP", control="ELSEWHERE"),
    }


def test_candidates_are_limited_to_the_page_and_skip_the_unusable() -> None:
    picked = {item.control for item in candidates(_ledger(), "HOME", now=NOW)}
    assert picked == {"A", "B"}, picked


def test_candidates_prefer_the_least_understood_then_least_tried() -> None:
    ledger = _ledger()
    ledger[control_key("HOME", "TRIED")] = _control(control="TRIED", attempts=4)
    order = [item.control for item in candidates(ledger, "HOME", now=NOW)]
    assert order.index("TRIED") > order.index("A"), order


def test_a_cooldown_that_has_run_out_is_offered_again() -> None:
    ledger = _ledger()
    ledger[control_key("HOME", "IN_COOLDOWN")].last_at = (NOW - timedelta(hours=1)).isoformat()
    picked = {item.control for item in candidates(ledger, "HOME", now=NOW)}
    assert "IN_COOLDOWN" in picked


def test_known_outcomes_can_be_narrowed_to_one_goal() -> None:
    ledger = _ledger()
    ledger[control_key("HOME", "A")].known_result = "OPEN_ALLIANCE"
    ledger[control_key("HOME", "A")].last_result = "PAGE_CHANGED"
    ledger[control_key("HOME", "A")].goal_help = {"ALLIANCE_ROUTINE": "opens the alliance page"}
    ledger[control_key("HOME", "B")].known_result = "OPEN_MAIL"
    ledger[control_key("HOME", "B")].last_result = "PAGE_CHANGED"
    assert {item.control for item in known_outcomes(ledger, "HOME")} == {"A", "B"}
    assert {item.control for item in known_outcomes(ledger, "HOME", goal_id="ALLIANCE_ROUTINE")} == {"A"}


def _verified_l1(**overrides: object) -> ControlExperience:
    entry = _control(control="BTN_OPEN_ALLIANCE")
    record_outcome(entry, change="PAGE_CHANGED", result_name="OPEN_ALLIANCE", now=NOW)
    register_l1(
        entry,
        goal="ALLIANCE_ROUTINE",
        state="HOME|IDLE",
        features={"text": "联盟"},
        action={"kind": "TAP_SEMANTIC", "target": "BTN_OPEN_ALLIANCE"},
        expected_effect="alliance_page_open",
        observed_effect="PAGE_CHANGED",
        now=NOW,
    )
    for key, value in overrides.items():
        setattr(entry, key, value)
    return entry


def test_l1_reuse_requires_expected_observed_and_matching_action_evidence() -> None:
    valid = _verified_l1()
    assert l1_reusable(valid, now=NOW)
    assert l1_for(
        {control_key(valid.page, valid.control): valid},
        page="HOME", goal="ALLIANCE_ROUTINE", state="HOME|IDLE",
        present_words=("联盟",), now=NOW,
    ) is valid

    for invalid in (
        _verified_l1(expected_effect=""),
        _verified_l1(observed_effect=""),
        _verified_l1(action={"kind": "TAP_SEMANTIC", "target": "BTN_OPEN_MAIL"}),
    ):
        assert not l1_reusable(invalid, now=NOW)
        assert l1_for(
            {control_key(invalid.page, invalid.control): invalid},
            page="HOME", goal="ALLIANCE_ROUTINE", state="HOME|IDLE",
            present_words=("联盟",), now=NOW,
        ) is None


# ----------------------------------------------------------------- store


def test_round_trip_keeps_the_position_and_the_frame_it_came_from(tmp_path) -> None:
    path = tmp_path / "control_experience.json"
    ledger = {control_key("HOME", "A"): _control(control="A")}
    save(ledger, path)
    reloaded = load(path)
    item = reloaded[control_key("HOME", "A")]
    assert item.position_norm == (0.5, 0.9)
    assert item.read_from_frame == "frame_a.png", "a coordinate must stay traceable to its frame"
    assert item.hypotheses == ("OPENS_ALLIANCE", "CLAIMS_REWARD")


def test_a_missing_or_broken_file_is_an_empty_store(tmp_path) -> None:
    assert load(tmp_path / "absent.json") == {}
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert load(broken) == {}


def test_saving_never_raises_on_an_unwritable_path(tmp_path) -> None:
    save({}, tmp_path)  # a directory, not a file


# ------------------------------------------------- the screen, not the page
#
# Measured 2026-09-23 (issue #109): the client draws 22 distinct overlays under ``POPUP``, and every
# one of the 2717 ``POPUP`` readings in the corpus names which.  The ledger keyed them all as
# ``POPUP|<control>``, so the close-X learned on the 退出确认 dialog at (0.8819, 0.3563) was handed
# to 加成总览 -- where that point is the middle of the panel's own number column.  Eight consecutive
# runs tapped it, observed nothing, and died.


def test_a_page_that_names_its_screen_keeps_the_page_key() -> None:
    """49 of the 57 stored positions are on pages the page fully describes; they must not move."""
    assert control_key("HOME", "BTN_OPEN_MAIL", "HOME") == "HOME|BTN_OPEN_MAIL"
    assert control_key("HOME", "BTN_OPEN_MAIL") == "HOME|BTN_OPEN_MAIL"
    assert control_key("MAP", "BTN_OPEN_HOME", "") == "MAP|BTN_OPEN_HOME"


def test_a_screen_the_page_cannot_name_goes_into_the_key() -> None:
    assert (control_key("POPUP", "BTN_CLOSE", "POPUP|POWER_OVERVIEW")
            == "POPUP|POWER_OVERVIEW|BTN_CLOSE")
    # ...and so do the two sub-states the client switches inside one page, for the same reason.
    assert (control_key("TRAINING", "BTN_START_TRAINING",
                        "TRAINING|training.camp_open_label=盾兵营")
            == "TRAINING|training.camp_open_label=盾兵营|BTN_START_TRAINING")


def test_two_popups_do_not_share_a_key() -> None:
    exit_confirm = control_key("POPUP", "BTN_CLOSE", "POPUP|EXIT_CONFIRM")
    power = control_key("POPUP", "BTN_CLOSE", "POPUP|POWER_OVERVIEW")
    assert exit_confirm != power


def test_a_point_measured_on_one_popup_is_refused_on_another() -> None:
    entry = ControlExperience(page="POPUP", control="BTN_CLOSE",
                              position_norm=(0.8819, 0.3563), screen="POPUP|EXIT_CONFIRM")
    assert reusable_on_this_screen(entry, "POPUP|EXIT_CONFIRM"), "the screen it was read on"
    assert not reusable_on_this_screen(entry, "POPUP|POWER_OVERVIEW"), (
        "and nothing else: this is the point that spent eight live runs on the wrong panel"
    )
    assert not reusable_on_this_screen(entry, "POPUP"), (
        "a frame that cannot name its popup cannot claim the point either"
    )


def test_an_entry_that_recorded_no_screen_is_refused_a_screen_that_matters() -> None:
    """The direction is strict on purpose: a point nothing wrote a screen for is not evidence."""
    legacy = ControlExperience(page="HOME", control="BTN_OPEN_MAIL", position_norm=(0.0, 0.5))
    assert reusable_on_this_screen(legacy, "HOME"), (
        "on a page that is its own screen the key already pinned the page, so nothing changed"
    )
    assert not reusable_on_this_screen(legacy, "HOME|QUICK_PANEL_OPEN")
    assert not reusable_on_this_screen(legacy, "POPUP|POWER_OVERVIEW")


def test_the_screen_field_survives_a_round_trip(tmp_path) -> None:
    path = tmp_path / "control_experience.json"
    key = control_key("POPUP", "BTN_CLOSE", "POPUP|EXIT_CONFIRM")
    entry = ControlExperience(page="POPUP", control="BTN_CLOSE", position_norm=(0.8819, 0.3563),
                              screen="POPUP|EXIT_CONFIRM", read_from_frame="frame_b.png")
    save({key: entry}, path)
    assert load(path)[key].screen == "POPUP|EXIT_CONFIRM"
    assert load(path)[key].position_norm == (0.8819, 0.3563)
