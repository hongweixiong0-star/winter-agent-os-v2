"""Read the claimed-state panel frame with the production vision stack.

Purpose: find what the client draws AFTER a day has been claimed, so a reader can
distinguish CLAIMED from FREE_CLAIMABLE without tapping anything.  Nothing here
touches the device.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend  # noqa: E402
from winter_agent_v2.vision import SemanticROIVision, SemanticWorldVision  # noqa: E402
from winter_agent_v2 import ui_collection  # noqa: E402

KEY = PROJECT / "dataset/truth_audit/login_gift_claim_20260924/key"


def main() -> int:
    cfg = json.loads((PROJECT / "config/v2.json").read_text(encoding="utf-8"))
    ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(cfg["ocr"]["module_path"]))))
    world_vision = SemanticWorldVision(PROJECT / "dataset/candidate/template_manifest.json")
    roi_vision = SemanticROIVision(PROJECT / "dataset/candidate/template_manifest.json")
    out: dict[str, object] = {}
    for name, path in (
        ("claimed_final", KEY / "04_claim_final.png"),
        ("before", KEY / "01_panel_free_tab_before.png"),
    ):
        world = world_vision.observe(path)
        rows: list[dict] = []
        try:
            regions = ui_collection.grounding_regions(path, ocr)
            rows = [
                {"text": r.get("text"),
                 "box": [round(float(r["box_norm"][k]), 4) for k in
                         ("x_norm", "y_norm", "x_norm", "y_norm")]}
                for r in regions
            ]
            for r, row in zip(regions, rows):
                b = r["box_norm"]
                row["box"] = [round(b["x_norm"], 4), round(b["y_norm"], 4),
                              round(b["x_norm"] + b["w_norm"], 4),
                              round(b["y_norm"] + b["h_norm"], 4)]
        except Exception as exc:  # noqa: BLE001
            rows = [{"error": repr(exc)[:120]}]
        matches = {
            s: (lambda m: {"distance": m.distance, "center": list(m.center_norm)} if m else None)(
                roi_vision.find(path, s))
            for s in ("LOGIN_GIFT_DAY_CLAIM", "PAGE_LOGIN_GIFT", "PAGE_SUPER_ACTIVITY")
        }
        out[name] = {"page": str(world.page), "events": world.events, "matches": matches,
                     "words": rows}
    print(json.dumps(out, ensure_ascii=False, indent=1)[:8000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
