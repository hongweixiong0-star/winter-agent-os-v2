"""Bounded probe: walk the 战力 route from HOME, one measured tap per hop.

Why this exists (2026-09-17).  `TRAIN` and `BUILD` are the two capabilities the
operator has asked for, and both are blocked on the same thing: the world state
never carries `training` / `building` / `research`, because every template that
would populate them was cropped from 2026-09-08 frames whose city camera and
account differ from today's client.  Measured on today's live HOME frame
(`dataset/raw/control_panel/probe/live_page_20260916_232514.png`):

    BTN_OPEN_POWER_OVERVIEW            MISS   (crop includes the power NUMBER)
    TARGET_INFANTRY_CAMP_HIGHLIGHTED   MISS
    BTN_OPEN_TRAINING_FROM_CAMP        MISS
    PAGE_TRAINING_INFANTRY             MISS
    BTN_START_TRAINING                 MISS

The city view today is also zoomed in far enough that the infantry camp is not on
screen at all (checked by eye on 2x crops of the lower half), so the camp cannot be
tapped directly -- the documented route is the only one available:

    HOME --tap power--> POPUP_POWER_OVERVIEW --实力详情--> POPUP_POWER_DETAILS
         --提升--> HOME(infantry camp focused) --训练--> TRAINING

This probe walks that route.  It is deliberately *not* a one-tap probe like
`probe_daily_chapter_tab.py`, because the intermediate coordinates do not exist yet:
each hop's coordinate is measured from the frame the previous hop produced, and every
coordinate is passed in on the command line so that no tap is ever blind.  The frames
it writes are the evidence the coordinates were read from.

Self-limits
-----------
* aborts unless the FIRST observed page is HOME (never starts from a popup, an
  event panel, or a page it does not recognise);
* taps only the coordinates given on the command line, in order, once each;
* hard step cap (``MAX_TAPS``);
* never taps a surface it has not been told to tap: the gem/instant-finish and any
  购买/礼包 control are only ever what the operator *did not* pass in;
* prints every OCR token of every frame so a following hop can be measured from
  evidence instead of guessed;
* ``--leave`` presses BACK once at the end and re-reads, so the client is returned
  to a known page and the return itself is part of the record.

Usage
-----
    python tools/probe_power_route.py --tap 115,72                 # hop 1
    python tools/probe_power_route.py --tap 115,72 --tap 400,700   # hop 1 + 2
    python tools/probe_power_route.py --tap 115,72 --leave
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "dataset" / "truth_audit" / "power_route_20260917"
MAX_TAPS = 6


def parse_point(raw: str) -> tuple[int, int]:
    try:
        x, y = raw.split(",")
        return int(x), int(y)
    except Exception as exc:  # pragma: no cover - argument validation only
        raise argparse.ArgumentTypeError(
            f"--tap wants X,Y in frame pixels, got {raw!r}") from exc


def build():
    from winter_agent_v2.device import ADBDevice
    from winter_agent_v2.ocr import HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend
    from winter_agent_v2.vision import SemanticWorldVision

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    device = ADBDevice(Path(config["device"]["adb_path"]), config["device"]["serial"],
                       production=True)
    device.resolve_connection()
    template = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))
    return device, HybridVision(template, ocr), template, ocr


def tokens_of(ocr, frame: Path, min_conf: float = 0.6):
    out = []
    try:
        result = ocr.recognize(frame)
    except Exception as exc:  # pragma: no cover - diagnostic only
        print(f"   ocr failed: {type(exc).__name__}: {exc}")
        return out
    for token in result.tokens:
        if not token.box or token.confidence < min_conf:
            continue
        xs = [p[0] for p in token.box]
        ys = [p[1] for p in token.box]
        out.append({
            "text": token.text,
            "conf": round(token.confidence, 3),
            "px": [round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))],
        })
    return out


def describe(tag: str, frame: Path, hybrid, ocr, dump_tokens: bool = True) -> dict:
    state = hybrid.observe(frame)
    print(f"{tag:<12} page={state.page.value:<9} conf={state.confidence:.2f} "
          f"popup={state.popup} training={json.dumps(state.training, ensure_ascii=False)} "
          f"building={json.dumps(state.building, ensure_ascii=False)}")
    tokens = tokens_of(ocr, frame) if dump_tokens else []
    if dump_tokens:
        keys = ("详情", "升级", "训练", "提升", "实力", "部队", "战", "矛兵", "射手",
                "盾兵", "攻击", "防御", "生命", "返回", "关闭", "购买", "礼包", "充值")
        shown = [t for t in tokens if any(k in t["text"] for k in keys)]
        print(f"             OCR tokens={len(tokens)}, of-interest={len(shown)}")
        for t in shown:
            print(f"               {t['text']!r:<16} conf={t['conf']} px={t['px']}")
    return {"frame": str(frame), "page": state.page.value, "popup": state.popup,
            "training": state.training, "building": state.building,
            "tokens": tokens}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tap", action="append", type=parse_point, default=[],
                        help="frame-pixel coordinate to tap, in order; repeatable")
    parser.add_argument("--leave", action="store_true",
                        help="press BACK once at the end and re-read")
    parser.add_argument("--tag", default="power_route")
    parser.add_argument("--allow-page", action="append", default=[],
                        help="page name the probe may START on, in addition to HOME. "
                             "Only pass a page whose frame the operator has already looked at "
                             "-- the point of the guard is that nothing is tapped from a page "
                             "nobody has identified.  Recorded in the probe JSON.")
    args = parser.parse_args()

    if len(args.tap) > MAX_TAPS:
        print(f"ABORT: {len(args.tap)} taps exceeds the hard cap of {MAX_TAPS}")
        return 1

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    device, hybrid, template, ocr = build()
    from winter_agent_v2.models import Page

    allowed = {"HOME", *args.allow_page}
    steps = []
    frame = OUT_DIR / f"{args.tag}_{stamp}_00_before.png"
    device.screenshot(frame)
    first = describe("before", frame, hybrid, ocr)
    steps.append(first)
    if first["page"] not in allowed:
        print(f"\nABORT: page is {first['page']}, expected one of {sorted(allowed)} "
              f"(this probe never starts from an unrecognised page).")
        return 1

    for index, (x, y) in enumerate(args.tap, start=1):
        print(f"\n-- tap {index}: ({x},{y})")
        device.tap(x, y)
        time.sleep(2.0)
        frame = OUT_DIR / f"{args.tag}_{stamp}_{index:02d}_after_tap_{x}_{y}.png"
        device.screenshot(frame)
        steps.append(describe(f"after#{index}", frame, hybrid, ocr))

    left = None
    if args.leave:
        print("\n-- BACK")
        device.press_back()
        time.sleep(2.0)
        frame = OUT_DIR / f"{args.tag}_{stamp}_99_after_back.png"
        device.screenshot(frame)
        left = describe("after BACK", frame, hybrid, ocr)

    (OUT_DIR / f"probe_{args.tag}_{stamp}.json").write_text(json.dumps({
        "probe": args.tag,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "self_limits": [
            "aborts unless the first observed page is HOME (or an explicitly allowed page)",
            "taps only the coordinates passed on the command line, once each, in order",
            f"hard cap of {MAX_TAPS} taps",
            "dumps every OCR token so the next hop is measured, not guessed",
        ],
        "allowed_start_pages": sorted(allowed),
        "taps_px": [list(p) for p in args.tap],
        "steps": steps,
        "after_back": left,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwritten -> {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
