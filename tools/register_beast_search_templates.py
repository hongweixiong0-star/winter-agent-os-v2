"""Merge the three reviewed beast-search controls into the production manifest.

Why this exists (measured 2026-09-21):

``BTN_SEARCH_BEAST_TAB``, ``SEARCH_BEAST_LEVEL_5_SELECTED`` and
``BTN_SUBMIT_BEAST_SEARCH`` were cut on 2026-09-06 from a human-reviewed live
capture and written to ``dataset/candidate/beast_search_v2_manifest.json``.
They were never merged, so the production ``SemanticWorldVision`` -- which reads
only ``dataset/candidate/template_manifest.json`` -- could not load them, and
the whole beast-search route stayed unwired (open issue #91).  The candidate
file is the only place they existed, which is also why an earlier sweep for
their names found nothing in the runtime.

What the three are, read off the reviewed frames rather than guessed:

    search_before.png  world map, the magnifier at bottom-left (the control
                       ``SEARCH_RESOURCE``/``BTN_OPEN_RESOURCE_SEARCH`` already taps)
    search_after.png   the panel that opens: a tab strip whose first cells are
                       the monster tabs, a level slider, a 搜索 button
    beast_tab.png      the same panel with 冰原巨兽 selected, level 5, 搜索 drawn

Verified on 2026-09-21 with ``tools/verify_template.py --manifest ...`` against
those frames, and the negative control is part of the result:

    BTN_SEARCH_BEAST_TAB            beast_tab d=6,  overlay on the 冰原巨兽 tab
    BTN_SUBMIT_BEAST_SEARCH         beast_tab d=4,  search_after NO MATCH
    SEARCH_BEAST_LEVEL_5_SELECTED   beast_tab d=0,  search_after NO MATCH

Both NO MATCHes are correct, not defects: on ``search_after`` the level is 8 and
no beast tab is selected, so neither control is drawn.  That is what makes these
discriminators of a *state* rather than generic buttons -- ``SEARCH_BEAST_LEVEL_5_SELECTED``
asserts "the level is currently 5", it does not set it.

Paths are stored relative to the project root.  The candidate manifest stored
``E:/...`` absolute paths, which is a second reason the merge was needed: a
relative path is what the rest of the manifest uses and what survives a move.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "dataset/candidate/template_manifest.json"
CANDIDATE = ROOT / "dataset/candidate/beast_search_v2_manifest.json"

# The candidate records carry the ROIs measured on the reviewed frames; this
# script moves the three records across unchanged apart from the path form.
MIGRATED = ("BTN_SEARCH_BEAST_TAB", "SEARCH_BEAST_LEVEL_5_SELECTED", "BTN_SUBMIT_BEAST_SEARCH")


def main() -> int:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records = payload["records"]
    candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))["records"]

    existing = {(str(r.get("semantic")), str(r.get("template_path"))) for r in records}
    known_semantics = {str(r.get("semantic")) for r in records}

    added = 0
    for row in candidate:
        semantic = str(row["semantic"])
        if semantic not in MIGRATED:
            continue
        if semantic in known_semantics:
            # Idempotent: a re-run must not append a second copy, which would
            # make ``find`` compare two files that are supposed to be one.
            print(f"{semantic}: already in the manifest, left alone")
            continue
        source = Path(row["template_path"])
        if not source.is_file():
            raise SystemExit(f"missing reviewed template: {source}")
        try:
            relative = source.relative_to(ROOT).as_posix()
        except ValueError:
            raise SystemExit(f"template is outside the project root: {source}")
        record = {
            "semantic": semantic,
            "template_id": row.get("template_id"),
            "template_path": relative,
            "roi_norm": row["roi_norm"],
            "source": row.get("parent_screenshot", ""),
            "parent_sha256": row.get("parent_sha256"),
            "provenance": "LIVE_CLIENT",
            "reviewed_from": row.get("source", "REPLAY_HUMAN_REVIEWED_SCREENSHOT"),
            "note": (
                "beast-search control cut from a human-reviewed live capture; merged from "
                "dataset/candidate/beast_search_v2_manifest.json on 2026-09-21 so the "
                "production vision can load it (issue #91)"
            ),
        }
        record = {key: value for key, value in record.items() if value is not None}
        if (semantic, record["template_path"]) not in existing:
            records.append(record)
            added += 1
        known_semantics.add(semantic)

    payload["count"] = len(records)
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    # The manifest's own format, matched rather than chosen: one-space indent and
    # sorted keys.  ``indent=2, sort_keys=False`` rewrote all 404 existing records
    # (14590 diff lines for a three-record change), which buries the real edit and
    # makes the file impossible to review.  Measured 2026-09-21 after the first
    # version of this script did exactly that.
    MANIFEST.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )
    print(f"manifest records: {len(records)} (+{added})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
