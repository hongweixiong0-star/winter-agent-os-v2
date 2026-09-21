"""CAP-Z01: the dispatchable beast is a table row, not a literal pair.

Measured 2026-09-17.  ``("MUSK_OX", 9)`` was written into the brain's BEAST_HUNT
route and into three verifiers, while ``knowledge/game/beasts.json`` already knew
about 麝牛/9 (dispatched live), 北极狼/6 and 雪豹/29 (refused on its red
assessment, ``action_result: BLOCKED_BEFORE_DISPATCH``).  None of that could
reach the route, so the level-24/25 moose on the current role's map had no way
to be judged at all.

Both halves are pinned here:

* today's behaviour is unchanged -- exactly one row is dispatchable, and the
  route/verifiers answer for it exactly as before;
* a row added to a *copy* of the table becomes dispatchable with no code change,
  which is the whole point of the slice.

The second half is the one that matters.  A test that only re-asserted
``MUSK_OX`` would pass just as well against the old literal.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from winter_agent_v2 import beast_targets as bt
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import (
    verify_beast_march_open,
    verify_beast_target_selected,
)

TABLE = Path(bt.__file__).resolve().parents[1] / "knowledge/game/beasts.json"


def table_copy(records: list[dict]) -> Path:
    """A scratch table, so a test can add a row without touching production."""
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump({"schema_version": "1.1", "records": records}, handle, ensure_ascii=False)
    handle.close()
    return Path(handle.name)


def record(**overrides) -> dict:
    base = {
        "id": "TEST_BEAST_7_LIVE",
        "name": "测试兽",
        "species": "TEST_BEAST",
        "dispatchable": True,
        "level": 7,
        "victory_assessment": bt.GREEN_ASSESSMENT,
        "status": "VERIFIED",
    }
    base.update(overrides)
    return base


class TableTest(unittest.TestCase):
    def test_the_live_verified_musk_ox_is_still_the_anchored_target(self):
        """The one row a live dispatch proved end to end, and its green assessment."""
        ox = bt.lookup("MUSK_OX", 9)
        self.assertIsNotNone(ox)
        self.assertTrue(ox.dispatchable)
        self.assertEqual(ox.name, "麝牛")
        self.assertEqual(ox.victory_assessment, bt.GREEN_ASSESSMENT)

    def test_every_dispatchable_row_is_justified_by_its_own_data(self):
        """The discipline, rather than a frozen count -- this test replaces one that said
        "exactly the musk ox".

        That assertion was written when the table held one target, and it went stale the
        moment a second row was added deliberately (MAMMOTH/5, 2026-09-18).  Freezing a
        count does not protect anything: what protects the route is that no row becomes
        dispatchable *without its own evidence saying why*.  So the rule asserted here is
        the one that must hold whatever the table grows to:

          * a live-verified row carries the exact green assessment string the dialog
            printed on a run whose dispatch verified; or
          * an explicitly-marked CANDIDATE carries a note naming the verifier that still
            gates each spend, and does not claim to be verified.

        A dispatchable row with neither is the overclaim this test exists to catch.
        """
        allowed = bt.dispatchable()
        self.assertTrue(allowed, "an empty dispatchable table would mean the route is dead")
        for target in allowed:
            if target.victory_assessment == bt.GREEN_ASSESSMENT:
                continue
            self.assertNotEqual(
                target.status, "VERIFIED",
                f"{target.species}/{target.level} claims VERIFIED without the green "
                f"assessment the client prints",
            )
            self.assertEqual(
                target.status, "CANDIDATE",
                f"{target.species}/{target.level} is dispatchable with no evidence at all: "
                f"status={target.status}, assessment={target.victory_assessment!r}",
            )
            self.assertTrue(
                target.notes and "verifier" in target.notes.lower(),
                f"{target.species}/{target.level} is a CANDIDATE without a note saying what "
                f"still gates the spend: {target.notes!r}",
            )

    def test_the_refused_row_still_records_why_it_is_refused(self):
        # 雪豹/29 is in the table on purpose: it was shown to the operator and
        # rejected before any stamina was spent.  A generalised route must read
        # that row as "not dispatchable" rather than as "unknown".
        leopard = bt.lookup("SNOW_LEOPARD", 29)
        self.assertIsNotNone(leopard)
        self.assertFalse(leopard.dispatchable)
        self.assertNotEqual(leopard.victory_assessment, bt.GREEN_ASSESSMENT)

    def test_a_reviewed_row_is_not_proven(self):
        # 北极狼/6 prints the green assessment but its own row says REVIEWED, and
        # one live run is not the same as a verified route.  Opt-in is separate
        # from the wording on screen.
        wolf = bt.lookup("ARCTIC_WOLF", 6)
        self.assertIsNotNone(wolf)
        self.assertFalse(wolf.dispatchable)

    def test_a_row_added_to_a_copy_becomes_dispatchable_without_a_code_change(self):
        scratch = table_copy([record()])
        try:
            self.assertTrue(bt.is_dispatchable({"visible_target": "TEST_BEAST", "level": 7}, bt.load(scratch)))
            # ... and the production table still allows only the musk ox.
            self.assertFalse(bt.is_dispatchable({"visible_target": "TEST_BEAST", "level": 7}))
        finally:
            scratch.unlink()

    def test_a_row_without_an_opt_in_is_never_dispatchable(self):
        scratch = table_copy([record(dispatchable=False, id="TEST_BEAST_7")])
        try:
            self.assertFalse(bt.is_dispatchable({"visible_target": "TEST_BEAST", "level": 7}, bt.load(scratch)))
        finally:
            scratch.unlink()

    def test_the_production_table_is_readable_and_has_levels(self):
        rows = bt.load(TABLE)
        self.assertTrue(rows)
        self.assertTrue(all(isinstance(t.level, int) for t in rows))


class PredicateTest(unittest.TestCase):
    def test_the_live_route_target_is_still_dispatchable(self):
        self.assertTrue(bt.is_dispatchable({"visible_target": "MUSK_OX", "level": 9, "available": True}))

    def test_an_empty_fragment_is_refused_not_guessed(self):
        for fragment in ({}, None, {"visible_target": "MUSK_OX"}, {"level": 9}):
            self.assertFalse(bt.is_dispatchable(fragment), fragment)

    def test_an_unknown_species_is_refused(self):
        self.assertFalse(bt.is_dispatchable({"visible_target": "MOOSE", "level": 24}))

    def test_a_known_species_at_the_wrong_level_is_refused(self):
        self.assertFalse(bt.is_dispatchable({"visible_target": "MUSK_OX", "level": 24}))

    def test_the_printeds_assessment_decides_when_it_is_on_the_frame(self):
        self.assertTrue(bt.is_dispatchable(
            {"visible_target": "MUSK_OX", "level": 9, "victory_assessment": bt.GREEN_ASSESSMENT}))
        self.assertFalse(bt.is_dispatchable(
            {"visible_target": "MUSK_OX", "level": 9, "victory_assessment": "本次出征胜算较低"}))


class RouteTest(unittest.TestCase):
    """The brain's decision, not just the helper it calls."""

    def setUp(self):
        self.brain = RuleBrain(current_goal="BEAST_HUNT")
        self.registry = v2_registry()

    def test_a_dispatchable_target_is_selected(self):
        world = WorldState(page=Page.MAP, march_used=0,
                           beast={"visible_target": "MUSK_OX", "level": 9, "available": True},
                           confidence=0.99)
        self.assertEqual(self.brain.decide(world, self.registry).skill, "SELECT_BEAST_TARGET")

    def test_a_target_the_table_refuses_is_not_selected(self):
        # The level-29 leopard is the measured refusal; the route must look for a
        # different target rather than spend on it.
        #
        # Since 2026-09-21 "look for a different target" starts with the client's
        # own search rather than a viewport pan: the pan cannot fly to a beast and
        # its own record shows it searched bare snow on 23 frames.  The intent of
        # this test is unchanged -- the refused target is not selected -- and the
        # route's first move away from it is now the search.
        world = WorldState(page=Page.MAP, march_used=0,
                           beast={"visible_target": "SNOW_LEOPARD", "level": 29, "available": True},
                           confidence=0.99)
        self.assertNotEqual(self.brain.decide(world, self.registry).skill, "SELECT_BEAST_TARGET")
        self.assertEqual(self.brain.decide(world, self.registry).skill, "SEARCH_RESOURCE")

    def test_an_unrecognised_map_scans_for_a_known_target(self):
        world = WorldState(page=Page.MAP, march_used=0, confidence=0.99)
        self.assertEqual(self.brain.decide(world, self.registry).skill, "SEARCH_RESOURCE")
        # And the pan is still reachable once the search has been spent.
        self.brain.beast_search_used = True
        self.assertEqual(self.brain.decide(world, self.registry).skill, "SCAN_MAP_FOR_BEAST")


