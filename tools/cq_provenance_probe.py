"""Can a MAA/HYBRID claim be traced to an INDEPENDENT artefact?

WB-R19-BACKEND-PROVENANCE-TRUTH exists because the previous round fixed field
COMPLETENESS, and completeness is not truth: a field written by the same code
path that chose the backend can be perfectly populated and perfectly wrong.

The ledger (learning/executor_backend.jsonl) and the episode are both written by
the runtime, so agreement between them proves only that the runtime is
self-consistent.  The independent artefacts available are the MAA framework log
and the screenshots.  This probe asks what those actually contain, before any
audit rule is written on the assumption that they correlate.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAA_LOG = ROOT / "learning/maa_logs/maafw.log"
LEDGER = ROOT / "learning/executor_backend.jsonl"
EPISODES = ROOT / "learning/episodes.jsonl"


def main() -> int:
    # 1. Which ledger rows claim MAA, and what do they claim about recognition?
    rows = [json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()]
    recent = rows[-40:]
    print("ledger rows: %d (inspecting the last %d)" % (len(rows), len(recent)))
    for row in recent:
        print("  %s | %-22s | used=%-4s recog=%-5s captured=%-16s executed=%s"
              % (row["recorded_at"][:19], row["skill_id"], row["used_backend"],
                 row["recognition_backend"], row["capture_backend"], row["executed"]))

    # 2. Does the MAA framework log contain anything per-execution?
    print()
    if not MAA_LOG.exists():
        print("maafw.log MISSING")
        return 0
    text = MAA_LOG.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    print("maafw.log: %d lines, %d bytes" % (len(lines), len(text)))
    for pattern in ("x:", "y:", "click", "Click", "TAP", "tap", "TemplateMatch", "OCR", "pip", "on_error"):
        hits = [line for line in lines if pattern in line]
        print("  %-16s occurrences: %6d   e.g. %s" % (pattern, len(hits), (hits[-1][:110] if hits else "-")))

    # 3. The decisive question: is the live tap coordinate in there?
    print()
    for coordinate in ("666", "954"):
        hits = [line for line in lines if coordinate in line]
        print("  lines containing %-5s : %d" % (coordinate, len(hits)))
        for line in hits[-3:]:
            print("      %s" % line[:150])

    # 4. Any timestamp that would let a row be joined to a log region?
    stamps = re.findall(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}", text)
    print()
    print("timestamps found in maafw.log: %d" % len(stamps))
    if stamps:
        print("  first:", stamps[0], " last:", stamps[-1])
        print("  distinct days:", sorted({s[:10] for s in stamps}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
