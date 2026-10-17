"""Offline replay for the bear/rally template pack.

Contract (winter_agent_v2/vision.py:1289)
-----------------------------------------
``SemanticROIVision.find(image_path, semantic)`` returns a ``SemanticMatch`` whose
``distance`` is a **pHASH Hamming distance -- lower is better**, or ``None`` when the
semantic has no record registered at all.  A miss at the ROI (distance above
``max_distance``) also surfaces as ``None``.

So a semantic only counts as *discriminating* when:
  * it is FOUND on the frame it was cut from              (positive hit), and
  * it is NOT found on a different live frame that lacks the control
    (negative miss) OR scores strictly worse there.

The second half is the point.  The directive forbids ``普通集结`` being read as
``巨熊集结`` and a generic 攻击 being read as the bear join; a template that fires
on every alliance-war screenshot would be exactly that mistake.

``find`` caches per (path, semantic), and the same frame is reused against many
semantics, so the cache is intentionally left on -- it is keyed by semantic too.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(r"E:\WinterAgent")
sys.path.insert(0, str(ROOT))

from winter_agent_v2.vision import SemanticROIVision

RAW = ROOT / "dataset/raw/bear_live_20260909"
MANIFEST = ROOT / "dataset/candidate/template_manifest.json"

# semantic -> (positive frame, negative frame that lacks the control)
CASES: dict[str, tuple[str, str]] = {
    "BTN_ALLIANCE_WAR":        ("alliance_main_now.png", "bear_troop_setup.png"),
    "TAB_RALLY_LIST":          ("join_list_now.png", "bear_troop_setup.png"),
    "TARGET_BEAR_TRAP":        ("bear_trap_detail.png", "bear_troop_setup.png"),
    "ROW_TARGET_BEAR_COLUMN":  ("join_list_now.png", "special_buildings.png"),
    "STATUS_RALLY_COUNTDOWN":  ("join_list_now.png", "special_buildings.png"),
    "BTN_JOIN_ROW":            ("bear_rally_panel.png", "bear_troop_setup.png"),
    "BTN_AUTO_JOIN":           ("bear_rally_panel.png", "bear_troop_setup.png"),
    "BTN_START_RALLY":         ("bear_trap_detail.png", "bear_troop_setup.png"),
    "POPUP_TITLE_START_RALLY": ("bear_rally_next.png", "bear_troop_setup.png"),
    "BTN_CONFIRM_START_RALLY": ("bear_rally_next.png", "bear_troop_setup.png"),
    "BTN_BEAR_GO":             ("special_buildings.png", "bear_troop_setup.png"),
    "STATUS_BEAR_WINDOW":      ("special_buildings.png", "bear_troop_setup.png"),
    "PAGE_TITLE_MARCH":        ("bear_troop_setup.png", "special_buildings.png"),
    "BTN_CONFIRM_MARCH":       ("bear_troop_setup.png", "special_buildings.png"),
}

# A second negative class: the *other bear/rally* frames.  For BTN_JOIN_ROW and the
# two leader-side controls, the strongest false positive risk is a neighbouring
# page of the same activity, not an unrelated page.
EXTRA_NEGATIVES: dict[str, tuple[str, ...]] = {
    "BTN_JOIN_ROW": ("join_list_now.png", "join_list_after_detail.png"),
    "BTN_AUTO_JOIN": ("bear_rally_next.png",),
    "BTN_START_RALLY": ("bear_rally_panel.png",),
    "BTN_CONFIRM_START_RALLY": ("bear_reset",),  # placeholder, filtered below
    "TARGET_BEAR_TRAP": ("special_buildings.png",),
}


def main() -> int:
    vision = SemanticROIVision(MANIFEST)
    registered = {r["semantic"] for r in vision.records}
    print(f"registered semantics: {len(registered)}")
    missing = [s for s in CASES if s not in registered]
    print(f"bear pack registered: {len(CASES) - len(missing)}/{len(CASES)}"
          + (f"  MISSING={missing}" if missing else ""))
    print()

    header = f"{'SEMANTIC':26s} {'POS':>5s} {'NEG':>5s} {'MAX':>4s}  VERDICT"
    print(header)
    print("-" * len(header))
    ok = ambiguous = absent = 0
    for semantic, (pos_name, neg_name) in CASES.items():
        if semantic not in registered:
            print(f"{semantic:26s} {'-':>5s} {'-':>5s} {'-':>4s}  NOT_REGISTERED")
            absent += 1
            continue
        p = vision.find(RAW / pos_name, semantic)
        n = vision.find(RAW / neg_name, semantic)
        pd = None if p is None else p.distance
        nd = None if n is None else n.distance
        max_d = vision.max_distance

        if pd is None:
            verdict = "POS_MISS"          # cut from this very frame yet not found -> broken
            ambiguous += 1
        elif nd is None:
            verdict = "OK"                # found here, absent there
            ok += 1
        elif pd < nd:
            verdict = "OK_WEAK"           # found both places, but clearly closer here
            ok += 1
        else:
            verdict = "AMBIGUOUS"         # cannot tell the pages apart
            ambiguous += 1
        print(f"{semantic:26s} {str(pd):>5s} {str(nd):>5s} {max_d:>4d}  {verdict}")

    print("-" * len(header))
    print(f"discriminating: {ok}/{len(CASES)}   ambiguous:{ambiguous}   not_registered:{absent}")

    # Extra negatives: report the second-closest page for the join control.
    print()
    print("extra negatives for the join affordance (must NOT appear on another page)")
    for semantic, frames in EXTRA_NEGATIVES.items():
        if semantic not in registered:
            continue
        for frame in frames:
            if not (RAW / frame).is_file():
                continue
            n = vision.find(RAW / frame, semantic)
            nd = None if n is None else n.distance
            print(f"  {semantic:24s} vs {frame:28s} -> {nd}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
