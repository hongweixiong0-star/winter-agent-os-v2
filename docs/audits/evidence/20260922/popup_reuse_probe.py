import sys,pathlib,json
ROOT=pathlib.Path(__file__).parent;sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.models import WorldState,Page
from winter_agent_v2.control_experience import ControlExperience
from tests.test_march_reservation_handover import FakeDevice,FakeSemantic
r=LiveRuntime(device=FakeDevice(),vision=None,semantic_vision=FakeSemantic(),capture_dir=ROOT/"audit_capture")
r._control_ledger={"POPUP|BTN_CLOSE":ControlExperience(page="POPUP",control="BTN_CLOSE",position_norm=(.7,.62),known_result="CLOSE_POPUP",known_change="POPUP_CLOSED",last_result="POPUP_CLOSED",risk="LOW",attempts=1)}
r._remembered_reuse=[];r._printed_remembered=set()
out={}
for popup in ["GENERIC_REWARD","EXIT_CONFIRM"]:
 out[popup]=r._resolve_semantic_target("BTN_CLOSE",WorldState(page=Page.POPUP,popup=popup,confidence=.99),frame_path=ROOT/"not_used.png",resource="WOOD")
(ROOT/"popup_reuse_probe.json").write_text(json.dumps(out),encoding="utf-8");print(out)
