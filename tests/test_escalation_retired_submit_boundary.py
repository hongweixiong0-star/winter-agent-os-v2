import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from winter_agent_v2 import escalation_queue as queue
from winter_agent_v2.workbuddy_bridge import JobStatus


def _adapter(tmp_path, monkeypatch, flags=None):
    path = tmp_path / "config/v2.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"workbuddy_channel": flags or {
        "enabled": False, "auto_submit_jobs": False, "auto_escalate": False,
    }}), encoding="utf-8")
    bridge = Mock()
    bridge.is_available.return_value = True
    bridge.submit.return_value = SimpleNamespace(job_id="new-job")
    ledger = queue.EscalationLedger(tmp_path / queue.DEFAULT_LEDGER)
    adapter = queue.EscalationQueueAdapter(root=tmp_path, ledger=ledger, bridge=bridge)
    adapter._build_request = Mock(return_value=SimpleNamespace())
    adapter._wiring_problems = lambda: 0
    monkeypatch.setattr(queue, "repo_revision", lambda _: queue.RepoRevision("same-head", 0, True))
    return adapter, bridge, path


def _candidate():
    return queue.EscalationCandidate(
        signature=queue.FailureSignature("CAMP", "SEMANTIC_TARGET_NOT_VERIFIED", "OPEN_CAMP"),
        condition=queue.UNKNOWN_UI, reason="real UI target was not proven",
    )


@pytest.mark.parametrize("origin", ["queue", "bootstrap", "bootstrap_seed"])
def test_all_automatic_producers_stop_at_the_common_submit_boundary(tmp_path, monkeypatch, origin):
    adapter, bridge, _ = _adapter(tmp_path, monkeypatch)
    candidate = _candidate()
    assert adapter._submit(candidate, queue.Dispatch(queue.SUBMIT, "allowed by legacy throttle"), origin=origin) == ""
    bridge.is_available.assert_not_called()
    bridge.submit.assert_not_called()
    adapter._build_request.assert_not_called()
    events = adapter.ledger.events()
    assert len(events) == 1
    assert events[0]["dispatch"] == queue.NOT_ESCALATABLE
    assert "workbuddy_channel.enabled=false" in events[0]["dispatch_reason"]
    assert adapter.ledger.snapshot().active_jobs() == ()


@pytest.mark.parametrize("disabled", ["enabled", "auto_submit_jobs", "auto_escalate"])
def test_any_existing_retirement_flag_prevents_automatic_submission(tmp_path, monkeypatch, disabled):
    flags = {"enabled": True, "auto_submit_jobs": True, "auto_escalate": True, disabled: False}
    adapter, bridge, _ = _adapter(tmp_path, monkeypatch, flags)
    assert adapter._submit(_candidate(), queue.Dispatch(queue.SUBMIT, "throttle allowed")) == ""
    assert disabled in adapter._last_submission_block_reason
    bridge.submit.assert_not_called()


def test_pending_pump_does_not_reopen_retired_channel_or_report_gateway_outage(tmp_path, monkeypatch):
    adapter, bridge, _ = _adapter(tmp_path, monkeypatch)
    candidate = _candidate()
    adapter._record(candidate, queue.Dispatch(queue.SUBMIT, "historical pending record"))
    observation = adapter.pump()
    assert not observation.submitted
    assert any("WORKBUDDY_AUTO_SUBMISSION_DISABLED" in why for _, why in observation.skipped)
    bridge.submit.assert_not_called()
    assert not any(event["event"] == "queued" for event in adapter.ledger.events())


def test_existing_job_can_still_settle_while_new_submissions_are_retired(tmp_path, monkeypatch):
    adapter, bridge, _ = _adapter(tmp_path, monkeypatch)
    candidate = _candidate()
    adapter._record(candidate, queue.Dispatch(queue.SUBMIT, "historical existing job"))
    adapter.ledger.append({
        "event": "submitted", "key": candidate.signature.key, "job_id": "existing-job",
        "repo_head": "same-head", "repo_dirty": 0,
    })
    bridge.status.return_value = JobStatus(
        job_id="existing-job", gateway_state="stopped", verdict=queue.STOPPED,
        detail="cancelled existing job", settled=True, alive=False,
    )
    _, errors = adapter.reconcile()
    assert errors == []
    bridge.status.assert_called_once_with("existing-job")
    bridge.submit.assert_not_called()
    assert adapter.ledger.snapshot().active_jobs() == ()
    assert any(event["event"] == "reconciled" for event in adapter.ledger.events())


def test_running_adapter_rereads_retirement_before_each_submission(tmp_path, monkeypatch):
    adapter, bridge, path = _adapter(tmp_path, monkeypatch, {
        "enabled": True, "auto_submit_jobs": True, "auto_escalate": True,
    })
    assert adapter._submit(_candidate(), queue.Dispatch(queue.SUBMIT, "legacy enabled")) == "new-job"
    path.write_text(json.dumps({"workbuddy_channel": {"enabled": False}}), encoding="utf-8")
    assert adapter._submit(_candidate(), queue.Dispatch(queue.SUBMIT, "stale decision")) == ""
    assert bridge.submit.call_count == 1


def test_unreadable_present_config_cannot_authorize_a_new_job(tmp_path, monkeypatch):
    adapter, bridge, path = _adapter(tmp_path, monkeypatch)
    path.write_text("{not-json", encoding="utf-8")
    assert adapter._submit(_candidate(), queue.Dispatch(queue.SUBMIT, "legacy allowed")) == ""
    assert "unreadable" in adapter._last_submission_block_reason
    bridge.submit.assert_not_called()
