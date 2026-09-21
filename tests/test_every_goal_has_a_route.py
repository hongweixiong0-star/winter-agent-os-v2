"""Every goal the library can emit must have a route, or it is scheduled and inert.

Measured 2026-09-21.  ``LiveRuntime`` translates a goal id into a brain route in exactly one
place, and a goal that is missing from that table is not "handled elsewhere" -- it is
scheduled, given ``current_goal=None``, and left to whatever ``RuleBrain`` does with no goal
at all.  That is how four panel routines stayed invisible while their capabilities worked:
the goals were emitted, priced, selected, and then produced no action.

The table moved into ``goal_library.GOAL_ROUTES`` today (the panel's Development Validation
cycle needs the same translation), so the invariant is checkable without a device or a
scheduler: enumerate what ``discover`` can emit, and assert each one maps.  One goal was
already failing this -- ``KEEP_MARCHES_PRODUCTIVE``, the only one ``route_for`` answered
``None`` for.  It happened to keep working because ``RuleBrain`` with no goal falls into its
gather branch, but that is an accident of the default, not a route.

The enumeration is over the *goals the library knows about*, gathered from two directions so
a goal cannot hide behind a page this test did not think to build:

* ``GOAL_REQUIREMENTS`` -- the capability table's own list of goals that have requirements;
* ``CAMP_GOAL_FOR`` -- the per-barracks ids, which are generated from ``CAMP_ORDER``;
* a sweep of many pages through ``discover``, for the ids that only appear from a reading.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from winter_agent_v2.goal_library import (  # noqa: E402
    CAMP_GOAL_FOR,
    GOAL_ROUTES,
    ROUTE_DOMAINS,
    GoalLibrary,
    route_for,
)
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.skill_factory import GOAL_REQUIREMENTS  # noqa: E402

#: Pages chosen to reach every branch of ``discover``: the map (march/stamina/beast), the
#: two panels that carry their own goal, the training page, and the intel board.
PAGES = (
    WorldState(page=Page.MAP, march_used=1, march_max=3, stamina={"current": 320}),
    WorldState(page=Page.MAP, march_used=0, march_max=6),
    WorldState(page=Page.HOME),
    WorldState(page=Page.ALLIANCE),
    WorldState(page=Page.DAILY),
    WorldState(page=Page.MAIL),
    WorldState(page=Page.RESEARCH),
    WorldState(page=Page.INTEL, intel={"status": "AVAILABLE"}),
    WorldState(page=Page.EXPLORATION),
    WorldState(page=Page.TRAINING,
               training={"troop_type": "INFANTRY", "status": "IN_PROGRESS"}),
)


def _discoverable() -> set[str]:
    library = GoalLibrary()
    ids: set[str] = set()
    for world in PAGES:
        ids.update(goal.goal_id for goal in library.discover(world))
    return ids


def test_the_enumeration_finds_the_goals_it_is_supposed_to():
    """A guard on the guard: an empty or tiny set would make the assertions below vacuous."""
    found = _discoverable()
    assert len(found) >= 8, f"the page sweep stopped reaching branches: {sorted(found)}"
    assert "KEEP_MARCHES_PRODUCTIVE" in found
    assert "CLEAR_INTEL" in found


def test_every_camp_goal_has_a_route():
    for camp, goal_id in CAMP_GOAL_FOR.items():
        assert route_for(goal_id) is not None, (
            f"{camp} emits {goal_id}, which has no route -- it would be scheduled and inert"
        )


def test_every_goal_the_capability_table_names_has_a_route():
    """``GOAL_REQUIREMENTS`` is the other direction: goals that exist without a current page."""
    missing = sorted(g for g in GOAL_REQUIREMENTS if route_for(g) is None)
    # Not every entry is a schedulable goal on this board -- the table also carries goals the
    # operator has not enabled.  What must not happen is one of *these* silently reaching the
    # scheduler, so the assertion is over the ones ``discover`` actually emits.
    leaked = sorted(g for g in missing if g in _discoverable())
    assert not leaked, f"discoverable goals with no route: {leaked}"


def test_every_discoverable_goal_has_a_route():
    missing = sorted(g for g in _discoverable() if route_for(g) is None)
    assert not missing, (
        f"these would be selected and then do nothing: {missing}.  Add them to GOAL_ROUTES."
    )


def test_every_route_points_at_a_domain_the_runner_accepts():
    bad = {g: r for g, r in GOAL_ROUTES.items() if r not in ROUTE_DOMAINS}
    assert not bad, f"routes run_live --goal would reject: {bad}"


def test_a_route_is_returned_for_a_route_name_too():
    """``route_for`` is idempotent: ledger records already hold some domains as their goal."""
    for domain in ROUTE_DOMAINS:
        assert route_for(domain) == domain
    assert route_for("") is None
    assert route_for(None) is None
    assert route_for("NOT_A_GOAL") is None


@pytest.mark.parametrize("goal_id", sorted(GOAL_ROUTES))
def test_the_translation_is_total_over_the_table(goal_id: str):
    assert route_for(goal_id) in ROUTE_DOMAINS
