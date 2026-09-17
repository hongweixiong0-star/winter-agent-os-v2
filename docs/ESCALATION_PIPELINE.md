# Escalation pipeline: AUTO finds the wall, the queue throttles, WorkBuddy fixes

Three layers, three jobs, one direction of blame:

```
AUTO runtime        discovers a wall, records it, keeps playing   ← never waits
escalation queue    dedup, concurrency, budget, cooldown, state   ← one ledger
WorkBuddy bridge    dispatches asynchronously                     ← transport only
WorkBuddy agent     Reuse Check .. Live Verify .. Commit/Push     ← its own process
```

The rule everything else follows from: **AUTO never waits for WorkBuddy.** A cycle
that stopped to await a development agent would trade a game runtime for a build
server, so the AUTO hook does two things -- reconcile jobs that already ended, and
hand off at most the decisions the concurrency cap allows -- and returns. The agent
works in its own process while the game keeps being played.

## 1. What AUTO does at the end of a run

`tools/run_live.py`, after the last atomic action and before the exit code:

```python
adapter = EscalationQueueAdapter(root=ROOT)
observation = adapter.observe_run(
    stop_reason=result.stop_reason,
    failures=failures_since(started_at, root=ROOT),
)
```

Three properties are load-bearing:

* **After the action, not during it.** Nothing is restarted or reloaded mid-action.
* **Never raises.** A gateway that is down, a slow status read, a broken ledger --
  each comes back as a line on the observation. The run's exit code is decided the
  same way it always was.
* **Never waits.** The only HTTP calls are one `health` probe and one `status` per
  in-flight job. A gateway that is unreachable leaves the escalation `QUEUED` and
  AUTO keeps playing.

Turn it off for a purely observational run with `--no-escalate`.

## 2. The five conditions, and the weather that is not a condition

| allowed | meaning |
| --- | --- |
| `CAPABILITY_MISSING` | the project itself records the capability as never implemented |
| `UNKNOWN_UI` | the client showed something V2 could not read or locate |
| `UNKNOWN_GAME_MECHANIC` | the client did something the model does not describe |
| `REPEATED_LIVE_FAILURE` | the same signature has now failed on the device more than once |
| `STUCK_15_MIN` | same signature, 15+ minutes, still no verified episode |

Everything else is left alone, including -- by name -- `mail_all_clear`,
`research_queue_busy`, `NOT_REFRESHED`, `QUEUE_BUSY`, `RESOURCE_SHORTAGE`,
`EVENT_CLOSED`, `RALLY_FULL`, `WAITING_FOR_NATURAL_STATE`. Those are correct
observations of a working system; escalating them would spend an agent on an empty
mailbox. A failure shape that matches none of the five also gets no condition --
guessing would send an agent after the wrong problem.

Classification is by **shape**, not by an exhaustive list. The first version listed
the six failure types that dominated the live distribution and was already wrong
the day it was written (it missed `TRAINING_PAGE_NOT_PROVEN`), so the UI family is
now matched by suffix (`_NOT_VERIFIED`, `_NOT_PROVEN`, `_NOT_OPEN`, `_NOT_FOUND`)
with an explicit set for the names that do not follow the convention.

## 3. The dedup key

`capability | failure_type | skill` -- and one active job per key, ever. A failure
that recurs every six minutes does not summon an agent every six minutes.

`capability` is resolved through the project's existing
`knowledge/goals/capability_skill_map.json` (Goal -> Capability -> Skill ->
Evidence). An unknown skill resolves to itself: it is a name with no better label,
not a capability to invent.

## 4. Throttle

```python
EscalationPolicy(
    max_concurrent_jobs = 1,     # two agents must not edit this repository at once
    repair_budget       = 2,     # post-fix shots per signature; the first is free
    cooldown_minutes    = 60,
    repeat_threshold    = 2,
    stuck_minutes       = 15,
)
```

`decide()` is one pure function and the order is deliberate: not-a-condition is
refused first, then an existing job for the same key, then the global concurrency
cap, then the repair budget, then cooldown. Anything else would let a recurring
failure slip past one of the limits.

When the budget is spent the signature goes `BLOCKED` then `COOLDOWN` and AUTO moves
to another capability -- that is what stops the `Runtime <-> WorkBuddy` repair loop.

## 5. States, and where they live

```
NEW -> QUEUED -> SUBMITTED -> WORKING -> DONE | FAILED
                                    \-> BLOCKED -> COOLDOWN
```

