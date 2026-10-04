# -*- coding: utf-8 -*-
"""Run VISIT_WANDERING_MERCHANT on the real client.

    python tools/run_shop_wandering.py [--buy] [--refresh]

Without ``--buy`` the pass is read-and-decide only: it names every card, applies the
operator's policy and reports the verdicts, which is what a first run on an unfamiliar roll
should do.  With ``--buy`` it also taps the purchase overlay's own price button for the BUY
verdicts (``winter_agent_v2.shop_visit.ShopVisitor.confirm``) and verifies the overlay closed.
``--refresh`` spends a **free** refresh only, and never more than three in a day, tracked in
learning/shop_state.json.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STATE = ROOT / "learning" / "shop_state.json"
FREE_PER_DAY = 3


def _state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _free_refreshes_today() -> int:
    day = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    return int(_state().get("free_refresh", {}).get(day, 0))


def _note_free_refresh() -> int:
    day = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    st = _state()
    used = int(st.setdefault("free_refresh", {}).get(day, 0)) + 1
    st["free_refresh"][day] = used
    st["free_refresh"] = {k: v for k, v in sorted(st["free_refresh"].items())[-14:]}
    st["last_visit"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    return used


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    argv = sys.argv[1:]
    buy = "--buy" in argv
    want_refresh = "--refresh" in argv
    used = _free_refreshes_today()
    if want_refresh and used >= FREE_PER_DAY:
        print(f"free refresh budget exhausted today ({used}/{FREE_PER_DAY}) -- not refreshing")
        want_refresh = False

    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import OWNER_DEVELOPMENT_VALIDATION, DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.shop_visit import visit

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    outd = ROOT / "dataset" / "evidence" / f"shop_visit_wandering_{stamp}"
    outd.mkdir(parents=True, exist_ok=True)

    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(
        owner=OWNER_DEVELOPMENT_VALIDATION, capability_id="VISIT_WANDERING_MERCHANT",
        ttl_seconds=2700,
        reason=f"VISIT_WANDERING_MERCHANT live pass (buy={buy}, refresh={want_refresh})")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2

    try:
        ad = MaaExecutorAdapter(adb_path=cfg["device"]["adb_path"],
                                serial=cfg["device"]["serial"], production=True,
                                template_dir=ROOT / "dataset/candidate/templates",
                                log_dir=ROOT / "learning/maa_logs")
        ok, reason = ad.ensure_ready()
        if not ok:
            print(reason)
            return 3
        print(f"buy={buy} refresh={want_refresh} (free refreshes used today: {used}/{FREE_PER_DAY})")
        # The pass's log is written into the evidence directory as well as to stdout.  The
        # 2026-10-05 01:50 pass was piped through ``tail`` and then interrupted, and the only
        # record of what it decided was lost with it -- the frames survived, the reasons did not.
        log_file = (outd / "run.log").open("w", encoding="utf-8")

        def say(line: str = "") -> None:
            print(line)
            log_file.write(str(line) + "\n")
            log_file.flush()

        try:
            report = visit(ad, outd, do_refresh=want_refresh, execute_buys=buy, log=say)
            # The budget is counted from what the pass actually spent.  It used to be noted only
            # ``if report.get("refreshed")``, and ``visit`` never set that key -- so the 3/day cap
            # the operator's policy depends on was never incremented at all.
            for _ in range(int(report.get("refreshed") or 0)):
                say(f"free refreshes used today: {_note_free_refresh()}/{FREE_PER_DAY}")
            say("\n--- verdicts ---")
            for rnd in report["cards"]:
                say(f"  [round {rnd['round']}]")
                for c in rnd["cards"]:
                    say(f"  r{c['row']}c{c['col']} 剩余={c['rest']:>2} {c['price']:>9}"
                        f"{'💎' if c['diamond'] else ' 资源'} {str(c.get('discount')):>5}"
                        f"  {str(c.get('name')):>14}  {c['verdict']:<4} {c['reason']}")
            say(f"\nwallet {report['wallet_before']} -> {report['wallet_after']}")
            say(f"backs={report['backs_used']} touch={report['touch_balance']}"
                f" taps_refused={report.get('tap_refused', 0)}")
            if report["purchases"]:
                say(f"\n--- purchases ({len(report['purchases'])}) ---")
                for p in report["purchases"]:
                    say(f"   r{p['card']['row']}c{p['card']['col']} {p['card']['name']}"
                        f" @ {p['card']['price']}{'💎' if p['card']['diamond'] else '资源'}"
                        f" -> {'TAPPED' if p['ok'] else 'FAILED'} ({p['why']})"
                        f"  verified={p.get('verified')}  {p.get('verify_note', '')}")
            if report["asks"]:
                say(f"\n!! {len(report['asks'])} card(s) the policy does not cover:")
                for c in report["asks"]:
                    say(f"   {c['name']} @ {c['price']} -- {c['reason']}")
            if report["unreadable"]:
                say(f"\n!! {len(report['unreadable'])} card(s) whose overlay would not open"
                    " (nothing was tapped):")
                for c in report["unreadable"]:
                    say(f"   r{c['row']}c{c['col']} 剩余={c['rest']} list-price={c['price']}"
                        f" -- {c['inspect_why']}")
            say(f"EVIDENCE: {outd}")
            return 0
        finally:
            log_file.close()
    finally:
        lease.release(result="DONE", reason="wandering merchant visit finished")


if __name__ == "__main__":
    raise SystemExit(main())
