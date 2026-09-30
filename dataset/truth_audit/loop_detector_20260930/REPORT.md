# LOOP_DETECTOR_V1 — historical-episode replay proof

Operator directive (2026-09-30), the 必须证明 clause:

> 完成后用历史Episode和真实AUTO证明：LOOP_FALSE_POSITIVE / LOOP_DETECTED / LOOP_RECOVERED / AUTO_CONTINUED

This directory holds the **historical Episode** half. `AUTO_CONTINUED` is proved where it can
be — on a live run loop — in `tests/test_loop_detector_boundary.py`
(`test_the_goal_goes_back_to_the_scheduler_and_the_run_keeps_turning`).

| file | what it is |
| --- | --- |
| `replay_episodes.py` | the harness: replays `learning/episodes.jsonl` through the real detector |
| `replay_report.json` | its machine-readable output, including every detection and every retraction |
| `REPORT.md` | this file |

Re-run with:

```
.venv/Scripts/python.exe dataset/truth_audit/loop_detector_20260930/replay_episodes.py
```

Measurement: **2026-09-30, `learning/episodes.jsonl`, 10124 rows, 31 runs (trace_id), 128
flows, 0 unparseable.** The file is append-only and AUTO is live, so re-running moves the tail
by a few rows and the counts with it; the JSON records the row count it was produced from, and
every number below is tied to this one. The structural facts — which patterns fire, the defer
rung's bar, the five retractions — reproduce.

## What is reconstructed exactly, and what is not

* **Exact.** Every row carries the full `WorldState` on both sides of the step, so
  `relevant_state_hash` is recomputed from the *same five fields* the live path hashes, under
  the same `empty != none` rule (an unread march count stays `None`).
* **Approximated.** The live signature's `skill_id` / `semantic_target` come from a
  `SessionStep`; the episode carries `skill` (which mixes registered skills and step kinds)
  plus `control` and `action.kind`. The mapping is in `replay_report.json → mapping`; a
  different mapping moves the counts and the harness can be re-run.
* **Flows are not sessions.** A flow is `(trace_id, goal_id)`, which is longer than a
  production session (routes declare budgets of 5–12 steps). This is why
  `steps_until_first_deferral` is reported — a deferral the replay reaches may never be
  reached in production.
* **Detections are counted per repeat, not per incident.** A run of eight identical steps
  yields six detections, one per rung, because that is what the engine does with them.

## Two readings of `progress`, and why both are reported

`progress` is the *Goal*-level fact, and it can come from two places. Reporting only one would
misdescribe the system:

* **`declared`** — `goal_progress`, the episode's own record of whether the Goal advanced. This
  is what an adapter declaring `StepVerdict.progress` supplies, and it is the reading the
  design wants. **None of the four business adapters declares it yet.**
* **`outcome`** — `goal_progress` when present, else the step's own result. **This is what the
  engine does today** (`SessionEngine._signature_for` falls back to `progress_from_outcome`).

## The proof

| metric | `outcome` (what the engine does today) | `declared` (goal-level) | one detector per run | `page_only_navigation` (A/B) |
| --- | ---: | ---: | ---: | ---: |
| `LOOP_DETECTED` | **1445** | 1323 | 552 | 1742 |
| `LOOP_FALSE_POSITIVE` | **5** | 0 | 0 | 5 |
| `LOOP_DETECTED_NET` | 1440 | 1323 | 552 | 1737 |
| `LOOP_RECOVERED` | **142** | 134 | 54 | 155 |
| `LOOP_DEFERRED` | **223** | 146 | 13 | 224 |
| flows that reached `defer_goal` | 11 / 128 | 9 / 128 | 1 / 31 | 11 / 128 |
| steps to the first deferral (min / median) | **8 / 157** | 52 / 157 | 1639 / 1639 | 8 / 156 |
| …within a 5 / 8 / 12-step session budget | 0 / 2 / 2 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 2 / 2 |

All four patterns the directive names fire on real data: `AAA`, `ABAB`,
`SAME_ACTION_NO_PROGRESS`, `NAVIGATION_LOOP`.

**`LOOP_FALSE_POSITIVE = 5 / 1445 = 0.35 %`** and every one of them is in
`replay_report.json` with the frame that disproved it. One real case, verbatim:
`SCROLL_QUICK_PANEL_TASKS` scrolled `QUICK_PANEL_SCROLL_CURRENT` at stream line 6950 (rung
`defer_goal`), and the panel moved at line 6954 — `LOOP_FALSE_POSITIVE: progress arrived after
defer_goal`.

## Worked examples — one per pattern, each the flow's own block

