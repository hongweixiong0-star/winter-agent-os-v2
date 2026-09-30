import json

from winter_agent_v2.pipeline_autogen import GeneratedNode, PipelineAutoGen


def node(template):
    return GeneratedNode(semantic='BTN_X', skill_id='SKILL_X', kind='TEMPLATE',
        routing_node={'kind': 'TEMPLATE', 'template': template},
        pipeline_node={'recognition': 'TemplateMatch', 'template': template})


def test_autogen_preserves_manual_route_and_saves_conflicting_candidate(tmp_path):
    path = tmp_path / 'backend_routing.json'
    payload = {'version': 1, 'skills': {'SKILL_X': {'preferred': 'MAA',
        'recognition': {'BTN_X': {'kind': 'TEMPLATE', 'template': 'manual'}},
        'promoted': True, 'evidence': {'operator': 'verified manually'}}}}
    path.write_text(json.dumps(payload), encoding='utf-8')
    original = path.read_bytes()
    generated = node('new-candidate')
    ok, reason = PipelineAutoGen(project_root=tmp_path, routing_path=path).wire(generated)
    assert not ok and reason.startswith('PROTECTED_RECOGNITION_CONFLICT:')
    assert path.read_bytes() == original
    assert (tmp_path / generated.evidence['pipeline_node_path']).exists()


def test_unpromoted_generated_route_can_still_be_repaired(tmp_path):
    path = tmp_path / 'backend_routing.json'
    generator = PipelineAutoGen(project_root=tmp_path, routing_path=path)
    assert generator.wire(node('first')) == (True, 'CREATED')
    assert generator.wire(node('repaired')) == (True, 'OVERWROTE')
    route = json.loads(path.read_text(encoding='utf-8'))['skills']['SKILL_X']
    assert route['recognition']['BTN_X']['template'] == 'repaired'


def test_manual_candidate_and_promoted_autogen_are_both_protected(tmp_path):
    path = tmp_path / 'backend_routing.json'
    generator = PipelineAutoGen(project_root=tmp_path, routing_path=path)
    generator.wire(node('first'))
    payload = json.loads(path.read_text(encoding='utf-8'))
    payload['skills']['SKILL_X']['promoted'] = True
    path.write_text(json.dumps(payload), encoding='utf-8')
    assert generator.wire(node('new'))[0] is False
    payload['skills']['SKILL_X']['promoted'] = False
    payload['skills']['SKILL_X']['recognition']['BTN_X']['template'] = 'manual-edit'
    path.write_text(json.dumps(payload), encoding='utf-8')
    assert generator.wire(node('another'))[0] is False
