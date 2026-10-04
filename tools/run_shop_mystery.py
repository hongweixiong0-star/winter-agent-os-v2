# -*- coding: utf-8 -*-
"""Run VISIT_MYSTERY_SHOP on the real client.

    python tools/run_shop_mystery.py [--buy] [--refresh] [--allow-agnes]

Without ``--buy`` the pass is read-and-decide only: it opens every card's own purchase
overlay, reads the item's real name there, applies the operator's rule and reports the
verdicts -- which is what a first run on an unfamiliar roll should do.

The operator's rule, treated as CONFIRMED business input:

    名称含「英雄组件自选箱」 且 折扣 = 50%  ->  买
    其他                                    ->  跳过
    只用免费刷新（基础 1 次/天；有艾格尼丝后最多 5 次），绝不用钻石刷新

``--refresh`` spends a **free** refresh only: the control must literally read 免费刷新, and the
day's count is tracked in ``learning/shop_state.json`` under its own key so the merchant's
3/day budget and this one cannot eat each other.  ``--allow-agnes`` raises the local cap to the
5 the operator describes for an account that has 艾格尼丝 -- it is a local cap only; the client
still decides whether the control reads 免费刷新.

Prices on this page are the **gold coin**, not diamonds, so the spend witness printed here is
the second number on the top bar and not the first.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STATE = ROOT / "learning" / "shop_state.json"
KEY = "free_refresh_mystery"


def _state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _used_today() -> int:
    day = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    return int(_state().get(KEY, {}).get(day, 0))


def _note_refresh() -> int:
    day = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    st = _state()
    used = int(st.setdefault(KEY, {}).get(day, 0)) + 1
    st[KEY][day] = used
    st[KEY] = {k: v for k, v in sorted(st[KEY].items())[-14:]}
    st["last_visit_mystery"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    return used


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    argv = sys.argv[1:]
    buy = "--buy" in argv
    want_refresh = "--refresh" in argv
    cap = 5 if "--allow-agnes" in argv else 1
    used = _used_today()
    if want_refresh and used >= cap:
        print(f"free refresh budget exhausted today ({used}/{cap}) -- not refreshing")
        want_refresh = False
    rounds = cap - used if want_refresh else 0

    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import OWNER_DEVELOPMENT_VALIDATION, DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.shop_visit import visit_mystery, wait_for_the_device

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    outd = ROOT / "dataset" / "evidence" / f"shop_visit_mystery_{stamp}"
    outd.mkdir(parents=True, exist_ok=True)
    log_file = (outd / "run.log").open("w", encoding="utf-8")

    def say(line: str = "") -> None:
        print(line)
        log_file.write(str(line) + "\n")
        log_file.flush()

    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(owner=OWNER_DEVELOPMENT_VALIDATION,
                             capability_id="VISIT_MYSTERY_SHOP", ttl_seconds=2700,
                             reason=f"VISIT_MYSTERY_SHOP live pass (buy={buy}, refresh={want_refresh})")
    if rec is None:
        say(json.dumps({"refused": why}, ensure_ascii=False))
        return 2

    try:
        # A lease is a request, not a handover: AUTO keeps acting until its next safe point
        # (measured 2026-10-05: 22 s), and a tap issued before that races its current action.
        wait_for_the_device(ROOT, log=say)
        ad = MaaExecutorAdapter(adb_path=cfg["device"]["adb_path"],
                                serial=cfg["device"]["serial"], production=True,
                                template_dir=ROOT / "dataset/candidate/templates",
                                log_dir=ROOT / "learning/maa_logs")
        ok, reason = ad.ensure_ready()
        if not ok:
            say(reason)
            return 3
        say(f"buy={buy} refresh={want_refresh} rounds={rounds} (free refreshes used today:"
            f" {used}/{cap})")
        try:
            report = visit_mystery(ad, outd, do_refresh=want_refresh and rounds > 0,
                                   execute_buys=buy, max_refreshes=max(0, rounds), log=say)
            for _ in range(int(report.get("refreshed") or 0)):
                say(f"free refreshes used today: {_note_refresh()}/{cap}")
            say("\n--- verdicts ---")
            for rnd in report["cards"]:
                say(f"  [round {rnd['round']}]")
                for c in rnd["cards"]:
                    say(f"  r{c['row']}c{c['col']} 剩余={c['rest']:>2}"
                        f" {str(c.get('discount')):>5} {c['price']:>9}"
                        f"  {str(c.get('name')):>16}  {c['verdict']:<4} {c['reason']}")
            say(f"\n钻石 {report['wallet_before']} -> {report['wallet_after']}"
                f"    金币 {report['gold_before']} -> {report['gold_after']}")
            say(f"backs={report['backs_used']} touch={report['touch_balance']}"
                f" taps_refused={report.get('tap_refused', 0)}")
            if report["purchases"]:
                say(f"\n--- purchases ({len(report['purchases'])}) ---")
                for p in report["purchases"]:
                    say(f"   r{p['card']['row']}c{p['card']['col']} {p['card']['name']}"
                        f" @ {p['card']['price']} -> {'TAPPED' if p['ok'] else 'FAILED'}"
                        f" ({p['why']})  verified={p.get('verified')} {p.get('verify_note','')}")
            if report["asks"]:
                say(f"\n!! {len(report['asks'])} card(s) the policy does not cover:")
                for c in report["asks"]:
                    say(f"   {c['name']} 折扣={c.get('discount')} -- {c['reason']}")
            if report["unreadable"]:
                say(f"\n!! {len(report['unreadable'])} card(s) whose overlay would not open"
                    " (nothing was tapped):")
                for c in report["unreadable"]:
                    say(f"   r{c['row']}c{c['col']} 剩余={c['rest']} 折扣={c.get('discount')}"
                        f" -- {c['inspect_why']}")
            say(f"EVIDENCE: {outd}")
            return 0
        finally:
            log_file.close()
    finally:
        lease.release(result="DONE", reason="mystery shop visit finished")


if __name__ == "__main__":
    raise SystemExit(main())
