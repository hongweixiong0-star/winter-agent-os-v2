# LOOP_DETECTOR_V1 — the proof the directive asks for

Operator directive (2026-09-30), the 必须证明 clause, verbatim:

> **完成后用历史Episode和真实AUTO证明：** LOOP_FALSE_POSITIVE / LOOP_DETECTED / LOOP_RECOVERED / AUTO_CONTINUED

Four metric names, two halves of evidence. This directory holds both, and the second half is
possible only because the detector was deployed to production at 15:24 local (see *Provenance*).

| file | what it is |
| --- | --- |
| `replay_episodes.py` | harness 1: replays the **whole** `learning/episodes.jsonl` through the real detector |
| `replay_report.json` | its output: 5 readings, every detection, every retraction, 4 worked examples |
| `replay_sessions.py` | harness 2: replays **only the Session Engine's own steps**, one detector per session, and reads the live telemetry |
| `replay_sessions_report.json` | its output: the 26 real sessions, the revision audit, the AUTO_CONTINUED evidence, the deployed detector's own metrics |
| `REPORT.md` | this file |

```
.venv/Scripts/python.exe dataset/truth_audit/loop_detector_20260930/replay_episodes.py
.venv/Scripts/python.exe dataset/truth_audit/loop_detector_20260930/replay_sessions.py
```

## Provenance — read this before any number below

Three things move while this is read, and a count without them is not evidence:

* **The code revision.** Both reports carry `code_revision`. These were produced at
  **`014a4df1dd0f`**. It matters: the counting rules changed twice *after* the first version of
  this directory was written — `772c0f9` added the timeline fields, and `014a4df` made
  `LOOP_RECOVERED` require **verified progress** on the new action instead of merely a different
  action. On the same stream that change took `LOOP_RECOVERED` from **147 → 16** (`outcome`
  reading): the earlier figure was inflated roughly tenfold by counting "the flow moved on" as
  recovery. The number in this file is the corrected one.
* **The stream.** `learning/episodes.jsonl` is append-only and AUTO is live. Episode snapshot
  **10,253 rows, 31 runs (trace_id), 128 flows**; session snapshot the same 10,253 rows,
  **105 session steps, 26 sessions**. The last two digits drift between re-runs; the structural
  facts reproduce.
* **The deployment.** The pinned production revision is now `014a4df` — i.e. production **is
  running the detector**. That is new since the first draft of this report, and it confines the
  offline half's claims: see *Part 4*.

> ### ⚠ Correction — read with *Part 2* (`STILL_PENDING_AUDIT.md`, 2026-09-30)
>
> *Part 2* reconstructs each session step's outcome from the `result` column. It was written
> before anyone had checked whether that column means the same thing at every revision, and it
> does not. Two claims in *Part 2* are therefore wrong, and one scope limit follows:
>
> 1. The **"42 of the 105 steps"** figure is a property of the *recording code*, not of the runs.
>    All 42 were written before `fa476b6` (*fix(evidence): distinguish session progress from
>    failed clicks*), which is the commit that stopped `result` from being `FAILURE` for **every**
>    session step. Measured: pre-`fa476b6` **60/60** session steps are `FAILURE`-only; post-fix,
>    `goal_progress=True && result=FAILURE` is **0**. The repository's own `VERIFIER_CONFLICT`
>    detector (`state_truth.py:1532`) was firing on the same artefact — **5 pre-fix, 0 post-fix**,
>    all of them `FISHING_CAST_VERIFIED`.
> 2. *Part 2*'s session-scoped counts (`LOOP_DETECTED 23 / LOOP_RECOVERED 2 / LOOP_DEFERRED 3`)
>    are a **counterfactual**, not an observation: they answer "what would the detector have said
>    if these steps had been fed as `FAILED`". The live engine fed **2 of the 10** steps of the
>    session shown below and detected **nothing** (*Part 4*). So the ladder block below must not
>    be read as "the detector ran here" — it did not.
>
> **Scope limit:** session-scoped replay detections may not be counted toward the four headline
> metrics. *Part 1*, *Part 3*, `revision_audit` and `live_detector_telemetry` are unaffected —
> they read the stream, the run's own ledger, or `session_timeline.jsonl`, never `result`.
> Full measurement, the revision boundary and the threshold analysis: `STILL_PENDING_AUDIT.md`.

