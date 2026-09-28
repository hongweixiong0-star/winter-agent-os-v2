from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from winter_agent_v2.hero_portraits import (
    evaluate_gather_formation,
    formation_slot_boxes,
    match_picker_hero,
    match_portrait,
    picker_card_selected,
    recognize_formation_heroes,
)
from winter_agent_v2.models import MarchState, Page, WorldState
from winter_agent_v2.verifier import (
    verify_gather_hero_picker_open,
    verify_gather_hero_picker_selected,
    verify_gather_hero_removed,
    verify_wood_dispatch_from_march,
)
from winter_agent_v2.hero_badge import remove_button_point
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.ocr import OCRPageClassifier, OCRResult, OCRToken


def _observation(occupied=(), *, availability="UNKNOWN"):
    occupied = {int(slot): (hero_id, identity) for slot, hero_id, identity in occupied}
    slots = []
    for slot in (1, 2, 3):
        if slot in occupied:
            hero_id, identity = occupied[slot]
            slots.append({"slot": slot, "state": "OCCUPIED", "hero_id": hero_id,
                          "identity_status": identity})
        else:
            slots.append({"slot": slot, "state": "EMPTY", "hero_id": None,
                          "identity_status": "NO_PORTRAIT_MATCH"})
    return {"status": "OBSERVED", "slots": slots,
            "empty_slots": [slot for slot in (1, 2, 3) if slot not in occupied],
            "specialist_availability": availability}


def test_match_portrait_reports_margin_and_abstains_for_blank(tmp_path):
    first = np.zeros((36, 36, 3), dtype=np.uint8)
    first[:, :18] = (230, 15, 40)
    first[::3, ::3] = (25, 225, 90)
    second = np.zeros((36, 36, 3), dtype=np.uint8)
    second[:18, :] = (15, 30, 235)
    second[::4, ::2] = (235, 220, 15)
    (tmp_path / "hero_a").mkdir()
    (tmp_path / "hero_b").mkdir()
    Image.fromarray(first).save(tmp_path / "hero_a/sample.png")
    Image.fromarray(second).save(tmp_path / "hero_b/sample.png")
    library = tmp_path / "index.json"
    library.write_text(json.dumps({"samples": {
        "HERO_A": {"display_name": "A", "portrait_samples": [{"path": "hero_a/sample.png"}]},
        "HERO_B": {"display_name": "B", "portrait_samples": [{"path": "hero_b/sample.png"}]},
    }}), encoding="utf-8")

    result = match_portrait(Image.fromarray(first), library_path=library)
    assert result["status"] == "IDENTITY_CONFIRMED"
    assert result["hero_id"] == "HERO_A"
    assert result["best_score"] > result["second_score"]
    assert result["margin"] >= 0.12
    assert match_portrait(Image.new("RGB", (36, 36), "black"), library_path=library)["status"] == "UNKNOWN"


def test_picker_match_is_page_gated_dynamic_and_compares_at_same_card(tmp_path):
    library = tmp_path / "index.json"
    rng = np.random.default_rng(418)
    target = rng.integers(0, 255, size=(51, 97, 3), dtype=np.uint8)
    other = rng.integers(0, 255, size=(51, 97, 3), dtype=np.uint8)
    Image.fromarray(target).save(tmp_path / "target.png")
    Image.fromarray(other).save(tmp_path / "other.png")
    library.write_text(json.dumps({"samples": {
        "HERO_TARGET": {"portrait_samples": [{"path": "target.png", "variant": "HERO_PICKER_FACE_CORE"}]},
        "HERO_OTHER": {"portrait_samples": [{"path": "other.png", "variant": "HERO_PICKER_FACE_CORE"}]},
    }}), encoding="utf-8")
    frame = Image.new("RGB", (720, 1280), (18, 35, 55))
    frame.paste(Image.fromarray(target), (210, 620))
    frame.paste(Image.fromarray(other), (420, 620))

    assert match_picker_hero(frame, "HERO_TARGET", picker_page_verified=False,
                             library_path=library)["status"] == "BLOCKED_PAGE_UNVERIFIED"
    result = match_picker_hero(frame, "HERO_TARGET", picker_page_verified=True,
                               library_path=library)
    assert result["status"] == "MATCHED"
    assert result["bbox"] == [210, 620, 97, 51]
    assert result["margin"] >= 0.12


