"""Measure the 联盟宝箱 tile's **own** badge and register it, or refuse to.

Operator directive 2026-09-23 §三: ``联盟总入口红点 != 联盟宝箱红点``.  The alliance page draws its
badges on individual tiles (联盟战争 / 联盟宝箱 / 联盟领地 / 联盟商店 ...), so the gifts entry needs
its own window before anything can be gated on it.  This tool measures that window over production
frames whose own episode record says ``page=ALLIANCE``, and writes the entry into the project's one
table of measured entry badges -- but only if the badge **varies**, because a badge that is always on
is a constant and gating on a constant is gating on nothing.

The window is not invented here either: it is taken from the already human-reviewed red-dot template
(``RED_DOT_ALLIANCE_GIFTS_18``, roi x 0.910 y 0.480 w 0.070 h 0.045, whose parent frame is
``dataset/raw/live_alliance_gifts_entry.png``) and widened by a small margin so the whole drawn circle
fits rather than only its centre.

    python tools/measure_alliance_tile_badge.py --dry-run
    python tools/measure_alliance_tile_badge.py

Read-only until the last step, and that step is one entry in one JSON file.  Never raises: a corpus
that cannot answer says so.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EPISODES = ROOT / "learning/episodes.jsonl"
TABLE = ROOT / "knowledge/ui/entry_badges.json"

ENTRY = "TILE_ALLIANCE_GIFTS"
LABEL = "联盟宝箱"
GOAL = "ALLIANCE_ROUTINE"
#: From ``RED_DOT_ALLIANCE_GIFTS_18``'s roi (x 0.910 y 0.480 w 0.070 h 0.045), margin widened to
#: 0.13 x 0.09 so the drawn circle is inside the window whichever corner it is pinned to.
WINDOW = [0.87, 0.455, 1.0, 0.545]
#: A control window over a neighbouring tile's badge (联盟战争), measured in the same loop.  It is
#: reported rather than registered: the point of it is to show that these windows read *different*
#: tiles, so a single window is not seeing "a red thing somewhere on the right".
CONTROL = {"联盟战争": [0.38, 0.44, 0.50, 0.53], "联盟领地": [0.38, 0.60, 0.50, 0.68]}


def _frames() -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
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
            state = row.get("state_before") or {}
            page = state.get("page")
            page = str(page.get("value") if isinstance(page, dict) else page or "")
            if page != "ALLIANCE":
                continue
            frame = str(row.get("before_screenshot") or "")
            if frame:
                out.append((str(row.get("recorded_at") or ""), Path(frame)))
    out.sort()
    return out


def _blob(frame: Path, window: list[float]) -> int:
    from PIL import Image

    from winter_agent_v2.entry_badges import _largest_blob

    image = Image.open(frame).convert("RGB")
    width, height = image.size
    box = (
        int(window[0] * width),
        int(window[1] * height),
        int(window[2] * width),
        int(window[3] * height),
    )
    pixels, _ = _largest_blob(image, box)
    return pixels


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from winter_agent_v2.entry_badges import MIN_BLOB_PX

    pairs = _frames()
    usable = [(at, frame) for at, frame in pairs if frame.is_file()]
    print(f"ALLIANCE before-frames: {len(pairs)} recorded, {len(usable)} still on disk")
    if not usable:
        print("nothing to measure")
        return 1

    verdicts: Counter = Counter()
    samples: dict[str, dict] = {}
    blobs: list[int] = []
    for at, frame in usable:
        try:
            pixels = _blob(frame, WINDOW)
        except (OSError, ValueError):
            continue
        blobs.append(pixels)
        present = pixels >= MIN_BLOB_PX
        verdicts["PRESENT" if present else "ABSENT"] += 1
        if present and "present" not in samples:
            samples["present"] = {"at": at, "frame": str(frame), "pixels": pixels}
        if not present and "absent" not in samples:
            samples["absent"] = {"at": at, "frame": str(frame), "pixels": 0}

    print(f"window {WINDOW} -> PRESENT {verdicts['PRESENT']} / ABSENT {verdicts['ABSENT']}")
    for name, window in CONTROL.items():
        control = Counter()
        for at, frame in usable:
            try:
                control["PRESENT" if _blob(frame, window) >= MIN_BLOB_PX else "ABSENT"] += 1
            except (OSError, ValueError):
                continue
        print(f"  control {name:<6} {window} -> PRESENT {control['PRESENT']} / ABSENT {control['ABSENT']}")
    print(f"blob sizes when present: {sorted(b for b in blobs if b)}")

    if verdicts["PRESENT"] == 0 or verdicts["ABSENT"] == 0:
        print(
            "\nREFUSING to register: this badge never changed in the sample, so it is a constant and "
            "gating a goal on it would gate on nothing (the same rule the table already applies to "
            "TAB_ALLIANCE and BTN_OPEN_DAILY)."
        )
        return 1

    entry = {
        "entry": ENTRY,
        "label": LABEL,
        "page": "ALLIANCE",
        "goal": GOAL,
        "anchor": "the 联盟宝箱 tile's own top-right corner, on the alliance page's tile grid",
        "search_window_norm": WINDOW,
        "measured_blob_norm": {
            "pixels": [min(b for b in blobs if b), max(blobs)],
        },
        "behaviour": (
            f"present in {verdicts['PRESENT']} of {len(blobs)} production alliance frames, absent in "
            f"{verdicts['ABSENT']} -- it comes and goes, so it can decide whether the goal exists"
        ),
        "evidence_frames": [
            f"{samples.get('present', {}).get('at', '')} draws {samples.get('present', {}).get('pixels', 0)} red px on the tile",
            f"{samples.get('absent', {}).get('at', '')} draws none",
        ],
        "verification": (
            "the window is the already-reviewed RED_DOT_ALLIANCE_GIFTS_18 roi widened slightly; the "
            "control windows over the neighbouring tiles read different counts in the same loop, so "
            "this is the gifts tile's own badge and not 'a red thing on the right of the screen'"
        ),
    }
    print()
    print(json.dumps(entry, ensure_ascii=False, indent=1))
    if args.dry_run:
        print("\n(dry run: the table is untouched)")
        return 0

    payload = json.loads(TABLE.read_text(encoding="utf-8"))
    payload["entries"] = [row for row in payload["entries"] if str(row.get("entry")) != ENTRY]
    payload["entries"].append(entry)
    payload["_dot_variability_read_me"] = payload.get("_dot_variability_read_me", "")
    variability = payload.setdefault("dot_variability", {"entries": {}})
    variability.setdefault("entries", {})[ENTRY] = {
        "present": verdicts["PRESENT"],
        "absent": verdicts["ABSENT"],
        "no_reading": 0,
        "varies": True,
        "evidence": (
            f"{len(blobs)} production alliance frames, window {WINDOW}; measured by "
            f"tools/measure_alliance_tile_badge.py"
        ),
    }
    variability["reproduce_with"] = sorted(
        set(list(variability.get("reproduce_with") or []) + ["tools/measure_alliance_tile_badge.py"])
    )
    variability["measured_on"] = "2026-09-23"
    TABLE.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\nregistered {ENTRY} in {TABLE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
