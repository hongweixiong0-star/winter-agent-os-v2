# V2 ↔ WorkBuddy bridge

V2 decides what to do and proves whether it happened. It cannot discover a game
mechanic or a UI surface nobody in this project has ever seen — when it hits that
wall it burns the whole timebox and stops. This bridge is the exit: it hands one
*stuck* capability to a local WorkBuddy (CodeBuddy) background agent and reports
back what that agent found.

It is a **transport**, not a manager. No second scheduler, no registry, no goal
state. The only decision it makes is "is this one of the five conditions the
operator allows".

## 1. Start the gateway (operator, once per session)

The CLI is not on `PATH`; it ships inside the desktop application.

```bash
export CODEBUDDY_GATEWAY_PASSWORD='<your local dev password>'
NODE="C:/Users/xhw/.workbuddy/binaries/node/versions/22.22.2-3/node.exe"
CLI="E:/work Buddy国内/WorkBuddy/resources/app.asar.unpacked/cli/bin/codebuddy"
"$NODE" "$CLI" --serve --port 8080 --session-id winter-agent-v2
```

`CODEBUDDY_GATEWAY_PASSWORD` pins the password (measured: it overrides the
auto-generated one, and the previous generated value then returns 401). Both the
gateway and V2 read the same variable, so **no credential ever enters the
repository** — there is no key to add to `config/v2.json` and the module does not
read that file at all.

For a persistent setup, set it as a Windows user environment variable
(`setx CODEBUDDY_GATEWAY_PASSWORD ...`), which lives outside the checkout.

Do **not** use `--auth none`: it lets any local process execute commands and
read/write files through the server.

## 2. Check it

```bash
python tools/workbuddy_bridge.py --check
```

```
base url      : http://127.0.0.1:8080
credential    : set via CODEBUDDY_GATEWAY_PASSWORD
cwd (fixed)   : E:\无尽冬日智能体
permission    : dontAsk
bg isolation  : none

gateway    : http://127.0.0.1:8080
verdict    : OK
```

Exit codes: `0` available, `1` unavailable (also "job not terminal yet"),
`2` refused (bad condition / missing `--capability`), `3` transport failure.

A missing gateway is reported as `GATEWAY_UNREACHABLE` or `NO_CREDENTIAL` — it is
an answer, never an exception, and it is **never a reason for V2 to stop working**.
V2 keeps doing local work; only this one escalation is unavailable.

## 3. The gate: five conditions, no others

```
CAPABILITY_MISSING        not in the catalog at all
UNKNOWN_UI                the entry or its appearance has never been seen
UNKNOWN_GAME_MECHANIC     the inputs and outcomes are not understood
REPEATED_LIVE_FAILURE     the same live failure has recurred
STUCK_15_MIN              15 minutes spent without a reliable implementation
```

**An ordinary game tick may never call WorkBuddy.** `submit` refuses anything
else *before* it touches the network (`EscalationRefused`), and the refusal is
the point: silently accepting a tick would turn this module into a second
scheduler by the back door. The same five names are the verdict values
`tools/reuse_check.py` already prints in step 8 ("NO LOCAL PATH -> escalate, in
this order"), so the two cannot drift apart.

Every submission appends one row to `learning/workbuddy_escalations.jsonl`
(condition, capability, job id, permission mode). That ledger is what makes
"ticks never call WorkBuddy" a checkable claim rather than an assertion.

## 4. What V2 sends

```bash
python tools/workbuddy_bridge.py \
  --submit REPEATED_LIVE_FAILURE \
  --capability BUILDING_UPGRADE \
  --goal KEEP_BUILDING_PRODUCTIVE --skill BUILDING_UPGRADE \
  --failure "point (280,640) selects a building but no route opens Page.BUILDING" \
  --reuse-check out_reuse.txt --external-prior knowledge/external/prior_build.md
```

Preview it without sending: `--prompt <CONDITION> --capability ...`.

The prompt is assembled by `build_prompt` and always carries: capability,
condition, goal, skill, timebox, failure reason, **current WorldState**, recent
live episodes, evidence paths, the Reuse Check result, the external prior, and
explicit acceptance criteria — then the required procedure
(`Reuse Check → External Knowledge → MAA → Minimal Patch → Test → Live Verify →
Evidence → Commit/Push`) and the permanent boundaries.

Three things about it are deliberate:

- **The WorldState names its own provenance.** `LIVE_AT_ESCALATION`,
  `REPLAYED_FROM_LAST_LIVE_EPISODE` or `NOT_SUPPLIED`. Passed in, it is live;
  recovered from disk, it is replayed from the last episode that had a
  `recorded_at`; absent, it says so. The prompt used to claim "last live
  observation" unconditionally — a claim about a value whose origin it had not
  seen, which is the same mistake as reading a level out of an unobserved dialog.
- **Acceptance criteria are never empty.** `default_acceptance()` supplies the
  project's own bar (verifier actually bound *and dispatched*, a live episode with
  `recorded_at`, evidence on disk, green tests plus `check_wiring problems: 0`,
  and any unsolved part named rather than hidden); a caller can append to it but
  the first four are not removable.
- **Only rows with `recorded_at` count as episodes.** Imported historical rows
  look identical otherwise, and once turned four non-live rows into a
  "4 successful runs" claim.

The prompt is truncated per section (WorldState 4 000 chars, episodes 4 000,
Reuse Check 4 000, external prior 6 000) so a 1 500-row log cannot make it
unusable.

## 5. What comes back

```bash
python tools/workbuddy_bridge.py --status <job-id>     # DONE / FAILED / STOPPED / RUNNING / BLOCKED
python tools/workbuddy_bridge.py --cancel <job-id>     # stops it
```

`JobStatus` is the structured result V2 reads: `verdict` in V2's vocabulary,
`terminal`, `detail`, `result`, timestamps and the raw job. The prompt's last
section asks the agent for status, root cause, files changed, evidence path,
commit hash, and explicitly for anything still unproven.

## 6. Measured transport facts

Full transcript and the exact payloads: `knowledge/failure_patterns/integration/WORKBUDDY_GATEWAY_CONTRACT.md`.
The two that matter operationally:

- `permissionMode: dontAsk` — measured running a shell tool unattended (a probe
  job ran `git rev-parse HEAD` and returned the real hash).
- `bgIsolation: none` — with a worktree the agent's commits land on a throwaway
  branch and V2 never sees them, so the escalation would report success while the
  repository was unchanged.

## 7. Phase 2 (reserved, not implemented)

The reverse direction: V2 exposes an **MCP server** so a WorkBuddy agent can query
the live `WorldState`, evidence frames, the capability catalog and live-test
status directly instead of receiving a frozen snapshot inside a prompt.

Seam: the prompt-building half of `workbuddy_bridge.py` is already pure and
separable from the transport half, so phase 2 changes `submit`, not the context.
It must reuse the existing read paths — `learning/episodes.jsonl`, `dataset/`,
`docs/CAPABILITY_COVERAGE.md`, `knowledge/goals/capability_skill_map.json` — and
must not introduce a new store to serve. Anything that reads the device has to go
through the one runtime that owns the device connection.
