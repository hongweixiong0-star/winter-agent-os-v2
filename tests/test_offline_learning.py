"""Offline grouping: the pile is grouped before anything is ever asked about it.

Directive 2026-10-01 sections 21-23.  The property that makes this worth doing at all is the
reduction ratio, and the property that keeps it honest is that a group never names a page -- it
says "these frames look alike", which is a measurement, not a claim about the game.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from winter_agent_v2 import offline_learning as ol


def _hasher(mapping):
    """A stand-in hasher: the tests need grouping behaviour, not real perception.

    Printed on purpose rather than mocked away -- the clustering in these tests is about the
    *distances between digests*, and a fixture that returns the same value for everything would
    prove nothing about the distances.
    """
    def hasher(path: str) -> str:
        return mapping[str(path)]
    return hasher


class ClusteringTests(unittest.TestCase):
    def test_frames_that_look_alike_become_one_group(self):
        frames = [
            ol.OfflineFrame(frame_path="a1.png", source="PAGES", episode_id="e1"),
            ol.OfflineFrame(frame_path="a2.png", source="PAGES", episode_id="e2"),
            ol.OfflineFrame(frame_path="b1.png", source="FAILURE_EPISODE", episode_id="e3",
                            failure_type="SEMANTIC_TARGET_NOT_FOUND"),
            ol.OfflineFrame(frame_path="b2.png", source="FAILURE_EPISODE", episode_id="e4",
                            failure_type="SEMANTIC_TARGET_NOT_FOUND"),
        ]
        # a1/a2 differ by 1 bit; b1/b2 differ by 1 bit; the two groups differ by 32.
        digests = {
            "a1.png": "0" * 16,
            "a2.png": "0" * 15 + "1",
            "b1.png": "f" * 16,
            "b2.png": "f" * 15 + "e",
        }
        clusters = ol.build_clusters(frames, hasher=_hasher(digests))
        self.assertEqual(len(clusters), 2)
        self.assertEqual([cluster.size for cluster in clusters], [2, 2])

    def test_a_single_frame_is_not_a_visual_state(self):
        """One occurrence is a transient, and naming it would cost a model call for nothing."""
        frames = [ol.OfflineFrame(frame_path="only.png", source="PAGES")]
        self.assertEqual(ol.build_clusters(frames, hasher=_hasher({"only.png": "0" * 16})), ())

    def test_the_representative_is_the_typical_member(self):
        """The medoid, not the first element: an odd frame must not become the one frame shown."""
        frames = [
            ol.OfflineFrame(frame_path="odd.png", source="PAGES"),
            ol.OfflineFrame(frame_path="t1.png", source="PAGES"),
            ol.OfflineFrame(frame_path="t2.png", source="PAGES"),
        ]
        digests = {
            "odd.png": "0" * 14 + "ff",
            "t1.png": "0" * 16,
            "t2.png": "0" * 15 + "1",
        }
        clusters = ol.build_clusters(frames, hasher=_hasher(digests))
        self.assertEqual(len(clusters), 1)
        self.assertIn(clusters[0].representative.frame_path, ("t1.png", "t2.png"))

    def test_grouping_is_stable_across_runs(self):
        """Re-running the analysis on the same pile must land on the same ids, or the candidate
        files fork every night."""
        frames = [
            ol.OfflineFrame(frame_path="a1.png", source="PAGES"),
            ol.OfflineFrame(frame_path="a2.png", source="PAGES"),
        ]
        digests = {"a1.png": "0" * 16, "a2.png": "0" * 15 + "1"}
        first = ol.build_clusters(frames, hasher=_hasher(digests))
        second = ol.build_clusters(list(reversed(frames)), hasher=_hasher(digests))
        self.assertEqual([c.cluster_id for c in first], [c.cluster_id for c in second])


class CandidateKnowledgeTests(unittest.TestCase):
    def test_a_group_never_names_a_page(self):
        """§39: only a model proposal or a real navigation may name something, and neither happens
        here -- so the group says how often it recurred and nothing else."""
        frames = [
            ol.OfflineFrame(frame_path="a1.png", source="PAGES", episode_id="e1"),
            ol.OfflineFrame(frame_path="a2.png", source="PAGES", episode_id="e2"),
        ]
        digests = {"a1.png": "0" * 16, "a2.png": "0" * 15 + "1"}
        cluster = ol.build_clusters(frames, hasher=_hasher(digests))[0]
        kinds = {item["kind"] for item in cluster.candidate_knowledge}
        self.assertIn("UnknownVisualStateCandidate", kinds)
        for item in cluster.candidate_knowledge:
            self.assertEqual(item["status"], "CANDIDATE")
            self.assertNotIn("page_name", item)
            self.assertNotIn("semantic", item)

    def test_shared_failures_become_a_failure_pattern_candidate(self):
        frames = [
            ol.OfflineFrame(frame_path="a1.png", source="FAILURE_EPISODE", episode_id="e1",
                            failure_type="SEMANTIC_TARGET_NOT_FOUND"),
            ol.OfflineFrame(frame_path="a2.png", source="FAILURE_EPISODE", episode_id="e2",
                            failure_type="SEMANTIC_TARGET_NOT_FOUND"),
        ]
        digests = {"a1.png": "0" * 16, "a2.png": "0" * 15 + "1"}
        cluster = ol.build_clusters(frames, hasher=_hasher(digests))[0]
        patterns = [item for item in cluster.candidate_knowledge
                    if item["kind"] == "FailurePatternCandidate"]
        self.assertEqual(len(patterns), 1)
        self.assertEqual(patterns[0]["failure_types"], ["SEMANTIC_TARGET_NOT_FOUND"])

    def test_every_candidate_carries_its_episodes(self):
        """§44: 禁止没有来源的 Knowledge."""
        frames = [
            ol.OfflineFrame(frame_path="a1.png", source="PAGES", episode_id="e1"),
            ol.OfflineFrame(frame_path="a2.png", source="PAGES", episode_id="e2"),
        ]
        digests = {"a1.png": "0" * 16, "a2.png": "0" * 15 + "1"}
        cluster = ol.build_clusters(frames, hasher=_hasher(digests))[0]
        for item in cluster.candidate_knowledge:
            self.assertTrue(item["evidence_episodes"])


class FrameSourceTests(unittest.TestCase):
    def test_a_failed_episode_is_only_included_when_a_screenshot_could_explain_it(self):
        episodes = [
            {"failure_type": "QUEUE_FULL", "after_screenshot": "a.png", "episode_id": "e1"},
            {"failure_type": "SEMANTIC_TARGET_NOT_FOUND", "after_screenshot": "b.png",
             "episode_id": "e2"},
            {"failure_type": "SEMANTIC_TARGET_NOT_FOUND", "episode_id": "e3"},
        ]
        frames = ol.frames_from_failures(episodes)
        self.assertEqual([frame.episode_id for frame in frames], ["e2"])

    def test_the_same_picture_from_two_stores_is_one_observation(self):
        frames = [
            ol.OfflineFrame(frame_path="same.png", source="PAGES"),
            ol.OfflineFrame(frame_path="same.png", source="UNKNOWN_REQUEST"),
        ]
        self.assertEqual(len(ol.dedupe(frames)), 1)


class WriteTests(unittest.TestCase):
    def test_the_summary_says_what_it_reduced(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = [
                ol.OfflineFrame(frame_path="a1.png", source="PAGES"),
                ol.OfflineFrame(frame_path="a2.png", source="PAGES"),
            ]
            clusters = ol.build_clusters(
                frames, hasher=_hasher({"a1.png": "0" * 16, "a2.png": "0" * 15 + "1"})
            )
            summary = ol.write_clusters(clusters, out_dir=Path(tmp))
            written = json.loads((Path(tmp) / "unknown_clusters.json").read_text(encoding="utf-8"))
            per_cluster = list((Path(tmp) / "candidates").glob("*.json"))
        self.assertEqual(summary["clusters"], 1)
        self.assertEqual(written["frames_in_clusters"], 2)
        self.assertEqual(len(per_cluster), 1)


if __name__ == "__main__":
    unittest.main()
