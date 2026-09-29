"""TASK THROUGHPUT V1 guards: the hash fast paths must not change a single answer.

Directive §25 requires a baseline before optimising and §27 requires every optimisation to be
kept only if it holds up.  The measurement that drove these changes (real production frame,
``learning/action_latency.jsonl``): ``reobserve_ms`` was 11.2 s P50 of a 13.2 s step, and a
cProfile of one observation put 13.8 s in 101,038 ``dhash`` calls and 8.9 s in 460 ``phash``
calls.  The fixes were justified *only* because they are bit-identical, so bit-identity is what
this module pins:

* ``phash``/``dhash`` are compared against the naive reference implementation -- the one that
  called ``math.cos`` in the innermost loop -- on synthetic images of several shapes;
* the map sweep is compared against a brute-force reimplementation of the original double loop,
  planted with a real hit so the early-exit path is exercised too;
* and the sweep is checked to hash each rectangle once, which is the whole point of the change.
"""

from __future__ import annotations

import json
import math
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from winter_agent_v2 import vision as vision_module
from winter_agent_v2.image_hash import _cos_table, dhash, hamming, phash
from winter_agent_v2.vision import SemanticROIVision


ROOT = Path(__file__).parents[1]


# ---------------------------------------------------------------------------------
# The reference implementations.  Deliberately the slow, obvious versions.
# ---------------------------------------------------------------------------------

def _reference_bits_to_hex(bits: list[bool]) -> str:
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return f"{value:0{len(bits) // 4}x}"


def reference_dhash(image: Image.Image, size: int = 8) -> str:
    resized = image.convert("L").resize((size + 1, size))
    pixels = list(resized.get_flattened_data())
    bits: list[bool] = []
    for row in range(size):
        start = row * (size + 1)
        bits.extend(
            pixels[start + column] > pixels[start + column + 1] for column in range(size)
        )
    return _reference_bits_to_hex(bits)


def reference_phash(image: Image.Image, size: int = 8, highfreq_factor: int = 4) -> str:
    """The original 2-D DCT, ``math.cos`` in the inner loop and all."""
    n = size * highfreq_factor
    resized = image.convert("L").resize((n, n))
    pixels = list(resized.get_flattened_data())
    rows = [pixels[index * n : (index + 1) * n] for index in range(n)]
    coeffs: list[float] = []
    for u in range(size):
        for v in range(size):
            total = 0.0
            for x in range(n):
                cosine_x = math.cos((2 * x + 1) * u * math.pi / (2 * n))
                for y in range(n):
                    total += rows[y][x] * cosine_x * math.cos(
                        (2 * y + 1) * v * math.pi / (2 * n)
                    )
            coeffs.append(total)
    median = sorted(coeffs[1:])[len(coeffs[1:]) // 2]
    return _reference_bits_to_hex([value > median for value in coeffs])


def _sample_images() -> list[Image.Image]:
    """A deterministic spread: flat, gradient, noise, and two real template files."""
    rng = random.Random(20260930)
    images = [
        Image.new("RGB", (90, 130), (17, 34, 51)),
        Image.new("RGB", (91, 129), (200, 200, 200)),
        Image.new("L", (100, 140), 128),
    ]
    gradient = Image.new("RGB", (120, 160))
    gradient.putdata([
        ((x * 2) % 256, (y * 2) % 256, ((x + y) * 3) % 256)
        for y in range(160) for x in range(120)
    ])
    images.append(gradient)
    noise = Image.new("RGB", (110, 150))
    noise.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256))
                   for _ in range(110 * 150)])
    images.append(noise)
    template_dir = ROOT / "dataset/candidate/templates"
    for path in sorted(template_dir.glob("*.png"))[:4] if template_dir.exists() else []:
        try:
            with Image.open(path) as opened:
                images.append(opened.convert("RGB"))
        except OSError:
            continue
    return images


