"""Capture the console's own window, so a claim about what the operator sees can be looked at.

Why this exists: every other ruler in this repo reads the window's *outputs* (a variable it set, a
hash it recorded, a log line it wrote).  Those prove the code ran, not what the operator received --
and the whole 2026-10-04 audit is about the gap between those two.  A screenshot closes it.

It is deliberately a root-level script rather than a production tool: it is an instrument for a
human reviewing a change, not part of the runtime, and nothing in the package may depend on it.

usage:
    python _capture_panel_window.py [--out <png>] [--title-contains <text>]

Exit code 0 on a capture, 1 when no visible window matches (which is itself the finding -- a console
that is not on screen cannot be reviewed, and "the window is fine" is then an assumption).
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SetProcessDPIAware()

TITLE_DEFAULT = "Winter Agent OS V2"


def _windows() -> list[tuple[int, str, tuple[int, int, int, int]]]:
    """Every visible top-level window as ``(hwnd, title, (l, t, r, b))``."""
    found: list[tuple[int, str, tuple[int, int, int, int]]] = []
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        if rect.right - rect.left < 80 or rect.bottom - rect.top < 80:
            return True  # a tray tooltip or a hidden stub, not a window to review
        found.append((hwnd, buf.value, (rect.left, rect.top, rect.right, rect.bottom)))
        return True

    user32.EnumWindows(proto(visit), 0)
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(ROOT / "learning" / "control_panel"
                                             / "_panel_window.png"))
    parser.add_argument("--title-contains", default=TITLE_DEFAULT)
    args = parser.parse_args(argv)

    matches = [w for w in _windows() if args.title_contains in w[1]]
    if not matches:
        print(f"no visible window whose title contains {args.title_contains!r}")
        print("visible windows:")
        for _hwnd, title, rect in _windows():
            print(f"   {title!r}  {rect}")
        return 1

    hwnd, title, bbox = max(matches, key=lambda w: (w[2][2] - w[2][0]) * (w[2][3] - w[2][1]))
    print(f"window: {title!r}  hwnd={hwnd}  bbox={bbox}")

    # Raise it, because a screenshot of a window that is behind another window is a screenshot of
    # the other window.  Best-effort: focus can be refused, and if it is, the capture still happens
    # and the reader sees the truth rather than an error.
    user32.ShowWindow(hwnd, 9)          # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    time.sleep(1.2)                      # one Tk tick, so the redraw is on screen

    from PIL import ImageGrab

    image = ImageGrab.grab(bbox=bbox, all_screens=True)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)
    grey = image.convert("L")
    pixels = list(grey.get_flattened_data()) if hasattr(grey, "get_flattened_data") \
        else list(grey.getdata())
    print(f"saved {out}  {image.size}  mean luminance {sum(pixels) // len(pixels)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
