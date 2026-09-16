"""Crop the right-hand HUD column of the intel frames for visual comparison.

The phash measurement showed the positives at distance 34-38 and the negatives at
30-32 -- almost no separation -- which means the registered ROI probably does not
sit on the control at all.  Before changing any geometry, look at what is actually
in that column on the failing frames versus the last-known-good one.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out_crop_right_column"
OUT.mkdir(exist_ok=True)

FRAMES = {
    "fail_a": "dataset/raw/control_panel/runtime_auto/intel_pins_20260915_230510_nav_00/intel_pins_20260915_230510_nav_00_step_002_before_20260915T230548379879.png",
    "fail_b": "dataset/raw/control_panel/runtime_auto/intel_pins_20260915_230917_nav_01/intel_pins_20260915_230917_nav_01_step_004_before_20260915T231036773155.png",
    "good": "dataset/raw/live_runtime/live_runtime_step_001_before_20260915T133445437576.png",
}

# The right-hand icon column, generously framed.
BOX = (540, 140, 720, 940)

for tag, rel in FRAMES.items():
    path = ROOT / rel
    if not path.exists():
        print("MISSING", rel)
        continue
    with Image.open(path) as opened:
        image = opened.convert("RGB")
        crop = image.crop(BOX)
        # scale x2 so small glyphs are readable
        crop = crop.resize((crop.width * 2, crop.height * 2), Image.NEAREST)
        target = OUT / ("%s_right_column.png" % tag)
        crop.save(target)
        print("wrote", target.name, crop.size)

# Also crop exactly the registered ROI on each frame, to see what the matcher sees.
ROI = (623, 813, 709, 909)
for tag, rel in FRAMES.items():
    path = ROOT / rel
    if not path.exists():
        continue
    with Image.open(path) as opened:
        image = opened.convert("RGB")
        crop = image.crop(ROI).resize((86 * 3, 96 * 3), Image.NEAREST)
        target = OUT / ("%s_roi.png" % tag)
        crop.save(target)
        print("wrote", target.name, crop.size)

with Image.open(ROOT / "dataset/candidate/intel_wild_entry_v2/btn_open_intel_wild_hud__wild_fresh_before__0.png") as opened:
    template = opened.convert("RGB")
    target = OUT / "template_roi.png"
    template.resize((template.width * 3, template.height * 3), Image.NEAREST).save(target)
    print("wrote", target.name, template.size)
