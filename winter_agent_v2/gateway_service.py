"""The gateway's lifecycle, because a system that cannot start its own developer is not unattended.

The gap this closes
-------------------
Every other link in the chain was wired: the queue pump consumed ``NEW``, the adapter
folded the ledger, the bridge knew the jobs API, the panel displayed the health.  What
did not exist was anything that *starts* the gateway.  ``winproc.port_owner`` even said
so, in prose: "Nothing in this project starts the service -- ``codebuddy --serve`` is
started by hand".

Measured consequence, 2026-09-18 18:04 local: ``pump.json`` read ``errors 17`` with
``last_error`` = ``status(d8ea0e44) failed: [WinError 10061] 由于目标计算机积极拒绝``,
and ``winproc.port_owner(8080)`` returned ``(0, '')``.  The whole development loop was
stopped, not by a bug in the loop, but by an operator prerequisite nobody had automated.
An "unattended" system whose first step is a manual ``codebuddy --serve`` in another
terminal is not unattended.

What this module is not
-----------------------
Not a second scheduler, not a job registry, not a state machine over jobs.  It knows
exactly one thing: whether a *process* is listening on the port, and if not, how to start
one.  Job state stays where it was -- ``workbuddy_escalations.jsonl`` and the adapter
that folds it.  The lifecycle record this module persists holds a pid, a launch time and
a failure ladder; nothing in it can be mistaken for the answer to "what is capability X
doing".

The two decisions that are easy to get wrong
--------------------------------------------
1. **Restart is not "spawn again".**  Measured 2026-09-18: a probe that failed once was
   answered by launching another gateway, and two instances fought over 8080.  So the
   ladder is: one failure is information, ``DEGRADED_AFTER_FAILURES`` consecutive
   failures is a state change, and only a state change may spawn.  A port that is
   already taken by an unknown process is ``PORT_CONFLICT`` -- reported, never killed.
2. **``STARTING`` is a real state and must be waited out.**  ``codebuddy --serve`` takes
   seconds to bind.  A launcher that re-checks the port in the same breath sees nothing
   listening and starts a second one.  ``STARTUP_GRACE_SECONDS`` is the window in which
   "not listening yet" is expected rather than a fault.

The credential rule
-------------------
The password comes from the environment (``CODEBUDDY_GATEWAY_PASSWORD``) and is passed to
the child by inheritance.  It is never written to the repository, never placed on the
command line, and ``--auth none`` is never used.  With no credential available the
service refuses to start and says ``NO_CREDENTIAL``: a gateway whose password the bridge
does not know is a gateway that will answer 401 forever, which is worse than an honest
"not started".
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import winproc

# --------------------------------------------------------------------- lifecycle states

#: A launch has been issued and the port is expected to come up within the grace window.
STARTING = "STARTING"
#: ``GET /api/v1/health`` answered 200 with ``status: ok``.
HEALTHY = "HEALTHY"
#: Consecutive probe failures crossed the threshold.  Eligible for a restart.
DEGRADED = "DEGRADED"
#: Nothing is listening and no launch is pending.
OFFLINE = "OFFLINE"
#: A restart is being issued right now.
RESTARTING = "RESTARTING"
#: Something else owns the port.  Not ours to kill.
PORT_CONFLICT = "PORT_CONFLICT"
#: The port owner is not answering health and is not ours -- same handling, different cause.
UNREACHABLE = "UNREACHABLE"
#: The gateway is *answering* and refusing us (401/403): alive, misconfigured, restart-proof.
REJECTING = "REJECTING"
#: Cannot start: no password in the environment.  Refusing beats starting a 401 machine.
NO_CREDENTIAL = "NO_CREDENTIAL"
#: Not started because the operator said STOP.  The watchdog must not override a human.
PASSIVE_STOPPED = "PASSIVE_STOPPED"
#: No probe has run yet.
UNKNOWN = "UNKNOWN"

STATES = (STARTING, HEALTHY, DEGRADED, OFFLINE, RESTARTING, PORT_CONFLICT, UNREACHABLE,
          REJECTING, NO_CREDENTIAL, PASSIVE_STOPPED, UNKNOWN)

# --------------------------------------------------------------------- decisions (actions)

ACT_PASSIVE = "PASSIVE"          # operator said STOP: report only
ACT_REUSE = "REUSE"              # a healthy gateway already exists: adopt it
ACT_WAIT = "WAIT"                # a launch is in flight, or the ladder says not yet
ACT_START = "START"              # nothing running and nothing pending: start one
ACT_RESTART = "RESTART"          # ours, but dead or wedged: replace it
ACT_PORT_CONFLICT = "PORT_CONFLICT"
ACT_NO_CREDENTIAL = "NO_CREDENTIAL"

#: Consecutive failed probes before the state becomes DEGRADED.  One timeout is not a state.
DEGRADED_AFTER_FAILURES = 3

#: How long "not bound yet" is expected rather than a fault.  ``--serve`` binds in a few
#: seconds; this is generous because a cold Node start on this machine has been measured
#: at over ten seconds, and a grace window that is too short recreates the double-start it
#: exists to prevent.
STARTUP_GRACE_SECONDS = 90.0

#: Restart back-off, in seconds, indexed by consecutive restart attempts.  The last rung
#: repeats, so a gateway that comes back after an hour is still noticed.
RESTART_BACKOFF = (30.0, 60.0, 120.0, 300.0)

#: Environment variables.  A credential is read from the environment only.
ENV_PASSWORD = "CODEBUDDY_GATEWAY_PASSWORD"
ENV_NODE = "CODEBUDDY_NODE_BIN"
ENV_APP_PATH = "WORKBUDDY_APP_PATH"

#: The bundle selector the WorkBuddy host sets on every CLI child it spawns.
#:
#: ``cli/bin/codebuddy`` routes to one of three bundles, and the routing is decided by argv
#: **or** by this environment variable -- there is no fourth branch:
#:
#:     CODEBUDDY_FORCE_LITE_WB_BUNDLE=1   -> dist/codebuddy-lite-wb.mjs  (ESM)
#:     CODEBUDDY_FORCE_HEADLESS_BUNDLE=1  -> dist/codebuddy-headless.js
#:     neither, and no --print/-p/--acp/--bg/--help on argv
#:                                        -> dist/codebuddy.js   <-- **does not ship in this
#:                                                                   install**
#:
#: Re-measured 2026-09-24 against 2.137.1, ``app.asar.unpacked/cli/dist`` holds exactly
#: ``codebuddy-headless.js`` and ``codebuddy-lite-wb.mjs``; there is no ``codebuddy.js``.  The
#: last branch therefore ends in ``MODULE_NOT_FOUND`` at ``bin/codebuddy:205`` and the process
#: exits in about a second.  Reproduced directly on this machine:
#:
#:     $ unset CODEBUDDY_FORCE_HEADLESS_BUNDLE CODEBUDDY_FORCE_LITE_WB_BUNDLE
#:     $ node bin/codebuddy --serve --port 18099 --session-id probe
#:     Error: Cannot find module '../dist/codebuddy'   ... bin/codebuddy:205:13   exit 1
#:     $ CODEBUDDY_FORCE_HEADLESS_BUNDLE=1 node bin/codebuddy --serve ...   -> boots, binds
#:
#: **Why this project, and not only the desktop, has to set it.**  The gateway forks every
#: background job as ``node <cli>/bin/codebuddy <prompt> --session-id … --model …`` with
#: ``env = {...process.env}`` (``forkBgSession`` -> ``forkDetached``), and it adds only
#: ``CODEBUDDY_JOB_*``; it never adds a bundle flag.  So the bundle a job worker loads is
#: decided entirely by the *gateway's* environment -- which is *this* launcher's environment,
#: because :meth:`GatewayService._spawn` starts the gateway with ``{**self.env, **plan.env}``.
#: A gateway started without this variable is a gateway that boots (nothing selected it) and
#: whose every job dies before it can read a screenshot: the reaper then reports the job as
#: ``failed / session ended — press enter to restart it``, which says nothing about the real
#: cause.  That was the measured state of the UNKNOWN channel on 2026-09-24: 7 questions
#: pending, every one of them ``no job``, and three job logs on disk carrying the same
#: ``Cannot find module '../dist/codebuddy'``.
#:
#: Headless rather than lite-wb on purpose: a job worker is a full non-TUI agent turn, and
#: ``--print`` / ``--acp`` / ``--bg`` all route to the headless bundle, so it is the one this
#: role's own argv would have chosen.  Both are verified to boot ``--serve`` on this machine.
ENV_FORCE_HEADLESS_BUNDLE = "CODEBUDDY_FORCE_HEADLESS_BUNDLE"

#: Where the CLI lives inside the desktop application bundle.  Recorded in
#: ``knowledge/failure_patterns/integration/WORKBUDDY_GATEWAY_CONTRACT.md`` §1, which is
#: where the measurement that ``which codebuddy`` fails on this machine comes from.
CLI_RELATIVE = Path("cli/bin/codebuddy")

DEFAULT_PORT = 8080

#: The session id the measured contract uses.  A fixed value, not a model choice: it names
#: this project's gateway so ``codebuddy ps`` shows one obvious entry.
SESSION_ID = "winter-agent-v2"

#: Environment variable that moves the gateway's log, for a machine where the default
#: location is not writable or a test needs it in a temp directory.
ENV_LOG_DIR = "WINTER_AGENT_GATEWAY_LOG_DIR"

#: An explicit path to the CLI, for a machine where nothing else in the discovery chain
#: answers.  Named rather than guessed at: the工单 asks that starting the gateway not depend
#: on the desktop having started normally, and the last resort has to be something an
#: operator can set deliberately.
ENV_CLI_OVERRIDE = "WINTER_AGENT_CODEBUDDY_CLI"

#: Variables that mark "this process is inside an agent's tool call", which a *service* must not
#: inherit from whatever shell happened to start it.
#:
#: Measured 2026-09-24, and it cost the whole channel its ability to create a job.  A gateway
#: started from a WorkBuddy agent shell carries that shell's tool-harness environment, and
#: ``forkBgSession`` passes ``{...process.env}`` of the gateway to every job worker -- so the
#: worker's PowerShell sessions found ``CODEBUDDY_TOOL_CALL_ID`` and the safe-delete shim's own
#: configuration and **armed the bulk-delete guard**:
#:
#:     POST /api/v1/jobs -> HTTP 500
#:     {"code":"INTERNAL_ERROR","message":"[safe-delete][SAFE_DELETE_BULK_CONFIRM_REQUIRED]
#:      {\"count\":89,\"threshold\":50,\"scope\":\"turn\",\"targets\":[\"…\\.locks\\…\"]}"}
#:
#: The 89 paths were the gateway's **own** stale job locks, which it garbage-collects at job
#: creation.  Nothing about the request was wrong; the guard was armed by a variable that names a
#: tool call from a completely different session -- the same class of leak the product itself
#: scrubs with ``scrubRequestContextFromEnv`` before forking a long-lived process.
#:
#: The guard is the host's feature and stays armed for the host's interactive sessions; it is not
#: this service's to inherit.  Named one by one rather than matched by a ``CODEBUDDY_`` prefix: the
#: same environment legitimately carries settings the CLI reads (``CODEBUDDY_FORCE_*_BUNDLE``,
#: ``CODEBUDDY_NODE_BIN``), and a prefix rule would take those with it.
AGENT_SESSION_MARKERS: tuple[str, ...] = (
    "CODEBUDDY_TOOL_CALL_ID",
    "CODEBUDDY_CONVERSATION_REQUEST_ID",
    "CODEBUDDY_CONVERSATION_MESSAGE_ID",
    "CODEBUDDY_SAFE_DELETE_ENABLED",
    "CODEBUDDY_SAFE_DELETE_BULK_GUARD",
    "CODEBUDDY_SAFE_DELETE_BULK_STATE_DIR",
    "CODEBUDDY_SAFE_DELETE_BULK_THRESHOLD",
    "CODEBUDDY_SAFE_DELETE_BULK_REPLAY_FILE",
)


def service_environment(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """The launcher's environment with the agent-session markers removed.

    Only removals -- every other variable is inherited exactly as it was, including the credential,
    which is why the gateway is started with this rather than with a built-up environment.  See
    :data:`AGENT_SESSION_MARKERS` for the measurement that made this necessary.
    """
    source = os.environ if env is None else env
    blocked = {name.upper() for name in AGENT_SESSION_MARKERS}
    return {key: value for key, value in source.items() if key.upper() not in blocked}


def default_log_path() -> Path:
    """Where the gateway's stdout goes.  **Outside the repository, deliberately.**

    Measured 2026-09-18, first live launch: ``codebuddy --serve`` announces its effective
    password on stdout --

        Endpoint    http://127.0.0.1:8080
        Web UI      http://127.0.0.1:8080/?password=<24 bytes of base64url>
        Password    <the same value>

    -- so whatever file receives that banner contains a working credential.  The natural
    place for it looked like ``learning/control_panel/gateway.log``, beside the panel's own
    logs, and ``git status`` showed it as an untracked file inside the tree: one ``git add``
    from committing a live password.  The project's rule is that the credential lives in the
    environment or the existing secure config and never in the repository, and a log file
    that happens to sit in the repository is the repository.

    So it goes under the user's local application data, beside the machine's other runtime
    state.  ``cwd`` stays the project root -- that is a separate requirement (§三) and the
    gateway must run in the tree it is asked to work on.
    """
    override = str(os.environ.get(ENV_LOG_DIR) or "").strip()
    if override:
        return Path(override) / "gateway.log"
    base = str(os.environ.get("LOCALAPPDATA") or "").strip()
    root = Path(base) / "WinterAgentV2" if base else Path(tempfile.gettempdir()) / "WinterAgentV2"
    return root / "gateway.log"


class GatewayStartRefused(RuntimeError):
    """Starting was decided against, with a reason an operator can act on."""


# --------------------------------------------------------------------- launch plan


@dataclass(frozen=True)
class LaunchPlan:
    """Everything needed to start one gateway, with the credential left in the env."""

    argv: tuple[str, ...]
    cwd: Path
    log_path: Path
    #: Environment *additions*, never replacements, and never containing the password --
    #: it is already in the parent environment and is inherited.
    env: Mapping[str, str] = field(default_factory=dict)
    #: Which link of the discovery chain answered, kept so §1 of the工单 can be audited.
    cli: str = ""
    cli_source: str = ""

    def as_record(self) -> dict[str, Any]:
        """The launch, as it may be persisted: argv is safe, the password is not present."""
        return {"argv": list(self.argv), "cwd": str(self.cwd), "log_path": str(self.log_path),
                "cli": self.cli, "cli_source": self.cli_source}


def cli_path(env: Mapping[str, str] | None = None) -> Path | None:
    """The bundled ``codebuddy`` entry point from the desktop's own environment, or ``None``.

    One link of :func:`discover_cli`'s chain, kept separate because it is the only link the
    desktop sets up for us -- and, measured 2026-09-18, the only one the first version had.
    A launcher that did not inherit that environment therefore could not start a gateway at
    all, which is why the chain no longer ends here.
    """
    environment = env if env is not None else os.environ
    app_path = str(environment.get(ENV_APP_PATH) or "").strip()
    if not app_path:
        return None
    base = Path(app_path)
    # ``app.asar`` -> ``app.asar.unpacked``: the packed archive holds no executables.
    unpacked = base.with_name(base.name + ".unpacked") if base.suffix == ".asar" else base
    return _candidate_from_root(unpacked) or _candidate_from_root(base)


def node_path(env: Mapping[str, str] | None = None) -> str:
    """The interpreter that runs the CLI.  The managed Node the desktop app itself uses."""
    environment = env if env is not None else os.environ
    return str(environment.get(ENV_NODE) or "").strip() or "node"


def _candidate_from_root(base: Path) -> Path | None:
    """The bundled CLI under ``base``, accepting any of the roots its callers actually hold.

    ``base`` may be the install root (``...\\WorkBuddy``), its ``resources`` directory, or
    the unpacked directory itself.  Measuring this once, in one place, is cheaper than four
    callers each guessing which one they have -- and the first version did guess wrong: it
    passed the *install root* to a helper that expected the unpacked directory, so the
    desktop-derivation link silently never matched and the refusal message claimed nothing
    on disk when the binary was there.  ``CLI_RELATIVE`` is relative to
    ``app.asar.unpacked``; the install-root case needs ``resources`` prepended, and that is
    the layout measured on this machine (``E:\\work Buddy国内\\WorkBuddy\\resources\\...``).
    """
    for candidate in (
        base / CLI_RELATIVE,                                       # app.asar.unpacked
        base / "app.asar.unpacked" / CLI_RELATIVE,                  # resources/
        base / "resources" / "app.asar.unpacked" / CLI_RELATIVE,    # the install root
    ):
        if candidate.exists():
            return candidate
    return None


def running_desktop_exe(timeout: float = 90.0) -> str:
    """Where the desktop's own binary lives, asked of the OS rather than of the environment.

    Measured 2026-09-18, and this is the whole point of the工单: the panel was refused a
    gateway because ``WORKBUDDY_APP_PATH`` was missing -- that variable is set *for the
    desktop's children*, and the panel had been launched by a different agent's
    interpreter.  The desktop was running the entire time.  A running process knows where
    its own binary is, so this asks that instead of asking a variable the launcher may not
    have passed on.  Cost measured at 0.35s, and it is only reached when the environment
    and the remembered plan have both failed to answer.
    """
    script = (
        "$p = Get-CimInstance Win32_Process -Filter \"Name='WorkBuddy.exe'\" "
        "| Select-Object -First 1 -ExpandProperty ExecutablePath; if ($p) { Write-Output $p }"
    )
    result = winproc.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                         timeout=timeout)
    return (result.stdout or "").strip().splitlines()[0].strip() if result.stdout else ""


def discover_cli(env: Mapping[str, str] | None = None,
                 remembered: Path | str | None = None,
                 desktop_exe: Callable[[], str] | None = None) -> tuple[Path | None, str]:
    """``(cli, how_it_was_found)`` -- a chain, because no single link is guaranteed.

    The operator's §5 is explicit that starting the gateway must not depend on the desktop
    having started normally.  Reading only ``WORKBUDDY_APP_PATH`` failed exactly that way:
    measured 2026-09-18, the panel sat in ``OFFLINE / RESTART / restart_attempts 0`` with
    ``consecutive_failures`` climbing to 20, refusing every attempt with "找不到 codebuddy
    CLI" while a working command line was already written down in its own record and the
    binary was on disk the whole time.

    So, in order: an explicit operator override, the desktop's environment (best when
    present), **the plan that was recorded when this worked before**, and finally the
    running desktop's own image path.  The provenance is returned rather than discarded:
    §1 of the工单 asks which of these is actually being used, and a discovery nobody can
    audit is a guess with a filename.

    ``desktop_exe`` is injectable so a test does not silently depend on whether a real
    desktop happens to be installed on the machine running the suite.
    """
    environment = env if env is not None else os.environ

    override = str(environment.get(ENV_CLI_OVERRIDE) or "").strip()
    if override and Path(override).exists():
        return Path(override), f"{ENV_CLI_OVERRIDE}（操作员显式指定）"

    found = cli_path(environment)
    if found is not None:
        return found, f"{ENV_APP_PATH}={environment.get(ENV_APP_PATH)}"

    if remembered:
        candidate = Path(str(remembered))
        if candidate.exists():
            return candidate, "上一次成功启动时记录的路径（环境变量缺失，但这条命令跑通过）"

    probe = desktop_exe if desktop_exe is not None else running_desktop_exe
    exe = probe()
    if exe:
        derived = _candidate_from_root(Path(exe).parent)
        if derived:
            return derived, f"由运行中的桌面程序位置推导（{exe}）"

    return None, ""


def build_plan(root: Path, *, port: int = DEFAULT_PORT, log_path: Path,
               env: Mapping[str, str] | None = None,
               remembered_argv: Sequence[str] | None = None,
               desktop_exe: Callable[[], str] | None = None) -> LaunchPlan:
    """The measured command: ``--serve --port <port> --session-id <id>``.

    No ``--model``: the operator's rule is explicit that the model is not to be hard-coded
    here, and a gateway that pins one would silently override every escalation's own
    choice.  No ``--auth none``, ever.
    """
    environment = env if env is not None else os.environ
    remembered = list(remembered_argv or ())
    remembered_cli = remembered[1] if len(remembered) > 1 else None
    cli, source = discover_cli(environment, remembered_cli, desktop_exe)
    if cli is None:
        raise GatewayStartRefused(
            "找不到 codebuddy CLI：依次尝试了 "
            f"{ENV_CLI_OVERRIDE} / {ENV_APP_PATH} / 上次成功的启动命令 / 运行中的桌面程序位置，"
            "都没有指向可执行文件（见 "
            "knowledge/failure_patterns/integration/WORKBUDDY_GATEWAY_CONTRACT.md §1）"
        )
    # The interpreter: this environment's Node wins, then the one the remembered plan used
    # (it is the same managed Node and it demonstrably works), then bare ``node``.
    node = str(environment.get(ENV_NODE) or "").strip()
    if not node and remembered and Path(str(remembered[0])).exists():
        node = str(remembered[0])
    node = node or "node"
    argv = (node, str(cli), "--serve", "--port", str(int(port)),
            "--session-id", SESSION_ID)
    return LaunchPlan(argv=argv, cwd=Path(root), log_path=Path(log_path),
                      cli=str(cli), cli_source=source,
                      # An *addition* to the launcher's environment, never a replacement, and
                      # deliberately unconditional: the variable selects a bundle that exists
                      # (``dist/codebuddy-headless.js``) instead of the one that does not
                      # (``dist/codebuddy.js``).  It is also the only thing that makes the job
                      # workers this gateway forks survive their own start-up -- see
                      # ``ENV_FORCE_HEADLESS_BUNDLE``.  The credential stays inherited.
                      env={ENV_FORCE_HEADLESS_BUNDLE: "1"})


# --------------------------------------------------------------------- the decision


#: Reasons that mean the gateway spoke and refused, as opposed to staying silent.
SILENT_REASONS = frozenset({"", "GATEWAY_UNREACHABLE", "NO_CREDENTIAL"})


def _answered(reason: str) -> bool:
    """Did the bridge get an HTTP answer?  ``False`` = nothing came back over the wire.

    Kept as one predicate because two questions depend on it: whether to *restart* (only
    silence justifies that) and how to describe the state (a refusal is a request problem,
    a silence is a process problem).  ``NO_CREDENTIAL`` counts as silence: the bridge refuses
    to send at all in that case, so no server ever spoke.
    """
    return str(reason or "").strip().upper() not in SILENT_REASONS


def _rejection(reason: str) -> bool:
    """Did the gateway answer with a *refusal* rather than not answering at all?

    The distinction is the whole reason these helpers exist: a refusal is a statement about
    the request, and the process is fine.  ``GATEWAY_UNREACHABLE`` is the bridge's word for
    "nothing came back", which is the only case a restart can help.
    """
    text = str(reason or "").strip().upper()
    return _answered(text) and (
        text in ("AUTH_REJECTED", "MISSING_REQUEST_MARKER")
        or text.startswith("HTTP_4") or text.startswith("HTTP_5")
        or text.startswith("UNHEALTHY")
    )


@dataclass(frozen=True)
class Measurement:
    """What was actually observed, as opposed to what the record claims."""

    port_pid: int = 0
    port_name: str = ""
    #: ``True`` / ``False`` / ``None`` -- the bridge's own answer, never inferred from a job.
    health: bool | None = None
    health_reason: str = ""
    #: Is the pid this service last launched still alive?
    own_pid_alive: bool = False
    #: ...and is that pid still *our gateway*?  A pid is not an identity: measured
    #: 2026-09-18, the recorded gateway pid 15140 was later alive as the sheetagent MCP
    #: server.  ``own_pid_alive`` alone would have reported "our gateway is running" about
    #: an unrelated program, and the gateway that was actually gone would never be
    #: restarted.  ``None`` means the question was not asked (the cheap branch).
    own_pid_is_gateway: bool | None = None
    #: Did the gateway answer HTTP at all?  ``False`` is "nothing came back" (dead or wedged,
    #: where a restart is the remedy); ``True`` with ``health`` false is "it answered and
    #: refused us" (401/403, where a restart is useless and destructive).  Measured
    #: 2026-09-18: a running gateway asked for a request header this project did not send,
    #: answered 403, read as unreachable, and was killed and restarted four times -- the
    #: process was never the problem.
    reachable: bool | None = None

    @property
    def port_taken(self) -> bool:
        return self.port_pid > 0

    @property
    def ours_running(self) -> bool:
        """Our gateway is alive: the pid exists *and* it is still running our command line."""
        if not self.own_pid_alive:
            return False
        return self.own_pid_is_gateway is not False


def decide(
    measurement: Measurement,
    record: Mapping[str, Any],
    *,
    now: float,
    operator_intent: str = "RUNNING",
    has_credential: bool = True,
) -> tuple[str, str, str]:
    """``(state, action, detail)`` for one observation.  Pure: no clock, no network, no spawn.

    Every branch is a sentence an operator could read off the window, and the ordering
    matters: "the operator said STOP" outranks everything, then "somebody else owns the
    port" (never kill), then "ours, in its grace window" (never double-start), and only then
    the question of whether to start anything at all.

    ``record["started_ever"]`` distinguishes the two reasons to start: the panel came up and
    found no gateway (the operator asked for exactly this -- GUI start = system start),
    versus a gateway that died while running.  Both start; the second one additionally has to
    satisfy the back-off ladder, so a crash loop cannot become a spawn loop.  It is read
    from the record rather than passed, because the first version took it as a parameter
    *and* read it from the record: a caller passing one value with a record holding the
    other got a decision that contradicted its own inputs, and the test that caught it was
    written from the record side.  One fact, one place.
    """
    failures = int(record.get("consecutive_failures") or 0)
    attempts = int(record.get("restart_attempts") or 0)
    launched_at = float(record.get("launched_at") or 0.0)
    next_attempt_at = float(record.get("next_attempt_at") or 0.0)
    own_pid = int(record.get("pid") or 0)
    started_ever = bool(record.get("started_ever"))

    if str(operator_intent).upper() == "STOPPED":
        # §二十五: a watchdog must not overrule a human.  Report, never start.
        if measurement.health is True:
            return HEALTHY, ACT_PASSIVE, "操作员已 STOP；网关仍在正常应答，保持现状（不重启）"
        return PASSIVE_STOPPED, ACT_PASSIVE, "操作员已 STOP；不启动网关（用户 STOP 优先于看门狗）"

    if not has_credential:
        # A gateway nobody can authenticate to would answer 401 forever; saying so is more
        # useful than a process that looks alive and refuses every request.
        return NO_CREDENTIAL, ACT_NO_CREDENTIAL, (
            f"环境变量 {ENV_PASSWORD} 未设置；拒绝启动网关"
            "（不把口令写进仓库，也不用 --auth none）"
        )

    # -- somebody is listening ------------------------------------------------------
    if measurement.port_taken:
        if measurement.health is True:
            return HEALTHY, ACT_REUSE, (
                f"复用已有网关（端口 {DEFAULT_PORT} 属于 pid {measurement.port_pid}"
                f" {measurement.port_name}，health 正常）"
            )
        ours = (own_pid and measurement.port_pid == own_pid
                and measurement.own_pid_is_gateway is not False)
        if ours:
            # Our own process holds the port but is not answering.  Inside the grace window
            # that is simply a slow bind.
            if launched_at and (now - launched_at) < STARTUP_GRACE_SECONDS:
                return STARTING, ACT_WAIT, f"网关正在启动（已 {(now - launched_at):.0f}s）"
            if measurement.reachable and _rejection(measurement.health_reason):
                # It answered, and it told us why it will not serve us.  Killing and
                # restarting a process that is working perfectly cannot change a request
                # header or a credential, so the ladder is deliberately not consulted.
                return REJECTING, ACT_WAIT, (
                    f"网关在运行并已应答，但拒绝本项目的请求（{measurement.health_reason}）"
                    "—— 重启不能解决，需要修正请求/凭据；已停止重启以免反复杀死健康进程"
                )
            # Past the grace window our own process is wedged: replace it.  This is the one
            # case where killing is allowed, because the process is provably ours.
            if now >= next_attempt_at:
                return RESTARTING, ACT_RESTART, (
                    f"本服务启动的网关（pid {own_pid}）持有端口但 health 无响应"
                    f"超过 {STARTUP_GRACE_SECONDS:.0f}s，判定卡死，重启它"
                )
            wait = max(0.0, next_attempt_at - now)
            return DEGRADED, ACT_WAIT, f"网关卡死，退避中（还剩 {wait:.0f}s）"
        # Not ours and not answering.  §三: do not force-kill an unknown process.
        return PORT_CONFLICT, ACT_PORT_CONFLICT, (
            f"端口 {DEFAULT_PORT} 被非本服务的进程占用（pid {measurement.port_pid}"
            f" {measurement.port_name}）且 health 无响应；不强杀，等待人工处置"
        )

    # -- nobody is listening --------------------------------------------------------
    if measurement.health is True:
        # Health answered but no listener was seen: the port query lost a race.  Trust the
        # stronger evidence rather than starting a second instance.
        return HEALTHY, ACT_REUSE, "health 正常（端口查询与应答竞争，按健康复用）"

    if measurement.ours_running:
        if launched_at and (now - launched_at) < STARTUP_GRACE_SECONDS:
            return STARTING, ACT_WAIT, (
                f"网关进程存在但尚未监听（pid {own_pid}，已 {(now - launched_at):.0f}s）"
            )
        if now >= next_attempt_at:
            return RESTARTING, ACT_RESTART, f"本服务的网关进程（pid {own_pid}）未监听且已过宽限期，重启"
        return DEGRADED, ACT_WAIT, f"网关未就绪，退避中（还剩 {max(0.0, next_attempt_at - now):.0f}s）"

    # A recorded pid that is alive but is *not* our gateway: the number was reused.  This
    # must not read as "our gateway is fine" -- see ``own_pid_is_gateway``.  Treated as
    # nothing running at all, which is what it is.
    reused = measurement.own_pid_alive and measurement.own_pid_is_gateway is False

    # Nothing at all.  The panel came up and found no gateway -- that is §二, and it starts
    # one immediately.  A gateway that died mid-run has to wait for the ladder.
    if not started_ever:
        return OFFLINE, ACT_START, "未发现网关；按 P0 §二 自动启动一个（GUI 启动 = 系统启动）"
    if reused:
        # Said out loud rather than silently: a pid that came back as somebody else is worth
        # a line in the record, because it is exactly the reading that would otherwise look
        # like "our gateway is alive".
        note = f"记录的 pid {own_pid} 已被其它进程复用（它已不是我们的网关），按未运行处理"
        if failures < DEGRADED_AFTER_FAILURES:
            return OFFLINE, ACT_WAIT, f"{note}；连续失败 {failures}/{DEGRADED_AFTER_FAILURES}，未达降级阈值"
        if now >= next_attempt_at:
            return OFFLINE, ACT_RESTART, f"{note}；连续失败 {failures} 次（≥ 阈值），第 {attempts + 1} 次自动重启"
        return DEGRADED, ACT_WAIT, f"{note}；退避中（还剩 {max(0.0, next_attempt_at - now):.0f}s）"
    if failures < DEGRADED_AFTER_FAILURES:
        return OFFLINE, ACT_WAIT, (
            f"未发现网关，连续失败 {failures}/{DEGRADED_AFTER_FAILURES}，"
            "未达降级阈值，不重启（一次超时不等于状态改变）"
        )
    if now >= next_attempt_at:
        attempt = attempts + 1
        return OFFLINE, ACT_RESTART, f"连续失败 {failures} 次（≥ 阈值）且无监听进程，第 {attempt} 次自动重启"
    return DEGRADED, ACT_WAIT, f"网关离线，退避中（还剩 {max(0.0, next_attempt_at - now):.0f}s）"


# --------------------------------------------------------------------- the service


class GatewayService:
    """Owns the gateway *process*.  Reads the bridge's health; never owns job state.

    All effects are injected (``spawn``, ``port_owner``, ``probe``, ``alive``), so the
    decision table above can be exercised without a port, a process or a network -- and so
    the production call sites are the only place that can actually start something.
    """

    def __init__(
        self,
        root: Path,
        *,
        port: int = DEFAULT_PORT,
        state_path: Path | None = None,
        log_path: Path | None = None,
        env: Mapping[str, str] | None = None,
        spawn: Callable[[LaunchPlan], int] | None = None,
        port_owner: Callable[[], tuple[int, str]] | None = None,
        probe: Callable[[], tuple[bool | None, str]] | None = None,
        alive: Callable[[int], bool] | None = None,
        kill: Callable[[int], bool] | None = None,
        runs: Callable[[int, str], bool] | None = None,
        desktop_exe: Callable[[], str] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.root = Path(root)
        self.port = int(port)
        # Sanitised here, at the one place the service's environment is decided: everything the
        # gateway launches -- including the job workers it forks with its own environment --
        # inherits this, so a leak here is a leak into every answering job.
        self.env = service_environment(env if env is not None else os.environ)
        self.state_path = Path(state_path) if state_path else (
            self.root / "learning/control_panel/gateway_service.json"
        )
        self.log_path = Path(log_path) if log_path else default_log_path()
        self._spawn = spawn or self._spawn_detached
        self._port_owner = port_owner or (lambda: winproc.port_owner(self.port))
        self._probe = probe or self._probe_bridge
        # ``pid_exists``, not ``alive``: the gateway is ``node.exe`` and the panel-body
        # check looks for an interpreter name.  Measured 2026-09-18 on the first live
        # launch -- node.exe holding 8080, health 200, and the check calling it dead.
        self._alive = alive or (lambda pid: winproc.pid_exists(pid))
        self._kill = kill or (lambda pid: winproc.kill_tree(pid))
        self._runs = runs or (lambda pid, needle: winproc.pid_runs(pid, needle))
        # Injectable so a test never depends on whether a real desktop is installed here.
        self._desktop_exe = desktop_exe if desktop_exe is not None else running_desktop_exe
        self._clock = clock or time.time

    # -- persistence -------------------------------------------------------

    def record(self) -> dict[str, Any]:
        """The lifecycle record.  Missing or unreadable is an empty record, never an error."""
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - an unreadable record is "nothing known"
            return {}
        return dict(payload) if isinstance(payload, Mapping) else {}

    def _write_record(self, record: Mapping[str, Any]) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(
                json.dumps(dict(record), ensure_ascii=False, indent=1), encoding="utf-8"
            )
        except Exception:  # noqa: BLE001 - an unwritable record must not stop the loop
            pass

    # -- measurement -------------------------------------------------------

    def _probe_bridge(self) -> tuple[bool | None, str]:
        """Ask the bridge.  A down gateway is an answer (``False``), not an exception."""
        try:
            from .workbuddy_bridge import WorkBuddyBridge

            probe = WorkBuddyBridge(cwd=self.root).is_available()
            return bool(probe), str(getattr(probe, "reason", "") or "")
        except Exception as exc:  # noqa: BLE001
            return None, f"{type(exc).__name__}: {exc}"

    def measure(self, record: Mapping[str, Any] | None = None,
                observed: tuple[bool | None, str] | None = None) -> Measurement:
        """Observe the world.  ``observed`` lets a caller that has *already* asked the
        bridge hand the answer over rather than paying for the same HTTP round trip twice:
        the panel's probe thread measures health for the window on every cycle, and a
        second probe inside the same cycle would double the requests and could disagree
        with the number on screen.
        """
        current = dict(record if record is not None else self.record())
        try:
            pid, name = self._port_owner()
        except Exception as exc:  # noqa: BLE001
            pid, name = 0, f"port query failed: {type(exc).__name__}"
        if observed is None:
            health, reason = self._probe()
        else:
            health, reason = observed
        # "It answered" is a separate fact from "it said yes".  ``GATEWAY_UNREACHABLE`` and
        # ``NO_CREDENTIAL`` mean nothing came back over the wire (the second one because the
        # bridge refused to send anything); every other reason is a server talking.
        reachable = None if health is None else (
            True if health is True else _answered(reason)
        )
        own = int(current.get("pid") or 0)
        own_alive = False
        identity: bool | None = None
        if own:
            try:
                own_alive = bool(self._alive(own))
            except Exception:  # noqa: BLE001
                own_alive = False
            if own_alive:
                # Ask the identity question -- but only here, where it can change the
                # answer, and only when there is something to match against.  A record with
                # no remembered launch (never started by us, or an older format) has no
                # needle, and an unverifiable identity is *not* the same as a negative one:
                # ``own_pid_is_gateway`` stays ``None`` and the conservative reading is
                # "assume it is ours, do not start a second one".
                expected = self._expected_cli(current)
                if expected:
                    try:
                        identity = bool(self._runs(own, expected))
                    except Exception:  # noqa: BLE001
                        identity = None
        return Measurement(port_pid=int(pid or 0), port_name=str(name or ""),
                           health=health, health_reason=reason, own_pid_alive=own_alive,
                           own_pid_is_gateway=identity, reachable=reachable)

    def _expected_cli(self, record: Mapping[str, Any]) -> str:
        """The CLI path the recorded launch used -- the needle that proves identity."""
        argv = (record.get("launch") or {}).get("argv") or []
        return str(argv[1]) if len(argv) > 1 else ""

    def has_credential(self) -> bool:
        return bool(str(self.env.get(ENV_PASSWORD) or "").strip())

    # -- effects -----------------------------------------------------------

    def _spawn_detached(self, plan: LaunchPlan) -> int:
        """Start the gateway as an independent, hidden service.

        Detached on purpose (§二十四 option B, the smaller change): the gateway outlives the
        window, so closing and reopening the GUI finds a healthy instance and reuses it
        instead of racing to create a second one.  ``winproc`` owns the console-hiding, and
        the credential is inherited rather than passed, so it never reaches a command line.
        """
        child = winproc.spawn_detached(
            plan.argv, log_path=plan.log_path, cwd=plan.cwd,
            env={**self.env, **dict(plan.env)},
        )
        return int(child.pid or 0)

    def start(self, *, record: Mapping[str, Any], now: float) -> dict[str, Any]:
        """One spawn attempt.  Returns the record to persist; raises only on a real refusal.

        The remembered command line is offered to :func:`build_plan`, which is what makes a
        launcher without the desktop's environment able to start a gateway anyway: the
        previous successful launch is evidence, and evidence outranks a missing variable.
        """
        remembered = (record.get("launch") or {}).get("argv") or None
        plan = build_plan(self.root, port=self.port, log_path=self.log_path, env=self.env,
                          remembered_argv=remembered, desktop_exe=self._desktop_exe)
        pid = int(self._spawn(plan) or 0)
        attempts = int(record.get("restart_attempts") or 0) + 1
        rung = min(attempts, len(RESTART_BACKOFF)) - 1
        updated = dict(record)
        updated.update({
            "pid": pid,
            "launched_at": now,
            "restart_attempts": attempts,
            "next_attempt_at": now + RESTART_BACKOFF[max(rung, 0)],
            "started_ever": True,
            "launch": plan.as_record(),
            "last_launch_reason": str(record.get("detail") or ""),
        })
        return updated

    # -- one pass ----------------------------------------------------------

    def ensure(self, *, operator_intent: str = "RUNNING",
               observed: tuple[bool | None, str] | None = None) -> dict[str, Any]:
        """Measure, decide, act if allowed, persist.  Returns the record that was written.

        Called on the panel's probe thread only.  It performs at most one spawn per call and
        never blocks on the HTTP probe beyond the bridge's own timeout, so a dead gateway
        cannot stall gameplay (§二十一).  ``observed`` is the health answer the caller
        already has, if it has one.
        """
        record = self.record()
        now = self._clock()
        measurement = self.measure(record, observed)

        # The ladder advances *before* the decision, so the state, the action and the
        # sentence explaining them all describe the same pass.  Measured in the first live
        # acceptance run: incrementing afterwards made the record say ``failures: 1`` while
        # its own detail read "连续失败 0/3" -- a window that contradicts the file an audit
        # reads is exactly the class of defect this工单 is about.
        if measurement.health is True:
            record["consecutive_failures"] = 0
        elif measurement.health is False:
            record["consecutive_failures"] = int(record.get("consecutive_failures") or 0) + 1
        failures = int(record.get("consecutive_failures") or 0)

        state, action, detail = decide(
            measurement, record, now=now, operator_intent=operator_intent,
            has_credential=self.has_credential(),
        )

        if measurement.health is True and action == ACT_REUSE:
            # A healthy instance is adopted: forget the ladder, keep the pid we can verify.
            record["restart_attempts"] = 0
            record["next_attempt_at"] = 0.0
            if measurement.port_pid:
                record["pid"] = measurement.port_pid
                record["started_ever"] = True

        spawned = False
        if action in (ACT_START, ACT_RESTART):
            if action == ACT_RESTART and int(record.get("pid") or 0):
                # Only ever our own pid, and only when the decision table proved it wedged
                # or gone.  An unknown port owner never reaches this branch: that case
                # returns ACT_PORT_CONFLICT, which is not in the tuple above.
                wedged = int(record.get("pid") or 0)
                if wedged and measurement.port_pid == wedged:
                    try:
                        self._kill(wedged)
                    except Exception:  # noqa: BLE001 - a failed kill is reported, not fatal
                        pass
            try:
                record = self.start(record=record, now=now)
                spawned = True
                state = STARTING
                detail = f"已启动网关（pid {record.get('pid')}），等待 health（{detail}）"
            except GatewayStartRefused as exc:
                state = NO_CREDENTIAL if not self.has_credential() else OFFLINE
                detail = f"启动被拒绝：{exc}"
            except Exception as exc:  # noqa: BLE001 - a failed spawn must not kill the thread
                state = OFFLINE
                detail = f"启动失败：{type(exc).__name__}: {exc}"

        record.update({
            "state": state,
            "action": action,
            "detail": detail,
            "consecutive_failures": failures,
            "health": measurement.health,
            "health_reason": measurement.health_reason,
            "port_pid": measurement.port_pid,
            "port_name": measurement.port_name,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "checked_epoch": now,
            "spawned": spawned,
            "credential": "present" if self.has_credential() else "missing",
            "port": self.port,
        })
        self._write_record(record)
        return record


__all__ = [
    "GatewayService", "Measurement", "LaunchPlan", "GatewayStartRefused",
    "decide", "build_plan", "cli_path", "node_path", "discover_cli",
    "running_desktop_exe", "default_log_path",
    "ENV_CLI_OVERRIDE", "ENV_LOG_DIR",
    "STARTING", "HEALTHY", "DEGRADED", "OFFLINE", "RESTARTING", "PORT_CONFLICT",
    "UNREACHABLE", "REJECTING", "NO_CREDENTIAL", "PASSIVE_STOPPED", "UNKNOWN", "STATES",
    "ACT_PASSIVE", "ACT_REUSE", "ACT_WAIT", "ACT_START", "ACT_RESTART",
    "ACT_PORT_CONFLICT", "ACT_NO_CREDENTIAL",
    "DEGRADED_AFTER_FAILURES", "STARTUP_GRACE_SECONDS", "RESTART_BACKOFF",
]
