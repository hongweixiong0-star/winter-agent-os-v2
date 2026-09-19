"""Panel routines: a goal that was defined but impossible to emit, and how it earns its state.

The operator's P0-B, the part that mattered most.  ``MAIL_ROUTINE`` and friends were defined in
``goal_capability_map.json``, had their capability chains mapped, and could **never** be emitted
by ``discover()`` -- so the scheduler never chose to open the panel, and the Goal Board showed
them as 未读取 for ever.  Nothing was missing except the entry point: vision already reads
``Page.MAIL`` / ``Page.DAILY`` / ``Page.ALLIANCE`` / ``Page.EXPLORATION`` into those fields, the
brain already has a MAP -> panel route for each, and every skill involved is registered with a
bound verifier.

What these tests defend, in the operator's terms:

* §6 ``NOT_OBSERVED_YET`` -> the goal exists and is **schedulable as the act of going to look**.
  "No observation" must not mean "this goal does not exist".
* §6 ``OBSERVED_UNKNOWN`` -> read, but unintelligible: a capability gap, not a routine.  The two
  are different states on purpose, because they have different remedies.
* A routine that is done is COMPLETE, and COMPLETE is not scheduled -- a finished daily must not
  hold the scheduler's attention.
* §5 the observation visit must be cheap: an unread routine is worth less than real work, so it
  is picked when nothing better is owed rather than ahead of it.
* No skill is offered to a schedulable goal unless it has a live-loop verifier; the project has
  already paid for that mistake once (``SKILL_NOT_ENABLED_FOR_LIVE_LOOP``).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.goal_library import (  # noqa: E402
    PANEL_ROUTINES,
    GoalLibrary,
    GoalStatus,
)
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402

ROUTINE_IDS = tuple(routine.goal_id for routine in PANEL_ROUTINES)


def emitted(world: WorldState) -> dict[str, object]:
    return {goal.goal_id: goal for goal in GoalLibrary().discover(world)}


def test_the_four_routines_stop_being_invisible():
    """The bare MAP world -- no readings at all -- must now name them."""
    goals = emitted(WorldState(page=Page.MAP, march_used=2, march_max=3))
    for goal_id in ROUTINE_IDS:
        assert goal_id in goals, f"{goal_id} is defined and must be discoverable"


@pytest.mark.parametrize("routine", PANEL_ROUTINES, ids=lambda r: r.goal_id)
def test_never_looked_is_its_own_state_and_is_schedulable(routine):
    """§6: NOT_OBSERVED_YET schedules an observation -- it does not hide the goal."""
    goal = emitted(WorldState(page=Page.MAP))[routine.goal_id]
    assert goal.status is GoalStatus.DISCOVERED
    assert goal.evidence["observed"] is False
    assert goal.available_skills == (routine.entry_skill,), (
        "an unread routine must offer exactly the skill that opens its panel"
    )
    assert goal.priority != float("-inf"), "DISCOVERED must be schedulable"
    assert goal.priority > 0


@pytest.mark.parametrize("routine", PANEL_ROUTINES, ids=lambda r: r.goal_id)
def test_read_and_claimable_is_ready_with_the_claim_skills(routine):
    world = WorldState(page=Page.MAP, **{routine.field: {"status": routine.work[0]}})
    goal = emitted(world)[routine.goal_id]
    assert goal.status is GoalStatus.READY
    assert goal.available_skills == routine.work_skills
    assert goal.evidence["observed"] is True
    assert goal.distance == 1.0


@pytest.mark.parametrize("routine", PANEL_ROUTINES, ids=lambda r: r.goal_id)
def test_read_and_finished_is_complete_and_not_scheduled(routine):
    """A finished routine must not hold attention -- COMPLETE is not schedulable."""
    world = WorldState(page=Page.MAP, **{routine.field: {"status": routine.done[0]}})
    goal = emitted(world)[routine.goal_id]
    assert goal.status is GoalStatus.COMPLETE
    assert goal.distance == 0.0
    assert goal.priority == float("-inf")


@pytest.mark.parametrize("routine", PANEL_ROUTINES, ids=lambda r: r.goal_id)
def test_read_but_unintelligible_is_unknown_not_discovered(routine):
    """§6: OBSERVED_UNKNOWN is a capability gap; NOT_OBSERVED_YET is a visit.

    Collapsing them would either send the loop to look at a page it has already read, or file
    a missing capability as "just not looked yet" -- the two remedies are not interchangeable.
    """
    world = WorldState(page=Page.MAP, **{routine.field: {"status": "WHAT_IS_THIS"}})
    goal = emitted(world)[routine.goal_id]
    assert goal.status is GoalStatus.UNKNOWN
    assert goal.evidence["observed"] is True
    assert goal.available_skills == (), "an unreadable page is not a routine to run"
    assert goal.priority == float("-inf")


def test_a_mail_badge_is_work_even_without_a_status_word():
    """The mail panel reports unclaimed tabs as badges, and that is the claimable signal."""
    world = WorldState(page=Page.MAP, mail={"tab_badges": {"ALLIANCE": 2, "SYSTEM": 0}})
    goal = emitted(world)["MAIL_ROUTINE"]
    assert goal.status is GoalStatus.READY
    assert goal.evidence["badge"] is True


def test_an_unread_routine_never_outranks_real_work():
    """§5: the observation visit is what happens when nothing better is owed.

    Measured on live goals: the stamina goal prices at 2615 and gathering at 70, so a routine
    discovery at 20 loses to both and wins over an idle world -- which is the bounded sweep,
    expressed through the priority the scheduler already uses instead of a second timer.
    """
    world = WorldState(page=Page.MAP, march_used=2, march_max=3, stamina={"current": 500})
    goals = {goal.goal_id: goal for goal in GoalLibrary().discover(world)}
    chosen = GoalLibrary().best(goals.values())
    assert chosen is not None
    assert chosen.goal_id not in ROUTINE_IDS, (
        f"{chosen.goal_id} outranked real work; the discovery value must stay small"
    )
    assert goals["AVOID_STAMINA_WASTE"].priority > goals["MAIL_ROUTINE"].priority


def test_no_routine_offers_a_skill_without_a_live_loop_verifier():
    """A skill that is not in VERIFIED_ATOMIC kills the run that selects it.

    ``DAILY_HERO_RECRUIT`` and ``ALLIANCE_TECH_CONTRIBUTE`` are both registered and both lack a
    bound live-loop verifier, so neither may appear in a schedulable routine's skill list.
    """
    registry = v2_registry()
    for routine in PANEL_ROUTINES:
        for skill in routine.work_skills + (routine.entry_skill,):
            assert registry.get(skill) is not None, f"{skill} is not registered"
            assert skill in LiveRuntime.VERIFIED_ATOMIC, (
                f"{routine.goal_id} offers {skill}, which has no live-loop verifier"
            )
    forbidden = {"DAILY_HERO_RECRUIT", "ALLIANCE_TECH_CONTRIBUTE"}
    offered = {s for routine in PANEL_ROUTINES for s in routine.work_skills}
    assert not (offered & forbidden), f"unverified skills offered: {sorted(offered & forbidden)}"
