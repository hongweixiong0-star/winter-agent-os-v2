import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageEnhance

from winter_agent_v2.models import Page
from winter_agent_v2.vision import SignatureVision


ROOT = Path(__file__).parents[1]
LABELS = ROOT / "tests" / "replay" / "labels.json"


class SignatureVisionTests(unittest.TestCase):
    def test_recognizes_reviewed_live_popup(self) -> None:
        vision = SignatureVision(LABELS)
        state = vision.observe(ROOT / "dataset" / "raw" / "live_current.png")
        self.assertIs(state.page, Page.POPUP)
        self.assertEqual(state.popup, "PURCHASE_POPUP")

    def test_tolerates_small_brightness_change(self) -> None:
        source = ROOT / "dataset" / "raw" / "legacy_home.png"
        with tempfile.TemporaryDirectory() as directory:
            changed = Path(directory) / "changed.png"
            with Image.open(source) as image:
                ImageEnhance.Brightness(image).enhance(1.02).save(changed)
            self.assertIs(SignatureVision(LABELS).observe(changed).page, Page.HOME)

    def test_rejects_unreviewed_scene(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            unknown = Path(directory) / "unknown.png"
            Image.new("RGB", (720, 1280), (255, 0, 255)).save(unknown)
            self.assertIs(SignatureVision(LABELS).observe(unknown).page, Page.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