Each block below is the **flow's** last entries, not contiguous file lines: rows from other
roles and Goals are interleaved in the stream, and rendering contiguous lines produced an
example that did not reproduce its own claim. All four are in `replay_report.json →
worked_examples`.

**AAA** — `OPEN_ALLIANCE` / `BTN_OPEN_ALLIANCE`, same page, three times consecutively
(lines 1253, 1281, 1303, signature `7a113273af`), `goal_progress` false each time.

**SAME_ACTION_NO_PROGRESS** — `CLOSE_POPUP` / `BTN_CLOSE` on `AUTO_DISCOVERY`: **60** failures
with `POPUP_CLOSE_NOT_PROVEN` across the flow (stream lines 1595–1715), every one on page
`POPUP`, every one with `goal_progress` *unread*. The detection at line 1695 is simply the
point at which the third consecutive identical failure landed in the window.

**ABAB** — `OPEN_INTEL` / `BACK` alternating at lines 173, 176, 177, 182
(`278b74e62c` / `7cfdd4dd12`).

**NAVIGATION_LOOP** — `SEARCH_RESOURCE → BACK → OPEN_MAP` cycled twice inside one
`AVOID_STAMINA_WASTE` flow (lines 515–529). Notably the two laps have **different** state
hashes (`fdc509c8c4` vs `b1ffc31fae`) — a reward popup on one lap and not the other. That is
why the pattern is periodic in the *move*, not in the whole signature: requiring the whole
signature to repeat would miss exactly the circuit a player is stuck in.

## Three findings the measurement produced

1. **The page-only navigation pattern was too loose, and it was tightened — measured as a
   controlled A/B on the same rows.** A page cycle alone fires on `HOME → ALLIANCE → HOME →
   ALLIANCE` where a *different* control is tapped on each visit: a client being used, not one
   walked in a circle. Adding `LoopSignature.move_key` (page **and** action) took
   `NAVIGATION_LOOP` from **569 to 272** and total detections from **1742 to 1445**, with every
   other pattern *identical* (AAA 614, `SAME_ACTION_NO_PROGRESS` 148, ABAB 411) -- which is what
   makes it a controlled comparison rather than two numbers from two days — while still catching the real circuit above. The pre-tightening
   class is kept in the harness as `_PageOnlyNavigation` so the number can be re-derived rather
   than remembered. Pinned by
   `test_two_pages_revisited_with_different_work_each_lap_are_not_a_navigation_loop` and
   `test_a_move_cycle_still_fires_when_the_state_and_verdict_differ_lap_to_lap`.

2. **The ladder is only ever spent on *consecutive* repeats — measured, not assumed.** All
   **223 / 223** `defer_goal` detections were confirmed escalations; none was reached across a
   gap. The mechanism is `_settle`'s stale branch: the moment the flow does something else, the
   tracked action's rung is dropped. Without it a move that fails once per round would climb to
   `defer_goal` over a whole run — answering the coarse question ("this Goal keeps failing",
   which `goal_utility.no_progress_streak` already handles between rounds) with fine-grained
   evidence. Pinned by `test_a_gap_restarts_the_ladder_at_its_cheapest_rung`.

3. **The defer rung is a high bar, so the risk of "it would defer everything" is refuted.**
   Reaching `defer_goal` needs 3 identical answers plus 5 confirmed escalations — 8 consecutive
   repeats. On real data the median flow needs 157 of its own steps to get there, only 11 of
   128 flows ever did, and **none** within a 5-step session; 2 within a 12-step one. So the
   detector's production effect is overwhelmingly the *cheap* rungs (907 of 1445 detections are
   `semantic_retry`), and a deferral happens only for genuinely pathological flows.

## The honest caveat about `LOOP_FALSE_POSITIVE`

Three of the five retractions happened at the **`defer_goal`** rung — and in the engine that
rung *ends the session on the spot* (`_terminal(..., continues=False)`), so the frame that
would have retracted the claim is never observed. In production those three are not retractions
at all; they are **wrongly deferred Goals**, and they present as `SESSION_DOMAIN_STUCK` with the
Goal handed back to the Scheduler.

Stated plainly: the 0.35 % figure is therefore **optimistic for the defer rung**, where the true
rate is 3/223 = 1.3 % of deferrals. It is recorded rather than tuned away, because the
alternative — a higher bar for the terminal rung — would delay the remedy for genuinely stuck
flows, and §7 already declares this ending recoverable (the Goal is deferred, AUTO continues).
A future change should be justified by a measurement of *wrongly deferred Goals*, which this
harness cannot produce on its own because it keeps feeding a flow the engine would have ended.
