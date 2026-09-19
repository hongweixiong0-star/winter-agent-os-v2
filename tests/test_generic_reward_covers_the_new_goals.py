"""A reward popup must not stop a goal that the sweep just made reachable.

Measured live 2026-09-19, the first time KEEP_TRAINING_PRODUCTIVE was selected: the run stopped
with ``generic_reward_without_goal_context``.  The GENERIC_REWARD branch carried one dismiss skill
per domain -- mail, daily, intel, exploration, alliance -- and none existed for training or
research, so the two goals the sweep had just wired could not get past a reward popup at all: the
sweep died on the first piece of standard UI it met.

``CLOSE_POPUP`` is registered and verifier-bound, and closing the popup is exactly what those
goals need next, so it is used rather than inventing per-domain skills that nothing would verify.
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


def reward_popup() -> WorldState:
    return WorldState(page=Page.POPUP, popup="GENERIC_REWARD", confidence=0.99)


def test_the_swept_goals_dismiss_the_popup_instead_of_stopping():
    for goal in ("TRAIN", "RESEARCH"):
        decision = RuleBrain(current_goal=goal).decide(reward_popup(), v2_registry())
        assert decision.skill != "SAFE_STOP", f"{goal} must not be stopped by a reward popup"
        assert decision.skill == "CLOSE_POPUP"
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


def test_a_goal_with_no_context_still_stops_honestly():
    """The fallback is kept: an unknown goal closing popups would be a guess."""
    decision = RuleBrain(current_goal="SOMETHING_ELSE").decide(reward_popup(), v2_registry())
    assert decision.skill == "SAFE_STOP"
    assert decision.reason == "generic_reward_without_goal_context"


def test_the_skill_it_uses_can_actually_run():
    registry = v2_registry()
    assert registry.get("CLOSE_POPUP") is not None
    assert "CLOSE_POPUP" in LiveRuntime.VERIFIED_ATOMIC
