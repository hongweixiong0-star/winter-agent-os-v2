# -*- coding: utf-8 -*-
"""START_RALLY once — giant-beast rally with FormationPolicy + shortest duration.

Operator rules (2026-09-28):
  * duration = SHORTEST option (3分钟) — RALLY_DURATION_PREFERENCE
  * formation chosen by TARGET: stamina-costing giant beast -> slot 1 (STAMINA_EFFICIENT)
    BEAR -> slot 8 (STRONGEST_ATTACK)

Chain (verified live 2026-09-28 00:02):
  city magnifier -> search panel 冰原巨兽 tab -> 搜索 -> tap located beast
  -> panel 集结 -> 发起集结 dialog (pick shortest) -> 发起集结 button
  -> PAGE_FORMATION -> SELECT_FORMATION_SLOT(policy) -> 出征
  -> verifier: city shows 集结中 + 集结队伍：<target> + march queue

usage: python tools/rally_start_once.py [target_type]
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
    FormationPolicy, formation_selected_verified,
    RALLY_DURATION_PREFERENCE, RALLY_DURATION_OPTIONS, stamina_cost_visible)

MAGNIFIER_TPL = ROOT / "dataset/candidate/templates/btn_open_resource_search__live_attempt8_idle__2.png"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    target_type = sys.argv[1] if len(sys.argv) > 1 else "ICEFIELD_BEAST"
    cfg = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.executor_router import _rapid_ocr_results

    STAMP = datetime.now().strftime("%Y%m%dT%H%M%S")
    EVID = ROOT / "dataset" / "evidence" / f"rally_start_once_{STAMP}"
    EVID.mkdir(parents=True, exist_ok=True)
    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(owner="DEVICE_RALLY_START", capability_id="RALLY_ENGINE",
                            ttl_seconds=420, reason="start rally once")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2
    out = {"flow": "START_RALLY", "target_type": target_type, "t0": datetime.now().strftime("%H:%M:%S")}
    try:
        ad = MaaExecutorAdapter(adb_path=cfg["device"]["adb_path"], serial=cfg["device"]["serial"],
                                production=True, template_dir=ROOT / "dataset/candidate/templates",
                                log_dir=ROOT / "learning/maa_logs")
        ad.ensure_ready()

        def frame(retries=3):
            for _ in range(retries):
                f = ad.frame()
                if f is not None:
                    return f if isinstance(f, Image.Image) else Image.fromarray(f)
                time.sleep(0.5)

        def toks(img):
            return _rapid_ocr_results(np.asarray(img), None, [])

        def text(img):
            return " ".join(t["text"] for t in toks(img))

        def save(img, tag):
            img.save(EVID / f"{tag}.png")

        def center(b):
            return int(b[0]) + int(b[2]) // 2, int(b[1]) + int(b[3]) // 2

        def tap(x, y, w=1.4):
            ad.click(int(x), int(y))
            time.sleep(w)

        def tap_tok(img, needle, w=1.8, exact=False, pick="bottom"):
            cs = [t for t in toks(img) if (t["text"].strip() == needle if exact else needle in t["text"])]
            if not cs:
                return False
            t = max(cs, key=lambda k: k["box"][1]) if pick == "bottom" else min(cs, key=lambda k: k["box"][1])
            tap(*center(t["box"]), w)
            return True

        def at_city(f):
            t = text(f)
            return "退出游戏" not in t and "领主档案" not in t and ("统帅" in t or "背包" in t)

        for _ in range(6):
            f = frame()
            t = text(f)
            if "退出游戏" in t:
                tap_tok(f, "取消", w=1.0, exact=True)
                continue
            if at_city(f):
                break
            ad.press_back(); time.sleep(0.9)

        # 1) open the search panel
        f = frame()
        if "搜索" not in text(f):
            tpl = cv2.cvtColor(np.asarray(Image.open(MAGNIFIER_TPL).convert("RGB")), cv2.COLOR_RGB2BGR)
            bgr = cv2.cvtColor(np.asarray(f.convert("RGB")), cv2.COLOR_RGB2BGR)
            res = cv2.matchTemplate(bgr, tpl, cv2.TM_CCOEFF_NORMED)
            _, sc, _, loc = cv2.minMaxLoc(res)
            if sc >= 0.7:
                h, w = tpl.shape[:2]
                tap(loc[0] + w // 2, loc[1] + h // 2, 2.0)
            else:
                tap(660, 990, 2.0)
            f = frame()
        save(f, "01_panel")

        # 2) switch to the 冰原巨兽 tab (OCR variants 巨兽/巨餐/巨善/巨鲁)
        for tk in toks(f):
            if re.search(r"冰原巨", tk["text"]):
                tap(*center(tk["box"]), 1.5)
                break
        f = frame(); save(f, "02_giant_tab")

        # 3) 搜索 -> locate
        for tk in toks(f):
            if tk["text"].strip() == "搜索":
                tap(*center(tk["box"]), 3.0)
                break
        f = frame(); save(f, "03_located")

        # 4) tap the located beast -> panel -> 集结
        cands = [center(tk["box"]) for tk in toks(f)
                 if re.search(r"等级\s*\d+", tk["text"]) and 150 < center(tk["box"])[1] < 1000]
        for c in (cands[:2] or [(360, 600)]):
            tap(*c, 2.2)
            f = frame()
            if "集结" in text(f):
                break
        save(f, "04_target_panel")
        out["panel_text"] = text(f)[:200]
        if "集结" not in text(f):
            out["error"] = "no 集结 on target panel"
            print(json.dumps(out, ensure_ascii=False))
            return 1
        tap_tok(f, "集结", w=2.0, exact=True)
        f = frame(); save(f, "05_setup_dialog")
        # 5) shortest duration
        if not tap_tok(f, RALLY_DURATION_PREFERENCE, w=1.2, exact=True):
            for opt in RALLY_DURATION_OPTIONS:
                if tap_tok(f, opt, w=1.2, exact=True):
                    break
        out["duration"] = RALLY_DURATION_PREFERENCE
        f = frame()
        # 6) the dialog's own 发起集结 button = LOWEST one on screen
        tap_tok(f, "发起集结", w=2.5, pick="bottom")
        f = frame(); save(f, "06_formation")
        ft = text(f)
        out["formation_text"] = ft[:200]
        if "盾兵" not in ft:
            out["error"] = "PAGE_FORMATION not reached"
            print(json.dumps(out, ensure_ascii=False))
            return 1
        before = FormationPolicy.fingerprint_from_ocr(ft)
        # live ground truth: the 罐头 badge inside 出征 = this dispatch spends stamina
        cost = stamina_cost_visible(f)
        out["stamina_cost_badge"] = cost          # None = no badge (no stamina)
        out["stamina_cost_detected"] = cost is not None
        pol = FormationPolicy("ROLE_CURRENT")
        sel = pol.select({"task_type": "START_RALLY", "target_type": target_type,
                          "action_type": "START", "stamina_cost": target_type != "BEAR",
                          "stamina_cost_visible": cost is not None})
        out["slot_choice"] = sel
        slot = sel["formation_slot"]
        x, y = FormationPolicy.slot_tap_point(slot, f.size[0])
        tap(x, y, 1.2)
        f2 = frame(); save(f2, f"07_slot{slot}")
        after = FormationPolicy.fingerprint_from_ocr(text(f2))
        out["slot_verified"] = formation_selected_verified(before, after)
        out["before_fp"] = before.get("troops"); out["after_fp"] = after.get("troops")
        tap_tok(f2, "出征", w=2.0, exact=True)
        out["dispatched"] = True
        time.sleep(4)
        f3 = frame(); save(f3, "08_after")
        t3 = text(f3)
        out["after_text"] = t3[:200]
        out["verified_rally_active"] = ("集结中" in t3) or ("集结队伍" in t3)
        m = re.search(r"行军\s*(\d+)\s*/\s*(\d+)", t3)
        out["march"] = m.group(0) if m else None
        out["done"] = datetime.now().strftime("%H:%M:%S")
        print(json.dumps(out, ensure_ascii=False, indent=1))
        (ROOT / "learning" / f"rally_start_once_{STAMP}.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        return 0
    finally:
        lease.release(result="DONE", reason="start rally once done")


if __name__ == "__main__":
    raise SystemExit(main())
