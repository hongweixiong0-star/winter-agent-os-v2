"""Archive the OPEN_INTEL recognition evidence under a protected directory.

tests/ may not reference dataset/raw or dataset/evidence: those are prunable and
tests/test_evidence_integrity.py fails the suite if a test references them.  The
frames the corpus gate is built on are copied here with a README that states what
each one demonstrates.
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DST = ROOT / "dataset/truth_audit/intel_entry_20260916"

ITEMS = {
    # The six 2026-09-16 07:05-07:11 failures: the control is on screen 93 px
    # below the registration ROI.  These are the frames this order exists for.
    "fail1": "dataset/raw/control_panel/runtime_auto/intel_pins_20260915_230510_nav_00/intel_pins_20260915_230510_nav_00_step_002_before_20260915T230548379879.png",
    "fail2": "dataset/raw/control_panel/runtime_auto/intel_pins_20260915_230510_nav_00/intel_pins_20260915_230510_nav_00_step_001_before_20260915T230612978098.png",
    "fail3": "dataset/raw/control_panel/runtime_auto/intel_pins_20260915_230917_nav_01/intel_pins_20260915_230917_nav_01_step_001_before_20260915T231108075082.png",
    # Day theme, control at the registration ROI.
    "day_ok": "dataset/raw/live_runtime/live_runtime_step_001_before_20260915T133445437576.png",
    # Night theme: same control, same place, different tint -- the day template
    # alone scored 0.390-0.448 on these, which is why two more templates were
    # registered.
    "night_a": "dataset/raw/live_runtime/live_runtime_step_001_before_20260914T131236556151.png",
    "night_b": "dataset/raw/live_runtime/live_runtime_step_001_before_20260914T131355670095.png",
    # Control-absent pages: the world-map HUD is not on screen.
    "neg_home": "dataset/raw/control_panel/probe/live_page_20260915_151524.png",
    "neg_intel": "dataset/raw/control_panel/runtime_auto/codex_0ba_0bb_live_20260915/codex_0ba_0bb_live_20260915_step_004_before_20260915T123110729514.png",
    "neg_gather_panel": "dataset/raw/live_runtime/live_runtime_step_003_before_20260915T160609443785.png",
}

README = """# OPEN_INTEL entry recognition (WB-R19-OPEN-INTEL-MAA-RECOVERY)

Frames the corpus gate for `BTN_OPEN_INTEL_WILD_HUD` is built on.

## What the control actually is

The blue rounded-square button with the white ring (the world-map HUD menu) at
x_norm 0.925.  It is **not** MAP-exclusive: BEAST and EXPLORATION keep the
world-map HUD visible and score 0.86-0.915 there, so the discriminator cannot be
"is this control on screen" but "which page asks for it" -- the skill is gated on
`Page.MAP`, and on the pages that are not MAP-derived (INTEL, POPUP, HOME, MARCH,
ALLIANCE, resource detail) the nearest match is 36 or worse.

## The two axes of variation

* **position** - the right-hand button stack is bottom-anchored, so the button
  sits at y_norm 0.6727 in one layout and 0.7453 in another, 93 px apart.  On the
  six failing frames the fixed ROI held empty sky (phash 34-38 against a threshold
  of 24) while the control was demonstrably present lower down (near-exact phash
  distance 2, ccoeff 0.945).  A ROI that is both "where it is" and "where to look"
  cannot express that.
* **theme** - the day/night cycle repaints the HUD.  The two `night_*` frames show
  the same control at the same place, but the day-colour template scored only
  0.390-0.448 on them.

## Measured separation (77 positives, 369 negatives, real `find()` path)

| | n | min | median | max |
|---|---:|---:|---:|---:|
| positive | 77 | 0 | 9 | 29 |
| negative | 369 | 28 | 40 | 44 |

The two populations **overlap**, so no threshold reaches 100% recall with zero
false positives.  The threshold was therefore left at its previous value of 24:
recall 72/77 (93.5%), 0 false positives, worst accepted positive 24, best
negative 28.  Raising it to catch the last five would put the threshold on top of
a negative frame, which is what the work order forbids.

## Files

* `fail1`..`fail3` - three of the six failures that motivated the order.  The
  control is visible at y_norm 0.7453.
* `day_ok` - day theme, control at the registration ROI (y_norm 0.6727).
* `night_a`, `night_b` - night theme; these are the parents of the two registered
  night templates.
* `neg_home`, `neg_intel`, `neg_gather_panel` - pages where the world-map HUD is
  not on screen, so recognition must refuse.
"""


def main() -> int:
    DST.mkdir(parents=True, exist_ok=True)
    for tag, rel in ITEMS.items():
        src = ROOT / rel
        if not src.exists():
            print("MISSING", rel)
            continue
        target = DST / ("%s__%s" % (tag, src.name))
        shutil.copyfile(src, target)
        print("archived %-46s %d" % (target.name, target.stat().st_size))
    (DST / "README.md").write_text(README, encoding="utf-8")
    print("wrote README.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
