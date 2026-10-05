"""Pin why ``CLEAR_INTEL`` can pass its verifier and still advance nothing.

`CLEAR_INTEL`'s recorded blocker says exactly that:

    capability READ_INTEL_LIST, state DEFERRED, source NO_GOAL_PROGRESS,
    reason "3 consecutive production episodes passed their verifier and advanced no part of
    this goal", failure_signature "READ_INTEL_LIST|NO_GOAL_PROGRESS|OPEN_MAP"

That sentence names two judges that turn out to read two different fields:

  * the verifier, ``verify_intel_list_read`` (registered at ``runtime.py:411``), requires
    ``after.intel["list_read"] is True`` plus a status word;
  * the goal's meter, ``goal_library._observation_meter`` for ``CLEAR_INTEL``, requires
    ``evidence["untried_pins"]``, which ``runtime.py:8994`` stamps **only** when the frame is
    the board itself: ``page is INTEL and not intel["mission_type"]``.

These tests pin the consequence rather than the prose: a frame can satisfy either one, and on
the live client no frame satisfies both. They deliberately assert the two conditions
*separately* so that a future change which makes one frame satisfy both has to fail here and be
looked at, instead of quietly passing.

Nothing here is device-dependent except the last test, which skips with a reason when the
captured frame is absent (evidence frames are gitignored).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: The board captured live on 2026-10-05T08:13Z: PAGE_INTEL, seven pins drawn, reading
#: {status: CLAIMABLE, claimable_count: 1, stamina: 35} -- i.e. with a reward ready and no count.
BOARD_EVIDENCE = ROOT / "dataset/evidence/intel_panel_observe_20261005T081303"
BOARD_FRAME = BOARD_EVIDENCE / "n2_look.png"
BOARD_PIN_COUNT = 7

#: The same page four minutes later (2026-10-05T08:17Z): nothing claimable, so the reading
#: carries available_count=9 / pins=9 / list_read=True while the board draws nine pins.
RECOUNT_EVIDENCE = ROOT / "dataset/evidence/intel_panel_observe_20261005T081721"
RECOUNT_FRAME = RECOUNT_EVIDENCE / "n1_look.png"
RECOUNT_PIN_COUNT = 9


def _goal(evidence: dict):
    from winter_agent_v2.goal_library import GoalState, GoalStatus

    return GoalState("CLEAR_INTEL", GoalStatus.READY, evidence=evidence, distance=1.0)


def _would_stamp(state) -> bool:
    """``runtime.py:8994``'s test, evaluated -- not copied.

    The runtime only stamps ``untried_pins`` / ``detected_pins`` onto the intel reading when the
    frame is the board and no mission card has been opened from it.
    """
    from winter_agent_v2.models import Page

    return state.page is Page.INTEL and not state.intel.get("mission_type")


def test_a_board_that_was_not_counted_yields_no_meter() -> None:
    """An absent ``untried_pins`` must read as *unobserved*, and must not invent a meter.

    ``goal_library`` is explicit that this is the difference between "not measured" and "no
    progress": when the field is missing the meter returns ``None`` and the goal falls back to
    its constant ``distance``. That fallback is what makes ``1.0 < 1.0`` False forever, which is
    how real work was reported as no work.
    """
    from winter_agent_v2.goal_library import _meter_for, _observation_meter

    uncounted = _goal({"status": "AVAILABLE", "untried_pins": None})
    assert _observation_meter(uncounted) is None, (
        "an uncounted board must not produce a meter"
    )
    assert _meter_for(uncounted) == 1.0, (
        "with no meter the goal falls back to its constant distance, which is what makes "
        "every later comparison 1.0 < 1.0 and therefore False"
    )

    counted = _goal({"status": "AVAILABLE", "untried_pins": BOARD_PIN_COUNT})
    # Negated on purpose: progress_moved compares with > for observation meters, and the raw
    # count falls as work is done, so the meter is stored negated (goal_library.py:2602-2614).
    assert _observation_meter(counted) == -float(BOARD_PIN_COUNT)


def test_the_verifier_and_the_meter_read_independent_fields() -> None:
    """The two verdicts come from different fields, so neither one implies the other.

    Uses the two shapes that actually occur: a board whose reading was counted but never
    annotated as read, and a mission-dialog-derived reading (``list_read`` plus a
    ``mission_type``) -- the latter is precisely the evidence shape ``learning/goal_state.json``
    was holding for ``CLEAR_INTEL``, read off a dialog frame.

    NOTE, because the first version of this test got it wrong: this asserts the fields are
    INDEPENDENT, not that no frame can satisfy both. A later live capture did satisfy both at
    once (see ``test_a_claimable_board_loses_the_count...``), and claiming exclusivity would
    have been a claim the client does not support.
    """
    from winter_agent_v2.models import Page, WorldState
    from winter_agent_v2.verifier import verify_intel_list_read

    uncounted = WorldState(
        page=Page.INTEL,
        intel={"status": "CLAIMABLE", "claimable_count": 1, "stamina": 35},
    )
    dialog = WorldState(
        page=Page.INTEL,
        intel={"status": "AVAILABLE", "list_read": True,
               "mission_type": "HERO_JOURNEY", "mission_level": 10},
    )

    # A frame can carry the meter's precondition while the verifier refuses it ...
    assert not verify_intel_list_read(uncounted, uncounted).ok
    assert _would_stamp(uncounted)

    # ... and a frame can pass the verifier while the meter's precondition is absent.
    assert verify_intel_list_read(dialog, dialog).ok
    assert not _would_stamp(dialog)

    # So "passed its verifier" is not evidence that the goal could report progress.
    for name, state in (("uncounted", uncounted), ("dialog", dialog)):
        verifier_ok = verify_intel_list_read(state, state).ok
        stamped = _would_stamp(state)
        assert verifier_ok != stamped, (
            f"the {name} frame now agrees on both verdicts; this test exists to keep the two "
            "fields visibly separate, so re-read both halves before relaxing it"
        )


def test_a_claimable_board_loses_the_count_that_the_page_carries_when_it_is_not_claimable() -> None:
    """The same page reads WITH a count and WITHOUT one, depending on whether a reward is ready.

    Measured on the live client four minutes apart:

      08:13Z  something was claimable (一键领取 was drawn): status=CLAIMABLE and the reading
              carried only {status, claimable_count, stamina} -- no available_count, no pins,
              no list_read at all -- while the board drew SEVEN pins.
      08:17Z  nothing was claimable: status=AVAILABLE and the reading carried
              available_count=9, pins=9, list_read=True, while the board drew NINE pins.

    Both frames are the same page. The cause is ``ocr.py:6116``: the pin counter runs only when
    the status is ``UNKNOWN``, and the template layer answers ``CLAIMABLE`` before control ever
    reaches it. So the reading's SHAPE depends on whether a reward happens to be sitting there --
    and ``verify_intel_list_read``, which needs ``list_read``, is only satisfiable on the half
    that happens to carry the count.

    This is why the count half of ``intel_count_and_status_known`` cannot be relied on, and it is
    a stronger statement than "the field is missing": the field arrives and leaves on its own.
    """
    claimable = BOARD_EVIDENCE / "n2_look.png"
    counted = RECOUNT_EVIDENCE / "n1_look.png"
    for path in (claimable, counted):
        if not path.is_file():
            pytest.skip(f"captured frame absent (gitignored): {path}")

    from winter_agent_v2.ocr import (
        HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend,
    )
    from winter_agent_v2.vision import SemanticWorldVision
    import json

    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(cfg["ocr"]["module_path"]))))
    hybrid = HybridVision(
        SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json"), ocr
    )

    a = dict(hybrid.observe(claimable).intel or {})
    b = dict(hybrid.observe(counted).intel or {})

    # The claimable half carries no count at all ...
    assert a.get("status") == "CLAIMABLE"
    for field in ("available_count", "pins", "list_read"):
        assert field not in a, (
            f"the claimable board now carries {field!r}; if the counter was widened past its "
            f"status gate, this test and the record both need revisiting. keys: {sorted(a)}"
        )
    # ... and the half without a ready reward carries both the count and list_read.
    assert b.get("status") == "AVAILABLE"
    assert isinstance(b.get("pins"), int) and b["pins"] > 0, (
        f"the non-claimable board used to carry a real pin count; got {b.get('pins')!r}"
    )
    assert b.get("list_read") is True, (
        "list_read is what the verifier keys on, and it only appears together with the count"
    )


def test_the_live_board_draws_pins_that_the_reading_does_not_count() -> None:
    """On the captured board, the reading carries no count while the board draws seven.

    This is the half of ``intel_count_and_status_known`` that fails: the production reading has
    no field for "how many missions are on this board". ``claimable_count`` is not it -- it
    counts ready rewards, and the board read ``claimable_count=1`` while holding seven pins.
    """
    if not BOARD_FRAME.is_file():
        pytest.skip(f"captured frame absent (gitignored): {BOARD_FRAME}")

    from winter_agent_v2.intel_pins import intel_pin_centers
    from winter_agent_v2.ocr import (
        HybridVision,
        OCRService,
        RapidOCRBackend,
        ResilientOCRBackend,
    )
    from winter_agent_v2.vision import SemanticWorldVision
    import json

    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(cfg["ocr"]["module_path"]))))
    hybrid = HybridVision(
        SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json"), ocr
    )

    state = hybrid.observe(BOARD_FRAME)
    intel = dict(state.intel or {})
    pins = intel_pin_centers(BOARD_FRAME)

    assert str(getattr(state.page, "value", state.page)) == "INTEL"
    assert len(pins) == BOARD_PIN_COUNT, (
        f"this frame drew {BOARD_PIN_COUNT} pins when it was captured; the detector now says "
        f"{len(pins)}. Re-measure before trusting the count below."
    )
    for field in ("pins", "detected_pins", "available_count", "untried_pins", "list_read"):
        assert field not in intel, (
            f"the reading now carries {field!r}; the count half may have been wired, in which "
            f"case this test and the record both need revisiting. reading keys: {sorted(intel)}"
        )
    assert intel.get("status") in {"AVAILABLE", "CLAIMABLE"}, (
        "the captured board was claimable; a different status means this is another frame"
    )
