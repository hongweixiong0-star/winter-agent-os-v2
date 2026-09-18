"""One runner for every background process, so no command can flash a console window.

Why this module exists
----------------------
Measured 2026-09-18: the control panel flashed a black console window every few seconds
while it ran.  The source was not ADB, which already passed ``CREATE_NO_WINDOW``
everywhere -- it was ``state_truth._head()``, which ran ``git rev-parse HEAD`` on **every
refresh** with no creation flags at all.  One un-hidden call in a period path is enough:
the window appears for a fraction of a second, the operator sees "something keeps
opening", and no amount of fixing *most* call sites helps.

So the rule is not "remember the flags".  The rule is: **a background process is started
here, and nowhere else.**  ``tools/check_wiring.py`` enforces it with an AST check over
the package and ``tools/``: a new ``subprocess.*`` or ``os.system`` call without the
wrapper fails the wiring gate, which is how this class of defect stays fixed.

Two facts this module has to get right on Windows
-------------------------------------------------
1. **Hidden** -- ``CREATE_NO_WINDOW`` plus ``STARTF_USESHOWWINDOW``/``SW_HIDE``.  The
   second pair matters when the parent *does* own a console (a developer running the
   panel from a terminal); ``CREATE_NO_WINDOW`` alone is the common half-fix.
2. **Decodable** -- console tools (``netstat``, ``tasklist``, ``adb``, ``git``) print in
   the OEM codepage, while this environment sets a UTF-8 default for Python's own I/O.
   Measured: ``subprocess.run(["netstat","-ano"], text=True)`` raised
   ``UnicodeDecodeError: 'utf-8' codec can't decode byte 0xbb`` in a Chinese Windows
   locale.  Every call here therefore pins ``encoding`` and ``errors="replace"``: a
   diagnostic that raises while measuring a fault is worse than one that mangles a glyph.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

# Development escape hatch.  The operator's rule: production never shows a console, and a
# developer who wants to watch one sets this before starting the panel rather than the
# code deciding per call site.
SHOW_CONSOLES_ENV = "V2_SHOW_BACKGROUND_CONSOLES"

# Console tools on Windows speak the OEM codepage.  ``oem`` is a real codec name on
# Windows and a no-op elsewhere, which keeps this module importable on any platform.
OEM_ENCODING = "oem"


def show_consoles() -> bool:
    """Is the operator asking to *see* background consoles?  Default: no."""
    raw = str(os.environ.get(SHOW_CONSOLES_ENV, "")).strip().lower()
    return raw in ("1", "true", "yes", "on")


def default_encoding() -> str:
    return OEM_ENCODING if os.name == "nt" else "utf-8"


def hidden_kwargs() -> dict[str, Any]:
    """The flags that stop a console window appearing for a child process.

    Returns ``{}`` off Windows, and ``{}`` as well when the operator has explicitly asked
    to watch consoles -- the point is a single decision, not a silent difference between
    platforms.
    """
    if os.name != "nt" or show_consoles():
        return {}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        "startupinfo": startup,
    }


def run(
    argv: Sequence[str],
    *,
    cwd: Path | str | None = None,
    timeout: float = 20.0,
    capture: bool = True,
    check: bool = False,
    encoding: str | None = None,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run one command to completion, hidden, and never inherit the parent's console.

    ``shell`` is not a parameter on purpose: every call site here passes an argument
    array, and a keyword that only exists to be misused is a liability.  Callers that
    genuinely need shell semantics must say so in a comment and use ``shell_command()``.
    """
    kwargs: dict[str, Any] = {
        "cwd": str(cwd) if cwd else None,
        "timeout": timeout,
        "check": check,
        "shell": False,
        "encoding": encoding or default_encoding(),
        # A measurement that raises on a stray byte is a measurement that fails exactly
        # when something is wrong, which is when it is needed.
        "errors": "replace",
        "text": True,
        **hidden_kwargs(),
    }
    if env is not None:
        kwargs["env"] = dict(env)
    if capture:
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    else:
        # Never inherit: an inherited handle is what lets a child's output reach a console
        # the operator did not ask for.
        kwargs.update(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return subprocess.run(list(argv), **kwargs)


def run_shell(command: str, *, cwd: Path | str | None = None, timeout: float = 20.0,
              capture: bool = True) -> subprocess.CompletedProcess:
    """``run`` for the rare command that needs shell semantics -- still hidden.

    Exists so "I need a pipe or a builtin" does not become a reason to call
    ``subprocess.run`` directly and lose the flags.
    """
    kwargs: dict[str, Any] = {
        "cwd": str(cwd) if cwd else None,
        "timeout": timeout,
        "shell": True,
        "encoding": default_encoding(),
        "errors": "replace",
        "text": True,
        **hidden_kwargs(),
    }
    kwargs.update(
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
    )
    return subprocess.run(command, **kwargs)


def spawn_detached(
    argv: Sequence[str],
    *,
    log_path: Path | str,
    cwd: Path | str | None = None,
    env: Mapping[str, str] | None = None,
) -> subprocess.Popen:
    """Start a long-lived background service: hidden, its own group, output to a log.

    Deliberately *not* tied to the parent's lifetime and *not* given the parent's
    console: the gateway is a service the operator may keep running after the window
    closes, and a GUI that kills it on exit would be the GUI inventing a lifecycle the
    operator never asked for.  The pid is the caller's to persist.
    """
    log = Path(log_path)
    log.parent.mkdir(parents=True, exist_ok=True)
    handle = open(log, "ab")
    kwargs: dict[str, Any] = {
        "cwd": str(cwd) if cwd else None,
        "stdin": subprocess.DEVNULL,
        "stdout": handle,
        "stderr": subprocess.STDOUT,
        "shell": False,
        "close_fds": True,
    }
    if env is not None:
        kwargs["env"] = dict(env)
    if os.name == "nt":
        # Two different problems, two different flags.  ``CREATE_NO_WINDOW`` answers "do
        # not flash a console"; ``DETACHED_PROCESS`` answers "do not belong to whoever
        # launched you".  A *service* needs the second: measured 2026-09-18, launching the
        # panel with only CREATE_NO_WINDOW (and CREATE_NEW_PROCESS_GROUP) meant it was
        # still inside the launcher's process tree and it died the moment that tool call
        # ended -- the panel looked like it had been restarted and then simply was not
        # there.  MSDN: CREATE_NO_WINDOW is ignored when DETACHED_PROCESS is given, and a
        # detached process has no console, which is the same outcome by a stronger route.
        kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    else:
        kwargs["start_new_session"] = True
    try:
        return subprocess.Popen(list(argv), **kwargs)
    except Exception:
        handle.close()
        raise


def kill_tree(pid: int, *, timeout: float = 20.0) -> bool:
    """End a process and its children, hidden.  False when it was already gone."""
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 15)
            return True
        except OSError:
            return False
    result = run(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=timeout)
    return result.returncode == 0


