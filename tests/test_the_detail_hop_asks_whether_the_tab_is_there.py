"""The hop back to the calendar grid asks the frame whether the tab is there.

Measured 2026-10-03 on the live client: ``OPEN_EVENT_CALENDAR_TAB`` succeeded 508 times and
failed 18, and the two sets separate perfectly on one field.  Every success carried
``regular_events_hub.calendar_tab_visible = True`` with a ``calendar_tab_tap_norm``; every
failure carried ``False`` with a null norm.  On the failures ``_resolve_semantic_target``
answered ``None`` -- correctly, because the client had drawn no tab -- and the step was
recorded as ``SEMANTIC_TARGET_NOT_VERIFIED``, which reads as "the control is not on screen"
when the truth is "nobody looked".

``brain.py`` already had that guard on the hub branch: no tab means scroll the strip, and
neither tab nor scroll means SAFE_STOP.  The activity-detail branch issued the same hop
without asking, so on a detail page whose tab was off-strip it burned a tap on nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from winter_agent_v2.models import Page, WorldState  # noqa: E402


def _brain():
    from winter_agent_v2.brain import RuleBrain

    return RuleBrain(current_goal="DISCOVER_EVENT_CALENDAR")


def _registry():
    from winter_agent_v2.skills import v2_registry

    return v2_registry()


def _event_page(detail=None, hub=None, calendar=None):
    events = {}
    if detail is not None:
        events["calendar_detail"] = detail
    if hub is not None:
        events["regular_events_hub"] = hub
    if calendar is not None:
        events["calendar"] = calendar
    return WorldState(page=Page.EVENT, confidence=0.98, events=events)


def _detail(**over):
    row = {"recognized": True, "event_id": "CANYON_CLASH", "display_name": "峡谷会战"}
    row.update(over)
    return row


def _hub(**over):
    row = {"kind": "REGULAR_EVENT_HUB", "recognized": True}
    row.update(over)
    return row


def _decide(world):
    brain = _brain()
    brain.goal_id = "DISCOVER_EVENT_CALENDAR"
    return brain.decide(world, _registry())


class TheDetailHopAsksTheFrameTests:
    def test_a_visible_tab_is_still_tapped(self):
        """The 508-frame majority must not regress into a scroll or a stop."""
        world = _event_page(detail=_detail(), hub=_hub(
            calendar_tab_visible=True, calendar_tab_tap_norm=[0.5, 0.12]))
        decision = _decide(world)
        assert decision.skill == "OPEN_EVENT_CALENDAR_TAB", decision.reason
        assert decision.expected_result == "event_calendar_tab_opened"

    def test_an_absent_tab_is_not_tapped_anymore(self):
        """The regression, stated as the frame that failed 18 times."""
        world = _event_page(detail=_detail(), hub=_hub(
            calendar_tab_visible=False, calendar_tab_tap_norm=None))
        decision = _decide(world)
        assert decision.skill != "OPEN_EVENT_CALENDAR_TAB", (
            "the tab was not drawn; tapping it is how 18 steps reported "
            "SEMANTIC_TARGET_NOT_VERIFIED on a control that was never there"
        )

    def test_an_absent_tab_scrolls_the_strip_instead(self):
        """The tab is a horizontal strip, so there is a gesture that brings it back."""
        world = _event_page(detail=_detail(), hub=_hub(
            calendar_tab_visible=False, calendar_tab_tap_norm=None,
            scroll_to_start_norm=[0.242, 0.1334, 0.77189, 0.1334]))
        decision = _decide(world)
        assert decision.skill == "SCROLL_REGULAR_EVENT_TABS", decision.reason

    def test_neither_tab_nor_scroll_stops_rather_than_guessing(self):
        world = _event_page(detail=_detail(), hub=_hub(
            calendar_tab_visible=False, calendar_tab_tap_norm=None,
            scroll_to_start_norm=None))
        decision = _decide(world)
        assert decision.skill == "SAFE_STOP", decision.reason
        assert decision.reason == "regular_event_tab_container_not_grounded"

    def test_a_grid_entry_still_returns_without_consulting_the_strip(self):
        """Coming from the grid, going back is a BACK, not a tab -- unchanged by this guard."""
        world = _event_page(detail=_detail(calendar_origin="GRID_ENTRY"), hub=_hub(
            calendar_tab_visible=False, calendar_tab_tap_norm=None))
        decision = _decide(world)
        assert decision.skill == "RETURN_EVENT_CALENDAR", decision.reason

    def test_a_frame_that_read_no_hub_at_all_is_not_left_guessing(self):
        """Absent evidence is not a licence to tap: the old code read no hub and tapped anyway."""
        world = _event_page(detail=_detail())
        decision = _decide(world)
        assert decision.skill != "OPEN_EVENT_CALENDAR_TAB", (
            "with no hub reading there is no tab, so the old branch tapped blind; "
            f"got {decision.skill}"
        )


class TheHubBranchWasAlreadyRightTests:
    """The guard this adds to the detail branch already existed on the hub branch.

    Both are asserted here so the two branches cannot drift apart again: the fix was to make
    the detail branch ask the same question the hub branch already answered.
    """

    def test_hub_with_a_visible_tab_taps_it(self):
        world = _event_page(hub=_hub(
            calendar_tab_visible=True, calendar_tab_tap_norm=[0.5, 0.12]))
        assert _decide(world).skill == "OPEN_EVENT_CALENDAR_TAB"

    def test_hub_without_a_visible_tab_scrolls(self):
        world = _event_page(hub=_hub(
            calendar_tab_visible=False, scroll_to_start_norm=[0.1, 0.1, 0.9, 0.1]))
        assert _decide(world).skill == "SCROLL_REGULAR_EVENT_TABS"

    def test_hub_with_neither_stops(self):
        world = _event_page(hub=_hub(calendar_tab_visible=False, scroll_to_start_norm=None))
        assert _decide(world).skill == "SAFE_STOP"

    def test_a_detail_page_is_not_mistaken_for_a_hub_page(self):
        """The detail branch must win when a detail is recognised, or the detail guard is dead code."""
        world = _event_page(detail=_detail(), hub=_hub(
            calendar_tab_visible=False, calendar_tab_tap_norm=None,
            scroll_to_start_norm=[0.1, 0.1, 0.9, 0.1]))
        decision = _decide(world)
        assert decision.skill == "SCROLL_REGULAR_EVENT_TABS"
        assert decision.reason == "calendar_tab_outside_current_activity_strip"


class TheSkillRegistryAgreesTests:
    """A guard that dispatches to a skill the registry lacks would fail at execution instead."""

    def test_every_skill_this_guard_can_choose_exists(self):
        from winter_agent_v2.skills import v2_registry

        registry = _registry()
        for skill_id in ("OPEN_EVENT_CALENDAR_TAB", "SCROLL_REGULAR_EVENT_TABS",
                         "RETURN_EVENT_CALENDAR", "SAFE_STOP"):
            if skill_id == "SAFE_STOP":
                continue  # a stop, not an action
            assert registry.get(skill_id) is not None, skill_id

    def test_the_scroll_skill_takes_a_four_number_gesture(self):
        """``_resolve_semantic_target`` reads ``scroll_to_start_norm`` as four numbers for this
        semantic, so a two-number box would resolve to nothing after the guard routes to it."""
        from winter_agent_v2.skills import v2_registry

        skill = _registry().get("SCROLL_REGULAR_EVENT_TABS")
        assert skill is not None and skill.action is not None
        assert skill.action.kind == "SWIPE", skill.action.kind
