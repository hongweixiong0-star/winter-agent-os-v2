# -*- coding: utf-8 -*-
"""Robust: ensure device is back on role A ([ioi]零氪纯盾流).

Dismiss popups aggressively, open avatar -> 设置 -> 角色管理, verify the
roles page is really open (contains two role rows), tap the A row, confirm,
then verify via profile (领主档案) that the active role is A.
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
EVID = ROOT / "dataset" / "evidence" / f"roleA_restore_{STAMP}"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.executor_router import _rapid_ocr_results

    EVID.mkdir(parents=True, exist_ok=True)
    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(
        owner="DEVICE_ROLEA_RESTORE", capability_id="BEAR_HUNT",
        ttl_seconds=900, reason="restore role A as active role")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2

    out: dict = {}
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

        def dismiss_popups(max_rounds=5):
            for i in range(max_rounds):
                f = frame()
                if f is None:
                    return
                t = text(f)
                # known popups: 确定/确认 buttons, 新的一天, 欢迎回来, 离线收益
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

        def read_profile_name():
            dismiss_popups()
            f = back_to_city()
            tap(44, 44, 3.0)
            f = frame()
            if f is None:
                return None
            t = text(f)
            if "领主档案" not in t:
                # maybe a popup again
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
            out["profile_text"] = t[:300]
            back_to_city()
            return name

        cur = read_profile_name()
        out["current_role"] = cur

        if cur and "零氪" in cur:
            out["action"] = "already role A"
        else:
            # switch flow with verification
            dismiss_popups()
            f = back_to_city()
            tap(44, 44, 3.0)
            f = frame()
            t = text(f)
            save(f, "s1_after_avatar")
            if "领主档案" not in t:
                dismiss_popups()
                tap(44, 44, 3.0)
                f = frame()
                t = text(f)
            if not tap_token(f, "设置", 2.5):
                # 设置 entry may be lower on profile page: scroll
                adapter.swipe(360, 1000, 360, 800)
                time.sleep(1.5)
                f = frame()
                tap_token(f, "设置", 2.5)
            f = frame()
            save(f, "s2_settings")
            if not tap_token(f, "角色管理", 3.0):
                adapter.swipe(360, 900, 360, 700)
                time.sleep(1.5)
                f = frame()
                tap_token(f, "角色管理", 3.0)
            f = frame()
            save(f, "s3_roles")
            roles_txt = text(f)
            out["roles_page_text"] = roles_txt[:300]
            if "零氪" not in roles_txt and "DIW" not in roles_txt:
                out["error"] = "roles page not open"
            else:
                if tap_token(f, "零氪", 3.0):
                    f = frame()
                    save(f, "s4_confirm")
                    if not tap_token(f, "确认", 3.0):
                        tap_token(f, "确定", 3.0)
                    # wait through reload
                    t0 = time.time()
                    while time.time() - t0 < 120:
                        f = frame()
                        if f is None:
                            time.sleep(3)
                            continue
                        t = text(f)
                        if "统帅" in t and "常规活动" in t:
                            break
                        if any(w in t for w in ("确定", "确认")):
                            tap_token(f, "确定", 2.0) or tap_token(f, "确认", 2.0)
                        time.sleep(3)
                    save(f, "s5_after_reload")
                    final = read_profile_name()
                    out["verified_role"] = final
                    out["switched_back"] = bool(final and "零氪" in final)
                else:
                    out["error"] = "A row not found"

        dest = ROOT / "learning" / "roleA_restore.json"
        dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    finally:
        lease.release(result="DONE", reason="restore done")


if __name__ == "__main__":
    raise SystemExit(main())
