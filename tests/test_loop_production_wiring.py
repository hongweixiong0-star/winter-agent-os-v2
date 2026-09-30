from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock
import json

from winter_agent_v2.ocr import HybridVision
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.session_engine import SessionEngine


def test_hybrid_forwards_loop_widen_to_actual_template_reader():
    templates = SimpleNamespace(focus=Mock(), sweeps_skipped=lambda: {"MAP": "focus"})
    vision = HybridVision(templates, Mock())
    vision.focus(goal="TRAIN", page_hint="HOME", widen=True, reason="loop")
    templates.focus.assert_called_once_with(goal="TRAIN", page_hint="HOME", widen=True, reason="loop")
    assert vision.sweeps_skipped() == {"MAP": "focus"}


def test_feature_reopen_requires_adapter_to_confirm_recovery():
    adapter = SimpleNamespace(recover=Mock(return_value=None))
    engine = SessionEngine()
    assert not engine._apply_loop_rung(None, None, adapter, None, None, None,
                                      SimpleNamespace(rung="feature_reopen", reason="AAA", pattern="AAA"))
    adapter.recover.return_value = True
    assert engine._apply_loop_rung(None, None, adapter, None, None, None,
                                  SimpleNamespace(rung="feature_reopen", reason="AAA", pattern="AAA"))


def test_timeline_retains_revision_role_and_metrics_next_to_run_frames():
    with TemporaryDirectory() as folder:
        runtime = SimpleNamespace(capture_dir=Path(folder), role_id="B", code_revision="test")
        LiveRuntime._record_session_timeline(runtime, "SESSION_ENDED", goal_id="TRAIN",
                                             metrics={"LOOP_DETECTED": 1})
        row = json.loads((Path(folder) / "session_timeline.jsonl").read_text(encoding="utf-8"))
        assert row["role_id"] == "B"
        assert row["repo_revision"] == "test"
        assert row["metrics"]["LOOP_DETECTED"] == 1
