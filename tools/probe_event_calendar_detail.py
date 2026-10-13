# -*- coding: utf-8 -*-
"""Why does OPEN_EVENT_CALENDAR_DETAIL fail 23/23? A read-only diagnostic.

Why this exists (2026-10-13)
---------------------------
``04_OPEN_ISSUES.md`` ranks ``EVENT_CALENDAR_DETAIL_NOT_PROVEN`` as a top live-evidenced
defect: ``OPEN_EVENT_CALENDAR_DETAIL`` failed 23 times, all inside the last 2 days, and
``event_schedule._unreachable_today``'s docstring records that an earlier version of this
skill "returned success every time while actually opening something else each time" -- a
false-positive verifier, the most expensive kind of defect to leave in place.

The verifier (``verifier.verify_event_calendar_detail_open``) needs four things at once:

  1. before.page is EVENT **and** after.page is EVENT
  2. ``before.events.calendar.recognized`` is True
  3. ``after.events.calendar_detail.recognized`` is True
  4. identity: the detail's event_id (or its attributed / occurrence key) equals the
     calendar's ``next_detail_event_id`` -- or, failing that, the first entry that has a
     ``tap_norm`` and ``details_observed is not True``.

A probe that only says "it failed" cannot tell those apart. This one reproduces the exact
production path with the production readers and matchers:

    home -> 常规活动 (regular-events hub) -> 日历 tab (template EVENT_CALENDAR_TAB,
    the same matcher and threshold production uses) -> read_event_calendar -> tap the same
    entry the skill would tap -> read_event_detail -> evaluate each condition separately

so the report names the broken rung instead of the symptom.

Read-only
---------
The only taps are navigation plus the one calendar-entry tap that the production skill
itself performs under its own authorization. Nothing inside the opened detail is touched,
no reward is claimed, no paid control is approached. The probe ends with BACK.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAMP = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
OUT = ROOT / "dataset" / "evidence" / f"event_calendar_detail_probe_{STAMP}"
REPORT = ROOT / "evidence" / f"event_calendar_detail_probe_{STAMP}.json"


def build():
    sys.path.insert(0, str(ROOT))
    from winter_agent_v2.device import ADBDevice
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.ocr import OCRService, RapidOCRBackend
    from winter_agent_v2.vision import SemanticWorldVision

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    device = ADBDevice(Path(config["device"]["adb_path"]), config["device"]["serial"], production=True)
    device.resolve_connection()
    ocr = OCRService(RapidOCRBackend(Path(config["ocr"]["module_path"])))
    template = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    return device, ocr, template, DeviceLease(ROOT)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    device, ocr, template, lease = build()

    rec, why = lease.acquire(
        owner="DEVICE_EVENT_CALENDAR_DETAIL_PROBE",
        capability_id="EVENT_CALENDAR",
        ttl_seconds=900,
        reason="read-only diagnosis of OPEN_EVENT_CALENDAR_DETAIL (23/23 failures)",
    )
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2

    from winter_agent_v2 import event_calendar

    report: dict = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "stamp": STAMP, "steps": [], "conditions": {}}

    def shoot(tag: str):
        path = OUT / f"{tag}.png"
        device.screenshot(path)
        result = ocr.recognize(path)
        tokens = [t for t in (result.tokens or []) if str(getattr(t, "text", "") or "").strip()]
        return tokens, path

    def words(tokens):
        return " ".join(t.text for t in tokens)

    def centre(tokens, needle):
        for t in tokens:
            if needle in t.text:
                xs = [p[0] for p in t.box]
                ys = [p[1] for p in t.box]
                return int(sum(xs) / 4), int(sum(ys) / 4)
        return None

    def log(tag, **kw):
        report["steps"].append({"tag": tag, **{k: (str(v)[:120] if isinstance(v, str) else v) for k, v in kw.items()}})
        print(f"[{tag}] " + " ".join(f"{k}={v}" for k, v in kw.items()), flush=True)

    def is_home(tokens):
        w = words(tokens)
        return ("野外" in w or "城镇" in w) and ("英雄" in w or "背包" in w)

    try:
        # ---- 1. reach the city/home view ----
        tokens, frame = shoot("00_start")
        log("00_start", text=words(tokens)[:110])
        for attempt in range(8):
            if is_home(tokens):
                break
            device.press_back()
            time.sleep(1.6)
            tokens, frame = shoot(f"0{attempt + 1}_back")
        if not is_home(tokens):
            log("STOP_no_home", text=words(tokens)[:110])
            REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return 3
        log("01_home", text=words(tokens)[:110])

        # ---- 2. open the regular-events hub (常规活动) ----
        entry = centre(tokens, "常规活动") or centre(tokens, "超值活动")
        if entry is None:
            log("STOP_no_regular_event_entry", text=words(tokens)[:160])
            REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return 4
        device.tap(*entry)
        time.sleep(3.0)
        tokens, frame = shoot("02_hub")
        log("02_hub", text=words(tokens)[:200])

        # ---- 3. switch to the 日历 tab with the production matcher ----
        # The tab strip is horizontally scrollable and its contents change over time
        # (2026-09-28 reference frame: 日历 / furnace / 联盟总动员; today: 军备竞演 /
        # 黎明的愿景 / 兵工厂争夺战), so the 日历 tab can be scrolled out of view.  Walk the
        # strip in both directions with the *verified* TAB_EVENT_CALENDAR template first.
        tab = None
        tried = []
        for direction in (1, -1, 1):
            for step in range(8):
                for semantic in ("TAB_EVENT_CALENDAR", "EVENT_CALENDAR_TAB"):
                    hit = template.semantic.find(frame, semantic)
                    if hit is not None and hit.center_norm is not None:
                        tab = (semantic, hit)
                        break
                if tab:
                    break
                tried.append({"direction": direction, "step": step})
                x0 = 600 if direction > 0 else 120
                x1 = 120 if direction > 0 else 600
                device.swipe(x0, 140, x1, 140)
                time.sleep(1.6)
                tokens, frame = shoot(f"03_strip_{direction}_{step}")
            if tab:
                break
        report["strip_walks"] = tried
        if tab is None:
            log("STOP_no_calendar_tab_after_walking_strip", strip_text=words(tokens)[:160])
            REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return 5
        semantic, hit = tab
        report["calendar_tab_match"] = {
            "semantic": semantic, "distance": hit.distance,
            "center_norm": list(hit.center_norm) if hit.center_norm else None,
        }
        tap_xy = (round(hit.center_norm[0] * 720), round(hit.center_norm[1] * 1280))
        log("03_calendar_tab", semantic=semantic, distance=hit.distance, tap=tap_xy)
        device.tap(*tap_xy)
        time.sleep(3.0)
        tokens, frame = shoot("04_grid")
        log("04_grid", text=words(tokens)[:200])

        # ---- 4. read the calendar grid with the production reader ----
        calendar = event_calendar.read_event_calendar(tokens, frame_size=(720, 1280), frame_path=frame)
        report["calendar"] = calendar
        log("05_calendar_read",
            recognized=calendar.get("recognized"),
            entries=len(calendar.get("entries") or []),
            next_detail_event_id=calendar.get("next_detail_event_id"),
            visible_dates=calendar.get("visible_dates_raw"))

        # ---- 5. pick the same entry the skill would tap ----
        target = None
        for row in calendar.get("entries") or ():
            if isinstance(row, dict) and row.get("tap_norm") and row.get("details_observed") is not True:
                target = row
                break
        report["chosen_entry"] = target
        if target is None:
            log("STOP_no_uninspected_entry", entries=len(calendar.get("entries") or []))
            REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return 6
        norm = target["tap_norm"]
        tap_xy = (round(float(norm[0]) * 720), round(float(norm[1]) * 1280))
        log("06_chosen_entry", event_id=target.get("event_id"), tap=tap_xy,
            label=str(target.get("label"))[:40])
        device.tap(*tap_xy)
        time.sleep(3.0)

        # ---- 6. read the detail with the production reader ----
        tokens2, frame2 = shoot("07_after_tap")
        log("07_after_tap", text=words(tokens2)[:220])
        label_token, best = None, -1.0
        for t in tokens2:
            h = max((p[1] for p in t.box), default=0.0) - min((p[1] for p in t.box), default=0.0)
            if h > best:
                best, label_token = h, t
        detail = event_calendar.read_event_detail(
            tokens2,
            event_label=label_token.text.strip() if label_token else None,
            frame_size=(720, 1280),
        )
        report["detail"] = detail
        log("08_detail_read", recognized=detail.get("recognized"),
            event_id=detail.get("event_id"), matched_event_id=detail.get("matched_event_id"),
            display_name=str(detail.get("display_name"))[:40])

        # ---- 7. evaluate the verifier's four conditions separately ----
        expected = str(calendar.get("next_detail_event_id") or "") or None
        if expected is None:
            expected = next((str(r.get("event_id") or "") for r in calendar.get("entries", ())
                             if isinstance(r, dict) and r.get("tap_norm")
                             and r.get("details_observed") is not True), None)
        actual = str(detail.get("event_id") or "")
        attributed = str(detail.get("matched_event_id") or "")
        occ_exp = calendar.get("next_detail_occurrence_key")
        occ_act = detail.get("matched_occurrence_key")
        conds = {
            "1_before_and_after_are_EVENT": bool(
                calendar.get("recognized") is True
                and ("常规活动" in words(tokens2) or detail.get("recognized") is True)),
            "2_calendar_recognized": calendar.get("recognized") is True,
            "3_calendar_detail_recognized": detail.get("recognized") is True,
            "4_identity_matches": bool(expected) and (
                actual == expected or attributed == expected
                or (occ_exp is not None and occ_act == occ_exp)),
        }
        report["conditions"] = conds
        report["expected_event_id"] = expected
        report["actual_event_id"] = actual
        report["attributed_event_id"] = attributed
        print("\n=== VERIFIER CONDITIONS ===", flush=True)
        for k, v in conds.items():
            print(f"  {'PASS' if v else 'FAIL':4s}  {k}", flush=True)
        first_bad = next((k for k, v in conds.items() if not v), None)
        report["first_failing_condition"] = first_bad
        print(f"\nFIRST FAILING RUNG: {first_bad}", flush=True)
        # The report is the durable artifact: write it on every path, not only on STOP.
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {REPORT.name}", flush=True)

        # ---- 8. leave the client where we found it ----
        device.press_back()
        time.sleep(1.8)
        tokens3, _ = shoot("09_after_back")
        log("09_after_back", text=words(tokens3)[:100])
        return 0
    finally:
        try:
            REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - a write failure must not mask the diagnosis
            print(f"report write failed: {exc}", flush=True)
        lease.release(result="DONE", reason="event calendar detail diagnosis done")


if __name__ == "__main__":
    raise SystemExit(main())
