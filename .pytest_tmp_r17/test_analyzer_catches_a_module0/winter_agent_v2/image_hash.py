from __future__ import annotations

import math

from PIL import Image


def _bits_to_hex(bits: list[bool]) -> str:
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return f"{value:0{len(bits) // 4}x}"


def dhash(image: Image.Image, size: int = 8) -> str:
    resized = image.convert("L").resize((size + 1, size))
    pixels = list(resized.get_flattened_data())
    bits: list[bool] = []
    for row in range(size):
        start = row * (size + 1)
        bits.extend(
            pixels[start + column] > pixels[start + column + 1]
            for column in range(size)
        )
    return _bits_to_hex(bits)


def phash(image: Image.Image, size: int = 8, highfreq_factor: int = 4) -> str:
    """Return a dependency-light perceptual hash suitable for screenshot gating."""
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
    return _bits_to_hex([value > median for value in coeffs])


def hamming(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()
