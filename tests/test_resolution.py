from __future__ import annotations

import unittest


def map_roi(roi: dict[str, float], width: int, height: int) -> tuple[int, int, int, int]:
    return tuple(round(roi[key] * scale) for key, scale in (("x_norm", width), ("y_norm", height), ("w_norm", width), ("h_norm", height)))


class ResolutionTests(unittest.TestCase):
    def test_normalized_roi_scales(self) -> None:
        roi = {"x_norm":0.25,"y_norm":0.5,"w_norm":0.1,"h_norm":0.2}
        self.assertEqual(map_roi(roi, 720, 1280), (180, 640, 72, 256))
        self.assertEqual(map_roi(roi, 1080, 2460), (270, 1230, 108, 492))

    def test_roi_is_inside_screen(self) -> None:
        roi = {"x_norm":0.01,"y_norm":0.65,"w_norm":0.11,"h_norm":0.08}
        x, y, w, h = map_roi(roi, 1440, 2560)
        self.assertGreaterEqual(x, 0)
        self.assertLessEqual(x + w, 1440)
        self.assertLessEqual(y + h, 2560)
