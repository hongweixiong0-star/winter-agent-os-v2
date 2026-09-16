# daily_entry_template_20260916 — the city daily-entry tap target, re-registered

**Why these frames exist.** `OPEN_DAILY` (HOME → DAILY) is the entry point of every
daily-mission capability, and on 2026-09-16T13:10Z the live loop failed it:

```
skill OPEN_DAILY   action TAP_SEMANTIC BTN_OPEN_DAILY   backend ADB
executed=false     error SEMANTIC_TARGET_NOT_VERIFIED
```

The semantic had one record, cut on **2026-09-08**.  Measured against the live city
frame it scored **distance 18 against a gate of 8**, while the city's other buttons
still hit (exploration d=0, alliance d=8, mail d=8–20 under its own gate of 24)
— so the frame was fine and only this template was stale.  Two things had changed
since 2026-09-08: the red claimable badge had left the icon, and the city drawn
behind it was a different one.

**Files**

| file | what it is |
|---|---|
| `00_live_home_20260916T131040Z.png` | the live city frame (720×1280) the replacement was cut from — `run_live.py --goal DAILY`, step 2 `before` |
| `01_home_frame_with_crop_and_tap_point.png` | same frame with the registered crop drawn in red and the point the executor actually taps marked in green |
| `02_zoom_crop_and_tap_point.png` | 3× zoom of the left column, so the crop and the tap point can be checked by eye |

**What was registered.** The left 2/3 of the icon circle — box `(12, 1026, 50, 1084)`,
normalized `x 0.016667 y 0.801562 w 0.052778 h 0.045312`, template
`dataset/candidate/daily_entry_20260916/btn_open_daily__live_20260916_home.png`,
semantic `BTN_OPEN_DAILY`.  The crop deliberately **excludes the badge corner**, so a
single record covers the claimable and the claimed states of the same control; the
2026-09-08 record is kept rather than replaced, because `find()` takes the minimum
distance over records and deleting evidence is not how this project retires anything.

**Why this crop, and not the old ROI with a bigger gate.**  Measured over all 3480
frames of `dataset/raw` (`tools/probe_daily_entry_gate.py`, recall proxy = the city/HUD
bottom-nav button, n=1104):

| candidate | recall (hud) | hits outside the proxy | distance on the 2026-09-08 frame |
|---|---:|---:|---:|
| existing (2026-09-08) | 24 (2.2%) | 0 | 2 |
| full circle incl. badge | 41 (3.7%) | 0 | 16 (miss) |
| lower band of the circle | 587 (53.2%) | 0 | 2 |
| **left 2/3 of the circle** | **1054 (95.5%)** | **1** | **6 (hit)** |

The single hit outside the proxy is `dataset/raw/legacy_resource_search.png`, which by
eye is a *city* frame of a different account whose bottom-nav buttons were faded — so
it is a true positive the proxy could not see, not a false one.  Raising the gate
instead would have "fixed" the symptom while leaving a 2.2%-recall tap target in place.

**Live evidence produced with it** (2026-09-16T13:44Z, `run_live.py --goal DAILY`):

```
1 OPEN_DAILY   HOME -> DAILY   verifier OK   {"before_home": true, "after_daily": true}
2 BACK         DAILY -> HOME   verifier OK   {"page_returned": true, ...}
3 SAFE_STOP     daily_panel_already_read_not_actionable
```

Step 2 exists because step 1 working exposed a second problem: the panel had nothing
claimable, and stopping *inside* it strands every later run — see
`dataset/truth_audit/daily_tasks_tab_20260916/`.

**Tests.** `tests/test_daily_entry_template.py` reads `00_` (positive: the semantic must
resolve, must be the 2026-09-16 record, and its tap point must land inside the icon) and
`02_` of the sibling set (negative: it must not resolve where the icon is not drawn).
These frames are archived here because `dataset/raw` is rotated by the retention pass and
a test that depends on it fails the suite.
