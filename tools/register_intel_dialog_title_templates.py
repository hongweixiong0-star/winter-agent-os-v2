"""CAP-A01: the Intel dialog's title template bakes in the mission level.

The order for CAP-A01 listed two candidates and forbade a fix until they were
separated:

  (a) ``BTN_INTEL_VIEW_TARGET``'s ROI centre is off the 前往查看 control, so the tap
      lands elsewhere;
  (b) the beast mission dialog is replaced by the hero-journey dialog between the
      observation and the tap.

Measured on the archived frames, **neither is true**:

    parent frame live_beast_intel_probe.png (a real INTEL_BEAST_MISSION dialog)
        BTN_INTEL_VIEW_TARGET      d =  0   centre (0.500, 0.730) -> px (360, 934)
        OCR 前往查看              centre (360, 934)   conf 0.994
    ⇒ the ROI centre is on the control, to the pixel.  (a) is refuted.

    failing episode 2026-09-17T04:38:27, before frame
        popup = INTEL_BEAST_MISSION  mission_id = INTEL_BEAST_10  type = BEAST
    and the frame itself, read by eye and by OCR:
        title = 英雄之旅等级2          <-- it is the HERO JOURNEY dialog
    ⇒ the classification was wrong before the tap, and the tap did the right thing
      for the dialog that was actually on screen.  (b) is refuted too.

Why it was wrong: the discriminating title matchers could not fire.

    POPUP_INTEL_HERO_JOURNEY_TITLE   d = 16   threshold 8 (default)   -> MISS
    POPUP_INTEL_MASTER_BOUNTY_TITLE  d = 26   threshold 8 (default)   -> MISS
    TARGET_INTEL_BEAST_MISSION       d = 28   threshold 54 (anywhere) -> HIT

``TARGET_INTEL_BEAST_MISSION`` is an *anywhere* matcher with a deliberately loose
gate of 54, used to answer "does a mission card exist in the list".  It was allowed
to answer "which dialog is this" because the matchers that were supposed to know
could not see the frame -- and the reason they could not is that their crops contain
**the mission level**, which changes per mission:

    crop source live_intel_purple_axes_probe.png : 英雄之旅等级10
    failing frame                                : 英雄之旅等级2

(That frame is the 8th sighting of this project's most-repeated defect: a crop that
covers content the game varies.  See
knowledge/failure_patterns/vision/TEMPLATE_CROP_COVERS_THE_VARIABLE.md.)

What this tool found, and why it does not register anything
-----------------------------------------------------------
The obvious repair -- re-crop the title so the level is not in it -- was tried and
**measured, and it does not work**:

    candidate crop (232,284)-(355,328) taken from the 等级2 frame, hashed at size=16
    (the size SemanticROIVision uses for a fixed-ROI record):

        same ROI on 等级2 frame      d =   0
        same ROI on 等级10 frame     d = 131
        same ROI on beast dialog     d = 126
        same ROI on master bounty    d = 115

The dialog title is a *centred* string, so the level's width shifts the invariant
part of it by 7-14 px -- and at this crop size one dhash cell is ~2.6 px wide.  Text
hashed at size=16 cannot absorb a shift of that many cells.  Registering one more
instance per level would measure perfectly (d=0 on its own frame) and cover only the
levels that happen to have been seen, which is the enumeration treadmill the crop
lesson warns about.

So the shipped fix is in ``winter_agent_v2/ocr.py``: ``_read_intel_dialog_title``
reads the title text (0.996-1.000 confidence on all four dialogs) and decides the
dialog's kind from it.  See ``INTEL_DIALOG_TITLES`` there for the measured table, and
``tests/test_intel_dialog_typing.py`` for what it pins.

Usage
-----
    python tools/register_intel_dialog_title_templates.py

Prints the measurement that refuted the crop approach.  ``--apply`` refuses, on
purpose: the numbers above are why.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"
# The candidate crop is written to a temp directory rather than into
# dataset/candidate: this tool measured the crop and rejected it, so leaving an
# unregistered template-shaped file in the candidate tree would invite a future
# session to adopt it -- which is the trap this tool exists to prevent.
import tempfile  # noqa: E402

OUT_DIR = Path(tempfile.gettempdir()) / "winter_intel_dialog_title_probe"

# The two observed levels of the same dialog.  Both are positives for the semantic.
LEVEL10_FRAME = ROOT / "dataset" / "raw" / "live_intel_purple_axes_probe.png"
LEVEL2_FRAME = ROOT / "dataset" / "raw" / "live_runtime/live_runtime_step_005_before_20260917T043816219622.png"

# A real beast-mission dialog and a real master-bounty dialog: negatives for the
# hero-journey semantic, and the frames the competing generic matcher must still
# classify the other way.
BEAST_FRAME = ROOT / "dataset" / "raw" / "live_beast_intel_probe.png"
BOUNTY_FRAME = ROOT / "dataset" / "raw" / "live_intel_orange_rabbit_probe.png"

SPECS: dict[str, dict] = {
    # 英雄之旅 is four centred characters; the level follows them.  OCR bounds
    # measured on both frames (720x1280):
    #   等级10: whole string x 237..483, so 英雄之旅 ends near x 360
    #   等级2 : whole string x 244..476, so 英雄之旅 ends near x 377
    # The crop therefore stops at x 355, which is inside 英雄之旅 on the level-2
    # frame and just past it on the level-10 frame -- one character of the string is
    # given up deliberately to keep 等级 out of the template.
    "POPUP_INTEL_HERO_JOURNEY_TITLE": {
        "box": (232, 284, 355, 328),
        "source_frame": LEVEL2_FRAME,
        "template_id": "popup_intel_hero_journey_title__level_free",
        "note": ("the 英雄之旅 half of the dialog title, with 等级N excluded: the "
                 "level is exactly the content the game varies, and baking it in is "
                 "why a level-10 crop could not see a level-2 dialog"),
    },
}


def crop(source: Path, box: tuple[int, int, int, int], dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image.crop(box).save(dest)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    # The manifest is read only so the measurement below runs against the records the
    # project actually has.  Nothing in this tool writes it: see the docstring.
    json.loads(MANIFEST.read_text(encoding="utf-8"))
    for spec in SPECS.values():
        if not Path(spec["source_frame"]).is_file():
            print(f"REFUSING: source frame missing: {spec['source_frame']}")
            return 2

    # 1. write the candidate crops somewhere measurable
    candidates: dict[str, Path] = {}
    for semantic, spec in SPECS.items():
        dest = OUT_DIR / f"{spec['template_id']}.png"
        crop(Path(spec["source_frame"]), spec["box"], dest)
        candidates[semantic] = dest
        print(f"cropped {semantic:34s} {spec['box']} -> {dest.name}")

    # 2. measure with the real matcher, over every frame of interest
    from winter_agent_v2.vision import SemanticROIVision

    names = ["POPUP_INTEL_HERO_JOURNEY_TITLE", "POPUP_INTEL_MASTER_BOUNTY_TITLE",
             "TARGET_INTEL_BEAST_MISSION", "TARGET_INTEL_BEAST_MISSION_BLUE"]
    frames = {
        "level10 (crop source)": LEVEL10_FRAME,
        "level2  (failure)": LEVEL2_FRAME,
        "beast dialog": BEAST_FRAME,
        "master bounty": BOUNTY_FRAME,
    }
    vision = SemanticROIVision(MANIFEST, max_distance=64)
    print("\n-- as-is (threshold 8 unless overridden) --")
    print(f"{'frame':24s}" + "".join(f"{n.replace('POPUP_INTEL_', '').replace('TARGET_', '')[:20]:>22s}" for n in names))
    for label, frame in frames.items():
        row = []
        for name in names:
            match = vision.find(frame, name) if frame.is_file() else None
            row.append(f"d={match.distance:3d}" if match else "MISS")
        print(f"{label:24s}" + "".join(f"{cell:>22s}" for cell in row))

    # 3. how far apart are the two levels on the new crop, and how far is it from
    #    the frames it must not fire on?
    print("\n-- the candidate crop, measured everywhere --")
    from winter_agent_v2.image_hash import dhash, hamming  # noqa: E402

    # size=16 is what SemanticROIVision uses for a fixed-ROI record, so these
    # numbers are directly comparable to the d= column above.
    probe_crop = Image.open(candidates["POPUP_INTEL_HERO_JOURNEY_TITLE"])
    reference = dhash(probe_crop, size=16)
    for label, frame in frames.items():
        if not frame.is_file():
            continue
        with Image.open(frame) as image:
            region = image.crop(SPECS["POPUP_INTEL_HERO_JOURNEY_TITLE"]["box"])
        print(f"  same ROI on {label:24s} d={hamming(reference, dhash(region, size=16)):3d}")

    print("\nThe shipped fix is winter_agent_v2/ocr.py::_read_intel_dialog_title, which "
          "reads the title text.  Nothing was registered: the crop above measures d=131 "
          "between two real levels of the same dialog, so a template recorded from it "
          "could not work.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
