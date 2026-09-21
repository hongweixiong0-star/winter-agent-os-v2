"""Read-only probe: validate the TROOP_PRESET recognition rule, measured not guessed.

Everything below was read off the archived dispatch frames; nothing is typed by
hand from memory.  The rule has three parts, each independently checkable:

 1. page gate   the dispatch page draws a near-uniform bar across y=88..96 whose
                colour is (13,129,198).  Frames that are not the dispatch page
                are far from it.
 2. chips       inside the bar, the preset chips are the runs of non-bar columns
                in the band y=104..144.  They are FOUND, not hardcoded: the
                number of presets is player-defined (this account happens to
                have eight).  The rightmost run is the save button.
 3. selected    a chip's border is gold (245,188,61) when selected and light blue
                (87,190,255) when not.  Sampled on the chip's left and right
                border columns, where the flag icon never reaches.

Run it as: python tools/probe_troop_preset_rule.py

Read-only: writes only ``out_troop_preset_rule.txt`` and tiles under
``out_troop_preset_band/``.
"""

from __future__ import annotations

import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out_troop_preset_band")

BAR_ROWS = (88, 96)
BAR_REF = (13, 129, 198)
BAR_TOL = 30
#: The stripe above the chips is not unique in the corpus: the alliance-tech page
#: draws a similar bar at (19,141,227) and passed the symmetric tolerance, which
#: would have made the probe tap the wrong page's widgets.  Measured over the
#: dispatch frames the bar is (15..35, 129..133, 192..198), so the separating
#: test is on blue: 192..198 for the formation page, 227 for alliance tech.
#: Kept as a separate, named test rather than a tightened symmetric tolerance so
#: the reason it exists survives.
BAR_BLUE_REF = 196
BAR_BLUE_TOL = 20
BAR_GREEN_REF = 131
BAR_GREEN_TOL = 14
BAR_RED_MAX = 45

CHIP_BAND = (104, 144)
CHIP_MIN_W = 30

GOLD_REF = (245, 188, 61)
BLUE_RING_REF = (87, 190, 255)
RING_TOL = 45
BORDER_INSET = 6          # sample this far inside the run's edge
RING_ROWS = (112, 136)
MIN_RING_PIXELS = 12


def _near(a, b, tol: int) -> bool:
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol and abs(a[2] - b[2]) <= tol


def bar_colour(im: Image.Image):
    px = im.load()
    n = 0
    acc = [0, 0, 0]
    for y in range(BAR_ROWS[0], BAR_ROWS[1] + 1):
        for x in range(24, 700, 8):
            c = px[x, y]
            acc[0] += c[0]
            acc[1] += c[1]
            acc[2] += c[2]
            n += 1
    return (acc[0] // n, acc[1] // n, acc[2] // n)


def is_dispatch_page(im: Image.Image):
    if im.size != (720, 1280):
        return False, (0, 0, 0)
    mean = bar_colour(im)
    ok = (
        abs(mean[2] - BAR_BLUE_REF) <= BAR_BLUE_TOL
        and abs(mean[1] - BAR_GREEN_REF) <= BAR_GREEN_TOL
        and mean[0] <= BAR_RED_MAX
        and _near(mean, BAR_REF, BAR_TOL)
    )
    return ok, mean


def find_chips(im: Image.Image):
    """Column runs inside the bar band that are not bar-coloured."""
    px = im.load()
    runs = []
    start = None
    for x in range(18, 712):
        cols = [px[x, y] for y in range(CHIP_BAND[0], CHIP_BAND[1], 4)]
        off_bar = sum(0 if _near(c, BAR_REF, BAR_TOL) else 1 for c in cols)
        is_chip = off_bar >= 3
        if is_chip and start is None:
            start = x
        elif not is_chip and start is not None:
            if x - start >= CHIP_MIN_W:
                runs.append((start, x - 1))
            start = None
    if start is not None and 712 - start >= CHIP_MIN_W:
        runs.append((start, 711))
    return runs


def read_chip(im: Image.Image, run):
    """Return (gold, blue) pixel counts on the run's border columns."""
    px = im.load()
    a, b = run
    gold = blue = 0
    for x in (a + BORDER_INSET, a + BORDER_INSET + 1, b - BORDER_INSET - 1, b - BORDER_INSET):
        for y in range(RING_ROWS[0], RING_ROWS[1] + 1):
            c = px[x, y]
            if _near(c, GOLD_REF, RING_TOL):
                gold += 1
            elif _near(c, BLUE_RING_REF, RING_TOL):
                blue += 1
    return gold, blue


def verdict(gold: int, blue: int) -> str:
    if gold >= MIN_RING_PIXELS and gold > blue:
        return "selected"
    if blue >= MIN_RING_PIXELS:
        return "unselected"
    return "unknown"


def analyse(im: Image.Image):
    runs = find_chips(im)
    out = []
    for i, run in enumerate(runs):
        gold, blue = read_chip(im, run)
        out.append((i, run, gold, blue, verdict(gold, blue)))
    return runs, out


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    rep: list[str] = []

    known = [
        ("dataset/raw/bear_live_20260909/bear_preset6.png", "熊6 (6th) is gold"),
        ("dataset/raw/bear_live_20260909/bear_troop_setup.png", "no gold chip"),
        ("dataset/raw/live_bear_troop_reduced.png", "no gold chip"),
        ("dataset/raw/live_march_selection.png", "gather dispatch, unknown gold"),
        ("dataset/raw/live_beast_march_selection.png", "beast dispatch"),
        ("dataset/raw/live_intel_beast10_march_current.png", "intel beast dispatch"),
    ]
    for rel, note in known:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            rep.append(f"{rel}: MISSING")
            continue
        im = Image.open(p).convert("RGB")
        gate, mean = is_dispatch_page(im)
        runs, chips = analyse(im) if gate else ([], [])
        rep.append(f"-- {rel}  [{note}]")
        rep.append(f"   gate={gate} bar={mean} chips_found={len(runs)}")
        for i, run, gold, blue, v in chips:
            rep.append(f"     chip{i} x{run[0]}-{run[1]} w{run[1]-run[0]+1} "
                       f"gold={gold:3d} blue={blue:3d} -> {v}")
        sel = [i for i, _, _, _, v in chips if v == "selected"]
        rep.append(f"   selected indices = {sel}")
        # tile for the eye
        crop = im.crop((16, 84, 704, 168))
        crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS).save(
            os.path.join(OUT, f"strip_{os.path.basename(rel)}")
        )

    rep.append("")
    rep.append("== page gate over the whole archived corpus (false-positive hunt) ==")
    scanned = 0
    hits = []
    for base in ("dataset/raw", "dataset/raw/bear_live_20260909"):
        d = os.path.join(ROOT, base)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not name.lower().endswith(".png"):
                continue
            p = os.path.join(d, name)
            try:
                im = Image.open(p).convert("RGB")
            except Exception:
                continue
            if im.size != (720, 1280):
                continue
            scanned += 1
            gate, mean = is_dispatch_page(im)
            if gate:
                runs, chips = analyse(im)
                sel = [i for i, _, _, _, v in chips if v == "selected"]
                hits.append(f"  HIT {base}/{name} bar={mean} chips={len(runs)} selected={sel}")
    rep.append(f"  scanned {scanned} frame(s)")
    rep.extend(hits or ["  no hits"])
    rep.append(f"  total hits: {len(hits)}")

    with open(os.path.join(ROOT, "out_troop_preset_rule.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(rep))
    print("\n".join(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
