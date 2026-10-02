"""WB-1002-22 (final shape): retire the node the way the file already retires nodes.

The file's own precedent is ``SEARCH_RESOURCE``: a semantic whose node was measured unusable is
retired by **emptying ``recognition``**, declaring ``recognition_backend: LEGACY``, and recording the
measurement under ``not_migrated["<SKILL>_RECOGNITION"]`` with its ``semantic`` and its reason.  A
node left in place beside a LEGACY declaration is explicitly forbidden by
``tests/test_recognition_backend_declaration.py`` ("the node would silently override the
declaration"), so this is not a style choice.

Idempotent: reads the current file, checks the preconditions, writes the target state, and refuses
to run twice.  Verifies that no other skill moved.
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
LEGACY_KEY = "OPEN_BUILDING_UPGRADE"

DEMOTION_REASON = (
    "Retired 2026-10-02 by applying the operator's own rule from executor_router's module docstring "
    "-- 'if MAA did not improve it, keep ADB', enforced by this file rather than by good intentions. "
    "A node may be preferred only after it is drawn on a real frame for visual check and an A/B shows "
    "it is not worse than the legacy matcher; this one recorded validation PENDING_RECORD from its "
    "harvest (dataset/raw/autogen/r2_home.png, roi x 335..483 y 288..432) and has since answered "
    "exactly zero times. Measured 2026-10-02, role 1061663148, goal KEEP_BUILDING_PRODUCTIVE: 10 "
    "attempts, 0 successes, every one SEMANTIC_TARGET_NOT_VERIFIED carrying "
    "MAA_TEMPLATE:NO_MATCH:score=0.5146:gate=0.7/0.75, duration 0.171 s, empty after_screenshot. The "
    "frame's own OCR reads the 升级 label at (0.4993, 0.7188) = px (359, 920) on the very frame the "
    "step failed on, so the miss is geometric rather than a threshold question: this control is drawn "
    "wherever the selected building happens to sit, and a rect harvested from one camera geometry "
    "cannot cover it. The harvested template image is still the right icon (blue hexagon, white "
    "curved arrow) at dataset/candidate/autogen/btn_selected_building_upgrade__rect_300f6cc7.png; "
    "the ROI is what needs re-measuring. With ADB preferred, "
    "LiveRuntime._resolve_semantic_target('BTN_SELECTED_BUILDING_UPGRADE') reads that same token off "
    "the current frame and answers (0.4993, 0.7188), verified read-only on the archived frame "
    "through the production chain."
)

NOT_MIGRATED_REASON = (
    "The autogen node for BTN_SELECTED_BUILDING_UPGRADE was harvested from a fixed rect on "
    "dataset/raw/autogen/r2_home.png (roi x 335..483, y 288..432) and recorded "
    "validation=PENDING_RECORD. It never answered: 10 attempts on 2026-10-02, 0 successes, all "
    "SEMANTIC_TARGET_NOT_VERIFIED with MAA_TEMPLATE:NO_MATCH:score=0.5146:gate=0.7/0.75. The "
    "frame's own OCR reads the 升级 label at (0.4993, 0.7188) = px (359, 920) on the very frame the "
    "step failed on, so the window is looking at scenery and the recall failure is geometric, not a "
    "threshold: a fixed rect cannot cover a control that is drawn wherever the selected building "
    "sits. This semantic is therefore NOT migrated -- ADB is preferred and the recognition is the V2 "
    "semantic vision, which reads the label off the current frame rather than from a stored offset. "
    "The template image is kept (dataset/candidate/autogen/"
    "btn_selected_building_upgrade__rect_300f6cc7.png); to migrate this, re-measure the way the "
    "battle button was -- locate the control by colour blob on the current client instead of "
    "cropping one frame -- then draw it on real frames and A/B it against the V2 reader. Recorded "
    "here rather than left as an unexplained 0."
)


def main() -> int:
    before = json.loads(ROUTING.read_text(encoding="utf-8"))
    entry = before["skills"][SKILL]

    assert entry["preferred"] == "ADB", f"expected the demotion in place, got {entry['preferred']}"
    assert entry["fallback"] == "MAA"
    assert entry["recognition_backend"] == "LEGACY"
    assert SEMANTIC in (entry.get("recognition") or {}), "the node must be present for this run"
    assert entry["evidence"].get("validation") == "PENDING_RECORD"
    stale = before.get("not_migrated") or {}
    assert SKILL in stale, "the first pass's record is the thing being renamed"
    assert f"{LEGACY_KEY}_RECOGNITION" not in stale, "already in the final shape; refusing to redo"

    after = copy.deepcopy(before)
    patched = after["skills"][SKILL]
    # Retire by removal, which is how this file already retires a node.
    patched.pop("recognition", None)
    patched["evidence"]["demotion_reason"] = DEMOTION_REASON
    patched["evidence"]["demoted_at"] = "2026-10-02T11:15:00Z"
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
        "template_kept_at": "dataset/candidate/autogen/btn_selected_building_upgrade__rect_300f6cc7.png",
    }
    # Rename to the file's own convention: <SKILL>_RECOGNITION, beside CLOSE_POPUP_RECOGNITION et al.
    del after["not_migrated"][SKILL]
    after["not_migrated"][f"{LEGACY_KEY}_RECOGNITION"] = {
        "semantic": SEMANTIC,
        "reason": NOT_MIGRATED_REASON,
        "measured_at": "2026-10-02T10:46:09Z",
    }

    for skill_id, value in before["skills"].items():
        if skill_id == SKILL:
            continue
        assert value == after["skills"][skill_id], f"unintended edit to {skill_id}"
    for key in before:
        if key in {"skills", "not_migrated"}:
            continue
        assert before[key] == after[key], key
    assert set(after["not_migrated"]) == (set(stale) - {SKILL}) | {f"{LEGACY_KEY}_RECOGNITION"}

    ROUTING.write_text(json.dumps(after, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    reloaded = json.loads(ROUTING.read_text(encoding="utf-8"))
    assert reloaded == after, "round-trip mismatch"
    final = reloaded["skills"][SKILL]
    print("patched", ROUTING.relative_to(ROOT))
    print("  preferred=%s fallback=%s recognition_backend=%s recognition=%r"
          % (final["preferred"], final["fallback"], final["recognition_backend"],
             final.get("recognition")))
    print("  not_migrated keys:", list(reloaded["not_migrated"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
