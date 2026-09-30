from types import SimpleNamespace
from dataclasses import replace
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import WorldState,Page
from winter_agent_v2.goal_library import GoalState,GoalStatus
from winter_agent_v2.operations_policy import choose_stamina_goal
from winter_agent_v2.rally import RallyTarget,rally_target_for_goal
from winter_agent_v2.session_adapters import BearSessionAdapter,BearDomain,route_for
from winter_agent_v2.verifier import verify_rally_created


def runtime_goal(intel=None,idle=1):
    runtime=object.__new__(LiveRuntime)
    runtime.brain=RuleBrain(reserve_marches=1)
    goal=GoalState('AVOID_STAMINA_WASTE',GoalStatus.READY,
                   evidence={'current':180,'idle_marches':idle,'intel_state':intel or {}})
    return runtime,goal


def test_production_sync_uses_polar_when_intel_is_empty_and_solo_beast_blocked():
    runtime,goal=runtime_goal({'status':'AVAILABLE','untried_pins':0})
    runtime._sync_brain_goal(goal,SimpleNamespace(capabilities={'SPEND_STAMINA_ON_BEAST':('BLOCKED',)}))
    assert runtime.brain.current_goal=='GIANT_BEAST'
    assert goal.evidence['stamina_sink']=='GIANT_BEAST'
    assert rally_target_for_goal(goal.goal_id,goal.evidence) is RallyTarget.POLAR_TERROR
    assert route_for(goal.goal_id,'START_RALLY').adapter=='bear'
    from winter_agent_v2.skills import v2_registry
    assert runtime.brain.decide(WorldState(page=Page.MAP),v2_registry()).skill=='START_RALLY'


def test_runnable_intel_wins_but_pending_intel_does_not_prevent_giant_route():
    runtime,goal=runtime_goal({'status':'AVAILABLE','untried_pins':2})
    runtime._sync_brain_goal(goal,SimpleNamespace(capabilities={}))
    assert runtime.brain.current_goal=='SPEND_STAMINA'
    assert choose_stamina_goal(180,'IN_PROGRESS',True,True).goal=='GIANT_BEAST'


def test_giant_failure_falls_back_without_reusing_polar_identity():
    runtime,goal=runtime_goal()
    runtime._sync_brain_goal(goal,SimpleNamespace(capabilities={}))
    runtime._giant_stamina_failed=True
    runtime._sync_brain_goal(goal,SimpleNamespace(capabilities={}))
    assert runtime.brain.current_goal=='BEAST_HUNT'
    assert 'rally_target' not in goal.evidence


def test_reserved_slot_is_available_but_actual_busy_or_own_rally_waits():
    assert choose_stamina_goal(30,'EMPTY',True,True,idle_slots=1).goal=='GIANT_BEAST'
    assert choose_stamina_goal(30,'EMPTY',True,True,idle_slots=0).goal=='WAIT'
    assert choose_stamina_goal(30,'EMPTY',True,True,own_rally=True).goal=='WAIT'
    assert choose_stamina_goal(29,'AVAILABLE',True,True).goal=='NONE'


def test_polar_created_requires_explicit_identity_and_own_countdown():
    before=WorldState(page=Page.MAP)
    for target in ('BEAR',None):
        row={'ownership':'SELF','remaining_seconds':299,'target_type':target}
        assert not verify_rally_created(before,WorldState(alliance={'rally':row}),'POLAR_TERROR').ok
    row={'ownership':'SELF','remaining_seconds':299,'target_type':'POLAR_TERROR'}
    assert verify_rally_created(before,WorldState(alliance={'rally':row}),'POLAR_TERROR').ok


