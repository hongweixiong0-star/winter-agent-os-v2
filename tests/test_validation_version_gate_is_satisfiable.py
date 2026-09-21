"""The §3 version gate must be a safety property, not a deadlock.

Measured 2026-09-21, and it cost a capability 6.5 hours of real-device time:

    job 280d1659 (capability OPEN_TRAINING_PAGE, goal KEEP_TRAINING_PRODUCTIVE)
    took the device lease, printed VALIDATION_VERSION_MISMATCH, exited 4 and released.
    54 times, between 07:10Z and 13:44Z, once per AUTO cycle.

The gate was not misbehaving.  ``expected_after_version`` is ``record.after_version``, the
fingerprint of the tree at the instant that development ended, frozen on the record forever.
Job 280d1659 settled against ``91e3475`` and the tree then moved 52 commits -- including the
three training fixes the job existed to produce.  So the demanded version really was not what
was loaded, and refusing on its own terms was correct.

What made it a deadlock is that nothing could ever satisfy it.  The demanded version is a
*stale* fingerprint; a validation cycle is always run by the current tree.  The two can only
agree if the tree is rolled back to a commit predating the fix under examination -- which would
examine the wrong code by construction.  A gate that can only be passed by reverting the fix is
not protecting the fix.

The repair keeps the property and drops the deadlock, on the observation that the property is
already enforced one layer down: every episode stamps ``repo_revision`` and
``expected_after_version``, and ``validation_settlement`` credits no row where they disagree.
So an episode cannot be mis-credited however this gate decides -- the gate's real job is the
weaker, checkable one of not spending device time on an examination the settlement will reject.

That job it can still do, by asking whether the demanded version is *still reachable*: an
ancestor of the loaded revision has been superseded (its fix is committed, the tree moved on),
while a non-ancestor or an unresolvable token has genuinely diverged and keeps the refusal.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import winproc  # noqa: E402


def _gate_helper(root: Path | None = None):
    """``_superseded_by_head`` as the entry point defines it, optionally rooted elsewhere.

    Loaded by source rather than by ``import tools.run_live``: importing that module freezes a
    process revision and pulls in MAA, cv2 and the OCR stack, which is a probe of the interpreter
    rather than of this predicate.  Compiled from its own text so the test still breaks if the
    real function is renamed or deleted (``test_the_entry_point_still_calls_it`` pins the call).

    ``root`` substitutes for the module-level ``ROOT``.  In production that ``ROOT`` is
    ``Path(__file__).resolve().parents[1]`` -- the project -- and the helper *must* use it, since
    the question is about this checkout.  A test that wants a throw-away repository has to say so
    through this parameter rather than hoping the helper will guess: passing the fixture's shas
    while the helper ran ``git`` against the project produced two failures whose cause was the
    harness, not the predicate, and a test that misfires for its own reasons is worse than absent.
    """
    source = (ROOT / "tools/run_live.py").read_text(encoding="utf-8")
    start = source.index("def _superseded_by_head")
    end = source.index("\n\n\n", start)
    namespace: dict[str, object] = {"ROOT": root if root is not None else ROOT, "winproc": winproc}
    exec(compile(source[start:end], "run_live._superseded_by_head", "exec"), namespace)
    return namespace["_superseded_by_head"]


def _git(root: Path, *args: str) -> str:
    result = winproc.run(["git", *args], cwd=root, timeout=60, encoding="utf-8")
    return (result.stdout or "") + (result.stderr or "")


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A repository with two commits, so an ancestor exists to be asked about."""
    _git(tmp_path, "init")
    module = tmp_path / "winter_agent_v2"
    module.mkdir(parents=True)
    (module / "runtime.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-m", "first")
    (module / "runtime.py").write_text("VALUE = 2\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-m", "second")
    return tmp_path


def _sha(root: Path, rev: str) -> str:
    return _git(root, "rev-parse", rev).strip()


# --------------------------------------------------------------------------- the real case


def test_the_280d1659_case_is_now_satisfiable():
    """The measured deadlock, on this repository's own history.

    ``91e3475`` is the version job 280d1659 demanded; ``d56875d`` is what every cycle actually
    loaded.  ``91e3475`` is an ancestor, so the examination is allowed to proceed and the
    episodes will carry the mismatch for the settlement to judge.
    """
    superseded = _gate_helper()
    demanded = "91e347522a2c6c0bab2c5df4740cbcae937c3cb9"
    loaded = "d56875dbce7105f6b7ed9615a77fe629d57997e6"
    assert superseded(demanded, loaded) is True, (
        "the demanded version is 52 commits behind the loaded one; refusing forever is the "
        "deadlock this test exists to prevent"
    )