def process_name(pid: int, *, timeout: float = 20.0) -> str:
    """The image name of ``pid`` (``node.exe``, ``python.exe``), or ``""`` when it is gone.

    Asked by number, never by pattern: a pattern over the whole process table matched the
    agent host process on 2026-09-18 and killed it.
    """
    if pid <= 0:
        return ""
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return ""
        return "process"
    result = run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], timeout=timeout)
    text = (result.stdout or "").strip()
    if not text or "No tasks" in text or "没有运行的任务" in text:
        return ""
    first = text.splitlines()[0]
    if not first.startswith('"'):
        return ""
    return first.split(",")[0].strip('"')


def pid_exists(pid: int, *, timeout: float = 20.0) -> bool:
    """Is *any* process running under this pid?

    Name-agnostic on purpose.  Measured 2026-09-18: the gateway was started as pid 5184,
    ``node.exe`` held port 8080 and ``/api/v1/health`` answered 200 -- and the lifecycle
    owner's liveness check said the pid was dead, because it had been written for the
    panel's interpreter and looked for the word "python".  It read a live process as gone,
    which is precisely the input that leads to starting a second one.  A liveness question
    must not assume the answer's process name.
    """
    return bool(process_name(pid, timeout=timeout))


def command_line(pid: int, *, timeout: float = 90.0) -> str:
    """The full command line of ``pid``, or ``""`` when it cannot be read.

    Needed because **a pid is not an identity**.  Measured 2026-09-18: the gateway was
    launched as pid 15140 and recorded; by 19:40 pid 15140 was alive again but was the
    sheetagent MCP server (``.../sheetagent/.../mcp/start.mjs``, parent a WorkBuddy.exe).
    A liveness check that asks only "does this pid exist" answers "yes, our gateway is
    fine" about an unrelated program -- and then never restarts the gateway that is
    actually gone.  So the lifecycle asks this instead, and matches the CLI path it
    launched.

    ``wmic`` is not available on this machine (measured: ``FileNotFoundError``), so this
    goes through PowerShell.  Measured cost: 0.35s, which is why it is only called on the
    ambiguous branch (a recorded pid with nobody listening) rather than on every probe.
    """
    if pid <= 0:
        return ""
    if os.name != "nt":
        return ""
    script = (
        f"$p = Get-CimInstance Win32_Process -Filter \"ProcessId={int(pid)}\" "
        "| Select-Object -First 1 -ExpandProperty CommandLine; "
        "if ($p) { Write-Output $p }"
    )
    result = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                 timeout=timeout)
    return (result.stdout or "").strip()


