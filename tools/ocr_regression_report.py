# -*- coding: utf-8 -*-
"""OCR production regression: RapidOCR path for routing OCR nodes on real frames.

Runs the production node shapes (kind=OCR) through _rapid_ocr_results on their
recorded positive frames + negative pages, writing tokens/bbox/score/result to
learning/ocr_regression_20260926.json.  Doctrine: text -> RapidOCR; MAA OCR is
gone, so every OCR node must resolve through this path.
"""
import json
import sys
from pathlib import Path
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from winter_agent_v2.executor_router import _rapid_ocr_results  # noqa: E402

routing = json.loads((ROOT / "knowledge/execution/backend_routing.json").read_text(encoding="utf-8"))

CASES = [
    ("DISPATCH_MARCH", "BTN_DISPATCH", "dataset/raw/control_panel/runtime_auto/20260926_055529_646039/20260926_055529_646039_step_004_after_20260925T215703933109.png"),
    ("RESEARCH", "BTN_START_RESEARCH", "dataset/raw/control_panel/runtime_auto/20260926_203129_111901/20260926_203129_111901_step_015_after_20260926T123730329502.png"),
    ("OPEN_BEAR_RALLY_LIST", "BTN_WAR_TAB_RALLY", "dataset/raw/autogen/r14_war.png"),
]
NEGATIVE_FRAMES = [
    "dataset/raw/autogen/20260925_182249_home.png",
    "dataset/raw/control_panel/runtime_auto/20260926_233019_274984/20260926_233019_274984_step_022_after_20260926T153755459479.png",
]


def main() -> None:
    report = {"positive": [], "negative": []}
    for skill, sem, frame in CASES:
        node = ((routing["skills"].get(skill) or {}).get("recognition") or {}).get(sem) or {}
        path = ROOT / frame
        if not node or not path.is_file():
            report["positive"].append({"semantic": sem, "result": "MISSING_NODE_OR_FRAME", "frame": frame})
            continue
        roi = tuple(node["roi"]) if node.get("roi") else None
        arr = np.asarray(Image.open(path))
        res = _rapid_ocr_results(arr, roi, list(node.get("expected") or []))
        best = max(res, key=lambda r: float(r.get("score", 0) or 0)) if res else None
        report["positive"].append({
            "semantic": sem, "skill": skill, "kind": node.get("kind"), "roi": node.get("roi"),
            "frame": frame, "hit": bool(best),
            "text": (best or {}).get("text"), "bbox": (best or {}).get("box"),
            "score": round(float((best or {}).get("score", 0) or 0), 3),
            "tokens_in_roi": len(res),
            "result": "RESOLVED" if best else "NO_MATCH",
        })
    for frame in NEGATIVE_FRAMES:
        path = ROOT / frame
        if not path.is_file():
            continue
        toks = _rapid_ocr_results(np.asarray(Image.open(path)), None, [])
        text = " ".join(t["text"] for t in toks)
        for skill, sem, _ in CASES:
            node = ((routing["skills"].get(skill) or {}).get("recognition") or {}).get(sem) or {}
            for exp in node.get("expected") or []:
                report["negative"].append({
                    "frame": frame, "semantic": sem, "expected": exp,
                    "word_on_negative_page": exp in text,
                })
    out = ROOT / "learning/ocr_regression_20260926.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
