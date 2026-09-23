"""Can the client's own printed name locate a control the templates cannot hold?

The instrument for operator directive item 2 (2026-09-23): when a popup is on screen, prefer locating
its real control **from the current frame**.  The strongest form of that is the word the client
prints on the control, and the runtime already prefers it over any remembered coordinate -- "a
printed word or instruction is a statement about *this* frame, while the ledger below is a coordinate
measured on an earlier one" (``_resolve_semantic_target``).

Why it is needed here, measured: ``BTN_OPEN_POWER_DETAILS`` fails with
``SEMANTIC_TARGET_NOT_VERIFIED`` on 14 live frames, all on the ``POWER_OVERVIEW`` popup, and its two
``phash`` registrations are at y 636..685 and y 762..832 -- while the button is drawn at y ~692..765,
**in the gap between them** (d=36 and d=33 against a threshold of 8).  A registration cannot express a
control the panel moves; a word can.

What it measures, per frame:

* whether ``find_printed_words`` (exact match, the project's own reader) returns the word, and the
  box it read;
* the point that reader would hand the executor -- the box centre -- and whether that point is
  inside the control's drawn pill, drawn on a review crop so it can be checked rather than assumed;
* the **negatives**: the same words on other frames, so "the word is on this screen" is a measurement
  rather than a hope.  Operator item 4 is explicit that "the most likely-looking position" must not
  be treated as a control that exists.

Nothing is changed by running it.

Usage:
    python tools/probe_printed_control.py --words 实力详情 --semantic BTN_OPEN_POWER_DETAILS
    python tools/probe_printed_control.py --words 实力详情 --only failures
    python tools/probe_printed_control.py --words 实力详情 --only negatives
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EPISODES = ROOT / "learning/episodes.jsonl"
DEFAULT_OUT = ROOT / "dataset/truth_audit/power_details_entry_20260923"


def _rows() -> list[dict]:
    out: list[dict] = []
    with EPISODES.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _page(state: dict) -> str:
    value = (state or {}).get("page")
    if isinstance(value, dict):
        value = value.get("value")
    return str(value or "")


def _failures(semantic: str, target: str) -> list[dict]:
    """Distinct frames where this control was named and the resolver found nothing."""
    seen: set[str] = set()
    out: list[dict] = []
    for row in _rows():
        if str(row.get("skill")) != semantic:
            continue
        if str(row.get("failure_type")) != "SEMANTIC_TARGET_NOT_VERIFIED":
            continue
        if str((row.get("action") or {}).get("target")) != target:
            continue
        frame = str(row.get("before_screenshot") or "")
        if not frame or frame in seen or not Path(frame).is_file():
            continue
        seen.add(frame)
        state = row.get("state_before") or {}
        out.append({
            "frame": frame,
            "recorded_at": str(row.get("recorded_at")),
            "page": _page(state),
            "popup": str(state.get("popup") or ""),
            "kind": "failure",
        })
    out.sort(key=lambda row: row["recorded_at"])
    return out


def _negatives(limit: int) -> list[dict]:
    """One frame per (page, popup) other than the one the control is asked on."""
    seen: dict[tuple[str, str], dict] = {}
    for row in reversed(_rows()):
        state = row.get("state_before") or {}
        page = _page(state)
        popup = str(state.get("popup") or "")
        if not page or (page, popup) in seen:
            continue
        frame = str(row.get("before_screenshot") or "")
        if not frame or not Path(frame).is_file():
            continue
        seen[(page, popup)] = {
            "frame": frame,
            "recorded_at": str(row.get("recorded_at")),
            "page": page,
            "popup": popup,
            "kind": "negative",
        }
        if len(seen) >= limit:
            break
    return [seen[key] for key in sorted(seen)]


def _ocr():
    from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    return OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))


def _review(frame: Path, hit: dict | None, out: Path, label: str) -> None:
    from PIL import Image, ImageDraw

    image = Image.open(frame).convert("RGB")
    if hit is not None:
        box = hit.get("box_norm") or {}
        draw = ImageDraw.Draw(image)
        left = box.get("x_norm", 0.0) * image.width
        top = box.get("y_norm", 0.0) * image.height
        right = left + box.get("w_norm", 0.0) * image.width
        bottom = top + box.get("h_norm", 0.0) * image.height
        draw.rectangle((left, top, right, bottom), outline=(255, 60, 60), width=3)
        cx, cy = left + (right - left) / 2, top + (bottom - top) / 2
        draw.line((cx - 14, cy, cx + 14, cy), fill=(0, 200, 80), width=3)
        draw.line((cx, cy - 14, cx, cy + 14), fill=(0, 200, 80), width=3)
    image.resize((image.width * 3 // 4, image.height * 3 // 4)).save(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--words", required=True, help="comma-separated candidate words")
    parser.add_argument("--semantic", default="", help="the skill whose frames to take (failure mode)")
    parser.add_argument("--target", default="", help="the action target to select frames by")
    parser.add_argument("--only", choices=("failures", "negatives", "both"), default="both")
    parser.add_argument("--negatives", type=int, default=14, help="how many other screens to sample")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    from winter_agent_v2.ocr import find_printed_words

    words = tuple(word.strip() for word in args.words.split(",") if word.strip())
    ocr = _ocr()
    args.out.mkdir(parents=True, exist_ok=True)

    picks: list[dict] = []
    if args.only in ("failures", "both") and args.semantic:
        picks += _failures(args.semantic, args.target or "")
    if args.only in ("negatives", "both") and args.only == "negatives":
        picks += _negatives(args.negatives)
    elif args.only == "both":
        picks += _negatives(args.negatives)
    if not picks:
        print("no frame matched -- nothing to measure")
        return 0

    report: dict = {
        "words": list(words),
        "semantic": args.semantic,
        "target": args.target,
        "frames": [],
    }
    for index, pick in enumerate(picks):
        frame = Path(pick["frame"])
        hit = find_printed_words(frame, words, ocr)
        entry = {
            **pick,
            "read": None if hit is None else {
                "word": str(hit.get("word")),
                "confidence": hit.get("confidence"),
                "box_norm": hit.get("box_norm"),
                "center_px": [round(hit["center_norm"][0] * 720), round(hit["center_norm"][1] * 1280)],
            },
        }
        crop = args.out / f"read_{pick['kind']}_{index:02d}.png"
        _review(frame, hit, crop, pick["kind"])
        entry["review_crop"] = str(crop)
        report["frames"].append(entry)
        where = "—" if hit is None else (f"{hit['center_norm'][0]:.4f},{hit['center_norm'][1]:.4f} "
                                        f"conf {hit.get('confidence')}")
        print(f"[{pick['kind']:<8}] {pick['recorded_at'][11:19]} {pick['page']}|{pick['popup']:<22} "
              f"-> {where}")

    failures = [row for row in report["frames"] if row["kind"] == "failure"]
    negatives = [row for row in report["frames"] if row["kind"] == "negative"]
    report["summary"] = {
        "failure_frames": len(failures),
        "failure_frames_where_the_word_is_read": sum(1 for row in failures if row["read"]),
        "negative_screens": len(negatives),
        "negative_screens_where_the_word_is_read": sum(1 for row in negatives if row["read"]),
        "negative_hits": dict(Counter(
            f"{row['page']}|{row['popup']}" for row in negatives if row["read"]
        )),
    }
    (args.out / "printed.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    print()
    print("summary:", json.dumps(report["summary"], ensure_ascii=False))
    print("wrote", args.out / "printed.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
