# -*- coding: utf-8 -*-
"""QUALITY_GAP scanner -- finds "success" that did not change anything.

Round brief 2026-09-27 §十一: a node existing is not the same as the capability
being reliable.  Four suspicion patterns, all from ``learning/episodes.jsonl``:

    A. result SUCCESS but observed_change is NO_OP / UNKNOWN
       (the action "worked" and the screen stayed the same)
    B. result SUCCESS with verifier_ok not true
       (MAA executed, verifier weak or absent)
    C. SUCCESS whose recognition came from OCR and whose recognised text is a
       long sentence (high-score hit on prose, not a control token)
    D. TEMPLATE-recognition SUCCESS on a page the step did not claim to be on
       (page semantics not recorded -> unverifiable hit)

Each finding is a QUALITY_GAP candidate: it goes to AutoRepair or verifier
strengthening, never to silent praise.  Read-only: this tool reports, it does
not edit skills or routing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EPISODES = ROOT / "learning" / "episodes.jsonl"

SUSPECT_CHANGES = {"NO_OP", "UNKNOWN", ""}
LONG_TEXT_RE = __import__("re").compile(r"[\u4e00-\u9fff]{6,}|[A-Za-z ]{25,}")

#: Only recent episodes count.  Older ones predate observed_change recording
#: entirely, so their "no change" is missing instrumentation, not fake success.
RECENT_DAYS = 7


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)
    findings: list[dict] = []
    counts = {"A_no_change": 0, "B_weak_verifier": 0, "C_long_ocr_text": 0, "D_template_no_page": 0}
    if not EPISODES.exists():
        print(json.dumps({"error": "no episodes ledger"}, ensure_ascii=False))
        return
    with EPISODES.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("result") != "SUCCESS":
                continue
            stamp = str(record.get("recorded_at") or "").replace("Z", "+00:00")
            try:
                when = datetime.fromisoformat(stamp)
            except ValueError:
                continue
            if when < cutoff:
                continue
            skill = record.get("skill")
            at = record.get("recorded_at")
            change = str(record.get("observed_change") or "").upper()
            # A. nothing changed
            if change in SUSPECT_CHANGES:
                counts["A_no_change"] += 1
                findings.append({"pattern": "A_no_change", "skill": skill, "at": at,
                                 "observed_change": change or None})
            # B. weak verifier
            if record.get("verifier_ok") is not True:
                counts["B_weak_verifier"] += 1
                findings.append({"pattern": "B_weak_verifier", "skill": skill, "at": at,
                                 "verifier_ok": record.get("verifier_ok"),
                                 "observed_change": change or None})
            # C. long OCR text as the recognised control
            text = str(record.get("control") or record.get("expected_result") or "")
            if record.get("recognition_backend") == "OCR" and LONG_TEXT_RE.search(text):
                counts["C_long_ocr_text"] += 1
                findings.append({"pattern": "C_long_ocr_text", "skill": skill, "at": at,
                                 "text": text[:60]})
            # D. template hit with no page semantics recorded
            if record.get("recognition_backend") == "TEMPLATE" and not record.get("capability"):
                counts["D_template_no_page"] += 1
                findings.append({"pattern": "D_template_no_page", "skill": skill, "at": at})
    # One finding per (pattern, skill) -- a skill that does this repeatedly is
    # ONE gap with count, not a wall of noise.
    dedup: dict[tuple, dict] = {}
    for finding in findings:
        key = (finding["pattern"], finding["skill"])
        entry = dedup.setdefault(key, {**finding, "count": 0, "last_at": finding["at"]})
        entry["count"] += 1
        if finding["at"] and finding["at"] > entry["last_at"]:
            entry["last_at"] = finding["at"]
    report = {
        "scanned": "learning/episodes.jsonl",
        "pattern_counts": counts,
        "quality_gaps": sorted(dedup.values(), key=lambda g: (-g["count"], g["pattern"])),
        "note": "read-only scan; route each gap to AutoRepair or verifier strengthening",
    }
    out = ROOT / "out" / "quality_gap_scan.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({**report, "written": str(out.relative_to(ROOT))}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
