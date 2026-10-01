import hashlib
import json
from types import SimpleNamespace

from winter_agent_v2 import ui_planner, ui_venus_online, unknown_advisor


class Client:
    def __init__(self, *, error="", replace_frame=False):
        self.calls = 0
        self.error = error
        self.replace_frame = replace_frame

    def ask_json(self, **kwargs):
        self.calls += 1
        if self.replace_frame:
            from pathlib import Path
            Path(kwargs["image_path"]).write_bytes(b"changed during inference")
        return SimpleNamespace(
            ok=not self.error, error=self.error, latency_ms=25.0, prompt_tokens=120,
            text=json.dumps({
                "goal": "MARKSMAN_CAMP_TRAINING", "decision": "EXECUTE",
                "action": {"type": "OPEN_PAGE", "target_element_id": "E1"},
                "expected": {"page": "HOME", "result": "camp_action_bar_opened"},
                "reason": "Open selected camp",
            }))


def setup(tmp_path, **client_options):
    frame = tmp_path / "current.png"
    frame.write_bytes(b"fresh captured frame")
    request = unknown_advisor.build_request(
        unknown_type=unknown_advisor.UNKNOWN_CONTROL,
        page_label="HOME", page_key="HOME", frame_path=frame,
        goal="MARKSMAN_CAMP_TRAINING", character="ROLE_A",
        ocr_texts=("射手营",), ocr_boxes=({"text": "射手营"},))
    request.trace_id = "unknown_parent"
    request.parent_trace_id = "session_parent"
    request.semantic_target = "OPEN_MARKSMAN_CAMP"
    request.relevant_state_signature = "focused:MARKSMAN"
    request.role_session_id = "role_session_A"
    request.episode_id = "episode_1"
    request.frame_id = "capture_1"
    client = Client(**client_options)
    advisor = ui_planner.ManagedAdvisor(
        client=client, ledger=ui_planner.PlannerLedger(tmp_path / "plans.jsonl"),
        root=tmp_path, max_steps_per_screen=2)
    return advisor, client, request


def rows(tmp_path):
    return [json.loads(line) for line in
            (tmp_path / ui_venus_online.ONLINE_LEDGER_PATH).read_text(encoding="utf-8").splitlines()]


def test_unknown_on_known_home_joins_real_call_contract_and_verifier(tmp_path):
    advisor, client, request = setup(tmp_path)
    advice = advisor.take_request(request)
    assert advice is not None
    advisor.note_outcome(request.request_id, verifier_ok=True,
                         skill="OPEN_MARKSMAN_CAMP", result="SUCCESS",
                         evidence={"action_bar_open": True})
    trace_rows = [row for row in rows(tmp_path) if row.get("record") == "learning_trace"]
    assert [row["stage"] for row in trace_rows] == [
        "UNKNOWN_OBSERVED", "VENUS_CALLED", "VENUS_PROPOSED",
        "CONTRACT_ALLOWED", "VERIFIER_SUCCESS"]
    assert client.calls == 1
    assert len({row["call_id"] for row in trace_rows}) == 1
    for row in trace_rows:
        assert row["mode"] == "ONLINE_UNKNOWN"
        assert row["trace_id"] == "unknown_parent"
        assert row["parent_trace_id"] == "session_parent"
        assert row["role_id"] == "ROLE_A"
        assert row["role_session_id"] == "role_session_A"
        assert row["goal_id"] == "MARKSMAN_CAMP_TRAINING"
        assert row["page"] == "HOME"
        assert row["episode_id"] == "episode_1"
        assert row["frame_id"] == "capture_1"
        assert row["frame_hash"] == "sha256:" + hashlib.sha256(b"fresh captured frame").hexdigest()
        assert row["unknown_identity"] == ui_venus_online.unknown_state_identity(
            goal_id=request.goal, page="HOME", semantic=request.semantic_target,
            state_signature=request.relevant_state_signature)
        assert row["recorded_at"]
    assert trace_rows[-1]["verifier_evidence"] == {"action_bar_open": True}
    assert not any(row.get("stage") == "MAA_EXECUTED" for row in trace_rows)


def test_retry_calls_have_unique_ids_but_one_unknown_and_screen_budget_stays_two(tmp_path):
    advisor, client, request = setup(tmp_path)
    assert advisor.take_request(request) is not None
    advisor.note_outcome(request.request_id, verifier_ok=False, result="NO_CHANGE")
    assert advisor.take_request(request) is not None
    latest_call_id = advisor.last_outcome["call_id"]
    advisor.note_outcome(request.request_id, verifier_ok=True, result="SUCCESS")
    assert advisor.take_request(request) is None
    trace_rows = rows(tmp_path)
    calls = [row for row in trace_rows if row.get("stage") == "VENUS_CALLED"]
    assert client.calls == len(calls) == 2
    assert len({row["call_id"] for row in calls}) == 2
    assert len([row for row in trace_rows if row.get("stage") == "UNKNOWN_OBSERVED"]) == 1
    successes = [row for row in trace_rows if row.get("stage") == "VERIFIER_SUCCESS"]
    assert successes[0]["call_id"] == latest_call_id
    assert advisor.last_outcome["error"] == "PLANNER_SCREEN_BUDGET_SPENT"


def test_server_failure_records_attempt_without_inventing_proposal(tmp_path):
    advisor, client, request = setup(tmp_path, error="SERVER_UNAVAILABLE")
    assert advisor.take_request(request) is None
    trace_rows = rows(tmp_path)
    assert client.calls == 1
    assert [row["stage"] for row in trace_rows] == [
        "UNKNOWN_OBSERVED", "VENUS_CALLED", "VENUS_CALL_FAILED"]
    assert trace_rows[-1]["error"] == "SERVER_UNAVAILABLE"


def test_stale_frame_rejection_stays_on_the_same_trace(tmp_path):
    advisor, client, request = setup(tmp_path, replace_frame=True)
    assert advisor.take_request(request) is None
    refused = [row for row in rows(tmp_path) if row.get("stage") == "CONTRACT_REJECTED"]
    assert len(refused) == 1
    assert refused[0]["trace_id"] == "unknown_parent"
    assert refused[0]["verdict"]["code"] == "CONTEXT_FRAME_MISMATCH"
    assert not any(row.get("stage") == "VERIFIER_SUCCESS" for row in rows(tmp_path))
