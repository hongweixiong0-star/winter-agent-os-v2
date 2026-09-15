"""Measure whether the HUD stamina ROI can read a genuine ``0``.

Why this exists
---------------
Measured live 2026-09-15T04:03:02Z (``dataset/raw/live_free_gift_claim_20260915b/
..._step_002_before_...png``): after the previous run's Hero Journey fight spent
its 10 stamina the gauge genuinely read **0**, and the production ROI read
returned *zero tokens* -- so ``HybridVision`` reported ``stamina={}`` on a world
map frame.  Two consequences followed from that one empty read:

* RuleBrain's map branch requires ``world.stamina["current"] is not None``
  before it will open the free-stamina panel, so the run skipped the check
  entirely -- on the exact frame where the free +150 gift mattered most; and
* RuleBrain's camp-panel affordability gate needs two integers, so it could not
  fire either.

The recognizer needs a little more vertical context than the 42x24 ROI gives: a
single ``0`` glyph is small, and on the 42x24 crop nothing is detected at all.

This probe answers two questions with numbers instead of reasoning:

1. At which padding/scale does the recognizer actually report the ``0``, and at
   what confidence?  (If the confidence stays below any sane gate, then the fix
   is *not* "lower the threshold" and must be something else.)
2. Does the winning rule change any value that already reads correctly?  A rule
   that silently rewrites a good reading is worse than the miss it repairs.

Run it read-only; it writes nothing outside ``dataset/probe_output/``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.ocr import (  # noqa: E402
    HUD_STAMINA_ROI,
    OCRService,
    RapidOCRBackend,
    ResilientOCRBackend,
    parse_stamina_number,
)

OUT = ROOT / "dataset" / "probe_output" / "stamina_zero"

# The frame that exposed the miss, plus every frame from today's two runs.
MISS_FRAME = (
    ROOT / "dataset/raw/live_free_gift_claim_20260915b"
    / "live_free_gift_claim_20260915b_step_002_before_20260915T040302279214.png"
)


def build_ocr() -> OCRService:
    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    return OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))


def roi_box(width: int, height: int, pad: int) -> tuple[int, int, int, int]:
    roi = HUD_STAMINA_ROI
    return (
        int(roi["x_norm"] * width),
        int(roi["y_norm"] * height) - pad,
        int((roi["x_norm"] + roi["w_norm"]) * width),
        int((roi["y_norm"] + roi["h_norm"]) * height) + pad,
    )


def read_with_padding(ocr: OCRService, image_path: Path, pad: int, scale: int = 1):
    """Return (tokens, parsed) for the ROI grown by ``pad`` px vertically."""
    with Image.open(image_path) as source:
        image = source.convert("RGB")
    crop = image.crop(roi_box(image.width, image.height, pad))
    if scale != 1:
        crop = crop.resize((crop.width * scale, crop.height * scale), Image.LANCZOS)
    OUT.mkdir(parents=True, exist_ok=True)
    scratch = OUT / f"_scratch_pad{pad}_x{scale}.png"
    crop.save(scratch)
    result = ocr.recognize(scratch, {"x_norm": 0.0, "y_norm": 0.0, "w_norm": 1.0, "h_norm": 1.0})
    return result.tokens, parse_stamina_number(result.tokens)


def frames() -> list[Path]:
    found: list[Path] = []
    for pattern in (
        "dataset/raw/live_free_gift_claim_20260915*/*.png",
        "dataset/raw/live_intel_hero_journey_2026091*/*.png",
        "dataset/truth_audit/camp_panel_stamina_gate_20260915/*.png",
        "dataset/truth_audit/stamina_check_live_20260915/*.png",
    ):
        found.extend(sorted(ROOT.glob(pattern)))
    return [path for path in found if path.is_file()]


def main() -> int:
    ocr = build_ocr()
    print(f"HUD_STAMINA_ROI = {HUD_STAMINA_ROI}")

    print("\n== 1. the frame whose gauge really reads 0")
    with Image.open(MISS_FRAME) as source:
        print(f"   frame {MISS_FRAME.name} size={source.size}")
    for pad in (0, 2, 4, 6, 8):
        for scale in (1, 2):
            tokens, parsed = read_with_padding(ocr, MISS_FRAME, pad, scale)
            shown = [(token.text, round(token.confidence, 3)) for token in tokens]
            print(f"   pad={pad:>2} scale={scale} -> {shown}  parsed={parsed}")

    print("\n== 2. does a padded read change any value that already reads correctly?")
    corpus = frames()
    print(f"   {len(corpus)} frames")
    changed = 0
    read_now = 0
    read_padded = 0
    for path in corpus:
        with Image.open(path) as source:
            image = source.convert("RGB")
        if image.size != (720, 1280):
            continue
        base_tokens = ocr.recognize(path, HUD_STAMINA_ROI).tokens
        base = parse_stamina_number(base_tokens)
        padded_tokens, padded = read_with_padding(ocr, path, 4)
        if base is not None:
            read_now += 1
        if padded is not None:
            read_padded += 1
        if base != padded:
            changed += 1
            print(
                f"   DIFF {path.name[:64]:<64} roi={base} padded={padded} "
                f"padded_tokens={[(t.text, round(t.confidence,3)) for t in padded_tokens]}"
            )
    print(f"   readable now={read_now}  readable padded={read_padded}  disagreements={changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
