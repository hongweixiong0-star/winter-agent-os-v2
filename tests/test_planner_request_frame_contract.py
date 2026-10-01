from winter_agent_v2 import unknown_advisor, ui_planner


def gate(tmp_path, *, changed=False):
    frame = tmp_path / 'current.png'
    frame.write_bytes(b'actual request frame bytes')
    request = unknown_advisor.build_request(
        unknown_type=unknown_advisor.UNKNOWN_CONTROL,
        page_label='EVENT', page_key='EVENT::reward', frame_path=frame,
        goal='DAILY_ROUTINE', character='TEST_ROLE')
    if changed:
        frame.write_bytes(b'new screenshot in the same path')
    planner = object.__new__(ui_planner.ManagedAdvisor)
    planner.root = tmp_path
    planner.steps = 1
    verdict = planner._contract_gate(
        plan=ui_planner.Plan(decision='EXECUTE', action_type='CLICK_ELEMENT',
                             target_element_id='E1', reason='Open reward'),
        question=request, elements=[{'id':'E1', 'kind':'INTERACTIVE_CONTROL',
                                    'executable':True, 'text':'Reward'}],
        frame_path=str(frame), page_key=request.page_key,
        request_id=request.request_id, raw='')
    return verdict


def test_real_unknown_request_short_hash_accepts_unchanged_frame(tmp_path):
    assert gate(tmp_path).ok


def test_real_unknown_request_rejects_replaced_frame_at_same_path(tmp_path):
    verdict = gate(tmp_path, changed=True)
    assert not verdict.ok
    assert verdict.code == 'CONTEXT_FRAME_MISMATCH'
