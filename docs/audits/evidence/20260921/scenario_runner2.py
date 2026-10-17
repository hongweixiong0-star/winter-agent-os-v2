import sys,os,json,pathlib
ROOT=pathlib.Path(__file__).parent
os.chdir(ROOT);sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
production=pathlib.Path(r"E:\无尽冬日智能体")
def guard(event,args):
 if event=="open" and isinstance(args[0],(str,bytes,os.PathLike)):
  mode=args[1]; flags=args[2]
  write=(isinstance(mode,str) and any(x in mode for x in "wax+")) or (isinstance(flags,int) and flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC))
  if write and pathlib.Path(os.fsdecode(args[0])).resolve().is_relative_to(production):raise RuntimeError("AUDIT_WRITE_DENIED")
 if event=="socket.connect":raise RuntimeError("AUDIT_NETWORK_DENIED")
 if event=="subprocess.Popen":
  cmd=str(args[1]).lower()
  if any(x in cmd for x in ["adb", "mumu", "run_live.py", "control_panel.py", "schtasks", "taskkill"]):raise RuntimeError("AUDIT_LIVE_PROCESS_DENIED")
sys.addaudithook(guard)
import pytest
class Plugin:
 def pytest_runtest_setup(self,item):
  (ROOT/"learning/observation_state.json").write_text("{\"domains\":{}}",encoding="utf-8")
 def pytest_collection_modifyitems(self,items):
  for it in items:
   if it.module.__name__.endswith("test_evidence_integrity"):
    it.module.ROOT=production;it.module.TESTS=production/"tests"
nodes=['tests/test_refusal_yields_the_cycle.py', 'tests/test_device_loss_is_not_a_goal_refusal.py', 'tests/test_device_lease.py', 'tests/test_three_camps_are_three_readings.py', 'tests/test_sweep_rotation_and_hop.py', 'tests/test_march_reservation_handover.py', 'tests/test_validation_driver.py', 'tests/test_worker_wait_is_bounded.py', 'tests/test_worker_exit_semantics.py']
code=pytest.main(["-q","--tb=short","-p","no:cacheprovider","--basetemp",str(ROOT/"pytest_temp_scenarios2"),"--junitxml="+str(ROOT/"scenarios_existing2.xml"),*nodes],plugins=[Plugin()])
print("AUDIT_PYTEST_EXIT",code,flush=True)
