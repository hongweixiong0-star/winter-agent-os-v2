"""Classify no-CJK gap-queue entries by how the client actually draws them.

The 50 entries without CJK visible_words cannot be harvested through the OCR
text path: there is no declared label to look for, and fabricating one is
forbidden. They are instead classified by the real UI feature each control
presents, recorded in ``recognition.method`` on the queue entry itself:

- ``OCR``          — the control prints Chinese text at runtime; the words are
                     simply not yet recorded. Nothing is invented here: the
                     harvest re-runs OCR on a live frame and takes whatever
                     tokens the client actually draws.
- ``TEMPLATE``     — an icon / image control (arrows, pins, map monsters,
                     dispatch markers) with no reliable text; a template is
                     cropped from a live frame at a declared or located rect.
- ``COLOR``        — bars/gauges whose state is a colour ratio, not a shape.
- ``STRUCTURE``    — controls defined by relative position inside a known
                     layout (ring positions, layout-anchored controls).
- ``LIST_DYNAMIC`` — rows whose content/position changes per state; need
                     per-instance capture at decision time, not a fixed node.

The classification is a *plan*, never evidence: a TEMPLATE entry still needs a
live frame before any node exists, and every generated node still passes the
same positive/negative validation as OCR nodes.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "knowledge" / "execution" / "pipeline_gap_queue.json"


def has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text or "")


# Rules in priority order. Each rule matches on the semantic's own recorded
# naming (which came from live observation when the gap was written) plus the
# family and pages already in the queue — no invented UI facts.
def rule_table():
    return [
        # Dynamic rows / per-instance targets change with state.
        (r"ROW_\d|_DYNAMIC|QUICK_PANEL_ROW|TARGET_BEAST_|TARGET_INTEL_",
         "LIST_DYNAMIC",
         "row/target whose content and position change per state; needs per-instance capture"),
        # Gauges are colour, not shape.
        (r"^HUD_|GAUGE",
         "COLOR",
         "gauge/bar: state is a colour ratio inside a fixed track"),
        # Layout-anchored controls: meaningful only relative to their layout.
        (r"^ORDINARY_CONTROL|^CONTROL\[|TRAINING_CAMP_(IN_RING|NEXT)|_NEXT_DETAIL$",
         "STRUCTURE",
         "position defined relative to a page layout (ring slot / next-slot anchor)"),
        # Map monsters and markers are unique sprites.
        (r"BEAST_ON_MAP|BEAST_SEARCH_TAB|RESOURCE_LEVEL_MINUS|^BTN_BACK_ARROW|^INTEL_PIN",
         "TEMPLATE",
         "unique icon sprite (map marker / arrow / pin / minus), no stable text"),
        # Remaining BTN_* icons on map/march/alliance are HUD icons.
        (r"^BTN_(OPEN_|BEAST_|ALLIANCE_(HELP_ALL|WAR)|POWER_|INTEL_VIEW|SELECTED_BUILDING|OPEN_TRAINING)",
         "TEMPLATE",
         "HUD icon button observed without caption text on its recorded page"),
    ]


def classify(semantic: str, family: str, pages: list[str]) -> tuple[str, str]:
    for pattern, method, basis in rule_table():
        if re.search(pattern, semantic):
            return method, basis
    # Default for the rest: a named button on a popup/menu almost always prints
    # Chinese text (upgrade / confirm / claim ...). It is classified OCR, which
    # only means "re-run live-frame OCR when the page is up" — no words typed in.
    return "OCR", "named action button; client prints caption text at runtime, to be read live"


def main() -> int:
    payload = json.loads(QUEUE.read_text(encoding="utf-8"))
    queue = payload.get("queue") or []
    counts: dict[str, int] = {}
    changed = 0
    for item in queue:
        if not isinstance(item, dict) or not item.get("semantic"):
            continue
        words = item.get("visible_words") or []
        if any(has_cjk(str(w)) for w in words):
            continue
        if item.get("recognition", {}).get("method"):
            counts[item["recognition"]["method"]] = counts.get(item["recognition"]["method"], 0) + 1
            continue
        method, basis = classify(str(item["semantic"]), str(item.get("family", "")),
                                 [str(p) for p in item.get("pages", [])])
        item["recognition"] = {"method": method, "basis": basis, "classified_at_source": "rule_table_v1"}
        counts[method] = counts.get(method, 0) + 1
        changed += 1
    QUEUE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"queue={len(queue)} newly_classified={changed} distribution={counts}")
    for item in queue:
        rec = item.get("recognition") or {}
        if rec.get("method"):
            print(f"  {rec['method']:12} {item['semantic']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