def test_polar_search_uses_client_tab_and_never_join_or_map_pan():
    adapter=BearSessionAdapter(target='POLAR_TERROR')
    adapter.configure({'stamina_sink':True})
    world=WorldState(page=Page.MAP,resource_search_open=True,resource_selected_tab='MEAT')
    domain=SimpleNamespace(world=world,idle_marches=1)
    assert adapter._polar_step(domain).skill_id=='SELECT_GIANT_BEAST_TAB'
    world=replace(world,resource_selected_tab='GIANT_BEAST')
    domain.world=world
    assert adapter._polar_step(domain).skill_id=='SUBMIT_GIANT_BEAST_SEARCH'
    domain.world=replace(world,beast_search_result={'has_rally':True,'title_level':1})
    step=adapter._polar_step(domain)
    assert step.target=='集结' and step.skill_id!='JOIN_RALLY'
    adapter._polar_words=['出征','大概率失败']
    assert adapter._polar_step(domain) is None
    adapter._polar_words=['出征','胜券在握']
    assert adapter._polar_step(domain).target=='出征'
    adapter._polar_dispatched=True
    assert adapter._polar_step(domain).target!='出征'


def test_intel_hud_stamina_survives_popup_without_borrowing_other_role(tmp_path):
    from winter_agent_v2 import observation_store
    from winter_agent_v2.goal_library import GoalLibrary
    runtime = object.__new__(LiveRuntime)
    role_path = tmp_path / 'role_A.json'
    runtime._role_observation_store_path = lambda: role_path
    runtime._record_observations(WorldState(page=Page.INTEL, intel={'stamina':284}))
    observed = observation_store.as_observation_input(observation_store.load(role_path))
    goals = GoalLibrary().discover(WorldState(page=Page.POPUP), observations=observed)
    stamina = next(g for g in goals if g.goal_id == 'AVOID_STAMINA_WASTE')
    assert stamina.evidence['current'] == 284
    assert stamina.evidence['reused'] is True
    assert not any(g.goal_id == 'AVOID_STAMINA_WASTE' for g in
                   GoalLibrary().discover(WorldState(page=Page.POPUP), observations={}))


def test_selected_monster_tab_uses_current_bracket_and_label_not_old_order(tmp_path):
    from PIL import Image
    from winter_agent_v2.ocr import selected_tab_from_live_labels
    path = tmp_path / 'frame.png'
    Image.new('RGB', (720,1280)).save(path)
    strokes = SimpleNamespace(_bracket_strokes=lambda image: [(332,10),(474,10)])
    labels = {'BEAST':(.34,.74),'GIANT_BEAST':(.56,.74)}
    assert selected_tab_from_live_labels(path,labels,strokes) == 'GIANT_BEAST'
    assert selected_tab_from_live_labels(path,{'BEAST':(.34,.74)},strokes) is None
    assert selected_tab_from_live_labels(path,{**labels,'MEAT':(.56,.74)},strokes) is None


def test_session_ocr_uses_observed_frame_and_disambiguates_dialog_action():
    from winter_agent_v2.session_host import LiveRuntimeSessionHost
    host = object.__new__(LiveRuntimeSessionHost)
    host._last_world_path = 'current_frame.png'
    assert host._frame_to_path(None) == 'current_frame.png'
    tokens = [SimpleNamespace(text='发起集结', centre=(360,400)),
              SimpleNamespace(text='请设定集结时间，所有部队', centre=(360,500)),
              SimpleNamespace(text='发起集结', centre=(360,840))]
    service = SimpleNamespace(recognize=lambda path: SimpleNamespace(tokens=tokens))
    assert host._locate_printed(None,'发起集结',service)[0] is None
    assert host._locate_printed(None,'发起集结',service,below_text='请设定集结时间')[0] == (360,840)
    assert host._locate_printed(None,'发起集结',service,below_text='不存在的说明')[0] is None


def test_polar_dispatch_uses_observed_free_slot_without_inventing_capacity():
    adapter=BearSessionAdapter(target='POLAR_TERROR')
    adapter._polar_target_confirmed=True
    adapter._polar_target_name='猛犸象'
    adapter._polar_words=['目标：猛犸象','118,110/118,110','出征']
    adapter._polar_slot_available=True
    adapter._polar_slot_observed_at=100
    domain=SimpleNamespace(world=WorldState(page=Page.MARCH),idle_marches=None)
    assert adapter._polar_step(domain,now=130).target=='出征'
    assert adapter._polar_step(domain,now=191) is None
    domain.idle_marches=0
    assert adapter._polar_step(domain,now=130) is None
    domain.idle_marches=1
    adapter._polar_words=['目标：别的目标','118,110/118,110','出征']
    assert adapter._polar_step(domain,now=130) is None
