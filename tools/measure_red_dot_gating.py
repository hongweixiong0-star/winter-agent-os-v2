"""The before/after numbers for red-dot-driven eligibility, from production episodes only.

Operator directive 2026-09-23 §八: 统计修改前后至少一段正式 AUTO --

    OPEN_MAIL 次数 · 其中入口 ABSENT 时的 OPEN_MAIL 次数
    OPEN_ALLIANCE_GIFTS 次数 · 其中宝箱 ABSENT 时的进入次数
    PRESENT 出现后到首次有效处理的延迟

and the acceptance it is measured against: 邮件 ABSENT → 无 OPEN_MAIL；宝箱 ABSENT →
无宝箱页面进入；PRESENT → 能及时处理；UNKNOWN → 不靠盲目进入页面解决.

The window is split at the commit that landed the gate, and the split is a constant here rather than
a remembered date so a reader can move it and re-run:

    python tools/measure_red_dot_gating.py
    python tools/measure_red_dot_gating.py --since 2026-09-23T13:20:00+00:00

The entry reading is the one production recorded on the step itself
(``state_before.red_dots``); a step whose entry is not in the ledger at all is counted as
**NO_READING**, never as ABSENT -- the distinction the whole layer exists for.  The alliance tile's
badge is read from the same ledger, and if it is missing there the window is measured off the frame
(as the registration tool measures it), so a step taken before the tile was registered is not silently
counted as "no dot".

Read-only: no device, no clicks, no writes.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EPISODES = ROOT / "learning/episodes.jsonl"

#: The observed-start of the real run that first executed the gate (its steps carry the reasons this
#: tool counts, which is what makes the boundary checkable rather than asserted).
GATE_LANDED_AT = "2026-09-23T13:25:00+00:00"

MAIL_ENTRY = "BTN_OPEN_MAIL"
GIFTS_ENTRY = "TILE_ALLIANCE_GIFTS"


def _rows() -> list[dict]:
    out: list[dict] = []
    try:
        handle = EPISODES.open(encoding="utf-8")
    except OSError:
        return out
    with handle:
        for line in handle:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("recorded_at"):
                out.append(row)
    return out


def _entry_state(row: dict, entry: str, *, frame_window: list[float] | None = None) -> str:
    """PRESENT / ABSENT / UNKNOWN / NO_READING, from the step's own ledger (else the frame)."""
    ledger = (row.get("state_before") or {}).get("red_dots")
    if isinstance(ledger, dict) and entry in ledger:
        return str((ledger.get(entry) or {}).get("state") or "UNKNOWN")
    if frame_window is None:
        return "NO_READING"
    frame = Path(str(row.get("before_screenshot") or ""))
    if not frame.is_file():
        return "NO_READING"
    try:
        from PIL import Image

        from winter_agent_v2.entry_badges import MIN_BLOB_PX, _largest_blob

        image = Image.open(frame).convert("RGB")
        width, height = image.size
        box = (
            int(frame_window[0] * width), int(frame_window[1] * height),
            int(frame_window[2] * width), int(frame_window[3] * height),
        )
        pixels, _ = _largest_blob(image, box)
    except (OSError, ValueError):
        return "NO_READING"
    return "PRESENT" if pixels >= MIN_BLOB_PX else "ABSENT"


def _window(rows: list[dict], since: str, until: str) -> list[dict]:
    out = []
    for row in rows:
        stamp = str(row.get("recorded_at") or "")
        if since and stamp < since:
            continue
        if until and stamp >= until:
            continue
        out.append(row)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default=None)
    parser.add_argument("--until", default="")
    args = parser.parse_args()

    from winter_agent_v2 import entry_badges

    split = args.since or GATE_LANDED_AT
    rows = _rows()
    if not rows:
        print("no episodes on file")
        return 1
    rows.sort(key=lambda row: str(row.get("recorded_at")))

    tile_window = (entry_badges.entries().get(GIFTS_ENTRY) or {}).get("search_window_norm")
    windows = (("BEFORE the gate (periodic, dot-as-priority)", "", split),
               ("AFTER  the gate (dot-as-eligibility)", split, args.until))

    for label, since, until in windows:
        slice_ = _window(rows, since, until)
        print(f"===== {label}")
        print(f"      steps {len(slice_)}"
              + (f"   from {slice_[0].get('recorded_at')}" if slice_ else "")
              + (f"   to {slice_[-1].get('recorded_at')}" if slice_ else ""))
        for skill, entry, frame_window in (
            ("OPEN_MAIL", MAIL_ENTRY, None),
            ("OPEN_ALLIANCE_GIFTS", GIFTS_ENTRY, tile_window),
        ):
            steps = [row for row in slice_ if str(row.get("skill")) == skill]
            counts = Counter(_entry_state(row, entry, frame_window=frame_window) for row in steps)
            print(f"   {skill:<22} steps {len(steps):>4}   by entry badge: {dict(counts)}")
            if entry == GIFTS_ENTRY:
                ledgered = Counter(
                    _entry_state(row, entry) for row in steps if _entry_state(row, entry) != "NO_READING"
                )
                if ledgered:
                    print(f"   {'':<22} of those, from the step's own ledger: {dict(ledgered)}")
        refusals = Counter(
            str(row.get("decision_reason")) for row in slice_
            if "entry_" in str(row.get("decision_reason") or "")
            or "refused_at_the_entry_gate" in str(row.get("decision_reason") or "")
        )
        print(f"   entry-gate decisions: {dict(refusals) or '(none)'}")
        print()

    print("expected after the gate:")
    print("  邮件 ABSENT/UNKNOWN  → 没有 OPEN_MAIL 步；宝箱 ABSENT/UNKNOWN → 没有 OPEN_ALLIANCE_GIFTS 步")
    print("  被拒的步应为 SAFE_STOP 且 reason 含 entry_gate / entry_badge（非致命，让位给其他 Goal）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
