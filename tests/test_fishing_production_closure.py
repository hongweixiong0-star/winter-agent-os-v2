from types import SimpleNamespace
from pathlib import Path

from winter_agent_v2.fishing_state import FishingState
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.session_adapters import FishingSessionAdapter, STAGE_LEAVING
from winter_agent_v2.session_engine import SessionStep, StepExecution, StepOutcome, STEP_OBSERVE_ONLY
from winter_agent_v2.session_host import LiveRuntimeSessionHost, SessionRunBinding


def test_servo_and_bait_cost_without_points_never_prove_a_cast():
    adapter = FishingSessionAdapter()
    adapter.started = True
    adapter.result_seen = True
    adapter.bait_before, adapter.bait_after = 1, 0
    adapter.points_before = 2990
    adapter.servo_report = {"moves_sent": 120}
    adapter.stage = STAGE_LEAVING
    host = SimpleNamespace(note=lambda *args, **kwargs: None)
    done, _ = adapter.is_complete(None, host, SimpleNamespace(on_home=True, bait=0))
    assert not done
    verdict = adapter.verify_step(None, host,
        SessionStep(0, STEP_OBSERVE_ONLY, tags={"verify_cast": True}), StepExecution(False, "OBSERVE"))
    assert verdict.outcome == StepOutcome.FAILED
    assert verdict.reason == "INCOMPLETE"
    assert not adapter.cast_verified


def test_zero_score_is_failure_even_when_every_ui_signal_is_present():
    adapter = FishingSessionAdapter()
    adapter.started = adapter.result_seen = True
    adapter.bait_before, adapter.bait_after = 2, 1
    adapter.points_before = adapter.points_after = 2990
    adapter.servo_report = {"moves_sent": 100}
    verdict = adapter.verify_step(None, SimpleNamespace(note=lambda *args, **kwargs: None),
        SessionStep(0, STEP_OBSERVE_ONLY, tags={"verify_cast": True}), StepExecution(False, "OBSERVE"))
    assert verdict.reason == "ZERO_SCORE_RUN"
    assert verdict.outcome == StepOutcome.FAILED


def test_current_role_ledger_does_not_double_subtract_observed_bait(tmp_path):
    path = tmp_path / "learning/fishing_state.json"
    ledger = path.parent / "fishing_runs.jsonl"
    store = FishingState.load(path, ledger)
    store.observe("ROLE_A", role_id="A", bait_current=7, points_total=190)
    store.observe("ROLE_B", role_id="B", bait_current=2, points_total=2990)
    store.save()
    runtime = SimpleNamespace(episode_store=SimpleNamespace(path=path.parent / "episodes.jsonl"),
                              capture_dir=tmp_path / "actual_run")
    host = LiveRuntimeSessionHost(runtime, SessionRunBinding(
        1, "USE_NORMAL_FISHING_BAIT", "B", WorldState(page=Page.EVENT), Path("before.png")))
    # The after-frame observation may arrive before the cast's ledger row.
    host.note("fishing_observation", bait_current=1, bait_cap=10, points_total=3140,
              event_live_open=True, remaining_seconds=3600)
    host.note("fishing_run", bait_before=2, bait_after=1, points_before=2990, points_after=3140,
              servo={"duration_s": 50, "control_hz": 20}, verifier={"status": "COMPLETE"})
    updated = FishingState.load(path, ledger)
    assert updated.role("ROLE_B").normal_bait_current == 1
    assert updated.role("ROLE_B").points_total == 3140
    assert updated.role("ROLE_A").normal_bait_current == 7
    assert updated.role("ROLE_A").points_total == 190
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1

