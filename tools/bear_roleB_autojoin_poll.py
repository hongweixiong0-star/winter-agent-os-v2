# -*- coding: utf-8 -*-
"""Bounded poller: catch role B's auto-join toggle in a gap between DIW rallies.

The toggle only renders on 联盟战争/集结 when the page shows 当前暂无战事.
DIW is chain-starting rallies (observed two back-to-back), so this session
polls: open rally page -> if empty state, read/toggle AUTO_JOIN and verify;
if a rally is live, read its 集结中 countdown and sleep until just after it
departs.  Hard time budget keeps role A's 20:30 open safe.
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
EVID = ROOT / "dataset" / "evidence" / f"bear_roleB_autojoin_poll_{STAMP}"

BUDGET_S = 12 * 60


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
        owner="DEVICE_ROLEB_AUTOJOIN_POLL", capability_id="BEAR_HUNT",
        ttl_seconds=1000, reason="poll for empty-rally state to set role B auto-join")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2

    out: dict = {"session_started_at": datetime.now(timezone.utc).isoformat(),
                 "polls": []}
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

        def open_rally():
            back_to_city()
            tap(511, 1243, 2.5)
            f = frame()
            if not tap_token(f, "联盟战争", 2.5):
                tap(246, 669, 2.5)
            f = frame()
            if not tap_token(f, "集结", 2.5, exact=True):
                tap(160, 130, 2.0)
            return frame()

        t_end = time.monotonic() + BUDGET_S
        poll_n = 0
        done = False
        while time.monotonic() < t_end and not done:
            poll_n += 1
            f = open_rally()
            if f is None:
                time.sleep(5)
                continue
            t = text(f)
            st = read_state_from_image(f)
            entry = {"poll": poll_n, "state": st.get("state"),
                     "head": t[:150]}
            if "自动加入" in t or st.get("state") in {"ON", "OFF"}:
                save(f, f"toggle_visible_{poll_n}")
                entry["toggle_visible"] = True
                if st.get("state") == "OFF":
                    tap(360, 1207, 2.5)
                    f2 = frame()
                    save(f2, f"after_tap_{poll_n}")
                    if "确认" in text(f2):
                        tap_token(f2, "确认", 2.5)
                        f2 = frame()
                    st1 = read_state_from_image(f2)
                    entry["after_tap"] = st1.get("state")
                    if entry["after_tap"] != "ON":
                        time.sleep(2.0)
                        f2 = frame()
                        st1 = read_state_from_image(f2)
                        entry["after_tap"] = st1.get("state")
                    entry["toggled"] = True
                done = True
            else:
                m = re.search(r"集结中[：:]?\s*(\d{1,2}):(\d{2}):(\d{2})", t)
                if m:
                    secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
                    wait = min(max(secs + 8, 10), 150)
                    entry["rally_departs_in_s"] = secs
                    entry["sleep_s"] = wait
                else:
                    wait = 20
                    entry["sleep_s"] = wait
                out["polls"].append(entry)
                # stay on the page: it updates live; just wait and re-grab
                time.sleep(wait)
                continue
            out["polls"].append(entry)
        out["done"] = done
        out["final_state"] = entry.get("after_tap") or entry.get("state")

        # back to city, leave device clean
        back_to_city()
        dest = ROOT / "learning" / "bear_roleB_autojoin_poll.json"
        dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        out["ledger"] = str(dest.relative_to(ROOT))
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    finally:
        lease.release(result="DONE", reason="poll done")


if __name__ == "__main__":
    raise SystemExit(main())
