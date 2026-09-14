"""Live-frame regression tests for the recall path and the HUD stamina gauge.

Both features exist because of the operator directive of 2026-09-14: stamina
must be spent (not left full), and a march may be recalled at any time when a
better use for its slot appears.

The tests are anchored on real frames captured on 2026-09-14, not on invented
states:

``dataset/truth_audit/march_recall_20260914_135242/``
    01_map_before.png              six gathering marches, search panel closed
    02_after_row1_tap.png          the 召回 confirmation dialog
    03_after_confirm_recall.png    marches still 6/6, one row now 返回中

``dataset/truth_audit/hud_stamina_20260914/``
    map_hud_with_stamina_200.png           the gauge reads 200
    map_hud_covered_by_recall_dialog.png   the gauge is covered -> unknown
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RECALL = ROOT / "dataset/truth_audit/march_recall_20260914_135242"
STAMINA = ROOT / "dataset/truth_audit/hud_stamina_20260914"
MANIFEST = ROOT / "dataset/candidate/template_manifest.json"
CONFIG = ROOT / "config/v2.json"


def _hybrid():
    from winter_agent_v2.ocr import HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend
    from winter_agent_v2.vision import SemanticWorldVision

    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    template = SemanticWorldVision(MANIFEST)
    return HybridVision(
        template,
        OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"])))),
    )


def _require(path: Path) -> Path:
    if not path.is_file():
        pytest.skip(f"live fixture missing: {path.relative_to(ROOT)}")
    return path


# --- vision: the recall dialog is recognized, and only where it exists ------


def test_recall_dialog_is_recognized_from_the_live_frame() -> None:
    from winter_agent_v2.models import Page

    state = _hybrid().observe(_require(RECALL / "02_after_row1_tap.png"))
    assert state.page is Page.POPUP
    assert state.popup == "MARCH_RECALL"


def test_map_frame_is_not_mistaken_for_the_recall_dialog() -> None:
    """Negative control: the templates must not fire anywhere on the map."""
    from winter_agent_v2.models import Page

    state = _hybrid().observe(_require(RECALL / "01_map_before.png"))
    assert state.page is Page.MAP
    assert state.popup is None


# --- vision: the stamina gauge becomes observable on the map ----------------


def test_map_hud_exposes_the_stamina_value() -> None:
    state = _hybrid().observe(_require(STAMINA / "map_hud_with_stamina_200.png"))
    assert state.stamina.get("current") == 200, state.stamina
    assert state.stamina.get("source") == "MAP_HUD"


def test_covers_the_gauge_reports_unknown_instead_of_guessing() -> None:
    """A dialog hides the gauge; the reader must decline rather than invent."""
    state = _hybrid().observe(_require(STAMINA / "map_hud_covered_by_recall_dialog.png"))
    assert state.stamina.get("current") is None


def test_stamina_roi_is_inside_the_hud_and_cannot_swallow_the_power_row() -> None:
    from winter_agent_v2.ocr import HUD_STAMINA_ROI

    # The power readout sits at y 0.045-0.068 and the gauge at y 0.080-0.091.
    # A ROI that reached up into the power row would start reporting telemetry
    # numbers as stamina.
    assert HUD_STAMINA_ROI["y_norm"] >= 0.070
    assert HUD_STAMINA_ROI["y_norm"] + HUD_STAMINA_ROI["h_norm"] <= 0.100
    assert HUD_STAMINA_ROI["w_norm"] <= 0.10


# --- verifier: the recall is proven by a state transition -------------------


def test_dialog_verifier_requires_an_active_march_before_the_tap() -> None:
    from winter_agent_v2.models import Page, WorldState
    from winter_agent_v2.verifier import verify_march_recall_dialog_open

    opened = WorldState(page=Page.POPUP, popup="MARCH_RECALL", confidence=0.99)
    with_march = WorldState(page=Page.MAP, march_used=6, march_max=6, confidence=0.99)
    without_march = WorldState(page=Page.MAP, march_used=0, march_max=6, confidence=0.99)
    assert verify_march_recall_dialog_open(with_march, opened).ok
    assert not verify_march_recall_dialog_open(without_march, opened).ok
    # An open search panel covers the march list, so row 1 would hit the map.
    search_open = WorldState(page=Page.MAP, march_used=6, march_max=6, resource_search_open=True, confidence=0.99)
    assert not verify_march_recall_dialog_open(search_open, opened).ok


def test_recall_is_proven_by_returning_not_by_an_idle_slot() -> None:
    """The measured semantics, pinned.

    Confirming the recall left the queue at 6/6: the slot is released when the
    troops arrive, not when the button is pressed.  A verifier that demanded an
    idle slot would therefore have rejected a correct recall -- which is what
    the skill's original ``NORMAL_IDLE_SLOT_INCREASED`` declared.
    """
    from winter_agent_v2.models import MarchState, Page, WorldState
    from winter_agent_v2.verifier import verify_march_recalled

    dialog = WorldState(page=Page.POPUP, popup="MARCH_RECALL", confidence=0.99)
    after = WorldState(
        page=Page.MAP,
        march_used=6,
        march_max=6,
        marches=(MarchState.GATHERING, MarchState.RETURNING, MarchState.MARCHING),
        confidence=0.99,
    )
    assert verify_march_recalled(dialog, after).ok

    no_transition = WorldState(
        page=Page.MAP, march_used=6, march_max=6, marches=(MarchState.GATHERING,), confidence=0.99
    )
    assert not verify_march_recalled(dialog, no_transition).ok

    # Already-returning before the tap is not evidence of this recall.
    already = WorldState(
        page=Page.POPUP, popup="MARCH_RECALL", marches=(MarchState.RETURNING,), confidence=0.99
    )
    assert not verify_march_recalled(already, after).ok


def test_recall_verifier_uses_the_live_frames() -> None:
    from winter_agent_v2.models import MarchState
    from winter_agent_v2.verifier import verify_march_recall_dialog_open, verify_march_recalled

    hybrid = _hybrid()
    before = hybrid.observe(_require(RECALL / "01_map_before.png"))
    dialog = hybrid.observe(_require(RECALL / "02_after_row1_tap.png"))
    after = hybrid.observe(_require(RECALL / "03_after_confirm_recall.png"))

    assert verify_march_recall_dialog_open(before, dialog).ok
    assert MarchState.RETURNING in after.marches
    assert verify_march_recalled(dialog, after).ok
    assert after.march_used == before.march_used == 6, "the slot is not freed on the tap"


# --- brain: an unexplained recall dialog is never confirmed -----------------


def test_recall_dialog_is_only_confirmed_when_this_loop_opened_it() -> None:
    from winter_agent_v2.brain import RuleBrain
    from winter_agent_v2.models import Page, WorldState
    from winter_agent_v2.skills import v2_registry

    dialog = WorldState(page=Page.POPUP, popup="MARCH_RECALL", confidence=0.99)
    registry = v2_registry()
    assert RuleBrain().decide(dialog, registry).skill == "CLOSE_POPUP"
    brain = RuleBrain(recall_on_demand=True)
    brain.pending_recall = True
    decision = brain.decide(dialog, registry)
    assert decision.skill == "RECALL_MARCH"
    assert brain.pending_recall is False, "the intent must be consumed exactly once"


def test_full_march_queue_triggers_a_recall_only_when_allowed() -> None:
    from winter_agent_v2.brain import RuleBrain
    from winter_agent_v2.models import MarchState, Page, WorldState
    from winter_agent_v2.skills import v2_registry

    full = WorldState(
        page=Page.MAP, march_used=6, march_max=6, marches=(MarchState.GATHERING,), confidence=0.99
    )
    registry = v2_registry()
    assert RuleBrain().decide(full, registry).skill == "SAFE_STOP"
    brain = RuleBrain(recall_on_demand=True)
    assert brain.decide(full, registry).skill == "SELECT_MARCH_TO_RECALL"
    assert brain.pending_recall is True


def test_a_stamina_march_is_never_the_recall_victim() -> None:
    """Recalling a beast or intel march would throw away paid stamina."""
    from winter_agent_v2.brain import RuleBrain
    from winter_agent_v2.models import MarchState, Page, WorldState
    from winter_agent_v2.skills import v2_registry

    only_beast = WorldState(
        page=Page.MAP, march_used=6, march_max=6, marches=(MarchState.MARCHING,), confidence=0.99
    )
    decision = RuleBrain(recall_on_demand=True).decide(only_beast, v2_registry())
    assert decision.skill == "SAFE_STOP"


# --- wiring: the config flag and the verifiers must actually be reachable ---


def test_recall_skills_are_dispatchable() -> None:
    from winter_agent_v2.runtime import LiveRuntime
    from winter_agent_v2.skills import v2_registry

    registered = {skill.id for skill in v2_registry().all()}
    for skill_id in ("SELECT_MARCH_TO_RECALL", "RECALL_MARCH"):
        assert skill_id in registered, f"{skill_id} is not in the live registry"
        assert skill_id in LiveRuntime.VERIFIED_ATOMIC, (
            f"{skill_id} has no verifier, so the live loop would never dispatch it"
        )


def test_config_enables_recall_on_demand() -> None:
    policy = json.loads(CONFIG.read_text(encoding="utf-8"))["march_policy"]
    assert policy["recall_on_demand"] is True


def test_brain_accepts_every_keyword_the_live_runner_passes() -> None:
    """``tools/run_live.py`` builds the brain from config every run.

    A drift between the two crashes the whole runner before it can take a
    single screenshot, which is exactly what happened while adding these flags.
    """
    from winter_agent_v2.brain import RuleBrain

    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    brain = RuleBrain(
        current_goal="INTEL",
        reserve_marches=int(config["march_policy"]["reserve_for_stamina"]),
        recall_on_demand=bool(config["march_policy"]["recall_on_demand"]),
        claim_free_stamina=bool(config["stamina_policy"]["claim_free_stamina"]),
    )
    assert brain.claim_free_stamina is True
    assert brain.recall_on_demand is True
    assert brain.pending_recall is False
    assert brain.stamina_panel_checked is False


def test_no_skill_targets_the_paid_stamina_control() -> None:
    """The panel sells stamina for diamonds; only the free control is a target."""
    from winter_agent_v2.skills import v2_registry

    targets = {
        str(skill.action.target)
        for skill in v2_registry().all()
        if getattr(skill, "action", None) is not None and getattr(skill.action, "target", None)
    }
    assert "BTN_CLAIM_FREE_STAMINA" in targets
    assert "BTN_PAID_STAMINA_PURCHASE" not in targets, (
        "a skill targets the paid stamina control; only the free claim is allowed"
    )
