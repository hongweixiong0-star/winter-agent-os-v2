"""Stage A of the training route is tapped at the ring, not at the template's centre.

The route reaches the infantry camp in two stages: A is the camp highlighted with no radial
menu drawn, B is the menu.  A is where it has been stuck -- 45 of KEEP_TRAINING_PRODUCTIVE's
127 steps sit in WAIT_FOR_CAMP_MENU and the training page is reached four times -- and the
recorded reason for not tapping was a tutorial finger over the camp, from ONE 2026-09-17
attempt whose after frame shows the world map.

That reason is falsified, and the frames here are the falsification:

  01_  the live stage A frame.  Ring, finger, no menu.
  02_  the same frame with the template's own centre marked: it lands on bare ground between
       the buildings, 103 px below the ring's centre and 88 px below the ring's lower edge.
  03_  a second, independent session in the same state.
  04_  the 2026-09-17 after frame -- the world map, which is what a tap on that bare ground
       produces.  The MAP trip was a coordinate error, not an occlusion.
  05_  the finger present AND the radial menu open, which is what makes 01_'s finger a guide
       rather than a cover.

What is asserted below is the measured offset and the bounded decision sequence; what is NOT
asserted anywhere is that tapping the ring opens the menu, because that has not happened on
a device yet.  The hop is CANDIDATE.
"""

from __future__ import annotations

import re
import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.brain import RuleBrain  # noqa: E402
from winter_agent_v2.camp_ring import ring_centre_norm  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402
from winter_agent_v2.verifier import verify_infantry_camp_selected  # noqa: E402
from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"
EVIDENCE = ROOT / "dataset" / "truth_audit" / "training_stage_a_20260921" / "key"
STAGE_A = EVIDENCE / "01_stage_a_ring_and_finger_20260921T163802.png"
STAGE_A_SECOND = EVIDENCE / "03_stage_a_second_session_20260920T160508.png"
MENU_OPEN = EVIDENCE / "05_finger_present_and_menu_open_20260920T013343.png"
TAPPED_MAP = EVIDENCE / "04_the_20260917_tap_landed_on_the_map.png"

TEMPLATE = "TARGET_INFANTRY_CAMP_HIGHLIGHTED"
#: The pair a human verified by hand, named for what a tap did on each.  The route's old
#: reading -- "the highlight signal cannot tell these two apart" -- is true of the template
#: distance (0.0 against 8.0, i.e. the failing frame sits ON the gate) and false of the ring:
#: the frame that opens the menu carries a 205x112 ring and the one that jumps to the map
#: carries a 7x15 fleck.
AMBIGUITY = ROOT / "dataset" / "truth_audit" / "training_camp_highlight_ambiguity_20260917"
CLICK_OPENS_MENU = AMBIGUITY / "camp_with_gold_ring__click_opens_menu__20260908.png"
CLICK_JUMPS_TO_MAP = AMBIGUITY / "camp_with_officer_badge__click_jumps_to_map__20260917.png"
#: Where the ring is drawn on the archived frames, in pixels of a 720x1280 frame.  Not a
#: target -- a bound, wide enough to hold all 46 measured frames (x 305-319, y 577-597).
RING_BOX = (250, 520, 380, 660)


def _vision() -> SemanticWorldVision:
    return SemanticWorldVision(MANIFEST)


