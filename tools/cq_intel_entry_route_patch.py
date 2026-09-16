"""Point BTN_OPEN_INTEL_WILD_HUD at the search-based matcher over a HUD band.

The semantic currently uses the fixed-ROI phash path, which measures "is the
control still where it was", not "is the control visible".  Measured on the six
2026-09-16 failures: distance 34-38 at the ROI against a threshold of 24, while
the control was demonstrably on screen 93 px lower (near-exact phash distance 2,
ccoeff 0.945).  This registers the same three templates with the search-based
matcher and a bounded window.

Only records of this one semantic are touched; no threshold is changed.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "dataset/candidate/template_manifest.json"
SEMANTIC = "BTN_OPEN_INTEL_WILD_HUD"

# The right-hand HUD column, bounded so the search cannot wander into the map
# field or the bottom navigation bar.  Reaches the control in both measured
# layouts (top edge y_norm 0.635 and 0.7453, height 0.075).
BAND = {"x_norm": 0.72, "y_norm": 0.30, "w_norm": 0.28, "h_norm": 0.55}


def main() -> int:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records = payload["records"]
    touched = 0
    for row in records:
        if row.get("semantic") != SEMANTIC:
            continue
        before = copy.deepcopy(row)
        row["matcher"] = "ccoeff"
        row["search_band"] = dict(BAND)
        row["matcher_note"] = (
            "Search-based: the control moves with the bottom-anchored HUD stack, so the "
            "registration ROI cannot double as the search window. Threshold unchanged."
        )
        touched += 1
        del before
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("records updated: %d" % touched)
    for row in records:
        if row.get("semantic") == SEMANTIC:
            print("  %-46s matcher=%s band=%s" % (row["template_id"], row.get("matcher"), json.dumps(row.get("search_band"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
