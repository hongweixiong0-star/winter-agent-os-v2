"""Switching the training page to another barracks -- the hop that did not exist.

Why this file, 2026-09-22
-------------------------
``KEEP_TRAINING_PRODUCTIVE`` reached the training page and stopped at the first busy barracks.
The brain's own branch said ``inspect_other_training_queue``, and nothing inspected anything:

    SELECT_LANCER_CAMP / SELECT_MARKSMAN_CAMP   do not exist as skills
    TRAIN_TROOPS                                0 attempts in the project's history
    Page.TRAINING                               reached 6 times

so 盾兵营 was trained three times and 矛兵营 / 射手营 never once.  The operator's rule is
§八: "一个兵营正在训练，不得阻止其他空闲兵营执行训练".

The fix is one derived target, ``TRAINING_CAMP_NEXT``, resolved from the frame -- not three
per-camp routes.  The reason it has to be derived is measured and is the first thing these
tests pin: the client draws **all three** tab labels on every camp page, so a template, a
remembered coordinate, or even "the label is on screen" cannot say which tab to tap.  Only
"which page am I on" can, and that is the title (``camp_open_label``).

Measured on the live training page (720x1280), 2026-09-22:

    盾兵营 (134, 1260) conf 0.997     矛兵营 (361, 1260) conf 0.990     射手营 (586, 1260) conf 0.995

A second thing worth a test, because it is how the first attempt failed: the training branch in
``observe`` RETURNS, so a fold written alongside the other per-page reads never runs for a
training frame.  Every unit test that called the classifier directly still passed.
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
from winter_agent_v2.verifier import verify_training_camp_switched  # noqa: E402

#: Kept outside ``dataset/raw``: the retention policy prunes captured frames, and a test that
#: points at a prunable file is a test that will one day fail for the wrong reason.
EVIDENCE = ROOT / "dataset/truth_audit/camp_action_bar_20260922"
TRAINING_FRAME = EVIDENCE / "training_page__three_camp_tabs_and_queue__live_20260921T0953.png"

#: The measured positions, as the client drew them on the frame above.
TABS = {"盾兵营": [0.1861, 0.984], "矛兵营": [0.5007, 0.984], "射手营": [0.8146, 0.9844]}


def _runtime():
    runtime = object.__new__(LiveRuntime)
    runtime.vision = object()
    runtime.semantic_vision = object()
    runtime._control_ledger = {}
    runtime._remembered_reuse = []
    runtime._printed_remembered = set()
    runtime._printed_reads = []
    runtime._printed_printed = set()
    return runtime


def _page(open_camp: str, tabs=None, page=Page.TRAINING):
    training = {"camp_open_label": open_camp, "queue_available": False}
    if tabs is not None:
        training["camp_tab_norm"] = tabs
    return WorldState(page=page, training=training, confidence=0.99)


# ------------------------------------------------------------------ which tab to tap


class ChoosingTests(unittest.TestCase):
    def test_the_next_barracks_after_the_busy_one_is_chosen(self):
        """盾兵营 is busy and open, so the tap goes to 矛兵营 -- not to the one already open."""
        point = _runtime()._resolve_semantic_target("TRAINING_CAMP_NEXT", _page("盾兵营", TABS))
        self.assertEqual(point, (0.5007, 0.984))

    def test_the_order_wraps_so_no_camp_is_unreachable(self):
        """射手营 is the last in the client's order; the next one is 盾兵营, not 'nothing'."""
        point = _runtime()._resolve_semantic_target("TRAINING_CAMP_NEXT", _page("射手营", TABS))
        self.assertEqual(point, (0.1861, 0.984))

    def test_all_three_labels_being_present_decides_nothing_on_its_own(self):
        """The reason this is a derived target at all.

        With no reading of which page this is, the first tab is the only honest choice -- the
        test exists so nobody later "improves" this into a label-presence rule.
        """
        point = _runtime()._resolve_semantic_target("TRAINING_CAMP_NEXT", _page("", TABS))
        self.assertEqual(point, (0.1861, 0.984))

    def test_a_frame_that_is_not_the_training_page_is_refused(self):
        self.assertIsNone(
            _runtime()._resolve_semantic_target("TRAINING_CAMP_NEXT", _page("盾兵营", TABS, page=Page.HOME))
        )

    def test_a_training_page_whose_tabs_could_not_be_read_is_refused(self):
        """No tabs read means no measured point, and an invented one is what this forbids."""
        self.assertIsNone(_runtime()._resolve_semantic_target("TRAINING_CAMP_NEXT", _page("盾兵营")))

    def test_a_tab_outside_the_frame_is_skipped(self):
        """A clipped or nonsensical reading must not become a tap."""
        tabs = {"盾兵营": [0.1861, 0.984], "矛兵营": [1.4, 0.984], "射手营": [0.8146, 0.9844]}
        point = _runtime()._resolve_semantic_target("TRAINING_CAMP_NEXT", _page("盾兵营", tabs))
        self.assertEqual(point, (0.8146, 0.9844))


