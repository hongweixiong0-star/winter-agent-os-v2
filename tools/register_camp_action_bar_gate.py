"""Register the selected-building action bar as a gate, and prove the gate separates.

Why a gate and not just the reading
-----------------------------------
Reading the bar on every HOME frame broke a contract this codebase keeps on purpose:
``tests/test_ocr.py::test_hybrid_is_template_first`` pins that **a page the template
layer fully resolves is not OCR'd**, because HOME is the most common frame in the loop.
That test caught the first version of this work (backend calls 0 -> 1 on a plain city
frame), and it was right to.

No existing template can serve as the gate: on the action-bar frames every registered
control scores NO MATCH, ``BTN_UPGRADE`` included -- which is the gate the 仓库 render
uses.  A cheap *pixel* gate was tried first and measured, not assumed: the three controls
are pale plates on a dimmed city, and "fraction of pixels with min channel >= 185" over
their own band separates nothing (action-bar frames 0.037-0.363, ordinary HOME frames
0.003-0.944 -- see tools/probe_action_bar_gate.py).  So the gate is the project's own
mechanism: a template.

What is cropped, and why that and not the plate
-----------------------------------------------
The plates are translucent, so their pixels carry whatever city is behind them and a
hash over one would move with the camera.  The icon drawn inside the middle plate is
opaque, and measured on the twelve action-bar frames (720x1280):

    white up-arrow icon   x 338-381   y 860-903   1043-1044 px   on every frame

Two frames report a wider white bbox because snow on the ground passes the same
threshold; the icon's own 44x44 box is identical on all twelve.  That box is the crop.

Usage
-----
    python tools/register_camp_action_bar_gate.py            # register, then measure
    python tools/register_camp_action_bar_gate.py --check     # measure only

``--check`` is the useful one after any client change: it prints the distance on every
action-bar frame (must be inside the gate) and on frames that must NOT match.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"
OUT_DIR = ROOT / "dataset" / "candidate" / "camp_action_bar_20260922"

#: The kept evidence copy, not the prunable capture: a template whose parent frame has
#: been deleted cannot be re-cut, and the retention policy prunes dataset/raw.
SOURCE_FRAME = (ROOT / "dataset/truth_audit/camp_action_bar_20260922"
                / "camp_selected_action_bar__shield_camp__live_20260922T0747.png")
SOURCE_BOX = (338, 860, 382, 904)          # the white up-arrow, measured above
SEMANTIC = "TARGET_CAMP_ACTION_BAR"
TEMPLATE_ID = "target_camp_action_bar__shield_camp__20260922"

#: The bar has TWO renderings and the gate above only covers one of them, so a second record
#: carries the one control that is drawn identically in both.
#:
#: Measured 2026-09-22: a camp with a batch in training draws 详情 / 立即完成 / 加速 / 训练, has no
#: 升级, and moves 详情 and 训练 outward and ~0.030 up.  The up-arrow above is the 升级 plate's own
#: icon, so on that layout it scores exactly background -- 0.651, i.e. distance 22 against the
#: default 6 -- and ``_read_selected_building`` is never called, which is how a frame showing the
#: client's bar was recorded as no bar at all (2026-09-22 16:42:30 and 18:54:27).
#:
#: The replacement candidate is the 详情 plate's document glyph, because it is the one control both
#: layouts draw the same way.  Cropping each layout's own 详情 glyph and scoring it on all three live
#: frames:
#:
#:     详情 glyph from the IDLE frame  ->  IDLE 1.000   BUSY 0.969   BUSY 0.969
#:     详情 glyph from a BUSY frame    ->  IDLE 0.969   BUSY 1.000   BUSY 1.000
#:     升级 glyph (this record)        ->  IDLE 1.000   BUSY 0.651   BUSY 0.651
#:     训练 glyph from the IDLE frame  ->  IDLE 1.000   BUSY 0.929   BUSY 0.585
#:
#: So 训练 does *not* carry across (the hand and the badge overlap it differently per layout) and
#: 详情 does.  0.969 is distance 2 against the default 6, on both layouts, from either source.
#:
#: The 升级 record stays: it is measured and perfect on the layout it came from, and ``find`` returns
#: a match if any record for the semantic matches, so keeping both costs one template read and covers
#: the layouts independently.
BUSY_SOURCE_FRAME = (ROOT / "dataset/truth_audit/camp_action_bar_20260922"
                     / "camp_selected_action_bar__shield_camp__busy_queue__live_20260922T1642.png")
#: The 详情 plate's glyph.  Located from that frame's own OCR'd 详情 label -- read at (194, 874) px,
#: conf 0.995, centre -- and the glyph sat 61 px above it, as the registered 升级 gate does (its label
#: reads at y 943 and its box centres on 882).
BUSY_SOURCE_BOX = (172, 791, 216, 835)
BUSY_TEMPLATE_ID = "target_camp_action_bar__busy_bar_detail_glyph__20260922"

IDLE_LAYOUT_FRAME = (ROOT / "dataset/truth_audit/camp_action_bar_20260922"
                     / "camp_selected_action_bar__lancer_camp__idle__live_20260922T1709.png")

GOLD_RING_FRAME = (ROOT / "dataset/truth_audit/camp_action_bar_20260922"
                   / "camp_gold_ring_render__shield_camp__live_20260921T1307.png")
TRAINING_PAGE_FRAME = (ROOT / "dataset/truth_audit/camp_action_bar_20260922"
                       / "training_page__three_camp_tabs_and_queue__live_20260921T0953.png")


def action_bar_frames() -> list[tuple[str, Path]]:
    return [(tag, path) for tag, path, is_bar in _navigate_frames() if is_bar]


def ring_render_frames() -> list[tuple[str, Path]]:
    """``NAVIGATE_INFANTRY_CAMP`` frames that ended on the GOLD RING render instead.

    The gate must not fire on these: the ring render draws no action bar at all, which is
    the whole reason ``camp_ring.py`` exists.  Split out by the frame's own recorded state
    rather than by date, because the same skill ended on the bar in the morning of
    2026-09-22 and on the ring by 19:03 -- asserting "every NAVIGATE frame is a bar frame"
    is what made this check report a miss on a frame the gate was right about.
    """
    return [(tag, path) for tag, path, is_bar in _navigate_frames() if not is_bar]


def _navigate_frames() -> list[tuple[str, Path, bool]]:
    rows = []
    for line in (ROOT / "learning/episodes.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            episode = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(episode.get("execution_mode")) != "PRODUCTION":
            continue
        if str(episode.get("skill")) != "NAVIGATE_INFANTRY_CAMP":
            continue
        recorded = str(episode.get("recorded_at") or "")
        after = episode.get("after_screenshot")
        if recorded >= "2026-09-21T16:00" and after:
            training = (episode.get("state_after") or {}).get("training") or {}
            rows.append((recorded[11:16], Path(str(after)),
                         not training.get("navigation")))
    return rows


def home_frames_that_must_not_match() -> list[tuple[str, Path]]:
    """PRODUCTION frames that ended on HOME without the action bar."""
    rows = []
    for line in (ROOT / "learning/episodes.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            episode = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(episode.get("execution_mode")) != "PRODUCTION":
            continue
        if str(episode.get("skill")) == "NAVIGATE_INFANTRY_CAMP":
            continue
        state = episode.get("state_after") or {}
        after = episode.get("after_screenshot")
        if state.get("page") == "HOME" and after:
            rows.append((str(episode.get("recorded_at") or "")[5:16], Path(str(after))))
    return rows[:: max(1, len(rows) // 10)][:10]


def _write_record(payload: dict, source_frame: Path, box: tuple[int, int, int, int],
                  template_id: str, note: str) -> None:
    """Cut one crop out of one kept frame and point the manifest's record at it."""
    records = payload["records"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with Image.open(source_frame) as image:
        image = image.convert("RGB")
        width, height = image.size
        if (width, height) != (720, 1280):
            raise SystemExit(f"{source_frame.name}: unexpected size {image.size}")
        left, top, right, bottom = box
        crop = image.crop(box)
    template_path = OUT_DIR / f"{template_id}.png"
    crop.save(template_path)
    print(f"wrote {template_path.relative_to(ROOT)}  {crop.size}")

    record = {
        "semantic": SEMANTIC,
        "template_path": str(template_path.relative_to(ROOT)).replace("\\", "/"),
        "roi_norm": {
            "x_norm": round(left / width, 6),
            "y_norm": round(top / height, 6),
            "w_norm": round((right - left) / width, 6),
            "h_norm": round((bottom - top) / height, 6),
        },
        "source": str(source_frame.relative_to(ROOT)).replace("\\", "/"),
        "provenance": "LIVE_CLIENT",
        "reviewed_from": "LIVE_CLIENT_SCREENSHOT",
        "confidence": 0.99,
        "status": "CANDIDATE",
        "template_id": template_id,
        "parent_screenshot": str(source_frame.relative_to(ROOT)).replace("\\", "/"),
        "width": crop.size[0],
        "height": crop.size[1],
        "note": note,
    }
    existing = next(
        (r for r in records
         if r.get("semantic") == SEMANTIC and r.get("template_id") == template_id),
        None,
    )
    if existing is not None:
        existing.update(record)
        print(f"updated {SEMANTIC} [{template_id}]")
    else:
        records.append(record)
        print(f"added   {SEMANTIC} [{template_id}]")


def register() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    _write_record(
        payload, SOURCE_FRAME, SOURCE_BOX, TEMPLATE_ID,
        "The selected building's action bar, as a GATE for the OCR reading in "
        "ocr.read_selected_building_actions: the middle control's opaque icon, cropped "
        "from the 2026-09-22 render where all three plates are translucent.  Measured "
        "identical at x338-381 y860-903 on all twelve live frames that failed "
        "NAVIGATE_INFANTRY_CAMP between 16:24 and 23:47; it gates, it is not the tap "
        "target -- the 训练 label read off the frame is, so a moved bar still taps right.  "
        "It covers the IDLE bar only: that middle plate is 升级, and a camp with a batch "
        "in training draws 立即完成 there instead (see the second record).",
    )
    _write_record(
        payload, BUSY_SOURCE_FRAME, BUSY_SOURCE_BOX, BUSY_TEMPLATE_ID,
        "The same gate for the OTHER rendering of the bar: a camp with a batch in training, "
        "which draws 详情 / 立即完成 / 加速 / 训练 and no 升级.  Cropped from the 详情 plate's "
        "document glyph, because it is the one control both renderings draw the same way -- "
        "cropping each layout's own 详情 glyph and scoring it on all three live frames gives "
        "IDLE 1.000 BUSY 0.969 BUSY 0.969 from the idle crop and IDLE 0.969 BUSY 1.000 BUSY "
        "1.000 from the busy crop, i.e. distance <= 2 against the default 6, while the 升级 "
        "glyph above scores background (0.651, distance 22) on this layout and the 训练 glyph "
        "carries across neither (0.929 / 0.585).  Without it the reader is never called on a "
        "busy camp and a frame showing the client's own bar is recorded as having none.",
    )
    payload["count"] = len(payload["records"])
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    # indent=1 is what the manifest on disk uses.  These two writers used indent=2, and
    # measured 2026-09-23 that costs 7499 insertions / 7359 deletions for ONE added record --
    # every key of all 408 records re-indented -- which makes a registration unreviewable and
    # hides the real change inside the noise.
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"manifest records: {len(payload['records'])}")


