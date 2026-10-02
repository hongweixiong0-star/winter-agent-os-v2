"""WB-1002-22: enforce the routing file's own operator rule for the one node that never answered.

Data-only change, with the measurement recorded next to the decision.  Writes nothing until every
precondition holds, and verifies afterwards that no other skill changed byte-for-byte.
"""

from __future__ import annotations

import copy
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
ROUTING = ROOT / "knowledge/execution/backend_routing.json"
SKILL = "OPEN_BUILDING_UPGRADE"
SEMANTIC = "BTN_SELECTED_BUILDING_UPGRADE"

DEMOTION_REASON = (
    "Executed the operator's own rule from executor_router's module docstring -- 'if MAA did not "
    "improve it, keep ADB', enforced by this file rather than by good intentions. A node may be "
    "preferred only after it is drawn on a real frame for visual check and an A/B shows it is not "
    "worse than the legacy matcher; this one records validation PENDING_RECORD from its harvest "
    "(dataset/raw/autogen/r2_home.png) and has since answered exactly zero times. Measured "
    "2026-10-02: 10 attempts, 0 successes, every one SEMANTIC_TARGET_NOT_VERIFIED carrying "
    "MAA_TEMPLATE:NO_MATCH:score=0.5146:gate=0.7/0.75, duration 0.171 s, empty after_screenshot. "
    "The node's search window is x 335..483, y 288..432 while the frame's own reading of the 升级 "
    "label sits at (0.4993, 0.7188) = px (359, 920): the window holds snow and a wall, and the "
    "distance is structural rather than a threshold question -- this control is drawn wherever the "
    "selected building happens to sit, so a rect harvested from one camera geometry cannot cover "
    "it. The template image itself is the right icon (blue hexagon, white curved arrow); only the "
    "harvested ROI is wrong. With ADB preferred, "
    "LiveRuntime._resolve_semantic_target('BTN_SELECTED_BUILDING_UPGRADE') reads that same token "
    "off the current frame and answers (0.4993, 0.7188); measured read-only on the archived frame "
    "through the production chain. Kept as an asset, retired as a node."
)

NOT_MIGRATED_REASON = (
    "The autogen node for BTN_SELECTED_BUILDING_UPGRADE was harvested from a fixed rect on "
    "dataset/raw/autogen/r2_home.png (roi x 335..483, y 288..432) and recorded "
    "validation=PENDING_RECORD. It never answered: 10 attempts on 2026-10-02, 0 successes, all "
    "SEMANTIC_TARGET_NOT_VERIFIED with MAA_TEMPLATE:NO_MATCH:score=0.5146:gate=0.7/0.75. The "
    "frame's own OCR reads the 升级 label at (0.4993, 0.7188) = px (359, 920) on the very frame the "
    "step failed on, so the window is looking at scenery and the recall failure is geometric, not a "
    "threshold: a fixed rect cannot cover a control that is drawn wherever the selected building "
    "sits. This semantic is therefore NOT migrated -- ADB is preferred and the recognition is the "
    "V2 semantic vision, which reads the label off the current frame. To migrate it, re-measure the "
    "way the battle button was: locate the control by colour blob on the current client rather than "
    "cropping one frame, then draw it on real frames and A/B it against the V2 reader. Recorded "
    "here rather than left as an unexplained 0."
)

RETIRED_REASON = (
    "Retired 2026-10-02 while the template is kept: the picture is the right icon, the roi is "
    "another frame's geometry (x 335..483, y 288..432 against a control measured at (0.4993, "
    "0.7188)). Re-wiring this node without a fresh measurement re-introduces the 10-for-10 recall "
    "failure it was demoted for."
)


def main() -> int:
    before = json.loads(ROUTING.read_text(encoding="utf-8"))
    entry = before["skills"][SKILL]

    # Preconditions -- refuse to write unless this is the state the measurement describes.
    assert entry["preferred"] == "MAA", entry["preferred"]
    assert entry["promoted"] is False
    assert entry["evidence"]["validation"] == "PENDING_RECORD"
    assert entry["recognition"][SEMANTIC]["roi"] == [335, 288, 148, 144]
    assert SKILL not in (before.get("not_migrated") or {}), "already recorded; refusing to double-write"

    after = copy.deepcopy(before)
    patched = after["skills"][SKILL]
    patched["preferred"] = "ADB"
    patched["fallback"] = "MAA"
    patched["recognition_backend"] = "LEGACY"
    patched["evidence"]["demotion_reason"] = DEMOTION_REASON
    patched["evidence"]["demoted_at"] = "2026-10-02T11:00:00Z"
    patched["evidence"]["measured_record"] = {
        "attempts": 10,
        "successes": 0,
        "failure_type": "SEMANTIC_TARGET_NOT_VERIFIED",
        "recognition_error": "MAA_TEMPLATE:NO_MATCH:score=0.5146:gate=0.7/0.75",
        "measured_at": "2026-10-02T10:46:09Z",
        "frame_declared_control_norm": [0.4993, 0.7188],
        "node_roi": [335, 288, 148, 144],
        "role_id": "1061663148",
        "goal_id": "KEEP_BUILDING_PRODUCTIVE",
    }
    patched["recognition"][SEMANTIC]["retired"] = True
    patched["recognition"][SEMANTIC]["retired_reason"] = RETIRED_REASON
    after.setdefault("not_migrated", {})[SKILL] = {
        "semantic": SEMANTIC,
        "reason": NOT_MIGRATED_REASON,
        "measured_at": "2026-10-02T10:46:09Z",
    }

    # Nothing else may move.
    for skill_id, value in before["skills"].items():
        if skill_id == SKILL:
            continue
        assert value == after["skills"][skill_id], f"unintended edit to {skill_id}"
    for key in before:
        if key in {"skills", "not_migrated"}:
            continue
        assert before[key] == after[key], key

    text = json.dumps(after, ensure_ascii=False, indent=2) + "\n"
    ROUTING.write_text(text, encoding="utf-8")

    reloaded = json.loads(ROUTING.read_text(encoding="utf-8"))
    assert reloaded == after, "round-trip mismatch"
    print("patched", ROUTING.relative_to(ROOT))
    print("  preferred ->", reloaded["skills"][SKILL]["preferred"],
          "| fallback ->", reloaded["skills"][SKILL]["fallback"],
          "| recognition_backend ->", reloaded["skills"][SKILL]["recognition_backend"])
    print("  not_migrated entries:", len(reloaded["not_migrated"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
