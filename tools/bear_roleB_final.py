# -*- coding: utf-8 -*-
"""Final bounded attempt: role B auto-join, with a hard deadline.

Fixes the poll session's bug (no role check) and adds a hard deadline:
whatever happens, the device must be back on role A well before 20:30.
If the toggle cannot be caught in a rally gap, role B's join method for
tonight is explicitly the JOIN_RALLY fallback (L4 path), not AUTO_JOIN.
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
EVID = ROOT / "dataset" / "evidence" / f"bear_roleB_final_{STAMP}"

DEADLINE_MONOTONIC_BUDGET = 13 * 60  # hard budget; well before 20:30


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
        owner="DEVICE_ROLEB_FINAL", capability_id="BEAR_HUNT",
        ttl_seconds=1100, reason="final role B auto-join attempt with hard deadline")
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
            for _ in range(max_rounds):
                f = frame()
                if f is None:
                    return
                t = text(f)
                if any(w in t for w in ("确定", "确认", "欢迎回来", "离线收益")):
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

        def profile_name():
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
            for tk in toks(f):
                m = re.search(r"\[[A-Za-z0-9]+\]\S+", tk["text"])
                if m and "分享" not in tk["text"] and "布局" not in tk["text"]:
                    name = m.group(0)
                    break
            back_to_city()
            return name

        def switch_to(needle):
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
            save(f, f"roles_{needle}")
            if not tap_token(f, needle, 3.0):
                return False
            f = frame()
            if not tap_token(f, "确认", 3.0):
                tap_token(f, "确定", 3.0)
            wait_city()
            return True

        def open_rally_on_current_role():
            """Navigate and return (frame, state) with a navigation sanity check."""
            for attempt in range(3):
                f = back_to_city()
                if f is None:
                    continue
                tap(511, 1243, 2.5)
                f = frame()
                save(f, f"alliance_a{attempt}")
                if not tap_token(f, "联盟战争", 2.5):
                    tap(246, 669, 2.5)
                f = frame()
                wt = text(f)
                if "联盟战争" not in wt:
                    continue  # navigation failed, retry
                save(f, f"war_a{attempt}")
                if not tap_token(f, "集结", 2.5, exact=True):
                    tap(160, 130, 2.0)
                f = frame()
                save(f, f"rally_a{attempt}")
                t = text(f)
                if "联盟战争" in t and ("集结" in t or "暂无战事" in t):
                    return f, t
            return None, None

        t_end = time.monotonic() + DEADLINE_MONOTONIC_BUDGET
        dismiss_popups()
        cur = profile_name()
        out["current_role"] = cur

        # ensure we are on role B
        if not (cur and "DIW" in cur):
            if not switch_to("DIW"):
                out["error"] = "switch to DIW failed"
            else:
                cur = profile_name()
                out["roleB_verified"] = cur

        result = None
        if cur and "DIW" in cur and time.monotonic() < t_end:
            for attempt in range(4):
                if time.monotonic() > t_end - 180:  # keep 3 min to switch back
                    break
                f, t = open_rally_on_current_role()
                if f is None:
                    time.sleep(15)
                    continue
                st = read_state_from_image(f)
                entry = {"attempt": attempt, "state": st.get("state"), "head": t[:160]}
                out.setdefault("attempts", []).append(entry)
                if st.get("state") in {"ON", "OFF"} or "自动加入" in t:
                    result = st.get("state")
                    if st.get("state") == "OFF":
                        tap(360, 1207, 2.5)
                        f2 = frame()
                        save(f2, "after_tap")
                        if "确认" in text(f2):
                            tap_token(f2, "确认", 2.5)
                            f2 = frame()
                        st1 = read_state_from_image(f2)
                        result = st1.get("state")
                        if result != "ON":
                            time.sleep(2.0)
                            f2 = frame()
                            result = read_state_from_image(f2).get("state")
                        out["toggled"] = True
                    break
                m = re.search(r"集结中[：:]?\s*(\d{1,2}):(\d{2}):(\d{2})", t)
                if m:
                    secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
                    wait = min(max(secs + 10, 15), 120)
                    entry["departs_in_s"] = secs
                    entry["sleep_s"] = wait
                    time.sleep(wait)
                else:
                    time.sleep(20)

        out["autojoin_roleB"] = result or "UNKNOWN"
        out["join_method_tonight"] = ("AUTO_JOIN=ON" if result == "ON"
                                      else "JOIN_RALLY fallback (L4) at 21:00; "
                                           "retry toggle at B T-15 20:45 if a gap appears")

        # ---------- restore role A (mandatory) ----------
        back_to_city()
        cur2 = profile_name()
        if cur2 and "零氪" in cur2:
            out["switched_back"] = True
        else:
            ok = switch_to("零氪")
            profA = profile_name()
            out["switched_back"] = bool(ok and profA and "零氪" in profA)
        out["roleA_verified"] = profile_name()

        dest = ROOT / "learning" / "bear_roleB_final.json"
        dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        out["ledger"] = str(dest.relative_to(ROOT))
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    finally:
        lease.release(result="DONE", reason="final role B attempt done")


if __name__ == "__main__":
    raise SystemExit(main())
