# -*- coding: utf-8 -*-
"""BTN_DISPATCH L4 device session: gather-chain navigation -> production dispatch -> march proof.

Why this exists
---------------
``BTN_DISPATCH`` sits at the end of a chain whose earlier links were never wired into
``backend_routing`` (``BTN_OPEN_RESOURCE_SEARCH``, ``BTN_RECALL`` ...), so AUTO never reaches
the formation page and the node has 85 recorded production attempts without a single proof.

This session drives the navigation manually (historical template images from
``dataset/candidate/templates``), then hands the decisive step to the **production** path:
``ExecutorRouter.maa_resolver("BTN_DISPATCH", "DISPATCH_MARCH")``.  Navigation may be manual;
the tap that proves the node may not.

Evidence lands in ``dataset/evidence/device_l4_session/dispatch_*.png`` and
``learning/device_dispatch_l4_<date>.json``.  Nothing here spends stamina: the target is an
ordinary resource gather, and the march is recalled afterwards so no queue stays occupied.

Usage::

    .venv/Scripts/python.exe tools/device_dispatch_l4.py [--recall / --keep-march]

Exit codes: 0 proved-or-honest-fail recorded, 2 lease refused, 3 no adapter.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

EVIDENCE = ROOT / "dataset" / "evidence" / "device_l4_session"
TEMPLATES = ROOT / "dataset" / "candidate" / "templates"


def _pil(x):
    return x if isinstance(x, Image.Image) else Image.fromarray(x)


def imread_any(path: Path):
    """cv2.imread cannot open non-ASCII Windows paths; read bytes and decode instead."""
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def match_best(frame_pil: Image.Image, names: list[str], threshold: float = 0.82):
    """Best pel template hit among ``names``, or ``None``.  Current frame only."""
    img = cv2.cvtColor(np.asarray(frame_pil.convert("RGB")), cv2.COLOR_RGB2BGR)
    best = None
    for name in names:
        path = TEMPLATES / name
        if not path.is_file():
            continue
        tpl = imread_any(path)
        if tpl is None or tpl.shape[0] > img.shape[0] or tpl.shape[1] > img.shape[1]:
            continue
        res = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)
        if score >= threshold and (best is None or score > best[0]):
            h, w = tpl.shape[:2]
            best = (float(score), name, (int(loc[0]), int(loc[1]), int(w), int(h)))
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recall", action="store_true", default=True,
                    help="recall the gathering march after verification (default: True)")
    ap.add_argument("--keep-march", dest="recall", action="store_false")
    ap.add_argument("--dry-run", action="store_true", help="never tap; only observe")
    args = ap.parse_args()

    cfg = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.executor_router import ExecutorRouter, RoutingTable, _rapid_ocr_results

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(
        owner="DEVICE_DISPATCH_L4",
        capability_id="L2_DIGESTION",
        ttl_seconds=420,
        reason="BTN_DISPATCH live proof through an ordinary gather",
    )
    if rec is None:
        print("REFUSED", why)
        return 2

    out: dict = {"session_started_at": datetime.now(timezone.utc).isoformat(), "steps": []}
    try:
        adapter = MaaExecutorAdapter(
            adb_path=cfg["device"]["adb_path"], serial=cfg["device"]["serial"],
            production=True, template_dir=TEMPLATES, log_dir=ROOT / "learning" / "maa_logs",
        )
        adapter.ensure_ready()
        router = ExecutorRouter(adb_executor=None, maa_adapter=adapter, routing=RoutingTable.load())

        def frame(retries: int = 4):
            for _ in range(retries):
                f = adapter.frame()
                if f is not None:
                    return _pil(f)
                time.sleep(1)
            return None

        def toks(img):
            return _rapid_ocr_results(np.asarray(img), None, [])

        def text(img):
            return " ".join(t["text"] for t in toks(img))

        def save(img, tag: str):
            p = EVIDENCE / f"dispatch_{tag}.png"
            _pil(img).save(p)
            out["steps"].append({"tag": tag, "frame": str(p.relative_to(ROOT))})
            return p

        def tap_center(box, note=""):
            x, y, w, h = box
            cx, cy = x + w // 2, y + h // 2
            if args.dry_run:
                return (cx, cy), False
            adapter.click(cx, cy)
            return (cx, cy), True

        def box_of(token):
            xs = [float(p[0]) for p in token["box"]]
            ys = [float(p[1]) for p in token["box"]]
            return (int(min(xs)), int(min(ys)), int(max(xs) - min(xs)), int(max(ys) - min(ys)))

        # 0. reach the city view first: AUTO may hand the device over mid-purpose
        # (this session started on the intel page once).  BACK out until the 统帅
        # HUD shows, and never let a BACK produce the exit dialog -- the city view
        # root answers BACK with 确认退出游戏吗？ and 取消 is the only safe answer.
        for _ in range(5):
            f0 = frame()
            if f0 is None:
                out["error"] = "no frame during handover"
                print(json.dumps(out, ensure_ascii=False))
                return 3
            t0 = text(f0)
            if "统帅" in t0:
                break
            if "确认退出游戏" in t0 or "退出游戏吗" in t0:
                cancel = [t for t in toks(f0) if "取消" in t["text"]]
                if cancel:
                    tap_center(box_of(cancel[0]))
                    time.sleep(1.5)
                    continue
            adapter.press_back()
            time.sleep(2.0)
            fguards = frame()
            tg = text(fguards) if fguards is not None else ""
            if "退出游戏吗" in tg:
                cancel = [t for t in toks(fguards) if "取消" in t["text"]]
                if cancel:
                    tap_center(box_of(cancel[0]))
                    time.sleep(1.5)

        # 1. HOME -> world map
        f = frame()
        if f is None:
            out["error"] = "no frame"
            print(json.dumps(out, ensure_ascii=False))
            return 3
        save(f, "01_start")
        out["page_text_head"] = text(f)[:200]
        out["start_is_home"] = "统帅" in text(f)

        pt = router.maa_resolver("PAGE_MAP", "OPEN_MAP")
        out["open_map_resolver"] = "OK" if pt else "NONE:" + str(router.last_recognition_error)
        if pt:
            tap = [int(pt[0] * f.width), int(pt[1] * f.height)]
            out["open_map_tap"] = tap
            tap_center((tap[0], tap[1], 0, 0))
            time.sleep(2.5)
            f = frame()
            save(f, "02_map")
        if pt is None:
            # The 城镇/野外 chips are switchable view targets read off this very frame.
            wild = [t for t in toks(f) if t["text"].strip() == "野外"]
            out["wild_chip"] = [t["box"] for t in wild]
            if wild:
                tap_frame = box_of(wild[0])
                out["open_map_tap"] = tap_center(tap_frame)[0]
                time.sleep(2.5)
                f = frame()
                save(f, "02_map")
        out["map_text_head"] = text(f)[:160]

        # 2. resource search panel
        for attempt in range(2):
            hit = match_best(f, [
                "btn_open_resource_search__live_attempt8_idle__2.png",
                "btn_open_resource_search__legacy_wilderness__1.png",
                "btn_open_resource_search__episode_search_button__0.png",
                "btn_open_resource_search__step_001_before__0.png",
            ])
            out[f"search_button_{attempt}"] = (None if hit is None
                                               else {"score": round(hit[0], 3), "name": hit[1], "box": list(hit[2])})
            if hit is None:
                # template corpus is old; the search entry is also a readable word band
                band = [t for t in toks(f)
                        if "搜索" in t["text"] and 900 < float(min(p[1] for p in t["box"])) < 1240]
                if band:
                    hit = (0.0, "OCR:搜索", box_of(band[0]))
                    out[f"search_button_{attempt}_ocr"] = {"text": band[0]["text"], "box": list(hit[2])}
            if hit is None:
                break
            _, clicked = tap_center(hit[2])
            time.sleep(2.0)
            f = frame()
            save(f, f"03_search_panel_{attempt}")
            t = text(f)
            if any(w in t for w in ("木材", "食物", "铁矿", "煤矿", "搜索", "派遣", "采集")):
                out["search_panel_open"] = True
                break

        # 3. submit the search
        hit = match_best(f, [
            "btn_resource_search_submit__live_executor_search_open__2.png",
            "btn_resource_search_submit__legacy_search_resource_panel__2.png",
            "btn_resource_search_submit__step_001_after__1.png",
            "btn_resource_search_submit__legacy_gathering__0.png",
        ])
        out["submit_button"] = (None if hit is None
                               else {"score": round(hit[0], 3), "name": hit[1], "box": list(hit[2])})
        if hit:
            _, _ = tap_center(hit[2])
            time.sleep(3.0)
            f = frame()
            save(f, "04_after_submit")

        # 4. resource detail -> 采集 (gather)
        hit = match_best(f, [
            "btn_gather__live_resource_attempt6__1.png",
            "btn_gather__live_resource_attempt7__1.png",
            "btn_gather__live_attempt8_resource__1.png",
            "btn_gather__legacy_available_resource_detail__1.png",
        ])
        out["gather_button"] = (None if hit is None
                               else {"score": round(hit[0], 3), "name": hit[1], "box": list(hit[2])})
        if hit is None:
            gout = None
            for tok in toks(f):
                if "采集" in tok["text"]:
                    gout = tok
                    break
            if gout is not None:
                xs = [p[0] for p in gout["box"]]
                ys = [p[1] for p in gout["box"]]
                hit = (0.0, "OCR:采集", (int(min(xs)), int(min(ys)),
                                         int(max(xs) - min(xs)), int(max(ys) - min(ys))))
                out["gather_button_ocr"] = {"box": list(hit[2]), "text": gout["text"]}
        before = None
        if hit:
            _, _ = tap_center(hit[2])
            time.sleep(3.0)
            before = frame()
            save(before, "05_formation_before")

        # 5. formation reader on the real page
        from winter_agent_v2.formation import read_formation_state_tokens

        class _T:
            def __init__(self, d):
                self.text = d["text"]
                self.box = d["box"]

        form = None
        if before is not None:
            form = read_formation_state_tokens([_T(t) for t in toks(before)], before.size)
            out["formation"] = {
                "is_formation": form["is_formation"],
                "confirm": form["confirm"],
                "troop_rows": [r["label"] for r in form["troop_rows"]],
                "hero_slots": len(form["hero_slot_norms"]),
            }

        # 6. THE production step: BTN_DISPATCH resolved by the real router and tapped by MAA
        target = None
        if before is not None:
            pt = router.maa_resolver("BTN_DISPATCH", "DISPATCH_MARCH")
            if pt is not None:
                px, py = int(pt[0] * before.width), int(pt[1] * before.height)
                # sanity: the real button lives in the bottom band of the formation page
                target = (px, py)
                out["dispatch_resolver"] = {"tap": [px, py], "in_bottom_band": py > 1000}
        if target is None:
            out["dispatch_resolver"] = "NONE:" + str(router.last_recognition_error)
            out["level"] = "L2_NODE_NOT_RESOLVED_ON_PAGE"
        else:
            out["dispatch_clicked"] = True
            if not args.dry_run:
                adapter.click(*target)
            time.sleep(4.0)
            after = frame()
            save(after, "06_after_dispatch")
            t_after = text(after)
            out["after_text_head"] = t_after[:240]
            form_after = read_formation_state_tokens([_T(t) for t in toks(after)], after.size)
            out["formation_after"] = {"is_formation": form_after["is_formation"]}
            marching_tokens = [t["text"] for t in toks(after)
                               if any(w in t["text"] for w in ("召回", "撤回", "行军", "采集", "前往"))]
            out["march_words"] = marching_tokens[:12]
            left_page = bool(form and form["is_formation"]) and not form_after["is_formation"]
            out["level"] = "L4_DISPATCH_TAPPED_PAGE_LEFT" if left_page else "L3_DISPATCH_TAPPED_UNPROVEN"

            # 8. recall so no queue is left busy before the bear window
            if args.recall:
                time.sleep(2.0)
                fmap = after
                hit = match_best(fmap, ["btn_recall__legacy_resource_detail__1.png"])
                recalled = False
                if hit:
                    _, recalled = tap_center(hit[2])
                if not recalled:
                    for tok in toks(fmap):
                        if any(w in tok["text"] for w in ("召回", "撤回")):
                            xs = [p[0] for p in tok["box"]]
                            ys = [p[1] for p in tok["box"]]
                            tap_center((int(min(xs)), int(min(ys)),
                                        int(max(xs) - min(xs)), int(max(ys) - min(ys))))
                            recalled = True
                            break
                out["recalled"] = recalled
                if recalled:
                    time.sleep(2.5)
                    save(frame(), "07_after_recall")

        out["finished_at"] = datetime.now(timezone.utc).isoformat()
        path = ROOT / "learning" / f"device_dispatch_l4_{datetime.now().strftime('%Y%m%d')}.json"
        path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    finally:
        lease.release(result="DONE", reason="dispatch L4 session end")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
