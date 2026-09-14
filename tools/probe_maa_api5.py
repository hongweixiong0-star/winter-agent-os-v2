"""Probe #6: TaskDetail/NodeDetail shape, correct template naming, and OCR model sources."""
from __future__ import annotations

import glob
import json
import os
import traceback

import numpy as np

R: dict = {}

# ---- A. where could OCR models come from?
def hunt(models_root_hints):
    hits = {}
    patterns = ["**/det.onnx", "**/rec.onnx", "**/keys.txt", "**/*.onnx"]
    for root in models_root_hints:
        if not os.path.isdir(root):
            continue
        found = []
        for pat in patterns[:3]:
            found += glob.glob(os.path.join(root, pat), recursive=True)[:20]
        if found:
            hits[root] = sorted(set(found))[:20]
    return hits


import site
import sys
sp = [p for p in sys.path if "site-packages" in p]
R["site_packages"] = sp
R["model_hunt"] = hunt(sp + [
    r"E:\dongri-mumu-bot\.venv\Lib\site-packages\maa",
    r"E:\dongri-mumu-bot\.venv\Lib\site-packages\MaaAgentBinary",
    r"E:\dongri-mumu-bot\.venv\Lib\site-packages\rapidocr_onnxruntime",
    r"E:\dongri-mumu-bot\.venv\Lib\site-packages\onnxruntime",
])

try:
    from maa.controller import AdbController
    from maa.toolkit import Toolkit
    from maa.resource import Resource
    from maa.tasker import Tasker
    from maa.pipeline import JRecognitionType, JTemplateMatch

    det = Toolkit.find_adb_devices()
    dev = det[0]
    ctrl = AdbController(
        adb_path=dev.adb_path, address="127.0.0.1:7555",
        screencap_methods=dev.screencap_methods, input_methods=dev.input_methods,
        config=dev.config,
    )
    ctrl.post_connection().wait()
    img = ctrl.post_screencap().wait().get()

    res = Resource()
    tasker = Tasker()
    tasker.bind(res, ctrl)

    from PIL import Image
    # The corrected template: name WITHOUT .png, and the frame is the real squad page.
    tpl = np.array(Image.open(
        r"E:\无尽冬日智能体\dataset\candidate\hero_camp\btn_hero_fight__live_squad.png"
    ).convert("RGB"))
    res.override_image("BTN_HERO_FIGHT", tpl)
    frame = np.array(Image.open(
        r"E:\无尽冬日智能体\dataset\truth_audit\hero_fight_final_20260914\00_before.png"
    ).convert("RGB"))
    R["frame_shape"] = list(frame.shape)

    job = tasker.post_recognition(
        JRecognitionType.TemplateMatch,
        JTemplateMatch(template=["BTN_HERO_FIGHT"], threshold=[0.6]),
        frame,
    )
    td = job.wait().get()
    R["taskdetail_attrs"] = [a for a in dir(td) if not a.startswith("_")]
    R["taskdetail_status"] = str(getattr(td, "status", None))
    nodes = getattr(td, "nodes", None)
    R["nodes_len"] = len(nodes) if nodes is not None else None
    if nodes:
        n0 = nodes[0]
        R["nodedetail_attrs"] = [a for a in dir(n0) if not a.startswith("_")]
        R["node0"] = {
            "name": getattr(n0, "name", None),
            "recognition": None,
        }
        reco = getattr(n0, "recognition", None)
        if reco is not None:
            R["node0"]["recognition"] = {
                "attrs": [a for a in dir(reco) if not a.startswith("_")],
                "hit": getattr(reco, "hit", None),
                "box": (lambda b: None if b is None else {"x": b.x, "y": b.y, "w": b.w, "h": b.h})(getattr(reco, "box", None)),
            }
            allr = getattr(reco, "all_results", None)
            R["node0"]["recognition"]["all_len"] = len(allr) if allr else 0
            if allr:
                best = allr[0]
                R["node0"]["recognition"]["first"] = {
                    "box": {"x": best.box.x, "y": best.box.y, "w": best.box.w, "h": best.box.h},
                    "score": round(float(best.score), 4),
                }
        R["tasker_get_reco"] = str(
            tasker.get_recognition_detail(getattr(reco, "reco_id", 0))
        )[:300] if reco is not None else None

    # ---- Action: click without touching the game. Use JActionType with a
    # screenshot-only verification of the CALL PATH: DoNothing is safe.
    from maa.pipeline import JActionType, JDoNothing
    a = tasker.post_action(JActionType.DoNothing, JDoNothing(), box=(0, 0, 10, 10))
    R["action_doNothing_ok"] = a.wait().succeeded

    # ---- can we load OCR models from RapidOCR's bundled onnx?
    import rapidocr_onnxruntime as ro
    R["rapidocr_dir"] = os.path.dirname(ro.__file__)
    cand = os.path.join(os.path.dirname(ro.__file__), "models")
    R["rapidocr_models_dir_exists"] = os.path.isdir(cand)
    if os.path.isdir(cand):
        R["rapidocr_models"] = sorted(os.listdir(cand))[:20]
        j = res.post_ocr_model(cand)
        R["post_ocr_model_ok"] = j.wait().succeeded
except Exception as exc:  # noqa: BLE001
    R["FATAL"] = f"{type(exc).__name__}: {exc}"
    R["tb"] = traceback.format_exc()[-2500:]

print(json.dumps(R, indent=2, ensure_ascii=False, default=str))
