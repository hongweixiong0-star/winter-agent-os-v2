"""Reach the live Alliance page and report what entries it actually shows.

Why this exists (2026-09-15)
---------------------------
``CHECK_ALLIANCE_EVENT`` is the highest-leverage missing skill in the registry:
it is the only alternative for ``CHECK_BEAR_PHASE`` inside ``PARTICIPATE_BEAR``
and one of three capabilities in ``ALLIANCE_TIMED_EVENTS`` (which is
``ANY_OF``, so this single skill can complete that goal outright).

But ``knowledge/alliance/mechanism_cards.json`` records it as
``MISSING_NEEDS_LIVE_DESIGN`` -- never observed on the live client, no
template, no verifier -- and the design draft in
``winter_agent_v2/skill_factory.py`` (PRIORS) *assumes* a required semantic
``ALLIANCE_EVENT_ENTRY``.  That string does not exist in
``dataset/candidate/template_manifest.json``: the alliance templates cover
home / help / tech / gifts and nothing else.  A semantic cannot be designed
from a draft, so this probe collects the missing evidence instead of guessing:
it navigates to the page through the production stack, keeps the frames with
provenance, and dumps a full-screen OCR inventory of every label the page
really shows.

Read-only
---------
The only taps this probe performs are ``BACK`` (to leave whatever page the
previous run left open) and the already-live-verified ``BTN_OPEN_ALLIANCE``
entry.  It never taps a control on the alliance page itself and never touches
a paid / purchase control.

Usage
-----
    "E:/无尽冬日智能体/.venv/Scripts/python.exe" -u tools/probe_alliance_event_entry.py
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAMP = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
OUT_DIR = ROOT / "dataset" / "raw" / "control_panel" / "probe"
EVIDENCE = ROOT / "evidence" / f"alliance_event_entry_discovery_{STAMP}.json"

# Pages from which the alliance entry is reachable.  HOME is the current
# client's bottom-navigation host; MAP is the world map, which carries the same
# bottom navigation.  Anything else is left with BACK first.
NAV_HOSTS = {"HOME", "MAP"}

# Semantic whose ROI we want to inventory on the alliance frame, so the page
# layout can be described from evidence rather than from memory.
INTERESTING = ("ALLIANCE", "EVENT", "RALLY", "BEAR", "TIMER", "HELP", "TECH", "GIFT")


def build():
    sys.path.insert(0, str(ROOT))
    from winter_agent_v2.device import ADBDevice
    from winter_agent_v2.ocr import HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend
    from winter_agent_v2.vision import SemanticWorldVision

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    device = ADBDevice(Path(config["device"]["adb_path"]), config["device"]["serial"], production=True)
    device.resolve_connection()
    template = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))
    hybrid = HybridVision(template, ocr)
    return device, template, ocr, hybrid


def shoot(device, hybrid, tag: str):
    path = OUT_DIR / f"ally_discovery_{STAMP}_{tag}.png"
    device.screenshot(path)
    return hybrid.observe(path), path


def ocr_inventory(ocr, image_path: Path) -> list[dict]:
    """Every token on the frame, in reading order, with its pixel box."""
    result = ocr.recognize(image_path)
    rows = []
    for token in result.tokens:
        xs = [point[0] for point in token.box] or [0.0]
        ys = [point[1] for point in token.box] or [0.0]
        rows.append({
            "text": token.text,
            "confidence": round(float(token.confidence), 3),
            "x": round(min(xs), 1),
            "y": round(min(ys), 1),
            "w": round(max(xs) - min(xs), 1),
            "h": round(max(ys) - min(ys), 1),
        })
    rows.sort(key=lambda row: (round(row["y"] / 20), row["x"]))
    return rows


def semantic_inventory(template, image_path: Path) -> list[dict]:
    """Every manifest semantic that matches this frame, nearest first.

    Uses the production matcher with its production thresholds, so a hit here
    is the same hit the classifier would see.
    """
    manifest = json.loads((ROOT / "dataset/candidate/template_manifest.json").read_text(encoding="utf-8"))
    names: list[str] = []
    for record in manifest["records"]:
        semantic = record.get("semantic")
        if semantic and semantic not in names:
            names.append(semantic)
    hits = []
    for semantic in names:
        match = template.semantic.find(image_path, semantic)
        if match is not None:
            hits.append({"semantic": semantic, "distance": match.distance,
                         "roi": {k: round(v, 4) for k, v in match.roi.items()}})
    hits.sort(key=lambda row: (row["distance"], row["semantic"]))
    return hits


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    device, template, ocr, hybrid = build()
    report: dict = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "stamp": STAMP, "navigation": [], "alliance_frame": None}

    state, frame = shoot(device, hybrid, "00_start")
    print(f"start page={state.page.value} popup={state.popup}", flush=True)
    report["navigation"].append({"tag": "00_start", "page": state.page.value, "popup": state.popup,
                                 "frame": str(frame.relative_to(ROOT))})

    # Leave whatever the previous run left open.  BACK is the project's own
    # safe-navigation skill; three levels is enough for the popups observed so
    # far (a modal reward card over the world map).
    for level in range(1, 4):
        if state.page.value in NAV_HOSTS:
            break
        device.press_back()
        time.sleep(1.5)
        state, frame = shoot(device, hybrid, f"{level:02d}_after_back")
        print(f"back {level}: page={state.page.value} popup={state.popup}", flush=True)
        report["navigation"].append({"tag": f"{level:02d}_after_back", "page": state.page.value,
                                     "popup": state.popup, "frame": str(frame.relative_to(ROOT))})

    if state.page.value not in NAV_HOSTS:
        print(f"STOP: could not reach a navigation host, stuck on {state.page.value}", flush=True)
        EVIDENCE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return 2

    entry = template.semantic.find(frame, "BTN_OPEN_ALLIANCE")
    if entry is None or entry.center_norm is None:
        print("STOP: BTN_OPEN_ALLIANCE did not match on this frame", flush=True)
        report["alliance_entry_match"] = None
        EVIDENCE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return 3
    width, height = device.status().resolution
    tap = (round(entry.center_norm[0] * width), round(entry.center_norm[1] * height))
    print(f"BTN_OPEN_ALLIANCE d={entry.distance} -> tap {tap}", flush=True)
    report["alliance_entry_match"] = {"distance": entry.distance, "tap": list(tap)}
    device.tap(*tap)
    time.sleep(2.5)

    state, frame = shoot(device, hybrid, "10_alliance_page")
    print(f"alliance page={state.page.value} popup={state.popup} alliance={state.alliance}", flush=True)
    report["alliance_frame"] = {"frame": str(frame.relative_to(ROOT)), "page": state.page.value,
                                "popup": state.popup, "alliance": state.alliance}

    inventory = ocr_inventory(ocr, frame)
    report["alliance_ocr_inventory"] = inventory
    print("\n=== ALLIANCE PAGE OCR INVENTORY (reading order) ===", flush=True)
    for row in inventory:
        print(f"  y={row['y']:>6} x={row['x']:>6} {row['w']:>5}x{row['h']:<4} conf={row['confidence']:.3f}  {row['text']}", flush=True)

    hits = semantic_inventory(template, frame)
    report["alliance_semantic_hits"] = hits
    print("\n=== MANIFEST SEMANTICS THAT MATCH THIS FRAME ===", flush=True)
    for row in hits:
        mark = " *" if any(word in row["semantic"].upper() for word in INTERESTING) else ""
        print(f"  d={row['distance']:>3}  {row['semantic']}{mark}", flush=True)

    EVIDENCE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {EVIDENCE.relative_to(ROOT)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
