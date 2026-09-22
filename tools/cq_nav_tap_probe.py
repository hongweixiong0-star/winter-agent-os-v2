"""Measure the live tap mapping: tap a point, read the page, back out, repeat.

Bounded and honest: it only taps coordinates passed on the command line, only
from an observed HOME, and recovers HOME with the client's own controls (the map's 城镇 door, a
popup's close button) rather than with blind BACKs -- BACK on the map opens 退出确认, which is how
this probe used to manufacture the state it then failed on.

**Pass points measured on the frame you are about to tap.**  A coordinate copied from another frame
taps whatever is drawn there now: measured 2026-09-23 19:11, a collapsed-panel handle point taken
from a test fixture (13, 550) opened a 军师 card page instead of the panel, and the three-tap sequence
that followed was measuring the wrong screen from its first step.  The handle in particular is located
per frame by ``ocr.find_quick_panel_handle``; its own point, not a remembered one, is what opens the
panel.
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

OUT_DIR = ROOT / "dataset" / "truth_audit" / "nav_to_map_20260918"


def build():
    from winter_agent_v2.device import ADBDevice
    from winter_agent_v2.device_lease import OWNER_DEVELOPMENT_VALIDATION, DeviceLease
    from winter_agent_v2.ocr import HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend
    from winter_agent_v2.vision import SemanticWorldVision

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    device = ADBDevice(Path(config["device"]["adb_path"]), config["device"]["serial"],
                       production=True)
    device.resolve_connection()
    template = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))
    return device, HybridVision(template, ocr), template


def take_the_lease(tag: str):
    """The device lease, or None with the reason already printed.

    A refusal is not an error: it is the device being busy, and the honest response is to wait for
    the safe point rather than to click anyway.
    """
    from winter_agent_v2.device_lease import OWNER_DEVELOPMENT_VALIDATION, DeviceLease

    lease = DeviceLease(ROOT)
    record, why = lease.acquire(
        owner=OWNER_DEVELOPMENT_VALIDATION,
        capability_id=f"probe:{tag}",
        reason=f"directed tap probe {tag}",
    )
    if record is None:
        print(f"REFUSED: {why}")
        return None
    print(f"lease: {why} (expires {record.expires_at.isoformat()})")
    return lease


def parse_point(raw: str) -> tuple[int, int]:
    x, y = raw.split(",")
    return int(x), int(y)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tap", action="append", type=parse_point, default=[])
    parser.add_argument("--tag", default="tapmap")
    #: Read the client without touching it: which page it is on, whether the 快捷面板 is drawn, and
    #: its rows.  A directed tap sequence has to know where it starts -- the same fixed sequence is a
    #: panel tap from HOME and a march order from the map, so "where are we" precedes "tap".
    parser.add_argument("--page", action="store_true", help="read the current page and exit")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    lease = take_the_lease(args.tag)
    if lease is None:
        return 3
    device, hybrid, template = build()
    status = device.status()
    print(f"device resolution (wm size): {status.resolution} focus={status.foreground_package}")

    if args.page:
        frame = OUT_DIR / f"{args.tag}_{stamp}_page.png"
        device.screenshot(frame)
        state = hybrid.observe(frame)
        panel = state.quick_panel or {}
        print(f"page={state.page.value} conf={state.confidence:.2f} popup={state.popup} "
              f"panel_open={panel.get('open')} rows={[r.get('key') for r in (panel.get('rows') or [])]}")
        for key, value in sorted((state.red_dots or {}).items()):
            print(f"   red_dot {key:34} {value.get('state')}")
        print(f"frame: {frame}")
        lease.release(result="OK", reason="read-only page check")
        return 0

    rows = []
    for index, (x, y) in enumerate(args.tap, start=1):
        # Reach HOME by the client's own controls.  See the module docstring: BACK is not a way out of
        # the map (it opens 退出确认) and pressing it there is how this probe used to create the state
        # it then failed on.
        for attempt in range(4):
            frame = OUT_DIR / f"{args.tag}_{stamp}_{index:02d}_pre{attempt}.png"
            device.screenshot(frame)
            state = hybrid.observe(frame)
            if state.page.value == "HOME":
                break
            if state.page.value == "UNKNOWN":
                # A frame the reader cannot place is not "somewhere else".  Treating it as one sent
                # this probe hopping to the map from HOME (measured 19:10:10: the frame right after a
                # panel tap read UNKNOWN/0.00, the recovery tapped the 野外 door, and the next tap
                # landed on the map instead of on the control under test).  One more look, because
                # that frame is a transition, and then stop rather than navigate on a guess.
                time.sleep(2.5)
                device.screenshot(frame)
                state = hybrid.observe(frame)
                if state.page.value == "UNKNOWN":
                    print(f"ABORT at {x},{y}: the frame reads UNKNOWN twice; not navigating on it")
                    break
                if state.page.value == "HOME":
                    break
            hop = None
            if state.page.value == "MAP":
                hop = template.semantic.find(frame, "BTN_OPEN_HOME")
                semantic = "BTN_OPEN_HOME"
            elif state.page.value == "POPUP":
                hop = template.semantic.find(frame, "BTN_CLOSE")
                semantic = "BTN_CLOSE"
            if hop is not None:
                roi = hop[2]
                point = (round((roi["x_norm"] + roi["w_norm"] / 2) * status.resolution[0]),
                         round((roi["y_norm"] + roi["h_norm"] / 2) * status.resolution[1]))
                print(f"      recovering: {semantic} matched on this frame -> tap {point}")
                device.tap(*point)
            else:
                print(f"      recovering: no registered control on {state.page.value}; one BACK")
                device.press_back()
            time.sleep(2.5)
        else:
            print(f"ABORT at {x},{y}: could not recover HOME (stuck on {state.page.value})")
            break
        print(f"[{index}] HOME ok; tapping ({x},{y}) via {device.__class__.__name__}.tap")
        device.tap(x, y)
        time.sleep(2.5)
        after_frame = OUT_DIR / f"{args.tag}_{stamp}_{index:02d}_after_{x}_{y}.png"
        device.screenshot(after_frame)
        after = hybrid.observe(after_frame)
        template_state = template.observe(after_frame)
        print(f"      after -> page={after.page.value} conf={after.confidence:.2f} "
              f"popup={after.popup} | template-only={template_state.page.value} "
              f"{template_state.confidence:.2f} | {after_frame.name}")
        rows.append({"tap": [x, y], "page": after.page.value, "confidence": after.confidence,
                     "popup": after.popup, "template_only": template_state.page.value,
                     "frame": str(after_frame)})

    (OUT_DIR / f"tapmap_{stamp}.json").write_text(
        json.dumps({"recorded_at": datetime.now(timezone.utc).isoformat(),
                    "device_resolution": status.resolution, "rows": rows},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    lease.release(result="OK", reason=f"{len(rows)} tap(s) measured")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
