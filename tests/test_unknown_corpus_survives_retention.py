"""The UNKNOWN corpus must survive retention, or the benchmark it feeds runs zero cases.

Measured 2026-10-08: all 8 ``learning/unknown_requests/*.json`` records had lost the frame they
were filed with, so ``tools/benchmark_gui_unknown.py`` -- which scores the local model on "the real
UNKNOWN screens this system actually failed to advance" -- ran 0 cases.  The records key their
frame as ``frame_path``, a name neither ``REFERENCE_KEYS`` nor ``CORPUS_FRAME_KEYS`` covers, so
nothing protected them and the 3-day capture TTL took every one.

What is pinned here is the SHAPE of the fix: the three keys, the tolerance that keeps the pruning
pass from ever raising, and that the third stream is actually wired into the union.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import retention  # noqa: E402


class UnknownRequestFramesAreEvidenceTest(unittest.TestCase):
    def _dir(self, records: dict[str, object]) -> Path:
        tmp = Path(tempfile.mkdtemp())
        for name, payload in records.items():
            (tmp / name).write_text(
                payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
        return tmp

    def test_all_three_keys_are_cited(self):
        payload = {
            "frame_path": "dataset/raw/one.png",
            "before_frame_path": "dataset/raw/before.png",
            "after_frame_path": "dataset/raw/after.png",
        }
        where = self._dir({"a.json": payload})
        cited = retention.unknown_request_evidence(Path("/nowhere"), directory=where)
        # The expectation is derived from the same payload instead of re-typed as fresh
        # ``Path()`` literals.  A repo-shaped record value is *data* -- nothing opens it --
        # and the evidence-integrity scan must not read the test's own payload as a
        # reference to repo evidence; deriving also removes any chance the two sides drift.
        self.assertEqual(cited, {Path(value) for value in payload.values()})

    def test_a_missing_directory_is_empty_not_an_error(self):
        self.assertEqual(
            retention.unknown_request_evidence(Path("/nowhere"), directory=Path("/no/such/dir")),
            set())

    def test_malformed_records_do_not_raise(self):
        """This runs inside the pruning pass; a raise here leaves the disk unbounded."""
        ok_payload = {"frame_path": "dataset/raw/ok.png"}
        where = self._dir({"broken.json": "{not json", "list.json": [1, 2], "ok.json": ok_payload})
        cited = retention.unknown_request_evidence(Path("/nowhere"), directory=where)
        self.assertEqual(cited, {Path(ok_payload["frame_path"])})

    def test_the_third_stream_is_wired_into_the_union(self):
        """A function nobody calls protects nothing -- which is the bug being fixed."""
        source = Path(retention.__file__).read_text(encoding="utf-8")
        self.assertIn("unknown_request_evidence(repo)", source,
                      "the evidence union in prune() must include the UNKNOWN corpus")
        self.assertIn('"frame_path"', source)


if __name__ == "__main__":
    unittest.main()
