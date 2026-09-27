# -*- coding: utf-8 -*-
"""Complete role B ([DIW]xhw) baseline BEFORE role A's 20:30 open.

Operator directive 19:08: role B must reach READY=true before 20:30, because
its nominal T-30 collides with role A's OPEN.  This session:

1. switches to [DIW]xhw (avatar -> 设置 -> 角色管理) and verifies via 领主档案;
2. reads AUTO_JOIN on 联盟战争/集结 (scrolling if a live rally occupies the
   page), toggles it ON if OFF, and re-reads ON;
3. reads march queue text;
4. re-reads the bear reserve time (client direct);
5. switches back to role A and verifies.

The two numeric ids are treated as role_id/character_id under one account
(the client shows a per-role 账号 field; the login account is shared).
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

STAMP = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
EVID = ROOT / "dataset" / "evidence" / f"bear_roleB_complete_{STAMP}"

RESERVE_RE = re.compile(
    r"预约自动开启[：:]?\s*(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})\s*(\d{1,2})[::](\d{2})")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.executor_router import _rapid_ocr_results
    from winter_agent_v2.bear_state import read_state_from_image

    EVID.mkdir(parents=True, exist_ok=True)
    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(
        owner="DEVICE_ROLEB_COMPLETE", capability_id="BEAR_HUNT",
        ttl_seconds=1500, reason="complete role B baseline before role A open 20:30")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2

    out: dict = {"session_started_at": datetime.now(timezone.utc).isoformat()}
    try:
        adapter = MaaExecutorAdapter(
            adb_path=cfg["device"]["adb_path"], serial=cfg["device"]["serial"],
            production=True, template_dir=ROOT / "dataset" / "candidate" / "templates",
            log_dir=ROOT / "learning" / "maa_logs",
        )
        adapter.ensure_ready()

        def frame(retries=4):
            for _ in range(retries):
                f = adapter.frame()
                if f is not None:
                    return f if isinstance(f, Image.Image) else Image.fromarray(f)
                time.sleep(1)
            return None

        def toks(img):
            return _rapid_ocr_results(np.asarray(img), None, [])

        def text(img):
            return " ".join(t["text"] for t in toks(img))

        def save(img, tag):
            p = EVID / f"{tag}.png"
            p.parent.mkdir(parents=True, exist_ok=True)
            (img if isinstance(img, Image.Image) else Image.fromarray(img)).save(p)
            return p

        def tap(x, y, wait=2.0):
            adapter.click(int(x), int(y))
            time.sleep(wait)

        def tap_token(img, needle, wait=2.5, exact=False):
            cands = [t for t in toks(img)
                     if ((t["text"].strip() == needle) if exact else (needle in t["text"]))]
            if not cands:
                return False

            def cy(t):
                box = t.get("box") or ()
                if len(box) == 4 and all(isinstance(v, (int, float)) for v in box):
                    return box[1] + box[3] / 2
                ys = [float(p[1]) for p in box]
                return (min(ys) + max(ys)) / 2

            t = max(cands, key=cy)
            box = t.get("box") or ()
            if len(box) == 4 and all(isinstance(v, (int, float)) for v in box):
                x, y, w, h = (int(v) for v in box)
            else:
                xs = [float(p[0]) for p in box]
                ys = [float(p[1]) for p in box]
                x, y = int(min(xs)), int(min(ys))
                w, h = int(max(xs) - min(xs)), int(max(ys) - min(ys))
            tap(x + w // 2, y + h // 2, wait)
            return True

        def dismiss_popups(max_rounds=6):
            for i in range(max_rounds):
                f = frame()
                if f is None:
                    return
                t = text(f)
                if any(w in t for w in ("确定", "确认", "欢迎回来", "离线收益", "新的一天")):
                    save(f, f"popup_{i}")
                    tap_token(f, "确定", 2.0) or tap_token(f, "确认", 2.0) or tap(360, 1080, 2.0)
                    time.sleep(1.5)
                else:
                    return

        def back_to_city(maxn=8):
            for _ in range(maxn):
                f = frame()
                if f is None:
                    return None
                t = text(f)
                if "统帅" in t and "常规活动" in t:
                    return f
                if "退出游戏" in t:
                    tap_token(f, "取消", 1.5)
                    continue
                adapter.press_back()
                time.sleep(2.0)
            return frame()

        def wait_city(timeout=120):
            t0 = time.time()
            while time.time() - t0 < timeout:
                f = frame()
                if f is None:
                    time.sleep(3)
                    continue
                t = text(f)
                if "统帅" in t and "常规活动" in t:
                    return f
                if any(w in t for w in ("确定", "确认")):
                    tap_token(f, "确定", 2.0) or tap_token(f, "确认", 2.0)
                    time.sleep(2)
                time.sleep(2.5)
            return frame()

        def read_profile_name():
            dismiss_popups()
            f = back_to_city()
            if f is None:
                return None
            tap(44, 44, 3.0)
            f = frame()
            if f is None:
                return None
            t = text(f)
            if "领主档案" not in t:
                dismiss_popups()
                tap(44, 44, 3.0)
                f = frame()
                if f is None:
                    return None
                t = text(f)
            save(f, "profile")
            name = None
            acct = None
            for tk in toks(f):
                m = re.search(r"\[[A-Za-z0-9]+\]\S+", tk["text"])
                if m and "分享" not in tk["text"] and "布局" not in tk["text"] and name is None:
                    name = m.group(0)
                ma = re.search(r"账号[：:]\s*(\d+)", tk["text"])
                if ma:
                    acct = ma.group(1)
            out["profile_text"] = t[:300]
            back_to_city()
            return {"name": name, "account_display": acct}

        def open_rally_page():
            back_to_city()
            tap(511, 1243, 2.5)
            f = frame()
            save(f, "alliance")
            if not tap_token(f, "联盟战争", 2.5):
                tap(246, 669, 2.5)
            f = frame()
            save(f, "war")
            if not tap_token(f, "集结", 2.5, exact=True):
                tap(160, 130, 2.0)
            f = frame()
            save(f, "rally")
            return f

        # the worker should yield at the next step boundary now that we hold the lease
        deadline = time.time() + 240
        while time.time() < deadline:
            f = frame(retries=2)
            if f is None:
                time.sleep(3)
                continue
            t = text(f)
            if "统帅" in t and "常规活动" in t:
                break
            time.sleep(4)
        dismiss_popups()

        # ---------- switch to role B ----------
        cur = read_profile_name()
        out["current_role_before"] = cur
        if not (cur and cur.get("name") and "零氪" in cur["name"]):
            out["error_pre"] = "active role is not A; abort to avoid wrong switch"
            print(json.dumps(out, ensure_ascii=False, indent=1))
            return 1

        f = back_to_city()
        tap(44, 44, 3.0)
        f = frame()
        if "领主档案" not in text(f):
            dismiss_popups()
            tap(44, 44, 3.0)
            f = frame()
        if not tap_token(f, "设置", 2.5):
            adapter.swipe(360, 1000, 360, 800)
            time.sleep(1.5)
            f = frame()
            tap_token(f, "设置", 2.5)
        f = frame()
        if not tap_token(f, "角色管理", 3.0):
            adapter.swipe(360, 900, 360, 700)
            time.sleep(1.5)
            f = frame()
            tap_token(f, "角色管理", 3.0)
        f = frame()
        save(f, "roles")
        if not tap_token(f, "DIW", 3.0):
            out["error"] = "DIW row not found"
            print(json.dumps(out, ensure_ascii=False, indent=1))
            return 1
        f = frame()
        save(f, "confirm_dialog")
        if not tap_token(f, "确认", 3.0):
            tap_token(f, "确定", 3.0)
        wait_city()
        profB = read_profile_name()
        out["roleB_profile"] = profB
        out["roleB_verified"] = bool(profB and profB.get("name") and "DIW" in profB["name"])

        # ---------- AUTO_JOIN on the rally page ----------
        f = open_rally_page()
        st = read_state_from_image(f) if f is not None else {}
        out["autojoin_first_read"] = st.get("state")
        # if the live rally occupies the page, scroll down to find the toggle
        if st.get("state") == "UNKNOWN" and f is not None:
            for i in range(3):
                adapter.swipe(360, 1000, 360, 560)
                time.sleep(1.8)
                f = frame()
                save(f, f"rally_scroll_{i}")
                t = text(f)
                out.setdefault("rally_scroll_texts", []).append(t[:250])
                st = read_state_from_image(f)
                out["autojoin_read_after_scroll"] = st.get("state")
                if st.get("state") in {"ON", "OFF"}:
                    break
        toggle_state = st.get("state")
        out["autojoin_before"] = toggle_state
        if toggle_state == "OFF":
            tap(360, 1207, 2.5)
            f = frame()
            save(f, "after_tap")
            if "确认" in text(f):
                tap_token(f, "确认", 2.5)
                f = frame()
                save(f, "confirmed")
            st1 = read_state_from_image(f)
            out["autojoin_after"] = st1.get("state")
            if out["autojoin_after"] != "ON":
                time.sleep(2.0)
                f = frame()
                save(f, "reread")
                st1 = read_state_from_image(f)
                out["autojoin_after"] = st1.get("state")
            out["autojoin_toggled"] = True
        elif toggle_state == "ON":
            out["autojoin_after"] = "ON"
            out["autojoin_toggled"] = False
        else:
            out["autojoin_after"] = toggle_state
            out["autojoin_note"] = "toggle not locatable; evidence saved"

        # ---------- march queues (city view) ----------
        f = back_to_city()
        if f is not None:
            save(f, "city_B")
            ct = text(f)
            out["city_march_text"] = ct[:400]
            m = re.search(r"(\d)\s*/\s*(\d)\s*行军", ct)
            out["march_queues"] = m.group(0) if m else "not readable from city view"

        # ---------- bear time re-read (client direct, role B) ----------
        # reuse the pass-11 tab-template approach via the war page's reserve text:
        tap(665, 190, 2.5)
        f = frame()
        save(f, "activities")
        t = text(f)
        m = RESERVE_RE.search(t)
        if not m:
            for tk in toks(f):
                m = RESERVE_RE.search(tk["text"])
                if m:
                    break
        out["bear_time_raw"] = m.group(0) if m else None
        if m:
            y_, mo, d, h, mi = (int(g) for g in m.groups())
            out["bear_time_roleB"] = (f"{y_:04d}-{mo:02d}-{d:02d}"
                                      f"T{h:02d}:{mi:02d}:00+08:00")

        # ---------- switch back to role A ----------
        f = back_to_city()
        tap(44, 44, 3.0)
        f = frame()
        if "领主档案" not in text(f):
            dismiss_popups()
            tap(44, 44, 3.0)
            f = frame()
        if tap_token(f, "设置", 2.5):
            if tap_token(f, "角色管理", 3.0):
                f = frame()
                save(f, "roles_back")
                if tap_token(f, "零氪", 3.0):
                    if not tap_token(f, "确认", 3.0):
                        tap_token(f, "确定", 3.0)
                    wait_city()
                    profA = read_profile_name()
                    out["roleA_restored"] = profA
                    out["switched_back"] = bool(profA and profA.get("name")
                                                and "零氪" in profA["name"])

        dest = ROOT / "learning" / "bear_roleB_complete.json"
        dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        out["ledger"] = str(dest.relative_to(ROOT))
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    finally:
        lease.release(result="DONE", reason="role B completion done")


if __name__ == "__main__":
    raise SystemExit(main())
