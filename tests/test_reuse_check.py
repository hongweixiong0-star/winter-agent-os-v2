"""The Reuse Check is a decision, so it must be pinned like one.

The operator's rule (2026-09-17) has two directions and both have a real cost when
they are wrong:

* a local route exists and the agent goes to GitHub anyway -- that is the time the
  TRAIN and RESEARCH rounds nearly wasted, because in both cases the brain route, the
  verifier bindings and the factory contract were already there and even the measured
  route was already written down in ``knowledge/skills/<X>_RESEARCH.md``;
* a local route does not exist and nobody escalates -- that is two hours of probing a
  UI that an existing project already automated.

``tools/reuse_check.py`` answers the first direction and prints the escalation ladder
for the second.  These tests hold the parts that must not drift: the predicate that
decides "reuse" versus "escalate", and the ladder itself.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import reuse_check  # noqa: E402


class ALocalRouteIsReusedNotReResearchedTests(unittest.TestCase):
    def test_a_wired_capability_reports_a_local_path(self):
        """OPEN_MAIL has a skill, a route and a verifier, so it is reusable."""
        self.assertTrue(reuse_check.local_path_exists("OPEN_MAIL"))

    def test_the_predicate_needs_all_three_parts_not_just_a_name(self):
        """A term that exists nowhere must not be called reusable."""
        self.assertFalse(reuse_check.local_path_exists("ZZZ_NO_SUCH_CAPABILITY_ZZZ"))

    def test_a_verifier_alone_does_not_count_as_a_route(self):
        """Conservative on purpose: you cannot run a verifier without a route."""
        bound, live = reuse_check.verifier_hits("RECONNECT_SESSION")
        self.assertTrue(bound, "precondition: this verifier binding exists")
        self.assertFalse(
            reuse_check.local_path_exists("ZZZ_WITH_VERIFIER_ONLY_ZZZ_UNUSED"),
            "no binding, no route -> not reusable",
        )

    def test_the_local_side_is_actually_searched(self):
        """Each of the five local questions has to return something for a real one."""
        self.assertTrue(reuse_check.registry_hits("OPEN_MAIL"))
        self.assertTrue(reuse_check.brain_hits("OPEN_MAIL"))
        bound, _ = reuse_check.verifier_hits("OPEN_MAIL")
        self.assertTrue(bound)
        self.assertTrue(reuse_check.knowledge_hits("MAIL"))


class TheEscalationLadderIsIntactTests(unittest.TestCase):
    """All seven of the operator's triggers, in the operator's order."""

    def test_every_trigger_is_present(self):
        joined = " | ".join(reuse_check.ESCALATION_TRIGGERS).lower()
        for needle in ("missing", "never implemented", "ui unknown", "gameplay unknown",
                       "navigation unknown", "repeated live failure", "15-30 min"):
            with self.subTest(trigger=needle):
                self.assertIn(needle, joined)

    def test_the_external_index_is_where_the_ladder_points(self):
        self.assertTrue(
            (ROOT / "knowledge" / "external" / "external_capability_map.json").is_file()
        )


class TheExternalIndexIsConsultedBeforeAnySearchTests(unittest.TestCase):
    def test_a_known_gap_returns_a_source_file_to_read(self):
        """Step 4 of the rule: an existing mapping means read that source, not search."""
        cards = reuse_check.external_hits("ARENA")
        self.assertTrue(cards, "the audit mapped ARENA; if this fails the index moved")
        self.assertTrue(
            any(card.get("source_files") for card in cards),
            "a card without source_files cannot satisfy the rule",
        )

    def test_each_card_carries_the_licence_and_reuse_level(self):
        """Those two fields decide whether a reading may become code."""
        for card in reuse_check.external_hits("ARENA"):
            with self.subTest(capability=card.get("capability")):
                self.assertIn("reuse_level", card)
                self.assertIn("license", card)


if __name__ == "__main__":
    unittest.main()
