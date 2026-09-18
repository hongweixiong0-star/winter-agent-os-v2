"""A version is identified by its content, not by a file count.

Operator §0A: the token used to be ``head[:12] + "+" + dirty_count``.  Two different working
trees can share a commit, share the number of modified files, and contain entirely different
code -- so the old token answered "same version" about two different trees.  Every rung that
trusts a version identity (activation, validation binding, production reuse) would have been
comparing nothing, and the failure would have looked like a pass.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.escalation_queue import RepoRevision, repo_revision  # noqa: E402

HEAD = "a" * 40


def _dirty(digest: str, *, dirty: int = 3) -> RepoRevision:
    return RepoRevision(head=HEAD, dirty=dirty, ok=True, digest=digest)


def test_the_operators_regression_same_head_same_count_different_content():
    """The exact case named in §0A: equal head, equal dirty count, different diff."""
    one = _dirty("1" * 64)
    two = _dirty("2" * 64)
    assert one.head == two.head
    assert one.dirty == two.dirty
    assert one.token != two.token, "two different trees must not share a version identity"
    assert one.differs_from(two)


def test_the_same_content_still_compares_equal():
    """The other half: the fix must not make everything look different."""
    assert _dirty("3" * 64).token == _dirty("3" * 64).token
    assert not _dirty("3" * 64).differs_from(_dirty("3" * 64))


def test_a_clean_tree_is_identified_by_the_full_commit():
    """A twelve-character prefix is a display convenience, not an identity."""
    clean = RepoRevision(head=HEAD, dirty=0, ok=True)
    assert clean.token == HEAD
    assert len(clean.token) == 40


def test_an_unreadable_tree_has_no_identity_at_all():
    """``ok=False`` must not accidentally equal another unreadable tree's token."""
    assert RepoRevision(ok=False).token == ""
    assert not RepoRevision(ok=False).differs_from(RepoRevision(ok=False))


def test_a_dirty_tree_is_never_confused_with_its_own_clean_commit():
    """An uncommitted fix is a different version from the commit it sits on."""
    clean = RepoRevision(head=HEAD, dirty=0, ok=True)
    assert _dirty("4" * 64).token != clean.token


def test_the_real_tree_yields_a_usable_identity():
    """Against this repository, so the change is measured on a real ``git`` invocation."""
    revision = repo_revision(ROOT)
    assert revision.ok, "the project is a git repository"
    assert len(revision.head) == 40
    assert revision.token
    if revision.dirty:
        assert revision.digest and len(revision.digest) == 64
        assert revision.token.startswith(revision.head)
        assert revision.token != revision.head, "a dirty tree is not its commit"
    else:
        assert revision.token == revision.head
