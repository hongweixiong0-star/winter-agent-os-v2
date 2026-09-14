"""Extract cell-relative resource-tab templates and validate the detector.

Templates are the full selected cell (bracket included, so every template
carries the same bracket contribution and identity comes from the icon+label).
Detection is: locate the bracket -> crop that cell -> nearest template by
colour-grid distance -> require a decisive margin.

Prints a per-frame verdict for every labelled live frame, so false-positive
rejection on non-gatherable tabs (beast / giant beast / sawmill) is measured,
not assumed.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(r"E:\无尽冬日智能体")
CLEAN = ROOT / "dataset/truth_audit/resource_cells_20260914_120027"
OUT = ROOT / "dataset/candidate/resource_tabs"
OUT.mkdir(parents=True, exist_ok=True)

BAND = (0.672, 0.789)
BAND_H = 0.117
SIG = 16

# Measured bracket-left for each resource in this scroll state, with cell width.
CELL_W = 145
CELL_H = 150
MEASURED = {
    "MEAT": "20260914_120027_c_002_select_MEAT.png",
    "WOOD": "20260914_120027_c_003_select_WOOD.png",
    "COAL": "20260914_120027_c_004_select_COAL.png",
    "IRON": "20260914_120027_c_005_select_IRON.png",
}
ANCHORS = {"MEAT": 87, "WOOD": 244, "COAL": 402, "IRON": 559}


def strokes(path: Path, thr: int = 238):
    with Image.open(path) as im:
        im = im.convert("RGB")
        w, h = im.size
        y0, y1 = round(BAND[0] * h), round(BAND[1] * h)
        counts = []
        for x in range(w):
            c = 0
            for y in range(y0, y1):
                r, g, b = im.getpixel((x, y))
                if r >= thr and g >= thr and b >= thr:
                    c += 1
            counts.append(c)
    bandh = y1 - y0
    groups, cur = [], None
    for x, c in enumerate(counts):
        if c >= 0.18 * bandh:
            cur = [x, x, c] if cur is None else [cur[0], x, max(cur[2], c)]
        else:
            if cur:
                groups.append(tuple(cur))
                cur = None
    if cur:
        groups.append(tuple(cur))
    return [((a + b) / 2, b - a + 1) for a, b, _ in groups]


def bracket_left(path: Path) -> float | None:
    """Left bracket stroke of the active tab, or None when no bracket is present.

    The rule is the validated one: two near-white vertical strokes 130-175 px
    apart.  A lone stroke whose partner would fall off-screen is accepted as a
    partially visible selected cell.
    """
    cand = [s for s in strokes(path) if s[1] >= 3]
    for i, (a, _) in enumerate(cand):
        for b, _ in cand[i + 1:]:
            if 130 <= b - a <= 175:
                return a
    wide = sorted(a for a, _ in cand)
    return wide[0] if wide else None


def signature(crop: Image.Image) -> bytes:
    return crop.convert("RGB").resize((SIG, SIG), Image.Resampling.BILINEAR).tobytes()


def dist(a: bytes, b: bytes) -> float:
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def cell_crop(im: Image.Image, left: float):
    w, h = im.size
    y0, y1 = round(BAND[0] * h), round(BAND[1] * h)
    x0 = max(0, round(left))
    x1 = min(w, x0 + CELL_W)
    return im.crop((x0, y0, x1, y1))


print("== extracting cell-relative templates ==")
templates: dict[str, bytes] = {}
for res, name in MEASURED.items():
    with Image.open(CLEAN / name) as im:
        im = im.convert("RGB")
        detected = bracket_left(CLEAN / name)
        crop = cell_crop(im, detected)
        path = OUT / f"resource_tab_{res.lower()}__live_cell.png"
        crop.save(path)
        templates[res] = signature(crop)
        print(f"  {res:5s} detected_left={detected} anchor={ANCHORS[res]} crop={crop.size} -> {path.name}")

print("\n== evaluating on every labelled live frame ==")
CASES: list[tuple[str, Path, str]] = []
for n in sorted((ROOT / "dataset/truth_audit/gather_live_20260914_115120").glob("*_step_*.png")):
    CASES.append((n.stem.split("_step_")[1], n, "?"))
for n in sorted((ROOT / "dataset/truth_audit/resource_strip_20260914_115635").glob("*_s_*.png")):
    CASES.append((n.stem.split("_s_")[1], n, "?"))
for res, name in MEASURED.items():
    CASES.append((f"select_{res}", CLEAN / name, res))

EXPECT = {
    "001_home": None, "002_map": None,
    "003_search_panel": None, "004_tab_tap_MEAT": None, "005_tab_tap_WOOD": None,
    "006_tab_tap_COAL": "MEAT", "007_tab_tap_IRON": "WOOD",
}

ok = bad = 0
for label, path, truth in CASES:
    with Image.open(path) as im:
        im = im.convert("RGB")
        left = bracket_left(path)
        if left is None:
            verdict, detail = None, "NO_BRACKET"
        else:
            sig = signature(cell_crop(im, left))
            ranked = sorted(((dist(sig, t), r) for r, t in templates.items()))
            d0, r0 = ranked[0]
            d1, r1 = ranked[1]
            margin = d1 - d0
            if d0 <= 14.0 and margin >= 3.0:
                verdict, detail = r0, f"d={d0:.2f} runner={r1}:{d1:.2f} margin={margin:.2f}"
            else:
                verdict, detail = None, f"reject best={r0}:{d0:.2f} margin={margin:.2f}"
    expect = EXPECT.get(label, truth if truth != "?" else None)
    mark = "OK " if verdict == expect else "!! "
    if verdict == expect:
        ok += 1
    else:
        bad += 1
    print(f"  {mark}{label:34s} verdict={str(verdict):5s} expect={str(expect):5s} {detail}")

print(f"\nsummary: {ok} correct, {bad} mismatched, {len(CASES)} frames")
