"""The revision a process reports is the one it *loaded*, not the one on the disk now.

Operator §B: ``tools/run_live.py`` imports fifteen runtime modules at module scope and used to
read the revision inside ``main()`` -- after those imports.  So its "revision" described the
disk at that later moment, and a job that finished mid-cycle would have its **new** revision
credited to an episode produced by the **old** code.  Each cycle is a fresh process, so the
freeze has to happen first and hold for the whole process.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import winproc  # noqa: E402
from winter_agent_v2 import version_identity as vi  # noqa: E402


def _git(root: Path, *args: str) -> None:
    winproc.run(["git", *args], cwd=root, timeout=60, encoding="utf-8")


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init")
    module = tmp_path / "winter_agent_v2"
    module.mkdir(parents=True)
    (module / "runtime.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-m", "initial")
    vi.reset_process_revision_for_tests()
    return tmp_path


def test_a_frozen_revision_does_not_follow_the_disk(repo: Path):
    """The counterexample: code changes after the process started, the process still says 1."""
    frozen = vi.freeze_process_revision(repo)
    assert frozen.token
    assert vi.process_revision_token() == frozen.token

    # The developer edits the tree while this process is running.
    (repo / "winter_agent_v2/runtime.py").write_text("VALUE = 2\n", encoding="utf-8")
    on_disk = vi.canonical_revision(repo)
    assert on_disk.token != frozen.token, "the disk really did change"

    assert vi.process_revision_token() == frozen.token, (
        "the running process must keep reporting the version it loaded, not the new one"
    )


def test_freezing_twice_returns_the_first_answer(repo: Path):
    """Idempotent, so no later code path can quietly move the goalposts mid-process."""
    first = vi.freeze_process_revision(repo)
    (repo / "winter_agent_v2/runtime.py").write_text("VALUE = 3\n", encoding="utf-8")
    assert vi.freeze_process_revision(repo) is first


def test_an_unfrozen_process_reports_nothing_rather_than_guessing(repo: Path):
    """"" is the honest answer for "this process never captured one"."""
    vi.reset_process_revision_for_tests()
    assert vi.process_revision() is None
    assert vi.process_revision_token() == ""


def test_run_live_captures_the_revision_before_it_imports_the_runtime():
    """Structural, because the ordering *is* the fix.

    Importing ``tools/run_live.py`` would execute its argparse-free module scope but also drag
    in MAA and OpenCV; so the source is read instead and the freeze is required to appear
    before the first ``winter_agent_v2`` runtime import.
    """
    source = (ROOT / "tools/run_live.py").read_text(encoding="utf-8")
    freeze_at = source.find("freeze_process_revision(ROOT)")
    first_runtime_import = source.find("from winter_agent_v2.device import")
    assert freeze_at != -1, "run_live must freeze the process revision"
    assert first_runtime_import != -1
    assert freeze_at < first_runtime_import, (
        "the freeze must precede the runtime imports, or it describes what those imports loaded"
    )
    # And the episode's own value must come from the freeze, not from a fresh git read.
    assert "code_revision = PROCESS_CODE_REVISION" in source
    assert "tree_revision(ROOT)" not in source
