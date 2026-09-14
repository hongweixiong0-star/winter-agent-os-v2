"""Regression: the beast Intel target card must be recognized on the live client.

Measured failure this fixes (2026-09-14, live INTEL run):

    SELECT_INTEL_BEAST_MISSION  verifier OK   (dialog opened)
    OPEN_INTEL_BEAST_TARGET     verifier FAIL evidence {"mission_dialog": true, "target": false}

The tap itself was correct -- ``BTN_INTEL_VIEW_TARGET`` matched at distance 6 and
its centre (0.5, 0.73) sat exactly on the 前往查看 label (OCR box px 292,914-428,955).
The real problem was that the client put the result on the *world map* as a target
card, and every beast template in the manifest had gone stale:

    BTN_BEAST_START_MARCH   best distance 30   (threshold 8)
    DIALOG_BEAST_TARGET     best distance 14
    BTN_BEAST_DISPATCH      best distance 36

so ``vision.py`` returned ``Page.MAP`` and ``verify_intel_target_open`` -- which
requires ``Page.BEAST`` with a matching mission id and level -- could never pass.
``BTN_BEAST_START_MARCH`` is doubly load-bearing: it is the page evidence *and*
the tap target of ``INTEL_BEAST_START_MARCH`` (the 出征 button).

The fixtures are the real frames from that run.  The card's content is
independently checkable: 等级22大角鹿 / 推荐实力 5,107,044 / 出征 costs 10 stamina,
which are exactly the values the verifier asserts for ``INTEL_BEAST_10``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.live_stack import production_vision

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "dataset/truth_audit/intel_beast_target_20260914"
DIALOG = FIXTURE / "01_intel_beast_mission_dialog.png"
CARD = FIXTURE / "02_beast_target_card_on_map.png"
EMPTY_INTEL = FIXTURE / "03_intel_page_empty_list.png"
MANIFEST = ROOT / "dataset/candidate/template_manifest.json"


def _fixture(path: Path) -> Path:
    if not path.is_file():
        pytest.skip(f"live fixture missing: {path.relative_to(ROOT)}")
    return path


def test_target_card_is_recognized_as_the_beast_page() -> None:
    from winter_agent_v2.models import Page

    vision = production_vision()
    if vision is None:
        pytest.skip("OCR runtime unavailable")
    state = vision.observe(_fixture(CARD))
    assert state.page is Page.BEAST, f"card classified as {state.page.value}"
    assert state.beast.get("mission_id") == "INTEL_BEAST_10"
    assert state.beast.get("level") == 22
    assert state.beast.get("available") is True
    # The recommended power is printed on the card; if the template were
    # matching the wrong card this would not line up.
    assert state.beast.get("recommended_power") == 5_107_044
    assert state.beast.get("stamina_cost_displayed") == 10


def test_intel_target_verifier_passes_on_the_live_pair() -> None:
    from winter_agent_v2.verifier import verify_intel_target_open

    vision = production_vision()
    if vision is None:
        pytest.skip("OCR runtime unavailable")
    before = vision.observe(_fixture(DIALOG))
    after = vision.observe(_fixture(CARD))
    result = verify_intel_target_open(before, after)
    assert result.ok, result.evidence
    assert result.evidence == {"mission_dialog": True, "target": True}


def test_verifier_rejects_when_the_target_never_opened() -> None:
    """Negative control: the same dialog twice must NOT count as a target."""
    from winter_agent_v2.verifier import verify_intel_target_open

    vision = production_vision()
    if vision is None:
        pytest.skip("OCR runtime unavailable")
    dialog = vision.observe(_fixture(DIALOG))
    assert not verify_intel_target_open(dialog, dialog).ok


def test_plain_map_frame_is_not_a_target_card() -> None:
    """The re-registered template must not fire on an ordinary map frame."""
    from winter_agent_v2.models import Page
    from winter_agent_v2.vision import SemanticWorldVision

    plain = ROOT / "dataset/truth_audit/hud_stamina_20260914/map_hud_with_stamina_200.png"
    if not plain.is_file():
        pytest.skip("map fixture missing")
    state = SemanticWorldVision(MANIFEST).observe(plain)
    assert state.page is Page.MAP
    assert state.beast == {}


def test_the_button_template_carries_the_measured_geometry() -> None:
    """The 出征 button is the tap target, so its ROI must stay measured."""
    from winter_agent_v2.vision import SemanticWorldVision

    semantic = SemanticWorldVision(MANIFEST).semantic
    match = semantic.find(_fixture(CARD), "BTN_BEAST_START_MARCH")
    assert match is not None and match.distance <= 8, (
        "the current-client 出征 button template no longer matches; re-measure it"
        " with tools/register_beast_target_templates.py"
    )
    # Measured px (241,583)-(476,651) on 720x1280 -> centre (0.4979, 0.4820).
    assert abs(match.center_norm[0] - 0.4979) < 0.01
    assert abs(match.center_norm[1] - 0.4820) < 0.01


def test_empty_intel_list_is_reported_not_left_unknown() -> None:
    """A visible-but-empty Intel list must not dead-end the goal.

    Before: ``PAGE_INTEL`` matched, no mission template matched, so the state was
    ``status=UNKNOWN`` and the brain could only answer ``SAFE_STOP
    intel_state_unknown`` -- indistinguishable from a vision failure.

    Now the two states are separated by OCR evidence measured on the live client:
    a card shows 前往查看, an empty list shows only the 下次刷新 header.
    """
    from winter_agent_v2.models import Page

    vision = production_vision()
    if vision is None:
        pytest.skip("OCR runtime unavailable")
    state = vision.observe(_fixture(EMPTY_INTEL))
    assert state.page is Page.INTEL
    assert state.intel.get("status") == "NOT_AVAILABLE"
    assert state.intel.get("list_read") is True
    assert state.intel.get("available_count") == 0
    # The refresh countdown is real evidence that the page rendered.
    assert state.intel.get("refresh")


def test_empty_intel_list_stops_with_a_meaningful_reason() -> None:
    from winter_agent_v2.brain import RuleBrain
    from winter_agent_v2.skills import v2_registry

    vision = production_vision()
    if vision is None:
        pytest.skip("OCR runtime unavailable")
    state = vision.observe(_fixture(EMPTY_INTEL))
    decision = RuleBrain(current_goal="INTEL").decide(state, v2_registry())
    assert decision.skill == "SAFE_STOP"
    assert decision.reason == "intel_not_available", decision.reason
    accepted = (ROOT / "tools/run_live.py").read_text(encoding="utf-8")
    assert '"intel_not_available"' in accepted, (
        "run_live.py must treat 'no intel missions available' as an accepted stop,"
        " otherwise a legitimately idle account reports a failed run"
    )


def test_intel_list_states_are_never_inferred_from_template_absence() -> None:
    """Documents why the empty-list rule uses OCR keywords.

    The card templates do go stale (that is exactly what broke
    ``OPEN_INTEL_BEAST_TARGET``), so "no template matched" is not evidence of an
    empty list -- it is evidence of nothing.
    """
    source = (ROOT / "winter_agent_v2/ocr.py").read_text(encoding="utf-8")
    assert "下次刷新" in source and "前往查看" in source
    assert "NOT_AVAILABLE" in source


def test_the_legacy_button_records_are_kept_for_provenance() -> None:
    """A current-client record was *added*; history is not rewritten.

    ``SemanticROIVision.find`` picks the best match across all records for a
    semantic, so the stale layout stays in the manifest as provenance without
    affecting behaviour.
    """
    import json

    records = json.loads(MANIFEST.read_text(encoding="utf-8"))["records"]
    gears = [r for r in records if r["semantic"] == "BTN_BEAST_START_MARCH"]
    assert len(gears) >= 2, "expected the legacy record(s) plus the measured one"
    assert any(r["roi_norm"]["y_norm"] < 0.6 for r in gears), "the measured record is missing"
