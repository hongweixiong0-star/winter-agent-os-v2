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

def test_a_generated_write_does_not_overwrite_a_hand_set_recognition_declaration(tmp_path):
    """``preferred`` is setdefault-preserved; the declaration beside it must be too.

    `recognition_backend` says which recogniser the skill's route actually uses -- MAA, LEGACY
    (the V2 semantic vision) or NONE.  A skill demoted to ADB because its node never answered
    (measured 2026-10-02: OPEN_BUILDING_UPGRADE, 10 attempts, 0 successes) declares LEGACY.  If a
    later generated write forces it back to MAA, the file claims a recognition path the router
    cannot reach: with ``preferred: ADB`` the MAA resolver is never asked.  The two lines above use
    ``setdefault`` for exactly this reason, and this one has to agree with them.
    """
    path = tmp_path / 'backend_routing.json'
    existing = {'kind': 'TEMPLATE', 'template': 'unusable'}
    payload = {'version': 1, 'skills': {'SKILL_X': {
        'preferred': 'ADB', 'fallback': 'MAA', 'recognition_backend': 'LEGACY',
        'recognition': {'BTN_X': dict(existing)},
        'promoted': False, 'migration_priority': 'P3',
        # Autogen-owned, which is what makes a later write allowed rather than protected: an
        # entry whose node nobody claims is treated as a manual asset and refused outright.
        'evidence': {'operator': 'demoted',
                     'autogen_owned_recognition': {'BTN_X': dict(existing)}}}}}
    path.write_text(json.dumps(payload), encoding='utf-8')
    generator = PipelineAutoGen(project_root=tmp_path, routing_path=path)
    ok, reason = generator.wire(node('repaired'))
    assert ok is True, reason
    route = json.loads(path.read_text(encoding='utf-8'))['skills']['SKILL_X']
    assert route['preferred'] == 'ADB'
    assert route['recognition_backend'] == 'LEGACY', (
        'the declaration follows the route; claiming MAA here would name a resolver that cannot run')


def test_the_declaration_follows_the_route_when_the_route_is_maa(tmp_path):
    """The other side of the same rule, so this is a rule and not a special case.

    A skill created by a generated write prefers MAA and must therefore declare MAA -- the node
    that was just wired is the one the router will call.
    """
    path = tmp_path / 'backend_routing.json'
    generator = PipelineAutoGen(project_root=tmp_path, routing_path=path)
    assert generator.wire(node('first')) == (True, 'CREATED')
    route = json.loads(path.read_text(encoding='utf-8'))['skills']['SKILL_X']
    assert route['preferred'] == 'MAA'
    assert route['recognition_backend'] == 'MAA'