---

## Part 1 — historical episodes, over the whole stream

`progress` is the *Goal*-level fact and can come from two places; reporting only one would
misdescribe the system:

* **`declared`** — `goal_progress`, the episode's own record of whether the Goal advanced. What
  an adapter supplying `StepVerdict.progress` gives, and the reading the design wants.
* **`outcome`** — `goal_progress` when present, else the step's own result. **This is what the
  engine does today** (`SessionEngine._signature_for` falls back to `progress_from_outcome`).

`page_only_navigation` and `after_only_state` are controlled A/B readings of the **same rows**,
each reverting one design decision, so each change is a measurement rather than a claim.

| metric | `outcome` (engine today) | `declared` | one detector per run | `page_only_navigation` (A/B) | `after_only_state` (A/B) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `LOOP_DETECTED` | **1511** | 1387 | 596 | 1795 | 1496 |
| `LOOP_FALSE_POSITIVE` | **5** | 0 | 0 | 5 | 5 |
| `LOOP_DETECTED_NET` | 1506 | 1387 | 596 | 1790 | 1491 |
| `LOOP_RECOVERED` | **16** | 6 | 6 | 16 | 16 |
| `LOOP_DEFERRED` | **225** | 148 | 15 | 226 | 225 |
| flows that reached `defer_goal` | 11 / 128 | 9 / 128 | 1 / 31 | 11 / 128 | 11 / 128 |
| steps to the first deferral (min / median / max) | **8 / 157 / 1145** | 52 / 157 / 1145 | 1639 | 8 / 156 / 1145 | 8 / 157 / 1145 |
| …within a 5 / 8 / 12-step session budget | 0 / 2 / 2 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 2 / 2 | 0 / 2 / 2 |

All four patterns the directive names fire on real data: `AAA` 638, `ABAB` 436,
`SAME_ACTION_NO_PROGRESS` 142, `NAVIGATION_LOOP` 295.

Which rung the 1511 detections land on — the number that describes the detector's cost, and
63 % of it is the cheapest rung:

| rung | detections |
| --- | ---: |
| `semantic_retry` | 954 |
| `local_reobserve` | 155 |
| `widen_observe` | 95 |
| `feature_reopen` | 45 |
| `home_recovery` | 37 |
| `defer_goal` | 225 |

**`LOOP_FALSE_POSITIVE = 5 / 1511 = 0.33 %`**, and all five are in `replay_report.json` with
the frame that disproved them. One real case, verbatim: `SCROLL_QUICK_PANEL_TASKS` scrolled
`QUICK_PANEL_SCROLL_CURRENT` at stream line 6950 (rung `defer_goal`), and the panel moved at
line 6954 — `LOOP_FALSE_POSITIVE: progress arrived after defer_goal`.

### Worked examples — one per pattern, each the flow's own block

Each block is the **flow's** last entries, not contiguous file lines: rows from other roles and
Goals are interleaved, and rendering contiguous lines produced an example that did not reproduce
its own claim. All four are in `replay_report.json → worked_examples`.

**AAA** — `OPEN_ALLIANCE` / `BTN_OPEN_ALLIANCE`, same page, three times consecutively
(lines 1253, 1281, 1303, signature `7a113273af`), `goal_progress` false each time.

**SAME_ACTION_NO_PROGRESS** — `CLOSE_POPUP` / `BTN_CLOSE` on `AUTO_DISCOVERY`: **60** failures
with `POPUP_CLOSE_NOT_PROVEN` across the flow (stream lines 1595–1715), every one on page
`POPUP`, every one with `goal_progress` *unread*. The detection at line 1695 is simply where the
third consecutive identical failure landed in the window.

**ABAB** — `OPEN_INTEL` / `BACK` alternating at lines 173, 176, 177, 182 (`278b74e62c` /
`7cfdd4dd12`).

**NAVIGATION_LOOP** — `SEARCH_RESOURCE → BACK → OPEN_MAP` cycled twice inside one
`AVOID_STAMINA_WASTE` flow (lines 515–529). The two laps have **different** state hashes
(`fdc509c8c4` vs `b1ffc31fae`) — a reward popup on one lap and not the other. That is why the
pattern is periodic in the *move*, not in the whole signature.

