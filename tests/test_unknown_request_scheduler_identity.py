from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.runtime import LiveRuntime


def test_unknown_request_uses_selected_goal_and_confirmed_role(tmp_path):
    runtime = object.__new__(LiveRuntime)
    runtime.brain = SimpleNamespace(current_goal='DAILY', goal_id='OLD_GOAL')
    runtime._committed_goal = 'CLAIM_CURRENT_EVENT_REWARD'
    runtime.role_id = 'ROLE_B_LIVE_ID'
    runtime.role_scope = 'LIVE_OBSERVED'
    runtime._multi_role_enabled = True
    runtime._role_identity_confirmed = True
    runtime._advisor = Mock()
    runtime._advisor.take_request.return_value = None
    runtime._learned_reuse_point = Mock(return_value=None)
    runtime._learned_ledger_rows = Mock(return_value=[])
    runtime._l1_state = Mock(return_value='current-state')
    runtime._ocr_service = Mock(return_value=None)
    runtime._advice_evidence = Mock(return_value=([], [], [], ''))
    frame = tmp_path / 'fresh.png'
    frame.write_bytes(b'fresh frame')
    runtime._advised_control('UNKNOWN', 'Reward', frame, WorldState(page=Page.UNKNOWN), True)
    request = runtime._advisor.take_request.call_args.args[0]
    assert request.goal == 'CLAIM_CURRENT_EVENT_REWARD'
    assert request.character == 'ROLE_B_LIVE_ID'
    assert runtime._learned_reuse_point.call_args.args[2] == request.goal

    runtime._role_identity_confirmed = False
    runtime._advised_control('UNKNOWN', 'Reward', frame, WorldState(page=Page.UNKNOWN), True)
    assert runtime._advisor.take_request.call_args.args[0].character == ''
