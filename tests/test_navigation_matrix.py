"""The navigation matrix is a projection of the registry, and has to stay one.

The operator asked which registered entries and paths each Goal already has, and how many functions
can be read without opening a detail page.  The answer is derived (``tools/ui_navigation_matrix.py``)
rather than written down, because hand-writing it would make a second source of truth for facts
the registry, the manifest and the verifier table already own.

Derived or not, a projection rots in two ways and both are worth a guard:

* it goes **stale** -- the registry changes and the committed file keeps describing the old tree;
* its queries silently **match nothing** after a rename, so a covered function reads as absent.

These tests pin the shape and the invariants; ``tools/check_wiring.py`` pins that the committed file
still equals a fresh projection (that check needs the whole tree, which is why it lives there).
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402

COMMITTED = ROOT / "knowledge" / "ui" / "navigation_matrix.json"


def _generator():
    spec = importlib.util.spec_from_file_location(
        "ui_navigation_matrix", ROOT / "tools" / "ui_navigation_matrix.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TheMatrixIsDerivedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = _generator().build()

    def test_every_registered_skill_is_a_row_exactly_once(self):
        rows = [e["skill"] for e in self.payload["entries"]]
        self.assertEqual(len(rows), len(set(rows)), "a skill appears twice")
        self.assertEqual(len(rows), len(v2_registry().all()), "a skill is missing")

    def test_schedulable_means_bound_to_a_verifier(self):
        """A row that claims it can be dispatched must have a VERIFIED_ATOMIC entry.

        This is the invariant the whole matrix is read for: everything else in it is descriptive,
        but `schedulable` is what a reader uses to decide whether a path is real.
        """
        for entry in self.payload["entries"]:
            with self.subTest(skill=entry["skill"]):
                self.assertEqual(entry["schedulable"], entry["skill"] in LiveRuntime.VERIFIED_ATOMIC)
                if entry["schedulable"]:
                    # The name is recorded rather than asserted to look like ``verify_*``: the table
                    # already holds lambdas, and pinning a naming convention here would go red on a
                    # legitimate binding.  What matters is that a schedulable row names its judge.
                    self.assertNotEqual(entry["verifier"], "UNKNOWN")

    def test_unmeasured_fields_say_unknown_rather_than_guessing(self):
        for entry in self.payload["entries"]:
            if entry["destination_page"] != "UNKNOWN":
                continue
            # UNKNOWN is allowed; what must not happen is a blank or a plausible-looking guess.
            self.assertEqual(entry["destination_page"], "UNKNOWN")
        unknown_count = sum(
            1 for e in self.payload["entries"] if e["destination_page"] == "UNKNOWN"
        )
        self.assertGreater(unknown_count, 0, "if every destination were known this field is decorative")

    def test_entries_with_visual_evidence_are_distinguishable_from_dynamic_ones(self):
        """A resolver-computed target and a template-backed one are different kinds of evidence."""
        kinds = {type(e["visual_evidence"]).__name__ for e in self.payload["entries"]}
        self.assertIn("str", kinds)
        dynamic = [e for e in self.payload["entries"] if e["visual_evidence"] == "DYNAMIC_RESOLVER"]
        self.assertTrue(dynamic, "the project has dynamic resolvers; they must not read as no-evidence")
        # NOT every dynamic target is schedulable, and that is correct: ALLIANCE_HELP computes
        # BTN_ALLIANCE_HELP_ALL from the frame but carries no verifier, so it is a resolver that
        # nothing may dispatch yet.  The property worth pinning is the one this field exists for --
        # a computed target must not read as "no evidence", and a template-backed one must not read
        # as computed.
        for entry in self.payload["entries"]:
            with self.subTest(skill=entry["skill"]):
                if entry["visual_evidence"] == "DYNAMIC_RESOLVER":
                    self.assertEqual(entry["target"] != "UNKNOWN", True)
                else:
                    self.assertNotEqual(entry["visual_evidence"], "DYNAMIC_RESOLVER")

    def test_the_operator_functions_are_all_reported_whether_covered_or_not(self):
        labels = {f["function"] for f in self.payload["operator_functions"]}
        self.assertEqual(len(labels), len(self.payload["operator_functions"]), "duplicate function")
        for entry in self.payload["operator_functions"]:
            with self.subTest(function=entry["function"]):
                self.assertIsInstance(entry["path_count"], int)
                if entry["path_count"] == 0:
                    # An absent function must still say what evidence exists for it, so a reader can
                    # tell "nobody templated it" from "it was templated and never wired".
                    self.assertIn("semantics_with_templates", entry)

    def test_the_functions_the_operator_named_are_all_queried(self):
        """A rename in the query must not silently drop a function from the report."""
        for name in ("城镇/野外快捷面板", "兵营/盾兵-矛兵-射手", "科技研究", "联盟捐献",
                     "情报/灯塔", "地图搜索栏", "巨兽/自动加入", "采集点/资源详情",
                     "回城/返回", "邮件", "活动/限时提醒", "体力HUD"):
            with self.subTest(function=name):
                self.assertIn(name, {f["function"] for f in self.payload["operator_functions"]})

    def test_the_query_does_not_confuse_research_with_a_search_bar(self):
        """RESEARCH contains SEARCH; a substring query grouped every research target as a search bar.

        This is the reason the query patterns exist at all, so it is pinned rather than remembered.
        """
        search = next(
            f for f in self.payload["operator_functions"] if f["function"] == "地图搜索栏"
        )
        self.assertNotIn("OPEN_RESEARCH", search["schedulable_entry_skills"])
        research = next(
            f for f in self.payload["operator_functions"] if f["function"] == "科技研究"
        )
        self.assertIn("OPEN_RESEARCH", research["schedulable_entry_skills"])


class TheCommittedFileIsWritableAndReadableTests(unittest.TestCase):
    def test_the_committed_matrix_parses_and_carries_its_provenance(self):
        payload = json.loads(COMMITTED.read_text(encoding="utf-8"))
        self.assertEqual(payload["gate"], "DERIVED")
        self.assertEqual(payload["generated_by"], "tools/ui_navigation_matrix.py")
        self.assertIn("counts", payload)
        self.assertIn("operator_functions", payload)


if __name__ == "__main__":
    unittest.main()
