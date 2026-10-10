# -*- coding: utf-8 -*-
"""Is ``details_visible=True`` a reliable sign that a panel really covers the grid?

The question this decides

    ``event_calendar.read_event_calendar`` sets the flag as::

        bool(date_range or _COUNTDOWN_RE.search(detail_text) or "活动详情" in detail_text)

    One candidate repair for the calendar-detail loop routes BACK when the flag is True and
    no ``calendar_detail`` was read.  That is only safe if the flag does not also fire on a
    plain grid frame -- a false positive there would back the scan out of a screen it should
    be reading, which is worse than the loop it fixes.

    So the flag is printed beside the frame's entries and its ``calendar_detail`` reading, and
    the answer is a table rather than an assumption.

Usage
    python tools/probe_whether_the_detail_flag_fires_on_a_plain_grid.py
    python tools/probe_whether_the_detail_flag_fires_on_a_plain_grid.py frame1.png frame2.png

Offline only: reads saved PNGs, never the device.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from winter_agent_v2.ocr import OCRPageClassifier, OCRService, RapidOCRBackend  # noqa: E402
from winter_agent_v2.runtime import read_frame_size  # noqa: E402
from winter_agent_v2.event_calendar import read_event_calendar  # noqa: E402

EVIDENCE = ROOT / "dataset" / "evidence"
#: Frames the run has actually stood on: the captured regular-activity session, the bear page,
#: and the newest runtime_auto frames around the calendar-detail steps.
DEFAULT_FRAMES = [
    EVIDENCE / "live_regular_activity_20261010T0745" / name for name in (
        "regular_activity_before_swipe.png", "regular_activity_calendar_off_screen.png",
        "regular_activity_after_forward_swipe.png", "regular_activity_forward_2.png",
        "regular_activity_forward_3.png", "regular_activity_production_run.png",
        "regular_activity_after_production_derived_swipe.png", "bear_tab_visible_on_strip.png",
        "bear_activity_page_live.png", "regular_activity_after_derived_nudge_back.png",
    )
] + [
    EVIDENCE / "live_bear_page_20261010T0800" / name for name in (
        "strip_before_tap_showing_bear_tab.png", "bear_page_live_20261010.png",
    )
] + sorted((ROOT / "dataset" / "raw" / "control_panel" / "runtime_auto").glob(
    "2026101*_*/2026101*_step_00[34]_before_*.png"))[-10:]


def main(argv: list[str]) -> int:
    frames = [Path(a) for a in argv[1:]] or DEFAULT_FRAMES
    ocr = OCRService(RapidOCRBackend())
    classifier = OCRPageClassifier()

    print(f"{'frame':58s} {'recognized':10s} {'details_visible':15s} "
          f"{'calendar_detail':16s} entries")
    print("-" * 118)
    by_flag: dict[bool, list[str]] = {True: [], False: []}
    panel_evidence: list[tuple[str, str]] = []
    for frame in frames:
        if not frame.is_file():
            continue
        result = ocr.recognize(frame)
        size = read_frame_size(frame)
        calendar = read_event_calendar(result.tokens, frame_size=size, frame_path=frame)
        events = (classifier.classify(result, frame_size=size).events or {})
        detail = events.get("calendar_detail") if isinstance(events.get("calendar_detail"), dict) else None
        flag = calendar.get("details_visible")
        if calendar.get("recognized") is True:
            by_flag[bool(flag)].append(frame.name)
            if flag:
                panel_evidence.append((frame.name, "calendar_detail read" if detail else
                                       "NO calendar_detail"))
        print(f"{frame.name[:58]:58s} {str(calendar.get('recognized')):10s} "
              f"{str(flag):15s} {str(bool(detail)):16s} {len(calendar.get('entries') or ())}")

    print("-" * 118)
    print(f"details_visible=True  on {len(by_flag[True])} recognised frames")
    for name in by_flag[True]:
        note = dict(panel_evidence).get(name, "")
        print(f"    {name}   <- {note}")
    print(f"details_visible=False on {len(by_flag[False])} recognised frames")
    print()

    if not by_flag[True] and not by_flag[False]:
        print("PROBLEMS: no frame was recognised as a calendar grid -- nothing was measured")
        return 1
    print("READING: the flag is safe as a 'a panel is covering the grid' signal when every")
    print("True frame is one where a panel really is up (the post-tap frames), and every")
    print("plain grid frame reads False.  A True on a frame with no calendar_detail and no")
    print("panel is the false positive that would make routing BACK unsafe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
