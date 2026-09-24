"""Mine real frames for icon+label controls, and measure the gate that separates them.

The break this exists to fix (measured 2026-09-25): on the city HUD the client draws an activity
icon with its name printed **underneath**.  The element table was built from OCR text boxes, so the
label box became the element and the tap landed on the text instead of on the control above it --
`SEMANTIC_TARGET_IS_A_LABEL_NOT_A_CONTROL`.  The model chose the right semantic; the geometry was
wrong.

This tool answers the two questions that have to be answered with measurements rather than taste:

1. **Where are the icons?**  For a label box the client printed, the band directly above it is
   measured.  A real control shows a compact, vivid, hard-edged block there; map terrain, town names
   and other plain text do not.
2. **What threshold?**  The gate is not invented here: `--report` prints the measured separation
   between the positives (labels the operator confirmed have an icon above them, e.g. 登录好礼) and
   the negatives (ordinary printed text on the same frames, e.g. town names), and the default is the
   value the measurement supports.

Why a *paired, frame-internal* comparison rather than an absolute threshold: the earlier note in
``ui_collection`` records that a whole-frame blob test reported "elements" at 138 of 289 grid points
because the volcanic artwork behind a panel is as textured as the icons.  That test asked "is this
region busy"; the right question is "is this region busy **in a way this frame's own text labels are
not**" -- so the terms compared are the band above a label, the label itself, and the label's own
flat surround, all from the same frame and the same lighting.

Read-only unless ``--extract`` is given, which writes crops for registration.

Usage:
    python tools/probe_icon_label_controls.py --frames 120 --report
    python tools/probe_icon_label_controls.py --frame <png> --report
    python tools/probe_icon_label_controls.py --frame <png> --label 登录好礼 --extract
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "dataset/truth_audit/icon_label_controls"

#: Labels the operator has confirmed carry a control above them.  Kept as a *sample list for
#: measurement*, never as the mechanism: the shipped gate does not consult this file.
POSITIVE_LABELS = ("登录好礼", "常规活动", "玉貌流光礼包", "超值活动", "明月的盛典")

#: The band is this many label-heights tall and this much wider than the label.  Both are bounded
#: so the window can only reach the control's own row, not an arbitrary part of the screen.
BAND_HEIGHT_RATIO = 0.85
BAND_WIDTH_PAD_RATIO = 0.18
BAND_MAX_HEIGHT_NORM = 0.075
BAND_MIN_SIDE_PX = 14


def _gray(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("L"), dtype=np.float32)


#: The four structure terms and the band geometry live in ``ui_collection`` and are imported here
#: rather than re-implemented: a calibration run and a production decision must not be able to
#: disagree about what "this band looks like artwork" means.
from winter_agent_v2.ui_collection import (  # noqa: E402
    band_above_label as band_above,
    region_structure as structure,
)


def _ocr(config_path: Path):
    from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend

    config = json.loads(config_path.read_text(encoding="utf-8"))
    return OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))


def _text_boxes(frame_path: Path, ocr) -> list[dict]:
    from winter_agent_v2 import ui_collection

    return ui_collection.grounding_regions(frame_path, ocr)


def measure_one(frame_path: Path, ocr, *, label: str | None = None) -> dict:
    """Every printed label on this frame, with the structure of the band above it."""
    from winter_agent_v2.ocr import read_frame_size

    size = read_frame_size(frame_path)
    if not size:
        return {"frame": str(frame_path), "error": "UNREADABLE"}
    with Image.open(frame_path) as image:
        image = image.convert("RGB")
    rows: list[dict] = []
    for region in _text_boxes(frame_path, ocr):
        text = str(region.get("text") or "").strip()
        if not text or (label and text != label):
            continue
        box = dict(region.get("box_norm") or {})
        rect = band_above(box, size)
        if rect is None:
            continue
        left, top, right, bottom = rect
        surround_rect = (left, bottom, right, min(size[1], bottom + (bottom - top)))
        rows.append({
            "text": text,
            "kind": "POSITIVE" if text in POSITIVE_LABELS else "OTHER",
            "label_box": box,
            "band_px": [left, top, right, bottom],
            "band": structure(image, rect),
            "surround": structure(image, surround_rect),
            "band_png": None,
        })
    return {"frame": str(frame_path), "size": list(size), "rows": rows}


def _recent_frames(limit: int) -> list[Path]:
    root = ROOT / "dataset/raw"
    found: list[tuple[float, Path]] = []
    for path in root.rglob("*.png"):
        try:
            found.append((path.stat().st_mtime, path))
        except OSError:
            continue
    found.sort(reverse=True)
    return [path for _mtime, path in found[:limit]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame", action="append", default=[], help="a specific frame (repeatable)")
    parser.add_argument("--frames", type=int, default=0, help="sample this many newest frames")
    parser.add_argument("--label", default="", help="only this printed word")
    parser.add_argument("--labels", default="", help="comma-separated words to measure")
    parser.add_argument("--all", action="store_true",
                        help="measure every printed word (gives negatives as well as positives)")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--extract", action="store_true", help="write crops for registration")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--config", default=str(ROOT / "config/v2.json"))
    args = parser.parse_args()

    frames = [Path(p) for p in args.frame]
    if args.frames:
        frames.extend(_recent_frames(args.frames))
    if not frames:
        print("no frames given; use --frame or --frames")
        return 2
    print(f"frames to measure: {len(frames)}")

    ocr = _ocr(Path(args.config))
    wanted = [w.strip() for w in args.labels.split(",") if w.strip()]
    if args.label:
        wanted.append(args.label)

    hits: list[dict] = []
    scanned = 0
    for frame in frames:
        scanned += 1
        if scanned % 25 == 0:
            print(f"  ... {scanned}/{len(frames)} scanned, {len(hits)} hit(s)", flush=True)
        try:
            result = measure_one(frame, ocr)
        except Exception as exc:  # noqa: BLE001 - one bad frame must not stop the scan
            continue
        for row in result.get("rows") or []:
            if wanted and row["text"] not in wanted:
                continue
            if not wanted and not args.all and row["text"] not in POSITIVE_LABELS:
                continue
            row["frame"] = result["frame"]
            row["size"] = result["size"]
            hits.append(row)
    print(f"scanned {scanned} frame(s); {len(hits)} label hit(s)")

    if args.extract and hits:
        args.out.mkdir(parents=True, exist_ok=True)
        for index, row in enumerate(hits):
            with Image.open(row["frame"]) as image:
                left, top, right, bottom = row["band_px"]
                crop = image.convert("RGB").crop((left, top, right, bottom))
            name = f"{row['text']}_{index:03d}.png"
            crop.save(args.out / name)
            row["band_png"] = str(args.out / name)
        print(f"wrote {len(hits)} crop(s) to {args.out}")

    if args.report:
        _print_report(hits, wanted)

    args.out.mkdir(parents=True, exist_ok=True)
    payload = {"measured_at_frames": scanned, "wanted": wanted, "hits": hits}
    (args.out / "samples.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"wrote {args.out / 'samples.json'}")
    return 0


def _sep(values: list[float]) -> tuple[float, float, float]:
    import statistics

    if not values:
        return (0.0, 0.0, 0.0)
    return (
        round(min(values), 4),
        round(statistics.median(values), 4),
        round(max(values), 4),
    )


def _print_report(hits: list[dict], wanted: list[str]) -> None:
    if not hits:
        print("no hits to report")
        return
    print()
    print(f"{'text':18} {'kind':10} {'edge_ratio':>10} {'sat_delta':>10} {'band.edge':>10} "
          f"{'surr.edge':>10} {'band.sat':>9} {'band.vivid':>11}")
    for row in hits[:60]:
        band, surround = row["band"], row["surround"]
        edge_ratio = band["edge"] / max(surround["edge"], 1e-6)
        print(f"{row['text'][:18]:18} {row.get('kind', '')[:10]:10} {edge_ratio:10.2f} "
              f"{band['sat'] - surround['sat']:10.4f} {band['edge']:10.4f} "
              f"{surround['edge']:10.4f} {band['sat']:9.4f} {band['vivid']:11.4f}")
    if len(hits) > 60:
        print(f"  ... {len(hits) - 60} more row(s) in samples.json")

    positives = [row for row in hits if row["text"] in POSITIVE_LABELS]
    negatives = [row for row in hits if row["text"] not in POSITIVE_LABELS]
    print()
    for name, rows in (("POSITIVE (control above)", positives), ("NEGATIVE (plain text)", negatives)):
        if not rows:
            print(f"{name}: none measured")
            continue
        ratios = [row["band"]["edge"] / max(row["surround"]["edge"], 1e-6) for row in rows]
        deltas = [row["band"]["sat"] - row["surround"]["sat"] for row in rows]
        print(f"{name}: n={len(rows)}")
        print(f"   edge_ratio  min/median/max = {_sep(ratios)}")
        print(f"   sat_delta   min/median/max = {_sep(deltas)}")
    if positives and negatives:
        p_ratio = min(row["band"]["edge"] / max(row["surround"]["edge"], 1e-6) for row in positives)
        n_ratio = max(row["band"]["edge"] / max(row["surround"]["edge"], 1e-6) for row in negatives)
        p_sat = min(row["band"]["sat"] - row["surround"]["sat"] for row in positives)
        n_sat = max(row["band"]["sat"] - row["surround"]["sat"] for row in negatives)
        print()
        print(f"separation on edge_ratio : positive_min={p_ratio:.2f}  negative_max={n_ratio:.2f}  "
              f"{'SEPARABLE' if p_ratio > n_ratio else 'OVERLAP'}")
        print(f"separation on sat_delta  : positive_min={p_sat:.4f}  negative_max={n_sat:.4f}  "
              f"{'SEPARABLE' if p_sat > n_sat else 'OVERLAP'}")
        print(f"a threshold on both would sit near edge_ratio="
              f"{(p_ratio + n_ratio) / 2:.2f}, sat_delta={(p_sat + n_sat) / 2:.4f}")


if __name__ == "__main__":
    raise SystemExit(main())
