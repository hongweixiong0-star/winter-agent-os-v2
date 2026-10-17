# -*- coding: utf-8 -*-
"""Scan the 8 preset formation slots of the CURRENT role.

Route: city -> beast search -> beast dialog -> 出征 (opens PAGE_FORMATION)
       -> tap preset slots 1..8, capture fingerprint each
       -> back out WITHOUT dispatching (no march, no stamina).

Output: learning/formation_fingerprint_<role_tag>.json
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

TPL = {
    "MAGNIFIER": "dataset/candidate/templates/btn_open_resource_search__live_attempt8_idle__2.png",
    "BEAST_TAB": "dataset/candidate/templates/resource_beast__legacy_search_resource_panel__0.png",
    "SUBMIT": "dataset/candidate/templates/btn_resource_search_submit__live_executor_search_open__2.png",
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    role_tag = sys.argv[1] if len(sys.argv) > 1 else "ROLE_CURRENT"
    cfg = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.executor_router import _rapid_ocr_results

    STAMP = datetime.now().strftime("%Y%m%dT%H%M%S")
    outd = ROOT / "dataset" / "evidence" / f"formation_scan_{role_tag}_{STAMP}"
    outd.mkdir(parents=True, exist_ok=True)
    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(owner=f"DEVICE_FORMATION_SCAN_{role_tag}", capability_id="FORMATION",
                             ttl_seconds=600, reason=f"scan 8 preset fingerprints for {role_tag}")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2
    out: dict = {"role_tag": role_tag, "t0": datetime.now().strftime("%H:%M:%S"), "slots": {}}
    try:
        tpls = {k: cv2.cvtColor(np.asarray(Image.open(ROOT / p).convert("RGB")), cv2.COLOR_RGB2BGR)
                for k, p in TPL.items()}
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
            img.save(outd / f"{tag}.png")

        def tap(x, y, w=1.6):
            ad.click(int(x), int(y))
            time.sleep(w)

        def tap_tok(img, needle, w=2.0, exact=False):
            cs = [t for t in toks(img) if (t["text"].strip() == needle if exact else needle in t["text"])]
            if not cs:
                return False
            t = max(cs, key=lambda k: (k.get("box") or (0, 0, 0, 0))[1])
            b = t.get("box") or ()
            if len(b) == 4:
                tap(int(b[0] + b[2]) // 2, int(b[1] + b[3]) // 2, w)
                return True
            return False

        def guard(f):
            t = text(f)
            if "退出游戏" in t:
                tap_tok(f, "取消", w=1.5, exact=True); return True
            if any(w in t for w in ("￥", "支付", "购买", "礼包", "祝贺你", "离线收益", "欢迎回来")):
                cs = [tt for tt in toks(f) if tt["text"].strip() in ("取消", "关闭")]
                if cs:
                    b = cs[0].get("box") or ()
                    if len(b) == 4:
                        tap(int(b[0] + b[2]) // 2, int(b[1] + b[3]) // 2, 1.5)
                else:
                    ad.press_back(); time.sleep(1.2)
                return True
            return False

        def at_city(f):
            t = text(f)
            return "退出游戏" not in t and ("统帅" in t or "背包" in t)

        # ---------- clean & go city ----------
        for _ in range(4):
            f = frame()
            if f is None:
                continue
            if guard(f):
                continue
            if at_city(f):
                break
            ad.press_back(); time.sleep(1.4)

        # ---------- open PAGE_FORMATION via beast attack dialog ----------
        f = frame()
        bgr = cv2.cvtColor(np.asarray(f.convert("RGB")), cv2.COLOR_RGB2BGR)
        opened = False
        for key in ("MAGNIFIER",):
            res = cv2.matchTemplate(bgr, tpls[key], cv2.TM_CCOEFF_NORMED)
            _, sc, _, loc = cv2.minMaxLoc(res)
            if sc >= 0.7:
                h, w = tpls[key].shape[:2]
                tap(loc[0] + w // 2, loc[1] + h // 2, 2.0)
                opened = True
                break
        if not opened:
            tap(660, 990, 2.0)
        f = frame(); save(f, "01_panel")
        bgr = cv2.cvtColor(np.asarray(f.convert("RGB")), cv2.COLOR_RGB2BGR)
        for key in ("BEAST_TAB",):
            res = cv2.matchTemplate(bgr, tpls[key], cv2.TM_CCOEFF_NORMED)
            _, sc, _, loc = cv2.minMaxLoc(res)
            if sc >= 0.7:
                h, w = tpls[key].shape[:2]
                tap(loc[0] + w // 2, loc[1] + h // 2, 1.8)
        f = frame()
        bgr = cv2.cvtColor(np.asarray(f.convert("RGB")), cv2.COLOR_RGB2BGR)
        res = cv2.matchTemplate(bgr, tpls["SUBMIT"], cv2.TM_CCOEFF_NORMED)
        _, sc, _, loc = cv2.minMaxLoc(res)
        if sc >= 0.7:
            h, w = tpls["SUBMIT"].shape[:2]
            tap(loc[0] + w // 2, loc[1] + h // 2, 3.0)
        else:
            tap_tok(f, "搜索", w=3.0)
        f = frame(); save(f, "02_world")
        # STRICT: world step must show a 等级N target token; otherwise abort cleanly.
        target_cands = []
        for attempt in range(2):
            f = frame()
            target_cands = []
            for tk in toks(f):
                if re.search(r"等级\s*\d+", tk["text"]) and any(
                        w in tk["text"] for w in ("雪豹", "避役", "猛犸", "野兽", "巨兽", "犀牛", "棕熊", "麋鹿")):
                    b = tk.get("box") or ()
                    if len(b) == 4:
                        c = (int(b[0] + b[2]) // 2, int(b[1] + b[3]) // 2)
                        if 300 < c[1] < 750:
                            target_cands.append(c)
            if target_cands:
                break
            if attempt == 0 and tap_tok(f, "搜索", w=3.0, exact=True):
                continue
            break
        if not target_cands:
            # the client centres the searched beast; try screen-centre taps first
            target_cands = [(360, 600), (360, 560), (360, 650)]
        out["target_candidates"] = target_cands
        opened = False
        for c in target_cands[:3]:
            tap(*c, 2.5)
            f = frame(); save(f, "03_dialog_try")
            if any(w in text(f) for w in ("攻击", "出征")):
                opened = True
                break
            ad.press_back(); time.sleep(1.5)
        if not opened:
            out["error"] = "beast dialog never opened"
            print(json.dumps(out, ensure_ascii=False)); return 1
        f = frame(); save(f, "03_dialog")
        if not any(tap_tok(f, w, w=2.5, exact=True) for w in ("出征", "攻击")):
            out["error"] = "cannot open formation page"
            print(json.dumps(out, ensure_ascii=False)); return 1
        f = frame(); save(f, "04_formation")
        if "预设" not in text(f) and "盾兵" not in text(f):
            out["error"] = "PAGE_FORMATION not detected"
            print(json.dumps(out, ensure_ascii=False)); return 1

        W = f.size[0]
        # ---------- scan slots 1..8 ----------
        prev_fp = None
        for slot in range(1, 9):
            x, y = FormationPolicy.slot_tap_point(slot, W)
            tap(x, y, 1.8)
            sf = frame(); save(sf, f"slot_{slot}")
            st = text(sf)
            fp = FormationPolicy.fingerprint_from_ocr(st)
            # hero band crop as visual fingerprint
            hero = sf.crop((int(0.1 * W), int(0.23 * sf.size[1]), int(0.9 * W), int(0.46 * sf.size[1])))
            hero.save(outd / f"slot_{slot}_hero.png")
            fp["hero_crop"] = f"slot_{slot}_hero.png"
            verified = formation_selected_verified(prev_fp, fp)
            out["slots"][str(slot)] = {
                "semantic": FormationPolicy.slot_tap_point.__name__ and __import__(
                    "winter_agent_v2.formation_policy", fromlist=["SLOT_SEMANTICS"]).SLOT_SEMANTICS[slot],
                "fingerprint": fp,
                "changed_vs_prev": verified,
            }
            prev_fp = fp
            out.setdefault("ocr_samples", {})[str(slot)] = st[:220]

        # ---------- leave without dispatch ----------
        for _ in range(4):
            f = frame()
            if f is None:
                continue
            if at_city(f):
                break
            if "退出游戏" in text(f):
                tap_tok(f, "取消", w=1.5, exact=True)
                continue
            ad.press_back(); time.sleep(1.5)
        out["back_at_city"] = at_city(frame())
        out["done"] = datetime.now().strftime("%H:%M:%S")

        out_path = ROOT / "learning" / f"formation_fingerprint_{role_tag}.json"
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        out["saved"] = str(out_path)
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    finally:
        lease.release(result="DONE", reason="formation scan done")


if __name__ == "__main__":
    raise SystemExit(main())
