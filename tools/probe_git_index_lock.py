"""What actually distinguishes `git status` from `git --no-optional-locks status`?

The first version of the guard test asserted "after reading, no lock is left behind", and it
failed its own counter-example: a flagless ``git status`` also leaves no lock behind, because
it takes the lock, refreshes, and releases it.  So the presence of a lock *after* the read
cannot tell the two apart, and a test built on it would have passed for the wrong reason.

This probe asks the question the right way round: **given a lock already present and held by
nobody, what does each form do?**  That is also the situation the production incident was in.

Runs in a throwaway repository under the temp directory.  Read-only with respect to this
project.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory


def git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def main() -> int:
    out: list[str] = []
    with TemporaryDirectory() as temp:
        root = Path(temp)
        git("init", "-q", cwd=root)
        git("config", "user.email", "t@example.invalid", cwd=root)
        git("config", "user.name", "t", cwd=root)
        tracked = root / "tracked.txt"
        tracked.write_text("one\n", encoding="utf-8")
        git("add", "tracked.txt", cwd=root)
        git("commit", "-qm", "seed", cwd=root)
        tracked.write_text("two\n", encoding="utf-8")
        import os

        future = time.time() + 120
        os.utime(tracked, (future, future))
        lock = root / ".git/index.lock"

        out.append("--- A. no lock present ---")
        r = git("status", "--porcelain", cwd=root)
        out.append(f"  flagless status           rc={r.returncode} lock_after={lock.exists()!r}")
        if lock.exists():
            lock.unlink()
        r = git("--no-optional-locks", "status", "--porcelain", cwd=root)
        out.append(f"  --no-optional-locks status rc={r.returncode} lock_after={lock.exists()!r}")
        if lock.exists():
            lock.unlink()

        out.append("")
        out.append("--- B. a stale lock already present (the production incident) ---")
        lock.write_text("", encoding="utf-8")
        out.append(f"  lock planted: {lock.exists()}")
        r = git("status", "--porcelain", cwd=root)
        out.append(f"  flagless status            rc={r.returncode} lock_after={lock.exists()!r}")
        out.append(f"      stderr: {(r.stderr or '').strip()[:160]!r}")
        out.append(f"      stdout lines: {len((r.stdout or '').splitlines())}")
        if not lock.exists():
            out.append("      (flagless status DELETED the foreign lock)")
        else:
            out.append("      (flagless status left it)")
        # restore for the next probe
        lock.write_text("", encoding="utf-8")
        r = git("--no-optional-locks", "status", "--porcelain", cwd=root)
        out.append(f"  --no-optional-locks status rc={r.returncode} lock_after={lock.exists()!r}")
        out.append(f"      stderr: {(r.stderr or '').strip()[:160]!r}")
        out.append(f"      stdout lines: {len((r.stdout or '').splitlines())}")

        out.append("")
        out.append("--- C. and what the writer does ---")
        r = git("add", "tracked.txt", cwd=root)
        out.append(f"  git add with the lock present rc={r.returncode}")
        out.append(f"      stderr: {(r.stderr or '').strip()[:200]!r}")

    text = "\n".join(out)
    Path(sys.argv[1] if len(sys.argv) > 1 else "out_gitlock_probe.txt").write_text(
        text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
