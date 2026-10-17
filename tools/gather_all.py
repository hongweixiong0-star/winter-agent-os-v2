# -*- coding: utf-8 -*-
"""Send every free march queue out to gather (operator request 2026-09-28).

Flow per queue:
  city -> magnifier -> search panel -> resource tab (ROI-first OCR)
  -> 搜索 (client auto-flies) -> node card -> 采集 -> PAGE_FORMATION
  -> remove non-gather heroes (keep one; red ⊖ on the extra hero cards)
  -> 出征 -> city: 行军 N/6 must increase

Reading everywhere goes through winter_agent_v2.ocr_full.read_all (standing rule:
never miss button text).  Resource tabs are located by winter_agent_v2.ocr_roi
(icon+label element box, no click offsets).

usage: python tools/gather_all.py [max_minutes] [target_queues]
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
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

sys.path.insert(0, str(ROOT))
from winter_agent_v2.ocr_full import read_all, find_text  # noqa: E402
from winter_agent_v2.ocr_roi import find_resource_tab  # noqa: E402
from winter_agent_v2.formation_policy import stamina_cost_visible  # noqa: E402
from winter_agent_v2.semantic_executor import (  # noqa: E402
    SemanticAction, SemanticActionExecutor, Observation, SUCCESS, STILL_PENDING, AMBIGUOUS)

MAGNIFIER_TPL = ROOT / "dataset/candidate/templates/btn_open_resource_search__live_attempt8_idle__2.png"
RESOURCE_ORDER = ("生肉", "木材", "煤矿", "铁矿", "养殖场", "野兽")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 12.0
    want = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    cfg = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    import cv2

    STAMP = datetime.now().strftime("%Y%m%dT%H%M%S")
    EVID = ROOT / "dataset" / "evidence" / f"gather_all_{STAMP}"
    EVID.mkdir(parents=True, exist_ok=True)
    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(owner="DEVICE_GATHER_ALL", capability_id="GATHER",
                            ttl_seconds=int(minutes * 60) + 180, reason="gather with all queues")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2
    log: dict = {"flow": "GATHER_ALL", "t0": datetime.now().strftime("%H:%M:%S"), "dispatches": []}
    try:
        ad = MaaExecutorAdapter(adb_path=cfg["device"]["adb_path"], serial=cfg["device"]["serial"],
                                production=True, template_dir=ROOT / "dataset/candidate/templates",
                                log_dir=ROOT / "learning/maa_logs")
        ad.ensure_ready()

        def frame(r=3):
            for _ in range(r):
                f = ad.frame()
                if f is not None:
                    return f if isinstance(f, Image.Image) else Image.fromarray(f)
                time.sleep(0.4)

        def save(img, tag):
            img.save(EVID / f"{tag}.png")

        def tap(x, y, w=1.3):
            ad.click(int(x), int(y)); time.sleep(w)

        def center(b):
            return int(b[0]) + int(b[2]) // 2, int(b[1]) + int(b[3]) // 2

        def read(f):
            return read_all(f)

        def toks(f):
            return read(f)

        def text(f):
            return " ".join(t["text"] for t in read(f))

        def march(f):
            m = re.search(r"行军\s*(\d+)\s*/\s*(\d+)", text(f))
            return (int(m.group(1)), int(m.group(2))) if m else (None, None)

        def at_city(f):
            t = text(f)
            return "退出游戏" not in t and "领主档案" not in t and ("统帅" in t or "背包" in t)

        def to_city():
            for _ in range(6):
                f = frame()
                t = text(f)
                if "退出游戏" in t:
                    hit = find_text(f, ["取消"])
                    if hit:
                        tap(*hit["centre"], 1.0)
                    continue
                if at_city(f):
                    return f
                ad.press_back(); time.sleep(0.9)
            return frame()

        def open_panel():
            f = to_city()
            bgr = cv2.cvtColor(np.asarray(f.convert("RGB")), cv2.COLOR_RGB2BGR)
            tpl = cv2.cvtColor(np.asarray(Image.open(MAGNIFIER_TPL).convert("RGB")), cv2.COLOR_RGB2BGR)
            res = cv2.matchTemplate(bgr, tpl, cv2.TM_CCOEFF_NORMED)
            _, sc, _, loc = cv2.minMaxLoc(res)
            if sc >= 0.7:
                h, w = tpl.shape[:2]
                tap(loc[0] + w // 2, loc[1] + h // 2, 2.0)
            else:
                tap(54, 875, 2.0)
            f = frame()
            if "搜索" not in text(f):
                tap(54, 875, 2.0); f = frame()
            return f

        def tap_search(f):
            hit = find_text(f, ["搜索"])
            if hit and "仅搜索" not in hit["text"]:
                tap(*hit["centre"], 3.2)
                return True
            return False

        def tap_gather_button(f):
            """Locate the node-card 采集 button (full read, lowest instance)."""
            cs = [t for t in toks(f) if t["text"].strip() == "采集"]
            if not cs:
                return None
            btn = max(cs, key=lambda t: t["centre"][1])
            tap(*btn["centre"], 2.2)
            return btn["centre"]

        def remove_extra_heroes(f):
            """Hero cards carry a red ⊖ at their top-right (~y 316 in 720x1280).
            Keep the first hero; remove the rest (operator: only the gather hero)."""
            W, H = f.size
            removed = 0
            for dx in (608, 420):                     # rightmost first
                tap(int(dx * W / 720), int(316 * H / 1280), 1.3)
                removed += 1
            return removed

        def dispatch(f):
            """出征 through the semantic executor: authorized -> click -> verify -> retry."""
            def st(img):
                toks = read_all(img)
                txt = " ".join(t["text"] for t in toks)
                return {"text": txt, "tokens": toks,
                        "has_dispatch": any(t["text"].strip() == "出征" for t in toks),
                        "has_form": ("盾兵" in txt or "射手" in txt)}
            ex = SemanticActionExecutor(
                observe=lambda: Observation(frame=frame(), state=st(frame())),
                click=lambda x, y: ad.click(int(x), int(y)),
                settle=lambda s: time.sleep(s))
            act = SemanticAction(
                name="DISPATCH",
                locate=lambda o: next((t["centre"] for t in o.state["tokens"]
                                       if t["text"].strip() == "出征"), None),
                postcondition=lambda b, a: (
                    SUCCESS if (not a.state["has_dispatch"] and not a.state["has_form"])
                    else (STILL_PENDING if a.state["has_dispatch"] else AMBIGUOUS)),
                settle_s=2.0, max_retry=2)
            r = ex.execute(act)
            log.setdefault("click_metrics", []).append(
                {"action": "DISPATCH", "outcome": r.outcome, "attempts": r.attempts})
            return r.ok

        base, cap = march(to_city())
        log["march_start"] = f"{base}/{cap}"
        deadline = time.time() + minutes * 60
        idx = 0
        while time.time() < deadline and (base or 0) < want:
            idx += 1
            res_name = RESOURCE_ORDER[(idx - 1) % len(RESOURCE_ORDER)]
            f = open_panel(); save(f, f"{idx:02d}_panel")
            tab = find_resource_tab(f, (res_name,))
            if tab is None:
                log["dispatches"].append({"n": idx, "resource": res_name, "error": "tab not found"})
                time.sleep(2); continue
            tap(*tab.get("control_centre", tab["centre"]), 1.4)
            f = frame(); save(f, f"{idx:02d}_tab")
            if not tap_search(f):
                log["dispatches"].append({"n": idx, "resource": res_name, "error": "no 搜索 button"})
                time.sleep(2); continue
            f = frame(); save(f, f"{idx:02d}_flown")
            t = text(f)
            node = re.search(r"等级\s*\d+\s*([^\s]{2,8})", t)
            record = {"n": idx, "resource": res_name, "node": node.group(0) if node else None}
            if "剩余存在时间" not in t and "采集" not in t:
                record["error"] = "no node card"; log["dispatches"].append(record); time.sleep(2); continue
            if tap_gather_button(f) is None:
                record["error"] = "no 采集 button (occupied?)"; log["dispatches"].append(record)
                time.sleep(2); continue
            f = frame(); save(f, f"{idx:02d}_formation")
            ft = text(f)
            record["formation_title"] = ft.split(" ")[0][:12]
            record["can_badge"] = stamina_cost_visible(f)
            if "射手" in ft or "盾兵" in ft:
                record["removed_heroes"] = remove_extra_heroes(f)
                f2 = frame(); save(f2, f"{idx:02d}_after_remove")
                record["dispatched"] = dispatch(f2)
                time.sleep(4)
                f3 = to_city()
                nb, ncap = march(f3)
                record["march_after"] = f"{nb}/{ncap}"
                record["march_increased"] = (base is not None and nb is not None and nb > base)
                save(f3, f"{idx:02d}_city")
                if nb is not None:
                    base, cap = nb, ncap
                log["dispatches"].append(record)
                if record["march_increased"]:
                    continue
            else:
                record["error"] = "PAGE_FORMATION not reached"
                log["dispatches"].append(record)
            time.sleep(2)
        log["march_end"] = f"{base}/{cap}"
        log["done"] = datetime.now().strftime("%H:%M:%S")
        print(json.dumps(log, ensure_ascii=False, indent=1))
        (ROOT / "learning" / f"gather_all_{STAMP}.json").write_text(
            json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
        return 0
    finally:
        lease.release(result="DONE", reason="gather all done")


if __name__ == "__main__":
    raise SystemExit(main())
