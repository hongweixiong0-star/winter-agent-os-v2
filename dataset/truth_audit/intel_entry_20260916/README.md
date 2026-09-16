# OPEN_INTEL entry recognition (WB-R19-OPEN-INTEL-MAA-RECOVERY)

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
