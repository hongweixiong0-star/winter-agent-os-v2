# -*- coding: utf-8 -*-
"""Observe the 每日任务 panel on the real client -- read-only, nothing spent, nothing tapped twice.

Why this exists
---------------
`DAILY_ACTIVITY_TARGET` is 已发现 on the console and its capability `READ_DAILY_PROGRESS` is
BLOCKED with 0 attempts / 0 successes / 0 failures.  The console's stored evidence is a
**six-day-old** reading whose shape carries no task rows::

    {"status": "AVAILABLE", "task_id": "HERO_RECRUIT_1", "progress": 0, "target": 1,
     "activity": 270}          # learning/observation_state.json -> domains.daily

Its source frame no longer exists, so the reading cannot be replayed.  A live look is the only
way to answer what the panel actually draws -- and on this project the rule is that the real
client outranks every archive, so that is what this tool takes.

What it does, in order (each step is checked before the next is attempted)
-----------------------------------------------------------------------
1. lease the device as the development owner and wait for AUTO to actually yield it;
2. reach HOME, and prove it is HOME from HOME's own bottom-nav wording;
3. find the 任务面板入口 by **template lookup against the reviewed manifest**
   (``BTN_OPEN_DAILY``), never by a remembered coordinate -- the project's constitution is that
   a UI element is the only legal source of a click position;
4. tap it once, and prove the page changed;
5. if the panel opened on another tab, read which tab is drawn and switch to 每日任务 once;
6. dump the frame's own OCR tokens and the **production reading** (``HybridVision.observe``, the
   same entry point the runtime calls) for the panel frame;
7. press back to HOME and prove it.

It touches nothing else: no 前往, no 一键领取, no chest.  A reward claim is a separate
capability (``DAILY_CLAIM_REWARDS``) and is deliberately out of scope here.

Usage
-----
    python tools/observe_daily_panel.py             # full pass, evidence written
    python tools/observe_daily_panel.py --no-lease  # observe only, take no lease
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MANIFEST = "dataset/candidate/template_manifest.json"

#: HOME's own bottom-bar labels.  Used to *prove* the city is on screen rather than to guess it:
#: all six are drawn at once, so seeing four of them is not a coincidence.
HOME_TABS = ("探险", "英雄", "背包", "商店", "联盟", "野外")

#: The daily panel's own wording, and the milestone thresholds this project has measured on a
#: real frame (``tests/replay/labels.json`` -> ``claimed_milestones`` / ``next_milestone``).
DAILY_WORDS = ("每日任务", "章节任务", "成长任务", "活跃", "前往", "一键领取", "领取")
MILESTONES = (40, 80, 120, 160, 215, 270, 325)


def _shot(ad, out: Path, tag: str, log) -> tuple[np.ndarray, Path]:
    """Capture one frame and write it to the evidence directory."""
    frame = None
    for _ in range(3):
        frame = ad.capture()
        if frame is not None:
            break
        time.sleep(0.4)
    if frame is None:
        raise RuntimeError("SCREENCAP_FAILED")
    image = np.asarray(frame)
    path = out / f"{tag}.png"
    from PIL import Image

    Image.fromarray(image).save(path)
    log(f"   frame {tag} -> {path.name}")
    return image, path


def _tokens(path: Path) -> list[dict]:
    from PIL import Image

    from winter_agent_v2.ocr_full import read_all

    with Image.open(path) as source:
        return list(read_all(source.convert("RGB")))


def _home_score(tokens: list[dict]) -> int:
    return sum(1 for t in tokens if t["text"].strip() in HOME_TABS)


def _tap_semantic(frame_path: Path, semantic: str, *, max_distance: int, log) -> tuple[int, int] | None:
    """Locate a reviewed UI element on this frame and return its pixel centre.

    Template lookup, so the tap comes from a measured element rather than a remembered
    coordinate.  Returns ``None`` when the element is not on the frame -- the caller must then
    not tap at all.
    """
    from winter_agent_v2.vision import SemanticROIVision

    vision = SemanticROIVision(ROOT / MANIFEST, max_distance=max_distance)
    found = vision.find(frame_path, semantic)
    if found is None:
        return None
    centre = getattr(found, "center_norm", None)
    if callable(centre):
        centre = centre()
    if not centre:
        return None
    from PIL import Image

    with Image.open(frame_path) as source:
        width, height = source.size
    return int(centre[0] * width), int(centre[1] * height)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-lease", action="store_true", help="observe without leasing")
    parser.add_argument("--max-distance", type=int, default=8)
    parser.add_argument("--keep-open", action="store_true",
                        help="do not press back at the end (leave the panel up)")
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    out = ROOT / "dataset" / "evidence" / f"daily_panel_observe_{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    log_file = (out / "run.log").open("w", encoding="utf-8")

    def log(line: str = "") -> None:
        print(line)
        log_file.write(str(line) + "\n")
        log_file.flush()

    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))

    from winter_agent_v2.device_lease import OWNER_DEVELOPMENT_VALIDATION, DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.shop_visit import wait_for_the_device

    lease = None
    lease_id = ""
    if not args.no_lease:
        lease = DeviceLease(ROOT)
        rec, why = lease.acquire(
            owner=OWNER_DEVELOPMENT_VALIDATION,
            capability_id="READ_DAILY_PROGRESS",
            # Short on purpose: the pass takes about a minute, and a lease that outlives a crash
            # keeps AUTO standing down for its whole TTL.  Measured once: a 3000 s TTL plus a
            # release that raised left the device held for the full 50 minutes.
            ttl_seconds=600,
            reason="READ_DAILY_PROGRESS first live observation of the 每日任务 panel",
        )
        if rec is None:
            log(json.dumps({"refused": why}, ensure_ascii=False))
            return 2
        lease_id = str(getattr(rec, "lease_id", "") or "")
        log(f"lease {lease_id or '(no id)'} acquired; expires "
            f"{getattr(rec, 'expires_at', None)}")

    try:
        # A lease is a request, not a handover: AUTO keeps acting until its next safe point.
        wait_for_the_device(ROOT, log=log)
        ad = MaaExecutorAdapter(
            adb_path=cfg["device"]["adb_path"],
            serial=cfg["device"]["serial"],
            production=True,
            template_dir=ROOT / "dataset/candidate/templates",
            log_dir=ROOT / "learning/maa_logs",
        )
        ok, reason = ad.ensure_ready()
        if not ok:
            log(reason)
            return 3

        # ---- 1. reach HOME -------------------------------------------------------------
        log("\n[1] reach HOME")
        home_path: Path | None = None
        for attempt in range(5):
            _img, path = _shot(ad, out, f"h{attempt}_look", log)
            toks = _tokens(path)
            score = _home_score(toks)
            log(f"   attempt {attempt}: home_score={score}/6")
            if score >= 4:
                home_path = path
                break
            log("   not the city -- one back")
            ad.press_back()
            time.sleep(1.2)
        if home_path is None:
            log("!! could not reach HOME; stopping without tapping anything")
            return 4

        # ---- 2. find the entry, from the manifest, on this frame -----------------------
        log("\n[2] locate 任务面板入口 (BTN_OPEN_DAILY) on this HOME frame")
        xy = _tap_semantic(home_path, "BTN_OPEN_DAILY", max_distance=args.max_distance, log=log)
        if xy is None:
            log("!! BTN_OPEN_DAILY is not on this frame -- not tapping; the entry is measured"
                " at bbox_norm x0.0111 y0.8 w0.0917 h0.0539 but a miss means this city frame"
                " does not draw it")
            log(f"   HOME tokens: {[t['text'] for t in _tokens(home_path)][:40]}")
            return 5
        log(f"   template centre -> {xy}")

        # ---- 3. tap once, and prove the page changed ----------------------------------
        log("\n[3] tap the entry once")
        res = ad.click(int(xy[0]), int(xy[1]))
        log(f"   click -> {res}")
        time.sleep(1.8)
        _img, panel_path = _shot(ad, out, "p1_after_entry_tap", log)
        panel_toks = _tokens(panel_path)
        panel_words = [t["text"] for t in panel_toks]
        log(f"   home_score now={_home_score(panel_toks)} (0 means the city is gone)")
        log(f"   daily words seen: {[w for w in DAILY_WORDS if any(w in p for p in panel_words)]}")

        # ---- 4. if another tab is drawn, switch to 每日任务 exactly once ----------------
        headings = [w for w in panel_words if w.strip() in ("每日任务", "章节任务", "成长任务")]
        log(f"\n[4] tab headings on the panel: {headings}")
        if headings and "每日任务" not in headings:
            log("   the panel opened on another tab -- switching once")
            tab_xy = _tap_semantic(panel_path, "BTN_DAILY_TAB_TASKS",
                                   max_distance=args.max_distance, log=log)
            log(f"   BTN_DAILY_TAB_TASKS centre -> {tab_xy}")
            if tab_xy is not None:
                log(f"   click -> {ad.click(int(tab_xy[0]), int(tab_xy[1]))}")
                time.sleep(1.8)
                _img, panel_path = _shot(ad, out, "p2_after_tab_tap", log)
                panel_toks = _tokens(panel_path)
                panel_words = [t["text"] for t in panel_toks]
                headings = [w for w in panel_words if w.strip() in ("每日任务", "章节任务", "成长任务")]
                log(f"   headings now: {headings}")

        # ---- 5. what the panel draws --------------------------------------------------
        log("\n[5] the panel's own wording (text @ pixel centre, normalised)")
        from PIL import Image

        with Image.open(panel_path) as source:
            width, height = source.size
        log(f"   frame size {width}x{height}")
        for t in sorted(panel_toks, key=lambda t: (t["centre"][1], t["centre"][0])):
            text = str(t["text"]).strip()
            if not text:
                continue
            x, y = t["centre"]
            log(f"     ({x:>4},{y:>4})  ({x / width:.4f},{y / height:.4f})  {text!r}")

        # ---- 6. the production reading for this same frame -----------------------------
        log("\n[6] production reading (HybridVision.observe -- the entry point the runtime uses)")
        from winter_agent_v2.ocr import (
            HybridVision,
            OCRService,
            RapidOCRBackend,
            ResilientOCRBackend,
        )
        from winter_agent_v2.vision import SemanticWorldVision

        ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(cfg["ocr"]["module_path"]))))
        hybrid = HybridVision(
            SemanticWorldVision(ROOT / MANIFEST, max_distance=args.max_distance), ocr
        )
        state = hybrid.observe(panel_path)
        log(f"   page       : {getattr(state.page, 'value', state.page)}")
        log(f"   confidence : {state.confidence}")
        daily = dict(state.daily or {})
        log(f"   daily keys : {sorted(daily.keys())}")
        log(f"   activity   : {daily.get('activity')}")
        log(f"   status     : {daily.get('status')}")
        log(f"   tab        : {daily.get('tab')}")
        rows = daily.get("tasks") or []
        log(f"   rows       : {len(rows)}  (visible_task_count={daily.get('visible_task_count')})")
        for row in rows:
            log(f"     {str(row.get('task_id')):34} {str(row.get('state')):10}"
                f" {row.get('progress')} {str(row.get('label'))!r}"
                f" btn={(row.get('action_button') or {}).get('semantic_id')}")
        (out / "production_reading.json").write_text(
            json.dumps(
                {
                    "page": getattr(state.page, "value", state.page),
                    "confidence": state.confidence,
                    "daily": daily,
                    "source_frame": panel_path.name,
                },
                ensure_ascii=False,
                indent=1,
                default=str,
            ),
            encoding="utf-8",
        )

        # ---- 7. what a READ_DAILY_PROGRESS reader must extract -------------------------
        log("\n[7] what the missing capability has to extract from this frame")
        numbers = []
        for t in panel_toks:
            text = str(t["text"]).strip().replace(",", "")
            if text.isdigit() and 1 <= len(text) <= 3:
                numbers.append((int(text), t["centre"]))
        log(f"   small numbers drawn: {sorted({n for n, _ in numbers})}")
        log(f"   milestone thresholds seen: "
            f"{sorted({n for n, _ in numbers if n in MILESTONES})}")
        log(f"   activity counter candidates: "
            f"{[(n, c) for n, c in numbers if n == daily.get('activity')]}")
        log(f"   rows with a 前往 button: "
            f"{sum(1 for r in rows if (r.get('action_button') or {}).get('semantic_id'))}")
        log(f"   rows already complete: "
            f"{sum(1 for r in rows if str(r.get('state')) == 'COMPLETED')}")

        # ---- 8. leave the panel -------------------------------------------------------
        if not args.keep_open:
            log("\n[8] back to HOME")
            for attempt in range(4):
                ad.press_back()
                time.sleep(1.2)
                _img, path = _shot(ad, out, f"b{attempt}_back", log)
                score = _home_score(_tokens(path))
                log(f"   attempt {attempt}: home_score={score}/6")
                if score >= 4:
                    break
        else:
            log("\n[8] --keep-open: panel left up")

        log(f"\nEVIDENCE: {out}")
        return 0
    finally:
        if lease is not None:
            # ``release`` takes ``result`` as a REQUIRED keyword-only argument, so calling it with
            # no arguments raises TypeError.  The first version of this tool did exactly that and
            # swallowed it in a bare ``except``, which printed to stdout rather than the log -- so
            # the lease was left held and AUTO stood down for the rest of its 50-minute TTL while
            # the run looked clean.  A safety net that hides its own failure is the same defect
            # this project keeps finding in the production path, so: pass the argument, and log
            # the outcome either way.
            try:
                released = lease.release(
                    result="OBSERVED",
                    reason="READ_DAILY_PROGRESS read-only observation finished",
                    expect_lease_id=lease_id,
                )
                log(f"lease release -> {released}")
            except Exception as exc:  # noqa: BLE001 - a failed release must not mask the result
                log(f"!! lease release FAILED: {type(exc).__name__}: {exc!r}"
                    " -- the device stays leased until it expires; release it by hand")
        log_file.close()


if __name__ == "__main__":
    sys.exit(main())
