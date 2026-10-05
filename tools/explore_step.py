"""One exploration step: one action, one observation, one evidence row.

Operator specification ``docs/DEVELOPMENT_FLOW.md`` §二.  Its requirement is the one thing the
project could not do: **execute an arbitrary single action without a pre-written Skill.**  The
measured state on 2026-10-06 was that ``tools/`` held 325 scripts and 161 of them were one-off
probes, so every "let me look at one step" cost a new script.  On 2026-10-05, reaching the bear
tab cost five of them.

So this is deliberately one command, not a framework:

    explore_step.py --purpose ... --scope ... --observe
    explore_step.py --purpose ... --scope ... --tap 0.669 0.173
    explore_step.py --purpose ... --scope ... --tap-text 取消
    explore_step.py --purpose ... --scope ... --swipe 0.72 0.09 0.21 0.09 --duration-ms 420
    explore_step.py --purpose ... --scope ... --back

Four things it does NOT do, each for a reason found elsewhere in this project:

* **It does not invent a tap path.**  The input goes through the project's own
  ``Executor`` on the project's own MAA adapter, under the project's own ``DeviceLease`` --
  the same three objects ``tools/probe_live_operation.py`` uses, because the coordinate gate
  records that only two code sites in the whole tree may tap a device and that number must not
  grow (``Operational §24``/its machine judge ``tools/check_coordinate_hardcoding.py``).
* **It does not restate the risk vocabulary.**  It imports ``HIGH_RISK_WORDS``, whose own comment
  says two risk vocabularies are two risk *rules* and the one nobody re-read is the one a spend
  gets through.
* **It does not re-implement label finding.**  ``--tap-text`` goes through
  ``ui_collection.grounding_regions`` -- the same call ``find_label`` in the probe makes.
* **It does not run in Auto.**  Exploration is a Manual-mode activity (§二), and §五 forbids
  search/inspection work while the runtime is executing.  The check is a refusal, not a warning.

What it DOES add, which is the point: the operator's exploration discipline (purpose, scope,
observe every step, record what was seen) is enforced by the command line rather than remembered.
``--purpose`` and ``--scope`` are required arguments -- §二 says an exploration must state what it
is trying to find out and where it is allowed to touch, and a habit is not a guarantee.
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

#: Where the frames of one exploration go.  Outside ``dataset/raw/`` on purpose: that tree is
#: retention-pruned, and a probe whose evidence is gone cannot be re-read (25 test files currently
#: assert on frames that prune has already taken).
FRAME_ROOT = ROOT / "dataset/exploration"

#: One row per invocation, appended.  §三 requires every explored UI to be recorded; §二 requires
#: the path, the control position and the state change.  This is the raw material for that, kept
#: separate from the UI knowledge base so a bad run cannot pollute it.
LOG_PATH = ROOT / "learning/exploration_log.jsonl"

#: The action kinds this tool will issue.  Everything else is refused rather than passed through:
#: an exploration tool that can send anything is a second execution chain by another name.
ACTIONS = ("observe", "screenshot", "tap", "tap-text", "swipe", "back")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _ocr(config: dict):
    from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend

    return OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))


def _vision(ocr, config: dict):
    from winter_agent_v2.ocr import HybridVision
    from winter_agent_v2.vision import SemanticWorldVision

    return HybridVision(
        SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json"), ocr
    )


#: The mode record this tool refuses to run outside Manual.  A module constant rather than a flag:
#: a guard with a command-line override is not a guard, and this one exists to keep exploration out
#: of Auto where §五 forbids it.  Tests exercise the function directly instead.
MODE_STATE_PATH = ROOT / "learning/MODE_STATE.json"


def _require_manual_mode(path: Path | None = None) -> None:
    """§二/§五: exploration belongs to Manual, and must not run while the runtime is executing."""
    from winter_agent_v2 import mode_state

    state = mode_state.load(path or MODE_STATE_PATH)
    if state.mode != mode_state.MODE_MANUAL:
        raise SystemExit(
            f"当前模式是 {state.mode}，不是 MANUAL：探索只能发生在 Manual 模式下"
            "（docs/DEVELOPMENT_FLOW.md §二；§五 也禁止在 Runtime 执行期做这类工作）。\n"
            "先切 Manual：python -m winter_agent_v2.mode_state --to-manual --by USER "
            "--reason ... --expected-minutes N --done-when ..."
        )


def _high_risk_words_in(text: str) -> list[str]:
    """Words from the project's canonical risk list that appear on this frame.

    Imported rather than restated: ``ui_venus_contract`` says two risk vocabularies are two risk
    *rules*, and the copy nobody re-reads is the one a spend gets through.
    """
    from winter_agent_v2.ui_venus_contract import HIGH_RISK_WORDS

    return sorted({word for word in HIGH_RISK_WORDS if word in text})


def _risk_refusal(action: str, tap_text: str | None, frame_text: str) -> list[str]:
    """Which risk words block this action -- empty means proceed.

    §二 探索边界 forbids real money, unauthorized gems and irreversible high-value operations.
    Where that screen is *applied* matters as much as having it.

    Measured 2026-10-06, by using this tool: it was first written to refuse any input whenever the
    frame carried a risk word, and the very next invocation was a ``--back`` to restore the client
    -- refused because the alliance HUD happens to draw 加速.  A BACK is a system key: it
    activates no control, so the screen cost the ability to leave a page and bought no safety.
    §32's question applies to guards too -- "cannot do this now" versus "should never do this".

    So: only pointing actions are screened, and
      * a **text** target is screened against **its own words**, which is precise -- tapping 背包
        while 加速 sits elsewhere on the HUD is not a risk;
      * a **raw point** is screened against the whole frame, because a point cannot say what is
        under it.  That is the only place the coarse screen is the right one.
    """
    if action != "tap":
        return []
    return _high_risk_words_in(tap_text) if tap_text else _high_risk_words_in(frame_text)


def _box_centre(box: dict) -> tuple[float, float]:
    return (
        round(float(box["x_norm"]) + float(box["w_norm"]) / 2, 4),
        round(float(box["y_norm"]) + float(box["h_norm"]) / 2, 4),
    )


def _find_text(ocr, frame: Path, needle: str) -> tuple[dict | None, float]:
    """The first grounded region whose text equals ``needle``, plus its confidence.

    Same call the existing probe's ``find_label`` makes, so this tool cannot drift from the way
    the rest of the project grounds text on a frame.
    """
    from winter_agent_v2 import ui_collection

    for region in ui_collection.grounding_regions(frame, ocr):
        if str(region.get("text") or "").strip() == needle:
            box = dict(region.get("box_norm") or {})
            if {"x_norm", "y_norm", "w_norm", "h_norm"} <= set(box):
                return box, float(region.get("confidence") or 0.0)
    return None, 0.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="一个动作 + 一次观察 + 一条证据（docs/DEVELOPMENT_FLOW.md §二）"
    )
    parser.add_argument("--purpose", required=True,
                        help="§二 探索纪律：这次想搞清什么（必填）")
    parser.add_argument("--scope", required=True,
                        help="§二 探索纪律：允许点到哪里、不允许点到哪里（必填）")
    parser.add_argument("--observe", action="store_true", help="只读当前页面，不发输入")
    parser.add_argument("--screenshot", action="store_true", help="只截图")
    parser.add_argument("--tap", nargs=2, type=float, metavar=("X", "Y"),
                        help="归一化坐标点击（探索专用）")
    parser.add_argument("--tap-text", default=None,
                        help="在当前帧上找到这段文字并点它的中心（优先于 --tap）")
    parser.add_argument("--swipe", nargs=4, type=float, metavar=("X1", "Y1", "X2", "Y2"))
    parser.add_argument("--duration-ms", type=int, default=420)
    parser.add_argument("--back", action="store_true")
    parser.add_argument("--settle", type=float, default=1.4, help="动作后等稳定再复拍")
    parser.add_argument("--config", default=str(ROOT / "config/v2.json"))
    args = parser.parse_args(argv)

    chosen = [name for name in ACTIONS
              if (args.observe and name == "observe")
              or (args.screenshot and name == "screenshot")
              or (args.tap is not None and name == "tap")
              or (args.tap_text is not None and name == "tap-text")
              or (args.swipe is not None and name == "swipe")
              or (args.back and name == "back")]
    if len(chosen) != 1:
        parser.error(f"一次只能做一个动作，收到 {chosen or '零个'}；可选：{', '.join(ACTIONS)}")
    action = chosen[0]
    if action == "tap-text":
        action = "tap"  # same executor path; the point is just located from text

    _require_manual_mode()

    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.executor import Executor
    from winter_agent_v2.executor_router import build_maa_adapter
    from winter_agent_v2.models import Action

    config = _load_config(Path(args.config))
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out = FRAME_ROOT / run_id
    out.mkdir(parents=True, exist_ok=True)

    adapter = build_maa_adapter(config, production=True)
    if adapter is None or not adapter.available():
        print(f"MAA 不可用：{adapter.unavailable_reason if adapter else 'disabled'}")
        return 4
    ocr = _ocr(config)
    vision = _vision(ocr, config)
    lease = DeviceLease(root=ROOT)

    record: dict[str, object] = {
        "at": _now(), "run_id": run_id, "purpose": args.purpose, "scope": args.scope,
        "action": action, "params": {}, "frames": [], "result": "UNKNOWN",
    }

    def shoot(name: str) -> Path:
        path = out / f"{name}.png"
        adapter.screenshot(path)
        record["frames"].append(str(path))
        return path

    def page_of(path: Path) -> str:
        return str(getattr(vision.observe(path).page, "value", ""))

    def finish(code: int) -> int:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"证据 -> {LOG_PATH}\n帧   -> {out}")
        return code

    # ``acquire`` returns ``(record, reason)`` -- a *tuple*, so a truthiness test on the result
    # would read a refusal as a success.  Unpacked deliberately.
    held, why = lease.acquire(
        owner="DEVICE_EXPLORE_STEP",
        capability_id="EXPLORATION",
        reason=f"{args.purpose} | scope={args.scope}",
        ttl_seconds=max(60.0, args.settle * 4 + 30.0),
    )
    if held is None:
        print(f"拿不到设备租约：{why}")
        record["result"] = "LEASE_REFUSED"
        return finish(5)
    record["lease_owner"] = held.owner

    try:
        before = shoot("before")
        before_text = ocr.recognize(before).text
        record["page_before"] = page_of(before)
        print(f"起始页面：{record['page_before']}")

        # §二 探索边界: real money, unauthorized gems and irreversible operations are forbidden.
        # The screen is action-aware -- see ``_risk_refusal`` for why screening every input was
        # both too broad and useless.
        blocked = _risk_refusal(action, args.tap_text, before_text)
        record["risk_screen"] = {
            "action": action,
            "frame_risk_words": _high_risk_words_in(before_text),
            "target_text": args.tap_text,
            "blocked_by": blocked,
            "basis": ("target_text" if args.tap_text else "whole_frame") if action == "tap"
                     else "not_a_pointing_action",
        }
        if blocked:
            print(f"拒绝在该帧发输入：风险词 {blocked}（§二 探索边界）")
            record["result"] = "REFUSED_HIGH_RISK"
            return finish(6)

        if action == "observe" or action == "screenshot":
            record["result"] = "OBSERVED"
            print(before_text[:400])
            return finish(0)

        if args.tap_text is not None:
            box, confidence = _find_text(ocr, before, args.tap_text)
            if box is None:
                print(f"当前帧上没有 {args.tap_text!r}，不发点击")
                record["result"] = "TEXT_NOT_ON_FRAME"
                return finish(7)
            point = _box_centre(box)
            record["params"] = {"tap_text": args.tap_text, "box_norm": box,
                                "confidence": round(confidence, 3)}
            executor = Executor(production=True, dry_run=False, device=adapter,
                                target_resolver=lambda _s: point, backend="MAA")
            result = executor.execute(Action("TAP_SEMANTIC", f"TEXT[{args.tap_text}]"))
        elif args.tap is not None:
            point = (float(args.tap[0]), float(args.tap[1]))
            record["params"] = {"point": point, "note": "exploration-supplied point"}
            executor = Executor(production=True, dry_run=False, device=adapter,
                                target_resolver=lambda _s: point, backend="MAA")
            result = executor.execute(Action("TAP_SEMANTIC", "EXPLORE_POINT"))
        elif args.swipe is not None:
            vector = ",".join(str(value) for value in args.swipe)
            record["params"] = {"vector": vector, "duration_ms": args.duration_ms}
            executor = Executor(production=True, dry_run=False, device=adapter, backend="MAA")
            result = executor.execute(
                Action("SWIPE", vector, payload={"duration_ms": args.duration_ms})
            )
        else:
            executor = Executor(production=True, dry_run=False, device=adapter, backend="MAA")
            result = executor.execute(Action("PRESS_BACK"))

        record["executed"] = bool(result.executed)
        record["backend"] = result.backend
        record["error"] = result.error
        record["tap_point"] = list(result.tap_point) if result.tap_point else None
        print(f"执行：executed={result.executed} backend={result.backend} err={result.error}")

        time.sleep(max(0.0, args.settle))
        after = shoot("after")
        record["page_after"] = page_of(after)
        record["observed_change"] = (
            f"{record['page_before']} -> {record['page_after']}"
            if record["page_before"] != record["page_after"] else "PAGE_UNCHANGED"
        )
        record["after_text"] = ocr.recognize(after).text[:2000]
        record["result"] = "DONE" if result.executed else "EXECUTOR_REFUSED"
        print(f"结果：{record['observed_change']}")
        return finish(0)
    finally:
        lease.release(result=str(record.get("result") or "UNKNOWN"),
                      reason=args.purpose[:120])


if __name__ == "__main__":
    raise SystemExit(main())
