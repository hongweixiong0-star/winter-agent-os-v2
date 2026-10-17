# -*- coding: utf-8 -*-
"""BEAR JOIN_RALLY fast loop v2 — FormationPolicy integrated.

  green+ pixel locate -> PAGE_FORMATION -> FormationPolicy.select(JOIN_RALLY)
  -> SELECT_FORMATION_SLOT(available from [2..7]) -> fingerprint verifier
  -> 出征 -> member/banner/capacity verifier -> next rally.

No per-rally HERO/TROOP dynamic analysis (knowledge/formation/
formation_policy_rules.json). FORMATION_TO_DISPATCH_MS recorded.
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

sys.path.insert(0, str(ROOT))
from winter_agent_v2.formation_policy import (  # noqa: E402
    FormationPolicy, formation_selected_verified)

DEADLINE_HMS = (23, 59, 0)  # override per window
BAND = (300, 700, 380, 720)  # green + search band on PAGE_FORMATION / detail


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.executor_router import _rapid_ocr_results

    STAMP = datetime.now().strftime("%Y%m%dT%H%M%S")
    EVID = ROOT / "dataset" / "evidence" / f"bear_join_v2_{STAMP}"
    EVID.mkdir(parents=True, exist_ok=True)
    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(owner="DEVICE_BEAR_JOIN_V2", capability_id="BEAR_HUNT",
                             ttl_seconds=900, reason="bear join fast loop with formation policy")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2
    policy = FormationPolicy("ROLE_CURRENT")  # bind role when role known
    out: dict = {"flow": "JOIN_RALLY", "target_type": "BEAR", "t0": datetime.now().strftime("%H:%M:%S"),
                 "occurrences": []}
    try:
        ad = MaaExecutorAdapter(adb_path=cfg["device"]["adb_path"], serial=cfg["device"]["serial"],
                                production=True, template_dir=ROOT / "dataset/candidate/templates",
                                log_dir=ROOT / "learning/maa_logs")
        ad.ensure_ready()

        def frame(retries=4):
            for _ in range(retries):
                f = ad.frame()
                if f is not None:
                    return f if isinstance(f, Image.Image) else Image.fromarray(f)
                time.sleep(0.8)

        def toks(img):
            return _rapid_ocr_results(np.asarray(img), None, [])

        def text(img):
            return " ".join(t["text"] for t in toks(img))

        def save(img, tag):
            img.save(EVID / f"{tag}.png")

        def tap(x, y, w=1.6):
            ad.click(int(x), int(y))
            time.sleep(w)

        def center(b):
            return int(b[0]) + int(b[2]) // 2, int(b[1]) + int(b[3]) // 2

        def tap_tok(img, needle, w=2.0, exact=False):
            cs = [t for t in toks(img) if (t["text"].strip() == needle if exact else needle in t["text"])]
            if not cs:
                return False
            t = max(cs, key=lambda k: (k.get("box") or [0, 0, 0, 0])[1])
            x, y = center(t.get("box") or [0, 0, 0, 0])
            tap(x, y, w)
            return True

        def guard(f):
            t = text(f)
            if "退出游戏" in t:
                tap_tok(f, "取消", w=1.5, exact=True); return True
            if any(w in t for w in ("￥", "支付", "购买", "礼包", "祝贺你", "离线收益", "欢迎回来")):
                cs = [tt for tt in toks(f) if tt["text"].strip() in ("取消", "关闭")]
                if cs:
                    x, y = center(cs[0].get("box") or [0, 0, 0, 0]); tap(x, y, 1.5)
                else:
                    ad.press_back(); time.sleep(1.2)
                return True
            return False

        def at_city(f):
            t = text(f)
            return "退出游戏" not in t and ("统帅" in t or "背包" in t)

        def go_home():
            for _ in range(6):
                f = frame()
                if f is None:
                    continue
                if guard(f):
                    continue
                if at_city(f):
                    return True
                if not tap_tok(f, "城镇", w=2.2, exact=True):
                    tap(593, 1243, 2.2)
            return False

        def find_green_plus(f):
            y0, y1, x0, x1 = BAND
            bgr = np.asarray(f.convert("RGB"))[:, :, ::-1].copy()
            hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, (35, 120, 120), (85, 255, 255))
            band = mask[y0:y1, x0:x1]
            ys, xs = np.nonzero(band)
            if len(xs) < 80:
                return None
            return int(np.mean(xs)) + x0, int(np.mean(ys)) + y0

        def find_rally_badge(f):
            """RALLY_JOIN_BADGE: city-screen red circle (crossed arrows + flag) with
            numeric badge. Unified join entry for ANY rally type (BEAR / ICEFIELD_BEAST /
            other) -- knowledge/rally/rally_engine_rules.json#city_rally_badge.
            Detection: saturated red ring in the right-middle band of the city screen."""
            W, H = f.size
            y0, y1 = int(H * 0.28), int(H * 0.42)
            x0, x1 = int(W * 0.70), int(W * 0.98)
            bgr = np.asarray(f.convert("RGB"))[:, :, ::-1].copy()
            hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
            m1 = cv2.inRange(hsv, (0, 110, 110), (10, 255, 255))
            m2 = cv2.inRange(hsv, (170, 110, 110), (180, 255, 255))
            mask = cv2.bitwise_or(m1, m2)[y0:y1, x0:x1]
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
            cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for c in sorted(cnts, key=cv2.contourArea, reverse=True)[:3]:
                if cv2.contourArea(c) < 400:
                    continue
                bx, by, bw, bh = cv2.boundingRect(c)
                if 0.6 <= bw / max(bh, 1) <= 1.7:  # roughly circular
                    return (x0 + bx + bw // 2, y0 + by + bh // 2)
            return None

        def dispatch_with_policy(stage_tag):
            """PAGE_FORMATION: pick available support slot, verify, dispatch."""
            t_form = time.time()
            f = frame()
            if f is None or "盾兵" not in text(f):
                return None
            before = FormationPolicy.fingerprint_from_ocr(text(f))
            choice = policy.select({"task_type": "JOIN_RALLY"})
            out["last_slot_choice"] = choice
            slot = choice.get("formation_slot")
            if slot is None:
                return None
            W = f.size[0]
            x, y = FormationPolicy.slot_tap_point(slot, W)
            tap(x, y, 1.8)
            f2 = frame()
            save(f2, f"{stage_tag}_slot_{slot}")
            after = FormationPolicy.fingerprint_from_ocr(text(f2))
            verified = formation_selected_verified(before, after)
            out["last_slot_verified"] = verified
            # dispatch even if fingerprint equal (same preset may be already active)
            if tap_tok(f2, "出征", w=2.2, exact=True):
                out["formation_to_dispatch_ms"] = int((time.time() - t_form) * 1000)
                policy.mark(slot, "RALLYING")
                return slot
            return None

        # ---------------- main loop until deadline ----------------
        h, m, s = DEADLINE_HMS
        dl = time.time()
        # deadline = today at DEADLINE_HMS local
        import datetime as _dt
        now = _dt.datetime.now()
        dl = now.replace(hour=h, minute=m, second=s, microsecond=0).timestamp()
        joined_count = 0
        while time.time() < dl:
            f = frame()
            if f is None:
                continue
            if guard(f):
                continue
            if not at_city(f):
                go_home(); continue
            # ENTRY 1 (preferred): city-screen RALLY_JOIN_BADGE -- unified entry for ANY
            # rally type, one tap into the rally detail (knowledge city_rally_badge).
            badge = find_rally_badge(f)
            if badge is not None:
                out["entry"] = "RALLY_JOIN_BADGE"
                save(f, "badge_before")
                t_join = time.time()
                tap(*badge, 2.5)
                f2 = frame(); save(f2, "badge_detail")
                slot = dispatch_with_policy("join")
                if slot is None:
                    for i in range(4):
                        df = frame()
                        if df is None:
                            continue
                        save(df, f"dialog_{i}")
                        if guard(df):
                            break
                        if any(tap_tok(df, w2, w=2.0, exact=(w2 == "出征")) for w2 in ("出征", "立即加入", "确定")):
                            break
                time.sleep(6)
                vf = frame(); save(vf, "after")
                at = text(vf)
                ok = "xhw" in at or "已抵达" in at
                out["occurrences"].append({
                    "ts": datetime.now().strftime("%H:%M:%S"), "entry": "badge", "slot": slot,
                    "frame_to_join_ms": int((time.time() - t_join) * 1000), "joined_seen": ok})
                if ok:
                    joined_count += 1
                go_home(); time.sleep(8)
                continue
            # ENTRY 2 (fallback): alliance war page -> 集结 list
            out["entry"] = "war_page_list"
            tap(511, 1243, 1.8)
            f = frame()
            if not tap_tok(f, "联盟战争", w=1.8):
                tap(246, 669, 1.8)
            f = frame()
            if "集结" in text(f):
                tap_tok(f, "集结", w=1.8, exact=True) or tap(160, 130, 1.2)
            f = frame(); save(f, "rally_page")
            t_join = time.time()
            gp = find_green_plus(f)
            if gp is None:
                go_home(); time.sleep(8); continue
            out["green_centre"] = gp
            tap(*gp, 2.5)
            # dialog may need formation select then dispatch
            slot = dispatch_with_policy("join")
            if slot is None:
                # fallback: word-driven dialog handling (bearer of JOIN_RALLY_CONFIRM)
                for i in range(4):
                    df = frame()
                    if df is None:
                        continue
                    save(df, f"dialog_{i}")
                    if guard(df):
                        break
                    if any(tap_tok(df, w2, w=2.0, exact=(w2 == "出征")) for w2 in ("出征", "立即加入", "确定")):
                        break
            time.sleep(6)
            vf = frame(); save(vf, "after")
            at = text(vf)
            ok = "xhw" in at or "已抵达" in at
            out["occurrences"].append({
                "ts": datetime.now().strftime("%H:%M:%S"),
                "slot": slot,
                "frame_to_join_ms": int((time.time() - t_join) * 1000),
                "joined_seen": ok,
            })
            if ok:
                joined_count += 1
            go_home(); time.sleep(8)
        out["joined_count"] = joined_count
        out["done"] = datetime.now().strftime("%H:%M:%S")
        print(json.dumps(out, ensure_ascii=False, indent=1))
        (ROOT / "learning" / f"bear_join_v2_{STAMP}.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        return 0
    finally:
        lease.release(result="DONE", reason="join v2 done")


if __name__ == "__main__":
    raise SystemExit(main())
