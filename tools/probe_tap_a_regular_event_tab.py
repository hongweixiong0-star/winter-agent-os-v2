# -*- coding: utf-8 -*-
"""Tap one tab on the 常规活动 strip, in the same frame that located it.

Why this is a tool and not a few adb commands typed by hand

    The strip returns to its selected tab.  Measured 2026-10-10
    (``dataset/evidence/live_regular_activity_20261010T0745/``): after swipes had it showing
    决战王城 / 堡垒争夺 / 社区, the next look showed 日历(selected) / 最强王国 / 变革的乐章 --
    the leftmost position.  A location read and then acted on two human-paced steps apart lands
    on whatever moved into that spot, which is exactly what happened when a point derived from
    ``bear_tab_visible_on_strip.png`` hit 日历 instead of 巨熊行动.

So the read and the tap happen here as one uninterrupted sequence, and the reader is the
production entry point (``_regular_event_hub_on_frame``, which includes the ROI crop pass) rather
than the inner ``read_regular_event_hub``.  That distinction cost a wrong defect report once
already.

What it refuses to do

    * tap anything while the named tab is not in the current frame's reading -- "not on screen"
      is not a position;
    * tap outside the strip band the reading itself reported;
    * swipe more than ``MAX_ATTEMPTS`` times.

Usage
    python tools/probe_tap_a_regular_event_tab.py 巨熊行动
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: Enough to walk a strip that holds six tabs, and few enough that a strip which never shows the
#: target gives up instead of grinding.
MAX_ATTEMPTS = 6
#: The point the swipe is drawn between, in the strip's own band.  Only the BAND is reused from
#: the reading; the length is the frame's, not a constant, because a strip that has stopped
#: moving does not care how far the gesture was.
SWIPE_FRACTION = 0.72


def attached_serials(adb: str) -> list[str]:
    """Which devices adb currently sees as usable."""
    done = subprocess.run([adb, "devices"], capture_output=True, text=True, check=False)
    rows = [line.split() for line in done.stdout.splitlines()[1:]]
    return [row[0] for row in rows if len(row) >= 2 and row[1] == "device"]


def resolve_serial(adb: str, preferred: str) -> tuple[str, bool]:
    """The configured serial if it is attached, else the only device that is.

    ``config/v2.json`` still names ``127.0.0.1:7555``, which this machine no longer has -- the
    emulator answers on ``emulator-5554``.  A probe that trusts the config silently produced an
    empty screenshot and then a PIL error a long way from the cause, so the substitution is made
    here and reported rather than left to fail downstream.
    """
    seen = attached_serials(adb)
    if preferred in seen:
        return preferred, False
    if len(seen) == 1:
        return seen[0], True
    return preferred, False


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    target = argv[1] if len(argv) > 1 else "巨熊行动"

    cfg = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
    adb = cfg["device"]["adb_path"]
    serial, substituted = resolve_serial(adb, cfg["device"]["serial"])

    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.ocr import OCRService, RapidOCRBackend
    from winter_agent_v2.runtime import LiveRuntime

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    evidence = ROOT / "dataset" / "evidence" / f"tap_regular_event_tab_{stamp}"
    evidence.mkdir(parents=True, exist_ok=True)

    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(
        owner="PROBE_TAP_REGULAR_EVENT_TAB", capability_id="BEAR_HUNT",
        ttl_seconds=600, reason=f"tap {target} on the regular-event strip")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2

    out: dict = {"target": target, "attempts": [], "serial": serial,
                 "serial_substituted_for_config": substituted,
                 "configured_serial": cfg["device"]["serial"],
                 "evidence": str(evidence.relative_to(ROOT))}
    if substituted:
        print(f"note: config names {cfg['device']['serial']}, using {serial} (the only device attached)")
    try:
        service = OCRService(RapidOCRBackend())
        runtime = object.__new__(LiveRuntime)
        runtime.vision = SimpleNamespace(ocr=service)

        def capture(tag: str) -> Path:
            path = evidence / f"{tag}.png"
            with open(path, "wb") as handle:
                subprocess.run([adb, "-s", serial, "exec-out", "screencap", "-p"],
                               stdout=handle, check=False)
            return path

        def tap(x: int, y: int) -> None:
            subprocess.run([adb, "-s", serial, "shell", "input", "tap", str(x), str(y)],
                           check=False)

        def swipe(x1: int, y1: int, x2: int, y2: int) -> None:
            subprocess.run([adb, "-s", serial, "shell", "input", "swipe",
                            str(x1), str(y1), str(x2), str(y2), "400"], check=False)

        towards_end = True
        previous_tabs: list[str] = []
        for attempt in range(1, MAX_ATTEMPTS + 1):
            frame = capture(f"attempt{attempt}_frame")
            hub = runtime._regular_event_hub_on_frame(frame)
            positions = hub.get("tab_positions_norm") or {}
            seen = sorted(positions)
            band = hub.get("tabstrip_roi_norm") or {}
            out["attempts"].append({"attempt": attempt, "tabs": seen,
                                    "calendar_tab_visible": hub.get("calendar_tab_visible")})

            if target in positions:
                nx, ny = positions[target]
                x, y = round(nx * 720), round(ny * 1280)
                # Refuse a point outside the band the reading itself reported.  The band is the
                # only thing here that came from this frame.
                top = band.get("y_norm") or 0.0
                bottom = top + (band.get("h_norm") or 0.0)
                inside = top <= ny <= bottom
                out["attempts"][-1].update(tapped=(x, y), inside_band=inside)
                if not inside:
                    out["stopped"] = "the only position found was outside the strip band"
                    break
                tap(x, y)
                time.sleep(3.0)
                after = capture(f"attempt{attempt}_after")
                out["attempts"][-1]["after_frame"] = after.name
                out["landed"] = True
                break

            # Not in this frame's reading.  Move the strip one step and look again -- never tap
            # a remembered position, because the strip may have returned to its selected tab.
            top = band.get("y_norm")
            height = band.get("h_norm")
            if isinstance(top, (int, float)) and isinstance(height, (int, float)) and height > 0:
                y_mid = round((top + height / 2) * 1280)
                span = round(SWIPE_FRACTION * 720 / 2)
                left, right = round(360 - span), round(360 + span)
                # Try BOTH directions, and let the strip decide -- the same rule the runtime
                # uses (``_regular_event_hub_on_frame``'s caller alternates on whether
                # ``tab_signature`` moved).  A fixed direction walks away from a target on the
                # other side: 巨熊行动 sat to the LEFT of 决战王城, and swiping towards the end
                # every time pushed it further out of view for all six attempts.
                if seen != previous_tabs:
                    # The strip moved since last time, so the direction just used is a live one.
                    pass
                else:
                    towards_end = not towards_end
                if towards_end:
                    swipe(left, y_mid, right, y_mid) if False else swipe(right, y_mid, left, y_mid)
                else:
                    swipe(left, y_mid, right, y_mid)
                out["attempts"][-1]["swipe_towards_end"] = towards_end
                previous_tabs = seen
                time.sleep(1.5)
    finally:
        lease.release(result="DONE", reason=f"probe finished, landed={out.get('landed', False)}")

    ledger = ROOT / "learning" / f"tap_regular_event_tab_{stamp}.json"
    ledger.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    out["ledger"] = str(ledger.relative_to(ROOT))
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
