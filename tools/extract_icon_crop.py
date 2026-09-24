"""Extract the icon above a label from a real frame, for registration as a template crop.

One-time extraction, with the window chosen from the label's own measured box and the result
written next to the frame it came from so a person can look at it before it is registered.  The
window is a search window, never a click target: recognition later runs the matcher over the
current frame and clicks where the match *is*.

Usage:
    python tools/extract_icon_crop.py --frame <png> --label 登录好礼 --out <dir>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--out", default=str(ROOT / "knowledge/ui/icon_templates"))
    parser.add_argument("--config", default=str(ROOT / "config/v2.json"))
    args = parser.parse_args()

    from winter_agent_v2 import ui_collection
    from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend, read_frame_size

    frame = Path(args.frame)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))
    size = read_frame_size(frame)
    if not size:
        print("frame unreadable")
        return 2
    width, height = int(size[0]), int(size[1])

    target = None
    for region in ui_collection.grounding_regions(frame, ocr):
        if str(region.get("text") or "").strip() == args.label:
            target = region
            break
    if target is None:
        print(f"label {args.label!r} not found on this frame")
        return 3
    label_box = dict(target["box_norm"])
    print(f"label {args.label!r} at {label_box}")

    with Image.open(frame) as handle:
        image = handle.convert("RGB")
    rect = ui_collection.band_above_label(label_box, (width, height))
    found = ui_collection._block_in_band(
        image,
        rect,
        label_row=(
            int(round(label_box["y_norm"] * height)),
            int(round((label_box["y_norm"] + label_box["h_norm"]) * height)),
        ),
    )
    if found is None:
        print("the gate found no block; widen the window by hand and re-run")
        return 4
    box_norm, detail = found
    print("block:", box_norm, "checks:", json.dumps(detail.get("checks") or {}, ensure_ascii=False))

    pad = 2
    left = max(0, int(round(box_norm["x_norm"] * width)) - pad)
    top = max(0, int(round(box_norm["y_norm"] * height)) - pad)
    right = min(width, int(round((box_norm["x_norm"] + box_norm["w_norm"]) * width)) + pad)
    bottom = min(height, int(round((box_norm["y_norm"] + box_norm["h_norm"]) * height)) + pad)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    crop = image.crop((left, top, right, bottom))
    name = f"{args.label}.png"
    crop.save(out_dir / name)
    print(f"wrote {out_dir / name} {crop.size} from rect {(left, top, right, bottom)}")
    print(f"provenance: {frame.name} (this crop must be looked at before it is registered)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
