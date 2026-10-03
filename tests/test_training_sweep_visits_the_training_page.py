"""The unobserved-training sweep must go to the page that produces the reading.

Measured 2026-10-03 on the live ledger, the whole shape of this family:

* 2908 HOME frames; **1736 of them carry no ``camps`` reading at all** (60%).
* ``KEEP_TRAINING_PRODUCTIVE`` -- the only training ticket that exists on those frames --
  was selected **561 times** and did ``OPEN_HOME`` **425** of them. Never once trained, and
  ``goal_progress`` was never ``True``.
* On frames that *do* carry ``camps``, the migration is clean: the legacy label is selected
  **0** times and ``*_CAMP_TRAINING`` is selected 131 of 202.

So the legacy label is not a stale leftover -- it is the fallback for "the training page has
never been read", which is exactly what its own docstring says it is
(``goal_library.py:671``: *"The never-read training page, as a routine"*). The defect is
where its one step goes. ``entry_skill="TRY_ORDINARY_CONTROL"`` lands on *going home*, and
coming home does not produce a ``camps`` reading, so the next frame is identical and the loop
is self-sustaining: the reason the sweep exists is to "go and look", and it goes somewhere
that cannot answer the question.

The page that does answer it is already registered and already proven on the device:
``OPEN_INFANTRY_TRAINING`` (Page.HOME, ``TAP_SEMANTIC BTN_OPEN_TRAINING_FROM_CAMP``) ran
**57 times, 57 SUCCESS**, and its after-frames carry exactly the reading that is missing:

    {"MARKSMAN_CAMP": {"status": "AVAILABLE", "queue_available": true, ...}}

These tests pin that one substitution and, more importantly, pin that it is the *only*
thing being changed: a sweep that starts reaching the training page must still not claim
progress, and a frame that already has a ``camps`` reading must still be served by the
per-camp goals, because the sweep is by definition the never-read case.
"""

import pytest

from winter_agent_v2 import goal_utility
from winter_agent_v2.goal_library import (
    TRAINING_SWEEP,
    GoalLibrary,
    progress_moved,
    route_for,
)
from winter_agent_v2.models import Page, WorldState

ROLE = "1061663148"


def _board(world, **kw):
    return GoalLibrary().discover(world, role_id=ROLE, **kw)


def test_the_sweep_goes_to_the_page_that_produces_the_reading():
    """The one behavioural change, stated as an assertion on the real board.

    ``entry_skill`` is what the runtime will actually be handed, and the page it names has to
    be the one that yields ``camps``. ``OPEN_INFANTRY_TRAINING`` is the measured answer: 57
    live attempts, all successful, after-frames carrying the reading.
    """
    goals = _board(WorldState(page=Page.HOME, march_used=1, march_max=6), observations={})
    sweep = next(g for g in goals if g.goal_id == TRAINING_SWEEP.goal_id)
    assert "OPEN_INFANTRY_TRAINING" in sweep.available_skills, (
        "the never-read training sweep must open the training page; "
        f"it offers {sweep.available_skills}, which is the loop that has run 561 times"
    )
    assert "TRY_ORDINARY_CONTROL" not in sweep.available_skills, (
        "a generic control is what resolved to going home every time, and coming home does "
        "not produce the reading the sweep exists to obtain"
    )


def test_the_step_still_names_a_registered_skill():
    """It has to be a real skill, not a plausible string.

    A sweep whose step is not in the registry cannot be executed, which would look like a fix
    and behave like a stall -- the exact failure the audit found in the audit gate.
    """
    from winter_agent_v2.skills import v2_registry

    registry = v2_registry()
    goals = _board(WorldState(page=Page.HOME, march_used=1, march_max=6), observations={})
    sweep = next(g for g in goals if g.goal_id == TRAINING_SWEEP.goal_id)
    for skill in sweep.available_skills:
        assert registry.get(skill) is not None, f"{skill} is not registered"
        assert route_for(TRAINING_SWEEP.goal_id) == "TRAIN"


def test_a_frame_with_camps_is_still_served_by_the_per_camp_goals():
    """The sweep is the never-read case; a read frame must not get it.

    If the substitution leaked into the read path, the per-camp goals would stop being
    selected and the family would be back to one coarse ticket that cannot tell a busy camp
    from an idle one -- the reason the migration happened at all.
    """
    camps = {
        "SHIELD_CAMP": {"troop_type": "INFANTRY", "label": "盾兵",
                        "status": "IDLE", "queue_available": True},
        "LANCER_CAMP": {"troop_type": "LANCER", "label": "矛兵",
                        "status": "IN_PROGRESS", "queue_available": False},
        "MARKSMAN_CAMP": {"troop_type": "MARKSMAN", "label": "弓兵",
                          "status": "IN_PROGRESS", "queue_available": False},
    }
    goals = _board(WorldState(page=Page.HOME, march_used=1, march_max=6, camps=camps), observations={})
    idle = next(g for g in goals if g.goal_id == "SHIELD_CAMP_TRAINING")
    busy = [g for g in goals if g.goal_id in {"LANCER_CAMP_TRAINING", "MARKSMAN_CAMP_TRAINING"}]
    assert idle.status.value == "READY" and "TRAIN_TROOPS" in idle.available_skills
    assert all(g.status.value == "BLOCKED" for g in busy), (
        "a busy camp must not carry work, or one busy camp closes the goal for all three"
    )
    legacy = [g for g in goals if g.goal_id == TRAINING_SWEEP.goal_id]
    assert not legacy or all(g.status.value != "READY" for g in legacy), (
        "the sweep must not compete with a per-camp reading that is already in hand"
    )


def test_opening_the_training_page_is_not_itself_progress():
    """The reason this defect was invisible: a SUCCESS that moved nothing.

    ``OPEN_INFANTRY_TRAINING`` recorded ``goal_progress=False`` on all 57 live attempts while
    its own after-frame carried the reading. So the frame in which the sweep arrives must not
    be scored as progress either -- otherwise the fix would buy a false metric.
    """
    camps = {
        "SHIELD_CAMP": {"troop_type": "INFANTRY", "label": "盾兵",
                        "status": "AVAILABLE", "queue_available": True},
    }
    before = _board(WorldState(page=Page.HOME, march_used=1, march_max=6), observations={})
    after = _board(
        WorldState(page=Page.HOME, march_used=1, march_max=6, camps=camps), observations={},
    )
    assert progress_moved({}, after, "KEEP_TRAINING_PRODUCTIVE") is None, (
        "the legacy label is gone from a read board, so the step that reads cannot be scored "
        "against it -- the reading lands as per-camp goals instead"
    )
    # And the per-camp goal it produces is scored on the camp's own state, not on arrival.
    assert any(g.goal_id == "SHIELD_CAMP_TRAINING" for g in after)
    assert not any(g.goal_id == "KEEP_TRAINING_PRODUCTIVE" for g in after)


def test_the_sweep_is_still_priced_below_real_work():
    """It remains a fallback: when a training queue is busy the page is not worth opening.

    ``TRAINING_SWEEP`` carries ``discovery_value=SWEEP_NEVER_VALUE`` precisely so that a
    real queue reading outranks it. If the substitution raised its price, the family would
    start spending steps on the training page while two camps are training.
    """
    from winter_agent_v2.goal_library import TRAINING_CAMP_VALUE

    assert TRAINING_SWEEP.discovery_value < TRAINING_CAMP_VALUE, (
        "a never-read sweep must stay below a camp with live work, or the substitution trades "
        "real training for observation"
    )
