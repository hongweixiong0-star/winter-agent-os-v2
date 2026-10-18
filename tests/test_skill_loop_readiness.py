"""The readiness probe must read a dumpsys line without guessing.

Only the parsing is tested: every other gate is a fact about the machine at the moment it ran,
which is exactly why the tool reports them instead of asserting them.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import skill_loop_readiness as readiness  # noqa: E402


def test_focus_package_is_read_from_the_activity_component():
    line = ("  mCurrentFocus=Window{9118b96 u0 com.gof.china/com.gof.china.MainActivity}\n"
            "  mFocusedApp=ActivityRecord{51a91b1 u0 com.gof.china/.MainActivity t2}\n")
    assert readiness.parse_focus(line) == "com.gof.china"


def test_focus_package_is_read_without_a_component_path():
    line = "  mCurrentFocus=Window{b695d53 u0 app.lawnchair/app.lawnchair.Launch}"
    assert readiness.parse_focus(line) == "app.lawnchair"


def test_no_focus_line_is_empty_not_a_guess():
    assert readiness.parse_focus("") == ""
    assert readiness.parse_focus("  mFocusedApp=ActivityRecord{1 u0 x/y t0}") == ""


def test_the_probe_is_read_only_by_construction():
    """No input, no lease, no server: only devices/dumpsys/ps are issued."""
    source = (ROOT / "tools" / "skill_loop_readiness.py").read_text(encoding="utf-8")
    for forbidden in ('"tap"', '"swipe"', '"input"', "DeviceLease(", "build_maa_adapter("):
        assert forbidden not in source
