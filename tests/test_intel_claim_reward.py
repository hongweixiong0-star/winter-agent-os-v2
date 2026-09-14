"""Regression: claiming completed Intel rewards must be provable.

Measured failure (2026-09-14, live INTEL run7):

    INTEL_CLAIM_REWARDS  verifier FAIL  INTEL_CLAIM_FEEDBACK_NOT_PROVEN

The claim itself worked: the after-frame shows the reward popup with
获得奖励 / EXP 6,000 / 50 / 点击任意位置退出.  What broke was the *classification*:
the client uses one shared reward popup for every source, and in vision.py
``POPUP_EXPLORATION_REWARD`` is consulted before ``POPUP_INTEL_REWARD``, so the
Intel claim produced ``popup == "EXPLORATION_REWARD"`` on the first after-frame
and ``GENERIC_REWARD`` on the refresh frames.  The verifier demanded
``INTEL_REWARD``, which is an arbitrary choice between two templates that match
the same artwork.

The fix follows the pattern ``verify_daily_claim_feedback`` already used (it
accepted GENERIC_REWARD): prove the source from the *before* state -- Intel page
with ``claimable_count > 0`` -- and accept any reward popup as the feedback.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.live_stack import production_vision

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "dataset/truth_audit/intel_claim_reward_20260914"
CLAIMABLE = FIXTURE / "01_intel_page_claimable.png"
REWARD = FIXTURE / "02_reward_popup_after_claim.png"


def _fixture(path: Path) -> Path:
    if not path.is_file():
        pytest.skip(f"live fixture missing: {path.relative_to(ROOT)}")
    return path


def test_claim_feedback_is_proven_from_the_live_pair() -> None:
    from winter_agent_v2.verifier import verify_intel_claim_feedback

    vision = production_vision()
    if vision is None:
        pytest.skip("OCR runtime unavailable")
    before = vision.observe(_fixture(CLAIMABLE))
    after = vision.observe(_fixture(REWARD))
    assert before.intel.get("status") == "CLAIMABLE"
    result = verify_intel_claim_feedback(before, after)
    assert result.ok, result.evidence


def test_claim_feedback_rejects_a_missing_reward_popup() -> None:
    """Negative control: claiming without a reward popup is not a claim."""
    from winter_agent_v2.verifier import verify_intel_claim_feedback

    vision = production_vision()
    if vision is None:
        pytest.skip("OCR runtime unavailable")
    before = vision.observe(_fixture(CLAIMABLE))
    assert not verify_intel_claim_feedback(before, before).ok


def test_the_reward_popup_is_source_agnostic() -> None:
    """Documents the measured ambiguity the fix depends on.

    The same claim frame is classified EXPLORATION_REWARD here.  Any verifier
    that pins the popup identity to one source will fail intermittently.
    """
    from winter_agent_v2.models import Page

    vision = production_vision()
    if vision is None:
        pytest.skip("OCR runtime unavailable")
    after = vision.observe(_fixture(REWARD))
    assert after.page is Page.POPUP
    assert after.popup != "INTEL_REWARD", (
        "the classification changed; if Intel now gets its own popup the "
        "is_reward_popup shortcut can be narrowed again -- but keep the "
        "before-state proof"
    )


def test_reward_popup_helper_covers_every_domain() -> None:
    from winter_agent_v2.models import Page, WorldState
    from winter_agent_v2.verifier import is_reward_popup

    for popup in ("INTEL_REWARD", "GENERIC_REWARD", "EXPLORATION_REWARD"):
        assert is_reward_popup(WorldState(page=Page.POPUP, popup=popup, confidence=0.99))
    assert not is_reward_popup(WorldState(page=Page.POPUP, popup="REAL_MONEY_OFFER", confidence=0.99))
    assert not is_reward_popup(WorldState(page=Page.INTEL, confidence=0.99))
