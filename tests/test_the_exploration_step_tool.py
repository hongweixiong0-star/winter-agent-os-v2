"""The single-step exploration tool's guards, asserted rather than described.

``tools/explore_step.py`` exists because the project had no way to execute an arbitrary single
action (``docs/DEVELOPMENT_FLOW.md`` §八 step 1: 325 tools, 161 one-off probes, nothing general).
The value of the tool is mostly in what it *refuses*, so these tests aim at the refusals and at
the pure helpers -- the device path itself needs a live client and is exercised by hand.

Why the mode guard is tested through the function and not the CLI: the CLI deliberately has no
override for it (§二 puts exploration in Manual), and adding one so a test could reach the guard
would have removed the guard.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

TOOL = ROOT / "tools/explore_step.py"


def _load_tool():
    """Import the tool as a module.

    ``sys.modules`` must be populated before ``exec_module`` -- the same reason the coordinate
    gate's test does it: without the registration an import-time ``dataclass`` lookup raises from
    inside the stdlib and reads like a bug in the tool.
    """
    name = "explore_step_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# -- pure helpers ---------------------------------------------------------------


def test_box_centre_is_the_middle_not_the_corner():
    tool = _load_tool()
    assert tool._box_centre({"x_norm": 0.1, "y_norm": 0.2, "w_norm": 0.2, "h_norm": 0.1}) == (
        0.2, 0.25,
    )


def test_the_risk_screen_uses_the_projects_own_vocabulary():
    """§二 探索边界: a raw point cannot know what is under it, so the frame is screened first.

    The words must come from ``ui_venus_contract.HIGH_RISK_WORDS`` rather than a local list --
    that module's own comment says two risk vocabularies are two risk *rules*, and the copy nobody
    re-read is the one a spend gets through.  This asserts the import is live, not that some
    particular word is absent from it.
    """
    from winter_agent_v2.ui_venus_contract import HIGH_RISK_WORDS

    tool = _load_tool()
    for word in HIGH_RISK_WORDS[:3]:
        assert tool._high_risk_words_in(f"某处写着{word}两个字") == [word]
    assert tool._high_risk_words_in("主城  城墙  升级效果") == []


def test_the_risk_screen_is_action_aware():
    """2026-10-06, found by using the tool: it refused a ``--back`` because the HUD showed 加速.

    A BACK is a system key and activates no control, so screening it cost the ability to leave a
    page and bought no safety -- the tool could not restore the client it had just moved.  §32 asks
    the same question of a guard that it asks of a filter: "cannot do this now" or "should never
    do this"?  So the screen now covers pointing actions only, and a text target is judged on its
    own words instead of on whatever else the frame happens to draw.
    """
    tool = _load_tool()

    # Navigation activates no control -> never screened, however dirty the frame.
    assert tool._risk_refusal("back", None, "联盟  帮助  加速  道具") == []
    assert tool._risk_refusal("swipe", None, "加速") == []
    assert tool._risk_refusal("observe", None, "立即完成") == []

    # A raw point cannot say what is under it -> the whole frame decides.
    assert tool._risk_refusal("tap", None, "联盟  帮助  加速") == ["加速"]
    assert tool._risk_refusal("tap", None, "主城  城墙") == []

    # A named text target is judged on its own words: 加速 elsewhere on the HUD is not a risk.
    assert tool._risk_refusal("tap", "背包", "联盟  加速  道具") == []
    assert tool._risk_refusal("tap", "立即完成", "主城") == ["立即完成"]


# -- the refusals ---------------------------------------------------------------


def test_exploring_outside_manual_mode_is_refused(tmp_path):
    """§二: exploration is a Manual-mode activity; §五 forbids it while the runtime executes."""
    from winter_agent_v2 import mode_state

    tool = _load_tool()
    state_path = tmp_path / "learning" / "MODE_STATE.json"
    mode_state.switch(mode_state.MODE_AUTO, initiator=mode_state.BY_USER,
                      reason="user takes the machine", path=state_path)

    with pytest.raises(SystemExit) as refused:
        tool._require_manual_mode(state_path)
    assert "MANUAL" in str(refused.value)


def test_exploring_in_manual_mode_is_allowed(tmp_path):
    from winter_agent_v2 import mode_state

    tool = _load_tool()
    state_path = tmp_path / "learning" / "MODE_STATE.json"
    mode_state.switch(mode_state.MODE_MANUAL, initiator=mode_state.BY_WORKBUDDY,
                      reason="observe one page", expected_seconds=600.0,
                      completion_criteria="done", path=state_path)

    tool._require_manual_mode(state_path)  # must not raise


def test_purpose_and_scope_are_required():
    """§二 探索纪律: an exploration must state what it is trying to find out and where it may touch.

    Enforced by the command line rather than by habit -- a discipline that lives only in the
    operator's head is the thing this project keeps having to re-learn.
    """
    tool = _load_tool()
    with pytest.raises(SystemExit):
        tool.main(["--observe"])
    with pytest.raises(SystemExit):
        tool.main(["--purpose", "看一眼"])


def test_two_actions_in_one_invocation_are_refused():
    """One action per invocation is what makes the evidence row readable."""
    tool = _load_tool()
    with pytest.raises(SystemExit):
        tool.main(["--purpose", "p", "--scope", "s", "--observe", "--back"])
    with pytest.raises(SystemExit):
        tool.main(["--purpose", "p", "--scope", "s", "--tap", "0.5", "0.5", "--back"])


def test_no_action_at_all_is_refused():
    tool = _load_tool()
    with pytest.raises(SystemExit):
        tool.main(["--purpose", "p", "--scope", "s"])


def test_the_action_set_is_closed():
    """An exploration tool that can send anything would be a second execution chain by another
    name, and the coordinate gate records that the number of tap sites must not grow."""
    tool = _load_tool()
    assert set(tool.ACTIONS) == {"observe", "screenshot", "tap", "tap-text", "swipe", "back"}
