"""Register the live cell-relative resource-tab templates in the manifest.

These are full selected-cell crops (145x150) taken from the 2026-09-14 live
capture, so every template carries the same white bracket and identity is
decided by the icon and label inside the cell.  This is what replaces the
scroll-offset-dependent RESOURCE_<NAME>_SELECTED templates for
``selected_resource``; the older records stay in the manifest for provenance but
are no longer consulted by the classifier.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"E:\无尽冬日智能体")
MANIFEST = ROOT / "dataset/candidate/template_manifest.json"

SOURCES = {
    "MEAT": ("20260914_120027_c_002_select_MEAT.png", 87),
    "WOOD": ("20260914_120027_c_003_select_WOOD.png", 244),
    "COAL": ("20260914_120027_c_004_select_COAL.png", 402),
    "IRON": ("20260914_120027_c_005_select_IRON.png", 559),
}
CAPTURE = ROOT / "dataset/truth_audit/resource_cells_20260914_120027"

payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
records = payload["records"]
existing = {(str(r.get("semantic")), str(r.get("template_path"))) for r in records}

added = 0
for resource, (frame, left) in SOURCES.items():
    template = ROOT / "dataset/candidate/resource_tabs" / f"resource_tab_{resource.lower()}__live_cell.png"
    if not template.is_file():
        raise SystemExit(f"missing extracted template: {template}")
    semantic = f"RESOURCE_TAB_{resource}_SELECTED"
    if (semantic, str(template)) in existing:
        continue
    records.append({
        "semantic": semantic,
        "template_path": str(template),
        "roi_norm": {
            "x_norm": round(left / 720, 6),
            "y_norm": 0.672,
            "w_norm": round(145 / 720, 6),
            "h_norm": 0.117,
        },
        "source": f"live_20260914_cell_capture/{frame}",
        "provenance": "LIVE_CLIENT",
        "note": (
            "cell-relative template: full selected cell incl. white bracket; "
            "used by SemanticROIVision.selected_resource with the bracket anchor"
        ),
    })
    added += 1

payload["count"] = len(records)
payload["generated_at"] = datetime.now(timezone.utc).isoformat()
MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"manifest records: {len(records)} (+{added})")
