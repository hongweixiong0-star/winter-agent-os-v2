# -*- coding: utf-8 -*-
"""Three separate blockers sit between "the tap opened the right card" and "the row is credited".

This is the acceptance instrument for repairing the calendar-detail loop, and it exists
because the first thing I believed about that loop was wrong.  I had concluded, from reading
the code, that the whole defect was one guard condition.  Measuring it found three blockers,
and the third one is the one that actually explains why the debt never clears.

Blocker 1 -- the reader is gated out of the very state it is meant to read.
    ``ocr.py:1282-1295`` computes ``seconds_to_start = self._explicit_start_seconds(...)``
    inside ``if ... and calendar_reading.get("recognized") is not True``.  The preview card is
    an OVERLAY, so the grid behind it is still recognised (5 rows instead of 6) and the branch
    never runs.  The reader itself already exists and is already called -- the gate excludes
    the state the overlay creates.

Blocker 2 -- the detail reader does not recognise the card.
    Measured on the real card frame: ``read_event_detail`` answers ``recognized=False``.
    ``verify_event_calendar_detail_open`` requires ``after.events["calendar_detail"]`` to be
    recognised, so without this the step can never verify and the row is never credited.

Blocker 3 -- and this one is not about either of the above: the identity is not stable.
    ``event_calendar._event_id`` hashes the OCR label::

        digest = hashlib.sha1(label.encode("utf-8")).hexdigest()[:10].upper()
        return f"DISCOVERED_EVENT_{digest}"

    So the SAME activity gets a DIFFERENT persistent id depending on how much of its label
    OCR happened to read -- and a card covering part of a row is exactly what truncates it:

        grid  神秘藏宝室 -> DISCOVERED_EVENT_A33B0DC6E9
        card  神秘藏     -> DISCOVERED_EVENT_2AE3F69AE7     DIFFERENT
        grid  旅途的收获 -> DISCOVERED_EVENT_2CED2A762E
        card  旅途的     -> DISCOVERED_EVENT_80FDBE61F5     DIFFERENT

    The debt on file is keyed on the GRID frame's ids, so a reading taken on a frame that read
    the label differently credits an id the debt has never heard of, and
    ``advertised_but_unread_activities`` cannot fall -- which is why this loop is not fixable
    by relaxing a guard.

Usage
    python tools/probe_whether_a_card_identity_matches_the_row.py

Offline only: reads saved PNGs, never the device.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from winter_agent_v2 import event_calendar as ec  # noqa: E402
from winter_agent_v2 import event_goal as eg  # noqa: E402
from winter_agent_v2.ocr import OCRService, RapidOCRBackend  # noqa: E402
from winter_agent_v2.runtime import read_frame_size  # noqa: E402

RUN = ROOT / "dataset" / "raw" / "control_panel" / "runtime_auto" / "20261010_084940_792088"
FRAMES = {
    "CARD (post-tap, panel over grid)": RUN / (
        "20261010_084940_792088_step_004_before_20261010T005039829501.png"),
    "GRID (pre-tap, plain)": RUN / (
        "20261010_084940_792088_step_003_before_20261010T005029288173.png"),
}


def discovered_id(label: str) -> str:
    """The id ``event_calendar._event_id`` would mint for an unregistered label."""
    known = eg.event_id_for_label(label)
    if known:
        return known
    return f"DISCOVERED_EVENT_{hashlib.sha1(label.encode('utf-8')).hexdigest()[:10].upper()}"


def main() -> int:
    ocr = OCRService(RapidOCRBackend())
    rows_by_frame: dict[str, dict[str, str]] = {}

    for label, frame in FRAMES.items():
        print("=" * 94)
        print(f"{label}\n  {frame.name}")
        if not frame.is_file():
            print("  MISSING -- cannot measure")
            continue
        size = read_frame_size(frame)
        tokens = ocr.recognize(frame).tokens
        detail = ec.read_event_detail(tokens, event_label=None, frame_size=size)
        calendar = ec.read_event_calendar(tokens, frame_size=size, frame_path=frame)
        print(f"  blocker 2  read_event_detail   -> recognized={detail.get('recognized')!r}")
        print(f"             read_event_calendar -> recognized={calendar.get('recognized')!r} "
              f"details_visible={calendar.get('details_visible')!r} "
              f"entries={len(calendar.get('entries') or ())}")
        rows_by_frame[label] = {
            str(r.get("display_name")): str(r.get("event_id"))
            for r in (calendar.get("entries") or ()) if isinstance(r, dict)
        }
        for name, eid in rows_by_frame[label].items():
            print(f"             row {name!r:12s} id={eid}")

    print("=" * 94)
    print("blocker 3  identity is sha1 of the OCR label, so it moves when the label is truncated")
    names = list(rows_by_frame.values())
    if len(names) == 2:
        grid, card = names
        same, differ = [], []
        for name, eid in grid.items():
            match = {n: i for n, i in card.items() if i == eid}
            (same if match else differ).append((name, eid, list(match) or None))
        print(f"  ids found on both frames : {len(same)}")
        for name, eid, other in same:
            print(f"      {name!r:14s} {eid}  (also read as {other})")
        print(f"  ids that did NOT survive  : {len(differ)}")
        for name, eid, _ in differ:
            print(f"      {name!r:14s} {eid}  <- absent from the other frame's reading")
        print()
        print("  worked example of the truncation a card causes:")
        for grid_name, card_name in (("神秘藏宝室", "神秘藏"), ("旅途的收获", "旅途的")):
            print(f"      grid {grid_name!r:8s} -> {discovered_id(grid_name)}")
            print(f"      card {card_name!r:8s} -> {discovered_id(card_name)}"
                  f"   {'SAME' if discovered_id(grid_name) == discovered_id(card_name) else 'DIFFERENT'}")

    print("=" * 94)
    print("READING: blockers 1 and 2 can be repaired by relaxing a gate and teaching the detail")
    print("reader this card.  Blocker 3 cannot: while identity is a hash of OCR text, a reading")
    print("taken on any frame that truncated a label credits an id the debt has never heard of.")
    print("So the repair is a change to how a discovered activity's identity is derived, not a")
    print("condition in a guard -- and it needs its own design.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
