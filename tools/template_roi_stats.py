"""Collect 48px ROI search-margin statistics for every TEMPLATE node.

Reads ``knowledge/execution/backend_routing.json`` and, for each TEMPLATE
recognition entry, records:

  template size (px, from the source template file)
  original ROI           (the generator's detection window)
  expanded ROI           (original + TEMPLATE_ROI_EXPAND on every side)
  matcher scores         (positive / negative hits recorded in evidence)
  target drift           (observed box vs original ROI, when recorded)

Purpose (operator directive section 11): accumulate real samples while keeping
the fixed 48px margin.  No adaptive algorithm yet — decide "fixed 48" vs
"observed drift + margin" only when the sample base is big enough.

Usage:
  .venv/Scripts/python.exe tools/template_roi_stats.py [--out FILE]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROUTING_PATH = PROJECT_ROOT / "knowledge" / "execution" / "backend_routing.json"
DEFAULT_OUT = PROJECT_ROOT / "learning" / "template_roi_stats.json"

try:  # margin lives in the harvester; fall back to the documented constant
    from tools.autogen_harvest import TEMPLATE_ROI_EXPAND  # type: ignore
except Exception:  # noqa: BLE001
    TEMPLATE_ROI_EXPAND = 48


def expand_roi(roi: list[int], expand: int) -> list[int]:
    x, y, w, h = roi
    return [max(0, x - expand), max(0, y - expand), w + 2 * expand, h + 2 * expand]


def template_size(path_text: str) -> list[int] | None:
    path = Path(path_text)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.is_file():
        return None
    try:
        from PIL import Image
        with Image.open(path) as im:
            return list(im.size)
    except Exception:  # noqa: BLE001
        return None


def collect() -> dict:
    routing = json.loads(ROUTING_PATH.read_text(encoding="utf-8"))
    rows = []
    for skill_id, entry in sorted(routing.get("skills", {}).items()):
        if not isinstance(entry, dict):
            continue
        for semantic, node in (entry.get("recognition") or {}).items():
            kind = str(node.get("kind", "TEMPLATE")).upper()
            if kind != "TEMPLATE":
                continue
            roi = node.get("roi")
            evidence = entry.get("evidence", {}) or {}
            report = evidence.get("validation_report", {}) or {}
            row = {
                "skill": skill_id,
                "semantic": semantic,
                "roi": roi,
                "expand": TEMPLATE_ROI_EXPAND,
                "expanded_roi": expand_roi(roi, TEMPLATE_ROI_EXPAND) if roi else None,
                "template_size": template_size(node.get("source_template", "")),
                "positive_hits": report.get("positive_hits"),
                "negative_hits": report.get("negative_hits"),
                "positives": report.get("positives"),
                "negatives": report.get("negatives"),
                "matcher_score": evidence.get("matcher_score") or evidence.get("score"),
                "observed_drift": evidence.get("observed_drift"),
            }
            rows.append(row)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "expand_px": TEMPLATE_ROI_EXPAND,
        "template_nodes": len(rows),
        "rows": rows,
    }


def main(argv: list[str]) -> int:
    out_path = DEFAULT_OUT
    if "--out" in argv:
        out_path = PROJECT_ROOT / argv[argv.index("--out") + 1]
    stats = collect()
    out_path.write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {out_path} ({stats['template_nodes']} template nodes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