---

## Part 2 — the Session Engine's own real AUTO sessions, replayed

This is the half `replay_episodes.py` cannot give: the Session Engine's steps, grouped the way
the engine groups them. `decision_reason` starts with `session:` because
`LiveRuntimeSessionHost.record_step` wrote it, so the prefix selects exactly those steps.

**All four reading variants agree on every session** — `declared`/`outcome` × `recorded`/
`after_only` all give `LOOP_DETECTED 23 / LOOP_FALSE_POSITIVE 0 / LOOP_RECOVERED 2 /
LOOP_DEFERRED 3`, all `AAA`. That agreement is worth stating, because the rows carry a *second,
disagreeing* signal: **42 of the 105 steps are `result=FAILURE` while `goal_progress=true`**
(the click did not verify; the Goal advanced anyway). A detector fed `result` alone would read
42 verified advances as "no progress". The fallback is safe here only because nothing reaches
it — `record_step` always writes `goal_progress`, so `progress_from_outcome` is never called.

> **Corrected 2026-09-30 — see the correction note in *Provenance* and `STILL_PENDING_AUDIT.md`.**
> The "42" is not a fact about these runs. All 42 predate `fa476b6`, which is the commit that made
> `result` mean anything at all for a session step; post-fix the count is **0**. The two
> readings agreeing is likewise weaker than it reads: both reconstruct the outcome from the same
> `result` column, so they agree by construction. And the counts in this Part are a
> **counterfactual** — the live engine fed 2 of these 10 steps and detected nothing (*Part 4*).

Three of the 26 sessions reached `defer_goal`. One of them is the case the rung exists for:

**`SA5E9B37CCF` — the live AUTO burning 8 of its 10 steps on one stuck observe.** Revision
`6ba2ab5`. Steps 3–10 are eight identical `FISHING_RESULT_PENDING` / `OBSERVE_ONLY` / `FAILURE` /
`goal_progress=false`:

```
 3 L10115 FISHING_RESULT_PENDING  OBSERVE_ONLY  FAILURE  gp=False
 4 L10116 FISHING_RESULT_PENDING  OBSERVE_ONLY  FAILURE  gp=False
 5 L10117 FISHING_RESULT_PENDING  OBSERVE_ONLY  FAILURE  gp=False  <== semantic_retry
 6 L10118 FISHING_RESULT_PENDING  OBSERVE_ONLY  FAILURE  gp=False  <== local_reobserve
 7 L10119 FISHING_RESULT_PENDING  OBSERVE_ONLY  FAILURE  gp=False  <== widen_observe
 8 L10120 FISHING_RESULT_PENDING  OBSERVE_ONLY  FAILURE  gp=False  <== feature_reopen
 9 L10121 FISHING_RESULT_PENDING  OBSERVE_ONLY  FAILURE  gp=False  <== home_recovery
10 L10122 FISHING_RESULT_PENDING  OBSERVE_ONLY  FAILURE  gp=False  <== defer_goal
```

Six detections and a full ladder, landing on `defer_goal` at the session's **last** step. The
ladder's cost (3 identical answers + 5 confirmed escalations = 8 consecutive repeats) and this
session's budget (10 steps, 8 of them repeats) coincide exactly.

> **This block is a counterfactual, and the `FAILURE` labels in it are a recording artefact.**
> The 8 rows are `FISHING_RESULT_PENDING`, whose verdict is `STILL_PENDING` — "the cast is still
> swimming" — a verdict the loop detector is (correctly) not shown, which is why the live run
> detected nothing. They read `FAILURE` because the outcome fold's admitted set is
> `{"PROGRESS", "AMBIGUOUS"}` and omits `STILL_PENDING`. Measured on the same revision: the run
> was **0.345 s of wall time** across all 8 steps, against a 150 s time budget — a 30 ms busy
> spin, not a wait. See *Part 4* and `STILL_PENDING_AUDIT.md` §1.

The other two, and the two recoveries, are in `replay_sessions_report.json → detail`, with
every step's line number, rung and signature.

---

## Part 3 — `AUTO_CONTINUED`, from the run's own ledger

`AUTO_CONTINUED` is emitted by the caller that owns the run loop, never by the detector, so it
cannot be read off episode rows at all. Two accounts, neither sufficient alone:

| account | reading |
| --- | --- |
| **the stream** | 26 sessions; **26 of 26** followed by more rows, **25 of 26** followed by *another session* |
| **the round ledger** (`learning/auto_uptime.jsonl`) | 34 rounds; **31 continuing**, 3 halted; 3 unhealthy |

**A session ending never ended the run.** Every closed session is followed by more episodes and
by the start of a new session; only the newest is still open. And `SEMANTIC_TARGET_NOT_VERIFIED`
— the `CAPABILITY_GAP` ending §7 says must be followed by "Recover → Bounded Retry → Defer/Skip
→ Next Goal" — appears as a *stop reason* 7 times while the run went on.

The three halts, in full, because they are the counter-example that has to be stated:

| when (UTC) | `stop_category` | `stop_reason` | `healthy` |
| --- | --- | --- | --- |
| 04:48:39 | CAPABILITY_GAP | `SEMANTIC_TARGET_NOT_VERIFIED` | false |
| 05:14:35 | SYSTEM_FAILURE | `DAILY_REWARD_ADVANCE_NOT_PROVEN` | false |
| 06:35:02 | SYSTEM_FAILURE | `device_leased_for_development` | false |

`AUTO_CONTINUED = false` three times in 34 rounds, then never again: **the six rounds after the
last halt all continued** (06:45:04 → 07:14:39 UTC), all `healthy`. Each halt is named by
timestamp in the code at HEAD as the measured incident behind a classifier fix
(`runtime_snapshot.classify_stop_reason`'s ordering; the panel's
`healthy = … and category is not SYSTEM_FAILURE`), and the last one is an *operator device
lease* graded as a system failure — a defect, not a fault.

Two facts stated rather than glossed: `auto_uptime.jsonl` records **no revision** per round
(empty in all 34 rows), so a halt cannot be attributed from the ledger alone; and the panel's
own revision-scoped acceptance is `loaded_revision = 6ba2ab5`, 2 rounds, 0 halted,
**`acceptance_met: false`** (needs 3).

---

## Part 4 — the detector's first live evidence, and it is a negative

`772c0f9` gave the runtime `_record_session_timeline`, so every run now writes
`<capture_dir>/session_timeline.jsonl`: one row per `SESSION_ENDED`, carrying the session's full
metrics dict — including all five `LOOP_*` counters and the detector's own bounded
`LOOP_TIMELINE` — plus an `AUTO_CONTINUED` row when a session ends `SESSION_DOMAIN_STUCK` and
the next Goal is picked. **That file is the only place the four metrics can be read as the
running system produced them.**

`replay_sessions_report.json → live_detector_telemetry` reads it. At `014a4df`, three runs, four
sessions, every one of them reporting:

```
LOOP_DETECTED 0   LOOP_FALSE_POSITIVE 0   LOOP_RECOVERED 0   LOOP_DEFERRED 0   LOOP_PATTERNS {}
AUTO_CONTINUED events recorded live: 0
```

And one of those four is the loop this module was built for:

```
S5995DB6CE5  USE_NORMAL_FISHING_BAIT  reason=SESSION_STEP_BUDGET_EXHAUSTED
  steps=10  verified=2  observes=10  ambiguous_retries=0
  observations_shown_to_the_detector = 2
  LOOP_TIMELINE = [PROGRESS/true, PROGRESS/true]
```

**Ten steps ran; the detector was shown two of them.** The eight it never saw are exactly the
eight `FISHING_RESULT_PENDING` steps. The gate is one line, and it is deliberate:

```python
# session_engine.py:997
if verdict.outcome not in (StepOutcome.AMBIGUOUS, StepOutcome.STILL_PENDING):
    loop = state.loop.observe(self._signature_for(context, step, execution, verdict))
```

with the documented rationale: "*Only answered attempts are shown to the detector. `AMBIGUOUS`
means the client never answered and `STILL_PENDING` means honest work is in flight; both already
have their own bounded ladders and their own names, and feeding them here would relabel 'the
screen was unreadable' as 'the flow is looping' — a different fact with a different remedy.*"

That reasoning is sound. The measurement is what it produces: **the fishing stuck pattern is
`STILL_PENDING`, so the detector never sees it, and the eight steps that make up the loop are
exactly the eight steps withheld.** The offline replay in Part 2 reported 23 detections, 2
recoveries and 3 deferrals on real sessions precisely because it reconstructed `progress` from
episode rows and fed *every* step; the engine feeds 2 of 10.

