"""Probe #3: exact API surface + screencap latency A/B (MAA native vs adb exec-out).

Never guess a signature again: print the real ones.
"""
from __future__ import annotations

import inspect
import json
import time
import traceback

R: dict = {"probe": "maa_api2"}


def sig(obj, names):
    out = {}
    for n in names:
        if not hasattr(obj, n):
            out[n] = "<MISSING>"
            continue
        fn = getattr(obj, n)
        try:
            out[n] = str(inspect.signature(fn))
        except Exception:  # noqa: BLE001
            out[n] = f"<no sig: {type(fn).__name__}>"
    return out


# ---- enums / define
def _define():
    from maa import define
    out = {}
    for en in [
        "MaaAdbScreencapMethodEnum", "MaaAdbInputMethodEnum", "MaaCtrlOptionEnum",
        "MaaStatusEnum", "JRecognitionType", "JActionType", "LoggingLevelEnum",
        "MaaControllerFeatureEnum",
    ]:
        cls = getattr(define, en, None)
        if cls is None:
            out[en] = "<MISSING>"
            continue
        try:
            out[en] = {m.name: int(m.value) for m in cls}
        except Exception as exc:  # noqa: BLE001
            out[en] = f"{type(exc).__name__}: {exc}"
    out["defines_extra"] = [n for n in dir(define) if n.startswith("Maa")]
    return out


R["define"] = {}
try:
    R["define"] = _define()
except Exception as exc:  # noqa: BLE001
    R["define"] = {"ERROR": f"{type(exc).__name__}: {exc}", "tb": traceback.format_exc()[-800:]}

# ---- class signatures
try:
    from maa.controller import AdbController
    from maa.resource import Resource
    from maa.tasker import Tasker
    from maa.toolkit import Toolkit

    R["AdbController"] = sig(AdbController, [
        "__init__", "post_connection", "post_click", "post_swipe", "post_press_key",
        "post_input_text", "post_screencap", "post_start_app", "post_stop_app",
        "post_touch_down", "post_touch_move", "post_touch_up", "connected",
        "cached_image", "set_option", "get_option", "post_scroll",
    ])
    R["Tasker"] = {}
    for n in dir(Tasker):
        if n.startswith("_"):
            continue
        fn = getattr(Tasker, n)
        if callable(fn):
            R["Tasker"][n] = sig(Tasker, [n])[n]
        else:
            R["Tasker"][n] = f"<attr {type(fn).__name__}>"
    R["Resource"] = {}
    for n in dir(Resource):
        if n.startswith("_"):
            continue
        fn = getattr(Resource, n)
        if callable(fn):
            R["Resource"][n] = sig(Resource, [n])[n]
        else:
            R["Resource"][n] = f"<attr {type(fn).__name__}>"
    R["Toolkit_static"] = {}
    for n in dir(Toolkit):
        if n.startswith("_"):
            continue
        fn = getattr(Toolkit, n)
        if callable(fn):
            R["Toolkit_static"][n] = sig(Toolkit, [n])[n]
except Exception as exc:  # noqa: BLE001
    R["class_sig_error"] = f"{type(exc).__name__}: {exc}"
    R["class_sig_tb"] = traceback.format_exc()[-1500:]

# ---- Job / result types
try:
    from maa.resource import Job, JobWithResult
    R["Job"] = sig(Job, ["wait", "status", "get", "done", "succeeded", "failed"])
except Exception as exc:  # noqa: BLE001
    R["Job"] = {"ERROR": f"{type(exc).__name__}: {exc}"}

# ---- latency A/B: MAA screencap vs adb exec-out screencap
MUMU_ADB = r"D:\Program Files\Netease\MuMu Player 12\nx_main\adb.exe"
try:
    import subprocess

    def adb_screencap(n=5):
        ts = []
        for _ in range(n):
            t0 = time.perf_counter()
            p = subprocess.run(
                [MUMU_ADB, "-s", "127.0.0.1:7555", "exec-out", "screencap", "-p"],
                capture_output=True,
            )
            ts.append(time.perf_counter() - t0)
        return {"n": n, "bytes": len(p.stdout), "ms": [round(t * 1000, 1) for t in ts],
                "mean_ms": round(sum(ts) / len(ts) * 1000, 1)}

    R["adb_screencap"] = adb_screencap()

    det = Toolkit.find_adb_devices()
    dev = det[0]
    ctrl = AdbController(
        adb_path=dev.adb_path,
        address="127.0.0.1:7555",
        screencap_methods=dev.screencap_methods,
        input_methods=dev.input_methods,
        config=dev.config,
    )
    R["ctrl_connect"] = ctrl.post_connection().wait().succeeded

    def maa_screencap(n=5):
        ts = []
        for _ in range(n):
            t0 = time.perf_counter()
            job = ctrl.post_screencap().wait()
            ts.append(time.perf_counter() - t0)
            if not job.succeeded:
                return {"error": "screencap job failed"}
        return {"n": n, "ms": [round(t * 1000, 1) for t in ts],
                "mean_ms": round(sum(ts) / len(ts) * 1000, 1)}

    R["maa_screencap"] = maa_screencap()
    R["screencap_methods_used"] = dev.screencap_methods
    R["screencap_method_names"] = [
        m.name for m in __import__("maa").define.MaaAdbScreencapMethodEnum
        if dev.screencap_methods & int(m.value)
    ]
    R["input_method_names"] = [
        m.name for m in __import__("maa").define.MaaAdbInputMethodEnum
        if dev.input_methods & int(m.value)
    ]
except Exception as exc:  # noqa: BLE001
    R["latency_ab"] = {"ERROR": f"{type(exc).__name__}: {exc}", "tb": traceback.format_exc()[-1500:]}

print(json.dumps(R, indent=2, ensure_ascii=False, default=str))
