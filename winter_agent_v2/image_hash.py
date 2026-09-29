from __future__ import annotations

import math

from PIL import Image


def _bits_to_hex(bits: list[bool]) -> str:
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return f"{value:0{len(bits) // 4}x}"


def _gray(image: Image.Image) -> Image.Image:
    """Luminance plane, without copying one that is already luminance.

    ``Image.convert`` returns a *copy* when the mode already matches, so this is the same
    pixels either way; it only stops the duplicate allocation.  Measured with cProfile on a
    real production frame, the redundant conversions inside the map sweep were 101,533 calls
    (directive §24/§27).
    """
    return image if image.mode == "L" else image.convert("L")


def dhash(image: Image.Image, size: int = 8) -> str:
    resized = _gray(image).resize((size + 1, size))
    pixels = list(resized.get_flattened_data())
    bits: list[bool] = []
    for row in range(size):
        start = row * (size + 1)
        bits.extend(
            pixels[start + column] > pixels[start + column + 1]
            for column in range(size)
        )
    return _bits_to_hex(bits)


#: ``[size][k][t] = cos((2t + 1)·k·π / 2n)`` for ``n = size * highfreq_factor``.
#:
#: The first version called ``math.cos`` in the innermost loop of the 2-D DCT, which is
#: 2·size²·n² evaluations of only ``size·n`` distinct angles.  Profiled on a real production
#: frame: **31,088,640 calls, 2.7 s**, for three observations (directive §24/§27 "从真实耗时日志找
#: TOP TIME SINKS").  The table holds the identical ``math.cos`` results, so the coefficient sums
#: are accumulated from the same values in the same order and the digest is bit-identical --
#: which is the only kind of change this directive allows here.
#: Bounded, because the table size is ``size * n`` and a caller is free to pass a large
#: ``size``: an unbounded cache would turn a memo into a leak.  Production uses exactly two
#: entries ((8, 32) and (16, 64)); the clear keeps a misuse from costing memory.
_COS_TABLES: dict[tuple[int, int], tuple[tuple[float, ...], ...]] = {}
_COS_TABLE_LIMIT = 8


def _cos_table(size: int, n: int) -> tuple[tuple[float, ...], ...]:
    key = (size, n)
    table = _COS_TABLES.get(key)
    if table is None:
        table = tuple(
            tuple(math.cos((2 * t + 1) * k * math.pi / (2 * n)) for t in range(n))
            for k in range(size)
        )
        if len(_COS_TABLES) >= _COS_TABLE_LIMIT:
            _COS_TABLES.clear()
        _COS_TABLES[key] = table
    return table


def phash(image: Image.Image, size: int = 8, highfreq_factor: int = 4) -> str:
    """Return a dependency-light perceptual hash suitable for screenshot gating."""
    n = size * highfreq_factor
    resized = _gray(image).resize((n, n))
    pixels = list(resized.get_flattened_data())
    table = _cos_table(size, n)
    coeffs: list[float] = []
    for u in range(size):
        cos_u = table[u]
        for v in range(size):
            cos_v = table[v]
            total = 0.0
            for x in range(n):
                cosine_x = cos_u[x]
                base = x
                for y in range(n):
                    total += pixels[base] * cosine_x * cos_v[y]
                    base += n
            coeffs.append(total)
    median = sorted(coeffs[1:])[len(coeffs[1:]) // 2]
    return _bits_to_hex([value > median for value in coeffs])


def hamming(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()
