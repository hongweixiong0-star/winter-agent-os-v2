"""The gather formation's resource must be a frame fact or nothing -- never a fabrication.

Regression under test (2026-10-02)
----------------------------------
``DISPATCH_MARCH`` was refused with ``STALE_OR_ROLE_UNSCOPED_FORMATION`` on the one attempt it has
ever had, and seven of that name's eight sub-conditions held on the failing frame.  The odd one out
was ``formation.resource_type ("WOOD") == before.resource_target ("MEAT")`` -- and ``resource_target``
was MEAT from step 7 to step 20 of that episode, never WOOD.

Two fabrications met in that comparison:

* the MARCH page's own reader synthesises ``WorldState(page=Page.MARCH, resource_target="WOOD")``
  from the dispatch button's template -- the picture never said WOOD (its header prints 生肉), so
  this is a frame fact invented by code; measured with the production stack on the archived frames,
  all four return ``resource_target == "WOOD"``;
* ``_annotate_gather_formation`` froze that value into evidence, falling back to
  ``self._active_gather_resource`` -- a *memory of another goal's plan* -- when the observation had
  nothing.

What the run was actually doing, replayed through the real policy on the recorded formations:

    step 14  policy(MEAT) -> CLEANUP_REQUIRED remove_slots=[2, 3]   the run cleared 2 and 3
    step 15  policy(MEAT) -> CLEANUP_REQUIRED remove_slots=[3]      the run cleared 3
    step 16  policy(MEAT) -> READY_WITH_SPECIALIST remove_slots=[]  ...and the dispatch was refused

So the clearing loop was correct and the formation did reach ready for the resource the run meant to
send.  The verifier never even evaluated the policy -- the role-scope clause short-circuits ahead of
it -- and on this frame the clause could never pass, for any resource but the placeholder.  The run
then re-searched, re-submitted, re-started and cleared again, which is stamina spent per lap.

The fix keeps the guard and stops it lying: the page states nothing, so the record says so
(``resource_source``), the value the dispatch will use is stamped where the plan is known, and the
resource clause only blocks a disagreement the *page* actually produced.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.live_stack import production_vision  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.verifier import verify_wood_dispatch_from_march  # noqa: E402

EPISODE = "20261002_172120_360764"
RUN = ROOT / "dataset/raw/control_panel/runtime_auto" / EPISODE
FORMATION_FRAME = RUN / f"{EPISODE}_step_016_before_20261002T092406618948.png"

# The formation as the run recorded it at step 16: one occupied slot holding the MEAT specialist,
# two empty, observed on this very frame, under the role that is running.
MEAT_SPECIALIST = "HERO_CLORIS"


def _formation(**overrides):
    record = {
        "status": "OBSERVED",
        "page": "PAGE_FORMATION",
        "role_id": "1063040265",
        "role_scope": "FRESH_RUNTIME",
        "observed_at": "2026-10-02T09:24:07.355820+00:00",
        "source_frame": "…/step_016_before_20261002T092406618948.png",
        "slots": [
            {"slot": 1, "state": "OCCUPIED", "hero_state": "SELECTED",
             "hero_id": MEAT_SPECIALIST, "identity_status": "IDENTITY_CONFIRMED"},
            {"slot": 2, "state": "EMPTY", "hero_state": None},
            {"slot": 3, "state": "EMPTY", "hero_state": None},
        ],
        "empty_slots": [2, 3],
        "specialist_availability": "UNKNOWN",
        "resource_type": "MEAT",
        "resource_source": "PLANNED",
        "resource_observed": None,
    }
    record.update(overrides)
    return record


def _world(formation, *, target="MEAT", timestamp="2026-10-02T09:24:07.355820+00:00",
           page=Page.MARCH):
    return WorldState(page=page, resource_target=target, hero_troop={"gather_formation": formation},
                      timestamp=timestamp, confidence=0.99)


def _after_success():
    from winter_agent_v2.models import MarchState
    return WorldState(page=Page.MAP, marches=(MarchState.GATHERING,), march_used=1,
                      resource_target="MEAT", confidence=0.99)


class ThePageDoesNotInventAResourceTest(unittest.TestCase):
    """A synthesized state must not state a resource the picture did not show."""

    def test_the_archived_formation_page_yields_no_resource_from_its_reader(self):
        vision = production_vision()
        if vision is None or not FORMATION_FRAME.is_file():
            self.skipTest("production OCR stack or the archived frame is unavailable here")
        observed = vision.observe(FORMATION_FRAME)
        self.assertEqual(observed.page.value, "MARCH")
        self.assertIsNone(
            observed.resource_target,
            "the dispatch button proves the page, not the resource: it must not report WOOD",
        )


class TheFormationRecordNamesItsSourceTest(unittest.TestCase):
    """``resource_type`` alone cannot say whether it was read or assumed; ``resource_source`` can."""

    def _runtime(self):
        runtime = object.__new__(LiveRuntime)
        runtime.role_id = "1063040265"
        runtime.role_scope = "FRESH_RUNTIME"
        return runtime

    def test_an_unread_page_leaves_the_record_without_a_resource(self):
        runtime = self._runtime()
        world = WorldState(page=Page.MARCH, resource_target=None, timestamp="T", confidence=0.99)
        annotated = runtime._annotate_gather_formation(world, FORMATION_FRAME)
        record = annotated.hero_troop["gather_formation"]
        self.assertIsNone(record.get("resource_type"))
        self.assertEqual(record.get("resource_source"), "NONE")

    def test_a_remembered_resource_is_never_substituted_for_a_reading(self):
        """``_active_gather_resource`` is another goal's plan; it must not fill this record."""
        runtime = self._runtime()
        runtime._active_gather_resource = "WOOD"
        world = WorldState(page=Page.MARCH, resource_target=None, timestamp="T", confidence=0.99)
        annotated = runtime._annotate_gather_formation(world, FORMATION_FRAME)
        record = annotated.hero_troop["gather_formation"]
        self.assertNotEqual(record.get("resource_type"), "WOOD")
        self.assertEqual(record.get("resource_source"), "NONE")

    def test_the_plan_is_stamped_where_the_plan_is_known(self):
        runtime = self._runtime()
        world = WorldState(page=Page.MARCH, resource_target=None,
                           hero_troop={"gather_formation": _formation(resource_type=None,
                                                                     resource_source="NONE")},
                           confidence=0.99)
        stamped = runtime._stamp_gather_formation_resource(world, "MEAT")
        record = stamped.hero_troop["gather_formation"]
        self.assertEqual(record.get("resource_type"), "MEAT")
        self.assertEqual(record.get("resource_source"), "PLANNED")
        # What the page itself produced is kept, so the two can never be confused again.
        self.assertIn("resource_observed", record)

    def test_a_page_that_stated_nothing_is_not_overwritten_with_a_guess(self):
        """No formation on the frame means there is nothing to stamp -- not an empty record."""
        runtime = self._runtime()
        world = WorldState(page=Page.MAP, resource_target=None, confidence=0.99)
        self.assertIs(runtime._stamp_gather_formation_resource(world, "MEAT"), world)


