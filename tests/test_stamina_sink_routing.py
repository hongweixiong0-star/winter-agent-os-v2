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