def test_picker_selected_state_requires_all_four_corner_brackets():
    from winter_agent_v2.hero_portraits import picker_card_selected

    frame = Image.new("RGB", (720, 1280), (18, 35, 55))
    match = {"bbox": [238, 637, 97, 51]}
    draw = ImageDraw.Draw(frame)
    color = (255, 205, 0)
    # Measured selector brackets surround the card, outside the face template.
    for xy in [(211, 588, 231, 608), (342, 588, 362, 608),
               (211, 720, 231, 740), (342, 720, 362, 740)]:
        draw.rectangle(xy, fill=color)
    assert picker_card_selected(frame, match)
    draw.rectangle((342, 720, 362, 740), fill=(18, 35, 55))
    assert not picker_card_selected(frame, match)


def test_live_test_alt_picker_portraits_match_named_current_capture():
    root = Path("dataset/raw/ui_exploration/20260928")
    captures = (
        root / "frame_136_PICKER_CLORIS_ROW_VISIBLE.png",
        root / "frame_099_PICKER_R1C2_SELECTED.png",
    )
    if not all(path.exists() for path in captures):
        pytest.skip("workspace-only live picker captures are unavailable")
    cloris_frame = Image.open(root / "frame_136_PICKER_CLORIS_ROW_VISIBLE.png").convert("RGB")
    cloris = match_picker_hero(cloris_frame, "HERO_CLORIS", picker_page_verified=True)
    assert cloris["status"] == "MATCHED"
    assert cloris["best_score"] >= 0.93
    assert cloris["margin"] >= 0.12
    assert picker_card_selected(cloris_frame, cloris)
    assert cloris["hero_state"] == "SELECTED"

    flint_frame = Image.open(root / "frame_099_PICKER_R1C2_SELECTED.png").convert("RGB")
    flint = match_picker_hero(flint_frame, "HERO_FLINT", picker_page_verified=True)
    assert flint["status"] == "MATCHED"
    assert picker_card_selected(flint_frame, flint)
    assert flint["hero_state"] == "SELECTED"


def test_live_named_roster_portraits_keep_all_sixteen_identities_distinct():
    """Regression-check the new Greg identity against every card on the live roster."""
    from winter_agent_v2.hero_portraits import portrait_roi

    roster_capture = Path("dataset/raw/ui_exploration/20260928/frame_227_HERO_ROSTER_OPEN.png")
    if not roster_capture.exists():
        pytest.skip("workspace-only live roster capture is unavailable")
    frame = Image.open(roster_capture).convert("RGB")
    columns = [32, 199, 367, 532]
    rows = [112, 394, 676, 956]
    expected = [
        ["HERO_GREG", "HERO_ALONSO", "HERO_FLINT", "HERO_MOLLY"],
        ["HERO_GINA", "HERO_SERGEY", "HERO_MIA", "HERO_BASHITI"],
        ["HERO_JESSE", "HERO_PATRICK", "HERO_CLORIS", "HERO_EUGENE"],
        ["HERO_SMITH", "HERO_CHARLIE", "HERO_JASSER", "HERO_SHUYUN"],
    ]
    for row_index, y in enumerate(rows):
        for column_index, x in enumerate(columns):
            card = frame.crop((x, y, x + 154, y + 270))
            result = match_portrait(portrait_roi(card))
            assert result["status"] == "IDENTITY_CONFIRMED", (row_index, column_index, result)
            assert result["hero_id"] == expected[row_index][column_index], result
            assert result["margin"] >= 0.12, result


def test_live_picker_title_names_hero_selection_overlay():
    state = OCRPageClassifier().classify(
        OCRResult((OCRToken("英雄选择", 0.997, ((250, 135), (430, 135), (430, 170), (250, 170))),), "test"),
        frame_size=(720, 1280),
    )
    assert state.page is Page.POPUP
    assert state.popup == "HERO_PICKER"