class HashBitIdentityTests(unittest.TestCase):
    """The fast paths must reproduce the naive implementation exactly."""

    def test_dhash_is_bit_identical_to_the_reference(self) -> None:
        for image in _sample_images():
            for size in (8, 16):
                with self.subTest(size=size, mode=image.mode, box=image.size):
                    self.assertEqual(
                        dhash(image, size=size), reference_dhash(image, size=size)
                    )

    def test_phash_is_bit_identical_to_the_reference(self) -> None:
        for image in _sample_images():
            for size, highfreq in ((8, 4), (16, 4)):
                with self.subTest(size=size, mode=image.mode, box=image.size):
                    self.assertEqual(
                        phash(image, size=size, highfreq_factor=highfreq),
                        reference_phash(image, size=size, highfreq_factor=highfreq),
                    )

    def test_the_shared_cosine_table_holds_exactly_math_cos(self) -> None:
        """Values, not approximations: the accumulator must see the same doubles."""
        for size, n in ((8, 32), (16, 64)):
            table = _cos_table(size, n)
            self.assertEqual(len(table), size)
            for k in range(size):
                self.assertEqual(len(table[k]), n)
                for t in range(n):
                    self.assertEqual(table[k][t], math.cos((2 * t + 1) * k * math.pi / (2 * n)))

    def test_the_cosine_table_is_reused_between_calls(self) -> None:
        self.assertIs(_cos_table(8, 32), _cos_table(8, 32))

    def test_a_luminance_image_is_not_reconverted(self) -> None:
        """``convert`` copies when the mode already matches, so skipping it is exact."""
        gray = _sample_images()[0].convert("L")
        self.assertEqual(dhash(gray), reference_dhash(gray))
        self.assertEqual(phash(gray), reference_phash(gray))


