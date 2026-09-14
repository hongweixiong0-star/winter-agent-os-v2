import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageEnhance

from winter_agent_v2.vision import SemanticROIVision


ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "dataset" / "candidate" / "templates_manifest.json"
LIVE_MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"


class SemanticROIVisionTests(unittest.TestCase):
    def test_finds_close_without_emitting_pixel_coordinates(self) -> None:
        match = SemanticROIVision(MANIFEST).find(
            ROOT / "dataset" / "raw" / "live_current.png", "BTN_CLOSE"
        )
        self.assertIsNotNone(match)
        self.assertTrue(0.0 < match.center_norm[0] < 1.0)
        self.assertTrue(0.0 < match.center_norm[1] < 1.0)

    def test_rejects_wrong_semantic_region(self) -> None:
        match = SemanticROIVision(MANIFEST).find(
            ROOT / "dataset" / "raw" / "legacy_home.png", "BTN_CLOSE"
        )
        self.assertIsNone(match)

    def test_tolerates_small_brightness_change(self) -> None:
        source = ROOT / "dataset" / "raw" / "legacy_available_resource_detail.png"
        with tempfile.TemporaryDirectory() as directory:
            changed = Path(directory) / "changed.png"
            with Image.open(source) as image:
                ImageEnhance.Brightness(image).enhance(1.02).save(changed)
            match = SemanticROIVision(MANIFEST).find(changed, "BTN_GATHER")
            self.assertIsNotNone(match)

    def test_finds_map_search_with_active_march_overlay_variance(self) -> None:
        match = SemanticROIVision(LIVE_MANIFEST, max_distance=8).find(
            ROOT / "dataset" / "raw" / "live_runtime_gather_fill_queue_2" / "step_001_before.png",
            "BTN_OPEN_RESOURCE_SEARCH",
        )
        self.assertIsNotNone(match)
        self.assertLessEqual(match.distance, 12)


if __name__ == "__main__":
    unittest.main()
