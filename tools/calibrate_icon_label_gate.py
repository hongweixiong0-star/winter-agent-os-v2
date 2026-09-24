"""Measure the label→control gate against a real corpus of positives and negatives.

This is the positive/negative validation the directive asks for, and it is a *measurement*, not a
formality: the previous gate (band saturation / edge strength) was accepted here only after it had
failed.  Run against ``dataset/truth_audit/icon_label_controls/samples.json`` -- frames mined from
production, with the label boxes this project's own OCR measured on them -- it asks one question:
for every printed label on a real screen, does the gate accept exactly the ones that carry a control
above them?

    positives  the HUD activity entries the operator confirmed (登录好礼 / 常规活动 / 超值活动 / 明月的盛典)
    negatives  every other printed word on the same frames -- town names, resource counts, captions

Read-only.  Prints, per label: how many were seen, how many accepted, and for the refusals the
gate's own reason, so a threshold that is merely "close" is visible as a distribution rather than
hidden behind a pass rate.

Usage:
    python tools/calibrate_icon_label_gate.py
    python tools/calibrate_icon_label_gate.py --samples <json> --show-refusals
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_SAMPLES = ROOT / "dataset/truth_audit/icon_label_controls/samples.json"

#: The labels the operator confirmed carry a control directly above them.  Kept here as the
#: *ground truth of the measurement*; production reads ``knowledge/ui/icon_label_controls.json``.
POSITIVE_LABELS = ("登录好礼", "常规活动", "超值活动", "明月的盛典")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES)
    parser.add_argument("--show-refusals", action="store_true")
    parser.add_argument("--limit-per-frame", type=int, default=0)
    args = parser.parse_args()

    from PIL import Image

    from winter_agent_v2 import ui_collection

    payload = json.loads(args.samples.read_text(encoding="utf-8"))
    hits = payload.get("hits") or []
    if not hits:
        print(f"no hits in {args.samples}; run tools/probe_icon_label_controls.py --all first")
        return 2

    by_frame: dict[str, list[dict]] = defaultdict(list)
    for row in hits:
        by_frame[str(row["frame"])].append(row)
    print(f"corpus: {len(hits)} label(s) over {len(by_frame)} frame(s)")

    accepted: Counter[str] = Counter()
    seen: Counter[str] = Counter()
    refusals: dict[str, Counter[str]] = defaultdict(Counter)
    accepted_negatives: Counter[str] = Counter()

    for frame, rows in by_frame.items():
        if not Path(frame).is_file():
            continue
        try:
            with Image.open(frame) as handle:
                image = handle.convert("RGB")
        except (OSError, ValueError):
            continue
        try:
            for row in rows:
                text = str(row["text"])
                seen[text] += 1
                measured = ui_collection.control_block_above_label(
                    frame, row["label_box"], label=text, image=image
                )
                if measured is not None:
                    accepted[text] += 1
                    if text not in POSITIVE_LABELS:
                        accepted_negatives[text] += 1
                    continue
                # Re-run to capture the reason without a second image open: the gate reports it in
                # ``detail`` only on the way out, so ask it once more with the reason preserved.
                reason = _refusal_reason(ui_collection, image, frame, row)
                refusals[text][reason] += 1
        finally:
            image.close()

    print()
    print(f"{'label':18} {'seen':>6} {'accepted':>9} {'rate':>8}  verdict")
    pos_seen = pos_ok = 0
    neg_seen = neg_ok = 0
    for text, count in sorted(seen.items(), key=lambda item: -item[1]):
        ok = accepted[text]
        rate = ok / max(count, 1)
        positive = text in POSITIVE_LABELS
        if positive:
            pos_seen += count
            pos_ok += ok
        else:
            neg_seen += count
            neg_ok += ok
        verdict = ""
        if positive:
            verdict = "should be accepted" if rate >= 0.8 else "POSITIVE MISSED"
        elif ok:
            verdict = "false positive" if rate > 0.02 else "rare false positive"
        print(f"{text[:18]:18} {count:6} {ok:9} {rate:8.2%}  {verdict}")

    print()
    print(f"positives: {pos_ok}/{pos_seen} accepted = {pos_ok / max(pos_seen, 1):.2%}  (want high)")
    print(f"negatives: {neg_ok}/{neg_seen} accepted = {neg_ok / max(neg_seen, 1):.2%}  (want low)")
    if accepted_negatives:
        print()
        print("negatives the gate accepted (each one is a would-be button that is not one):")
        for text, count in accepted_negatives.most_common(15):
            print(f"   {text[:24]:24} {count}")
    if args.show_refusals:
        print()
        print("refusal reasons on run-together rows:")
        for text, counter in sorted(refusals.items()):
            if text in POSITIVE_LABELS:
                print(f"   {text[:24]:24} {dict(counter)}")
    return 0


def _refusal_reason(ui_collection, image, frame: str, row: dict) -> str:
    """The gate's own reason, captured without changing the gate's contract.

    The refusal list lives in ``detail`` and is only returned alongside a box, so this re-derives
    the band's measurements the same way the gate does and reports which check would have failed.
    """
    from winter_agent_v2.ocr import read_frame_size

    size = read_frame_size(frame)
    if not size:
        return "UNREADABLE"
    rect = ui_collection.band_above_label(row["label_box"], size)
    if rect is None:
        return "NO_BAND"
    found = ui_collection._block_in_band(image, rect)
    if found is None:
        return "NO_BLOCK"
    _box, detail = found
    label_box = row["label_box"]
    frame_w, frame_h = int(size[0]), int(size[1])
    label_w = float(label_box["w_norm"]) * frame_w
    label_h = float(label_box["h_norm"]) * frame_h
    label_cx = (float(label_box["x_norm"]) + float(label_box["w_norm"]) / 2) * frame_w
    label_top = float(label_box["y_norm"]) * frame_h
    block_w = _box["w_norm"] * frame_w
    block_h = _box["h_norm"] * frame_h
    block_cx = (_box["x_norm"] + _box["w_norm"] / 2) * frame_w
    block_bottom = (_box["y_norm"] + _box["h_norm"]) * frame_h
    if min(block_w, block_h) < ui_collection.MIN_ELEMENT_SIDE_PX:
        return "BLOCK_TOO_SMALL"
    if detail["block_fill"] < ui_collection.CONTROL_MIN_BLOCK_FILL:
        return "BLOCK_NOT_SOLID"
    ratio = block_w / max(label_w, 1e-6)
    if ratio < ui_collection.CONTROL_MIN_WIDTH_RATIO:
        return "BLOCK_NARROWER_THAN_A_CONTROL"
    if ratio > ui_collection.CONTROL_MAX_WIDTH_RATIO:
        return "BLOCK_WIDER_THAN_A_CONTROL"
    if abs(block_cx - label_cx) / max(label_w, 1e-6) > ui_collection.CONTROL_MAX_CENTER_OFFSET:
        return "BLOCK_NOT_CENTRED_ON_LABEL"
    if max(0.0, label_top - block_bottom) / max(label_h, 1e-6) > ui_collection.CONTROL_MAX_GAP_RATIO:
        return "BLOCK_NOT_ADJACENT_TO_LABEL"
    if _box["w_norm"] * _box["h_norm"] > ui_collection.CONTROL_BOX_MAX_AREA_NORM:
        return "BLOCK_TOO_LARGE_TO_BE_A_CONTROL"
    return "ACCEPTED"


if __name__ == "__main__":
    raise SystemExit(main())
