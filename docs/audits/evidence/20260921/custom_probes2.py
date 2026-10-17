import sys,os,pathlib,json,dataclasses
from unittest.mock import patch
ROOT=pathlib.Path(__file__).parent;os.chdir(ROOT);sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.models import WorldState,Page,Decision,ExecutionResult,Action
from winter_agent_v2.scheduler import TickResult
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.goal_library import GoalLibrary,GoalState,GoalStatus
from winter_agent_v2.skills import v2_registry
from winter_agent_v2 import observation_store as obs
from tests.test_march_reservation_handover import FakeDevice,FakeSemantic
obs.STATE_PATH=ROOT/'learning/probe2_obs.json';obs.STATE_PATH.write_text('{"domains":{}}')
out={}
world=WorldState(page=Page.HOME,confidence=.99)
class Vision:
 def observe(self,p):return world
class Goals(GoalLibrary):
 def discover(self,*a,**k):return (GoalState('MAIL_ROUTINE',GoalStatus.READY,reward_value=500,available_skills=('OPEN_MAIL',)),GoalState('SHIELD_CAMP_TRAINING',GoalStatus.READY,development_value=90,available_skills=('TRAIN_TROOPS',)))
rt=LiveRuntime(device=FakeDevice(),vision=Vision(),semantic_vision=FakeSemantic(),capture_dir=ROOT/'failure_probe',brain=RuleBrain(current_goal='MAIL'),sleeper=lambda _:None,observation_retries=0)
rt.goal_library=Goals()
d=Decision('OPEN_MAIL','mail_goal',.99,'mail_open')
with patch('winter_agent_v2.runtime.Scheduler.tick',return_value=TickResult(d,ExecutionResult(True,False,Action('TAP_SEMANTIC','BTN_OPEN_MAIL')))):
 run=rt.run(max_actions=6)
out['nonfatal_verifier_failure']={'steps':len(run.steps),'stop':run.stop_reason,'other_ready':'SHIELD_CAMP_TRAINING','yielded':list(rt._yielded_goals)}
b=RuleBrain(current_goal='BEAST_HUNT');b.beast_search_used=True
w=WorldState(page=Page.MAP,march_used=1,march_max=3,stamina={'current':100},confidence=.99)
out['after_success_without_visible_target']=[dataclasses.asdict(b.decide(w,v2_registry())) for _ in range(6)]
out['role_switch_skills']=[x.id for x in v2_registry().all() if 'ROLE' in x.id or 'ACCOUNT' in x.id]
out['registered_not_live_enabled']=[x.id for x in v2_registry().all() if x.id not in LiveRuntime.VERIFIED_ATOMIC]
# Last two scenarios have no role loop to invoke; below proves role is not a Goal input.
out['goal_discovery_parameters']=str(__import__('inspect').signature(GoalLibrary.discover))
(ROOT/'custom_probes2.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(out,ensure_ascii=False,indent=2))

