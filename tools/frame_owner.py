"""Which episode does this frame belong to, and what did that record say?

Written because three rounds in a row produced a wrong claim from the same mistake: keying frames
to episodes by **timestamp** instead of by path.

    * the previous round called 17:51:16 / 17:51:35 "the tightest pair, same camera".  The frames it
      showed were each one step earlier than the labels it put on them.
    * the round before that read a highlight into the frame after a tick tap; the frame was right,
      the pairing was not.
    * this round's issue #93 was filed on "the reader calls a world-map frame HOME".  The frame
      ``step_005_before_20260922T175116240696.png`` is owned by exactly one episode --
      ``17:51:35 OPEN_HOME`` -- and that record says ``page=MAP``.  The reader was right; the
      timestamp join was wrong.  #93 is withdrawn.

A frame is written by one step and referenced by the record of that step as either
``before_screenshot`` or ``after_screenshot``.  The page and the panel state that belong to it are
the ones under the matching ``state_before`` / ``state_after`` -- never the ones from an episode
that merely happened to run at a similar time, and never the other side's.

Usage::

    python tools/frame_owner.py <frame path, or a unique part of it> [--ring]

``--ring`` additionally reports whether the 快捷面板's green tick or the camp's highlight ring
matches that frame, which is the pair of readings most of these investigations turn on.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def episodes() -> list[dict]:
    path = ROOT / "learning/episodes.jsonl"
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith("{"):
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def owners(rows: list[dict], needle: str) -> list[tuple]:
    found = []
    for row in rows:
        for side, key in (("before_screenshot", "state_before"), ("after_screenshot", "state_after")):
            recorded = str(row.get(side) or "")
            if needle and needle not in recorded:
                continue
            state = row.get(key) or {}
            panel = state.get("quick_panel") or {}
            found.append(
                (
                    str(row.get("recorded_at") or "")[11:19],
                    side.split("_")[0],
                    str(row.get("skill") or ""),
                    str(state.get("page") or ""),
                    bool(panel.get("open")),
                    str(row.get("result") or ""),
                    Path(recorded).name,
                )
            )
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve a frame to the record that owns it.")
    parser.add_argument("frame", help="full path, or any unique part of it")
    parser.add_argument("--ring", action="store_true", help="also report the frame's ring / tick reading")
    args = parser.parse_args(argv)

    rows = episodes()
    hits = owners(rows, args.frame)
    print(f"episodes referencing a frame matching {args.frame!r}: {len(hits)}")
    for when, side, skill, page, panel, result, name in sorted(hits):
        print(f"  {when}  {side:6} {skill[:30]:30} page={page:8} panel_open={panel!s:5} {result[:7]:7} {name}")
    if not hits:
        print("  none -- the frame is an orphan: no record owns it, so no recorded page may be quoted for it.")
    if hits and not args.ring:
        return 0
    if not args.ring:
        return 0

    from winter_agent_v2.vision import SemanticWorldVision  # imported late: only needed for --ring

    frame = Path(args.frame)
    if not frame.exists():
        # An orphan frame has no record to point at it, so the name is resolved on disk instead --
        # the recordings live under dataset/raw and are named after the step that wrote them.
        # A frame is usually quoted by part of its name, so the match is on the substring: the
        # files carry the step's own prefix (``20260923_015029_train_``) before the ``step_00N_``
        # part, and asking for the exact leaf name would silently find nothing.
        needle = Path(args.frame).name
        found = next(iter(sorted((ROOT / "dataset").rglob(f"*{needle}*"))), None)
        if found is None:
            found = next((Path(str(r.get(side) or "")) for r in rows
                          for side in ("before_screenshot", "after_screenshot")
                          if args.frame in str(r.get(side) or "")), None)
        frame = found or frame
    if not frame.exists():
        print(f"  (no such frame on disk: {frame})")
        return 1
    vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    ring = vision.semantic.find(frame, "TARGET_INFANTRY_CAMP_HIGHLIGHTED")
    print(f"  frame {frame.name}")
    print(f"    highlight ring : {'present, d=%d' % ring[1] if ring else 'not present'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
