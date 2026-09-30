from pathlib import Path

from winter_agent_v2.runtime_snapshot import (
    AgentState, RuntimeSnapshotStore, StopCategory, is_fatal_stop, state_for_stop_reason,
)


def test_running_state_cannot_survive_dead_runtime(tmp_path: Path) -> None:
    store = RuntimeSnapshotStore(tmp_path / "runtime.json")
    snapshot = store.update(agent_state=AgentState.AUTO_RUNNING.value,
                            runtime_thread_alive=False, scheduler_loop_alive=False)
    assert snapshot.agent_state == AgentState.DEGRADED.value


def test_safe_stop_and_auto_running_are_mutually_exclusive(tmp_path: Path) -> None:
    store = RuntimeSnapshotStore(tmp_path / "runtime.json")
    snapshot = store.update(agent_state=AgentState.SAFE_STOP.value,
                            runtime_thread_alive=False, scheduler_loop_alive=False)
    assert snapshot.agent_state == AgentState.SAFE_STOP.value
    assert not snapshot.runtime_thread_alive


def test_recovering_allows_runtime_bootstrap_before_scheduler(tmp_path: Path) -> None:
    store = RuntimeSnapshotStore(tmp_path / "runtime.json")
    snapshot = store.update(agent_state=AgentState.RECOVERING.value,
                            runtime_thread_alive=True, scheduler_loop_alive=False)
    assert snapshot.agent_state == AgentState.RECOVERING.value


def test_ordinary_goal_failures_are_not_fatal() -> None:
    for reason in ("NOT_PROVEN", "NOT_VERIFIED", "SEMANTIC_NOT_FOUND", "QUEUE_FULL",
                   "NO_ATTEMPT", "RALLY_FULL", "EVENT_CLOSED", "unknown_page"):
        assert not is_fatal_stop(reason)
    assert is_fatal_stop("FATAL_DEVICE_CORRUPTION")


def test_fruitless_no_action_is_idle_and_not_degraded() -> None:
    category, state = state_for_stop_reason(
        "every_page_this_run_was_fruitless", decision_skill="SAFE_STOP"
    )
    assert category is StopCategory.EXPECTED_NO_ACTION
    assert state is AgentState.IDLE


def test_unmapped_safe_stop_is_a_capability_gap_not_system_failure() -> None:
    category, state = state_for_stop_reason("new_unmapped_reason", decision_skill="SAFE_STOP")
    assert category is StopCategory.CAPABILITY_GAP
    assert state is AgentState.SAFE_STOP


def test_a_role_re_observation_request_is_not_a_system_failure() -> None:
    """TASK THROUGHPUT V1 §24: an unclassified stop reason stopped AUTO and idled the device.

    Measured on pin 7055f02, 2026-09-30.  A run ended with
    ``ACTIVE_ROLE_NO_CANDIDATE_REOBSERVE`` after three successful actions
    (OPEN_MAIL / MAIL_CLAIM_REWARDS / DISMISS_SHARED_REWARD).  The reason was not in any of
    the recognised sets, so ``classify_stop_reason`` fell through to SYSTEM_FAILURE, the
    panel's ``healthy`` became false, ``should_continue_auto_cycle`` returned False, and AUTO
    stopped -- the device then sat idle while the account still had runnable Goals.
    """
    category, state = state_for_stop_reason(
        "ACTIVE_ROLE_NO_CANDIDATE_REOBSERVE", decision_skill="GLOBAL_SCHEDULER"
    )
    assert category is StopCategory.CAPABILITY_GAP
    assert state is AgentState.SAFE_STOP
    assert not is_fatal_stop("ACTIVE_ROLE_NO_CANDIDATE_REOBSERVE")


def test_every_keep_current_reason_survives_the_classifier() -> None:
    """The runtime's no-switch verdicts must never read as an unhealthy stop.

    ``ROLE_REFRESH_ONLY_REASONS`` is the set the runtime uses to mean "do not switch; look at
    the same account again".  A member the classifier does not recognise falls through to
    SYSTEM_FAILURE, which stops the whole AUTO cycle -- so adding a new member to that set
    without registering it here is a production outage, not a cosmetic omission.  This is the
    guard for that pair.
    """
    from winter_agent_v2.runtime import ROLE_REFRESH_ONLY_REASONS

    assert ROLE_REFRESH_ONLY_REASONS, "the no-switch reason set must not be empty"
    for reason in sorted(ROLE_REFRESH_ONLY_REASONS):
        category, _state = state_for_stop_reason(reason, decision_skill="GLOBAL_SCHEDULER")
        assert category is not StopCategory.SYSTEM_FAILURE, (
            f"{reason} classifies as {category.value}, which stops AUTO"
        )


