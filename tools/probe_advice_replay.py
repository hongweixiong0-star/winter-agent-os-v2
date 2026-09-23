"""Replay an existing AI answer on its own frame: which gate stops it, if any.

Read-only.  No device, no clicks, no writes.

Why this exists.  Operator directive 2026-09-23 §一 asks for one real AUTO answer to be traced
through "answer returns -> the task resumes -> the brain adopts it -> the target is located on the
current frame -> MAA executes -> the after-frame verifies".  Before fixing anything, the chain has to
be audited for **its first actual break point**, and the two candidates are structurally different:

* the answer is never reached (the consumption site is not entered with that request id), or
* the answer is reached and refused by one of the gates the directive itself demands
  (wrong screen / no measured grounding / refused risk).

This tool tells the two apart by running ``LiveRuntime._advised_control`` on the frame the question
was asked about, with the real answer on disk, and then reporting every gate's own verdict as well as
the point the method would have returned.

Usage:
    python tools/probe_advice_replay.py                 # every request that has an answer
    python tools/probe_advice_replay.py --request unknown__control__b6546e80
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_OUT = ROOT / "dataset/truth_audit/advice_execution_20260923"
ANSWERS_DIR = "answers"


def _ocr():
    from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    return OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))


def _runtime(ocr):
    """The resolver as the live loop calls it, without a device (same shape as the suite's)."""
    from winter_agent_v2 import page_knowledge, ui_collection, unknown_advisor
    from winter_agent_v2.runtime import LiveRuntime
    from winter_agent_v2.skills import v2_registry

    runtime = object.__new__(LiveRuntime)
    runtime.vision = SimpleNamespace(ocr=ocr)
    runtime.semantic_vision = SimpleNamespace(ocr=None)
    runtime.registry = v2_registry()
    runtime._control_ledger = {}
    runtime._remembered_reuse = []
    runtime._printed_remembered = set()
    runtime._printed_reads = []
    runtime._printed_printed = set()
    runtime._printed_boxes = {}
    runtime._l1_frame_hint = ""
    runtime.MAX_ORDINARY_ATTEMPTS = 2
    runtime._ordinary_attempts = 0
    runtime._ordinary_tried = set()
    runtime._ordinary_last = None
    runtime._l1_context = None
    runtime._last_known_label = ""
    runtime._last_advice = None
    runtime._last_attempt_summary = {}
    runtime._advisor = unknown_advisor.UnknownAdvisor(root=ROOT / unknown_advisor.REQUEST_ROOT)
    runtime._transitions = None
    runtime._ui_pages = None
    runtime._ui_candidates = ui_collection.UiCandidateStore(
        root=ROOT / "knowledge/perception/candidates", manifest=ROOT / "dataset/candidate/template_manifest.json"
    )
    runtime.brain = SimpleNamespace(current_goal="", goal_id="")
    return runtime


def _answered(advisor) -> list[str]:
    answers = Path(advisor.root) / ANSWERS_DIR
    return sorted(p.stem for p in answers.glob("*.json") if not p.name.endswith(".rejected.json"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", action="append", default=[], help="only these request ids")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    from winter_agent_v2 import page_knowledge, ui_collection, unknown_advisor

    advisor = unknown_advisor.UnknownAdvisor(root=ROOT / unknown_advisor.REQUEST_ROOT)
    ids = args.request or _answered(advisor)
    if not ids:
        print("no answered request on disk -- nothing to replay")
        return 0

    ocr = _ocr()
    report: dict = {"generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                    "answer_root": str(Path(advisor.root) / ANSWERS_DIR), "cases": []}

    for request_id in ids:
        request = advisor.read_request(request_id)
        case: dict = {"request_id": request_id}
        if request is None:
            case["error"] = "the request file is gone; the answer has nothing to be matched against"
            report["cases"].append(case)
            print(f"=== {request_id}: {case['error']}")
            continue
        frame = Path(str(request.frame_path))
        case.update({
            "asked_on": str(request.created_at),
            "page_key": str(request.page_key),
            "goal_at_ask_time": str(request.goal),
            "frame": str(frame),
            "frame_exists": frame.exists(),
        })
        print(f"=== {request_id}")
        print(f"    asked {case['asked_on']} about {case['page_key']} (goal {case['goal_at_ask_time']})")

        if not frame.exists():
            case["error"] = "the frame the question was asked about is gone"
            report["cases"].append(case)
            print(f"    {case['error']}")
            continue

        from winter_agent_v2.ocr import HybridVision
        from winter_agent_v2.vision import SemanticWorldVision

        vision = HybridVision(SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json"), ocr)
        world = vision.observe(frame)
        title = ""
        try:
            size = None
            from winter_agent_v2.ocr import read_frame_size
            size = read_frame_size(frame)
            info = page_knowledge.read_title_candidate(frame, ocr, size) if size else None
            title = str((info or {}).get("text") or "")
        except (OSError, ValueError):
            pass
        page = str(getattr(world.page, "value", world.page))
        if world.known:
            page_label, title = page, ""
        else:
            page_label = "UNKNOWN"
        key = page_knowledge.page_key(page_label, title)
        case.update({"page_now": page_label, "title_now": title, "page_key_now": key,
                     "request_id_now": unknown_advisor.request_id(key, unknown_advisor.UNKNOWN_CONTROL),
                     "id_matches_the_answer": unknown_advisor.request_id(
                         key, unknown_advisor.UNKNOWN_CONTROL) == request_id})

        runtime = _runtime(ocr)
        runtime.brain = SimpleNamespace(current_goal=str(request.goal or ""), goal_id="")
        regions, boxes, texts, note = runtime._advice_evidence(page_label, frame, ocr)
        advice = advisor.take(unknown_advisor.request_id(key, unknown_advisor.UNKNOWN_CONTROL),
                              registry=runtime.registry)
        case.update({
            "advice_taken": advice is not None,
            "grounding_basis": str(getattr(advice, "grounding_basis", "")),
            "target_anchor": dict(getattr(advice, "target_anchor", {}) or {}),
            "proposed_action": str(getattr(advice, "proposed_action", "")),
            "frame_regions": len(regions),
            "frame_texts": len(texts),
        })
        print(f"    today the frame reads {page_label} / title {title!r} -> request_id "
              f"{case['request_id_now']}")
        print(f"    the answer is taken: {case['advice_taken']}   (regions on this frame: {len(regions)})")

        if advice is not None:
            stale = unknown_advisor.advice_staleness(
                advice, request, page_key=key, goal=str(request.goal or "")
            )
            anchor_region = None
            anchor_point = None
            if advice.target_anchor:
                anchor_region = ui_collection.anchored_region(advice.target_anchor, regions)
            if anchor_region is not None:
                box = anchor_region.get("box_norm") or {}
                anchor_point = (
                    float(box.get("x_norm", 0.0)) + float(box.get("w_norm", 0.0)) / 2,
                    float(box.get("y_norm", 0.0)) + float(box.get("h_norm", 0.0)) / 2,
                )
            region = unknown_advisor.grounded_region(
                advice, regions, points=[anchor_point] if anchor_point else (),
            )
            risk = runtime._advice_risk(advice, region) if region is not None else ""
            case.update({
                "staleness": str(stale or ""),
                "anchored_region": None if anchor_region is None else {
                    "box_norm": dict(anchor_region.get("box_norm") or {}),
                    "detail": dict(anchor_region.get("detail") or {}),
                },
                "grounded_region": None if region is None else {
                    "box_norm": dict(region.get("box_norm") or {}),
                    "basis": str(region.get("basis") or ""),
                    "text": str(region.get("text") or ""),
                },
                "risk_verdict": str(risk or ""),
            })
            print(f"    staleness: {case['staleness'] or '(fresh)'}")
            print(f"    anchor grounding: {case['anchored_region']}")
            print(f"    grounded region: {case['grounded_region']}")
            print(f"    risk: {case['risk_verdict'] or '(none refused)'}")

        # And then the method itself, which is the answer to "would the tap have happened".
        point = runtime._advised_control(page_label, title, frame, world, True,
                                        confidence=float(getattr(world, "confidence", 0.0) or 0.0))
        case["point"] = None if point is None else [round(float(point[0]), 4), round(float(point[1]), 4)]
        case["last_advice_set"] = runtime._last_advice is not None
        print(f"    _advised_control -> {case['point']}   (_last_advice set: {case['last_advice_set']})")
        report["cases"].append(case)
        print()

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", args.out / "replay.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
