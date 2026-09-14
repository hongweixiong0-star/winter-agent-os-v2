"""Minimal: is MaaFramework's recognition cache returning a stale result?

Symptom under test: the migration harness reported the SAME score (e.g.
0.162466) for every frame in a case, including a frame whose template is a
verbatim sub-array of it (which self-matches at 1.0 in isolation).  Identical
scores across different frames means the matcher is not looking at the frames.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maa.controller import AdbController  # noqa: E402
from maa.pipeline import JRecognitionType, JTemplateMatch  # noqa: E402
from maa.resource import Resource  # noqa: E402
from maa.tasker import Tasker  # noqa: E402
from maa.toolkit import Toolkit  # noqa: E402

T = ROOT / "dataset/truth_audit"
FRAMES = [
    T / "hero_fight_final_20260914/00_before.png",
    T / "fight_why_20260914/10_map.png",
    T / "hero_fight_seq_20260914/03_squad.png",
]
TPL = ROOT / "dataset/candidate/hero_camp/btn_hero_fight__live_squad.png"

dev = Toolkit.find_adb_devices()[0]
ctrl = AdbController(adb_path=dev.adb_path, address="127.0.0.1:7555",
                     screencap_methods=dev.screencap_methods,
                     input_methods=dev.input_methods, config=dev.config)
ctrl.post_connection().wait()

tpl = np.array(Image.open(TPL).convert("RGB"))
arrays = [(f.name, np.array(Image.open(f).convert("RGB"))) for f in FRAMES]

R: dict = {}


def score_of(detail):
    nodes = getattr(detail, "nodes", None) or []
    if not nodes:
        return {"nodes": 0}
    reco = getattr(nodes[0], "recognition", None)
    if reco is None:
        return {"reco": None}
    best = getattr(reco, "best_result", None)
    s = getattr(best, "score", None) if best is not None else None
    box = getattr(reco, "box", None)
    return {"hit": bool(getattr(reco, "hit", False)), "score": s,
            "box": None if box is None else [int(box.x), int(box.y), int(box.w), int(box.h)]}


def sweep(label, *, cache_limit=None, reuse_tasker=True, rebuild_per_frame=False):
    rows = []
    tasker = None
    for name, arr in arrays:
        if tasker is None or rebuild_per_frame:
            res = Resource()
            res.override_image("BTN_HERO_FIGHT", tpl)
            tasker = Tasker()
            tasker.bind(res, ctrl)
            if cache_limit is not None:
                Tasker.set_reco_image_cache_limit(cache_limit)
        param = JTemplateMatch(template=["BTN_HERO_FIGHT"], roi=(0, 0, 0, 0),
                               threshold=[0.6], method=5)
        detail = tasker.post_recognition(JRecognitionType.TemplateMatch, param, arr).wait().get()
        rows.append({"frame": name, **score_of(detail)})
    R[label] = rows


sweep("1_shared_tasker_default_cache", reuse_tasker=True)
sweep("2_shared_tasker_cache_0", cache_limit=0, reuse_tasker=True)
sweep("3_fresh_tasker_per_frame", rebuild_per_frame=True)

print(json.dumps(R, indent=2, ensure_ascii=False, default=str))
