"""One operation, one id, every frame timed: why did this tap do nothing?

The previous round left a suspicion -- the HUD moves between recognising and tapping -- and this
measures it rather than assuming it.  A single run records, under one operation id:

    plan frame        the frame the element table was built from and the semantic the planner chose
    pre-tap frame     a *fresh* capture taken immediately before the tap, re-matched
    the tap           the coordinates MAA sent, and the wall-clock moment it was sent
    after-0 frame     captured immediately, before anything settles
    after-N frame     captured once the screen is stable

and also, without touching anything, a **drift series**: the same icon's position across frames
while the client is left alone.  That series is what separates "the icon moved" from "the tap was
wrong" -- two frames either side of a tap cannot tell them apart, which is exactly the reasoning
mistake the last round made.

Nothing here decides or clicks outside the existing executor: the tap goes through the project's
own ``Executor`` on the project's own MAA adapter, with the device lease the project already uses.

Usage:
    python tools/probe_live_operation.py --goal DAILY_ROUTINE --label 登录好礼
    python tools/probe_live_operation.py --drift-only --frames 10 --every 0.4
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_ROOT = ROOT / "dataset/truth_audit/live_ops"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Stop:
    def __init__(self) -> None:
        self.t0 = time.perf_counter()

    def at(self) -> dict[str, object]:
        return {"utc": _now(), "ms_since_start": round((time.perf_counter() - self.t0) * 1000.0, 1)}


def _ocr(config: dict):
    from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend

    return OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))


def _vision(ocr, config: dict):
    from winter_agent_v2.ocr import HybridVision
    from winter_agent_v2.vision import SemanticWorldVision

    return HybridVision(
        SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json"), ocr
    )


def locate_icon(frame_path: Path, label_box: dict, template: Path, size) -> dict | None:
    from winter_agent_v2 import ui_collection

    return ui_collection.registered_icon_region(
        frame_path, label_box, template_path=template, frame=size
    )


def find_label(ocr, frame_path: Path, label: str) -> dict | None:
    from winter_agent_v2 import ui_collection

    for region in ui_collection.grounding_regions(frame_path, ocr):
        if str(region.get("text") or "").strip() == label:
            return dict(region.get("box_norm") or {})
    return None


def _delta(before: Path, after: Path, box: dict | None) -> dict:
    """How much the frame changed, overall and inside the target region."""
    import numpy as np
    from PIL import Image

    try:
        a = np.asarray(Image.open(before).convert("L"), dtype=np.float32)
        b = np.asarray(Image.open(after).convert("L"), dtype=np.float32)
    except (OSError, ValueError):
        return {"frame_mean_abs": 0.0, "region_mean_abs": 0.0, "region_px": 0}
    whole = float(np.abs(a - b).mean())
    region = 0.0
    region_px = 0
    if box:
        height, width = a.shape[:2]
        x0 = int(float(box["x_norm"]) * width)
        y0 = int(float(box["y_norm"]) * height)
        x1 = int((float(box["x_norm"]) + float(box["w_norm"])) * width)
        y1 = int((float(box["y_norm"]) + float(box["h_norm"])) * height)
        x0, y0 = max(0, x0 - 10), max(0, y0 - 10)
        x1, y1 = min(width, x1 + 10), min(height, y1 + 10)
        if x1 > x0 and y1 > y0:
            region = float(np.abs(a[y0:y1, x0:x1] - b[y0:y1, x0:x1]).mean())
            region_px = int((np.abs(a[y0:y1, x0:x1] - b[y0:y1, x0:x1]) > 15).sum())
    return {
        "frame_mean_abs": round(whole, 2),
        "frame_px_over_15": int((np.abs(a - b) > 15).sum()),
        "region_mean_abs": round(region, 2),
        "region_px_over_15": region_px,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goal", default="DAILY_ROUTINE")
    parser.add_argument("--label", default="登录好礼")
    parser.add_argument("--op-id", default="")
    parser.add_argument("--drift-only", action="store_true")
    parser.add_argument("--frames", type=int, default=6)
    parser.add_argument("--every", type=float, default=0.35)
    parser.add_argument("--settle", type=float, default=1.6)
    parser.add_argument("--burst", type=int, default=8, help="post-tap frames")
    parser.add_argument("--burst-every", type=float, default=0.3, help="seconds between burst frames")
    parser.add_argument("--execute", action="store_true", help="actually tap")
    parser.add_argument("--config", default=str(ROOT / "config/v2.json"))
    args = parser.parse_args()

    from winter_agent_v2 import ui_collection
    from winter_agent_v2.device_lease import OWNER_DEVELOPMENT_VALIDATION, DeviceLease
    from winter_agent_v2.executor import Executor
    from winter_agent_v2.executor_router import build_maa_adapter
    from winter_agent_v2.ocr import read_frame_size

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    registry = ui_collection.load_control_registry()
    record = registry.get(args.label)
    if not record:
        print(f"{args.label!r} has no registered control in {ui_collection.ICON_CONTROL_REGISTRY}")
        return 2
    template = ROOT / str(record["template_path"])
    if not template.is_file():
        print(f"template missing: {template}")
        return 3

    op_id = args.op_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + f"_{args.label}"
    out = OUT_ROOT / op_id
    out.mkdir(parents=True, exist_ok=True)
    clock = Stop()
    report: dict[str, object] = {
        "op_id": op_id,
        "label": args.label,
        "goal": args.goal,
        "template": str(template),
        "started": clock.at(),
        "steps": [],
    }

    adapter = build_maa_adapter(config, production=True)
    if adapter is None or not adapter.available():
        print(f"MAA unavailable: {adapter.unavailable_reason if adapter else 'disabled'}")
        return 4
    ocr = _ocr(config)
    vision = _vision(ocr, config)
    lease = DeviceLease(root=ROOT)

    def shoot(name: str) -> Path:
        path = out / f"{name}.png"
        adapter.screenshot(path)
        return path

    def page_of(path: Path) -> dict:
        world = vision.observe(path)
        return {
            "page": str(getattr(world.page, "value", world.page)),
            "confidence": round(float(getattr(world, "confidence", 0.0) or 0.0), 3),
            "known": bool(getattr(world, "known", False)),
        }

    def record(name: str, **fields) -> dict:
        row = {"step": name, **clock.at(), **fields}
        report["steps"].append(row)
        return row

    print(f"op {op_id}; frames -> {out}")

    # ---------------------------------------------------------------- drift series
    print("-- drift series (no input at all) --")
    drift: list[dict] = []
    for index in range(max(1, args.frames)):
        path = shoot(f"drift_{index:02d}")
        size = read_frame_size(path)
        label_box = find_label(ocr, path, args.label)
        found = locate_icon(path, label_box, template, size) if label_box and size else None
        box = (found or {}).get("box_norm")
        drift.append({
            "index": index,
            "utc": _now(),
            "label_box": label_box,
            "icon_box": box,
            "score": (found or {}).get("confidence"),
            "page": page_of(path)["page"] if path.is_file() else "",
        })
        print(f"   {index:2d} label_x={ (label_box or {}).get('x_norm') } "
              f"icon_x={(box or {}).get('x_norm')} icon_y={(box or {}).get('y_norm')} "
              f"score={(found or {}).get('confidence')}")
        if index + 1 < args.frames:
            time.sleep(max(0.0, args.every))
    report["drift"] = drift
    xs = [row["icon_box"]["x_norm"] for row in drift if row.get("icon_box")]
    ys = [row["icon_box"]["y_norm"] for row in drift if row.get("icon_box")]
    if len(xs) > 1:
        report["drift_span"] = {
            "x": round(max(xs) - min(xs), 4),
            "y": round(max(ys) - min(ys), 4),
            "frames": len(xs),
        }
        print(f"   span: dx={max(xs) - min(xs):.4f} dy={max(ys) - min(ys):.4f} over {len(xs)} frames")

    if args.drift_only:
        (out / "live.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
        print(f"wrote {out / 'live.json'}")
        return 0

    # ---------------------------------------------------------------- plan frame
    print("-- plan --")
    plan_path = shoot("plan_frame")
    size = read_frame_size(plan_path)
    label_box = find_label(ocr, plan_path, args.label)
    if not label_box:
        record("plan", error=f"label {args.label!r} not on this frame",
               page=page_of(plan_path))
        print(f"   {args.label!r} not visible; page={page_of(plan_path)}")
        (out / "live.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
        return 6
    planned = locate_icon(plan_path, label_box, template, size)
    record("plan", frame=str(plan_path), label_box=label_box,
           icon_box=(planned or {}).get("box_norm"), score=(planned or {}).get("confidence"),
           page=page_of(plan_path))
    print(f"   planned icon at {(planned or {}).get('box_norm')}")

    if not args.execute:
        (out / "live.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
        print("(no tap: pass --execute)")
        return 0

    # ---------------------------------------------------------------- lease
    acquired = lease.acquire(
        owner=OWNER_DEVELOPMENT_VALIDATION,
        capability_id=f"probe:{args.label}",
        job_id="",
        reason=f"live operation probe {op_id}",
    )
    record("lease_acquire", acquired=bool(acquired), holder=str(lease.holder() or {})) 
    if not acquired:
        print("   could not take the device lease; another owner is driving the client")
        (out / "live.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
        return 7

    try:
        # ------------------------------------------------------------ fresh pre-tap frame
        pre_path = shoot("pre_tap_frame")
        pre_size = read_frame_size(pre_path)
        pre_label = find_label(ocr, pre_path, args.label)
        pre_found = locate_icon(pre_path, pre_label, template, pre_size) if pre_label else None
        pre_page = page_of(pre_path)
        record("pre_tap_frame", frame=str(pre_path), label_box=pre_label,
               icon_box=(pre_found or {}).get("box_norm"),
               score=(pre_found or {}).get("confidence"), page=pre_page)
        print(f"   pre-tap icon at {(pre_found or {}).get('box_norm')} page={pre_page}")

        if pre_found is None:
            record("tap", executed=False, reason="RELOCATE_FAILED: the control is not on this frame")
            print("   the control is not on the fresh frame -- stopping rather than tapping")
            lease.release(result="RELOCATE_FAILED", reason="icon absent on the pre-tap frame")
            return 8
        if str(pre_page["page"]).upper() != str(page_of(plan_path)["page"]).upper():
            record("tap", executed=False, reason="PAGE_CHANGED_BEFORE_TAP")
            print("   the page changed between plan and tap -- stopping")
            lease.release(result="PAGE_CHANGED", reason="page differed at relocation")
            return 9

        box = pre_found["box_norm"]
        point = (
            round(box["x_norm"] + box["w_norm"] / 2, 4),
            round(box["y_norm"] + box["h_norm"] / 2, 4),
        )
        executor = Executor(production=True, dry_run=False, device=adapter,
                            target_resolver=lambda _s: point, backend="MAA")
        from winter_agent_v2.models import Action

        sent = clock.at()
        result = executor.execute(Action("TAP_SEMANTIC", f"CONTROL[{args.label}]"))
        record("tap", point=point, sent_at=sent, executed=bool(result.executed),
               backend=result.backend, error=result.error,
               tap_point=list(result.tap_point) if result.tap_point else None,
               latency_ms=result.latency_ms)
        print(f"   tap {point} -> executed={result.executed} px={result.tap_point}")

        # A burst, not a before/after pair.  The controlled click on a bottom-nav entry produced
        # EXPLORATION at +0.35 s and MAP again by +1.2 s -- a response that short is invisible to
        # "capture once, then again after a settle", which is how the previous rounds concluded
        # "nothing happened".  So the frames come fast, and each one is compared against the frame
        # the tap was actually sent from.
        burst: list[dict] = []
        for index in range(max(1, args.burst)):
            if index:
                time.sleep(max(0.0, args.burst_every))
            shot = shoot(f"after_{index:02d}_frame")
            page = page_of(shot)
            delta = _delta(pre_path, shot, box)
            burst.append({"index": index, "frame": str(shot), "page": page, "delta": delta})
            record(f"after_{index:02d}", page=page["page"], **delta)
            print(f"   +{index * args.burst_every:.2f}s page={page['page']} "
                  f"frame_delta={delta['frame_mean_abs']} region_delta={delta['region_mean_abs']}")
        report["burst"] = burst
        after0 = shot
        time.sleep(max(0.0, args.settle))
        after1 = shoot("after_1_frame")
        record("after_1_frame", frame=str(after1), page=page_of(after1))

        from winter_agent_v2.runtime import LiveRuntime

        verifier = LiveRuntime.VERIFIED_ATOMIC.get("TRY_ORDINARY_CONTROL")
        if verifier is not None:
            verdict = verifier(vision.observe(plan_path), vision.observe(after1))
            record("verifier", verifier=getattr(verifier, "__name__", "?"),
                   ok=bool(getattr(verdict, "ok", verdict)),
                   reason=str(getattr(verdict, "reason", "") or ""),
                   pages=[s.get("page") for s in report["burst"]] if report.get("burst") else [])
            print(f"   verifier ok={getattr(verdict, 'ok', verdict)}")
        print(f"   page {page_of(plan_path)['page']} -> {page_of(after0)['page']} "
              f"-> {page_of(after1)['page']}")
    finally:
        lease.release(result="RELEASED", reason="probe finished")

    (out / "live.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
    print(f"wrote {out / 'live.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