def test_live_formation_recognizer_identifies_one_hero_and_two_empty_slots():
    from winter_agent_v2.hero_portraits import INDEX, LIBRARY

    library = json.loads(INDEX.read_text(encoding="utf-8"))["samples"]
    canvas = Image.new("RGB", (720, 1280), (11, 49, 91))
    draw = ImageDraw.Draw(canvas)
    hero_id = "HERO_EUGENE"
    sample = Image.open(LIBRARY / library[hero_id]["portrait_samples"][0]["path"]).convert("RGB")
    for number, (x, y, w, h) in enumerate(formation_slot_boxes(canvas.size), 1):
        draw.rounded_rectangle((x, y, x + w - 1, y + h - 1), radius=18, fill=(42, 91, 145))
        if number == 1:
            canvas.paste(sample, (x + 20, y + 28))
        else:
            cx, cy = x + w // 2, y + h // 2
            draw.rectangle((cx - 4, cy - 23, cx + 4, cy + 23), fill="white")
            draw.rectangle((cx - 23, cy - 4, cx + 23, cy + 4), fill="white")
    observed = recognize_formation_heroes(canvas)
    assert [(slot["state"], slot["hero_id"]) for slot in observed["slots"]] == [
        ("OCCUPIED", hero_id), ("EMPTY", None), ("EMPTY", None),
    ]
    assert observed["slots"][0]["identity_status"] == "IDENTITY_CONFIRMED"
    assert observed["slots"][0]["hero_state"] == "SELECTED"
    assert observed["slots"][1]["hero_state"] is None


def test_gather_policy_accepts_only_exact_specialist_or_confirmed_unavailable_empty():
    exact = _observation([(1, "HERO_EUGENE", "IDENTITY_CONFIRMED")])
    result = evaluate_gather_formation("WOOD", exact)
    assert result["status"] == "READY_WITH_SPECIALIST"
    assert result["expected_hero_id"] == "HERO_EUGENE"

    wrong = _observation([(1, "HERO_GINA", "IDENTITY_CONFIRMED")])
    result = evaluate_gather_formation("WOOD", wrong)
    assert result["status"] == "CLEANUP_REQUIRED"
    assert result["remove_slots"] == [1]

    unknown_identity = _observation([(2, None, "UNKNOWN")])
    result = evaluate_gather_formation("WOOD", unknown_identity)
    assert result["status"] == "CLEANUP_REQUIRED"
    assert result["remove_slots"] == [2]

    available_empty = evaluate_gather_formation("WOOD", _observation(availability="AVAILABLE"))
    assert available_empty["status"] == "SELECT_SPECIALIST_REQUIRED"
    unavailable_empty = evaluate_gather_formation("WOOD", _observation(availability="IN_USE"))
    assert unavailable_empty["status"] == "READY_EMPTY"
    unknown_empty = evaluate_gather_formation("WOOD", _observation())
    assert unknown_empty["status"] == "READY_EMPTY"
    assert unknown_empty["fallback_reason"] == "SPECIALIST_NOT_CONFIRMED_USE_EMPTY"


def test_unknown_specialist_availability_empty_fallback_can_pass_real_dispatch_verifier():
    before = WorldState(
        page=Page.MARCH,
        resource_target="WOOD",
    )
    formation = _observation(availability="UNKNOWN")
    formation.update({
        "page": "PAGE_FORMATION",
        "role_id": "test-alt-role",
        "role_scope": "LIVE_OBSERVED",
        "resource_type": "WOOD",
        "source_frame": "current-march-frame.png",
        "observed_at": before.timestamp,
    })
    before.hero_troop["gather_formation"] = formation
    after = WorldState(
        page=Page.MAP,
        marches=(MarchState.GATHERING,),
        march_used=1,
    )
    result = verify_wood_dispatch_from_march(before, after)
    assert result.ok
    assert result.evidence["gather_formation_policy"] == "READY_EMPTY"
    assert result.evidence["gather_formation_is_current_role_scoped"]


def test_gather_dispatch_verifier_rejects_missing_stale_or_cross_role_formation():
    after = WorldState(page=Page.MAP, marches=(MarchState.GATHERING,), march_used=1)
    missing = WorldState(page=Page.MARCH, resource_target="WOOD")
    result = verify_wood_dispatch_from_march(missing, after)
    assert not result.ok
    assert result.evidence["gather_formation_policy"] == "MISSING_CURRENT_ROLE_SCOPED_FORMATION"

    for changes in (
        {"role_scope": "PERSISTED", "role_id": "test-alt-role"},
        {"role_scope": "LIVE_OBSERVED", "role_id": "test-alt-role", "resource_type": "MEAT"},
        {"role_scope": "LIVE_OBSERVED", "role_id": "test-alt-role", "observed_at": "old-frame"},
    ):
        before = WorldState(page=Page.MARCH, resource_target="WOOD")
        formation = _observation(availability="UNKNOWN")
        formation.update({
            "page": "PAGE_FORMATION",
            "role_id": "test-alt-role",
            "role_scope": "LIVE_OBSERVED",
            "resource_type": "WOOD",
            "source_frame": "current-march-frame.png",
            "observed_at": before.timestamp,
            **changes,
        })
        before.hero_troop["gather_formation"] = formation
        result = verify_wood_dispatch_from_march(before, after)
        assert not result.ok
        assert result.evidence["gather_formation_policy"] == "STALE_OR_ROLE_UNSCOPED_FORMATION"


