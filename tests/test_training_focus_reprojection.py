from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from PIL import Image

from winter_agent_v2.camp_ring import reproject_point_on_static_city_view


def test_tutorial_overlay_change_is_allowed_only_when_city_view_is_static():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        rng = np.random.default_rng(4)
        reference = rng.integers(30, 220, size=(1280, 720), dtype=np.uint8)
        current = reference.copy()
        current[420:704, 164:556] = 255 - current[420:704, 164:556]
        Image.fromarray(reference).save(root / "reference.png")
        Image.fromarray(current).save(root / "current.png")

        assert reproject_point_on_static_city_view(
            root / "reference.png", root / "current.png", (0.50, 0.46)
        ) == (0.50, 0.46)

        moved = np.roll(current, 24, axis=1)
        Image.fromarray(moved).save(root / "moved.png")
        assert reproject_point_on_static_city_view(
            root / "reference.png", root / "moved.png", (0.50, 0.46)
        ) is None


def test_bad_or_out_of_frame_points_are_never_reprojected():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        frame = np.zeros((1280, 720), dtype=np.uint8)
        Image.fromarray(frame).save(root / "frame.png")
        assert reproject_point_on_static_city_view(
            root / "frame.png", root / "frame.png", (-0.1, 0.46)
        ) is None
        assert reproject_point_on_static_city_view(
            root / "missing.png", root / "frame.png", (0.50, 0.46)
        ) is None
