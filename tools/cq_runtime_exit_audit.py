"""WB-RUNTIME-EXIT-ROOTCAUSE: stratify unexpected_worker_exits=15 by evidence.

The acceptance is explicit that history must not be rewritten and no crash may be
manufactured, so this only reads: the snapshot, the crash reports, the latest log,
the counter's own code, and whether anything recent actually crashed.

Read-only.
"""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> None:
    print("=== runtime snapshot (the counter's only home) ===")
    snap_path = ROOT / "learning/runtime_snapshot.json"
    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    for k in (
        "updated_at",
        "unexpected_worker_exits",
        "watchdog_restart_count",
        "last_fatal_error",
        "agent_state",
        "stop_reason",
        "runtime_thread_alive",
        "scheduler_loop_alive",
    ):
        print("  %-26s %s" % (k, json.dumps(snap.get(k), ensure_ascii=False)))
    print("  all snapshot keys:", sorted(snap.keys()))

    print()
    print("=== crash reports ===")
    crashes = ROOT / "learning/control_panel/crashes"
    if crashes.exists():
        items = sorted(crashes.rglob("*"))
        files = [p for p in items if p.is_file()]
        print("  files:", len(files))
        for p in files[-20:]:
            st = datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
            print("    %-52s %8d  mtime=%s" % (p.name, p.stat().st_size, st.isoformat(timespec="seconds")))
    else:
        print("  directory MISSING:", crashes)

    print()
    print("=== control panel logs ===")
    cp = ROOT / "learning/control_panel"
    if cp.exists():
        for p in sorted(cp.rglob("*")):
            if p.is_file():
                st = datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
                print("    %-46s %9d  mtime=%s" % (str(p.relative_to(cp)), p.stat().st_size, st.isoformat(timespec="seconds")))
    else:
        print("  MISSING")

    print()
    print("=== who increments unexpected_worker_exits? ===")
    for p in sorted((ROOT / "winter_agent_v2").glob("*.py")):
        txt = p.read_text(encoding="utf-8", errors="replace")
        if "unexpected_worker_exits" in txt:
            for i, ln in enumerate(txt.splitlines(), 1):
                if "unexpected_worker_exits" in ln:
                    print("  %-24s %5d  %s" % (p.name, i, ln.strip()[:130]))
    for p in sorted((ROOT / "tools").glob("*.py")):
        txt = p.read_text(encoding="utf-8", errors="replace")
        if "unexpected_worker_exits" in txt:
            for i, ln in enumerate(txt.splitlines(), 1):
                if "unexpected_worker_exits" in ln:
                    print("  tools/%-18s %5d  %s" % (p.name, i, ln.strip()[:130]))

    print()
    print("=== any worker restart evidence in the last 6 hours? ===")
    cutoff = datetime.now(timezone.utc).timestamp() - 6 * 3600
    recent = []
    for pattern in ("learning/**/*.json", "evidence/**/*.json", "learning/**/*.log"):
        for p in ROOT.glob(pattern):
            try:
                if p.stat().st_mtime >= cutoff:
                    recent.append(p)
            except OSError:
                continue
    print("  files touched in the last 6h:", len(recent))
    for p in sorted(recent, key=lambda x: x.stat().st_mtime)[-12:]:
        st = datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
        print("    %-64s %s" % (str(p.relative_to(ROOT)), st.isoformat(timespec="seconds")))

    print()
    print("=== episodes whose result is a crash-ish failure ===")
    rows = [
        json.loads(ln)
        for ln in (ROOT / "learning/episodes.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    from collections import Counter

    c = Counter(
        r.get("failure_type")
        for r in rows
        if str(r.get("failure_type") or "").lower().find("crash") >= 0
        or str(r.get("failure_type") or "").startswith(("FATAL_", "WORKER_"))
    )
    print("  crash/fatal-ish failure types:", dict(c) or "none")


if __name__ == "__main__":
    main()
