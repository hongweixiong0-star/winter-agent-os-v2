"""A quick-panel row the client already calls完成 must not be offered as work.

Measured 2026-10-03 on the full ledger (10463 episodes):

    OPEN_TASK_FROM_QUICK_PANEL_PET_TREASURE   43 steps, 43 SUCCESS, 0 FAILURE
    the PET_TREASURE row on the BEFORE frame:
        (status=COMPLETED, control=ARROW, badge=PRESENT) -> 37
        (status=UNKNOWN,  control=ARROW, badge=PRESENT) ->  6

So 37 of the 43 taps were sent to a row whose own reading already said **已完成**.
Perfect separation, no overlap -- so this is not "sometimes the row is stale".

The 6 ``UNKNOWN`` ones are the more damning half, and they are only visible by pairing:
every one of them is followed 5-7 seconds later by a ``BACK``.  The step opened the pet
page and came straight back.  So **all 43 produced no reward**, and the episode ledger
called every one of them SUCCESS -- the verifier confirmed "the tap landed and the client
responded", which is a different question from "the row had anything left".

The defect is narrow and specific
---------------------------------
``goal_library._append_quick_panel_task_goals`` gates the row on badge and control only:

    if pet.get("badge") == entry_badges.PRESENT and pet.get("control") in {"ARROW", "DONE"}:

``status`` is read by the panel reader, written into every observation, printed in every
episode's ``state_before`` -- and not consulted here.  The evidence is already in hand; the
reader simply does not use it.  This is the mirror image of the project's own rule that a
synthesised state may only claim what its evidence covers: here the evidence covers more
than the claim does.

What this file does and does not claim
-------------------------------------
It does **not** claim the pet page is unreachable or the hunt is finished.  ``UNKNOWN`` is
exactly "we could not read this row's state", and it must stay actionable -- refusing it
would turn a readable row into a blackhole.  The gate therefore separates the three states
rather than collapsing them:

* ``COMPLETED`` / a completion word on the row  -> not offered (this is the fix)
* ``ARROW`` with no completion word             -> offered, as before
* anything else, including ``UNKNOWN``           -> unchanged

``MY_REWARDS`` is the same shape one row above (``control == "DONE"`` *is* the completion
marker, and its own comment already says a green check alone must not license a second
claim).  It is included here as a pinned observation rather than a fix: measured, it has
never run -- ``COLLECT_MY_REWARDS_ROW`` has 0 episodes -- so changing it now would be an
unmeasured product change.  The test states the fact and says so.
"""

import pytest

from winter_agent_v2.entry_badges import PRESENT
from winter_agent_v2.goal_library import GoalLibrary
from winter_agent_v2.models import Page, WorldState


def _panel(pet_status, pet_word="已完成", control="ARROW", badge=PRESENT):
    """One HOME frame with the panel open and a single PET_TREASURE row on it."""
    return WorldState(
        page=Page.HOME,
        quick_panel={
            "open": True,
            "rows": [{
                "key": "PET_TREASURE", "kind": "PET_TREASURE", "label": "宠物寻宝",
                "label_norm": [0.1361, 0.4816], "y_norm": 0.5117,
                "status": pet_status, "source_word": pet_word,
                "arrow_norm": [0.5618, 0.5164], "arrow_basis": "ROW_BUTTON_SCAN",
                "badge": badge, "control": control,
            }],
        },
        confidence=0.99,
    )


def _pet_goal(world):
    return next(
        (g for g in GoalLibrary().discover(world, observations={})
         if g.goal_id == "PET_TREASURE"),
        None,
    )


def test_a_row_the_client_calls_complete_is_not_offered():
    """The fix, and the state that caused 37 wasted taps.

    ``status``/``source_word`` were on the row in every one of those 43 episodes.  The gate
    looked at badge and control and never at them.
    """
    assert _pet_goal(_panel("COMPLETED")) is None


def test_the_completion_word_alone_is_enough_to_refuse():
    """``source_word`` is the same fact read a different way, so it has to count too.

    The panel reader sets ``status`` from the word it read.  If a future frame carries the
    word but not the derived status -- a partial read, a renamed field -- refusing must not
    silently stop working, or the 37 wasted taps come back.
    """
    assert _pet_goal(_panel("UNKNOWN", pet_word="已完成")) is None


def test_a_readable_arrow_row_is_still_offered():
    """The control that keeps this from becoming "never touch the pet page".

    6 of the 43 taps were on rows whose state could not be read.  Those are legitimate work:
    opening the page is how the state gets read.  A gate that refused them would be the
    ``None``-as-refusal mistake in a new place.
    """
    goal = _pet_goal(_panel("UNKNOWN", pet_word=None))
    assert goal is not None
    assert goal.available_skills == ("OPEN_TASK_FROM_QUICK_PANEL_PET_TREASURE",)
    assert goal.reward_value == 250


def test_the_refusal_is_not_silent_about_why():
    """A goal that vanishes with no trace is the defect this project keeps paying for.

    When a row is refused because it is already complete, that fact has to be readable
    somewhere, or the next round cannot tell "refused because finished" from "not
    discovered".  The evidence file on the panel carries the row, so an auditor can still
    see it -- this test pins that the row itself is intact on the frame.
    """
    world = _panel("COMPLETED")
    goal = _pet_goal(world)
    assert goal is None
    row = world.quick_panel["rows"][0]
    assert row["status"] == "COMPLETED" and row["source_word"] == "已完成", (
        "the frame must keep the evidence; the refusal happens at the goal layer"
    )


def test_my_rewards_is_the_same_shape_but_has_never_run():
    """Measured, stated, and deliberately not changed.

    ``MY_REWARDS`` gates on ``control == "DONE"``, and ``DONE`` *is* the completion marker --
    the same inverted gate.  But ``COLLECT_MY_REWARDS_ROW`` has 0 episodes, so the goal has
    never been selected and there is no live waste to stop.  Changing it now would be a
    product change with no evidence behind it; the fact is pinned here so the day it does
    run, this shape is already written down.
    """
    rewards = WorldState(
        page=Page.HOME,
        quick_panel={
            "open": True,
            "rows": [{
                "key": "MY_REWARDS", "kind": "MY_REWARDS", "label": "仓库补给",
                "label_norm": [0.3118, 0.3902], "y_norm": 0.3902,
                "status": "COMPLETED", "source_word": "已完成",
                "badge": PRESENT, "control": "DONE",
            }],
        },
        confidence=0.99,
    )
    goal = next(
        (g for g in GoalLibrary().discover(rewards, observations={})
         if g.goal_id == "MY_REWARDS"),
        None,
    )
    assert goal is not None, (
        "unchanged on purpose: 0 episodes means 0 measured waste. If this starts being "
        "selected, revisit it with the ledger in hand rather than on the shape alone."
    )