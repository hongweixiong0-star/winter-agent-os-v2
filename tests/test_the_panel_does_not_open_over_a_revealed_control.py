"""The panel must not open over a control another goal has just revealed.

Measured 2026-10-06 on the frames of one run (``20261006_011043_659372``):

    step_002_after  OPEN_TASK_FROM_QUICK_PANEL_BUILDING had closed the panel and revealed the
                    building's action bar -- 详情 / 升级 / 城镇防御, with 升级 under the tutorial hand
    step_003_after  DISCOVER_QUICK_PANEL_TASKS re-opened the panel, and that bar was gone: covered

The building goal then had to tap its row a second time to get its own control back -- two row taps
and one wasted open per upgrade, and up to 80% of a run's actions while the two alternated.

The precondition added reads the current frame (``upgrade_tap_norm`` is present exactly when the
升级 control was readable on this frame), so the tests below are about the two directions of that
decision and, just as importantly, about its **liveness**: this goal is the only thing in the module
that can open the panel, so a precondition that could suppress it permanently would starve the four
goals that need a panel row.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import goal_library
from winter_agent_v2.goal_library import GoalStatus
from winter_agent_v2.models import Page, WorldState

PANEL_CLOSED = {"open": False, "handle": {"state": "COLLAPSED", "point_norm": [0.02, 0.43]}}
PANEL_OPEN = {"open": True}


def _board(**world_kwargs) -> list:
    """Whatever the quick-panel section of the goal board contains for this world."""
    world = WorldState(**world_kwargs)
    goals: list = []
    goal_library._append_quick_panel_task_goals(goals, world)
    return [g for g in goals if g.goal_id == "DISCOVER_QUICK_PANEL_TASKS"]


def _ready_row():
    rows = _board(page=Page.HOME, quick_panel=PANEL_CLOSED)
    assert len(rows) == 1 and rows[0].status is GoalStatus.READY
    return rows[0]


def test_the_panel_is_still_offered_when_nothing_was_revealed():
    """The existing behaviour, unchanged: closed panel + collapsed handle -> READY at 260."""
    row = _ready_row()
    assert row.reward_value == 260
    assert row.available_skills == ("OPEN_QUICK_PANEL",)


def test_the_panel_is_not_offered_over_a_revealed_control():
    """The fix.  A readable 升级 control on this frame means opening would cover it."""
    assert _board(page=Page.HOME, quick_panel=PANEL_CLOSED,
                  building={"upgrade_tap_norm": [0.5, 0.71]}) == []


def test_the_panel_is_offered_again_once_the_control_is_gone():
    """**Liveness**, and the point of the whole change.

    This goal is the sole opener -- ``OPEN_QUICK_PANEL`` appears nowhere else in the module -- while
    at least four goals need a panel row (``OPEN_TASK_FROM_QUICK_PANEL_BUILDING`` / ``_HERO_RECRUIT``
    / ``_HERO_RECRUIT_EPIC`` / ``_PET_TREASURE``).  So the precondition has to be a deferral: the
    moment the other goal has spent its control, the panel is offered again at the same 260.
    """
    assert _board(page=Page.HOME, quick_panel=PANEL_CLOSED,
                  building={"upgrade_tap_norm": [0.5, 0.71]}) == []
    after_the_control_is_spent = _board(page=Page.HOME, quick_panel=PANEL_CLOSED,
                                        building={"upgrade_tap_norm": None})
    assert len(after_the_control_is_spent) == 1
    assert after_the_control_is_spent[0].status is GoalStatus.READY
    assert after_the_control_is_spent[0].reward_value == 260


@pytest.mark.parametrize("malformed", [None, [], [0.5], "0.5,0.71", 1, {"x": 0.5}, [0.5, 0.71, 0.9]])
def test_a_malformed_control_value_cannot_suppress_the_sole_opener(malformed):
    """A shape this code does not recognise must not read as "a control is revealed".

    The failure direction matters: treating junk as a revealed control would silence the only goal
    that can open the panel, and nothing would put it back.  Measured over 11,611 recorded states
    the key is either a two-element list or absent, so anything else is a bug elsewhere and the
    safe reading is "no control readable".
    """
    assert len(_board(page=Page.HOME, quick_panel=PANEL_CLOSED,
                      building={"upgrade_tap_norm": malformed})) == 1


def test_the_served_marker_is_untouched():
    """The other half of the two-state machine, which this change must not disturb.

    An open panel still answers the goal -- COMPLETE with ``served_by`` -- so "answered" stays
    distinguishable from "never asked".  Deliberately not reused for "postponed": COMPLETE is what
    this goal emits when it really was served, and reusing it would misreport coverage.
    """
    rows = _board(page=Page.HOME, quick_panel=PANEL_OPEN)
    assert len(rows) == 1
    assert rows[0].status is GoalStatus.COMPLETE
    assert rows[0].evidence.get("served_by") == "OPEN_QUICK_PANEL"


def test_a_revealed_control_on_another_page_is_irrelevant():
    """The precondition belongs to the HOME branch only; it must not leak into other pages."""
    for page in (Page.MAP, Page.BUILDING, Page.EVENT):
        assert _board(page=page, quick_panel=PANEL_CLOSED,
                      building={"upgrade_tap_norm": [0.5, 0.71]}) == []
