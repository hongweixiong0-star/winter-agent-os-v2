# -*- coding: utf-8 -*-
"""Role B ([DIW]xhw) independent bear baseline.

Account/role isolation: switch via avatar -> 设置 -> 角色管理 -> [DIW]xhw,
verify the switch, then read the bear tab by template match (labels are
icon-overlapped and OCR-blind), AUTO_JOIN via red-badge pixels, march queue
text.  Then switch back to role A.  Nothing is inherited from role A.
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
EVID = ROOT / "dataset" / "evidence" / f"bear_baseline_roleB_{STAMP}"

TEMPLATE_SOURCE = ROOT / "dataset/evidence/bear_baseline_newaccount_20260927T095435Z/p8b_nudge_0.png"
TEMPLATE_BOX = (210, 88, 350, 168)  # 巨熊行动 tab

RESERVE_RE = re.compile(
    r"预约自动开启[：:]?\s*(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})\s*(\d{1,2})[::](\d{2})")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.executor_router import _rapid_ocr_results
    from winter_agent_v2.bear_state import read_state_from_image
    import cv2  # noqa: E402

    EVID.mkdir(parents=True, exist_ok=True)
    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(
        owner="DEVICE_BEAR_BASELINE_ROLEB", capability_id="BEAR_HUNT",
        ttl_seconds=1200, reason="role B independent bear baseline")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2

    out: dict = {"session_started_at": datetime.now(timezone.utc).isoformat()}
    try:
        template = np.asarray(
            Image.open(TEMPLATE_SOURCE).convert("RGB").crop(TEMPLATE_BOX), dtype=np.uint8)
        th, tw = template.shape[:2]

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

            t = max(cands, key=cy)  # bottom-most instance avoids chat overlays
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

        def back_to_city(maxn=8):
            for _ in range(maxn):
                f = frame()
                if f is None:
                    return None
                t = text(f)
                if "统帅" in t:
                    return f
                if "退出游戏" in t:
                    tap_token(f, "取消", 1.5)
                    continue
                adapter.press_back()
                time.sleep(2.0)
            return frame()

        def wait_city(timeout=100):
            t0 = time.time()
            while time.time() - t0 < timeout:
                f = frame()
                if f is None:
                    time.sleep(3)
                    continue
                t = text(f)
                if "统帅" in t:
                    return f
                if "确认" in t or "确定" in t or "切换" in t:
                    tap_token(f, "确认", 2.0) or tap_token(f, "确定", 2.0)
                time.sleep(3)
            return frame()

        def open_bear_page():
            """常规活动 -> template-match the bear tab -> read reserve time."""
            tap(665, 190, 2.5)
            best = None
            for i in range(14):
                f = frame()
                if f is None:
                    break
                band = np.asarray(f.crop((0, 60, 636, 190)), dtype=np.uint8)
                res = cv2.matchTemplate(band, template, cv2.TM_CCOEFF_NORMED)
                _, score, _, loc = cv2.minMaxLoc(res)
                if best is None or score > best[0]:
                    best = (float(score), loc[0] + tw // 2, 60 + loc[1] + th // 2, i)
                if score >= 0.72:
                    out.setdefault("tab_match_scores", []).append(round(float(score), 4))
                    out["tab_matched_at_step"] = i
                    tap(loc[0] + tw // 2, 60 + loc[1] + th // 2, 3.0)
                    break
                adapter.swipe(480, 122, 420, 122)
                time.sleep(1.8)
            if "tab_matched_at_step" not in out and best and best[0] >= 0.55:
                out["tapped_best_score"] = round(best[0], 4)
                tap(best[1], best[2], 3.0)
            page = frame()
            if page is None:
                return None
            save(page, "bear_page")
            pt = text(page)
            m = RESERVE_RE.search(pt)
            if not m:
                for t in toks(page):
                    m = RESERVE_RE.search(t["text"])
                    if m:
                        break
            return {"page_text": pt[:800], "match": m.group(0) if m else None,
                    "start": (f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
                              f"T{int(m.group(4)):02d}:{int(m.group(5)):02d}:00+08:00") if m else None}

        def read_autojoin():
            tap(511, 1243, 2.5)
            f = frame()
            save(f, "alliance")
            if not tap_token(f, "联盟战争", 2.5):
                tap(246, 669, 2.5)
            f = frame()
            save(f, "war")
            if "集结" in text(f):
                if not tap_token(f, "集结", 2.5, exact=True):
                    tap(160, 130, 2.0)
            f = frame()
            save(f, "rally")
            st = read_state_from_image(f) if f is not None else {}
            return {"state": st.get("state"), "evidence": st,
                    "page_text": text(f)[:400] if f is not None else None}

        # ---- handover ----
        for _ in range(6):
            f = frame()
            t = text(f)
            if "统帅" in t:
                break
            if "退出游戏" in t:
                tap_token(f, "取消", 1.5)
                continue
            adapter.press_back()
            time.sleep(2.0)

        # ---- switch to [DIW]xhw ----
        tap(44, 44, 2.5)
        f = frame()
        save(f, "01_profile_A")
        if not tap_token(f, "设置", 2.5):
            out["error"] = "no 设置 on profile"
            print(json.dumps(out, ensure_ascii=False, indent=1))
            return 1
        f = frame()
        if not tap_token(f, "角色管理", 3.0):
            out["error"] = "no 角色管理"
            print(json.dumps(out, ensure_ascii=False, indent=1))
            return 1
        f = frame()
        save(f, "02_roles")
        if not tap_token(f, "DIW", 3.0):
            out["error"] = "DIW row not found"
            print(json.dumps(out, ensure_ascii=False, indent=1))
            return 1
        f = frame()
        save(f, "03_confirm_dialog")
        out["confirm_dialog_text"] = text(f)[:200]
        if not tap_token(f, "确认", 3.0):
            tap_token(f, "确定", 3.0)
        fB = wait_city()
        save(fB, "04_after_switch")
        out["after_switch_text"] = text(fB)[:300]

        # verify role via profile
        tap(44, 44, 2.5)
        prof = frame()
        save(prof, "05_profile_B")
        ptB = text(prof)
        out["profile_B"] = ptB[:400]
        out["switch_verified"] = "DIW" in ptB
        out["profile_B_alliance_hint"] = next(
            (t["text"] for t in toks(prof) if t["text"].strip().startswith("[")), None)
        back_to_city()

        # ---- bear time (role B, independent) ----
        bt = open_bear_page()
        if bt:
            out["bear_page"] = {k: v for k, v in bt.items() if k != "page_text"}
            out["bear_page_text"] = bt["page_text"]
        back_to_city()

        # ---- AUTO_JOIN + rally context (role B) ----
        aj = read_autojoin()
        out["auto_join"] = aj
        back_to_city()

        # ---- switch back to role A ----
        tap(44, 44, 2.5)
        f = frame()
        if tap_token(f, "设置", 2.5):
            if tap_token(f, "角色管理", 3.0):
                f = frame()
                save(f, "06_roles_back")
                if tap_token(f, "零氪", 3.0):
                    if not tap_token(f, "确认", 3.0):
                        tap_token(f, "确定", 3.0)
                    wait_city()
                    out["switched_back"] = True
        back_to_city()

        dest = ROOT / "learning" / "bear_baseline_roleB.json"
        dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        out["ledger"] = str(dest.relative_to(ROOT))
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    finally:
        lease.release(result="DONE", reason="role B baseline done")


if __name__ == "__main__":
    raise SystemExit(main())
