"""Bounded probe: put the 任务 panel on its FIRST tab, so the tab-switch skill can be seen.

Why this exists (2026-09-16).  `SELECT_DAILY_TAB` exists because the panel opens on
章节任务 while every daily skill was calibrated on the 每日任务 tab.  Verifying the skill
therefore needs the panel on the *other* tab -- but the client **remembers** the last tab
it was on: after the 13:46 probe it kept opening on 每日任务, so a plain `--goal DAILY`
run never exercised the skill (measured: 13 frames of that run, the tab was already the
daily one).

This probe does exactly one thing: one tap on the 章节任务 tab, at a coordinate measured
from the archived panel frame (OCR put the 章节任务 label at px x 70..185, y 1117..1154,
and the selected pill around it at x 15..235).  It then reports what the vision reads, so
the follow-up run's precondition is a measured fact rather than an assumption.

Self-limits: aborts unless the page is already DAILY (it never opens the panel itself --
that is `OPEN_DAILY`'s job and the run above does it), taps exactly one control, taps
nothing else, and touches no paid surface.

Usage
-----
    python tools/probe_daily_chapter_tab.py
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STAMP = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
OUT_DIR = ROOT / "dataset" / "truth_audit" / "daily_tab_switch_20260916"

# Measured on the archived panel frame (dataset/truth_audit/daily_tasks_tab_20260916/
# 01_before_20260916_134609.png): the 章节任务 label is centred at (127, 1135).
CHAPTER_TAB_CENTER = (127, 1135)


def build():
    from winter_agent_v2.device import ADBDevice
    from winter_agent_v2.ocr import HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend
    from winter_agent_v2.vision import SemanticWorldVision

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    device = ADBDevice(Path(config["device"]["adb_path"]), config["device"]["serial"],
                       production=True)
    device.resolve_connection()
    template = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))
    return device, HybridVision(template, ocr), template


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    device, hybrid, template = build()
    from winter_agent_v2.models import Page

    before_frame = OUT_DIR / f"01_before_{STAMP}.png"
    device.screenshot(before_frame)
    before = hybrid.observe(before_frame)
    print(f"before : page={before.page} daily={json.dumps(before.daily, ensure_ascii=False)}")
    if before.page is not Page.DAILY:
        print(f"ABORT: page is {before.page}, expected DAILY (the panel must already be "
              f"open; this probe never opens it).")
        return 1

    device.tap(*CHAPTER_TAB_CENTER)
    time.sleep(2.0)

    after_frame = OUT_DIR / f"02_after_chapter_tap_{STAMP}.png"
    device.screenshot(after_frame)
    after = hybrid.observe(after_frame)
    # The template layer alone, so the reading can be attributed to the records under test.
    template_view = template.observe(after_frame)
    print(f"after  : page={after.page} daily={json.dumps(after.daily, ensure_ascii=False)}")
    print(f"         template layer: page={template_view.page} "
          f"daily={json.dumps(template_view.daily, ensure_ascii=False)}")

    (OUT_DIR / f"probe_{STAMP}.json").write_text(json.dumps({
        "probe": "daily_chapter_tab",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "self_limits": ["aborts unless the page is already DAILY",
                        "exactly one tap, on a coordinate measured from an archived frame",
                        "nothing else is tapped"],
        "tap_px": list(CHAPTER_TAB_CENTER),
        "before": {"frame": str(before_frame), "page": before.page.value, "daily": before.daily},
        "after": {"frame": str(after_frame), "page": after.page.value, "daily": after.daily,
                  "template_layer_daily": template_view.daily},
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    ready = after.daily.get("tab") == "NOT_TASKS"
    print(f"\nprecondition for SELECT_DAILY_TAB (tab == NOT_TASKS): "
          f"{'READY' if ready else 'NOT READY'}")
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
