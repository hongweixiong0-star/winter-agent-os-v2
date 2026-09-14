"""Probe #4: recognition/action param objects + result-reading surface."""
from __future__ import annotations

import json
import traceback

R: dict = {}


def dump_cls(mod_name, cls_name, report):
    try:
        mod = __import__(mod_name, fromlist=["*"])
        cls = getattr(mod, cls_name, None)
        if cls is None:
            report[cls_name] = "<MISSING>"
            return
        info = {"kind": type(cls).__name__}
        try:
            import dataclasses
            if dataclasses.is_dataclass(cls):
                info["is_dataclass"] = True
                info["fields"] = [
                    {"name": f.name, "type": str(f.type), "default": str(f.default)}
                    for f in dataclasses.fields(cls)
                ]
        except Exception as exc:  # noqa: BLE001
            info["dataclass_err"] = str(exc)
        ann = getattr(cls, "__annotations__", None)
        if ann:
            info["annotations"] = {k: str(v) for k, v in ann.items()}
        mem = [n for n in dir(cls) if not n.startswith("_")]
        info["members"] = mem[:60]
        report[cls_name] = info
    except Exception as exc:  # noqa: BLE001
        report[cls_name] = f"ERR {type(exc).__name__}: {exc}"


# --- maa.pipeline module map
try:
    import maa.pipeline as P
    R["pipeline_module_file"] = getattr(P, "__file__", "?")
    R["pipeline_top"] = [n for n in dir(P) if not n.startswith("_")]
except Exception as exc:  # noqa: BLE001
    R["pipeline_module"] = f"ERR {type(exc).__name__}: {exc}"

for group, names in {
    "pipeline": [
        "JRecognitionType", "JActionType", "JTemplateMatch", "JOCR", "JColorMatch",
        "JFeatureMatch", "JDirectHit", "JAnd", "JOr", "JClick", "JSwipe", "JDoNothing",
        "JLongPress", "JScroll", "JCustomRecognizer", "JCustomAction", "JNeuralNetworkDetect",
        "JPipelineData", "TemplateMatch",
    ],
    "define": [
        "RecognitionDetail", "TemplateMatchResult", "OCRResult", "ColorMatchResult",
        "FeatureMatchResult", "Rect", "BoxAndScoreResult", "NodeDetail", "TaskDetail",
        "ActionDetail", "AndRecognitionResult", "OrRecognitionResult",
    ],
}.items():
    R[group] = {}
    for n in names:
        dump_cls(f"maa.{group}", n, R[group])

# --- is JRecognitionType an enum? show members
for en in ["JRecognitionType", "JActionType"]:
    try:
        import maa.pipeline as P
        cls = getattr(P, en)
        R[f"{en}_members"] = {m.name: int(m.value) for m in cls}
    except Exception as exc:  # noqa: BLE001
        R[f"{en}_members"] = f"{type(exc).__name__}: {exc}"

# --- how to construct a JTemplateMatch
try:
    import maa.pipeline as P
    import inspect
    for n in ["JTemplateMatch", "JOCR", "JClick", "JColorMatch"]:
        cls = getattr(P, n)
        try:
            R.setdefault("ctor_sig", {})[n] = str(inspect.signature(cls))
        except Exception as exc:  # noqa: BLE001
            R.setdefault("ctor_sig", {})[n] = f"{type(exc).__name__}: {exc}"
except Exception as exc:  # noqa: BLE001
    R["ctor_sig"] = str(exc)

# --- TaskJob surface
try:
    import maa.job as J
    R["job_top"] = [n for n in dir(J) if not n.startswith("_")]
    for n in ["Job", "TaskJob", "JobWithResult"]:
        cls = getattr(J, n, None)
        if cls is None:
            R.setdefault("job_classes", {})[n] = "<MISSING>"
            continue
        R.setdefault("job_classes", {})[n] = [m for m in dir(cls) if not m.startswith("_")]
except Exception as exc:  # noqa: BLE001
    R["job_module"] = f"{type(exc).__name__}: {exc}"

print(json.dumps(R, indent=2, ensure_ascii=False, default=str))
