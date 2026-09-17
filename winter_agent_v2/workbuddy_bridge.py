"""Escalation transport: V2 hands a *stuck* capability to a local WorkBuddy agent.

What this is for
----------------
V2 is good at the two things it was built for -- deciding what to do next, and
proving whether it happened.  It is bad at one thing: discovering a game
mechanic or a UI surface that nobody in the project has ever seen.  When V2 hits
that wall it currently burns the whole timebox and stops.  This module is the
exit: it packages everything V2 already knows into one task for a local
WorkBuddy (CodeBuddy) background agent, and reports back what that agent found.

The transport is the **official** CodeBuddy HTTP gateway -- ``codebuddy --serve``
-- and specifically its ``/api/v1/jobs`` family, measured live on 2026-09-17
against 2.137.1 (see ``knowledge/failure_patterns/integration/`` for the probe
transcript).  No third-party proxy is involved, and none should be added: the
endpoints below are the product's own contract.

    is_available()      GET  /api/v1/health
    submit(context)     POST /api/v1/jobs
    status(job_id)      GET  /api/v1/jobs/{id}
    cancel(job_id)      POST /api/v1/jobs/{id}/stop

Why ``/jobs`` and not ``/runs``
-------------------------------
``/api/v1/runs`` exists too, but it is the interactive Gateway-Protocol path: it
returns a ``runId`` you are expected to follow over SSE.  ``/jobs`` is the
*background agent* path -- it returns a job with a durable id, a ``state``
(``working`` / ``blocked`` / ``done`` / ``failed`` / ``stopped``), a ``settled``
flag, ``startedAt`` / ``firstTerminalAt`` timestamps and an ``output`` object.
That is pollable, survives the dispatching process, and is what
``codebuddy agents --jobs`` shows, so an operator can audit an escalation with
the product's own tooling.

What it deliberately does not do
--------------------------------
It creates no second scheduler, no manager, no registry, and holds no goal
state.  :func:`should_escalate` is a pure predicate over a condition label; the
only decision this module makes is "is this one of the five conditions the
operator allows an escalation for".  Everything else -- when to replan, which
capability matters -- stays in ``brain.py`` / ``scheduler.py``.

Credentials
-----------
Read from the environment, never from the repository::

    CODEBUDDY_GATEWAY_PASSWORD   the gateway password (``--auth password``)
    WORKBUDDY_GATEWAY_URL        optional, defaults to http://127.0.0.1:8080

``config/v2.json`` is intentionally *not* consulted.  This project has a
recorded failure mode of plausible-looking config keys that nothing reads
(``reserve_marches_for_stamina_spend``), and a credential is the worst possible
thing to leave in a tracked file.  :func:`redact` exists so a password can never
reach a prompt, a ledger row or a log line even by accident.

Phase 2 (reserved, not implemented)
-----------------------------------
The reverse direction is planned and the seam is here on purpose: V2 will expose
an **MCP server** so a WorkBuddy agent can query the live ``WorldState``,
evidence frames, the capability catalog and live-verification status directly,
instead of receiving a frozen snapshot inside a prompt.  That is a separate
module (``tools/mcp_winter_agent.py``) and must reuse the existing read paths --
``learning/episodes.jsonl``, ``dataset/`` and ``docs/CAPABILITY_COVERAGE.md`` --
rather than introduce a new store.  Nothing in this module blocks it: the
prompt-building half is already pure and separable from the transport half.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# Fixed on purpose.  An escalation is always about *this* project; letting a
# caller point the agent somewhere else would let V2 edit an unrelated tree.
PROJECT_ROOT = Path(r"E:\无尽冬日智能体")

ENV_BASE_URL = "WORKBUDDY_GATEWAY_URL"
ENV_PASSWORD = "CODEBUDDY_GATEWAY_PASSWORD"
ENV_PERMISSION_MODE = "WORKBUDDY_BRIDGE_PERMISSION_MODE"

DEFAULT_BASE_URL = "http://127.0.0.1:8080"

HEALTH_PATH = "/api/v1/health"
JOBS_PATH = "/api/v1/jobs"

# Measured: creating a job returns in ~1 s (the child process starts lazily), but
# a slow first token on the model side is not the caller's problem here.
SUBMIT_TIMEOUT_SECONDS = 60.0
READ_TIMEOUT_SECONDS = 15.0

# ``dontAsk`` was measured to run a shell tool unattended (a probe job ran
# ``git rev-parse HEAD`` and came back with 2f946), which is the minimum for an
# escalation to be able to run pytest and commit.  ``bgIsolation: none`` is the
# other half of the same measurement: with a worktree the agent's edits and
# commits land on a throwaway branch and V2 would never see them.
DEFAULT_PERMISSION_MODE = "dontAsk"
DEFAULT_BG_ISOLATION = "none"

# ---------------------------------------------------------------- escalation gate

CAPABILITY_MISSING = "CAPABILITY_MISSING"
UNKNOWN_UI = "UNKNOWN_UI"
UNKNOWN_GAME_MECHANIC = "UNKNOWN_GAME_MECHANIC"
REPEATED_LIVE_FAILURE = "REPEATED_LIVE_FAILURE"
STUCK_15_MIN = "STUCK_15_MIN"

# The complete list.  Anything absent -- notably an ordinary game tick -- is not
# escalatable, and ``submit`` refuses rather than silently downgrading.  The
# operator's wording for the last one is "15 分钟仍无法解决"; it is the same
# rule as the project's own Reuse Check step 7.
ESCALATION_CONDITIONS: tuple[str, ...] = (
    CAPABILITY_MISSING,
    UNKNOWN_UI,
    UNKNOWN_GAME_MECHANIC,
    REPEATED_LIVE_FAILURE,
    STUCK_15_MIN,
)

# What the escalated agent is asked to do, in order.  Kept identical to the
# operator's doctrine so an escalation cannot become a licence to rewrite the
# architecture.
REQUIRED_PROCEDURE: tuple[str, ...] = (
    "Reuse Check",
    "External Knowledge",
    "MAA",
    "Minimal Patch",
    "Test",
    "Live Verify",
    "Evidence",
    "Commit/Push",
)

# Permanent boundaries.  These mirror 00_MASTER_RULES.md §8b T4 and are repeated
# in every prompt because the agent receiving it has no other context.
HARD_BOUNDARIES: tuple[str, ...] = (
    "No second Scheduler, Manager or Registry. Adapt the existing brain route, "
    "skill, verifier and executor; do not add a parallel one.",
    "MAA is the default UI engine and RapidOCR the text reader. Do not "
    "reimplement ADB screenshot/tap, template search, retry loops or wait-page.",
    "Never enter the repository: real-money payment, recharge, account/role "
    "deletion, account-security or password/binding changes, state transfer.",
    "Never force-push, never rewrite ``main``, never ``--amend`` an existing commit.",
    "Credentials live in environment variables only. Do not write them to any file.",
    "A click that returns success is not a verified capability: promotion "
    "requires a live episode with ``recorded_at``, an evidence frame and a "
    "verifier result.",
)


def is_escalation_condition(value: object) -> bool:
    """True only for the five conditions the operator allows."""
    return isinstance(value, str) and value.strip().upper() in ESCALATION_CONDITIONS


def should_escalate(value: object) -> bool:
    """Pure predicate, no state and no side effect -- the whole gate."""
    return is_escalation_condition(value)


class EscalationRefused(ValueError):
    """Raised when a caller tries to escalate something that is not allowed.

    A refusal is a bug in the caller, not a transport failure, so it raises
    instead of returning a status: silently accepting an ordinary game tick
    would turn this module into a second scheduler by the back door.
    """


class GatewayUnavailable(RuntimeError):
    """The local gateway did not answer.  Callers should use :func:`is_available`."""


# --------------------------------------------------------------------- redaction


def redact(text: str, secrets: Iterable[str | None] = None) -> str:
    """Replace any credential with ``***`` before it can be stored or sent."""
    out = text
    for secret in list(secrets or ()) + [gateway_password()]:
        if secret and len(str(secret)) >= 4:
            out = out.replace(str(secret), "***")
    return out


def gateway_password() -> str | None:
    """The gateway password, from the environment only."""
    value = os.environ.get(ENV_PASSWORD, "")
    return value.strip() or None


def gateway_base_url() -> str:
    value = os.environ.get(ENV_BASE_URL, "")
    return (value.strip() or DEFAULT_BASE_URL).rstrip("/")


# ------------------------------------------------------------------ context shape


def world_state_dict(value: object) -> dict[str, Any]:
    """Normalise a ``WorldState`` (or a mapping, or ``None``) into plain JSON."""
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(k): v for k, v in value.items()}
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            result = to_dict()
        except Exception:  # noqa: BLE001 - a broken observation must not break the escalation
            return {"unavailable": "WorldState.to_dict() raised"}
        if isinstance(result, Mapping):
            return {str(k): v for k, v in result.items()}
    return {"unavailable": f"cannot serialise {type(value).__name__}"}


# Where the WorldState in a prompt came from.  Named rather than assumed, so the
# receiving agent can tell a live observation from a replayed one.
WORLD_STATE_LIVE = "LIVE_AT_ESCALATION"
WORLD_STATE_LAST_EPISODE = "REPLAYED_FROM_LAST_LIVE_EPISODE"
WORLD_STATE_NOT_SUPPLIED = "NOT_SUPPLIED"


def default_acceptance(capability: str) -> tuple[str, ...]:
    """The project's standard bar for a capability to count as verified.

    Supplied by default so "explicit acceptance criteria" is never accidentally
    omitted; a caller may append to it but not weaken the first four.
    """
    return (
        f"{capability} has a verifier bound in the live runtime's VERIFIED_ATOMIC "
        "(or a documented adapter), and it is actually dispatched -- a written "
        "verifier that no dispatch path can reach does not count.",
        f"At least one live episode for {capability} with a ``recorded_at`` "
        "timestamp, a verifier ``ok: true`` and an evidence frame path.",
        "Evidence recorded under ``dataset/truth_audit/`` or "
        "``dataset/raw/control_panel/`` and referenced from the capability "
        "catalog / ``docs/CAPABILITY_COVERAGE.md``.",
        "``python -m pytest tests -q -o tmp_path_retention_policy=all`` green and "
        "``python tools/check_wiring.py`` reporting ``problems: 0``.",
        "Root cause stated in one sentence, and any part left unsolved named "
        "explicitly rather than hidden behind a success message.",
    )


@dataclass(frozen=True)
class EscalationContext:
    """Everything V2 knows about the wall it just hit.

    Required by the operator's spec: capability, current WorldState, failure
    reason, recent episode, evidence path, Reuse Check result, external prior and
    explicit acceptance criteria.  ``condition`` is the gate; ``submit`` refuses
    when it is not one of the five allowed values.
    """

    capability: str
    condition: str
    failure_reason: str
    goal: str = ""
    skill: str = ""
    world_state: Mapping[str, Any] = field(default_factory=dict)
    # Where that WorldState came from.  The prompt used to say "last live
    # observation" unconditionally, which is a claim about a value it had not
    # seen the origin of -- the same class of mistake as reading a level out of
    # an unobserved dialog.
    world_state_source: str = WORLD_STATE_NOT_SUPPLIED
    evidence_paths: tuple[str, ...] = ()
    recent_episodes: tuple[Mapping[str, Any], ...] = ()
    reuse_check: str = ""
    external_prior: str = ""
    acceptance: tuple[str, ...] = ()
    timebox_minutes: int = 45
    notes: str = ""

    def normalised(self) -> "EscalationContext":
        """Canonicalise the two free-form labels and merge the acceptance bar."""
        merged = list(default_acceptance(self.capability))
        for item in self.acceptance:
            if str(item).strip() and str(item).strip() not in merged:
                merged.append(str(item).strip())
        return EscalationContext(
            capability=str(self.capability).strip(),
            condition=str(self.condition).strip().upper(),
            failure_reason=str(self.failure_reason).strip(),
            goal=str(self.goal).strip(),
            skill=str(self.skill).strip(),
            world_state=world_state_dict(self.world_state),
            world_state_source=str(self.world_state_source),
            evidence_paths=tuple(str(p) for p in self.evidence_paths),
            recent_episodes=tuple(dict(e) for e in self.recent_episodes),
            reuse_check=str(self.reuse_check),
            external_prior=str(self.external_prior),
            acceptance=tuple(merged),
            timebox_minutes=int(self.timebox_minutes),
            notes=str(self.notes),
        )


# ------------------------------------------------------------------ prompt build

# Bounded on purpose: a prompt that quotes the whole 1520-episode log would be
# rejected or truncated by the receiving side, and the useful part is the last
# few attempts anyway.
MAX_WORLD_STATE_CHARS = 4000
MAX_EPISODES_CHARS = 4000
MAX_REUSE_CHECK_CHARS = 4000
MAX_EXTERNAL_PRIOR_CHARS = 6000


def _bounded(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + f"\n... [truncated, {len(text) - limit} chars omitted]"


def build_prompt(context: EscalationContext) -> str:
    """Compose the task the WorkBuddy agent receives.

    Pure: same context in, same string out.  Every clause the operator listed is
    present by construction -- if it were left to the caller an escalation would
    eventually be sent without its evidence and look like a vague instruction.
    """
    ctx = context.normalised()
    if not is_escalation_condition(ctx.condition):
        raise EscalationRefused(
            f"{ctx.condition!r} is not an escalation condition; allowed: "
            + ", ".join(ESCALATION_CONDITIONS)
        )
    if not ctx.capability:
        raise EscalationRefused("capability is required")

    state = _bounded(json.dumps(dict(ctx.world_state), ensure_ascii=False, indent=2),
                     MAX_WORLD_STATE_CHARS)
    episodes = _bounded(json.dumps(list(ctx.recent_episodes), ensure_ascii=False, indent=2),
                        MAX_EPISODES_CHARS)
    evidence = "\n".join(f"- {p}" for p in ctx.evidence_paths) or "- (none recorded)"
    acceptance = "\n".join(f"{i}. {a}" for i, a in enumerate(ctx.acceptance, 1))
    procedure = " -> ".join(REQUIRED_PROCEDURE)
    boundaries = "\n".join(f"- {b}" for b in HARD_BOUNDARIES)

    parts = [
        f"# Winter Agent OS V2 escalation: {ctx.capability}",
        "",
        "You are a background agent working inside the Whiteout Survival "
        "automation project at `E:\\无尽冬日智能体`. V2 (the runtime that usually "
        "drives the device) hit a wall it cannot get past and has handed you one "
        "capability. Work only on this capability.",
        "",
        "## Why this was escalated",
        f"- condition  : {ctx.condition}",
        f"- capability : {ctx.capability}",
        f"- goal       : {ctx.goal or '(none)'}",
        f"- skill      : {ctx.skill or '(none)'}",
        f"- timebox    : {ctx.timebox_minutes} minutes",
        "",
        "## Failure",
        ctx.failure_reason or "(not stated)",
        "",
        "## Current WorldState",
        f"source: {ctx.world_state_source}",
        "```json",
        state,
        "```",
        "",
        "## Recent episodes",
        "```json",
        episodes or "[]",
        "```",
        "",
        "## Evidence on disk",
        evidence,
        "",
        "## Reuse Check result (already run by V2 -- start from here, do not redo it)",
        "```",
        _bounded(ctx.reuse_check, MAX_REUSE_CHECK_CHARS) or "(not supplied)",
        "```",
        "",
        "## External prior",
        "```",
        _bounded(ctx.external_prior, MAX_EXTERNAL_PRIOR_CHARS) or "(not supplied)",
        "```",
        "",
        "## Acceptance criteria (all must hold)",
        acceptance,
        "",
        "## Required procedure",
        procedure,
        "",
        "Read the local project rules first: `.workbuddy-ai/handoff/00_MASTER_RULES.md`, "
        "`START_HERE.md` and `docs/ADDING_A_LIVE_ROUTE.md`. External knowledge is a "
        "*prior*, never production truth: probe the current client, then live-verify.",
        "",
        "## Hard boundaries",
        boundaries,
    ]
    if ctx.notes.strip():
        parts += ["", "## Notes from V2", ctx.notes.strip()]
    parts += [
        "",
        "## What to report back",
        "Reply with: (1) status DONE / BLOCKED / PARTIAL, (2) root cause in one "
        "sentence, (3) the exact files changed, (4) the live evidence produced and "
        "its path, (5) the commit hash once pushed, (6) anything still unproven. "
        "If you could not finish, say which of that is missing instead of "
        "describing what you intended.",
    ]
    # Redacted where the text is produced, not only where it is sent: ``--prompt``
    # prints this string straight to a terminal, and masking at one of the two
    # consumers would have left the other one leaking.
    return redact("\n".join(parts))


# ----------------------------------------------------------------- transport types


@dataclass(frozen=True)
class Availability:
    available: bool
    reason: str
    base_url: str = ""
    detail: Mapping[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:  # so ``if bridge.is_available():`` reads naturally
        return self.available

    def describe(self) -> str:
        lines = [f"gateway    : {self.base_url or '(unset)'}",
                 f"verdict    : {self.reason}"]
        if self.detail:
            lines.append(f"detail     : {json.dumps(dict(self.detail), ensure_ascii=False)[:300]}")
        return "\n".join(lines)


@dataclass(frozen=True)
class Submission:
    job_id: str
    state: str
    name: str = ""
    cwd: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict)


# V2's own vocabulary for what the escalation is doing, so a caller never has to
# know the gateway's words.
VERDICT_RUNNING = "RUNNING"
VERDICT_DONE = "DONE"
VERDICT_FAILED = "FAILED"
VERDICT_STOPPED = "STOPPED"
VERDICT_BLOCKED = "BLOCKED"
VERDICT_UNKNOWN = "UNKNOWN"

_GATEWAY_TO_VERDICT = {
    "working": VERDICT_RUNNING,
    "blocked": VERDICT_BLOCKED,
    "done": VERDICT_DONE,
    "failed": VERDICT_FAILED,
    "stopped": VERDICT_STOPPED,
}
TERMINAL_VERDICTS = frozenset({VERDICT_DONE, VERDICT_FAILED, VERDICT_STOPPED})


@dataclass(frozen=True)
class JobStatus:
    job_id: str
    gateway_state: str
    verdict: str
    detail: str = ""
    settled: bool = False
    alive: bool = False
    cwd: str = ""
    result: str = ""
    started_at: int | None = None
    first_terminal_at: int | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def terminal(self) -> bool:
        return self.verdict in TERMINAL_VERDICTS or self.settled

    def describe(self) -> str:
        lines = [f"job        : {self.job_id}",
                 f"verdict    : {self.verdict} (gateway state={self.gateway_state}, settled={self.settled})",
                 f"detail     : {self.detail or '(none)'}"]
        if self.result:
            lines.append(f"result     : {redact(self.result)[:600]}")
        return "\n".join(lines)


# --------------------------------------------------------------- the bridge class


class WorkBuddyBridge:
    """The four operations.  Nothing else lives here on purpose.

    ``_request`` is the single seam over HTTP so tests can drive the transport
    without a live gateway; production code must not monkeypatch it.
    """

    def __init__(
        self,
        base_url: str | None = None,
        password: str | None = None,
        *,
        cwd: Path | str = PROJECT_ROOT,
        permission_mode: str | None = None,
        bg_isolation: str = DEFAULT_BG_ISOLATION,
        ledger_path: Path | None = None,
        timeout: float = READ_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = (base_url or gateway_base_url()).rstrip("/")
        # Deliberately not stored on ``self``: a password held as an attribute
        # ends up in a repr, a traceback or a dataclass dump sooner or later.
        self._password = password if password is not None else gateway_password()
        self.cwd = Path(cwd)
        self.permission_mode = (
            permission_mode
            or os.environ.get(ENV_PERMISSION_MODE, "").strip()
            or DEFAULT_PERMISSION_MODE
        )
        self.bg_isolation = bg_isolation
        self.ledger_path = Path(ledger_path) if ledger_path else self.cwd / "learning/workbuddy_escalations.jsonl"
        self.timeout = timeout

    # -- plumbing ---------------------------------------------------------

    def __repr__(self) -> str:  # never leak the credential through a repr
        return (f"WorkBuddyBridge(base_url={self.base_url!r}, cwd={str(self.cwd)!r}, "
                f"permission_mode={self.permission_mode!r}, has_password={bool(self._password)})")

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> tuple[int, dict[str, Any]]:
        """One HTTP round trip.  Returns ``(status_code, parsed_body)``."""
        url = f"{self.base_url}{path}"
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        if self._password:
            headers["Authorization"] = f"Bearer {self._password}"

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                body = response.read().decode("utf-8", "replace")
                return response.status, _parse_json(body)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            return exc.code, _parse_json(body)
        except urllib.error.URLError as exc:
            raise GatewayUnavailable(f"{url}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise GatewayUnavailable(f"{url}: timed out after {timeout or self.timeout}s") from exc

    # -- 1. is_available --------------------------------------------------

    def is_available(self) -> Availability:
        """Probe ``GET /api/v1/health``.  Never raises: a down gateway is an answer."""
        if not self._password:
            return Availability(
                False,
                "NO_CREDENTIAL",
                self.base_url,
                {"fix": f"set {ENV_PASSWORD} in the environment (never in the repo)"},
            )
        try:
            code, body = self._request("GET", HEALTH_PATH, timeout=min(self.timeout, 8.0))
        except GatewayUnavailable as exc:
            return Availability(False, "GATEWAY_UNREACHABLE", self.base_url, {"error": str(exc)})

        if code == 200 and isinstance(body.get("data"), Mapping):
            data = dict(body["data"])
            status = str(data.get("status", ""))
            if status == "ok":
                return Availability(True, "OK", self.base_url, data)
            return Availability(False, f"UNHEALTHY:{status or 'no status'}", self.base_url, data)
        if code == 401:
            return Availability(False, "AUTH_REJECTED", self.base_url, _error_of(body))
        return Availability(False, f"HTTP_{code}", self.base_url, _error_of(body))

    # -- 2. submit --------------------------------------------------------

    def submit(
        self,
        context: EscalationContext,
        *,
        name: str | None = None,
        model: str | None = None,
        effort: str | None = None,
    ) -> Submission:
        """Dispatch one escalation as a background agent job.

        Refuses anything outside the five conditions *before* touching the
        network, then writes one ledger row so the escalation is auditable.
        """
        ctx = context.normalised()
        prompt = build_prompt(ctx)  # raises EscalationRefused on a bad condition

        payload: dict[str, Any] = {
            # ``build_prompt`` already masks the environment credential; the
            # explicit one is masked here too, because a password handed to the
            # constructor is unknown to ``redact``'s environment lookup.
            "prompt": redact(prompt, [self._password]),
            "cwd": str(self.cwd),
            "name": name or f"V2 escalation: {ctx.capability}",
            "permissionMode": self.permission_mode,
            "bgIsolation": self.bg_isolation,
        }
        if model:
            payload["model"] = model
        if effort:
            payload["effort"] = effort

        code, body = self._request("POST", JOBS_PATH, payload, timeout=SUBMIT_TIMEOUT_SECONDS)
        data = body.get("data") if isinstance(body.get("data"), Mapping) else {}
        if code != 200 or not data:
            self._ledger({
                "event": "submit_failed",
                "capability": ctx.capability,
                "condition": ctx.condition,
                "http_status": code,
                "error": _error_of(body),
            })
            raise GatewayUnavailable(
                f"POST {JOBS_PATH} -> HTTP {code}: "
                f"{json.dumps(_error_of(body), ensure_ascii=False)}"
            )

        submission = Submission(
            job_id=str(data.get("id", "")),
            state=str(data.get("state", "")),
            name=str(data.get("name", "")),
            cwd=str(data.get("cwd", "")),
            raw=dict(data),
        )
        self._ledger({
            "event": "submitted",
            "job_id": submission.job_id,
            "capability": ctx.capability,
            "condition": ctx.condition,
            "goal": ctx.goal,
            "skill": ctx.skill,
            "session_id": data.get("sessionId"),
            "permission_mode": self.permission_mode,
            "bg_isolation": self.bg_isolation,
        })
        return submission

    # -- 3. status --------------------------------------------------------

    def status(self, job_id: str) -> JobStatus:
        """Read one job back.  Raises :class:`GatewayUnavailable` if it cannot."""
        code, body = self._request("GET", f"{JOBS_PATH}/{job_id}")
        data = body.get("data") if isinstance(body.get("data"), Mapping) else {}
        job = data.get("job") if isinstance(data.get("job"), Mapping) else {}
        if not job:
            raise GatewayUnavailable(
                f"GET {JOBS_PATH}/{job_id} -> HTTP {code}: "
                f"{json.dumps(_error_of(body), ensure_ascii=False)}"
            )
        gateway_state = str(job.get("state", ""))
        output = job.get("output") if isinstance(job.get("output"), Mapping) else {}
        return JobStatus(
            job_id=str(job.get("id", job_id)),
            gateway_state=gateway_state,
            verdict=_GATEWAY_TO_VERDICT.get(gateway_state, VERDICT_UNKNOWN),
            detail=str(job.get("detail", "")),
            settled=bool(job.get("settled", False)),
            alive=bool(job.get("alive", False)),
            cwd=str(job.get("cwd", "")),
            result=str(output.get("result", "")) if output else "",
            started_at=_as_int(job.get("startedAt")),
            first_terminal_at=_as_int(job.get("firstTerminalAt")),
            raw=dict(job),
        )

    # -- 4. cancel --------------------------------------------------------

    def cancel(self, job_id: str) -> bool:
        """Stop a running job.  ``True`` when the gateway reports it stopped."""
        code, body = self._request("POST", f"{JOBS_PATH}/{job_id}/stop")
        data = body.get("data") if isinstance(body.get("data"), Mapping) else {}
        stopped = bool(data.get("stopped", False))
        self._ledger({"event": "cancel" if stopped else "cancel_failed",
                      "job_id": job_id, "http_status": code})
        if not stopped:
            raise GatewayUnavailable(
                f"POST {JOBS_PATH}/{job_id}/stop -> HTTP {code}: "
                f"{json.dumps(_error_of(body), ensure_ascii=False)}"
            )
        return True

    # -- audit trail ------------------------------------------------------

    def _ledger(self, row: Mapping[str, Any]) -> None:
        """Append one audit row.  Never raises: the transport must not fail on it.

        This is the evidence that an escalation only ever happened for one of
        the five allowed conditions -- without it, "ordinary game ticks never
        call WorkBuddy" would be an unverifiable claim.
        """
        try:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            record = dict(row)
            record["recorded_at"] = datetime.now(timezone.utc).isoformat()
            line = redact(json.dumps(record, ensure_ascii=False))
            with self.ledger_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except Exception:  # noqa: BLE001 - audit failure must not break an escalation
            pass


def bridge_from_environment(**kwargs: Any) -> WorkBuddyBridge:
    """Convenience constructor: URL and password both come from the environment."""
    return WorkBuddyBridge(permission_mode=kwargs.pop("permission_mode", None), **kwargs)


# ------------------------------------------------------------------- small helpers


def _parse_json(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"_raw": text[:1000]}
    return parsed if isinstance(parsed, dict) else {"_raw": parsed}


def _error_of(body: Mapping[str, Any]) -> dict[str, Any]:
    error = body.get("error")
    if isinstance(error, Mapping):
        return dict(error)
    return {"raw": json.dumps(dict(body), ensure_ascii=False)[:400]} if body else {}


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def recent_episodes(
    path: Path | str | None = None,
    *,
    limit: int = 3,
    skill: str | None = None,
) -> tuple[dict[str, Any], ...]:
    """The last few episodes, optionally filtered to one skill.

    Only rows carrying ``recorded_at`` are real device evidence -- the project's
    own rule, because imported historical rows look identical otherwise and once
    turned four non-live rows into a "4 successful runs" claim.
    """
    target = Path(path) if path else PROJECT_ROOT / "learning/episodes.jsonl"
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    rows: list[dict[str, Any]] = []
    for line in reversed(lines):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not row.get("recorded_at"):
            continue
        if skill and row.get("skill") != skill:
            continue
        rows.append(row)
        if len(rows) >= limit:
            break
    return tuple(reversed(rows))


def evidence_paths_for(capability: str, root: Path | str | None = None, *, limit: int = 12) -> tuple[str, ...]:
    """Shallowest evidence directories whose name mentions the capability.

    Read-only glob over the two places the project already keeps frames in.
    Empty is a valid answer and is reported as such rather than papered over.

    Two corrections are baked in.  The needle and the haystack are normalised the
    same way, because an earlier version stripped ``_`` from the path but not from
    ``BUILDING_UPGRADE`` so the match could never fire.  And direct children are
    *kept* -- the evidence directory itself (``power_route_20260917``) is the
    useful answer, not its ``key`` subfolder; descendants of an already-reported
    directory are dropped for that reason.
    """
    base = Path(root) if root else PROJECT_ROOT
    needle = _evidence_key(capability)
    if not needle:
        return ()

    matches: list[Path] = []
    for parent in (base / "dataset/truth_audit", base / "dataset/raw/control_panel"):
        if not parent.is_dir():
            continue
        for child in parent.rglob("*"):
            if child.is_dir() and needle in _evidence_key(child.name):
                matches.append(child)

    matches.sort(key=lambda path: (len(path.parts), str(path)))
    kept: list[Path] = []
    for candidate in matches:
        if any(candidate.is_relative_to(already) for already in kept):
            continue
        kept.append(candidate)
        if len(kept) >= limit:
            break
    return tuple(str(path) for path in kept)


def _evidence_key(text: str) -> str:
    """Lower-case, separator-free form used for both sides of the match."""
    return "".join(ch for ch in str(text).lower() if ch.isalnum())


def escalation_request_from_project(
    capability: str,
    condition: str,
    failure_reason: str,
    *,
    goal: str = "",
    skill: str = "",
    world_state: object = None,
    evidence_paths: Sequence[str] = (),
    reuse_check: str = "",
    external_prior: str = "",
    notes: str = "",
    timebox_minutes: int = 45,
    root: Path | str | None = None,
) -> EscalationContext:
    """Build a context, filling episodes, evidence and WorldState from disk.

    Keeps the mechanical parts (read the log, find the frames, recover the last
    observation) in one place so a caller cannot forget them and send an
    escalation with no evidence.  ``world_state`` passed explicitly is labelled
    ``LIVE_AT_ESCALATION``; recovered from the last episode it is labelled
    ``REPLAYED_FROM_LAST_LIVE_EPISODE``; neither available is
    ``NOT_SUPPLIED``.  The three are never conflated.
    """
    base = Path(root) if root else PROJECT_ROOT
    episodes = recent_episodes(base / "learning/episodes.jsonl", skill=skill or None)

    source = WORLD_STATE_NOT_SUPPLIED
    state: object = world_state
    if world_state is not None:
        source = WORLD_STATE_LIVE
    else:
        latest = recent_episodes(base / "learning/episodes.jsonl", limit=1)
        if latest and isinstance(latest[-1].get("state_before"), Mapping):
            state = latest[-1]["state_before"]
            source = WORLD_STATE_LAST_EPISODE

    return EscalationContext(
        capability=capability,
        condition=condition,
        failure_reason=failure_reason,
        goal=goal,
        skill=skill,
        world_state=world_state_dict(state),
        world_state_source=source,
        evidence_paths=tuple(evidence_paths) or evidence_paths_for(capability, base),
        recent_episodes=episodes,
        reuse_check=reuse_check,
        external_prior=external_prior,
        notes=notes,
        timebox_minutes=timebox_minutes,
    )
