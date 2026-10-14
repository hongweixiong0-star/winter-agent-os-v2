# The WorkBuddy model-call channel is retired (2026-09-25)

**Operator directive.** V2 no longer reaches the WorkBuddy desktop model by itself — not through
the local gateway, not through the Open Platform, not through OAuth, not through any bridge.
WorkBuddy goes back to being a development tool a person drives by hand. The automatic answering
of UNKNOWN questions moves to the **local Qwen** already deployed on this machine.

This file is the failure record the directive asks to keep (§1.5), so the next account does not
spend another day re-attempting a route that has been measured to dead-end.

---

## 1. What was tried, and where each attempt actually stopped

Every claim below was measured on this machine, with the job's own log or the gateway's own
endpoint as the evidence. The full trace lives in `WORKBUDDY_GATEWAY_CONTRACT.md` §9–§10.

| attempt | stopped at | evidence |
| --- | --- | --- |
| `POST /api/v1/jobs` (the escalation bridge) | worker died ~1 s after start | `job-b25c1f12.log`: `Cannot find module '../dist/codebuddy'` at `cli/bin/codebuddy:205` |
| fixed the bundle selector | worker boots, then waits for ever | `state=working, detail="starting…"`, 30 min, 0 IO, no model request |
| fixed the config root | worker reaches `preparing`, exits silently at 8.3 s | `_probe_lifecycle.py`, job `7d253d09` |
| attached a client with the product's own `codebuddy attach` | reaches `idle` — "a session waiting to be asked" — and still no answer | `_probe_attach.py`, job `c0df8fa2` |
| `POST /api/v1/runs` (documented, 202`accepted`) | nothing, with or without the daemon started through the documented endpoint | `sessions/live -> {"sessionId": null}` |
| one-shot CLI turn in the gateway's own environment | timed out, both config roots, with and without `-p` | `_probe_headless_turn.py`, 4 attempts |

## 2. The layer underneath all of it

`forkBgSession` hands every job worker `{...process.env}` **of the gateway**, so the worker's whole
world is what the gateway inherited. Measured:

| | environment variables | of interest |
| --- | --- | --- |
| this project's gateway | 61 | bundle selector, gateway password, internal-internet marker — and **no other `CODEBUDDY_*`** |
| the app's per-session sidecar | 146 | 86 more: `CODEBUDDY_HOST=workbuddy-desktop`, `CODEBUDDY_HOST_CAPABILITIES`, `WORKBUDDY_PAC_RPC_TOKEN`, product-config spill, and `--settings`/`--mcp-config`/`--prompt-vars-file` on argv |

**Neither environment carries a model credential.** The app grants model access to the CLI
processes *it* spawns for a conversation, by handing them the host identity and a session token.
So the difference between the two paths is not a flag, a model name or a prompt — it is **who owns
the session**. `CODEBUDDY_GATEWAY_PASSWORD` opens a local door; it is not an account credential,
and a reachable gateway proves nothing about model access.

The only supported route for a third party is the Open Platform `localassistant` API, which needs
a registered application plus a one-time user authorization. It does not exist on this machine and
**was not created or borrowed here**: copying `WORKBUDDY_PAC_RPC_TOKEN`, reusing a session's argv,
or reading a session's cookies were all explicitly out of bounds and none of them was attempted.

## 3. What is retired, and what deliberately is not

**Retired — V2 no longer does these on its own:**

| switch / site | effect |
| --- | --- |
| `config/v2.json -> workbuddy_channel.enabled = false` | the switch itself; default is the retired behaviour |
| `tools/control_panel.py::_unknown_tick` | passes `submit=False`; still **reconciles**, so a job placed before the directive is settled instead of holding the in-flight slot for ever |
| `winter_agent_v2/unknown_dispatch.py::worker(submit=...)` | `submit=False` reconciles and reports `skipped: WORKBUDDY_CHANNEL_RETIRED` |
| `tools/unknown_ai_worker.py` | reads the same switch; `--once`/`--loop` reconcile only, and say so out loud rather than printing "submitted 0" |

**Kept, on purpose:**

* `workbuddy_bridge.py`, `gateway_service.py`, `unknown_dispatch.py` and their tests. They are
  public components other paths import, and `GatewayService` is still how a person starts a
  gateway for a development job. §1.4 forbids deleting a component that is still depended on.
* `learning/unknown_requests/` and its historical answers. Knowledge, not a channel.
* Every probe tool written while tracing this (`_probe_lifecycle.py`, `_probe_attach.py`,
  `_probe_headless_turn.py`, `_probe_runs.py`) and the §9–§10 sections of the gateway contract.

