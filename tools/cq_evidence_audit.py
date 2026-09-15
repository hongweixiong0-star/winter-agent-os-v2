"""WB-EXECUTOR-EVIDENCE-AUDIT: which write paths leave backend fields empty?

The work order is explicit that historical empty fields must be preserved and only
the current write path may be fixed.  So the first job is to separate the two:
how many empties are old, how many are from today, and which skill/backend
combinations produce them.

Read-only.
"""
from __future__ import annotations

import json
import pathlib
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIELDS = ("capture_backend", "recognition_backend", "action_backend", "executor_backend")


def main() -> None:
    rows = [
        json.loads(ln)
        for ln in (ROOT / "learning/episodes.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    print("total episodes:", len(rows))

    def empty(r: dict, f: str) -> bool:
        return not r.get(f)

    print()
    print("=== empties by date (capture_backend as the sentinel) ===")
    per_day = defaultdict(lambda: [0, 0])
    for r in rows:
        day = (r.get("recorded_at") or "UNDATED")[:10]
        per_day[day][0] += 1
        if empty(r, "capture_backend"):
            per_day[day][1] += 1
    for day in sorted(per_day):
        total, empt = per_day[day]
        print("  %-12s total=%-5d empty_capture=%-5d (%d%%)" % (day, total, empt, round(100 * empt / total)))

    print()
    print("=== today's episodes: completeness of all four fields ===")
    today = [r for r in rows if (r.get("recorded_at") or "").startswith("2026-09-15")]
    complete = sum(1 for r in today if all(r.get(f) for f in FIELDS))
    print("  today total: %d | all four fields present: %d (%.0f%%)" % (len(today), complete, 100 * complete / max(len(today), 1)))

    print()
    print("=== today, grouped by which fields are missing ===")
    shape = Counter()
    for r in today:
        missing = tuple(f for f in FIELDS if empty(r, f))
        shape[missing] += 1
    for missing, n in shape.most_common():
        print("  missing=%-40s x%d" % (",".join(m.split("_")[0] for m in missing) or "(none)", n))

    print()
    print("=== the ADB-vs-MAA asymmetry that stands out ===")
    for label, pred in (
        ("action_backend == MAA", lambda r: r.get("action_backend") == "MAA"),
        ("action_backend == ADB", lambda r: r.get("action_backend") == "ADB"),
    ):
        sub = [r for r in today if pred(r)]
        if not sub:
            print("  %-24s no episodes today" % label)
            continue
        c = Counter(r.get("recognition_backend") or "(EMPTY)" for r in sub)
        print("  %-24s n=%-4d recognition_backend=%s" % (label, len(sub), dict(c)))

    print()
    print("=== today: rows whose recognition_backend is empty, with their action backend ===")
    rows_bad = [r for r in today if empty(r, "recognition_backend")]
    print("  count:", len(rows_bad))
    c = Counter((r.get("skill"), r.get("action_backend") or "(EMPTY)", r.get("executor_backend") or "(EMPTY)") for r in rows_bad)
    for k, n in c.most_common(20):
        print("   skill=%-24s action=%-6s executor=%-8s x%d" % (k[0], k[1], k[2], n))

    print()
    print("=== sample of today's complete rows (the shape to match) ===")
    for r in [r for r in today if all(r.get(f) for f in FIELDS)][:6]:
        print(
            "  %s | %-22s | cap=%-16s recog=%-5s action=%-5s exec=%-8s"
            % (
                (r.get("recorded_at") or "")[:19],
                r.get("skill"),
                r.get("capture_backend"),
                r.get("recognition_backend"),
                r.get("action_backend"),
                r.get("executor_backend"),
            )
        )


if __name__ == "__main__":
    main()