def test_unknown_resource_and_unknown_slot_never_become_dispatch_ready():
    empty = _observation(availability="IN_USE")
    assert evaluate_gather_formation("GEMS", empty)["status"] == "BLOCKED_UNKNOWN_RESOURCE"
    empty["slots"][0]["state"] = "UNKNOWN"
    empty["empty_slots"].remove(1)
    assert evaluate_gather_formation("WOOD", empty)["status"] == "BLOCKED_REOBSERVE"


def test_live_formation_remove_button_uses_current_scaled_geometry():
    frame = Image.new("RGB", (720, 1280), "navy")
    assert remove_button_point(frame, 1) == (238, 324)
    scaled = Image.new("RGB", (1080, 1920), "navy")
    assert remove_button_point(scaled, 1) == (357, 486)
    assert remove_button_point(frame, 4) is None


def test_remove_verifier_requires_an_occupied_to_empty_transition():
    before_obs = _observation([(1, "HERO_GINA", "IDENTITY_CONFIRMED")], availability="UNKNOWN")
    after_obs = _observation(availability="UNKNOWN")
    before = WorldState(page=Page.MARCH, hero_troop={"gather_formation": before_obs})
    after = WorldState(page=Page.MARCH, hero_troop={"gather_formation": after_obs})
    result = verify_gather_hero_removed(before, after)
    assert result.ok
    assert result.evidence["removed_slots"] == [1]

    unchanged = WorldState(page=Page.MARCH, hero_troop={"gather_formation": before_obs})
    assert not verify_gather_hero_removed(before, unchanged).ok


def test_live_runtime_attaches_fresh_role_scoped_formation_read(tmp_path):
    path = tmp_path / "march.png"
    Image.new("RGB", (720, 1280), (11, 49, 91)).save(path)
    runtime = object.__new__(LiveRuntime)
    runtime.role_id = "1063040265"
    runtime.role_scope = "LIVE_OBSERVED"
    world = WorldState(page=Page.MARCH, resource_target="WOOD")
    result = runtime._annotate_gather_formation(world, path)
    observed = result.hero_troop["gather_formation"]
    assert observed["status"] == "OBSERVED"
    assert observed["role_id"] == "1063040265"
    assert observed["role_scope"] == "LIVE_OBSERVED"
    assert observed["source_frame"] == str(path)
    assert observed["specialist_availability"] == "UNKNOWN"


def test_gather_dispatch_is_gated_by_current_formation_identity_and_availability():
    def decision(formation):
        return RuleBrain(current_goal="GATHER_RESOURCE").decide(
            WorldState(page=Page.MARCH, resource_target="WOOD", confidence=0.99,
                       hero_troop={"gather_formation": formation}),
            v2_registry(),
        )

    exact = _observation([(1, "HERO_EUGENE", "IDENTITY_CONFIRMED")], availability="IN_USE")
    exact.update({"role_scope": "LIVE_OBSERVED", "resource_type": "WOOD"})
    assert decision(exact).skill == "DISPATCH_MARCH"

    wrong = _observation([(2, "HERO_GINA", "IDENTITY_CONFIRMED")], availability="AVAILABLE")
    wrong.update({"role_scope": "LIVE_OBSERVED", "resource_type": "WOOD"})
    assert decision(wrong).skill == "CLEAR_GATHER_HEROES"

    unknown = _observation(availability="UNKNOWN")
    unknown.update({"role_scope": "LIVE_OBSERVED", "resource_type": "WOOD"})
    result = decision(unknown)
    assert result.skill == "DISPATCH_MARCH"
    assert result.expected_result == "gather_march_dispatched"


