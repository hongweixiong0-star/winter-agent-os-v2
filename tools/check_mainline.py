"""Check the one-mainline invariants, and name the one that is broken.

2026-10-04, operator instruction: reconcile the development repo and the production branch,
then write the rules down.  A rule is only worth writing if something can contradict it, so
this is the machine half of §27 in ``.workbuddy-ai/handoff/00_MASTER_RULES.md`` -- three
facts, each independently falsifiable, and a non-zero exit code when any of them is false:

    1. the pinned worktree sits at the commit the manifest pins
    2. that commit is on the mainline branch
    3. the read-only mirror ``main`` is on the mainline branch

What is deliberately *not* checked: that the pin is the mainline's *newest* commit.  Pinning
a commit that is on the mainline but not its tip is a decision (a rollback, a bisect), not a
defect.  Checking it would turn a deliberate act into a failure, and a guard that fires on
correct behaviour teaches its reader to ignore it.

And what is deliberately not asserted at startup.  ``launch_pinned_production.verify_pin``
already refuses to start when HEAD is not ``expected_commit``, and that refusal must stay
narrow: it is the production entry point, so a rule added there can stop production.  These
three criteria are a *diagnostic*, run by hand and by the session's own discipline, and they
can only print.

Measured 2026-10-04, the reconciliation this guards:

    main            ff19040c      1 ahead / 41 behind codex/production-pin-recovery
    production      23360c0a
    merge-base      05042268
    ff19040c vs b314adb1  the same stable patch-id 7a3fb91a2184ceb82e1974311cf9cf8e7718ad8d
    git merge --no-commit --no-ff ff19040c  ->  0 conflicts, tree 6d922d19, byte-identical
    merge commit    ca336ddb      both parents, so neither line loses a commit
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[1]
if str(CODE_ROOT) not in sys.path:  # run as a script, from either worktree
    sys.path.insert(0, str(CODE_ROOT))

from config import paths  # noqa: E402
from winter_agent_v2 import winproc  # noqa: E402

#: The one line production is pinned from.  A name is not evidence -- criterion 2 is, and it
#: is checked rather than assumed.  This string only says which ref to ask about.
MAINLINE_BRANCH = "codex/production-pin-recovery"
#: The development repo's branch, kept as a mirror that is only ever fast-forwarded.
MIRROR_BRANCH = "main"
#: ``E:\无尽冬日智能体_worktrees`` -- derived, never a drive literal, per §26.3.
WORKTREE_ROOT = paths.MAIN_REPO.parent / f"{paths.MAIN_REPO.name}_worktrees"
PIN_HOME = WORKTREE_ROOT / "winter-prod-pinned"
PIN_WORKTREE = PIN_HOME / paths.MAIN_REPO.name
MANIFEST_NAME = "PRODUCTION_PIN.json"
MIRROR_WORKTREE = paths.MAIN_REPO


def short(sha: str) -> str:
    """Eight characters, or ``?`` -- a missing sha must print as missing, not as empty."""
    return (sha or "?")[:8]


def read_manifest(path: Path) -> dict:
    """The pin manifest, or ``{}``.  Unreadable is reported by criterion 1, not raised."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _git(cwd: Path, *args: str) -> tuple[int, str]:
    """One git call, hidden and bounded.  ``winproc.run`` keeps this off the console."""
    if not cwd.exists():
        return 1, ""
    proc = winproc.run(["git", "-C", str(cwd), *args], timeout=60.0)
    return proc.returncode, (proc.stdout or "").strip()


def head_of(worktree: Path) -> str:
    rc, out = _git(worktree, "rev-parse", "HEAD")
    return out if rc == 0 else ""


def branch_of(worktree: Path) -> str:
    rc, out = _git(worktree, "rev-parse", "--abbrev-ref", "HEAD")
    return out if rc == 0 else ""


def is_ancestor(ancestor: str, descendant: str, cwd: Path) -> bool:
    """``git merge-base --is-ancestor`` is true when they are the *same* commit too.

    That is the semantics the rule wants: the mirror may lag the mainline, and may equal it,
    and may not carry anything the mainline does not have.
    """
    if not ancestor or not descendant:
        return False
    rc, _ = _git(cwd, "merge-base", "--is-ancestor", ancestor, descendant)
    return rc == 0


def verdicts(*, pin_head: str, expected_commit: str, mainline_tip: str, mirror_head: str,
             expected_on_mainline: bool, mirror_on_mainline: bool) -> list[tuple[bool, str]]:
    """The three criteria as (ok, sentence) pairs.  Pure, so a test needs no repository."""
    return [
        (bool(expected_commit) and pin_head == expected_commit,
         f"1. pin worktree HEAD {short(pin_head)} == manifest expected_commit "
         f"{short(expected_commit)}"),
        (expected_on_mainline,
         f"2. expected_commit {short(expected_commit)} is on {MAINLINE_BRANCH} "
         f"{short(mainline_tip)}"),
        (mirror_on_mainline,
         f"3. mirror {MIRROR_BRANCH} {short(mirror_head)} is on {MAINLINE_BRANCH} "
         f"{short(mainline_tip)}"),
    ]


def gather(pin_worktree: Path, manifest_path: Path, mirror_worktree: Path) -> dict:
    """Resolve the five facts the verdicts need.  A missing worktree yields empty strings,
    which fail their criteria -- the report has to survive the thing it is reporting on."""
    repo = pin_worktree if pin_worktree.exists() else mirror_worktree
    mainline_tip = ""
    rc, out = _git(repo, "rev-parse", f"refs/heads/{MAINLINE_BRANCH}")
    if rc == 0:
        mainline_tip = out
    pin_head = head_of(pin_worktree)
    expected = str(read_manifest(manifest_path).get("expected_commit") or "")
    mirror_head = head_of(mirror_worktree)
    return {
        "pin_head": pin_head,
        "expected_commit": expected,
        "mainline_tip": mainline_tip,
        "mirror_head": mirror_head,
        "expected_on_mainline": is_ancestor(expected, mainline_tip, repo),
        "mirror_on_mainline": is_ancestor(mirror_head, mainline_tip, repo),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="check the one-mainline invariants")
    parser.add_argument("--pin-home", type=Path, default=PIN_HOME,
                        help="directory holding PRODUCTION_PIN.json and the pinned worktree")
    parser.add_argument("--mirror", type=Path, default=MIRROR_WORKTREE,
                        help="the read-only mirror checkout (branch main)")
    parser.add_argument("--json", action="store_true", help="print the facts as JSON")
    args = parser.parse_args(argv)

    pin_worktree = args.pin_home / paths.MAIN_REPO.name
    facts = gather(pin_worktree, args.pin_home / MANIFEST_NAME, args.mirror)
    rows = verdicts(**facts)

    if args.json:
        print(json.dumps({**facts, "criteria": [{"ok": ok, "says": says} for ok, says in rows]},
                         ensure_ascii=False, indent=2))
    else:
        print(f"pin worktree  : {pin_worktree}")
        print(f"mirror        : {args.mirror}  [{branch_of(args.mirror) or '?'}]")
        print(f"mainline      : {MAINLINE_BRANCH} @ {short(facts['mainline_tip'])}")
        for ok, says in rows:
            print(f"  {'OK  ' if ok else 'FAIL'} {says}")

    broken = [says for ok, says in rows if not ok]
    print("RESULT:", "MAINLINE_OK" if not broken else f"MAINLINE_BROKEN={len(broken)}")
    for says in broken:
        print("  BROKEN", says)
    return 0 if not broken else 1


if __name__ == "__main__":
    raise SystemExit(main())