def check() -> None:
    from winter_agent_v2.vision import SemanticROIVision

    vision = SemanticROIVision(MANIFEST)
    threshold = getattr(vision, "semantic_max_distance", {}).get(SEMANTIC, 6)
    print(f"gate for {SEMANTIC}: max_distance {threshold}")
    print("=" * 70)
    print("MUST MATCH  (the frames the route died on, plus one of each bar layout)")
    misses = 0
    must_match = list(action_bar_frames()) + [
        ("IDLE bar, evidence", IDLE_LAYOUT_FRAME),
        ("BUSY bar, evidence", BUSY_SOURCE_FRAME),
    ]
    for tag, path in must_match:
        if not path.exists():
            print(f"   {tag}  MISSING ON DISK")
            misses += 1
            continue
        match = vision.find(path, SEMANTIC)
        state = "hit " if match else "MISS"
        if not match:
            misses += 1
        distance = getattr(match, "distance", None)
        print(f"   {tag}  {state} distance={distance}")
    print("=" * 70)
    print("MUST NOT MATCH  (HOME frames without the bar, and the other two renders)")
    wrong = []
    negatives = home_frames_that_must_not_match()
    #: ``gate_also_matches__research_lab_selected__...`` is deliberately NOT listed here.  The bar is
    #: drawn for whatever building is selected, so the gate fires on a selected 仓库 as well -- the
    #: project's own evidence file is named for that, and it is not a defect: the gate is a cheap
    #: pre-filter and the reading behind it requires the name to be a barracks
    #: (``read_building_action_tokens`` returns ``camp == ""`` for anything else).  Listing it as a
    #: negative would be asserting something the measurement contradicts.
    for tag, path in negatives + [("gold-ring render", GOLD_RING_FRAME),
                                  ("training page", TRAINING_PAGE_FRAME)] \
            + [(f"ring render {tag}", path) for tag, path in ring_render_frames()]:
        if not path.exists():
            print(f"   {tag}  MISSING ON DISK")
            continue
        match = vision.find(path, SEMANTIC)
        if match is not None:
            wrong.append((tag, getattr(match, "distance", None)))
        print(f"   {tag:<18} {'hit' if match else 'no match':<9}"
              f" distance={getattr(match, 'distance', None)}")
    print()
    print(f"action-bar frames missed: {misses}")
    print(f"false positives: {wrong if wrong else 'none'}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="measure only, change nothing")
    args = parser.parse_args()
    if not args.check:
        register()
    check()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
