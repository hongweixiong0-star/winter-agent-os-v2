from __future__ import annotations

import unittest

from tools.extract_templates import roi_pixels, safe_name


class TemplateExtractionTests(unittest.TestCase):
    def test_roi_mapping(self) -> None:
        roi = {"x_norm":0.25,"y_norm":0.5,"w_norm":0.1,"h_norm":0.2}
        self.assertEqual(roi_pixels(roi, 720, 1280), (180, 640, 252, 896))

    def test_out_of_bounds_is_rejected(self) -> None:
        roi = {"x_norm":0.95,"y_norm":0.9,"w_norm":0.1,"h_norm":0.2}
        with self.assertRaises(ValueError):
            roi_pixels(roi, 720, 1280)

    def test_semantic_filename_is_safe(self) -> None:
        self.assertEqual(safe_name("BTN Search / 搜索"), "btn_search")


if __name__ == "__main__":
    unittest.main()
