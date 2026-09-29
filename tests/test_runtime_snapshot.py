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
