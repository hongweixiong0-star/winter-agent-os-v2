import unittest

from winter_agent_v2.capability_miner import ExternalCapability, ExternalCapabilityMiner
from winter_agent_v2.external_knowledge import (
    EvidenceFusion,
    EvidenceSource,
    ExternalKnowledgeProvider,
    KnowledgeCandidate,
    ResearchTrigger,
)
from winter_agent_v2.skills import p0_registry


def candidate(value, source_type, source="source", confidence=0.8):
    return KnowledgeCandidate("deploy_button_text", value, source_type, source, confidence, "2026-09-02T00:00:00Z")


class ExternalKnowledgeTests(unittest.TestCase):
    def test_live_client_wins_over_external_prior(self) -> None:
        result = EvidenceFusion().fuse([
            candidate("派遣", EvidenceSource.OPEN_SOURCE_PROJECT),
            candidate("出征", EvidenceSource.LIVE_CLIENT, "live", 0.99),
        ])
        self.assertEqual(result.status, "VERIFIED")
        self.assertEqual(result.value, "出征")

    def test_external_conflict_is_not_silently_resolved(self) -> None:
        result = EvidenceFusion().fuse([
            candidate("派遣", EvidenceSource.PLAYER_GUIDE, "a"),
            candidate("出征", EvidenceSource.OPEN_SOURCE_PROJECT, "b"),
        ])
        self.assertEqual(result.status, "CONFLICT")

    def test_provider_records_jit_trigger(self) -> None:
        provider = ExternalKnowledgeProvider()
        provider.trigger(ResearchTrigger.NAVIGATION_FAILED, "START_GATHER did not open deployment")
        self.assertEqual(provider.events[0][0], ResearchTrigger.NAVIGATION_FAILED)

    def test_capability_miner_creates_candidate_gap(self) -> None:
        capability = ExternalCapability("ALLIANCE_HELP", "external", (), (), (), (), ())
        gaps = ExternalCapabilityMiner().find_gaps([capability], p0_registry())
        self.assertEqual(gaps[0].status, "CANDIDATE")


if __name__ == "__main__":
    unittest.main()
