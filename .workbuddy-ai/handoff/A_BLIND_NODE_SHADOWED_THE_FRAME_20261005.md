# A blind node was shadowing the frame's own answer

**Date:** 2026-10-05
**Change:** `knowledge/execution/backend_routing.json` (data), `tests/test_a_blind_node_does_not_shadow_the_frame_itself.py`
**Families:** `OPEN_TASK_FROM_QUICK_PANEL_BUILDING` (103 failures), `OPEN_TASK_FROM_QUICK_PANEL_HERO_RECRUIT` (79)
**Ledger size at measurement:** 357 and 326 attempts

---

## 1. What was wrong

Both skills preferred a MAA recognition node. On the frames where its template missed, the step
died with no input at all:

```
failure_type       SEMANTIC_TARGET_NOT_VERIFIED
recognition_error  MAA_TEMPLATE:NO_MATCH:score≈0.46:gate=0.7/0.75
duration           0.06 - 0.13 s
after_screenshot   ""                  <- nothing was tapped
```

and the episode's own `state_before` already carried the row:

```json
{"open": true, "rows": [
   {"key": "BUILDING", "control": "ARROW", "arrow_norm": [0.5618, 0.343], "status": "IDLE"},
   ...]}
```

A recognition miss on the MAA path does **not** fall through — deliberately, because a
position-blind matcher must not become a blind tap (pinned by
`test_executor_router.test_recognition_miss_blocks_instead_of_falling_back_to_a_blind_matcher`).
So the runtime resolver that reads the row off the current frame was never consulted, even though
it answers on every one of those frames.

## 2. Why the node cannot work, in one line

It carries a **fixed roi** (`[130, 279, 189, 162]` / `[0, 448, 268, 166]`) while the quick panel
draws the row wherever its own scroll leaves it. The x is a constant (the panel's right-hand
column); **the y wanders** — across the recorded rows it is read at 0.343, 0.3648, 0.4102, 0.4273…
A rect cropped from one scroll position cannot cover that. This is the same geometric failure the
`OPEN_BUILDING_UPGRADE` node was retired for on 2026-10-02 ("the window contains snow and a wall").

Their provenance already said as much:

* `QUICK_PANEL_ROW_BUILDING` — `validation: "GENERATED_ONLY"`, `source: "…V2_NATIVE fallback
  (generator unavailable)"`, `trigger: "runtime unresolved after 1 attempt(s)"`;
* `QUICK_PANEL_ROW_HERO_RECRUIT` — `validation: "NONE"`, `corpus_sufficient: false`.

Neither was ever drawn on a real frame for visual check.

## 3. The rule this follows

`executor_router`'s module docstring, quoted in `tests/test_unvalidated_node_keeps_adb.py`:

> recognition — Migrated per semantic, only after a node is authored *and* drawn on a real frame
> for visual check, and only after an A/B shows it is not worse than the legacy matcher. … The
> operator's rule "if MAA did not improve it, keep ADB" is enforced by the routing file.

## 4. The A/B (this is the part that licenses the change)

`_ab_quick_panel_row_routing.py` — computable from the ledger alone, because
`_dictionary_hint` answers `QUICK_PANEL_ROW_<KEY>` from `frame.quick_panel.rows[key]["arrow_norm"]`,
which every episode already recorded. No screenshot, no OCR, no device.

| skill | frames MAA got right | frames MAA missed |
|---|---|---|
| `OPEN_TASK_FROM_QUICK_PANEL_BUILDING` | **254 / 254** answered by ADB | **86 / 103** answered (17 silent) |
| `OPEN_TASK_FROM_QUICK_PANEL_HERO_RECRUIT` | **247 / 247** answered by ADB | **79 / 79** answered |

**Not worse than the legacy matcher**: on the frames the node got right the ADB path answers too,
so nothing is lost, and 165 taps are gained. The 17 silent BUILDING frames were already failures,
so they are not a regression either.

## 5. The change

Per-skill, following the two precedents (`SEARCH_RESOURCE`, `OPEN_BUILDING_UPGRADE`):

```diff
-  "preferred": "MAA",
+  "preferred": "ADB",
-  "recognition_backend": "MAA",
+  "recognition_backend": "LEGACY",
-  "recognition": { "QUICK_PANEL_ROW_…": { …TEMPLATE… } },          (removed)
+  evidence.demoted_at / demotion_reason / measured_record          (added)
+  not_migrated["<SKILL>_RECOGNITION"] = {semantic, reason, measured_at}
```

`fallback` is **unchanged at `ADB`** (it already was). The precedents keep `fallback: MAA`, but that
difference is theirs, not a rule: **capture** is decided at the device level
(`device.preferred: MAA`, 8.92 ms vs ADB's 324 ms over a 20-sample live A/B), so a skill-level
fallback of ADB does not cost capture. Changing it would be a behaviour change this round has no
measurement for, so it was left alone.

The `recognition` dict is **removed**, not merely shadowed by the preference: that is what the two
precedents look like, and leaving it would let any later `fallback: MAA` — or any caller of
`recognition_node` directly — resurrect a matcher this change measured as blind. The node's
provenance is not lost: it stays in `evidence.autogen_owned_recognition` / `pipeline_node_path`,
and the pipeline node file stays on disk.

## 6. Evidence

* `tests/test_a_blind_node_does_not_shadow_the_frame_itself.py`, 6 tests, pins **both halves** —
  the route that makes the resolver reachable *and* the resolver's answer — because the previous
  round's fix was lost with only one half asserted.
* Mutation, **on a copy of the tree** (the routing file is read by production every cycle, so it
  must not be mutated in place): putting the node and the MAA preference back fails exactly four
  tests — the three that assert on the file, plus `test_no_other_skill_lost_its_node_to_this_change`
  — while the two that exercise the resolver itself stay green, which is correct: the resolver does
  not read the routing file.
* The first mutation attempt was invalid and is recorded rather than hidden: the copy was missing
  `knowledge/ui/semantic_dictionary.json`, so the two resolver tests failed for a harness reason and
  read as signal. Re-run with the dictionary copied, the unmutated copy was 6/6 and the mutation
  produced exactly the predicted four.

## 7. What this does NOT cover

`OPEN_INFANTRY_TRAINING` (64 failures, 64/64 with an empty after-frame) looks like the same family
but is **not**: it runs on ADB with `recognition_backend: V2`, its `recognition_error` is
`UNKNOWN_NAV:PROVIDER_ANSWERED_NOTHING`, and its `decision_reason` is
`panel_open_but_training_unread_so_the_page_that_answers_it_is_the_step` — the training **section**
was not readable on the frame, so there was no row to point at. That needs its own measurement:
does the panel reader miss the training section, or was the section genuinely not drawn?

## 8. Acceptance criteria for a later reader

* `OPEN_TASK_FROM_QUICK_PANEL_BUILDING` / `…_HERO_RECRUIT` on revs at or after this change must
  record a **non-empty `after_screenshot`** and a duration in seconds, not milliseconds. A step
  that still records its old 0.06 s and an empty after-frame has not been fixed.
* `MAA_TEMPLATE:NO_MATCH` **shall not** recur as the `recognition_error` of these two skills.
* `RoutingTable.load().route(skill).recognition` must stay empty for both.
