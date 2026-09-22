"""Why does ``TRY_ORDINARY_CONTROL`` fail?  Ask the readers on the frames it failed on.

Measured 2026-09-22/23: 69 attempts, 38 success / 31 failure, every failure
``SEMANTIC_TARGET_NOT_VERIFIED`` -- which is the *resolver* answering "this frame names no control",
not a tap that landed wrong.  So the question is a reader question, and it can be answered on the
stored frames without the device:

    the 快捷面板 handle      ``ocr.find_quick_panel_handle(frame, panel_open=False)``
    the printed whitelist    ``ocr.find_printed_words`` for every ``ui_collection.PLAIN_ACTION_WORDS``
    the page                 the production vision, once per frame

Grouped by what the episode itself recorded (result, and whether the panel was open), so the
comparison is like-for-like: the SUCCESS frames are the control group -- if the handle is found there
and not here, the reader is the difference; if it is found in both, the difference is in the gate
above the reader.

Read-only.  Writes one JSON report beside the tool's stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EPISODES = ROOT / "learning/episodes.jsonl"


def _episodes(skill: str) -> list[dict]:
    rows, skipped = [], 0
    with EPISODES.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1  # the runtime appends to this file while it is read
                continue
            if str(row.get("skill")) == skill:
                rows.append(row)
    if skipped:
        print(f"note: {skipped} malformed line(s) skipped (a live runtime appends to this file)")
    rows.sort(key=lambda row: str(row.get("recorded_at")))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill", default="TRY_ORDINARY_CONTROL")
    parser.add_argument("--limit", type=int, default=0, help="0 = every episode of that skill")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "dataset/truth_audit/ordinary_control_failures_20260923/report.json")
    args = parser.parse_args()

    from winter_agent_v2 import ui_collection
    from winter_agent_v2.ocr import (
        OCRService,
        RapidOCRBackend,
        ResilientOCRBackend,
        find_printed_words,
        find_quick_panel_handle,
    )

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))
    words = tuple(ui_collection.PLAIN_ACTION_WORDS)

    rows = _episodes(args.skill)
    if args.limit:
        rows = rows[-args.limit:]
    print(f"episodes of {args.skill}: {len(rows)}")
    print(f"whitelist under test ({len(words)}): {words}")
    print()

    report = {"skill": args.skill, "whitelist": list(words), "frames": []}
    tally: Counter[tuple] = Counter()
    printed_tally: dict[tuple, Counter] = defaultdict(Counter)

    for row in rows:
        path = Path(str(row.get("before_screenshot") or ""))
        if not path.exists():
            tally[("MISSING_FRAME", str(row.get("result")))] += 1
            continue
        state = row.get("state_before") or {}
        panel = state.get("quick_panel") or {}
        result = str(row.get("result"))
        handle = find_quick_panel_handle(path, panel_open=False)
        printed = {
            word: bool(find_printed_words(path, (word,), ocr)) for word in words
        }
        hit_words = sorted(word for word, found in printed.items() if found)
        # The page is taken from the record rather than re-classified: the record is production
        # evidence of the same family, the re-classification would cost seconds per frame and could
        # only disagree about the page -- not about the handle, which is what is under test.
        page = state.get("page")
        page = str(page.get("value") if isinstance(page, dict) else page or "")
        entry = {
            "recorded_at": str(row.get("recorded_at")),
            "result": result,
            "goal": str(row.get("goal_id")),
            "frame": str(path),
            "panel_open_at_record": panel.get("open") if isinstance(panel, dict) else None,
            "page_at_record": page,
            "handle_found_now": handle is not None,
            "handle_state": str((handle or {}).get("state") or ""),
            "handle_point_norm": (handle or {}).get("point_norm"),
            "printed_whitelist_words": hit_words,
        }
        report["frames"].append(entry)
        tally[(result, entry["panel_open_at_record"], bool(handle))] += 1
        printed_tally[(result, bool(handle))].update(hit_words)

    print("result / panel_open_at_record / handle_found_now :")
    for key, count in sorted(tally.items(), key=lambda item: -item[1]):
        print(f"  {count:>3}  {key}")
    print()
    print("whitelist words actually printed, by (result, handle_found):")
    for key, counter in sorted(printed_tally.items()):
        print(f"  {key}: {dict(counter.most_common(8))}")
    print()
    for entry in report["frames"]:
        print(f"  {entry['recorded_at'][11:19]} {entry['result']:<7} panel={entry['panel_open_at_record']} "
              f"handle={'YES' if entry['handle_found_now'] else 'no ':>3} "
              f"page={entry['page_at_record']:<9} words={entry['printed_whitelist_words']}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
