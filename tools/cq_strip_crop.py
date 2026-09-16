"""Crop the resource-tab band from a calibration frame and a live failing frame.

The pitch measurement refuted the "pitch is wrong" hypothesis (measured 157/158 px
on frames whose selection is known, against a configured 157), and the joint
anchor search still finds NOTHING supported on the live frames.  So the difference
must be visible.  Put the same band side by side and look, rather than infer.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out_crop_strip"
OUT.mkdir(exist_ok=True)

FRAMES = {
    "cal_MEAT": "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_002_select_MEAT.png",
    "cal_IRON": "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_005_select_IRON.png",
    "live_fail": "dataset/raw/live_runtime/live_runtime_step_003_before_20260915T233727132656.png",
}

# The configured band is y 0.672..0.789 -> 860..1010 at 1280.  Take a generous
# slice so a shifted row would be visible rather than cropped away.
BAND = (0, 800, 720, 1120)


def main() -> int:
    for tag, rel in FRAMES.items():
        path = ROOT / rel
        if not path.exists():
            print("MISSING", rel)
            continue
        with Image.open(path) as opened:
            image = opened.convert("RGB")
        crop = image.crop(BAND)
        crop = crop.resize((crop.width, crop.height * 2), Image.LANCZOS)
        target = OUT / ("%s_band.png" % tag)
        crop.save(target)
        print("wrote", target.name, crop.size)

    # Also a full-frame side-by-side at reduced scale for layout context.
    sheets = []
    for tag, rel in FRAMES.items():
        path = ROOT / rel
        if path.exists():
            with Image.open(path) as opened:
                sheets.append((tag, opened.convert("RGB").resize((360, 640))))
    if sheets:
        sheet = Image.new("RGB", (360 * len(sheets), 640), (0, 0, 0))
        for index, (_tag, image) in enumerate(sheets):
            sheet.paste(image, (360 * index, 0))
        target = OUT / "side_by_side.png"
        sheet.save(target)
        print("wrote", target.name, sheet.size, [tag for tag, _ in sheets])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
