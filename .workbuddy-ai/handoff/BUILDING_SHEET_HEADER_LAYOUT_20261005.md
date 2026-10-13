# The selected building's upgrade sheet is drawn with the lab's layout

**Date:** 2026-10-05
**Change:** `winter_agent_v2/ocr.py` (`OCRPageClassifier`), `tests/test_building_detail_fallback.py`
**Family:** `KEEP_BUILDING_PRODUCTIVE / OPEN_BUILDING_UPGRADE / BUILDING_UPGRADE_PANEL_NOT_PROVEN`
**Ledger size at measurement:** 107 rows — 106 `FAILURE`, 1 `SUCCESS`
**Commit:** `ad7c9ad` on `codex/production-pin-recovery`
**Delivery:** `repin_production --to ad7c9ad` → `CLEAN_OUTSIDE_DATA`;
`check_mainline.py` → `MAINLINE_OK`; `gui_wiring_verify.py` → 19/19, mismatched 0.
Panel-side code untouched, so no panel restart was needed.
**Regression A/B:** the 21 test files that touch the classifier, run with and without
this change, produce an **identical failing set** (15 pre-existing reds); `ocr.py`
sha256 verified identical after the revert-and-restore. 0 new reds; 5 tests added.
**Live note:** `winter_agent_v2/*` is re-imported from disk every cycle, so editing the
pin worktree goes live on the next cycle — this change had already been exercised in
production before it was committed (§5.2).

---

## 1. What was wrong

`OPEN_BUILDING_UPGRADE` taps the selected building's own 升级 control. The tap works and the
sheet opens — but the reader cannot name it, so the verifier refuses.

The episode says so itself. Every one of the 107 rows:

```
observed_change   PAGE_CHANGED          <- the client did move to another page
recognition_error ''                   <- nothing refused the target
after_screenshot  present              <- the after-frame was captured
state_after       non-empty
after_page        UNKNOWN              <- and this is the only thing missing
```

and the verifier's own evidence:

```json
{"page_before": "HOME", "page_after": "UNKNOWN", "upgrade_dialog_visible": null}
```

`OPEN_BUILDING_UPGRADE` is judged by (`winter_agent_v2/runtime.py`):

```python
b.page is Page.HOME and a.page is Page.BUILDING
and a.building.get("upgrade_dialog_visible") is True
```

so both missing pieces come from one place: `OCRPageClassifier.classify` never returned
`Page.BUILDING` for that frame.

## 2. Which frame it is

Real after-frame, `20261005_130747_314531_step_003_after_refresh_2_20261005T050825668096.png`
(720x1280) — the selected 城墙 sheet: title 城墙, headers 升级效果 and 需要条件, the
大熔炉 等级 24 prerequisite row, four resource rows each with a green check, and
立即完成 💎15,699 beside 升级 ⏱19:37:25.

**The sheet is open and unambiguous. The reader is what failed.**

## 3. Why it failed — measured, clause by clause

`classify` accepted a building sheet through two recognisers. On that frame, printed one
clause at a time:

| clause | old generic (`_building_upgrade_sheet_evidence`) | lab (`_research_lab_upgrade_sheet_evidence`) |
|---|---|---|
| `时间` at x 0.04-0.24, y 0.56-0.66 | **False** | not tested |
| `属性` at x 0.04-0.24, y 0.60-0.72 | **False** | not tested |
| `升级` at x 0.72-0.96, y 0.46-0.56 | **False** | not tested |
| a `N秒` duration | **False** | not tested |
| an `N+N` attribute value | **False** | not tested |
| `科研所` at x 0.35-0.65, y 0.10-0.20 | not tested | **False** (the title is 城墙) |
| `升级效果` at x 0.35-0.65, y 0.18-0.28 | not tested | **True** |
| `需要条件` at x 0.35-0.65, y 0.38-0.50 | not tested | **True** |
| `大熔炉` + `等级` with centre y 0.42-0.54 | not tested | **True** |
| `升级` at x 0.60-0.90, y 0.75-0.84 | not tested | **True** |

So each recogniser missed by exactly one kind of clause, and both misses are the same fact:

> **The client draws an ordinary building's upgrade sheet in the layout the Research
> Institute has always used.** The generic recogniser still tests the older two-column
> layout (`时间` / `属性`), which this client no longer draws; the lab recogniser tests the
> right layout but also demands the title 科研所.

## 4. The change

Split the sheet's *structure* from the *name*. `OCRPageClassifier` gains three small pieces:

* `_upgrade_sheet_placed(tokens, *, frame_size)` — the positioned-token list either
  recogniser needs (previously duplicated verbatim in both).
* `_upgrade_sheet_text(placed, text, *, x=None, y=None)` — exact string plus a band.
* `_current_upgrade_sheet_layout(placed)` — the header layout only:
  `升级效果` + `需要条件` + a `大熔炉 … 等级` row + a `升级` control in the button band.
  **The title is deliberately not part of it.**

Then:

```python
_building_upgrade_sheet_evidence  -> old two-column layout  OR  _current_upgrade_sheet_layout
_research_lab_upgrade_sheet_evidence -> _current_upgrade_sheet_layout AND title == 科研所
```

### What this deliberately does *not* do

* It never sets `upgradeable`, so it cannot authorize spending. Both docstrings already
  carried that contract; it is unchanged.
* It never invents a building identity. The layout proves *which page* this is, never
  *which building* — that stays `building_identity.BUILDING_IDS`, an exact table, so 城墙
  comes back as `id=UNKNOWN, name=null, identity_source=NO_BUILDING_NAME_TOKEN`.