class TheRingIsWhereTheFrameSaysItIsTests(unittest.TestCase):
    def test_the_ring_is_measured_inside_the_template_window(self):
        vision = _vision()
        for frame in (STAGE_A, STAGE_A_SECOND):
            with self.subTest(frame=frame.name):
                match = vision.semantic.find(frame, TEMPLATE)
                self.assertIsNotNone(match, "this frame is stage A; the template must match")
                point = ring_centre_norm(frame, match.roi)
                self.assertIsNotNone(point, "the ring is drawn on this frame and must be read")
                x, y = point[0] * 720, point[1] * 1280
                left, top, right, bottom = RING_BOX
                self.assertTrue(left <= x <= right and top <= y <= bottom,
                                f"ring centre ({x:.0f},{y:.0f}) is outside the measured box {RING_BOX}")

    def test_the_templates_own_centre_is_not_the_ring(self):
        """The whole point: the template resolves to a point on bare ground."""
        vision = _vision()
        match = vision.semantic.find(STAGE_A, TEMPLATE)
        self.assertIsNotNone(match)
        ring = ring_centre_norm(STAGE_A, match.roi)
        self.assertIsNotNone(ring)
        tx, ty = match.center_norm[0] * 720, match.center_norm[1] * 1280
        rx, ry = ring[0] * 720, ring[1] * 1280
        self.assertGreater(((tx - rx) ** 2 + (ty - ry) ** 2) ** 0.5, 80,
                           "if these two agreed, there would be nothing to fix")
        self.assertGreater(ty - ry, 60, "the template's centre sits below the ring, not beside it")

    def test_the_pair_a_human_verified_is_separated_by_the_ring(self):
        """The discriminator the project had been missing since 2026-09-17.

        Two frames carry the same semantic and were tapped by hand to different ends.  Their
        template distances are 0.0 and 8.0 -- the second sits exactly on the production gate,
        which is why the recorded conclusion was that the signal cannot tell them apart.  It
        was measuring the wrong quantity: what the failing frame carries is a 7x15 fleck of
        gold (an officer badge's edge), and the surviving one a 205x112 ring.
        """
        vision = _vision()
        opens = vision.semantic.find(CLICK_OPENS_MENU, TEMPLATE)
        self.assertIsNotNone(opens)
        point = ring_centre_norm(CLICK_OPENS_MENU, opens.roi)
        self.assertIsNotNone(point, "this is the frame whose tap opened the menu; it has a ring")

        jumps = vision.semantic.find(CLICK_JUMPS_TO_MAP, TEMPLATE)
        self.assertIsNotNone(jumps, "the failing frame still matches the template -- that is the trap")
        self.assertIsNone(
            ring_centre_norm(CLICK_JUMPS_TO_MAP, jumps.roi),
            "this frame's tap jumped to the MAP, so it must carry no selection ring and the "
            "route must wait rather than tap",
        )

    def test_a_window_with_no_ring_answers_none_rather_than_guessing(self):
        """No ring read means no point.  A fallback to the template's centre is the bug.

        Note what this detector is NOT: it is not a whole-frame gold finder, and it is never
        asked to be one -- it is only ever called with the ``roi_norm`` of a matched
        ``TARGET_INFANTRY_CAMP_HIGHLIGHTED``, so the premise "this frame is stage A" is the
        template's job.  An unwindowed version of this mask did exactly that and came back
        with the right-hand activity rail, which is why the window is the caller's.
        """
        for roi in (None, {}, "not a dict",
                    {"x_norm": 0.0, "y_norm": 0.0, "w_norm": 0.0, "h_norm": 0.1},
                    {"x_norm": 0.0, "y_norm": 0.0, "h_norm": 0.1},
                    {"x_norm": 0.02, "y_norm": 0.45, "w_norm": 0.06, "h_norm": 0.06}):
            with self.subTest(roi=roi):
                self.assertIsNone(ring_centre_norm(STAGE_A, roi))


class TheReportedStateCarriesTheMeasuredPointTests(unittest.TestCase):
    def test_the_vision_layer_publishes_it(self):
        state = _vision().observe(STAGE_A)
        self.assertEqual(state.page, Page.HOME)
        self.assertEqual(state.training.get("navigation"), "INFANTRY_CAMP_HIGHLIGHTED")
        point = state.training.get("camp_tap_norm")
        self.assertIsInstance(point, (tuple, list), "the tap point must travel with the state")
        x, y = point[0] * 720, point[1] * 1280
        left, top, right, bottom = RING_BOX
        self.assertTrue(left <= x <= right and top <= y <= bottom)

    def test_the_menu_state_is_not_reported_as_stage_a(self):
        """05_ is stage B, and nothing about it may look like the highlighted-only state."""
        state = _vision().observe(MENU_OPEN)
        self.assertTrue(state.training.get("menu_open"),
                        "the menu is drawn on this frame; that is what makes the finger a guide")
        self.assertNotEqual(state.training.get("navigation"), "INFANTRY_CAMP_HIGHLIGHTED")


