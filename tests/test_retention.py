from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from winter_agent_v2.retention import (
    _is_protected,
    prune_runtime_screenshots,
    referenced_evidence,
    select_prunable_screenshots,
)


class RetentionTests(unittest.TestCase):
    def test_count_limit_keeps_newest_runtime_images(self):
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paths = []
            for index in range(4):
                path = root / f"{index}.png"
                path.write_bytes(b"image")
                stamp = (now - timedelta(minutes=4 - index)).timestamp()
                os.utime(path, (stamp, stamp))
                paths.append(path)
            selected = select_prunable_screenshots(paths, max_count=2, ttl_days=30, now=now)
            self.assertEqual(selected, paths[:2])

    def test_prune_is_scoped_and_ignores_non_images(self):
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder)
            root = parent / "runtime"
            root.mkdir()
            old_image = root / "old.png"
            old_image.write_bytes(b"image")
            keep_log = root / "latest.log"
            keep_log.write_text("keep", encoding="utf-8")
            outside = parent / "outside.png"
            outside.write_bytes(b"outside")
            stamp = (now - timedelta(days=20)).timestamp()
            os.utime(old_image, (stamp, stamp))
            os.utime(outside, (stamp, stamp))
            removed = prune_runtime_screenshots(root, max_count=10, ttl_days=14, now=now)
            self.assertEqual(removed, [old_image.resolve()])
            self.assertFalse(old_image.exists())
            self.assertTrue(keep_log.exists())
            self.assertTrue(outside.exists())


class ProtectedEvidenceTests(unittest.TestCase):
    """The long-term retention areas must never be prunable.

    ``dataset/verified`` and ``dataset/production`` were missing from the
    protection list entirely, so the two areas that hold the only frames able to
    prove a live run happened participated in the normal rotation.
    """

    def test_long_term_areas_are_protected(self):
        for name in ("verified", "production", "normalized", "truth_audit", "candidate", "evidence"):
            path = Path("E:/repo/dataset") / name / "frame.png"
            self.assertTrue(_is_protected(path), f"dataset/{name} must be protected")

    def test_rotating_runtime_captures_are_still_prunable(self):
        path = Path("E:/repo/dataset/raw/control_panel/runtime_auto/20260101_000000") / "frame.png"
        self.assertFalse(_is_protected(path))


class ReferencedEvidenceTests(unittest.TestCase):
    """Section 13: a frame an episode points at must survive retention."""

    def test_referenced_stream_paths_are_protected_from_pruning(self):
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            (repo / "learning").mkdir(parents=True)
            captures = repo / "dataset/raw/control_panel/runtime_auto/run1"
            captures.mkdir(parents=True)
            referenced = captures / "run1_step_001_before.png"
            unreferenced = captures / "run1_step_002_before.png"
            for path in (referenced, unreferenced):
                path.write_bytes(b"image")
                stamp = (now - timedelta(days=90)).timestamp()
                os.utime(path, (stamp, stamp))
            (repo / "learning/episodes.jsonl").write_text(
                json.dumps({"skill": "X", "before_screenshot": str(referenced)}) + "\n",
                encoding="utf-8",
            )

            self.assertEqual(referenced_evidence(repo), {referenced})
            candidates = select_prunable_screenshots(
                [referenced, unreferenced], max_count=0, ttl_days=0, now=now,
                referenced=referenced_evidence(repo),
            )
            self.assertEqual(candidates, [unreferenced])

    def test_malformed_stream_never_breaks_pruning(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            (repo / "learning").mkdir(parents=True)
            (repo / "learning/episodes.jsonl").write_text(
                "not json\n{\"before_screenshot\": 42}\n[]\n", encoding="utf-8"
            )
            self.assertEqual(referenced_evidence(repo), set())


if __name__ == "__main__":
    unittest.main()
