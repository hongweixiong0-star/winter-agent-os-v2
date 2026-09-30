import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from winter_agent_v2.models import Page, VerificationResult, WorldState
from winter_agent_v2.session_engine import STEP_SKILL, SessionStep
from winter_agent_v2.session_host import LiveRuntimeSessionHost


def test_giant_search_session_reaches_existing_retry_bridge_without_name_error():
    before = WorldState(page=Page.MAP, resource_selected_tab='GIANT_BEAST')
    after = WorldState(page=Page.BEAST, beast_search_result={'has_rally': True})
    execution = SimpleNamespace(executed=True, backend='MAA', tap_point=None, error=None)
    proof = VerificationResult(True, 'POLAR_SEARCH_RESULT')
    runtime = SimpleNamespace(_session_execute_atomic=Mock(return_value=execution),
        _retry_semantic_click=Mock(return_value=(after, Path('fresh.png'), execution, proof, {})))
    host = object.__new__(LiveRuntimeSessionHost)
    host.runtime = runtime
    host.binding = SimpleNamespace(planned_resource=None, rally_target='POLAR_TERROR',
                                   index=1, settle_seconds=0, latency={})
    host._world_for_step = Mock(return_value=(before, Path('before.png')))
    host._last_world_path = Path('after.png')
    host.sleep = Mock()
    host.observe = Mock(return_value=after)
    result = host._run_skill(SessionStep(0, STEP_SKILL, skill_id='SUBMIT_GIANT_BEAST_SEARCH'), time.monotonic())
    assert result.executed
    assert host._verification is proof
    assert runtime._retry_semantic_click.call_args.kwargs['decision'].skill == 'SUBMIT_GIANT_BEAST_SEARCH'
