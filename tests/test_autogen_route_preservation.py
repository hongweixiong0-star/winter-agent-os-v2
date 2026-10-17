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

    2026-10-17: this payload is the illegal pair itself -- LEGACY *carrying* a node.  It was
    tolerated when this test was written (the write repaired the node and left the declaration
    alone); measured 2026-10-16 the live file reached exactly this shape and
    ``test_recognition_backend_declaration`` failed on it.  The writer now refuses, which keeps
    both halves of the promise: the declaration survives *and* the file cannot end up
    self-contradicting.  Lifting LEGACY is a curator edit, then the same write goes through.
    """
    path = tmp_path / 'backend_routing.json'
    existing = {'kind': 'TEMPLATE', 'template': 'unusable'}
    payload = {'version': 1, 'skills': {'SKILL_X': {
        'preferred': 'ADB', 'fallback': 'MAA', 'recognition_backend': 'LEGACY',
        'recognition': {'BTN_X': dict(existing)},
        'promoted': False, 'migration_priority': 'P3',
        # Autogen-owned, so the write is not refused as a manual-asset conflict; the refusal
        # below is the LEGACY rule, not the protection rule.
        'evidence': {'operator': 'demoted',
                     'autogen_owned_recognition': {'BTN_X': dict(existing)}}}}}
    path.write_text(json.dumps(payload), encoding='utf-8')
    original = path.read_bytes()
    generator = PipelineAutoGen(project_root=tmp_path, routing_path=path)
    ok, reason = generator.wire(node('repaired'))
    assert ok is False and reason.startswith('LEGACY_DECLARATION_TAKES_NO_NODE'), reason
    assert path.read_bytes() == original, 'the declaration and the node are both left as they were'


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


def _demoted_payload():
    """The measured demoted shape, as every retirement so far has left it.

    ``recognition`` emptied, the route on ADB, the declaration LEGACY, and the demotion's own
    record kept in ``evidence`` where the retirement scripts leave it.  Measured 2026-10-10:
    against exactly this shape the runtime hook's regeneration trigger ("runtime unresolved
    after N attempt(s)") re-wired QUICK_PANEL_ROW_BUILDING and REGULAR_EVENT_ENTRY (x2) --
    three entries -- putting back the node the A/B had retired.
    """
    return {'version': 1, 'skills': {'SKILL_X': {
        'preferred': 'ADB', 'fallback': 'ADB', 'recognition_backend': 'LEGACY',
        'promoted': False, 'migration_priority': 'P3',
        'evidence': {
            'demoted_at': '2026-10-05T08:59:25Z',
            'demotion_reason': 'The autogen node for BTN_X is position-blind for a control '
                               'that moves: it carries a fixed roi while the panel draws the '
                               'row wherever its own scroll leaves it.',
            'autogen_owned_recognition': {'BTN_X': {'kind': 'TEMPLATE', 'template': 'old'}},
        }}},
        'not_migrated': {'SKILL_X_RECOGNITION': {'semantic': 'BTN_X'}}}


def test_a_measured_demotion_is_not_resurrected_by_a_regeneration(tmp_path):
    """The retirement removed the node; the pipeline's own trigger must not put it back.

    Without this check the removal does not stick: the very failure the demotion was measured
    from ("runtime unresolved") is what fires the regeneration, so the node comes back on the
    next occurrence unless the record itself refuses the write.  The candidate stays on disk
    for review, and the entry stays byte-for-byte untouched -- same refusal shape as
    ``PROTECTED_RECOGNITION_CONFLICT``.
    """
    path = tmp_path / 'backend_routing.json'
    path.write_text(json.dumps(_demoted_payload()), encoding='utf-8')
    original = path.read_bytes()
    generated = node('fresh-crop')
    ok, reason = PipelineAutoGen(project_root=tmp_path, routing_path=path).wire(generated)
    assert not ok
    assert reason.startswith('DEMOTED_SEMANTIC_KEEPS_ITS_RETIREMENT:'), reason
    assert path.read_bytes() == original, 'a refused write must not touch the routing file'
    assert (tmp_path / generated.evidence['pipeline_node_path']).exists()


def test_a_demotion_naming_another_semantic_does_not_block_the_new_one(tmp_path):
    """The refusal is scoped to the demoted semantic, so the check cannot over-block.

    A skill can retire one semantic and later legitimately carry a node for a different one;
    keying the refusal on "the entry has a demotion record" alone would forbid that forever.

    The declaration is flipped to MAA first on purpose: a LEGACY declaration may not carry *any*
    node (see ``test_recognition_backend_declaration``), so a LEGACY payload would be refused by
    that rule and this test would no longer be measuring the demotion scope it is about.  A
    skill that gains a node has to move its declaration with it -- that is the contract the
    other rule states, not an exception to it.
    """
    path = tmp_path / 'backend_routing.json'
    payload = _demoted_payload()
    payload['skills']['SKILL_X']['recognition_backend'] = 'MAA'
    path.write_text(json.dumps(payload), encoding='utf-8')
    other = GeneratedNode(
        semantic='BTN_Y', skill_id='SKILL_X', kind='TEMPLATE',
        routing_node={'kind': 'TEMPLATE', 'template': 'other'},
        pipeline_node={'recognition': 'TemplateMatch', 'template': 'other'})
    ok, reason = PipelineAutoGen(project_root=tmp_path, routing_path=path).wire(other)
    assert ok is True, reason
    route = json.loads(path.read_text(encoding='utf-8'))['skills']['SKILL_X']
    assert set(route['recognition']) == {'BTN_Y'}


def test_a_legacy_declaration_refuses_the_node_instead_of_contradicting_itself(tmp_path):
    """LEGACY plus a node is not a state worth writing: the node overrides the declaration.

    Measured 2026-10-16: the runtime re-wired ``REGULAR_EVENT_ENTRY`` into
    ``OPEN_EVENT_CALENDAR_FROM_HOME`` (``preferred: ADB``, ``recognition_backend: LEGACY``) and
    the entry ended up carrying both -- ``test_recognition_backend_declaration`` calls that pair
    illegal, so the writer has to be the one that refuses.  Otherwise the invalidity is re-created
    by the very trigger that runs on every unresolved attempt.
    """
    path = tmp_path / 'backend_routing.json'
    payload = {'version': 1, 'skills': {'SKILL_X': {
        'preferred': 'ADB', 'fallback': 'MAA', 'recognition_backend': 'LEGACY',
        'promoted': False, 'migration_priority': 'P3'}}}
    path.write_text(json.dumps(payload), encoding='utf-8')
    original = path.read_bytes()
    generated = node('fresh-crop')
    ok, reason = PipelineAutoGen(project_root=tmp_path, routing_path=path).wire(generated)
    assert not ok
    assert reason.startswith('LEGACY_DECLARATION_TAKES_NO_NODE'), reason
    assert path.read_bytes() == original, 'a refused write must not touch the routing file'
