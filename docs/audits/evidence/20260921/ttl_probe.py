import sys,os,json,pathlib
ROOT=pathlib.Path(__file__).parent
os.chdir(ROOT);sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
production=pathlib.Path(r"E:\WinterAgent")
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

from datetime import datetime,timezone,timedelta
from winter_agent_v2.goal_library import GoalLibrary
from winter_agent_v2.models import WorldState,Page
from winter_agent_v2 import observation_store as o
o.STATE_PATH=ROOT/"learning/ttl_probe.json"
now=datetime.now(timezone.utc);o.record("mail",{"status":"CLAIMED"},now=now)
lib=GoalLibrary();w=WorldState(page=Page.HOME,confidence=.99)
r={}
for label,at in [("fresh",now),("expired",now+timedelta(hours=2))]:
 goals=lib.discover(w,observations=o.as_observation_input(o.load(),now=at))
 r[label]=[(g.goal_id,g.status.value) for g in goals if g.goal_id=="MAIL_ROUTINE"]
(ROOT/"ttl_probe.json").write_text(json.dumps(r),encoding="utf-8");print(r)
