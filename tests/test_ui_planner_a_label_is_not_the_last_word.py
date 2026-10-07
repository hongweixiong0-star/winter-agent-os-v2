"""``PLAN_TARGET_IS_NOT_A_CONTROL`` must ask whether there was anything else to name.

Measured 2026-10-06.  The learning ledger held 58 refusals of one shape -- the model named a
printed label -- and 50 of them were the *same* element on the *same* screen (``UNKNOWN::城墙``),
spread over 50 different frames.  Recomputing the element table for those exact frames (a ledger
row's ``frame_hash`` is the png's own sha256, so the frame the model was shown is findable on
disk) gave one answer for every one of them:

    element_count 18, executable_count 0, text_label_count 18, unjudged_count 0

**The frame offered nothing nameable at all.**  Naming a label was not a mistake the model could
avoid by trying harder; it was the only thing the table let it do.  And because the refusal
happens before the proposal channel below it, that screen could never be read -- which is the
permanent UNKNOWN blackhole ``PRINCIPLES §4`` forbids.  Those frames also *required* a region by
schema (``needs_box`` is true when nothing is reliable), so the box the reply already carried was
being thrown away unread.

So: the guard keeps its teeth where it was measured to matter (a screen that did offer a control,
and the model reached for the label instead) and yields to the proposal channel when there was
nothing else to name **and** the reply actually carries a region.  §2 is untouched -- the label is
still never tapped; the box stays a proposal that the live frame has to justify.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import ui_planner  # noqa: E402
from winter_agent_v2 import ui_venus_online  # noqa: E402

#: The measured screen: eight of its eighteen labels, every one typed as printed text and every
#: one explicitly non-executable -- i.e. ``executable_count`` 0.
WALL_SCREEN = [
    {"id": f"E{i}", "text": text, "kind": "TEXT_LABEL", "semantic": "", "executable": False,
     "area": "middle"}
    for i, text in enumerate(
        ["城墙", "X", "升级效果", "城墙耐久度", "15,000+5", "实力", "86,360+6", "需要条件"], start=1)
]

#: A screen that really did offer a control -- the 2026-09-25 shape that the guard exists for.
SCREEN_WITH_A_CONTROL = [
    {"id": "E1", "text": "登录好礼", "kind": "TEXT_LABEL", "semantic": "", "executable": False,
     "area": "middle"},
    {"id": "E2", "text": "领取", "kind": "COMPOSITE_CONTROL", "semantic": "AI_ADVICE[登录好礼]",
     "executable": True, "area": "middle"},
]

BOX = [0.5, 0.86, 0.2, 0.06]


def execute_naming(target: str, **extra) -> str:
    payload = {
        "goal": "KEEP_BUILDING_PRODUCTIVE",
        "decision": "EXECUTE",
        "action": {"type": "CLICK_ELEMENT", "target_element_id": target},
        "semantic_target": "升级",
        "candidate_bbox_norm": BOX,
        "expected": {"page": "BUILDING", "result": "面板打开"},
        "reason": "点击升级",
    }
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


class WhenNothingOnTheScreenCouldBeNamedTest(unittest.TestCase):
    """The measured shape: 18 labels, no control, a reply that names one of them."""

    def test_the_region_it_carried_is_read_instead_of_the_whole_reply_being_refused(self):
        parsed = ui_planner.parse_plan(execute_naming("E3"), elements=WALL_SCREEN)
        self.assertTrue(parsed.ok, parsed.error)
        self.assertEqual(parsed.plan.basis, ui_planner.BASIS_VISION_PROPOSAL)
        self.assertEqual(parsed.plan.candidate_bbox_norm, tuple(BOX))

    def test_and_the_label_it_named_is_not_the_target(self):
        # §2: the printed word is still not a control.  The reply is read as "something is here",
        # not as "tap E3".
        parsed = ui_planner.parse_plan(execute_naming("E3"), elements=WALL_SCREEN)
        self.assertEqual(parsed.plan.target_element_id, "")
        self.assertEqual(parsed.plan.target_text, "")

    def test_a_reply_that_carries_no_region_is_still_refused(self):
        # The fall-through is *to* the proposal channel, so a reply with nothing to fall through
        # to keeps the original refusal rather than becoming an unanchorable plan.
        parsed = ui_planner.parse_plan(
            execute_naming("E3", candidate_bbox_norm=None), elements=WALL_SCREEN)
        self.assertFalse(parsed.ok)
        self.assertIn("PLAN_TARGET_IS_NOT_A_CONTROL", parsed.error)

    def test_an_empty_table_is_unchanged_but_a_named_id_in_it_cannot_happen(self):
        # No elements at all: an id this frame never produced is still the hallucination refusal,
        # which is a different sentence from "that is not a control".
        parsed = ui_planner.parse_plan(execute_naming("E3"), elements=[])
        self.assertFalse(parsed.ok)
        self.assertIn("PLAN_TARGET_NOT_ON_THIS_SCREEN", parsed.error)


class WhenTheScreenDidOfferAControlTest(unittest.TestCase):
    """The guard's original measurement: the model reached for the label and skipped the control."""

    def test_a_label_is_still_refused_even_though_a_region_was_carried(self):
        parsed = ui_planner.parse_plan(execute_naming("E1"), elements=SCREEN_WITH_A_CONTROL)
        self.assertFalse(parsed.ok)
        self.assertIn("PLAN_TARGET_IS_NOT_A_CONTROL", parsed.error)

    def test_naming_the_control_itself_still_works(self):
        parsed = ui_planner.parse_plan(execute_naming("E2"), elements=SCREEN_WITH_A_CONTROL)
        self.assertTrue(parsed.ok, parsed.error)
        self.assertEqual(parsed.plan.basis, ui_planner.BASIS_ELEMENT)
        self.assertEqual(parsed.plan.target_element_id, "E2")


class TheTwoCopiesOfThePredicateAgreeTest(unittest.TestCase):
    """``_offered_a_usable_control`` and ``ElementItem.pressable`` are one rule, twice.

    ``parse_plan`` reads plain dicts and the contract module reads ``ElementItem``, so the rule
    exists in two places.  That is how the last one drifted; this pins them together.
    """

    CASES = (
        {"id": "E1", "kind": "TEXT_LABEL", "executable": False},
        {"id": "E2", "kind": "TEXT_LABEL", "executable": None},
        {"id": "E3", "kind": "TEXT_LABEL", "executable": True},
        {"id": "E4", "kind": "COMPOSITE_CONTROL", "executable": True},
        {"id": "E5", "kind": "COMPOSITE_CONTROL", "executable": False},
        {"id": "E6", "kind": "", "executable": None},
        {"id": "E7", "kind": "", "executable": False},
    )

    def test_every_case_answers_the_same_way_in_both_modules(self):
        for case in self.CASES:
            with self.subTest(element=case):
                item = ui_venus_online.ElementItem(
                    id=str(case["id"]), kind=str(case["kind"]), executable=case["executable"])
                self.assertEqual(
                    ui_planner._offered_a_usable_control([case]), item.pressable,
                    f"{case} disagrees between parse_plan and the contract")

    def test_the_measured_screen_offers_nothing(self):
        self.assertFalse(ui_planner._offered_a_usable_control(WALL_SCREEN))

    def test_the_2026_09_25_screen_offered_something(self):
        self.assertTrue(ui_planner._offered_a_usable_control(SCREEN_WITH_A_CONTROL))


if __name__ == "__main__":
    unittest.main()
