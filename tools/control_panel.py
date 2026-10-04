from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
import ctypes
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tkinter import ttk
from typing import Any, Callable, Mapping, NamedTuple

from PIL import Image, ImageDraw, ImageTk

ROOT = Path(__file__).resolve().parents[1]
# Freeze a content identity for the control plane itself.  The shared runtime revision
# intentionally excludes this GUI module, so the queue heartbeat records this hash
# alongside the frozen runtime token instead of implying that one identifies both.
try:
    CONTROL_PLANE_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
except OSError:
    CONTROL_PLANE_SOURCE_SHA256 = ""

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ``tools/`` is the directory this file lives in.  ``runpy.run_path`` -- which is how
# the pinned launcher runs the panel -- does not put it on sys.path the way
# ``python tools/control_panel.py`` would, so the sibling module below has to be made
# importable explicitly.
TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import panel_window  # noqa: E402

from winter_agent_v2 import runtime_env
from winter_agent_v2 import winproc
from winter_agent_v2 import event_schedule
from winter_agent_v2 import learning_funnel
from winter_agent_v2 import offline_learning
from winter_agent_v2.device import ADBDevice
from winter_agent_v2.escalation_queue import (
    AUTO_ESCALATION_CONDITIONS,
    DEFAULT_LEDGER,
    EscalationLedger,
    # §7: the one answer to "which trace is current", shared by the development page and the
    # closed-loop card so the two cannot name different capabilities side by side.
    current_development_trace,
    # Needed by the closed-loop card, which reads the record's own lifecycle state so §十一's
    # "Version must read the real ledger" is satisfied.  Its absence was invisible for a
    # while: the call sat inside a broad ``except`` that turned a NameError into an empty
    # version cell rather than into a failure.
    fold,
)
from winter_agent_v2.models import MarchState, Page, SkillState, WorldState
from winter_agent_v2.role_session import role_switch_quality_metrics
# The job-lost answer, so "this job is gone" can be told apart from "the gateway is down"
# without catching a bare Exception and guessing.  Measured 2026-09-18: conflating them made a
# healthy gateway look dead and restarted it 51 times.
from winter_agent_v2.workbuddy_bridge import JobLost
from winter_agent_v2.retention import prune_runtime_screenshots
from winter_agent_v2.runtime_reload import (
    REQUEST_KIND,
    ReloadSignal,
    default_path as reload_path,
    newest_write,
)
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.runtime_snapshot import (
    UNCLASSIFIED_EVENT,
    AgentState,
    RuntimeSnapshotStore,
    StopCategory,
    append_uptime_ledger,
    counts_as_unexpected_worker_exit,
    is_fatal_stop,
    state_for_stop_reason,
    uptime_ledger_row,
)
from winter_agent_v2.worker_recovery import RecoveryOutcome, retry_until_ready

CONFIG_PATH = ROOT / "config/v2.json"
PANEL_STATE_PATH = ROOT / "config/control_panel_state.json"
#: The operator's policy file.  Read at startup and merged on save; see
#: ``load_policy_categories`` / ``write_policy_state`` for why both halves matter.
POLICY_STATE_PATH = ROOT / "config/policy_state.json"
RUNTIME_PATH = ROOT / "tools/run_live.py"
#: The AUTO uptime ledger (ACCEPTANCE §22).  One row per finished round, written at the single
#: point where the panel has already decided whether another round follows, so "how long has
#: AUTO been self-continuing" is a number instead of a narrative.  Classified RUNTIME_MUTABLE by
#: ``tools/build_runtime_state_manifest.py`` (``learning/**/*.jsonl``), so it is never tracked.
AUTO_UPTIME_LEDGER_PATH = ROOT / "learning/auto_uptime.jsonl"
#: The mode a calibration cycle reports, so an examination can never be mistaken for
#: production play when its episode is read back (operator's §8 rule).  Kept next to
#: ``RUNTIME_PATH`` because it is part of the same command-line contract.
VALIDATION_MODE = "DEVELOPMENT_VALIDATION"


def validation_command(record: Mapping[str, Any], *, capture_dir: str, serial: str,
                      lease_id: str = "") -> list[str]:
    """The unified executor's command line for one Development Validation cycle.

    Built here, as a pure function, for two reasons: the five validation fields have to be
    impossible to omit -- an examination whose episode cannot be attributed is worse than no
    examination -- and the one way to be sure they are always present is to have a single place
    that writes them, with a test that asserts it.

    Same executor as AUTO.  There is deliberately no second runner: the operator's rule is that
    a calibration goes through ``run_live`` -> V2 -> Executor -> MAA/ADB -> Verifier -> Episode
    exactly like any other cycle, differing only in what it is told it is doing.

    ``--no-escalate`` is passed because failing this examination must not open a second
    WorkBuddy job: the queue and the reconciler own that decision, and a test process that
    filed an escalation for failing its own exam would be a loop.

    The goal is translated through ``GOAL_ROUTES`` before it reaches the command line: the
    ledger stores a goal **id** and ``run_live --goal`` accepts only a route **domain**.
    Measured 2026-09-21, passing the id straight through made every calibration die in
    argparse before the device was touched --

        invalid choice: 'KEEP_TRAINING_PRODUCTIVE'

    -- while still taking the device lease, and the panel reported it as "EXIT_2, reason
    unknown".  A goal with no route raises instead of being passed through, because a
    calibration aimed at a route that does not exist would prove nothing about the goal.
    """
    from winter_agent_v2.goal_library import route_for

    goal_id = str(record.get("goal") or "")
    route = route_for(goal_id)
    if goal_id and not route:
        raise ValueError(
            f"no route for goal {goal_id!r}: a calibration must aim at a route run_live accepts"
        )
    return [
        runtime_python_path(), str(RUNTIME_PATH),
        "--execution-mode", VALIDATION_MODE,
        # The trace.  Present even when empty, so the absence is visible in the command
        # rather than implied by a missing flag.
        "--trace-id", str(record.get("key") or ""),
        "--job-id", str(record.get("job_id") or ""),
        "--capability", str(record.get("capability") or ""),
        "--lease-id", str(lease_id or ""),
        # What this cycle must be running for its evidence to be creditable.  run_live refuses
        # before the first device action when it does not match (operator §3).
        "--expected-after-version", str(record.get("after_version") or ""),
        "--goal", route or "",
        "--max-actions", str(VALIDATION_MAX_ACTIONS),
        "--capture-dir", str(capture_dir),
        "--serial", serial,
        "--no-escalate",
    ]
# A calibration is an examination, not a gaming session: bounded so the device goes back
# to normal play quickly (the operator's §6: 真机负责校准，而不是从零学整个游戏).
VALIDATION_MAX_ACTIONS = 12

# Raised when the panel is asked to start work on an interpreter that cannot run
# the production loop.  It is classified as an environment failure (see
# ENVIRONMENT_FAILURES) so refusing to start is never counted as a worker crash.
RUNTIME_ENV_STOP_REASON = "RUNTIME_ENV_NOT_PRODUCTION_READY"

# How long to wait before re-checking a deferred start.  Each cycle is a fresh
# subprocess, so "reload" here means "do not import a half-written tree" -- there
# is no in-process hot swap to perform (see winter_agent_v2/runtime_reload.py).
RELOAD_RETRY_MS = 5000

_ESCALATION_LEDGER_PATH = ROOT / DEFAULT_LEDGER


def reload_deferral() -> tuple[ReloadSignal, object]:
    """Should this start be postponed because a development agent just wrote code?

    Returns the signal so the caller can clear it once the wait is over.  Reads the
    escalation ledger for in-flight jobs only to *report* them: an active job must
    not hold AUTO off (the operator's §七/§十三), and the wait is the short settle
    window measured from the newest write to the tree.  A fresh write is a real
    hazard for a fresh import; a job that is merely still running is not.
    """
    signal = ReloadSignal(reload_path(ROOT))
    try:
        active = len(EscalationLedger(_ESCALATION_LEDGER_PATH).snapshot().active_jobs())
    except Exception:  # noqa: BLE001 - an unreadable ledger must not block a start
        active = 0
    return signal, signal.evaluate(
        active_jobs=active,
        # Freshness comes from the tree, not the marker: the wait is for a write
        # that just happened, and an active job is reported rather than waited for.
        newest_write_at=newest_write(ROOT),
    )


_INTERPRETER_LOCK = threading.Lock()
_INTERPRETER_REPORT: runtime_env.InterpreterReport | None = None


def runtime_interpreter_report() -> runtime_env.InterpreterReport:
    """The interpreter the worker will be spawned with, probed exactly once.

    ``PYTHON_PATH`` used to be derived from the panel's own ``sys.executable``,
    which made the worker inherit whichever interpreter launched the panel.  The
    panel running on 2026-09-17 had been launched with a generic runtime python
    without ``maa`` or ``cv2``, and the worker said so in its piped stdout
    ("MAA_IMPORT_FAILED:ModuleNotFoundError ... observations stay on ADB").  No
    *executed* step in those runs belonged to a skill promoted to MAA, so nothing
    was measured through the slow path yet -- but the next AUTO run would have
    taken ADB capture at 324 ms where MAA EmulatorExtras costs 8.92 ms, and the
    run would still have looked healthy.  The interpreter is now resolved and
    *proved* before it is used.
    """
    global _INTERPRETER_REPORT
    if _INTERPRETER_REPORT is None:
        with _INTERPRETER_LOCK:
            if _INTERPRETER_REPORT is None:
                _INTERPRETER_REPORT = runtime_env.resolve_for_project(ROOT)
    return _INTERPRETER_REPORT


def runtime_python_path() -> str:
    """The production interpreter as an executable path, for spawning the worker."""
    return str(runtime_interpreter_report().python_exe)


def runtime_env_blocker() -> str | None:
    """``None`` when production can run here, otherwise why it cannot."""
    report = runtime_interpreter_report()
    return None if report.ok else report.reason
CAPTURE_ROOT = ROOT / "dataset/raw/control_panel"
LOG_ROOT = ROOT / "learning/control_panel"
CRASH_ROOT = LOG_ROOT / "crashes"
# The window's own narration, on disk.  It carries the startup preflight verdict,
# which is what decides whether AUTO starts -- a decision that has to be auditable
# from outside the process.
PANEL_LOG_PATH = LOG_ROOT / "panel.log"
# The queue pump's last tick.  Written every pass and read by anyone who wants to
# know whether the consumer is actually running -- a thread inside a GUI cannot be
# checked from outside any other way, and "it is started on line N" is not evidence.
PUMP_STATE_PATH = LOG_ROOT / "pump.json"


def gateway_probe_path() -> Path:
    """Where the gateway probe records its last result.

    Derived from ``PANEL_LOG_PATH`` at *call* time, exactly like ``panel_pid_path``, and
    for the same reason: every window-building test redirects ``PANEL_LOG_PATH``, and a
    module-level constant would keep pointing at production.  Measured 2026-09-18: the
    first version was a constant, and running the suite wrote
    ``learning/control_panel/gateway.json`` from a test window -- so the next audit read
    "gateway 正常" out of a file a test had just produced.  A value that a test wrote is
    not a measurement of anything.
    """
    return Path(PANEL_LOG_PATH).parent / "gateway.json"


def gateway_service_state_path() -> Path:
    """Where the gateway *lifecycle* record lives (pid, ladder, launch).

    Separate from ``gateway.json``, and separated on purpose: that file answers "is the
    gateway answering", which is what the truth audit grades; this one answers "is there a
    process, and what has been done about it".  Mixing a pid and a restart counter into the
    health probe would make ``gateway_health`` claim more than a health check measured.

    Derived from ``PANEL_LOG_PATH`` at call time, for the reason recorded on
    ``gateway_probe_path``: a module-level constant kept pointing at production while every
    test redirected the log path.
    """
    return Path(PANEL_LOG_PATH).parent / "gateway_service.json"


def gateway_service_log_path() -> Path:
    """Where the gateway's stdout/stderr go.

    **Not** derived from the panel's log directory, unlike every other path here.  The
    gateway's banner contains its effective password, so a file beside ``panel.log`` would
    put a live credential one ``git add`` away from the repository.  ``state_path`` has no
    such constraint; this one does.  See ``gateway_service.default_log_path``.
    """
    from winter_agent_v2.gateway_service import default_log_path

    return default_log_path()


def observes_only(panel: Any) -> bool:
    """Is another window ticking the clock, making this one read-only?

    A module-level predicate rather than a method, because a gate must be answerable
    for *any* object: the first version read ``self._other_instance`` and then a
    property of the same name, and both crashed on an existing test's minimal stub
    (``SimpleNamespace(operator_intent="STOPPED")``).  A gate that raises on an
    unexpected object is worse than one that answers "assume I am the owner" -- being
    the owner is what this window would do anyway, and the answers are cheap.
    """
    return bool(getattr(panel, "_other_instance", 0))


def panel_pid_path() -> Path:
    """Where the panel records its own pid, derived from the log path.

    Derived rather than a second constant so that redirecting ``PANEL_LOG_PATH``
    (which every window-building test already does) also redirects this: a test
    window writing the production pid file would aim the stop command at the wrong
    process.  Written by the panel itself because the launcher cannot know it -- a
    venv ``pythonw.exe`` is a stub that spawns the real interpreter and exits, so
    the pid a launcher holds is dead within a second while the panel runs on.
    """
    return Path(PANEL_LOG_PATH).parent / "panel.pid"


# How long a queue-clock heartbeat stays meaningful.  The same 90 seconds the queue
# itself uses to decide whether a validation lease may be requested: one number, so
# "the panel is running" cannot mean two different things in two places.
PANEL_CLOCK_MAX_AGE_SECONDS = 90.0


def panel_clock_owner(*, now: "datetime | None" = None) -> tuple[int, float]:
    """``(pid, age_seconds)`` of whoever is ticking the queue clock right now.

    Read from the one heartbeat that already exists (``pump.json``), not from a second
    bookkeeping file: the pump writes its own pid on every tick, so a fresh file *is*
    the ownership evidence.  0 means "nobody", which is also the answer when the file
    is missing or unreadable -- a clock that has never ticked has no owner to name.

    Measured 2026-09-18: two panels were alive within the same minute (pump.json named
    pid 26428 at 16:34:52, a console start was logged at 16:35:19, then pump.json named
    pid 16508 at 16:36:22).  Both ran a ``QueuePump`` and both would have auto-started
    AUTO: two owners of one device and a second consumer on one queue.  The operator's
    Single UI Owner rule had no equivalent at the window layer.
    """
    moment = now or datetime.now(timezone.utc)
    try:
        payload = json.loads(Path(PUMP_STATE_PATH).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return 0, float("inf")
    try:
        pid = int(payload.get("process") or 0)
    except (TypeError, ValueError):
        return 0, float("inf")
    try:
        written = datetime.fromisoformat(str(payload.get("written_at") or ""))
    except ValueError:
        # A pid we cannot date is as useless as no pid: the caller may only act on an
        # owner it can vouch for, so neither half is offered.
        return 0, float("inf")
    if written.tzinfo is None:
        written = written.replace(tzinfo=timezone.utc)
    if pid <= 0:
        # Same rule for a dated file with no usable pid: "nobody" comes with no age,
        # so a caller cannot report "just now" about an owner it does not have.
        return 0, float("inf")
    return pid, (moment - written).total_seconds()


def _pid_is_live(pid: int) -> bool:
    """Ask about one pid by number.  Never by pattern over the process table.

    Delegated to the restart tool, where this question already lives: a pattern over
    the whole table matched the agent host process on 2026-09-18 and killed it, and a
    second implementation would be a second place for that mistake to live.  An
    unanswerable question returns True -- refusing to open a window because a liveness
    check failed is worse than opening a read-only one.

    Both import spellings are tried, because the *panel* runs through
    ``launch_pinned_production.py`` -> ``runpy.run_path`` with ``cwd=CODE_ROOT``, where
    ``tools/`` is not on ``sys.path``: ``from panel_restart import alive`` raised
    ``ModuleNotFoundError`` there and *only* there.  Measured 2026-09-30: that made the
    except-branch fire for every call, so every pid answered "live" and AUTO was refused
    for a whole window against a pid that did not exist --

        03:41:11  另一个实例正在运行（pid 3168）：本窗口只读，不消费队列、不启动 AUTO
        03:42:00  不自动启动 AUTO：另一个实例（pid 3168）正在运行。本窗口只读。

    ``alive`` itself was never wrong: ``alive(3168)`` is False and ``alive(<panel pid>)``
    is True.  Only the name it was looked up under was wrong.
    """
    if pid <= 0:
        return False
    try:
        try:
            from panel_restart import alive  # type: ignore[import-not-found]
        except ImportError:
            from tools.panel_restart import alive  # type: ignore[import-not-found]
        return bool(alive(pid))
    except Exception:  # noqa: BLE001
        return True


PANEL_LOG_MAX_BYTES = 1_000_000
RUNTIME_SNAPSHOT_PATH = ROOT / "learning/runtime_snapshot.json"
MUMU_PATH = Path(r"D:\Program Files\Netease\MuMu Player 12\nx_main\MuMuNxMain.exe")
MUMU_MANAGER_PATH = Path(r"D:\Program Files\Netease\MuMu Player 12\nx_main\MuMuManager.exe")
MUMU_VM_INDEX = "0"
BG, PANEL, PANEL2 = "#0b1118", "#111b26", "#172432"
TEXT, MUTED, ACCENT = "#e7edf4", "#8fa1b3", "#53b7ff"
GOOD, WARN, BAD = "#52d49a", "#f0b35a", "#ef6b73"
NO_WINDOW_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_INSTANCE_MUTEX: int | None = None


def _acquire_single_instance() -> bool:
    """Keep desktop double-clicks from creating competing control panels.

    Returning False is not an error: it means the operator is asking again for a panel
    that is already running, and ``main`` turns that into "show the existing window"
    rather than a silent exit.
    """
    global _INSTANCE_MUTEX
    if os.name != "nt":
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateMutexW(None, False, "Local\\WinterAgentOSV2ControlPanel")
    if not handle:
        return False
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return False
    _INSTANCE_MUTEX = handle
    return True


# A second launch must answer the question the double-click asked.  The implementation
# lives in ``tools/panel_window.py`` because the launcher needs the same behaviour
# before it calls schtasks: the task is registered IgnoreNew, so once a panel is
# running a second ``schtasks /Run`` starts nothing and this module is never loaded.
# One copy of the Win32 probing, two callers.
# ---------------------------------------------------------------------------


def _existing_panel_pid() -> int:
    """The pid the live panel recorded, or ``0`` when there is nothing readable."""
    return panel_window.read_panel_pid(panel_pid_path())


def _report_existing_panel() -> None:
    """Answer the operator's double-click instead of exiting silently.

    This covers the mutex half: the launcher did start an instance and the
    single-instance gate refused it.  Wrapped, because it runs on the way out of a
    launch that is about to return 0 -- an exception here would restore the silent
    second-click it exists to remove.
    """
    try:
        code, reason = panel_window.focus_existing_panel(panel_pid_path())
    except Exception as exc:  # noqa: BLE001 - the operator needs the reason, not a traceback
        code, reason = panel_window.UNAVAILABLE, f"检查已有面板时出错：{type(exc).__name__}: {exc}"
    if code == panel_window.SHOWN:
        return
    panel_window.notify_operator(
        "Winter Agent OS V2 的面板已经在运行，但没有把它显示出来：\n\n"
        f"{reason}\n\n"
        "双击不会打开第二个面板（一个面板对应一份 AUTO，这是设计如此）。\n"
        "请在任务管理器中结束该面板进程后重新双击；如果它已经卡住，重启计算机最干净。"
    )


def _background_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    """Run a console utility hidden, with a decodable default encoding.

    The flags come from winproc rather than a local constant: one place owns how a
    background process is started, and tools/check_wiring.py enforces it (operator P0,
    2026-09-18).  encoding/errors default here because this environment sets a
    UTF-8 default for Python's own I/O while console tools print the OEM codepage --
    measured: netstat raised UnicodeDecodeError on byte 0xbb, i.e. the diagnostic
    failed exactly when it was needed.
    """
    kwargs.setdefault("encoding", winproc.default_encoding())
    kwargs.setdefault("errors", "replace")
    return subprocess.run(command, **winproc.hidden_kwargs(), **kwargs)


def _background_popen(command: list[str], **kwargs: Any) -> subprocess.Popen[str]:
    """Launch a runtime child fully backgrounded."""
    kwargs.setdefault("encoding", winproc.default_encoding())
    kwargs.setdefault("errors", "replace")
    return subprocess.Popen(command, **winproc.hidden_kwargs(), **kwargs)


# ---------------------------------------------------------------------------
# Waiting for a worker has to be bounded, or one non-exiting child ends the cycle.
#
# Measured live 2026-09-21 11:43:24 local: that round's worker finished its loop -- the runtime
# snapshot was written at 03:45:04 with ``runtime_thread_alive`` and ``scheduler_loop_alive`` both
# false -- and then never exited.  The panel waits on the child's pipe (see ``await_worker``), which
# returns at EOF, and on Windows the process the panel holds is the venv *redirector*: the real
# worker (and anything it leaves behind, MAA included) is a grandchild that also holds that pipe.
# So the panel blocked for the rest of the session: no round started, ``panel.log`` wrote nothing
# for thirteen minutes, ``operator_intent`` stayed RUNNING, and the panel's own escalation pump kept
# ticking the whole time -- which is exactly what makes it look alive.  The operator had to restart
# the window.
#
# Sixteen wait sites in this file had the same shape, so the bound lives in one function rather
# than in each call.  This is not "restart faster": nothing about the interval changes, and a round
# that is working is still waited for.  What changes is that a worker which does not come back can
# no longer stop every other task -- the same rule the runtime applies to a goal that cannot act.
# ---------------------------------------------------------------------------

#: How long one worker invocation may run before the panel stops waiting for it.
#:
#: A round is bounded by its own action budget (``--max-actions 24``) and every action is a device
#: round trip, so this is generous rather than tight.  The number matters less than its existence.
WORKER_WAIT_SECONDS = 900.0

#: Grace allowed for the killed tree to release the pipe so its last output can still be read.
WORKER_KILL_GRACE_SECONDS = 20.0

#: Reported instead of a worker's own exit code when the panel stopped waiting.
#:
#: Distinct from the codes the worker emits (0 verified, 2 unverified, 4 wrong version) so a reader
#: can tell "the worker said this" from "the panel gave up waiting".  Non-zero on purpose: the
#: round did not produce a verified end, and ``summarize_runtime_result`` already treats a non-zero
#: code as an abnormal round -- which keeps the cycle going and reports it honestly.
WORKER_ABANDONED_CODE = 130


def await_worker(
    process: subprocess.Popen[str],
    *,
    label: str,
    wait_seconds: float = WORKER_WAIT_SECONDS,
) -> tuple[str, int]:
    """Read a worker's output, but never for longer than ``wait_seconds``.

    Returns ``(output, exit_code)``.  On timeout the process tree is ended (the same
    ``taskkill /T`` the panel's own stop button uses) and the code is
    ``WORKER_ABANDONED_CODE``, with a line appended to the output saying so -- the output is
    what gets written to ``latest.log``, so an abandoned round must be readable there rather
    than looking like a round that simply ended.
    """
    try:
        output, _ = process.communicate(timeout=wait_seconds)
        return output or "", process.returncode
    except subprocess.TimeoutExpired:
        winproc.kill_tree(process.pid, timeout=WORKER_KILL_GRACE_SECONDS)
        try:
            output, _ = process.communicate(timeout=WORKER_KILL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            output = ""
        note = (
            f"[panel] {label} did not exit within {wait_seconds:.0f}s after its loop returned; "
            f"the panel ended its process tree and carried on with the next round. The round's own "
            f"evidence is in its captures; this line is the panel's, not the worker's."
        )
        return f"{output or ''}\n{note}\n", WORKER_ABANDONED_CODE



# Environment failures the worker raises on purpose when the emulator, the ADB
# link, or the operator gets in the way.  They are recoverable by waiting and
# retrying, and they are NOT evidence of a worker defect, so they must not be
# counted as an unexpected worker exit.  Anything else that escapes the worker
# thread is a real crash and is counted, with a full report.
ENVIRONMENT_FAILURES = (
    "DEVICE_NOT_CONNECTED", "DEVICE_AMBIGUOUS", "DEVICE_CONNECT_TIMEOUT",
    "ADB_DISCOVERY_FAILED", "ADB_COMMAND_TIMEOUT", "ADB_FAILED",
    "MUMU_LAUNCHER_NOT_FOUND", "MUMU_LAUNCH_FAILED",
    "MuMu 未连接", "MuMu 实例启动失败", "等待 MuMu 连接超时", "用户已停止",
    "SCREENSHOT_NOT_PNG", "SCREENSHOT_DAMAGED", RUNTIME_ENV_STOP_REASON,
)


def classify_worker_failure(message: str) -> str:
    """Return ``ENVIRONMENT`` or ``WORKER_CRASH`` for a worker failure message."""
    text = str(message or "")
    return "ENVIRONMENT" if any(marker in text for marker in ENVIRONMENT_FAILURES) else "WORKER_CRASH"


MAX_CONSECUTIVE_WORKER_CRASH_RESTARTS = 3


def worker_result_failure(output: str, exit_code: int) -> dict[str, Any]:
    """A child that never returned its result failed, even if the panel stayed alive."""
    lines = str(output or "").splitlines()
    traceback_start = next((i for i, line in enumerate(lines)
                            if line.startswith("Traceback (most recent call last):")), None)
    child_traceback = ""
    message = f"WORKER_RESULT_MISSING: exit={exit_code}"
    if traceback_start is not None:
        tail = lines[traceback_start:]
        exception_line = next((i for i, line in reversed(list(enumerate(tail)))
                               if re.match(r"^[\w.]+(?:Error|Exception|Exit|Interrupt)(?::|$)", line)), None)
        if exception_line is not None:
            message = tail[exception_line]
            child_traceback = "\n".join(tail[:exception_line + 1])
        else:
            child_traceback = "\n".join(tail)
    elif exit_code == WORKER_ABANDONED_CODE:
        message = f"WORKER_TIMEOUT: exit={exit_code}"
    return {"message": message, "classification": classify_worker_failure(message),
            "exit_code": exit_code, "child_traceback": child_traceback}


def write_worker_crash_report(
    *, where: str, exc: BaseException, snapshot: Any, context: dict[str, Any] | None = None,
) -> Path:
    """Persist the evidence needed to find the real root cause of a worker exit.

    Previously the worker caught ``Exception`` and forwarded only ``str(exc)``,
    so every crash arrived as one unhelpful line and the counter could not be
    acted on.  This records the exception type, the full traceback, the runtime
    state at the moment of death, and the live thread inventory.
    """
    CRASH_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    snapshot_data = snapshot.__dict__ if hasattr(snapshot, "__dict__") else {"value": str(snapshot)}
    context = context if isinstance(context, dict) else {}

    def event_tail(path: Path, *, limit: int = 20) -> list[dict[str, str]]:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            stamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        except OSError:
            return []
        return [{"source": path.name, "file_mtime": stamp, "line": line}
                for line in lines[-limit:]]

    panel_events = event_tail(PANEL_LOG_PATH)
    runtime_output = event_tail(LOG_ROOT / "latest.log")
    recovery_events = event_tail(LOG_ROOT / "worker_recovery.jsonl")
    events = (panel_events + runtime_output + recovery_events)[-20:]
    report = {
        "at": datetime.now(timezone.utc).isoformat(),
        "where": where,
        "exception_type": type(exc).__name__,
        "exception_message": str(exc),
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        "classification": classify_worker_failure(str(exc)),
        "goal": context.get("goal", snapshot_data.get("current_goal")),
        "skill": context.get("skill", snapshot_data.get("current_skill")),
        "role": context.get("role", snapshot_data.get("role_id")),
        "page": context.get("page", snapshot_data.get("page", "UNKNOWN")),
        "last_20_events": events,
        "device_state": context.get("device_state", snapshot_data.get("device", "UNKNOWN")),
        "adb_state": context.get("adb_state", "UNKNOWN"),
        "maa_state": context.get("maa_state", {
            "configured": None,
            "vision": snapshot_data.get("vision", "UNKNOWN"),
        }),
        "retry_state": context.get("retry_state", {
            "watchdog_restart_count": snapshot_data.get("watchdog_restart_count", 0),
            "unexpected_worker_exits_before_report": snapshot_data.get("unexpected_worker_exits", 0),
        }),
        "recovery_attempt": context.get("recovery_attempt"),
        "thread_state": [
            {"name": thread.name, "alive": thread.is_alive(), "daemon": thread.daemon}
            for thread in threading.enumerate()
        ],
        "runtime_snapshot": snapshot_data,
        "child_traceback": context.get("child_traceback", ""),
        "child_exit_code": context.get("exit_code"),
    }
    path = CRASH_ROOT / f"{stamp}_{where}.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)
    return path

PAGE_ZH = {"HOME": "主城", "MAP": "世界地图", "RESOURCE_DETAIL": "资源点", "MARCH": "行军编队",
           "MARCH_QUEUE": "行军队列", "BUILDING": "建筑", "RESEARCH": "科技", "TRAINING": "训练",
           "INTEL": "情报", "BEAST": "野怪", "DAILY": "日常", "ALLIANCE": "联盟", "MAIL": "邮件",
           "EXPLORATION": "探险", "HERO": "英雄", "POPUP": "弹窗", "UNKNOWN": "页面未识别"}
SKILL_ZH = {"GATHER_RESOURCE": "资源采集", "BUILDING_UPGRADE": "建筑升级", "RESEARCH": "科技研究",
            "TRAIN_TROOPS": "训练部队", "INTEL_CLAIM_REWARDS": "情报奖励", "BEAST_HUNT": "野怪狩猎",
            "DAILY_HERO_RECRUIT": "每日招募", "DAILY_CLAIM_REWARDS": "日常奖励",
            "ALLIANCE_TECH_CONTRIBUTE": "联盟科技", "ALLIANCE_HELP": "联盟帮助",
            "ALLIANCE_GIFTS": "联盟礼物", "MAIL_CLAIM_REWARDS": "邮件奖励",
            "OPEN_POWER_OVERVIEW": "打开战力总览", "OPEN_POWER_DETAILS": "打开实力详情",
            "NAVIGATE_INFANTRY_CAMP": "定位盾兵营", "OPEN_INFANTRY_TRAINING": "打开盾兵训练",
            "TRAIN_TROOPS": "训练盾兵",
            "OPEN_MAIL": "打开邮件", "SELECT_MAIL_ALLIANCE_TAB": "联盟邮件", "SELECT_MAIL_SYSTEM_TAB": "系统邮件",
            "SELECT_MAIL_REPORT_TAB": "报告邮件", "DISMISS_MAIL_REWARD": "关闭邮件奖励",
            "EXPLORATION_IDLE_CLAIM": "探险收益", "OPEN_MAP": "前往世界地图",
            "OPEN_HOME": "返回主城", "SEARCH_RESOURCE": "搜索资源", "SELECT_RESOURCE": "选择资源",
            "SUBMIT_RESOURCE_SEARCH": "查找资源点", "START_GATHER": "开始采集",
            "OPEN_EXPLORATION": "打开探险", "EXPLORATION_IDLE_CLAIM": "打开挂机收益",
            "CONFIRM_EXPLORATION_IDLE_CLAIM": "领取挂机收益", "DISMISS_EXPLORATION_REWARD": "关闭探险奖励",
            "OPEN_DAILY": "打开每日任务", "DAILY_CLAIM_REWARDS": "领取每日奖励", "DISMISS_DAILY_REWARD": "关闭每日奖励",
            "DISMISS_MAIL_GENERIC_REWARD": "关闭邮件奖励",
            "DISPATCH_MARCH": "派遣行军", "CLOSE_POPUP": "关闭弹窗",
            "OPEN_INTEL": "打开情报", "SELECT_INTEL_BEAST_MISSION": "选择情报兽任务", "SELECT_INTEL_FIREBEAST_MISSION": "选择炽红巨兽情报",
            "SELECT_INTEL_RESCUE_SURVIVORS": "选择营救幸存者", "OPEN_INTEL_RESCUE_SURVIVORS_TARGET": "查看营救目标", "EXECUTE_INTEL_RESCUE_SURVIVORS": "执行营救",
            "OPEN_INTEL_BEAST_TARGET": "查看情报目标", "INTEL_BEAST_START_MARCH": "情报兽编队",
            "DISPATCH_INTEL_BEAST": "派遣情报兽", "DISMISS_INTEL_REWARD": "关闭情报奖励"}
REASON_ZH = {"no_idle_march": "没有空闲行军，已安全等待", "reserved_march_for_stamina": "已为体力任务预留1支行军", "max_actions_reached": "本轮动作上限已到",
             "target_skill_verified": "任务已通过验证", "UNKNOWN_PAGE": "页面未识别",
             "unknown_page": "页面未识别", "DEVICE_BUSY": "设备忙", "VISION_FAILURE": "视觉识别失败",
             "PAGE_NOT_FOUND": "未找到目标页面", "SKILL_NOT_ENABLED_FOR_LIVE_LOOP": "能力尚未接入实机主循环",
             "mail_all_clear": "邮件奖励已全部清空", "mail_state_unknown": "邮件状态未识别",
             # A run that has stood on every page it can reach and been offered nothing on any of
             # them.  It reads as a sentence about the round's search, not as an error code, because
             # that is what it is -- see ``LiveRuntime._stop_instead_of_looking_again``.
             "every_page_this_run_was_fruitless": "本轮每一页都看过，都没有可做的事"}
MARCH_ZH = {MarchState.IDLE: "空闲", MarchState.MARCHING: "行军中", MarchState.GATHERING: "采集中",
            MarchState.RETURNING: "返回中", MarchState.UNKNOWN: "未识别"}


def _global_wait_delay_ms(reason: str, *, now: datetime | None = None) -> int:
    """Wait until the persisted global wake time, with a bounded fallback refresh."""
    if reason != "GLOBAL_WAIT":
        return 30000
    path = ROOT / "learning/global_scheduler_state.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw = payload.get("global_next_wakeup_at") if isinstance(payload, dict) else None
        wake = datetime.fromisoformat(str(raw).replace("Z", "+00:00")) if raw else None
    except (OSError, ValueError, json.JSONDecodeError, TypeError):
        wake = None
    if wake is None:
        return 30000
    moment = now or datetime.now(timezone.utc)
    if wake.tzinfo is None:
        wake = wake.replace(tzinfo=timezone.utc)
    seconds = max(1.0, (wake.astimezone(timezone.utc) - moment.astimezone(timezone.utc)).total_seconds())
    # Do not lose an exact near-term wake, and retain one daily health refresh if
    # the source time is unexpectedly far away.
    return int(min(seconds, 24 * 60 * 60) * 1000)

def _global_decision_timeline(history: Any, names: dict[str, str], *, limit: int = 10) -> str:
    """Format persisted arbitration decisions for the operator console."""
    if not isinstance(history, list):
        return "暂无历史决策"
    rows = [row for row in history if isinstance(row, dict)][-max(1, int(limit)):]
    if not rows:
        return "暂无历史决策"
    decision_labels = {
        "KEEP_ROLE": "保持角色",
        "ROLE_REFRESH_REQUIRED": "请求切换",
        "GLOBAL_WAIT": "全局等待",
        "ROLE_SWITCH_FAILED": "切换失败",
    }
    lines = []
    for row in rows:
        stamp = str(row.get("at") or row.get("timestamp") or "")
        when = stamp.replace("T", " ")[:19] if stamp else "时间未知"
        source = str(row.get("current_role_id") or "")
        target = str(row.get("selected_role_id") or source)
        source_name = names.get(source, source or "未知")
        target_name = names.get(target, target or "未知")
        kind = str(row.get("decision") or "").upper()
        if kind == "GLOBAL_WAIT":
            selection = "全局等待"
        elif kind == "KEEP_ROLE" or (source and source == target):
            selection = f"保持 {target_name}"
        else:
            selection = f"{decision_labels.get(kind, kind or '选择')} {source_name}→{target_name}"
        goal = str(row.get("selected_goal_id") or row.get("selected_skill_id") or "无目标")
        reason = " ".join(str(row.get("reason") or "暂无原因").split())
        if len(reason) > 72:
            reason = reason[:69] + "..."
        lines.append(f"{when}｜{selection}｜{goal}｜{reason}")
    return "\n".join(lines)


def _global_hard_event(decision: dict[str, Any], names: dict[str, str]) -> str:
    """Summarize the strongest hard-time candidate from the latest global round."""
    candidates = decision.get("candidates")
    if not isinstance(candidates, list):
        return "最近一次评估未提供硬时间目标"
    hard = [row for row in candidates if isinstance(row, dict) and row.get("hard_event") is True]
    if not hard:
        return "最近一次评估无临近硬时间目标"
    selected = max(hard, key=lambda row: float(row.get("score") or 0.0))
    role_id = str(selected.get("role_id") or "")
    role = names.get(role_id, role_id or "角色未知")
    goal = str(selected.get("goal_id") or selected.get("skill_id") or "活动状态刷新")
    remaining = selected.get("deadline_seconds", selected.get("remaining_seconds"))
    event_start = selected.get("event_starts_in_seconds")
    phase = str(selected.get("event_phase") or "").upper()
    if isinstance(remaining, (int, float)) and not isinstance(remaining, bool):
        timing = f"剩余 {max(0, int(remaining))} 秒"
    elif isinstance(event_start, (int, float)) and not isinstance(event_start, bool):
        timing = ("活动窗口已开放" if int(event_start) <= 0 and phase == "OPEN"
                  else f"距离开始 {max(0, int(event_start))} 秒")
        if phase:
            timing += f"（{phase}）"
    elif phase and phase != "IDLE":
        timing = f"调度阶段 {phase}"
    else:
        timing = "调度硬时间优先级已触发"
    return f"{role} · {goal} · {timing}"


def _fmt_duration(seconds: Any) -> str:
    try:
        value = int(float(seconds))
    except (TypeError, ValueError):
        return "未知"
    if value < 0:
        return "未知"
    hours, remainder = divmod(value, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def _role_session_display(payload: dict[str, Any],
                          names: dict[str, str]) -> dict[str, str]:
    """ROLE_SESSION_PRODUCTION_V2 §16: show the real session, not a paraphrase.

    Everything here is read from artifacts the runtime already wrote -- the persisted
    session counters and the last arbitration's own gate verdict -- so a panel that is not
    running cannot disagree with the worker about why a role switch did or did not happen.
    """
    decision = payload.get("last_decision") if isinstance(payload.get("last_decision"), dict) else {}
    gate = decision.get("session_gate") if isinstance(decision.get("session_gate"), dict) else {}
    session = payload.get("role_session") if isinstance(payload.get("role_session"), dict) else {}
    active = str(payload.get("active_role_id") or "")
    label = names.get(active, active or "未知")

    if not session and not gate:
        return {
            "session": "尚未建立角色Session（等待首次身份确认）",
            "preempt": "暂无跨角色限时抢占评估",
            "switch_quality": "切换质量样本不足",
        }

    discovered = gate.get("goals_discovered")
    if discovered is None:
        discovered = session.get("session_goal_count")
    consumed = gate.get("goals_consumed")
    if consumed is None:
        consumed = session.get("session_done_goal_count")
    ratio = gate.get("completion_ratio")
    if ratio is None:
        ratio = session.get("completion_ratio")
    try:
        ratio_text = f"{float(ratio):.0%}" if ratio is not None else "未知"
    except (TypeError, ValueError):
        ratio_text = "未知"
    allowed = bool(gate.get("allowed"))
    reason = str(gate.get("detail") or session.get("switch_reason") or "未知")
    # The dwell clock is the session's own age: it starts when the role took the device.
    elapsed = gate.get("session_elapsed_seconds")
    if elapsed is None:
        elapsed = session.get("elapsed_seconds")
    dwell = (_fmt_duration(elapsed) if elapsed is not None
             else ("计于 " + str(session.get("started_at") or "")[:19]
                   if session.get("started_at") else "未知"))
    ready = gate.get("ready_now")
    if ready is None:
        ready = session.get("ready_now")
    waiting = gate.get("waiting_now")
    if waiting is None:
        waiting = session.get("waiting_now")
    session_line = (
        f"{label}｜驻留 {dwell}｜本Session 完成/已发现 "
        f"{int(consumed or 0)}/{int(discovered or 0)}（{ratio_text}）"
        f"｜READY {int(ready or 0)}｜WAIT {int(waiting or 0)}"
        f"｜切换 {'ALLOWED' if allowed else 'LOCKED'}｜Reason {reason}"
    )

    preempt_rows = decision.get("hard_event_roles")
    preempt_rows = preempt_rows if isinstance(preempt_rows, list) else []
    if preempt_rows:
        parts = []
        for row in preempt_rows[:2]:
            if not isinstance(row, dict):
                continue
            other = names.get(str(row.get("role_id") or ""), str(row.get("role_id") or "未知"))
            starts = row.get("event_starts_in_seconds")
            deadline = row.get("deadline_seconds")
            if isinstance(starts, (int, float)):
                timing = f"T-{_fmt_duration(starts)}"
            elif isinstance(deadline, (int, float)):
                timing = f"截止 {_fmt_duration(deadline)}"
            else:
                timing = str(row.get("event_phase") or "窗口内")
            parts.append(f"{other} HARD EVENT: {row.get('skill_id') or '未知'}｜{timing}")
        preempt = "；".join(parts) + " → PREEMPT_PENDING"
    else:
        preempt = "无跨角色限时抢占（普通优先级差异不构成切换理由）"

    history = payload.get("role_switch_history")
    history = history if isinstance(history, list) else []
    quality_rows = [row for row in history if isinstance(row, dict)]
    if quality_rows:
        # One definition of these metrics, shared with the state store's own accessor, so
        # the panel and any programmatic reader cannot report different numbers.
        measured = role_switch_quality_metrics(switch_history=quality_rows)
        per_hour = measured.get("role_switches_per_hour")
        avg_dwell = _fmt_duration(measured.get("avg_role_session_duration_seconds"))
        avg_goals = (f"{float(measured['avg_goals_per_role_session']):.1f}"
                     if measured.get("avg_goals_per_role_session") is not None else "未知")
        reasons = measured.get("last_switch_reasons") or []
        quality = (
            f"样本 {len(quality_rows)} 次 Session｜ROLE_SWITCHES_PER_HOUR "
            f"{per_hour if per_hour is not None else '样本不足'}｜平均驻留 {avg_dwell}｜"
            f"平均每 Session 完成 Goal {avg_goals}｜"
            f"最近原因 {', '.join(str(item or '未分类') for item in reasons) or '无'}"
        )
    else:
        quality = "切换质量样本不足（尚无完成的角色Session）"
    return {"session": session_line, "preempt": preempt, "switch_quality": quality}


def global_scheduler_display(root: Path = ROOT) -> dict[str, Any]:
    """Render the persisted arbitration decision without inventing live role state."""
    try:
        payload = json.loads((root / "learning/global_scheduler_state.json").read_text(encoding="utf-8"))
        catalog = json.loads((root / "knowledge/roles/role_inventory.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {"current": "尚未启动", "roles": [], "decision": "暂无双角色决策", "hard_event": "暂无硬时间评估", "timeline": "暂无历史决策", "metrics": "暂无切换样本", "telemetry": "生产计数尚未初始化", "remaining_a": "今日完成看板尚未生成", "remaining_b": "今日完成看板尚未生成", "task_completion": "暂无今日任务完成证据", "session": "尚未建立角色Session（等待首次身份确认）", "preempt": "暂无跨角色限时抢占评估", "switch_quality": "切换质量样本不足"}
    if not isinstance(payload, dict):
        return {"current": "尚未启动", "roles": [], "decision": "暂无双角色决策", "hard_event": "暂无硬时间评估", "timeline": "暂无历史决策", "metrics": "暂无切换样本", "telemetry": "生产计数尚未初始化", "remaining_a": "今日完成看板尚未生成", "remaining_b": "今日完成看板尚未生成", "task_completion": "暂无今日任务完成证据", "session": "尚未建立角色Session（等待首次身份确认）", "preempt": "暂无跨角色限时抢占评估", "switch_quality": "切换质量样本不足"}
    names = {
        str(row.get("role_id")): str(row.get("role_key") or row.get("display_name") or row.get("role_id"))
        for row in (catalog.get("roles", []) if isinstance(catalog, dict) else [])
        if isinstance(row, dict) and row.get("role_id")
    }
    role_ids = list(names)
    active = str(payload.get("active_role_id") or "")
    current = f"{names.get(active, active or '未知')} · {active or '身份未确认'}"
    decision = payload.get("last_decision") if isinstance(payload.get("last_decision"), dict) else {}
    statuses = decision.get("role_statuses") if isinstance(decision.get("role_statuses"), list) else []
    status_by_id = {str(row.get("role_id")): row for row in statuses if isinstance(row, dict)}
    role_lines = []
    for role_id in role_ids[:2]:
        row = status_by_id.get(role_id, {})
        top = str(row.get("top_goal") or "无可执行目标")
        ready = int(row.get("runnable_count") or 0)
        blocked = int(row.get("blocked_count") or 0)
        wait = str(row.get("wait_until") or "无")
        deadline = row.get("next_deadline_seconds")
        deadline_text = f"{int(deadline)}秒" if isinstance(deadline, (int, float)) else "无"
        freshness = "本轮已观测" if row.get("state_fresh") else "使用逻辑快照/待刷新"
        cooldown = str(row.get("switch_cooldown_until") or "")
        failure_streak = int(row.get("switch_failure_streak") or 0)
        switch_state = f"｜切换退避至 {cooldown}（失败 {failure_streak} 次）" if cooldown else ""
        role_lines.append(
            f"{names.get(role_id, role_id)}：{top}｜可执行 {ready}｜阻塞 {blocked}｜"
            f"等待至 {wait}｜最近期限 {deadline_text}｜{freshness}{switch_state}"
        )
    selected_role = str(decision.get("selected_role_id") or "")
    selected_goal = str(decision.get("selected_goal_id") or "")
    selected_skill = str(decision.get("selected_skill_id") or "")
    selected_label = names.get(selected_role, selected_role or "无")
    why = str(decision.get("reason") or payload.get("last_switch_reason") or "暂无")
    action = str(decision.get("decision") or "暂无")
    next_wakeup = str(payload.get("global_next_wakeup_at") or decision.get("next_wakeup") or "无")
    metrics = {
        "count": int(payload.get("role_switch_count") or 0),
        "success": int(payload.get("role_switch_success_count") or 0),
        "failure": int(payload.get("role_switch_failure_count") or 0),
    }
    complete = metrics["success"] + metrics["failure"]
    rate = f"{metrics['success'] / complete:.0%}" if complete else "暂无"
    duration_rows = payload.get("role_switch_durations_ms", [])
    if not isinstance(duration_rows, list):
        duration_rows = []
    samples = sorted(float(value) for value in duration_rows if isinstance(value, (int, float)))
    p50 = f"{samples[max(0, (len(samples) + 1) // 2 - 1)]:.0f}ms" if samples else "暂无"
    p95 = f"{samples[max(0, int(len(samples) * .95 + .999999) - 1)]:.0f}ms" if samples else "暂无"
    telemetry_since = str(payload.get("telemetry_since") or "")
    if telemetry_since:
        completed_by_role = payload.get("completed_goal_count_by_role")
        completed_by_role = completed_by_role if isinstance(completed_by_role, dict) else {}
        completed_text = " / ".join(
            f"{names.get(role_id, role_id)} {int(completed_by_role.get(role_id) or 0)}"
            for role_id in role_ids[:2]
        ) or "暂无角色"
        telemetry = (
            f"自 {telemetry_since[:10]}：GLOBAL_WAIT {int(payload.get('global_wait_count') or 0)} 次"
            f"（带可执行 Goal {int(payload.get('global_wait_with_runnable_goal_count') or 0)} 次）｜"
            f"共享 Goal credit {int(payload.get('shared_goal_credit_count') or 0)} 次｜"
            f"已完成 Goal {completed_text}｜动作结果 {int(payload.get('action_outcome_count') or 0)} 条"
        )
    else:
        telemetry = "生产计数尚未初始化（从本版本首条 Scheduler / ActionOutcome 记录开始统计）"
    completion_view = task_completion_display(root, role_ids, names)
    session_view = _role_session_display(payload, names)
    return {
        "current": current,
        "roles": role_lines,
        "decision": f"{action} → {selected_label} {selected_goal} / {selected_skill}；{why}",
        "hard_event": _global_hard_event(decision, names),
        "timeline": _global_decision_timeline(payload.get("decision_history"), names),
        "telemetry": telemetry,
        "wakeup": next_wakeup,
        "metrics": f"切换 {metrics['count']} 次｜成功率 {rate}｜p50 {p50}｜p95 {p95}",
        **session_view,
        **completion_view,
    }


def task_completion_display(
    root: Path, role_ids: list[str], names: dict[str, str],
) -> dict[str, str]:
    """Show today's role boards from the Goal/Episode projection when available."""
    try:
        matrix = json.loads((root / "learning/task_completion_matrix.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        matrix = {}
    roles = matrix.get("roles") if isinstance(matrix, dict) else {}
    roles = roles if isinstance(roles, dict) else {}
    lines: dict[str, str] = {}
    completed_total = observed_total = unseen_total = 0
    status_zh = {"READY": "可执行", "RUNNING": "进行中", "WAITING": "等待", "BLOCKED": "阻塞",
                 "NOT_DISCOVERED": "未发现", "COMPLETE": "完成", "EXPIRED": "已过期"}
    task_zh = {
        "DAILY": "每日任务", "INTEL": "情报", "MAIL": "邮件", "REWARD": "奖励",
        "ALLIANCE": "联盟", "ALLIANCE_DONATION": "联盟捐献", "TRAINING": "训练",
        "RESEARCH": "科研", "BUILDING": "建筑", "GATHER": "采集", "STAMINA": "体力",
        "BEAST": "打野", "ICEFIELD_BEAST": "冰原巨兽", "ARENA": "竞技场",
        "ACTIVITY_CLAIM": "活动奖励", "FREE_REWARD": "免费奖励",
        "ALLIANCE_MOBILIZATION": "联盟总动员", "BEAR": "巨熊", "FISHING": "钓鱼", "OTHER_CURRENT_EVENTS": "其他活动",
    }
    for index, role_id in enumerate(role_ids[:2]):
        key = "remaining_a" if index == 0 else "remaining_b"
        role = roles.get(role_id) if isinstance(roles.get(role_id), dict) else {}
        board = role.get("daily_board") if isinstance(role.get("daily_board"), dict) else {}
        tasks = board.get("tasks") if isinstance(board.get("tasks"), dict) else {}
        summary = board.get("summary") if isinstance(board.get("summary"), dict) else {}
        completed_total += int(summary.get("completed") or 0)
        observed_total += max(0, int(summary.get("observed") or 0) - int(summary.get("expired") or 0))
        unseen_total += int(summary.get("not_discovered") or 0)
        if not board:
            lines[key] = f"{names.get(role_id, role_id)}：尚无当日角色 Goal 观察"
            continue
        pending = []
        for task_type, row in tasks.items():
            if not isinstance(row, dict) or row.get("status") in {"COMPLETE", "EXPIRED", "NOT_DISCOVERED"}:
                continue
            status = status_zh.get(str(row.get("status") or ""), str(row.get("status") or "待识别"))
            reason = str(row.get("reason_code") or "")
            suffix = f"/{reason}" if reason else ""
            pending.append(f"{task_zh.get(task_type, task_type)} {status}{suffix}")
        unseen = int(summary.get("not_discovered") or 0)
        completed = int(summary.get("completed") or 0)
        observed = max(0, int(summary.get("observed") or 0) - int(summary.get("expired") or 0))
        text = "、".join(pending[:7]) if pending else "当前已发现目标均完成或过期"
        if len(pending) > 7:
            text += f"等 {len(pending)} 项"
        text += f"；完成 {completed}/{observed}，未发现 {unseen} 类"
        productive = [task_zh.get(kind, kind) for kind, row in tasks.items()
                      if isinstance(row, dict) and row.get("PRODUCTIVE_CYCLE_VERIFIED")]
        if productive:
            text += "；今日生产循环已验证：" + "、".join(productive)
        lines[key] = f"{names.get(role_id, role_id)}：{text}"
    if len(role_ids) < 2:
        lines.setdefault("remaining_b", "角色 B：尚未登记启用角色")
    rate = f"{completed_total}/{observed_total}（{completed_total / observed_total:.0%}）" if observed_total else "暂无可计算的已观察任务"
    return {
        **lines,
        "task_completion": f"已观察角色任务完成度 {rate}｜未发现类别 {unseen_total}（未并入分母）",
    }

def parse_runtime_result(text: str) -> dict:
    """The runtime's result object, wherever the client's own output lands.

    The MuMu adapter prints its connect lines on stdout, and they arrive glued to
    the end of the result JSON **on the same line** -- measured 2026-09-18:

        ..."stop_reason": "verified_beast_target_not_visible"}product: MuMuPlayer-12.0-0

    Requiring the whole line to be JSON therefore dropped *every* payload, and
    with it every ``stop_reason``-driven decision in this file: the window said
    暂无结构化结果 while a complete, valid result sat on that line.  So scan for
    the object instead of demanding a clean line.
    """
    decoder = json.JSONDecoder()
    for line in reversed(text.splitlines()):
        start = line.find("{")
        while start != -1:
            try:
                payload, _ = decoder.raw_decode(line[start:])
            except json.JSONDecodeError:
                start = line.find("{", start + 1)
                continue
            if isinstance(payload, dict) and "stop_reason" in payload:
                return payload
            break
    return {}


def summarize_runtime_result(payload: dict, exit_code: int = 0) -> dict[str, Any]:
    steps = payload.get("steps", []) if isinstance(payload, dict) else []
    steps = steps if isinstance(steps, list) else []
    executed = verified = failures = 0
    verifier_reasons: list[str] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        execution, verification = step.get("execution") or {}, step.get("verification")
        executed += int(isinstance(execution, dict) and execution.get("executed") is True)
        if isinstance(verification, dict):
            verified += int(verification.get("ok") is True)
            failures += int(verification.get("ok") is False)
            if verification.get("ok") is False:
                verifier_reasons.append(str(verification.get("reason") or ""))
    reason = payload.get("stop_reason", "暂无结构化结果") if isinstance(payload, dict) else "暂无结构化结果"
    last = next((step for step in reversed(steps) if isinstance(step, dict)), {})
    decision = last.get("decision") if isinstance(last.get("decision"), dict) else {}
    execution = last.get("execution") if isinstance(last.get("execution"), dict) else {}
    last_verification = last.get("verification") if isinstance(last.get("verification"), dict) else {}
    category, agent_state = state_for_stop_reason(
        str(reason),
        decision_skill=str(decision.get("skill") or ""),
        action_executed=execution.get("executed") is True,
        verifier_failed=failures > 0,
        # Which failure ended the round, not merely that one happened: a stop naming a recoverable
        # verifier reason must not be refused as a system failure (measured 2026-09-30 05:14:35
        # UTC, DAILY_REWARD_ADVANCE_NOT_PROVEN).  See classify_stop_reason.
        verifier_reasons=tuple(verifier_reasons),
        last_step_verifier_failed=last_verification.get("ok") is False,
    )
    normal_ends = {
        StopCategory.EXPECTED_NO_ACTION,
        StopCategory.COMPLETED,
    }
    # Health is a property of how the round *ended* -- its classification -- not a count of the
    # events inside it.  ``failures`` stays in the summary and still drives ``verifier_failed``
    # for the classification, so nothing is hidden; but one miss inside a round that then used
    # its whole action budget is not a reason to stop an unattended system.
    #
    # Measured 2026-09-30 11:21 local: 24 actions, 23 verified, one BEAST_SEARCH_TAB miss, ended
    # MAX_ACTIONS_REACHED.  ``failures == 0`` made ``healthy`` false, ``should_continue_auto_cycle``
    # declined, and AUTO stopped with the device idle for fifteen minutes.  This is the companion
    # to the classifier fix in ``runtime_snapshot``, and it is the half that survives that one.
    healthy = exit_code == 0 and category is not StopCategory.SYSTEM_FAILURE
    return {"steps": len(steps), "executed": executed, "verified": verified, "failures": failures,
            "reason": reason, "stop_category": category.value,
            "agent_state": agent_state.value,
            "healthy": healthy,
            # ``ok`` continues to mean the cycle reached a normal no-action or
            # completion result. A capability gap is safe to continue around, but
            # it is not a completed task and must remain visible as such.
            "ok": exit_code == 0 and failures == 0 and category in normal_ends}


def auto_halt_reason(
    *, healthy: bool, reason: str, continuous: bool,
    stop_requested: bool, paused: bool, fatal: bool,
) -> str:
    """Why AUTO will not start another round, in the operator's language.

    Returns ``""`` when the cycle does continue, so a caller can log this on every round.
    A halt used to log *nothing*: measured 2026-09-30 11:21 local, a 24-action round was
    relabelled ``SYSTEM_FAILURE``, the gate declined, and ``panel.log`` simply stopped after
    the snapshot refresh -- AUTO looked alive while the device sat idle for fifteen minutes
    and nothing on screen said why.  The operator should never have to infer a halt from
    silence.

    This is the single source for the question ``should_continue_auto_cycle`` answers; that
    wrapper exists so the older call sites and their tests keep their boolean.
    """
    role_handoff = str(reason or "").startswith((
        "ROLE_SWITCH_FAILED:", "ROLE_SWITCHED_TO:", "ROLE_IDENTITY_CHANGED:",
    ))
    if continuous and not stop_requested and not paused and not fatal and (healthy or role_handoff):
        return ""
    if not continuous:
        return "连续运行开关已关闭，面板不会自动进入下一轮"
    if stop_requested:
        return "收到停止请求（操作员主动停止）"
    if paused:
        return "运行已暂停（PAUSED）"
    if fatal:
        return f"本轮停止原因不可自动恢复：{reason}"
    return f"本轮被判定为系统故障：{reason}"


def should_continue_auto_cycle(
    *, healthy: bool, reason: str, continuous: bool,
    stop_requested: bool, paused: bool, fatal: bool,
) -> bool:
    """Keep the global scheduler alive across recoverable role handoffs.

    A round can include a verifier failure from one yielded Goal and then end at a
    role-switch boundary. The failure stays visible in the run summary, but it must
    not cancel the next fresh observation that lets the other role continue.
    A confirmed switch and an externally changed role also require a new cycle so
    the scheduler can identify the active role and rebuild its live state.
    """
    return not auto_halt_reason(
        healthy=healthy, reason=reason, continuous=continuous,
        stop_requested=stop_requested, paused=paused, fatal=fatal,
    )


ROLE_SWITCH_RETRY_DELAY_MS = 15_000

# The runtime re-observes the same role inside its own run when the Scheduler finds no
# candidate for it (TASK THROUGHPUT V1 §10).  This reason only reaches the panel after that
# in-process bound is exhausted.  See ``next_cycle_delay``.
ROLE_REOBSERVE_REASON = "ACTIVE_ROLE_NO_CANDIDATE_REOBSERVE"


class CycleDelay(NamedTuple):
    """How long the panel waits before starting the next AUTO round."""

    delay_ms: int
    delay_text: str
    immediate: bool


def activity_bounded_wait_ms(ms: int) -> int:
    """Cap an AUTO-round wait at the next scheduled activity node.

    An unreadable event clock must keep ordinary polling rather than abort the wait, so
    the requested delay is returned unchanged when the clock cannot be read.
    """
    try:
        return int(event_schedule.bounded_poll_delay_seconds(ms / 1000.0, event_schedule.load()) * 1000)
    except Exception:  # noqa: BLE001 -- an unreadable event clock keeps ordinary polling
        return ms


def next_cycle_delay(
    *, reason: str, summary: Mapping[str, Any], role_handoff: bool,
    retryable_role_switch: bool, bound_ms: Callable[[int], int] | None = None,
) -> CycleDelay:
    """Decide the wait before the next AUTO round.

    Extracted from ``ControlPanel._schedule_next_cycle`` so the ladder can be tested
    without a Tk root.  Four different things used to collapse into one 30-second wait:

        A  this ``run_live.py`` subprocess ended
        B  one repeatable goal finished its current pass
        C  this character has no executable work left
        D  the whole AUTO work cycle is done

    A round that spent its action budget on real actions has, by definition, more of this
    cycle to do, so it continues at once.  A round that failed to resolve a target is the
    "this goal cannot act right now" case: yielding to another goal immediately is what the
    operator asked for, and it is bounded -- the no-progress deferral counts those episodes
    and stands the goal down after three, so this cannot spin.  Everything else keeps the
    existing breather, which is the loop protection: this must not become a tight restart
    loop on an environmental failure.

    ``ACTIVE_ROLE_NO_CANDIDATE_REOBSERVE`` is the newest member of the "continue at once"
    set.  The account is unchanged and the very next observation is exactly what the reason
    asks for, so waiting on it is pure device idle (TASK THROUGHPUT V1 §23/§24).  Measured
    on pin 553d8df (2026-09-30 03:13:19-03:14:37 local; ``runtime_loaded_revision`` in
    ``learning/control_panel/pump.json`` confirms the pin): a round of three successful
    actions ended for this reason and no further round ever started.  The classifier half of
    that outage is fixed in ``runtime_snapshot``; this half removes the residual wait that
    would otherwise remain on an account that has not changed.

    ``bound_ms`` lets the caller cap the wait at the next activity node; it must be a pure
    function of the delay so this decision stays reproducible.
    """
    no_progress_stall = summary["reason"] == "SEMANTIC_TARGET_NOT_VERIFIED"
    spent_its_budget = summary["reason"] == "MAX_ACTIONS_REACHED" and summary["executed"] > 0
    full_queue = summary["reason"] in {"no_idle_march", "reserved_march_for_stamina"}
    global_wait = reason == "GLOBAL_WAIT"
    role_reobserve = reason == ROLE_REOBSERVE_REASON
    immediate = no_progress_stall or spent_its_budget or role_handoff or role_reobserve
    delay_ms = (ROLE_SWITCH_RETRY_DELAY_MS if retryable_role_switch else 0 if immediate else 600000 if full_queue
                else _global_wait_delay_ms(reason) if global_wait else 30000)
    if delay_ms > 0 and bound_ms is not None:
        delay_ms = int(bound_ms(delay_ms))
    delay_text = ("15 秒后重新观察当前角色" if retryable_role_switch else
                  "立即刷新角色" if role_handoff else
                  "立即" if immediate else
                  (f"{max(1, delay_ms // 1000)} 秒后唤醒" if global_wait else
                   "10 分钟" if full_queue else "30 秒"))
    if not immediate and not retryable_role_switch and delay_ms < (600000 if full_queue else 30000):
        delay_text = f"活动节点前 {max(1, delay_ms // 1000)} 秒"
    return CycleDelay(delay_ms=delay_ms, delay_text=delay_text, immediate=immediate)


def human_reason(value: Any) -> str:
    if value is None or value == "":
        return "暂无数据"
    text = str(value)
    if text.startswith("ROLE_SWITCHED_TO:"):
        return f"已切换到角色 {text.partition(':')[2]}，正在刷新状态"
    if text.startswith("ROLE_IDENTITY_CHANGED:"):
        return f"检测到角色 {text.partition(':')[2]} 已变化，正在重新识别"
    if text == "ROLE_IDENTITY_UNCONFIRMED":
        return "暂时无法确认当前角色，已停止输入并等待重新识别"
    if text.startswith("ROLE_SWITCH_FAILED:"):
        _, _, detail = text.partition(":")
        target, _, reason = detail.partition(":")
        return f"切换到角色 {target} 暂未成功，已停止旧页面操作并按退避时间重试：{human_reason(reason)}"
    return REASON_ZH.get(text, text.replace("_", " "))


LIVE_PANEL_TASKS = frozenset({"采集", "野怪", "Intel", "邮件", "探险", "日常", "联盟", "训练"})

#: The category switches the panel exposes.  One tuple, read by both the startup load and the
#: save, so a category can never be written without also being read back.
POLICY_CATEGORIES: tuple[str, ...] = (
    "日常低保", "持续发展", "联盟协作", "限时活动", "PVE", "实时活动", "资源优化", "自动学习",
)


# ``event_goal_is_current(item)`` used to live here: a second, contradicting rule for the same
# fact the activity record's audit already answers.  It read ``item["updated_at"]`` -- a key the
# record does not carry (``learning/event_goal_state.json`` writes ``verified_at``) -- so it
# returned False for every input, and its only test asserted that False, which is exactly why it
# survived.  The one rule is ``state_truth.legacy_event_row_for``: it reads ``verified_at``,
# compares the recorded countdown against the clock, and *carries the verdict on the row* so no
# reader re-derives it.  Removed 2026-10-04 with the R4 sweep; a page that keeps a private
# freshness rule is how two pages come to disagree about the same file.
GATHER_RUNTIME_PAGES = frozenset({
    Page.HOME,
    Page.MAP,
    Page.RESOURCE_DETAIL,
    Page.BEAST,
    Page.MARCH,
    Page.POPUP,
})


def bootstrap_recovery_action(world: WorldState, unknown_streak: int) -> str:
    """Choose a bounded, non-guessing recovery before the Gather live loop.

    A first UNKNOWN frame is commonly a launch/transition frame, so observe it
    once more without touching the client. Known pages outside the Gather
    route, and persistent UNKNOWN frames, may be backed out safely.
    """
    if world.page in GATHER_RUNTIME_PAGES:
        return "READY"
    if not world.known and unknown_streak <= 1:
        return "WAIT"
    return "BACK"


def task_toggle_label(name: str, enabled: bool, available: bool = True) -> str:
    """Unambiguous user-facing task state; never use a cross for enabled."""
    if not available:
        return f"◇ {name} · 待接入"
    return f"✓ {name} · 已启用" if enabled else f"○ {name} · 未启用"


def policy_toggle_label(name: str, enabled: bool, *, editable: bool = True) -> str:
    """The same vocabulary for the strategy switches (operator P1, 2026-09-18).

    The page rendered each policy as a bare ``Checkbutton``, and the indicator read as a
    ✕ to the operator -- a glyph reserved for 关闭/取消/失败/拒绝, never for "enabled".
    The marker is now written into the label, and a rule that cannot be edited says so
    instead of looking like a switch the operator may operate.
    """
    if not editable:
        return f"🔒 {name} · 永久禁止（安全规则，不可修改）"
    return f"✓ {name} · 已启用" if enabled else f"○ {name} · 未启用"


def load_task_selection(path: Path, names: tuple[str, ...]) -> dict[str, bool]:
    defaults = {name: name == "采集" for name in names}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults
    saved = payload.get("task_enabled", {}) if isinstance(payload, dict) else {}
    if not isinstance(saved, dict):
        return defaults
    return {
        name: bool(saved.get(name, defaults[name])) if name in LIVE_PANEL_TASKS else False
        for name in names
    }


def load_continuous_selection(path: Path) -> bool:
    """AUTO_EXECUTION defaults to unattended repeat unless explicitly disabled."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    return bool(payload.get("continuous", True)) if isinstance(payload, dict) else True


def save_task_selection(path: Path, values: dict[str, bool], continuous: bool | None = None) -> None:
    if continuous is None:
        continuous = load_continuous_selection(path)
    write_panel_state(
        path,
        task_enabled={
            name: bool(enabled) for name, enabled in values.items() if name in LIVE_PANEL_TASKS
        },
        continuous=bool(continuous),
    )


# What the operator last asked for.  This is the one piece of operator intent the
# window must own, because it has to outlive the process: without it, closing and
# reopening the GUI re-read `auto_execution` from the config and started AUTO
# again over the operator's stop -- the loop the operator named as unacceptable
# (点停止 → 刷新/GUI 重启 → 又自动开起来).  Only the explicit 开始 button clears it.
OPERATOR_INTENTS = ("RUNNING", "PAUSED", "STOPPED")


def read_panel_state(path: Path) -> dict:
    """The panel state file, or ``{}``.  A broken file is not a state."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_panel_state(path: Path, **changes: object) -> dict:
    """Merge-and-write, so two writers cannot erase each other's field.

    The operator's intent and the task selection are written from different
    controls; a writer that rewrote the whole file would silently drop the other.
    """
    payload = read_panel_state(path)
    payload.update(changes)
    payload["schema_version"] = "1.2"
    payload["updated_at"] = datetime.now().astimezone().isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def load_operator_intent(path: Path) -> str:
    """``RUNNING`` unless the operator explicitly stopped or paused."""
    value = str(read_panel_state(path).get("operator_intent") or "RUNNING").upper()
    return value if value in OPERATOR_INTENTS else "RUNNING"


def save_operator_intent(path: Path, intent: str, reason: str = "") -> str:
    wanted = str(intent).upper()
    if wanted not in OPERATOR_INTENTS:
        raise ValueError(f"unknown operator intent {intent!r}")
    write_panel_state(path, operator_intent=wanted,
                      operator_intent_at=datetime.now().astimezone().isoformat(),
                      operator_intent_reason=reason)
    return wanted


# The operator's policy file is the second place an operator decision has to outlive the
# process, and it carried the defect described just above in a worse form -- on both halves.
# ``_save_policy_state`` rebuilt the payload from scratch, so it dropped every key it did not
# know about, and nothing ever read the saved categories back: ``__init__`` built all eight
# toggles as ``True`` and then immediately overwrote the file.  Measured 2026-09-30 at
# 09:46:02, seconds after the panel started, ``config/policy_state.json`` was rewritten with
# every category forced on.  A policy that resets itself to permissive on each restart is not
# a policy, and directive FISHING TOURNAMENT — NORMAL BAIT MAX SCORE POLICY V2 §4 (2026-09-30)
# puts a *standing prohibition* in this file (``disabled_goals``) that no panel save may erase.


def read_policy_state(path: Path) -> dict:
    """The operator policy file, or ``{}``.  A broken file is not a policy."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_policy_state(path: Path, **changes: object) -> dict:
    """Merge-and-write, for the same reason ``write_panel_state`` is one.

    ``disabled_goals`` is written by the operator and read by the runtime; a panel save that
    rewrote the whole file would silently re-arm special-mode fishing, which is exactly the
    outcome §4 forbids.
    """
    payload = read_policy_state(path)
    payload.update(changes)
    payload.setdefault("schema_version", "1.0")
    payload["updated_at"] = datetime.now().astimezone().isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return payload


def load_policy_categories(path: Path, names: tuple[str, ...]) -> dict[str, bool]:
    """The saved category switches; an unreadable file keeps every category enabled."""
    saved = read_policy_state(path).get("goal_categories")
    if not isinstance(saved, dict):
        return {name: True for name in names}
    return {name: bool(saved.get(name, True)) for name in names}


# ``count_knowledge()`` lived here until 2026-10-04.  Its only caller was ``_knowledge`` --
# the 知识 page, which is never built -- so it was removed rather than kept "in case".  Note
# what it did, because that is the part worth not repeating: it counted files in three
# directories (one of them 29 days stale) and printed the totals as the state of the
# knowledge base, with no age and no denominator.  A count of records in an unread file is
# not knowledge coverage, and the audit that removed this asked two questions of every
# displayed field: who writes it, and who can see how old it is.


# ------------------------------------------------------- architecture status layer
#
# The four layers this panel displays, frozen by the operator on 2026-09-17:
#
#     MAA        = eyes + hands          (UI perception and execution)
#     V2         = gameplay brain        (state, goals, scheduling, verification)
#     WorkBuddy  = development platform  (turns a capability gap into a capability)
#     models     = replaceable compute   (inside WorkBuddy -- never a V2 component)
#
# Everything in this section is a *derivation* from files that already exist: the
# capability catalog, the skill registry, the episode log, the executor backend
# ledger, the runtime snapshot and the escalation ledger.  Nothing here owns
# state, so the window cannot become a second source of truth -- if a number here
# is wrong, the file it came from is where to fix it.  That is why there is no
# new Manager, Registry or Scheduler behind any of it.

# Two different kinds of "we don't know", deliberately spelled differently.  The
# panel used to print "未知 / 待识别" for both, which reads as if V2 had looked and
# failed -- nine times out of ten it had simply never looked.  The operator's
# wording: only a genuine unknown may say 未知.
PENDING = "未读取"
NO_DATA = "暂无数据"
# One mark per health word, shared by the top bar and every panel header.  Six words and
# no more -- a bar with three shades of "fine" is a bar nobody reads.
DOT_GOOD, DOT_WORK, DOT_IDLE = "● 正常", "● 工作中", "● 等待"
DOT_WARN, DOT_BAD, DOT_UNKNOWN = "● 降级", "● 异常", "● 未确认"

DOT_TEXT: dict[str, str] = {
    "good": DOT_GOOD, "work": DOT_WORK, "idle": DOT_IDLE,
    "warn": DOT_WARN, "bad": DOT_BAD, "unknown": DOT_UNKNOWN,
}

# label -> the status value that drives it.  One cell per thing an operator must be able to
# disbelieve at a glance: the top bar answers "is it OK", and the detail belongs one click
# down.  Nine cells since 2026-09-30, and the ninth is the exception that proves the old
# rule -- the frozen four layers said "models = replaceable compute *inside WorkBuddy*,
# never a V2 component", which was true while the only local model belonged to the
# development platform.  The operator's 2026-09-30 directive made one model a *runtime*
# component: UI-Venus-2-9B answers the UNKNOWN-page question, so whether it is up is a
# fact about V2 and it gets a cell.  It is still one word from the same six.
SYSTEM_INDICATORS: tuple[tuple[str, str], ...] = (
    ("V2", "dot_v2"), ("MAA", "dot_maa"), ("MuMu", "dot_mumu"), ("游戏", "dot_game"),
    ("AUTO", "dot_auto"), ("WorkBuddy", "dot_wb"), ("本地模型", "dot_model"),
    ("预载", "dot_boot"), ("时间", "clock"),
)

# The tab labels, and **only** the tabs that exist.  Key = the page's internal name (what
# ``_tab`` and every deep link use); value = the text the operator reads.  This is a
# *display-name* map, not a restructuring: the frames and their content are untouched, so an
# existing link to a page still lands on that page -- only the visible text changed.
#
# Measured 2026-10-04: this map declared twelve names while ``_build`` created seven, so
# five of them -- 任务 / 自动化覆盖 / 知识 / 日志 / 设置 -- labelled nothing at all.  A label
# map that lists a page nobody builds is the same class of defect as a column that is always
# empty, and it is worse for a reader: the five were retired on purpose, so the map was
# advertising work that had already been decided against.  The 运行· prefix is carried by the
# three pages that *are* one activity stream in the operator's head; 总览 / 能力 / 自动开发 /
# 系统 are single answers and read vaguer with a prefix than without one.
# ``tests/test_console_shows_only_what_it_can_fill.py`` derives the tab list from ``_build``
# and asserts this map matches it, so the two cannot drift again.
TAB_GROUP: dict[str, str] = {
    "总览": "总览",
    "策略": "运行·策略",
    "目标": "运行·目标",
    "活动": "运行·活动",
    "能力": "能力",
    "自动开发": "自动开发",
    "系统": "系统",
}
UNKNOWN_NOW = "未知（识别中）"
# One word for "the evidence behind this expired, so it is not today's answer".  Used by the
# activity record's TTL and by every derived figure whose source has stopped being written --
# one word, so the reader learns it once.  (The word is load-bearing: 2026-10-04 the operator
# rejected the earlier approach of printing the stale number with a 历史参考 prefix, on the
# grounds that "前缀不是藏身处".)
REOBSERVE = "待重新观测"
# A stop reason the panel cannot classify while nothing is running.  Distinct from
# UNKNOWN_NOW because nothing is being recognised at that moment -- the honest
# reading is that the reason itself is unclassified, not that a look is in flight.
UNKNOWN_STOP = "未知（原因未分类）"
# How long a freshness table may be reused.  ``_refresh_truth`` runs on the 1500 ms UI tick
# and the table stats 26 files; once every half minute is indistinguishable to the reader and
# 20x cheaper.  Time-boxed rather than permanent because the *content* of this table is an
# age -- a memo that never expires would freeze exactly the number it exists to report.
FRESHNESS_TTL_SECONDS = 30.0

# -- information tiers: what stays, what opens on request, what folds -------------------
#
# The operator's 2026-10-04 directive, *translated* (master rules §28).  He said the console
# showed too much; he did not ask for anything to be removed.  So nothing below is deleted --
# every block still gets built, still gets refreshed, and is one click away.  What changes is
# which of them the eye has to cross to reach the handful of facts that decide whether he acts.
#
# L3 does not mean "unimportant".  It means "does not change what you do next **while it is
# healthy**" -- which is exactly why L3 is the tier that must open itself the moment it is not.
L1, L2, L3 = "L1", "L2", "L3"
#: Open on first paint?  Keyed by tier, not per block, so a block cannot privately choose a
#: different default from the tier the 2026-10-04 audit assigned it.
FOLD_DEFAULT_OPEN: dict[str, bool] = {L1: True, L2: False, L3: False}

#: Folds with **no** rule at all -- neither one that opens them nor one that marks their header --
#: each with the reason it does not need one.
#:
#: Same shape as the activity page's ``OPTIONAL_EVENT_KEYS``, and for the same reason: a folded
#: block that can never say anything about itself is not automatically a defect, but it has to be
#: a decision somebody wrote down rather than an omission nobody noticed.  ``_sync_folds`` is the
#: acting half of this table and a guard test is the checking half -- every registered fold must
#: escalate, annotate, or be named here.
INERT_FOLDS: dict[str, str] = {
    "queues": "七格是游戏自身队列状态的只读投影（``_compact`` 回的是状态词，不是条数），"
              "面板没有任何积压阈值，编一个就是第二个意见。真正有「卡住」判据的"
              "WorkBuddy 队列是上面那一块，它自己有规则。",
    "events": "最近事件是日志摘要：按定义它永远是过去，不会有「异常」这个状态，"
              "浮上来只会挤掉真正需要看的东西。",
    "stats": "本次启动统计是这个窗口自己跑了多少轮，不是系统状态，也没有可比较的阈值。",
    "today": "与运行·目标页同源；「没有目标进展」的告警已经由常驻的进度行承担"
             "（``_progress_line`` 会加 ⚠ 前缀），再浮一次就是同一件事说两遍。",
    "decision": "六行都是**当前决策**的展开（为什么 / 前置 / 判定 / 下一步 / 风险 / 置信度），"
                "而它现在的答案已经在常驻的三行里（当前 Goal / Skill / 状态）；"
                "要报的故障由「需要关注」与干预卡承担。给「风险」编一个严重度解析器"
                "就是第二个意见。",
    # The four added with the 系统 page.  Same rule as above: a block with no rule of its own
    # says here why it has none, so "folded and silent" is never the same thing as "forgotten".
    "sys_decision": "两行是「上一次怎么决定的 / 下一次什么时候醒来」——按定义一行是过去、"
                    "一行是将来，都不是当前状态。这页的 L1 是当前角色，这两行不改变任何决定；"
                    "真出事由看门狗块和「需要关注」承担。",
    "arbitration": "十一行是同一个 Scheduler 的内部记账（两个角色各剩多少、切换指标、"
                   "最近十次选择）。它们只在解释「为什么不动」时有用，而那时看门狗块和"
                   "「需要关注」已经先浮上来了；给「切换质量」编阈值就是第二个意见。",
    "header_evidence": "六行是顶栏几个格的原始依据。顶栏本身在 L1 常驻，这一块只是同一件事"
                       "展开一层——它永远不会比顶栏先出问题。",
    "sys_logs": "日志文本框与四个「打开目录」按钮：要看的时候才看，按定义不会自己变成"
                "一条告警。",
    # The five added with the 能力 and 自动开发 pages.  Same rule: a block with no rule of its own
    # says here why it has none.
    "cap_catalog": "覆盖表是「游戏里有什么、验证到哪一步」的清单。它的异常形态是**单行**"
                   "（某个能力被阻塞），而那一行就在这张表里、行内的 Blocked 列自己写着原因；"
                   "为「有几行是 Blocked」编一个阈值，就把「哪一行」这件唯一有用的事换成了计数。",
    "cap_registry": "Skill 执行注册表回答「谁能把动作做出来」——实现层的问题。操作者要问的"
                    "「这事到底做没做」由上面那张覆盖表和四张卡回答，这一块永远不该抢先。",
    "dev_queue": "队列状态条与条件分桶回答同一个问题（「排了什么、为什么」），而 §六 里"
                 "「积压超阈值浮 L1」的那半**故意没实现**：面板里没有声明过的积压阈值，"
                 "编一个就是第二个意见（同 ``queues`` 的理由）。真正有判据的「卡住」是"
                 "``WORKBUDDY_QUEUE_STUCK``，由 WorkBuddy 块承担。",
    "dev_pump": "消费泵与设备所有权只用来解释「为什么不动」，而它们只在已经卡住的时候有用 ——"
                "真卡住时 ``WORKBUDDY_QUEUE_STUCK`` 与闭环断点已经先浮上来了。",
    "dev_jobs": "Job 历史与模型战绩是两本账：审计**过去**某一轮怎么跑的时候才看，"
                "不决定下一步做什么。",
}


def failure_priority(count: int) -> str:
    """The severity bucket for a failure seen ``count`` times.

    A named function rather than the literal, because two places now need the same judgement:
    the 自动开发 page prints it as a column, and the fold rule opens the block on it.  A second
    copy of ``10`` would be a second opinion about what P0 means -- and the reason §六's
    「失败次数 ≥ 阈值」 row could be implemented *at all* without inventing a number is that this
    bucketing already existed; the threshold is the project's, not the fold's.
    """
    return "P0" if count >= 10 else ("P1" if count >= 3 else "P2")


def run_fold_rule(rule: Callable[[], str] | None) -> str:
    """Evaluate one fold rule, and treat "could not run" as a verdict rather than as silence.

    Deliberately a **module-level function**, not a method and not a ``staticmethod``.  It was a
    ``staticmethod`` for one commit, and a test stub that binds every callable it finds with
    ``MethodType`` then handed it two arguments -- so the guard died inside the harness rather than
    in the panel.  That is a binding-convention dependency in a helper that needs no binding at
    all, and the cure is to own nothing: this touches no ``self``, so nothing can mis-bind it.

    The behaviour matters more than the placement.  A rule that raises must not read as an
    all-clear: the whole point of the badge is that an abnormal block cannot be hidden, and a
    broken verdict is precisely an abnormal block whose state is unknown.
    """
    if rule is None:
        return ""
    try:
        return rule() or ""
    except Exception as exc:  # noqa: BLE001 - see the docstring
        return f"异常判定失败（{type(exc).__name__}）"


class Fold:
    """One collapsible block, plus the two rules that keep it from hiding something.

    ``escalate`` and ``annotate`` are deliberately **two** rules, not one, because §六's exception
    table draws exactly this line and collapsing them was a mistake worth writing down:

    * ``escalate`` -- the block itself must float to L1 and opens with no click.  Reserved for the
      rows that say so: 看门狗 / WorkBuddy / 队列 / 预载 非正常，或队列有活跃 Job。
    * ``annotate`` -- the block's numbers are no longer current, so its header must say so, but
      the block stays folded.  This is the stale-source row, whose "浮上来的内容" is 「那些格子
      显示『待重新观测』，并在『需要关注』里点名」 -- the *cells* and the L1 card, not the block.

    Merging them (v1 of this change did) auto-opens every block whose file went stale, which on
    real data meant two L3 blocks sitting open permanently: ``capability_catalog.json`` is on a
    7-day budget written by development work, not by AUTO, so "stale" is its steady state.  That
    would have made folding pointless for exactly the blocks the operator complained about -- and
    would have taught him that an alarm is background noise, which is the failure mode
    ``source_freshness`` warns about in its own docstring.
    """

    __slots__ = ("key", "title", "level", "outer", "body", "toggle", "badge",
                 "escalate", "annotate", "sources", "expanded", "auto_opened", "user_closed",
                 "last_reason", "_painted")

    def __init__(self, *, key: str, title: str, level: str, outer: Any, body: Any,
                 toggle: Any, badge: Any, escalate: Callable[[], str] | None,
                 annotate: Callable[[], str] | None = None,
                 sources: tuple[str, ...] = ()) -> None:
        self.key, self.title, self.level = key, title, level
        self.outer, self.body, self.toggle, self.badge = outer, body, toggle, badge
        self.escalate, self.annotate = escalate, annotate
        self.sources = tuple(sources)
        self.expanded = bool(FOLD_DEFAULT_OPEN.get(level, False))
        self.auto_opened = False
        self.user_closed = False
        self.last_reason = ""
        self._painted: bool | None = None

    def paint(self) -> None:
        """Make the widgets match ``expanded``.  Cheap to call on every tick: the comparison
        below is why a collapsed block is not re-packed 40 times a minute."""
        if self._painted == self.expanded:
            return
        self._painted = self.expanded
        if self.expanded:
            self.body.pack(fill="x", pady=(8, 0))
            self.toggle.configure(text=f"▾  {self.title}")
        else:
            self.body.pack_forget()
            self.toggle.configure(text=f"▸  {self.title}")


CATALOG_PATH = ROOT / "knowledge/game/capability_catalog.json"
EPISODES_PATH = ROOT / "learning/episodes.jsonl"
# How much of the tail of ``episodes.jsonl`` a UI-tick reader may touch.  An episode
# row averages ~13 KB (it carries screenshot metadata), so 512 KB holds ~39 rows --
# comfortably more than the 30 a tick asks for, and still three orders of magnitude
# less than the 150 MB+ file a full read would pull off disk.
EPISODE_TAIL_BYTES = 512_000
BACKEND_LEDGER_PATH = ROOT / "learning/executor_backend.jsonl"
MODEL_STATS_PATH = ROOT / "learning/workbuddy_model_stats.jsonl"
# The one runtime local model's two ledgers.  The name and the endpoint come from
# ``config/v2.json``; liveness comes from the service's own ``/health``; what it last
# decided comes from these files.  Nothing here owns state.
LOCAL_GUI_LEDGER_PATH = ROOT / "learning/local_gui_model_calls.jsonl"
LOCAL_GUI_PLAN_LEDGER_PATH = ROOT / "learning/local_planner_steps.jsonl"
LOCAL_GUI_CONFIG_PATH = ROOT / "config/v2.json"

MAA_NORMAL, MAA_ADB_FALLBACK, MAA_BROKEN = "● 正常", "● 降级ADB", "● 不可用"
MAA_UNINITIALISED = "● 未初始化"

# How stale the newest MAA execution may be before the cell stops claiming 正常.
# Measured 2026-09-17: the ledger's last 200 rows held 30 steps that asked for MAA and
# all 30 got MAA -- and every one of them was more than an hour old, while the loop kept
# running on ADB-only skills.  A cell that answered from ``preferred_backend`` would have
# said 正常 throughout.  This constant is what makes it say "正常 · 64 分钟无 MAA 执行"
# instead, which is the honest reading of the same evidence.
MAA_FRESH_SECONDS = 900.0

# AUTO is a control-surface verdict, so it is derived from what the panel itself is
# doing (its worker process, its pause flag, its scheduled restart) rather than from
# a status file that a dead worker may have left behind.
AUTO_RUNNING, AUTO_STARTING, AUTO_PAUSED, AUTO_WAITING, AUTO_STOPPED = (
    "● 运行中", "● 启动中", "● 已暂停", "● 等待下一轮", "● 已停止",
)
WORKBUDDY_LABELS = {
    # One label per real state, because collapsing them was a lie the operator caught:
    # until 2026-09-18 a record created but never dispatched (``NEW``) was shown as
    # "● 排队", which says a job is waiting its turn when in fact nothing has been sent
    # anywhere.  NEW means "not submitted yet"; QUEUED means "decided, waiting to be
    # sent"; SUBMITTED means "the gateway issued a job id"; WORKING means a development
    # agent is actually editing the tree.
    "PENDING_SUBMIT": "● 待提交", "IDLE": "● 待命", "QUEUED": "● 排队",
    "SUBMITTED": "● 已提交", "WORKING": "● 开发中",
    "VERIFYING": "● 验证中", "BLOCKED": "● Blocked", "UNAVAILABLE": "● 不可用",
    # §21's word for the rung the operator added: the version exists and is waiting for
    # its own examination.  Distinct from 验证中, which is a verification happening now.
    "VERIFY_PENDING": "● 等待真机验证",
}

# Stop reasons that mean "come back later", not "something is broken".  A runtime
# sitting on one of these is *waiting*, which is a real state the operator asked
# to see by name instead of a blanket unknown.
RUNTIME_WAITING_STOPS = frozenset({
    "no_idle_march", "reserved_march_for_stamina", "training_queue_busy", "research_queue_busy",
    "NOT_REFRESHED", "EVENT_CLOSED", "QUEUE_BUSY", "RALLY_FULL", "DEVICE_BUSY",
    "DEVICE_TEMPORARILY_BUSY", "mail_all_clear", "exploration_income_not_ready",
    "daily_no_claimable_rewards", "alliance_action_not_needed", "intel_not_available",
    "verified_beast_target_not_visible", "WAITING_FOR_NATURAL_STATE",
    # The device belongs to a development validation right now (§2 A).  Waiting, not
    # broken -- and the device row says which of the operator's four states it is in.
    "device_leased_for_development",
    # Nothing anywhere: the run looked at every page it can reach and the scheduler offered
    # nothing on any of them.  It is the end of a *search*, which is a waiting state -- the
    # next cycle re-observes -- and not a failure of the round.  Registered on the day the
    # reason was introduced (2026-09-23) precisely so the panel does not show ● 异常 for a
    # round whose every step verified; ``human_reason`` and ``successful_stops`` above carry
    # the same entry, because all three read this vocabulary and only one of them is the
    # runtime's.
    "every_page_this_run_was_fruitless",
})

CATALOG_META = {
    "observed": ("已读取特性", "capability_catalog.json · 角色可用性或真机尝试已读到"),
    "implemented": ("已实现", "capability_catalog.json · implementation_status=EXISTING"),
    "tried": ("Live Tried", "capability_catalog.json · live_attempts>0"),
    "verified": ("Live Verified", "capability_catalog.json · lifecycle=LIVE_VERIFIED"),
    "stable": ("Stable", "Skill Registry · SkillState.STABLE"),
    "never": ("从未尝试", "capability_catalog.json · MISSING 且 0 次真机"),
    "blocked": ("Blocked", "capability_catalog.json · 带 blocked_reason"),
    "queue": ("WorkBuddy Queue", "workbuddy_escalations.jsonl · 活跃 / 累计"),
}

#: The four 总览 fact cards: (title, value key, source label, the freshness-table key).
#: One declaration read by both the build and the refresh, so a card cannot print a source
#: line that the freshness table does not know about -- and every one of these four figures
#: is derived from a file, which is why each now carries its own file's age.
OVERVIEW_FACTS: tuple[tuple[str, str, str, str], ...] = (
    ("现在为什么不动", "why_idle",
     "learning/runtime_snapshot.json · 决策原因", "learning/runtime_snapshot.json"),
    ("执行器（最近 100 步实测）", "executor_mix",
     "learning/executor_backend.jsonl", "learning/executor_backend.jsonl"),
    ("自动开发 / 能力学习", "bootstrap",
     "learning/knowledge_bootstrap/STATE.json · WorkBuddy 台账",
     "learning/knowledge_bootstrap/STATE.json"),
    ("能力覆盖", "coverage",
     "knowledge/game/capability_catalog.json", "knowledge/game/capability_catalog.json"),
)

#: Which fact card stays and which folds, keyed by the card's **value key**.
#:
#: ``why_idle`` is L1 on its own: it is the answer to 「有没有卡住」, which §六 of the audit
#: listed as L1, and it happens to live in a block whose other three members are L2.  Splitting
#: it out is what lets the other three fold without hiding an L1 fact.
#:
#: This is a second list beside ``OVERVIEW_FACTS``, which is the R3 shape -- two declarations of
#: one fact.  It is allowed here for the same reason ``source_freshness.SOURCES`` is allowed to
#: be a second list beside these labels: a guard test asserts the key sets are *equal*, so the
#: two cannot disagree, rather than merely not having disagreed yet.
OVERVIEW_FACT_TIERS: dict[str, str] = {
    "why_idle": L1,
    "executor_mix": L2,
    "bootstrap": L2,
    "coverage": L2,
}

#: Which file each of the 8 KPI cards derives from, so a card's own source line can carry that
#: file's age -- the gap the audit named (「总览 8 个 KPI 卡 ... 没有任何年龄标注」) and which the
#: previous pass closed only for the four fact cards.  Card key -> freshness-table key.
#:
#: Declared rather than read out of ``CATALOG_META``'s prose, because pulling a path out of that
#: sentence by substring match is the R3 defect wearing a regex, and a guard test asserts the keys
#: here plus ``CATALOG_UNFRESHNESSED`` below cover ``CATALOG_META`` exactly.
CATALOG_FRESHNESS: dict[str, str] = {
    "observed": "knowledge/game/capability_catalog.json",
    "implemented": "knowledge/game/capability_catalog.json",
    "tried": "knowledge/game/capability_catalog.json",
    "verified": "knowledge/game/capability_catalog.json",
    "never": "knowledge/game/capability_catalog.json",
    "blocked": "knowledge/game/capability_catalog.json",
    "queue": "learning/workbuddy_escalations.jsonl",
}

#: The KPI cards with no file to age, and why.  ``stable`` counts ``SkillState.STABLE`` off the
#: registry object the panel already holds, not off a file -- so there is nothing whose age could
#: be stated, and inventing a freshness row for a file nothing writes would be a claim about a
#: missing writer rather than a measurement.
CATALOG_UNFRESHNESSED: dict[str, str] = {
    "stable": "读的是进程内 registry 对象的 SkillState.STABLE，不是文件，没有可报的年龄。",
}

#: The files the KPI fold watches, **derived** from ``CATALOG_FRESHNESS`` above rather than typed
#: a second time -- so the fold cannot watch a different set of files from the ones its cards
#: print the age of.
KPI_FOLD_SOURCES: tuple[str, ...] = tuple(dict.fromkeys(CATALOG_FRESHNESS.values()))

_CACHE_LOCK = threading.Lock()
_CATALOG_CACHE: tuple[float, dict[str, Any]] | None = None
# One entry holds the per-skill tally, the durations, the timestamped outcomes and
# the failure histogram from a single pass.  Keyed by ``(mtime, size, offset, scan)``
# rather than just mtime: the runtime *appends* to this log continuously, so an
# mtime-only key changed on literally every tick and the "cache" re-parsed the whole
# file every 1.5 s.  ``offset`` is the byte position already absorbed, which is what
# makes the next pass incremental instead of a full re-read.
_EPISODE_CACHE: tuple[float, int, int, dict[str, Any]] | None = None
# The first pass over a 150 MB+ log must not happen on the UI thread.  A daemon
# thread streams it once at startup and publishes a growing snapshot, so the
# capability page fills in over the first second or two instead of freezing the
# window.  ``_EPISODE_PARTIAL`` is that in-progress snapshot; after the thread
# finishes, callers use the incremental cache above and this stops being consulted.
_EPISODE_PARTIAL: dict[str, Any] | None = None
_EPISODE_WARM_STARTED = False
_EPISODE_WARM_DONE = False

# The five conditions that may summon a development agent, in Chinese.  They come
# from winter_agent_v2.escalation_queue.AUTO_ESCALATION_CONDITIONS -- the panel
# only translates them, so it cannot drift from what the queue actually accepts.
CONDITION_ZH = {
    "CAPABILITY_MISSING": "能力缺失",
    "UNKNOWN_UI": "未识别界面",
    "UNKNOWN_GAME_MECHANIC": "未知玩法机制",
    "REPEATED_LIVE_FAILURE": "真机反复失败",
    "STUCK_15_MIN": "15 分钟未解决",
    "（不升级）": "不升级（普通状态）",
}

STATE_ZH = {
    # NEW is "created, not dispatched yet": 新建 reads like a form field and hid the
    # fact that nothing had been sent.  The four first states are the operator's own
    # ladder -- 待提交 -> 排队 -> 已提交 -> 开发中 -- and each one is a different fact.
    "NEW": "待提交", "QUEUED": "排队", "SUBMITTED": "已提交", "WORKING": "开发中",
    # The operator's §21 word for the rung between "a developer finished" and "the
    # game proved it": the version exists and is waiting for its own examination.
    "LIVE_VERIFY_PENDING": "等待真机验证",
    # The two rungs the operator added on 2026-09-18 evening (§一/§八), each named for the
    # fact it represents rather than for the step that produced it: the new version is
    # *loaded* (proved by an episode whose revision equals after_version), and the capability
    # has *re-joined* normal play (proved by a production episode, not by the examination).
    "VERSION_ACTIVE": "新版本已加载",
    "REJOINED": "已回到正常Gameplay",
    "DONE": "完成", "FAILED": "失败", "BLOCKED": "Blocked", "COOLDOWN": "冷却",
}


def tail_jsonl(path: Path, limit: int = 60, *, max_bytes: int = 96_000) -> list[dict[str, Any]]:
    """The last ``limit`` JSON objects of a JSONL file, without reading all of it.

    ``learning/executor_backend.jsonl`` is a few hundred KB and growing, and the
    panel polls every 1.5 s, so reading the whole file each time would be pure
    waste.  A partial first line (from seeking into the middle of a record) is
    dropped rather than parsed.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return []
    offset = max(0, size - max_bytes)
    try:
        with path.open("rb") as handle:
            if offset:
                handle.seek(offset)
            blob = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = blob.splitlines()
    if offset and lines:
        lines = lines[1:]
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            out.append(parsed)
    return out


def capability_catalog(root: Path | None = None) -> dict[str, Any]:
    """The capability coverage table, cached until the file changes.

    Read-only and mtime-keyed: the file is regenerated by tooling, and the panel
    must show the new numbers the moment it is.
    """
    global _CATALOG_CACHE
    path = (root / "knowledge/game/capability_catalog.json") if root else CATALOG_PATH
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return {"capabilities": [], "summary": {}}
    with _CACHE_LOCK:
        if _CATALOG_CACHE is not None and _CATALOG_CACHE[0] == stamp:
            return _CATALOG_CACHE[1]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"capabilities": [], "summary": {}}
    if not isinstance(payload, dict):
        payload = {"capabilities": [], "summary": {}}
    with _CACHE_LOCK:
        _CATALOG_CACHE = (stamp, payload)
    return payload


def _new_episode_scan() -> dict[str, Any]:
    """The empty scan accumulator, with every key a caller may read."""
    return {"index": {}, "durations": [], "results": [], "failures": Counter(), "partial": False}


def _absorb_episode_lines(scan: dict[str, Any], lines) -> int:
    """Fold parsed episode rows into ``scan``; returns how many rows were absorbed.

    Shared by the incremental UI-thread pass and the one-off background warm-up, so
    the two cannot drift into disagreeing tallies.
    """
    index: dict[str, dict[str, Any]] = scan["index"]
    failures: Counter = scan["failures"]
    absorbed = 0
    for line in lines:
        if not isinstance(line, dict):
            continue
        absorbed += 1
        skill = str(line.get("skill") or "")
        if skill:
            entry = index.setdefault(skill, {"live": 0, "claims": 0, "verified": 0, "failed": 0, "last": ""})
            if line.get("recorded_at"):
                entry["live"] += 1
                entry["verified"] += int(line.get("verifier_ok") is True)
                entry["failed"] += int(line.get("verifier_ok") is False)
                entry["last"] = str(line.get("recorded_at"))[:19]
            else:
                entry["claims"] += 1
        if isinstance(line.get("duration"), (int, float)):
            scan["durations"].append(float(line["duration"]))
        if line.get("recorded_at"):
            scan["results"].append((str(line["recorded_at"]), line.get("result") == "SUCCESS"))
            if line.get("failure_type"):
                failures[str(line["failure_type"])] += 1
    return absorbed


def _snapshot_scan(scan: dict[str, Any], partial: bool) -> dict[str, Any]:
    """A copy safe for another thread to read while the warm-up keeps going."""
    return {
        "index": {key: dict(value) for key, value in scan["index"].items()},
        "durations": list(scan["durations"]),
        "results": list(scan["results"]),
        "failures": Counter(scan["failures"]),
        "partial": partial,
    }


def _iter_jsonl_stream(path: Path, offset: int = 0):
    """Yield JSON objects from ``offset`` onwards, streaming -- never a whole-file read.

    The old helper did ``path.read_text()``, which pulled the entire (150 MB+)
    episode log into memory to walk it line by line.

    ``offset`` is always a *record boundary* -- it is the file size captured right
    after the previous pass, and the runtime only ever appends whole lines.  So this
    does not skip a leading line: doing so would silently discard exactly the record
    the incremental pass exists to pick up.  If a seek ever did land mid-record the
    fragment simply fails to parse and is skipped below.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            if offset:
                handle.seek(offset)
            for raw in handle:
                raw = raw.strip()
                if not raw.startswith("{"):
                    continue
                try:
                    row = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    yield row
    except OSError:
        return


def _warm_episode_scan(path: Path) -> None:
    """Stream the whole episode log once, off the UI thread, publishing as it goes.

    The capability page needs lifetime tallies, so the first pass really does have to
    cover the file -- but it must not cover it *on the tick*.  This publishes a
    growing snapshot so the page is populated within a second or two, then hands the
    finished accumulator to the incremental cache.
    """
    global _EPISODE_PARTIAL, _EPISODE_WARM_DONE, _EPISODE_CACHE
    scan = _new_episode_scan()
    seen = 0
    try:
        for row in _iter_jsonl_stream(path):
            _absorb_episode_lines(scan, (row,))
            seen += 1
            if seen % 500 == 0:
                with _CACHE_LOCK:
                    _EPISODE_PARTIAL = _snapshot_scan(scan, True)
        try:
            stat = path.stat()
            stamp, size = stat.st_mtime, stat.st_size
        except OSError:
            stamp, size = 0.0, 0
        finished = _snapshot_scan(scan, False)
        with _CACHE_LOCK:
            _EPISODE_CACHE = (stamp, size, size, finished)
            _EPISODE_PARTIAL = finished
            _EPISODE_WARM_DONE = True
    except Exception:  # noqa: BLE001 - a warm-up failure must never kill the panel
        with _CACHE_LOCK:
            _EPISODE_WARM_DONE = True


def episode_scan(root: Path | None = None) -> dict[str, Any]:
    """Everything the panel needs from the episode log, without re-reading it.

    ``episodes.jsonl`` is a production log that passed 150 MB, and the runtime
    *appends to it continuously* -- which is why the old mtime-keyed cache never
    hit: the file changed on every single tick, so every 1.5 s refresh paid a full
    parse.  Measured on this machine: **549 ms per call**, a third of the tick.

    Now:
      * the first pass runs once on a daemon thread (``_warm_episode_scan``) and
        publishes a growing snapshot, so the window never blocks on 150 MB;
      * afterwards each call absorbs only the bytes appended since the last one;
      * if the log is rotated or truncated (size shrinks) the warm-up restarts.

    Same keys, same semantics, same single pass -- only the cost changed.  A scan
    served before the warm-up finishes carries ``partial=True``.
    """
    global _EPISODE_CACHE, _EPISODE_WARM_STARTED, _EPISODE_WARM_DONE, _EPISODE_PARTIAL
    path = (root / "learning/episodes.jsonl") if root else EPISODES_PATH
    try:
        stat = path.stat()
        stamp, size = stat.st_mtime, stat.st_size
    except OSError:
        return _new_episode_scan()

    with _CACHE_LOCK:
        cache = _EPISODE_CACHE
    if cache is not None:
        c_stamp, c_size, c_offset, c_scan = cache
        if c_stamp == stamp and c_size == size:
            return c_scan
        if size > c_size and c_offset <= size:
            # Appended-to: absorb just the new tail.  Bounded, because a long gap
            # between refreshes (or a backgrounded window) could otherwise pull tens
            # of MB onto the UI thread; anything beyond the cap is left for the next
            # tick rather than stalling this one.
            if size - c_offset > EPISODE_TAIL_BYTES:
                _start_episode_warm(path)
                return c_scan
            rows = list(_iter_jsonl_stream(path, c_offset))
            if rows:
                merged = _snapshot_scan(c_scan, False)
                _absorb_episode_lines(merged, rows)
                merged["partial"] = False
            else:
                merged = c_scan
            with _CACHE_LOCK:
                _EPISODE_CACHE = (stamp, size, size, merged)
            return merged
        # Shrunk or replaced (rotation / truncation): the old tally describes a file
        # that no longer exists, so it must be rebuilt rather than extended.
        with _CACHE_LOCK:
            _EPISODE_CACHE = None
            _EPISODE_WARM_DONE = False
            _EPISODE_PARTIAL = None
            _EPISODE_WARM_STARTED = False

    if not _EPISODE_WARM_STARTED:
        _start_episode_warm(path)
    with _CACHE_LOCK:
        partial = _EPISODE_PARTIAL
    if partial is not None:
        return partial
    # Warm-up has not published anything yet: report an honestly-empty scan rather
    # than pretending the log has no episodes.
    empty = _new_episode_scan()
    empty["partial"] = True
    return empty


def _start_episode_warm(path: Path) -> None:
    """Kick off the one-off full pass, at most once per process."""
    global _EPISODE_WARM_STARTED
    with _CACHE_LOCK:
        if _EPISODE_WARM_STARTED:
            return
        _EPISODE_WARM_STARTED = True
    threading.Thread(target=_warm_episode_scan, args=(path,),
                     name="panel-episode-warm", daemon=True).start()


def episode_index(root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Per-skill tally from :func:`episode_scan`."""
    return episode_scan(root)["index"]


def _iter_jsonl(path: Path):
    """Yield each JSON object of a JSONL file, skipping anything unparseable."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            yield row


def live_failure_counts(root: Path | None = None) -> Counter:
    """How often each failure type appeared on a row that carries ``recorded_at``.

    Part of the same cached pass as the per-skill tally, so the panel parses the
    episode log once per change rather than once per question.
    """
    return episode_scan(root)["failures"]


def escalation_buckets(root: Path | None = None) -> dict[str, dict[str, int]]:
    """Distinct failure types and live occurrences per escalation condition.

    Runs ``classify_condition`` -- the same function the AUTO hook calls -- rather
    than re-implementing the rule here.  A panel that decided for itself which
    failures deserve a development agent would be exactly the second state system
    the operator forbids.
    """
    from winter_agent_v2.escalation_queue import (
        CAPABILITY_MISSING, EscalationPolicy, FailureSignature, classify_condition,
    )

    buckets: dict[str, dict[str, int]] = {}
    policy = EscalationPolicy()
    now = datetime.now(timezone.utc)
    for key in (*AUTO_ESCALATION_CONDITIONS, CAPABILITY_MISSING, "（不升级）"):
        buckets[key] = {"types": 0, "episodes": 0}
    for failure_type, occurrences in live_failure_counts(root).items():
        signature = FailureSignature(capability="", failure_type=failure_type, skill="")
        verdict = classify_condition(signature, occurrences=occurrences, first_seen=None, now=now, policy=policy)
        condition = verdict[0] if verdict else "（不升级）"
        entry = buckets.setdefault(condition, {"types": 0, "episodes": 0})
        entry["types"] += 1
        entry["episodes"] += occurrences
    return buckets


def capability_gap_view(root: Path | None = None) -> dict[str, Any]:
    """Goal-level gaps, read from the project's own capability -> skill map.

    This is the second capability table and it is *not* merged with the 522-row
    coverage catalog on purpose: the catalog counts what the game contains, this
    one tracks the 16 goals and which capability blocks each.  Two questions, two
    files, and the panel labels which one it is answering.
    """
    base = Path(root) if root else ROOT
    try:
        payload = json.loads((base / "knowledge/goals/capability_skill_map.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"summary": {}, "goals": (), "highest_leverage": (), "readable": False}
    goals: list[tuple[str, str, int, str]] = []
    for goal in payload.get("goals") or []:
        blocked = [str(c.get("capability")) for c in (goal.get("capabilities") or [])
                   if str(c.get("status") or "").upper() in ("BLOCKED", "DEGRADED")]
        goals.append((str(goal.get("goal")), str(goal.get("status")), len(blocked), "、".join(blocked[:3])))
    return {
        "summary": payload.get("summary") or {},
        "goals": tuple(goals),
        "highest_leverage": tuple(payload.get("highest_leverage") or ()),
        "readable": True,
    }


def backend_axis(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Which of MAA / ADB actually executed the recent steps, and whether that is a fallback.

    The distinction that matters and that a bare backend name hides: several
    skills are *deliberately* still on ADB (they are not migrated yet, and
    ``backend_routing.json`` says so), while a step whose ``preferred_backend``
    was MAA but whose ``used_backend`` is ADB is a real degradation.
    """
    last = rows[-1] if rows else {}
    used = str(last.get("used_backend") or "").upper()
    capture = str(last.get("capture_backend") or "")
    preferred = str(last.get("preferred_backend") or "").upper()
    latency = last.get("latency_ms")
    suffix = f" · {latency:.0f}ms" if isinstance(latency, (int, float)) else ""
    if not last:
        label = PENDING
    elif used == "MAA":
        label = f"MAA · {capture}{suffix}"
    elif preferred == "MAA":
        label = f"ADB 降级 · {capture}{suffix}"
    else:
        label = f"ADB · {capture}（该技能未迁移 MAA）{suffix}"
    mix = Counter(str(row.get("used_backend") or "?") for row in rows)
    maa_rows = [row for row in rows if str(row.get("used_backend") or "").upper() == "MAA"]
    # A MAA_* reason is the adapter saying it could not come up (MAA_IMPORT_FAILED /
    # MAA_CONNECT_FAILED / MAA_SCREENCAP_FAILED).  Note that SEMANTIC_TARGET_NOT_VERIFIED
    # also lands in ``attempts[].error`` and is NOT a backend failure -- it is a
    # recognition miss -- so the prefix test is what keeps the two apart.
    failures = sorted({
        str(attempt.get("error"))
        for row in rows
        for attempt in (row.get("attempts") or [])
        if str(attempt.get("error") or "").startswith("MAA_")
    } | {str(row.get("error")) for row in rows if str(row.get("error") or "").startswith("MAA_")})
    newest_maa = str(maa_rows[-1].get("recorded_at") or "") if maa_rows else ""
    return {
        "label": label, "used": used, "capture": capture, "preferred": preferred,
        "latency_ms": latency, "recorded_at": str(last.get("recorded_at") or ""),
        "degraded": bool(used and used == "ADB" and preferred == "MAA")
        or any(row.get("fallback_used") for row in rows),
        "errors": sum(1 for row in rows if row.get("error")),
        "mix": f"MAA {mix.get('MAA', 0)} / ADB {mix.get('ADB', 0)}（近 {len(rows)} 步）",
        "steps": len(rows),
        "maa_used": mix.get("MAA", 0),
        "maa_failures": tuple(failures),
        "maa_last_at": newest_maa,
    }


def age_seconds(stamp: str, now: datetime | None = None) -> float | None:
    """Seconds since an ISO timestamp, or ``None`` when it cannot be parsed."""
    if not stamp:
        return None
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return ((now or datetime.now(timezone.utc)) - moment).total_seconds()


def _human_age(seconds: float | None) -> str:
    if seconds is None:
        return "时间未知"
    if seconds < 60:
        return f"{seconds:.0f} 秒前"
    if seconds < 3600:
        return f"{seconds / 60:.0f} 分钟前"
    return f"{seconds / 3600:.1f} 小时前"


def maa_cell(report: runtime_env.InterpreterReport, axis: dict[str, Any], *, now: datetime | None = None) -> str:
    """MAA's state, from initialisation evidence and from when it last actually ran.

    Ordered so that a *positive* failure outranks a stale success, and so that silence
    is never rendered as health:

    * no ledger rows at all          -> 未初始化 (nothing has ever executed)
    * the worker interpreter cannot import maa, or cannot run the loop -> 不可用
    * a MAA_* reason recorded        -> 不可用 (the adapter said so itself)
    * MAA was asked for and ADB ran  -> 降级ADB
    * MAA ran recently               -> 正常
    * none of the above              -> 正常, with how long ago it last ran

    The last case is the one this cell was rebuilt for.  On 2026-09-17 the ledger held 30
    MAA-preferred steps that all really used MAA, the newest of them 64 minutes old, while
    the loop kept working through ADB-only skills.  ``preferred_backend`` would have said
    正常 and been wrong about the present; the probe says the capability is intact, and the
    freshness note says the evidence is old.  Both facts, neither invented.
    """
    if not axis.get("steps"):
        return MAA_UNINITIALISED
    missing = tuple(getattr(report, "missing", ()) or ())
    if not getattr(report, "exists", False) or missing or axis.get("maa_failures"):
        return MAA_BROKEN
    if axis.get("degraded"):
        return MAA_ADB_FALLBACK
    seconds = age_seconds(str(axis.get("maa_last_at") or ""), now)
    if seconds is not None and seconds <= MAA_FRESH_SECONDS:
        return f"{MAA_NORMAL} · {_human_age(seconds)}执行"
    if seconds is None:
        return MAA_NORMAL
    return f"{MAA_NORMAL} · {_human_age(seconds)}无 MAA 执行"


def maa_note(report: runtime_env.InterpreterReport, axis: dict[str, Any]) -> str:
    """The evidence behind :func:`maa_cell`, for the system tab and for the log."""
    if not axis.get("steps"):
        return "未初始化：执行台账里没有任何一步，MAA 尚未被真正调用过"
    if not getattr(report, "exists", False):
        return f"不可用：生产解释器不存在（{report.python_exe}）"
    if getattr(report, "missing", ()):
        return "不可用：解释器缺少 " + "、".join(report.missing)
    if axis.get("maa_failures"):
        return "不可用：台账记录了 " + "、".join(axis["maa_failures"])
    if axis.get("degraded"):
        return "降级ADB：有步骤请求了 MAA 但由 ADB 执行（fallback_used / preferred=MAA, used=ADB）"
    seconds = age_seconds(str(axis.get("maa_last_at") or ""))
    if seconds is None:
        return f"正常：解释器可导入 maa，但近 {axis.get('steps', 0)} 步里没有 MAA 执行记录"
    return (f"正常：解释器可导入 maa；最近一次 MAA 执行在 {_human_age(seconds)}"
            f"（{axis.get('mix', '')}）")


def auto_cell(*, starting: bool, worker_alive: bool, paused: bool, stop_requested: bool,
              restart_scheduled: bool) -> str:
    """What AUTO is doing, from the panel's own control state.

    A status *file* is the wrong source here: a worker that died between cycles leaves
    ``agent_state=AUTO_RUNNING`` behind, so a GUI reading that file would show a running
    loop with no process behind it.  These inputs are the ones the buttons actually
    change, which is also why this function is the one the button tests drive.
    """
    if stop_requested:
        return AUTO_STOPPED
    if paused:
        return AUTO_PAUSED
    if starting:
        return AUTO_STARTING
    if worker_alive:
        return AUTO_RUNNING
    if restart_scheduled:
        return AUTO_WAITING
    return AUTO_STOPPED


def device_cells(state: dict[str, Any], expected_package: str) -> tuple[str, str]:
    """``(MuMu, 游戏)`` from a real device probe -- never from configuration.

    ``state`` is the probe's record, so that "the probe has not run yet" and "the probe
    ran and the device was not there" are different answers.  They were the same answer
    until this was measured: a failed ``ADBDevice.status()`` stored ``status=None`` and
    the cell rendered 未探测, which would have shown 未探测 forever on an unplugged
    emulator -- silence dressed up as "no data yet" when it was in fact a disconnection.
    """
    probed = state.get("ok")
    if probed is None:
        return "未探测", PENDING
    if probed is False:
        reason = str(state.get("error") or "").strip()
        return ("● 未连接" + (f"（{reason}）" if reason else ""), PENDING)
    status = state.get("status")
    if status is None:
        return "● 未连接（探测未返回状态）", PENDING
    if not getattr(status, "connected", False):
        # ADBDevice.status() only ever returns connected=True, so this is a guard for a
        # future probe rather than a live path -- but a status that says "not connected"
        # must not be rendered as 已连接 on the strength of its other fields.
        return "● 未连接", PENDING
    serial = str(getattr(status, "serial", "") or "")
    resolution = getattr(status, "resolution", None)
    size = f" {resolution[0]}x{resolution[1]}" if resolution else ""
    foreground = str(getattr(status, "foreground_package", "") or "")
    if not foreground:
        return f"● 已连接 {serial}{size}", PENDING
    return (f"● 已连接 {serial}{size}",
            "运行中" if foreground == expected_package else f"未在前台（{foreground}）")


def _records_sorted(snapshot: Any) -> list[Any]:
    records = list(getattr(snapshot, "records", {}).values())
    return sorted(records, key=lambda r: (r.last_seen or r.first_seen or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)


def escalation_view(root: Path | None = None) -> dict[str, Any]:
    """The development escalation queue, folded from its own ledger.

    Uses ``winter_agent_v2.escalation_queue.fold`` rather than re-deriving states
    here: the queue already knows what SUBMITTED means, and a panel that
    recomputed it would be the second source of truth the operator forbids.
    """
    from winter_agent_v2.escalation_queue import (
        BLOCKED, CODE_CHANGED, COOLDOWN, DONE, FAILED, LIVE_VERIFIED, LIVE_VERIFY_PENDING,
        NEW, OUTCOME_BLOCKED, QUEUED, REPLAY_PASS, SUBMITTED, TEST_PASS, WORKING,
        EscalationPolicy,
    )

    path = (root / DEFAULT_LEDGER) if root else _ESCALATION_LEDGER_PATH
    try:
        snapshot = EscalationLedger(path).snapshot()
    except Exception:  # noqa: BLE001 - an unreadable ledger shows as empty, never crashes the window
        return {"total": 0, "records": (), "current": None, "counts": {}, "conditions": Counter(),
                "pending_verify": (), "blocked": (), "verified": (), "max_concurrent": 1, "readable": False}
    records = _records_sorted(snapshot)
    # §7: one selector, shared with the closed-loop card.  This used to be ``active[0]`` with a
    # separate fallback to the first awaiting record, while the card chose its own -- and the
    # two named different capabilities side by side, both calling themselves current.
    from winter_agent_v2.escalation_queue import current_development_trace

    current_record = current_development_trace(snapshot)
    active = [r for r in records if r.state in (NEW, QUEUED, SUBMITTED, WORKING)]
    # A version that exists and has not been examined yet.  It is neither active (no
    # agent is working, so it does not hold the agent slot) nor finished, and leaving it
    # out of every list is how it became invisible in the window on 2026-09-18.
    awaiting = [r for r in records if r.state == LIVE_VERIFY_PENDING]
    pending_verify = [r for r in records if r.state == DONE and r.outcome in (CODE_CHANGED, TEST_PASS, REPLAY_PASS)]
    blocked = [r for r in records if r.state in (BLOCKED, FAILED, COOLDOWN) or r.outcome == OUTCOME_BLOCKED]
    conditions: Counter[str] = Counter()
    for record in records:
        for condition in [record.condition] if record.condition else []:
            conditions[condition] += 1
    return {
        "total": len(records), "records": tuple(records), "current": current_record,
        "active": tuple(active), "counts": snapshot.count_by_state(), "conditions": conditions,
        "awaiting_verification": tuple(awaiting),
        "pending_verify": tuple(pending_verify), "blocked": tuple(blocked),
        "verified": tuple(r for r in records if r.outcome == LIVE_VERIFIED),
        "max_concurrent": EscalationPolicy().max_concurrent_jobs, "readable": True,
    }


def workbuddy_cell(view: dict[str, Any], gateway: dict[str, Any]) -> tuple[str, str]:
    """``(状态, 说明)`` for the header cell -- WorkBuddy's own state, never a model name.

    Order matters.  A job that is running outranks one waiting for its live
    verification, which outranks a blocked one, which outranks idle.
    """
    from winter_agent_v2.escalation_queue import NEW, QUEUED, SUBMITTED, WORKING

    if gateway.get("available") is False:
        return WORKBUDDY_LABELS["UNAVAILABLE"], str(gateway.get("reason") or "")
    current = view.get("current")
    if current is not None:
        if current.state in (SUBMITTED, WORKING):
            label = (
                WORKBUDDY_LABELS["SUBMITTED"] if current.state == SUBMITTED
                else WORKBUDDY_LABELS["WORKING"]
            )
            return label, current.job_id or current.key
        if current.state == NEW:
            return WORKBUDDY_LABELS["PENDING_SUBMIT"], current.key
        if current.state == QUEUED:
            return WORKBUDDY_LABELS["QUEUED"], current.key
    if view.get("awaiting_verification"):
        record = view["awaiting_verification"][0]
        return WORKBUDDY_LABELS["VERIFY_PENDING"], record.capability or record.key
    if view.get("pending_verify"):
        return WORKBUDDY_LABELS["VERIFYING"], view["pending_verify"][0].key
    if view.get("blocked"):
        return WORKBUDDY_LABELS["BLOCKED"], view["blocked"][0].key
    return WORKBUDDY_LABELS["IDLE"], ""


GATEWAY_REASON_ZH = {
    "NO_CREDENTIAL": "未配置凭据（需在环境变量里设置网关密码，禁止写入仓库）",
    "AUTH_REJECTED": "凭据被拒绝（环境里的密码与正在运行的网关不一致）",
    "GATEWAY_UNREACHABLE": "网关不可达（未启动或端口不同）",
}


GATEWAY_STALE_SECONDS = 20.0


def workbuddy_header(gateway: dict[str, Any], *, now: datetime | None = None) -> str:
    """The header word for WorkBuddy: the **gateway's** health, never the job's state.

    Operator P0-3, 2026-09-18: the cell said ``● 正常`` while the development page said
    ``GatewayUnavailable /api/v1/jobs/... timed out after 15s``.  A job whose last known
    state is WORKING is a fact about the past that the *gateway* would be the thing to
    update -- so it cannot be evidence that anything is reachable.  Two facts, two cells.
    """
    age = age_seconds(str(gateway.get("checked_at_utc") or ""), now)
    if age is not None and age > GATEWAY_STALE_SECONDS:
        return "● 未确认"
    if gateway.get("available") is True:
        return "● 正常"
    if gateway.get("available") is False:
        return "● 异常"
    return "● 未确认"


def gateway_cell(gateway: dict[str, Any], *, now: datetime | None = None,
                 job_label: str = "", auto_line: str = "") -> str:
    """The gateway line: what it is, since when, and what that does *not* mean.

    "网关正常" from a four-minute-old poll is a claim about the past, and a disconnect has
    to show up when it happens -- so a reading older than three poll intervals says so
    instead of presenting itself as current.

    When it is not answering, the operator asked for the whole picture in one place
    (P0 §十一): the cause, the last time it did answer, the job's **last known** state (not
    a re-reading -- the gateway is the thing that would report it), that AUTO is
    unaffected, and when the next attempt is due.  Every clause comes from a measurement;
    none of them is inferred from the other.
    """
    checked = str(gateway.get("checked_at") or "")
    age = age_seconds(str(gateway.get("checked_at_utc") or ""), now)
    if age is not None and age > GATEWAY_STALE_SECONDS:
        return f"网关状态待测（最近检查 {checked or '—'}，{_human_age(age)}）"
    if gateway.get("available") is True:
        return f"网关正常 · 检查于 {checked or '—'}"
    if gateway.get("available") is None and not checked:
        # Never probed: there is no cause to name and no last success to age.  Saying
        # "last success: none" about a probe that never ran is noise dressed as knowledge.
        return "网关状态待测"
    if gateway.get("available") is not True:
        parts = [f"网关{'不可用' if gateway.get('available') is False else '状态待测'}"
                 f" · {gateway_reason_cn(gateway.get('reason'))}"]
        failures = int(gateway.get("consecutive_failures") or 0)
        backoff = float(gateway.get("backoff_seconds") or 0)
        if failures:
            parts.append(f"连续 {failures} 次失败")
        if backoff:
            parts.append(f"下一次探测 {int(backoff)} 秒后")
        last_ok = str(gateway.get("last_ok_at") or "")
        ok_age = age_seconds(last_ok, now)
        parts.append(f"最后成功 {_human_age(ok_age) if ok_age is not None else '无记录'}")
        if job_label:
            parts.append(f"当前 Job（上次已知）{job_label}")
        if auto_line:
            parts.append(f"AUTO {auto_line}")
        return " · ".join(parts)
    return "网关状态待测"


#: Set by ``Start-Winter-Agent-V2.cmd`` before it starts the window.  An explicit marker
#: beats an inference: §三 requires the acceptance to be run by *the production GUI*, and
#: the window has to be able to say which launch path it came from.
LAUNCH_PATH_ENV = "WINTER_AGENT_LAUNCH_PATH"


def launch_context() -> tuple[str, str]:
    """``("production" | "development", why)`` -- which launch path this window came from.

    Measured 2026-09-18: a panel started by a development tool's interpreter ran the product
    correctly but could not be kept alive, because that host reaps its children when the call
    ends (panels 24936/25408 and every gateway they started, all dead with the call).  §三
    and §九 are explicit that this is a limitation of the *tooling that builds* the product,
    not of the product, and that the fix is to move the acceptance into the real launch path
    rather than to grow detach or WMI workarounds inside the product.

    So the window answers the question honestly, twice over: the marker its launcher set, or
    -- for a window started by hand -- the fact that it is the production interpreter's
    sibling (the launcher runs ``pythonw.exe`` beside the proven ``python.exe``).  A window
    that came from anywhere else says so, and its soak is marked as not being evidence.
    """
    marker = str(os.environ.get(LAUNCH_PATH_ENV) or "").strip().lower()
    if marker == "desktop":
        return "production", f"{LAUNCH_PATH_ENV}=desktop（正式桌面入口）"
    try:
        exe = Path(sys.executable).resolve()
        production = Path(runtime_python_path()).resolve()
        if exe.parent == production.parent:
            return "production", f"运行解释器是生产解释器同目录的 {exe.name}"
        return "development", f"运行解释器 {exe} 不在生产解释器目录 {production.parent} 内"
    except Exception as exc:  # noqa: BLE001
        return "unknown", f"无法判定启动路径：{type(exc).__name__}: {exc}"


#: The card is derived from the ledger, the episodes and ``git log``, and the window
#: refreshes every few seconds -- but the project's rule is that the GUI refresh path does
#: not run CLIs, and the answer moves on the scale of a job, not of a repaint.  So it is
#: computed once a minute.  What changed on 2026-10-04 is *where*: see
#: :class:`ClosureCardProbe`.
CLOSURE_INTERVAL = 60.0
#: A card that *failed* to compute is retried at this cadence instead of waiting the full
#: interval.  The usual failure is transient -- the escalation ledger rewritten under the
#: reader, or ``git`` briefly unavailable -- and a stale card plus up to a minute of silence is
#: exactly the lag :class:`ClosureCardProbe` exists to remove.  A card that is merely *empty*
#: ("no upgrade carries a job id yet") is a real answer, not a failure, and keeps the full
#: interval so the idle case is not read six times as often for no new information.
CLOSURE_RETRY_SECONDS = 10.0
#: How much of the tail of ``episodes.jsonl`` the closure card may read.  The log passed
#: 158 MB; a full ``read_text`` of it measured 549 ms and was the single hottest frame in
#: a py-spy dump of the live panel.  The card joins a trace to *its own* episode, and the
#: trace it shows is the newest one, so the rows it can possibly need are at the tail.
CLOSURE_EPISODE_BYTES = 32_000_000
CLOSURE_EPISODE_LIMIT = 5_000
#: What the window shows until the first card lands.  ``pending`` is what tells the renderer
#: this is "still counting" rather than "nothing has happened" -- the two must not look alike,
#: and the previous design could only ever show the second one honestly.
CLOSURE_WARMING: dict[str, Any] = {
    "ok": False,
    "pending": True,
    "reason": "闭环卡片正在后台计算（首次约数秒，之后每分钟一次）",
}


class ClosureCardProbe:
    """Keeps the closure card computed and published, off the UI thread.

    Division of labour, the operator's rule of 2026-10-04: the main thread does UI, scheduling
    and dispatch; I/O belongs on a background thread.  This card is I/O by that rule -- it reads
    ``learning/workbuddy_escalations.jsonl`` (7.5 MB), a 32 MB tail of ``learning/episodes.jsonl``
    and runs ``git log`` through :func:`unattended_closure.heads` -- and by measurement it cost
    **3104 ms cold on the thread that draws the window**, once a minute.  The operator reported
    that as lag, and a 3 s freeze is not something a TTL can excuse: the previous cache knew the
    answer was fresh and still recomputed it on the UI thread.

    This class only *computes and publishes*.  Nothing here touches Tk, the process or the
    device.  ``closure_card`` is the consumer and reads a published snapshot; ``refresh_once``
    is exposed so a test can compute one card synchronously instead of waiting for the thread.

    Measured 2026-10-04, before and after moving the chain selection to
    :func:`unattended_closure.ordered_keys`:

        closure_card cold              3104 ms   ->  ~700 ms
          of which closure.build x 195 2602 ms   ->  ~13 ms (one chain, not 195)
          tail_jsonl(32 MB)             396 ms   ->   396 ms (unchanged, now off-thread)
          EscalationLedger.events()     168 ms   ->   168 ms
          current_development_trace     111 ms   ->   111 ms
    """

    def __init__(self, root: Path | str, *, interval: float = CLOSURE_INTERVAL) -> None:
        self.root = Path(root)
        self.interval = max(5.0, float(interval))
        self._lock = threading.Lock()
        self._card: dict[str, Any] | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Begin publishing cards.  Idempotent, and it never blocks the caller."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="closure-card-probe", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Ask the thread to finish.  Daemon, so a missed call cannot keep the process up."""
        self._stop.set()

    def latest(self) -> dict[str, Any] | None:
        """The most recent card, or ``None`` before the first one lands.  No I/O."""
        with self._lock:
            return self._card

    def refresh_once(self) -> dict[str, Any]:
        """Compute one card, publish it and return it.  Never raises."""
        card = closure_card_now(self.root)
        with self._lock:
            self._card = card
        return card

    def _loop(self) -> None:
        """Publish a card, then wait -- sooner if the card is a failure rather than an answer.

        ``refresh_once`` never raises: it returns a failure as ``ok: False``, so the delay is
        decided from the returned card, not from an exception.  Only a card marked
        ``transient`` (an exception was caught while building it) shortens the wait; an empty
        ledger keeps the full interval.
        """
        while True:
            card = self.refresh_once()
            delay = CLOSURE_RETRY_SECONDS if card.get("transient") else self.interval
            if self._stop.wait(delay):
                return


_CLOSURE_PROBES: dict[str, ClosureCardProbe] = {}
_CLOSURE_PROBES_LOCK = threading.Lock()


def closure_probe(root: Path | None = None) -> ClosureCardProbe:
    """The one probe for ``root``, created on first use.

    One per root rather than one per caller: two probes would compute the same card twice, and
    the panel's page and its narration both ask for it.
    """
    target = Path(root or ROOT)
    key = str(target.resolve())
    with _CLOSURE_PROBES_LOCK:
        probe = _CLOSURE_PROBES.get(key)
        if probe is None:
            probe = ClosureCardProbe(target)
            _CLOSURE_PROBES[key] = probe
        return probe


def closure_card(root: Path | None = None) -> dict[str, Any]:
    """The unattended chain as last published.  Never computes, never blocks.

    §八 asks the window to show the eight steps with the current ``trace_id`` and the current
    breakpoint.  All of it already exists: ``tools/unattended_closure.py`` joins the ledger,
    the episodes and the commits by ``trace_id`` and reports ``failure_step``.  Re-implementing
    that join in the GUI would be a second answer to one question, and the two would drift.

    The chain chosen is the one that tool would call the newest -- decided by
    :func:`unattended_closure.ordered_keys`, which is the same ranking that tool applies, done
    without building the chains that lose -- so the window and the command line cannot disagree
    about which chain is current.

    Call this from the UI thread.  It starts the publisher on first use (idempotent) and then
    reads whatever is published; until the first card lands it returns :data:`CLOSURE_WARMING`,
    which says so rather than rendering as "the loop has not started".
    """
    probe = closure_probe(root)
    probe.start()
    card = probe.latest()
    if card is None:
        return dict(CLOSURE_WARMING)
    return dict(card)


def closure_card_now(root: Path | None = None) -> dict[str, Any]:
    """Compute the card on *this* thread and return it.

    For the CLI, for tests, and for :class:`ClosureCardProbe`.  The window must go through
    :func:`closure_card` instead -- calling this from a repaint is the 3 s freeze this pair
    exists to remove.
    """
    try:
        tools_dir = str(Path(__file__).resolve().parent)
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        import unattended_closure as closure

        ledger_path = Path(_ESCALATION_LEDGER_PATH)
        ledger = closure.rows(closure.LEDGER)
        episodes = tail_jsonl(closure.EPISODES, limit=CLOSURE_EPISODE_LIMIT,
                              max_bytes=CLOSURE_EPISODE_BYTES)
        commits = [(line.split(" ", 1)[0], closure.moment(line.split(" ", 1)[1]))
                   for line in closure.heads()]
        commits = [(sha, when) for sha, when in commits if when is not None]

        # §7: the trace this card shows is the one the *panel* shows -- chosen by the one
        # selector both of them now share, not by "newest with a job id".  When nothing is open,
        # the newest chain is still built so the page has history to show, but it is labelled as
        # such rather than presented as the present.
        current = current_development_trace(fold(ledger))
        current_key = str(current.key) if current is not None else ""

        # One chain is read, so one chain is built.  This used to build every key's chain and
        # keep the first after sorting: measured 2026-10-04, 195 chains cost 2602 ms of a
        # 3104 ms card, and the 127 that had a job id were all discarded.  ``ordered_keys`` is
        # that same filter-and-sort, on the two fields it needs, so the winner can be built
        # alone.  A key that has no chain (no submission row, so no job) is dropped there
        # exactly as ``if not chain.job_id`` dropped it here.
        ordered = closure.ordered_keys(ledger, current_key=current_key)

        card: dict[str, Any]
        if not ordered:
            card = {"ok": False,
                    "reason": "台账中没有带 Job 的升级记录，闭环尚未开始"}
        else:
            by_key, by_capability = closure.group_ledger(ledger)
            chain = closure.build(ordered[0], ledger, episodes, commits,
                                  by_key=by_key, by_capability=by_capability)
            # The record's own lifecycle state, so §十一's "Version must read the real
            # ledger" is satisfied: VERSION_ACTIVATION_PENDING and VERSION_ACTIVE are states
            # in the ledger, and the card shows which one it is rather than inferring a
            # version step from ``git HEAD`` -- which only describes the disk, not what ran.
            state = ""
            outcome = ""
            before_version = after_version = active_version = ""
            activation_episode_id = live_try_episode_id = live_verify_episode_id = ""
            reuse_episode_id = ""
            try:
                snapshot = fold(EscalationLedger(ledger_path).events())
                record = snapshot.get(chain.trace_id)
                if record is None:
                    # ``build`` falls back to matching by capability when no ledger row
                    # carries the key (a bridge-only submission does not), so the card has to
                    # make the same fallback or it would show an empty version cell for a
                    # record that does exist.
                    record = next(
                        (r for r in snapshot.records.values()
                         if r.capability and r.capability == chain.capability),
                        None,
                    )
                if record is not None:
                    state = str(record.state or "")
                    outcome = str(record.outcome or "")
                    before_version = str(record.before_version or "")
                    after_version = str(record.after_version or "")
                    active_version = str(record.active_version or "")
                    # The three episode ids the operator's §8 requires the cells to be graded on.
                    # Read from the record, never inferred from the chain tool's own steps:
                    # ``auto_resumed``/``post_resume_verified`` describe the *reload* mechanism,
                    # and using them for 生产复用 produced a state that cannot exist -- "LIVE
                    # VERIFIED 等待" beside "生产复用 ✓".
                    activation_episode_id = str(record.activation_episode_id or "")
                    live_try_episode_id = str(record.live_try_episode_id or "")
                    live_verify_episode_id = str(record.live_verify_episode_id or "")
                    reuse_episode_id = str(record.production_reuse_episode_id or "")
            except Exception as exc:  # noqa: BLE001
                # Reported rather than swallowed.  Measured: a NameError here (``fold`` was
                # not imported) surfaced as an empty version cell, which reads exactly like
                # "there is no version yet" -- the one answer that is wrong in a way nobody
                # would question.
                state = f"读取失败：{type(exc).__name__}"
            card = {
                "ok": True,
                "trace_id": chain.trace_id,
                "job_id": chain.job_id,
                "capability": chain.capability,
                "completed": chain.completed,
                "total": len(chain.applicable),
                # ``verdict``, ``completed``, ``failure_step`` and ``applicable`` are
                # properties on ``Chain``, not methods.  Calling ``verdict()`` raised
                # "'str' object is not callable", which only a live run showed: the card is
                # wrapped in a broad except so the window stayed up, and the failure surfaced
                # as a reason string rather than as a crash.
                "verdict": chain.verdict,
                "breakpoint": chain.failure_step,
                "steps": [(step.name, step.done, step.note) for step in chain.steps],
                "record_state": state,
                "outcome": outcome,
                "before_version": before_version,
                "after_version": after_version,
                "active_version": active_version,
                "activation_episode_id": activation_episode_id,
                "live_try_episode_id": live_try_episode_id,
                "live_verify_episode_id": live_verify_episode_id,
                "production_reuse_episode_id": reuse_episode_id,
                # §7: whether this chain is the *current* trace or merely the most recent one.
                # With nothing open the selector returns None, and the page may still show
                # history -- but it must say that is what it is, or a finished trace reads as
                # the present, which is the defect the operator named.
                "is_current": bool(current_key),
            }
    except Exception as exc:  # noqa: BLE001 - a card must never take the window down
        # ``transient`` is what tells :class:`ClosureCardProbe` this is a *failure to answer*
        # -- retry soon -- and not the answer "nothing has happened yet", which is also
        # ``ok: False`` but carries no such mark.
        card = {"ok": False, "transient": True, "reason": f"{type(exc).__name__}: {exc}"}

    return card


#: The eight cells §八 asks for, each mapped onto the chain steps that prove it.  A cell is
#: 完成 only when *its own* steps are done: "Gateway ✓" because the gateway answered is not
#: the same claim as "Job ✓", and one green tick for the whole pipeline is exactly the
#: conflation the operator has been correcting all along.
LOOP_CELLS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Gateway", ("gap_detected",)),
    ("Queue", ("escalation_created", "queue_deduped")),
    ("Job", ("job_submitted", "job_working", "code_changed", "tests_passed")),
    ("Version", ("reload_requested", "reload_settled")),
    ("真机校准", ("live_verify_episode",)),
    ("LIVE VERIFIED", ("outcome_live_verified",)),
    ("生产复用", ("auto_resumed", "post_resume_verified")),
    ("Next Capability", ()),
)


def render_loop_card(card: Mapping[str, Any] | None) -> str:
    """The eight cells as one line of ✓ / 等待 / 异常, plus the trace and the breakpoint."""
    if card and card.get("pending"):
        # Not the same claim as "the loop has not started".  The card is computed on a
        # background thread (see ClosureCardProbe) and the first answer takes a few seconds;
        # rendering that window as 闭环尚未开始 would be a claim about the system made from a
        # fact about the renderer.
        return f"闭环卡片计算中（{str(card.get('reason') or '')}）"
    if not card or not card.get("ok"):
        return f"闭环尚未开始（{str((card or {}).get('reason') or '无记录')}）"
    done = {name: bool(state) for name, state, _ in card.get("steps") or ()}
    # §十一: the Version cell is graded on the *ledger state*, because that is where the fact
    # lives.  ``reload_requested``/``reload_settled`` are the chain tool's own steps and they
    # describe the reload mechanism, not whether this version was ever loaded.
    state = str(card.get("record_state") or "")
    version_zh = {
        "VERSION_ACTIVE": "✓ 已加载",
        "LIVE_VERIFY_PENDING": "等待真机验证",
        "VERSION_ACTIVATION_PENDING": "等待新版本首次加载",
    }
    # §8: three of the eight cells are graded on the *episode ids the ledger recorded*, because
    # that is where those facts live.  The chain tool's own steps describe the reload mechanism,
    # and reading them here produced states that cannot exist -- measured 2026-09-18: "LIVE
    # VERIFIED 等待" beside "生产复用 ✓", i.e. reuse credited before verification.
    evidence_cells = {
        "真机校准": (str(card.get("live_try_episode_id") or "")
                    or str(card.get("live_verify_episode_id") or "")),
        "LIVE VERIFIED": str(card.get("live_verify_episode_id") or ""),
        "生产复用": str(card.get("production_reuse_episode_id") or ""),
    }
    cells: list[str] = []
    for label, members in LOOP_CELLS:
        if label == "Version":
            cells.append(f"{label} {version_zh.get(state, '等待')}")
            continue
        if label in evidence_cells:
            episode = evidence_cells[label]
            cells.append(f"{label} ✓" if episode else f"{label} 等待")
            continue
        if not members:
            # "Next Capability" has no step of its own: it is a statement about what the
            # bootstrap controller selected next, and it is reported on its own row.  Saying
            # ✓ here because the other seven are done would be the conflation again.
            cells.append(f"{label} —")
            continue
        if all(done.get(name) for name in members):
            cells.append(f"{label} ✓")
        elif any(done.get(name) for name in members):
            cells.append(f"{label} 进行中")
        else:
            cells.append(f"{label} 等待")
    trace = f"trace_id {card.get('trace_id')}"
    if card.get("job_id"):
        trace += f" · job {card.get('job_id')}"
    version_note = ""
    if card.get("after_version"):
        version_note = (f" · 版本 {str(card.get('before_version') or '?')[:8]} → "
                        f"{str(card.get('after_version'))[:8]}"
                        + (f"（已加载 {str(card.get('active_version'))[:8]}）"
                           if card.get("active_version") else "（尚未被真实 Episode 加载）"))
    breakpoint = str(card.get("breakpoint") or "")
    tail = (f"{card.get('completed')}/{card.get('total')} 步 · 断点：{breakpoint}"
            if breakpoint else f"{card.get('completed')}/{card.get('total')} 步 · 无断点 · PASS")
    if not card.get("is_current"):
        traceline = (f"当前无未完成 trace（以下为最近一次历史，不是当前工作）：\n{trace}"
                     f"{version_note}   {tail}")
        return "   ".join(cells) + f"\n{traceline}"
    return "   ".join(cells) + f"\n{trace}{version_note}   {tail}"


def render_soak(record: Mapping[str, Any] | None, soak_error: str = "") -> str:
    """The acceptance soak as one operator-readable line, or a *named* reason it is not running.

    The distinction the operator asked for (§6): 尚未开始 must never stand in for "it declined".
    A soak is either running (with its timer and sample count), finished (with its verdict), or
    not started -- and in the last case the window says which of the two it is: not triggered
    yet, or triggered and refused, with the refusal's own words.
    """
    if not record:
        if soak_error:
            return f"启动失败：{soak_error}（不是「尚未开始」——窗口已尝试并给出了原因）"
        return "尚未触发（GUI 启动后由窗口自行测量；若长时间如此即为异常，而非等待）"
    verdict = (record.get("verdict") or {})
    overall = str(verdict.get("overall") or "INCOMPLETE")
    elapsed = float(record.get("duration_minutes") or 0.0)
    window = float(record.get("window_seconds") or 900.0) / 60.0
    complete = bool(record.get("complete"))
    failed = [name for name, item in (verdict.get("conditions") or {}).items()
              if item.get("ok") is False]
    unknown = [name for name, item in (verdict.get("conditions") or {}).items()
               if item.get("ok") is None]
    zh = {name: label for name, label in (
        ("gui_alive", "GUI存活"), ("gateway_reachable", "网关可达"),
        ("single_gateway", "单网关"), ("port_owner_legal", "端口归属"),
        ("no_restart_loop", "无重启循环"), ("pump_ticking", "泵心跳"),
        ("auto_gameplay", "AUTO继续"), ("gateway_fault_does_not_block_auto", "故障不阻塞AUTO"),
        ("no_duplicate_job", "无重复Job"), ("no_extra_spawn_per_refresh", "无额外spawn"),
        ("no_black_console", "无黑窗"), ("topbar_agrees", "顶部一致"),
    )}
    phase = "完成" if complete else "运行中"
    line = (f"{phase} {overall} · {elapsed:.1f}/{window:.0f} 分钟 / "
            f"{record.get('sample_count', 0)} 样本 · 重启 "
            f"{record.get('distinct_gateway_pids') and len(record['distinct_gateway_pids']) or 0} 个网关进程"
            f" · 黑窗 {record.get('black_console_windows', 0)}")
    if failed:
        line += f" · 未通过：{'、'.join(zh.get(n, n) for n in failed)}"
    if unknown:
        line += f" · 未测量：{'、'.join(zh.get(n, n) for n in unknown)}"
    if record.get("development_env_limitation"):
        line += " · DEVELOPMENT_ENV_LIMITATION（非正式启动路径，不构成验收证据）"
    return line


def gateway_reason_cn(reason: str) -> str:
    """The escalation gateway's answer, in Chinese.

    Worth translating rather than passing through: NO_CREDENTIAL and
    AUTH_REJECTED look equally like "unavailable" but need different fixes, and
    the 2026-09-17 session found the environment holding a stale password while a
    different one was actually serving -- exactly the case the second string names.
    """
    text = str(reason or "")
    if text in GATEWAY_REASON_ZH:
        return GATEWAY_REASON_ZH[text]
    if text.startswith("HTTP_"):
        return f"网关返回 HTTP {text[5:]}"
    if text.startswith("UNHEALTHY"):
        return f"网关健康检查未通过：{text.split(':', 1)[-1]}"
    return text or "原因未提供"


def duration_label(record: Any, now: datetime | None = None) -> str:
    """How long the job has been running (or ran), in the operator's units."""
    started = getattr(record, "submitted_at", None) or getattr(record, "first_seen", None)
    if started is None:
        return NO_DATA
    ended = getattr(record, "settled_at", None)
    moment = now or datetime.now(timezone.utc)
    seconds = ((ended or moment) - started).total_seconds()
    if seconds < 0:
        return NO_DATA
    if seconds < 60:
        return f"{seconds:.0f} 秒"
    if seconds < 3600:
        return f"{seconds / 60:.0f} 分钟"
    return f"{seconds / 3600:.1f} 小时"


def capability_lifecycle_cn(entry: dict[str, Any], *, skill_state: str = "") -> str:
    """Coverage lifecycle in plain Chinese, from the catalog's own field."""
    if entry.get("blocked_reason"):
        return "Blocked"
    lifecycle = str(entry.get("lifecycle") or "").upper()
    if lifecycle == "LIVE_VERIFIED":
        return "Stable" if skill_state == SkillState.STABLE.value else "Live Verified"
    if lifecycle == "LIVE_TRIED":
        return "Live Tried"
    if lifecycle == "CANDIDATE":
        return "候选"
    if lifecycle == "MISSING":
        return "未实现"
    return PENDING


def capability_state_cn(
    entry: dict[str, Any],
    *,
    skill_state: str = "",
    running_skill: str = "",
    claims: int = 0,
) -> str:
    """The availability half of a capability's status.

    Every branch is a fact from an existing file.  ``claims`` is the number of
    episode rows for this capability's skill that carry no ``recorded_at`` -- the
    catalog's own evidence policy says those cannot support a verification, so
    the honest word is 待刷新 rather than 可执行.
    """
    skill = str(entry.get("existing_skill") or "")
    if str(entry.get("real_money_cost") or "").upper() == "FORBIDDEN":
        return "不可用"
    if str(entry.get("unlock_status") or "").upper() == "LOCKED":
        return "未解锁"
    if running_skill and skill and running_skill == skill:
        return "执行中"
    if entry.get("blocked_reason"):
        return "Blocked"
    if str(entry.get("lifecycle") or "").upper() in ("LIVE_VERIFIED", "LIVE_TRIED"):
        return "可执行"
    if skill and skill_state == SkillState.BLOCKED.value:
        return "Blocked"
    if claims:
        return "待刷新"
    if str(entry.get("implementation_status") or "").upper() == "EXISTING":
        return "可执行"
    if str(entry.get("current_role_available") or "").upper() == "OBSERVED_AVAILABLE":
        return "已识别"
    return PENDING


def runtime_status_cn(stop_reason: str | None, *, running: bool) -> str:
    """What the current runtime state is called in the panel.

    This is where 等待 lives: a runtime sitting on an ordinary-weather stop is
    waiting, which is different from unread and different from broken.
    """
    reason = str(stop_reason or "")
    if reason in RUNTIME_WAITING_STOPS:
        return "等待"
    if running:
        return "执行中"
    if not reason:
        return PENDING
    return UNKNOWN_STOP


def overview_kpis(root: Path | None = None, *, registry: Any = None, view: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """The eight numbers the operator asked to see first.

    Each card carries the file it came from, because a KPI nobody can trace back
    to a source is a number people learn to ignore.
    """
    catalog = capability_catalog(root)
    entries = catalog.get("capabilities") or []
    index = episode_index(root)
    view = view if view is not None else escalation_view(root)
    if registry is None:
        registry = v2_registry()
    skills = registry.all()
    stable = sum(1 for skill in registry.all() if skill.state is SkillState.STABLE)
    # The registry is the only place "Stable" is defined, and today it holds none --
    # showing a bare 0 with no context would read as a bug rather than as the state
    # of the promotion gate, so the card carries the real distribution beside it.
    state_mix = Counter(skill.state.value for skill in skills)
    stable_source = "Skill Registry · " + " / ".join(
        f"{name} {state_mix.get(name, 0)}" for name in ("STABLE", "VERIFIED", "CANDIDATE", "BLOCKED")
    )
    observed = implemented = tried = verified = never = blocked = 0
    for entry in entries:
        lifecycle = str(entry.get("lifecycle") or "").upper()
        attempts = int(entry.get("live_attempts") or 0)
        if (str(entry.get("current_role_available") or "").upper() != "UNKNOWN"
                or str(entry.get("unlock_status") or "").upper() != "UNKNOWN" or attempts):
            observed += 1
        if str(entry.get("implementation_status") or "").upper() == "EXISTING":
            implemented += 1
        if attempts:
            tried += 1
        if lifecycle == "LIVE_VERIFIED":
            verified += 1
        if lifecycle == "MISSING":
            never += 1
        if entry.get("blocked_reason"):
            blocked += 1
    active = len(view.get("active") or ())
    values = {
        "observed": str(observed), "implemented": str(implemented), "tried": str(tried),
        "verified": str(verified), "stable": str(stable), "never": str(never),
        "blocked": str(blocked), "queue": f"{active} 活跃 / {view.get('total', 0)} 累计",
    }
    return {key: {"label": CATALOG_META[key][0], "value": values[key],
                  "source": stable_source if key == "stable" else CATALOG_META[key][1]}
            for key in CATALOG_META}


def intervention_of(*, problems: list, auto_running: bool, policy: Any = None) -> str:
    """The one cell that answers 需要我干预吗, and what the operator would do about it.

    Operator's audit (2026-10-04, second layer §五A) found this slot **missing**: the console
    could say what it was doing and why, but no cell anywhere said whether the *human* was
    needed -- and the two nearest answers, ``attention`` and ``mode``, sat far apart on the
    same page.  It was the only L1 item absent from the whole window.

    Two properties make this honest rather than decorative:

    * ``problems`` is the *same list* the 需要关注 card prints, passed in rather than
      recomputed, so this cell and that card cannot hold different opinions.
    * The spend line is read from ``config/policy_state.json`` -- the file the strategy page
      already renders -- so "花钱" is answered from a declared verdict rather than from a
      plausible-looking zero.  Where the file is silent the cell says 未声明 instead of
      implying nothing can be spent.
    """
    problems = [str(item) for item in problems if str(item).strip()]
    if problems:
        verdict = f"需要你看一眼（{len(problems)} 项）"
        reason = "；".join(problems[:2])
    else:
        verdict = "不需要你干预"
        reason = ("没有冲突、没有过期数据源、没有卡住；"
                  + ("AUTO 正在运行" if auto_running else "AUTO 未在运行（这是你的选择，不是故障）"))

    state = policy if isinstance(policy, dict) else {}
    money = str(state.get("real_money") or "").upper()
    spend = "真钱：永久禁止 🔒" if money == "PERMANENTLY_BLOCKED" else f"真钱：{money or '未声明'}"
    forbid = state.get("disabled_goals")
    if isinstance(forbid, dict) and forbid:
        spend += f" · 已禁用 Goal {len(forbid)} 个（自动选择已排除）"

    return "\n".join([
        f"结论：{verdict}",
        f"原因：{reason}",
        f"此刻会不会花钱 / 不可逆操作：{spend}",
        "去哪里：策略页「运行方式」有截图 / 证据 / 日志入口；顶部 AUTO 指示器可确认它在不在跑",
    ])


def status_defaults() -> dict[str, str]:
    """Every status variable the panel owns, with its value before anything is read.

    A function rather than an inline literal because the handler tests need to
    build a stub mapping for ``ControlPanel`` without a Tk window, and a stub that
    hard-codes its own key list silently stops matching the real panel the moment
    a key is added -- which is exactly what happened when MAA and WorkBuddy
    replaced the previous provider and recognition cells in the header.  Deriving
    the stub from here makes the two impossible to desynchronise.
    """
    return {
        "agent": "● 等待", "maa": MAA_NORMAL, "device": "未探测", "game": PENDING, "page": PENDING,
        "mode": "停止", "workbuddy": WORKBUDDY_LABELS["IDLE"], "clock": "--:--:--",
        "march": "行军：暂无数据", "task_cn": "等待启动", "skill": NO_DATA,
        "reason": "尚未产生决策", "preconditions": PENDING, "next": "截图并识别当前页面",
        "backend": PENDING, "backend_detail": PENDING, "risk": PENDING,
        "confidence_decision": NO_DATA, "confidence_frame": NO_DATA, "runtime_state": PENDING,
        "verifier": "等待任务执行", "result": "尚未运行",
        "wb_state": WORKBUDDY_LABELS["IDLE"], "wb_capability": PENDING, "wb_reason": PENDING,
        "wb_job": PENDING, "wb_model": PENDING, "wb_duration": PENDING,
        "wb_job_state": PENDING, "wb_improvement": PENDING, "wb_result": "尚未产生开发任务",
        "wb_gateway": PENDING, "wb_queue_line": PENDING, "wb_gap": PENDING,
        "wb_pump": PENDING, "lease": PENDING, "learn": PENDING,
        # The truth-source row.  Deliberately *not* a plausible-looking default: before the
        # first audit pass the window must admit it does not know, not print a placeholder
        # that reads like an observation.
        "role": PENDING, "role_state": "", "truth": "",
        # The top-bar indicators, one word each from one vocabulary
        # (``state_truth.health_of``).  They start at 未确认 rather than at a plausible
        # "正常": a bar that is green before anything has been read is lying about the
        # only thing it exists to say.
        "dot_v2": DOT_UNKNOWN, "dot_maa": DOT_UNKNOWN, "dot_mumu": DOT_UNKNOWN,
        "dot_game": DOT_UNKNOWN, "dot_auto": DOT_UNKNOWN, "dot_wb": DOT_UNKNOWN,
        "dot_model": DOT_UNKNOWN, "dot_boot": DOT_UNKNOWN,
        # The new panels' own lines.
        "why_idle": PENDING, "executor_mix": PENDING, "progress": PENDING,
        "bootstrap": PENDING, "coverage": PENDING, "attention": "暂无需要关注的问题",
        # The one L1 slot the 2026-10-04 audit found missing from the entire window: whether
        # the operator is needed, and what they would do.  It starts at 未读取 rather than at
        # a reassuring 不需要, because a cell that answers "is the human needed" must not
        # answer it before anything has been read.
        "intervene": PENDING,
        "watchdog": PENDING, "local_model": PENDING, "local_model_last": PENDING,
        # Operator directive 2026-10-01 §36: the learning-effect lines.  Two rows rather than one
        # because the funnel and the KPI set answer different questions -- "where did it stop" is
        # not the same as "did the game get played".
        "learning": PENDING, "learning_kpi": PENDING,
        # §八's closed-loop card: the eight cells, the trace and the current breakpoint, all
        # from ``unattended_closure``.  And §一's acceptance, which the window runs itself so
        # the operator never has to execute a second command.
        "loop_card": PENDING, "loop_trace": PENDING, "loop_break": PENDING,
        "soak": "尚未开始（GUI 启动后由窗口自行测量，无需任何手工命令）",
        # §9: contradictions in what the page is about to display.  Starts as 未检查 rather
        # than as "一致": a page that has not compared anything must not claim consistency.
        "consistency": "未检查（等待首次刷新）",
        # §7: the control plane's own two versions.  Shown side by side because the measured
        # symptom was a window that could not tell that the code under it had changed -- and a
        # single cell saying "已同步" would have hidden which of the two it compared.
        "control_plane": PENDING, "control_plane_loaded": PENDING, "control_plane_disk": PENDING,
        "stats": "本次启动：0 轮 · 0 动作",
    }


# ------------------------------------------------------- the one runtime local model
#
# Operator directive 2026-09-30: V2 has exactly one local model (UI-Venus-2-9B Q4_K_M) and the
# window has to answer three questions without the operator opening a log --
# *which* model, *is it up*, and *what did it last decide*.  Everything below is a derivation
# from artifacts that already exist, like the rest of this section: the name comes from
# ``config/v2.json``'s ``local_planner``, liveness from the service's own ``/health``, and the
# last call from the ledger the client writes.  Nothing here owns state, so a wrong number is
# fixed where it came from.
#
# Two boundaries are encoded in what is deliberately *not* shown:
#
# * a known Skill's work is never dressed up as model reasoning.  This line only ever cites
#   rows the model client itself wrote; a step that a Skill handled has no row here at all.
# * a model's *claim* is never shown as a verified outcome.  The verdict column is filled
#   from the verifier's own record or it says 未验证 -- the local model cannot certify itself.
#: The single source string the runtime's advisor stamps on the rows it writes.  Duplicated as a
#: literal rather than imported so the panel does not pull the planner into its process just to
#: compare a string; ``tests/test_local_planner.py`` pins the two together, because a silent
#: divergence here would make the window show *no* last decision while the ledger was full of them.
LOCAL_GUI_SOURCE = "LOCAL_GUI_MODEL"
LOCAL_GUI_MODEL_UNSET = "未读取"


def local_gui_model_config(root: Path | None = None) -> dict[str, Any]:
    """``config/v2.json``'s ``local_planner`` section, or ``{}``.

    Read here rather than imported from the runtime so that turning the model off in the config
    changes this cell with no code edit -- and so the panel cannot disagree with the file the
    operator actually edits.
    """
    try:
        payload = json.loads((root or ROOT).joinpath("config/v2.json").read_text(
            encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, Mapping):
        return {}
    section = payload.get("local_planner")
    return dict(section) if isinstance(section, Mapping) else {}


def _last_ledger_row(path: Path) -> dict[str, Any]:
    """The last parseable record of a JSONL ledger, or ``{}``.

    Walks backwards on purpose.  A ledger that is missing, empty or truncated mid-write must
    say *nothing*; trusting the final line would turn a half-written row into a fabricated
    "last call", which is the one thing a status line may not do.
    """
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    for line in reversed(raw.strip().splitlines()):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, Mapping):
            return dict(row)
    return {}


def local_gui_model_line(root: Path | None = None) -> str:
    """Which model, under which provider and endpoint -- the operator's first question."""
    planner = local_gui_model_config(root)
    if not planner:
        return f"{LOCAL_GUI_MODEL_UNSET}（config/v2.json 里没有 local_planner 段）"
    if not planner.get("enabled", False):
        return "已停用（local_planner.enabled=false）· UNKNOWN 页面按既有规则降级，AUTO 不受影响"
    name = str(planner.get("model") or "未命名")
    quant = str(planner.get("quantization") or "").strip()
    provider = str(planner.get("provider") or "").strip()
    endpoint = str(planner.get("endpoint") or "").strip()
    context = planner.get("context")
    steps = planner.get("max_steps_per_run")
    bits = [f"{name} {quant}".strip()]
    if provider:
        bits.append(provider)
    if endpoint:
        bits.append(endpoint)
    if context:
        bits.append(f"ctx {context}")
    if steps:
        bits.append(f"预算 {steps} 步/轮")
    bits.append("multimodal（每次调用带当前截图）" if planner.get("multimodal") else "纯文本")
    return " · ".join(bits)


def local_gui_model_last_call(root: Path | None = None) -> str:
    """Goal / page / decision / target / latency / screenshot proof, from the client's ledger.

    The screenshot fields are printed because they are the only *measurable* answer to "did the
    model really see the frame": ``image_sent`` plus the byte count and digest come from the
    request the client built, so a text-only regression shows up here as a missing image rather
    than as a plausible-looking plan.
    """
    planner = local_gui_model_config(root)
    if planner and not planner.get("enabled", False):
        return "已停用，不产生调用"
    row = _last_ledger_row((root or ROOT) / "learning/local_gui_model_calls.jsonl")
    if not row:
        return "尚无调用记录（模型只在 UNKNOWN 页面被问到，已知 Skill 不调用它）"
    when = str(row.get("recorded_at") or "")[:19].replace("T", " ")
    purpose = str(row.get("purpose") or "?")
    ok = row.get("ok")
    verdict = "成功" if ok else f"失败 {str(row.get('error') or '')[:60]}"
    try:
        latency = f"{float(row.get('latency_ms') or 0.0) / 1000:.1f}s"
    except (TypeError, ValueError):
        latency = "?"
    bits = [when, f"{purpose}", verdict, latency]
    if row.get("image_sent"):
        try:
            kib = float(row.get("image_bytes") or 0) / 1024
            bits.append(f"截图 {kib:.0f} KiB ({str(row.get('image_digest') or '')[:8]})")
        except (TypeError, ValueError):
            bits.append("截图 已发送")
    else:
        bits.append("无截图")
    if row.get("element_count") is not None:
        bits.append(f"元素表 {row.get('element_count')}")
    # The decision comes from the *planner's* ledger, which is a separate file because it
    # records a separate fact: what the answer was.  The call ledger only knows that a call
    # happened and what it cost.  A row written by a source this build no longer runs (the
    # retired provider) is not a "last decision" and must not be shown as one.
    plan = _last_plan_row((root or ROOT) / LOCAL_GUI_PLAN_LEDGER_PATH)
    if plan:
        decision = str(plan.get("decision") or "").strip()
        target = str(plan.get("target_element_id") or plan.get("semantic_target") or "").strip()
        for label, value in (("Goal", plan.get("goal")), ("页面", plan.get("page_key")),
                             ("Decision", decision), ("Target", target)):
            if str(value or "").strip():
                bits.append(f"{label} {value}")
    # The verdict, and only ever the verifier's.  The local model cannot certify its own step:
    # a plan with no settlement says 未验证 rather than borrowing the plan's own confidence.
    bits.append(_settlement_line((root or ROOT) / LOCAL_GUI_PLAN_LEDGER_PATH))
    return " · ".join(str(bit) for bit in bits if str(bit).strip())


def _learning_funnel_payload(root: Path | None = None) -> dict[str, Any]:
    """The funnel snapshot the panel reads, or ``{}`` when nothing has written one yet.

    Read from the file rather than folded here for a measured reason: the fold walks
    ``episodes.jsonl``, which is thousands of rows in production, and this runs on a UI tick.
    An empty result is shown as 未生成 rather than as zeroes, because "nobody has refreshed it"
    and "the runtime learned nothing" are different facts.
    """
    path = (root or ROOT) / "learning" / "learning_funnel.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def learning_effect_line(root: Path | None = None) -> str:
    """§36's funnel line, in Chinese: where the model's involvement stopped turning into skill."""
    payload = _learning_funnel_payload(root)
    if not payload:
        return "未生成（运行 tools/learning_report.py --funnel 生成一次）"
    console = payload.get("console") or {}

    def show(label: str) -> str:
        value = console.get(label)
        if value is None:
            return f"{label} —"
        if isinstance(value, float) and 0.0 <= value <= 1.0:
            return f"{label} {value:.0%}"
        return f"{label} {value}"

    stops = [
        stage for stage in (payload.get("funnel") or [])
        if stage.get("count") is None
    ]
    bits = [show(label) for label in (
        "今日 UI-Venus 调用", "UNKNOWN 次数", "UNKNOWN 成功解决", "新 Candidate Skill",
        "重复 UNKNOWN 调用率", "KNOWN_MODEL_CALLS",
    )]
    if stops:
        # Named, not summarised: "the funnel stopped here" is the single most useful thing the
        # console can say, and a reader who has to open a JSON file to find out will not.
        bits.append(f"未测量 {len(stops)} 级（首个：{stops[0].get('stage')}）")
    return " · ".join(bits)


def learning_kpi_line(root: Path | None = None) -> str:
    """§37's KPI line.  Rates with their sample sizes, and ``—`` where there is no denominator."""
    payload = _learning_funnel_payload(root)
    if not payload:
        return "未生成（运行 tools/learning_report.py --funnel 生成一次）"
    metrics = payload.get("metrics") or {}

    def rate(name: str, n_key: str = "") -> str:
        value = metrics.get(name)
        shown = "—" if value is None else f"{value:.0%}"
        if n_key:
            shown += f"(n={metrics.get(n_key, 0)})"
        return f"{name} {shown}"

    return " · ".join((
        rate("GAME_TASK_COMPLETION_RATE", "game_task_completion_rate_n"),
        rate("UNKNOWN_RESOLUTION_RATE"),
        rate("UNKNOWN_VERIFIER_PASS_RATE"),
        f"MODEL_CALLS_PER_HOUR {metrics.get('MODEL_CALLS_PER_HOUR', 0)}",
    ))


def _last_plan_row(path: Path) -> dict[str, Any]:
    """The last *proposal* row this build wrote, or ``{}``.

    Rows from the retired provider are skipped rather than displayed.  Measured 2026-09-30: the
    first version accepted any row carrying a ``decision`` key, and the ledger's newest row at that
    moment was an old provider's timeout -- so the window's "最近调用" line claimed the model had
    been asked about ``BEAST_HUNT``, which it never was.  Attribution has to be by source, and a row
    whose source this build does not run is not a last decision; it is history.
    """
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    for line in reversed(raw.strip().splitlines()):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, Mapping) or row.get("record") == "outcome":
            continue
        if str(row.get("source") or "") == LOCAL_GUI_SOURCE:
            return dict(row)
    return {}


def _settlement_line(path: Path) -> str:
    """``Verifier PASS/FAIL/未判定`` from the newest settlement row, or 未验证 when there is none."""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "Verifier 未验证"
    for line in reversed(raw.strip().splitlines()):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, Mapping) or row.get("record") != "outcome":
            continue
        ok = row.get("verifier_ok")
        word = "Verifier PASS" if ok else "Verifier FAIL" if ok is False else "Verifier 未判定"
        skill = str(row.get("skill") or "").strip()
        return f"{word}（{skill}）" if skill else word
    return "Verifier 未验证"


def local_gui_model_truth(root: Path | None = None, *, online: bool | None = None):
    """A ``TruthValue`` for the model cell, from the config plus the service's own answer.

    ``online is None`` means "not probed yet" and stays 未确认, like every other cell before its
    first read.  A configured-but-unreachable model is **not** 异常: the runtime is built to
    defer the UNKNOWN and keep the AUTO round going, so 等待 is the honest word, and the note
    says which of the two situations it is.
    """
    from winter_agent_v2.state_truth import TruthValue, UNKNOWN, LIVE_OBSERVED, PERSISTED

    planner = local_gui_model_config(root)
    source = "config/v2.json:local_planner + 服务 /health"
    if not planner:
        return TruthValue(name="local_model", value="未配置", status=UNKNOWN, source=source,
                          note="config/v2.json 里没有 local_planner 段")
    name = str(planner.get("model") or "未命名")
    quant = str(planner.get("quantization") or "").strip()
    if not planner.get("enabled", False):
        return TruthValue(name="local_model", value="已停用", status=PERSISTED, source=source,
                          note="local_planner.enabled=false：模型不是运行时依赖，"
                               "UNKNOWN 页面按既有规则降级，已知 Skill 完全不受影响")
    if online is None:
        return TruthValue(name="local_model", value=f"{name} {quant}".strip(), status=UNKNOWN,
                          source=source, note="已配置，但服务还没被探测过")
    if online:
        return TruthValue(name="local_model", value=f"{name} {quant}".strip(),
                          status=LIVE_OBSERVED, source=source,
                          note=f"{planner.get('provider', '')} 服务在线 · "
                               f"{planner.get('endpoint', '')}")
    return TruthValue(name="local_model", value=f"{name} {quant}".strip() + "（离线）",
                      status=UNKNOWN, source=source,
                      note="服务没有应答。不是故障：UNKNOWN 会 defer，AUTO 继续跑其它 Goal；"
                           f"端点 {planner.get('endpoint', '')}")


class PanelProbes:
    """Off-thread reads of the two facts the panel cannot get from a file.

    The WorkBuddy jobs API is HTTP and the device state is ``adb shell``; either one
    inside a Tk callback freezes the window, and the panel already learned that lesson
    once with subprocesses (see ``_background_run``).  Both live here on one daemon
    thread, and the UI only ever reads ``gateway()`` / ``device()``.

    A probe that fails is a *reported state*, not an exception: a gateway that is down or
    an emulator that is unplugged must show up in the window (the operator asked for
    exactly that) and must never stop the AUTO loop.
    """

    GATEWAY_INTERVAL = 5.0
    DEVICE_INTERVAL = 10.0
    # The truth audit walks several megabytes of episode stream, so it runs on a slower
    # cadence than the gateway poll.  Its answers change on the scale of an AUTO cycle,
    # not a few seconds, and the window must not stutter for a number nobody re-reads.
    TRUTH_EVERY = 4

    def __init__(self, root: Path | None = None, device: Any | None = None,
                 gateway_service: Any | None = None,
                 gui_model_service: Any | None = None) -> None:
        self.root = root or ROOT
        self._device_probe = device
        self._lock = threading.Lock()
        self._gateway: dict[str, Any] = {"available": None, "reason": "", "job": {}, "checked_at": ""}
        # The gateway back-off ladder's position, and when the next probe may happen.
        self._gateway_failures = 0
        self._gateway_next_at: datetime | None = None
        # The gateway's *process* lifecycle.  The panel owns it because the operator asked
        # for exactly one action to start the system, and a manual ``codebuddy --serve`` in
        # another terminal is a second action.  Injectable so a test can drive the probe
        # loop without a port or a process.
        self._gateway_service = gateway_service
        self._gateway_lifecycle: dict[str, Any] = {}
        # The local GUI model's *process* lifecycle.  The panel owns it for the same reason it
        # owns the gateway's, and the reason is the one the operator hit: 2026-10-03/04 the
        # model was down for 24 hours while this probe went on asking its ``/health`` every
        # fifteen seconds and grading the cell 等待.  Reporting an outage the window cannot end
        # is half a probe.  Injectable so a test drives the loop with no port and no GPU.
        self._gui_model_service = gui_model_service
        self._gui_model_lifecycle: dict[str, Any] = {}
        # The GUI's own acceptance soak (§一).  Created lazily, and only when this window is
        # the *production* launch path: a window started by a development tool must not
        # produce a soak that looks like evidence (§三/§九).
        self._soak: Any = None
        self._soak_context: tuple[str, str] = ("unknown", "")
        self._soak_error: str = ""
        self._device: dict[str, Any] = {"ok": None, "status": None, "error": "", "checked_at": ""}
        self._truth: dict[str, Any] = {"ok": None, "report": None, "checked_at": ""}
        # The one local GUI model's service.  Reachability is a *different* question from
        # configuration -- the same distinction the gateway probe exists to keep -- so it gets
        # its own poll and its own record rather than being inferred from the config file.
        self._local_model: dict[str, Any] = {"online": None, "reason": "", "checked_at": ""}
        self._watch: str = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def gateway_service(self) -> Any:
        """The lifecycle owner, built on first use against the *current* log directory.

        Built here rather than in ``__init__`` so the paths are read at call time, and so a
        window that never reaches this code never constructs one.
        """
        if self._gateway_service is None:
            from winter_agent_v2.gateway_service import GatewayService

            self._gateway_service = GatewayService(
                self.root,
                state_path=gateway_service_state_path(),
                log_path=gateway_service_log_path(),
            )
        return self._gateway_service

    def lifecycle(self) -> dict[str, Any]:
        """The last lifecycle record, for the window's WorkBuddy detail cells and for tests."""
        with self._lock:
            return dict(self._gateway_lifecycle)

    def soak(self) -> Any:
        """The acceptance soak, or ``None`` before the first production sample.

        Read by the UI thread only, like every other probe result: the window never runs the
        measurement, it displays it.
        """
        return self._soak

    def soak_payload(self) -> dict[str, Any]:
        soak = self._soak
        if soak is None:
            return {}
        try:
            return soak.payload()
        except Exception:  # noqa: BLE001
            return {}

    # -- readers (called from the UI thread) -------------------------------

    def gateway(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._gateway)

    def device(self) -> Any:
        """The probed ``DeviceStatus``, or ``None`` when the probe has not answered."""
        with self._lock:
            return self._device.get("status")

    def device_state(self) -> dict[str, Any]:
        """The probe's whole record, so "not probed" and "probe failed" stay distinct."""
        with self._lock:
            return dict(self._device)

    def device_note(self) -> str:
        with self._lock:
            return str(self._device.get("error") or "")

    def local_model(self) -> dict[str, Any]:
        """The local-model probe's whole record: "not probed" and "probe failed" stay distinct."""
        with self._lock:
            return dict(self._local_model)

    def local_model_truth(self) -> Any:
        """The ``TruthValue`` for the model cell, graded from the probe's own answer."""
        return local_gui_model_truth(self.root, online=self.local_model().get("online"))

    def gui_model_service(self) -> Any:
        """The local model's lifecycle owner, built on first use against the *current* root.

        Built here rather than in ``__init__`` for the same two reasons as the gateway's: the
        paths are read at call time, and a window that never reaches this code never
        constructs one.
        """
        if self._gui_model_service is None:
            from winter_agent_v2.gui_model_service import GuiModelService

            self._gui_model_service = GuiModelService(self.root)
        return self._gui_model_service

    def local_model_lifecycle(self) -> dict[str, Any]:
        """The last lifecycle record, so a test and the window read the same sentence."""
        with self._lock:
            return dict(self._gui_model_lifecycle)

    def truth(self) -> dict[str, Any]:
        """The last truth-source audit, or an empty record before the first pass.

        Read by the UI thread only, so the panel never runs ``git`` or walks the episode
        stream inside a Tk callback -- the same reason the gateway and device probes live
        on this thread.
        """
        with self._lock:
            return dict(self._truth)

    def watch(self, job_id: str) -> None:
        with self._lock:
            self._watch = job_id or ""

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="panel-probes", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        passes = 0
        while not self._stop.is_set():
            self._poll_gateway()
            self._poll_device()
            # Slower than the gateway: whether a model answers changes on the scale of a start
            # or a crash, not of a few seconds, and the window must not re-probe for a number
            # nobody re-reads.
            if passes % 3 == 0:
                self._poll_local_model()
            if passes % max(1, self.TRUTH_EVERY) == 0:
                self._poll_truth()
            passes += 1
            self._stop.wait(self.GATEWAY_INTERVAL)

    # -- the probes --------------------------------------------------------

    def _poll_local_model(self) -> None:
        """Ask the local model's service whether it is up.  Its ``/health``, not its config.

        Configuration and reachability are two questions, and the gateway probe's own history is
        the reason they are kept apart: inferring one from the other is what made the top bar say
        异常 about a gateway that was answering.  A model that is configured but silent is a
        reported state, not an exception -- the runtime defers the UNKNOWN and keeps the round
        going, so the honest word here is 等待 rather than 异常.

        Short timeout on purpose: this shares a machine with the emulator and with MAA, and a
        probe that blocks the probe thread is a window that stops updating.
        """
        import urllib.request

        state: dict[str, Any] = {"online": None, "reason": "",
                                 "checked_at": datetime.now().strftime("%H:%M:%S")}
        planner = local_gui_model_config(self.root)
        endpoint = str(planner.get("endpoint") or "").rstrip("/")
        if not planner.get("enabled", False) or not endpoint:
            state["reason"] = "本机没有启用的本地 GUI 模型"
        else:
            try:
                with urllib.request.urlopen(endpoint + "/health", timeout=3.0) as answer:
                    state["online"] = int(getattr(answer, "status", 0)) == 200
                    if not state["online"]:
                        state["reason"] = f"HTTP {getattr(answer, 'status', '?')}"
            except Exception as exc:  # noqa: BLE001 - a poll never reaches the UI as an exception
                state["online"] = False
                state["reason"] = type(exc).__name__
        # Measured, then handed to the lifecycle owner -- the same order and for the same reason
        # as the gateway probe: the window shows the lifecycle beside the health it came from.
        # This is where the 2026-10-04 outage gets *ended* rather than merely reported.  The
        # probe already knew the answer for twenty-four hours; nothing was allowed to act on it.
        state["lifecycle"] = self._ensure_gui_model(state)
        with self._lock:
            self._local_model = state

    def _ensure_gui_model(self, state: dict[str, Any]) -> dict[str, Any]:
        """One lifecycle pass for the resident model.  Never raises: this thread also drives
        gameplay's probes.

        Fire and forget, and that is a requirement rather than a shortcut.
        ``launch_gui_model_server`` blocks for up to 180 seconds waiting for ``/health``,
        because a human running it by hand wants the verdict; this thread must not, or the
        gateway and device probes queue behind it for three minutes and the window stops
        updating -- the defect class 2026-10-04 was spent removing.  Nothing is lost by not
        waiting: ``_poll_local_model`` re-asks ``/health`` itself, so the next pass *is* the
        confirmation.  ``observed`` hands it the answer this pass already has instead of taking
        it twice.
        """
        observed: tuple[bool | None, str] | None = (
            state.get("online"), str(state.get("reason") or "")
        )
        if observed[0] is None:
            # "Not probed" is not "down", and the two may not be conflated -- the gateway's own
            # history is the proof: inferring reachability from configuration restarted a
            # healthy gateway 51 consecutive times.  An unanswered probe hands the service
            # nothing, so it decides from the config instead of from a fabricated outage.
            observed = None
        try:
            lifecycle = self.gui_model_service().ensure(observed=observed)
        except Exception as exc:  # noqa: BLE001
            lifecycle = {"state": "UNKNOWN", "detail": f"{type(exc).__name__}: {exc}"}
        with self._lock:
            self._gui_model_lifecycle = dict(lifecycle)
        return dict(lifecycle)

    def _poll_truth(self) -> None:
        """Every state the window claims to know -- with its source, or saying it does not.

        The panel used to print ``当前角色 xhw`` from a string literal.  Nothing here is a
        literal: this asks the one projection that reads the artifacts, so the window and
        the audit cannot disagree.  A failure is a *state* ("audit unavailable") rather
        than an exception, for the same reason as the other two probes.
        """
        try:
            from winter_agent_v2.state_truth import TruthAudit

            report = TruthAudit(self.root).report()
            state = {
                "ok": True,
                "report": report,
                "checked_at": datetime.now().strftime("%H:%M:%S"),
                "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:  # noqa: BLE001
            state = {
                "ok": False, "report": None,
                "reason": f"{type(exc).__name__}: {exc}",
                "checked_at": datetime.now().strftime("%H:%M:%S"),
                "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        with self._lock:
            self._truth = state

    def _intent(self) -> str:
        """The operator's persisted intent, read at call time.

        Read from the persisted state rather than from a panel attribute because this
        thread starts before the window finishes building: on the first cycles there is no
        ``self.operator_intent`` to read, and a STOP left over from the previous session
        must still outrank the watchdog (§二十五).  A reader that raises is an intent we
        do not know, and the safe answer to an unknown intent is the passive one.
        """
        try:
            return load_operator_intent(PANEL_STATE_PATH)
        except Exception:  # noqa: BLE001
            return "STOPPED"

    def _poll_gateway(self) -> None:
        # A gateway that is not answering must not be asked every five seconds.  Measured
        # 2026-09-18: the log carried a 15-second timeout per poll, back to back, while
        # the development page showed GatewayUnavailable for /api/v1/jobs/d8ea0e44.  The
        # probe thread was almost entirely blocked in those timeouts, and the gateway was
        # being retried as hard as the loop could manage.  Consecutive failures now back
        # off (30s → 60 → 120 → 300) and one success clears the count.
        moment = datetime.now(timezone.utc)
        with self._lock:
            if self._gateway_next_at is not None and moment < self._gateway_next_at:
                return
        state: dict[str, Any] = {"available": None, "reason": "", "job": {},
                                 "checked_at": datetime.now().strftime("%H:%M:%S"),
                                 "checked_at_utc": moment.isoformat()}
        try:
            from winter_agent_v2.workbuddy_bridge import WorkBuddyBridge

            bridge = WorkBuddyBridge(cwd=self.root)
            probe = bridge.is_available()
            state["available"] = bool(probe)
            state["reason"] = str(getattr(probe, "reason", "") or "")
        except Exception as exc:  # noqa: BLE001 - a poll must never reach the UI as an exception
            bridge = None
            state["available"] = False
            state["reason"] = f"{type(exc).__name__}: {exc}"

        # The *job's* answer, in a try of its own -- the operator's P0-3 rule applied to the
        # code that reads the job: "what is this job doing" and "is the gateway reachable" are
        # two questions, and one may not answer for the other.
        #
        # Measured 2026-09-18 23:11: the two shared a try, so `status(job)` raising
        # ``JobLost`` wrote `JobLost: GET /api/v1/jobs/06271322 -> HTTP 404` into the *health*
        # record with ``available=False``.  Three consequences from one conflation: the top bar
        # said WorkBuddy 异常 about a gateway that was answering; the lifecycle owner read
        # "unreachable", took the ladder and restarted a healthy gateway repeatedly (51
        # consecutive failures); and the probe then went into its 300-second backoff, so the
        # probe file stopped being rewritten and the window reported 网关状态待测 -- which is
        # what the operator saw.
        if state.get("available") and bridge is not None:
            with self._lock:
                job_id = self._watch
            if job_id:
                try:
                    status = bridge.status(job_id)
                    state["job"] = {
                        "job_id": status.job_id, "verdict": status.verdict,
                        "state": status.gateway_state, "settled": status.settled,
                        "detail": status.detail, "result": status.result,
                    }
                except JobLost as exc:
                    # A job the gateway says is gone.  Recorded as the job's state and nothing
                    # more: it is a fact about the work, not about the connection.
                    state["job"] = {"job_id": job_id, "verdict": "JOB_LOST",
                                    "state": "JOB_LOST", "detail": str(exc)[:300]}
                except Exception as exc:  # noqa: BLE001
                    state["job"] = {"job_id": job_id, "verdict": "UNKNOWN", "state": "UNKNOWN",
                                    "detail": f"{type(exc).__name__}: {exc}"[:300]}

        # Hand the health we just measured to the lifecycle owner, so the whole P0 §二
        # sequence -- measure, decide, start if absent, reuse if healthy -- happens in one
        # place and one HTTP round trip.  It runs before the record is written so the
        # window can show the lifecycle alongside the health it came from.
        lifecycle = self._ensure_gateway(state, moment)
        state["lifecycle"] = lifecycle
        self._record_gateway(state, now=moment)
        # §一: the acceptance is measured by the window, on this thread, after the health and
        # the lifecycle are known -- so the evidence and the display come from one observation.
        self._drive_soak(state, lifecycle)

    def _ensure_gateway(self, state: dict[str, Any], moment: datetime) -> dict[str, Any]:
        """One lifecycle pass.  Never raises: this thread also drives gameplay's probes."""
        try:
            lifecycle = self.gateway_service().ensure(
                operator_intent=self._intent(),
                observed=(state.get("available"), str(state.get("reason") or "")),
            )
        except Exception as exc:  # noqa: BLE001
            lifecycle = {"state": "UNKNOWN", "detail": f"{type(exc).__name__}: {exc}"}
        with self._lock:
            self._gateway_lifecycle = dict(lifecycle)
        return dict(lifecycle)

    # Back-off ladder for a gateway that keeps timing out.  Bounded: the last rung is five
    # minutes, so a gateway that comes back is noticed without the panel ever giving up.
    GATEWAY_BACKOFF = (30.0, 60.0, 120.0, 300.0)
    # While a launch is in flight the probe runs at its normal cadence instead of climbing
    # the ladder: the point of starting a gateway is to watch it bind.
    GATEWAY_STARTING_INTERVAL = 5.0
    # One soak sample every N probe passes.  The probe runs at 5s, so this is a ten-second
    # cadence: fine enough that a restart is visible, coarse enough that the four file reads
    # behind it never come close to the probe's own cost.
    SOAK_SAMPLE_EVERY = 2

    def _soak_facts(self, state: dict[str, Any], lifecycle: dict[str, Any]) -> dict[str, Any]:
        """Everything §一 asks the window to record, read from artifacts that already exist.

        Gathered here rather than inside the soak so the soak stays a pure aggregator and can
        be tested without a port, a process or a clock -- and so the numbers on the GUI card
        and the numbers in the evidence file are the same numbers.
        """
        port_pids: list[int] = []
        try:
            port_pids = winproc.listeners(8080)
        except Exception:  # noqa: BLE001
            port_pids = []
        owner = port_pids[0] if port_pids else 0
        recorded = int(lifecycle.get("pid") or 0)

        job_id = ""
        job_state = ""
        duplicates: list[str] = []
        try:
            view = escalation_view(self.root)
            current = view.get("current") or {}
            job_id = str(current.get("job_id") or "")
            job_state = str(current.get("state") or "")
        except Exception:  # noqa: BLE001
            pass
        try:
            snapshot = EscalationLedger(Path(_ESCALATION_LEDGER_PATH)).snapshot()
            grouped: dict[str, set[str]] = {}
            for record in snapshot.active_jobs():
                grouped.setdefault(record.capability or record.key, set()).add(record.job_id)
            duplicates = [cap for cap, jobs in grouped.items()
                          if len({j for j in jobs if j}) > 1]
        except Exception:  # noqa: BLE001
            pass

        pump_age: float | None = None
        try:
            payload = json.loads(Path(PUMP_STATE_PATH).read_text(encoding="utf-8"))
            stamp = str(payload.get("written_at") or "")
            if stamp:
                pump_age = max(0.0, (datetime.now(timezone.utc)
                                     - datetime.fromisoformat(stamp)).total_seconds())
        except Exception:  # noqa: BLE001
            pump_age = None

        auto_running: bool | None = None
        try:
            snapshot = json.loads((self.root / "learning/runtime_snapshot.json")
                                  .read_text(encoding="utf-8"))
            auto_running = str(snapshot.get("mode") or "").upper() == "AUTO" and bool(
                snapshot.get("runtime_thread_alive") or snapshot.get("scheduler_loop_alive")
            )
        except Exception:  # noqa: BLE001
            auto_running = None

        # The stronger half of the same measurement: how many rounds this process has
        # actually finished.  Read defensively for the same reason ``auto_running`` is --
        # a fact that cannot be read is unproven, not zero.
        try:
            auto_rounds: int | None = int(auto_rounds_completed())
        except Exception:  # noqa: BLE001
            auto_rounds = None

        truth = self.truth()
        report = (truth or {}).get("report") or {}
        topbar = ""
        try:
            topbar = str(report["truths"]["gateway_health"].value)
        except Exception:  # noqa: BLE001
            topbar = ""

        return {
            "gui_pid": os.getpid(),
            "gateway_pid": recorded,
            # Only claimed when the port itself proves it: a pid that exists but holds no port
            # is exactly the ambiguity the identity check exists for, and the soak must not
            # record an identity it did not verify.
            "gateway_identity": True if (recorded and owner == recorded) else None,
            "port_8080_owner": owner,
            "port_8080_name": "",
            "health": state.get("available"),
            "lifecycle_state": str(lifecycle.get("state") or ""),
            "restart_count": int(lifecycle.get("restart_attempts") or 0),
            "duplicate_gateway_count": max(0, len(port_pids) - 1),
            "queue_pump_heartbeat": pump_age,
            "current_job_id": job_id,
            "job_state": job_state,
            "auto_running": auto_running,
            "auto_rounds": auto_rounds,
            "topbar_word": topbar,
            "duplicate_job_capabilities": duplicates,
        }

    def _drive_soak(self, state: dict[str, Any], lifecycle: dict[str, Any]) -> None:
        """One soak pass, on the probe thread, gated on the *production* launch path.

        §三/§九: a window a development tool started must not produce a soak that reads like
        acceptance evidence, because that host reaps its children and the window cannot be
        kept alive -- a limitation of the tooling, recorded as such, never worked around in
        the product.  The soak is created on the first production pass and then owns its own
        window; a GUI restart starts a new one, and the old file stays as history.
        """
        try:
            context, why = self._soak_context
            if context == "unknown":
                context, why = launch_context()
                self._soak_context = (context, why)
            if self._soak is None:
                if context != "production":
                    # Recorded, never silent.  Measured 2026-09-18 23:14: the window showed
                    # "尚未开始（GUI 启动后由窗口自行测量，无需任何手工命令）" -- a sentence that
                    # promises the measurement will happen -- while this branch had already
                    # decided it would not.  The operator's rule is explicit: a refusal is a
                    # state to display, not a blank.
                    self._soak_error = f"未启动：{why or context}"
                    self._log_soak_once(f"验收 Soak 未启动：{self._soak_error}")
                    return
                from winter_agent_v2.gateway_soak import GatewaySoak

                self._soak = GatewaySoak(
                    self.root,
                    facts=lambda: dict(self._soak_facts(self._gateway, self._gateway_lifecycle)),
                    sample_every=self.SOAK_SAMPLE_EVERY,
                    console_counter=self._console_windows_for_this_window,
                    rounds_completed=auto_rounds_completed,
                    launch_context=context,
                )
                self._log_soak_once(f"验收 Soak 已启动（{why}）：窗口 {self._soak.window_seconds:.0f} 秒，"
                                    f"由 GUI 自行测量，无需任何手工命令")
            soak = self._soak
            if soak.finished():
                return
            facts = self._soak_facts(state, lifecycle)
            sample = soak.observe(facts)
            if sample and soak.expired():
                record = soak.close()
                verdict = (record.get("verdict") or {}).get("overall")
                self._log_soak(f"验收 Soak 窗口结束：GATEWAY_SOAK = {verdict}"
                               f"（{record.get('sample_count')} 样本 / "
                               f"{record.get('duration_minutes')} 分钟）")
        except Exception as exc:  # noqa: BLE001 - a measurement must never take the window down
            # Both the page *and* the log.  Measured 2026-09-18: the soak declined in a live
            # window and the only place the reason existed was a process's memory -- the page
            # could show it but a reader of the log could not, and the window could not be
            # interrogated from outside.  A reason that only exists on screen is a reason that
            # cannot be diagnosed.
            self._soak_error = f"{type(exc).__name__}: {exc}"
            self._log_soak_once(f"验收 Soak 驱动失败：{self._soak_error}")

    def _console_windows_for_this_window(self) -> int | None:
        """Visible console windows owned by *this* window's process tree (§二 condition 11)."""
        try:
            from winter_agent_v2 import console_watch

            return len(console_watch.console_windows_for({os.getpid()}))
        except Exception:  # noqa: BLE001
            return None

    def _log_soak(self, message: str) -> None:
        try:
            LOG_ROOT.mkdir(parents=True, exist_ok=True)
            with PANEL_LOG_PATH.open("a", encoding="utf-8") as handle:
                handle.write(f"{datetime.now().strftime('%H:%M:%S')}  {message}\n")
        except Exception:  # noqa: BLE001
            pass

    def _log_soak_once(self, message: str) -> None:
        """Log a soak decision the first time it is taken, and never again.

        The driver runs every probe pass, so an unconditional write would put the same line in
        the log every ten seconds and bury it -- which is the failure mode the pump's own
        narration already solved the same way.  A change of decision logs again, because that is
        news.
        """
        if getattr(self, "_soak_noted", "") == message:
            return
        self._soak_noted = message
        self._log_soak(message)

    def _record_gateway(self, state: dict[str, Any], *, now: datetime) -> None:
        """Persist the probe and decide when the next one may happen.

        Persisted because the gateway's health is a *state the operator asked to be able
        to check*, and because the truth projection may only report what an artifact says:
        a value living in this process's memory cannot be audited, and "Job=WORKING so the
        gateway must be fine" is exactly the inference that made the top bar lie.
        """
        with self._lock:
            previous = dict(self._gateway)
            lifecycle = dict(state.get("lifecycle") or {})
            # The failure count is *the service's*, not a second one computed here.  Two
            # counters for one fact is how the earlier bug happened: the probe backed off on
            # a ladder the restarter knew nothing about, so the window waited five minutes
            # while the lifecycle owner was ready to act immediately.
            ladder = int(lifecycle.get("consecutive_failures") or 0)
            starting = str(lifecycle.get("action") or "") in ("START", "RESTART") or (
                str(lifecycle.get("state") or "") == "STARTING"
            )
            if state.get("available") is True:
                self._gateway_failures = 0
                self._gateway_next_at = None
                state["consecutive_failures"] = 0
                state["last_ok_at"] = now.isoformat()
                state["backoff_seconds"] = 0
            elif starting:
                # A launch is in flight.  Backing off now would be the worst possible
                # moment to stop looking: the whole point of starting it is to see it bind.
                self._gateway_failures = int(lifecycle.get("consecutive_failures") or 0)
                self._gateway_next_at = now + timedelta(seconds=self.GATEWAY_STARTING_INTERVAL)
                state["consecutive_failures"] = self._gateway_failures
                state["backoff_seconds"] = self.GATEWAY_STARTING_INTERVAL
                state["last_ok_at"] = str(previous.get("last_ok_at") or "")
            elif state.get("available") is False:
                # Prefer the lifecycle owner's count; fall back to a local one only when
                # there is no lifecycle record at all (a health check with no service wired).
                local = int(self._gateway_failures or 0) + 1
                self._gateway_failures = ladder if lifecycle else local
                rung = min(self._gateway_failures, len(self.GATEWAY_BACKOFF)) - 1
                wait = self.GATEWAY_BACKOFF[max(rung, 0)]
                self._gateway_next_at = now + timedelta(seconds=wait)
                state["consecutive_failures"] = self._gateway_failures
                state["backoff_seconds"] = wait
                state["last_ok_at"] = str(previous.get("last_ok_at") or "")
            else:
                # Unknown is not a failure and not a success: do not move the ladder.
                state["consecutive_failures"] = int(self._gateway_failures or 0)
                state["backoff_seconds"] = 0
                state["last_ok_at"] = str(previous.get("last_ok_at") or "")
            self._gateway = state
        try:
            path = gateway_probe_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:  # noqa: BLE001 - an unwritable probe must not kill the thread
            pass

    def _poll_device(self) -> None:
        """Read the real device state.  Read-only: it never connects or launches anything."""
        if self._device_probe is None:
            return
        state: dict[str, Any] = {"ok": None, "status": None, "error": "",
                                 "checked_at": datetime.now().strftime("%H:%M:%S")}
        try:
            state["status"] = self._device_probe.status()
            state["ok"] = bool(state["status"].connected)
        except Exception as exc:  # noqa: BLE001
            state["ok"] = False
            message = str(exc) or type(exc).__name__
            state["error"] = message.strip().splitlines()[-1][:120] if message.strip() else type(exc).__name__
        with self._lock:
            self._device = state


def _workbuddy_channel_enabled(root: str | Path | None) -> bool:
    """Whether V2 may still place a WorkBuddy job by itself.

    Operator directive 2026-09-25 section 1: it may not.  The switch lives in
    ``config/v2.json -> workbuddy_channel.enabled`` because "V2 does not call the desktop model
    on its own" is a deployment decision, and a decision that only exists inside an ``if``
    cannot be audited.  Read fresh each pass -- the file is 5 kB and the pass runs every
    ``UNKNOWN_EVERY`` ticks -- so flipping it takes effect without restarting the window.

    Default is **False**: the retired behaviour.  A missing or unreadable config resolves to
    the safe answer rather than to the old one, because "I could not read the switch" must not
    mean "submit a job".
    """
    try:
        path = Path(root) / "config/v2.json" if root else Path(__file__).resolve().parents[1] / "config/v2.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        section = payload.get("workbuddy_channel")
        if isinstance(section, dict):
            return bool(section.get("enabled", False))
        return False
    except (OSError, json.JSONDecodeError, TypeError):
        return False


class QueuePump:
    """The escalation queue's clock.

    ``EscalationQueueAdapter.observe_run`` only fires at the end of an AUTO cycle,
    and a cycle is minutes long -- measured 2026-09-18, ten minutes while the run
    ended in an ordinary stop.  So the queue had a consumer but nothing to drive
    it: a record created near the end of one cycle waited for the next, and if
    AUTO was stopped or paused it waited forever.  That is the shape the operator
    reported as "NEW=2, nothing submitted, gateway healthy".

    The panel owns the long-lived process, so the clock lives here.  It ticks on
    its own daemon thread, never raises, and rebuilds its adapter if one tick
    fails -- a broken pump is a reported state, not a dead window.
    """

    INTERVAL = 30.0
    # The Capability Bootstrap / Preload pass, in ticks.  Twenty ticks of thirty
    # seconds is a ten-minute cadence: one scan is ~0.5 s and it is a *background*
    # job by the operator's own rule, so it must be an order of magnitude rarer than
    # the queue consumer it shares this thread with.  It is also refused outright
    # while anything more important is owed -- see capability_bootstrap.preload_gate.
    PRELOAD_EVERY = 20

    # The UNKNOWN question channel, in ticks (30 s each).  Eight ticks is four minutes: a question
    # the AUTO filed is worth answering promptly -- the screen it is about is often gone within a
    # cycle -- while asking more often than that would only re-poll jobs whose state cannot have
    # changed.  Cheaper than the preload pass because a pass with nothing pending is one directory
    # listing and one gateway probe.
    UNKNOWN_EVERY = 8

    def __init__(self, *, enabled: Any | None = None, interval: float | None = None,
                 preload_every: int | None = None,
                 unknown_every: int | None = None) -> None:
        self._enabled = enabled or (lambda: True)
        self._interval = float(interval or self.INTERVAL)
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {
            "passes": 0, "submitted": 0, "released": 0, "reconciled": 0, "errors": 0,
            "last_tick": "", "last_line": "", "last_error": "", "gated": "",
            "preload_ticks": 0, "preloads": 0, "preload_last": "", "preload_note": "",
            "preload_decision": "", "preload_selected": "", "preload_next": "",
            "preload_status": "", "preload_learning": "", "preload_current": "",
            "preload_waiting": 0, "preload_gap": "", "preload_ingest": "",
            "preload_coverage": {},
            "preload_every": self.PRELOAD_EVERY if preload_every is None else int(preload_every),
            # The UNKNOWN question channel (winter_agent_v2/unknown_dispatch.py).  Separate keys so
            # the heartbeat answers the two questions an operator actually asks -- "are questions
            # being answered without me" and "is the thing that answers them alive" -- in words
            # rather than in a log they have to grep.
            "unknown_ticks": 0, "unknown_last": "", "unknown_note": "",
            "unknown_gateway": None, "unknown_pending": 0, "unknown_answered": 0,
            "unknown_in_flight": [], "unknown_submitted": 0, "unknown_attempts": {},
            "unknown_every": self.UNKNOWN_EVERY if unknown_every is None else int(unknown_every),
        }
        try:
            from winter_agent_v2.version_identity import process_revision

            loaded = process_revision()
            self._state["runtime_loaded_revision"] = loaded.token if loaded is not None else ""
            self._state["runtime_loaded_at"] = datetime.now(timezone.utc).isoformat()
        except Exception:  # noqa: BLE001 - missing telemetry must not stop the controller
            self._state["runtime_loaded_revision"] = ""
            self._state["runtime_loaded_at"] = ""
        self._state["control_plane_loaded_sha256"] = CONTROL_PLANE_SOURCE_SHA256
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._adapter: Any = None
        # The root the adapter was built against, so the controller's knowledge store
        # and state file land in the same tree -- including in a test that redirects
        # the ledger path, which is how a test avoids writing production knowledge.
        self._root_path: Path | None = None

    # -- readers (UI thread) -----------------------------------------------

    def state(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="queue-pump", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        # A short first delay: the window opens, the first AUTO run may take ten
        # minutes, and the records already in the ledger are owed a consumer now.
        self._stop.wait(5.0)
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(self._interval)

    # -- one pass -----------------------------------------------------------

    def tick(self) -> dict[str, Any]:
        """One consume pass.  Never raises: the pump must not take the window down."""
        if not self._enabled():
            with self._lock:
                self._state["gated"] = "operator stopped"
            self._persist()
            return self.state()
        with self._lock:
            self._state["gated"] = ""
        try:
            adapter = self._adapter if self._adapter is not None else self._build()
            self._adapter = adapter
            observation = adapter.pump()
        except Exception as exc:  # noqa: BLE001 - a failed tick is a state, not a crash
            self._adapter = None
            with self._lock:
                self._state["errors"] += 1
                self._state["last_error"] = f"{type(exc).__name__}: {exc}"
                self._state["last_tick"] = datetime.now().strftime("%H:%M:%S")
            self._persist()
            return self.state()
        with self._lock:
            self._state["passes"] += 1
            self._state["submitted"] += len(observation.submitted)
            self._state["released"] += len(observation.released)
            self._state["reconciled"] += len(observation.reconciled)
            self._state["errors"] += len(observation.errors)
            self._state["last_error"] = observation.errors[-1] if observation.errors else ""
            self._state["last_line"] = observation.line
            self._state["last_tick"] = datetime.now().strftime("%H:%M:%S")
        self._preload_tick()
        self._unknown_tick()
        self._persist()
        return self.state()

    def _preload_tick(self) -> None:
        """The slow Knowledge Bootstrap pass, on the same thread and adapter.

        Runs the whole loop (SCAN -> SELECT -> ... -> SELECT NEXT), not just the
        dispatch: the controller writes ``learning/knowledge_bootstrap/STATE.json``
        itself, and this records the one-line answer in the pump's own heartbeat so a
        reader outside the GUI can see both "the consumer ran" and "the preloader
        decided this".  A refusal is persisted too -- "the mechanism is resting, and
        here is why" is the state the operator asked to be able to check.
        """
        try:
            every = int(self._state.get("preload_every") or self.PRELOAD_EVERY)
            ticks = int(self._state.get("preload_ticks") or 0) + 1
            self._state["preload_ticks"] = ticks
            if every <= 0 or ticks % every:
                return
            from winter_agent_v2.capability_bootstrap import KnowledgeBootstrapController

            adapter = self._adapter if self._adapter is not None else self._build()
            self._adapter = adapter
            controller = KnowledgeBootstrapController(self._root_path, adapter=adapter)
            report = controller.cycle()
            # The controller wrote its own state file during that pass; read it back
            # rather than recomputing, so the GUI shows what the loop actually recorded
            # (including "the executor wrote nothing back this time") and not a second
            # opinion that could drift from it.
            snapshot: dict[str, Any] = {}
            try:
                snapshot = json.loads(
                    (Path(self._root_path) / "learning/knowledge_bootstrap/STATE.json")
                    .read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                snapshot = {}
            with self._lock:
                # Both halves: the structured line, and the decision's own sentence --
                # which of the five gates refused, or what is missing, is the difference
                # between "resting" and "broken".
                self._state["preload_note"] = (
                    f"{report.line} -- {report.note}" if report.note else report.line
                )
                self._state["preload_decision"] = report.decision
                self._state["preload_selected"] = report.selected
                self._state["preload_next"] = report.next_capability
                self._state["preload_status"] = snapshot.get("status", "")
                self._state["preload_learning"] = snapshot.get("learning", "")
                self._state["preload_current"] = snapshot.get("current_capability", "")
                self._state["preload_waiting"] = snapshot.get("waiting_live_verify_count", 0)
                self._state["preload_gap"] = ", ".join(snapshot.get("knowledge_gap") or ())
                self._state["preload_ingest"] = snapshot.get("last_ingest", "")
                self._state["preload_coverage"] = snapshot.get("coverage", {})
                if report.decision == "PRELOADED":
                    self._state["preloads"] = int(self._state.get("preloads") or 0) + 1
                self._state["preload_last"] = datetime.now().strftime("%H:%M:%S")
        except Exception as exc:  # noqa: BLE001 - a background pass is a state, not a crash
            with self._lock:
                self._state["preload_note"] = f"preload failed: {type(exc).__name__}: {exc}"
                self._state["preload_last"] = datetime.now().strftime("%H:%M:%S")

    def _unknown_tick(self) -> None:
        """Reconcile the UNKNOWN question channel; submitting is retired (config-gated).

        This is the consumer the channel never had: ``unknown_advisor`` writes a question and reads
        an answer if one is there, and until this ran the only thing that ever wrote one was a person
        at a terminal.  Each pass reconciles the jobs already dispatched, then submits at most one new
        one -- so the AUTO keeps playing throughout and a screen that has generated no question costs
        nothing beyond a directory listing.

        **Retired as an automatic model call, 2026-09-25.**  The operator's directive is that V2 no
        longer tries to reach the WorkBuddy desktop model by itself, and WorkBuddy goes back to being
        a tool a person drives.  The answering half moved *into* the cycle: the local planner decides
        the action in the same step it is asked, inside the runtime (``ui_planner``), so there is no
        job to dispatch and no answer to wait for.  ``config/v2.json -> workbuddy_channel.enabled``
        is the switch; while it is false this tick keeps reconciling anything already in flight (so no
        job is left dangling) and submits nothing.

        The model is deliberately not named here: ``tests/test_control_panel.py`` pins that this
        layer names none, so that the console keeps working when the planner is swapped or absent.

        Never raises: a gateway that is down, a ledger that cannot be read or a request that turns out
        to be malformed is reported in the heartbeat and left for the next tick.  The channel must not
        be able to take the window down, for the same reason the queue consumer must not.
        """
        try:
            every = int(self._state.get("unknown_every") or self.UNKNOWN_EVERY)
            ticks = int(self._state.get("unknown_ticks") or 0) + 1
            self._state["unknown_ticks"] = ticks
            if every <= 0 or ticks % every:
                return

            from winter_agent_v2.unknown_dispatch import UnknownDispatcher

            dispatcher = UnknownDispatcher(root=self._root_path or None)
            result = dispatcher.worker(submit=_workbuddy_channel_enabled(self._root_path))
            snapshot = dispatcher.state()
            reconcile = result.get("reconcile") or {}
            dispatch = result.get("dispatch") or {}
            submitted = dispatch.get("submitted") or []
            errors = list(reconcile.get("errors") or []) + list(dispatch.get("errors") or [])
            with self._lock:
                self._state["unknown_gateway"] = snapshot.get("gateway")
                self._state["unknown_pending"] = snapshot.get("pending", 0)
                self._state["unknown_answered"] = snapshot.get("answered", 0)
                self._state["unknown_in_flight"] = snapshot.get("in_flight") or []
                self._state["unknown_attempts"] = snapshot.get("attempts") or {}
                self._state["unknown_submitted"] = int(
                    self._state.get("unknown_submitted") or 0
                ) + len(submitted)
                if submitted:
                    note = "submitted " + ", ".join(
                        f"{item['request_id']}->{item.get('job_id', '?')}" for item in submitted
                    )
                elif reconcile.get("done") or reconcile.get("failed"):
                    note = (
                        f"reconciled: done={reconcile.get('done', 0)} "
                        f"failed={reconcile.get('failed', 0)} lost={reconcile.get('lost', 0)}"
                    )
                elif errors:
                    note = errors[-1][:200]
                elif snapshot.get("pending"):
                    note = (
                        f"{snapshot['pending']} question(s) waiting, "
                        f"{len(snapshot.get('in_flight') or [])} in flight"
                    )
                else:
                    note = "nothing pending"
                if not _workbuddy_channel_enabled(self._root_path):
                    # Not an error and not a backlog: the answer is produced locally, inside the
                    # cycle, so "nothing was submitted" is the configured behaviour.  Prefixed to
                    # the real reading rather than replacing it -- the window still needs to know
                    # what the reconcile pass found, and "retired" alone would hide a job that is
                    # still in flight from before the directive.
                    note = f"channel retired (local planner answers in-cycle); {note}"
                self._state["unknown_note"] = note
                self._state["unknown_last"] = datetime.now().strftime("%H:%M:%S")
        except Exception as exc:  # noqa: BLE001 - a background pass, not a critical path
            with self._lock:
                self._state["unknown_note"] = f"unknown channel failed: {type(exc).__name__}: {exc}"
                self._state["unknown_last"] = datetime.now().strftime("%H:%M:%S")

    def alive(self) -> bool:
        """Is the clock actually running?

        A consumer that lives on a thread inside a GUI is exactly the mechanism that
        stops quietly, and the operator asked to be told rather than to assume.  The
        question "Controller 是否运行" therefore has a real answer: this, plus the
        freshness of ``pump.json``.
        """
        return self._thread is not None and self._thread.is_alive()

    def revive(self) -> bool:
        """Restart the thread after it died, and say whether that was needed.

        The window owns the only long-lived process, so the panel's existing watchdog
        is the right place to notice a dead clock rather than inventing a second
        supervisor.  Only a thread that has actually stopped is replaced; a live one is
        left alone.
        """
        if self.alive():
            return False
        self._stop.clear()
        self._thread = None
        self.start()
        return True

    def _persist(self) -> None:
        """Write the tick where a reader outside this process can see it.

        A consumer that lives on a thread inside a GUI is exactly the kind of
        mechanism that stops quietly and leaves no trace, and the operator asked to
        be able to check that it is running rather than assume it.  The timestamp is
        also a watchdog signal: a stale file means the thread died, which is
        otherwise indistinguishable from a queue with nothing to do.
        """
        try:
            path = Path(PUMP_STATE_PATH)
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = dict(self.state())
            payload["written_at"] = datetime.now(timezone.utc).isoformat()
            payload["process"] = os.getpid()
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:  # noqa: BLE001 - an unwritable log must not stop the pump
            pass

    def _build(self) -> Any:
        """A real adapter on the real ledger -- the same one ``run_live`` uses.

        The ledger path is read from the module global at build time so a test
        that redirects it (the same way it redirects ``PANEL_LOG_PATH``) gets a
        pump that cannot write to production.
        """
        from winter_agent_v2.escalation_queue import EscalationLedger, EscalationQueueAdapter

        ledger_path = Path(_ESCALATION_LEDGER_PATH)
        root = ledger_path.parents[1] if ledger_path.parent.name == "learning" else ROOT
        self._root_path = root
        return EscalationQueueAdapter(root=root, ledger=EscalationLedger(ledger_path))


# How many AUTO rounds *this* panel process has run to completion, counted once per chain
# stage subprocess that finished.  Why it exists: ``auto_running`` in
# ``learning/runtime_snapshot.json`` is an instantaneous flag, and every AUTO round is a
# fresh process, so the flag is true only for the few seconds a round is in flight --
# measured 2026-09-20, a 15-minute window sampled 40 times read it False all 40 times while
# 13 rounds actually completed in it, and the soak concluded AUTO had stopped.  A counter
# that only moves when a round finished cannot be missed that way.
#
# Deliberately a module-level int under a lock rather than per-panel state: the only reader
# is the acceptance soak, which reads a *difference* across a window, so it needs a value
# that survives and never resets.  It is not persisted either -- a restarted process starts
# a new window, and a count that survived one would claim rounds this process never ran.
_AUTO_ROUNDS_LOCK = threading.Lock()
_AUTO_ROUNDS_COMPLETED = 0


def _note_auto_round_completed() -> None:
    """Record one finished AUTO round.  Never raises; a counter is not worth a worker."""
    global _AUTO_ROUNDS_COMPLETED
    try:
        with _AUTO_ROUNDS_LOCK:
            _AUTO_ROUNDS_COMPLETED += 1
    except Exception:  # noqa: BLE001
        pass


def auto_rounds_completed() -> int:
    """Completed AUTO rounds since this process started.  The soak's second evidence source."""
    with _AUTO_ROUNDS_LOCK:
        return _AUTO_ROUNDS_COMPLETED


#: How often the control-plane staleness question is recomputed.
#:
#: Measured 2026-10-04 on the pinned production tree: one answer costs
#: ``canonical_revision`` 1.03 s (a ``git rev-parse`` plus a content hash of every
#: version-relevant dirty path) and ``changed_paths_since`` a second ``git`` process on top.
#: The refresh cycle that consumed it ran every 1.5 s (``root.after(1500, ...)``) *on the UI
#: thread*, so two thirds of every cycle was spent in ``git`` and hashing -- the operator's
#: 卡顿, and the largest single block in a py-spy profile of the live window.
#:
#: Thirty seconds is far tighter than the event it detects: the notice is "a commit touched a
#: file this window imports", and the operator's next action is a restart at a safe point.
#: Nobody commits a control-plane fix and expects the banner within the same second.
CONTROL_PLANE_INTERVAL = 30.0


class ControlPlaneAnswer(NamedTuple):
    """One computed answer.  Immutable, so publishing it is a single reference swap."""

    loaded_token: str
    disk_token: str
    changed: tuple[str, ...]
    error: str = ""


class ControlPlaneProbe:
    """Answers "is this window running code that is no longer on disk?" off the UI thread.

    Division of labour, the operator's rule of 2026-10-04: the main thread does UI,
    scheduling and dispatch only, and I/O belongs on a background thread.  Reading the tree's
    version is I/O by that rule (``git`` subprocesses, then ``sha256`` over the dirty files),
    and by measurement it is the most expensive thing the refresh cycle did.

    This class only *computes and publishes*.  Acting on the answer -- writing the reload
    marker, deciding a safe point, delegating the restart to the launcher -- stays on the UI
    thread, because it touches the process and Tk.  ``_check_control_plane_reload`` is the
    consumer; ``refresh_once`` is exposed so a test can compute one answer synchronously
    instead of waiting for the thread.
    """

    def __init__(self, root: Path | str, *,
                 interval: float = CONTROL_PLANE_INTERVAL) -> None:
        self.root = Path(root)
        self.interval = max(1.0, float(interval))
        self._lock = threading.Lock()
        self._answer: ControlPlaneAnswer | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Begin publishing answers.  Idempotent, and it never blocks the caller."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="control-plane-probe", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Ask the thread to finish.  Daemon, so a missed call cannot keep the process up."""
        self._stop.set()

    def latest(self) -> ControlPlaneAnswer | None:
        """The most recent answer, or ``None`` before the first one lands.  No I/O."""
        with self._lock:
            return self._answer

    def refresh_once(self) -> ControlPlaneAnswer:
        """Compute one answer, publish it and return it.  Never raises."""
        try:
            from winter_agent_v2.control_plane_reload import changed_paths_since
            from winter_agent_v2.version_identity import canonical_revision, process_revision

            loaded = process_revision()
            loaded_token = loaded.token if loaded is not None else ""
            disk_token = canonical_revision(self.root, timeout=15.0).token
            changed = changed_paths_since(
                self.root, loaded.head if loaded is not None else ""
            )
            answer = ControlPlaneAnswer(loaded_token, disk_token, tuple(changed))
        except Exception as exc:  # noqa: BLE001 - a probe must never take the window down
            answer = ControlPlaneAnswer("", "", (), f"{type(exc).__name__}: {exc}")
        with self._lock:
            self._answer = answer
        return answer

    def _loop(self) -> None:
        while True:
            self.refresh_once()
            if self._stop.wait(self.interval):
                return


class ControlPanel:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Winter Agent OS V2 — 无尽冬日 AI 指挥中心")
        root.geometry("1360x820")
        root.minsize(1080, 680)
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        self.device = ADBDevice(Path(self.config["device"]["adb_path"]), self.config["device"]["serial"], production=True)
        self.registry = v2_registry()
        self.runtime_store = RuntimeSnapshotStore(RUNTIME_SNAPSHOT_PATH)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.process: subprocess.Popen[str] | None = None
        self.starting = False
        self.refreshing = False
        # Tab-scoped refresh.  The 1.5 s tick used to rebuild *every* page's data
        # whether or not anyone was looking at it; the expensive pages now refresh
        # only while their tab is on screen (and once more the moment it is opened),
        # which is what keeps the light pages responsive.  See _tab()/_on_tab_changed().
        self._tab_names: list[str] = []
        self._tab_refreshers: dict[str, list] = {}
        self._render_preview_job: str | None = None
        self._last_preview_render_at = 0.0
        self.stop_requested = self.paused = False
        self._device_launch_requested = False
        self._device_recovery_started_at = ""
        self._worker_thread: threading.Thread | None = None
        self.repeat_after_id: str | None = None
        self.latest_world: WorldState | None = None
        self.latest_image_path: Path | None = None
        self.preview_source: Image.Image | None = None
        # Decoded on first render, not on arrival: ``Image.open`` is lazy, and the
        # ~14 ms PNG decode plus the resize are only worth paying if someone is
        # looking at the preview.
        self._preview_rgb: Image.Image | None = None
        self.preview_photo: ImageTk.PhotoImage | None = None
        self.session = Counter()
        self.event_lines: list[str] = []
        self.watchdog_restart_pending = False
        defaults = status_defaults()
        self.values = {k: tk.StringVar(value=v) for k, v in defaults.items()}
        self.kpi: dict[str, tk.StringVar] = {}
        # Reads the device and the WorkBuddy jobs API off the UI thread; every value below
        # is read from a file that already exists, so the window still owns no state.
        self.probes = PanelProbes(ROOT, device=self.device)
        # The control plane's own reload state (§3-§5).  ``_reload_started`` guards against a
        # spawn loop when a restart fails; ``_reload_waiting`` holds the reason a reload is
        # owed but not yet allowed, so the window can say what it is waiting for.
        self._reload_started = False
        self._reload_waiting = ""
        # §7: capture the version this window is loading, here, so the top bar can compare it
        # with the disk later.  Without a frozen "current", a stale window has nothing to compare
        # against and cannot honestly say whether it is stale -- the measured failure was exactly
        # that silence.
        try:
            from winter_agent_v2.version_identity import freeze_process_revision

            freeze_process_revision(ROOT)
        except Exception:  # noqa: BLE001 - a missing version is reported, not fatal
            pass
        # Measured lazily, off the UI thread: see ControlPlaneProbe.  Started here rather than
        # on first use so the first refresh already has an answer to read.
        self.control_plane_probe = ControlPlaneProbe(ROOT)
        self.control_plane_probe.start()
        # The closure card is I/O too -- a 7.5 MB ledger, a 32 MB episode tail and a git log --
        # and it measured 3104 ms cold on this thread, once a minute.  Same reasoning as the
        # probe above, same shape: computed and published on a daemon thread, read here.
        self.closure_probe = closure_probe(ROOT)
        self.closure_probe.start()
        self.probes.start()
        # The queue's clock.  Started with the window, not with AUTO: the operator's
        # rule is that a running GUI keeps consuming its development backlog even
        # while the game side is between rounds.
        # Who owns the queue clock, decided before anything can act on it.  Measured
        # 2026-09-18: two panels alive in the same minute, each with a pump and each
        # about to start AUTO.  The window that loses still opens -- the operator gets
        # their view -- but it is read-only, and says so.
        try:
            owner_pid, owner_age = panel_clock_owner()
        except Exception:  # noqa: BLE001
            owner_pid, owner_age = 0, float("inf")
        self._other_instance = (
            owner_pid
            if owner_pid and owner_pid != os.getpid()
            and owner_age <= PANEL_CLOCK_MAX_AGE_SECONDS
            and _pid_is_live(owner_pid)
            else 0
        )
        self.pump = QueuePump(enabled=self._auto_development_allowed)
        if self._other_instance:
            # A second window must not become a second clock.  It starts no pump, so it
            # writes no heartbeat and cannot be mistaken for the owner by anything that
            # reads pump.json -- including the queue's own lease consumer.
            self._append(
                f"另一个实例正在运行（pid {self._other_instance}）：本窗口只读，"
                "不消费队列、不启动 AUTO、不申请设备租约。"
            )
        else:
            self.pump.start()
        # Counters, plus the last preload note so a repeating "resting" answer is
        # narrated once rather than every ten minutes.
        self._pump_prev: dict[str, Any] = {}
        # One bounded calibration run at a time: the device belongs to whoever holds the
        # lease, and two validation runs would be two owners.
        self.validating = False
        try:
            pid_path = panel_pid_path()
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text(str(os.getpid()), encoding="utf-8")
        except OSError:
            pass
        task_names = ("邮件", "探险", "采集", "建筑", "科技", "训练", "Intel", "联盟", "日常", "野怪", "巨熊")
        saved_tasks = load_task_selection(PANEL_STATE_PATH, task_names)
        self.task_enabled = {n: tk.BooleanVar(value=saved_tasks[n]) for n in task_names}
        self.continuous = tk.BooleanVar(value=True if self.config.get("auto_execution") else load_continuous_selection(PANEL_STATE_PATH))
        # The operator's last explicit request, remembered across restarts.  Read
        # before anything can start: `_maybe_autostart` is the only auto-start.
        self.operator_intent = load_operator_intent(PANEL_STATE_PATH)
        self.startup_preflight: dict | None = None
        self.preview_mode = tk.StringVar(value="原始画面")
        # ``self.resource_policy`` (五个 StringVar，绑在 设置 页的组合框上) was removed on
        # 2026-10-04.  Nothing read it -- not this window, not ``winter_agent_v2`` -- so those
        # comboboxes were controls that changed no policy, and a control that changes nothing
        # is worse than no control: the operator would believe a limit had been set.  The
        # enforced limits are real and are shown on 运行·策略 as a read-only list.
        self.policy_enabled = {
            name: tk.BooleanVar(value=enabled)
            for name, enabled in load_policy_categories(POLICY_STATE_PATH, POLICY_CATEGORIES).items()
        }
        self._build()
        self._save_policy_state()
        self._save_panel_state()
        self._enforce_retention()
        root.after(100, self._drain_events)
        root.after(250, self._tick)
        root.after(1000, self._refresh_runtime_snapshot)
        self.refresh()
        # The auto-start lives in ``_maybe_autostart`` (called once from ``main``)
        # and nowhere else: this block used to schedule a second ``start`` at
        # 1800 ms while ``main`` scheduled one at 1200 ms, so two paths decided
        # the same thing and only the guard inside ``start`` kept them apart.

    def _style(self) -> None:
        s = ttk.Style()
        if "clam" in s.theme_names():
            s.theme_use("clam")
        s.configure(".", background=BG, foreground=TEXT, fieldbackground=PANEL2, bordercolor="#263849")
        s.configure("TFrame", background=BG); s.configure("Card.TFrame", background=PANEL); s.configure("Card2.TFrame", background=PANEL2)
        s.configure("TLabel", background=BG, foreground=TEXT, font=("Microsoft YaHei UI", 9))
        s.configure("Muted.TLabel", foreground=MUTED); s.configure("Title.TLabel", font=("Microsoft YaHei UI", 20, "bold"))
        s.configure("Section.TLabel", font=("Microsoft YaHei UI", 11, "bold")); s.configure("Value.TLabel", font=("Microsoft YaHei UI", 12, "bold"))
        s.configure("Accent.TButton", font=("Microsoft YaHei UI", 10, "bold"), padding=(16, 9), background="#1876ac")
        s.configure("TaskEnabled.TButton", font=("Microsoft YaHei UI", 10, "bold"), padding=(16, 12), background="#176b50", foreground="#dcfff1")
        s.configure("TaskDisabled.TButton", font=("Microsoft YaHei UI", 10), padding=(16, 12), background=PANEL2, foreground=MUTED)
        s.configure("TaskUnavailable.TButton", font=("Microsoft YaHei UI", 10), padding=(16, 12), background="#101923", foreground="#607181")
        s.map("TaskEnabled.TButton", background=[("active", "#1d8563")])
        s.map("TaskDisabled.TButton", background=[("active", "#263849")])
        s.configure("TButton", padding=(11, 8), background=PANEL2); s.configure("TNotebook", background=BG, borderwidth=0)
        s.configure("TNotebook.Tab", padding=(16, 9), background=PANEL, foreground=MUTED)
        s.map("TNotebook.Tab", background=[("selected", PANEL2)], foreground=[("selected", TEXT)])
        s.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=27)
        s.configure("Treeview.Heading", background=PANEL2, foreground=TEXT); s.configure("TCheckbutton", background=PANEL)

    def _build(self) -> None:
        self._style()
        shell = ttk.Frame(self.root, padding=(16, 12)); shell.pack(fill="both", expand=True)
        header = ttk.Frame(shell, style="Card.TFrame", padding=(16, 12)); header.pack(fill="x")
        title = ttk.Frame(header, style="Card.TFrame"); title.pack(side="left")
        ttk.Label(title, text="Winter Agent OS V2", style="Title.TLabel", background=PANEL).pack(anchor="w")
        ttk.Label(title, text="《无尽冬日》AI 指挥中心", style="Muted.TLabel", background=PANEL).pack(anchor="w")
        status = ttk.Frame(header, style="Card.TFrame"); status.pack(side="right", expand=True, fill="x", padx=(26, 0))
        # Eight cells, one word each, from one vocabulary (``state_truth.health_of``).
        # Long sentences used to sit here -- "MAA 正在参与生产" and the like -- which grew
        # with every capability and could not be scanned.  A model name still appears only
        # as WorkBuddy's second-level detail: this row is the four frozen layers plus the
        # three system services, and nothing else.
        self.indicators: dict[str, tk.Label] = {}
        for i, (label, key) in enumerate(SYSTEM_INDICATORS):
            cell = ttk.Frame(status, style="Card.TFrame"); cell.grid(row=0, column=i, padx=6, sticky="w")
            ttk.Label(cell, text=label, style="Muted.TLabel", background=PANEL).pack(anchor="w")
            mark = tk.Label(cell, textvariable=self.values[key], background=PANEL, fg=MUTED)
            mark.pack(anchor="w")
            self.indicators[key] = mark
        self.tabs = ttk.Notebook(shell); self.tabs.pack(fill="both", expand=True, pady=(10, 0))
        self._overview(); self._goals(); self._strategy(); self._event_goal(); self._capabilities(); self._auto_development(); self._system()
        # Opening a tab is the moment its data must be current, not the next tick.
        self.tabs.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _tab(self, name: str, scroll: bool = False) -> ttk.Frame:
        f = ttk.Frame(self.tabs, padding=10); self.tabs.add(f, text=TAB_GROUP.get(name, name))
        # Index order equals add order, which is what _current_tab_name() relies on.
        self._tab_names.append(name)
        return self._scroll_area(f) if scroll else f

    def _register_tab_refresh(self, name: str, fn) -> None:
        """Declare that ``fn`` fills tab ``name``, so the tick can skip it when hidden."""
        self._tab_refreshers.setdefault(name, []).append(fn)

    def _current_tab_name(self) -> str | None:
        """The tab the operator is actually looking at, or None before first paint."""
        try:
            index = self.tabs.index("current")
        except tk.TclError:
            return None
        if 0 <= index < len(self._tab_names):
            return self._tab_names[index]
        return None

    def _tab_visible(self, name: str) -> bool:
        return self._current_tab_name() == name

    def _refresh_visible_tabs(self) -> None:
        """Refresh only the on-screen tab's own data.

        The always-on top strip (runtime snapshot, truth dots, device state) stays on
        the fast tick either way -- those are the six words the whole window is read
        for, and they are cheap now.  What is skipped is the per-tab body work: the
        capability table, the development board.
        """
        name = self._current_tab_name()
        if name is None:
            return
        for fn in self._tab_refreshers.get(name, ()):
            try:
                fn()
            except Exception:  # noqa: BLE001 - one page must not stall the tick
                pass

    def _on_tab_changed(self, _event=None) -> None:
        self._refresh_visible_tabs()

    def _scroll_area(self, parent: ttk.Frame) -> ttk.Frame:
        """Wrap tall tab content in a scrollbar.

        Measured rather than guessed: with the 2026-09-17 information architecture
        the 总览 tab requested 1282 px of height, 自动开发 1101 and 能力 912, while the
        window hands the notebook about 660.  Tk does not scroll a notebook tab, so
        everything below the fold -- including the run controls -- was simply
        clipped and unreachable.  This is the standard canvas-plus-inner-frame pair,
        not a second layout system: the frame the tab returns is the same frame it
        would have returned before, so every existing `pack`/`grid` call inside is
        unchanged.

        The wheel binding is scoped to pointer enter/leave so it cannot capture
        scrolling from the treeviews, which scroll themselves.
        """
        canvas = tk.Canvas(parent, bg=BG, highlightthickness=0, borderwidth=0)
        bar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas, padding=10)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y"); canvas.pack(side="left", fill="both", expand=True)
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))

        def on_wheel(event: tk.Event) -> None:
            canvas.yview_scroll(-int(event.delta / 120), "units")

        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", on_wheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))
        return inner

    # -- how old the evidence behind every number is ------------------------------------
    #
    # One table, one place.  Measured 2026-10-04: the console read 28 data files and checked
    # the age of exactly one of them, so a 24.9-day-old ``goal_coverage.json`` and a fresh
    # ``runtime_snapshot.json`` rendered identically.  These three helpers are the whole of
    # the cure: ``_freshness`` holds the table, ``_source_age_note`` is how a column admits
    # its source has stopped moving, and ``_attention_with_sources`` is how that admission
    # reaches the one card the operator is told to watch.

    def _freshness(self) -> tuple:
        """``(all ages, keys of sources that aged out while a writer should have run)``.

        The second element is deliberately *not* "every old file": ``stale_among`` returns
        nothing at all when AUTO is down, because when nothing is running nothing writes these
        files and their age is the design, not a fault.  Reporting them would be the "狼来了"
        failure the operator named, and it would train them to ignore the one notice that
        matters.

        Only the *ages* are memoised.  Caching the AUTO verdict alongside them would freeze it
        for the whole window, so pressing 开始 would not raise the alarm for up to
        ``FRESHNESS_TTL_SECONDS`` and pressing 停止 would not clear it for the same time.
        """
        from winter_agent_v2 import source_freshness

        now = time.monotonic()
        ages = getattr(self, "_freshness_ages", None)
        if ages is None or now - getattr(self, "_freshness_at", 0.0) >= FRESHNESS_TTL_SECONDS:
            ages = source_freshness.all_ages(ROOT)
            self._freshness_ages, self._freshness_at = ages, now
        running = self.process is not None and self.process.poll() is None
        ends = {age.key for age in source_freshness.stale_among(ages, auto_running=running)}
        return ages, ends

    def _source_age_note(self, key: str) -> str:
        """``""`` when the source is current, otherwise a suffix naming how old it is.

        Empty-when-fine so a caller can concatenate it unconditionally and get the honest
        line either way, instead of writing an ``if`` at every use site and eventually
        forgetting one -- which is how the columns got into this state.

        This is a statement about the file, not an alarm: it does not consult AUTO, so it also
        fires while the system is paused.  ``_attention_with_sources`` is the alarming half and
        that one does consult AUTO; the split is the difference between "written 8 days ago"
        (always worth saying) and "something stopped writing" (only a fault if a writer should
        have been running).
        """
        ages, _ = self._freshness()
        age = ages.get(key)
        if age is None or age.fresh:
            return ""
        return f"　（{age.source.label}{age.age_text()}，已过期）"

    def _attention_with_sources(self, lines: list) -> list:
        """Prepend the stale-source lines the operator must see, then the truth conflicts."""
        ages, ends = self._freshness()
        if not ends:
            return lines
        worst = sorted((ages[k] for k in ends), key=lambda a: -(a.age_seconds or 0.0))
        head = [f"⚠ 数据源已过期：{a.source.key}（{a.age_text()}）· 用于 {a.source.used_by}"
                for a in worst[:2]]
        return head + list(lines)

    # -- tiers: an abnormal block may not stay folded -------------------------------------
    #
    # The operator's rule is that an L3 block folds **except** when it is over a threshold, in an
    # abnormal state, or waiting on a decision -- and then it must surface by itself.  ``_fold``
    # is the declaration, ``_sync_folds`` is the acting half, and the guard is that a block with
    # an active reason always carries the reason in its header even when it is shut.

    def _fold(self, parent: Any, *, key: str, title: str, level: str,
              sources: tuple[str, ...] = (), escalate: Callable[[], str] | None = None,
              annotate: Callable[[], str] | None = None,
              style: str = "Card.TFrame", padding: tuple[int, int] = (12, 10),
              badge_wrap: int = 560, grid: dict | None = None,
              pack: dict | None = None) -> Any:
        """Declare one collapsible block and return **the frame to draw its content into**.

        Returning the body rather than the container is what keeps this from being a second
        layout system: every existing ``pack``/``grid`` call inside a block is unchanged, because
        the frame they receive is the same kind of frame they received before.  The container is
        placed through ``grid=``/``pack=`` here so a call site stays a single statement and the
        geometry stays visible where the block is declared.
        """
        background = PANEL2 if "Card2" in style else PANEL
        outer = ttk.Frame(parent, style=style, padding=padding)
        head = ttk.Frame(outer, style=style)
        head.pack(fill="x")
        toggle = ttk.Label(head, text="", style="Section.TLabel", background=background,
                           cursor="hand2")
        toggle.pack(side="left")
        badge = tk.StringVar(value="")
        ttk.Label(head, textvariable=badge, background=background, foreground=BAD,
                  font=("Microsoft YaHei UI", 8), wraplength=badge_wrap,
                  justify="right").pack(side="right")
        body = ttk.Frame(outer, style=style)
        fold = Fold(key=key, title=title, level=level, outer=outer, body=body, toggle=toggle,
                    badge=badge, escalate=escalate, annotate=annotate, sources=sources)
        toggle.bind("<Button-1>", lambda _event: self._toggle_fold(key))
        folds = getattr(self, "_folds", None)
        if folds is None:
            folds = {}
            self._folds = folds
        folds[key] = fold
        fold.paint()
        if grid is not None:
            outer.grid(**grid)
        if pack is not None:
            outer.pack(**pack)
        return body

    def _toggle_fold(self, key: str) -> None:
        """The operator opened or shut a block by hand; remember that it was their call."""
        fold = getattr(self, "_folds", {}).get(key)
        if fold is None:
            return
        fold.expanded = not fold.expanded
        fold.auto_opened = False
        # A hand-shut block stays shut for **this** fault -- re-opening it on the next tick would
        # be the window arguing with the person using it.  The header keeps the reason either
        # way, so nothing is hidden, and ``_sync_folds`` gives a *new* fault a fresh chance.
        fold.user_closed = not fold.expanded
        fold.paint()

    def _stale_source_note(self, *keys: str) -> Callable[[], str]:
        """Mark a block whose files have stopped being written -- **without** opening it.

        Reads ``_freshness()``'s second element rather than the raw ages on purpose: that element
        is ``source_freshness.stale_among``'s answer, so the TTL rule *and* the AUTO gate stay
        owned by the one module that documents them.  Reporting whenever a file was merely old
        would fire every time the operator paused AUTO, which is the "狼来了" failure the audit
        warned about -- an old file is only a fault while a writer should have been running.

        This is ``annotate``, not ``escalate``: §六's stale-source row surfaces the *cells* that
        use the file and names the file in 需要关注, both of which are already done elsewhere
        (``_source_age_note`` and ``_attention_with_sources``).  Opening the block as well was
        the mistake described on ``Fold``.
        """
        def check() -> str:
            ages, ends = self._freshness()
            hit = [key for key in keys if key in ends]
            if not hit:
                return ""
            worst = max((ages[key] for key in hit), key=lambda age: -(age.age_seconds or 0.0))
            return (f"{worst.source.label} 已停更（{worst.age_text()}），"
                    f"这一块的数字不是当前读数")
        return check

    def _escalate_workbuddy(self) -> str:
        """Gateway unhealthy, or the queue has something nobody consumed.

        Both halves are read, not invented: the first is ``health_of`` on the same
        ``gateway_health`` value the top-bar cell is painted from -- so this badge and that cell
        cannot grade the gateway differently -- and the second reuses the audit's own
        ``WORKBUDDY_QUEUE_STUCK`` anomaly rather than a row count with a threshold of my choosing.

        ``unknown`` deliberately does **not** open this block.  It means the probe did not answer,
        which is a fact about the panel's own reach rather than about the development platform,
        and the top-bar cell already prints 未确认 for it -- so the fact is visible in L1 anyway.
        """
        value = getattr(self, "_gateway_value", None)
        if value is not None:
            from winter_agent_v2.state_truth import health_of

            word, colour = health_of(value)
            if colour in ("bad", "warn"):
                return f"WorkBuddy 网关{word}"
        stuck = sorted(kind for kind in getattr(self, "_attention_kinds", ())
                       if str(kind).startswith("WORKBUDDY_"))
        if stuck:
            return f"{stuck[0]}：队列里有东西一直没被消费"
        return ""

    def _worker_exits_since_window(self) -> int:
        """How many workers died *while this window was open* -- the only reading the counters
        support, since both are cumulative for the machine.

        Extracted so the watchdog block and the 能力 page's runtime-quality block cannot end up
        grading the same field by two different standards; §57 is the record of what the literal
        ``> 0`` did here.
        """
        base = getattr(self, "_exits_baseline", None)
        now = getattr(self, "_unexpected_exits", None)
        if base is None or now is None:
            return 0
        return max(0, now - base)

    def _escalate_capability_runtime(self) -> str:
        """§六's row for the 能力 page: ``runtime_quality`` 四格 is L3, "``unexpected_worker_exits``
        非 0 必须浮上来".

        Same correction as the watchdog block's (MEMORY §57): the field is cumulative, so
        「非 0」 was implemented as *growth since the window opened*.  The two rules share
        ``_worker_exits_since_window`` rather than each reading the baselines.
        """
        grew = self._worker_exits_since_window()
        if grew:
            return f"窗口打开以来有 {grew} 次意外的 Worker 退出"
        return ""

    def _escalate_dev_loop(self) -> str:
        """§六: 「自主开发闭环 **L1 当有断点**，否则 L3」.

        Graded from ``closure_card``'s own ``ok`` / ``breakpoint`` fields rather than from the
        sentence the block prints.  That distinction is not fussiness: a rule that parses a
        *display* string breaks the moment the wording improves, and this project already has a
        written rule about display strings not being parseable input.

        Two states deliberately do **not** open the block.  ``ok`` false means the loop has not
        produced a card at all -- on a fresh install that is the normal state, and opening it
        would be the wolf-cry this whole mechanism exists to avoid.  A card with no ``breakpoint``
        is a PASS, which is the one case that must stay folded.
        """
        card = getattr(self, "_closure_card", None)
        if not card or not card.get("ok"):
            return ""
        breakpoint = str(card.get("breakpoint") or "").strip()
        return f"闭环卡在：{breakpoint}" if breakpoint else ""

    def _escalate_dev_failures(self) -> str:
        """§六: 「最近失败分类 **L2**（次数超阈值浮 L1）」, with the threshold taken from
        ``failure_priority`` -- the project's own P0/P1/P2 bucketing -- rather than invented.

        ``live_failure_counts`` is the cached scan the page already uses, so asking here costs
        nothing per tick (it re-parses the episode log only when the log changes).
        """
        try:
            counts = live_failure_counts()
        except Exception:  # noqa: BLE001 - a missing ledger is not an alarm
            return ""
        worst = [(count, failure) for failure, count in counts.items()
                 if failure_priority(count) == "P0"]
        if not worst:
            return ""
        count, failure = max(worst)
        return f"{human_reason(failure)} 已出现 {count} 次（P0）"

    def _escalate_watchdog(self) -> str:
        """The one watchdog rule, used by **both** blocks that show the watchdog.

        The 总览 block and the 系统 page block call this same method rather than each writing
        their own, because a block and its indicator grading one source differently is how the
        audit's P0-3 class of defect happens.

        Two halves, and the second is §六's own threshold row (``unexpected_worker_exits`` > 0 ·
        ``watchdog_restart_count`` 增长 → 看门狗块浮到 L1):

        * the truth value first, because the V2 top-bar dot is painted from that very value --
          a restart storm cannot make the dot say 异常 while this block stays folded;
        * then the two *counters*, because the truth value does not necessarily move for a
          single unexpected exit, and one worker dying and being restarted is a fault the
          operator must be able to see without clicking anything.

        **Both counters are read as growth against the value this window first saw, not against
        zero -- including the unexpected-exit half, where §六 writes the literal ``> 0``.**  The
        literal was implemented first and measurement killed it on this very machine: the two
        fields are cumulative (``previous.unexpected_worker_exits + 1``, persisted in the runtime
        store), and the live values here are ``unexpected_worker_exits = 22`` and
        ``watchdog_restart_count = 28``.  ``> 0`` therefore measures the machine's *history*
        rather than the present, and would hold this block permanently open on a host whose
        workers have ever died once -- the "狼来了" failure mode ``source_freshness`` warns about
        in its own docstring, and the same mistake the first commit in this series had to fix for
        stale sources.  Growth means "it happened while you were watching", which is the only
        reading under which the threshold says anything about now.  §六's *intent* -- an
        unexpected exit is the signal -- is kept; its arithmetic is corrected to match what the
        fields actually hold.
        """
        value = getattr(self, "_watchdog_value", None)
        if value is not None:
            from winter_agent_v2.state_truth import health_of

            word, colour = health_of(value)
            if colour in ("bad", "warn"):
                return f"看门狗{word}"
        exits_grew = self._worker_exits_since_window()
        if exits_grew:
            return (f"窗口打开以来有 {exits_grew} 次意外的 Worker 退出"
                    f"（累计 {getattr(self, '_unexpected_exits', 0)}）")
        restarts_base = getattr(self, "_restart_baseline", None)
        restarts = getattr(self, "_restart_count", None)
        if restarts_base is not None and restarts is not None and restarts > restarts_base:
            return f"看门狗重启次数从 {restarts_base} 涨到 {restarts}"
        return ""

    def _sync_folds(self) -> None:
        """Open what must float, mark what went stale, shut what healed, and never hide a reason.

        Four behaviours, all four of them guardable:

        * a block with an ``escalate`` reason opens itself -- no click needed;
        * a block with only an ``annotate`` note stays folded but **says so in its header**, which
          is the difference between "folded" and "hidden";
        * a block the alarm opened shuts itself again once the reason clears -- but a block the
          operator opened deliberately is not yanked shut;
        * the reason goes in the header regardless of state.
        """
        for fold in getattr(self, "_folds", {}).values():
            reason = run_fold_rule(fold.escalate)   # may open the block
            note = "" if reason else run_fold_rule(fold.annotate)  # header only
            said = reason or note
            if said != fold.last_reason:
                # A *new* fault gets its own chance to surface, even if the operator shut this
                # block earlier: they silenced the previous fault, not this one.
                fold.user_closed = False
                fold.last_reason = said
            if reason and not fold.expanded and not fold.user_closed:
                fold.expanded = True
                fold.auto_opened = True
            elif not reason and fold.expanded and fold.auto_opened:
                fold.expanded = False
                fold.auto_opened = False
            fold.badge.set(f"⚠ {said}" if said else "")
            fold.paint()

    def _overview(self) -> None:
        tab = self._tab("总览", scroll=True); tab.rowconfigure(0, weight=1); tab.columnconfigure(1, weight=1)
        left = ttk.Frame(tab, style="Card.TFrame", padding=14, width=215); left.grid(row=0, column=0, sticky="nsew", padx=(0, 8)); left.grid_propagate(False)
        center = ttk.Frame(tab, style="Card.TFrame", padding=10); center.grid(row=0, column=1, sticky="nsew")
        right = ttk.Frame(tab, style="Card.TFrame", padding=14, width=270); right.grid(row=0, column=2, sticky="nsew", padx=(8, 0)); right.grid_propagate(False)
        ttk.Label(left, text="当前角色", style="Section.TLabel", background=PANEL).pack(anchor="w")
        # Two literals used to live here: ``text="xhw"`` and ``text="● 在线"``.  The first
        # printed a role nobody had observed, and the second claimed the device was online
        # unconditionally.  Both now read the one truth projection, so this cell cannot
        # disagree with the rest of the system -- and when the role has not been read off
        # the *current* client it says so instead of printing a confident old name.
        ttk.Label(left, textvariable=self.values["role"], style="Value.TLabel",
                  background=PANEL, wraplength=195, justify="left").pack(anchor="w", pady=(10, 0))
        ttk.Label(left, textvariable=self.values["role_state"], background=PANEL,
                  wraplength=195, justify="left").pack(anchor="w")
        ttk.Label(left, textvariable=self.values["truth"], background=PANEL, foreground=BAD,
                  wraplength=195, justify="left").pack(anchor="w")
        ttk.Label(left, textvariable=self.values["device"], background=PANEL,
                  wraplength=195, justify="left").pack(anchor="w")
        ttk.Label(left, textvariable=self.values["march"], style="Muted.TLabel", background=PANEL).pack(anchor="w", pady=(3, 16))
        ttk.Separator(left).pack(fill="x", pady=(0, 12))
        # L2 (§六): the same six figures the 运行·目标 page already owns, so they fold.  It
        # carries no rule of its own, and that is a decision written into ``INERT_FOLDS``
        # rather than an omission nobody noticed.
        today_body = self._fold(left, key="today", title="今日 Goal 摘要", level=L2,
                                pack=dict(fill="x"), padding=(0, 0), badge_wrap=150)
        self.today: dict[str, tk.StringVar] = {}
        for task in ("活动低保", "情报", "体力", "训练", "科研", "建筑"):
            row = ttk.Frame(today_body, style="Card.TFrame"); row.pack(fill="x", pady=3)
            ttk.Label(row, text=task, background=PANEL).pack(side="left")
            self.today[task] = tk.StringVar(value=PENDING)
            ttk.Label(row, textvariable=self.today[task], style="Muted.TLabel", background=PANEL).pack(side="right")
        bar = ttk.Frame(center, style="Card.TFrame"); bar.pack(fill="x", pady=(0, 8))
        ttk.Label(bar, text="游戏实时画面", style="Section.TLabel", background=PANEL).pack(side="left")
        choice = ttk.Combobox(bar, textvariable=self.preview_mode, values=("原始画面", "Vision", "OCR", "识别结果"), width=12, state="readonly")
        choice.pack(side="right"); choice.bind("<<ComboboxSelected>>", lambda _e: self._render_preview())
        # Fixed-height holder: inside a scroll area the preview has no leftover space
        # to expand into, so without a declared height it would render at whatever
        # the last label measured and jump when the first screenshot arrived.
        holder = tk.Frame(center, bg="#070b10", height=300)
        holder.pack(fill="both", expand=True); holder.pack_propagate(False)
        self.preview = tk.Label(holder, text="正在获取 MuMu 截图…", bg="#070b10", fg=MUTED, font=("Microsoft YaHei UI", 11))
        self.preview.pack(fill="both", expand=True)
        # Debounced: <Configure> fires continuously while a window is dragged, and
        # each fire re-ran a full decode plus a LANCZOS resize (~25 ms).  Dragging the
        # window therefore stuttered for the whole drag.  One render 120 ms after the
        # last resize event is indistinguishable and costs one pass.
        self.preview.bind("<Configure>", lambda _e: self._schedule_preview_render())
        self.preview_meta = tk.StringVar(value=NO_DATA)
        ttk.Label(center, textvariable=self.preview_meta, style="Muted.TLabel", background=PANEL).pack(anchor="w", pady=(8, 0))
        ttk.Label(right, text="当前决策", style="Section.TLabel", background=PANEL).pack(anchor="w")
        # V2 decides, MAA executes.  The backend is the first thing in this column
        # because "which hands moved" is the fact that makes every other line here
        # trustworthy or not: a measurement taken through the ADB fallback is not
        # the same measurement as one taken through MAA.
        ttk.Label(right, text="执行后端", style="Muted.TLabel", background=PANEL).pack(anchor="w", pady=(10, 1))
        ttk.Label(right, textvariable=self.values["backend"], style="Value.TLabel", background=PANEL, wraplength=235, justify="left").pack(anchor="w")
        ttk.Label(right, textvariable=self.values["backend_detail"], style="Muted.TLabel", background=PANEL, wraplength=235, justify="left").pack(anchor="w")
        ttk.Label(right, text="V2 决定做什么 · MAA 负责执行 · Verifier 判定成功", style="Muted.TLabel", background=PANEL, wraplength=235, justify="left").pack(anchor="w", pady=(2, 0))
        # Three lines stay open: 现在在干什么.  The six below them are the *expansion* of that
        # answer (§六 L2), and 本次启动统计 is a session counter (L3).  The split is why the
        # column no longer asks the eye to cross nine label/value pairs to reach the three that
        # decide anything.
        for label, key, style in (("当前 Goal", "task_cn", "Value.TLabel"),
                                  ("当前 Universal Skill", "skill", "Muted.TLabel"),
                                  ("当前状态", "runtime_state", "Value.TLabel")):
            ttk.Label(right, text=label, style="Muted.TLabel", background=PANEL).pack(anchor="w", pady=(10, 1))
            ttk.Label(right, textvariable=self.values[key], style=style, background=PANEL, wraplength=235, justify="left").pack(anchor="w")
        detail = self._fold(right, key="decision", title="决策依据", level=L2,
                            pack=dict(fill="x", pady=(10, 0)), badge_wrap=210)
        for label, key, style in (("为什么执行", "reason", "TLabel"),
                                  ("Preconditions", "preconditions", "TLabel"), ("Verifier", "verifier", "TLabel"),
                                  ("下一步", "next", "TLabel"), ("风险", "risk", "TLabel"),
                                  ("决策置信度", "confidence_decision", "Value.TLabel")):
            ttk.Label(detail, text=label, style="Muted.TLabel", background=PANEL).pack(anchor="w", pady=(10, 1))
            ttk.Label(detail, textvariable=self.values[key], style=style, background=PANEL, wraplength=235, justify="left").pack(anchor="w")
        stats_body = self._fold(right, key="stats", title="本次启动统计", level=L3,
                                pack=dict(fill="x", side="bottom"), badge_wrap=210)
        ttk.Label(stats_body, textvariable=self.values["stats"], style="Muted.TLabel", background=PANEL, wraplength=235).pack(anchor="w")
        # Row 1: coverage and verification progress, first thing the eye lands on.
        # Row 1, above everything else: the one question the 2026-10-04 audit found nowhere in
        # the window -- 需要我干预吗.  It sits first because it is the only cell whose answer
        # changes what the operator does next; every block beneath it is detail for the case
        # where the answer is 「需要」.  Same reason the report put it at L1 and marked it the
        # only missing L1 item.
        verdict = ttk.Frame(tab, style="Card.TFrame", padding=(12, 10))
        verdict.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        ttk.Label(verdict, text="需不需要干预", style="Section.TLabel", background=PANEL).pack(anchor="w")
        ttk.Label(verdict, textvariable=self.values["intervene"], background=PANEL,
                  wraplength=1150, justify="left").pack(anchor="w", pady=(5, 0))
        ttk.Label(verdict, text="state_truth 需要的关注项 + 数据源新鲜度 · config/policy_state.json",
                  style="Muted.TLabel", background=PANEL, font=("Microsoft YaHei UI", 7),
                  wraplength=1150, justify="left").pack(anchor="w", pady=(4, 0))
        # L3: eight derived resource counts, whose only source is a 7-day-budget catalog.  Folded
        # because they do not change what the operator does next while the catalog is current.
        #
        # ``annotate``, not ``escalate``: when the catalog goes stale this block must *say* so,
        # and the 需要关注 card must name the file -- but it must not open itself.  See ``Fold``
        # for the measurement that settled this (on real data it would sit open permanently).
        kpis = self._fold(tab, key="kpi", title="资源与覆盖 KPI", level=L3,
                          sources=KPI_FOLD_SOURCES,
                          annotate=self._stale_source_note(*KPI_FOLD_SOURCES),
                          grid=dict(row=2, column=0, columnspan=3, sticky="ew", pady=(10, 0)),
                          padding=(10, 10))
        self.kpi_source: dict[str, tk.StringVar] = {}
        for i, (key, meta) in enumerate(CATALOG_META.items()):
            card = ttk.Frame(kpis, style="Card2.TFrame", padding=(12, 7)); card.grid(row=0, column=i, sticky="ew", padx=4); kpis.columnconfigure(i, weight=1)
            ttk.Label(card, text=meta[0], style="Muted.TLabel", background=PANEL2).pack(anchor="w")
            self.kpi[key] = tk.StringVar(value=NO_DATA)
            ttk.Label(card, textvariable=self.kpi[key], style="Value.TLabel", background=PANEL2).pack(anchor="w")
            self.kpi_source[key] = tk.StringVar(value=meta[1])
            ttk.Label(card, textvariable=self.kpi_source[key], style="Muted.TLabel", background=PANEL2, wraplength=140, justify="left", font=("Microsoft YaHei UI", 7)).pack(anchor="w")
        # Row 2: what the development platform is doing right now.  L3 (§六), with its own rule:
        # an unhealthy gateway or an unconsumed queue opens it.  The gateway line moved inside the
        # block because it is the second-level detail of this heading -- the top bar's WorkBuddy
        # cell is where "is it reachable" is answered from L1.
        wb = self._fold(tab, key="workbuddy", title="WorkBuddy 自动开发", level=L3,
                        sources=("learning/workbuddy_escalations.jsonl",),
                        escalate=self._escalate_workbuddy,
                        grid=dict(row=3, column=0, columnspan=3, sticky="ew", pady=(10, 0)))
        ttk.Label(wb, textvariable=self.values["wb_gateway"], style="Muted.TLabel", background=PANEL).pack(anchor="w")
        grid = ttk.Frame(wb, style="Card.TFrame"); grid.pack(fill="x", pady=(6, 0))
        for index, (label, key) in enumerate((("状态", "wb_state"), ("当前 Capability", "wb_capability"),
                                              ("Escalation Reason", "wb_reason"), ("Job ID", "wb_job"),
                                              ("当前模型", "wb_model"), ("运行时间", "wb_duration"),
                                              ("Job 状态", "wb_job_state"), ("Live Improvement", "wb_improvement"))):
            cell = ttk.Frame(grid, style="Card.TFrame"); cell.grid(row=index // 4, column=index % 4, sticky="w", padx=(0, 22), pady=2)
            ttk.Label(cell, text=label, style="Muted.TLabel", background=PANEL).pack(anchor="w")
            ttk.Label(cell, textvariable=self.values[key], background=PANEL, wraplength=190, justify="left").pack(anchor="w")
            grid.columnconfigure(index % 4, weight=1)
        result = ttk.Frame(grid, style="Card.TFrame"); result.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        ttk.Label(result, text="最近结果", style="Muted.TLabel", background=PANEL).pack(anchor="w")
        ttk.Label(result, textvariable=self.values["wb_result"], background=PANEL, wraplength=1150, justify="left").pack(anchor="w")
        # L2: seven read-only projections of the game's own queues.  Folded, because they are long
        # stable and the eye should not cross them to reach the verdict above.  No rule of its own
        # -- ``_compact`` returns a status *word*, not a count, so any "backlog" threshold here
        # would be mine rather than the system's; the reason is written into ``INERT_FOLDS``.
        cards = self._fold(tab, key="queues", title="生产队列", level=L2,
                           grid=dict(row=4, column=0, columnspan=3, sticky="ew", pady=(10, 0)),
                           padding=(10, 10))
        self.queues: dict[str, tk.StringVar] = {}
        for i, name in enumerate(("行军", "建筑", "科技", "训练", "Intel", "联盟", "活动")):
            card = ttk.Frame(cards, style="Card2.TFrame", padding=(14, 8)); card.grid(row=0, column=i, sticky="ew", padx=4); cards.columnconfigure(i, weight=1)
            ttk.Label(card, text=name, style="Muted.TLabel", background=PANEL2).pack(anchor="w")
            self.queues[name] = tk.StringVar(value=PENDING); ttk.Label(card, textvariable=self.queues[name], style="Value.TLabel", background=PANEL2).pack(anchor="w")
        # Rows 4-6: the four questions the operator wants answered without opening a log
        # -- why nothing is moving, whether production is really using MAA, what the
        # development platform is doing, and whether coverage is growing.  Every line here
        # is a `state_truth` value, so the panel cannot hold a second opinion about any of
        # them, and any line that cannot be confirmed says 未确认 / 未知 rather than a
        # plausible-looking stale number.
        #
        # Split across two tiers by ``OVERVIEW_FACT_TIERS``: 现在为什么不动 is the answer to
        # 「有没有卡住」 and stays open at L1; the other three are L2.  One loop over the one
        # declaration, dispatching on the tier, so the labels are still typed exactly once and
        # the two guards on this declaration stay meaningful.
        head_facts = ttk.Frame(tab, style="Card.TFrame", padding=(12, 10))
        head_facts.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        head_facts.columnconfigure(0, weight=1)
        fact_sources = tuple(row[3] for row in OVERVIEW_FACTS
                             if OVERVIEW_FACT_TIERS.get(row[1]) != L1)
        facts = self._fold(tab, key="facts", title="事实卡（逐项来源）", level=L2,
                           sources=fact_sources,
                           annotate=self._stale_source_note(*fact_sources),
                           grid=dict(row=6, column=0, columnspan=3, sticky="ew", pady=(10, 0)))
        facts.columnconfigure(0, weight=1); facts.columnconfigure(1, weight=1)
        # The source line under each card carries the age of the file it names, set on the tick
        # by ``_refresh_truth``.  All four of these figures are *derived* -- which is exactly
        # the surface that made a 24.9-day-old source look like a current reading.
        self.fact_source: dict[str, tk.StringVar] = {}
        folded = 0
        for column, (title, key, source, source_key) in enumerate(OVERVIEW_FACTS):
            if OVERVIEW_FACT_TIERS.get(key) == L1:
                cell_parent, wraplength = head_facts, 1150
                where = dict(row=0, column=column, sticky="nsew", padx=4)
            else:
                cell_parent, wraplength = facts, 560
                where = dict(row=folded // 2, column=folded % 2, sticky="nsew", padx=4, pady=4)
                folded += 1
            cell = ttk.Frame(cell_parent, style="Card2.TFrame", padding=(12, 8))
            cell.grid(**where)
            ttk.Label(cell, text=title, style="Section.TLabel", background=PANEL2).pack(anchor="w")
            ttk.Label(cell, textvariable=self.values[key], background=PANEL2,
                      wraplength=wraplength, justify="left").pack(anchor="w", pady=(4, 0))
            self.fact_source[key] = tk.StringVar(value=source)
            ttk.Label(cell, textvariable=self.fact_source[key], style="Muted.TLabel",
                      background=PANEL2, font=("Microsoft YaHei UI", 7), wraplength=wraplength,
                      justify="left").pack(anchor="w", pady=(4, 0))

        lower = ttk.Frame(tab, style="Card.TFrame", padding=(12, 10))
        lower.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        lower.columnconfigure(0, weight=1); lower.columnconfigure(1, weight=1)
        # 需要关注 is the one block that is L1 *and* built like a plain card: it is where the
        # window says a fault exists, so it cannot be the thing that folds -- folding it would
        # let the window hide exactly what the fold rule exists to surface.  The audit's
        # exception table lists it as permanent L1 for the same reason.
        attention_cell = ttk.Frame(lower, style="Card2.TFrame", padding=(12, 8))
        attention_cell.grid(row=0, column=0, sticky="nsew", padx=4)
        ttk.Label(attention_cell, text="需要关注", style="Section.TLabel", background=PANEL2).pack(anchor="w")
        ttk.Label(attention_cell, textvariable=self.values["attention"], background=PANEL2,
                  wraplength=560, justify="left").pack(anchor="w", pady=(4, 0))
        ttk.Label(attention_cell,
                  text="state_truth：STATE_CONFLICT / 角色未知 / 队列卡住 / 无目标进展 / MAA 降级",
                  style="Muted.TLabel", background=PANEL2,
                  font=("Microsoft YaHei UI", 7), wraplength=560,
                  justify="left").pack(anchor="w", pady=(4, 0))
        # L3, and the one block here whose rule is an indicator's own grade: the V2 top-bar dot is
        # painted from the very same ``watchdog`` value, so a restart storm cannot leave the dot
        # red while this stays folded.
        watchdog_cell = self._fold(lower, key="watchdog", title="看门狗与版本", level=L3,
                                   style="Card2.TFrame", padding=(12, 8), badge_wrap=260,
                                   escalate=self._escalate_watchdog,
                                   grid=dict(row=0, column=1, sticky="nsew", padx=4))
        ttk.Label(watchdog_cell, textvariable=self.values["watchdog"], background=PANEL2,
                  wraplength=560, justify="left").pack(anchor="w")
        ttk.Label(watchdog_cell, text="learning/runtime_snapshot.json · config/control_panel_state.json",
                  style="Muted.TLabel", background=PANEL2, font=("Microsoft YaHei UI", 7),
                  wraplength=560, justify="left").pack(anchor="w", pady=(4, 0))

        # 动作成功 ≠ 目标取得进展.  The operator's own distinction, shown where the eye
        # lands rather than buried in a per-step log.
        ttk.Label(tab, textvariable=self.values["progress"], background=PANEL,
                  wraplength=1150, justify="left").grid(row=8, column=0, columnspan=3,
                                                        sticky="w", pady=(8, 0))

        bottom = ttk.Frame(tab, style="Card.TFrame", padding=10); bottom.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        controls = ttk.Frame(bottom, style="Card.TFrame"); controls.pack(side="left")
        self.start_button = ttk.Button(controls, text="开始自动运行", style="Accent.TButton", command=self.start); self.start_button.pack(side="left", padx=(0, 4))
        self.pause_button = ttk.Button(controls, text="暂停", command=self.pause, state="disabled"); self.pause_button.pack(side="left", padx=3)
        self.stop_button = ttk.Button(controls, text="停止", command=self.stop, state="disabled"); self.stop_button.pack(side="left", padx=3)
        ttk.Button(controls, text="刷新状态", command=self.refresh).pack(side="left", padx=3)
        ttk.Button(controls, text="截图", command=self.take_screenshot).pack(side="left", padx=3)
        # 视觉调试: off by default.  The operator's rule is that the picture stays clean
        # and ROI / template / target / verifier boxes appear only on request -- a preview
        # covered in debug furniture is one nobody can read a page from.
        self.vision_debug = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls, text="视觉调试", variable=self.vision_debug,
                        command=self._render_preview).pack(side="left", padx=(8, 3))
        # L3: a log digest.  The controls stay where they are -- they are how the operator acts
        # on the verdict two rows up, so they never fold.
        event = self._fold(bottom, key="events", title="最近事件", level=L3,
                           pack=dict(side="left", fill="both", expand=True, padx=(18, 0)),
                           badge_wrap=300)
        self.event_text = tk.StringVar(value="控制台已启动，等待真实状态。")
        ttk.Label(event, textvariable=self.event_text, background=PANEL, wraplength=640).pack(anchor="w")

    def _strategy(self) -> None:
        tab = self._tab("策略")
        ttk.Label(tab, text="自动化策略", style="Title.TLabel").pack(anchor="w", pady=(5, 4))
        ttk.Label(tab, text="这里只控制 Goal Category / Policy；Universal Skill 由唯一 Scheduler 按 Goal 与实时状态调用。", style="Muted.TLabel").pack(anchor="w", pady=(0, 14))
        grid = ttk.Frame(tab, style="Card.TFrame", padding=18); grid.pack(fill="x")
        ttk.Label(grid, text="以下开关可修改，会写入 config/policy_state.json；"
                  "只读规则（🔒）不提供控件，因为它们不是设置。",
                  style="Muted.TLabel", background=PANEL, wraplength=1200, justify="left").grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        self.policy_buttons: dict[str, Any] = {}
        for index, (name, var) in enumerate(self.policy_enabled.items()):
            # The label carries the state (✓ 已启用 / ○ 未启用) and is refreshed on toggle:
            # the indicator alone was read as a ✕, which this project reserves for
            # 关闭/取消/失败/拒绝.
            button = ttk.Checkbutton(
                grid, text=policy_toggle_label(name, bool(var.get())), variable=var,
                command=lambda n=name: self._toggle_policy(n),
            )
            button.grid(row=1 + index // 4, column=index % 4, sticky="w", padx=18, pady=10)
            self.policy_buttons[name] = button
            grid.columnconfigure(index % 4, weight=1)
        reward = ttk.Frame(tab, style="Card.TFrame", padding=18); reward.pack(fill="x", pady=(12, 0))
        ttk.Label(reward, text="Reward Policy · FREE_CLAIM_FIRST", style="Section.TLabel", background=PANEL).pack(anchor="w")
        ttk.Label(reward, text="免费无选择奖励：自动领取  ·  未知奖励内容：允许领取  ·  有选择奖励：交给 Strategy  ·  有成本：Resource Policy 判断  ·  真实支付：永久禁止 🔒", background=PANEL, wraplength=1050).pack(anchor="w", pady=(8, 0))
        resource = ttk.Frame(tab, style="Card.TFrame", padding=18); resource.pack(fill="x", pady=(12, 0))
        ttk.Label(resource, text="Resource Policy", style="Section.TLabel", background=PANEL).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        policies = (("普通资源", "自动优化"), ("加速", "按 Queue / Deadline / Event Synergy 决定"),
                    ("钻石", "保守"), ("活动道具", "优先截止期"), ("稀缺资源", "Resource Bank 预留"),
                    ("真实支付", "永久禁止 🔒"))
        for row, (name, value) in enumerate(policies, 1):
            ttk.Label(resource, text=name, style="Muted.TLabel", background=PANEL, width=16).grid(row=row, column=0, sticky="w", pady=5)
            ttk.Label(resource, text=value, background=PANEL, foreground=BAD if name == "真实支付" else TEXT).grid(row=row, column=1, sticky="w", pady=5)
        # The operator's standing prohibitions are shown as read-only rules, for the same
        # reason the 🔒 rows above are: they are not settings and not a to-do list.  Directive
        # FISHING TOURNAMENT — NORMAL BAIT MAX SCORE POLICY V2 §4 (2026-09-30) asks explicitly
        # that special-mode fishing NOT appear as pending work, because there is nothing to
        # build -- so it has to be visible as forbidden, or it will be re-proposed forever.
        forbidden = read_policy_state(POLICY_STATE_PATH).get("disabled_goals")
        if isinstance(forbidden, dict) and forbidden:
            blocked = ttk.Frame(tab, style="Card.TFrame", padding=18); blocked.pack(fill="x", pady=(12, 0))
            ttk.Label(blocked, text="禁止执行 · POLICY_DISABLED_BY_USER 🔒", style="Section.TLabel", background=PANEL).pack(anchor="w")
            ttk.Label(blocked, text="由操作者明确禁止：不进入候选、不执行、不需要开发；不是待接入，也不是能力缺失。",
                      style="Muted.TLabel", background=PANEL, wraplength=1200, justify="left").pack(anchor="w", pady=(6, 4))
            for goal_id, reason in sorted(forbidden.items()):
                ttk.Label(blocked, text=f"{goal_id}   ·   {reason}",
                          background=PANEL, foreground=BAD).pack(anchor="w", pady=1)
        # The one live control that had no surface.  ``continuous`` is read by the runtime
        # handoff, the watchdog and the stop path (four call sites) and persisted to
        # ``config/control_panel_state.json``, and its only checkbox lived on `_settings` --
        # a page that is never built, so the operator could not change it.  Found by the
        # audit of 2026-10-04 that asked, per field, "who can set this, and who reads it".
        # 运行方式 is a real decision (it is the difference between unattended repeat and
        # "stop after one round"), so it belongs on the page whose whole job is policy.
        runtime = ttk.Frame(tab, style="Card.TFrame", padding=18); runtime.pack(fill="x", pady=(12, 0))
        ttk.Label(runtime, text="运行方式", style="Section.TLabel", background=PANEL).pack(anchor="w")
        ttk.Checkbutton(
            runtime,
            text="连续运行（可执行时 30 秒复查；行军已满时 10 分钟复查）",
            variable=self.continuous,
            command=self._save_panel_state,
        ).pack(anchor="w", pady=(8, 0))
        ttk.Label(runtime, text="硬安全边界：真实充值、账号/角色删除、账号安全设置始终禁止。",
                  background=PANEL, foreground=BAD).pack(anchor="w", pady=(10, 0))
        row = ttk.Frame(runtime, style="Card.TFrame"); row.pack(anchor="w", pady=(8, 0))
        for label, path in (("打开截图目录", CAPTURE_ROOT), ("打开证据目录", ROOT / "evidence"),
                            ("打开最新截图", None), ("打开日志目录", LOG_ROOT)):
            command = self.open_latest if path is None else (lambda p=path: self._open(p))
            ttk.Button(row, text=label, command=command).pack(side="left", padx=4)

    def _toggle_policy(self, name: str) -> None:
        """Redraw the switch's own label, then persist -- in that order.

        The label is the state (✓ 已启用 / ○ 未启用); a control that only repaints its
        indicator is the thing the operator could not read.  The write is the same one the
        page always did, so this changes what is shown, not what is stored.
        """
        button = getattr(self, "policy_buttons", {}).get(name)
        if button is not None:
            try:
                button.configure(text=policy_toggle_label(name, bool(self.policy_enabled[name].get())))
            except Exception:  # noqa: BLE001 - a label must not break a real write
                pass
        self._save_policy_state()

    def _save_policy_state(self) -> None:
        write_policy_state(
            POLICY_STATE_PATH,
            goal_categories={k: v.get() for k, v in self.policy_enabled.items()},
            reward_policy="FREE_CLAIM_FIRST",
            real_money="PERMANENTLY_BLOCKED",
        )

    def _goals(self) -> None:
        tab = self._tab("目标")
        ttk.Label(tab, text="今日目标", style="Title.TLabel").pack(anchor="w", pady=(5, 4))
        ttk.Label(tab, text="来自最近一次真实识别；“未知”不是完成，勾选任务也不是完成。", style="Muted.TLabel").pack(anchor="w", pady=(0, 12))
        # No 置信度 column.  It was added on 2026-10-04 to stop the board printing the frame's
        # recognition confidence in every Goal row, and it did that honestly -- by reading the
        # Goal's *own* confidence, which ``GoalState`` does not have, so all 33 rows read
        # 未计算.  A column whose every cell is 未计算 carries no information; the operator's
        # rule for this audit is "不要因为以后可能有用就保留".  The frame's number is still
        # shown once, correctly labelled, in ``goal_board_meta`` below -- which is where
        # "this is page recognition, not a per-Goal figure" can actually be said in words.
        self.goal_board = ttk.Treeview(tab, columns=("goal", "category", "priority", "status", "progress", "deadline", "next", "blocked", "skills"), show="headings")
        for key, title, width in (("goal", "目标", 185), ("category", "类别", 80), ("priority", "优先级", 70), ("status", "状态", 90), ("progress", "进度/目标", 105), ("deadline", "剩余", 80), ("next", "下一动作", 150), ("blocked", "阻塞原因", 120), ("skills", "贡献能力", 190)):
            self.goal_board.heading(key, text=title); self.goal_board.column(key, width=width, anchor="w")
        self.goal_board.pack(fill="both", expand=True)
        self.goal_board_meta = tk.StringVar(value="尚无真实 GoalState；运行识别后自动更新。")
        ttk.Label(tab, textvariable=self.goal_board_meta, style="Muted.TLabel").pack(anchor="w", pady=(8, 0))
        self._refresh_goal_board()

    #: The frame's own reasons for holding a Goal back, in words.  A code that is not in
    #: here is shown as its own code rather than guessed at: an unrecognised reason is
    #: information, and inventing Chinese for it would destroy the one thing it carries.
    GOAL_BLOCK_ZH = {
        "this_camp_is_training": "该兵营正在训练中（队列未空）",
        "camp_queue_busy": "兵营队列忙",
        "queue_busy": "队列忙，已有工作在进行",
        "timer_running": "计时器未到",
        "no_batch_available": "没有可执行批次",
        "no_free_march": "没有空闲行军位",
    }

    @classmethod
    def _blocked_cell(cls, goal: dict, blockers: dict) -> str:
        """The real reason this Goal is held back, or an explicit "not blocked".

        Measured 2026-10-04: this cell rendered ``goal.get("blocked_reason")``, and
        ``blocked_reason`` is **not a field of ``GoalState``** (its 15 fields are
        goal_id/status/completion/…/distance) and is not written by ``GoalStateStore``
        either -- so all 33 rows showed "—" while real reasons existed for seven of them.
        The operator's report was exactly this: "检查阻塞原因为什么很多是空的".

        The reasons come from two places, because there are two kinds of not-running:

        * an **expired-history / no-progress** deferral is the scheduler's own decision, and
          it arrives in ``goal_state.json["blockers"]`` from ``CapabilityGate`` (recorded by
          the runtime, not re-derived here);
        * a **busy queue** is the frame's own reading: the library already marks those Goals
          ``BLOCKED`` with ``evidence.reason`` / ``evidence.condition`` / ``retry_after``.
          ``SHIELD_CAMP_TRAINING`` was ``this_camp_is_training`` and
          ``KEEP_RESEARCH_PRODUCTIVE`` was ``queue_busy`` with a 15-day timer.

        And an unblocked Goal no longer shows "—", because "—" reads as "unknown".  Nothing
        is holding an actionable Goal back; the reason it has not run is that the scheduler
        selected something else.  That is a different statement, and the honest one.
        """
        row = blockers.get(goal.get("goal_id")) if isinstance(blockers, dict) else None
        row = row if isinstance(row, dict) else {}
        reason = str(row.get("reason") or "").strip()
        if not reason:
            status = str(goal.get("status") or "")
            # The frame's own reason is read **only for a Goal the library itself marked
            # BLOCKED**.  A ``condition`` on a READY Goal is the precondition that *is* met
            # (``fresh_fishing_read``, ``camp_queue_idle``), and rendering that as a blocker
            # would invent a wall where there is none -- measured 2026-10-04.
            if status == "BLOCKED":
                evidence = goal.get("evidence") if isinstance(goal.get("evidence"), dict) else {}
                why = str(evidence.get("reason") or evidence.get("condition") or "").strip()
                if why:
                    retry = str(goal.get("retry_after") or evidence.get("timer") or "").strip()
                    text = cls.GOAL_BLOCK_ZH.get(why, why)
                    return f"{text} · 剩余 {retry}" if retry else text
                return "已判为阻塞，但这一次的读数没有带原因（证据为空）"
            if status in ("READY", "DISCOVERED"):
                return "就绪 · 未被阻塞（未选中＝调度顺序，不是被拦）"
            return "—"
        capability = str(row.get("capability") or "").strip()
        state = str(row.get("state") or "").strip()
        until = str(row.get("until") or "").strip()
        try:
            streak = int(row.get("streak") or 0)
        except (TypeError, ValueError):
            streak = 0
        parts = [f"{capability}：" if capability else "", reason]
        if streak:
            parts.append(f"（连续 {streak} 个 episode 无进展）")
        if state:
            parts.append(f" · [{state}]")
        if until:
            parts.append(f" · 至 {until}")
        return "".join(parts)

    def _refresh_goal_board(self) -> None:
        if not hasattr(self, "goal_board"):
            return
        for item in self.goal_board.get_children(): self.goal_board.delete(item)
        path = ROOT / "learning/goal_state.json"
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        names = {"CLEAR_INTEL":"清空情报", "AVOID_STAMINA_WASTE":"避免体力溢出", "KEEP_TRAINING_PRODUCTIVE":"保持训练", "KEEP_RESEARCH_PRODUCTIVE":"保持研究", "KEEP_BUILDING_PRODUCTIVE":"保持建筑", "EVENT_MINIMUM_GUARANTEE":"活动低保"}
        statuses = {"READY":"待执行", "IN_PROGRESS":"进行中", "COMPLETE":"✓ 完成", "BLOCKED":"暂时阻塞", "UNKNOWN":"未知（引擎未判定）", "DISCOVERED":"已发现"}
        goals = snapshot.get("goals", [])
        # The runtime's own deferral map, written beside the Goals it explains.  Absent on a
        # snapshot written by an older runtime, in which case every cell says so honestly
        # rather than inventing a reason.
        blockers = snapshot.get("blockers")
        blockers = blockers if isinstance(blockers, dict) else {}
        if not goals:
            self.goal_board.insert("", "end", values=("等待下一次可验证 Goal", "运行时", "—", PENDING, "—", "—", "观察 WorldState", "当前页面信息不足", "GoalLibrary / Scheduler"))
        for goal in goals:
            remaining = goal.get("remaining_seconds")
            deadline = "—" if remaining is None else f"{int(remaining)//3600:02d}:{int(remaining)%3600//60:02d}"
            goal_id = goal.get("goal_id")
            category = "活动" if "EVENT" in str(goal_id) or "BEAR" in str(goal_id) else ("日常" if "INTEL" in str(goal_id) or "STAMINA" in str(goal_id) else "发展")
            priority_value = goal.get("priority")
            priority = "P0" if isinstance(priority_value, (int, float)) and priority_value >= 2000 else ("P1" if isinstance(priority_value, (int, float)) and priority_value >= 500 else "P2")
            evidence = goal.get("evidence", {}) if isinstance(goal.get("evidence"), dict) else {}
            progress = f"{float(goal.get('completion',0)):.0%}"
            if "points_missing" in evidence: progress += f" · 缺 {evidence['points_missing']}"
            skills = ", ".join(goal.get("available_skills", ())) or "待发现"
            self.goal_board.insert("", "end", values=(names.get(goal_id, goal_id), category, priority,
                statuses.get(goal.get("status"), goal.get("status")), progress, deadline,
                (goal.get("available_skills") or ["待规划"])[0], self._blocked_cell(goal, blockers), skills))
            left_key = {"EVENT_MINIMUM_GUARANTEE": "活动低保", "CLEAR_INTEL": "情报", "AVOID_STAMINA_WASTE": "体力",
                        "KEEP_TRAINING_PRODUCTIVE": "训练", "KEEP_RESEARCH_PRODUCTIVE": "科研", "KEEP_BUILDING_PRODUCTIVE": "建筑"}.get(goal_id)
            if left_key in getattr(self, "today", {}): self.today[left_key].set(statuses.get(goal.get("status"), goal.get("status")))
        self.goal_board_meta.set(
            f"识别页面：{snapshot.get('page','UNKNOWN')} · 整帧识别置信度：{float(snapshot.get('confidence',0)):.0%}"
            f"（这是页面识别，不是每个目标的置信度）· 时间：{snapshot.get('observed_at','—')}"
        )

    def _event_goal(self) -> None:
        tab = self._tab("活动", scroll=True)
        ttk.Label(tab, text="活动低保", style="Title.TLabel").pack(anchor="w", pady=(5, 4))
        ttk.Label(tab, text="当前活动页拥有最终事实优先级；外部资料只提供候选先验。", style="Muted.TLabel").pack(anchor="w", pady=(0, 16))
        box = ttk.Frame(tab, style="Card.TFrame", padding=22); box.pack(fill="x")
        # Two fields were removed here on 2026-10-04: 预计成本 / 预计完成.  The record this
        # page reads has 14 keys and neither of them is among them, and nothing in the tree
        # ever writes either one into it (``goal_library`` reads ``estimated_cost`` off a
        # *goal spec*, a different object) -- so the two rows read 待计算 on every cycle
        # forever.  "待计算" is not an empty cell; it is a promise that a calculation is
        # pending, and there is no calculation.  The operator's rule for this audit is that
        # a field the system cannot fill must not be drawn.
        fields = (("活动", "name"), ("阶段", "phase"), ("数据来源", "source"), ("最后验证", "last_verified"),
                  ("目标档位", "tier"), ("当前积分", "current"), ("低保目标", "target"), ("积分缺口", "missing"),
                  ("剩余时间（验证时）", "remaining"), ("状态", "status"), ("已执行计划", "plan"),
                  ("资源消耗", "resource"), ("积分验证", "verified"), ("奖励", "rewards"))
        self.event_goal_vars = {key: tk.StringVar(value="暂无数据") for _, key in fields}
        for i, (label, key) in enumerate(fields):
            ttk.Label(box, text=label, style="Muted.TLabel", background=PANEL, width=18).grid(row=i, column=0, sticky="nw", pady=6)
            style = "Value.TLabel" if key in {"name", "status"} else "TLabel"
            ttk.Label(box, textvariable=self.event_goal_vars[key], style=style, background=PANEL, wraplength=760).grid(row=i, column=1, sticky="w", pady=6)
        self._fishing_box(tab)
        self._refresh_fishing_display()
        self._refresh_event_goal_display()
        self._refresh_goal_board()

    # ------------------------------------------------------- fishing (§16, policy V2)
    #
    # Directive FISHING TOURNAMENT — NORMAL BAIT MAX SCORE POLICY V2 (2026-09-30) §16 asks for
    # normal bait and event points per role, and asks in the same section that special mode NOT
    # be shown as a to-do.  Those two requests are one requirement: the page has to make the
    # *only* legal resource visible and the forbidden ones visible-as-forbidden, because a
    # forbidden action that is merely absent reads like unfinished work and gets re-proposed.

    FISHING_ROLE_FIELDS: tuple[tuple[str, str], ...] = (
        ("bait", "普通鱼饵"),
        ("next_bait_at", "下次恢复"),
        ("points_total", "活动积分"),
        ("pressure", "调度压力"),
        ("available", "剩余可出钓"),
        ("left_at_end", "预计残留"),
    )

    FISHING_KPI_FIELDS: tuple[tuple[str, str], ...] = (
        ("NORMAL_BAIT_USED", "普通鱼饵已用"),
        ("NORMAL_BAIT_WASTED", "回满浪费"),
        ("NORMAL_BAIT_REMAINING", "当前剩余"),
        ("TOTAL_POINTS", "本活动积分"),
        ("POINTS_PER_BAIT_AVG", "每饵均分"),
        ("POINTS_PER_BAIT_P50", "每饵中位"),
        ("BEST_POINTS_PER_BAIT", "最佳每饵"),
        ("AVG_DEPTH", "平均深度"),
        ("BEST_DEPTH", "最佳深度"),
        ("AVG_FISH_CAUGHT", "平均鱼数"),
        ("COLLISION_RATE", "碰撞/局"),
    )

    FISHING_PRESSURE_ZH = {
        "UNKNOWN": "状态未读取",
        "NO_BAIT": "无饵",
        "ENDGAME": "收尾（优先出钓）",
        "CAP_FULL": "已满（避免浪费）",
        "NORMAL": "正常",
    }

    def _fishing_box(self, tab: ttk.Frame) -> None:
        box = ttk.Frame(tab, style="Card.TFrame", padding=18); box.pack(fill="x", pady=(18, 0))
        ttk.Label(box, text="钓鱼锦标赛 · 普通鱼饵策略", style="Section.TLabel",
                  background=PANEL).pack(anchor="w")
        ttk.Label(box, text=(
            "唯一允许消耗：NORMAL_BAIT。特殊鱼饵 / 宝藏券 / Treasure Mode / 免费特殊次数 = "
            "POLICY_DISABLED_BY_USER（即使免费也不使用）。它是策略禁止，不是能力缺失，"
            "所以这里也不列为待办。"
        ), style="Muted.TLabel", background=PANEL, wraplength=1200,
            justify="left").pack(anchor="w", pady=(6, 10))

        self.fishing_vars: dict[str, tk.StringVar] = {}
        roles = ttk.Frame(box, style="Card.TFrame"); roles.pack(fill="x")
        for index, key in enumerate(("ROLE_A", "ROLE_B")):
            card = ttk.Frame(roles, style="Card2.TFrame", padding=14)
            card.grid(row=0, column=index, sticky="nsew", padx=(0, 10))
            roles.columnconfigure(index, weight=1)
            title = tk.StringVar(value=key)
            self.fishing_vars[f"{key}.title"] = title
            ttk.Label(card, textvariable=title, style="Section.TLabel",
                      background=PANEL2).pack(anchor="w", pady=(0, 6))
            for field_key, label in self.FISHING_ROLE_FIELDS:
                variable = tk.StringVar(value="—")
                self.fishing_vars[f"{key}.{field_key}"] = variable
                row = ttk.Frame(card, style="Card2.TFrame"); row.pack(fill="x", pady=1)
                ttk.Label(row, text=label, style="Muted.TLabel", background=PANEL2,
                          width=12).pack(side="left")
                ttk.Label(row, textvariable=variable, background=PANEL2).pack(side="left")

        kpis = ttk.Frame(box, style="Card.TFrame"); kpis.pack(fill="x", pady=(10, 0))
        ttk.Label(kpis, text="本活动指标（普通鱼饵口径）", style="Section.TLabel",
                  background=PANEL).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 6))
        for position, (metric, label) in enumerate(self.FISHING_KPI_FIELDS):
            variable = tk.StringVar(value="—")
            self.fishing_vars[f"kpi.{metric}"] = variable
            column = (position % 2) * 2
            row = 1 + position // 2
            ttk.Label(kpis, text=label, style="Muted.TLabel", background=PANEL,
                      width=16).grid(row=row, column=column, sticky="w", pady=2)
            ttk.Label(kpis, textvariable=variable, background=PANEL).grid(
                row=row, column=column + 1, sticky="w", pady=2)
        self.fishing_meta = tk.StringVar(value="尚无钓鱼记录；出钓后自动更新。")
        ttk.Label(kpis, textvariable=self.fishing_meta, style="Muted.TLabel",
                  background=PANEL, wraplength=1200, justify="left").grid(
            row=1 + (len(self.FISHING_KPI_FIELDS) + 1) // 2, column=0, columnspan=4,
            sticky="w", pady=(8, 0))

    @staticmethod
    def _fishing_countdown(iso_stamp: Any) -> str:
        """``3小时12分后`` / ``已到`` / ``未读取``.  Never a silent blank."""
        from winter_agent_v2.fishing_state import parse_instant

        moment = parse_instant(iso_stamp)
        if moment is None:
            return "未读取"
        remaining = (moment - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            return "已到"
        if remaining >= 3600:
            return f"{int(remaining // 3600)}小时{int((remaining % 3600) // 60)}分后"
        return f"{int(remaining // 60)}分后"

    @classmethod
    def _fishing_next_recovery(cls, card: dict) -> str:
        """The next recovery instant, or an explicit "needs re-reading".

        A stored instant older than one regeneration period must not be presented as the next
        recovery, because the counter has almost certainly moved since it was read.  ``待重读``
        is both the honest answer and the actionable one: it names the missing step instead of
        showing a number that invites a wrong decision.
        """
        from winter_agent_v2.fishing_state import parse_instant

        observed = parse_instant(card.get("observed_at"))
        regen = card.get("regen_seconds")
        if observed is None:
            return "未读取"
        age = (datetime.now(timezone.utc) - observed).total_seconds()
        if regen and age > float(regen):
            return f"待重读（读数 {age / 3600.0:.0f} 小时前）"
        return cls._fishing_countdown(card.get("next_bait_at"))

    @staticmethod
    def _fishing_number(value: Any, *, digits: int = 0, suffix: str = "") -> str:
        if value is None:
            return "—"
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "—"
        return (f"{number:.{digits}f}" if digits else f"{number:.0f}") + suffix

    def _refresh_fishing_display(self) -> None:
        """Read the fishing record and render it.  A failure here must not touch the panel."""
        if not hasattr(self, "fishing_vars"):
            return
        try:
            from winter_agent_v2.fishing_state import FishingState

            store = FishingState.load(ROOT / "learning/fishing_state.json",
                                      ROOT / "learning/fishing_runs.jsonl")
            snapshot = store.snapshot()
        except Exception:  # noqa: BLE001 - a display must never break the control loop
            return

        for key, card in (snapshot.get("roles") or {}).items():
            title = self.fishing_vars.get(f"{key}.title")
            if title is not None:
                label = card.get("name") or card.get("role_id") or ""
                title.set(f"{key}{(' · ' + str(label)) if label else ''}")
            pairs = {
                "bait": card.get("bait") or "未读取",
                "next_bait_at": self._fishing_next_recovery(card),
                "points_total": self._fishing_number(card.get("points_total")),
                "pressure": self.FISHING_PRESSURE_ZH.get(
                    str(card.get("pressure")), str(card.get("pressure"))
                ),
                "available": self._fishing_number(card.get("bait_available_until_end")),
                "left_at_end": self._fishing_number(card.get("projected_bait_at_end")),
            }
            for field_key, value in pairs.items():
                variable = self.fishing_vars.get(f"{key}.{field_key}")
                if variable is not None:
                    variable.set(value)

        total = snapshot.get("event_total") or {}
        for metric, _label in self.FISHING_KPI_FIELDS:
            variable = self.fishing_vars.get(f"kpi.{metric}")
            if variable is None:
                continue
            value = total.get(metric)
            variable.set(self._fishing_number(
                value, digits=1 if isinstance(value, float) else 0
            ))

        roles = snapshot.get("roles") or {}
        endgame = [key for key, card in roles.items()
                   if (card.get("endgame") or {}).get("active")]
        notes = [
            f"出钓记录 {total.get('runs', 0)} 竿（其中 {total.get('runs_with_efficiency', 0)} "
            f"竿有积分读数）",
        ]
        if total.get("zero_score_runs"):
            notes.append(f"零分竿 {total['zero_score_runs']} 竿（已进入失败分析）")
        if endgame:
            notes.append(f"收尾窗口：{'、'.join(sorted(endgame))} 剩余普通鱼饵可能用不完")
        source = next((card.get("regen_source") for card in roles.values()
                       if card.get("regen_source")), None)
        if source == "OPERATOR_PRIOR":
            notes.append("恢复节奏目前来自操作者先验（3 小时/个），未真机标定")
        self.fishing_meta.set(" · ".join(notes))

    def _refresh_event_goal_display(self) -> None:
        """The activity page: what is live now, and separately what is only history.

        Operator P0-1, 2026-09-18: this page showed 最强王国·击败野兽 as the running
        activity while its own fields said 数据来源 HISTORY / 最后验证 待验证 / 置信度 0%,
        verified nine days earlier with its recorded countdown long expired.  The
        classification is the audit's own (``legacy_event_row_for``), not a second opinion
        computed here.

        Operator, 2026-10-04, second round: the fix above marked the row as history but still
        printed the *numbers*, prefixed.  Reported as "界面上如果数据已过期，应该显示待重新
        观测或隐藏，而不是继续展示 25 天前的模板".  A prefix is not a hiding place, and by
        then the record was 595 h old.  An expired row now shows 待重新观测 in every value
        cell; only provenance survives, and its age is stated next to it.  The record also
        carries its own ``expired`` verdict, so this page does not re-derive the expiry rule
        and cannot disagree with the audit about the same file.
        """
        from winter_agent_v2.state_truth import legacy_event_row_for

        row = legacy_event_row_for(ROOT)
        if not row:
            for key in self.event_goal_vars:
                self.event_goal_vars[key].set("暂无数据")
            if hasattr(self, "queues") and "活动" in self.queues:
                self.queues["活动"].set("未读到")
            return

        raw = row.get("raw") or {}
        live = bool(row.get("planner_usable"))
        expired = bool(row.get("expired")) or not live
        age = row.get("age_seconds")
        age_text = "" if age is None else f"{float(age) / 3600.0:.0f} 小时前"
        remaining = row.get("remaining_seconds_at_verification")

        # A stale record has no part of today's answer, so its numbers are not rendered at
        # all.  Until 2026-10-04 this branch showed them behind a 历史参考（不参与当前
        # Planner）prefix, and the operator reported exactly that as the defect: "继续展示
        # 25 天前的模板".  A prefix is not a hiding place -- those figures were still the only
        # figures on the page, and they were 25 days old.  Every value cell now reads
        # 待重新观测.  What stays is provenance (which file, recorded when, how old), because
        # "which reading is this" is the one question a stale row can still answer truthfully.
        # (The word itself is the module-level ``REOBSERVE`` -- it is shared with the source
        # freshness lines so the reader learns one word, not two spellings of one idea.)

        def number(key: str, default: str = "暂无数据") -> str:
            if expired:
                return REOBSERVE
            value = raw.get(key)
            if value is None:
                return default
            try:
                return f"{int(value):,}"
            except (TypeError, ValueError):
                return str(value)

        def text(key: str, default: str) -> str:
            return REOBSERVE if expired else str(raw.get(key) or default)

        values = {
            # Only a current row may carry a name under this heading.
            "name": row.get("event_name") if live else "当前活动尚未实时确认",
            "current": number("current_points"),
            "phase": text("event_phase", "待识别"),
            "source": row.get("source") or "",
            "last_verified": (str(row.get("observed_at") or "待验证")
                              + (f"（{age_text}，已过期）" if expired and age_text else "")),
            # No 置信度 cell.  The classifier returns ``confidence = 0.0`` for this row as a
            # verdict ("this is not a live observation"), not as a percentage, and the record
            # itself carries no confidence key -- so the cell read "—" on every cycle.  A row
            # that can never be filled is not a row; 数据来源 + 最后验证 already answer "which
            # reading is this", which is the only question this row can answer truthfully.
            "tier": text("target_tier", "低保目标档"),
            "target": number("target_points"),
            "missing": number("points_missing"),
            "remaining": ("—" if (remaining is None or expired) else
                          f"{int(remaining) // 3600:02d}:{int(remaining) % 3600 // 60:02d}:{int(remaining) % 60:02d}"),
            "status": (
                ("✓ 今日低保完成" if raw.get("minimum_guarantee_complete") else "⚠ 未完成")
                if live else
                f"⚠ {REOBSERVE} —— {row.get('note') or ''}"
            ),
            "plan": text("plan", "暂无数据"),
            "resource": number("resource_spent"),
            "verified": number("verified_points_gain"),
            "rewards": (("全部目标档位已领取" if raw.get("all_target_rewards_claimed")
                         else "仍有奖励待领取") if live else REOBSERVE),
        }
        for key, value in values.items():
            self.event_goal_vars[key].set(value)
        if hasattr(self, "queues") and "活动" in self.queues:
            self.queues["活动"].set(
                ("低保完成" if raw.get("minimum_guarantee_complete") else
                 f"缺 {int(raw.get('points_missing', 0)):,}") if live else REOBSERVE
            )

    def _capabilities(self) -> None:
        tab = self._tab("能力", scroll=True)
        ttk.Label(tab, text="Capability 覆盖与 Skill 执行层", style="Title.TLabel").pack(anchor="w", pady=(5, 4))
        ttk.Label(tab, text="上表是 Capability 覆盖表（capability_catalog.json）——游戏里有什么、验证到哪一步；"
                            "下表是 Skill 执行注册表（v2_registry）——谁能把动作做出来。两张表各自独立，面板不合并、不改写任何一个。",
                  style="Muted.TLabel", wraplength=1250, justify="left").pack(anchor="w", pady=(0, 8))
        summary = ttk.Frame(tab, style="Card.TFrame", padding=10); summary.pack(fill="x")
        self.capability_summary = {key: tk.StringVar(value=NO_DATA) for key in ("implemented", "tried", "verified", "blocked")}
        for index, (key, label) in enumerate((("implemented", "已实现"), ("tried", "Live Tried"),
                                              ("verified", "Live Verified"), ("blocked", "Blocked"))):
            card = ttk.Frame(summary, style="Card2.TFrame", padding=12); card.grid(row=0, column=index, sticky="ew", padx=4); summary.columnconfigure(index, weight=1)
            ttk.Label(card, text=label, style="Muted.TLabel", background=PANEL2).pack(anchor="w")
            ttk.Label(card, textvariable=self.capability_summary[key], style="Value.TLabel", background=PANEL2).pack(anchor="w")
        # **The four cards stay open, which is a deliberate change from §六.**  §六 assigns 覆盖度
        # L2 on the grounds that it is 「要不要开发的依据」 --也就是一个 L1 式的理由 —— and this page has
        # no other L1 candidate: folding everything §六 lists would make the page open as four shut
        # bars, which is the failure mode ``test_no_page_opens_as_a_stack_of_shut_headers`` exists to
        # catch.  The cards are four numbers, so leaving them open costs height rather than attention.
        # The vocabulary is printed, not implied: the whole point of section 5 is that
        # a reader can tell 未读取 from 未知 from Blocked without guessing.
        ttk.Label(tab, text="状态词义：未读取＝没人读过它（不是未知）· 待刷新＝只有未带 recorded_at 的导入记录，不能作为证据 · "
                            "可执行＝已实现且可派发 · 执行中＝正在跑 · Blocked＝有具名阻塞原因 · Live Tried / Live Verified＝真机证据。",
                  style="Muted.TLabel", wraplength=1250, justify="left").pack(anchor="w", pady=(6, 0))
        catalog_body = self._fold(tab, key="cap_catalog", title="Capability 覆盖表", level=L2,
                                  pack={"fill": "both", "expand": True, "pady": (10, 0)})
        head = ttk.Frame(catalog_body); head.pack(fill="x", pady=(0, 4))
        ttk.Label(head, text="游戏里有什么、验证到哪一步（capability_catalog.json）", style="Muted.TLabel",
                  background=PANEL).pack(side="left")
        self.show_all_capabilities = tk.BooleanVar(value=False)
        ttk.Checkbutton(head, text="显示全部（默认只看已实现 / 已尝试 / 被阻塞）", variable=self.show_all_capabilities,
                        command=self._refresh_capabilities).pack(side="right")
        self.capability_tree = ttk.Treeview(catalog_body, columns=("id", "code", "category", "lifecycle", "state", "backend", "live", "rate", "blocked"),
                                            show="headings", height=10)
        for key, title, width in (("id", "Capability ID", 105), ("code", "能力", 235), ("category", "分类", 165),
                                  ("lifecycle", "生命周期", 95), ("state", "可用性", 90), ("backend", "首选后端", 70),
                                  ("live", "真机成功/尝试", 95), ("rate", "成功率", 70), ("blocked", "阻塞原因", 260)):
            self.capability_tree.heading(key, text=title); self.capability_tree.column(key, width=width, anchor="w")
        self.capability_tree.pack(fill="both", expand=True)
        # L3: the executor registry.  It answers "谁能把动作做出来", which is an implementation
        # question -- the covering table above already answers the operator's one ("这事到底做没做").
        registry_body = self._fold(tab, key="cap_registry", title="Skill 执行注册表", level=L3,
                                   pack={"fill": "both", "expand": True, "pady": (10, 0)})
        ttk.Label(registry_body, text="谁能把动作做出来（v2_registry）", style="Muted.TLabel",
                  background=PANEL).pack(anchor="w", pady=(0, 4))
        self.skill_tree = ttk.Treeview(registry_body, columns=("layer", "skill", "verifier", "risk", "state", "live", "claims", "meaning"),
                                       show="headings", height=8)
        for key, title, width in (("layer", "层级", 90), ("skill", "Skill", 200), ("verifier", "Verifier", 130),
                                  ("risk", "风险", 55), ("state", "阶段", 90), ("live", "真机验证/尝试", 95),
                                  ("claims", "无时间戳声明", 100), ("meaning", "说明", 330)):
            self.skill_tree.heading(key, text=title); self.skill_tree.column(key, width=width, anchor="w")
        self.skill_tree.pack(fill="both", expand=True)
        # L3, and it opens itself: §六 asks for 「unexpected_worker_exits 非 0 必须浮上来」, implemented
        # as growth since the window opened (MEMORY §57 -- the field is cumulative).
        runtime_quality = self._fold(tab, key="cap_runtime", title="运行时质量（4 格）", level=L3,
                                     escalate=self._escalate_capability_runtime,
                                     pack={"fill": "x", "pady": (10, 0)})
        self.runtime_quality_vars = {key: tk.StringVar(value=NO_DATA) for key in ("success24", "recovery", "exit", "latency")}
        for index, (key, label) in enumerate((("success24", "24h Skill Success"), ("recovery", "Recovery Success"), ("exit", "Unexpected Worker Exit"), ("latency", "Average Realtime Latency"))):
            ttk.Label(runtime_quality, text=label, style="Muted.TLabel", background=PANEL).grid(row=0, column=index, sticky="w", padx=8)
            ttk.Label(runtime_quality, textvariable=self.runtime_quality_vars[key], background=PANEL).grid(row=1, column=index, sticky="w", padx=8); runtime_quality.columnconfigure(index, weight=1)
        # Registered rather than left on the global tick: this rebuilds two Treeviews
        # from the catalog, which is real work nobody sees unless this tab is open.
        self._register_tab_refresh("能力", self._refresh_capabilities)
        self._refresh_capabilities()

    def _refresh_capabilities(self) -> None:
        if not hasattr(self, "capability_tree"): return
        from winter_agent_v2.runtime import LiveRuntime

        universal_ids = {"CLAIM_REWARD", "NAVIGATE_TO", "SEND_MARCH", "START_RALLY", "JOIN_RALLY", "START_BUILD", "START_RESEARCH", "TRAIN_OR_PROMOTE", "USE_ACTIVITY_ATTEMPT", "READ_EVENT_STATE", "OPEN_HOME", "OPEN_MAP", "BACK", "CLOSE_POPUP", "DISPATCH_MARCH"}
        index = episode_index()
        snapshot = self.runtime_store.read()
        running_skill = str(snapshot.current_skill or "")
        catalog = capability_catalog()
        entries = catalog.get("capabilities") or []
        cataloged_skills = {str(e.get("existing_skill")) for e in entries if e.get("existing_skill")}
        for row in self.capability_tree.get_children(): self.capability_tree.delete(row)
        shown = 0
        for entry in entries:
            skill = str(entry.get("existing_skill") or "")
            tally = index.get(skill, {}) if skill else {}
            interesting = (bool(skill) or int(entry.get("live_attempts") or 0) or bool(entry.get("blocked_reason")))
            if not (self.show_all_capabilities.get() or interesting):
                continue
            shown += 1
            rate = entry.get("success_rate")
            self.capability_tree.insert("", "end", values=(
                entry.get("capability_id"), entry.get("code"), entry.get("name_cn"),
                capability_lifecycle_cn(entry, skill_state=self._skill_state(skill)),
                capability_state_cn(entry, skill_state=self._skill_state(skill), running_skill=running_skill,
                                    claims=int(tally.get("claims") or 0)),
                entry.get("preferred_backend") or PENDING,
                f"{int(entry.get('live_success') or 0)}/{int(entry.get('live_attempts') or 0)}",
                f"{float(rate):.0%}" if isinstance(rate, (int, float)) else "—",
                str(entry.get("blocked_reason") or "—")[:150],
            ))
        for row in self.skill_tree.get_children(): self.skill_tree.delete(row)
        verified_skills = stable_skills = 0
        for skill in self.registry.all():
            layer = "Universal" if skill.id in universal_ids else ("Event Adapter" if any(k in skill.id for k in ("BEAR", "EVENT")) else "Composite")
            tally = index.get(skill.id, {})
            live = f"{tally.get('verified', 0)}/{tally.get('live', 0)}" if tally.get("live") else "未实机"
            if tally.get("live") and tally.get("verified"): verified_skills += 1
            if skill.state is SkillState.STABLE: stable_skills += 1
            bound = skill.id in LiveRuntime.VERIFIED_ATOMIC
            meaning = ("已绑定 verifier，可由 Scheduler 派发" if bound
                       else "未绑定 verifier：写好了但不会被派发（见 VERIFIER_SHAPE_MISMATCH）")
            if tally.get("claims") and not tally.get("live"):
                meaning = f"{tally['claims']} 行导入声明未带 recorded_at，需要一次真机刷新才算证据"
            self.skill_tree.insert("", "end", values=(layer, skill.id, "已绑定" if bound else "未绑定",
                                                      skill.risk, skill.state.value, live,
                                                      str(tally.get("claims") or 0), meaning))
        kpi = overview_kpis(registry=self.registry)
        for key in ("implemented", "tried", "verified", "blocked"):
            self.capability_summary[key].set(kpi[key]["value"])
        if hasattr(self, "runtime_quality_vars"):
            scan = episode_scan()
            recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            recent: list[bool] = []
            for stamp, ok in scan["results"]:
                try:
                    if datetime.fromisoformat(stamp.replace("Z", "+00:00")) >= recent_cutoff:
                        recent.append(ok)
                except ValueError:
                    pass
            durations = scan["durations"]
            self.runtime_quality_vars["success24"].set(f"{sum(recent)}/{len(recent)}" if recent else "无24h时间戳样本")
            self.runtime_quality_vars["recovery"].set(f"{snapshot.watchdog_restart_count} 次重启")
            self.runtime_quality_vars["exit"].set(str(snapshot.unexpected_worker_exits))
            self.runtime_quality_vars["latency"].set(f"{sum(durations)/len(durations):.1f}s" if durations else PENDING)

    def _skill_state(self, skill_id: str) -> str:
        if not skill_id:
            return ""
        try:
            skill = self.registry.get(skill_id)
        except Exception:  # noqa: BLE001 - an unknown skill simply has no state here
            return ""
        return skill.state.value if skill is not None else ""


    # ``_skills()`` (能力目录) was removed here on 2026-10-04.  It built a *second* tab also
    # named 能力 and was never called.  The guard that enforces "exactly seven primary tabs"
    # listed the retired builders **by hand** -- ``_tasks/_coverage/_knowledge/_logs/
    # _settings/_learning`` -- and did not mention this one, so that retirement had an element
    # nobody was checking.  The guard below now enumerates the family by walking ``_build``,
    # which is why this method is gone rather than merely unused: a hand-written family list
    # is a family list that loses members.

    # ``_knowledge()`` (知识库) and its helper ``count_knowledge()`` were removed here on
    # 2026-10-04.  The page was never built, and the helper it needed printed raw record
    # counts from three files -- one of them 29 days stale -- as the state of the knowledge
    # base, with no age and no denominator.

    def _auto_development(self) -> None:
        """The development platform's own page.

        Renamed from 学习 on 2026-09-17: what happens here is not the runtime
        learning from experience, it is a development agent being handed a
        capability gap and returning either a working capability or an honest
        BLOCKED.  Every number on this page comes from the escalation ledger or
        from ``classify_condition`` -- the same rule the AUTO hook uses.
        """
        from winter_agent_v2.escalation_queue import ALL_STATES

        tab = self._tab("自动开发", scroll=True)
        ttk.Label(tab, text="WorkBuddy 自动开发平台", style="Title.TLabel").pack(anchor="w", pady=(5, 4))
        ttk.Label(tab, text="V2 发现能力缺口 → 升级队列（去重 / 并发 1 / 修复预算）→ WorkBuddy 后台开发 → 真机验证。"
                            "模型只是 WorkBuddy 内部的可替换算力，不是 Winter Agent OS 的组件。",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        # §八's closed-loop card, first on the page because it answers "闭环卡在哪一步" --
        # which is the question the operator had to read logs to answer.  The eight cells are
        # the eight things the operator listed, and each is graded from its *own* chain steps
        # by ``unattended_closure`` rather than from a single green tick for the pipeline.
        # L3 + it opens itself: §六 puts 自主开发闭环 at 「L1 当有断点，否则 L3」, and the fold
        # mechanism's opening rule *is* that "when".  The page title and the block header stay on
        # screen either way, so a folded loop is still named rather than hidden.
        loop = self._fold(tab, key="dev_loop", title="自主开发闭环", level=L3,
                          escalate=self._escalate_dev_loop,
                          pack={"fill": "x", "pady": (0, 10)})
        ttk.Label(loop, text="由 unattended_closure 按 trace_id 联结台账/Episode/提交 得出",
                  style="Muted.TLabel", background=PANEL).pack(anchor="w", pady=(0, 4))
        ttk.Label(loop, textvariable=self.values["loop_card"], background=PANEL,
                  wraplength=1150, justify="left").pack(anchor="w")
        for label, key in (("当前 trace", "loop_trace"), ("当前断点", "loop_break"),
                           ("网关验收 Soak", "soak"), ("一致性", "consistency")):
            row = ttk.Frame(loop, style="Card.TFrame"); row.pack(fill="x", pady=(4, 0))
            ttk.Label(row, text=label, style="Muted.TLabel", background=PANEL, width=14).pack(side="left")
            ttk.Label(row, textvariable=self.values[key], background=PANEL,
                      wraplength=1000, justify="left").pack(side="left")
        # L3: the development platform's own eight cells.  §六 calls these 内部平台细节 -- and it
        # gives the block an opening rule, which this one takes from the *same* method the 总览
        # block uses, because §六's exception belongs to the gateway rather than to a page: an
        # unreachable gateway must not be folded away on one surface and open on another.
        status = self._fold(tab, key="dev_wb", title="WorkBuddy 状态（内部平台）", level=L3,
                            escalate=self._escalate_workbuddy, pack={"fill": "x"})
        ttk.Label(status, textvariable=self.values["wb_gateway"], style="Muted.TLabel",
                  background=PANEL).pack(anchor="w", pady=(0, 4))
        grid = ttk.Frame(status, style="Card.TFrame"); grid.pack(fill="x")
        for index, (label, key) in enumerate((("状态", "wb_state"), ("当前 Capability", "wb_capability"),
                                              ("Escalation Reason", "wb_reason"), ("Job ID", "wb_job"),
                                              ("当前模型", "wb_model"), ("运行时间", "wb_duration"),
                                              ("Job 状态", "wb_job_state"), ("Live Improvement", "wb_improvement"))):
            cell = ttk.Frame(grid, style="Card.TFrame"); cell.grid(row=index // 4, column=index % 4, sticky="w", padx=(0, 22), pady=3)
            ttk.Label(cell, text=label, style="Muted.TLabel", background=PANEL).pack(anchor="w")
            ttk.Label(cell, textvariable=self.values[key], background=PANEL, wraplength=280, justify="left").pack(anchor="w")
            grid.columnconfigure(index % 4, weight=1)
        result = ttk.Frame(grid, style="Card.TFrame"); result.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        ttk.Label(result, text="最近结果", style="Muted.TLabel", background=PANEL).pack(anchor="w")
        ttk.Label(result, textvariable=self.values["wb_result"], background=PANEL, wraplength=1150, justify="left").pack(anchor="w")
        # The operator's §十四 row: knowledge preload, as a state rather than a promise.
        # Every value comes from real artifacts (the controller's STATE.json, the
        # catalog, the knowledge files, the ledger), so this row cannot say "learning"
        # while nothing is learning -- which is the failure mode the operator named.
        learn_row = ttk.Frame(grid, style="Card.TFrame"); learn_row.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        ttk.Label(learn_row, text="能力学习 / 预装（Knowledge → Capability Preload）", style="Muted.TLabel", background=PANEL).pack(anchor="w")
        ttk.Label(learn_row, textvariable=self.values["learn"], background=PANEL, wraplength=1150, justify="left").pack(anchor="w")
        # L2: "why is nothing moving" -- the pump's clock and who owns the device.  These used to be
        # two more rows inside the WorkBuddy grid; §六 puts them at L2 while the eight cells are L3,
        # so they are a separate block rather than rows of one.  §21's device row is read from the
        # lease file and 恢复AUTO is a real answer, never hardcoded.
        pump = self._fold(tab, key="dev_pump", title="队列消费泵 / 设备所有权", level=L2,
                          pack={"fill": "x", "pady": (10, 0)})
        for label, key in (("队列消费泵（面板常驻）", "wb_pump"),
                           ("设备所有权（Single UI Owner）", "lease")):
            ttk.Label(pump, text=label, style="Muted.TLabel", background=PANEL).pack(anchor="w", pady=(4, 0))
            ttk.Label(pump, textvariable=self.values[key], background=PANEL,
                      wraplength=1150, justify="left").pack(anchor="w")
        # L2, and one block rather than two: §六's row is 「队列状态条 + 升级条件分桶 **L2**（积压超阈值浮 L1）」
        # -- the two strips answer one question ("what is queued and why"), which is why they were
        # adjacent when both were open.  **The 积压 half is deliberately not implemented**: the panel
        # has no declared backlog threshold, and ``INERT_FOLDS`` already records that inventing one
        # would be a second opinion -- the real "stuck" judgement belongs to ``WORKBUDDY_QUEUE_STUCK``
        # on the WorkBuddy block above.  So this block has no rule of its own, on purpose.
        queue = self._fold(tab, key="dev_queue", title="Development Escalation Queue · 升级条件分桶",
                           level=L2, pack={"fill": "x", "pady": (10, 0)})
        qhead = ttk.Frame(queue, style="Card.TFrame"); qhead.pack(fill="x")
        ttk.Label(qhead, text="队列状态", style="Muted.TLabel", background=PANEL).pack(side="left")
        ttk.Label(qhead, textvariable=self.values["wb_queue_line"], style="Muted.TLabel", background=PANEL).pack(side="right")
        strip = ttk.Frame(queue, style="Card.TFrame"); strip.pack(fill="x", pady=(6, 0))
        self.escalation_state_vars: dict[str, tk.StringVar] = {}
        for index, state in enumerate(ALL_STATES):
            card = ttk.Frame(strip, style="Card2.TFrame", padding=(10, 5)); card.grid(row=0, column=index, sticky="ew", padx=3); strip.columnconfigure(index, weight=1)
            ttk.Label(card, text=STATE_ZH.get(state, state), style="Muted.TLabel", background=PANEL2).pack(anchor="w")
            self.escalation_state_vars[state] = tk.StringVar(value="0")
            ttk.Label(card, textvariable=self.escalation_state_vars[state], style="Value.TLabel", background=PANEL2).pack(anchor="w")
        chead = ttk.Frame(queue, style="Card.TFrame"); chead.pack(fill="x", pady=(10, 0))
        ttk.Label(chead, text="Capability Gap · 升级条件分桶", style="Muted.TLabel", background=PANEL).pack(side="left")
        ttk.Label(chead, text="按 escalation_queue.classify_condition 分类当前真机失败", style="Muted.TLabel", background=PANEL).pack(side="right")
        cstrip = ttk.Frame(queue, style="Card.TFrame"); cstrip.pack(fill="x", pady=(6, 0))
        self.bucket_vars: dict[str, tk.StringVar] = {}
        for index, condition in enumerate((*AUTO_ESCALATION_CONDITIONS, "（不升级）")):
            card = ttk.Frame(cstrip, style="Card2.TFrame", padding=(10, 5)); card.grid(row=0, column=index, sticky="ew", padx=3); cstrip.columnconfigure(index, weight=1)
            ttk.Label(card, text=CONDITION_ZH.get(condition, condition), style="Muted.TLabel", background=PANEL2).pack(anchor="w")
            self.bucket_vars[condition] = tk.StringVar(value=NO_DATA)
            ttk.Label(card, textvariable=self.bucket_vars[condition], style="Value.TLabel", background=PANEL2).pack(anchor="w")
        # L2 + it opens itself.  §六: 「最近失败分类 **L2**（次数超阈值浮 L1）」, and the threshold is
        # the project's own P0 bucket via ``failure_priority`` rather than a number invented here --
        # so the 优先级 column below and the rule that opens this block cannot disagree about what
        # P0 means, and this rule needed no new constant to be implementable.
        failures = self._fold(tab, key="dev_failures", title="最近失败分类（真机 episode）", level=L2,
                              escalate=self._escalate_dev_failures,
                              pack={"fill": "both", "expand": True, "pady": (12, 0)})
        self.failure_tree = ttk.Treeview(failures, columns=("type", "count", "priority", "last"), show="headings", height=6)
        for key, title, width in (("type", "问题", 260), ("count", "次数", 60), ("priority", "优先级", 70), ("last", "最近出现", 160)):
            self.failure_tree.heading(key, text=title); self.failure_tree.column(key, width=width, anchor="w")
        self.failure_tree.pack(fill="both", expand=True)
        # L3: two ledgers, read when auditing a past decision rather than to decide the next one.
        # They share a block because they answer the same follow-up -- "那一轮用谁跑的、结果如何" --
        # which is also why they used to sit side by side.
        jobs = self._fold(tab, key="dev_jobs", title="Job 历史 / 模型战绩", level=L3,
                          pack={"fill": "both", "expand": True, "pady": (12, 0)})
        self.job_tree = ttk.Treeview(jobs, columns=("time", "capability", "reason", "state", "model", "outcome", "changed", "duration"),
                                     show="headings", height=6)
        for key, title, width in (("time", "时间", 150), ("capability", "Capability", 210), ("reason", "Escalation Reason", 150),
                                  ("state", "状态", 80), ("model", "模型", 130), ("outcome", "结果", 110),
                                  ("changed", "代码", 70), ("duration", "耗时", 80)):
            self.job_tree.heading(key, text=title); self.job_tree.column(key, width=width, anchor="w")
        self.job_tree.pack(fill="x")
        ttk.Label(jobs, text="模型战绩（WorkBuddy 内部算力，只读）", style="Muted.TLabel", background=PANEL).pack(anchor="w", pady=(8, 0))
        self.model_tree = ttk.Treeview(jobs, columns=("model", "task", "jobs", "success", "live", "duration", "cost"),
                                       show="headings", height=6)
        for key, title, width in (("model", "模型", 130), ("task", "任务类型", 130), ("jobs", "样本", 55),
                                  ("success", "成功率", 70), ("live", "Live 改进", 80), ("duration", "平均耗时", 90), ("cost", "成本", 110)):
            self.model_tree.heading(key, text=title); self.model_tree.column(key, width=width, anchor="w")
        self.model_tree.pack(fill="both", expand=True, pady=(4, 0))
        self.dev_note = tk.StringVar(value=PENDING)
        ttk.Label(tab, textvariable=self.dev_note, style="Muted.TLabel", wraplength=1250, justify="left").pack(anchor="w", pady=(8, 0))
        ttk.Button(tab, text="打开升级台账", command=lambda: self._open(ROOT / "learning/workbuddy_escalations.jsonl")).pack(anchor="w", pady=(6, 0))
        # Same reasoning as the capability table: three Treeviews of ledger rows that
        # only matter while this tab is on screen.
        self._register_tab_refresh("自动开发", self._refresh_auto_development)
        self._refresh_auto_development()

    def _refresh_auto_development(self) -> None:
        if not hasattr(self, "job_tree"): return
        view = escalation_view()
        buckets = escalation_buckets()
        for state, var in self.escalation_state_vars.items():
            var.set(str((view.get("counts") or {}).get(state, 0)))
        for condition, var in self.bucket_vars.items():
            entry = buckets.get(condition) or {}
            var.set(f"{entry.get('types', 0)} 类 / {entry.get('episodes', 0)} 次" if entry else "0 类 / 0 次")
        for row in self.job_tree.get_children(): self.job_tree.delete(row)
        for record in view.get("records") or ():
            stamp = (record.submitted_at or record.first_seen)
            self.job_tree.insert("", "end", values=(
                stamp.astimezone().strftime("%m-%d %H:%M") if stamp else "—",
                record.capability or record.skill or record.key,
                record.condition or "—",
                STATE_ZH.get(record.state, record.state),
                record.model or PENDING,
                record.outcome or "待对账",
                "已变更" if record.code_changed else "未变更",
                duration_label(record),
            ))
        for row in self.model_tree.get_children(): self.model_tree.delete(row)
        for row in self._model_rows():
            self.model_tree.insert("", "end", values=(row["model"], row["task_type"], row["jobs"], row["success"],
                                                      row["live"], row["duration"], row["cost"]))
        for row in self.failure_tree.get_children(): self.failure_tree.delete(row)
        for failure, count in live_failure_counts().most_common(12):
            priority = failure_priority(count)
            self.failure_tree.insert("", "end", values=(human_reason(failure), count, priority, ""))
        gap = capability_gap_view()
        summary = gap.get("summary") or {}
        leverage = gap.get("highest_leverage") or ()
        notes = [
            f"最近成功开发 Capability：{self._developed_capabilities(view) or '尚无（还没有升级任务达到 Live Verified）'}",
            f"Goal 覆盖：{summary.get('fully_live_verified', 0)}/{summary.get('total', 0)} 完全真机验证"
            f" · 部分 {summary.get('partial', 0)} · 阻塞 {summary.get('blocked', 0)} · 退化 {summary.get('degraded', 0)}"
            f" · 从未尝试 {summary.get('never_tried', 0)}（源：capability_skill_map.json）",
            "最高杠杆缺口：" + ("、".join(
                f"{entry.get('skill_id')}（阻塞 {entry.get('blocked_goals', 0)} 个 Goal）" for entry in leverage[:3]
            ) or "无"),
        ]
        self.dev_note.set("\n".join(notes))

    def _developed_capabilities(self, view: dict[str, Any]) -> str:
        """Capabilities a development job actually pushed to Live Verified."""
        names = [r.capability or r.skill for r in (view.get("verified") or ()) if (r.capability or r.skill)]
        return "、".join(list(dict.fromkeys(names))[:4])

    def _model_rows(self) -> list[dict[str, str]]:
        """Model record, straight from the router's own outcome log.

        Field names are the router's, not this table's: ``Rung`` counts ``samples`` and
        ``live_improvements``.  The first version of this method read ``jobs`` and
        ``live_verified``, which do not exist -- and nothing noticed until the reconcile
        wrote the stats file for the first time, at which point this raised inside a Tk
        callback and blanked the tab.  A test now drives this against that real file.

        Cost is not obtainable: the jobs API exposes no usage field, so the column says
        so instead of inventing an estimate the router might start trusting.
        """
        from winter_agent_v2.workbuddy_model_router import (
            ModelStatsStore, default_stats_path, stats_for,
        )

        try:
            rows = ModelStatsStore(default_stats_path(ROOT)).rows()
        except Exception:  # noqa: BLE001 - an unreadable stats file is an empty table
            return []
        if not rows:
            return []
        out: list[dict[str, str]] = []
        for task_type in sorted({str(row.get("task_type") or "") for row in rows}):
            for model, rung in sorted(stats_for(rows, task_type).items()):
                if not rung.samples:
                    continue
                out.append({
                    "model": model, "task_type": task_type or PENDING, "jobs": str(rung.samples),
                    "success": f"{rung.success_rate:.0%}",
                    "live": f"{rung.live_rate:.0%}" if rung.live_improvements else "0%",
                    "duration": f"{rung.mean_duration:.0f}s" if rung.mean_duration else "—",
                    "cost": "不可得（jobs API 无用量字段）",
                })
        return out


    def _system(self) -> None:
        tab = self._tab("系统")
        # **The whole of L1 on this page is one row, and it is not foldable.**  Every number
        # below is scoped by who is playing -- the watchdog counters, the eleven arbitration
        # rows, the log -- so a page that opened as a stack of shut headers would make the reader
        # guess whose numbers those are.  §六 splits one block here (当前角色 at L1, the other
        # arbitration rows at L3), which is why the block is built as two frames and not one.
        self.global_role_vars = {
            key: tk.StringVar(value="等待双角色状态")
            for key in ("current", "session", "role_a", "role_b", "remaining_a", "remaining_b",
                        "task_completion", "decision", "wakeup", "metrics", "switch_quality",
                        "hard_event", "preempt", "timeline", "telemetry")
        }
        role_cell = ttk.Frame(tab, style="Card.TFrame", padding=(12, 10)); role_cell.pack(fill="x")
        for index, (label, key, label_style) in enumerate((
            ("当前角色", "current", "Section.TLabel"),
            ("角色Session", "session", "Muted.TLabel"),
        )):
            ttk.Label(role_cell, text=label, style=label_style, background=PANEL, width=12).grid(
                row=index, column=0, sticky="nw", padx=(0, 8), pady=(0, 2))
            ttk.Label(role_cell, textvariable=self.global_role_vars[key], background=PANEL,
                      wraplength=1100, justify="left").grid(row=index, column=1, sticky="w",
                                                            pady=(0, 2))
        role_cell.columnconfigure(1, weight=1)
        # L2: the two answers asked *after* the role -- what was decided last, when it wakes next.
        # No rule of its own; the reason is written into ``INERT_FOLDS``.
        ask = self._fold(tab, key="sys_decision", title="最近决策 / 下一唤醒", level=L2,
                         pack={"fill": "x", "pady": (10, 0)})
        for index, (label, key) in enumerate((("最近决策", "decision"), ("下一唤醒", "wakeup"))):
            ttk.Label(ask, text=label, style="Muted.TLabel", background=PANEL, width=12).grid(
                row=index, column=0, sticky="nw", padx=(0, 8), pady=2)
            ttk.Label(ask, textvariable=self.global_role_vars[key], background=PANEL,
                      wraplength=1100, justify="left").grid(row=index, column=1, sticky="w", pady=2)
        ask.columnconfigure(1, weight=1)
        # L3, and one of the two blocks in the window allowed to open itself.  It calls the same
        # rule the 总览 block calls rather than writing its own, so this block and the V2 top-bar
        # dot cannot grade the watchdog differently.
        watch = self._fold(tab, key="runtime_watchdog", title="Runtime Watchdog", level=L3,
                           escalate=self._escalate_watchdog,
                           pack={"fill": "x", "pady": (10, 0)})
        self.runtime_detail_vars = {key: tk.StringVar(value="待刷新") for key in ("thread", "scheduler", "tick", "action", "success", "fatal", "restart", "unexpected")}
        names = (("thread", "Runtime Thread"), ("scheduler", "Scheduler Loop"), ("tick", "Last Tick"), ("action", "Last Action"),
                 ("success", "Last Success"), ("fatal", "Last Fatal"), ("restart", "Watchdog Restart"), ("unexpected", "Unexpected Exit"))
        for index, (key, name) in enumerate(names):
            ttk.Label(watch, text=name, style="Muted.TLabel", background=PANEL).grid(row=index // 4 * 2, column=index % 4, sticky="w", padx=8, pady=(8 if index // 4 else 0, 0))
            ttk.Label(watch, textvariable=self.runtime_detail_vars[key], background=PANEL).grid(row=1 + index // 4 * 2, column=index % 4, sticky="w", padx=8)
            watch.columnconfigure(index % 4, weight=1)
        # L3: the eleven rows that explain "why is it not moving".  By the time they matter the
        # watchdog block above and 需要关注 have already surfaced, so this one stays shut.
        dual = self._fold(tab, key="arbitration", title="角色仲裁 · 单 Scheduler（其余各项）",
                          level=L3, pack={"fill": "x", "pady": (10, 0)})
        for row, (label, key) in enumerate((
            ("角色 A", "role_a"), ("角色 B", "role_b"),
            ("A 今日剩余", "remaining_a"), ("B 今日剩余", "remaining_b"),
            ("今日完成度", "task_completion"),
            ("切换指标", "metrics"), ("切换质量", "switch_quality"),
            ("临近硬时间活动", "hard_event"), ("抢占待执行", "preempt"),
            ("生产遥测", "telemetry"),
            ("最近 10 次选择", "timeline"),
        )):
            ttk.Label(dual, text=label, style="Muted.TLabel", background=PANEL, width=12).grid(
                row=row, column=0, sticky="nw", padx=(0, 8), pady=2)
            ttk.Label(dual, textvariable=self.global_role_vars[key], background=PANEL,
                      wraplength=1100, justify="left").grid(row=row, column=1, sticky="w", pady=2)
        dual.columnconfigure(1, weight=1)
        # The evidence behind the two header cells an operator is most likely to doubt.
        # Both lines are produced by the same functions that drive the cells, so they
        # cannot drift apart from what is displayed.
        evidence = self._fold(tab, key="header_evidence", title="顶部状态的真实依据", level=L3,
                              pack={"fill": "x", "pady": (10, 0)})
        self.maa_note_var = tk.StringVar(value=PENDING)
        self.device_note_var = tk.StringVar(value=PENDING)
        # The local model's two lines (operator directive 2026-09-30).  They belong with the other
        # header cells' evidence because they answer the same question one click down -- which
        # model, is it up, and what did it last decide -- and the verdict column is the verifier's
        # record, never the model's own confidence.  A step a known Skill handled has no row here
        # at all, so no Skill is ever dressed up as model reasoning.
        for index, (label, var) in enumerate((
            ("MAA", self.maa_note_var), ("MuMu", self.device_note_var),
            ("本地模型", self.values["local_model"]),
            ("最近调用", self.values["local_model_last"]),
            ("学习效果", self.values["learning"]),
            ("学习 KPI", self.values["learning_kpi"]),
        )):
            ttk.Label(evidence, text=label, style="Muted.TLabel", background=PANEL, width=8).grid(row=index, column=0, sticky="w", pady=2)
            ttk.Label(evidence, textvariable=var, background=PANEL, wraplength=1000, justify="left").grid(row=index, column=1, sticky="w", pady=2)
        # The buttons went inside the fold with the log they open, rather than staying on the page:
        # §六 puts both at L3, and four buttons that open a directory are not a reason to keep this
        # page's height from shrinking.
        logs = self._fold(tab, key="sys_logs", title="完整日志 / Vision Debug / Replay", level=L3,
                          pack={"fill": "x", "pady": (10, 0)})
        self.log = tk.Text(logs, bg="#070b10", fg="#bccbda", relief="flat", font=("Consolas", 9), padx=12, pady=10, wrap="word", height=14); self.log.pack(fill="both", expand=True)
        for label, path in (("日志目录", LOG_ROOT), ("截图目录", CAPTURE_ROOT), ("Evidence", ROOT / "evidence"), ("Replay", ROOT / "tests/replay")):
            ttk.Button(logs, text=label, command=lambda p=path: self._open(p)).pack(side="right", padx=3)
        self._append("控制台已启动。")

    def _refresh_runtime_snapshot(self, schedule_next: bool = True) -> None:
        snapshot = self.runtime_store.read()
        names = {"AUTO_RUNNING": "● 自动运行", "IDLE": "● 空闲", "GOAL_RUNNING": "● Goal 执行中", "RECOVERING": "● 恢复中", "DEGRADED": "● 退化运行", "SAFE_STOP": "● 安全停止", "FATAL_STOPPED": "● 致命停止", "PAUSED": "● 已暂停"}
        running = snapshot.agent_state in {"AUTO_RUNNING", "GOAL_RUNNING", "RECOVERING"}
        self.values["agent"].set(names.get(snapshot.agent_state, snapshot.agent_state))
        self.values["page"].set(PAGE_ZH.get(snapshot.page, snapshot.page or (UNKNOWN_NOW if running else PENDING)))
        self.values["task_cn"].set("自动目标发现" if snapshot.current_goal == "AUTO_DISCOVERY" else (snapshot.current_goal or PENDING))
        self.values["skill"].set(snapshot.current_skill or PENDING)
        self.values["reason"].set(human_reason(snapshot.reason)); self.values["preconditions"].set(" · ".join(snapshot.preconditions) or PENDING)
        self.values["verifier"].set(human_reason(snapshot.verifier)); self.values["next"].set(human_reason(snapshot.next_action))
        self.values["risk"].set(snapshot.risk if snapshot.risk and snapshot.risk != "UNKNOWN" else PENDING)
        # Two cells, because there are two questions and this cell used to answer both.
        # ``RuntimeSnapshot.confidence`` is the *decision's* confidence (fixed 2026-10-04 --
        # it had four writers, two of which were writing the frame's recognition score into
        # it); the frame's own number lives in ``frame_confidence`` and is shown where the
        # picture is, not in a column headed 当前决策.
        self.values["confidence_decision"].set(
            f"{snapshot.confidence:.0%}" if snapshot.current_skill or snapshot.current_goal else NO_DATA)
        self.values["confidence_frame"].set(f"{snapshot.frame_confidence:.0%}")
        # AUTO is derived from this panel's own control state -- the worker process it
        # spawned, its pause flag, its scheduled restart -- not from the status file a
        # dead worker may have left behind.  See auto_cell().
        worker = self.process
        self.values["mode"].set(auto_cell(
            starting=self.starting,
            worker_alive=bool(worker is not None and worker.poll() is None),
            paused=self.paused,
            stop_requested=self.stop_requested,
            restart_scheduled=self.repeat_after_id is not None,
        ))
        self.values["runtime_state"].set(runtime_status_cn(snapshot.stop_reason, running=running))
        try:
            global_view = global_scheduler_display(ROOT)
            self.global_role_vars["current"].set(global_view.get("current", "暂无"))
            self.global_role_vars["session"].set(global_view.get("session", "尚未建立角色Session"))
            role_lines = list(global_view.get("roles", []))
            self.global_role_vars["role_a"].set(role_lines[0] if role_lines else "暂无角色 A 快照")
            self.global_role_vars["role_b"].set(role_lines[1] if len(role_lines) > 1 else "暂无角色 B 快照")
            self.global_role_vars["remaining_a"].set(global_view.get("remaining_a", "今日完成看板尚未生成"))
            self.global_role_vars["remaining_b"].set(global_view.get("remaining_b", "今日完成看板尚未生成"))
            self.global_role_vars["task_completion"].set(global_view.get("task_completion", "暂无今日任务完成证据"))
            self.global_role_vars["decision"].set(global_view.get("decision", "暂无"))
            self.global_role_vars["wakeup"].set(global_view.get("wakeup", "无"))
            self.global_role_vars["metrics"].set(global_view.get("metrics", "暂无"))
            self.global_role_vars["switch_quality"].set(
                global_view.get("switch_quality", "切换质量样本不足"))
            self.global_role_vars["hard_event"].set(global_view.get("hard_event", "暂无"))
            self.global_role_vars["preempt"].set(
                global_view.get("preempt", "暂无跨角色限时抢占评估"))
            self.global_role_vars["telemetry"].set(global_view.get("telemetry", "生产计数尚未初始化"))
            self.global_role_vars["timeline"].set(global_view.get("timeline", "暂无历史决策"))
        except (AttributeError, OSError, TypeError, ValueError):
            # The live runtime status remains usable when the optional global state
            # artifact has not been created yet or is malformed.
            pass
        # MAA / backend axis.  Taken from the executor ledger and the resolved
        # production interpreter, so this cell cannot claim MAA is fine while the
        # worker is quietly running on ADB capture -- and it reports how old the newest
        # MAA execution is, because "asked for MAA" is not the same as "MAA ran".
        axis = backend_axis(tail_jsonl(BACKEND_LEDGER_PATH, 200))
        report = runtime_interpreter_report()
        self.values["maa"].set(maa_cell(report, axis))
        self.values["backend"].set(axis["label"])
        self.values["backend_detail"].set(f"{axis['mix']} · 最近错误 {axis['errors']} 次")
        # MuMu / 游戏 come from a real device probe running off the UI thread.  Nothing
        # here reads the configuration: a configured serial is not a connected device,
        # and 未探测 is what an unanswered probe says.
        mumu, game = device_cells(self.probes.device_state(), str(self.config["device"]["package_name"]))
        self.values["device"].set(mumu)
        self.values["game"].set(game)
        if hasattr(self, "maa_note_var"):
            self.maa_note_var.set(maa_note(report, axis))
            self.device_note_var.set(self.probes.device_note() or "设备探测正常（adb shell 直读）")
        if snapshot.march_used is not None and snapshot.march_max is not None:
            march = f"{snapshot.march_used}/{snapshot.march_max}"; self.values["march"].set(f"行军：{march}"); self.queues["行军"].set(march)
        queue_names = {"建筑": "building", "科技": "research", "训练": "training", "Intel": "intel", "联盟": "alliance", "活动": "events"}
        for label, key in queue_names.items(): self.queues[label].set(self._compact(snapshot.queues.get(key, {})))
        if snapshot.screenshot_path:
            image_path = Path(snapshot.screenshot_path)
            if image_path.exists() and image_path != self.latest_image_path:
                try:
                    # ``Image.open`` is lazy; the ~14 ms decode only happens if the
                    # preview is actually rendered (see _render_preview).  A tick that
                    # lands on another tab therefore pays nothing for a screenshot
                    # nobody is looking at.
                    self.latest_image_path = image_path
                    self.preview_source = Image.open(image_path)
                    self._preview_rgb = None
                    self._render_preview()
                    self.preview_meta.set(f"Runtime Evidence · {PAGE_ZH.get(snapshot.page, snapshot.page)} · 识别置信度 {snapshot.frame_confidence:.0%}")
                except OSError: pass
        if hasattr(self, "runtime_detail_vars"):
            vals = {"thread": "存活" if snapshot.runtime_thread_alive else "未运行", "scheduler": "存活" if snapshot.scheduler_loop_alive else "未运行",
                    "tick": snapshot.last_tick_time or "无", "action": snapshot.last_action_time or "无", "success": snapshot.last_success_time or "无",
                    "fatal": snapshot.last_fatal_error or "无", "restart": str(snapshot.watchdog_restart_count), "unexpected": str(snapshot.unexpected_worker_exits)}
            for key, value in vals.items(): self.runtime_detail_vars[key].set(value)
        # Both counters are cumulative for the machine, so both are read against the value this
        # window first saw -- see ``_escalate_watchdog`` for why ``> 0`` was not usable.
        self._unexpected_exits = int(snapshot.unexpected_worker_exits or 0)
        self._restart_count = int(snapshot.watchdog_restart_count or 0)
        if getattr(self, "_exits_baseline", None) is None:
            self._exits_baseline = self._unexpected_exits
        if getattr(self, "_restart_baseline", None) is None:
            self._restart_baseline = self._restart_count
        # The per-tab bodies are refreshed only while their tab is on screen; the
        # always-visible strip above them (runtime snapshot, truth dots, device,
        # backend) is refreshed every tick by the code above, because that is what
        # the window exists to show.  This replaced an unconditional rebuild of
        # every page 40 times a minute.
        self._refresh_workbuddy(); self._refresh_visible_tabs()
        if schedule_next: self.root.after(1500, self._refresh_runtime_snapshot)

    def _refresh_workbuddy(self) -> None:
        """Keep every WorkBuddy surface on one set of derived facts.

        The header cell, the overview card and the development tab all read these
        same values, so they cannot disagree about what the development platform is
        doing -- which is the whole point of not building a second state store.
        """
        view = escalation_view()
        gateway = self.probes.gateway()
        self._narrate_pump()
        self._report_device_owner()
        self._refresh_learning()
        self._refresh_truth()
        # Immediately after the audit, because every fold rule reads what that just computed.
        # Outside ``_refresh_truth`` rather than inside it so the early return -- the audit
        # unavailable path -- does not skip it: a window that cannot audit must still shut the
        # blocks it can no longer justify, and must still paint the ones it can.
        self._sync_folds()
        self._maybe_validate()
        label, detail = workbuddy_cell(view, gateway)
        # The header grades the gateway; the job's last known state is detail (P0-3).  This
        # cell read the *ledger* and said 正常 while the gateway was timing out.
        self.values["workbuddy"].set(workbuddy_header(gateway))
        self.values["wb_state"].set(label + (f"（{detail}）" if detail else ""))
        auto_value = getattr(self, "_auto_value", None)
        self.values["wb_gateway"].set(gateway_cell(
            gateway, job_label=label,
            auto_line=(auto_value.value if auto_value is not None else ""),
        ))
        current = view.get("current")
        settled = view.get("pending_verify") or ()
        if current is None and settled:
            current = settled[0]
        self.values["wb_queue_line"].set(
            " · ".join(f"{state} {count}" for state, count in sorted((view.get("counts") or {}).items())) or PENDING
        )
        if current is None:
            self.values["wb_capability"].set(PENDING)
            self.values["wb_reason"].set(PENDING)
            self.values["wb_job"].set(PENDING)
            self.values["wb_model"].set(PENDING)
            self.values["wb_duration"].set(PENDING)
            self.values["wb_job_state"].set(PENDING)
            self.values["wb_improvement"].set(PENDING)
            self.values["wb_result"].set("尚未产生开发任务：升级队列为空。")
            self.probes.watch("")
        else:
            self.values["wb_capability"].set(current.capability or current.skill or current.key)
            self.values["wb_reason"].set(current.condition or PENDING)
            self.values["wb_job"].set(current.job_id or "尚未提交")
            # The model is WorkBuddy's own compute, read back from the ledger it
            # wrote -- the panel never names one and never chooses one.
            self.values["wb_model"].set(current.model or PENDING)
            # "运行时间" only means something once a job exists.  For a gap that has
            # been noticed but not submitted, the honest reading is how long we have
            # been sitting on it -- calling that a job's runtime would overstate it.
            self.values["wb_duration"].set(
                f"未提交（发现于 {duration_label(current)}前）" if not current.submitted_at
                else duration_label(current)
            )
            job = gateway.get("job") or {}
            self.values["wb_job_state"].set(
                f"{current.state}" + (f" · 网关 {job.get('verdict')}" if job.get("verdict") else "")
            )
            self.values["wb_improvement"].set(
                "是" if current.outcome == "LIVE_VERIFIED" else ("否" if current.outcome else "待对账")
            )
            self.values["wb_result"].set(self._describe_escalation(current))
            self.probes.watch(current.job_id)
        kpi = overview_kpis(view=view)
        for key, var in self.kpi.items():
            var.set(kpi.get(key, {}).get("value", NO_DATA))
        if hasattr(self, "kpi_source"):
            # The age of the file each card counted, appended to the card's own source line -- the
            # gap the audit named and the previous pass closed only for the four fact cards.  Set
            # here rather than in ``_refresh_truth`` because this block runs *after* it, so an age
            # written there would be overwritten a few lines later by the static label.
            for key, var in self.kpi_source.items():
                note = self._source_age_note(CATALOG_FRESHNESS.get(key, ""))
                var.set(kpi.get(key, {}).get("source", PENDING) + note)

    def _refresh_truth(self) -> None:
        """The role cell and the conflict banner, from the audit -- never from a literal.

        The operator's rule is that a displayed state must be able to name its source, or
        say it does not know.  So this prints the role *with its status* (``上次已知`` /
        ``未知``), and prints a ``STATE_CONFLICT`` line the moment two artifacts disagree,
        rather than letting the window pick whichever it read last.
        """
        try:
            probe = self.probes.truth()
        except Exception:  # noqa: BLE001 - a panel must not die for a missing probe
            probe = {"ok": False, "report": None}
        from winter_agent_v2.state_truth import STATUS_ZH as STATUS_ZH_TRUTH

        report = probe.get("report")
        if report is None:
            self.values["role"].set(f"{PENDING}（尚未审计）")
            self.values["role_state"].set(
                "角色未知" if not self.probes.truth().get("reason") else "审计不可用"
            )
            self.values["truth"].set("")
            # The verdict cell must not keep a stale 不需要 while the audit it derived that
            # from is unavailable -- "I could not check" and "nothing is wrong" are opposites.
            self.values["intervene"].set("结论：未知（审计不可用，无法判断是否需要你干预）")
            # And the fold badges must not keep last tick's faults either.  Cleared rather than
            # pinned because a failed read cannot manufacture an alarm -- inventing one here
            # would be worse than staying quiet, and the 干预卡 above already carries the
            # "无法判断" statement that a missing audit deserves.
            self._attention_kinds = set()
            self._watchdog_value = None
            return

        role = report.by_name("current_role")
        if role is not None:
            # The operator's format (P0-2): a heading that says 当前角色 may only carry a
            # *current* identity.  A persisted one is 未确认 with its last known value
            # beneath, never the headline -- that is how a 46-hour-old read came to be
            # shown as the logged-in character.
            from winter_agent_v2.state_truth import CATEGORY_OF

            self.values["role"].set(role.headline)
            bits = [f"身份状态：{CATEGORY_OF.get(role.status, role.status)}"
                    f"（{STATUS_ZH_TRUTH.get(role.status, role.status)}）"]
            if role.last_known:
                when = (f"{role.age_seconds / 3600:.1f} 小时前"
                        if role.age_seconds is not None else "时间未知")
                bits.append(f"Last Known：{role.last_known} · {when}")
            elif role.status == "UNKNOWN":
                bits.append("没有任何角色观测记录")
            if role.source:
                bits.append(f"来源 {role.source}")
            self.values["role_state"].set(" · ".join(bits))
        conflicts = report.conflicts
        if conflicts:
            self.values["truth"].set(f"⚠ {conflicts[0].describe()[:150]}")
        else:
            stale = len(report.worst())
            self.values["truth"].set(f"一致性 OK · {stale} 项非当前值" if stale else "一致性 OK")

        # The panels that answer "what is it doing, why, and is it growing".
        self._set_health("dot_auto", report.by_name("auto_state"))
        self._set_health("dot_boot", report.by_name("bootstrap"))
        self._set_health("dot_maa", report.by_name("maa_state"))
        self._set_health("dot_v2", report.by_name("watchdog"))
        # Gateway health, **not** the job's last known state (operator P0-3).  A job that
        # says WORKING says nothing about whether anything is reachable.
        self._set_health("dot_wb", report.by_name("gateway_health"))
        # The one local model (operator directive 2026-09-30).  Graded from the service's own
        # answer plus the config, never from whether a plan happened to be produced: a model that
        # is up but was not needed this cycle is still up.
        self._set_health("dot_model", self.probes.local_model_truth())
        self.values["local_model"].set(local_gui_model_line(ROOT))
        self.values["local_model_last"].set(local_gui_model_last_call(ROOT))
        # §36's Chinese learning lines.  Read from the file ``learning_funnel.refresh`` writes
        # rather than folded here: the panel is on a UI tick and folding the episode stream on
        # every tick would make the console the slowest thing in the process.
        self.values["learning"].set(learning_effect_line(ROOT))
        self.values["learning_kpi"].set(learning_kpi_line(ROOT))
        self._workbuddy = report.by_name("workbuddy_job")
        self._gateway_value = report.by_name("gateway_health")
        # The gateway detail line cites AUTO's real state rather than asserting it is fine.
        self._auto_value = report.by_name("auto_state")

        idle = report.by_name("why_idle")
        if idle is not None:
            marker = "⚠ " if idle.value == "UNEXPLAINED_IDLE" else ""
            self.values["why_idle"].set(f"{marker}{idle.value}")
        mix = report.by_name("executor_mix")
        if mix is not None:
            self.values["executor_mix"].set(f"{mix.value}｜{mix.note}")
        boot = report.by_name("bootstrap")
        if boot is not None:
            self.values["bootstrap"].set(f"{boot.value}\n{boot.note}".strip())
        cov = report.by_name("coverage")
        if cov is not None:
            self.values["coverage"].set(f"{cov.value}\n{cov.note}".strip())
        watch = report.by_name("watchdog")
        if watch is not None:
            self.values["watchdog"].set(f"{watch.value}\n{watch.note}".strip())
        # The same value the V2 top-bar dot is painted from, kept for the fold rules below so a
        # block and its indicator cannot grade one source differently.
        self._watchdog_value = watch

        attention = report.needs_attention()
        # The audit's own *kinds*, kept for the folds.  Read from ``attention`` before
        # ``_attention_with_sources`` prepends the freshness lines, because those are statements
        # about files and already have their own rule (``_escalate_on_sources``); matching on
        # them here would let a stale file open the WorkBuddy block.
        self._attention_kinds = {str(item.get("kind") or "") for item in attention}
        lines = [f"⚠ {a['kind']}：{str(a['detail'])[:110]}" for a in attention[:4]]
        # Stale sources go first because they are the one class of fault the audit cannot
        # see: ``needs_attention`` grades *contradictions between artifacts*, and a file
        # that simply stopped being written contradicts nothing.  It is also why this card
        # can no longer print 暂无需要关注的问题 while a source is dead -- measured
        # 2026-10-04, it said "nothing to watch" beside a 24.9-day-old goal_coverage.json.
        lines = self._attention_with_sources(lines)
        if lines:
            self.values["attention"].set("\n".join(lines))
        else:
            healed = len(report.anomalies) - len(attention)
            self.values["attention"].set(
                f"暂无需要关注的问题" + (f"（{healed} 条已自动恢复，见历史）" if healed else "")
            )
        # The verdict, from the very lines the card above is printing.  Passing them in
        # rather than recomputing is what keeps this cell from becoming a second opinion.
        self.values["intervene"].set(intervention_of(
            problems=lines,
            auto_running=self.process is not None and self.process.poll() is None,
            policy=read_policy_state(POLICY_STATE_PATH),
        ))
        # Each fact card now says how old the file it derived its figure from is.  This is the
        # weaker of the two freshness statements, and deliberately so: it is a property of the
        # *source line*, not a warning, so it is shown whenever the file is over budget --
        # including while AUTO is stopped, when that age is expected and harmless.  The
        # 需要关注 card above is where a stopped writer becomes an alarm, and that one does
        # honour the AUTO check.
        for _title, key, label, source_key in OVERVIEW_FACTS:
            var = getattr(self, "fact_source", {}).get(key)
            if var is not None:
                var.set(label + self._source_age_note(source_key))

        # MuMu and 游戏 are probed live (adb shell), not audited -- they are the two facts
        # that cannot come from a file, which is why they live on the probe thread.
        device = self.probes.device_state()
        ok = device.get("ok")
        self.values["dot_mumu"].set(
            DOT_GOOD if ok is True else (DOT_BAD if ok is False else DOT_UNKNOWN)
        )
        self.values["dot_game"].set(
            DOT_GOOD if ok is True else (DOT_BAD if ok is False else DOT_UNKNOWN)
        )
        for key in ("dot_mumu", "dot_game"):
            label = self.indicators.get(key)
            if label is not None:
                label.configure(fg=GOOD if ok is True else (BAD if ok is False else MUTED))

        # 动作成功 ≠ 目标取得进展.  Read from the production stream, not from the
        # runtime's opinion of itself.
        self._progress_line()

    def _set_health(self, key: str, value: Any) -> None:
        """Paint one top-bar cell from a TruthValue, using the shared six words."""
        label = self.indicators.get(key)
        if value is None:
            self.values[key].set(DOT_UNKNOWN)
            if label is not None:
                label.configure(fg=MUTED)
            return
        from winter_agent_v2.state_truth import health_of

        word, colour = health_of(value)
        self.values[key].set(DOT_TEXT.get(colour, DOT_UNKNOWN))
        if label is not None:
            label.configure(fg={"good": GOOD, "work": GOOD, "idle": WARN,
                                "warn": WARN, "bad": BAD, "unknown": MUTED}[colour])

    def _progress_line(self) -> str:
        """Action progress vs goal progress, from the last steps of the real stream.

        This runs on the 1.5 s tick and ``episodes.jsonl`` is a production log that
        had grown past 150 MB.  Reading it whole to keep 30 lines measured
        **549 ms per call** -- a third of every tick spent on disk -- so it reads a
        bounded tail instead (measured 1.5 ms).  An episode row averages ~13 KB, so
        the window is sized for far more than ``limit`` rows rather than exactly
        enough, and anything that does not fit is simply not shown.
        """
        try:
            rows = tail_jsonl(EPISODES_PATH, limit=30, max_bytes=EPISODE_TAIL_BYTES)
        except (OSError, json.JSONDecodeError):
            rows = []
        if not rows:
            self.values["progress"].set(PENDING)
            return ""
        actions = sum(1 for r in rows if r.get("verifier_ok") is True)
        progress = sum(1 for r in rows if r.get("goal_progress") is True)
        unobserved = sum(1 for r in rows if r.get("goal_progress") is None)
        text = (f"最近 {len(rows)} 步：动作成功 {actions} · 目标进展 {progress}"
                f" · 未观测 {unobserved}")
        if actions and not progress:
            text = "⚠ 无目标进展｜" + text
        self.values["progress"].set(text)
        return text

    def _refresh_learning(self) -> None:
        """Report the knowledge-preload controller, from its own heartbeat.

        The operator's §十三 is a list of questions a human should be able to answer
        without opening a log: is it running, what is it learning, what is missing,
        what is being preloaded, what waits for the device, what was the last success,
        what is next.  This reads the answers out of ``STATE.json`` instead of
        reconstructing them here, so the panel cannot flatter the mechanism.
        """
        path = ROOT / "learning/knowledge_bootstrap/STATE.json"
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.values["learn"].set(
                f"{PENDING}（还没有 STATE.json：控制器尚未在任何进程里跑过一轮）")
            return
        try:
            written = datetime.fromisoformat(str(state.get("written_at")))
            if written.tzinfo is None:
                written = written.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - written).total_seconds()
        except (TypeError, ValueError):
            age = -1.0
        beat = f"心跳 {int(age)}s 前" if age >= 0 else "心跳时间不可读"
        # Three preload intervals: below that a stale file means the window is not
        # running this code, which is the exact "代码支持自动预装但控制器没运行" case.
        if age > 3 * QueuePump.PRELOAD_EVERY * QueuePump.INTERVAL:
            beat = f"⚠ 心跳过期（{int(age / 60)} 分钟）——面板可能未运行新代码"

        coverage = (state.get("coverage") or {}).get("unlocked") or {}
        knowledge = (state.get("coverage") or {}).get("knowledge") or {}
        learning = str(state.get("learning") or "-")
        missing = state.get("learning_missing") or []
        # The running state is translated here from the controller's own vocabulary, so
        # the window and the state file cannot disagree about what "waiting" means.
        from winter_agent_v2.capability_bootstrap import BOOTSTRAP_STATE_ZH

        status = BOOTSTRAP_STATE_ZH.get(str(state.get("status") or ""), str(state.get("status") or "-"))
        parts = [
            f"控制器：运行中（{status}） · {beat} · 阶段 {state.get('stage') or '-'} · "
            f"决策 {state.get('decision') or '-'} · 下一个 {state.get('next_capability') or '-'}",
            f"正在学习：{learning}"
            + (f"（缺 {'、'.join(missing)}）" if missing else "")
            + f" · 正在预装：{state.get('preloading') or '-'}"
            + f" · 等待真机校准：{state.get('waiting_live_verify_count') or len(state.get('awaiting_calibration') or [])}"
            + f" · 知识阻塞：{len(state.get('knowledge_blocked') or [])}",
            f"在飞：开发中 {state.get('developing') or '-'} · 当前 Job {state.get('current_job') or '-'}"
            f" · 队列 {state.get('queue_depth') or 0}（NEW {state.get('queue_new') or 0}）"
            f" · 知识回写 {state.get('last_ingest') or '尚无'}",
            "Coverage（已解锁 {total}）：LIVE_VERIFIED {live}% ({verified} 项) · "
            "Candidate {cand}% · LIVE_TRIED {tried}".format(
                total=coverage.get("total", "-"),
                live=coverage.get("live_verified_percent", "-"),
                verified=coverage.get("live_verified", "-"),
                cand=coverage.get("candidate_percent", "-"),
                tried=coverage.get("live_tried", "-"),
            ),
            "知识：记录 {records} · 够用 {sufficient} · CONFIRMED {confirmed} · "
            "冲突 {conflicts} · 外部来源占比 {external}%（应随运行时间下降）".format(
                records=knowledge.get("records", 0),
                sufficient=knowledge.get("sufficient", 0),
                confirmed=knowledge.get("confirmed", 0),
                conflicts=knowledge.get("conflicts", 0),
                external=knowledge.get("external_share", 0.0),
            ),
        ]
        self.values["learn"].set("\n".join(parts))

    def _report_device_owner(self) -> None:
        """§21's device row, read from the lease file rather than inferred.

        The four words are the operator's, and none of them is "故障": a validation
        holding the device is the system working, and an expired lease reads 恢复AUTO
        because that is what happens next.  A missing file is not an error either -- it
        means gameplay owns the device, which is the normal case.
        """
        try:
            from winter_agent_v2.device_lease import DeviceLease

            lease = DeviceLease(ROOT)
            self.values["lease"].set(f"{lease.state()} · {lease.describe()}")
        except Exception as exc:  # noqa: BLE001 - the row must never break the window
            self.values["lease"].set(f"{PENDING}（{type(exc).__name__}）")

    def _narrate_pump(self) -> None:
        """Report the queue pump on the UI thread, where the log lives.

        The pump runs off-thread and cannot touch Tk, so it only records into its
        own state; the narration and the label happen here.  Only ticks that did
        something are narrated -- a pump printing "nothing to do" every thirty
        seconds would bury the one line that matters, which is the same mistake
        the per-step deferral narration made.
        """
        state = self.pump.state()
        previous = self._pump_prev
        moves: dict[str, int] = {}
        for key in ("passes", "submitted", "released", "reconciled", "errors"):
            now = int(state.get(key) or 0)
            delta = now - int(previous.get(key) or 0)
            if delta:
                moves[key] = delta
            previous[key] = now
        gated = str(state.get("gated") or "")
        passes = int(state.get("passes") or 0)
        if observes_only(self):
            # The cell a reader looks at to ask "is the queue being consumed".  It must
            # not say "运行中" in a window that is not the one consuming it.
            self.values["wb_pump"].set(
                f"只读：另一个实例（pid {self._other_instance}）持有队列时钟；"
                "本窗口不消费、不提交、不启动 AUTO"
            )
        elif gated:
            self.values["wb_pump"].set(f"已暂停：{gated}（用户已停止，不自动提交开发任务）")
        elif not passes:
            self.values["wb_pump"].set(f"{PENDING}（尚未完成第一次消费；每 30 秒一次）")
        else:
            self.values["wb_pump"].set(
                f"运行中 · 已消费 {passes} 次 · 上次 {state.get('last_tick') or '-'}"
                f" · 提交 {state.get('submitted') or 0} · 释放 {state.get('released') or 0}"
                f" · 对账 {state.get('reconciled') or 0}"
                + (f" · 错误 {state.get('errors')}" if state.get("errors") else "")
                + f" · 预载 {state.get('preloads') or 0}"
            )
        # §八: the closed-loop card, and §一's acceptance -- both read from artifacts the
        # running system already writes.  The trace and the breakpoint come from
        # ``unattended_closure`` so the window cannot disagree with the tool an operator
        # would otherwise have to run by hand.
        card = closure_card(ROOT)
        # Kept as data, not only as the sentence below: ``_escalate_dev_loop`` grades ``ok`` and
        # ``breakpoint`` from here, because a rule that parses the rendered line breaks the moment
        # the wording improves.
        self._closure_card = card
        self.values["loop_card"].set(render_loop_card(card))
        if card.get("ok"):
            self.values["loop_trace"].set(
                f"{card.get('trace_id') or '—'}"
                + (f" · job {card.get('job_id')}" if card.get("job_id") else "")
                + (f" · {card.get('capability')}" if card.get("capability") else "")
            )
            # §十一 asks the breakpoint to say what it is *waiting for*, in the operator's own
            # words, when the wait is at the activation rung -- "INCOMPLETE" is true but it
            # does not tell a reader which fact is missing.
            #
            # Named ``record_state``, not ``state``: this block was first written with the
            # shorter name and it happens to sit inside ``_narrate_pump``, whose ``state`` is
            # the pump's snapshot dict.  Shadowing it turned every later ``state.get(...)``
            # into ``AttributeError: 'str' object has no attribute 'get'`` -- and because this
            # runs on the refresh path, the window died moments after opening, which the
            # operator experienced as "点击桌面GUI无法启动".  A local name is not local when the
            # function already has one; the fix is the name, and the guard is that the panel is
            # now started and observed rather than merely imported.
            record_state = str(card.get("record_state") or "")
            breakpoint = str(card.get("breakpoint") or "无断点 · 闭环 PASS")
            if record_state == "LIVE_VERIFY_PENDING" and str(card.get("outcome")) == "VERSION_ACTIVATION_PENDING":
                breakpoint = "VERSION_ACTIVATION_PENDING：等待 after_version 首次被真实 Episode 加载"
            elif record_state == "VERSION_ACTIVE":
                breakpoint = "VERSION_ACTIVE：等待真机校准（Development Validation Lease）"
            self.values["loop_break"].set(breakpoint)
        else:
            self.values["loop_trace"].set("—")
            self.values["loop_break"].set(f"尚未开始：{card.get('reason')}")
        self.values["soak"].set(render_soak(self.probes.soak_payload(),
                                            getattr(self.probes, "_soak_error", "")))
        # §9: the contradictions in what this page is *about to display*, found before a reader
        # has to notice them.  Every value comes from a selector or an artifact that already
        # exists -- including the one trace selector, because comparing two independently chosen
        # "current" traces is what produced the conflict this catches.
        try:
            from winter_agent_v2.consistency import render_conflicts, state_conflicts

            # The development view, folded from the escalation ledger by the one helper that owns
            # that answer -- the same call two sibling refreshes already make.  It was missing here,
            # so ``view`` resolved to nothing and the NameError was swallowed by the broad except
            # below: the consistency card failed on every refresh and said nothing about it, which
            # is the exact shape of silence this panel exists to prevent.
            view = escalation_view()

            development = view.get("current")
            findings = state_conflicts({
                "closure_trace_id": card.get("trace_id") if card.get("ok") else "",
                "development_trace_id": str(getattr(development, "key", "") or ""),
                "verified_episode_id": card.get("live_verify_episode_id") or "",
                "reuse_episode_id": card.get("production_reuse_episode_id") or "",
                "job_state": str(getattr(development, "state", "") or ""),
                "displayed_phase": str(self.values["wb_job_state"].get() or ""),
                "lease_released_at": str(getattr(self, "_lease_released_at", "") or ""),
                "lease_current_holder": self._lease_holder_label(),
                "lease_displayed_holder": str(self.values["lease"].get() or ""),
            })
            self.values["consistency"].set(render_conflicts(findings))
        except Exception as exc:  # noqa: BLE001 - a check must never take the page down
            self.values["consistency"].set(f"{PENDING}（检查失败 {type(exc).__name__}）")
        # §1-§5: is this window itself stale?  Checked here, on the same refresh that recomputes
        # the gateway cell -- because the measured symptom was exactly this cell showing 异常
        # from code that had already been fixed on disk.
        self._check_control_plane_reload()
        if moves.get("submitted"):
            self._append(f"开发队列：已向 WorkBuddy 提交 {moves['submitted']} 个真实任务。")
        if moves.get("released"):
            self._append(f"开发队列：释放 {moves['released']} 条缺口（真机已自行证明，不派开发任务）。")
        if moves.get("reconciled"):
            self._append(f"开发队列对账 {moves['reconciled']} 个任务（{state.get('last_line') or ''}）。")
        if moves.get("errors"):
            self._append(f"开发队列本轮 {moves['errors']} 个错误：{state.get('last_error') or '见台账'}")
        # The preload pass is narrated only when its answer *changes*: 'resting,
        # because the main loop is not proven yet' would otherwise print every ten
        # minutes forever, which is the same mistake as the per-step deferral line.
        preload_note = str(state.get("preload_note") or "")
        if preload_note and preload_note != previous.get("preload_note"):
            previous["preload_note"] = preload_note
            self._append(f"能力预载（后台低优先级）：{preload_note}")
        # The watchdog half of §十三: "Controller 是否运行" has to have an answer, and a
        # dead clock has to come back by itself rather than waiting for a human to
        # notice that nothing has been preloaded for a week.
        if not self.pump.alive():
            if self.pump.revive():
                self._append("能力预载控制器线程已停止，看门狗已重启该线程。")
                previous.pop("preload_note", None)

    def _describe_escalation(self, record: Any) -> str:
        """One honest line about what a finished development job achieved."""
        parts = [f"结果 {record.outcome or '待对账'}"]
        if record.repairs_used:
            parts.append(f"已用修复预算 {record.repairs_used}")
        parts.append("代码已变更" if record.code_changed else "代码未变更")
        if record.notes:
            parts.append(str(record.notes[-1])[:200])
        if record.evidence:
            parts.append(f"证据 {Path(str(record.evidence[0])).name}")
        return " · ".join(parts)

    # ``_logs()`` (日志) was removed here on 2026-10-04 -- the page was never built, and the
    # window's log is already on 系统 as a real Text widget that ``_append`` writes to.
    #
    # ``_settings()`` (设置) went with it, and the two live things it held were moved rather
    # than dropped: the 连续运行 checkbox now sits on 运行·策略 (it is read by the runtime
    # handoff, the watchdog and the stop path, and persisted), and the four 打开目录 buttons
    # went with it.  Its ``resource_policy`` comboboxes were **not** moved, because they set
    # nothing: neither the panel nor ``winter_agent_v2`` ever reads those StringVars, so they
    # were controls that changed no policy -- which is worse than no control, since the
    # operator would believe something had been set.  The rules themselves are still shown on
    # 运行·策略 as what they are (a read-only list, with 真实支付 locked).

    def _tick(self) -> None:
        self.values["clock"].set(datetime.now().strftime("%H:%M:%S")); self.root.after(1000, self._tick)

    def _append(self, message: str) -> None:
        line = f"{datetime.now():%H:%M:%S}  {message.rstrip()}"
        if hasattr(self, "log"): self.log.insert("end", line + "\n"); self.log.see("end")
        self.event_lines = (self.event_lines + [line])[-20:]
        if hasattr(self, "event_text"): self.event_text.set("   |   ".join(self.event_lines[-3:]))
        self._append_to_file(line)

    def _append_to_file(self, line: str) -> None:
        """Keep the window's own narration on disk, because it is evidence.

        The startup preflight decides whether AUTO starts at all, and a decision
        that only ever existed inside a Tk text widget cannot be audited afterwards
        -- the acceptance test for "启动 GUI = 自动运行 + 自动开发" would have to
        take the window's word for it.  Bounded so an unattended month cannot fill
        the disk: past ``PANEL_LOG_MAX_BYTES`` the file keeps its tail.
        """
        try:
            LOG_ROOT.mkdir(parents=True, exist_ok=True)
            if PANEL_LOG_PATH.exists() and PANEL_LOG_PATH.stat().st_size > PANEL_LOG_MAX_BYTES:
                tail = PANEL_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()[-500:]
                PANEL_LOG_PATH.write_text("\n".join(tail) + "\n", encoding="utf-8")
            with PANEL_LOG_PATH.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            # A log that cannot be written must never take the window down.
            pass

    # ``_sync_tasks()`` and ``_toggle_task()`` were removed here on 2026-10-04: the only page
    # that could reach them was ``_tasks``, which is never built, so both were unreachable
    # code whose effect was a config round-trip nothing reads -- ``task_enabled`` has no
    # consumer anywhere in ``winter_agent_v2/``.  ``task_toggle_label`` and the
    # load/save pair stay: they are the persistence contract for
    # ``config/control_panel_state.json`` and are covered by tests of their own.
    #
    # ``_sync_tasks`` was also the only writer of the 奖励 row in 总览's 今日 Goal 摘要, which
    # is why that row was removed with it: a row whose last writer is gone reads "待执行"
    # forever, and this audit's rule is that a field the system cannot fill must not be drawn.

    def _save_panel_state(self) -> None:
        save_task_selection(
            PANEL_STATE_PATH,
            {name: var.get() for name, var in self.task_enabled.items()},
            self.continuous.get(),
        )

    def refresh(self) -> None:
        self._refresh_runtime_snapshot(schedule_next=False)
        self._append("已从统一 Runtime Snapshot 刷新；面板只读现有状态文件，不自行识别。")

    def take_screenshot(self) -> None:
        self._append("截图由 Runtime 统一采集；已显示最新 Runtime Evidence。"); self.refresh()

    def _refresh_worker(self) -> None:
        self.events.put(("note", "状态由 Runtime Snapshot 统一提供。"))

    # -- startup semantics -------------------------------------------------
    #
    # 启动 GUI = 启动整个无人值守系统 (operator, 2026-09-18), in this order:
    #   operator intent -> real preflight -> AUTO, with the WorkBuddy gateway
    #   reported but never a blocker, and the operator's own stop remembered.
    PREFLIGHT_TIMEOUT_SECONDS = 60.0
    CORE_RETRY_MS = 60_000

    def _kill_worker_tree(self) -> None:
        """Stop the worker *and its children*, so closing leaves no orphan.

        The worker is spawned through the production interpreter, and on Windows
        that is a venv redirector: the process this panel holds is a stub whose
        child is the one really driving the device (and MAA, 12.1 ms against
        246.2 ms).  Terminating the stub can leave that grandchild running -- an
        orphan AUTO worker still tapping the game with no window left to stop it.
        So the tree goes down, and the handle is cleared either way.
        """
        process = self.process
        if process is None or process.poll() is not None:
            self.process = None
            return
        killed = False
        if os.name == "nt":
            try:
                killed = _background_run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True, text=True, timeout=15, check=False,
                ).returncode == 0
            except Exception:  # noqa: BLE001 - fall through to terminate()
                killed = False
        try:
            process.terminate()
            process.wait(timeout=10)
        except Exception:  # noqa: BLE001 - a worker that will not die shows up in poll()
            pass
        self._append(f"worker 已停止（进程树{'整体' if killed else '未能整体'}结束）。")
        self.process = None

    def _run_startup_preflight(self) -> dict | None:
        """The real preflight, run once at startup with the production interpreter.

        Same command the desktop launcher runs, so what the window reports and
        what the launcher enforces cannot drift.  Bounded, because a hanging
        emulator probe must not hold the window hostage.
        """
        command = [runtime_python_path(), str(ROOT / "tools/preflight.py"), "--json"]
        try:
            done = _background_run(command, cwd=str(ROOT), capture_output=True, text=True,
                                   timeout=self.PREFLIGHT_TIMEOUT_SECONDS, check=False)
        except Exception as exc:  # noqa: BLE001 - a preflight that cannot run is a failure
            self._append(f"启动预检未能执行：{type(exc).__name__}: {exc}")
            return None
        try:
            data = json.loads(done.stdout or "{}")
        except json.JSONDecodeError:
            self._append("启动预检输出无法解析；按未通过处理。")
            return None
        return data if isinstance(data, dict) else None

    def _log_preflight(self, report: dict) -> None:
        sections = report.get("sections") or {}
        interpreter = sections.get("interpreter") or {}
        device = sections.get("device") or {}
        gateway = sections.get("gateway") or {}
        self._append(
            f"预检·核心：Runtime {'OK' if interpreter.get('ok') else 'FAIL'} "
            f"({interpreter.get('exe')}) · MuMu {'OK' if device.get('ok') else 'FAIL'} "
            f"({device.get('serial')} {device.get('resolution') or device.get('want_resolution')} "
            f"前台 {device.get('foreground')})")
        # A device that is not ready but that this window can repair is not a refusal,
        # and it must not read as one either.  Measured 2026-10-01: the emulator sat on
        # the Android launcher with the game not running, preflight called it a core
        # blocker, and AUTO was never started -- so ``_ensure_device``, the only thing
        # that launches MuMu and foregrounds the game, was never reached.  The line
        # says which repair is about to happen so the operator can tell a recovery
        # from a silent start on a broken device.
        for name in report.get("recovering") or []:
            section = sections.get(name) or {}
            self._append(
                f"预检·可恢复：{name} 未就绪（{section.get('not_ready_reason') or 'unknown'}），"
                f"运行时会执行 {section.get('repair') or 'recovery'} 并退避重试；仍启动 AUTO。")
        if gateway.get("ok"):
            self._append(f"预检·辅助：WorkBuddy Gateway OK（{gateway.get('base_url')}）")
        else:
            self._append(f"预检·辅助：WorkBuddy Gateway 不可用（{gateway.get('reason')}）"
                         "；自动开发标记为不可用，后台周期重试，不影响 AUTO。")

    def _auto_development_allowed(self) -> bool:
        """The pump's gate.  The operator's own stop outranks the clock.

        A paused or between-rounds AUTO must *not* stop the pump -- the queue is
        still owed a consumer, and that is exactly the case the operator reported.
        An explicit stop is different: their rule is that nothing may restart
        automatic work after a stop without them, and submitting development jobs
        is automatic work.

        A second window is refused outright: one device, one queue, one clock.
        """
        if observes_only(self):
            return False
        return self.operator_intent != "STOPPED"

    def _maybe_autostart(self) -> None:
        """The only auto-start path: intent first, then a real preflight, then AUTO."""
        if observes_only(self):
            # Two AUTO trees on one device.  The owner keeps running the system; this
            # window only observes it.
            self._append(
                f"不自动启动 AUTO：另一个实例（pid {self._other_instance}）正在运行。"
                "本窗口只读。"
            )
            self._idle_buttons()
            return
        if not self.config.get("auto_execution", False):
            self._append("manual mode (config auto_execution=false)：等待用户点击“开始自动运行”。")
            return
        if self.operator_intent != "RUNNING":
            stopped = self.operator_intent == "STOPPED"
            self._append(f"不自动启动：上次由用户{'停止' if stopped else '暂停'}"
                         "，只有点击“开始自动运行”才会恢复。")
            self._idle_buttons()
            self.runtime_store.update(agent_state=AgentState.IDLE.value, runtime_thread_alive=False,
                                      scheduler_loop_alive=False,
                                      stop_reason="USER_STOPPED" if stopped else "USER_PAUSED")
            return
        if not self.continuous.get():
            self._append("不自动启动：连续运行已关闭。")
            return
        self._append("启动预检：真实 preflight（MuMu / MAA / RapidOCR / Runtime / WorkBuddy Gateway）")
        report = self._run_startup_preflight()
        self.startup_preflight = report
        if report is None:
            self._append("预检未通过（无法执行）；不启动 AUTO。诊断：python tools/preflight.py")
            self._idle_buttons()
            return
        self._log_preflight(report)
        if not report.get("core_ok"):
            blockers = "、".join(report.get("blockers") or []) or "unknown"
            self._append(f"预检未通过：核心环境不可用（{blockers}）；不启动 AUTO，"
                         f"{self.CORE_RETRY_MS // 1000} 秒后重试。")
            self._idle_buttons()
            self.runtime_store.update(agent_state=AgentState.DEGRADED.value, runtime_thread_alive=False,
                                      scheduler_loop_alive=False, stop_reason=RUNTIME_ENV_STOP_REASON,
                                      reason=f"预检未通过：{blockers}", next_action="修复核心环境后自动重试")
            self._cancel_repeat()
            self.repeat_after_id = self.root.after(self.CORE_RETRY_MS, self._maybe_autostart)
            return
        self.start()

    def start(self) -> None:
        worker = self._worker_thread
        if worker is not None and worker.is_alive():
            # A stopped worker may still be finishing one bounded ADB call.  Do
            # not create a second device owner; defer an explicit restart until
            # the previous thread has returned.
            if self.stop_requested or self.paused:
                if not self.repeat_after_id:
                    self.repeat_after_id = self.root.after(250, self.start)
            return
        self._worker_thread = None
        if self.process is not None or self.starting: return
        if self.paused:
            self._consecutive_worker_crashes = 0
        blocker = runtime_env_blocker()
        if blocker is not None:
            # Refuse rather than degrade.  Starting work on an interpreter that
            # cannot import MAA means every measurement afterwards is taken
            # through a path the project already paid to replace, and the run
            # still looks healthy.  See runtime_interpreter_report() above.
            self._append(f"未启动：运行环境不满足生产要求（{blocker}）。")
            for line in runtime_interpreter_report().describe().splitlines():
                self._append(f"    {line}")
            self._append("    诊断：python tools/preflight.py；"
                         "修复：在 config/v2.json 的 runtime.python_path 指定可用解释器。")
            self.runtime_store.update(
                agent_state=AgentState.DEGRADED.value, runtime_thread_alive=False,
                scheduler_loop_alive=False, stop_reason=RUNTIME_ENV_STOP_REASON,
                reason=f"解释器不可用：{blocker}", next_action="修复运行环境后重新启动",
            )
            self.events.put(("note", f"未启动：{blocker}"))
            return
        # A development agent may have just written code.  Each cycle is a fresh
        # subprocess that imports vision/brain/skills from disk, so the new code
        # takes effect by itself -- what must not happen is importing a tree
        # mid-write, which is the failure `run_live.py`'s VERIFIER_MAPPING_CORRUPT
        # guard was added for.  The wait is bounded inside the signal.
        reload_signal, deferral = reload_deferral()
        if deferral:
            self._append(f"延后启动：{deferral.reason}")
            self.events.put(("note", deferral.reason))
            self.runtime_store.update(
                agent_state=AgentState.RECOVERING.value, runtime_thread_alive=False,
                scheduler_loop_alive=False, stop_reason=REQUEST_KIND,
                reason=deferral.reason, next_action="等待代码写入落定后自动继续",
            )
            self.repeat_after_id = self.root.after(RELOAD_RETRY_MS, self.start)
            return
        reload_signal.clear("settled")
        self.starting = True
        self._append(f"运行环境预检通过：{runtime_python_path()}")
        if self.repeat_after_id: self.root.after_cancel(self.repeat_after_id); self.repeat_after_id = None
        self.stop_requested = self.paused = False; self._device_launch_requested = False; self._running_buttons()
        # An explicit 开始 (or an allowed auto-start) is the operator saying
        # "run": that is what clears a remembered stop.
        self.operator_intent = save_operator_intent(PANEL_STATE_PATH, "RUNNING", "started")
        self.runtime_store.update(agent_state=AgentState.RECOVERING.value, runtime_thread_alive=True,
                                  scheduler_loop_alive=False, stop_reason=None, last_fatal_error=None,
                                  current_goal=None, current_skill=None, reason="启动并校准真实客户端",
                                  verifier=None, next_action="启动唯一 Scheduler")
        self._append("自动运行已启动：Goal 与 Universal Skill 由唯一 Scheduler 决定。")
        self._worker_thread = threading.Thread(target=self._run_unified_worker, name="unified-auto-worker", daemon=True)
        self._worker_thread.start()

    def _check_control_plane_reload(self) -> None:
        """Is this window running code that is no longer on disk?

        Measured 2026-09-18: the gateway fix was committed, and the window went on showing
        "WorkBuddy 异常" at the top.  Nothing was wrong with the fix -- the process had imported
        the old modules at start-up and no code path ever told it the files under it had
        changed.  A worker reload would not have helped: the stale code was in the window.

        Two facts are printed, in the operator's words: the version this process *loaded*, and
        the version on disk now.  When they differ and a control-plane file is among the
        changes, the marker is written and the window says 待重载 rather than pretending.

        The restart itself waits for a safe point (:func:`safe_to_reload`): an atomic gameplay
        step in flight, a device lease, or an operator STOP/PAUSE each refuse it.  A process
        cannot replace itself through its own imports, so the restart is delegated to the
        project's existing launcher -- there is no second reload mechanism here.

        Measurement and decision are split by thread.  Reading the versions is I/O -- a ``git
        rev-parse``, then a content hash of every version-relevant dirty path, measured at
        1.03 s on the pinned tree -- so :class:`ControlPlaneProbe` does it on a background
        thread and this method, which runs every 1.5 s on the UI thread, only reads the latest
        answer and acts on it.  Before that split the UI thread was inside ``git`` for two
        thirds of every cycle, which was the 卡顿.

        The answer can therefore be up to :data:`CONTROL_PLANE_INTERVAL` seconds old.  That is
        deliberately acceptable: the event being detected is a commit touching a file this
        window imports, and acting on it means a restart at a safe point -- not a reaction
        that has to land inside a second.
        """
        answer = self.control_plane_probe.latest()
        if answer is None:
            # First cycle after start-up: the background thread has not answered yet.  Say so
            # rather than showing the previous window's opinion, and never block waiting.
            self.values["control_plane"].set(f"{PENDING}（后台检查中）")
            return
        if answer.error:
            self.values["control_plane"].set(f"{PENDING}（{answer.error}）")
            return
        try:
            from winter_agent_v2.control_plane_reload import (
                control_plane_signal, needs_reload, reload_reason, safe_to_reload,
            )
        except Exception as exc:  # noqa: BLE001 - a probe must never take the window down
            self.values["control_plane"].set(f"{PENDING}（{type(exc).__name__}）")
            return

        loaded_token = answer.loaded_token
        current_token = answer.disk_token
        changed = answer.changed
        reason = reload_reason(loaded_token, current_token, changed)
        stale = needs_reload(loaded_token, current_token, changed)

        self.values["control_plane_loaded"].set(loaded_token[:12] or "未记录")
        self.values["control_plane_disk"].set(current_token[:12] or "读不到")
        if not stale:
            self.values["control_plane"].set("已同步（无需重载）")
            # Retire the marker an earlier window left behind.  Measured 2026-10-04: this
            # marker's only writer is the ``stale`` branch below, and nothing ever withdrew it,
            # so after a restart it stayed on disk reading "本进程加载的 08886209 已被 90a9990
            # 取代" while the process *was* 90a9990 -- permanently true and permanently wrong.
            # ``needs_reload``'s own docstring names the cost: telling the operator to restart
            # for nothing trains them to ignore the one that matters.
            #
            # Not disguised by hand-deleting it once: the defect returns on the next
            # deployment.  The reader that can prove the claim false is the one that retires
            # it, and that reader is this branch.
            #
            # A read-only second window runs this check too, and each process can only speak
            # for itself -- but the marker is one shared file and a window that really is
            # behind re-raises it on its own next tick (1.5 s), so a withdrawal cannot stick
            # against a true claim.  That is why no second ownership rule is needed here.
            try:
                control_plane_signal().clear("superseded_claim_resolved")
            except Exception:  # noqa: BLE001 - retiring a notice must never take the window down
                pass
            return
        self.values["control_plane"].set(f"待重载 -- {reason}")
        try:
            # No explicit root: the marker's root is ``control_plane_reload.MARKER_ROOT``, a
            # module attribute, so a test run can point it at a scratch root.  Passing ``ROOT``
            # here bypassed that and wrote the *live* marker -- which asks the running window to
            # restart itself -- every time a panel test ran against a dirty tree.
            control_plane_signal().request(
                job_id="", reason=reason, evidence=tuple(changed[:12]),
            )
        except Exception:  # noqa: BLE001
            pass

        ok, why = safe_to_reload(
            atomic_step_running=self.process is not None and self.process.poll() is None,
            lease_holder=self._lease_holder_label(),
            operator_intent=self.operator_intent,
            panel_owned=not observes_only(self),
        )
        if not ok:
            # Reported, not silent: "why nothing happened" is the question the operator has
            # had to read logs to answer, and the answer here is a real state.
            self._reload_waiting = why
            return
        self._reload_waiting = ""
        self._start_control_plane_reload(reason)

    def _lease_holder_label(self) -> str:
        """Who holds the device right now, as the lease file reports it (never inferred)."""
        try:
            from winter_agent_v2.device_lease import DeviceLease

            # No explicit root, so the lease root stays the redirectable ``device_lease.DEFAULT_ROOT``;
            # passing ``ROOT`` bypassed the test harness's redirect and read the live lease.
            return str(DeviceLease().holder() or "")
        except Exception:  # noqa: BLE001
            return ""

    def _start_control_plane_reload(self, reason: str) -> None:
        """Report that the control plane changed, and wait for a human to restart it.

        It used to hand the restart to ``panel_restart.py --restart``, on the reasoning that a
        process cannot re-import itself into a new version.  That reasoning is still sound; the
        delegation is what does not survive, and the helper's own tree kill is why (see below).
        So until a replacement is driven from outside the doomed process tree, the honest
        behaviour is to say so and keep running: a control-plane edit must not be able to close a
        live panel and leave nothing behind.

        Guarded by a flag so the notice is reported once rather than every refresh.
        """
        if self._reload_started:
            return
        self._reload_started = True
        # The delegated restart is disabled until it is proven to survive, because it does not
        # survive today and it takes the panel down permanently.
        #
        # ``panel_restart.py --restart`` is ``cmd_stop()`` then ``cmd_start()``, and ``cmd_stop``
        # ends in ``taskkill /PID <panel> /T /F`` (panel_restart.py:290).  ``/T`` follows
        # *parentage*, and this helper is spawned BY the panel (below, previously
        # ``winproc.spawn_detached``), so the helper is inside the tree it is killing: it kills
        # itself before ``cmd_start`` is ever reached.  The project already knows this shape --
        # ``_ensure_gateway_after_stop``'s docstring says "taskkill /PID <panel> /T follows
        # parentage, and DETACHED_PROCESS does not change parentage", measured 2026-09-18 -- and
        # it fixed it for the gateway, whose resurrection is called from inside the helper after
        # the kill.  That call is unreachable for the same reason.
        #
        # Measured 2026-09-20, twice, and the log states it: panel_reload.log for the 18:18 run
        # reads "stopping panel tree at pid 19612" and then ends.  The next line the helper would
        # print is "workers left after the kill: N" (panel_restart.py:294) and the line after that
        # is cmd_start().  Neither appears, for either attempt (pid 2272 and pid 19612), and the
        # 12:37 one was launched by the operator's own desktop entry -- so this is not the
        # development host reaping children, which is what I wrongly concluded earlier.
        #
        # Until a replacement is driven by something outside the doomed tree, a control-plane edit
        # must not be allowed to close a running panel.  The operator's rule for this round is
        # explicit: "禁止让未经验证的重载流程再次自动关闭正在运行的正式面板 … 可以暂时改为
        # 提示待重载，并在安全点等待人工重启".  STOP / PAUSE, the device lease and the production
        # isolation checks are untouched; only the self-kill is.
        self._append(f"控制面已变更（{reason}）。**自动重载暂时停用**："
                     "重启助手会被它自己的 taskkill /T 杀掉，窗口不会回来。"
                     "请在安全点手动重启（Start-Winter-Agent-V2.cmd），AUTO 意图与队列会随新窗口恢复。")

    def _maybe_validate(self) -> None:
        """Drive a bounded calibration run for a version that is waiting to be examined.

        This is the other half of the device hand-off: the queue *asks* for the device
        for a ``LIVE_VERIFY_PENDING`` record (and refuses to ask when no panel heartbeat
        is fresh), and this method is the consumer that then actually drives it.  Without
        this half the request would make V2 stand down for nobody.

        It never takes the device by force: it acts only while a validation lease is
        already held, and only between AUTO rounds.  ``_run_validation_worker`` always
        releases in a ``finally``, so a crash cannot freeze gameplay.
        """
        if observes_only(self):
            # The clock's owner drives calibrations; a second window driving its own
            # would be the second device owner the lease exists to prevent.
            return
        if self.validating or self.process is not None or self.starting:
            return
        if self.paused or self.stop_requested or self.operator_intent != "RUNNING":
            return
        try:
            from winter_agent_v2.device_lease import OWNER_DEVELOPMENT_VALIDATION, DeviceLease

            holder = DeviceLease(ROOT).holder()
        except Exception:  # noqa: BLE001 - a status read must not break the window
            return
        if holder is None or holder.owner != OWNER_DEVELOPMENT_VALIDATION:
            return
        goal = self._pending_validation_goal(holder.trace_id)
        if not goal:
            # Nothing to aim a run at: hand the device straight back rather than leave
            # gameplay frozen waiting for a validation that cannot be pointed anywhere.
            self._release_validation_lease(
                "NO_GOAL", "the pending record names no goal", expect_key=holder.trace_id,
            )
            return
        self.validating = True
        threading.Thread(target=self._run_validation_worker,
                         args=(goal, holder.trace_id or "", holder.lease_id or ""), daemon=True).start()

    def _pending_validation_record(self, key: str) -> dict[str, Any]:
        """The record a validation cycle is about to examine, by trace where one is known.

        Operator §2/§3: the cycle needs more than a goal.  It has to say which trace, which job
        and which capability it is examining, and *which version it must be running* for its
        evidence to count -- and only the ledger knows those.

        ``key`` is authoritative: when a trace is named, only that trace may be validated.
        Falling back to "the first LIVE_VERIFY_PENDING" is only for the case where no trace was
        named at all, and the caller is told that is what happened by the returned record
        carrying the key it actually resolved to.
        """
        try:
            from winter_agent_v2.escalation_queue import EscalationLedger, fold

            snapshot = fold(EscalationLedger(Path(_ESCALATION_LEDGER_PATH)).events())
        except Exception:  # noqa: BLE001
            return {}
        record = snapshot.get(key) if key else None
        if record is None and not key:
            waiting = [r for r in snapshot.records.values() if r.state == "LIVE_VERIFY_PENDING"]
            record = waiting[0] if waiting else None
        if record is None:
            return {}
        return {
            "key": str(record.key or ""),
            "job_id": str(record.job_id or ""),
            "capability": str(record.capability or ""),
            "goal": str(record.goal or ""),
            # The version this cycle must be running.  Empty means the record has no measured
            # after_version yet, and the gate in run_live deliberately does nothing when it is
            # empty -- so a missing version cannot silently pass as a match.
            "after_version": str(record.after_version or ""),
            "state": str(record.state or ""),
        }

    def _pending_validation_goal(self, key: str) -> str:
        """The goal the pending version was produced for, read from the one ledger."""
        return str(self._pending_validation_record(key).get("goal") or "")

    def _release_validation_lease(self, result: str, reason: str, *, expect_key: str = "") -> None:
        try:
            from winter_agent_v2.escalation_queue import EscalationLedger, EscalationQueueAdapter

            EscalationQueueAdapter(
                root=ROOT, ledger=EscalationLedger(Path(_ESCALATION_LEDGER_PATH))
            ).release_validation_lease(result=result, reason=reason, expect_key=expect_key)
        except Exception as exc:  # noqa: BLE001 - the device must be returned, not reported
            self.events.put(("note", f"真机校准：释放租约失败（{type(exc).__name__}），TTL 到期后自动归还。"))

    def _run_validation_worker(self, goal: str, key: str, lease_id: str = "") -> None:
        """One bounded run of the unified executor, aimed at the pending capability.

        Bounded (``VALIDATION_MAX_ACTIONS``) on purpose: a calibration is an examination,
        not a gaming session, and a long one would hold the device the operator wants
        returned to normal play.  Same executor as AUTO -- there is no second one.
        """
        result = "VALIDATION_FAILED"
        try:
            self.active_panel_task = "VALIDATION"
            self.events.put(("note", f"真机校准：已取得设备（{key or 'unknown'}），开始有界验证运行 --goal {goal}。"))
            self._ensure_device()
            LOG_ROOT.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            # Operator §2: the whole validation context goes on the command line, read from the
            # record rather than only its goal.  Without these five fields the episode produced
            # here could not be attributed to a trace or a version, so nothing downstream could
            # honestly credit it -- the examination would run and prove nothing.
            record = self._pending_validation_record(key)
            if not record:
                self.events.put(("note",
                                 f"真机校准：台账里找不到 {key or 'unknown'} 的记录，"
                                 "不启动验证进程（不猜、不碰设备）。"))
                result = "VALIDATION_CONTEXT_MISSING"
                return
            command = validation_command(
                record,
                capture_dir=str(CAPTURE_ROOT / "validation" / stamp),
                serial=self.device.serial,
                lease_id=lease_id,
            )
            process = _background_popen(command, cwd=str(ROOT), stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True,
                                        encoding="utf-8", errors="replace")
            output, code = await_worker(process, label="真机校准")
            (LOG_ROOT / "validation.log").write_text(output or "", encoding="utf-8")
            result = f"EXIT_{code}"
            parsed = parse_runtime_result(output or "")
            self.events.put(("note", f"真机校准：验证运行结束（{result}），"
                                     f"停止原因 {parsed.get('stop_reason') or '未知'}。"))
        except BaseException as exc:  # noqa: BLE001 - a dead validation is a reported state
            result = f"WORKER_FAILURE_{type(exc).__name__}"
            try:
                write_worker_crash_report(where="validation_worker", exc=exc,
                                          snapshot=self.runtime_store.read())
            except Exception:  # noqa: BLE001
                pass
            self.events.put(("note", f"真机校准：验证运行失败（{type(exc).__name__}: {exc}）。"))
        finally:
            self.validating = False
            # §15: the device goes back whatever the outcome was.
            self._release_validation_lease(
                result, f"validation run for {key or goal} finished", expect_key=key,
            )

    def _run_unified_worker(self) -> None:
        """Lifecycle adapter only; it never selects a Goal or Skill."""
        recovery = None
        recovery_started_at = None
        self._device_recovery_retry_count = 0
        try:
            blocker = runtime_env_blocker()
            if blocker is not None:
                raise RuntimeError(f"{RUNTIME_ENV_STOP_REASON}: {blocker}")
            self.active_panel_task = "AUTO"
            recovery_started_at = datetime.now(timezone.utc).isoformat()
            self._device_recovery_started_at = recovery_started_at
            recovery = retry_until_ready(
                self._ensure_device,
                should_stop=lambda: self.stop_requested or self.paused,
                wait=self._wait_for_worker_retry,
                is_recoverable=lambda exc: classify_worker_failure(str(exc)) == "ENVIRONMENT",
                on_retry=self._record_device_recovery_retry,
                initial_delay_seconds=5.0,
                max_delay_seconds=60.0,
            )
            if not recovery.ready:
                return
            if recovery.retries:
                self._record_device_recovered(recovery, recovery_started_at)
            if self.stop_requested or self.paused: return
            LOG_ROOT.mkdir(parents=True, exist_ok=True); CAPTURE_ROOT.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            command = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "24",
                       "--capture-dir", str(CAPTURE_ROOT / "runtime_auto" / stamp), "--serial", self.device.serial]
            self.process = _background_popen(command, cwd=str(ROOT), stdout=subprocess.PIPE,
                                             stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
            output, code = await_worker(self.process, label="本轮 AUTO")
            _note_auto_round_completed()
            (LOG_ROOT / "latest.log").write_text(output, encoding="utf-8")
            self.events.put(("complete", (code, parse_runtime_result(output), output)))
        except BaseException as exc:
            # Catch everything, including KeyboardInterrupt/SystemExit, so a
            # worker death is never silent.  The full traceback plus the runtime
            # state is written to learning/control_panel/crashes/ before the GUI
            # is told anything; only the classified outcome drives the counters.
            snapshot = self.runtime_store.read()
            device_state = {}
            try:
                device_state = self.probes.device_state()
            except Exception:  # noqa: BLE001 - crash evidence is best effort
                device_state = {"status": "UNAVAILABLE"}
            retry_count = getattr(
                recovery, "retries", getattr(self, "_device_recovery_retry_count", None)
            )
            report = write_worker_crash_report(
                where="unified_worker", exc=exc, snapshot=snapshot,
                context={
                    "goal": snapshot.current_goal,
                    "skill": snapshot.current_skill,
                    "role": snapshot.role_id,
                    "page": snapshot.page,
                    "device_state": device_state,
                    "adb_state": device_state.get("status", "UNKNOWN"),
                    "maa_state": {
                        "vision": snapshot.vision,
                        "configured": None,
                        "last_known_backend": snapshot.device,
                    },
                    "retry_state": {
                        "device_recovery_started_at": recovery_started_at,
                        "retries": retry_count,
                        "ready": getattr(recovery, "ready", None),
                    },
                    "recovery_attempt": {
                        "attempted": bool(recovery_started_at),
                        "retry_count": retry_count,
                        "ready": getattr(recovery, "ready", None),
                    } if recovery_started_at else None,
                },
            )
            self.runtime_store.update(
                agent_state=AgentState.FATAL_STOPPED.value if is_fatal_stop(str(exc)) else AgentState.DEGRADED.value,
                stop_category=StopCategory.SYSTEM_FAILURE.value,
                runtime_thread_alive=False, scheduler_loop_alive=False,
                last_fatal_error=str(exc) if is_fatal_stop(str(exc)) else None, stop_reason=str(exc))
            self.events.put(("worker_failure", {
                "message": f"运行失败：{exc}",
                "classification": classify_worker_failure(str(exc)),
                "crash_report": str(report),
            }))
        finally:
            self.process = None; self.starting = False
            if self._worker_thread is threading.current_thread():
                self._worker_thread = None

    def _wait_for_worker_retry(self, delay_seconds: float) -> bool:
        """Wait interruptibly so Stop/Pause does not strand a recovery worker."""
        deadline = time.monotonic() + max(0.0, delay_seconds)
        while True:
            if self.stop_requested or self.paused:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            threading.Event().wait(min(0.25, remaining))

    def _append_device_recovery_event(self, row: dict[str, Any]) -> None:
        """Persist device recovery evidence without letting logging kill AUTO."""
        try:
            LOG_ROOT.mkdir(parents=True, exist_ok=True)
            snapshot = self.runtime_store.read()
            role_id = None
            role_observed_at = None
            try:
                identity = json.loads((ROOT / "learning/role_identity.json").read_text(encoding="utf-8"))
                if isinstance(identity, dict):
                    role_id = identity.get("role_id") or identity.get("role")
                    role_observed_at = identity.get("observed_at") or identity.get("updated_at")
            except (OSError, json.JSONDecodeError, TypeError):
                pass
            record = {
                "at": datetime.now(timezone.utc).isoformat(),
                "event": row.get("event"),
                "role_id_last_observed": role_id,
                "role_observed_at": role_observed_at,
                "current_goal": snapshot.current_goal,
                "current_skill": snapshot.current_skill,
                "last_page": snapshot.page,
                "exception": row.get("exception"),
                "device_state": row.get("device_state", "UNKNOWN"),
                "maa_state": "NOT_STARTED",
                "adb_state": row.get("adb_state", "UNKNOWN"),
                "retry_count": row.get("retry_count", 0),
                "planned_backoff_seconds": row.get("planned_backoff_seconds"),
                "recovery_result": row.get("recovery_result"),
                "restart_latency_ms": row.get("restart_latency_ms"),
                "recovery_started_at": row.get("recovery_started_at") or self._device_recovery_started_at or None,
            }
            with (LOG_ROOT / "worker_recovery.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                stream.flush()
        except Exception:  # noqa: BLE001 - diagnostics may never stop recovery
            return

    def _record_device_recovery_retry(self, exc: Exception, retry_count: int,
                                      delay_seconds: float, elapsed_seconds: float) -> None:
        self._device_recovery_retry_count = int(retry_count)
        message = str(exc) or type(exc).__name__
        try:
            self.runtime_store.update(
                agent_state=AgentState.RECOVERING.value,
                runtime_thread_alive=True,
                scheduler_loop_alive=False,
                stop_reason=message,
                reason="device_reconnect_wait",
                next_action="bounded_device_reconnect_retry",
                device="DISCONNECTED",
            )
        except Exception:  # noqa: BLE001
            pass
        self._append_device_recovery_event({
            "event": "DEVICE_RECOVERY_RETRY",
            "exception": f"{type(exc).__name__}: {message}",
            "adb_state": message,
            "device_state": "DISCONNECTED",
            "retry_count": retry_count,
            "planned_backoff_seconds": delay_seconds,
            "recovery_result": "ENVIRONMENT_BLOCKED",
        })
        self.events.put(("note", f"MuMu/ADB 暂不可用；worker 保持运行，{delay_seconds:.0f}s 后重试（第 {retry_count} 次）。"))

    def _record_device_recovered(self, outcome: RecoveryOutcome, started_at: str) -> None:
        latency_ms = round(outcome.elapsed_seconds * 1000.0, 1)
        self._append_device_recovery_event({
            "event": "DEVICE_RECOVERED",
            "adb_state": "ONLINE",
            "device_state": "CONNECTED",
            "retry_count": outcome.retries,
            "recovery_result": "RECOVERED",
            "restart_latency_ms": latency_ms,
            "recovery_started_at": started_at,
        })
        if not self.stop_requested and not self.paused:
            try:
                self.runtime_store.update(
                    agent_state=AgentState.RECOVERING.value,
                    runtime_thread_alive=True,
                    scheduler_loop_alive=False,
                    stop_reason=None,
                    reason="device_reconnected",
                    next_action="resume_auto_cycle",
                    device="CONNECTED",
                )
            except Exception:  # noqa: BLE001
                pass

    def _ensure_device(self) -> None:
        if self.stop_requested or self.paused:
            raise RuntimeError("用户已停止")
        # Keep every ADB probe under one 120-second deadline.  The old nested
        # 60x retry loop could multiply per-command timeouts into many minutes.
        deadline = time.monotonic() + 120.0
        def remaining(cap: float) -> float:
            return max(0.0, min(cap, deadline - time.monotonic()))
        def connect_adb() -> None:
            timeout = remaining(5.0)
            if timeout <= 0:
                raise RuntimeError("DEVICE_CONNECT_TIMEOUT")
            try:
                _background_run([str(self.device.adb_path), "connect", self.device.serial],
                                capture_output=True, text=True, timeout=timeout, check=False)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("ADB_COMMAND_TIMEOUT") from exc
        retryable = {"DEVICE_NOT_CONNECTED", "ADB_COMMAND_TIMEOUT", "ADB_DISCOVERY_FAILED", "ADB_FAILED"}
        connect_adb()
        try:
            self.device.resolve_connection(timeout_s=remaining(5.0))
        except RuntimeError as exc:
            if str(exc) != "DEVICE_NOT_CONNECTED":
                raise
            if not self._device_launch_requested:
                self._device_launch_requested = True
                if not MUMU_MANAGER_PATH.exists() and not MUMU_PATH.exists():
                    self._device_launch_requested = False
                    raise RuntimeError("MUMU_LAUNCHER_NOT_FOUND") from exc
                if MUMU_MANAGER_PATH.exists():
                    timeout = remaining(30.0)
                    if timeout <= 0:
                        raise RuntimeError("DEVICE_CONNECT_TIMEOUT") from exc
                    try:
                        launch = _background_run(
                            [str(MUMU_MANAGER_PATH), "control", "-v", MUMU_VM_INDEX,
                             "launch", "-pkg", self.config["device"]["package_name"]],
                            capture_output=True, text=True, timeout=timeout, check=False,
                        )
                    except subprocess.TimeoutExpired as launch_error:
                        self._device_launch_requested = False
                        raise RuntimeError("MUMU_LAUNCH_FAILED:launcher_timeout") from launch_error
                    if launch.returncode != 0:
                        self._device_launch_requested = False
                        raise RuntimeError(f"MUMU_LAUNCH_FAILED:{launch.stderr.strip() or launch.stdout.strip()}")
                else:
                    try:
                        _background_popen([str(MUMU_PATH)])
                    except OSError as launch_error:
                        raise RuntimeError(f"MUMU_LAUNCH_FAILED:{launch_error}") from launch_error
            attempt = 0
            while remaining(0.05) > 0:
                if self.stop_requested or self.paused:
                    raise RuntimeError("用户已停止")
                connect_adb()
                try:
                    self.device.resolve_connection(timeout_s=remaining(5.0))
                    break
                except RuntimeError as retry_error:
                    if str(retry_error) not in retryable:
                        raise
                    delay = min(float(2 ** min(attempt, 4)), 15.0, remaining(15.0))
                    if delay <= 0 or self._wait_for_worker_retry(delay):
                        raise RuntimeError("用户已停止") from retry_error
                    attempt += 1
            else:
                raise RuntimeError("DEVICE_CONNECT_TIMEOUT")
        self._device_launch_requested = False
        if self.device.status().foreground_package != self.config["device"]["package_name"]:
            self.device.launch(self.config["device"]["package_name"])
            threading.Event().wait(3)
        # Page understanding and recovery belong to Runtime. The GUI lifecycle
        # adapter proceeds only after the client is reachable and foreground.

    def _run_worker(self) -> None:
        try:
            blocker = runtime_env_blocker()
            if blocker is not None:
                raise RuntimeError(f"{RUNTIME_ENV_STOP_REASON}: {blocker}")
            self._ensure_device()
            if self.stop_requested: return
            LOG_ROOT.mkdir(parents=True, exist_ok=True); CAPTURE_ROOT.mkdir(parents=True, exist_ok=True)
            active_task = getattr(self, "active_panel_task", "采集")
            is_intel = active_task == "Intel"
            is_beast = active_task == "野怪"
            is_mail = active_task == "邮件"
            is_exploration = active_task == "探险"
            is_daily = active_task == "日常"
            is_alliance = active_task == "联盟"
            is_training = active_task == "训练"
            goal = "MAIL" if is_mail else ("DAILY" if is_daily else ("ALLIANCE" if is_alliance else ("TRAIN" if is_training else ("EXPLORATION" if is_exploration else ("INTEL" if is_intel else ("BEAST_HUNT" if is_beast else "GATHER_RESOURCE"))))))
            stop_after = None if (is_mail or is_daily or is_alliance or is_training or is_exploration) else ("DISPATCH_INTEL_BEAST" if is_intel else ("DISPATCH_BEAST" if is_beast else "DISPATCH_MARCH"))
            capture_name = "runtime_mail" if is_mail else ("runtime_daily" if is_daily else ("runtime_alliance" if is_alliance else ("runtime_training" if is_training else ("runtime_exploration" if is_exploration else ("runtime_intel" if is_intel else ("runtime_beast" if is_beast else "runtime"))))))
            # Never overwrite screenshots from an earlier run.  On Windows an
            # open preview, indexer, or virus scanner may hold the old PNG and
            # make os.replace fail with WinError 5.  A unique evidence folder
            # also preserves each unattended run as an auditable episode.
            run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            cmd = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "12", "--goal", goal, "--capture-dir", str(CAPTURE_ROOT / capture_name / run_stamp)]
            if stop_after:
                cmd.extend(["--stop-after", stop_after])
            self.process = _background_popen(cmd + ["--serial", self.device.serial], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
            output, code = await_worker(self.process, label="本轮 AUTO")
            _note_auto_round_completed()
            first_payload = parse_runtime_result(output)
            if is_mail and first_payload.get("stop_reason") == "mail_all_clear" and self.enabled_task_snapshot.get("日常", False) and not self.stop_requested:
                self.active_panel_task = "日常"
                self.run_chain_tasks.add("日常")
                is_daily, is_mail = True, False
                self.events.put(("note", "邮件奖励已清空，继续检查每日任务奖励。"))
                self._ensure_device()
                fallback_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                fallback = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "DAILY", "--capture-dir", str(CAPTURE_ROOT / "runtime_daily" / fallback_stamp)]
                if self.stop_requested: return
                self.process = _background_popen(fallback + ["--serial", self.device.serial], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                fallback_output, code = await_worker(self.process, label=f"子任务 {self.active_panel_task or '未命名'}")
                _note_auto_round_completed()
                output = output.rstrip() + "\n" + fallback_output
                first_payload = parse_runtime_result(output)
            if is_mail and first_payload.get("stop_reason") == "mail_all_clear" and not self.enabled_task_snapshot.get("日常", False) and self.enabled_task_snapshot.get("联盟", False) and not self.stop_requested:
                self.active_panel_task = "联盟"
                self.run_chain_tasks.add("联盟")
                is_alliance, is_mail = True, False
                self.events.put(("note", "邮件奖励已清空，继续检查联盟赠礼。"))
                self._ensure_device()
                fallback_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                fallback = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "ALLIANCE", "--capture-dir", str(CAPTURE_ROOT / "runtime_alliance" / fallback_stamp)]
                if self.stop_requested: return
                self.process = _background_popen(fallback + ["--serial", self.device.serial], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                fallback_output, code = await_worker(self.process, label=f"子任务 {self.active_panel_task or '未命名'}")
                _note_auto_round_completed()
                output = output.rstrip() + "\n" + fallback_output
                first_payload = parse_runtime_result(output)
            if is_mail and first_payload.get("stop_reason") == "mail_all_clear" and self.enabled_task_snapshot.get("探险", False) and not self.stop_requested:
                self.active_panel_task = "探险"
                self.run_chain_tasks.add("探险")
                is_exploration, is_mail = True, False
                self.events.put(("note", "邮件奖励已清空，继续检查探险挂机收益。"))
                self._ensure_device()
                fallback_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                fallback = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "EXPLORATION", "--capture-dir", str(CAPTURE_ROOT / "runtime_exploration" / fallback_stamp)]
                if self.stop_requested: return
                self.process = _background_popen(fallback + ["--serial", self.device.serial], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                fallback_output, code = await_worker(self.process, label=f"子任务 {self.active_panel_task or '未命名'}")
                _note_auto_round_completed()
                output = output.rstrip() + "\n" + fallback_output
                first_payload = parse_runtime_result(output)
            if is_daily and first_payload.get("stop_reason") in {"daily_state_unknown_or_not_actionable", "daily_no_claimable_rewards"} and self.enabled_task_snapshot.get("联盟", False) and not self.stop_requested:
                self.active_panel_task = "联盟"
                self.run_chain_tasks.add("联盟")
                is_alliance, is_daily = True, False
                self.events.put(("note", "每日奖励已检查，继续检查联盟赠礼。"))
                self._ensure_device()
                fallback_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                fallback = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "ALLIANCE", "--capture-dir", str(CAPTURE_ROOT / "runtime_alliance" / fallback_stamp)]
                if self.stop_requested: return
                self.process = _background_popen(fallback + ["--serial", self.device.serial], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                fallback_output, code = await_worker(self.process, label=f"子任务 {self.active_panel_task or '未命名'}")
                _note_auto_round_completed()
                output = output.rstrip() + "\n" + fallback_output
                first_payload = parse_runtime_result(output)
            if is_daily and first_payload.get("stop_reason") in {"daily_state_unknown_or_not_actionable", "daily_no_claimable_rewards"} and self.enabled_task_snapshot.get("探险", False) and not self.stop_requested:
                self.active_panel_task = "探险"
                self.run_chain_tasks.add("探险")
                is_exploration, is_daily = True, False
                self.events.put(("note", "每日奖励已检查，继续检查探险挂机收益。"))
                self._ensure_device()
                fallback_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                fallback = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "EXPLORATION", "--capture-dir", str(CAPTURE_ROOT / "runtime_exploration" / fallback_stamp)]
                if self.stop_requested: return
                self.process = _background_popen(fallback + ["--serial", self.device.serial], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                fallback_output, code = await_worker(self.process, label=f"子任务 {self.active_panel_task or '未命名'}")
                _note_auto_round_completed()
                output = output.rstrip() + "\n" + fallback_output
                first_payload = parse_runtime_result(output)
            if is_alliance and first_payload.get("stop_reason") == "alliance_action_not_needed" and self.enabled_task_snapshot.get("训练", False) and not self.stop_requested:
                self.active_panel_task = "训练"
                self.run_chain_tasks.add("训练")
                is_training, is_alliance = True, False
                self.events.put(("note", "联盟赠礼已检查，继续检查部队训练。"))
                self._ensure_device()
                fallback_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                fallback = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "10", "--goal", "TRAIN", "--capture-dir", str(CAPTURE_ROOT / "runtime_training" / fallback_stamp)]
                if self.stop_requested: return
                self.process = _background_popen(fallback + ["--serial", self.device.serial], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                fallback_output, code = await_worker(self.process, label=f"子任务 {self.active_panel_task or '未命名'}")
                _note_auto_round_completed()
                output = output.rstrip() + "\n" + fallback_output
                first_payload = parse_runtime_result(output)
            if is_alliance and first_payload.get("stop_reason") == "alliance_action_not_needed" and self.enabled_task_snapshot.get("探险", False) and not self.stop_requested:
                self.active_panel_task = "探险"
                self.run_chain_tasks.add("探险")
                is_exploration, is_alliance = True, False
                self.events.put(("note", "联盟赠礼已检查，继续检查探险挂机收益。"))
                self._ensure_device()
                fallback_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                fallback = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "EXPLORATION", "--capture-dir", str(CAPTURE_ROOT / "runtime_exploration" / fallback_stamp)]
                if self.stop_requested: return
                self.process = _background_popen(fallback + ["--serial", self.device.serial], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                fallback_output, code = await_worker(self.process, label=f"子任务 {self.active_panel_task or '未命名'}")
                _note_auto_round_completed()
                output = output.rstrip() + "\n" + fallback_output
                first_payload = parse_runtime_result(output)
            if is_training and first_payload.get("stop_reason") in {"training_queue_busy", "TARGET_SKILL_VERIFIED", "MAX_ACTIONS_REACHED"} and self.enabled_task_snapshot.get("探险", False) and not self.stop_requested:
                self.active_panel_task = "探险"
                self.run_chain_tasks.add("探险")
                is_exploration, is_training = True, False
                self.events.put(("note", "部队训练已检查，继续检查探险挂机收益。"))
                self._ensure_device()
                fallback_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                fallback = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "EXPLORATION", "--capture-dir", str(CAPTURE_ROOT / "runtime_exploration" / fallback_stamp)]
                if self.stop_requested: return
                self.process = _background_popen(fallback + ["--serial", self.device.serial], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                fallback_output, code = await_worker(self.process, label=f"子任务 {self.active_panel_task or '未命名'}")
                _note_auto_round_completed()
                output = output.rstrip() + "\n" + fallback_output
                first_payload = parse_runtime_result(output)
            if is_exploration and first_payload.get("stop_reason") == "exploration_income_not_ready" and self.enabled_task_snapshot.get("Intel", False) and not self.stop_requested:
                self.active_panel_task = "Intel"
                self.run_chain_tasks.add("Intel")
                is_intel, is_exploration = True, False
                self.events.put(("note", "探险收益已检查，继续检查情报任务。"))
                self._ensure_device()
                fallback_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                fallback = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "INTEL", "--stop-after", "DISPATCH_INTEL_BEAST", "--capture-dir", str(CAPTURE_ROOT / "runtime_intel" / fallback_stamp)]
                if self.stop_requested: return
                self.process = _background_popen(fallback + ["--serial", self.device.serial], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                fallback_output, code = await_worker(self.process, label=f"子任务 {self.active_panel_task or '未命名'}")
                _note_auto_round_completed()
                output = output.rstrip() + "\n" + fallback_output
                first_payload = parse_runtime_result(output)
            if is_mail and first_payload.get("stop_reason") == "mail_all_clear" and self.enabled_task_snapshot.get("Intel", False) and not self.stop_requested:
                self.active_panel_task = "Intel"
                self.run_chain_tasks.add("Intel")
                is_intel, is_mail = True, False
                self.events.put(("note", "邮件奖励已清空，继续检查情报任务。"))
                self._ensure_device()
                fallback_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                fallback = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "INTEL", "--stop-after", "DISPATCH_INTEL_BEAST", "--capture-dir", str(CAPTURE_ROOT / "runtime_intel" / fallback_stamp)]
                if self.stop_requested: return
                self.process = _background_popen(fallback + ["--serial", self.device.serial], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                fallback_output, code = await_worker(self.process, label=f"子任务 {self.active_panel_task or '未命名'}")
                _note_auto_round_completed()
                output = output.rstrip() + "\n" + fallback_output
                first_payload = parse_runtime_result(output)
            if is_exploration and first_payload.get("stop_reason") == "exploration_income_not_ready" and self.enabled_task_snapshot.get("Intel", False) and not self.stop_requested:
                self.active_panel_task = "Intel"
                self.run_chain_tasks.add("Intel")
                is_intel, is_exploration = True, False
                self.events.put(("note", "探险收益已检查，继续检查情报任务。"))
                self._ensure_device()
                fallback_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                fallback = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "INTEL", "--stop-after", "DISPATCH_INTEL_BEAST", "--capture-dir", str(CAPTURE_ROOT / "runtime_intel" / fallback_stamp)]
                if self.stop_requested: return
                self.process = _background_popen(fallback + ["--serial", self.device.serial], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                fallback_output, code = await_worker(self.process, label=f"子任务 {self.active_panel_task or '未命名'}")
                _note_auto_round_completed()
                output = output.rstrip() + "\n" + fallback_output
                first_payload = parse_runtime_result(output)
            if (
                is_intel
                and first_payload.get("stop_reason") in {"intel_state_unknown", "intel_available_no_claim", "SEMANTIC_TARGET_NOT_VERIFIED"}
                and self.enabled_task_snapshot.get("野怪", False)
                and not self.stop_requested
            ):
                self.active_panel_task = "野怪"
                self.run_chain_tasks.add("野怪")
                self.events.put(("note", "当前没有可验证的蓝色情报兽任务，切换到普通野怪消耗体力。"))
                self._ensure_device()
                fallback_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                fallback = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "BEAST_HUNT", "--stop-after", "DISPATCH_BEAST", "--capture-dir", str(CAPTURE_ROOT / "runtime_beast" / fallback_stamp)]
                if self.stop_requested: return
                self.process = _background_popen(fallback + ["--serial", self.device.serial], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                fallback_output, code = await_worker(self.process, label=f"子任务 {self.active_panel_task or '未命名'}")
                _note_auto_round_completed()
                output = output.rstrip() + "\n" + fallback_output
                first_payload = parse_runtime_result(output)
            if (
                (is_beast or getattr(self, "active_panel_task", "") == "野怪")
                and first_payload.get("stop_reason") == "verified_beast_target_not_visible"
                and self.enabled_task_snapshot.get("采集", False)
                and not self.stop_requested
            ):
                self.active_panel_task = "采集"
                self.run_chain_tasks.add("采集")
                self.events.put(("note", "当前画面没有已验证的低等级普通野怪，切换到保留行军位的采集检查。"))
                fallback_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                fallback = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "GATHER_RESOURCE", "--stop-after", "DISPATCH_MARCH", "--capture-dir", str(CAPTURE_ROOT / "runtime" / fallback_stamp)]
                if self.stop_requested: return
                self.process = _background_popen(fallback + ["--serial", self.device.serial], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                fallback_output, code = await_worker(self.process, label=f"子任务 {self.active_panel_task or '未命名'}")
                _note_auto_round_completed()
                output = output.rstrip() + "\n" + fallback_output
            (LOG_ROOT / "latest.log").write_text(output, encoding="utf-8")
            self.events.put(("complete", (code, parse_runtime_result(output), output)))
        except BaseException as exc:
            report = write_worker_crash_report(where="panel_worker", exc=exc,
                                               snapshot=self.runtime_store.read())
            self.runtime_store.update(
                agent_state=AgentState.FATAL_STOPPED.value if is_fatal_stop(str(exc)) else AgentState.DEGRADED.value,
                stop_category=StopCategory.SYSTEM_FAILURE.value,
                runtime_thread_alive=False, scheduler_loop_alive=False,
                last_fatal_error=str(exc) if is_fatal_stop(str(exc)) else None, stop_reason=str(exc))
            self.events.put(("worker_failure", {
                "message": f"运行失败：{exc}",
                "classification": classify_worker_failure(str(exc)),
                "crash_report": str(report),
            }))
        finally:
            self.process = None
            self.starting = False

    def pause(self) -> None:
        self.paused = self.stop_requested = True; self.starting = False; self._cancel_repeat()
        self._kill_worker_tree()
        self.operator_intent = save_operator_intent(PANEL_STATE_PATH, "PAUSED", "user pressed pause")
        self.values["agent"].set("● 等待"); self.values["mode"].set("暂停"); self.values["result"].set("已暂停；状态与截图保留")
        self._clear_running_task_labels()
        self.runtime_store.update(agent_state=AgentState.PAUSED.value, runtime_thread_alive=False, scheduler_loop_alive=False, stop_reason="USER_PAUSED")
        self._append("智能体已暂停。"); self._idle_buttons()

    def stop(self) -> None:
        self.stop_requested = True; self.paused = False; self.starting = False; self._cancel_repeat()
        self._kill_worker_tree()
        # Remembered on disk: a GUI restart must not undo the operator's stop
        # (see ``load_operator_intent``).
        self.operator_intent = save_operator_intent(PANEL_STATE_PATH, "STOPPED", "user pressed stop")
        self.values["agent"].set("● 等待"); self.values["mode"].set("停止"); self.values["result"].set("用户停止")
        self._clear_running_task_labels(); self._append("智能体已停止。"); self._idle_buttons()
        self.runtime_store.update(agent_state=AgentState.IDLE.value, runtime_thread_alive=False, scheduler_loop_alive=False, stop_reason="USER_STOPPED")

    def _cancel_repeat(self) -> None:
        if self.repeat_after_id: self.root.after_cancel(self.repeat_after_id); self.repeat_after_id = None

    def _drain_events(self) -> None:
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "refresh": self._apply_world(*data)
                elif kind == "complete": self._apply_complete(*data)
                elif kind == "note":
                    self._append(str(data))
                elif kind == "worker_failure":
                    self._handle_worker_failure(data)
                else:
                    self._handle_runtime_error(str(data))
        except queue.Empty: pass
        self.root.after(100, self._drain_events)

    def _handle_worker_failure(self, data: dict) -> None:
        """Route a worker death by classification instead of one blunt counter.

        ``ENVIRONMENT`` failures (emulator down, ADB dropped, operator stop) are
        recoverable conditions that the operator has to fix or simply retry, so
        they restart the watchdog but do not inflate ``unexpected_worker_exits``.
        A ``WORKER_CRASH`` is a defect in the worker itself, is counted, and has
        already been written to ``learning/control_panel/crashes/`` with a full
        traceback and the runtime state at the moment of death.
        """
        message = str(data.get("message", ""))
        classification = str(data.get("classification", "WORKER_CRASH"))
        report = data.get("crash_report")
        fatal = is_fatal_stop(message)
        previous = self.runtime_store.read()
        # One rule for the counter, shared with _handle_runtime_error below.
        counts_as_exit = counts_as_unexpected_worker_exit(
            classification=classification, message=message, stop_requested=self.stop_requested
        )
        self.runtime_store.update(
            agent_state=AgentState.FATAL_STOPPED.value if fatal else AgentState.DEGRADED.value,
            stop_category=StopCategory.SYSTEM_FAILURE.value,
            runtime_thread_alive=False, scheduler_loop_alive=False, stop_reason=message,
            last_fatal_error=message if fatal else previous.last_fatal_error,
            unexpected_worker_exits=previous.unexpected_worker_exits + (1 if counts_as_exit else 0),
        )
        self.values["runtime_state"].set("异常"); self.values["result"].set(message)
        self._append(f"⚠ {message}（{classification}）")
        if report: self._append(f"  根因证据：{report}")
        self._idle_buttons(); self._clear_running_task_labels()
        if self.continuous.get() and not fatal and not self.stop_requested and not self.paused:
            if classification == "WORKER_CRASH":
                self._consecutive_worker_crashes = getattr(self, "_consecutive_worker_crashes", 0) + 1
                if self._consecutive_worker_crashes > MAX_CONSECUTIVE_WORKER_CRASH_RESTARTS:
                    self.paused = True
                    self.operator_intent = save_operator_intent(
                        PANEL_STATE_PATH, "PAUSED", "worker crash restart budget exhausted")
                    self._append("连续 Worker 异常已耗尽恢复预算，AUTO 已暂停；根因和现场已保留。")
                    return
            delay_ms = (min(30_000, 5_000 * 2 ** (getattr(self, "_consecutive_worker_crashes", 1) - 1))
                        if classification == "WORKER_CRASH" else 5_000)
            self.runtime_store.update(watchdog_restart_count=previous.watchdog_restart_count + 1)
            self.repeat_after_id = self.root.after(delay_ms, self.start)
            self._waiting_buttons(); self._append(f"Watchdog 将在 {delay_ms // 1000} 秒后重新观察并恢复唯一 Runtime。")

    def _handle_runtime_error(self, message: str) -> None:
        """Handle an event that is NOT a worker death.

        This is the fallback for every event kind the drain loop does not
        recognise, so by construction it never carries a worker verdict.  It
        used to increment ``unexpected_worker_exits`` for every non-fatal
        message, which is why the counter could not be driven to zero by fixing
        crashes (RR-001).  It now asks the same question as
        ``_handle_worker_failure`` and answers it honestly: this event has no
        worker classification, so it is not a worker exit.

        The reason is recorded as ``stop_reason`` either way -- declining to
        count something is not the same as hiding it, and the counter is not the
        only record.
        """
        fatal = is_fatal_stop(message)
        previous = self.runtime_store.read()
        counts_as_exit = counts_as_unexpected_worker_exit(
            classification=UNCLASSIFIED_EVENT, message=message, stop_requested=self.stop_requested
        )
        self.runtime_store.update(
            agent_state=AgentState.FATAL_STOPPED.value if fatal else AgentState.DEGRADED.value,
            stop_category=StopCategory.SYSTEM_FAILURE.value,
            runtime_thread_alive=False, scheduler_loop_alive=False, stop_reason=message,
            last_fatal_error=message if fatal else previous.last_fatal_error,
            unexpected_worker_exits=previous.unexpected_worker_exits + (1 if counts_as_exit else 0),
        )
        self.values["runtime_state"].set("异常"); self.values["result"].set(message); self._append(f"⚠ {message}")
        self._idle_buttons(); self._clear_running_task_labels()
        if self.continuous.get() and not fatal and not self.stop_requested and not self.paused:
            self.runtime_store.update(watchdog_restart_count=previous.watchdog_restart_count + 1)
            self.repeat_after_id = self.root.after(5000, self.start)
            self._waiting_buttons(); self._append("Watchdog 将在 5 秒后恢复唯一 Runtime。")

    def _apply_world(self, status: Any, world: WorldState, path: Path) -> None:
        self.latest_world, self.latest_image_path = world, path
        self.preview_source = Image.open(path); self._preview_rgb = None
        self.values["device"].set("● 已连接")
        expected_package = self.config["device"]["package_name"]
        self.values["game"].set("运行中" if status.foreground_package == expected_package else "未在前台")
        self.values["page"].set(PAGE_ZH.get(world.page.value, world.page.value) if world.known else UNKNOWN_NOW)
        self.values["confidence_frame"].set(f"{world.confidence:.0%}")
        self.values["runtime_state"].set("执行中" if world.known else UNKNOWN_NOW)
        self._refresh_event_goal_display()
        self._refresh_goal_board()
        self._refresh_fishing_display()
        march = f"{world.march_used}/{world.march_max}" if world.march_used is not None and world.march_max is not None else "暂无数据"
        self.values["march"].set(f"行军：{march}"); self.queues["行军"].set(march)
        for name, value in (("建筑", world.building), ("科技", world.research), ("训练", world.training), ("Intel", world.intel), ("联盟", world.alliance)):
            self.queues[name].set(self._compact(value))
        marches = "、".join(MARCH_ZH.get(m, "未识别") for m in world.marches) or "暂无队列明细"
        self.preview_meta.set(f"页面：{PAGE_ZH.get(world.page.value, world.page.value)} · 行军：{marches}")
        if self.process is None and not self.paused: self.values["agent"].set("● 等待")
        self._render_preview(); self._append(f"识别完成：{PAGE_ZH.get(world.page.value, world.page.value)}，置信度 {world.confidence:.0%}。")

    @staticmethod
    def _compact(value: dict[str, Any]) -> str:
        if not value: return PENDING
        for key in ("status", "state", "available", "claimable", "queue"):
            if key in value: return human_reason(value[key])
        return f"已识别 {len(value)} 项"

    def _apply_complete(self, code: int, payload: dict, output: str) -> None:
        if not payload and not self.stop_requested and not self.paused:
            failure = worker_result_failure(output, code)
            report = write_worker_crash_report(
                where="auto_subprocess", exc=RuntimeError(failure["message"]),
                snapshot=self.runtime_store.read(), context=failure,
            )
            failure["crash_report"] = str(report)
            self._handle_worker_failure(failure)
            return
        summary = summarize_runtime_result(payload, code); steps = payload.get("steps", []) if isinstance(payload, dict) else []
        if summary["healthy"] or summary["verified"]:
            self._consecutive_worker_crashes = 0
        last = steps[-1] if steps else {}; decision = last.get("decision", {}) if isinstance(last, dict) else {}; verification = last.get("verification", {}) if isinstance(last, dict) else {}
        reason = str(summary["reason"] or "")
        role_handoff = reason.startswith(("ROLE_SWITCHED_TO:", "ROLE_IDENTITY_CHANGED:"))
        skill = ("ROLE_SWITCH" if role_handoff else
                 decision.get("skill", "GATHER_RESOURCE") if isinstance(decision, dict)
                 else "GATHER_RESOURCE")
        self.values["skill"].set(skill); self.values["task_cn"].set(SKILL_ZH.get(skill, "角色切换" if role_handoff else "资源采集")); self.values["reason"].set(human_reason(reason if role_handoff else decision.get("reason") if isinstance(decision, dict) else None))
        self.values["next"].set(
            "等待下一轮状态观察" if summary["ok"] else
            ("切换其他任务并记录能力缺口" if summary["stop_category"] == StopCategory.CAPABILITY_GAP.value
             else "进入安全恢复或停止")
        )
        self.values["verifier"].set(("验证通过" if verification.get("ok") else human_reason(verification.get("reason"))) if isinstance(verification, dict) and verification else "本轮无最终验证数据")
        category = summary["stop_category"]
        state_label = (
            "● 等待" if summary["ok"] else
            ("◇ 待补能力" if category == StopCategory.CAPABILITY_GAP.value else "● 异常")
        )
        self.values["result"].set(human_reason(summary["reason"])); self.values["agent"].set(state_label)
        self.session["runs"] += 1; self.session["actions"] += summary["executed"]
        if summary["ok"]:
            self.session["success"] += 1
        elif category == StopCategory.CAPABILITY_GAP.value:
            self.session.setdefault("blocked", 0)
            self.session["blocked"] += 1
        else:
            self.session["failed"] += 1
        self.values["stats"].set(
            f"本次启动：{self.session['runs']} 轮 · {self.session['actions']} 动作 · "
            f"正常 {self.session['success']} · 待补能力 {self.session.get('blocked', 0)} · 异常 {self.session['failed']}"
        )
        icon = "✓ " if summary["ok"] else ("◇ " if category == StopCategory.CAPABILITY_GAP.value else "⚠ ")
        self._append(icon + f"本轮结束：{human_reason(summary['reason'])}")
        # Full structured output belongs only in latest.log. Rendering large
        # JSON blobs in Tk made the UI appear flooded and could stall it.
        self._idle_buttons(); self._enforce_retention(); self.refresh()
        # After the refresh, not before: the two console lines above read the file this writes, so
        # the round that just ended is the first one whose numbers are folded in, and the operator
        # sees them one round later rather than never (which is what happened while nothing wrote
        # the file at all).
        self._refresh_learning_funnel()
        self._maybe_run_nightly_learning()
        fatal = is_fatal_stop(str(summary["reason"]))
        self.runtime_store.update(agent_state=summary["agent_state"], stop_category=category,
                                  runtime_thread_alive=False, scheduler_loop_alive=False, stop_reason=summary["reason"],
                                  last_fatal_error=summary["reason"] if fatal else None)
        retryable_role_switch = reason.startswith("ROLE_SWITCH_FAILED:")
        # One decision, two readers.  ``auto_halt_reason`` is already documented as the single
        # source for "will AUTO continue"; the uptime ledger records that same value, so the
        # measurement can never disagree with the behaviour it measures (ACCEPTANCE §22 needs a
        # number for ">= 72h unattended", and before this the project had only a narrative).
        halt_reason = auto_halt_reason(
            healthy=summary["healthy"], reason=reason,
            continuous=self.continuous.get(), stop_requested=self.stop_requested,
            paused=self.paused, fatal=fatal,
        )
        self._record_auto_round(summary, reason, halt_reason=halt_reason)
        if should_continue_auto_cycle(
            healthy=summary["healthy"], reason=reason,
            continuous=self.continuous.get(), stop_requested=self.stop_requested,
            paused=self.paused, fatal=fatal,
        ):
            # Four different things used to collapse into one 30-second wait:
            #
            #   A  this ``run_live.py`` subprocess ended
            #   B  one repeatable goal finished its current pass
            #   C  this character has no executable work left
            #   D  the whole AUTO work cycle is done
            #
            # The panel only ever knew A, and waited as if A were D.  Measured live 2026-09-20
            # 18:02-18:14 (ten rounds): five of them performed exactly one action and failed it,
            # CLOSE_POPUP failed three rounds in a row, no DISPATCH/MARCH episode appeared at all,
            # and every single round was followed by the full wait.
            #
            # The ladder itself now lives in ``next_cycle_delay`` so it can be tested without a
            # Tk root; the loop-protection reasoning is documented there.
            decision = next_cycle_delay(
                reason=reason, summary=summary, role_handoff=role_handoff,
                retryable_role_switch=retryable_role_switch, bound_ms=activity_bounded_wait_ms,
            )
            delay_ms, delay_text, immediate = decision
            self.values["mode"].set("继续" if immediate else "等待")
            self.repeat_after_id = self.root.after(delay_ms, self.start)
            self._waiting_buttons()
            self._append(f"连续运行已启用，{delay_text}后进入下一轮。"
                         + ("（角色切换已确认，本轮重启只用于刷新目标角色状态）" if role_handoff else
                            "（目标角色已有切换退避；下一轮重新读取当前角色与页面）" if retryable_role_switch else
                            "（角色仍持有设备，立即重新观察同一角色）"
                            if reason == ROLE_REOBSERVE_REASON else
                            "（子进程结束不等于工作周期结束，立即继续）" if immediate else ""))
        else:
            # A halt must never be silent.  Measured 2026-09-30 11:21: the round above was
            # relabelled SYSTEM_FAILURE, this gate declined, and the panel logged nothing --
            # the last line was the snapshot refresh, so AUTO looked alive while the device
            # sat idle for fifteen minutes and the operator had no reason to read.
            self.values["mode"].set("停止")
            self._append(f"⏹ 未进入下一轮：{halt_reason}");

    def _record_auto_round(self, summary: dict, reason: str, *, halt_reason: str) -> None:
        """One ledger row per finished round: the measurement ACCEPTANCE §22 never had.

        ``halt_reason`` is passed in rather than recomputed, because it is the *same* value that
        decides whether the next round starts -- the ledger records behaviour, it does not
        predict it.

        ``continues`` is deliberately not ``healthy``: a round can be unhealthy yet still be
        followed by another one (watchdog recovery, a role handoff), and the acceptance question
        is "did AUTO keep going", not "was this round pretty".
        """
        try:
            snapshot = self.runtime_store.read()
            append_uptime_ledger(
                AUTO_UPTIME_LEDGER_PATH,
                uptime_ledger_row(
                    recorded_at=datetime.now(timezone.utc).isoformat(),
                    stop_reason=str(summary.get("reason") or ""),
                    stop_category=str(summary.get("stop_category") or ""),
                    healthy=bool(summary.get("healthy")),
                    continues=not halt_reason,
                    halt_reason=halt_reason,
                    executed=int(summary.get("executed") or 0),
                    verified=int(summary.get("verified") or 0),
                    failures=int(summary.get("failures") or 0),
                    # Only what this class really owns.  Measured live 2026-09-30 12:24:46: an
                    # earlier version read ``self._state`` for the code revision and the write
                    # died with AttributeError -- ``_state`` belongs to QueuePump, not to
                    # ControlPanel.  The revision of the running code is already recorded
                    # elsewhere (``desktop_startup.log`` CODE_COMMIT, and the episode's
                    # ``repo_revision``); the ledger does not need to duplicate it and must not
                    # depend on an interface this class does not have.
                    role_id=str(getattr(snapshot, "role_id", "") or ""),
                ),
            )
        except Exception as exc:  # noqa: BLE001 - measurement must never stop the run
            self._append(f"运行时长台账写入失败（不影响 AUTO）：{type(exc).__name__}: {exc}")

    def _enforce_retention(self) -> None:
        """Drain the capture trees toward the configured budget, a bounded burst at a time.

        Called once per round, not only at start-up.  That change is the whole fix: the policy
        was already correct (``max_screenshots`` 500, ``screenshot_ttl_days`` 14,
        ``auto_prune`` true), but it ran exactly once per process, and one pass removes at most
        ``MAX_DELETIONS_PER_PASS`` files.  A run that writes ~3100 frames a day therefore grew
        a backlog no single start-up could ever repay -- measured 2026-10-03: 50,051 files in
        ``dataset/raw/control_panel`` alone, 33 GB.

        Still bounded per call, deliberately.  The host aborts a process that deletes 50 files
        within one turn, and 2026-09-18 that abort killed the panel with AUTO attached.  A
        steady per-round drain reaches the budget within a few rounds without ever approaching
        that threshold in one go.
        """
        policy = self.config.get("retention", {})
        if not policy.get("auto_prune", False):
            return
        removed = prune_runtime_screenshots(
            CAPTURE_ROOT,
            max_count=int(policy.get("max_screenshots", 500)),
            ttl_days=int(policy.get("screenshot_ttl_days", 3)),
            # Evidence gets a lifetime, not an exemption.  "Never prune a cited frame" reads
            # safe and accumulates for ever, because the cited set only grows; measured
            # 2026-10-03 that alone held 20,340 frames.  30 days matches the operator's rule
            # for frames a Verifier or Candidate points at.  Absent from an older config, the
            # old exclude-outright behaviour is kept rather than guessed at.
            referenced_ttl_days=(
                int(policy["referenced_ttl_days"])
                if "referenced_ttl_days" in policy else None
            ),
        )
        if removed:
            self._append(f"磁盘保护：已清理 {len(removed)} 张过期或超额运行截图。")

    def _refresh_learning_funnel(self) -> None:
        """Re-fold the §38 funnel once per round, so §36's console lines are current.

        The panel *reads* ``learning/learning_funnel.json`` on every UI tick (see the
        ``values["learning"]`` lines in ``refresh``), and until this method existed nothing in the
        panel ever wrote it -- the numbers were whatever the last manual
        ``tools/learning_report.py --funnel`` had left behind, which is a console that looks live
        and is not.  That is the specific failure the directive's §36 is trying to avoid.

        Called at the round boundary rather than on the tick, for the reason the comment at the
        read site gives: the fold walks the episode stream (measured 2026-10-01: 123.7 MB /
        ~1.7 s), so on a one-second tick it would make the console the slowest thing in the
        process.  At the round boundary there is nothing else to do -- the panel is already
        waiting out ``next_cycle_delay`` -- and it sits beside ``_enforce_retention``, which is
        the same class of once-per-round housekeeping.

        A failure here must not take a round down: the funnel is a *reading*, and a reading that
        cannot be taken is a stale line, not a stopped AUTO.
        """
        try:
            learning_funnel.refresh(root=ROOT)
        except Exception as exc:  # noqa: BLE001 - a readout must never stop the loop
            self._append(f"学习效果刷新失败（读数保持上一次的值）：{type(exc).__name__}: {exc}")

    def _maybe_run_nightly_learning(self) -> None:
        """Start §21's offline pass once a night, in its own process.

        Two decisions, both deliberate:

        * **its own process.**  The pass hashes frames, and the count is whatever the stores have
          accumulated -- so running it on the Tk thread would freeze the console for however long
          that takes.  It is launched detached through ``winproc``, the same way this panel already
          launches the live loop, and it is *read-only with respect to the device*: §21 says the
          offline pass must not operate the game, and it can't -- it only reads screenshots and
          writes ``knowledge/offline/``.
        * **the marker is written before the launch.**  See ``offline_learning.mark_nightly_run``:
          a pass that dies at startup must not be relaunched at every round boundary all night.

        The timing rule itself is not here; it is ``offline_learning.is_nightly_run_due``, so it can
        be tested without a clock or a Tk root -- the same split ``next_cycle_delay`` already uses.
        """
        now = datetime.now().astimezone()
        if not offline_learning.is_nightly_run_due(now, offline_learning.last_run_date(ROOT)):
            return
        offline_learning.mark_nightly_run(now, ROOT)
        try:
            winproc.spawn_detached(
                [sys.executable, str(ROOT / "tools" / "learning_report.py"),
                 "--offline", "--root", str(ROOT)],
                log_path=ROOT / offline_learning.NIGHTLY_LOG,
                cwd=str(ROOT),
            )
            self._append("离线夜间学习已启动（只读截图建索引，不操作设备）。")
        except Exception as exc:  # noqa: BLE001 - a nightly job that cannot start is not fatal
            self._append(f"离线夜间学习未能启动：{type(exc).__name__}: {exc}")


    def _schedule_preview_render(self) -> None:
        """Coalesce a burst of resize events into one render."""
        if self._render_preview_job is not None:
            try:
                self.root.after_cancel(self._render_preview_job)
            except tk.TclError:
                pass
        self._render_preview_job = self.root.after(120, self._render_preview)

    def _render_preview(self) -> None:
        if self.preview_source is None or not hasattr(self, "preview"): return
        self._render_preview_job = None
        width, height = max(260, self.preview.winfo_width() - 8), max(300, self.preview.winfo_height() - 8)
        # Decode once, on demand: the tick stores a lazily-opened image, and this is
        # the first point that actually needs pixels.
        if self._preview_rgb is None:
            try:
                self._preview_rgb = self.preview_source.convert("RGB")
            except OSError:
                return
        image = self._preview_rgb.copy(); mode = self.preview_mode.get()
        # The debug furniture (border, boxes) is drawn only when the operator asks for it.
        # It used to appear for any non-raw mode, which meant the one thing the centre
        # column exists for -- reading the page off the picture -- was obstructed by
        # default.  The *text* summary stays, because that is information, not clutter.
        debug = bool(getattr(self, "vision_debug", None) and self.vision_debug.get())
        if mode != "原始画面":
            if debug:
                ImageDraw.Draw(image).rectangle((3, 3, image.width - 4, image.height - 4), outline=(83, 183, 255), width=5)
            if mode == "OCR": self.preview_meta.set("OCR：当前 World State 未提供区域坐标；未伪造识别框")
            elif mode == "Vision": self.preview_meta.set("Vision：真实识别摘要；当前结果未提供检测框坐标")
            else: self.preview_meta.set(self._recognition())
        if debug:
            self.preview_meta.set(f"{self.preview_meta.get()}｜调试：ROI/模板未提供坐标，不伪造框")
        # BILINEAR, not LANCZOS: at a ~420 px preview the difference is not visible,
        # and measured on a 720x1280 runtime screenshot it is 4.6 ms instead of 9.5 ms
        # -- which mattered a lot when a window drag re-rendered this continuously.
        image.thumbnail((width, height), Image.Resampling.BILINEAR)
        canvas = Image.new("RGB", (width, height), "#070b10"); canvas.paste(image, ((width-image.width)//2, (height-image.height)//2))
        self.preview_photo = ImageTk.PhotoImage(canvas); self.preview.configure(image=self.preview_photo, text="")

    def _recognition(self) -> str:
        w = self.latest_world
        if w is None: return "识别结果：暂无数据"
        parts = [f"页面 {PAGE_ZH.get(w.page.value, w.page.value)}", f"置信度 {w.confidence:.0%}"]
        if w.resource_selected: parts.append(f"资源 {w.resource_selected}")
        if w.popup: parts.append(f"弹窗 {w.popup}")
        return "识别结果：" + " · ".join(parts)

    def _running_buttons(self) -> None:
        self.start_button.configure(state="disabled"); self.pause_button.configure(state="normal"); self.stop_button.configure(state="normal")

    def _idle_buttons(self) -> None:
        self.start_button.configure(state="normal"); self.pause_button.configure(state="disabled"); self.stop_button.configure(state="disabled")

    def _waiting_buttons(self) -> None:
        """A scheduled unattended run must remain cancellable from the UI."""
        self.start_button.configure(state="disabled")
        self.pause_button.configure(state="normal")
        self.stop_button.configure(state="normal")

    def _clear_running_task_labels(self) -> None:
        for name, value in self.today.items():
            if value.get() == "运行中":
                value.set("待识别")

    def _open(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True); os.startfile(path)

    def open_latest(self) -> None:
        if self.latest_image_path and self.latest_image_path.exists(): os.startfile(self.latest_image_path)
        else: self.values["result"].set("暂无可打开的截图")

    def close(self) -> None:
        # No orphan AUTO worker: the whole tree goes down, not just the venv stub
        # the panel holds (see ``_kill_worker_tree``).
        self.stop_requested = True
        self._cancel_repeat()
        self._kill_worker_tree()
        # The gateway poller is a daemon thread, so the process would exit anyway --
        # stopping it explicitly keeps a closing window from making one last request.
        self.probes.stop()
        # Same for the pump: a closing window must not leave a thread mid-submit.
        self.pump.stop()
        # And the control-plane probe, which shells out to ``git``.
        self.control_plane_probe.stop()
        # And the closure-card publisher, which reads the ledger and the episode tail.
        self.closure_probe.stop()
        self.root.destroy()


def main() -> int:
    if not _acquire_single_instance():
        # A second double-click must not vanish.  Show the panel that already holds the
        # lock, and if that window cannot be brought up, say why (see
        # ``_report_existing_panel``) -- the launcher still reports 成功 either way, so
        # this box is the only place the operator can learn what happened.
        _report_existing_panel()
        return 0
    root = tk.Tk(); panel = ControlPanel(root)
    # 启动 GUI = 启动整个无人值守系统: one path, which checks the operator's
    # remembered intent, runs the real preflight, and then starts AUTO.
    root.after(1200, panel._maybe_autostart)
    root.mainloop(); return 0


if __name__ == "__main__":
    raise SystemExit(main())