* It does not touch the lab path's meaning: the lab is now "that sheet **and** its own title",
  which is what it always was.

Downstream, `RuleBrain` (brain.py:1838-1851) already handles `Page.BUILDING` +
`upgrade_dialog_visible` + *not* `upgradeable` by returning
`SAFE_STOP / building_identity_or_upgrade_conditions_unknown`. That is the designed outcome
and it is preserved.

## 5. Evidence

### 5.1 Frames, two-sided

`_verify_building_sheet_fix.py` / `_verify_building_sheet_verifier.py`: the recorded
after-frames, read by the deployed classifier and by an exact reproduction of the pre-fix
one (the old `_building_upgrade_sheet_evidence` body, restored through
`inspect.getattr_static` so the `staticmethod` descriptor survives).

The ledger groups the failures by what its own `page_after` said, and the groups behave
differently — see §6. Measured over **every** frame still on disk, pre-fix reproduced exactly
(`_verify_building_sheet_coverage.py`):

```
rows=107  frames gone=0
verdict tally: {'PASS': 78, 'INVALID': 29}      MISS 0

-- by the ledger's own page_after --
   UNKNOWN   PASS     77     <- this change
   BUILDING  PASS      1     <- this change (the live success of §5.2)
   BUILDING  INVALID  29     <- not covered; §6
```

So the change repairs **78 of the 107 (73%)**, `MISS 0` — it never fails to recognise a frame
it should. The 29 it does not reach are exactly the template-recognised ones.

### 5.2 Production

* 106 failures, the last at `2026-10-05T05:08:28Z` on rev `7f41a293`.
* The only attempt since: `2026-10-05T07:54:44Z`, rev `2c08116f` — **SUCCESS**.

That success is attributable, and not by proximity:

* its row carries `identity_source = "NO_BUILDING_NAME_TOKEN"`, and
  `_read_building_identity` is called from exactly one site for a sheet frame —
  `ocr.py:5613`, inside `if classified.page is Page.BUILDING and
  classified.building.get("upgrade_dialog_visible")`;
* on that same frame the old two-column clauses are **all False** (measured), so pre-fix
  `classify` returned `UNKNOWN` and could not have reached that site;
* the header clauses are all True, and the header clause is this change.

⇒ the success was produced by this change, on the first cycle that ran it.

**Operational note.** The pin worktree *is* the production code root, and `run_live.py`
re-imports `winter_agent_v2/*` from disk every cycle. Editing the pin tree in place therefore
goes live on the next cycle, before any commit. That is what happened here (the successful
episode's run dir is `runtime_auto/20261005_155409_646498`, minutes after the edit). It is
not a defect in the delivery chain — it is a property of it, and worth knowing.

## 6. What this change does NOT cover — the other 29 rows, with the diagnosis

29 of the failures recorded `page_after = BUILDING`, i.e. **the template layer did name the
page** — those frames were never UNKNOWN. They still failed, because `upgrade_dialog_visible`
is set by exactly one thing: the text classifier's `building_sheet or research_lab_sheet`
branch (`ocr.py:1204-1207`). And the classifier only runs on frames the template could *not*
name:

```python
# ocr.py:5552
if primary.page is Page.UNKNOWN:
    ...
    classified = self.classifier.classify(result, frame_size=frame_size)
```

So for those frames the classification never happened, and the verifier's second clause could
not be produced by any code path. This is a trap rather than a gap:

> **When the template succeeds, the verifier's clause becomes unreachable.**

Two ways out, neither taken here because each is its own change with its own A/B:

1. Have the template-derived `Page.BUILDING` path also carry the navigation flag when the
   frame's own layout says upgrade sheet.
2. Move the layout evidence to the single choke point — `HybridVision.observe`, which wraps
   `_observe_inner` precisely because `_observe_inner` has one `return` per page and attaching
   anything at each of them has already failed twice in this module (see its own docstring).

Option 2 is the structurally honest one. It also needs care: `vision.py:2118` sets
`building={"upgradeable": True}` on a template match, so a change in that area must keep
"navigation proved" and "spending authorized" apart.

## 7. Repeatable instruments added

| file | what it answers |
|---|---|
| `_probe_building_sheet_two_layouts.py` | per frame, which clause of each recogniser matched |
| `_verify_building_sheet_fix.py` | deployed vs pre-fix page, with an INVALID tier |
| `_verify_building_sheet_verifier.py` | the verifier's own clause, both readers, both ledger groups |
| `_verify_building_sheet_coverage.py` | the same over every frame on disk, pre-fix reproduced exactly |
| `_probe_building_sheet_group_coverage.py` | the classifier's own verdict per ledger group |
| `_dissect_family.py` | reopen a `(goal, skill)` pair the ranking collapsed to one signature |

## 8. Acceptance criteria for a later reader

* `OPEN_BUILDING_UPGRADE` on a frame that carries the header layout must record
  `after_page = BUILDING` and `upgrade_dialog_visible = True`, and the episode must be
  `SUCCESS` with reason `BUILDING_UPGRADE_PANEL_OPENED`.
* `BUILDING_UPGRADE_PANEL_NOT_PROVEN` on revs at or after this change **shall not** carry a
  `page_after = UNKNOWN` row for a frame with the header layout.
* The lab path must be unchanged: a 科研所 sheet still yields `identity = RESEARCH_CENTER`.
* No episode may gain `upgradeable` from this change.