There is exactly one place any of this is stored:
`learning/workbuddy_escalations.jsonl`. Every state above is a **fold over that event
stream** -- there is no second copy, because this project has been bitten by
plausible-looking stores nobody reads, and a second registry would make "is this
capability already being worked on" answerable from two places that can disagree.

The file carries two event families, distinguished by `source`:

* `source: "bridge"` -- transport audit written by the bridge (job id, permission
  mode). Not queue state.
* `source: "queue"` -- the escalation lifecycle. Only these carry a `key`, and the
  fold ignores rows without one.

```bash
python tools/escalations.py --state        # fold and print the queue
python tools/escalations.py --reconcile    # poll in-flight jobs and measure outcomes
python tools/escalations.py --reload       # is RUNTIME_RELOAD_REQUIRED pending?
python tools/escalations.py --reload-done  # clear it
```

## 6. A finished job is not a finished capability

Reconciliation measures locally and reports one of five outcomes. The gateway's
verdict for the job is used **only** to tell "did nothing" from "failed"; it is never
treated as proof that a capability works.

| outcome | how it is measured |
| --- | --- |
| `LIVE_VERIFIED` | a production episode for the capability with `recorded_at`, `verifier_ok: true`, both screenshots, and a timestamp **after** the job was dispatched |
| `TEST_PASS` | the tree changed (`git rev-parse HEAD` / dirty count before vs after) and `check_wiring` reports `problems: 0` |
| `CODE_CHANGED` | the tree changed but the wiring gate did not pass or could not run |
| `BLOCKED` | the job ended `FAILED`/`STOPPED` and nothing changed |
| `NO_IMPROVEMENT` | job finished, no code change, no new verified episode |

Two honest limits, stated rather than papered over:

* `TEST_PASS` is backed by `check_wiring` only. The full suite takes ~18 minutes and
  does not belong inside the AUTO hook; the explanation string says so in words.
* The jobs API exposed **no** token or cost field (measured 2026-09-17: the job
  payload carries `id`/`state`/`output` and nothing about usage), so the ledger
  records `tokens: null`, `cost: null` and a `usage_note` explaining why, instead of
  estimating.

## 7. Model routing: one ladder, four rungs, no manager

```
deepseek-v4.1-flash   default: any ordinary capability, UI or navigation defect
glm-5.3-flash         long context -- huge logs, many files, cross-file analysis
hy4-preview-f         vision-heavy -- image understanding, or a second opinion
deepseek-v4-pro       last resort: architecture conflict, or a spent fix budget
```

All four ids were verified end to end on 2026-09-17 (each dispatched a job that came
back `done`). Routing is a pure function, not a manager: attempt 0 uses the cheapest
rung, and each spent attempt climbs one rung -- and only when the rung below produced
no live improvement. A known-hard shape can start higher (`needs="logs"` starts at
GLM-5.3 Flash, `needs="vision"` at Hy4). Every submission records `model`,
`model_reason` and `escalated_from` so the ladder can be tuned from real success
rates rather than taste.

## 8. `RUNTIME_RELOAD_REQUIRED`, and why there is no reload manager

Every AUTO cycle is a **fresh subprocess** -- the panel re-launches
`tools/run_live.py` each time, and that process imports `vision`, `brain`, `skills`
and `runtime` from disk at start-up. Code that lands on disk is therefore in effect
on the next cycle by construction; a reload manager would be a second runtime manager
solving a problem that does not exist.

What does exist is one real hazard: **starting a cycle while an editor is mid-write.**
A run that reads a half-written `runtime.py` can bind a verifier to the wrong
function, which is why `run_live.py` already carries a `VERIFIER_MAPPING_CORRUPT`
guard.

So the signal is a marker file plus one pure predicate:

* written when reconciliation measures that the tree actually changed;
* the panel's `start()` defers while the marker is fresh (< 20 s) or while an
  escalation job is still active;
* **and always gives up after 15 minutes**, because a hung development agent must
  not become a stalled game runtime.

When the wait is over the marker is cleared and the next cycle starts normally, on
the new code.

## 9. What was deliberately not built

No second scheduler, manager, registry or orchestrator. The queue is an adapter over
one ledger; the throttle is a pure function; the hook is `try/except`-wrapped and
non-blocking; the reload is a marker plus a bounded wait. Anything that reads the
device still goes through the one runtime that owns the device connection.
