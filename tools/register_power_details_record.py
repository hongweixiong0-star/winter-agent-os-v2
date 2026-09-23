"""Add BTN_OPEN_POWER_DETAILS to the semantic dictionary, with its measured evidence.

Written as a script rather than by hand so the insertion is reproducible and the file keeps the
indent the rest of the dictionary uses (``indent=1``; a different indent rewrites all 112 records
and hides the real change -- see tools/merge_template_manifest.py for what that cost once).

Usage:
    python tools/register_power_details_record.py --dry-run
    python tools/register_power_details_record.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DICTIONARY = ROOT / "knowledge/ui/semantic_dictionary.json"

RECORD = {
    "id": "BTN_OPEN_POWER_DETAILS",
    "type": "BUTTON",
    "cn": "实力详情",
    "en_aliases": [],
    "ocr": ["实力详情"],
    #: The client draws the ≡ icon on the same pill as the name, and OCR returns them as one token.
    "ocr_merged": True,
    "icon_semantic": "action.power_details",
    "pages": ["POPUP"],
    "target_state": "POWER_DETAILS_OPEN",
    "actions": ["TAP"],
    "related_goals": ["KEEP_TRAINING_PRODUCTIVE", "KEEP_RESEARCH_PRODUCTIVE"],
    "risk": "LOW",
    "status": "VERIFIED",
    "verification": {
        "printed_name": (
            "MEASURED 2026-09-23 on the 14 live POWER_OVERVIEW frames where the route named this "
            "control: OCR returns one token 三实力详情 at confidence 0.901 whose centre (360,728) = "
            "(0.501,0.568) is 3 px from the button's drawn centre (357.5,727.5).  The name is inside "
            "the token rather than the whole of it because the client draws the ≡ icon on the same "
            "pill -- which is what ocr_merged declares."
        ),
        "why_no_template_can_hold_it": (
            "the panel's vertical offset varies and the button moves with it: the two reviewed phash "
            "registrations sit at y 636..685 and y 762..832, while the button is drawn at y ~692..765 "
            "-- in the gap between them (distance 36 and 33 against a threshold of 8).  The template "
            "tier therefore answers nothing on all 14 frames, and the remembered-coordinate ledger "
            "has no entry for this screen either."
        ),
    },
    "notes": (
        "Only ever asked on the 加成总览 popup: both brain branches that emit OPEN_POWER_DETAILS are "
        "gated on world.popup == POWER_OVERVIEW, so POPUP is as narrow as pages can express here.  "
        "Resolved by _client_printed_control, which runs before the remembered ledger."
    ),
}

SCHEMA_NOTE_ADDITION = (
    " Additional field: ocr_merged marks a control whose printed name the client draws together "
    "with its icon, so that OCR returns one token containing the name instead of equalling it "
    "(measured: the 实力详情 button is read as 三实力详情).  It is declared per record and only that "
    "record's reading is relaxed; find_printed_words keeps its exact-match default, which exists "
    "because a containment match once answered with a different control's position (城镇 inside "
    "我的城镇)."
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    payload = json.loads(DICTIONARY.read_text(encoding="utf-8"))
    records = list(payload.get("records") or ())
    existing = next((row for row in records if row.get("id") == RECORD["id"]), None)
    if existing is not None:
        print(f"already present: {RECORD['id']}")
        return 0

    print(f"about to add {RECORD['id']} to {len(records)} records")
    print(json.dumps(RECORD, ensure_ascii=False, indent=1)[:700])
    if args.dry_run:
        print("dry run: nothing written")
        return 0

    records.append(RECORD)
    payload["records"] = records
    note = str(payload.get("schema_note") or "")
    if "ocr_merged" not in note:
        payload["schema_note"] = note + SCHEMA_NOTE_ADDITION
    DICTIONARY.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {DICTIONARY} ({len(records)} records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
