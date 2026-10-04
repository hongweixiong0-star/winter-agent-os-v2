"""Own the runtime's one local model *process*, the way ``GatewayService`` owns the gateway's.

Why this module exists
----------------------
The operator's 2026-09-30 directive made UI-Venus-2-9B a **runtime component**: its own cell
in the top bar (``本地模型``), its own config section (``config/v2.json``'s ``local_planner``),
its own ledger.  ``tools/launch_gui_model_server.py`` states the lifecycle requirement in its
docstring -- the model "must be **resident**" and "the normal state is that this process is
already up when the runtime asks" -- and provides ``start`` / ``stop`` / ``--status``.

What no component provided was an *owner*.  ``start`` was reachable only by running the tool
by hand or from a profiling script, so the model was up exactly when somebody had started it.

Measured 2026-10-04.  ``E:/winter_models/llama.cpp/server.log`` stopped being written at
``2026-10-03 10:21``; nothing listened on ``127.0.0.1:18080`` for the next 24 hours, and every
AUTO round in that window printed::

    [planner] UI-Venus-2-9B at http://127.0.0.1:18080
              -> LOCAL_GUI_MODEL_UNAVAILABLE 127.0.0.1:18080 (TimeoutError)

The panel was not blind to it.  ``PanelProbes._poll_local_model`` asks that endpoint's
``/health`` every fifteen seconds and graded the cell 等待 for a day.  The panel could *report*
the outage and could not *end* it, which is the whole of the gap this module closes.  A
component the operator has to start by hand is a component that is down whenever they have
not -- and the failure is silent, because a missing planner degrades a round rather than
stopping it.

Four decisions, and the reason for each
---------------------------------------
**Fire and forget, and never wait.**  ``launch_gui_model_server.start`` blocks for up to 180
seconds waiting for ``/health``, because a human running it wants the verdict.  A probe thread
must not: it also drives the gateway and device probes, and a three-minute stall there is the
window freezing -- the exact defect class this project spent 2026-10-04 removing from the
panel.  So the spawn is detached and *the next probe pass is the confirmation*: the caller
already re-asks ``/health`` every fifteen seconds, so the start needs no waiter at all.

**A startup grace, so the model is not judged before it can load.**  5.9 GB of weights plus a
multimodal projector do not answer on the next frame.  Without a grace the ladder would read
our own startup as a failure and spawn a *second* server, which is the one way this service
could make the machine worse instead of better.  ``STARTUP_GRACE_SECONDS`` is the window
during which no second attempt may be made.

**Never touch a healthy model.**  ``ensure`` returns ``ACT_REUSE`` the moment ``/health``
answers.  This is not an optimisation, it is the requirement: the model is resident precisely
so that a repin or a panel restart costs no reload, and a supervisor that reloaded 5.5 GB of
VRAM on every restart would be worse than no supervisor.

**A bounded ladder.**  A machine with no VRAM headroom must not spawn a 5.9 GB model every
fifteen seconds.  ``START_BACKOFF`` climbs and stays bounded, so a model that comes back is
noticed without the panel ever giving up.

Everything with an effect is injected (``probe``, ``spawn``, ``port_owner``, ``clock``), so the
decision table is exercised in tests without a port, a process or a GPU -- and so the
production call site is the only place that can actually start a server.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from . import winproc

# -- states ------------------------------------------------------------------------------
#: The model answered its own ``/health``.
HEALTHY = "HEALTHY"
#: A launch is in flight and inside :data:`STARTUP_GRACE_SECONDS`.
STARTING = "STARTING"
#: Asked and it said no, and the ladder is not yet due to try again.
BACKOFF = "BACKOFF"
#: ``local_planner.enabled`` is false, or no endpoint is configured.
DISABLED = "DISABLED"
#: The endpoint could not be reached *and* nothing could be attempted yet.
UNKNOWN = "UNKNOWN"

STATES: tuple[str, ...] = (HEALTHY, STARTING, BACKOFF, DISABLED, UNKNOWN)

# -- actions -----------------------------------------------------------------------------
#: Healthy: adopt it, touch nothing.
ACT_REUSE = "REUSE"
#: Down and the ladder is due: start the launcher.
ACT_START = "START"
#: Down but a launch is in flight, or the ladder is waiting.
ACT_WAIT = "WAIT"
#: Nothing to do: the planner is switched off in the config.
ACT_PASSIVE = "PASSIVE"

#: Back-off after consecutive unsuccessful attempts.  Bounded at ten minutes: long enough that
#: a machine out of VRAM is not hammered, short enough that a model put back is noticed in the
#: same working session.
START_BACKOFF: tuple[float, ...] = (60.0, 120.0, 300.0, 600.0)

#: How long a launch may take before it is even *eligible* to be called a failure.  Measured
#: 2026-10-01: ``llama-server`` reported ``model loaded`` and bound the port within a handful of
#: seconds of launch, but the first request afterwards still had to page the weights and took
#: seconds more.  Two minutes covers a cold load with MuMu and MAA sharing the GPU.
STARTUP_GRACE_SECONDS = 120.0

#: ``/health`` is answered from the model's own state, so a short timeout is right -- and a
#: blocking probe on this thread is a window that stops updating.
HEALTH_TIMEOUT_SECONDS = 3.0

#: The launcher, relative to the project root.  Spawned as a script so the *measured* profile
#: (``-ngl 30``, f16 KV, 32K, the image-token floor) lives in exactly one place; a second copy
#: of those numbers here is the drift this project's module docstrings argue against.
LAUNCHER_RELATIVE = "tools/launch_gui_model_server.py"


@dataclass(frozen=True)
class PlannerPlan:
    """What ``config/v2.json`` says about the local planner, or that it says nothing."""

    enabled: bool
    endpoint: str
    model: str
    port: int

    @property
    def actionable(self) -> bool:
        return bool(self.enabled and self.endpoint and self.port > 0)


def plan_from_config(root: Path | None = None, config_path: Path | None = None) -> PlannerPlan:
    """Read the planner section.  Unreadable or absent reads as *disabled*, never as a guess.

    The panel reads the same section through ``control_panel.local_gui_model_config`` so that
    turning the model off in the file changes both the cell and this service with no code edit.
    """
    path = Path(config_path) if config_path else (
        (Path(root) if root else Path(__file__).resolve().parents[1]) / "config/v2.json"
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return PlannerPlan(False, "", "", 0)
    if not isinstance(payload, Mapping):
        return PlannerPlan(False, "", "", 0)
    section = payload.get("local_planner")
    if not isinstance(section, Mapping):
        return PlannerPlan(False, "", "", 0)
    endpoint = str(section.get("endpoint") or "").strip().rstrip("/")
    port = 0
    if endpoint:
        tail = endpoint.rsplit(":", 1)[-1]
        if tail.isdigit():
            port = int(tail)
    return PlannerPlan(
        enabled=bool(section.get("enabled", False)),
        endpoint=endpoint,
        model=str(section.get("model") or ""),
        port=port,
    )


class GuiModelService:
    """Owns the local model *process*.  Measures ``/health``; never owns the model's answers.

    One pass -- :meth:`ensure` -- performs at most one spawn and never blocks beyond
    :data:`HEALTH_TIMEOUT_SECONDS`, so it is safe on the panel's probe thread.
    """

    def __init__(
        self,
        root: Path,
        *,
        state_path: Path | None = None,
        log_path: Path | None = None,
        launcher: Path | None = None,
        python: str | None = None,
        probe: Callable[[], tuple[bool | None, str]] | None = None,
        spawn: Callable[[list[str], Path], int] | None = None,
        port_owner: Callable[[], tuple[int, str]] | None = None,
        clock: Callable[[], float] | None = None,
        config_path: Path | None = None,
    ) -> None:
        self.root = Path(root)
        self.state_path = Path(state_path) if state_path else (
            self.root / "learning/control_panel/gui_model_service.json"
        )
        self.log_path = Path(log_path) if log_path else (
            self.root / "learning/control_panel/gui_model_launcher.log"
        )
        self.launcher = Path(launcher) if launcher else (self.root / LAUNCHER_RELATIVE)
        # ``sys.executable`` and not a literal: the panel is launched by the production
        # interpreter, so its own interpreter is the one that is already known to have the
        # project's dependencies.  A test passes a stand-in and never runs anything.
        self.python = str(python if python is not None else sys.executable)
        self.config_path = Path(config_path) if config_path else None
        self._probe = probe or self._probe_health
        self._spawn = spawn or self._spawn_launcher
        self._port_owner = port_owner or (lambda port: winproc.port_owner(port))
        self._clock = clock or time.time

    # -- configuration -----------------------------------------------------

    def plan(self) -> PlannerPlan:
        return plan_from_config(self.root, self.config_path)

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

    def _probe_health(self) -> tuple[bool | None, str]:
        """Ask the service's own ``/health``.  Stop by the caller, so no port is opened here.

        ``None`` and ``False`` are different answers and stay different: ``None`` is "there was
        no question to ask" (no endpoint configured), ``False`` is "asked, and it said no".
        Flattening them is what once made a panel report 异常 about a gateway that answered.
        """
        plan = self.plan()
        if not plan.endpoint:
            return None, "no endpoint configured"
        url = f"{plan.endpoint}/health"
        try:
            with urllib.request.urlopen(url, timeout=HEALTH_TIMEOUT_SECONDS) as answer:
                body = json.loads(answer.read().decode("utf-8", "replace") or "{}")
                status = str(body.get("status") or "") if isinstance(body, Mapping) else ""
                if int(getattr(answer, "status", 0)) == 200 and status == "ok":
                    return True, ""
                return False, f"health said {status or getattr(answer, 'status', '?')}"
        except Exception as exc:  # noqa: BLE001 - a poll never reaches the UI as an exception
            return False, type(exc).__name__

    def _spawn_launcher(self, argv: list[str], log_path: Path) -> int:
        """Start the launcher detached and hidden.  Returns its pid; never raises on success.

        ``winproc.spawn_detached`` and not ``subprocess`` here: this module is not the one place
        allowed to decide about consoles, and ``tools/check_wiring.py`` fails the build for a
        raw call.  ``DETACHED_PROCESS`` also matters for a service -- a child inside the
        launcher's process tree dies with it, which is how a panel once "restarted" and then
        simply was not there.
        """
        process: subprocess.Popen = winproc.spawn_detached(argv, log_path=log_path)
        return int(getattr(process, "pid", 0) or 0)

    # -- one pass ----------------------------------------------------------

    def ensure(self, *, observed: tuple[bool | None, str] | None = None) -> dict[str, Any]:
        """Measure, decide, act if allowed, persist.  Returns the record that was written.

        ``observed`` is the health answer the caller already has, so the panel's own fifteen
        second poll is not repeated one line later.
        """
        record = self.record()
        now = self._clock()
        plan = self.plan()

        health: bool | None
        reason: str
        if observed is not None:
            health, reason = observed
        else:
            try:
                health, reason = self._probe()
            except Exception as exc:  # noqa: BLE001 - a poll never reaches a probe thread as one
                health, reason = False, f"{type(exc).__name__}: {exc}"

        failures = int(record.get("consecutive_failures") or 0)
        next_attempt_at = float(record.get("next_attempt_at") or 0.0)
        spawned = False
        port_pid = int(record.get("port_pid") or 0)
        #: ``now < launch_in_flight_until`` is the whole of "a launch is in flight".  A field
        #: rather than an inference from ``spawned``: the two answer different questions --
        #: ``spawned`` is what happened last pass, this is whether it may still be loading --
        #: and inferring one from the other is how the record ends up contradicting itself.
        launch_in_flight_until = float(record.get("launch_in_flight_until") or 0.0)

        if not plan.actionable:
            state, action = DISABLED, ACT_PASSIVE
            detail = (
                "本地规划模型未启用（config/v2.json 的 local_planner.enabled 为 false），"
                "不启动"
            )
            failures = 0
            next_attempt_at = 0.0
            launch_in_flight_until = 0.0
        elif health is True:
            # Adopted.  Forget the ladder; record the pid we can actually verify.
            state, action = HEALTHY, ACT_REUSE
            detail = f"本地规划模型在线（{plan.model or 'model'} @ {plan.endpoint}），保持常驻"
            failures = 0
            next_attempt_at = 0.0
            launch_in_flight_until = 0.0
            if plan.port:
                try:
                    pid, _name = self._port_owner(plan.port)
                    port_pid = int(pid or 0) or port_pid
                except Exception:  # noqa: BLE001 - an unreadable owner is not a fault
                    pass
        elif now < next_attempt_at:
            # A launch is in flight, or the ladder is waiting.  Either way: do not spawn.
            waiting = max(0.0, next_attempt_at - now)
            state = STARTING if now < launch_in_flight_until else BACKOFF
            action = ACT_WAIT
            detail = (
                f"本地规划模型未就绪（{reason or 'unreachable'}），{int(waiting)} 秒后再试"
            )
        else:
            failures += 1
            state, action = STARTING, ACT_START
            try:
                spawn_argv = [self.python, str(self.launcher)]
                pid = self._spawn(spawn_argv, self.log_path)
                spawned = True
                launch_in_flight_until = now + STARTUP_GRACE_SECONDS
                detail = (
                    f"已启动本地规划模型（launcher pid {pid}），{int(STARTUP_GRACE_SECONDS)} "
                    f"秒内不判失败；下一轮探测即确认"
                )
            except Exception as exc:  # noqa: BLE001 - a failed spawn must not kill the thread
                state = BACKOFF
                launch_in_flight_until = 0.0
                detail = f"启动本地规划模型失败：{type(exc).__name__}: {exc}"
            # The grace is set whether or not the spawn raised: a spawn that raised still
            # consumed a rung, and retrying it on the next fifteen-second pass is the storm
            # this ladder exists to prevent.
            rung = min(failures, len(START_BACKOFF)) - 1
            next_attempt_at = now + max(
                STARTUP_GRACE_SECONDS, START_BACKOFF[max(rung, 0)]
            )

        record.update({
            "state": state,
            "action": action,
            "detail": detail,
            "consecutive_failures": failures,
            "health": health,
            "health_reason": reason,
            "endpoint": plan.endpoint,
            "model": plan.model,
            "port": plan.port,
            "port_pid": port_pid,
            "launcher": str(self.launcher),
            "spawned": spawned,
            "next_attempt_at": next_attempt_at,
            "launch_in_flight_until": launch_in_flight_until,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "checked_epoch": now,
        })
        self._write_record(record)
        return record


__all__ = [
    "GuiModelService", "PlannerPlan", "plan_from_config",
    "HEALTHY", "STARTING", "BACKOFF", "DISABLED", "UNKNOWN", "STATES",
    "ACT_REUSE", "ACT_START", "ACT_WAIT", "ACT_PASSIVE",
    "START_BACKOFF", "STARTUP_GRACE_SECONDS", "HEALTH_TIMEOUT_SECONDS",
    "LAUNCHER_RELATIVE",
]
