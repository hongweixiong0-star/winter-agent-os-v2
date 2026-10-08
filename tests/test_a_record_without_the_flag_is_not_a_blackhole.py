"""A record that recorded the kind but not the flag must not become unwinnable.

``elements_from_request`` read two fields that always travel together with **opposite** defaults:
an absent ``element_kind`` left the element untyped (and therefore permitted), while an absent
``element_executable`` became ``bool(None)`` -- "not a control" -- so every element of the screen
was refused as a click target.

Measured 2026-10-08 over ``learning/unknown_requests/sweepcase_*.json``: all six records carry
``element_kind`` on every box and ``element_executable`` on **none** (0 of 5/5/5/7/40/32).  Two of
them hold a real registered composite control, and the model named it:

    case 5  PLAN_TARGET_IS_NOT_A_CONTROL: E1  is COMPOSITE_CONTROL
            E1 = 登录好礼, semantic CONTROL[登录好礼] -- a control the project has a verified
            crop for, refused with its own kind quoted back at it

So the guard's own stated goal -- "a screen must never be readable-only, the permanent UNKNOWN
blackhole PRINCIPLES §4 forbids" -- was being defeated by a default rather than by a decision.

Executability is derived from the kind **only when the flag is absent**, and the kind set is the
project's own ``EXECUTABLE_ELEMENT_KINDS``.  Everything else is unchanged, and the tests below pin
both halves: the derivation, and the guard that must keep its teeth.
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
from winter_agent_v2.ui_collection import EXECUTABLE_ELEMENT_KINDS  # noqa: E402


class _Request:
    """The two attributes ``elements_from_request`` reads."""

    def __init__(self, texts, boxes):
        self.ocr_texts = texts
        self.ocr_boxes = boxes


def _box(text, kind=None, executable="ABSENT", semantic=""):
    box = {"text": text}
    if kind is not None:
        box["element_kind"] = kind
        box["element_semantic"] = semantic
    if executable != "ABSENT":
        box["element_executable"] = executable
    return box


#: The live reply from case 5, verbatim from the benchmark's own row.
LOGIN_GIFT_REPLY = json.dumps({
    "decision": "EXECUTE",
    "action": {"type": "CLICK_ELEMENT", "target_element_id": "E1"},
    "expected": {"page": "LOGIN_GIFT", "result": "Login gift popup opens"},
    "reason": "Goal is to keep building productive; claiming login gift is a free resource boost.",
})


class TheFlagIsDerivedFromTheKindTests(unittest.TestCase):

    def _elements(self, *boxes):
        return ui_planner.elements_from_request(
            _Request([b["text"] for b in boxes], list(boxes)))

    def test_a_composite_control_with_no_flag_is_offered_as_a_control(self):
        elements = self._elements(
            _box("登录好礼", "COMPOSITE_CONTROL", semantic="CONTROL[登录好礼]"))
        self.assertEqual(elements[0]["kind"], "COMPOSITE_CONTROL")
        self.assertIs(elements[0]["executable"], True)

    def test_an_interactive_control_with_no_flag_is_offered_as_a_control(self):
        elements = self._elements(_box("登录好礼", "INTERACTIVE_CONTROL"))
        self.assertIs(elements[0]["executable"], True)

    def test_a_text_label_with_no_flag_is_still_not_a_control(self):
        elements = self._elements(_box("采集中", "TEXT_LABEL"))
        self.assertIs(elements[0]["executable"], False,
                      "the derivation must follow the kind, not the absence of a flag")

    def test_an_explicit_flag_is_honoured_whatever_it_says(self):
        """The guard is not relaxed: a recorded False on a control stays False."""
        elements = self._elements(_box("登录好礼", "COMPOSITE_CONTROL", executable=False))
        self.assertIs(elements[0]["executable"], False)

    def test_an_untyped_box_stays_untyped(self):
        """No kind recorded is not the same statement as 'it is a control'."""
        elements = self._elements(_box("任意文字"))
        self.assertNotIn("kind", elements[0])
        self.assertNotIn("executable", elements[0])

    def test_the_derivable_set_is_the_projects_own(self):
        self.assertEqual(EXECUTABLE_ELEMENT_KINDS, frozenset({"COMPOSITE_CONTROL",
                                                              "INTERACTIVE_CONTROL"}))


class TheReplyThatWasRefusedTests(unittest.TestCase):
    """End to end through the parser, because that is where the refusal was produced."""

    def _parse(self, boxes):
        elements = ui_planner.elements_from_request(
            _Request([b["text"] for b in boxes], list(boxes)))
        return ui_planner.parse_plan(
            LOGIN_GIFT_REPLY, elements=elements, actions=ui_planner.OFFERED_ACTIONS)

    def test_the_login_gift_control_is_now_nameable(self):
        parsed = self._parse([
            _box("登录好礼", "COMPOSITE_CONTROL", semantic="CONTROL[登录好礼]"),
            _box("10-0817:17:18", "TEXT_LABEL"),
        ])
        self.assertTrue(parsed.ok, parsed.error)
        self.assertEqual(parsed.plan.target_element_id, "E1")

    def test_the_guard_keeps_its_teeth_when_a_control_was_really_offered(self):
        """A screen that does offer a control still refuses a reach for the label.

        This is the half that must not move.  With the flag back on and set to False -- i.e. the
        record really does say this control is not clickable -- the same reply is refused, and the
        refusal quotes the kind it refused.
        """
        parsed = self._parse([
            _box("登录好礼", "COMPOSITE_CONTROL", executable=False,
                 semantic="CONTROL[登录好礼]"),
            _box("10-0817:17:18", "TEXT_LABEL"),
        ])
        self.assertFalse(parsed.ok)
        self.assertIn("PLAN_TARGET_IS_NOT_A_CONTROL", parsed.error)

    def test_a_label_named_while_a_control_exists_is_still_refused(self):
        reply = json.dumps({
            "decision": "EXECUTE",
            "action": {"type": "CLICK_ELEMENT", "target_element_id": "E2"},
            "reason": "naming the printed label instead of the control",
        })
        elements = ui_planner.elements_from_request(_Request(
            ["登录好礼", "10-0817:17:18"],
            [_box("登录好礼", "COMPOSITE_CONTROL", semantic="CONTROL[登录好礼]"),
             _box("10-0817:17:18", "TEXT_LABEL")],
        ))
        parsed = ui_planner.parse_plan(reply, elements=elements,
                                       actions=ui_planner.OFFERED_ACTIONS)
        self.assertFalse(parsed.ok)
        self.assertIn("E2 is TEXT_LABEL", parsed.error)


if __name__ == "__main__":
    unittest.main()
