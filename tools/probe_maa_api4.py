"""Probe #5: Job semantics + channel order + RecognitionDetail on a real frame."""
from __future__ import annotations

import json
import time
import traceback

import numpy as np

R: dict = {}

try:
    from maa.controller import AdbController
    from maa.toolkit import Toolkit
    from maa.resource import Resource
    from maa.tasker import Tasker
    from maa.pipeline import JRecognitionType, JTemplateMatch, JOCR, JClick, JActionType
    from maa.define import RecognitionDetail

    det = Toolkit.find_adb_devices()
    dev = det[0]
    ctrl = AdbController(
        adb_path=dev.adb_path, address="127.0.0.1:7555",
        screencap_methods=dev.screencap_methods, input_methods=dev.input_methods,
        config=dev.config,
    )
    R["connect"] = ctrl.post_connection().wait().succeeded

    job = ctrl.post_screencap().wait()
    R["job_type"] = type(job).__name__
    for attr in ["done", "succeeded", "failed", "pending", "running", "status", "job_id"]:
        v = getattr(job, attr, "<MISSING>")
        R[f"job.{attr}"] = {
            "callable": callable(v), "value": (v() if callable(v) else v) if not isinstance(v, str) else v,
            "type": type(v).__name__,
        }
    img = job.get()
    R["img_shape"] = list(img.shape)
    # channel order probe: the game's loading/UI has large saturated red areas
    # (red badges) at top-right. Compare R vs B channel means of that corner.
    h, w = img.shape[:2]
    corner = img[0:int(0.12 * h), int(0.85 * w):w].reshape(-1, 3).astype(float)
    R["corner_channel_means_as_given"] = [round(float(corner[:, i].mean()), 2) for i in range(3)]
    R["corner_channel_means_flipped"] = [round(float(corner[:, 2 - i].mean()), 2) for i in range(3)]
    # save both variants for visual check
    from PIL import Image
    Image.fromarray(img).save(r"E:\无尽冬日智能体\dataset\evidence\maa_probe_asgiven.png")
    Image.fromarray(img[:, :, ::-1]).save(r"E:\无尽冬日智能体\dataset\evidence\maa_probe_flipped.png")

    # ---- Resource/Tasker bind + recognition on a real frame
    res = Resource()
    R["resource_loaded"] = res.loaded
    tasker = Tasker()
    R["bind"] = tasker.bind(res, ctrl)
    R["inited_0"] = tasker.inited

    # recognize with JTemplateMatch on a template we already own
    tpl_path = r"E:\无尽冬日智能体\dataset\candidate\hero_camp\btn_hero_fight__live_squad.png"
    tpl = np.array(Image.open(tpl_path).convert("RGB"))
    R["tpl_shape"] = list(tpl.shape)
    ok_img = res.override_image("BTN_HERO_FIGHT", tpl)
    R["override_image"] = ok_img
    R["inited_1"] = tasker.inited

    reco = tasker.post_recognition(
        JRecognitionType.TemplateMatch,
        JTemplateMatch(template=["BTN_HERO_FIGHT.png"], threshold=[0.7]),
        img,
    )
    R["reco_job"] = type(reco).__name__
    detail = reco.wait().get()
    R["reco_detail_type"] = type(detail).__name__
    R["reco_hit"] = getattr(detail, "hit", None)
    box = getattr(detail, "box", None)
    R["reco_box"] = None if box is None else {"x": box.x, "y": box.y, "w": box.w, "h": box.h}
    allr = getattr(detail, "all_results", None)
    R["reco_all_len"] = len(allr) if allr else 0
    if allr:
        r0 = allr[0]
        R["reco_first"] = {"box": {"x": r0.box.x, "y": r0.box.y, "w": r0.box.w, "h": r0.box.h},
                           "score": r0.score}

    # OCR probe (no expectation -> does it return raw text?)
    ojob = tasker.post_recognition(JRecognitionType.OCR, JOCR(expected=[], roi=(0, 0, 720, 200)), img)
    od = ojob.wait().get()
    R["ocr_hit"] = getattr(od, "hit", None)
    texts = []
    for r in (getattr(od, "all_results", None) or [])[:12]:
        texts.append({"text": getattr(r, "text", None), "score": round(float(getattr(r, "score", 0)), 3)})
    R["ocr_texts"] = texts

except Exception as exc:  # noqa: BLE001
    R["FATAL"] = f"{type(exc).__name__}: {exc}"
    R["tb"] = traceback.format_exc()[-2500:]

print(json.dumps(R, indent=2, ensure_ascii=False, default=str))
