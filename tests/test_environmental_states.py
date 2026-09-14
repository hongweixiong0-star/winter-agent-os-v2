"""Lock the environmental states that end the client-restart loop.

A maintenance window and the startup splash were previously classified as
ordinary UNKNOWN or as an unrelated popup.  The brain then either stopped the
worker (which the control panel counted as an unexpected exit) or tapped Back
on the splash, restarting the client so it hit the same screen again.  These
tests pin both states to an explicit WAIT.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_environmental_wait

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "dataset" / "candidate" / "template_manifest.json"
FRAMES = ROOT / "dataset" / "truth_audit"


def _vision():
    from winter_agent_v2.vision import SemanticWorldVision

    return SemanticWorldVision(CANDIDATE)


def _require(name: str) -> Path:
    path = FRAMES / name
    if not path.exists():
        pytest.skip(f"live frame not captured: {name}")
    return path


def test_live_maintenance_notice_is_its_own_page() -> None:
    state = _vision().observe(_require("maintenance_now.png"))
    assert state.page is Page.MAINTENANCE
    assert state.popup == "MAINTENANCE"


def test_live_splash_is_recognised_as_loading() -> None:
    state = _vision().observe(_require("toast_probe_now.png"))
    assert state.page is Page.LOADING


def test_maintenance_is_not_mistaken_for_a_dismissible_popup() -> None:
    state = _vision().observe(_require("maintenance_now.png"))
    assert state.page is not Page.POPUP


def test_a_plain_map_frame_is_neither_loading_nor_maintenance() -> None:
    for name in ("live_now.png", "tapchk_after.png"):
        state = _vision().observe(_require(name))
        assert state.page not in {Page.LOADING, Page.MAINTENANCE}


@pytest.mark.parametrize("page", [Page.MAINTENANCE, Page.LOADING])
def test_brain_waits_instead_of_stopping_or_tapping(page: Page) -> None:
    decision = RuleBrain().decide(WorldState(page=page, confidence=0.99), v2_registry())
    assert decision.skill == "WAIT"
    assert decision.skill != "SAFE_STOP"
    assert decision.skill != "BACK"


def test_wait_skill_is_a_no_click_observation() -> None:
    skill = v2_registry().get("WAIT")
    assert skill is not None
    assert skill.action.kind == "OBSERVE"


def test_wait_is_verifier_backed() -> None:
    from winter_agent_v2.runtime import LiveRuntime

    assert "WAIT" in LiveRuntime.VERIFIED_ATOMIC


def test_wait_is_verified_when_the_environment_persists() -> None:
    before = WorldState(page=Page.MAINTENANCE, popup="MAINTENANCE", confidence=0.99)
    after = WorldState(page=Page.MAINTENANCE, popup="MAINTENANCE", confidence=0.99)
    assert verify_environmental_wait(before, after).ok is True


def test_wait_is_verified_when_the_splash_naturally_advances() -> None:
    before = WorldState(page=Page.LOADING, confidence=0.99)
    after = WorldState(page=Page.HOME, confidence=0.99)
    assert verify_environmental_wait(before, after).ok is True


def test_wait_is_not_verified_when_observation_breaks() -> None:
    before = WorldState(page=Page.LOADING, confidence=0.99)
    after = WorldState(page=Page.UNKNOWN, confidence=0.0)
    result = verify_environmental_wait(before, after)
    assert result.ok is False
    assert result.reason == "ENVIRONMENTAL_WAIT_NOT_PROVEN"


def test_wait_never_fires_outside_an_environmental_state() -> None:
    before = WorldState(page=Page.MAP, confidence=0.99)
    after = WorldState(page=Page.MAP, confidence=0.99)
    assert verify_environmental_wait(before, after).ok is False