Two more facts from the same session, each checkable:

1. **The withheld steps were `STILL_PENDING`, and that is a deduction, not a guess.** The gate
   excludes only `AMBIGUOUS` and `STILL_PENDING`. Had any of the eight been `AMBIGUOUS`,
   `SESSION_AMBIGUOUS_RETRIES` would be non-zero — it is **0** — and the session would have ended
   `SESSION_AMBIGUOUS:…` rather than at its step budget. Ten steps ran, two were shown, so the
   other eight were `STILL_PENDING`.
2. **`STILL_PENDING` has no bound and no counter, so "its own bounded ladder" is not true of
   it.** The engine's comment names both branches as bounded; `AMBIGUOUS` has
   `max_ambiguous_retries`, and `STILL_PENDING` has no counter at all — the only handling is
   `_terminal(..., STILL_PENDING, ...)`, which records the step and continues. The live metrics
   confirm it: 10 steps, 2 verified, and **`SESSION_SEMANTIC_RETRIES`, `SESSION_AMBIGUOUS_RETRIES`,
   `SESSION_RECOVERIES` and `SESSION_WAITS` all 0** — eight steps consumed the entire budget
   while no counter anywhere moved. The session's *step budget* is the only thing bounding it.

   > **Partly fixed 2026-09-30.** The counter now exists: `SessionState.still_pending` and the
   > metric `SESSION_STILL_PENDING`, kept out of both `SESSION_STEPS` and `loop_recoveries` on
   > purpose. The *bound* is deliberately still absent — `STILL_PENDING_AUDIT.md` §4 shows the
   > wait is a 30 ms busy spin bounded only by the step ceiling (**0.345 s** for the whole run,
   > against a 150 s time budget), so the next change belongs in the adapter's wait semantics,
   > and its size needs one live reading (hypothesis H1, §4 of that file).

A third boundary, also live: lines 10216–10237 of the stream are eleven laps of
`OPEN_INTEL` / `BACK` on `CLEAR_INTEL`, every one `gp=False` — a textbook `ABAB`. They are
**goal-driven** steps, not session steps, so the Session Engine's detector cannot see them by
construction. `LOOP_DETECTOR_V1` is the Generic Session Engine's capability; the main step loop
has no detector. That is the declared scope, and this is what it looks like from outside.

---

## The four metrics, and exactly how far each is proven

| metric | proven | not proven |
| --- | --- | --- |
| `LOOP_FALSE_POSITIVE` | **5 / 1511 (0.33 %)** over 10,253 historical episodes, each named with its disproof; **0 / 23** over the real sessions; **0** live | the *defer-rung* rate (see the caveat below). And a live rate is not measurable yet: 0 detections means 0 opportunities to be wrong |
| `LOOP_DETECTED` | **1511** over the stream, all four patterns; **23** over the 26 real sessions, all `AAA`, with line numbers; **live: 0 in 4 sessions**, with the mechanism (`session_engine.py:997`) and the deduction that pins the withheld steps to `STILL_PENDING` | that the running AUTO will detect anything: the deployed detector has been shown 2 of 10 steps in the one live session that looped, and fired never |
| `LOOP_RECOVERED` | **16** over the stream at the corrected rule; **2** over real sessions; on the real `LiveRuntime` in `tests/test_loop_detector_boundary.py` | a live recovery — live `LOOP_RECOVERED` is 0, and cannot be non-zero while `LOOP_DETECTED` is 0 |
| `AUTO_CONTINUED` | **31 / 34** rounds continued and **26 / 26** sessions were followed by the run starting another; the 3 halts are named and each attributed to a fixed misclassification; a session ending has never been the reason the run stopped | the case the metric exists for: **0 live `AUTO_CONTINUED` events**, because no session has yet ended `SESSION_DOMAIN_STUCK`. The run-loop wiring is in place and inert |

Blunt summary: `LOOP_FALSE_POSITIVE` and `LOOP_DETECTED` are proven on historical episodes;
`AUTO_CONTINUED` is proven of the run, not of the detector; and **the live half is a negative
result with a fully identified cause**, which is a better artifact than a positive one that
cannot be reproduced.