class TheDispatchIsJudgedOnRealEvidenceTest(unittest.TestCase):
    def test_a_role_scoped_ready_formation_dispatches_when_the_page_stated_no_resource(self):
        """The step-16 shape: everything that can be checked is right, so the march goes out."""
        result = verify_wood_dispatch_from_march(_world(_formation()), _after_success())
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(result.evidence.get("gather_formation_policy"), "READY_WITH_SPECIALIST")
        self.assertEqual(result.evidence.get("gather_formation_resource_clause"),
                         "NOT_STATED_BY_PAGE")

    def test_a_page_that_stated_a_different_resource_is_still_refused(self):
        """The guard stays wired for the day a page reader exists: a real disagreement blocks."""
        formation = _formation(resource_type="WOOD", resource_source="PAGE",
                               resource_observed="WOOD")
        result = verify_wood_dispatch_from_march(_world(formation), _after_success())
        self.assertFalse(result.ok)
        self.assertEqual(result.evidence.get("gather_formation_resource_clause"), "DISAGREES")

    def test_a_page_that_agrees_is_not_refused(self):
        formation = _formation(resource_type="MEAT", resource_source="PAGE",
                               resource_observed="MEAT")
        result = verify_wood_dispatch_from_march(_world(formation), _after_success())
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(result.evidence.get("gather_formation_resource_clause"), "AGREES")

    def test_a_formation_from_another_frame_is_still_refused(self):
        formation = _formation(observed_at="2026-10-02T09:20:00.000000+00:00")
        result = verify_wood_dispatch_from_march(_world(formation), _after_success())
        self.assertFalse(result.ok)
        self.assertEqual(result.evidence.get("gather_formation_policy"),
                         "STALE_OR_ROLE_UNSCOPED_FORMATION")
        self.assertFalse(result.evidence.get("gather_formation_role_scoped"))

    def test_the_role_scope_field_answers_only_the_role_scope_question(self):
        """It used to fold the resource clause in, so it was false on a formation that was current.

        Measured on the failing row: ``gather_formation_is_current_role_scoped`` was False while the
        formation was observed on that very frame under the running role.
        """
        result = verify_wood_dispatch_from_march(_world(_formation()), _after_success())
        self.assertTrue(result.evidence.get("gather_formation_role_scoped"))


if __name__ == "__main__":
    unittest.main()
