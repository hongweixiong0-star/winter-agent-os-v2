"""Probe #2: does MaaFramework (MaaFw 5.12.3) actually load and drive MuMu?

Read-only-ish: may connect to the device and take a screenshot. No game interaction,
no input events that could alter game state (we only do screencap).
"""
from __future__ import annotations

import json
import os
import traceback

R: dict = {"probe": "maa_api"}


def step(label, fn):
    try:
        R[label] = fn()
    except Exception as exc:  # noqa: BLE001
        R[label] = {"ERROR": f"{type(exc).__name__}: {exc}", "tb": traceback.format_exc()[-1200:]}
    return R[label]


# ---- 1. import surface
def _imports():
    out = {}
    import maa
    out["maa_module"] = getattr(maa, "__file__", "?")
    out["maa_version"] = getattr(maa, "__version__", None)
    out["dir"] = [n for n in dir(maa) if not n.startswith("_")]
    for name in ["resource", "controller", "tasker", "toolkit", "define", "job", "custom"]:
        try:
            mod = __import__(f"maa.{name}", fromlist=["*"])
            out[f"maa.{name}"] = [n for n in dir(mod) if not n.startswith("_")][:40]
        except Exception as exc:  # noqa: BLE001
            out[f"maa.{name}"] = f"IMPORT_FAIL: {type(exc).__name__}: {exc}"
    return out


step("imports", _imports)

# ---- 2. toolkit: detect adb devices
def _toolkit():
    from maa.toolkit import Toolkit
    res = {}
    try:
        adb_paths = Toolkit.find_adb_devices()
        res["find_adb_devices"] = [
            {
                "name": getattr(d, "name", None),
                "adb_path": getattr(d, "adb_path", None),
                "address": getattr(d, "address", None),
                "screencap_methods": getattr(d, "screencap_methods", None),
                "input_methods": getattr(d, "input_methods", None),
                "config": getattr(d, "config", None),
            }
            for d in adb_paths
        ]
    except Exception as exc:  # noqa: BLE001
        res["find_adb_devices"] = f"{type(exc).__name__}: {exc}"
    try:
        res["version"] = Toolkit.version()
    except Exception as exc:  # noqa: BLE001
        res["version"] = f"{type(exc).__name__}: {exc}"
    return res


step("toolkit", _toolkit)

# ---- 3. AdbController + connect + screencap
MUMU_ADB = r"D:\Program Files\Netease\MuMu Player 12\nx_main\adb.exe"
SHOT_PATH = r"E:\无尽冬日智能体\dataset\evidence\maa_probe_shot.png"


def _controller():
    from maa.controller import AdbController
    from maa.toolkit import Toolkit

    os.makedirs(os.path.dirname(SHOT_PATH), exist_ok=True)

    info = {}
    ctrl = AdbController(
        adb_path=MUMU_ADB,
        address="127.0.0.1:7555",
        screencap_methods=0xFFFFFFFF,  # all
        input_methods=0xFFFFFFFF,     # all
        config={},
    )
    info["created"] = str(ctrl)
    info["post_connection"] = str(ctrl.post_connection().wait().succeeded)
    try:
        info["connected"] = ctrl.connected
    except Exception as exc:  # noqa: BLE001
        info["connected"] = f"{type(exc).__name__}: {exc}"
    try:
        uuid = ctrl.uuid
        info["uuid"] = str(uuid)
    except Exception as exc:  # noqa: BLE001
        info["uuid"] = f"{type(exc).__name__}: {exc}"
    # screencap
    try:
        job = ctrl.post_screencap().wait()
        info["screencap_succeeded"] = job.succeeded
        img = job.get()
        info["image_type"] = str(type(img))
        try:
            import numpy as np
            arr = img
            info["shape"] = list(arr.shape)
            info["dtype"] = str(arr.dtype)
            mean = float(np.asarray(arr).mean())
            info["mean_pixel"] = round(mean, 2)
            info["is_black"] = mean < 3.0
            try:
                from PIL import Image
                Image.fromarray(arr).save(SHOT_PATH)
                info["saved"] = SHOT_PATH
                info["saved_bytes"] = os.path.getsize(SHOT_PATH)
            except Exception as exc:  # noqa: BLE001
                info["save_error"] = f"{type(exc).__name__}: {exc}"
        except Exception as exc:  # noqa: BLE001
            info["array_error"] = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001
        info["screencap_error"] = f"{type(exc).__name__}: {exc}"
        info["screencap_tb"] = traceback.format_exc()[-1500:]
    return info


step("controller", _controller)

print(json.dumps(R, indent=2, ensure_ascii=False, default=str))