# ------------------------------------------------------------------ proving it switched


class VerifierTests(unittest.TestCase):
    def test_a_different_barracks_is_a_switch(self):
        result = verify_training_camp_switched(_page("盾兵营"), _page("矛兵营"))
        self.assertTrue(result.ok)
        self.assertEqual(result.evidence["to"], "矛兵营")

    def test_the_same_barracks_is_not(self):
        """This is the case a label-presence verifier would pass."""
        result = verify_training_camp_switched(_page("盾兵营"), _page("盾兵营"))
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "TRAINING_CAMP_UNCHANGED")

    def test_an_unread_page_is_absence_of_evidence_not_success(self):
        result = verify_training_camp_switched(_page(""), _page("矛兵营"))
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "TRAINING_CAMP_SWITCH_NOT_PROVEN")

    def test_the_troop_word_answers_when_the_label_is_missing(self):
        """``troop_type`` is the same fact read another way; either proves the switch."""
        before = WorldState(page=Page.TRAINING, training={"troop_type": "INFANTRY"})
        after = WorldState(page=Page.TRAINING, training={"troop_type": "LANCER"})
        self.assertTrue(verify_training_camp_switched(before, after).ok)


# ------------------------------------------------------------------ on the frame itself


class RealFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._vision = None

    def _production(self):
        if RealFrameTests._vision is None:
            sys.path.insert(0, str(ROOT / "tests"))
            from live_stack import production_vision

            RealFrameTests._vision = production_vision()
        return RealFrameTests._vision

    def test_the_three_tabs_are_read_where_the_client_drew_them(self):
        """Positions only -- all three are on every camp page, so they decide nothing."""
        self.assertTrue(TRAINING_FRAME.exists(), f"evidence frame missing: {TRAINING_FRAME}")
        state = self._production().observe(TRAINING_FRAME)
        self.assertIs(state.page, Page.TRAINING)
        tabs = (state.training or {}).get("camp_tab_norm")
        self.assertEqual(set(tabs or {}), {"盾兵营", "矛兵营", "射手营"})
        for label, point in (("盾兵营", (0.1861, 0.984)), ("矛兵营", (0.5007, 0.984))):
            self.assertAlmostEqual(tabs[label][0], point[0], places=2, msg=label)
            self.assertAlmostEqual(tabs[label][1], point[1], places=2, msg=label)

    def test_and_the_route_taps_the_next_one(self):
        """盾兵营 is training on this frame, so the switch goes to 矛兵营."""
        self.assertTrue(TRAINING_FRAME.exists(), f"evidence frame missing: {TRAINING_FRAME}")
        vision = self._production()
        state = vision.observe(TRAINING_FRAME)
        runtime = object.__new__(LiveRuntime)
        runtime.vision = vision
        runtime.semantic_vision = vision.template_vision
        runtime._control_ledger = {}
        runtime._remembered_reuse = []
        runtime._printed_remembered = set()
        runtime._printed_reads = []
        runtime._printed_printed = set()
        point = runtime._resolve_semantic_target("TRAINING_CAMP_NEXT", state, frame_path=TRAINING_FRAME)
        self.assertIsNotNone(point)
        self.assertAlmostEqual(point[0], 0.5007, places=2)


if __name__ == "__main__":
    unittest.main()
