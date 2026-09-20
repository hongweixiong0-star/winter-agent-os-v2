"""A reward popup must not stop a goal that the sweep just made reachable.

Measured live 2026-09-19, the first time KEEP_TRAINING_PRODUCTIVE was selected: the run stopped
with ``generic_reward_without_goal_context``.  The GENERIC_REWARD branch carried one dismiss skill
per domain -- mail, daily, intel, exploration, alliance -- and none existed for training or
research, so the two goals the sweep had just wired could not get past a reward popup at all: the
sweep died on the first piece of standard UI it met.

``CLOSE_POPUP`` was used to bridge that.  Measured live 2026-09-20 (open issue #64) it turned out
to be a bridge to nowhere: ``CLOSE_POPUP`` taps ``BTN_CLOSE``, which scores phash 28 against a
tolerance of 6 on the dialog (its ROI is the top-right corner, empty on this dialog), so on the
one dialog it was added for it never landed.  It is replaced by ``DISMISS_SHARED_REWARD``, whose
target is the 点击任意位置退出 footer band, and which is bound to ``verify_popup_closed`` -- the
same proof ``CLOSE_POPUP`` used, since the dialog covers whichever page was underneath.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.brain import RuleBrain  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402
from winter_agent_v2.verifier import verify_popup_closed  # noqa: E402


def reward_popup() -> WorldState:
    return WorldState(page=Page.POPUP, popup="GENERIC_REWARD", confidence=0.99)


def test_the_swept_goals_dismiss_the_popup_instead_of_stopping():
    for goal in ("TRAIN", "RESEARCH"):
        decision = RuleBrain(current_goal=goal).decide(reward_popup(), v2_registry())
        assert decision.skill != "SAFE_STOP", f"{goal} must not be stopped by a reward popup"
        assert decision.skill == "DISMISS_SHARED_REWARD"
        assert decision.expected_result == "underlying_page_restored"


def test_the_domain_dismisses_are_unchanged():
    expected = {
        "MAIL": "DISMISS_MAIL_GENERIC_REWARD",
        "DAILY": "DISMISS_DAILY_GENERIC_REWARD",
        "INTEL": "DISMISS_INTEL_GENERIC_REWARD",
        "EXPLORATION": "DISMISS_EXPLORATION_GENERIC_REWARD",
        "ALLIANCE": "DISMISS_ALLIANCE_GENERIC_REWARD",
    }
    for goal, skill in expected.items():
        assert RuleBrain(current_goal=goal).decide(reward_popup(), v2_registry()).skill == skill


def test_a_goal_with_no_context_closes_the_dialog_rather_than_stopping():
    """The fallback used to be SAFE_STOP; stopping could not clear the dialog.

    The client declares the exit on the dialog itself (点击任意位置退出), so this is
    not a guess about which page to return to -- and five of six live AUTO rounds on
    2026-09-20 ended here, so stopping was the shape of the outage rather than a
    guard against one.
    """
    decision = RuleBrain(current_goal="SOMETHING_ELSE").decide(reward_popup(), v2_registry())
    assert decision.skill == "DISMISS_SHARED_REWARD"
    assert decision.reason == "shared_reward_popup_dismissed_by_its_declared_exit"


def test_the_skill_it_uses_can_actually_run():
    registry = v2_registry()
    assert registry.get("DISMISS_SHARED_REWARD") is not None
    assert LiveRuntime.VERIFIED_ATOMIC["DISMISS_SHARED_REWARD"] is verify_popup_closed
