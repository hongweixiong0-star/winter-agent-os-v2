"""The largest failure in the ledger must say which half of it failed.

``SUBMIT_GIANT_BEAST_SEARCH`` was verified by a one-line lambda that (a) passed no
evidence at all and (b) chose its reason from a **looser** test than its own verdict.
Measured 2026-10-14 over the whole production stream: all 164 episodes carrying
``GIANT_BEAST_SEARCH_NOT_PROVEN`` had an empty ``verifier_evidence``, and a step that
FAILED because the giant-beast tab was never selected could still be filed under the
success-sounding ``GIANT_BEAST_SEARCH_RESULT``.

Both halves are pinned here.  The second is the one that needs the test: nothing
crashes when a failure is mislabelled, the counter just reads wrong -- and this is the
project's largest failure cluster, so a wrong count is expensive.
"""

from __future__ import annotations

import unittest

from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.verifier import verify_giant_beast_search


def _states(*, before_tab: str, result: dict) -> tuple[WorldState, WorldState]:
    before = WorldState(page=Page.MAP, resource_selected_tab=before_tab)
    after = WorldState(page=Page.MAP, beast_search_result=result)
    return before, after


class GiantBeastSearchNamesItsOwnFailureTest(unittest.TestCase):
    def test_a_selected_tab_and_a_card_are_a_result(self):
        result = verify_giant_beast_search(
            *_states(before_tab="GIANT_BEAST", result={"title_text": "冰原巨兽"})
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.reason, "GIANT_BEAST_SEARCH_RESULT")

    def test_a_missed_tab_is_not_filed_as_a_result(self):
        """The regression pin.

        The card is present, so the old expression answered ``True`` and the step was
        filed under ``GIANT_BEAST_SEARCH_RESULT`` -- a step whose own verdict was
        FAILURE, counted under a name that reads like success.
        """
        result = verify_giant_beast_search(
            *_states(before_tab="NORMAL_BEAST", result={"title_text": "雪豹"})
        )
        self.assertFalse(result.ok, "the verdict still needs the giant-beast tab")
        self.assertEqual(result.reason, "GIANT_BEAST_TAB_NOT_SELECTED")
        self.assertNotEqual(result.reason, "GIANT_BEAST_SEARCH_RESULT")

    def test_a_tab_with_no_card_keeps_the_original_name(self):
        """Only the mislabelled half moves out; the result counter keeps its meaning."""
        result = verify_giant_beast_search(
            *_states(before_tab="GIANT_BEAST", result={})
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "GIANT_BEAST_SEARCH_NOT_PROVEN")

    def test_every_verdict_carries_evidence(self):
        """Empty evidence is what made 164 failures unattributable."""
        for before_tab, result in (
            ("GIANT_BEAST", {"title_text": "x"}),
            ("NORMAL_BEAST", {"title_text": "x"}),
            ("GIANT_BEAST", {}),
        ):
            with self.subTest(before_tab=before_tab, result=result):
                out = verify_giant_beast_search(*_states(before_tab=before_tab, result=result))
                self.assertTrue(out.evidence, "a verdict must state what it looked at")
                self.assertEqual(out.evidence["before_tab"], before_tab)
                self.assertIn("result_keys", out.evidence)

    def test_a_rally_card_also_counts_as_a_result(self):
        """``has_rally`` is the other half of the card test -- a 5-level beast offers 集结."""
        result = verify_giant_beast_search(
            *_states(before_tab="GIANT_BEAST", result={"has_rally": True})
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.reason, "GIANT_BEAST_SEARCH_RESULT")


if __name__ == "__main__":
    unittest.main()
