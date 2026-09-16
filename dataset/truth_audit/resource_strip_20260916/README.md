# Resource strip gate (2026-09-16)

Frames that pin the corrected resource-tab ceiling in `winter_agent_v2/vision.py`.

## What was wrong

`SELECT_RESOURCE` was the last blocker on the gather chain: `SEARCH_RESOURCE`
succeeded and the chain then stopped, every time.  The first hypothesis was that
the strip geometry (pitch 157 px) had drifted on the current client.

**That hypothesis is refuted.**  Measured on frames whose selected tab is known
(`resource_cells_20260914_120027`, where each of MEAT/WOOD/COAL/IRON is selected in
turn), the bracket advances by **157.0 / 158.0 / 157.0 px** and the absolute
positions match the configured nominal to within 1 px.  The geometry is correct.

The real defect is one number.  On `live_fail_233727` the bracket sits on tab
index 1 at x=172, which predicts 生肉 (MEAT) at x=486 -- and the frame really does
show 生肉 starting at about 486, confirmed independently by scanning offsets and
asking which one puts the gatherable templates on their own cells (it returns
offset +399 and bracket index 1.0).  So the model was right and the **gate** refused
it: the crop scores **6.49** against a ceiling of **6.0**.

## The two populations (10 frames with verified anchors)

| observation | n | min | median | max |
|---|---:|---:|---:|---:|
| correct -- predicted position vs its own template | 27 | 0.00 | 5.34 | **6.49** |
| wrong -- same cell, another template | 27 | **10.65** | 14.77 | 16.17 |
| wrong -- non-gatherable tab vs any template | 10 | 14.74 | 19.41 | 25.09 |

The ceiling has to satisfy `6.49 < gate < 10.65`.  It was **6.0**, i.e. below the
largest value its own calibration frames produce -- the frames measuring 6.45 and
6.49 were rejected by it.  The value is now **8.0**: 1.51 of headroom above the
worst correct observation, 2.65 below the best wrong one.  The identity margin gate
is unchanged at 4.0 and was never binding (the live frames' correct reading has a
margin of 8.00).

## Files

* `live_fail_233727`, `live_fail_233739` -- the two production failures.  Both must
  now resolve to `GIANT_BEAST` (tab index 1) with a MEAT tap target of 0.7757.
* `live_fail_160609` -- the earlier failure, bracket on index 2, resolves to
  `SAWMILL`.
