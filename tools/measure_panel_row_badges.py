"""Do the quick panel's own row dots discriminate between the rows a goal can act on?

The operator's §二② (2026-09-23) makes a red dot a *priority* signal, and the first document's
§一 makes it a signal only when it is bound to a concrete entry or task row.  The panel row
badges satisfy the second half already -- ``read_quick_panel`` reads them per row, and
``entry_badges.quick_panel_badges`` reports UNKNOWN for a row nobody scrolled to -- and nothing in
the goal layer has ever looked at them.

Before wiring them into the one ranking layer, measure whether the signal can change an order at
all.  A term that adds the same number to every candidate is dead code, so the question is:

    on a frame where the panel is open, how often does at least one row read PRESENT while
    another row of the same reading reads ABSENT?

Counted per row key, and per frame, over what production recorded.  ``UNKNOWN`` rows are counted
separately and never treated as ABSENT (operator §一).  Read-only.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EPISODES = ROOT / "learning/episodes.jsonl"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from winter_agent_v2.entry_badges import QUICK_PANEL_ROW_GOALS, table

    #: The rows the panel draws, from the same table ``read_quick_panel`` keys its reading by.
    keys = tuple(QUICK_PANEL_ROW_GOALS)
    known = {str(row["entry"]) for row in table()["entries"]}
    print(f"panel row keys under test : {len(keys)}")
    print(f"measured table entries    : {sorted(known)}")

    rows = []
    skipped = 0
    with EPISODES.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                # Counted rather than swallowed: ``episodes.jsonl`` is appended to by a live
                # runtime, so a half-written tail is expected and a silent skip would be
                # indistinguishable from a smaller corpus.
                skipped += 1
    print(f"lines skipped (malformed): {skipped}")

    per_key: Counter[str] = Counter()
    frames_with_panel: list[dict[str, str]] = []
    seen_panels = set()
    goal_bindings: Counter[str] = Counter()

    for row in rows:
        state = row.get("state_before")
        if not isinstance(state, dict):
            continue
        panel = state.get("quick_panel") or {}
        if not isinstance(panel, dict) or not panel.get("open"):
            continue
        frame = str(row.get("before_screenshot") or "")
        if frame in seen_panels:
            continue
        seen_panels.add(frame)
        dots = state.get("red_dots") or {}
        reading = {}
        for key in keys:
            entry = f"QUICK_PANEL_ROW_{key}"
            record = dots.get(entry) if isinstance(dots, dict) else None
            word = str((record or {}).get("state") or "NOT_READ")
            reading[key] = word
            per_key[f"{key}={word}"] += 1
            goal = (record or {}).get("goal")
            if word == "PRESENT" and goal:
                goal_bindings[str(goal)] += 1
        frames_with_panel.append(reading)

    print(f"\npanel-open, distinct frames : {len(frames_with_panel)}")
    print("\nper-row states (NOT_READ means the ledger carried no record for that row):")
    for key in keys:
        states = {k.split("=", 1)[1]: v for k, v in per_key.items() if k.startswith(f"{key}=")}
        print(f"  {key:<20} {states}")

    discriminating = 0
    mixed_present = 0
    all_read_absent = 0
    for reading in frames_with_panel:
        present = [k for k, v in reading.items() if v == "PRESENT"]
        absent = [k for k, v in reading.items() if v == "ABSENT"]
        if present and absent:
            discriminating += 1
        if len(present) > 1:
            mixed_present += 1
        if not present and len(absent) == len(reading):
            all_read_absent += 1

    print(f"\nframes where >=1 row is PRESENT and >=1 other row is ABSENT : {discriminating}")
    print(f"frames where more than one row is PRESENT                   : {mixed_present}")
    print(f"frames where every readable row is ABSENT                   : {all_read_absent}")
    print(f"\ngoals a PRESENT dot would point at, by count                 : {dict(goal_bindings)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
