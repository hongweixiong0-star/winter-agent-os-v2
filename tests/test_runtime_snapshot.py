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