class TheDecisionIsBoundedTests(unittest.TestCase):
    def _stage_a_state(self) -> WorldState:
        return WorldState(page=Page.HOME,
                          training={"navigation": "INFANTRY_CAMP_HIGHLIGHTED",
                                    "queue_available": True,
                                    "camp_tap_norm": (0.435, 0.4565)},
                          confidence=0.99)

    def test_it_waits_because_the_tap_was_tried_live_and_failed(self):
        """The experiment ran, and it did not work: stage A waits again.

        Live 2026-09-20T18:43:51Z, one round after the tap was wired: SELECT_INFANTRY_CAMP
        carried training["camp_tap_norm"] = (0.441, 0.4551), i.e. (317, 583) -- inside the ring
        -- action_backend was ADB, so the tap really went out, and the outcome was FAILURE /
        INFANTRY_CAMP_MENU_NOT_PROVEN with after.training EMPTY: neither the menu nor the
        highlight, just the ring gone, which is what the client does when a tap lands on nothing.

        Four live taps now, four failures -- three at the template's own centre (346, 682, on
        bare ground; one of them ending on the world map) and one inside the ring.  Aiming is
        not the problem, so the tap is withdrawn and no further one will be added until the
        state itself is identified.  What the frame still provides -- the ring, and the measured
        point on it -- is pinned by the tests above, because that measurement is sound and is the
        input any future attempt needs.

        The state WAS identified on 2026-09-21, from the frames themselves (issue #82): the
        ellipse is on the ground, five lit action blocks sit inside it, the tutorial hand rests
        on the 2-badged one, and three consecutive live frames show nothing progressing toward
        a menu.  It is a guided tutorial step, so the blocker names the precondition rather than
        a menu that is merely late.

        Since 2026-09-23 the wait in front of the blocker is gone as well: the ring is drawn by the
        client on its own schedule (17:50:32 no ring, 17:51:00 the same city view with it, the
        盾兵 row's state unchanged in between), so there was nothing to wait on.  The blocker is
        reached on the first sighting, with the same reason and the same non-fatal hand-over.
        """
        brain = RuleBrain(current_goal="TRAIN")
        state = self._stage_a_state()
        last = brain.decide(state, v2_registry())
        self.assertEqual(last.skill, "SAFE_STOP")
        self.assertEqual(last.reason, "camp_entry_is_a_guided_step_not_a_selection")
        # And the reason must hand the cycle over rather than ending it: the training
        # entry point being unusable says nothing about the other goals.
        from winter_agent_v2.runtime_snapshot import is_fatal_stop
        self.assertFalse(is_fatal_stop(last.reason))

    def test_nothing_taps_the_highlighted_camp(self):
        """Nothing may send input from this state while its meaning is unknown."""
        source = (ROOT / "winter_agent_v2" / "brain.py").read_text(encoding="utf-8")
        self.assertNotIn('return Decision("SELECT_INFANTRY_CAMP"', source,
                         "the tap was tried live and failed; it must not come back without a "
                         "new measurement (issue #82)")

    def test_without_a_measured_point_it_never_taps(self):
        """A ring that could not be read is not an invitation to tap somewhere else."""
        brain = RuleBrain(current_goal="TRAIN")
        state = WorldState(page=Page.HOME,
                           training={"navigation": "INFANTRY_CAMP_HIGHLIGHTED",
                                     "queue_available": True},
                           confidence=0.99)
        decision = brain.decide(state, v2_registry())
        self.assertEqual(decision.skill, "SAFE_STOP")
        self.assertNotEqual(decision.skill, "SELECT_INFANTRY_CAMP")

    def test_the_hop_is_registered_and_bound_to_the_menu_verifier(self):
        registry = v2_registry()
        skill = registry.get("SELECT_INFANTRY_CAMP")
        self.assertIsNotNone(skill, "a skill nothing registers is a skill nothing schedules")
        self.assertEqual(skill.action.target, "TRAINING_CAMP_IN_RING")
        self.assertIs(LiveRuntime.VERIFIED_ATOMIC["SELECT_INFANTRY_CAMP"],
                      verify_infantry_camp_selected)

    def test_the_executor_refuses_a_point_read_on_another_page(self):
        """The fragment belongs to the HOME frame it came from; a stale one must not be used."""
        source = (ROOT / "winter_agent_v2" / "runtime.py").read_text(encoding="utf-8")
        # The resolver takes the frame as an argument since 2026-09-21 (it was a closure
        # inside ``run``), so the guard reads ``frame.page`` rather than ``before.page``.
        # What is asserted is unchanged: the page check sits inside this branch, ahead of
        # the tap point being returned.
        pattern = (r'if semantic == "TRAINING_CAMP_IN_RING":.*?'
                   r'if frame\.page is not Page\.HOME:\s+return None')
        # Compiled, not asserted with a flags argument: assertRegex's third parameter is the
        # failure message, so passing re.DOTALL there silently does nothing and the pattern
        # then has to match inside a single line.
        self.assertRegex(source, re.compile(pattern, re.DOTALL))
        self.assertEqual(len(re.findall(r'if semantic == "TRAINING_CAMP_IN_RING":', source)), 1)

    def test_the_resolver_is_reachable_without_a_run(self):
        """The point of lifting the resolver out: a test can call what the executor taps.

        Before this the page guard could only be asserted by grepping the source, which
        proves the text exists but not that it answers ``None``.  Now the answer itself is
        checked, on a frame that is on the wrong page and one that is right.
        """
        runtime = LiveRuntime(
            device=object(), vision=object(), semantic_vision=object(),
            capture_dir=Path("."), brain=RuleBrain(current_goal="TRAIN"),
            sleeper=lambda _s: None,
        )
        # Right page, a measured ring: the point comes back.
        on_home = WorldState(page=Page.HOME,
                             training={"navigation": "INFANTRY_CAMP_HIGHLIGHTED",
                                       "camp_tap_norm": (0.441, 0.4551)},
                             confidence=0.99)
        self.assertEqual(runtime._resolve_semantic_target("TRAINING_CAMP_IN_RING", on_home),
                         (0.441, 0.4551))
        # Same fragment, different page: refused, so it cannot be reused.
        on_map = replace(on_home, page=Page.MAP)
        self.assertIsNone(runtime._resolve_semantic_target("TRAINING_CAMP_IN_RING", on_map))


if __name__ == "__main__":
    unittest.main()
