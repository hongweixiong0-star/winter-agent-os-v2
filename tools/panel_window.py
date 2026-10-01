"""Show the panel that is already running, so a second double-click is not a no-op.

Two separate mechanisms make the second launch of the desktop entry point silent,
and both were measured on 2026-10-01:

* the scheduled task is registered with ``MultipleInstancesPolicy=IgnoreNew``, so
  once the panel is running ``schtasks /Run`` answers 正在运行 and starts *nothing* --
  ``desktop_startup.log`` gains no row, ``PRODUCTION_LAUNCH.log`` gains no row, and
  no window appears;
* when the panel was not started by that task (measured 09:59:02), a new instance
  does launch, and ``control_panel._acquire_single_instance`` returns False, which
  used to be a bare ``return 0``.

Neither mechanism is wrong on its own.  What was missing is that the operator's
double-click asks "show me the panel" and got no answer at all -- no window, no log
line, and the launcher still printing 成功.  Measured: the panel was alive but wrote
nothing from 12:03:42 until the machine rebooted at 20:41, so every double-click in
those 8.5 hours opened nothing.

So the launcher asks this module first, and again after starting the task.  It
answers with one of three codes plus the reason on stdout, which is what lets the
batch file either show the panel, or say plainly that it could not.

Exit codes (the launcher branches on these, in descending order):

===  ==========================================================================
0    a running panel's window was found and brought to the front
1    nothing is running -- the caller should start one
2    a panel process exists but its window cannot be shown (reason on stdout)
===  ==========================================================================
"""

from __future__ import annotations

import ctypes
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import winproc  # noqa: E402

SHOWN = 0
ABSENT = 1
UNAVAILABLE = 2

SW_SHOW = 5
SW_RESTORE = 9
WM_NULL = 0x0000
SMTO_NORMAL = 0x0000
SMTO_ABORTIFHUNG = 0x0002
#: ``SMTO_NORMAL``, never ``SMTO_ABORTIFHUNG``.  Measured 2026-10-01 21:03 against the
#: live panel: with ``SMTO_ABORTIFHUNG`` a *minimised* window reported no response --
#: the call sat for the full 2000 ms and returned 0 -- while ``SMTO_NORMAL`` answered
#: that same window in 219 ms.  Minimised is exactly the state an operator is in when
#: they double-click, so the abort flag would have called a healthy panel hung and
#: refused to raise it, which is the defect this module exists to remove.
WINDOW_PROBE_FLAGS = SMTO_NORMAL
WINDOW_PROBE_TIMEOUT_MS = 2000
WINDOW_POLL_SECONDS = 0.5

#: Tk's window class for a ``Tk``/``Toplevel`` window.  Needed to pick the panel out of
#: the several top-level windows a Tk process owns -- see ``top_level_windows``.
PANEL_WINDOW_CLASS = "TkTopLevel"


def panel_pid_path() -> Path:
    """Where the panel records its own pid, derived from this file's location.

    Derived rather than configured, because the pinned code checkout mounts the shared
    data directories into itself: the pinned tree's ``learning/`` resolves to the same
    file the panel writes, and so does this path.
    """
    return Path(__file__).resolve().parents[1] / "learning" / "control_panel" / "panel.pid"


def read_panel_pid(path: Path | None = None) -> int:
    """The pid the live panel recorded, or ``0`` when there is nothing readable."""
    try:
        raw = (path or panel_pid_path()).read_text(encoding="utf-8").strip()
    except OSError:
        return 0
    try:
        return int(raw)
    except ValueError:
        return 0


def top_level_windows(pid: int) -> list[int]:
    """Handles of ``pid``'s Tk top-level windows -- the window that is actually the panel.

    Filtered by class on purpose.  A Tk process also owns a hidden TtkMonitorWindow, an
    IME window and an MSCTFIME window, and ``EnumWindows`` returns them in Z-order
    rather than with the main window first: measured 2026-10-01 21:06 the order was
    TtkMonitorClass, TkTopLevel, MSCTFIME UI, IME -- so taking the first handle would
    have picked a window that is not the panel at all.

    ``EnumWindows`` rather than .NET's ``MainWindowHandle``: that property reports 0 for
    a Tk top-level, so on 2026-10-01 20:47 it answered "no window" while ``EnumWindows``
    showed a visible 1376x859 window titled "Winter Agent OS V2 — 无尽冬日 AI 指挥中心".
    A check built on the wrong API would have concluded the healthy panel did not exist.
    """
    if sys.platform != "win32":
        return []
    user32 = ctypes.windll.user32
    found: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)

    def _visit(hwnd: int, _lparam: int) -> bool:
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(owner))
        if owner.value != pid:
            return True
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(ctypes.c_void_p(hwnd), cls, 256)
        if cls.value == PANEL_WINDOW_CLASS:
            found.append(int(hwnd))
        return True

    user32.EnumWindows(callback_type(_visit), 0)
    return found