def test_a_role_re_observation_request_is_not_a_system_failure() -> None:
    """TASK THROUGHPUT V1 §24: an unclassified stop reason stopped AUTO and idled the device.

    Measured on pin 7055f02, 2026-09-30.  A run ended with
    ``ACTIVE_ROLE_NO_CANDIDATE_REOBSERVE`` after three successful actions
    (OPEN_MAIL / MAIL_CLAIM_REWARDS / DISMISS_SHARED_REWARD).  The reason was not in any of
    the recognised sets, so ``classify_stop_reason`` fell through to SYSTEM_FAILURE, the
    panel's ``healthy`` became false, ``should_continue_auto_cycle`` returned False, and AUTO
    stopped -- the device then sat idle while the account still had runnable Goals.
    """
    category, state = state_for_stop_reason(
        "ACTIVE_ROLE_NO_CANDIDATE_REOBSERVE", decision_skill="GLOBAL_SCHEDULER"
    )
    assert category is StopCategory.CAPABILITY_GAP
    assert state is AgentState.SAFE_STOP
    assert not is_fatal_stop("ACTIVE_ROLE_NO_CANDIDATE_REOBSERVE")


def test_every_keep_current_reason_survives_the_classifier() -> None:
    """The runtime's no-switch verdicts must never read as an unhealthy stop.

    ``ROLE_REFRESH_ONLY_REASONS`` is the set the runtime uses to mean "do not switch; look at
    the same account again".  A member the classifier does not recognise falls through to
    SYSTEM_FAILURE, which stops the whole AUTO cycle -- so adding a new member to that set
    without registering it here is a production outage, not a cosmetic omission.  This is the
    guard for that pair.
    """
    from winter_agent_v2.runtime import ROLE_REFRESH_ONLY_REASONS

    assert ROLE_REFRESH_ONLY_REASONS, "the no-switch reason set must not be empty"
    for reason in sorted(ROLE_REFRESH_ONLY_REASONS):
        category, _state = state_for_stop_reason(reason, decision_skill="GLOBAL_SCHEDULER")
        assert category is not StopCategory.SYSTEM_FAILURE, (
            f"{reason} classifies as {category.value}, which stops AUTO"
        )


# ---------------------------------------------------------------------------------------------
# The action budget ends a round; a verifier miss inside it does not.
#
# Measured 2026-09-30 11:21 local (pin b2cb6f1).  Round ``20260930_111430_903715`` issued 24
# actions, 23 of them verified, with one BEAST_SEARCH_TAB miss at step 005; it then worked for
# nineteen more steps and ended MAX_ACTIONS_REACHED.  The blanket ``verifier_failed``
# short-circuit fired first, so the snapshot recorded ``stop_category=SYSTEM_FAILURE`` /
# ``agent_state=DEGRADED``; the panel's ``healthy`` went false, ``should_continue_auto_cycle``
# declined, and AUTO stopped with the device idle -- and the panel logged no reason at all.
# ---------------------------------------------------------------------------------------------


def test_a_budget_bounded_round_is_not_relabelled_by_one_verifier_miss() -> None:
    category, state = state_for_stop_reason(
        "MAX_ACTIONS_REACHED", decision_skill="OPEN_MAP",
        action_executed=True, verifier_failed=True,
    )
    assert category is StopCategory.COMPLETED
    assert state is AgentState.IDLE
    assert is_fatal_stop("MAX_ACTIONS_REACHED") is False


def test_the_budget_exemption_does_not_cover_every_completed_stop() -> None:
    """``TARGET_SKILL_VERIFIED`` is deliberately not exempted.

    It is reached by a verification *succeeding*, so a verifier miss in the same round is the
    closest case to the failure and this measurement does not cover it.
    """
    category, _state = state_for_stop_reason(
        "TARGET_SKILL_VERIFIED", decision_skill="CLEAR_INTEL",
        action_executed=True, verifier_failed=True,
    )
    assert category is StopCategory.SYSTEM_FAILURE


def test_a_fatal_reason_still_outranks_the_budget_exemption() -> None:
    category, _state = state_for_stop_reason("FATAL_DEVICE_CORRUPTION", action_executed=True)
    assert category is StopCategory.SYSTEM_FAILURE


def test_the_measured_round_shape_now_continues_the_cycle() -> None:
    """End to end through the panel's own summary: one miss must not idle the device."""
    from tools.control_panel import should_continue_auto_cycle, summarize_runtime_result

    ok = {"execution": {"executed": True}, "verification": {"ok": True}}
    miss = {"execution": {"executed": True}, "verification": {"ok": False}}
    summary = summarize_runtime_result(
        {"steps": [ok] * 23 + [miss], "stop_reason": "MAX_ACTIONS_REACHED"}, 0
    )
    assert summary["failures"] == 1, "the miss must stay visible in the summary"
    assert summary["healthy"] is True
    assert should_continue_auto_cycle(
        healthy=summary["healthy"], reason=summary["reason"],
        continuous=True, stop_requested=False, paused=False, fatal=False,
    ) is True


def test_safe_development_handoff_is_not_a_worker_failure() -> None:
    from tools.control_panel import should_continue_auto_cycle, summarize_runtime_result
    from winter_agent_v2.runtime_snapshot import classify_stop_reason
    summary = summarize_runtime_result(
        {"steps": [], "stop_reason": "device_leased_for_development"}, 0)
    assert summary["healthy"] is True
    assert classify_stop_reason("device_leased_for_development") is StopCategory.EXPECTED_NO_ACTION
    assert should_continue_auto_cycle(
        healthy=summary["healthy"], reason=summary["reason"], continuous=True,
        stop_requested=False, paused=False, fatal=False)
