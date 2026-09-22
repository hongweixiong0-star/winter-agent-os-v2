"""Report the automatic UI-collection inventory, from the indexes the AUTO writes.

    python tools/ui_collect_report.py                 # candidates + pages + learned transitions
    python tools/ui_collect_report.py --status VERIFIED
    python tools/ui_collect_report.py --detail
    python tools/ui_collect_report.py --pages-only

Read-only: it opens ``knowledge/perception/candidates/INDEX.json``,
``knowledge/perception/pages/INDEX.json`` and ``knowledge/ui/page_transitions.json`` and prints
what is really there.  Nothing here invents a candidate or a transition, and an empty inventory is
reported as empty -- the whole point of the collector is that "how much has the machine actually
learned about the UI" is a question with a measured answer.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import control_experience, page_knowledge, ui_collection  # noqa: E402

COLUMNS = (
    ("candidate_id", 46),
    ("page", 12),
    ("semantic_id", 30),
    ("verification_status", 12),
)


def _row(record: dict) -> str:
    parts = [
        str(record.get("candidate_id") or "")[:44].ljust(46),
        str(record.get("page") or "")[:10].ljust(12),
        str(record.get("semantic_id") or "")[:28].ljust(30),
        str(record.get("verification_status") or "")[:10].ljust(12),
    ]
    return "".join(parts) + str(record.get("ocr_text") or "")[:16]


def _index_rows(path: Path, key: str) -> tuple[dict, list[dict]]:
    if not path.exists():
        return {}, []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, []
    return payload, [row for row in payload.get(key) or () if isinstance(row, dict)]


def report_pages(detail: bool) -> None:
    """The unnamed screens the AUTO kept, and the transitions it learned out of them."""
    index = page_knowledge.PAGE_ROOT / page_knowledge.INDEX_NAME
    payload, rows = _index_rows(index, "pages")
    print("=" * 100)
    print("PAGES the page model could not name")
    print(f"index   : {index.as_posix()}")
    if not index.exists():
        print("no page index yet -- the AUTO has not met an unnamed screen since this shipped")
    else:
        print(f"written : {payload.get('written_at')}")
        print(f"counts  : {json.dumps(payload.get('counts_by_status') or {}, ensure_ascii=False)}")
        print(f"listing : {len(rows)} record(s)")
        print()
        print("page_key".ljust(30) + "status".ljust(12) + "semantics".ljust(34) + "attempts")
        for row in sorted(rows, key=lambda item: str(item.get("last_seen_at") or ""), reverse=True):
            semantics = ",".join(str(item) for item in (row.get("candidate_page_semantics") or ()))
            print(
                str(row.get("page_key") or "")[:28].ljust(30)
                + str(row.get("verification_status") or "")[:10].ljust(12)
                + semantics[:32].ljust(34)
                + f"{row.get('attempt_count', 0)}/{row.get('success_count', 0)}"
            )
            if detail:
                print(json.dumps(row, ensure_ascii=False, indent=1))
    ledger_path = page_knowledge.TRANSITIONS_PATH
    ledger = page_knowledge.TransitionLedger(path=ledger_path)
    print()
    print("TRANSITIONS the AUTO measured (before page -> control -> action -> after page)")
    print(f"ledger  : {ledger_path.as_posix()}")
    counts = ledger.counts()
    print(f"counts  : total={counts['total']} verified={counts['verified']}")
    if not ledger_path.exists():
        print("no ledger yet -- it is written at the end of a run that executed a step")
        return
    print()
    print("before_page".ljust(26) + "control".ljust(38) + "after_page".ljust(18) + "ok  n")
    for row in sorted(ledger._rows.values(), key=lambda item: item.last_at or "", reverse=True)[:60]:
        print(
            str(row.before_page or "")[:24].ljust(26)
            + str(row.control or "")[:36].ljust(38)
            + str(row.after_page or "")[:16].ljust(18)
            + ("yes " if row.verified else "no  ")
            + str(row.count)
        )


def report_l1() -> None:
    """The single-step actions the AUTO has proved, with the conditions they hold under (§八).

    A different shelf from the element candidates and the templates, and it says so: an L1 record
    means one real step reached its expected result with this control -- not a finished skill and
    not a stable template.
    """
    ledger = control_experience.load()
    entries = [entry for entry in ledger.values() if entry.level == control_experience.LEVEL_L1]
    print()
    print("=" * 100)
    print("L1 single-step actions the AUTO registered (one proven step each)")
    print(f"ledger  : {control_experience.STATE_PATH.as_posix()}")
    print(f"controls: {len(ledger)} recorded, {len(entries)} at level L1")
    if not entries:
        print("none yet -- an L1 is only written by a step whose own verifier passed")
        return
    print()
    print("page".ljust(14) + "control".ljust(32) + "goal".ljust(24) + "state".ljust(18) + "basis".ljust(14) + "effect")
    for entry in sorted(entries, key=lambda item: item.last_at or "", reverse=True):
        conditions = entry.conditions or {}
        print(
            str(entry.page or "")[:12].ljust(14)
            + str(entry.control or "")[:30].ljust(32)
            + str(conditions.get(control_experience.CONDITION_GOAL) or "")[:22].ljust(24)
            + str(conditions.get(control_experience.CONDITION_STATE) or "")[:16].ljust(18)
            + str(entry.basis or "")[:12].ljust(14)
            + str(entry.observed_effect or "")
        )
        print(
            "      element: "
            + json.dumps(
                {
                    "text": entry.visual_features.get("text"),
                    "box_norm": entry.visual_features.get("box_norm"),
                    "read_from_frame": str(entry.visual_features.get("read_from_frame") or "")[-52:],
                },
                ensure_ascii=False,
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", default="", help="only this verification status")
    parser.add_argument("--detail", action="store_true", help="one block per record")
    parser.add_argument("--pages-only", action="store_true", help="skip the element candidates")
    args = parser.parse_args()

    report_l1()

    if not args.pages_only:
        root = ui_collection.CANDIDATE_ROOT
        index = root / ui_collection.INDEX_NAME
        if not index.exists():
            print(f"no candidate index yet at {index.as_posix()}")
            print("the collector writes it after the first AUTO step that offers evidence")
        else:
            payload = json.loads(index.read_text(encoding="utf-8"))
            rows = [row for row in payload.get("candidates") or () if isinstance(row, dict)]
            if args.status:
                rows = [row for row in rows if str(row.get("verification_status")) == args.status.upper()]
            rows.sort(key=lambda item: str(item.get("last_seen_at") or ""), reverse=True)

            print(f"index   : {index.as_posix()}")
            print(f"written : {payload.get('written_at')}")
            print(f"counts  : {json.dumps(payload.get('counts_by_status') or {}, ensure_ascii=False)}")
            print(f"listing : {len(rows)} record(s)" + (f" with status {args.status.upper()}" if args.status else ""))
            print()
            print("".join(name.ljust(width) for name, width in COLUMNS) + "ocr_text")
            for row in rows:
                print(_row(row))
            if args.detail:
                for row in rows:
                    print()
                    print("=" * 100)
                    print(json.dumps(row, ensure_ascii=False, indent=1))
        print()

    report_pages(args.detail)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
