from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tools.dataset_audit import build_manifest, dhash, hamming


class DatasetAuditTests(unittest.TestCase):
    def test_hash_is_stable(self) -> None:
        image = Image.new("RGB", (32, 32), "white")
        self.assertEqual(dhash(image), dhash(image.copy()))
        self.assertEqual(hamming(dhash(image), dhash(image.copy())), 0)

    def test_exact_duplicate_and_damaged(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            Image.new("RGB", (32, 32), "red").save(root / "a.png")
            (root / "b.png").write_bytes((root / "a.png").read_bytes())
            (root / "bad.png").write_bytes(b"not-a-png")
            metadata = root / "metadata.json"
            metadata.write_text(json.dumps({"assets": {}}), encoding="utf-8")
            manifest = build_manifest(root, metadata)
            self.assertEqual(manifest["counts"]["CANDIDATE"], 1)
            self.assertEqual(manifest["counts"]["DUPLICATE"], 1)
            self.assertEqual(manifest["counts"]["DAMAGED"], 1)

    def test_runtime_capture_gets_live_client_provenance_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            capture = root / "live_runtime_example"
            capture.mkdir()
            Image.new("RGB", (32, 32), "blue").save(capture / "step_001_before.png")
            metadata = root / "metadata.json"
            metadata.write_text(json.dumps({"assets": {}}), encoding="utf-8")
            manifest = build_manifest(root, metadata)
            record = manifest["records"][0]
            self.assertEqual(record["source"], "LIVE_CLIENT")
            self.assertEqual(record["source_path"], "ADB:emulator-5554/com.gof.china")


if __name__ == "__main__":
    unittest.main()
