"""March capacity must be observed per role, and the reservation must follow it.

Master directive (2026-09-16) sections 7-10 and 24: march capacity is role-scoped
and dynamic, must come from the client rather than from a furnace-level rule, and
the reservation must be a *policy over facts* rather than a fixed number of slots.

Two defects were measured today, both live:

1. ``world/flight`` -- the 2026-09-16 live client runs at **capacity 2**.  With
   ``reserve_for_stamina = 2`` the condition ``idle_marches <= reserve`` was already
   true after a single dispatch, so three consecutive GATHER_RESOURCE runs answered
   ``SAFE_STOP reserved_march_for_stamina`` and produced **no episode at all**.  The
   same constant is reasonable for the 6-slot role it was written for, which is the
   whole point: the number is not a constant, it is a function of capacity.

2. ``vision.py`` wrote **invented** march counts: four beast/hero status branches
   returned ``march_used=1/2/5/6`` against a fixed ``march_max=6``, and the page
   model's default capacity was 6.  Inventing capacity is the dangerous direction --
   it feeds ``idle_marches`` and can authorize a dispatch into a full queue -- and
   the project already has an honest value for "not read": ``None``.

These tests pin both, and they pin the direction of the safety: a reservation may
never make the running goal unreachable, and a count that was not read is never
reported as a number.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import MarchState, Page, WorldState
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.vision import SemanticWorldVision

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "dataset/candidate/template_manifest.json"


def _map(used: int | None, maximum: int | None, *, marches: tuple[MarchState, ...] = ()) -> WorldState:
    return WorldState(page=Page.MAP, marches=marches, march_used=used, march_max=maximum, confidence=0.99)


# ------------------------------------------------- reservation follows capacity


@pytest.mark.parametrize(
    "capacity,used,reserve,expect_reserved_stop",
    [
        # The live case from 2026-09-16: capacity 2, one march out, one free.
        # The goal must be allowed to use the free slot.
        (2, 1, 2, False),
        # The account the constant was written for keeps its protection:
        # gathering may take at most four of six slots.
        (6, 4, 2, True),
        (6, 3, 2, False),
        # Three slots can afford one reserved slot, so the stop needs idle <= 1.
        (3, 2, 2, True),
        (3, 1, 2, False),
        (3, 0, 2, False),
        # Four slots can afford the full two.
        (4, 2, 2, True),
        (4, 1, 2, False),
    ],
)
def test_the_reservation_is_a_function_of_capacity(
    capacity: int, used: int, reserve: int, expect_reserved_stop: bool
) -> None:
    brain = RuleBrain(current_goal="GATHER_RESOURCE", reserve_marches=reserve)
    decision = brain.decide(_map(used, capacity), v2_registry())
    got = decision.reason == "reserved_march_for_stamina"
    assert got is expect_reserved_stop, (
        f"capacity={capacity} used={used} reserve={reserve}: "
        f"reserved-stop={got}, expected {expect_reserved_stop} (decision {decision.skill}/{decision.reason})"
    )


def test_the_reservation_never_equals_the_capacity() -> None:
    """The invariant that makes a small account able to work at all.

    The stop fires when ``idle <= reserved_slots``.  If ``reserved_slots`` ever
    reaches the capacity then NO occupancy lets the goal through -- idle can never
    exceed the capacity -- and the goal is dead for good rather than merely blocked.

    That is exactly the live state on 2026-09-16: capacity 2 with a standing reserve
    of 2, so ``idle <= 2`` held for every possible idle and three GATHER_RESOURCE
    runs produced no episode.  Note the weaker statement that does NOT hold and must
    not be asserted: a reservation is *allowed* to stop a goal while free slots
    remain, because preserving slots for realtime work is its entire purpose.
    """
    for reserve in (0, 1, 2, 5):
        brain = RuleBrain(current_goal="GATHER_RESOURCE", reserve_marches=reserve)
        for capacity in (1, 2, 3, 4, 6, 10):
            reserved = brain.reserved_slots(_map(0, capacity))
            assert reserved < capacity, (
                f"capacity={capacity} reserve={reserve}: reserved={reserved} consumes the whole "
                f"army, so no idle value can satisfy idle > reserved"
            )


def test_an_unread_capacity_is_not_treated_as_a_number() -> None:
    """Unknown capacity asks for a measurement; it does not assume one."""
    brain = RuleBrain(current_goal="GATHER_RESOURCE", reserve_marches=2)
    decision = brain.decide(_map(None, None), v2_registry())
    assert decision.skill == "CHECK_MARCH"
    assert brain.reserved_slots(_map(None, None)) == 0


def test_reserved_slots_is_capped_and_never_negative() -> None:
    brain = RuleBrain(current_goal="GATHER_RESOURCE", reserve_marches=2)
    assert brain.reserved_slots(_map(0, 2)) == 0, "capacity 2 cannot afford a standing reservation"
    assert brain.reserved_slots(_map(0, 6)) == 2
    assert brain.reserved_slots(_map(0, 1)) == 0, "a single slot can never be reserved away"


# ------------------------------------------------ the page model stops inventing


def test_the_page_model_has_no_default_march_capacity() -> None:
    """It used to default to 6, an assumption about one account presented as a fact."""
    vision = SemanticWorldVision(MANIFEST)
    assert vision.calibrated_march_max is None
    state = WorldState(page=Page.MAP)
    assert state.idle_marches is None, "None capacity propagates to 'not proven'"


def test_no_page_model_branch_invents_a_march_capacity() -> None:
    """No WorldState built from a template may carry a hand-written CAPACITY.

    A template match proves a page is up and, sometimes, the state of one march.  It
    cannot prove how many slots the account has.  Claiming a capacity is the
    dangerous half: a capacity of 6 on a role that has 2 computes four phantom free
    slots and authorises a dispatch into a full queue -- and the reverse (a capacity
    of 6 stated as "6 of 6 used" when only one march is out) drives ``idle_marches``
    to 0 and sends the brain looking for a gathering march to recall.

    A numeric ``march_used`` is still allowed, because for a status template it can
    be a PROVEN LOWER BOUND ("a musk ox march is outbound" implies at least one slot
    is in use), and an under-stated occupancy cannot create a phantom slot when the
    capacity is unknown.  Only ``march_max`` -- a capacity -- is forbidden as a
    literal.
    """
    import re

    source = (ROOT / "winter_agent_v2/vision.py").read_text(encoding="utf-8")
    pattern = re.compile(r"^\s*march_max\s*=\s*\d+\s*,?\s*$")
    offending = [line.strip() for line in source.splitlines() if pattern.match(line)]
    assert offending == [], (
        "vision.py must not hand-write a march capacity; found: %s" % offending
    )


def test_the_page_model_reports_no_capacity_until_one_is_read() -> None:
    """Capacity is unknown until the client is read, and stays unknown otherwise."""
    vision = SemanticWorldVision(MANIFEST)
    assert vision.calibrated_march_max is None
    assert WorldState(page=Page.MAP).idle_marches is None
    # A lower bound with no capacity still yields "not proven", never a number.
    bounded = WorldState(page=Page.MAP, march_used=1)
    assert bounded.idle_marches is None


# ------------------------------------- the start condition may not need a capacity
#
# Removing the invented capacity exposed that the client does not draw the counter
# while nothing is out, so `idle_marches` is None in exactly the state the goal needs
# to leave.  Measured live 2026-09-16T11:09-11:16: three GATHER_RESOURCE runs spent
# all eight actions on CHECK_MARCH and produced no dispatch, because re-observing an
# idle map cannot reveal a counter that is not drawn.  GATHER_RESOURCE is the
# operator's phase priority #1, so this is the blocker, not a curiosity.


def test_an_idle_map_with_no_counter_may_still_start_a_march() -> None:
    """Nothing out proves at least one slot is free -- without claiming a capacity."""
    world = _map(0, None)
    assert world.idle_marches is None, "the count itself stays unknown"
    assert world.has_free_march_slot is True, "but the weaker fact is knowable"
    decision = RuleBrain(current_goal="GATHER_RESOURCE", reserve_marches=2).decide(world, v2_registry())
    assert decision.skill == "SEARCH_RESOURCE", decision
    assert decision.reason == "idle_march_available"


def test_an_unreadable_occupancy_still_asks_for_a_measurement() -> None:
    """`used` unknown is a different state from `used` read as zero."""
    world = _map(None, None)
    assert world.has_free_march_slot is None
    assert RuleBrain(current_goal="GATHER_RESOURCE").decide(world, v2_registry()).skill == "CHECK_MARCH"


def test_check_march_survives_for_the_state_where_observing_again_can_help() -> None:
    """A march IS out, so the counter is drawn: looking again is a real move."""
    world = _map(1, None, marches=(MarchState.GATHERING,))
    assert world.has_free_march_slot is None
    assert RuleBrain(current_goal="GATHER_RESOURCE").decide(world, v2_registry()).skill == "CHECK_MARCH"


def test_a_read_capacity_behaves_exactly_as_before() -> None:
    """The lower bound must not change any decision that already had a number."""
    brain = RuleBrain(current_goal="GATHER_RESOURCE", reserve_marches=2)
    assert brain.decide(_map(0, 2), v2_registry()).skill == "SEARCH_RESOURCE"
    assert brain.decide(_map(1, 2), v2_registry()).skill == "SEARCH_RESOURCE"
    recalling = RuleBrain(current_goal="GATHER_RESOURCE", reserve_marches=2, recall_on_demand=True)
    decision = recalling.decide(_map(2, 2, marches=(MarchState.GATHERING,)), v2_registry())
    assert decision.skill == "SELECT_MARCH_TO_RECALL", (
        "a full queue with a gathering march still offers the recall"
    )


def test_a_full_queue_with_nothing_recallable_is_not_forced() -> None:
    """A full queue of beast/intel marches is a stop, not a recall."""
    brain = RuleBrain(current_goal="GATHER_RESOURCE", reserve_marches=2)
    decision = brain.decide(_map(2, 2, marches=(MarchState.MARCHING,)), v2_registry())
    assert decision.skill == "SAFE_STOP"
    assert decision.reason == "no_idle_march"


def test_the_free_slot_predicate_is_tri_state_and_never_a_count() -> None:
    assert _map(0, None).has_free_march_slot is True
    assert _map(0, 2).has_free_march_slot is True
    assert _map(1, 2).has_free_march_slot is True
    assert _map(2, 2).has_free_march_slot is False
    assert _map(None, 2).has_free_march_slot is None
    assert _map(1, None).has_free_march_slot is None
