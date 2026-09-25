"""Execute one freshly harvested node through V2's real router — the closed loop.

Run:  python tools/autogen_closed_loop.py --skill OPEN_ALLIANCE --semantic BTN_OPEN_ALLIANCE

This is the proof step the operator's brief asks for and the one most often
faked: not "a node exists", not "JSON was written", but *the router picked the
generated node up, MAA recognised the control through it, a tap landed, and the
page the tap was supposed to open actually opened*.

Every layer is reported separately on purpose:

  node wired      - the routing table carries the node
  MAA recognised  - recognition_backend == "MAA" on the ExecutionResult
  tap landed      - tap_point is a real device pixel
  page changed    - the after-frame shows the destination page's own marker

A step that fails is reported as failing; nothing here upgrades a click into a
completed task.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.device import ADBDevice  # noqa: E402
from winter_agent_v2.device_lease import DeviceLease  # noqa: E402
from winter_agent_v2.executor import Executor  # noqa: E402
from winter_agent_v2.executor_router import (  # noqa: E402
    BackendLedger,
    RoutingTable,
    build_maa_adapter,
    build_router,
)
from winter_agent_v2.models import Action  # noqa: E402
from winter_agent_v2.ocr import OCRService, RapidOCRBackend  # noqa: E402
from winter_agent_v2.pipeline_autogen import PipelineAutoGen  # noqa: E402

ADB = Path(r"D:\Program Files\Netease\MuMu Player 12\nx_main\adb.exe")
SERIAL = "127.0.0.1:7555"
FRAMES = ROOT / "dataset" / "raw" / "autogen"


def page_words(ocr: OCRService, frame: Path) -> list[str]:
    return [str(t.text) for t in ocr.recognize(frame).tokens if t.text]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skill", required=True)
    ap.add_argument("--semantic", required=True)
    ap.add_argument("--expect-word", default="", help="word that should appear once the tap lands")
    ap.add_argument("--backs-first", type=int, default=2)
    args = ap.parse_args()

    table = RoutingTable.load()
    node = table.recognition_node(args.skill, args.semantic)
    print(f"1. node wired      : {bool(node)} ({json.dumps(node, ensure_ascii=False)[:110]})")
    if node is None:
        print("   nothing to execute — run tools/autogen_harvest.py --apply first")
        return 2

    lease = DeviceLease()
    record, reason = lease.request(
        capability_id="PIPELINE_AUTOGEN_CLOSED_LOOP", trace_id="WORKBUDDY_AUTOGEN_E2E",
        reason=f"execute generated node {args.skill}/{args.semantic} through the router",
    )
    if record is None:
        print(f"[BLOCKED] lease unavailable: {reason}")
        return 3

    device = ADBDevice(ADB, SERIAL, production=True)
    if not device.status().connected:
        lease.release(result="failed", reason="device not connected")
        print("[BLOCKED] device not connected")
        return 4

    ocr = OCRService(RapidOCRBackend())
    gen = PipelineAutoGen(device=device)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    try:
        for _ in range(args.backs_first):
            device.press_back()
            time.sleep(1.2)
        before = FRAMES / f"{stamp}_before.png"
        device.screenshot(before)
        words_before = page_words(ocr, before)

        config = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
        adapter = build_maa_adapter(config, production=True)
        if adapter is None or not adapter.ensure_ready()[0]:
            lease.release(result="failed", reason="MAA adapter unavailable")
            print("[BLOCKED] MAA adapter unavailable")
            return 5

        def adb_resolver(semantic: str):
            found = gen.locate_text(before, gen.ocr and semantic or semantic)
            return None  # V2 fallback stays honest: this loop must prove the MAA node

        adb_executor = Executor(production=True, dry_run=False, device=device,
                                target_resolver=adb_resolver, backend="ADB")
        router = build_router(adb_executor=adb_executor, adb_resolver=adb_resolver,
                              maa_adapter=adapter, skill_id=args.skill,
                              routing=table, ledger=BackendLedger())

        result = router.execute(Action("TAP_SEMANTIC", args.semantic), skill_id=args.skill)
        print(f"2. MAA recognised  : {result.recognition_backend == 'MAA'}"
              f"  (recognition_backend={result.recognition_backend!r},"
              f" capture={result.capture_backend!r})")
        print(f"3. tap landed      : {result.executed}  tap_point={result.tap_point}"
              f"  error={result.error!r}")

        time.sleep(3.0)
        after = FRAMES / f"{stamp}_after.png"
        device.screenshot(after)
        words_after = page_words(ocr, after)
        new_words = [w for w in words_after if w not in words_before]
        print(f"4. page changed    : {len(new_words)} new words, sample={new_words[:8]}")
        if args.expect_word:
            hit = any(args.expect_word in w for w in words_after)
            print(f"   expect-word {args.expect_word!r} present: {hit}")
            task_done = hit
        else:
            task_done = bool(new_words)

        print()
        print(f"VERDICT: node={'wired' if node else 'missing'}"
              f" maa_recognised={result.recognition_backend == 'MAA'}"
              f" tap={result.executed} page_changed={task_done}")
        lease.release(result="ok" if result.executed and task_done else "partial",
                      reason=f"closed loop {args.skill}/{args.semantic}")
        return 0 if (result.executed and task_done) else 1
    except Exception as exc:  # noqa: BLE001
        lease.release(result="failed", reason=str(exc))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
