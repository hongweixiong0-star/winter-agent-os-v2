"""Commander-queue reconnaissance: current truth for the queue executor.

Read-only. Prints git state, new episodes since HEAD, backend-field coverage,
and the answers the commander queue needs before any task starts.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
CWD = str(ROOT)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", CWD, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout


def main() -> None:
    print("=== GIT ===")
    print("HEAD:", git("rev-parse", "--short", "HEAD").strip())
    dirty = [ln for ln in git("status", "--porcelain").splitlines() if ln.strip()]
    print("dirty files:", len(dirty))
    for ln in dirty[:40]:
        print("   ", ln)
    print()
    print("recent log:")
    for ln in git("log", "--oneline", "-8").splitlines():
        print("   ", ln)

    print()
    print("=== EPISODES ===")
    committed_raw = git("show", "HEAD:learning/episodes.jsonl")
    committed = [ln for ln in committed_raw.splitlines() if ln.strip()]
    current = [ln for ln in (ROOT / "learning/episodes.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    print("committed:", len(committed), "working:", len(current), "delta:", len(current) - len(committed))
    for ln in current[len(committed):][:25]:
        r = json.loads(ln)
        print(
            "  + %s | %-26s | %-8s | cb=%-16s rb=%-6s ab=%-6s eb=%-8s | fail=%s"
            % (
                (r.get("recorded_at") or "")[:19],
                r.get("skill"),
                str(r.get("result")).upper(),
                r.get("capture_backend") or "-",
                r.get("recognition_backend") or "-",
                r.get("action_backend") or "-",
                r.get("executor_backend") or "-",
                r.get("failure_type") or "-",
            )
        )

    rows = [json.loads(ln) for ln in current]
    print()
    print("=== BACKEND FIELD COVERAGE (all %d episodes) ===" % len(rows))
    for field in ("capture_backend", "recognition_backend", "action_backend", "executor_backend"):
        c = Counter(r.get(field) or "(EMPTY)" for r in rows)
        print("  %-20s %s" % (field, dict(c.most_common(8))))

    print()
    print("=== RECENT FAILURES (last 15) ===")
    fails = [r for r in rows if str(r.get("result")).upper() == "FAILURE"]
    for r in fails[-15:]:
        print(
            "   %s | %-26s | %-38s | stop=%s"
            % ((r.get("recorded_at") or "")[:19], r.get("skill"), r.get("failure_type"), r.get("stop_reason"))
        )

    print()
    print("=== STOP REASONS (last 200) ===")
    for k, v in Counter(r.get("stop_reason") or "(none)" for r in rows[-200:]).most_common(15):
        print("   %-46s %d" % (k, v))

    print()
    print("=== SEMANTIC_TARGET_NOT_VERIFIED (recent 12) ===")
    sem = [r for r in rows if r.get("failure_type") == "SEMANTIC_TARGET_NOT_VERIFIED"]
    print("total:", len(sem))
    for r in sem[-12:]:
        b = r.get("state_before") or {}
        print(
            "   %s | %-24s | target=%-22s | page=%s | ep=%s"
            % (
                (r.get("recorded_at") or "")[:19],
                r.get("skill"),
                (r.get("action") or {}).get("target"),
                b.get("page"),
                r.get("episode_id"),
            )
        )

    print()
    print("=== RUNTIME SNAPSHOT ===")
    snap = ROOT / "learning/runtime_snapshot.json"
    if snap.exists():
        d = json.loads(snap.read_text(encoding="utf-8"))
        for k in (
            "updated_at",
            "unexpected_worker_exits",
            "watchdog_restart_count",
            "last_fatal_error",
            "agent_state",
            "stop_reason",
        ):
            print("   %-26s %s" % (k, json.dumps(d.get(k), ensure_ascii=False)))
    else:
        print("   MISSING")

    print()
    print("=== COMMANDER DIR ===")
    cmd = ROOT / ".workbuddy-ai/commander"
    for p in sorted(cmd.rglob("*")):
        if p.is_file():
            print("   %-70s %d" % (str(p.relative_to(cmd)), p.stat().st_size))


if __name__ == "__main__":
    main()
