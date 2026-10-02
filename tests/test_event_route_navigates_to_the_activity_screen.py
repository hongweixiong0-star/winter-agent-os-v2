"""An EVENT-route goal must navigate toward the activity screen, not fall through to gather.

Measured 2026-10-02 on the live device, revisions 9f468b3 / 2ee4908 / 5b7e9cd / f3e5d8d
(222 episodes total).  ``SCHEDULED_*`` goals were selected **66 times** through their
observation ticket and produced **38 episodes** on the pages where they were selected:

    pages    MARCH 12 · MAP 9 · RESOURCE_DETAIL 8 · HOME 8 · ALLIANCE 1
    skills   INTEL_HERO_DISPATCH 12 · START_GATHER 8 · OPEN_MAP 8
             SUBMIT_RESOURCE_SEARCH 7 · SELECT_RESOURCE 2 · BACK 1
    results  SUCCESS 26 · FAILURE 12
    goal_progress == True   **0**

Twenty-six verified successes and not one unit of goal progress.  ``RuleBrain.decide`` has
exactly two branches for the EVENT route (``brain.py:753`` and ``brain.py:782``) and both
require ``world.page is Page.EVENT``.  On any other page an EVENT-route goal walks the whole
``if`` chain to the generic ``registry.ready(world)`` fallback at ``brain.py:2903`` and takes
whatever the page offers -- which is how a 兄弟手臂 activity ends up dispatching a gather
hero and having the verifier declare it a success.

The honest reading of that episode pair, straight from the ledger:

    skill SUBMIT_RESOURCE_SEARCH | verifier_ok True | goal_progress False
    verifier_evidence {"configured_wood": true, "resource_page": "RESOURCE_DETAIL", ...}
    goal_progress_by_id {"SCHEDULED_STATE_VS_STATE": false}

``verifier_ok`` answers "did the resource page accept this search", which is true and
irrelevant.  ``goal_progress`` is the field that knows the difference, and it is false.

**The map has no way in, and that is not a bug to code around.** Measured on 148 live
MAP/HOME frames since the new revisions: frames carrying a visible 常规活动 entry,
**0**.  ``read_calendar_entry`` needs the label at heading scale on the current frame, and
the client draws it only in the city.  So the correct first move from the field is
``OPEN_HOME`` -- the same thing ``_append_event_calendar_goal`` already emits for a due
calendar scan -- and the 常规活动 entry from the HOME frame.  This test pins that shape and
refuses the shortcut that would fake it: a tap at a remembered position is the one thing the
production constitution forbids outright, and a test that let one pass would be worse than
the defect.
"""

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState


def _world(page, **kwargs):
    return WorldState(page=page, confidence=0.99, **kwargs)


def _brain(current_goal, *, goal_id=""):
    brain = RuleBrain()
    brain.current_goal = current_goal
    brain.goal_id = goal_id
    return brain


def test_an_event_route_goal_on_the_map_goes_to_the_city_not_to_gather():
    """The measured waste, in one assertion.

    ``goal_progress == 0`` across 38 episodes was produced by exactly this: an EVENT-route
    goal on a non-EVENT page reaching the generic fallback.  On the map the only honest
    next move is the city HUD, because that is where the client draws the entry.
    """
    brain = _brain("EVENT", goal_id="SCHEDULED_BROTHERS_IN_ARMS")
    decision = brain.decide(_world(Page.MAP, march_used=1, march_max=6), registry=_registry())
    assert decision.skill != "OPEN_MAP", (
        "OPEN_MAP is what the generic fallback produced; it is the action that made "
        "26 verified successes with zero goal progress"
    )
    assert decision.skill == "OPEN_HOME", (
        f"expected the city HUD as the only route to an activity entry, got {decision.skill!r}"
    )


def test_an_event_route_goal_in_the_city_uses_the_entry_the_frame_actually_draws():
    """With the entry visible, the move is the entry -- and its geometry is the frame's."""
    entry = {"visible": True, "tap_norm": [0.226, 0.032], "source": "CURRENT_FRAME_OCR"}
    brain = _brain("EVENT", goal_id="SCHEDULED_CANYON_CLASH")
    decision = brain.decide(
        _world(Page.HOME, events={"calendar_entry": entry}), registry=_registry()
    )
    assert decision.skill == "OPEN_EVENT_CALENDAR_FROM_HOME"
    assert _registry().get(decision.skill) is not None, (
        "the branch must name a registered skill, not a plausible-looking string"
    )


def test_no_event_route_branch_ever_invents_a_tap_point():
    """The constitution's first rule, as an executable assertion.

    ``read_calendar_entry`` returns a ``tap_norm`` measured on the frame it was read from,
    and it returns ``None`` when it cannot measure one.  So the branch above must key on
    ``visible is True`` and the resolver must carry the point; a branch that "knows" where
    the entry is would be a memorised coordinate wearing a skill's name.
    """
    brain = _brain("EVENT", goal_id="SCHEDULED_CANYON_CLASH")
    decision = brain.decide(
        _world(Page.HOME, events={"calendar_entry": {"visible": False}}), registry=_registry()
    )
    assert decision.skill != "OPEN_EVENT_CALENDAR_FROM_HOME", (
        "the frame drew no entry, so there is nothing to tap; this is the case that must "
        "decline rather than act on a remembered position"
    )


def test_an_event_route_goal_on_the_event_page_is_left_to_its_own_branches():
    """The two existing EVENT branches own that page; this must not preempt them.

    ``brain.py:753`` decides whether a non-EVENT goal leaves an activity session, and
    ``brain.py:782`` is the bounded ordinary-control fallback for a live EVENT goal.  A new
    navigation branch placed above them would silently replace both.
    """
    brain = _brain("EVENT", goal_id="SCHEDULED_CANYON_CLASH")
    decision = brain.decide(_world(Page.EVENT), registry=_registry())
    assert decision.skill in {"TRY_ORDINARY_CONTROL", "SAFE_STOP", "BACK"}, (
        f"the activity page keeps its own handling, got {decision.skill!r}"
    )


def test_a_gather_goal_is_unaffected_by_the_new_navigation():
    """The control group.  This change is about the EVENT route and nothing else.

    If GATHER_RESOURCE ever starts returning OPEN_HOME, the ordinary work loop has been
    broken by a fix aimed at a different goal family.
    """
    brain = _brain("GATHER_RESOURCE")
    decision = brain.decide(
        _world(Page.MAP, march_used=1, march_max=6, resource_target="MEAT"), registry=_registry()
    )
    assert decision.skill not in {"OPEN_EVENT_CALENDAR_FROM_HOME", "OPEN_EVENT_CALENDAR_FROM_MAP"}


def _registry():
    from winter_agent_v2.skills import v2_registry
    return v2_registry()
