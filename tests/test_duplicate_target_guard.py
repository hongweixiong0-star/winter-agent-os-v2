"""The duplicate-target question during resource gathering.

When the world-map search produces a node that another of our teams already
targets, the client asks "有其他队伍与您的出征目标相同，依然要发兵吗?".  Sending
anyway spends a march on a contested node and produces nothing, so the
reviewed policy is to cancel and let the next search offer a different node.

The dangerous failure mode is that the dialog is classified as a generic
blocking popup: the agent then closes it as "unknown", the configured
resource is abandoned, and the gather silently fails.  These tests pin the
classification, the decision, and the verifier together.
"""

from pathlib import Path

import pytest

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_duplicate_target_cancelled
from winter_agent_v2.vision import SemanticWorldVision


ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"
DIALOG_FRAME = ROOT / "dataset" / "raw" / "live_phase_e_start.png"
FORMATION_FRAME = ROOT / "dataset" / "raw" / "live_phase_e_after_confirm.png"


def _require(path: Path) -> Path:
    if not path.exists():
        pytest.skip(f"reviewed live frame missing: {path.name}")
    return path


def test_duplicate_target_dialog_is_classified_as_its_own_popup() -> None:
    frame = _require(DIALOG_FRAME)
    state = SemanticWorldVision(MANIFEST).observe(frame)
    assert state.page is Page.POPUP
    assert state.popup == "DUPLICATE_TARGET"


def test_formation_page_is_not_mistaken_for_the_dialog() -> None:
    frame = _require(FORMATION_FRAME)
    state = SemanticWorldVision(MANIFEST).observe(frame)
    assert state.popup != "DUPLICATE_TARGET"


def test_brain_cancels_instead_of_forwarding_the_march() -> None:
    state = WorldState(page=Page.POPUP, popup="DUPLICATE_TARGET", confidence=0.99)
    decision = RuleBrain().decide(state, v2_registry())
    assert decision.skill == "CANCEL_DUPLICATE_TARGET"


def test_cancel_skill_is_registered_and_has_a_live_verifier() -> None:
    from winter_agent_v2.runtime import LiveRuntime

    registry = v2_registry()
    assert registry.get("CANCEL_DUPLICATE_TARGET") is not None
    assert "CANCEL_DUPLICATE_TARGET" in LiveRuntime.VERIFIED_ATOMIC


def test_cancel_is_verified_only_when_the_search_panel_returns() -> None:
    before = WorldState(page=Page.POPUP, popup="DUPLICATE_TARGET", confidence=0.99)
    restored = WorldState(page=Page.MAP, resource_search_open=True, resource_selected="COAL", confidence=0.99)
    strayed = WorldState(page=Page.MAP, resource_search_open=False, confidence=0.99)
    assert verify_duplicate_target_cancelled(before, restored).ok is True
    assert verify_duplicate_target_cancelled(before, strayed).ok is False


def test_generic_popup_close_is_not_accepted_as_a_duplicate_cancel() -> None:
    """Closing the dialog as an unknown popup must not count as the policy."""
    before = WorldState(page=Page.MAP, resource_search_open=True, confidence=0.99)
    after = WorldState(page=Page.MAP, resource_search_open=True, resource_selected="MEAT", confidence=0.99)
    # The dialog was never observed, so nothing proves a contested node was cancelled.
    assert verify_duplicate_target_cancelled(before, after).ok is False
