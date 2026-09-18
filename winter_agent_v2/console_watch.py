"""Console windows nobody asked for -- the measurement, in one place.

Operator P0, 2026-09-18: "GUI 运行过程中频繁短暂弹出黑色命令行窗口".  The fix was to route every
background process through ``winter_agent_v2.winproc``.  This module is how the *claim* is
checked, because "I removed the flags problem" is a statement about source code and the
operator's complaint is about pixels.

It lives in the package rather than in ``tools/console_window_watch.py`` because there are
now two askers: that CLI, run by hand while watching a launch, and the GUI's own acceptance
soak (§二十二 asks that a production run is measured, not a development run).  Two copies of
``EnumWindows`` would be two instruments that can drift, and an instrument that drifts
silently reports zero.

"Unwanted" is defined by descent, not by existence: the operator's own terminal is a console
window, and counting it would make every measurement fail.  What matters is a console window
*descended from the processes under test* -- the panel runs from ``pythonw`` with no console,
so a console opened by one of its descendants is one the operator did not ask for.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes

from . import winproc

#: Window classes that mean "a console".  ``PseudoConsoleWindow`` is the ConPTY host, which
#: is what an un-hidden child flashes on this machine -- measured 10-20 ms, which is why any
#: sampler slower than that misses it entirely.
CONSOLE_CLASSES = frozenset({
    "consolewindowclass",              # a real console host
    "cascadia_hosting_window_class",   # Windows Terminal hosting a console
    "pseudoconsolewindow",
})

IS_WINDOWS = winproc.os.name == "nt"

if IS_WINDOWS:  # pragma: no cover - the import itself only makes sense on Windows
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
else:  # keep the module importable so the soak can be tested anywhere
    _user32 = None
    _ENUMPROC = None


def visible_windows() -> list[tuple[int, int, str]]:
    """``(hwnd, pid, class_name)`` for every visible top-level window."""
    if not IS_WINDOWS:
        return []
    found: list[tuple[int, int, str]] = []

    def callback(hwnd, _lparam):
        if not _user32.IsWindowVisible(hwnd):
            return True
        length = _user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(max(length + 1, 2))
        _user32.GetWindowTextW(hwnd, buffer, len(buffer))
        class_buffer = ctypes.create_unicode_buffer(256)
        _user32.GetClassNameW(hwnd, class_buffer, 256)
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        found.append((int(hwnd), int(pid.value), class_buffer.value))
        return True

    _user32.EnumWindows(_ENUMPROC(callback), 0)
    return found


def process_tree(timeout: float = 40.0) -> dict[int, int]:
    """``{pid: parent_pid}`` for every process.  One external call, so keep it rare."""
    script = (
        "Get-CimInstance Win32_Process | "
        "ForEach-Object { \"$($_.ProcessId)|$($_.ParentProcessId)|$($_.Name)\" }"
    )
    listing = winproc.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout=timeout
    )
    tree: dict[int, int] = {}
    for line in (listing.stdout or "").splitlines():
        parts = line.strip().split("|")
        if len(parts) != 3:
            continue
        try:
            tree[int(parts[0])] = int(parts[1])
        except ValueError:
            continue
    return tree


def descendants(roots: "set[int] | frozenset[int]", tree: dict[int, int]) -> set[int]:
    """Every pid whose parent chain reaches one of ``roots``.  Bounded, never spins."""
    out: set[int] = set()
    for pid, parent in tree.items():
        walk = parent
        for _ in range(12):  # bounded: a corrupt tree must not spin
            if walk in roots:
                out.add(pid)
                break
            walk = tree.get(walk, 0)
            if not walk:
                break
    return out


def console_windows_for(roots: "set[int] | frozenset[int]",
                        *, tree: dict[int, int] | None = None,
                        windows: list[tuple[int, int, str]] | None = None
                        ) -> list[tuple[int, int, str]]:
    """Visible console windows owned by ``roots`` or by anything they spawned."""
    if not IS_WINDOWS or not roots:
        return []
    tree = process_tree() if tree is None else tree
    windows = visible_windows() if windows is None else windows
    ours = set(roots) | descendants(roots, tree)
    return [(hwnd, pid, cls) for hwnd, pid, cls in windows
            if pid in ours and cls.lower() in CONSOLE_CLASSES]


__all__ = ["CONSOLE_CLASSES", "IS_WINDOWS", "visible_windows", "process_tree",
           "descendants", "console_windows_for"]
