"""Keep the public mirror honest: one place to ask "is GitHub up to date?" and to push.

Why this exists (2026-09-16).  The repository became public
(https://github.com/hongweixiong0-star/winter-agent-os-v2) and pushing is now part of
the development loop, so the loop needs three things that a bare `git push` does not
give:

1. **A pre-push gate for secrets.**  The tree is PUBLIC, so a bad push is a
   disclosure, not an untidy commit.  ``push`` runs ``tools/scan_public_repo.py`` first
   and refuses on any credential-shaped hit (``--skip-scan`` overrides, and says so).
2. **A record of the last push** so a later session can see at a glance whether the
   local tree is ahead -- ``local_head``, ``remote_head``, ``git_dirty``,
   ``unpushed_commits``, ``last_push_at``, ``last_push_status`` live in
   ``learning/git_sync_state.json`` and are rendered into the handoff by
   ``tools/update_workbuddy_handoff.py``.
3. **A classification of the dirty tree** (§六 of the sync rules): every dirty path is
   reported as KEEP / TEMP / DISCARD-ish by rule, so a session never silently leaves a
   pile of unknown files behind.  The rules are deliberately conservative -- "KEEP" is
   the default and nothing is ever deleted here.

What it will not do, by design:

* no ``push --force``, no history rewrite, no ``reset --hard`` -- if the remote has
  moved, ``push`` stops and says what it saw, because a conflict is a decision and the
  tool is not allowed to make it;
* no network access outside ``fetch`` / ``push`` themselves, and both are given a
  deadline so a credential prompt cannot hang a session (§十一).

Usage
-----
    python tools/git_sync.py status
    python tools/git_sync.py status --json out_git_sync.json
    python tools/git_sync.py push
    python tools/git_sync.py push --skip-scan
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "learning" / "git_sync_state.json"
SCANNER = ROOT / "tools" / "scan_public_repo.py"

# ' M path' (worktree modified) and 'M  path' (staged) both have to parse.
STATUS_ROW = re.compile(r"^[ MADRCU?!]{1,2}\s+(.*)$")

GIT_TIMEOUT = 120
REMOTE = "origin"
BRANCH = "main"

# Dirty-tree classification (never deletes anything -- it only labels).
TEMP_PATTERNS = ("out_", "out_crop_", "__pycache__", ".pytest_cache")
KEEP_PREFIXES = ("winter_agent_v2/", "tools/", "tests/", "dataset/candidate/",
                 "dataset/truth_audit/", "knowledge/", "docs/", "config/",
                 ".workbuddy-ai/", ".workbuddy/memory/", "learning/episodes.jsonl",
                 "learning/git_sync_state.json", "evidence/", "START_HERE.md")
DISCARD_HINTS = (".tmp", ".log~", ".orig", ".rej", ".bak")


def git(*args: str) -> tuple[int, str, str]:
    """Run git.  Read-only subcommands get ``--no-optional-locks``.

    git takes ``.git/index.lock`` for subcommands that refresh the index, even
    when they only report -- and a process killed while holding it leaves the lock
    behind, which then blocks every later ``git add`` while ``git log`` and
    ``git status`` keep working.  That happened twice on 2026-09-21/22: a lock sat
    for forty minutes with no git process alive.  The flag is git's own answer for
    read-only callers and does not change what is read.  Naming every read
    subcommand explicitly is the point: a silent default would put us back here.
    """
    readonly = {"status", "rev-parse", "log", "diff", "show", "rev-list", "ls-files",
                "remote", "branch", "worktree", "cat-file", "describe"}
    extra = ("--no-optional-locks",) if args and args[0] in readonly else ()
    try:
        proc = subprocess.run(
            ["git", *extra, *args], cwd=ROOT, capture_output=True, text=True,
            timeout=GIT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {GIT_TIMEOUT}s"
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def load_state() -> dict:
    if STATE.is_file():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def classify_dirty(paths: list[str]) -> dict[str, list[str]]:
    """Label each ``git status --porcelain`` row KEEP / TEMP / DISCARD? / UNKNOWN.

    The path is taken with a regex rather than a fixed slice because ``git()`` strips
    the output it returns, and stripping removes the *leading space* of the first row
    (' M .gitignore' becomes 'M .gitignore'), so a blind ``row[3:]`` ate the first
    character of the first path.  Measured 2026-09-16: that reported ``gitignore``.
    """
    buckets: dict[str, list[str]] = {"KEEP": [], "TEMP": [], "DISCARD?": [], "UNKNOWN": []}
    for row in paths:
        match = STATUS_ROW.match(row)
        path = match.group(1).strip() if match else row.strip()
        if len(path) > 1 and path[0] == path[-1] == '"':
            path = path[1:-1]
        if any(token in path for token in TEMP_PATTERNS) or path.endswith(DISCARD_HINTS):
            buckets["TEMP" if not path.endswith(DISCARD_HINTS) else "DISCARD?"].append(path)
        elif path.startswith(KEEP_PREFIXES) or path == ".gitignore":
            buckets["KEEP"].append(path)
        else:
            buckets["UNKNOWN"].append(path)
    return buckets


def status(fetch: bool = True) -> dict:
    if fetch:
        git("fetch", REMOTE, "--prune")
    _, ls_remote, _ = git("remote", "-v")
    has_remote = bool(ls_remote)
    _, head, _ = git("rev-parse", "HEAD")
    _, remote_head, _ = git("rev-parse", f"{REMOTE}/{BRANCH}")
    _, porcelain, _ = git("status", "--porcelain")
    dirty = porcelain.splitlines() if porcelain else []
    behind = ahead = None
    if remote_head:
        code, out, _ = git("rev-list", "--left-right", "--count",
                           f"{REMOTE}/{BRANCH}...HEAD")
        if code == 0 and out:
            left, _, right = out.partition("\t")
            behind, ahead = int(left), int(right)
    _, subject, _ = git("log", "-1", "--pretty=%s")
    state = load_state()
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "remote_url": (ls_remote.splitlines()[0].split()[1] if has_remote and ls_remote else None),
        "branch": BRANCH,
        "local_head": head or None,
        "remote_head": remote_head or None,
        "local_head_subject": subject or None,
        "behind": behind,
        "ahead": ahead,
        "unpushed_commits": ahead,
        "in_sync": bool(head and remote_head and head == remote_head),
        "git_dirty": bool(dirty),
        "git_dirty_count": len(dirty),
        "dirty_classified": classify_dirty(dirty),
        "last_push_at": state.get("last_push_at"),
        "last_push_status": state.get("last_push_status"),
        "last_push_head": state.get("last_push_head"),
        "last_push_error": state.get("last_push_error"),
    }


def render(info: dict) -> str:
    lines = [
        f"remote            : {info['remote_url'] or '(none configured)'}",
        f"branch            : {info['branch']}",
        f"local_head        : {info['local_head']}",
        f"remote_head       : {info['remote_head']}",
        f"unpushed_commits  : {info['unpushed_commits']}   (behind: {info['behind']})",
        f"in_sync           : {info['in_sync']}",
        f"git_dirty         : {info['git_dirty']} ({info['git_dirty_count']} path(s))",
        f"last_push_at      : {info['last_push_at']}",
        f"last_push_status  : {info['last_push_status']}",
    ]
    if info["last_push_error"]:
        lines.append(f"last_push_error   : {info['last_push_error']}")
    if info["git_dirty_count"]:
        for bucket, paths in info["dirty_classified"].items():
            if paths:
                lines.append(f"  {bucket:<9}: {len(paths)} path(s), e.g. {paths[0]}")
    if info["in_sync"]:
        lines.append("verdict           : GitHub mirrors the local tree")
    elif info["ahead"]:
        lines.append(f"verdict           : LOCAL IS AHEAD by {info['ahead']} commit(s) "
                     f"- run `python tools/git_sync.py push`")
    elif info["behind"]:
        lines.append(f"verdict           : LOCAL IS BEHIND by {info['behind']} commit(s) "
                     f"- fetch and merge deliberately, never force")
    return "\n".join(lines)


def run_scanner() -> tuple[bool, str]:
    if not SCANNER.is_file():
        return True, "scanner missing - skipped"
    proc = subprocess.run([sys.executable, str(SCANNER)], cwd=ROOT,
                          capture_output=True, text=True, timeout=600)
    tail = [line for line in proc.stdout.splitlines() if line.startswith(("counts", "VERDICT"))]
    return proc.returncode == 0, "; ".join(tail) or f"rc={proc.returncode}"


def active_escalation_jobs() -> list[str]:
    """Job ids currently editing this tree, if any.

    Read from the escalation ledger rather than guessing from timestamps: the queue
    already knows, and the alternative is exactly the mistake this check exists to
    prevent.  Measured 2026-09-17: an escalation job was mid-edit while a commit
    ran, so its in-progress ``brain.py``/``skills.py``/``verifier.py`` changes were
    swept into an unrelated commit, and ``main`` was briefly inconsistent -- the
    brain decided a skill whose verifier binding was still uncommitted in the
    working tree.  The design says one writer at a time; this makes the commit path
    respect it too.
    """
    try:
        import sys as _sys

        _sys.path.insert(0, str(ROOT))
        from winter_agent_v2.escalation_queue import EscalationLedger

        snapshot = EscalationLedger(ROOT / "learning/workbuddy_escalations.jsonl").snapshot()
    except Exception:  # noqa: BLE001 - a missing ledger must not block a push
        return []
    return [record.job_id or record.key for record in snapshot.active_jobs()]


def do_push(skip_scan: bool, allow_active_agent: bool = False) -> int:
    info = status(fetch=True)
    if not info["remote_url"]:
        print("no remote configured; nothing to push")
        return 2

    if info["behind"]:
        print(f"REFUSING: local is behind {REMOTE}/{BRANCH} by {info['behind']} commit(s).\n"
              f"Fetch, look at the remote changes, then merge or rebase -- this tool will\n"
              f"not force, rewrite or reset anything.")
        return 2

    active = active_escalation_jobs()
    if active and not allow_active_agent:
        print("active agent      : " + ", ".join(active))
        print("REFUSING: a WorkBuddy escalation job is editing this tree right now.\n"
              "          Committing while it works sweeps its half-finished files into\n"
              "          your commit and can leave main inconsistent -- which happened\n"
              "          once, on 2026-09-17.  Wait for the job to settle, or pass\n"
              "          --allow-active-agent if you have checked that the tree is\n"
              "          coherent (compiles, check_wiring problems: 0, tests green).")
        return 2

    if not skip_scan:
        ok, summary = run_scanner()
        print(f"secret scan       : {'PASS' if ok else 'FAIL'} ({summary})")
        if not ok:
            print("REFUSING: the scan found credential-shaped content; see "
                  "out_secret_scan.json. Re-run with --skip-scan only after a human "
                  "has looked at every hit.")
            return 2
    else:
        print("secret scan       : SKIPPED (--skip-scan)")

    if info["in_sync"]:
        print("already in sync; nothing to push")
        state = load_state()
        state.update({"last_push_status": "ALREADY_IN_SYNC",
                      "last_push_at": datetime.now(timezone.utc).isoformat(),
                      "last_push_head": info["local_head"]})
        save_state(state)
        return 0

    print(f"pushing {info['unpushed_commits']} commit(s) to {REMOTE}/{BRANCH} ...")
    code, out, err = git("push", REMOTE, f"HEAD:{BRANCH}")
    state = load_state()
    state.update({
        "last_push_at": datetime.now(timezone.utc).isoformat(),
        "last_push_head": info["local_head"],
        "last_push_status": "PUSHED" if code == 0 else "FAILED_GIT_SYNC_PENDING",
        "last_push_error": None if code == 0 else (err or out)[:500],
    })
    save_state(state)
    if out:
        print("   " + out.replace("\n", "\n   "))
    if err:
        print("   stderr: " + err.replace("\n", "\n   "))
    if code == 0:
        print("push OK")
        return 0
    print("push FAILED - recorded as GIT_SYNC_PENDING in learning/git_sync_state.json; "
          "keep developing and retry later (rule: a remote problem never blocks a "
          "capability).")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p_status = sub.add_parser("status")
    p_status.add_argument("--json", default="")
    p_status.add_argument("--no-fetch", action="store_true")
    p_push = sub.add_parser("push")
    p_push.add_argument("--skip-scan", action="store_true")
    p_push.add_argument(
        "--allow-active-agent", action="store_true",
        help="Push even though a WorkBuddy escalation job is editing this tree. "
             "Only after checking the tree is coherent: it compiles, check_wiring "
             "reports problems: 0, and the tests are green.",
    )
    args = parser.parse_args()

    if args.command == "status":
        info = status(fetch=not args.no_fetch)
        print(render(info))
        if args.json:
            target = Path(args.json)
            if not target.is_absolute():
                target = ROOT / target
            target.write_text(json.dumps(info, ensure_ascii=False, indent=2),
                              encoding="utf-8")
            print(f"wrote {target.relative_to(ROOT)}")
        return 0

    return do_push(args.skip_scan, args.allow_active_agent)


if __name__ == "__main__":
    raise SystemExit(main())
