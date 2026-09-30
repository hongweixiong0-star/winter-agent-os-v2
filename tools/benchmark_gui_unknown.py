"""GUI_UNKNOWN_BENCHMARK: what the local GUI model actually does on real UNKNOWN screens.

Operator directive 2026-09-30, "离线Benchmark".  The cases are **real production evidence**,
not authored examples: every one is a ``learning/unknown_requests/*.json`` record with the frame
it was filed with, so each row is a screen the live system genuinely could not advance.

What is measured, and what is deliberately not
----------------------------------------------
Four of the six metrics the directive names can be measured against evidence that already
exists, and they are:

``INVALID_ACTION_RATE``
    Share of replies the production ``parse_plan`` refused.  Objective: the refusal reasons are
    the parser's own.
``SAFE_DEFER_RATE``
    Share of *valid* replies that decided not to tap (OBSERVE/REPLAN/DEFER/BLOCKED/COMPLETE).
    Objective, and the right first question about a GUI agent: does it know when to stop?
``ELEMENT_ID_VALIDITY``
    Share of element-naming plans whose id this frame really produced.  Objective, and it is
    the element path's whole guarantee.
``BBOX_HIT_RATE``
    Share of region proposals that survive ``unknown_advisor.justified_point`` against **this
    frame's own** OCR boxes -- i.e. that a current-frame region actually sits under.  This is
    the exact gate the runtime uses before a tap, so the number means what it says.

``PAGE_UNDERSTANDING_ACC`` and ``SEMANTIC_TARGET_ACC`` are reported as ``NOT_MEASURED`` with a
reason.  Both need ground-truth labels ("the right next control on this screen is X"), and this
corpus has none: an UNKNOWN request records that the system did *not* know the screen.  A number
produced by grading a model against its own output would be worse than no number, so the tool
refuses to print one.  The directive itself says not to run a large manual annotation project,
and this is the honest consequence of that.

Usage::

    python tools/benchmark_gui_unknown.py                 # every case with a readable frame
    python tools/benchmark_gui_unknown.py --limit 5
"""

from __future__ import annotations

import argparse
import glob
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import local_gui_model, ui_planner, unknown_advisor  # noqa: E402

REQUESTS_GLOB = str(ROOT / "learning" / "unknown_requests" / "*.json")
OUT_PATH = ROOT / "dataset" / "truth_audit" / "gui_unknown_benchmark" / "benchmark.json"


def _vram_mib() -> int | None:
    """Used VRAM, or ``None`` when nvidia-smi is not available.

    Through ``winproc`` like every other child process in this tree: a benchmark that flashes a
    console over the game is a benchmark the operator has to stop, and the project keeps one
    decision about consoles rather than one per tool.
    """
    from winter_agent_v2 import winproc

    try:
        out = winproc.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            timeout=10.0)
        return int(out.stdout.strip().splitlines()[0])
    except Exception:  # noqa: BLE001
        return None


def _regions_from_request(request) -> list[dict]:
    """This frame's own measured regions, in the shape ``justified_point`` expects.

    The OCR boxes ARE the frame's evidence -- they are what the runtime itself passes as
    ``regions`` -- so reusing them here means the benchmark scores against exactly the gate
    production uses, not a re-implementation of it.
    """
    regions: list[dict] = []
    boxes = list(getattr(request, "ocr_boxes", ()) or ())
    for box in boxes:
        if not isinstance(box, dict):
            continue
        try:
            values = {k: float(box[k]) for k in ("x_norm", "y_norm", "w_norm", "h_norm")}
        except (KeyError, TypeError, ValueError):
            continue
        if values["w_norm"] <= 0 or values["h_norm"] <= 0:
            continue
        regions.append({
            "box_norm": values,
            "point": (round(values["x_norm"] + values["w_norm"] / 2, 4),
                      round(values["y_norm"] + values["h_norm"] / 2, 4)),
        })
    return regions


