"""Live production state must not be checkout-controlled.

Structural regression for 2026-09-29: ``config``/``knowledge``/``learning``/``dataset``
are junctions into the shared DATA_ROOT that the pinned worktree mounts, so a
``git checkout``/``git rebase`` writes *through* them.  That rolled the live
production state back to an 11-day-old committed copy -- the wrong account, a
10k-row episode ledger truncated to 2.1k rows, a scheduler snapshot from a role no
longer on the device.

``tools/build_runtime_state_manifest.py`` classifies every tracked file under the
data root and untracks the RUNTIME_MUTABLE ones.  These tests keep that true.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import build_runtime_state_manifest as manifest  # noqa: E402


def _tracked() -> list[str]:
    return manifest.tracked_files()


def test_every_tracked_data_file_is_classified() -> None:
    files = _tracked()
    assert files, "the data root scan found nothing -- the classifier would be vacuous"
    unclassified = sorted(path for path in files if manifest.classify(path) == "UNCLASSIFIED")
    assert unclassified == [], f"unclassified tracked files: {unclassified[:10]}"


def test_runtime_mutable_files_are_not_tracked() -> None:
    still_tracked = sorted(
        path for path in _tracked() if manifest.classify(path) == manifest.RUNTIME_MUTABLE
    )
    assert still_tracked == [], (
        "these are rewritten by the running loop and must not be checkout-controlled: "
        f"{still_tracked[:10]}"
    )


def test_the_named_live_state_is_untracked() -> None:
    """The operator's own enumeration, each with a writer in the running loop."""
    for path in (
        "learning/runtime_snapshot.json",
        "learning/goal_state.json",
        "learning/role_identity.json",
        "learning/event_goal_state.json",
        "learning/timed_event_schedule.json",
        "learning/stamina_supply.json",
        "learning/resource_rotation.json",
        "learning/candidate_attempt_pool.json",
        "config/control_panel_state.json",
        "config/policy_state.json",
    ):
        assert manifest.classify(path) == manifest.RUNTIME_MUTABLE, path


def test_knowledge_and_code_stay_in_git() -> None:
    """The classification must not become a licence to untrack knowledge."""
    tracked = set(_tracked())
    for path in (
        "knowledge/events/event_registry.json",
        "knowledge/game/daily.json",
        "knowledge/goals/capability_skill_map.manual.json",
    ):
        assert manifest.classify(path) == manifest.VERSIONED_KNOWLEDGE, path
        assert path in tracked, f"versioned knowledge was untracked: {path}"

    code = subprocess.run(["git", "ls-files", "winter_agent_v2", "tools", "tests"], cwd=ROOT,
                          capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    assert "winter_agent_v2/runtime.py" in code
    assert "winter_agent_v2/capability_coverage.py" in code
    assert "tools/check_wiring.py" in code


def test_gitignore_covers_the_runtime_mutable_paths() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert manifest.BLOCK_BEGIN in gitignore and manifest.BLOCK_END in gitignore
    for path in ("learning/runtime_snapshot.json", "learning/control_panel/pump.json",
                 "config/control_panel_state.json"):
        done = subprocess.run(["git", "check-ignore", "-q", "--", path], cwd=ROOT,
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert done.returncode == 0, f"{path} is not ignored by Git"
