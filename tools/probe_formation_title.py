"""Does the 出征 formation page actually display which beast it will attack?

Read-only corpus probe.  Motivation (2026-09-15)
-----------------------------------------------
``SemanticWorldVision`` reports a beast identity on ``Page.MARCH``, but that
identity is not read from the page: ``BTN_BEAST_DISPATCH_MUSK_OX_9`` and
``BTN_BEAST_DISPATCH`` are crops of *the same* 出征 button taken from two
different live frames, and both match both frames at distance 0 (measured with
``tools/probe_beast_formation_identity.py``).  The reported name/level is
therefore decided by branch order, i.e. by nothing.

A visual review of the two parent frames showed a real difference that the
classifier never looks at: the **title bar**.  The wilderness frame reads
``目标：麝牛`` while the intel frame reads plain ``出征``.

This probe asks the question that decides the fix: across the whole corpus,
which frames are formation pages, and what does each one's title bar say?  If
the title carries the target, the honest fix is to read it; if it does not, the
identity must be removed from this page and carried forward instead.

Usage::

    "E:/dongri-mumu-bot/.venv/Scripts/python.exe" tools/probe_formation_title.py
    ... tools/probe_formation_title.py --corpus dataset/raw/stamina_emergency
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"

# Any of these means "this frame is the 出征 formation page".
FORMATION_ANCHORS = (
    "PAGE_BEAST_MARCH",
    "BTN_BEAST_DISPATCH",
    "BTN_BEAST_DISPATCH_MUSK_OX_9",
)

# The title strip, measured on the two reviewed parent frames (720x1280):
# the 出征 / 目标：<name> text sits at x 86-260, y 15-75.  The ROI is widened a
# little so a longer target name is not clipped.
TITLE_ROI = (0.08, 0.004, 0.50, 0.066)


def build_ocr():
    from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    return OCRService(
        ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"])))
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default="dataset/raw")
    parser.add_argument("--threshold", type=int, default=8)
    args = parser.parse_args()

    corpus = Path(args.corpus)
    if not corpus.is_absolute():
        corpus = ROOT / corpus
    frames = sorted(corpus.rglob("*.png"))

    vision = SemanticWorldVision(MANIFEST, max_distance=args.threshold)
    ocr = build_ocr()

    hits: list[tuple[Path, dict[str, int]]] = []
    for frame in frames:
        matched: dict[str, int] = {}
        for name in FORMATION_ANCHORS:
            found = vision.semantic.find(frame, name)
            if found is not None:
                matched[name] = found.distance
        if matched:
            hits.append((frame, matched))

    print(f"corpus={corpus} frames={len(frames)} formation-page frames={len(hits)}", flush=True)

    width, height = TITLE_ROI[2] - TITLE_ROI[0], TITLE_ROI[3] - TITLE_ROI[1]
    for frame, matched in hits:
        with Image.open(frame) as image:
            bounds = (
                round(TITLE_ROI[0] * image.size[0]),
                round(TITLE_ROI[1] * image.size[1]),
                round(TITLE_ROI[2] * image.size[0]),
                round(TITLE_ROI[3] * image.size[1]),
            )
            crop = image.crop(bounds)
        out_dir = ROOT / "dataset" / "raw" / "control_panel" / "probe" / "formation_title"
        out_dir.mkdir(parents=True, exist_ok=True)
        crop_path = out_dir / f"{frame.parent.name}__{frame.stem}.png"
        crop.save(crop_path)
        tokens = ocr.recognize(crop_path).tokens
        text = " | ".join(f"{t.text}@{t.confidence:.2f}" for t in tokens)
        state = vision.observe(frame)
        print(
            f"\n{frame.relative_to(ROOT)}\n"
            f"    anchors  : {matched}\n"
            f"    observe  : page={state.page.value} beast={state.beast}\n"
            f"    title OCR: {text!r}"
        )
    print(f"\n(crop roi={width:.3f}x{height:.3f}; crops kept under "
          f"dataset/raw/control_panel/probe/formation_title/)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