def test_the_demanded_version_really_is_behind_and_not_merely_different():
    """Pins the *fact* the predicate relies on, read from git rather than asserted from memory.

    A predicate that answered "superseded" for any two different shas would pass its own tests
    and be wrong; the property it needs is that one is an ancestor of the other.
    """
    demanded = "91e347522a2c6c0bab2c5df4740cbcae937c3cb9"
    loaded = "d56875dbce7105f6b7ed9615a77fe629d57997e6"
    assert winproc.run(["git", "merge-base", "--is-ancestor", demanded, loaded],
                       cwd=ROOT, timeout=30, encoding="utf-8").returncode == 0
    assert winproc.run(["git", "merge-base", "--is-ancestor", loaded, demanded],
                       cwd=ROOT, timeout=30, encoding="utf-8").returncode != 0


# ------------------------------------------------------------------- the property preserved


def test_a_divergent_version_still_refuses(repo: Path):
    """A demanded version that is *ahead* of what loaded has genuinely diverged.

    The tree has been rolled back: nothing this cycle runs describes that version, and no
    amount of device time can close the gap.  This keeps the original refusal.
    """
    superseded = _gate_helper(repo)
    first, second = _sha(repo, "HEAD~1"), _sha(repo, "HEAD")
    assert superseded(second, first) is False


def test_an_unresolvable_version_keeps_the_refusal(repo: Path):
    """An object git cannot resolve is treated as diverged, and the direction is deliberate.

    Guessing "superseded" wrongly spends device time on episodes the settlement discards;
    guessing "diverged" wrongly costs one more refused cycle, which is the state this branch
    exists to make *visible* rather than to hide.
    """
    superseded = _gate_helper(repo)
    assert superseded("0" * 40, _sha(repo, "HEAD")) is False
    assert superseded("not-a-sha", _sha(repo, "HEAD")) is False


def test_an_empty_demand_is_not_a_supersession(repo: Path):
    """``""`` means the flag was not passed; the gate above already short-circuits on it."""
    superseded = _gate_helper(repo)
    assert superseded("", _sha(repo, "HEAD")) is False


def test_an_equal_version_is_not_a_supersession(repo: Path):
    """Equal tokens mean the gate passed without reaching this branch -- not a supersession."""
    superseded = _gate_helper(repo)
    head = _sha(repo, "HEAD")
    assert superseded(head, head) is False


def test_a_dirty_loaded_token_asks_about_its_head(repo: Path):
    """The loaded token on a dirty tree is ``<head>+<digest>``; git knows only the head.

    And the head is the right question anyway: a dirty tree sitting on top of a commit still
    contains every commit that commit's ancestors introduced.
    """
    superseded = _gate_helper(repo)
    first, second = _sha(repo, "HEAD~1"), _sha(repo, "HEAD")
    assert superseded(first, f"{second}+dc0629e7fbc7d78f") is True


def test_a_dirty_expected_token_is_asked_by_its_head_too(repo: Path):
    """Symmetric: the demanded side is a token as well, and carries the same suffix."""
    superseded = _gate_helper(repo)
    first, second = _sha(repo, "HEAD~1"), _sha(repo, "HEAD")
    assert superseded(f"{first}+deadbeefdeadbeef", second) is True


# ------------------------------------------------------------------ the wiring, structurally


def test_the_entry_point_still_calls_it(repo: Path):
    """The predicate is only a repair if the gate consults it.

    Structural on purpose: the ordering and the branch are the guarantee, and a predicate that
    is tested in isolation while the entry point keeps its old unconditional ``return 4`` would
    leave the deadlock exactly where it was.
    """
    source = (ROOT / "tools/run_live.py").read_text(encoding="utf-8")
    gate_at = source.index("if args.expected_after_version and args.expected_after_version != code_revision:")
    call_at = source.index("if not _superseded_by_head(", gate_at)
    refusal_at = source.index("return 4", gate_at)
    assert call_at < refusal_at, (
        "the entry point must ask whether the demanded version was superseded *before* it "
        "decides to refuse"
    )
    # And the gate must still sit before LiveRuntime, which is the first device touch.
    assert gate_at < source.index("result = LiveRuntime(")
    assert "VALIDATION_VERSION_MISMATCH" in source
    assert "VALIDATION_VERSION_SUPERSEDED" in source


def test_the_superseded_branch_does_not_silently_pass_the_gate(repo: Path):
    """Proceeding is not the same as passing: the mismatch is printed, not hidden.

    A reader auditing the log must be able to tell "the gate was satisfied" from "the gate was
    superseded", because only the second one needs the settlement's mismatch check to be doing
    its job.
    """
    source = (ROOT / "tools/run_live.py").read_text(encoding="utf-8")
    gate_at = source.index("if args.expected_after_version and args.expected_after_version != code_revision:")
    tail = source[gate_at:gate_at + 4000]
    assert "VALIDATION_VERSION_SUPERSEDED" in tail
    assert "validation_settlement credits none of them" in tail, (
        "the branch must name the rung that keeps the property, so a later reader knows where "
        "the mismatch is actually adjudicated"
    )