**Not touched:** the desktop console, the AUTO runtime, the game loop, the device path. The
retirement is a config-gated off-switch on one call site, not a removal of a subsystem.

## 4. What replaced it

`winter_agent_v2/local_qwen.py` (the one file that knows the endpoint) +
`winter_agent_v2/ui_planner.py` (the structured-action protocol and the planner). The runtime
takes an injectable `advisor=` and `run_live.py` builds the planner from config, so the runtime
itself never learns a model name. Acceptance levels and the live evidence:
`docs/LOCAL_PLANNER_ACCEPTANCE.md`.

## 5. Why `learning/unknown_dispatch.jsonl` goes quiet — and why that is not a fault

Added 2026-10-10, after this exact question was asked and investigated from scratch ("the dispatch
loop has not run for 17 days — fix it"). The answer is that **it is not broken**, and the fact was
not written down anywhere, which is what made it cost an investigation.

**Measured, not inferred:**

| reading | value |
|---|---|
| the channel's only periodic trigger | the WorkBuddy automation **`404bbf18-5dcd-4f94-a091-b40ea26dc614`「UNKNOWN 问题通道：自动派发与结算」** (`FREQ=HOURLY;INTERVAL=1`) — status **`PAUSED`** |
| the panel tick that supersedes it | alive: `unknown_ticks = 1353`, `unknown_last = 20:13:49`, i.e. it ran ~30 s before it was read |
| what that tick does | `worker(submit=False)` — reconcile only, and it says so: `unknown_note = "channel retired (local planner answers in-cycle); 14 question(s) waiting, 0 in flight"` |
| the switch that makes it submit nothing | `config/v2.json -> workbuddy_channel.enabled = false`, `retired_at 2026-09-25` (this section's §3) |
| last write to the ledger | `2026-09-23T19:54:40` — i.e. the silence starts at the retirement, not at a crash |

**So: two independent stops, and both are deliberate.** The submitter is off by the config switch,
and the hourly automation that used to drive `tools/unknown_ai_worker.py --once` is `PAUSED`. A
silent `unknown_dispatch.jsonl` is the **expected** reading of that combination. The panel tick still
reconciles, so a job placed before the retirement would still be settled rather than holding the
in-flight slot for ever.

**Do not "fix" either one without being asked.** Resuming the automation would run
`unknown_ai_worker.py --once`, which under `enabled = false` reconciles and returns
`skipped: WORKBUDDY_CHANNEL_RETIRED` — no functional change, because the panel already reconciles
every `UNKNOWN_EVERY = 8` ticks. Re-enabling `workbuddy_channel.enabled` would violate the
2026-09-25 directive and re-enter the route §1 measured to a dead end.

**The rule this cost an investigation to re-learn** — the project already wrote it down for the other
automation, in `.workbuddy-ai/handoff/04_OPEN_ISSUES.md` (items `0ap` / `0az`), after the same
confusion recurred four times: *"不要因为它不产出新 episode 就判定自动化故障…先查状态是不是 PAUSED"*.
This section applies that rule to the UNKNOWN channel, whose paused state was **not** recorded
anywhere until now.

**Where to look first, in this order:**

1. `automation_update` `list` — is `404bbf18-…「UNKNOWN 问题通道：自动派发与结算」` `ACTIVE` or `PAUSED`?
2. `learning/control_panel/pump.json` — `unknown_ticks` / `unknown_last` / `unknown_note`. Fresh
   values with `submitted: 0` mean **the loop is running and correctly idle**, not broken.
3. `config/v2.json -> workbuddy_channel.enabled`.

**What the accumulated `learning/unknown_requests/*.json` records are.** They are *not* a queue
waiting for the retired channel. The runtime consults the in-cycle local planner **first**
(`runtime.py` → `advisor.take_request(request, ...)`), and writes a request file **only when the
planner returns `None`** (`if advice is None: advisor.ask(request)`). So a file means *the local
model declined this screen* — which is exactly the not-authored evaluation corpus
`tools/benchmark_gui_unknown.py` scores the local model on, and the reason
`winter_agent_v2/retention.py::unknown_request_evidence()` keeps those frames. Keep them; they are
the local model's exam paper, not a stuck backlog.

**One honest caveat about that corpus:** 8 of the 15 records on disk (2026-10-10) have already lost
their frame, and a record whose frame is gone cannot be scored — `tools/unknown_chain_check.py`
reports it as *"the frame this question is about is gone: it cannot be replayed, only re-asked"*.
Those 8 predate `unknown_request_evidence()`; the 7 that survive are all covered by it. Worth a
periodic count of "records that still have a frame", because that number, not the record count, is
the size of the usable corpus.

