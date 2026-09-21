"""What does the current vision say about the frame the training route died on?

Measured question, one frame.  A live AUTO step at 2026-09-21T16:24:02 issued
``NAVIGATE_INFANTRY_CAMP`` (tap ``BTN_POWER_TROOP_IMPROVE``, from the 实力详情 popup) and the
verifier answered ``INFANTRY_CAMP_HIGHLIGHT_NOT_PROVEN``.  The frame it answered about reads,
to a human, as a *success*: the 盾兵营 building carries its label, is surrounded by a bright
radial halo, and the client has drawn its own 详情 / 升级 / 训练 controls underneath it with a
finger pointing at 训练.

So either the template that stands for "this camp is selected" does not match this frame, or
it matches and something downstream drops it.  Read-only; prints distances.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.vision import SemanticROIVision, SemanticWorldVision

MANIFEST = ROOT / "dataset/candidate/template_manifest.json"

FRAME = (ROOT / "dataset/raw/control_panel/runtime_auto/20260922_001615_642151"
         / "20260922_001615_642151_step_011_after_refresh_2_20260921T162341609773.png")

CANDIDATES = (
    "TARGET_INFANTRY_CAMP_HIGHLIGHTED",
    "TARGET_MARKSMAN_CAMP_HIGHLIGHTED",
    "TARGET_LANCER_CAMP_HIGHLIGHTED",
    "BTN_TRAINING_MENU_LABEL",
    "BTN_OPEN_TRAINING_FROM_CAMP",
    "BTN_OPEN_TRAINING",
    "BTN_TRAIN_TROOPS",
    "BTN_UPGRADE",
    "BTN_DETAIL",
    "BTN_POWER_TROOP_IMPROVE",
    "BTN_POWER_OVERVIEW",
)


def main() -> int:
    print("manifest:", MANIFEST, MANIFEST.exists())
    print("frame   :", FRAME.name, FRAME.exists())
    if not (MANIFEST.exists() and FRAME.exists()):
        return 2

    vision = SemanticWorldVision(MANIFEST)
    state = vision.observe(FRAME)
    print("\n--- SemanticWorldVision.observe ---")
    print("  page      :", state.page)
    print("  popup     :", state.popup)
    print("  training  :", state.training)
    print("  confidence:", state.confidence)
    print("  known     :", state.known)

    roi = SemanticROIVision(MANIFEST)
    print("\n--- per-template matches (a miss is a fact, not an error) ---")
    for name in CANDIDATES:
        try:
            match = roi.find(FRAME, name)
        except Exception as exc:  # noqa: BLE001 - a missing template is an answer
            print(f"  {name:42} ERR {type(exc).__name__}: {exc}")
            continue
        if match is None:
            print(f"  {name:42} (no template record / no hit)")
        else:
            print(f"  {name:42} hit distance={getattr(match, 'distance', None)} "
                  f"roi={getattr(match, 'roi_norm', None)}")

    print("\n--- which templates the manifest even knows ---")
    try:
        import json
        records = json.loads(MANIFEST.read_text(encoding="utf-8")).get("records") or []
    except Exception as exc:  # noqa: BLE001
        print("  manifest unreadable:", exc)
        return 0
    wanted = [n for n in CANDIDATES]
    by_semantic = {}
    for record in records:
        semantic = str(record.get("semantic") or "")
        by_semantic.setdefault(semantic, []).append(record)
    for name in wanted:
        got = by_semantic.get(name)
        print(f"  {name:42} {'recorded x' + str(len(got)) if got else 'NOT IN MANIFEST'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
