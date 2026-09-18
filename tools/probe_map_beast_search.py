"""Bounded probe: does the world map's own search fly the camera to a beast?

Why this exists (2026-09-18)
----------------------------
Escalation ``SPEND_STAMINA_ON_BEAST|NO_GOAL_PROGRESS|SCAN_MAP_FOR_BEAST`` (second
shape).  ``AVOID_STAMINA_WASTE`` is metered by ``stamina - 30``, so the only thing
that advances it is actually spending stamina on a beast, and the route never
reaches one: the sole "target is not visible" hop is a fixed three-pan sweep
(``winter_agent_v2/brain.py:857``) that stops instead of searching.

A previous round measured that the pan really does move the viewport
(``tools/probe_beast_scan_pan.py``, ``dataset/truth_audit/beast_scan_pan_20260918/``)
and recorded that the client's own beast search was never wired.  This probe is
the missing live half: it walks that search on today's client and keeps the frames.

Bounded and honest
------------------
* starts only from an observed MAP page (aborts otherwise);
* taps only the coordinates given on the command line, in order, once each;
* hard cap of ``MAX_TAPS``;
* presses BACK between hops only when ``--back-between`` is passed;
* prints every OCR token of every frame with its pixel centre, so the next hop is
  measured from evidence rather than guessed;
* writes every frame it read under ``dataset/truth_audit/map_beast_search_20260918/key/``.

Usage
-----
    "E:/dongri-mumu-bot/.venv/Scripts/python.exe" -u tools/probe_map_beast_search.py
    "E:/dongri-mumu-bot/.venv/Scripts/python.exe" -u tools/probe_map_beast_search.py --tap 44,900 --tag magnifier
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

OUT_DIR = ROOT / "dataset" / "truth_audit" / "map_beast_search_20260918" / "key"
MAX_TAPS = 6


def parse_point(raw: str) -> tuple[int, int]:
    x, y = raw.split(",")
    return int(x), int(y)


def build():
    from winter_agent_v2.device import ADBDevice
    from winter_agent_v2.ocr import HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend
    from winter_agent_v2.vision import SemanticWorldVision

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    device = ADBDevice(Path(config["device"]["adb_path"]), config["device"]["serial"],
                       production=True)
    device.resolve_connection()
    template = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    backend = RapidOCRBackend(Path(config["ocr"]["module_path"]))
    ocr = OCRService(ResilientOCRBackend(backend))
    return device, HybridVision(template, ocr), backend


def dump_tokens(backend, frame: Path, label: str) -> list[dict]:
    from PIL import Image

    image = Image.open(frame)
    width, height = image.size
    tokens = backend.recognize(image)
    rows = []
    for token in tokens:
        xs = [p[0] for p in token.box] or [0.0]
        ys = [p[1] for p in token.box] or [0.0]
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        rows.append({"text": token.text, "conf": round(token.confidence, 3),
                     "cx": round(cx, 1), "cy": round(cy, 1),
                     "x_norm": round(cx / width, 4), "y_norm": round(cy / height, 4)})
    print(f"-- OCR {label} ({frame.name}) {width}x{height}, {len(rows)} tokens")
    for row in rows:
        print(f"   ({row['cx']:>6.1f},{row['cy']:>6.1f}) n=({row['x_norm']},{row['y_norm']}) "
              f"c={row['conf']} {row['text']}")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tap", action="append", type=parse_point, default=[])
    parser.add_argument("--tag", default="search")
    parser.add_argument("--settle", type=float, default=2.5)
    parser.add_argument("--back-between", action="store_true")
    args = parser.parse_args()
    if len(args.tap) > MAX_TAPS:
        print(f"refusing: {len(args.tap)} taps > MAX_TAPS={MAX_TAPS}")
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    device, hybrid, backend = build()
    status = device.status()
    print(f"device resolution: {status.resolution} focus={status.foreground_package}")

    record: dict = {"recorded_at": datetime.now(timezone.utc).isoformat(),
                    "resolution": status.resolution, "hops": [], "key": []}

    def shoot(label: str) -> tuple[Path, object]:
        frame = OUT_DIR / f"{args.tag}_{stamp}_{label}.png"
        device.screenshot(frame)
        state = hybrid.observe(frame)
        print(f"== {label}: page={state.page.value} conf={state.confidence:.2f} "
              f"popup={state.popup} stamina={state.stamina.get('current') if state.stamina else None}")
        record["key"].append(frame.name)
        return frame, state

    frame, state = shoot("000_before")
    if state.page.value != "MAP":
        print(f"NOT_ON_MAP ({state.page.value}); aborting without tapping")
        (OUT_DIR / f"{args.tag}_{stamp}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        return 3
    record["hops"].append({"hop": 0, "frame": frame.name, "page": state.page.value,
                           "tokens": dump_tokens(backend, frame, "before")})

    for index, (x, y) in enumerate(args.tap, start=1):
        print(f"--> tap ({x},{y})")
        device.tap(x, y)
        time.sleep(args.settle)
        frame, state = shoot(f"{index:03d}_after_{x}_{y}")
        record["hops"].append({"hop": index, "tap": [x, y], "frame": frame.name,
                               "page": state.page.value, "popup": state.popup,
                               "tokens": dump_tokens(backend, frame, f"after tap {x},{y}")})
        if args.back_between:
            device.press_back()
            time.sleep(args.settle)

    (OUT_DIR / f"{args.tag}_{stamp}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {OUT_DIR / (args.tag + '_' + stamp + '.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
