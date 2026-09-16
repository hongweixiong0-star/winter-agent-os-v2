# vip_entry_20260917 — the external VIP-entry hypothesis, tested and rejected

**Why these frames exist.** `CAP-B09/B10 VIP` has been blocked by one question since the
start: where is the VIP entry? The external audit produced a testable hypothesis — 
`Shederator/wosbot`'s `VipRoutine.java` opens the VIP menu with a box at
`(430,48)-(530,85)` on a **720×1280 / MuMu** client, i.e. the same configuration V2 runs.

Under the project's rules that is a **measurement hypothesis, not a fact** (AGPL-3.0-only:
no code or asset may be copied either way), so it was tested on V2's own client with a
bounded probe (`tools/probe_vip_entry.py`: aborts unless the page is HOME or MAP, exactly
one tap, one bounded BACK if nothing changed).

| file | what it is |
|---|---|
| `01_before_*.png` | the HOME screen before the tap |
| `02_after_tap_*.png` | **the result: a `REAL_MONEY_OFFER` popup** |
| `04_after_dismiss_popup.png` | after one BACK: HOME, popup cleared |
| `probe_*.json` | both readings, the tap point, the OCR read at that point, the self-limits |

**Result: the hypothesis is WRONG on V2's client, and the hard block held.**

```
before : page=HOME
  OCR at the point: 6.0万 / 用 / 统帅4        <- the power / 统帅 HUD area
after  : page=POPUP popup=REAL_MONEY_OFFER rewards={'real_money_cost': True, 'action': 'BLOCKED'}
after one BACK: page=HOME popup=None
```

So on the Chinese client the top-centre area is **not** the VIP entry: tapping there opens
a paid offer. This is the third independent confirmation today that
`DISMISS_REAL_MONEY_OFFER` blocks the paid surface correctly, and it is exactly why the
rule "external coordinates are hypotheses" exists — the two clients differ in UI version
and language (Frostguard's strings are English).

**What the HOME screen actually exposes** (full-frame OCR, 28 high-confidence tokens):
no `VIP` / `特权` / `贵族` / `会员` text anywhere. The only relevant entries are
`常规活动` (px 634–700, y 176–203) and `超值活动` (px 623–700, y 275–297) on the right edge,
plus the activity column seen in earlier frames (生存者试炼 / 万象杂货铺 / 联盟总动员 / 首充).

**Next precise step for VIP** (not done here — it is a discovery sub-task, not a patch):
probe those two panels one at a time with the same bounded shape, or check the
chief-profile panel's tabs; the candidate that shows a VIP level/expiry is the entry.
Register a template from that frame before writing any skill, and give the skill a
verifier that reads the *panel* (not just "a tap happened").

**Honest accounting.** The probe cost 1 action and produced a negative result. Negative
results are the cheap half of discovery: they remove a wrong hypothesis, they are
recorded with frames, and they leave the client in a known state.
