"""The fishing entry tap must ask the frame before pressing, like every sibling branch does.

Measured 2026-10-05 over the retained ledger, goal ``OBSERVE_FISHING_STATE``:

* 51 episodes, 47 of them ``PRINTED_TAP``;
* 42 ended ``FAILED`` with ``SESSION_TAP_WORD_ABSENT:钓鱼锦标赛`` and ``executed=False``
  (``failure_type = NO_EXECUTION``, ``state_after.page = None``) -- about once every 30-60
  minutes over 10-02..10-05, never advancing the goal;
* the same 5 that succeeded carried ``FISHING_FRAME_ADVANCED``, so the branch works when the
  word really is on the frame.

``FishingDomain`` already carries the frame's ``text`` (``on_home`` is derived from it on the
line above), and every other branch of ``choose_step`` reads the frame before deciding --
``on_home``, ``popup_word``, ``result_page``.  Only the entry tap did not check.
"""

import unittest

from winter_agent_v2.session_adapters import (
    FISHING_ENTRY_WORD,
    FISHING_HOME_WORD,
    FishingDomain,
    FishingSessionAdapter,
)
from winter_agent_v2.session_engine import STEP_OBSERVE_ONLY, STEP_PRINTED_TAP

ENTRY = FISHING_ENTRY_WORD  # 钓鱼锦标赛


def domain(*, text="", on_home=False, bait=None, points=None, popup_word=""):
    return FishingDomain(
        frame=None, text=text, bait=bait, bait_cap=None, points=points,
        depth_m=None, on_home=on_home, popup_word=popup_word, result_page=False,
    )


def observe_only_adapter():
    adapter = FishingSessionAdapter()
    adapter.observe_only = True
    return adapter


class TheEntryTapAsksTheFrameFirst(unittest.TestCase):
    def test_the_entry_tap_is_dropped_when_its_word_is_not_on_the_frame(self):
        """The measured case: 42 executions planned this tap from a frame without the word."""
        adapter = observe_only_adapter()
        step = adapter.choose_step(None, None, domain(text="", on_home=False))
        self.assertIsNone(step)

    def test_the_entry_tap_is_still_planned_when_the_word_is_there(self):
        adapter = observe_only_adapter()
        step = adapter.choose_step(None, None, domain(text=f"... {ENTRY} ...", on_home=False))
        self.assertIsNotNone(step)
        self.assertEqual(step.kind, STEP_PRINTED_TAP)
        self.assertEqual(step.target, ENTRY)

    def test_a_different_word_on_the_frame_is_not_enough(self):
        """Presence of *some* text must not authorise a tap on a different word."""
        adapter = observe_only_adapter()
        self.assertIsNone(
            adapter.choose_step(None, None, domain(text="主城 出征 集结", on_home=False))
        )

    def test_on_home_still_observes_instead_of_tapping(self):
        """Unchanged: the observe-only shortcut and its reading of the bait counter."""
        adapter = observe_only_adapter()
        step = adapter.choose_step(None, None, domain(text=FISHING_HOME_WORD, on_home=True))
        self.assertIsNotNone(step)
        self.assertEqual(step.kind, STEP_OBSERVE_ONLY)

    def test_on_home_with_no_reading_still_produces_no_step(self):
        """A real session (not observe-only) declines to tap a level it cannot read."""
        adapter = FishingSessionAdapter()
        self.assertFalse(adapter.observe_only)
        self.assertIsNone(
            adapter.choose_step(None, None, domain(text=FISHING_HOME_WORD, on_home=True))
        )

    def test_a_non_observe_session_also_drops_the_absent_entry_tap(self):
        """The guard is about the frame, not about observe-only mode."""
        adapter = FishingSessionAdapter()
        self.assertFalse(adapter.observe_only)
        self.assertIsNone(adapter.choose_step(None, None, domain(text="", on_home=False)))

    def test_a_missing_text_field_is_treated_as_no_text_not_as_a_crash(self):
        adapter = observe_only_adapter()
        blank = domain()
        blank.text = None
        self.assertIsNone(adapter.choose_step(None, None, blank))


if __name__ == "__main__":
    unittest.main()
