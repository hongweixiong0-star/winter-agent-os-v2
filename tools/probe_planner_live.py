"""One real planner step on the real client: which acceptance level does it reach?

Operator directive 2026-09-25 sections 6–8 and 11.  The four levels are kept apart because they
are separately earned:

    STRUCTURED_OUTPUT_PASS   the model returned a plan that parses and validates
    MAA_EXECUTION_PASS       MAA located the element on the current frame and issued the action
    GOAL_VERIFIED            the project's own verifier confirmed the goal's state changed
    SKILL_REUSABLE           the verified flow was filed as a declarative candidate

This probe reaches the first two on a real screen and stops there.  It does not choose a goal and
it does not claim a verifier result.

How it stays honest about "the point came from the current frame"
-----------------------------------------------------------------
* the element table is read off the frame by the project's own OCR (``ui_collection``), not typed in;
* the model never sees a position -- it names an element id (``ui_planner.FORBIDDEN_KEYS`` refuses
  a reply that tries), so the anchor it produces is the client's own printed words;
* the point is then produced by ``unknown_advisor.grounded_region`` against the **same frame**, and
  the risk screen (``_advice_risk``) is applied to the candidate before anything is tapped;
* the runtime is the stub shape the project's own replay probes use (``probe_advice_replay``), so
  the method under test is the production ``_advised_control`` rather than a copy of it.

Usage:
    python tools/probe_planner_live.py --goal DAILY_ROUTINE
    python tools/probe_planner_live.py --goal DAILY_ROUTINE --execute
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_OUT = ROOT / "dataset/truth_audit/local_planner_live"


def _ocr():
    from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    return OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))


def _runtime(ocr, advisor):
    """The resolver as the live loop calls it, with the planner as its advisor.

    Same construction as ``tools/probe_advice_replay.py``: the method under test is the production
    ``LiveRuntime._advised_control``, and the only thing swapped is *who answers*.
    """
    from winter_agent_v2 import ui_collection
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
    runtime._advisor = advisor
    runtime._transitions = None
    runtime._ui_pages = None
    runtime._ui_candidates = ui_collection.UiCandidateStore(
        root=ROOT / "knowledge/perception/candidates",
        manifest=ROOT / "dataset/candidate/template_manifest.json",
    )
    runtime.brain = SimpleNamespace(current_goal="", goal_id="", ordinary_scan_exhausted=False)
    return runtime


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goal", default="DAILY_ROUTINE")
    parser.add_argument("--serial", default="")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--execute", action="store_true",
                        help="actually issue the tap through MAA (the point is always resolved first)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--config", default=str(ROOT / "config/v2.json"))
    args = parser.parse_args()

    from winter_agent_v2 import local_qwen, page_knowledge, ui_planner
    from winter_agent_v2.executor import Executor
    from winter_agent_v2.executor_router import build_maa_adapter
    from winter_agent_v2.models import Action
    from winter_agent_v2.ocr import HybridVision, read_frame_size
    from winter_agent_v2.vision import SemanticWorldVision

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "goal": args.goal, "execute_requested": bool(args.execute),
    }

    client = local_qwen.from_config(config, root=ROOT)
    if client is None:
        print("local_planner.enabled is false -- nothing to probe")
        return 3
    ok, reason = client.available(force=True)
    print(f"model      : {client.model} ({'reachable' if ok else reason})")
    report["model"] = client.model
    report["model_reachable"] = ok
    if not ok:
        return 2

    adapter = build_maa_adapter(config, production=True)
    if adapter is None or not adapter.available():
        print(f"MAA unavailable: {adapter.unavailable_reason if adapter else 'disabled by config'}")
        return 4
    status = adapter.status()
    print(f"device     : connected={status.connected} resolution={status.resolution} "
          f"foreground={adapter._foreground_package()}")
    report["device"] = {"connected": status.connected, "resolution": list(status.resolution or ()),
                        "foreground": adapter._foreground_package()}
    if not status.connected:
        print("device not connected -- start MuMu and the client first")
        return 4

    args.out.mkdir(parents=True, exist_ok=True)
    before = args.out / "before_frame.png"
    if not adapter.screenshot(before):
        print("MAA could not write a frame")
        return 5
    print(f"frame      : {before} (capture={adapter.capture_backend})")

    ocr = _ocr()
    vision = HybridVision(SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json"), ocr)
    world = vision.observe(before)
    title = ""
    try:
        size = read_frame_size(before)
        info = page_knowledge.read_title_candidate(before, ocr, size) if size else None
        title = str((info or {}).get("text") or "")
    except (OSError, ValueError):
        pass
    page = str(getattr(world.page, "value", world.page))
    page_label = page if world.known else "UNKNOWN"
    if world.known:
        title = ""
    print(f"page       : {page_label} title={title!r} confidence={world.confidence}")
    report["page"] = {"label": page_label, "title": title, "confidence": float(world.confidence or 0.0)}

    planner = ui_planner.ManagedAdvisor(
        client=client,
        ledger=ui_planner.PlannerLedger(ROOT / "learning/local_planner_steps.jsonl"),
        root=ROOT, max_steps_per_run=1, max_steps_per_screen=1,
    )
    runtime = _runtime(ocr, planner)
    runtime.brain = SimpleNamespace(current_goal=args.goal, goal_id="", ordinary_scan_exhausted=False)

    regions, _boxes, texts, note = runtime._advice_evidence(page_label, before, ocr)
    print(f"elements   : {len(regions)} region(s) / {len(texts)} text(s) on this frame")
    report["frame_elements"] = {"regions": len(regions), "texts": len(texts),
                               "sample": [str(t) for t in list(texts)[:12]]}

    point = runtime._advised_control(page_label, title, before, world, True,
                                     confidence=float(getattr(world, "confidence", 0.0) or 0.0))
    plan_outcome = dict(getattr(planner, "last_outcome", {}) or {})
    print("-" * 78)
    print(f"plan       : {json.dumps(plan_outcome, ensure_ascii=False)}")
    report["plan"] = plan_outcome
    report["point"] = None if point is None else [round(float(point[0]), 4), round(float(point[1]), 4)]
    report["advice_used"] = dict(runtime._last_advice or {}) if runtime._last_advice else None

    if point is None:
        print("RESULT     : no tappable point this step -> see the plan's decision/error above")
        print("             (every step is filed in learning/local_planner_steps.jsonl)")
        (args.out / "live.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
        return 6

    semantic = str((runtime._ordinary_last or {}).get("semantic") or "")
    print(f"resolved   : {semantic!r} at {point[0]:.4f},{point[1]:.4f} "
          f"basis={(runtime._ordinary_last or {}).get('basis')}")
    report["semantic"] = semantic
    report["basis"] = str((runtime._ordinary_last or {}).get("basis") or "")
    report["structured_output_pass"] = True
    report["maa_located_on_current_frame"] = True

    if not args.execute:
        print("STRUCTURED_OUTPUT_PASS + element located on the current frame (no tap issued)")
        (args.out / "live.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
        return 0

    # The MAA executor exactly as ``build_router`` builds it: same class, same adapter, same
    # backend stamp.  ``production=True`` with ``dry_run=False`` is the pair that unlocks a real
    # device action, and it is why this branch only runs behind an explicit flag.
    executor = Executor(production=True, dry_run=False, device=adapter,
                        target_resolver=lambda _semantic: point, backend="MAA")
    result = executor.execute(Action("TAP_SEMANTIC", semantic))
    print(f"executed   : executed={result.executed} backend={result.backend} "
          f"error={result.error} tap={result.tap_point} latency={result.latency_ms}ms")
    report["execution"] = {
        "executed": bool(result.executed), "backend": result.backend, "error": result.error,
        "tap_point": list(result.tap_point) if result.tap_point else None,
        "latency_ms": result.latency_ms,
    }
    if result.executed:
        report["maa_execution_pass"] = True
        after = args.out / "after_frame.png"
        adapter.screenshot(after)
        print(f"after frame: {after}")
        # The verdict is the project's own, taken from the table the runtime dispatches from --
        # not this probe's opinion about what a page ought to look like now.
        from winter_agent_v2.runtime import LiveRuntime

        verdict = None
        verifier = LiveRuntime.VERIFIED_ATOMIC.get("TRY_ORDINARY_CONTROL")
        if verifier is not None:
            world_after = vision.observe(after)
            verdict = verifier(world, world_after)
            report["after"] = {
                "page_before": page_label,
                "page_after": str(getattr(world_after.page, "value", world_after.page)),
                "confidence_after": float(getattr(world_after, "confidence", 0.0) or 0.0),
            }
            report["verifier"] = {
                "name": getattr(verifier, "__name__", "?"),
                "ok": bool(getattr(verdict, "ok", verdict)),
                "reason": str(getattr(verdict, "reason", "") or ""),
            }
            print(f"verifier   : {report['verifier']['name']} ok={report['verifier']['ok']} "
                  f"reason={report['verifier']['reason']!r}")
            print(f"page       : {page_label} -> {report['after']['page_after']}")
            if report["verifier"]["ok"]:
                report["state_changed_and_verified"] = True
        else:
            print("verifier   : TRY_ORDINARY_CONTROL has no bound verifier -- nothing to judge with")

    (args.out / "live.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    print(f"wrote {args.out / 'live.json'}")
    return 0 if result.executed else 7


if __name__ == "__main__":
    raise SystemExit(main())