---

## Six findings the measurement produced

**1. The page-only navigation pattern was too loose, and it was tightened — measured as a
controlled A/B on the same rows.** A page cycle alone fires on `HOME → ALLIANCE → HOME →
ALLIANCE` where a *different* control is tapped on each visit: a client being used, not one
walked in a circle. Adding `LoopSignature.move_key` (page **and** action) took `NAVIGATION_LOOP`
from **579 to 295** and total detections from **1795 to 1511** — with every other pattern
*identical* (AAA 638, `SAME_ACTION_NO_PROGRESS` 142, ABAB 436), which is what makes it a
controlled comparison rather than two numbers from two days — while still catching the real
circuit above. Pinned by
`test_two_pages_revisited_with_different_work_each_lap_are_not_a_navigation_loop` and
`test_a_move_cycle_still_fires_when_the_state_and_verdict_differ_lap_to_lap`.

**2. The ladder is only ever spent on *consecutive* repeats — measured, not assumed.** All
**225 / 225** `defer_goal` detections were confirmed escalations; none was reached across a gap.
The mechanism is `_settle`'s stale branch: the moment the flow does something else, the tracked
action's rung is dropped. Pinned by `test_a_gap_restarts_the_ladder_at_its_cheapest_rung`.

**3. The defer rung is a high bar, so the risk of "it would defer everything" is refuted.**
Reaching `defer_goal` needs 8 consecutive repeats. The median flow needs 157 of its own steps to
get there, only 11 of 128 flows ever did, and **none** within a 5-step session; 2 within a
12-step one. In the 26 real sessions exactly three reached it — and the one printed in Part 2
was spending 8 of its 10 steps on the same observe, so it is the case the rung is for.

**4. The replay harness itself had a state-source defect, and fixing it was measured.** A session
step records `state_before` and an **empty** `state_after`; an empty mapping is still a
`Mapping`, so the original `episode_fields` accepted it and hashed the context over an all-`None`
projection — for 562 of the stream's rows. That is the `empty != none` rule broken one layer
down. Corrected, and kept as the `after_only_state` A/B on the same rows: `LOOP_DETECTED` 1496 →
1511 (AAA 632 → 638, `SAME_ACTION_NO_PROGRESS` 148 → 142, NAVIGATION 279 → 295), with
**`LOOP_FALSE_POSITIVE` unchanged at 5 and `LOOP_DEFERRED` unchanged at 225**. A correctness fix
with a ~1 % effect — the honest size of it, not a headline.

**5. `LOOP_RECOVERED` was inflated about tenfold until `014a4df`.** Counting "the next action was
different" as recovery treats a *second failure* as success. Requiring verified progress on the
new action took the whole-stream count from **147 to 16** and the per-run count from **55 to 6**.
Anyone quoting the earlier figure is quoting a number the commit message already disowned.

**6. The detector is deployed and inert on the production loop, for a stated reason.** Part 4.
This is the finding that matters most for the directive's "Fishing/Bear/Stamina/Training Batch
全部复用" clause: **Fishing is not covered.** Its stuck pattern is `STILL_PENDING`, which is
withheld from the detector by design; the withholding is right in principle and total in
practice; `STILL_PENDING` is also the one outcome with no bound of its own. Three of the four
routes were not observed looping in this window at all, so nothing is claimed about them.

## The honest caveat about `LOOP_FALSE_POSITIVE`

Three of the five retractions happened at the **`defer_goal`** rung — and in the engine that rung
*ends the session on the spot* (`_terminal(..., continues=False)`), so the frame that would have
retracted the claim is never observed. In production those three are not retractions at all; they
are **wrongly deferred Goals**, presenting as `SESSION_DOMAIN_STUCK` with the Goal handed back.

Stated plainly: the 0.33 % figure is **optimistic for the defer rung**, where the true rate is
3/225 = 1.3 % of deferrals. It is recorded rather than tuned away, because the alternative — a
higher bar for the terminal rung — would delay the remedy for genuinely stuck flows, and §7
already declares this ending recoverable (the Goal is deferred, AUTO continues). A future change
should be justified by a measurement of *wrongly deferred Goals*, which this harness cannot
produce on its own because it keeps feeding a flow the engine would have ended.
