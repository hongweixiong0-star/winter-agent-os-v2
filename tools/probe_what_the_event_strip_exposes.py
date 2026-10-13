# -*- coding: utf-8 -*-
"""What does the 常规活动 strip actually expose on a frame the run will stand on?

Why this exists

    The strip is the last thing ``advertised_but_unread_activities`` still owes
    (``event_schedule.py:509-519``) and the only tab the runtime can currently open on it is
    日历.  This probe answers the one question that decides how large the fix is: **does the
    production hub reading already carry a tap point for a named tab, or does a new reader
    have to be written?**

    It is deliberately frame-based, not device-based.  The question is about the reader, and
    reading saved frames steals nothing from a running AUTO loop.

Why the production entry and not the inner helper

    ``runtime._regular_event_hub_on_frame`` (``runtime.py:2504``) is the reader the runtime
    actually calls: it adds an ROI-crop second OCR pass that recovers the ~23px tab labels
    RapidOCR's whole-frame detector misses.  Measuring the inner ``read_regular_event_hub``
    once produced a wrong defect report in this project, so this tool builds a real
    ``LiveRuntime`` shell around a real ``OCRService`` and calls the production method.

What it measured on 2026-10-10

    ``dataset/evidence/live_regular_activity_20261010T0745/``
      regular_activity_before_swipe.png     tabs=[变革的乐章, 日历]              cal=True
      regular_activity_after_production_derived_swipe.png
                                            tabs=[决战王城, 巨熊行动]  <<< 巨熊行动 present
      bear_tab_visible_on_strip.png         tabs=[决战王城, 巨熊行动]  <<< tap_norm=[0.25556, 0.13359]
      strip_before_tap_showing_bear_tab.png tabs=[存戏, 巨熊行动, 决战王城, 堡垒争夺]
                                                                     <<< tap_norm=[0.32153, 0.13398]
      regular_activity_calendar_off_screen.png
                                            tabs=[决战王城, 堡垒争夺, 社区]      scroll both ways

    Two things follow, and they are the whole point of the file:

      1. ``tab_positions_norm`` already carries ``{label: [x_norm, y_norm]}`` for every unique
         tab on the strip.  **No new reader is needed** -- the geometry is already produced,
         and one of today's frames puts 巨熊行动 in it.
      2. The strip is a real scroller: the same screen shows three different tab sets at three
         scroll positions, and 巨熊行动 sits beside 决战王城, not at the leftmost slot.  A fix
         that taps it must first reveal it.

Usage
    python tools/probe_what_the_event_strip_exposes.py [frame.png ...]
    python tools/probe_what_the_event_strip_exposes.py            # uses the default frame set

Exit code is 0 when every frame that the hub recognises behaves consistently with the notes
above, and 1 when the strip stops exposing per-tab positions at all -- the regression this
probe exists to catch.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EVIDENCE = ROOT / "dataset" / "evidence"
DEFAULT_FRAMES = (
    EVIDENCE / "live_regular_activity_20261010T0745" / "regular_activity_before_swipe.png",
    EVIDENCE / "live_regular_activity_20261010T0745" / "regular_activity_calendar_off_screen.png",
    EVIDENCE / "live_regular_activity_20261010T0745" / "regular_activity_after_forward_swipe.png",
    EVIDENCE / "live_regular_activity_20261010T0745" / "regular_activity_production_run.png",
    EVIDENCE / "live_regular_activity_20261010T0745"
    / "regular_activity_after_production_derived_swipe.png",
    EVIDENCE / "live_regular_activity_20261010T0745" / "bear_tab_visible_on_strip.png",
    EVIDENCE / "live_regular_activity_20261010T0745" / "bear_activity_page_live.png",
    EVIDENCE / "live_bear_page_20261010T0800" / "strip_before_tap_showing_bear_tab.png",
    EVIDENCE / "live_bear_page_20261010T0800" / "bear_page_live_20261010.png",
)

#: The tab this whole line of work exists to reach.
TARGET = "巨熊行动"


def build_reader():
    """The production hub reader, without a device.

    ``_regular_event_hub_on_frame`` reaches the OCR service through ``self._ocr_service()``,
    which the real runtime fills from its vision object.  An uninitialised ``LiveRuntime``
    with only that attribute set is enough to call the real method -- the same shell
    ``tools/probe_tap_a_regular_event_tab.py`` uses.
    """
    from winter_agent_v2.ocr import OCRService, RapidOCRBackend
    from winter_agent_v2.runtime import LiveRuntime

    runtime = object.__new__(LiveRuntime)
    runtime.vision = SimpleNamespace(ocr=OCRService(RapidOCRBackend()))
    return runtime._regular_event_hub_on_frame


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    frames = [Path(a) for a in argv[1:]] or [Path(p) for p in DEFAULT_FRAMES]
    read_hub = build_reader()

    recognised = 0
    with_positions = 0
    targets: list[tuple[str, object]] = []

    print(f"{'frame':54s} {'recog':5s} {'cal':5s} {'display':10s} tab_positions_norm keys")
    print("-" * 132)
    for frame in frames:
        if not frame.is_file():
            print(f"{frame.name:54s} MISSING  ({frame})")
            continue
        hub = read_hub(frame)
        positions = hub.get("tab_positions_norm") or {}
        if hub.get("recognized") is True:
            recognised += 1
            if positions:
                with_positions += 1
        if TARGET in positions:
            targets.append((frame.name, positions[TARGET]))
        mark = "  <<< TARGET PRESENT" if TARGET in positions else ""
        print(f"{frame.name:54s} {str(hub.get('recognized')):5s} "
              f"{str(hub.get('calendar_tab_visible')):5s} "
              f"{str(hub.get('display_name'))[:10]:10s} {sorted(positions)}{mark}")
        if positions:
            print(f"       positions: "
                  f"{ {k: v for k, v in positions.items()} }")
        print(f"       tabs(raw)={[t.get('label') for t in (hub.get('tabs') or [])]} "
              f"scroll_start={bool(hub.get('scroll_to_start_norm'))} "
              f"scroll_end={bool(hub.get('scroll_to_end_norm'))} "
              f"band={hub.get('tabstrip_roi_norm')}")

    print("-" * 132)
    print(f"recognised {recognised}/{len(frames)}  "
          f"with per-tab positions {with_positions}  "
          f"frames showing {TARGET} {len(targets)}")
    if targets:
        print(f"{TARGET} tap points measured:")
        for name, point in targets:
            print(f"  {name} -> {point}")

    problems: list[str] = []
    if recognised == 0:
        problems.append("no frame was recognised as the regular-event hub")
    if with_positions == 0:
        problems.append("no frame exposed per-tab positions at all -- the reader regressed")
    if not targets:
        problems.append(f"no frame exposed a {TARGET} tab -- the strip may have changed shape")
    if problems:
        print("PROBLEMS:")
        for problem in problems:
            print("  -", problem)
        return 1
    print("OK: the production hub reader exposes per-tab tap points, and a tab tap needs no "
          "new reader.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
