"""An activity ticket that names what it needs read must carry a way to read it.

Measured 2026-10-03 on the 24 hours then: all 20 ``SCHEDULED_*`` tickets were selected
121 times and 284 decisions named one as the winner, and the skills they actually ran were
``OPEN_MAP`` 38, ``INTEL_HERO_DISPATCH`` 26, ``START_GATHER`` 15,
``SUBMIT_RESOURCE_SEARCH`` 14 -- none of them about the activity.

The cause was never visibility.  The observation ticket prices these rows (measured 50.0)
and ``goal_utility.rank`` keeps any row whose price reaches, so they *were* on the board.
It was ``available_skills=()``: with no action to issue, the brain fell through to the
generic fallback and the page happened to be the map, so it went to the map.  A scheduled
observation that has no observation step is how reading an activity turns into gathering
stamina instead.

The action offered is ``READ_EVENT_CALENDAR`` -- ``Action("OBSERVE", "EVENT_CALENDAR")``
on ``Page.EVENT``, verified by the implemented ``verify_event_calendar_read``, which passes
only on page EVENT plus a recognised calendar plus at least two distinct date anchors plus at
least one entry.  It takes no input and claims nothing, so a ticket blocked on
``required_observation`` cannot become a way to act on an activity whose live conditions
were never read.

These tests pin the pairing (a declared observation has a matching action) and the refusal
(``READ_TIMER`` looks like a closer fit and is not offered, because its ``TIMER_READ``
verifier does not exist in the package).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2 import event_schedule as es  # noqa: E402
from winter_agent_v2 import goal_library as gl  # noqa: E402
from winter_agent_v2 import goal_utility as gu  # noqa: E402
from winter_agent_v2 import verifier as V  # noqa: E402
from winter_agent_v2.models import WorldState  # noqa: E402
from winter_agent_v2.skills import Page, v2_registry  # noqa: E402

OBSERVATION_SKILLS = gl._ACTIVITY_OBSERVATION_SKILLS


def _tickets() -> list:
    snapshot = es.latest_calendar_snapshot("1063040265") or {}
    return gl.GoalLibrary().discover(WorldState(page=Page.EVENT, events={"calendar": snapshot}))


def test_every_waiting_activity_ticket_carries_a_reading_action():
    tickets = [g for g in _tickets() if str(g.goal_id).startswith("SCHEDULED_")]
    if not tickets:
        pytest.skip("no activity tickets in the current window")
    without = [g.goal_id for g in tickets if not g.available_skills]
    assert not without, (
        f"{len(without)} activity tickets name a required_observation but offer no action: "
        f"{without[:6]}. A selected ticket with no skill runs the generic fallback, which "
        "is how reading an activity becomes gathering stamina."
    )


def test_the_offered_action_exists_with_a_verifier_that_is_implemented():
    """A declared verifier is not an implemented one; this is the trap that was avoided."""
    registry = v2_registry()
    for name in OBSERVATION_SKILLS:
        skill = registry.get(name)
        assert skill is not None, f"{name} is offered but is not in the skill registry"
        assert skill.verifier, f"{name} declares no verifier"
        assert skill.required_page is Page.EVENT, (
            f"{name} reads the calendar but is not declared for Page.EVENT, so it can never "
            "be ready on the page it exists to read"
        )
        # The binding the runtime actually uses, and the function behind it.
        assert hasattr(V, "verify_event_calendar_read"), (
            f"{name}'s verifier is declared in skills.py but the runtime binds an "
            "implemented function; adding a skill whose verifier is missing turns an "
            "invisible ticket into one certain to fail"
        )
    source = (ROOT / "winter_agent_v2/runtime.py").read_text(encoding="utf-8")
    for name in OBSERVATION_SKILLS:
        assert f'"{name}":' in source, (
            f"{name} is offered by goal_library but runtime.py has no entry mapping it to a "
            "verifier, so selecting it would raise instead of observing"
        )


def test_read_timer_is_deliberately_not_offered():
    """It reads closer to "read this activity's window" and it cannot be executed."""
    assert "READ_TIMER" not in OBSERVATION_SKILLS, (
        "READ_TIMER's declared TIMER_READ verifier and its execution path are absent from "
        "winter_agent_v2, so offering it would convert 'no action' into 'an action that "
        "always fails'. Add the verifier first, then reconsider."
    )
    # The declaration at skills.py is expected -- a skill may name a verifier that nothing
    # implements yet.  What must not exist is the wiring that would make it executable: a
    # runtime mapping key binding it to a verifier function, and a dispatch site.  A name in
    # a declaration is a wish; a name as a mapping key is a route.
    runtime = (ROOT / "winter_agent_v2/runtime.py").read_text(encoding="utf-8")
    assert '"READ_TIMER":' not in runtime and "'READ_TIMER':" not in runtime, (
        "READ_TIMER is now bound to a verifier in runtime.py; if that verifier is "
        "implemented, the choice of READ_EVENT_CALENDAR should be revisited on its merits"
    )
    registry = (ROOT / "winter_agent_v2/verifier.py").read_text(encoding="utf-8")
    assert "TIMER_READ" not in registry, (
        "verify_timer_read now exists; nothing forces the tickets onto it, but the reason "
        "recorded in goal_library for not offering READ_TIMER is no longer true"
    )


def test_offering_a_read_does_not_reprice_the_ticket_as_work():
    """Reading is half of doing, and the observation ticket must stay the whole price.

    ``observation_ticket`` deliberately returns a value the utility layer installs as the
    base rather than adding on top, so a ticket that can now act is still not competing as
    though it had already made progress.
    """
    tickets = [g for g in _tickets() if str(g.goal_id).startswith("SCHEDULED_")]
    if not tickets:
        pytest.skip("no activity tickets in the current window")
    ranked = gu.rank(tickets)
    assert ranked, "the tickets are priced and must still reach the board"
    for goal, breakdown in ranked:
        if str(goal.goal_id).startswith("SCHEDULED_"):
            assert breakdown.observation == breakdown.base, (
                f"{goal.goal_id}: observation {breakdown.observation} and base "
                f"{breakdown.base} must be the same number -- the ticket is the price, not an "
                "extra on top of it"
            )
            break
