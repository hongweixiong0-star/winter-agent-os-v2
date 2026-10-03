"""Does the page-identity branch mistake a calendar grid for an event detail page?

The other direction was measured on the real 峡谷会战 frame: the branch recognises it and
names CANYON_CLASH, with every time field still None. This checks the frame that must NOT
be recognised, because a false positive here is worse than the bug being fixed -- it would
attribute a grid observation to an activity and poison the detail store.

Frames come from the production ledger (``state_before.page == EVENT`` with a
``calendar`` reading and no ``regular_events_hub``) and are read with the project's own OCR.
Every frame is checked and the count is printed, so an empty sample reports itself as
``0 / 0`` rather than passing silently -- which is exactly what happened when this was
first run through a shell that truncated the argument.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from winter_agent_v2 import event_calendar as ec  # noqa: E402
from winter_agent_v2 import ocr as o  # noqa: E402

LEDGER = ROOT / "learning/episodes.jsonl"
WINDOW = 2500
LIMIT = 12


def grid_frames() -> list[str]:
    rows: list[dict] = []
    with LEDGER.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("recorded_at"):
                rows.append(row)
    rows.sort(key=lambda r: r["recorded_at"])
    frames: list[str] = []
    for row in rows[-WINDOW:]:
        before = row.get("state_before")
        if not isinstance(before, dict) or before.get("page") != "EVENT":
            continue
        events = before.get("events")
        if not isinstance(events, dict):
            continue
        if not isinstance(events.get("calendar"), dict):
            continue
        if isinstance(events.get("regular_events_hub"), dict):
            continue
        shot = row.get("before_screenshot")
        if shot and Path(shot).exists():
            frames.append(shot)
    return frames[-LIMIT:]


def main() -> int:
    frames = grid_frames()
    print(f"real calendar-grid frames: {len(frames)}")
    if not frames:
        print("FAIL: no grid frame available; the negative direction is unmeasured")
        return 1
    service = o.OCRService(o.RapidOCRBackend())
    false_positives = 0
    for shot in frames:
        path = Path(shot)
        width, height = Image.open(path).size
        tokens = service.recognize(path).tokens
        reading = ec.read_event_detail(tokens, event_label=None, frame_size=(width, height))
        heading = ec._heading_scale_activity(
            [(t, t.text.strip()) for t in tokens if t.text.strip()], (width, height))
        recognised = reading.get("recognized") is True
        false_positives += recognised
        print(f"  {path.name[:44]:<46} recognized={str(recognised):<6} "
              f"event_id={str(reading.get('event_id'))[:20]:<22} heading={heading!r}")
    print()
    print(f"grid frames mistaken for a detail page: {false_positives} / {len(frames)}")
    return 0 if false_positives == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
