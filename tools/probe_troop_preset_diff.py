"""Read-only probe: does choosing a preset change anything but the gold ring?

Matters for the verifier.  If the only observable change is the ring, then
"selected index == target index" is the whole of the state change and the
verifier must be built on exactly that -- and must not lean on a troop count
that may not move.

Reads the 兵力 amounts off the two archived formation frames and prints them
side by side, plus a pixel diff of everything except the preset strip.

Read-only: writes only ``out_troop_preset_band/``.
"""

from __future__ import annotations

import os
import sys

from PIL import Image, ImageChops

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out_troop_preset_band")

A = "dataset/raw/bear_live_20260909/bear_troop_setup.png"   # no gold chip
B = "dataset/raw/bear_live_20260909/bear_preset6.png"       # 熊6 gold

# regions read off the frames
AMOUNT_ROI = (20, 170, 340, 220)      # 兵力 全部 amount, left of the bar
POWER_ROI = (430, 170, 700, 220)      # 战力 number, right of the bar
STRIP = (16, 84, 704, 168)


def ocr(im: Image.Image, roi):
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception as exc:  # noqa: BLE001
        return [f"<no rapidocr: {exc}>"]
    engine = RapidOCR()
    crop = im.crop(roi)
    crop = crop.resize((crop.width * 3, crop.height * 3), Image.LANCZOS)
    path = os.path.join(OUT, "ocr_tmp.png")
    crop.save(path)
    result, _ = engine(path)
    return [r[1] for r in (result or [])]


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    rep: list[str] = []
    ia = Image.open(os.path.join(ROOT, A)).convert("RGB")
    ib = Image.open(os.path.join(ROOT, B)).convert("RGB")

    for label, roi in (("兵力 amount", AMOUNT_ROI), ("战力", POWER_ROI)):
        rep.append(f"== {label} ==")
        rep.append(f"  A bear_troop_setup (no gold) : {ocr(ia, roi)}")
        rep.append(f"  B bear_preset6   (熊6 gold)  : {ocr(ib, roi)}")

    rep.append("")
    rep.append("== pixel diff outside the preset strip ==")
    diff = ImageChops.difference(ia, ib)
    px = diff.load()
    inside = outside = 0
    for y in range(0, 1280, 2):
        for x in range(0, 720, 2):
            d = sum(px[x, y])
            if d <= 30:
                continue
            if STRIP[0] <= x <= STRIP[2] and STRIP[1] <= y <= STRIP[3]:
                inside += 1
            else:
                outside += 1
    rep.append(f"  changed samples inside strip : {inside}")
    rep.append(f"  changed samples outside strip: {outside}")
    rep.append("  (a 2-px grid, so these are counts of 4-pixel blocks)")

    # where, outside the strip, does it differ?
    rows: dict[int, int] = {}
    for y in range(0, 1280, 2):
        for x in range(0, 720, 2):
            if sum(px[x, y]) > 30 and not (
                STRIP[0] <= x <= STRIP[2] and STRIP[1] <= y <= STRIP[3]
            ):
                rows[y // 20 * 20] = rows.get(y // 20 * 20, 0) + 1
    rep.append(f"  outside-strip differences by 20-px row band: "
               f"{sorted(rows.items(), key=lambda kv: -kv[1])[:12]}")

    # keep a visual of the strip pair for the record
    for label, im in (("A_no_gold", ia), ("B_xiong6_gold", ib)):
        crop = im.crop(STRIP)
        crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS).save(
            os.path.join(OUT, f"stripdiff_{label}.png")
        )

    with open(os.path.join(ROOT, "out_troop_preset_diff.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(rep))
    print("\n".join(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
