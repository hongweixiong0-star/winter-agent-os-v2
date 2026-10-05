# -*- coding: utf-8 -*-
"""Run VISIT_ALLIANCE_SHOP on the real client.

    python tools/run_shop_alliance.py [--buy] [--tab 本周]

Without ``--buy`` the pass is read-and-decide only: it opens every card's own purchase
overlay, reads the item's real name there, applies the operator's rule and reports the
verdicts -- which is what a first run on an unfamiliar roll should do.

The operator's rule, treated as CONFIRMED business input:

    名称含「统帅经验」  ->  买
    其他                ->  跳过
    无需刷新（这个商店自己按计时器换货）

There is deliberately no ``--refresh`` here, unlike the other two shop drivers.  The operator's
联盟商店 policy has no refresh step, and the page backs that up: it carries a self-refresh banner
(``下次刷新：`` + a countdown) rather than a control to tap, so a refresh flag would have nothing
legal to do.

The spend witness is the **single number on the top bar** (x~630), because this page does not
render the store's 钻石 slot at all.  ``--buy`` spends only when a card's own overlay names
统帅经验; every other card is dismissed with the client's own ✕ and nothing else is touched.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    argv = sys.argv[1:]
    buy = "--buy" in argv
    tab = None
    if "--tab" in argv:
        tab = argv[argv.index("--tab") + 1]

    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import OWNER_DEVELOPMENT_VALIDATION, DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.shop_visit import visit_alliance, wait_for_the_device

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    outd = ROOT / "dataset" / "evidence" / f"shop_visit_alliance_{stamp}"
    outd.mkdir(parents=True, exist_ok=True)
    log_file = (outd / "run.log").open("w", encoding="utf-8")

    def say(line: str = "") -> None:
        print(line)
        log_file.write(str(line) + "\n")
        log_file.flush()

    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(owner=OWNER_DEVELOPMENT_VALIDATION,
                             capability_id="VISIT_ALLIANCE_SHOP", ttl_seconds=3000,
                             reason=f"VISIT_ALLIANCE_SHOP live pass (buy={buy}, tab={tab})")
    if rec is None:
        say(json.dumps({"refused": why}, ensure_ascii=False))
        return 2

    try:
        # A lease is a request, not a handover: AUTO keeps acting until its next safe point
        # (measured 2026-10-05: 14-22 s), and a tap issued before that races its current action.
        wait_for_the_device(ROOT, log=say)
        ad = MaaExecutorAdapter(adb_path=cfg["device"]["adb_path"],
                                serial=cfg["device"]["serial"], production=True,
                                template_dir=ROOT / "dataset/candidate/templates",
                                log_dir=ROOT / "learning/maa_logs")
        ok, reason = ad.ensure_ready()
        if not ok:
            say(reason)
            return 3
        say(f"buy={buy} tab={tab or '今日(default)'}")
        try:
            report = visit_alliance(ad, outd, execute_buys=buy, tab=tab, log=say)
            say("\n--- verdicts ---")
            for rnd in report["rounds"]:
                say(f"  [round {rnd['round']}] {rnd['on_screen']} on screen,"
                    f" {rnd['inspected']} inspected")
            for c in report["cards"]:
                say(f"  y{c['tap_xy'][1]:>4} c{c['col']} 剩余={c['rest']:>2}"
                    f" {str(c.get('discount')):>5} {c['price']:>9}"
                    f"  {str(c.get('name')):>18}  {c['verdict']:<4} {c['reason']}")
            say(f"\n联盟币/顶部数字 {report['coin_before']} -> {report['coin_after']}"
                f"   (top bar before: {report['top_bar_before']})")
            say(f"swipes={report['swipes']} backs={report['backs_used']}"
                f" touch={report['touch_balance']} taps_refused={report.get('tap_refused', 0)}")
            if report["purchases"]:
                say(f"\n--- purchases ({len(report['purchases'])}) ---")
                for p in report["purchases"]:
                    say(f"   y{p['card']['tap_xy'][1]} {p['card']['name']}"
                        f" @ {p['card']['price']} -> {'TAPPED' if p['ok'] else 'FAILED'}"
                        f" ({p['why']})")
            if report["asks"]:
                say(f"\n!! {len(report['asks'])} card(s) whose name could not be read")
                for c in report["asks"]:
                    say(f"   y{c['tap_xy'][1]} -- {c['reason']}")
            if report["unreadable"]:
                say(f"\n!! {len(report['unreadable'])} card(s) whose overlay would not open"
                    " (nothing was tapped):")
                for c in report["unreadable"]:
                    say(f"   y{c['tap_xy'][1]} 剩余={c['rest']} -- {c['inspect_why']}")
            say(f"EVIDENCE: {outd}")
            return 0
        finally:
            log_file.close()
    finally:
        lease.release(result="DONE", reason="alliance shop visit finished")


if __name__ == "__main__":
    raise SystemExit(main())
