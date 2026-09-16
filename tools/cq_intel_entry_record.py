"""Record the R19 OPEN_INTEL recognition measurement in the routing table.

``knowledge/execution/backend_routing.json`` is the machine-readable record of
which backend recognises each skill, together with the evidence behind that
choice.  The OPEN_INTEL entry still described the 2026-09-14 regression; this
appends what was measured on 2026-09-16 without changing the chosen backends.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTING = ROOT / "knowledge/execution/backend_routing.json"
EVIDENCE_DIR = ROOT / "dataset/truth_audit/intel_entry_20260916"
LIVE_FRAME = ROOT / "dataset/raw/live_runtime/live_runtime_step_002_before_20260916T020345929477.png"

NOTE = (
    "Recognition recalibrated 2026-09-16 (WB-R19-OPEN-INTEL-MAA-RECOVERY), backends unchanged "
    "(skill stays preferred MAA / fallback ADB / recognition LEGACY=V2 semantic, and the live step "
    "recorded recognition_backend=V2 with action_backend=MAA and executor_backend=HYBRID). "
    "Root cause of the six consecutive failures was NOT the threshold. The control is the world-map "
    "HUD menu button at x_norm 0.925, and the right-hand button stack is bottom-anchored, so its row "
    "moves with the rest of the HUD: y_norm 0.6727 in one layout, 0.7453 in another, 93 px apart. On "
    "the failing frames the fixed ROI held empty sky (phash 34-38 against a threshold of 24) while the "
    "control was demonstrably on screen lower down (phash 2, ccoeff 0.945). A ROI that is both "
    "'where it is' and 'where to look' cannot follow that, so the record now carries a separate "
    "search_band and the match reports the bounds it FOUND - the executor taps match.center_norm, and "
    "reporting the registration would have sent the tap 93 px above the button. A second axis is "
    "theme: the day/night cycle repaints the HUD and the day-colour template scored only 0.390-0.448 "
    "on the two night frames, so a night template was registered from each. Measured over 77 MAP "
    "positives and 369 control-absent negatives through the real find() path: recall 72/77 (93.5%), "
    "0 false positives. The two populations overlap (worst positive 29, best negative 28), so the "
    "threshold was deliberately left at 24: raising it to catch the last five would put it on top of a "
    "negative frame. The control is not MAP-exclusive - BEAST and EXPLORATION keep the HUD visible and "
    "score 0.86-0.915 - which is why the discriminator is the page gate, not the control's presence. "
    "Live 2026-09-16T02:04:04Z: OPEN_INTEL MAP->INTEL, verifier ok (before_map/after_intel), tap "
    "dispatched at (666, 954) - exactly the found row, not the registration row 861."
)


def main() -> int:
    payload = json.loads(ROUTING.read_text(encoding="utf-8"))
    entry = payload["skills"]["OPEN_INTEL"]
    entry["evidence"] = {
        "measured_at": "2026-09-16T02:04:00Z",
        "source": "corpus replay through SemanticWorldVision.find + live run tools/run_live.py --goal INTEL (episode 2026-09-16T02:04:04Z)",
        "prior_evidence": entry.get("evidence"),
        "note": NOTE,
        "corpus": {
            "positives": 77,
            "negatives": 369,
            "map_derived_control_visible": 55,
            "recall": "72/77",
            "false_positives": 0,
            "positive_distance_max": 29,
            "negative_distance_min": 28,
            "threshold": 24,
            "threshold_changed": False,
            "templates": 3,
            "themes": ["day", "night"],
            "search_band": {"x_norm": 0.72, "y_norm": 0.3, "w_norm": 0.28, "h_norm": 0.55},
        },
        "regression_reverted": False,
    }
    ROUTING.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("updated OPEN_INTEL evidence in %s" % ROUTING.name)

    if LIVE_FRAME.exists():
        target = EVIDENCE_DIR / ("live_pass__" + LIVE_FRAME.name)
        shutil.copyfile(LIVE_FRAME, target)
        print("archived live evidence frame %s" % target.name)
    else:
        print("live frame not found: %s" % LIVE_FRAME)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
