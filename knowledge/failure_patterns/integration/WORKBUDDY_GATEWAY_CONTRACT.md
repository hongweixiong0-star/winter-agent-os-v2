# WorkBuddy / CodeBuddy HTTP gateway — the measured contract

Recorded 2026-09-17, against CodeBuddy **2.137.1** on this machine, because the
escalation bridge (`winter_agent_v2/workbuddy_bridge.py`) depends on facts that
are not documented anywhere the project can read offline.

Everything below was measured, not inferred. Where a value came from reading the
bundled OpenAPI spec inside `dist/codebuddy.js`, that is stated as such; where it
came from an actual request, the request is quoted.

## 1. The binary is not on `PATH`

```
$ which codebuddy            -> not found
$ codebuddy --version        -> command not found
```

The CLI ships inside the desktop application:

```
E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\cli\bin\codebuddy
```

It is a Node script (`@genie/agent-cli`), so it needs a Node ≥ 18.20.8. The
managed Node works:

```
C:\Users\xhw\.workbuddy\binaries\node\versions\22.22.2-3\node.exe \
  "E:/work Buddy国内/WorkBuddy/resources/app.asar.unpacked/cli/bin/codebuddy" --version
-> 2.137.1
```

**Do not** hard-code a launcher to the Codex runtime python that this desktop
application also ships — that is the same mistake as
`TOOLING_INTERPRETER_DRIFT.md`, one layer up.

## 2. `--serve` is real, and it needs a password

```
codebuddy --serve --port 8080 --session-id winter-agent-v2
```

Measured output:

```
  Endpoint    http://127.0.0.1:8080
  Web UI      http://127.0.0.1:8080/?password=<generated>
  Password    <generated>
```

Credential resolution order, read from the bundle:

1. `CODEBUDDY_GATEWAY_PASSWORD` environment variable
2. `settings.gateway.password`
3. a generated 24-byte `base64url` value, persisted

Verified live: launching with `CODEBUDDY_GATEWAY_PASSWORD=v2-bridge-dev-local-only`
made that the accepted password **and the previously generated one returned 401**.
This is the whole reason the bridge can keep credentials out of the repository:
the secret is pinned by an environment variable that both sides read.

`--auth none` also exists. **Do not use it**: it lets any local process execute
commands and read/write files through the server, which is a much larger hole
than one shared password.

## 3. `/api/v1/health` requires authentication

```
$ curl -s http://127.0.0.1:8080/api/v1/health
{"error":{"code":"AUTH_REQUIRED","message":"Authentication required"}}   HTTP 401

$ curl -s -H "Authorization: Bearer <pw>" http://127.0.0.1:8080/api/v1/health
{"data":{"status":"ok","uptime":15.55,"platforms":["generic","wecom","wechat-kf"],"pid":22268}}  HTTP 200
```

`GET /api/v1/info` additionally reports the server's own `cwd` — measured
`E:\无尽冬日智能体`, i.e. the gateway inherits the launcher's directory.

There is no reachable OpenAPI document (`/openapi.json`, `/docs`, `/swagger.json`
all 404), so the spec has to be read out of `dist/codebuddy.js`. The envelope is
`{"data": ...}` on success and `{"error": {"code", "message", "details"}}` on
failure.

## 4. `/jobs` is the background path; `/runs` is the interactive one

Both exist. `/api/v1/runs` returns an `runId` designed to be followed over SSE —
that is the interactive Gateway-Protocol path. `/api/v1/jobs` is what
`codebuddy agents --jobs` shows, with a durable id and a pollable `state`:

| operation | call |
| --- | --- |
| `is_available` | `GET /api/v1/health` |
| `submit` | `POST /api/v1/jobs` |
| `status` | `GET /api/v1/jobs/{id}` |
| `cancel` | `POST /api/v1/jobs/{id}/stop` |

`POST /api/v1/jobs` body (from the bundled spec):

```jsonc
{
  "prompt":         "…",              // required
  "cwd":            "E:\\无尽冬日智能体",
  "name":           "…",
  "permissionMode": "default|acceptEdits|plan|auto|dontAsk|bypassPermissions",
  "bgIsolation":    "none|worktree",  // "首次写文件时是否自动进入隔离 worktree"
  "model":          "…", "effort": "minimal|low|…|max",
  "bash": false, "sourceSessionId": "…"
}
```

`GET /api/v1/jobs/{id}` returns `{data: {job: AgentJob}}` where `AgentJob` has
`id`, `shortId`, `sessionId`, `kind`, `state` ∈ `working|blocked|done|failed|stopped`,
`status` ∈ `busy|idle|waiting|stopped`, `tempo`, `name`, `intent`, `detail`,
`waitingFor`, `cwd`, `startedAt`, `updatedAt`, `firstTerminalAt`, `webUrl`, `pid`,
`alive`, `settled`, and `output` (`{result: "…"}`) once terminal.

Measured lifecycle of a trivial job (`BRIDGE_OK` probe):

```
submit   -> {"id":"5a300a1d","state":"working","settled":false,"alive":false,"detail":"starting…"}
poll ~2s -> detail "requesting the model", status "busy", alive true, pid 28280
poll ~12s-> state "done", settled true, alive false, output {"result":"BRIDGE_OK"}
```

`POST /api/v1/jobs/{id}/stop` -> `{"data":{"stopped":true}}`, and a follow-up read
reports `state: "stopped", settled: true`. Measured on a real job.