def pid_runs(pid: int, needle: str, *, timeout: float = 90.0) -> bool:
    """Is ``pid`` running a process whose command line contains ``needle``?

    The identity question behind :func:`command_line`, in the form its callers ask it.
    """
    if not needle:
        return False
    line = command_line(pid, timeout=timeout).lower()
    return bool(line) and needle.lower() in line


def alive(pid: int, *, timeout: float = 20.0) -> bool:
    """Is this pid the *panel's* interpreter?  For the launcher, which starts python.

    Kept separate from :func:`pid_exists` rather than folded into it: the launcher's
    question is "is the window I started still running", and for that the name is part of
    the answer -- a recycled pid belonging to some other program is not the panel.
    """
    return "python" in process_name(pid, timeout=timeout).lower()


def listeners(port: int, *, timeout: float = 20.0) -> list[int]:
    """Every ``(pid, ...)`` listening on ``port``, so "is there more than one?" is answerable.

    :func:`port_owner` returns the *first* owner, which is the right answer to "who holds
    this port" and the wrong answer to "is a second gateway running" -- the second one looks
    exactly like the first from the outside, and that is the failure §五 names.  Measured
    2026-09-18: the soak's duplicate check needs the count, not the winner.
    """
    result = run(["netstat", "-ano"], timeout=timeout)
    if result.returncode != 0:
        return []
    found: list[int] = []
    for line in (result.stdout or "").splitlines():
        parts = line.split()
        if len(parts) < 5 or "LISTEN" not in line.upper():
            continue
        if not parts[1].endswith(f":{port}"):
            continue
        try:
            pid = int(parts[-1])
        except ValueError:
            continue
        if pid not in found:
            found.append(pid)
    return found


def port_owner(port: int, *, timeout: float = 20.0) -> tuple[int, str]:
    """``(pid, process_name)`` listening on ``port``, or ``(0, "")`` when nobody is.

    The operator asked for this explicitly (P0 §五): one gateway, one instance, one owner
    of 8080.  This used to end with "nothing in this project starts the service --
    ``codebuddy --serve`` is started by hand", which was true until
    ``gateway_service.py`` was written and is exactly the prerequisite that工单 removed.
    Kept as a measurement rather than an assumption: "is there a second one?" is a question
    about the port, and the port does not care who asked.
    """
    result = run(["netstat", "-ano"], timeout=timeout)
    if result.returncode != 0:
        return 0, ""
    for line in (result.stdout or "").splitlines():
        parts = line.split()
        if len(parts) < 5 or "LISTEN" not in line.upper():
            continue
        if not parts[1].endswith(f":{port}"):
            continue
        try:
            pid = int(parts[-1])
        except ValueError:
            continue
        listing = run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], timeout=timeout)
        name = ""
        if listing.returncode == 0 and listing.stdout.strip():
            first = listing.stdout.strip().splitlines()[0]
            name = first.split(",")[0].strip('"')
        return pid, name
    return 0, ""
