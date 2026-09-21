"""Reading the version must not join the fight over ``.git/index.lock``.

Measured 2026-09-22 00:39: ``.git/index.lock`` had been sitting in this repository for forty
minutes with **no git process alive**, and every ``git add`` failed with

    fatal: Unable to create '.git/index.lock': File exists.

while ``git log`` and ``git status`` kept working normally -- which is exactly what made it
easy to miss.  The writer was blocked; the readers were not.

What is *not* claimed here, and the first version of this file got wrong: nothing in this
repository proves which process left that lock.  The obvious candidate is the hot-path reader
(``repo_revision`` runs on every ``run_live`` cycle, every queue drain, and in the bootstrap,
each with a subprocess timeout that kills ``git``), but "candidate" is not "cause", and the
experiment below shows the observable behaviour cannot separate them.

``tools/probe_git_index_lock.py`` ran the comparison in a throwaway repository:

    no lock present      flagless status rc=0, no lock left;  --no-optional-locks same
    stale lock present   BOTH rc=0 and both leave the foreign lock alone
    writer               git add rc=128, "File exists ... may be stale"

So "did a lock survive the read" cannot distinguish the two forms: a read that does take the
lock releases it again, and a read that finds a foreign lock leaves it.  The difference is
only inside the window where ``git`` is running -- flagless ``status`` may take the lock to
refresh its stat cache; ``--no-optional-locks`` never does.  A process killed inside that
window is the only way to leave one behind, and the flag removes the window rather than
shortening it.

These tests therefore pin what *can* be pinned: the flag is passed on both readers, reading
still returns the same answer with it, and a read still succeeds while a stale lock is
sitting there (the read path was never the thing that broke).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import version_identity  # noqa: E402


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


@pytest.fixture()
def dirty_repo():
    """A throwaway repository with one tracked file modified and a stale stat cache.

    Built this way on purpose: a freshly-initialised clean repo asks ``git`` for nothing, so a
    fixture like that would exercise none of the paths this file is about.  The stale mtime is
    what makes an index refresh a possibility at all.
    """
    with TemporaryDirectory() as temp:
        root = Path(temp)
        if _git("init", "-q", cwd=root).returncode != 0:
            pytest.skip("git unavailable")
        _git("config", "user.email", "t@example.invalid", cwd=root)
        _git("config", "user.name", "t", cwd=root)
        tracked = root / "tracked.txt"
        tracked.write_text("one\n", encoding="utf-8")
        _git("add", "tracked.txt", cwd=root)
        _git("commit", "-qm", "seed", cwd=root)
        tracked.write_text("two\n", encoding="utf-8")
        future = time.time() + 120
        os.utime(tracked, (future, future))
        lock = root / ".git/index.lock"
        if lock.exists():
            lock.unlink()
        yield root, lock, tracked


def test_the_version_readers_pass_the_flag():
    """Both hot-path readers, because either one can be the process that gets killed."""
    source = (ROOT / "winter_agent_v2/version_identity.py").read_text(encoding="utf-8")
    queue = (ROOT / "winter_agent_v2/escalation_queue.py").read_text(encoding="utf-8")
    assert '"--no-optional-locks", "status"' in source, (
        "version_identity.dirty_entries must not take the index lock"
    )
    assert '"--no-optional-locks", "status"' in queue, (
        "escalation_queue.repo_revision must not take the index lock"
    )


def test_the_flag_does_not_change_what_is_read(dirty_repo):
    """It is about locking, not about content.  Measured equal on this fixture."""
    root, _lock, _tracked = dirty_repo
    with_flag = {path for _status, path in version_identity.dirty_entries(root)}
    plain = _git("status", "--porcelain", "-z", cwd=root).stdout
    plain_paths = {entry[3:] for entry in plain.split("\0") if len(entry) > 3}
    assert plain_paths == with_flag
    assert any("tracked.txt" in path for path in with_flag), (
        "the fixture must actually be dirty, or this compares two empty answers"
    )


def test_a_stale_lock_does_not_block_the_read(dirty_repo):
    """The read path was never what broke -- measured, so the incident is not misremembered.

    With the lock planted, both forms still answer and neither deletes the foreign lock.  If a
    future change made a read refuse (or made it delete someone else's lock) this fails, which
    is the behaviour worth pinning: readers survive, writers are the ones that stop.
    """
    root, lock, _tracked = dirty_repo
    lock.write_text("", encoding="utf-8")
    try:
        entries = version_identity.dirty_entries(root)
        assert any("tracked.txt" in path for _status, path in entries)
        assert lock.exists(), "the read must not have removed a lock it does not own"
    finally:
        if lock.exists():
            lock.unlink()
