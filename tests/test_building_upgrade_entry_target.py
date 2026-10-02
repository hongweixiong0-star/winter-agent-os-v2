"""The selected building's own 升级 control: the frame carries it, so the executor must read it.

Measured 2026-10-02, sanctioned pinned panel, role 1061663148, goal KEEP_BUILDING_PRODUCTIVE.
The step ran twice and failed identically both times:

    05:11:45  OPEN_BUILDING_UPGRADE   FAILURE
    05:51:29  OPEN_BUILDING_UPGRADE   FAILURE

    action            TAP_SEMANTIC / BTN_SELECTED_BUILDING_UPGRADE
    failure_type      SEMANTIC_TARGET_NOT_VERIFIED
    duration          0.171 s
    after_screenshot  (empty)

and the episode's own ``state_before`` says the control was right there:

    "building": {"id": "UNKNOWN", "name": "城墙", "level": 8, "target_level": 9,
                 "identity_confidence": 0.9983133375644684,
                 "identity_source": "FLOATING_LABEL_OCR+QUEST_BANNER",
                 "upgrade_tap_norm": [0.5, 0.7195]}

Reproduced read-only from the archived frame through the production chain with the same
attention the runtime sets (``focus(goal="KEEP_BUILDING_PRODUCTIVE")``; the 城墙 read path is
gated on that -- see ``_building_is_selected``): the state comes back byte-for-byte identical.
So the producer half already worked and was already covered by
``test_building_action_gate_fallback``; what was missing was the consumer.  ``BTN_SELECTED_
BUILDING_UPGRADE`` was named in exactly one place in the whole runtime -- the skill's own
``Action`` -- so the resolver fell through and answered nothing, which is
``SEMANTIC_TARGET_NOT_VERIFIED``, the project's largest failure family, in its cheapest possible
form: the answer was in the frame the whole time.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402

#: The exact frame the failing step saw.  Under ``dataset/raw/control_panel/runtime_auto``,
#: which retention prunes -- so the frame-dependent test below skips with a reason rather than
#: failing, because a test that goes red when the product does its job is a test that trains
#: the next reader to ignore red.
FRAME = (ROOT / "dataset/raw/control_panel/runtime_auto/20261002_135045_182262"
         / "20261002_135045_182262_step_004_before_20261002T055125902702.png")

#: The reading the live episode recorded for that frame.
LIVE_BUILDING = {
    "id": "UNKNOWN",
    "name": "城墙",
    "level": 8,
    "target_level": 9,
    "identity_confidence": 0.9983133375644684,
    "identity_source": "FLOATING_LABEL_OCR+QUEST_BANNER",
    "upgrade_tap_norm": [0.5, 0.7195],
}


def resolver():
    return LiveRuntime.__new__(LiveRuntime)


class TheExecutorReadsTheFramesOwnControlTests(unittest.TestCase):
    def test_the_tap_the_frame_carried_is_the_tap_that_is_used(self):
        """The one wire.  Everything else about this step already existed."""
        world = WorldState(page=Page.HOME, confidence=0.98, building=dict(LIVE_BUILDING))
        self.assertEqual(
            resolver()._resolve_semantic_target("BTN_SELECTED_BUILDING_UPGRADE", world),
            (0.5, 0.7195),
        )

    def test_a_tap_read_on_another_page_must_not_be_reused(self):
        """The resolver's own rule: ``None`` rather than a remembered offset.

        ``upgrade_tap_norm`` is read off the pixels of the frame it belongs to, so replaying it
        onto a frame that does not draw that action bar is exactly the stale-coordinate reuse the
        sibling branches guard against.
        """
        for page in (Page.MAP, Page.BUILDING, Page.POPUP):
            world = WorldState(page=page, confidence=0.98, building=dict(LIVE_BUILDING))
            self.assertIsNone(
                resolver()._resolve_semantic_target("BTN_SELECTED_BUILDING_UPGRADE", world),
                f"a tap measured on HOME must not be usable on {page}",
            )

    def test_the_client_did_not_draw_it_so_the_answer_is_nothing(self):
        """No selected building, and a selected building with no 升级 label, both answer None."""
        for building in ({}, {"name": "城墙", "level": 8}, {"name": "城墙", "upgrade_tap_norm": None}):
            world = WorldState(page=Page.HOME, confidence=0.98, building=building)
            self.assertIsNone(
                resolver()._resolve_semantic_target("BTN_SELECTED_BUILDING_UPGRADE", world),
                f"nothing to tap for {building!r}",
            )

    def test_a_malformed_or_off_frame_point_is_refused(self):
        """The same three guards the sibling frame-read branches apply."""
        for bad in ([0.5], [0.5, 0.7, 0.1], (0.5, 1.4), (-0.2, 0.5), ("x", 0.5), [None, 0.5]):
            world = WorldState(page=Page.HOME, confidence=0.98,
                               building={"name": "城墙", "upgrade_tap_norm": bad})
            self.assertIsNone(
                resolver()._resolve_semantic_target("BTN_SELECTED_BUILDING_UPGRADE", world),
                f"refused point {bad!r}",
            )


class TheSkillAndTheResolverAgreeTests(unittest.TestCase):
    def test_the_target_the_skill_declares_is_the_target_the_resolver_answers(self):
        """Tied through the registry, not through two copies of the same literal.

        If either side is renamed this fails, which is the point: the measured failure was two
        halves of one hop that had never been introduced to each other.
        """
        skill = v2_registry().get("OPEN_BUILDING_UPGRADE")
        self.assertIsNotNone(skill, "the brain names this skill; it has to exist")
        declared = skill.action.target
        world = WorldState(page=Page.HOME, confidence=0.98, building=dict(LIVE_BUILDING))
        self.assertEqual(
            resolver()._resolve_semantic_target(declared, world), (0.5, 0.7195),
            f"the skill declares {declared!r} and the resolver does not answer for it",
        )

    def test_opening_the_sheet_is_not_the_same_claim_as_starting_the_upgrade(self):
        """The order's own separation, asserted where it lives.

        ``OPEN_BUILDING_UPGRADE`` is judged by ``BUILDING_UPGRADE_PANEL_OPENED``; the separate
        ``BUILDING_UPGRADE`` skill carries the queue-start proof.  Nothing here may let the first
        stand in for the second.
        """
        self.assertIn("OPEN_BUILDING_UPGRADE", LiveRuntime.VERIFIED_ATOMIC)
        before = WorldState(page=Page.HOME, confidence=0.98, building=dict(LIVE_BUILDING))
        opened = WorldState(page=Page.BUILDING, confidence=0.98,
                            building={"id": "UNKNOWN", "upgrade_dialog_visible": True})
        result = LiveRuntime.VERIFIED_ATOMIC["OPEN_BUILDING_UPGRADE"](before, opened)
        self.assertTrue(result.ok)
        self.assertEqual(result.reason, "BUILDING_UPGRADE_PANEL_OPENED")
        # The sheet merely being open says nothing about a queue.
        self.assertNotIn("timer", opened.building)
        self.assertIsNone(opened.building.get("queue_building"))


class TheRealFrameTests(unittest.TestCase):
    def test_the_frame_this_came_from_is_still_here(self):
        if not FRAME.exists():
            self.skipTest(
                "the frame was pruned by retention (it lives under runtime_auto): "
                f"{FRAME}"
            )
        self.assertGreater(FRAME.stat().st_size, 0)

    def test_the_archived_frame_drives_both_halves_of_the_hop(self):
        """Not a stub: the live frame through HybridVision, then the brain, then the resolver.

        This is the measurement the change rests on, so it is asserted rather than described --
        and it fails loudly if the frame is gone, because then the evidence behind it is gone
        too.  RapidOCR missing is an environment fact, not a defect, so that skips visibly.
        """
        if not FRAME.exists():
            self.fail(
                "the evidence frame for this change has been pruned and the change would then be "
                f"resting on nothing: {FRAME}"
            )
        try:
            from winter_agent_v2.ocr import HybridVision, OCRService, RapidOCRBackend
            from winter_agent_v2.vision import SemanticWorldVision

            ocr = OCRService(RapidOCRBackend())
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"RapidOCR unavailable: {type(exc).__name__}: {exc}")

        manifest = ROOT / "dataset/candidate/template_manifest.json"
        vision = HybridVision(SemanticWorldVision(manifest), ocr)
        # Same attention the runtime set; without it the 城墙 read path is not even attempted.
        vision.focus(goal="KEEP_BUILDING_PRODUCTIVE", page_hint="HOME", reason="test")
        state = vision.observe(FRAME)

        self.assertIs(state.page, Page.HOME)
        self.assertEqual(state.building.get("name"), "城墙")
        self.assertEqual(state.building.get("level"), 8)
        self.assertEqual(state.building.get("target_level"), 9)
        tap = state.building.get("upgrade_tap_norm")
        self.assertIsNotNone(tap, "the selected building's own 升级 control has to carry a tap")
        # Measured on this frame: the 升级 label's box centre is (360, 921) in 720x1280.
        self.assertAlmostEqual(tap[0], 360 / 720, places=2)
        self.assertAlmostEqual(tap[1], 921 / 1280, places=2)

        from winter_agent_v2.brain import RuleBrain

        decision = RuleBrain(current_goal="KEEP_BUILDING_PRODUCTIVE").decide(state, v2_registry())
        self.assertEqual(decision.skill, "OPEN_BUILDING_UPGRADE",
                         "the brain must ask for the hop on the frame that draws the control")
        self.assertEqual(
            resolver()._resolve_semantic_target(decision.skill and
                                                v2_registry().get(decision.skill).action.target,
                                                state),
            (tap[0], tap[1]),
            "the executor has to arrive at the same point the brain did",
        )

    def test_the_building_id_this_frame_reports_is_still_unknown(self):
        """Recorded as a known gap, not as a passing state.

        ``id`` is UNKNOWN because ``building_identity.BUILDING_IDS`` has no entry for 城墙 and
        that table's own rule is "exact match only; every entry names its evidence".  Once the
        sheet opens, ``verify_building_upgrade`` needs ``before.building["id"] == building_id``
        and ``queue_building == building_id``, so BUILD_STARTED cannot be proven until this
        resolves.  Written down here so the next reader does not have to rediscover it, and so
        that resolving it shows up as a failure of this test rather than as silence.
        """
        from winter_agent_v2.building_identity import BUILDING_IDS, UNKNOWN

        self.assertNotIn("城墙", BUILDING_IDS)
        self.assertEqual(LIVE_BUILDING["id"], UNKNOWN)


if __name__ == "__main__":
    unittest.main()
