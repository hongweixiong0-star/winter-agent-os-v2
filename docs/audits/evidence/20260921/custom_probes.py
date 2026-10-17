import sys,os,json,pathlib,dataclasses
ROOT=pathlib.Path(__file__).parent
os.chdir(ROOT);sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from winter_agent_v2.models import WorldState,Page,MarchState
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.goal_library import GoalLibrary,GoalState,GoalStatus,route_for
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.ocr import HybridVision
from winter_agent_v2 import observation_store as obs
from winter_agent_v2.device_lease import DeviceLease,OWNER_DEVELOPMENT_VALIDATION
from winter_agent_v2.verifier import verify_beast_dispatch
from tests.test_march_reservation_handover import FakeDevice,FakeSemantic
out={}; reg=v2_registry(); lib=GoalLibrary()
def decision(b,w): return dataclasses.asdict(b.decide(w,reg))
# Each probe writes only to the isolated snapshot.
obs.STATE_PATH=ROOT/'learning/audit_observation.json'
obs.record('stamina',{'current':175})
observed=obs.as_observation_input(obs.load())
out['role_unscoped_store']={'load_keys':list(obs.load()),'role_A_then_role_B_same_store':observed['stamina']['reading'],'record_parameters':__import__('inspect').signature(obs.record).__str__()}
world=WorldState(page=Page.MAP,march_used=2,march_max=3,stamina={'current':30},confidence=.99)
out['reserved_slot']={g:decision(RuleBrain(current_goal=g,reserve_marches=2,claim_free_stamina=False),world) for g in ['GATHER_RESOURCE','BEAST_HUNT']}
goals=lib.discover(WorldState(page=Page.MAP,march_used=0,march_max=3,confidence=.99))
out['ready_discovered']={'ranking':[(g.goal_id,g.status.value,g.priority) for g in sorted(goals,key=lambda g:g.priority,reverse=True)],'selected':lib.best(goals).goal_id}
panel={'open':True,'camps':{'SHIELD_CAMP':{'status':'IN_PROGRESS','queue_available':False},'LANCER_CAMP':{'status':'IDLE','queue_available':True},'MARKSMAN_CAMP':{'status':'IDLE','queue_available':True}}}
pw=HybridVision._with_quick_panel(WorldState(page=Page.HOME,confidence=.99),panel)
out['quick_panel_schema']={'camps':pw.camps,'goals':[(g.goal_id,g.status.value) for g in lib.discover(pw) if 'CAMP_TRAINING' in g.goal_id]}
camps={'SHIELD_CAMP':{'observed':True,'busy':True,'status':'IN_PROGRESS'},'LANCER_CAMP':{'observed':True,'busy':False,'status':'IDLE'},'MARKSMAN_CAMP':{'observed':False,'status':'UNKNOWN'}}
w=WorldState(page=Page.TRAINING,camps=camps,training={'troop_type':'INFANTRY','queue_available':False,'status':'IN_PROGRESS'},confidence=.99)
out['camp_routing']={}
for goal in ['SHIELD_CAMP_TRAINING','LANCER_CAMP_TRAINING','MARKSMAN_CAMP_TRAINING']:
 b=RuleBrain(current_goal=route_for(goal));b.goal_id=goal;out['camp_routing'][goal]=decision(b,w)
r=object.__new__(LiveRuntime);r.brain=RuleBrain(current_goal='BEAST_HUNT');r._committed_goal='AVOID_STAMINA_WASTE'
g=GoalState('SHIELD_CAMP_TRAINING',GoalStatus.READY,available_skills=('TRAIN_TROOPS',))
out['goal_attribution']={'executing_route':r.brain.current_goal,'committed':r._committed_goal,'episode_owner':r._step_goal(g)}
out['stored_stamina_seed']={'actual':obs.load()['stamina'].reading,'runtime_result':r._stored_stamina_value()}
class Vision:
 def observe(self,p):return world
lease=DeviceLease(ROOT/'lease_probe')
lease.acquire(owner=OWNER_DEVELOPMENT_VALIDATION,job_id='audit_job',trace_id='audit_trace')
device=FakeDevice()
rt=LiveRuntime(device=device,vision=Vision(),semantic_vision=FakeSemantic(),capture_dir=ROOT/'probe_capture',brain=RuleBrain(current_goal='BEAST_HUNT'),device_lease=lease,execution_mode='DEVELOPMENT_VALIDATION',job_id='audit_job',trace_id='audit_trace',sleeper=lambda _:None)
run=rt.run(max_actions=1)
out['validation_own_lease']={'stop_reason':run.stop_reason,'steps':len(run.steps)}
# Same owner string is accepted even for another validation job.
record,reason=lease.acquire(owner=OWNER_DEVELOPMENT_VALIDATION,job_id='other_job')
out['lease_wrong_job']={'accepted':record is not None,'returned_job':record.job_id,'reason':reason}
b=RuleBrain(current_goal='BEAST_HUNT',claim_free_stamina=False)
rally=WorldState(page=Page.BEAST,beast={'attack_card':True},beast_search_result={'solo_attack':False,'has_rally':True},confidence=.99)
out['rally_card']=decision(b,rally)
before=WorldState(page=Page.MARCH,beast={'name':'麝牛','victory_assured':True},march_used=1,march_max=3,stamina={'current':100},confidence=.99)
after=WorldState(page=Page.MAP,marches=(MarchState.MARCHING,),march_used=1,march_max=3,stamina={'current':100},confidence=.99)
out['beast_dispatch_no_new_march']=dataclasses.asdict(verify_beast_dispatch(before,after))
# All-goal discoverable route coverage (not just the curated route map).
special=WorldState(page=Page.HOME,building={'upgradeable':True},events={'minimum_guarantee':{'points_missing':10},'bear':{'status':'ACTIVE'}},rewards={'verified_claimable':['TEST'],'skills':{'TEST':['CLAIM_REWARD']}},confidence=.99)
out['unrouted_discovered']=[{'goal':g.goal_id,'route':route_for(g.goal_id),'skills':g.available_skills} for g in lib.discover(special) if g.available_skills and route_for(g.goal_id) is None]
(ROOT/'custom_probes.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(out,ensure_ascii=False,indent=2))

