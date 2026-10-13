# The upgrade was authorized by a field with two writers of different strength

**Date:** 2026-10-05
**Change:** `winter_agent_v2/brain.py` (one gate at the spend site),
`tests/test_build_verifier.py`, `tests/test_building_upgrade_entry_target.py`
**Family:** `KEEP_BUILDING_PRODUCTIVE`, the `BUILDING_UPGRADE` spend decision
**Found while looking for something else:** the residual `OPEN_BUILDING_UPGRADE` failures (§6)

---

## 1. What was found

`brain.py`'s spend decision reads one field:

```python
if world.page is Page.BUILDING and world.building.get("upgradeable"):
    return Decision("BUILDING_UPGRADE", ...)
```

and that field has **two writers of different strength**:

| writer | basis | what it proves |
|---|---|---|
| `ocr.py` `_read_research_lab_upgrade_control` | `CURRENT_FRAME_GREEN_REQUIREMENTS_AND_BLUE_BUTTON` | every prerequisite row carries the client's green check **and** the 升级 control is the enabled blue one |
| `vision.py` template `BTN_BUILD_UPGRADE` | a template match | "the 升级 control is drawn" — which a **greyed-out** control also satisfies |

Both write the same key and **nothing downstream can tell them apart**. The route's own guard
(`_goal_route() == "BUILDING"`) refuses only when the field is **absent**:

> "Do not let generic exploration tap its spend control when the building identity, cost, or
> strategy checks are still unknown."

So a frame whose identity was never read, carrying the template's weaker `upgradeable`, came out of
`decide` as `BUILDING_UPGRADE`.

## 2. The measurement

* **30** episodes end on `Page.BUILDING` with `upgradeable=True`. **All 30** read
  `id=UNKNOWN, name=None, identity_source=NO_BUILDING_NAME_TOKEN`.
* Reproduced from the real state of episode `01:49:05`, through `decide` with the BUILDING route as
  the episode's goal uses:

```
as recorded                        -> BUILDING_UPGRADE / building_prerequisites_satisfied
+ upgrade_dialog_visible=True      -> BUILDING_UPGRADE / building_prerequisites_satisfied
+ dialog=True, upgradeable absent  -> SAFE_STOP / building_identity_or_upgrade_conditions_unknown
```

The third line is the design's intent, and it works — it is simply bypassed whenever the weaker
writer set the field.

* **`BUILDING_UPGRADE` has 0 rows in the ledger.** It has never spent.

**Why it never spent is an accident, not a guard**: that state only arises from a *failed*
`OPEN_BUILDING_UPGRADE`, and the failure ends the session before the brain is asked again. An
accident of ordering is exactly the kind of thing this project does not leave standing.

**And the spend could never have been credited anyway**: `verify_building_upgrade` requires
`before.building["id"] == building_id`. A spend on an identity-less frame is unverifiable as well
as unsafe.

## 3. The change

The spend now needs an identity the client actually named:

```python
_named_id = str(_building.get("id") or "").strip().upper()
_identity_known = bool(str(_building.get("name") or "").strip()) or _named_id not in {
    "", "UNKNOWN", "NONE",
}
if not _identity_known:
    return Decision("SAFE_STOP", "building_upgrade_needs_a_known_identity", 1.0, "switch_task")
```

**A name is enough**: a floating label read (`26 仓库`) names the building even when the catalogue
lookup did not — the same fact `verify_selected_building_upgrade_panel_opened` calls
`identity_known`. `"UNKNOWN"` counts as **unknown** here, even though that verifier accepts it as a
non-empty string, because for a spend the difference is the whole question.

## 4. Evidence

* All **30** recorded states now answer `SAFE_STOP / building_upgrade_needs_a_known_identity`
  (verified by replaying them through `decide`).
* Constructed states with a `name`, and with a catalogued `id`, still answer `BUILDING_UPGRADE` —
  the gate is about the identity, not about refusing upgrades.
* Tests: four new cases in `test_building_upgrade_entry_target.py` (the recorded state refused; a
  named building and a catalogued id still spend; the only difference between refusing and spending
  is the identity).
* `test_build_verifier.test_brain_selects_verified_build_skill` went red, and that was the A/B
  discipline working: it observed a real frame through `SemanticWorldVision` **alone**, which is the
  template layer and therefore carries no identity (the identity comes from `HybridVision`'s OCR
  enrichment — `vision.py`'s own comment says so, and names that very frame). It now asserts the
  pair: the same frame nameless stops and says why, and with the name the OCR enrichment adds it
  still picks a verifier-bound `BUILDING_UPGRADE` — which was the test's point all along.
* Regression A/B over the 17 test files that mention `BUILDING_UPGRADE` / `upgradeable` /
  `Page.BUILDING`, with and without (the baseline arm reverts the two test files as well, so the
  comparison is change-against-HEAD rather than a mixed state).

## 5. The general lesson

**A field with two writers of different strength has no provenance, and any consumer that trusts it
absolutely is trusting the weaker one half the time.** Here the weaker writer is a template that
cannot distinguish an enabled control from a disabled one, and the consumer is a resource spend.

Two shapes of fix exist and only one of them is safe: narrowing the consumer (this change) refuses
the strong case too if the provenance is unavailable; *labelling* the field with its basis
(`upgradeability_basis` already exists on the reader's output and is simply not carried into
`WorldState`) would let the consumer demand the strong one. The second is the better fix and is
**not** done here — it needs the template layer's own decision about what its match is worth, which
is a question this round did not have the evidence to settle.

## 6. Found while looking for something else: the residual `OPEN_BUILDING_UPGRADE` failures

The round set out to fix these. The current distribution (110 rows: 105 failures, 5 successes):

```
 75  page_after=UNKNOWN            -> the text-classifier path  (fixed by ad7c9ad)
 30  page_after=BUILDING, dialog=None  -> the template path     (NOT fixed)
  5  page_after=BUILDING, dialog=True  -> SUCCESS
```

On the 30, the template layer **names the page and sees the 升级 control** (`upgradeable=True`),
while the text classifier never runs — it is reached only when the template says `UNKNOWN`
(`ocr.py:5552`) — so `upgrade_dialog_visible`, the flag `OPEN_BUILDING_UPGRADE`'s verifier demands,
is never set. The fix is to let that page's own sheet evidence supply the flag whichever layer
named the page.

**That is deliberately not done in this commit**, and the reason is this commit: fixing the flag
makes the step succeed and the route continue into the very spend this change just gated. Order
matters — the gate first, the navigation proof second — and the gate is the half that was unsafe.

## 7. Acceptance criteria for a later reader

* `BUILDING_UPGRADE` **shall not** be selected on a frame whose `building` has no `name` and whose
  `id` is `UNKNOWN`/`NONE`/empty; the tick must record `building_upgrade_needs_a_known_identity`.
* A frame with a named or catalogued building must still answer `BUILDING_UPGRADE`.
* If `BUILDING_UPGRADE` ever gains rows while its states read `id=UNKNOWN`, this gate has been lost.
* The residual 30 may now be fixed: a step that succeeds there leads to a state that stops instead
  of spending, which is what the gate is for.
