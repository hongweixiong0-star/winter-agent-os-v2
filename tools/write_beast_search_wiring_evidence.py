"""Write the evidence set for the SPEND_STAMINA_ON_BEAST escalation of 2026-09-18.

Escalation ``SPEND_STAMINA_ON_BEAST|NO_GOAL_PROGRESS|SCAN_MAP_FOR_BEAST`` was the
second shape of the same failure: every step passed its own verifier and the goal
meter never moved.  A previous round proved the ``SCAN_MAP_FOR_BEAST`` pan really
does move the viewport and recorded that the client's own beast search was never
wired (``dataset/truth_audit/beast_scan_pan_20260918/``).

This round measured that search on today's client and found why it could not be
wired: the resource-search tab strip's first three entries in
``SemanticROIVision.resource_tab_order`` had drifted, so the index-based tap
target for ``BEAST`` pointed one whole tab-pitch to the left of the real 野兽 tab
and off the screen.

The script is read-only apart from writing the evidence directory.  It copies the
frames it relies on and records what was measured, so the numbers in the finding
can be re-derived by the next reader instead of trusted.

Usage
-----
    "E:/无尽冬日智能体/.venv/Scripts/python.exe" -u tools/write_beast_search_wiring_evidence.py
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SET_NAME = "beast_search_wiring_20260918"
SOURCE = ROOT / "dataset/truth_audit/map_beast_search_20260918/key"
DEST = ROOT / "dataset/truth_audit" / SET_NAME / "key"

#: Frames this finding rests on.  The first five are this round's live probes, the
#: last three are the previous round's beast-card walk-through that shows the
#: client's own search does reach a huntable beast.
KEEP = (
    "measure_now.png",
    "measure_now_tabband.png",
    "scroll0.png",
    "scroll1.png",
    "probe_b_search_open.png",
    "baseline_20260918_014520_000_before.png",
    "tapox_20260918_014906_001_after_60_655.png",
    "go_20260918_014947_001_after382x844.png",
    "go_20260918_014947_001_after_382_844.png",
)


def main() -> int:
    from winter_agent_v2.vision import SemanticWorldVision

    DEST.mkdir(parents=True, exist_ok=True)
    vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    roi = vision.semantic

    copied = []
    for name in KEEP:
        source = SOURCE / name
        if source.is_file():
            shutil.copy2(source, DEST / name)
            copied.append(name)

    measured = {}
    for name in ("measure_now.png", "scroll0.png", "scroll1.png", "probe_b_search_open.png"):
        frame = SOURCE / name
        if not frame.is_file():
            continue
        match = roi.selected_resource(frame)
        measured[name] = {
            "offset_px": roi.resource_tab_offset,
            "selected": match.semantic if match else None,
            "beast_center_norm": roi.resource_cell_center_norm("BEAST"),
            "giant_beast_center_norm": roi.resource_cell_center_norm("GIANT_BEAST"),
        }

    payload = {
        "schema_version": "1.0",
        "set": SET_NAME,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "capability": "SPEND_STAMINA_ON_BEAST",
        "goal": "AVOID_STAMINA_WASTE",
        "skill": "SCAN_MAP_FOR_BEAST",
        "escalation": "REPEATED_LIVE_FAILURE / NO_GOAL_PROGRESS "
                      "(SPEND_STAMINA_ON_BEAST|NO_GOAL_PROGRESS|SCAN_MAP_FOR_BEAST)",
        "verdict": "ROOT_CAUSE_FIXED_ON_THE_VISION_SIDE__ROUTE_STILL_NOT_DISPATCHING",
        "root_cause": {
            "one_sentence": (
                "AVOID_STAMINA_WASTE can only advance by reaching a beast, its only "
                "such hop (SCAN_MAP_FOR_BEAST) is a viewport sweep with no convergence "
                "criterion, and the client's own way to reach a beast -- the 野兽 tab of "
                "the world-map search panel -- was made untappable by a frozen "
                "resource_tab_order whose first three names have drifted with the client, "
                "so resource_cell_center_norm('BEAST') resolved one whole tab-pitch "
                "(157 px) to the left of the real tab and returned None on every frame."
            ),
            "facts": [
                "learning/episodes.jsonl: 336 AVOID_STAMINA_WASTE episodes ran SCAN_MAP_FOR_BEAST; every recorded goal_progress is false.",
                "winter_agent_v2/verifier.py:732 verify_beast_scan_observed passes on any readable MAP->MAP pair, so it cannot tell 'panned' from 'found'.",
                "winter_agent_v2/brain.py:857 max_beast_scans = 3, then SAFE_STOP verified_beast_target_not_visible.",
                "winter_agent_v2/vision.py resource_tab_order was (BEAST, GIANT_BEAST, SAWMILL, MEAT, WOOD, COAL, IRON); the live client draws 失控的雪怪 / 野兽 / 冰原巨兽 at indices 0/1/2 and MEAT/WOOD/COAL/IRON at 3/4/5/6.",
                "resource_cell_center_norm is index-based, so BEAST resolved to index 0 -- one pitch left of the real 野兽 tab, off the screen, hence None.",
                "The client's own search does fly the camera onto a huntable beast: go_20260918_014947_001_after_382_844.png shows 等级4洞斑鬣狗 with an 攻击 control costing 10 stamina, reached from the 前往 control of a beast card.",
            ],
        },
        "live_measurement": {
            "date": "2026-09-18",
            "device": "MuMu 720x1280, foreground com.gof.china, stamina 577, marches 1/3",
            "method": "RapidOCR over the tab band y=860..1010, label centre in px, pitch measured between adjacent labels",
            "strip_unscrolled": [
                {"x": 45.2, "label": "野兽"},
                {"x": 202.2, "label": "冰原巨兽"},
                {"x": 360.8, "label": "生肉"},
                {"x": 517.4, "label": "木材"},
                {"x": 675.5, "label": "煤矿"},
            ],
            "strip_after_scrolling_left": [
                {"x": 88.8, "label": "失控的雪怪"},
                {"x": 245.8, "label": "野兽"},
                {"x": 402.4, "label": "冰原巨兽"},
                {"x": 561.0, "label": "生肉"},
            ],
            "pitch_px": 157.0,
            "offset_pinned_by_reviewed_cells_px": 200.0,
            "corrected_index1_nominal_left_px": -27.0,
            "measured_beast_label_left_px": -27.3,
            "note": "the corrected index 1 lands on the real 野兽 tab to within 0.3 px; "
                    "the old index 0 nominal centre was -111.5 px, off the screen",
            "archived_frame_cross_check": {
                "gather_live_20260914_115120 (2026-09-14 client)": [
                    "idx0 野兽", "idx1 冰原巨兽", "idx2 大型锯木厂", "idx3 生肉",
                ],
                "live_fail_233727 / 233739 / 160609 (2026-09-15 client)": [
                    "idx0 失控的雪怪", "idx1 野兽", "idx2 冰原巨兽", "idx3 生肉",
                ],
                "conclusion": "the first three tab names DRIFT; only MEAT/WOOD/COAL/IRON "
                              "at indices 3..6 are stable, which is what the reviewed cell "
                              "templates pin the offset with",
            },
        },
        "change": {
            "file": "winter_agent_v2/vision.py",
            "what": "resource_tab_order's first three entries corrected from "
                    "(BEAST, GIANT_BEAST, SAWMILL) to (SNOW_MONSTER, BEAST, GIANT_BEAST).  "
                    "The list still holds seven entries, so MEAT/WOOD/COAL/IRON keep "
                    "indices 3/4/5/6 and every nominal position and reviewed cell "
                    "template is unchanged.",
            "effect": "resource_cell_center_norm('BEAST') and resource_tab_swipe_for('BEAST') "
                      "now address the real 野兽 tab; before they addressed index 0, a "
                      "different target.",
            "test": "tests/test_resource_tab_anchor.py: the four archived volatile-anchor "
                    "cases now assert geometry (the strip is located, and no gatherable "
                    "identity is invented) instead of a drifting name.",
        },
        "post_change_measurement": measured,
        "not_done": [
            "No live episode in which SPEND_STAMINA_ON_BEAST spends stamina.  The route "
            "does not yet open the search, select 野兽 and submit it, and there is no "
            "recognition for a normal (non-musk-ox) beast target card.",
            "The durable fix for the front three tabs is to identify the anchored tab "
            "from the label the client prints (RapidOCR) rather than from any frozen "
            "list.  That is designed here but NOT implemented.",
            "The corrected names are correct for the 2026-09-18 client only; they will "
            "drift again.",
        ],
        "key": copied,
    }

    out = DEST / "finding.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {out}")
    print(f"copied {len(copied)} frame(s): {copied}")
    for name, row in measured.items():
        print(name, row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