def test_gather_picker_goal_selects_only_a_current_exact_specialist():
    brain = RuleBrain(current_goal="GATHER_RESOURCE")

    def decision(*, match="MATCHED", available="AVAILABLE", selected=False):
        picker = {
            "open": True,
            "role_scope": "LIVE_OBSERVED",
            "role_id": "1063040265",
            "hero_id": "HERO_CLORIS",
            "match_status": match,
            "specialist_availability": available,
            "selected": selected,
        }
        return brain.decide(WorldState(page=Page.POPUP, popup="HERO_PICKER", confidence=0.99,
                                       hero_troop={"hero_picker": picker}), v2_registry())

    assert decision().skill == "SELECT_GATHER_HERO"
    assert decision(selected=True).skill == "ASSIGN_GATHER_HERO"
    assert decision(match="UNKNOWN").skill == "BACK"
    assert decision(match="AMBIGUOUS").skill == "BACK"
    assert decision(match="NO_PICKER_SAMPLE").skill == "BACK"
    # A current match may be tapped to test selectability; only its gold
    # selection brackets allow the following assign action.
    assert decision(available="UNKNOWN").skill == "SELECT_GATHER_HERO"


def test_gather_picker_runtime_annotation_is_live_and_role_scoped():
    frame_path = Path(
        "dataset/raw/ui_exploration/20260928/frame_136_PICKER_CLORIS_ROW_VISIBLE.png"
    )
    if not frame_path.exists():
        pytest.skip("workspace-only live picker capture is unavailable")
    runtime = object.__new__(LiveRuntime)
    runtime.role_id = "1063040265"
    runtime.role_scope = "LIVE_OBSERVED"
    runtime._active_gather_resource = "MEAT"
    world = WorldState(page=Page.POPUP, popup="HERO_PICKER", resource_target="MEAT")

    result = runtime._annotate_gather_picker(world, frame_path)
    picker = result.hero_troop["hero_picker"]
    assert picker["hero_id"] == "HERO_CLORIS"
    assert picker["match_status"] == "MATCHED"
    assert picker["specialist_availability"] == "SELECTABILITY_UNVERIFIED"
    assert picker["role_id"] == "1063040265"
    assert picker["role_scope"] == "LIVE_OBSERVED"
    assert picker["source_frame"] == str(frame_path)


def test_gather_picker_verifiers_require_live_page_transition_and_same_role():
    before = WorldState(page=Page.MARCH, popup=None)
    after = WorldState(page=Page.POPUP, popup="HERO_PICKER", hero_troop={
        "hero_picker": {"open": True, "role_scope": "LIVE_OBSERVED", "role_id": "r1"}
    })
    assert verify_gather_hero_picker_open(before, after).ok

    selected_before = WorldState(page=Page.POPUP, popup="HERO_PICKER", hero_troop={
        "hero_picker": {"hero_id": "HERO_CLORIS", "source_frame": "a", "role_id": "r1"}
    })
    selected_after = WorldState(page=Page.POPUP, popup="HERO_PICKER", hero_troop={
        "hero_picker": {"hero_id": "HERO_CLORIS", "match_status": "MATCHED", "selected": True,
                        "source_frame": "b", "role_id": "r1"}
    })
    assert verify_gather_hero_picker_selected(selected_before, selected_after).ok
    selected_after.hero_troop["hero_picker"]["role_id"] = "r2"
    assert not verify_gather_hero_picker_selected(selected_before, selected_after).ok


def test_live_hero_picker_semantics_are_registered_as_candidates():
    from pathlib import Path

    payload = json.loads(Path("knowledge/ui/semantic_dictionary.json").read_text(encoding="utf-8"))
    records = {row["id"]: row for row in payload["records"]}
    expected = {"PAGE_HERO_PICKER", "HERO_PICKER_CARD_DYNAMIC", "HERO_SLOT_EMPTY", "BTN_HERO_PICKER_ASSIGN"}
    assert expected <= records.keys()
    assert all(records[key]["status"] == "CANDIDATE" for key in expected)
    assert records["HERO_PICKER_CARD_DYNAMIC"]["preconditions"]
    assert records["BTN_HERO_PICKER_ASSIGN"]["verification"]["postcondition"]


def test_gather_picker_skills_are_registered_and_enabled_for_live_runtime():
    registry = v2_registry()
    skill_ids = {skill.id for skill in registry.all()}
    required = {"OPEN_GATHER_HERO_PICKER", "SELECT_GATHER_HERO", "ASSIGN_GATHER_HERO"}
    assert required <= skill_ids
    assert required <= LiveRuntime.VERIFIED_ATOMIC.keys()
    assert all(registry.get(skill_id).state.value == "CANDIDATE" for skill_id in required)