def window_is_responding(hwnd: int) -> bool:
    """False when the window's thread is not pumping messages, i.e. a frozen panel.

    ``SendMessageTimeout`` returns nonzero for "the call succeeded" (the message's own
    result lands in the out-parameter), so a zero really does mean timeout or failure.
    The flags decide whether that answer is trustworthy -- see ``WINDOW_PROBE_FLAGS``.
    """
    if sys.platform != "win32":
        return True
    result = ctypes.c_void_p()
    sent = ctypes.windll.user32.SendMessageTimeoutW(
        ctypes.c_void_p(hwnd), WM_NULL, 0, 0, WINDOW_PROBE_FLAGS,
        WINDOW_PROBE_TIMEOUT_MS, ctypes.byref(result),
    )
    return bool(sent)


def activate_window(hwnd: int) -> None:
    """Show and raise ``hwnd``.

    Windows may refuse the foreground change, but the window is restored to a visible
    state either way, which is what the operator asked for by double-clicking.
    """
    if sys.platform != "win32":
        return
    user32 = ctypes.windll.user32
    user32.ShowWindow(ctypes.c_void_p(hwnd), SW_SHOW)
    user32.ShowWindow(ctypes.c_void_p(hwnd), SW_RESTORE)
    user32.SetForegroundWindow(ctypes.c_void_p(hwnd))


def notify_operator(message: str) -> None:
    """Show an operator-visible box.  ``pythonw`` has no console, so a print is invisible."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.MessageBoxW(None, message, "Winter Agent OS V2", 0x40 | 0x1000)
    except Exception:  # a missing window station must not turn into a traceback
        pass


def panel_is_showing(pid: int) -> bool:
    """True when ``pid`` is a live process with a window on screen."""
    return bool(pid) and winproc.alive(pid, timeout=2.0) and bool(top_level_windows(pid))


def focus_existing_panel(path: Path | None = None) -> tuple[int, str]:
    """Bring the running panel's window forward.  ``(code, reason)``."""
    pid = read_panel_pid(path)
    if not pid:
        return ABSENT, "没有面板进程记录（panel.pid 缺失或不可读）"
    if not winproc.alive(pid, timeout=2.0):
        return ABSENT, f"它记录的进程 {pid} 已经不在了"
    windows = top_level_windows(pid)
    if not windows:
        return UNAVAILABLE, f"进程 {pid} 在运行，但没有可显示的窗口"
    hwnd = windows[0]
    # Raise it unconditionally.  A panel mid-round blocks its own message loop while it
    # waits on the worker, so a liveness probe answers "no" for a panel that is healthy
    # and merely busy -- measured 2026-10-01 21:05, where the first probe after
    # minimising sat for its whole timeout and the next one answered the same window in
    # 219 ms.  Gating on that would refuse to show the panel exactly when the operator
    # is most likely to be double-clicking, so the probe only decorates the answer.
    activate_window(hwnd)
    if not window_is_responding(hwnd):
        return SHOWN, (
            f"已把面板（PID {pid}）带到前台；它的窗口暂时没有响应"
            "（AUTO 轮次进行中，或已经卡住需要结束该进程）"
        )
    return SHOWN, f"已把运行中的面板（PID {pid}）带到前台"


def wait_for_panel(seconds: float, path: Path | None = None) -> tuple[int, str]:
    """Poll for a panel window, so a start that did not happen becomes visible.

    ``schtasks /Run`` returns 0 whether it started the task or ignored it because
    another instance was still registered, so the exit code cannot tell the operator
    which happened.  A window that never appears can.
    """
    deadline = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < deadline:
        if panel_is_showing(read_panel_pid(path)):
            return SHOWN, f"面板已启动（PID {read_panel_pid(path)}）"
        time.sleep(WINDOW_POLL_SECONDS)
    pid = read_panel_pid(path)
    if not pid:
        return UNAVAILABLE, (
            f"{seconds:.0f} 秒内没有面板写下 panel.pid：计划任务可能仍停留在"
            "「正在运行」（进程已死但任务实例未结束），所以 schtasks 忽略了这次启动。"
        )
    if not winproc.alive(pid, timeout=2.0):
        return UNAVAILABLE, f"panel.pid 里是 PID {pid}，但它已经不存在"
    return UNAVAILABLE, f"PID {pid} 在运行，但 {seconds:.0f} 秒内没有出现窗口"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--wait":
        seconds = float(args[1]) if len(args) > 1 else 30.0
        code, reason = wait_for_panel(seconds)
    else:
        code, reason = focus_existing_panel()
    print(reason, flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