class MapSweepEquivalenceTests(unittest.TestCase):
    """``_find_anywhere`` must return the same distance and rectangle, hit or miss."""

    WIDTH, HEIGHT = 720, 1280
    REGION = (0.10, 0.10, 0.90, 0.90)

    def _fixture(self, *, plant_hit: bool):
        """A synthetic map frame plus one sweep record, optionally with the target drawn in."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)

        rng = random.Random(4242)
        frame = Image.new("RGB", (self.WIDTH, self.HEIGHT))
        frame.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256))
                       for _ in range(self.WIDTH * self.HEIGHT)])

        crop_w, crop_h = 88, 112
        template = Image.new("RGB", (crop_w, crop_h))
        template.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256))
                          for _ in range(crop_w * crop_h)])
        template_path = root / "sweep_target.png"
        template.save(template_path)

        step = max(4, round(self.WIDTH / 90))
        x_start = round(self.WIDTH * self.REGION[0])
        y_start = round(self.HEIGHT * self.REGION[1])
        # A grid-aligned offset inside the region, so the planted patch is exactly a candidate.
        planted = (x_start + step, y_start + step)
        if plant_hit:
            frame.paste(template, planted)

        frame_path = root / "sweep_frame.png"
        frame.save(frame_path)

        manifest = root / "manifest.json"
        manifest.write_text(json.dumps({"records": []}), encoding="utf-8")
        vision = SemanticROIVision(manifest)
        vision.records = [{
            "semantic": "TEST_SWEEP",
            "matcher": "phash",
            "template_path": str(template_path),
            "roi_norm": {
                "x_norm": crop_w / self.WIDTH, "y_norm": crop_h / self.HEIGHT,
                "w_norm": crop_w / self.WIDTH, "h_norm": crop_h / self.HEIGHT,
            },
        }]
        vision.anywhere_max_distance["TEST_SWEEP"] = 64
        vision.anywhere_regions["TEST_SWEEP"] = self.REGION
        vision.attention["widen"] = True
        return vision, frame_path, planted

    def _brute_force(self, vision, frame_path: Path):
        """The original double loop, with no memoisation and no early exit."""
        with Image.open(frame_path) as opened:
            image = opened.convert("RGB")
        width, height = image.size
        x0, y0, x1, y1 = self.REGION
        x_start, x_stop = round(width * x0), round(width * x1)
        y_start, y_stop = round(height * y0), round(height * y1)
        step = max(4, round(width / 90))
        best = None
        for row in vision.records:
            roi = row["roi_norm"]
            crop_width = max(8, round(roi["w_norm"] * width))
            crop_height = max(8, round(roi["h_norm"] * height))
            with Image.open(row["template_path"]) as opened:
                target_hash = reference_dhash(opened, size=16)
            for y in range(y_start, max(y_start + 1, y_stop - crop_height + 1), step):
                for x in range(x_start, max(x_start + 1, x_stop - crop_width + 1), step):
                    distance = hamming(
                        target_hash,
                        reference_dhash(
                            image.crop((x, y, x + crop_width, y + crop_height)), size=16
                        ),
                    )
                    if best is None or distance < best["distance"]:
                        best = {
                            "distance": distance,
                            "x": x, "y": y,
                            "roi": {
                                "x_norm": x / width, "y_norm": y / height,
                                "w_norm": crop_width / width, "h_norm": crop_height / height,
                            },
                        }
        return best

    def test_a_miss_agrees_with_the_brute_force_scan(self) -> None:
        """No plant: both paths must decline, and for the same reason (the minimum is too far)."""
        vision, frame_path, _ = self._fixture(plant_hit=False)
        hit = vision._find_anywhere(frame_path, vision.records, "TEST_SWEEP")
        oracle = self._brute_force(vision, frame_path)

        self.assertIsNone(hit, "a random frame must not contain a planted-looking match")
        self.assertGreater(oracle["distance"], vision.anywhere_max_distance["TEST_SWEEP"])

    def test_a_hit_matches_the_brute_force_distance_and_rectangle(self) -> None:
        """Planted so the distance is 0, which is also what fires the early exit."""
        vision, frame_path, planted = self._fixture(plant_hit=True)
        hit = vision._find_anywhere(frame_path, vision.records, "TEST_SWEEP")
        oracle = self._brute_force(vision, frame_path)

        self.assertEqual(oracle["distance"], 0, "the planted patch must hash to the template")
        self.assertIsNotNone(hit)
        self.assertEqual(int(hit.distance), oracle["distance"])
        self.assertEqual(
            {k: round(float(v), 6) for k, v in hit.roi.items()},
            {k: round(float(v), 6) for k, v in oracle["roi"].items()},
        )
        self.assertEqual(
            (round(hit.roi["x_norm"] * self.WIDTH), round(hit.roi["y_norm"] * self.HEIGHT)),
            planted,
        )

    def test_the_sweep_hashes_each_rectangle_once(self) -> None:
        """The optimisation: rows that share a crop size must not re-hash the same window.

        ``TARGET_INTEL_BEAST_MISSION`` is the production case -- 10 candidate rows at only 4
        distinct sizes, measured at 3.85 s for one sweep before this change.
        """
        vision, frame_path, _ = self._fixture(plant_hit=False)
        # Three rows sharing one crop size, so a naive loop hashes every window three times.
        base = vision.records[0]
        vision.records = [dict(base) for _ in range(3)]

        calls = {"n": 0}
        real_dhash = vision_module.dhash

        def counting(image, size=8):
            calls["n"] += 1
            return real_dhash(image, size=size)

        with patch.object(vision_module, "dhash", side_effect=counting):
            vision._find_anywhere(frame_path, vision.records, "TEST_SWEEP")

        width, height = self.WIDTH, self.HEIGHT
        step = max(4, round(width / 90))
        x_start, x_stop = round(width * self.REGION[0]), round(width * self.REGION[2])
        y_start, y_stop = round(height * self.REGION[1]), round(height * self.REGION[3])
        roi = vision.records[0]["roi_norm"]
        crop_w = max(8, round(roi["w_norm"] * width))
        crop_h = max(8, round(roi["h_norm"] * height))
        columns = len(range(x_start, max(x_start + 1, x_stop - crop_w + 1), step))
        rows = len(range(y_start, max(y_start + 1, y_stop - crop_h + 1), step))
        distinct = columns * rows

        # ``dhash`` also serves ``_template_digest``, which hashes each template file once and
        # caches it, so exactly one of these calls is the template rather than a window.
        self.assertEqual(
            calls["n"], distinct + 1, "every window must be hashed exactly once"
        )
        # The naive loop would have hashed the same grid once per row.
        self.assertEqual(distinct * len(vision.records) + 1, distinct * 3 + 1)
        self.assertLess(calls["n"], distinct * len(vision.records))


if __name__ == "__main__":
    unittest.main()
