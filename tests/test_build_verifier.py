from __future__ import annotations

import unittest
from pathlib import Path

from winter_agent_v2.verifier import verify_building_upgrade
from winter_agent_v2.vision import ReplayVision, SemanticWorldVision
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.skills import v2_registry


ROOT = Path(__file__).resolve().parents[1]


class BuildVerifierTests(unittest.TestCase):
    def test_live_warehouse_upgrade_started(self) -> None:
        vision = ReplayVision(ROOT / "tests/replay/labels.json")
        before = vision.observe(ROOT / "dataset/raw/live_build_warehouse_upgrade_dialog.png")
        after = vision.observe(ROOT / "dataset/raw/live_build_warehouse_started.png")
        result = verify_building_upgrade(before, after, "STOREHOUSE")
        self.assertTrue(result.ok, result)

    def test_brain_selects_verified_build_skill(self) -> None:
        """The skill the brain picks has to be one the loop can credit -- and crediting needs an id.

        Observed through ``SemanticWorldVision`` alone, which is the template layer: it sets
        ``page=BUILDING, upgradeable=True`` and **no identity**, because the identity is supplied by
        ``HybridVision``'s OCR enrichment (``vision.py``'s own comment says so, and names this very
        frame: its dialog shows only the *prerequisite* 大熔炉 等级 27, so no current level and no
        name is on it at all).

        That matters here because ``verify_building_upgrade`` needs ``before.building["id"] ==
        building_id``: a spend on an identity-less frame could never be credited, whatever the
        template saw.  Measured 2026-10-05: every one of the 30 recorded ``Page.BUILDING`` +
        ``upgradeable`` states reads ``id=UNKNOWN, name=None``, and ``BUILDING_UPGRADE`` has 0 rows
        in the ledger.  So the brain now refuses that combination and says why -- and the skill it
        picks when the identity *is* known is still a verifier-bound one, which is this test's point.
        """
        vision = SemanticWorldVision(ROOT / "dataset/candidate/templates_manifest.json")
        observed = vision.observe(ROOT / "dataset/raw/live_build_warehouse_upgrade_dialog.png")

        # The frame as the template layer reads it: the sheet, and nothing that names the building.
        from dataclasses import replace as _replace

        nameless = _replace(observed, building=dict(observed.building))
        nameless.building.pop("id", None)
        nameless.building.pop("name", None)
        decision = RuleBrain().decide(nameless, v2_registry())
        self.assertEqual(decision.skill, "SAFE_STOP")
        self.assertEqual(decision.reason, "building_upgrade_needs_a_known_identity")

        # The same frame with the identity the OCR enrichment adds -- a name is enough.
        named = _replace(observed, building={**observed.building, "name": "仓库"})
        decision = RuleBrain().decide(named, v2_registry())
        self.assertEqual(decision.skill, "BUILDING_UPGRADE")
        from winter_agent_v2.runtime import LiveRuntime

        self.assertIn(decision.skill, LiveRuntime.VERIFIED_ATOMIC)


if __name__ == "__main__":
    unittest.main()
