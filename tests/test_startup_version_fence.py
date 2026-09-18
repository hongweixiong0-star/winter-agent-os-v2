"""The startup fence: R1 == R2, or this cycle produces nothing.

Operator, 2026-09-18: freeze the version-relevant tree before the runtime imports (R1), then
re-measure it after the imports and the key initialisation (R2).  Only R1 == R2 may proceed to
real-device execution.

Why refuse rather than carry on: an episode written by a process whose tree moved under it
belongs to *no* version, but every reader downstream -- activation, validation binding,
production reuse -- will attribute it to whichever version it assumed.  Refusing costs one
cycle and writes nothing half-done, because no device action has happened yet.
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


def test_an_unchanged_tree_passes_the_fence(repo: Path):
    vi.freeze_process_revision(repo)
    ok, frozen, current = vi.startup_fence(repo)
    assert ok is True
    assert frozen.token == current.token


def test_a_tree_that_moved_under_the_process_fails_the_fence(repo: Path):
    """The operator's condition: R1 != R2 must stop the cycle before it touches the device."""
    vi.freeze_process_revision(repo)
    (repo / "winter_agent_v2/runtime.py").write_text("VALUE = 2\n", encoding="utf-8")

    ok, frozen, current = vi.startup_fence(repo)
    assert ok is False
    assert frozen.token != current.token
    # Both sides are reported, so the ledger can say what changed to what.
    assert frozen.token and current.token


def test_a_run_product_written_during_startup_does_not_fail_the_fence(repo: Path):
    """The fence must not fire on the runtime's own output -- only on the code."""
    vi.freeze_process_revision(repo)
    (repo / "learning").mkdir(parents=True, exist_ok=True)
    (repo / "learning/runtime_snapshot.json").write_text("{}\n", encoding="utf-8")
    (repo / "dataset/raw").mkdir(parents=True, exist_ok=True)
    (repo / "dataset/raw/shot.png").write_bytes(b"png")
    ok, _, _ = vi.startup_fence(repo)
    assert ok is True, "an episode or a screenshot appearing must not abort a live cycle"


def test_the_entry_point_refuses_before_it_reaches_the_runtime(repo: Path):
    """Structural, because the ordering is the guarantee.

    The fence must sit after the frozen revision is chosen and before ``LiveRuntime`` is
    constructed -- the first thing that can touch the device.
    """
    source = (ROOT / "tools/run_live.py").read_text(encoding="utf-8")
    fence_at = source.find("startup_fence(ROOT)")
    runtime_at = source.find("result = LiveRuntime(")
    freeze_at = source.find("freeze_process_revision(ROOT)")
    assert fence_at != -1 and runtime_at != -1 and freeze_at != -1
    assert freeze_at < fence_at < runtime_at, (
        "the fence must run after the freeze and before any device action"
    )
    assert "STARTUP_VERSION_CHANGED" in source
    assert "return 3" in source[fence_at:fence_at + 600]
