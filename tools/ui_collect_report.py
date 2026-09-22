"""Report the automatic UI-collection inventory, from the index the AUTO writes.

    python tools/ui_collect_report.py                 # counts + every candidate, newest first
    python tools/ui_collect_report.py --status VERIFIED
    python tools/ui_collect_report.py --detail

Read-only: it opens ``knowledge/perception/candidates/INDEX.json`` and prints what is really
there.  Nothing here invents a candidate, and an empty inventory is reported as empty -- the
whole point of the collector is that "how many elements have we actually collected" is a
question with a measured answer.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import ui_collection  # noqa: E402

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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", default="", help="only this verification status")
    parser.add_argument("--detail", action="store_true", help="one block per candidate")
    args = parser.parse_args()

    root = ui_collection.CANDIDATE_ROOT
    index = root / ui_collection.INDEX_NAME
    if not index.exists():
        print(f"no candidate index yet at {index.as_posix()}")
        print("the collector writes it after the first AUTO step that offers evidence")
        return 0
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
