"""Read-only: which semantics can make ``SemanticROIVision.find`` raise?

``find`` builds ``matches`` by appending one entry per candidate record, but the
``ccoeff`` branch appends nothing when ``match_ccoeff`` returns ``None``.  If a
semantic's records are all ``ccoeff`` and none of them can be evaluated, the
list stays empty and ``min(matches, ...)`` raises ``ValueError`` -- the vision
layer crashes instead of reporting UNKNOWN.

``match_ccoeff`` returns ``None`` when every scale is skipped because the
template is not strictly smaller than the search window (window = ROI + margin
on each side).  This probe measures that condition per semantic, so the
guaranteed crashers are separated from the merely possible ones.

Usage: python tools/probe_ccoeff_window_fit.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from winter_agent_v2.matchers import SCALES, SEARCH_MARGIN  # noqa: E402

MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"
FRAME = ROOT / "dataset" / "raw" / "live_exploration_after_claim.png"


def main() -> int:
    records = json.loads(MANIFEST.read_text(encoding="utf-8"))["records"]
    with Image.open(FRAME) as source:
        width, height = source.size

    print(f"frame {width}x{height}, margin {SEARCH_MARGIN}px, scales {SCALES}\n")
    guaranteed: list[str] = []
    for row in records:
        if row.get("matcher") != "ccoeff":
            continue
        roi = row["roi_norm"]
        x0 = max(0, round(roi["x_norm"] * width) - SEARCH_MARGIN)
        y0 = max(0, round(roi["y_norm"] * height) - SEARCH_MARGIN)
        x1 = min(width, round((roi["x_norm"] + roi["w_norm"]) * width) + SEARCH_MARGIN)
        y1 = min(height, round((roi["y_norm"] + roi["h_norm"]) * height) + SEARCH_MARGIN)
        window = (x1 - x0, y1 - y0)
        with Image.open(row["template_path"]) as template:
            tw0, th0 = template.size
        usable = []
        for scale in SCALES:
            tw = max(8, round(tw0 * scale))
            th = max(8, round(th0 * scale))
            if th < window[1] and tw < window[0]:
                usable.append(scale)
        verdict = "CRASHES (no scale can run)" if not usable else f"ok at {usable}"
        if not usable:
            guaranteed.append(row["semantic"])
        print(
            f"  {row['semantic']:32s} template {tw0}x{th0}  window {window[0]}x{window[1]}  {verdict}"
        )

    print(f"\n{len(guaranteed)} semantics always return None -> find() raises:")
    for semantic in guaranteed:
        print(f"   {semantic}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
