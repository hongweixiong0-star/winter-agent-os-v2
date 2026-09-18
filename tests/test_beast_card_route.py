"""Lock the 2026-09-18 beast-card route (SPEND_STAMINA_ON_BEAST escalation).

Root cause of the escalation: AVOID_STAMINA_WASTE could only advance by
reaching a beast, and its only such hop was a viewport pan with no convergence
criterion -- three verified swipes in a row moved the camera and nothing else.
The route can now converge through the client's own mechanism: a tapped
wilderness sprite opens a beast card whose 攻击 control (stamina cost drawn
inside the button) opens the formation page the dispatch verifier already
binds.

Frames used here are the escalation's own live captures:

    dataset/raw/esc_beast_current.png                     mammoth on MAP
    dataset/truth_audit/map_beast_search_20260918/key/    probe frames

Measured separation for the mammoth sprite template: its own live frame
self-matches at distance 0 and ten frames without the sprite measure 66..82,
so the threshold (32) sits between the populations.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from winter_agent_v2 import runtime as runtime_module
from winter_agent_v2.beast_targets import is_dispatchable, load as load_targets, lookup_by_name
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.escalation_queue import capability_for_skill
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.vision import SemanticWorldVision
from winter_agent_v2.verifier import verify_beast_card_march_open, verify_beast_mammoth_target_selected

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "dataset/candidate/template_manifest.json"

MAMMOTH_FRAME = ROOT / "dataset/raw/esc_beast_current.png"
ATTACK_FRAME = (
    ROOT
    / "dataset/truth_audit/map_beast_search_20260918/key/go_20260918_014947_001_after_382_844.png"
)
GO_ONLY_FRAME = (
    ROOT
    / "dataset/truth_audit/map_beast_search_20260918/key/go_20260918_014947_000_before.png"
)
MUSK_OX_FRAME = ROOT / "dataset/raw/stamina_emergency/beast9_round3_target.png"


def _vision() -> SemanticWorldVision:
    return SemanticWorldVision(MANIFEST)


def _brain(goal: str = "BEAST_HUNT") -> RuleBrain:
    brain = RuleBrain()
    brain.current_goal = goal
    return brain


# -- templates ----------------------------------------------------------


def test_manifest_carries_the_two_route_records():
    payload = __import__("json").loads(MANIFEST.read_text(encoding="utf-8"))
    by_semantic: dict[str, list[dict]] = {}
    for row in payload["records"]:
        by_semantic.setdefault(row["semantic"], []).append(row)
    for semantic in ("TARGET_BEAST_MAMMOTH_5", "BTN_BEAST_CARD_ATTACK"):
        assert by_semantic.get(semantic), f"{semantic} missing from the manifest"
        for row in by_semantic[semantic]:
            # The click target must be inside the reviewed ROI: the executor
            # taps the found centre, so a crop that is not centred on the
            # control would tap next to it.
            roi = row["roi_norm"]
            assert 0.0 <= roi["x_norm"] and roi["x_norm"] + roi["w_norm"] <= 1.0
            assert 0.0 <= roi["y_norm"] and roi["y_norm"] + roi["h_norm"] <= 1.0
            assert Path(row["template_path"]).exists()


def test_mammoth_negative_frames_stay_below_the_gate():
    v = _vision()
    # The route must not propose a mammoth on frames that show the map without
    # the sprite or show other pages entirely (measured 66..82 on this corpus).
    for frame in (GO_ONLY_FRAME, ATTACK_FRAME, MUSK_OX_FRAME):
        assert v.semantic.find(frame, "TARGET_BEAST_MAMMOTH_5") is None, frame.name


# -- observation --------------------------------------------------------


def test_live_mammoth_frame_proposes_the_mammoth_target():
    w = _vision().observe(MAMMOTH_FRAME)
    assert w.page is Page.MAP
    assert w.beast.get("visible_target") == "MAMMOTH"
    assert w.beast.get("level") == 5
    assert is_dispatchable(w.beast)


def test_attack_card_frame_classifies_as_beast_with_attack_card():
    w = _vision().observe(ATTACK_FRAME)
    assert w.page is Page.BEAST
    # The 攻击 control is generic: the observation claims the control, never a
    # species identity it did not read.
    assert w.beast.get("attack_card") is True
    assert "name" not in w.beast


def test_go_only_card_frame_is_not_an_attack_card():
    # The giant-beast card with only 前往 must not fire the 攻击 branch --
    # measured live: this frame keeps the map classification.
    w = _vision().observe(GO_ONLY_FRAME)
    assert w.page is Page.MAP
    assert not w.beast.get("attack_card")


# -- brain --------------------------------------------------------------


def test_brain_selects_the_mammoth_target():
    reg = v2_registry()
    d = _brain().decide(
        WorldState(page=Page.MAP, beast={"visible_target": "MAMMOTH", "level": 5, "available": True}, confidence=0.99),
        reg,
    )
    assert d.skill == "SELECT_BEAST_TARGET_MAMMOTH"


def test_brain_opens_the_formation_from_the_attack_card():
    reg = v2_registry()
    d = _brain().decide(
        WorldState(page=Page.BEAST, beast={"attack_card": True}, confidence=0.99),
        reg,
    )
    assert d.skill == "ATTACK_BEAST_CARD"


def test_brain_musk_ox_route_is_unchanged():
    reg = v2_registry()
    d = _brain().decide(
        WorldState(page=Page.BEAST, beast={"name": "麝牛", "level": 9, "available": True}, confidence=0.99),
        reg,
    )
    assert d.skill == "BEAST_HUNT"


# -- verifiers ----------------------------------------------------------


def test_mammoth_selection_verifier_accepts_the_measured_pair():
    before = WorldState(page=Page.MAP, beast={"visible_target": "MAMMOTH", "level": 5, "available": True}, confidence=0.99)
    after = WorldState(page=Page.BEAST, beast={"attack_card": True}, confidence=0.99)
    assert verify_beast_mammoth_target_selected(before, after).ok
    # A march page is not a selection; an unidentified card is not the target.
    assert not verify_beast_mammoth_target_selected(before, WorldState(page=Page.MARCH, beast={"victory_assured": True}, confidence=0.99)).ok
    assert not verify_beast_mammoth_target_selected(
        WorldState(page=Page.MAP, beast={}, confidence=0.99), after
    ).ok


def test_attack_card_verifier_accepts_the_formation_page():
    before = WorldState(page=Page.BEAST, beast={"attack_card": True}, confidence=0.99)
    after = WorldState(page=Page.MARCH, beast={"victory_assured": True}, confidence=0.99)
    assert verify_beast_card_march_open(before, after).ok
    # The card still on screen is not an opened formation.
    assert not verify_beast_card_march_open(before, WorldState(page=Page.BEAST, beast={"attack_card": True}, confidence=0.99)).ok


# -- wiring -------------------------------------------------------------


def test_both_new_skills_are_bound_in_verified_atomic():
    bound = runtime_module.LiveRuntime.VERIFIED_ATOMIC
    assert bound.get("SELECT_BEAST_TARGET_MAMMOTH") is verify_beast_mammoth_target_selected
    assert bound.get("ATTACK_BEAST_CARD") is verify_beast_card_march_open


def test_both_new_skills_resolve_to_spend_stamina_on_beast():
    assert capability_for_skill("SELECT_BEAST_TARGET_MAMMOTH") == "SPEND_STAMINA_ON_BEAST"
    assert capability_for_skill("ATTACK_BEAST_CARD") == "SPEND_STAMINA_ON_BEAST"


def test_beast_table_allows_the_measured_mammoth_row():
    targets = load_targets()
    row = lookup_by_name("猛犸象", 5, targets)
    assert row is not None and row.dispatchable
    assert is_dispatchable({"visible_target": "MAMMOTH", "level": 5, "available": True}, targets)
