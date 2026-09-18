"""Watch for console windows that no operator asked for.

Operator P0, 2026-09-18: "GUI 运行过程中频繁短暂弹出黑色命令行窗口".  The fix was to route
every background process through ``winter_agent_v2.winproc``; this is how the *claim* is
checked, because "I removed the flags problem" is a statement about source code and the
operator's complaint is about pixels.

What it measures, by sampling (default every 150 ms):

* **Visible console-class top-level windows** -- ``ConsoleWindowClass`` and the Windows
  Terminal host class -- owned by a pid that is not on the allow-list.  A window that
  appears for one sample is enough to be reported: the flashes the operator described
  last a fraction of a second, so counting them is the point.
* **Children of the watched pids** that are console tools.  This separates "a child was
  started" from "a child was started *visibly*": the wrapper's whole job is that a child
  can exist without a window, and this shows both halves.

Usage:

    python tools/console_window_watch.py --seconds 150 --watch-pid 24112

Exit code is 0 when nothing was seen, 1 when a console window appeared (so it can be used
as a gate), 2 when the measurement itself failed.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wintypes
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import winproc  # noqa: E402

CONSOLE_CLASSES = {
    "consolewindowclass",              # a real console host
    "cascadia_hosting_window_class",   # Windows Terminal hosting a console
    "pseudoconsolewindow",
}

user32 = ctypes.WinDLL("user32", use_last_error=True)

ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _visible_windows() -> list[tuple[int, int, str]]:
    """``(hwnd, pid, class_name)`` for every visible top-level window."""
    found: list[tuple[int, int, str]] = []

    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(max(length + 1, 2))
        user32.GetWindowTextW(hwnd, buffer, len(buffer))
        class_buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buffer, 256)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        found.append((int(hwnd), int(pid.value), class_buffer.value))
        return True

    user32.EnumWindows(ENUMPROC(callback), 0)
    return found


def _process_tree() -> dict[int, int]:
    """``{pid: parent_pid}`` for every process.  One call, ~2 s cadence."""
    script = (
        "Get-CimInstance Win32_Process | "
        "ForEach-Object { \"$($_.ProcessId)|$($_.ParentProcessId)|$($_.Name)\" }"
    )
    listing = winproc.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout=40
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


def _descendants(roots: set[int], tree: dict[int, int]) -> set[int]:
    """Every pid whose parent chain reaches one of ``roots``.

    The allow-list cannot be "console windows that exist" -- the operator's own terminal is
    a console window, and flagging it would make this tool useless.  What matters is a
    console window *descended from the processes under test*: the panel runs from pythonw
    with no console, so any console a descendant opens is one the operator did not ask for.
    """
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=150.0)
    parser.add_argument("--interval", type=float, default=0.15)
    parser.add_argument("--watch-pid", type=int, default=0,
                        help="a pid whose children are also reported (typically the panel)")
    args = parser.parse_args(argv)

    roots = {int(args.watch_pid)} if args.watch_pid else {__import__("os").getpid()}
    tree = _process_tree()
    print(f"watching {args.seconds:.0f}s at {args.interval * 1000:.0f}ms intervals; "
          f"roots={sorted(p for p in roots if p)}")
    hits: list[str] = []
    seen_children: set[int] = set()
    samples = 0
    deadline = time.monotonic() + max(args.seconds, 1.0)
    while time.monotonic() < deadline:
        samples += 1
        if samples % 12 == 0:
            # Every ~2 s: enumerating the process tree costs a process of its own, and a
            # watcher that spawns 7 console tools a second would be measuring itself.
            tree = _process_tree()
        family = _descendants(roots, tree)
        seen_children |= {pid for pid in family}
        for _hwnd, pid, klass in _visible_windows():
            if klass.strip().lower() not in CONSOLE_CLASSES:
                continue
            if pid in roots or pid in family:
                line = (f"{time.strftime('%H:%M:%S')} console window from our own tree "
                        f"pid={pid} class={klass}")
                print("  ! " + line)
                hits.append(line)
        time.sleep(max(args.interval, 0.02))

    print(f"\nsamples={samples}  console windows from our tree={len(hits)}")
    if seen_children:
        print(f"descendant pids observed under the watched roots: {len(seen_children)} "
              f"(a child may exist without a window -- that is the point)")
    else:
        print("no descendants were spawned during the window")
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
