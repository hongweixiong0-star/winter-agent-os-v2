# -*- coding: utf-8 -*-
"""Role B AUTO_JOIN retry + restore role A.

Learned from bear_roleB_complete: the auto-join toggle only renders when the
rally page shows 当前暂无战事; role B's alliance had a live rally then.  That
rally has departed, so the toggle should be readable now.  Device is expected
to still be on role B (the previous switch-back did not record success).
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
EVID = ROOT / "dataset" / "evidence" / f"bear_roleB_autojoin_retry_{STAMP}"


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
        owner="DEVICE_ROLEB_AUTOJOIN", capability_id="BEAR_HUNT",
        ttl_seconds=1200, reason="role B auto-join toggle (rally page now empty) + restore A")
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
            save(f, f"confirm_{needle}")
            if not tap_token(f, "确认", 3.0):
                tap_token(f, "确定", 3.0)
            wait_city()
            return True

        dismiss_popups()
        cur = read_profile_name()
        out["current_role"] = cur
        out["on_role_B"] = bool(cur and "DIW" in cur)

        if not out["on_role_B"]:
            # switch to B first
            if not switch_to("DIW"):
                out["error"] = "could not switch to DIW"
                print(json.dumps(out, ensure_ascii=False, indent=1))
                return 1
            cur = read_profile_name()
            out["roleB_verified"] = bool(cur and "DIW" in cur)

        # ---------- AUTO_JOIN read/toggle on the (now empty) rally page ----------
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
        save(f, "rally_now")
        out["rally_page_head"] = text(f)[:250] if f is not None else None
        st = read_state_from_image(f) if f is not None else {}
        out["autojoin_before"] = st.get("state")
        if st.get("state") == "OFF":
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
        else:
            out["autojoin_after"] = st.get("state")
            out["autojoin_toggled"] = False

        # ---------- restore role A ----------
        back_to_city()
        cur2 = read_profile_name()
        if cur2 and "零氪" in cur2:
            out["switched_back"] = True
            out["roleA_verified"] = cur2
        else:
            ok = switch_to("零氪")
            profA = read_profile_name()
            out["switched_back"] = bool(ok and profA and "零氪" in profA)
            out["roleA_verified"] = profA

        dest = ROOT / "learning" / "bear_roleB_autojoin.json"
        dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        out["ledger"] = str(dest.relative_to(ROOT))
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    finally:
        lease.release(result="DONE", reason="autojoin retry done")


if __name__ == "__main__":
    raise SystemExit(main())