class VerifierTest(unittest.TestCase):
    def test_the_live_route_still_verifies_end_to_end(self):
        before = WorldState(page=Page.MAP, march_used=0,
                            beast={"visible_target": "MUSK_OX", "level": 9, "available": True},
                            confidence=0.99)
        after = WorldState(page=Page.BEAST,
                           beast={"name": "麝牛", "level": 9, "available": True}, confidence=0.99)
        self.assertTrue(verify_beast_target_selected(before, after).ok)

    def test_a_dialog_the_table_does_not_carry_is_not_proven(self):
        before = WorldState(page=Page.MAP, march_used=0,
                            beast={"visible_target": "MUSK_OX", "level": 9, "available": True},
                            confidence=0.99)
        after = WorldState(page=Page.BEAST,
                           beast={"name": "驼鹿", "level": 24, "available": True}, confidence=0.99)
        self.assertFalse(verify_beast_target_selected(before, after).ok)

    def test_the_formation_page_needs_a_row_the_route_may_spend_on(self):
        before = WorldState(page=Page.BEAST,
                            beast={"name": "麝牛", "level": 9, "available": True}, confidence=0.99)
        after = WorldState(page=Page.MARCH,
                           beast={"name": "麝牛", "victory_assured": True}, confidence=0.99)
        self.assertTrue(verify_beast_march_open(before, after).ok)

        stranger = WorldState(page=Page.BEAST,
                              beast={"name": "驼鹿", "level": 24, "available": True}, confidence=0.99)
        self.assertFalse(verify_beast_march_open(stranger, after).ok)


if __name__ == "__main__":
    unittest.main()
