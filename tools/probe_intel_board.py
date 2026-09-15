"""Diagnose the intel board: what the production vision says vs what pins exist.

Read-only probe.  It exists because the production INTEL availability decision
and the pin detector disagreed in a way that mattered:

- `winter_agent_v2/ocr.py` decides AVAILABLE / NOT_AVAILABLE for the intel page
  from OCR text alone ("has 前往查看 -> AVAILABLE", "has 下次刷新 -> NOT_AVAILABLE").
- `winter_agent_v2/intel_pins.py` counts the teardrop mission pins, which is what
  the page actually is (the mission card only appears AFTER tapping a pin).

Both are printed side by side on the same live frame, plus a gate trace of the
blobs that were rejected by exactly one shape gate, so a false zero can be
attributed to a specific threshold instead of guessed at.

Usage: python tools/probe_intel_board.py [out_tag]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAMP = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
TAG = sys.argv[1] if len(sys.argv) > 1 else "intel_board"


def gate_trace(image_path: Path) -> list[dict]:
    """Blobs that pass every gate EXCEPT the aspect ratio, plus their geometry.

    Reuses the detector's own mask/component helpers so the trace cannot drift
    from the detector.  Anything reported here is a *candidate* false zero, not
    a detection: a human still has to look at the annotated frame.
    """
    import numpy as np
    from PIL import Image

    from winter_agent_v2.intel_pins import _components, _has_white_icon, _mask_for

    with Image.open(image_path) as image:
        rgb = np.asarray(image.convert("RGB"))

    out: list[dict] = []
    for name, mask in (
        ("PURPLE", _mask_for(rgb, 250, 330, 70, 50)),
        ("BLUE", _mask_for(rgb, 195, 250, 90, 110)),
        ("ORANGE", _mask_for(rgb, 10, 55, 90, 120)),
    ):
        for blob in _components(mask):
            area = len(blob["pixels"])
            if not (800 <= area <= 12000):
                continue
            xs = [p[0] for p in blob["pixels"]]
            ys = [p[1] for p in blob["pixels"]]
            w = max(xs) - min(xs) + 1
            h = max(ys) - min(ys) + 1
            ratio = round(w / max(h, 1), 3)
            fill = round(area / (w * h), 3)
            # MUST match the detector's live bounds in winter_agent_v2/intel_pins.py.
            # This was 0.65 here after the detector moved its floor to 0.5 for the
            # orange pin's glow, so the trace claimed a pin was "rejected only by
            # ratio" while production was in fact detecting it - i.e. the probe
            # manufactured a false zero on a full board.  Keep the two in sync.
            passes_ratio = 0.5 <= ratio <= 1.3
            passes_fill = fill >= 0.30
            passes_icon = _has_white_icon(rgb, xs, ys)
            passes_size = h >= 60 and w >= 40
            if passes_ratio:
                continue  # counted by the detector already
            out.append({
                "color": name,
                "area": area,
                "w": w,
                "h": h,
                "ratio": ratio,
                "fill": fill,
                "bbox": [min(xs), min(ys), max(xs), max(ys)],
                "rejected_only_by_ratio": bool(passes_size and passes_fill and passes_icon),
                "white_icon": passes_icon,
            })
    out.sort(key=lambda d: -d["area"])
    return out


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from winter_agent_v2.device import ADBDevice
    from winter_agent_v2.intel_pins import annotate, intel_pin_centers
    from winter_agent_v2.ocr import HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend
    from winter_agent_v2.vision import SemanticWorldVision

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    device = ADBDevice(Path(config["device"]["adb_path"]), config["device"]["serial"], production=True)
    device.resolve_connection()
    probe_dir = ROOT / "dataset/raw/control_panel/probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    shot = probe_dir / f"{TAG}_{STAMP}.png"
    device.screenshot(shot)
    print(f"frame: {shot.relative_to(ROOT)}", flush=True)

    template = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    hybrid = HybridVision(
        template,
        OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"])))),
    )
    state = hybrid.observe(shot)
    print("--- production vision ---")
    print(json.dumps({
        "page": state.page.value,
        "popup": state.popup,
        "intel": state.intel,
        "stamina": state.stamina,
    }, ensure_ascii=False, indent=2), flush=True)

    pins = intel_pin_centers(shot)
    print(f"--- pins detected: {len(pins)} ---")
    for index, pin in enumerate(pins):
        print(f"  {index}: {pin.color} ({pin.x},{pin.y}) area={pin.area}", flush=True)
    if pins:
        out = probe_dir / f"{TAG}_{STAMP}_annotated.png"
        annotate(shot, pins, out)
        print(f"annotated: {out.relative_to(ROOT)}", flush=True)

    print("--- blobs rejected by the aspect-ratio gate only ---")
    trace = gate_trace(shot)
    for entry in trace[:15]:
        print("  " + json.dumps(entry, ensure_ascii=False), flush=True)
    if not trace:
        print("  (none)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
