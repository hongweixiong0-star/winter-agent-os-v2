"""Bisect: why does the adapter's match disagree with a raw MaaFramework match?

probe6 found BTN_HERO_FIGHT on hero_fight_final_20260914/00_before.png with
box (375,1165,305,72).  The adapter reports 0/7 on the same corpus.  One of the
two is wrong, so this script runs both paths side by side and then removes the
adapter's optional settings one at a time until they agree.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MUMU_ADB = r"D:\Program Files\Netease\MuMu Player 12\nx_main\adb.exe"
SERIAL = "127.0.0.1:7555"
FRAME = ROOT / "dataset/truth_audit/hero_fight_final_20260914/00_before.png"
TPL = ROOT / "dataset/candidate/hero_camp/btn_hero_fight__live_squad.png"

R: dict = {}


def box_dict(b):
    if b is None:
        return None
    if hasattr(b, "x"):
        return {"x": int(b.x), "y": int(b.y), "w": int(b.w), "h": int(b.h)}
    try:
        return list(b)
    except TypeError:
        return str(b)


def reco_summary(detail):
    nodes = getattr(detail, "nodes", None) or []
    if not nodes:
        return {"nodes": 0}
    reco = getattr(nodes[0], "recognition", None)
    if reco is None:
        return {"nodes": len(nodes), "recognition": None}
    allres = getattr(reco, "all_results", None) or []
    first = allres[0] if allres else None
    first_info = None
    if first is not None:
        first_info = {
            "type": type(first).__name__,
            "box": box_dict(getattr(first, "box", None)),
            "score": getattr(first, "score", None),
            "repr": repr(first)[:200],
        }
    best = getattr(reco, "best_result", None)
    return {
        "hit": getattr(reco, "hit", None),
        "box": box_dict(getattr(reco, "box", None)),
        "all_len": len(allres),
        "first": first_info,
        "best_type": type(best).__name__,
        "best": (best if isinstance(best, (str, int, float)) else
                 (box_dict(getattr(best, "box", None)) if best is not None else None)),
        "algorithm": str(getattr(reco, "algorithm", "")),
        "name": getattr(reco, "name", ""),
    }


from maa.controller import AdbController  # noqa: E402
from maa.pipeline import JRecognitionType, JTemplateMatch  # noqa: E402
from maa.resource import Resource  # noqa: E402
from maa.tasker import Tasker  # noqa: E402
from maa.toolkit import Toolkit  # noqa: E402

dev = Toolkit.find_adb_devices()[0]
ctrl = AdbController(adb_path=dev.adb_path, address=SERIAL,
                     screencap_methods=dev.screencap_methods,
                     input_methods=dev.input_methods, config=dev.config)
ctrl.post_connection().wait()
R["connect"] = ctrl.connected

frame = np.array(Image.open(FRAME).convert("RGB"))
tpl = np.array(Image.open(TPL).convert("RGB"))
R["frame_shape"] = list(frame.shape)
R["tpl_shape"] = list(tpl.shape)
R["tpl_is_subarray_of_frame"] = bool((frame[1165:1237, 375:680] == tpl[:72, :305]).all()) \
    if frame.shape[0] > 1237 and frame.shape[1] > 680 else None


def run(label, *, roi, method, thresholds, use_override_image=True, save_draw=None,
        stdout_level=None, log_dir=None, bundle=None):
    res = Resource()
    if bundle:
        res.post_bundle(str(bundle)).wait()
    tasker = Tasker()
    tasker.bind(res, ctrl)
    if log_dir:
        tasker.set_log_dir(str(log_dir))
    if stdout_level is not None:
        tasker.set_stdout_level(stdout_level)
    if save_draw is not None:
        tasker.set_save_draw(save_draw)
    if use_override_image:
        res.override_image("BTN_HERO_FIGHT", tpl)
    param = JTemplateMatch(template=["BTN_HERO_FIGHT"], roi=roi, threshold=thresholds, method=method)
    detail = tasker.post_recognition(JRecognitionType.TemplateMatch, param, frame).wait().get()
    info = reco_summary(detail)
    info["inited"] = bool(getattr(tasker, "inited", None))
    R[label] = info
    return info


run("A_raw_like_probe6", roi=(0, 0, 0, 0), method=5, thresholds=[0.6])
run("B_plus_save_draw", roi=(0, 0, 0, 0), method=5, thresholds=[0.6], save_draw=True)
run("C_plus_stdout_off", roi=(0, 0, 0, 0), method=5, thresholds=[0.6], save_draw=True,
    stdout_level=0)
run("D_plus_bad_bundle", roi=(0, 0, 0, 0), method=5, thresholds=[0.6], save_draw=True,
    stdout_level=0, bundle=ROOT / "dataset/candidate/templates")
run("E_roi_omitted", roi=None, method=5, thresholds=[0.6])
run("F_threshold_07", roi=(0, 0, 0, 0), method=5, thresholds=[0.7])
run("G_threshold_multi", roi=(0, 0, 0, 0), method=5, thresholds=[0.6, 0.7])

# and the adapter itself, on the same frame
from winter_agent_v2.maa_executor import MaaExecutorAdapter  # noqa: E402

adapter = MaaExecutorAdapter(adb_path=MUMU_ADB, serial=SERIAL, production=False,
                             template_dir=ROOT / "dataset/candidate/templates",
                             log_dir=ROOT / "learning/maa_logs")
ok, reason = adapter.ensure_ready()
R["adapter_ready"] = [ok, reason]
out = adapter.match_template(frame, template="BTN_HERO_FIGHT", semantic="BTN_HERO_FIGHT",
                             threshold=0.6, images={"BTN_HERO_FIGHT": TPL})
R["H_adapter"] = out.to_dict()

print(json.dumps(R, indent=2, ensure_ascii=False, default=str))
