"""Bounded probe: is the VIP entry where the external source says it is?

Why this exists (2026-09-17).  `CAP-B09/B10 VIP` has been blocked from the start by one
question: *where is the VIP entry?*  V2 has no skill for it and the registry's landing
queue records `OPEN_VIP` as not implemented, so the capability has never been attempted.

The external audit produced a testable hypothesis.  `Shederator/wosbot` drives the same
client configuration as V2 (720x1280 portrait, MuMu Player, per its README) and its
`VipRoutine.java` opens the VIP menu with

    VIP_MENU_BUTTON_TOP_LEFT  = (430, 48)
    VIP_MENU_BUTTON_BOTTOM_RIGHT = (530, 85)

i.e. a tap at the centre (480, 66) — the top-centre area of the HOME screen, where the
VIP level badge sits.  Under the project's rules that is a *measurement hypothesis*, not a
fact: it must be re-observed on V2's own client before anything is registered, and the
licence (AGPL-3.0-only) forbids copying their code or assets regardless.

Self-limits (the bounded-probe contract):
  * aborts unless the client is on HOME or MAP — it never navigates to get there;
  * taps exactly ONE control, at the hypothesised point, and nothing else;
  * if the result is not a clearly recognisable panel it backs out once and says so;
  * frames + probe.json land in dataset/truth_audit/vip_entry_20260917/ so the next
    session can act on evidence instead of re-probing.

Usage
-----
    python tools/probe_vip_entry.py
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
OUT_DIR = ROOT / "dataset" / "truth_audit" / "vip_entry_20260917"

# centre of the externally documented box (430,48)-(530,85), 720x1280 client
VIP_ENTRY_CENTER = (480, 66)


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
    return device, HybridVision(template, ocr), ocr, config


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    device, hybrid, ocr, config = build()
    from winter_agent_v2.models import Page

    before_frame = OUT_DIR / f"01_before_{STAMP}.png"
    device.screenshot(before_frame)
    before = hybrid.observe(before_frame)
    print(f"before : page={before.page} popup={before.popup} "
          f"stamina={json.dumps(before.stamina, ensure_ascii=False)}")
    if before.page not in {Page.HOME, Page.MAP}:
        print(f"ABORT: page is {before.page}; this probe only runs from HOME or MAP.")
        return 1

    # Read what is actually drawn at the hypothesised point, before touching it.
    band = {"x_norm": 380 / 720, "y_norm": 20 / 1280, "w_norm": 240 / 720, "h_norm": 110 / 1280}
    tokens = []
    try:
        result = ocr.recognize(before_frame, band)
        for token in result.tokens:
            if token.box and token.confidence >= 0.6:
                xs = [p[0] for p in token.box]
                ys = [p[1] for p in token.box]
                tokens.append({"text": token.text, "conf": round(token.confidence, 3),
                               "px": [round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))]})
    except Exception as exc:  # pragma: no cover - diagnostic only
        print(f"ocr at the hypothesised point failed: {type(exc).__name__}: {exc}")
    print(f"tokens at the hypothesised point ({len(tokens)}): "
          f"{json.dumps(tokens, ensure_ascii=False)}")

    device.tap(*VIP_ENTRY_CENTER)
    time.sleep(2.0)

    after_frame = OUT_DIR / f"02_after_tap_{STAMP}.png"
    device.screenshot(after_frame)
    after = hybrid.observe(after_frame)
    print(f"after  : page={after.page} popup={after.popup} rewards={after.rewards}")

    opened = after.page is not before.page or after.popup not in {None, before.popup}
    if not opened:
        print("no page/popup change - restoring with one BACK")
        device.press_back()
        time.sleep(2.0)
        restore = OUT_DIR / f"03_after_back_{STAMP}.png"
        device.screenshot(restore)
        print(f"restored to: {hybrid.observe(restore).page}")

    (OUT_DIR / f"probe_{STAMP}.json").write_text(json.dumps({
        "probe": "vip_entry",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "hypothesis_source": {
            "repo": "Shederator/wosbot",
            "file": "modules/tasks/src/main/java/dev/frostguard/tasks/dailies/VipRoutine.java",
            "box": [[430, 48], [530, 85]],
            "licence": "AGPL-3.0-only - used as a measurement hypothesis only; no code or asset copied",
        },
        "self_limits": ["aborts unless the page is HOME or MAP",
                        "exactly one tap at the hypothesised point",
                        "one bounded BACK if nothing changed"],
        "tap_px": list(VIP_ENTRY_CENTER),
        "tokens_at_point": tokens,
        "before": {"frame": str(before_frame), "page": before.page.value, "popup": before.popup},
        "after": {"frame": str(after_frame), "page": after.page.value, "popup": after.popup},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"frames : {before_frame.name} / {after_frame.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
