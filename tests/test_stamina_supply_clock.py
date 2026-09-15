"""The free gift's supply clock: read it, store it, and stop paying for it.

Context (2026-09-15, all LIVE_CLIENT measurements)

The free 丰盛的招待 gift (+150 stamina) is the cheapest stamina in the game and
the operator directive says it must be claimed.  Two problems made it expensive
to claim:

1. ``0au`` -- the check lives in the world-map branch of the brain, but the
   unattended intel loop spends its whole run on the intel page.  Measured
   04:10:33Z: a run that began on an intel pin popup never stood on the map
   once, so the check could not run at all.

2. ``0e`` -- the panel is the only place the gift is visible, so a blind
   once-per-run check costs about 16 actions an hour (8 cycles x 2 actions)
   to find a gift that arrives every 7 hours.

The countdown fixes both: it turns "go and look" into a dated event.  These
tests pin the three things that can silently break it -- parsing, persistence,
and the direction of the unknown case.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.ocr import OCRToken, read_next_supply_seconds
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.stamina_supply import StaminaSupplyStore

FRAME = Path("dataset/truth_audit/free_stamina_claim_20260915")
FRAME_AFTER_CLAIM = FRAME / "04_panel_after_claim_stamina_152_live.png"


def token(text: str, confidence: float = 0.94) -> OCRToken:
    return OCRToken(text=text, confidence=confidence, box=((0, 0), (10, 0), (10, 10), (0, 10)))


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def test_a_real_countdown_parses_to_seconds() -> None:
    # Read at 04:12:26Z on the panel right after the claim; implies 11:00:01Z.
    assert read_next_supply_seconds((token("06:47:35"),)) == 6 * 3600 + 47 * 60 + 35


def test_a_short_countdown_is_not_treated_as_missing() -> None:
    # 00:00:15 at 03:59:46.7Z is the frame that proved the cadence: it implied
    # 04:00:01Z, exactly 7 hours before the post-claim instant.
    assert read_next_supply_seconds((token("00:00:15"),)) == 15


def test_the_label_beside_the_countdown_does_not_confuse_the_reader() -> None:
    # The panel draws 下次补给 on the line above the number, and OCR returns
    # both.  A stray label must not be read as a value.
    tokens = (token("下次补给", 0.98), token("00:55:33", 0.952))
    assert read_next_supply_seconds(tokens) == 55 * 60 + 33


def test_a_claimable_panel_reports_no_countdown() -> None:
    # On a claimable panel the green 领取 button sits where the countdown
    # would be, so the only token in the row is the button itself.
    assert read_next_supply_seconds((token("领取", 0.997),)) is None


def test_an_out_of_range_field_is_rejected_rather_than_wrapped() -> None:
    # "00:99:99" is not a time.  Silently folding it into 1h40m39s would invent
    # a supply instant out of an OCR misread.
    assert read_next_supply_seconds((token("00:99:99"),)) is None


def test_low_confidence_tokens_are_ignored() -> None:
    assert read_next_supply_seconds((token("06:47:35", 0.40),)) is None


def test_the_parser_never_returns_zero_for_absence() -> None:
    # 0 would mean "due right now" to a naive caller.  Absence must be None.
    result = read_next_supply_seconds(())
    assert result is None
    assert result != 0


@pytest.mark.skipif(not FRAME_AFTER_CLAIM.exists(), reason="archived live frame not present")
def test_the_countdown_round_trips_on_the_archived_live_panel() -> None:
    """The parser must still read the very frame the cadence was measured on."""
    pytest.importorskip("PIL")
    from winter_agent_v2.ocr import NEXT_SUPPLY_ROI, OCRService, RapidOCRBackend

    ocr = OCRService(RapidOCRBackend())
    tokens = ocr.recognize(FRAME_AFTER_CLAIM, NEXT_SUPPLY_ROI).tokens
    assert read_next_supply_seconds(tokens) == 6 * 3600 + 47 * 60 + 35


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------


def test_recording_a_countdown_stores_an_absolute_aware_instant(tmp_path: Path) -> None:
    store = StaminaSupplyStore(tmp_path / "supply.json")
    at = datetime(2026, 9, 15, 4, 12, 26, tzinfo=timezone.utc)
    instant = store.record(6 * 3600 + 47 * 60 + 35, at=at)
    assert instant == datetime(2026, 9, 15, 11, 0, 1, tzinfo=timezone.utc)
    assert store.next_supply_at() == instant


def test_a_missing_file_means_unknown_and_never_due(tmp_path: Path) -> None:
    store = StaminaSupplyStore(tmp_path / "does_not_exist.json")
    assert store.next_supply_at() is None
    # The optimisation must fail *open* toward claiming: unknown is not due,
    # and the brain falls back to its historical once-per-run check.
    assert store.is_due() is False


def test_a_corrupt_file_is_not_allowed_to_break_a_run(tmp_path: Path) -> None:
    path = tmp_path / "supply.json"
    path.write_text("{not json at all", encoding="utf-8")
    store = StaminaSupplyStore(path)
    assert store.next_supply_at() is None
    assert store.is_due() is False


def test_a_naive_timestamp_is_rejected_instead_of_guessed(tmp_path: Path) -> None:
    path = tmp_path / "supply.json"
    path.write_text(json.dumps({"next_supply_at": "2026-09-15T11:00:01"}), encoding="utf-8")
    # Comparing a naive instant against an aware "now" raises TypeError, which
    # would kill the run.  Treat it as absent instead.
    assert StaminaSupplyStore(path).next_supply_at() is None


def test_due_flips_only_once_the_instant_has_passed(tmp_path: Path) -> None:
    store = StaminaSupplyStore(tmp_path / "supply.json")
    store.record(3600, at=datetime(2026, 9, 15, 4, 0, 0, tzinfo=timezone.utc))
    instant = datetime(2026, 9, 15, 5, 0, 0, tzinfo=timezone.utc)
    assert store.is_due(at=instant - timedelta(seconds=1)) is False
    assert store.is_due(at=instant) is True
    assert store.is_due(at=instant + timedelta(hours=1)) is True


# --------------------------------------------------------------------------
# The brain's routing decision
# --------------------------------------------------------------------------


def map_world() -> WorldState:
    return WorldState(page=Page.MAP, confidence=1.0)


def intel_world(pins: int = 3) -> WorldState:
    return WorldState(page=Page.INTEL, confidence=1.0, intel={"status": "AVAILABLE", "pins": pins})


def test_an_unknown_clock_still_runs_the_check_once_per_run() -> None:
    """Unknown must not be able to skip the gift.

    This is the direction that matters.  A wrong "not due" silently loses 150
    stamina every 7 hours; a wrong "due" costs two actions.  The two failures
    are not symmetric, so unknown resolves to "go and look".
    """
    brain = RuleBrain(claim_free_stamina=True)
    assert brain.next_supply_at is None
    decision = brain.decide(map_world(), v2_registry())
    assert decision.skill == "OPEN_STAMINA_SOURCES"


def test_a_known_future_supply_defers_the_check() -> None:
    brain = RuleBrain(claim_free_stamina=True)
    brain.next_supply_at = datetime.now(timezone.utc) + timedelta(hours=3)
    decision = brain.decide(map_world(), v2_registry())
    assert decision.skill != "OPEN_STAMINA_SOURCES"


def test_a_due_supply_triggers_the_check() -> None:
    brain = RuleBrain(claim_free_stamina=True)
    brain.next_supply_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    decision = brain.decide(map_world(), v2_registry())
    assert decision.skill == "OPEN_STAMINA_SOURCES"


def test_a_supply_due_in_seconds_is_already_worth_looking() -> None:
    # The countdown is second-accurate and the panel opens a step or two later,
    # so a supply about to arrive must not be missed by a whole cycle.
    brain = RuleBrain(claim_free_stamina=True)
    brain.next_supply_at = datetime.now(timezone.utc) + timedelta(seconds=20)
    decision = brain.decide(map_world(), v2_registry())
    assert decision.skill == "OPEN_STAMINA_SOURCES"


def test_the_check_still_runs_at_most_once_per_run() -> None:
    brain = RuleBrain(claim_free_stamina=True)
    brain.next_supply_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    first = brain.decide(map_world(), v2_registry())
    assert first.skill == "OPEN_STAMINA_SOURCES"
    brain.stamina_panel_checked = True
    second = brain.decide(map_world(), v2_registry())
    assert second.skill != "OPEN_STAMINA_SOURCES"


def test_the_intel_page_routes_to_the_map_when_the_gift_is_due() -> None:
    """`0au`: the loop lives on the intel page, so the check must be reachable.

    Without this the panel is never opened by the unattended loop at all, no
    matter how cheap the check became.
    """
    brain = RuleBrain(claim_free_stamina=True, current_goal="INTEL")
    brain.next_supply_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    decision = brain.decide(intel_world(), v2_registry())
    assert decision.skill == "BACK"
    assert v2_registry().get(decision.skill).ready(intel_world())
    assert decision.reason == "free_stamina_gift_is_due_go_to_the_map"
    # It must not be marked as done yet -- the panel has not been looked at.
    assert brain.stamina_panel_checked is False


def test_the_intel_page_does_not_detour_when_the_supply_is_far_off() -> None:
    brain = RuleBrain(claim_free_stamina=True, current_goal="INTEL")
    brain.next_supply_at = datetime.now(timezone.utc) + timedelta(hours=5)
    decision = brain.decide(intel_world(), v2_registry())
    assert decision.skill != "BACK"


def test_the_intel_page_still_works_when_nothing_is_due() -> None:
    """The detour must not break the intel chain it interrupts."""
    brain = RuleBrain(claim_free_stamina=True, current_goal="INTEL")
    brain.stamina_panel_checked = True
    decision = brain.decide(intel_world(), v2_registry())
    assert decision.skill == "SELECT_INTEL_PIN"


def test_the_detour_is_bounded_to_one_map_trip_per_run() -> None:
    brain = RuleBrain(claim_free_stamina=True, current_goal="INTEL")
    brain.next_supply_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    assert brain.decide(intel_world(), v2_registry()).skill == "BACK"
    # Once the map has been visited the flag is set and the loop stays on task.
    brain.stamina_panel_checked = True
    assert brain.decide(intel_world(), v2_registry()).skill != "BACK"


def test_the_detour_is_off_when_the_operator_disables_free_stamina() -> None:
    brain = RuleBrain(claim_free_stamina=False, current_goal="INTEL")
    brain.next_supply_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    decision = brain.decide(intel_world(), v2_registry())
    assert decision.skill != "BACK"


def test_the_map_check_respects_the_stateless_default_constructor() -> None:
    """A brain built without the flag must not start opening the panel."""
    brain = RuleBrain()
    decision = brain.decide(map_world(), v2_registry())
    assert decision.skill != "OPEN_STAMINA_SOURCES"
