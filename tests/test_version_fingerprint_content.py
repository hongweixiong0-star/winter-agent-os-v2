"""The fingerprint must follow *content*, and must not follow run products.

Two regressions, both named by the operator, both about a fingerprint that answers a
different question than the one being asked:

* **The untracked hole (A).** The digest covered an untracked file's *path* but not its bytes,
  so editing the contents of an untracked file -- which is exactly how a development agent
  delivers a new template or knowledge file -- produced the same version.
* **The drift hole.** Hashing everything dirty would make the version change every time an
  episode was recorded or a screenshot was written, so a version could never be observed twice
  and "the same version ran" would be unfalsifiable.

These run against a real throw-away repository, because the thing under test is a git
invocation rather than a formula.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import winproc  # noqa: E402
from winter_agent_v2.version_identity import canonical_revision, is_version_relevant  # noqa: E402


def _git(root: Path, *args: str) -> str:
    """git through the one hidden runner -- tests must not add a second process wrapper."""
    result = winproc.run(["git", *args], cwd=root, timeout=60, encoding="utf-8")
    return (result.stdout or "") + (result.stderr or "")


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A committed repository with one version-relevant module in it."""
    _git(tmp_path, "init")
    module = tmp_path / "winter_agent_v2"
    module.mkdir(parents=True)
    (module / "runtime.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-m", "initial")
    assert (canonical_revision(tmp_path).dirty) == 0, "the fixture must start clean"
    return tmp_path


def test_an_untracked_file_with_different_content_is_a_different_version(repo: Path):
    """The operator's new counterexample, verbatim: same head, same count, same name.

    The name is even the same file -- only its bytes differ.
    """
    target = repo / "dataset/candidate/beast_card_route.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"route": "musk-ox"}\n', encoding="utf-8")
    first = canonical_revision(repo)

    target.write_text('{"route": "mammoth"}\n', encoding="utf-8")
    second = canonical_revision(repo)

    assert first.head == second.head
    assert first.dirty == second.dirty == 1
    assert first.paths == second.paths, "the same path, so the old form would have matched"
    assert first.token != second.token, (
        "editing an untracked file's contents must change the version"
    )


def test_the_same_content_twice_is_the_same_version(repo: Path):
    """The fix must not make every read a new version."""
    target = repo / "dataset/candidate/route.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"route": "musk-ox"}\n', encoding="utf-8")
    assert canonical_revision(repo).token == canonical_revision(repo).token


def test_a_deleted_version_relevant_file_changes_the_version(repo: Path):
    """A deletion is a change, and skipping it would join two trees into one version."""
    before = canonical_revision(repo)
    (repo / "winter_agent_v2/runtime.py").unlink()
    after = canonical_revision(repo)
    assert before.token != after.token
    assert after.dirty == 1


def test_run_products_do_not_drift_the_version(repo: Path):
    """The drift guard: an episode, a screenshot or a panel log must not create a version."""
    baseline = canonical_revision(repo).token

    (repo / "learning").mkdir(parents=True, exist_ok=True)
    (repo / "learning/episodes.jsonl").write_text('{"result":"SUCCESS"}\n', encoding="utf-8")
    (repo / "learning/runtime_snapshot.json").write_text("{}\n", encoding="utf-8")
    (repo / "dataset/raw").mkdir(parents=True, exist_ok=True)
    (repo / "dataset/raw/shot.png").write_bytes(b"\x89PNG fake")
    (repo / "evidence").mkdir(parents=True, exist_ok=True)
    (repo / "evidence/INDEX.json").write_text("{}\n", encoding="utf-8")

    assert canonical_revision(repo).token == baseline
    assert canonical_revision(repo).dirty == 0


def test_the_policy_names_what_the_runtime_loads_and_not_the_gui(repo: Path):
    """Whitelist by meaning, not by directory convenience."""
    for path in ("winter_agent_v2/runtime.py", "tools/run_live.py", "config/v2.json",
                 "knowledge/game/beasts.json", "dataset/candidate/template_manifest.json"):
        assert is_version_relevant(path), path
    for path in ("tools/control_panel.py", "learning/episodes.jsonl", "evidence/INDEX.json",
                 "dataset/raw/x.png", "docs/NOTES.md", "out_probe.txt",
                 "winter_agent_v2/__pycache__/runtime.cpython-312.pyc"):
        assert not is_version_relevant(path), path


def test_a_tracked_file_edit_is_a_different_version(repo: Path):
    """The ordinary case, so the content digest is exercised on a tracked path too."""
    before = canonical_revision(repo)
    (repo / "winter_agent_v2/runtime.py").write_text("VALUE = 2\n", encoding="utf-8")
    after = canonical_revision(repo)
    assert before.token != after.token
    assert after.head == before.head
