"""A plan and an identity are two different questions about the same registry.

`known_activities()` originally returned every gate, because filtering DISCOVERED rows out had once
made "not yet verified" look like "does not exist" -- and it was the only source of the project's
event vocabulary, so a frame printing 联盟总动员 had to keep resolving to ALLIANCE_MOBILIZATION.

But the goal layer built a ticket -- with `prepare`, `participation_conditions` and
`next_open_condition` -- for every row it returned.  A DISCOVERED row has none of those reviewed;
the registry's own `gate` says so.  Measured 2026-10-05: 21 `SCHEDULED_*` tickets were on the board
and 14 of them were leads the registry had not vouched for.

The fix separated the two jobs rather than choosing between them:

  * `known_activities()`      -- what a plan may be built from (REVIEWED / VERIFIED only)
  * `registry_activities()`   -- the identity vocabulary (every known gate)

These tests keep both halves true, because dropping either one is a real regression: over-filter and
the OCR stops recognising a discovered event's name, under-filter and unreviewed leads get plans.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.event_goal import (  # noqa: E402
    event_id_for_label,
    known_activities,
    registry_activities,
)


class OnlyRegistryVouchedGatesBecomePlansCase:
    def test_a_plan_is_built_only_from_reviewed_or_verified_rows(self):
        activities = known_activities()
        assert activities, "the registry must vouch for at least one plannable activity"
        for activity in activities:
            assert activity.gate in {"REVIEWED", "VERIFIED"}, (
                f"{activity.event_id} is a {activity.gate} lead; a lead is not a plan"
            )

    def test_bear_hunt_is_still_plannable(self):
        """The fix must not achieve correctness by dropping the event the operator asked about."""
        assert "BEAR_HUNT" in {a.event_id for a in known_activities()}

    def test_a_discovered_lead_is_not_silently_deleted(self):
        """It keeps its place in the registry -- it just does not get a ticket."""
        plannable = {a.event_id for a in known_activities()}
        registered = {a.event_id for a in registry_activities()}
        assert plannable, "REVIEWED/VERIFIED rows must survive the split"
        assert plannable < registered, (
            "the vocabulary must be a strict superset: filtering the plan must not shrink identity"
        )


class TheIdentityVocabularyIsNotShrunkByThePlanFilterCase:
    def test_a_discovered_events_label_still_resolves(self):
        """The original worry, kept as a test: over-filtering makes an event stop existing.

        A frame that prints a discovered activity's name must resolve to its id, or the generic
        flow/Qwen fallback can never see it -- the exact regression the old docstring records.
        """
        discovered = [a for a in registry_activities() if a.gate == "DISCOVERED"]
        assert discovered, "this registry carries discovered leads; the vocabulary must include them"
        for activity in discovered:
            assert event_id_for_label(activity.name) == activity.event_id, (
                f"{activity.name} no longer resolves to {activity.event_id}"
            )
            for alias in activity.aliases:
                if alias.strip():
                    assert event_id_for_label(alias) == activity.event_id

    def test_an_unknown_label_stays_unknown(self):
        assert event_id_for_label("这不是任何已登记活动") is None
        assert event_id_for_label("") is None
