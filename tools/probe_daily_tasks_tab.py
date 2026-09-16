"""Bounded probe: what is behind the 每日任务 tab of the panel `OPEN_DAILY` opens?

Measured 2026-09-16T13:44Z: tapping the city scroll icon (`BTN_OPEN_DAILY`) opens the
tabbed 任务 panel and the production vision classifies it `Page.DAILY`, but the
panel lands on the **章节任务** tab, so the reading is

    daily = {"status": "AVAILABLE", "claimable_count": 0}

and the brain honestly stops with `daily_no_claimable_rewards`.  The daily-mission
skills (`DAILY_CLAIM_REWARDS`, ...) are written against the **每日任务** tab
(every archived frame they were calibrated on, e.g.
`dataset/raw/live_cycle2_daily_tasks.png`, shows that tab).  Nothing in the registry
can switch tabs, so before designing anything the question is:

    what does the 每日任务 tab actually show on this account right now?

Self-limits (the project's bounded-probe contract):
  * aborts unless the current page is already DAILY -- it never opens the panel;
  * taps exactly one control, at a coordinate measured visually from a live frame
    (crop archived next to the frames), and taps nothing else;
  * touches no paid surface -- if the resulting frame looks like a purchase
    surface the probe says so and backs out once;
  * writes the frames and a probe.json, so the run is reproducible evidence
    rather than a claim.

Usage
-----
    "E:/dongri-mumu-bot/.venv/Scripts/python.exe" tools/probe_daily_tasks_tab.py
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
OUT_DIR = ROOT / "dataset" / "truth_audit" / "daily_tasks_tab_20260916"

# Measured on live_runtime_step_001_after_20260916T134403879899.png (720x1280):
# the panel's three tabs sit on one row at y 1081..1172; 每日任务 is the third one,
# box (480,1081)-(700,1172).  See daily_tabbar_zoom.png next to the frames.
TAB_DAILY_TASKS_CENTER = (590, 1127)

FIELDS = ("daily", "popup", "rewards", "stamina")


def build():
    from winter_agent_v2.device import ADBDevice
    from winter_agent_v2.ocr import (
        HybridVision,
        OCRService,
        RapidOCRBackend,
        ResilientOCRBackend,
    )
    from winter_agent_v2.vision import SemanticWorldVision

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    device = ADBDevice(
        Path(config["device"]["adb_path"]),
        config["device"]["serial"],
        production=True,
    )
    device.resolve_connection()
    template = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    ocr = OCRService(
        ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"])))
    )
    return device, HybridVision(template, ocr), ocr


def describe(label: str, state) -> None:
    print(f"--- {label} ---")
    print(f"page       : {state.page}")
    print(f"confidence : {state.confidence}")
    for name in FIELDS:
        value = getattr(state, name, None)
        if value:
            print(f"{name:<11}: {json.dumps(value, ensure_ascii=False, default=str)}")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    device, hybrid, ocr = build()
    from winter_agent_v2.models import Page

    before_frame = OUT_DIR / f"01_before_{STAMP}.png"
    device.screenshot(before_frame)
    before = hybrid.observe(before_frame)
    describe("BEFORE (no action yet)", before)

    if before.page is not Page.DAILY:
        print(f"ABORT: page is {before.page}, expected DAILY; the panel is not open "
              f"and this probe never opens it.")
        return 1

    device.tap(*TAB_DAILY_TASKS_CENTER)
    time.sleep(2.0)

    after_frame = OUT_DIR / f"02_after_tap_{STAMP}.png"
    device.screenshot(after_frame)
    after = hybrid.observe(after_frame)
    describe("AFTER one tap on 每日任务", after)

    tokens = []
    band = {"x_norm": 0.0, "y_norm": 0.28, "w_norm": 1.0, "h_norm": 0.66}
    try:
        import json as _json

        status = device.status()
        width, height = status.resolution
        result = ocr.recognize(after_frame, band)
        for token in result.tokens:
            if not token.box:
                continue
            xs = [p[0] for p in token.box]
            ys = [p[1] for p in token.box]
            tokens.append({
                "text": token.text,
                "confidence": round(token.confidence, 3),
                "px": [round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))],
                "norm": [round(min(xs) / width, 4), round(min(ys) / height, 4)],
            })
    except Exception as exc:  # pragma: no cover - diagnostic only
        print(f"ocr token dump failed: {type(exc).__name__}: {exc}")

    for token in tokens:
        print(f"    {token['text']!r:>18} conf={token['confidence']:.3f} "
              f"px={token['px']}")

    payload = {
        "probe": "daily_tasks_tab",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "self_limits": [
            "aborts unless the page is already DAILY",
            "exactly one tap, on a coordinate measured from a live frame",
            "nothing else is tapped",
        ],
        "tap_px": list(TAB_DAILY_TASKS_CENTER),
        "before": {"frame": str(before_frame), "page": before.page.value,
                   "daily": before.daily},
        "after": {"frame": str(after_frame), "page": after.page.value,
                  "daily": after.daily},
        "ocr_tokens_after": tokens,
    }
    (OUT_DIR / f"probe_{STAMP}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nlanded_on   : {after.page}")
    print(f"daily_after : {json.dumps(after.daily, ensure_ascii=False, default=str)}")
    print(f"frames      : {before_frame.name} / {after_frame.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
