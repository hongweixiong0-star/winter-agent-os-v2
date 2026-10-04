"""The one-mainline criteria: each must be able to say no.

A criterion that cannot fail is a decoration.  So every test here is written against a
*false* fact first, and the true case is the second assertion.  The verdict function is pure
on purpose: the thing worth testing is which fact makes which sentence say FAIL, and that
needs no repository, no git and no clock.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.check_mainline as cm  # noqa: E402


def facts(**overrides) -> dict:
    """Every fact true, so a test changes exactly the one it is about."""
    base = {
        "pin_head": "a" * 40,
        "expected_commit": "a" * 40,
        "mainline_tip": "b" * 40,
        "mirror_head": "c" * 40,
        "expected_on_mainline": True,
        "mirror_on_mainline": True,
    }
    base.update(overrides)
    return base


def broken(rows) -> list[str]:
    return [says for ok, says in rows if not ok]


# --------------------------------------------------------------- each criterion can fail


def test_a_pin_worktree_off_its_manifest_fails_the_first_criterion():
    rows = cm.verdicts(**facts(pin_head="d" * 40))
    assert len(broken(rows)) == 1
    assert broken(rows)[0].startswith("1.")
    assert cm.verdicts(**facts())[0][0] is True


def test_a_commit_that_is_not_on_the_mainline_fails_the_second_criterion():
    rows = cm.verdicts(**facts(expected_on_mainline=False))
    assert len(broken(rows)) == 1
    assert broken(rows)[0].startswith("2.")
    assert cm.verdicts(**facts())[1][0] is True


def test_a_mirror_carrying_its_own_commits_fails_the_third_criterion():
    """The mirror may lag the mainline and may equal it; it may not be ahead of it."""
    rows = cm.verdicts(**facts(mirror_on_mainline=False))
    assert len(broken(rows)) == 1
    assert broken(rows)[0].startswith("3.")
    assert cm.verdicts(**facts())[2][0] is True


def test_an_empty_expected_commit_is_broken_rather_than_equal():
    """``"" == ""`` would make an unreadable manifest look pinned.  It must not."""
    rows = cm.verdicts(**facts(pin_head="", expected_commit=""))
    assert broken(rows)[0].startswith("1.")
    assert cm.verdicts(**facts())[0][0] is True


def test_a_missing_pin_worktree_is_reported_not_raised(tmp_path: Path):
    """The report has to survive the thing it reports on."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "check_mainline.py"),
         "--pin-home", str(tmp_path / "nowhere"),
         "--mirror", str(tmp_path / "also-nowhere")],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 1
    assert "MAINLINE_BROKEN=3" in result.stdout
    assert "Traceback" not in result.stderr


# --------------------------------------------------------------- the sentence and the paths


def test_short_says_missing_rather_than_empty():
    assert cm.short("") == "?"
    assert cm.short("0123456789abcdef") == "01234567"


def test_read_manifest_returns_empty_on_rubbish(tmp_path: Path):
    path = tmp_path / "PRODUCTION_PIN.json"
    assert cm.read_manifest(path) == {}
    path.write_text("{ not json", encoding="utf-8")
    assert cm.read_manifest(path) == {}
    path.write_text(json.dumps({"expected_commit": "e" * 40}), encoding="utf-8")
    assert cm.read_manifest(path)["expected_commit"] == "e" * 40


def test_the_pin_home_is_derived_from_the_data_root_and_not_a_drive_literal():
    """§26.3: no new drive literals.  ``MAIN_REPO.parent`` is where the worktrees live."""
    assert cm.PIN_HOME == cm.WORKTREE_ROOT / "winter-prod-pinned"
    assert cm.WORKTREE_ROOT.parent == cm.MIRROR_WORKTREE.parent
    assert cm.PIN_WORKTREE.name == cm.MIRROR_WORKTREE.name


@pytest.mark.parametrize("branch", [cm.MAINLINE_BRANCH, cm.MIRROR_BRANCH])
def test_the_two_checked_branches_are_named_exactly(branch: str):
    assert branch in ("codex/production-pin-recovery", "main")