## 5. Two defaults that were measured, not chosen

Both were established with real jobs, and both would have looked fine in a unit
test while quietly breaking the workflow:

- **`permissionMode: "bypassPermissions"`.** Four real jobs, one prompt, 2026-09-17:

  | mode | result |
  | --- | --- |
  | `dontAsk` | DENIED (`DENIED=git rev-parse --short HEAD`) |
  | `acceptEdits` | DENIED (`DENIED=1`) |
  | `auto` | DENIED |
  | `bypassPermissions` | **EXECUTED** (`GIT=19964ec PY=42`) |

  **This corrects an earlier claim in this file.** A first probe used `dontAsk`,
  asked for `git rev-parse HEAD` and returned the correct 40-character hash, which
  was read as proof that `dontAsk` runs shells. It proved nothing of the kind:
  `.git/refs/heads/main` holds the same hash and Read was permitted, and an agent
  later described the mechanism exactly -- `Bash` denied outright, the shell
  fallback restricted to a **read-only allowlist** where `git rev-parse` passed and
  `python` / `pytest` / `git commit` did not. That earlier measurement had verified
  the output and not the mechanism. A pipeline whose agent can only read cannot fix
  a capability, which is why the default is now the one mode that executes.
- **`bgIsolation: "none"`.** The spec's own wording is that the default follows a
  global setting and may auto-enter an isolated worktree on first file write. With
  a worktree, the escalated agent's commits land on a throwaway branch and V2
  never sees them — the escalation would report success while the repository was
  unchanged.

## 6. A CLI wiring bug that only a live run could catch

`tools/workbuddy_bridge.py` first read `args.job_id` for `--status`. argparse had
stored the value under `args.status` (the option name *is* the dest when the
option takes a value), so every invocation raised `AttributeError` — while all 48
unit tests passed, because they exercised `WorkBuddyBridge` directly and never
the argument plumbing.

Fixed by naming `dest` explicitly (`status_job`, `cancel_job`), and a
`CliWiringTest` class now drives `main()` so this class of mistake is caught in
the suite instead of on the first real escalation.

**Lesson, third time in this project:** the thing that gets verified must be the
thing that runs. A verified library under an unverified entry point is still an
unverified feature.

## 7. Do not add a proxy

The operator's instruction is explicit: use the official HTTP API, not a
third-party proxy. Nothing in the measured contract needs one, and each hop would
be another place the credential lives.

## 8. The contract changed: a request marker is now required (re-measured 2026-09-18 20:14)

The contract above was measured against **2.137.1** on 2026-09-17 and it said
`Authorization: Bearer <password>` was sufficient for `/api/v1/health`. It is not
any more. Re-measured against the gateway running as **pid 11304**
(`--serve --port 8080 --session-id winter-agent-v2`):

| request | answer |
| --- | --- |
| no extra header | `403 {"error": "Missing required header: x-codebuddy-request"}` |
| `x-codebuddy-request: 1` (any non-empty value) | `401 AUTH_REQUIRED` — the marker is satisfied |
| marker + `Authorization: Bearer <settings.json password>` | **`200 {"data":{"status":"ok","pid":11304}}`** |
| marker + `Authorization: Bearer <CODEBUDDY_GATEWAY_PASSWORD>` | `401 AUTH_REQUIRED` |

Two separate facts, both of which cost a working gateway its life:

1. **The marker.** Its value only has to be non-empty; `1`, `true` and `cli` all
   behaved identically. `winter_agent_v2/workbuddy_bridge.py` now sends
   `x-codebuddy-request: 1` on every request (`REQUEST_MARKER_HEADER`).
2. **The environment credential was stale.** The 43-character
   `CODEBUDDY_GATEWAY_PASSWORD` in this session's environment is *rejected* (401)
   while the 24-character password in `settings.json` is *accepted*. §2 of the
   earlier measurement still holds — "the credential resolution order is
   environment, then settings, then generated" — but the bridge only falls back to
   the persisted one **on a 401**. Because the missing marker produced a **403**,
   the fallback never ran, so a correctly-running gateway looked unreachable.

### Why this looked like a process problem and was not

`gateway.json` recorded `available=false`, so `GatewayService` concluded the
gateway was wedged and **killed and restarted it four times** (`restart_attempts=4`,
`consecutive_failures=122`), while `pump.json` accumulated 22 identical errors
reconciling job `d8ea0e44`. The process had never been at fault.

The lifecycle now separates the two:
`Measurement.reachable` distinguishes *nothing came back* from *it answered and
refused us*. Only silence justifies a restart, because restarting a process cannot
change a request header or a credential; a refusal becomes `REJECTING` with the
reason named.

### And a lost job is not an unreachable one

`GET /api/v1/jobs/d8ea0e44` answered `404 {"code":"JOB_NOT_FOUND"}`. **Jobs do not
survive their gateway instance**, so a restart strands the ledger on work that can
never finish — and because that was raised as the same `GatewayUnavailable` used
for a dead port, the record stayed `WORKING` and held the single development slot
(`max_concurrent_jobs = 1`), refusing every escalation behind it with
`CONCURRENCY_WAIT`. The queue was deadlocked by a ghost.

`status()` now raises `JobLost` (a subclass, so existing handlers keep working), the
adapter folds it to a terminal `FAILED` with `outcome = JOB_LOST`, and the slot is
freed for the capability to be re-offered from its budget rather than silently
duplicated (operator §六).