def _cases(limit: int | None) -> list:
    cases = []
    for path in sorted(glob.glob(REQUESTS_GLOB)):
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        request = unknown_advisor.UnknownRequest(**{
            key: value for key, value in payload.items()
            if key in unknown_advisor.UnknownRequest.__dataclass_fields__
        })
        for attr in ("ocr_texts", "ocr_boxes"):
            setattr(request, attr, tuple(getattr(request, attr) or ()))
        frame = str(getattr(request, "frame_path", "") or "")
        if not frame or not Path(frame).exists():
            continue
        cases.append(request)
    return cases[:limit] if limit else cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", default=str(OUT_PATH))
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    config = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
    client = local_gui_model.from_config(config, root=ROOT)
    if client is None:
        print("local_planner.enabled is false -- nothing to benchmark")
        raise SystemExit(3)
    ok, reason = client.available(force=True)
    if not ok:
        print(f"model unreachable: {reason}")
        raise SystemExit(4)

    cases = _cases(args.limit or None)
    rows: list[dict] = []
    vram_before = _vram_mib()
    vram_peak = vram_before or 0

    for index, request in enumerate(cases, start=1):
        elements = ui_planner.elements_from_request(request)
        packet = ui_planner.build_packet(
            goal=str(getattr(request, "goal", "") or ""),
            role_id=str(getattr(request, "character", "") or ""),
            current_page=str(getattr(request, "page_key", "") or ""),
            world_state=getattr(request, "world_state", {}) or {},
            elements=elements,
            actions=ui_planner.OFFERED_ACTIONS,
            remaining_steps=2,
        )
        call = client.ask_json(
            system=ui_planner.SYSTEM_PROMPT, user=ui_planner.render_packet(packet),
            purpose="benchmark", element_count=len(elements),
            image_path=getattr(request, "frame_path", None), timeout_s=args.timeout,
        )
        sampled = _vram_mib()
        if sampled:
            vram_peak = max(vram_peak, sampled)

        parsed = ui_planner.parse_plan(call.text, elements=elements) if call.ok else None
        plan = parsed.plan if parsed and parsed.ok else None
        row: dict = {
            "case": index,
            "request_id": str(getattr(request, "request_id", "") or ""),
            "page_key": str(getattr(request, "page_key", "") or ""),
            "goal": str(getattr(request, "goal", "") or ""),
            "elements_on_screen": len(elements),
            "model_ok": bool(call.ok),
            "error": call.error,
            "latency_ms": call.latency_ms,
            "image_sent": call.image_sent,
            "image_bytes": call.image_bytes,
            "decision": plan.decision if plan else "",
            "basis": plan.basis if plan else "",
            "target_element_id": plan.target_element_id if plan else "",
            "semantic_target": plan.semantic_target if plan else "",
            "confidence": plan.confidence if plan else 0.0,
            "parse_error": ("" if parsed is None else parsed.error),
            "raw": (call.text or "")[:400],
        }
        if plan and plan.basis == ui_planner.BASIS_VISION_PROPOSAL:
            # The scoring reuses the production translation and the production gate rather than
            # a copy of them, so "grounded" here means exactly what it means before a tap.
            # The ledger is a scratch path and is never appended to on this route.
            advisor = ui_planner.ManagedAdvisor(
                client=client, ledger=ui_planner.PlannerLedger(ROOT / "learning" / "_bench_scratch.jsonl"),
                root=ROOT)
            advice = advisor._advice_for(plan, request, elements, row["request_id"])
            row["vision_grounded"] = bool(
                advice is not None and unknown_advisor.justified_point(
                    advice, _regions_from_request(request)) is not None)
        rows.append(row)
        print(f"[{index}/{len(cases)}] {row['page_key'][:34]:34} "
              f"model_ok={row['model_ok']} decision={row['decision'] or '-':8} "
              f"basis={row['basis'] or '-':32} {row['latency_ms']:.0f}ms "
              f"{('ERR:' + row['error']) if row['error'] else ''}"
              f"{('REFUSED:' + row['parse_error']) if row['parse_error'] else ''}")

    answered = [r for r in rows if r["model_ok"]]
    valid = [r for r in answered if not r["parse_error"]]
    element_plans = [r for r in valid if r["basis"] == ui_planner.BASIS_ELEMENT
                     and r["decision"] == "EXECUTE"]
    vision_plans = [r for r in valid if r["basis"] == ui_planner.BASIS_VISION_PROPOSAL]
    latencies = sorted(r["latency_ms"] for r in rows if r["model_ok"] and r["latency_ms"])

    def rate(numerator: int, denominator: int) -> float | None:
        return None if not denominator else round(numerator / denominator, 4)

    def pct(values: list[float], q: float) -> float | None:
        if not values:
            return None
        index = min(len(values) - 1, int(round(q * (len(values) - 1))))
        return round(values[index], 1)

    metrics = {
        "cases": len(rows),
        "model_answered": len(answered),
        "MODEL_ANSWER_RATE": rate(len(answered), len(rows)),
        "INVALID_ACTION_RATE": rate(len(answered) - len(valid), len(answered)),
        "SAFE_DEFER_RATE": rate(sum(1 for r in valid if r["decision"] != "EXECUTE"), len(valid)),
        "ELEMENT_ID_VALIDITY": rate(
            sum(1 for r in element_plans if r["target_element_id"]), len(element_plans)),
        "BBOX_HIT_RATE": rate(
            sum(1 for r in vision_plans if r.get("vision_grounded")), len(vision_plans)),
        "element_plans": len(element_plans),
        "vision_proposals": len(vision_plans),
        "PAGE_UNDERSTANDING_ACC": "NOT_MEASURED",
        "PAGE_UNDERSTANDING_ACC_reason": (
            "needs ground-truth page labels; an UNKNOWN request records that the system did not "
            "know the page, so there is nothing to grade against"),
        "SEMANTIC_TARGET_ACC": "NOT_MEASURED",
        "SEMANTIC_TARGET_ACC_reason": (
            "needs a labelled correct control per screen; none exists in this corpus and the "
            "directive rules out building one by hand"),
        "LATENCY_P50_MS": pct(latencies, 0.5),
        "LATENCY_P95_MS": pct(latencies, 0.95),
        "LATENCY_MIN_MS": (round(latencies[0], 1) if latencies else None),
        "LATENCY_MAX_MS": (round(latencies[-1], 1) if latencies else None),
        "LATENCY_MEAN_MS": (round(statistics.fmean(latencies), 1) if latencies else None),
        "VRAM_USED_MIB_BEFORE": vram_before,
        "VRAM_USED_MIB_PEAK": vram_peak or None,
    }

    report = {
        "what_this_is": ("the local GUI model answering the real UNKNOWN screens this system "
                         "actually failed to advance, scored against the production parser and "
                         "the production grounding gate"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": {"provider": client.provider, "model": client.model,
                  "quantization": client.quantization, "endpoint": client.endpoint,
                  "multimodal": client.multimodal},
        "metrics": metrics,
        "rows": rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("\n" + json.dumps(metrics, indent=2, ensure_ascii=False))
    print("written:", out)


if __name__ == "__main__":
    main()
