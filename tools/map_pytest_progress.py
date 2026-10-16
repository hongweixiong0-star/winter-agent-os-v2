"""Recover a pytest failure list from a ``-q`` progress stream (no re-run needed).

Why this exists
---------------
On this machine a full ``pytest tests`` run has repeatedly **lost its summary line**: the host's
batch-delete guard interrupts pytest while it cleans ``%TEMP%\\pytest-of-*``, ``SystemExit``
swallows the terminal summary, and the run's outcome disappears (``03_NEXT_ACTION.md`` records
this, and 2026-10-14's full run was the first to get a summary at all, via ``--basetemp``).

The **progress stream** still reaches stdout.  This suite's order is **deterministic** (no
``pytest-randomly`` is installed), so the Nth progress character is the Nth collected test.  This
maps the two back together and names the failures -- from a file you already captured.

Usage
-----
    python -m pytest tests -q > progress.txt 2>&1      # capture (summary may be swallowed)
    python tools/map_pytest_progress.py progress.txt   # name the failures

    python tools/map_pytest_progress.py --collect      # just print the collection order

The tool is **read-only**: it neither runs the suite nor writes anything.

How the two halves are joined
-----------------------------
``--collect-only -q`` prints one test id per line, in execution order.  A ``-q`` run prints one
result character per collected item (``.`` pass, ``F`` fail, ``E`` error, ``s`` skip, ``x``/``X``
xfail/xpass), interrupted only by pytest's ``[ NN%]`` markers.  Strip the markers, keep the
result characters, and the two sequences line up index-for-index.  When they do not line up the
tool says so instead of guessing.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.winproc import hidden_kwargs  # noqa: E402

#: pytest's progress characters, from `_pytest.terminal`.
RESULT_CHARS = frozenset(".FEsxX")
_MARKER = re.compile(r"\[[^\]\n]*\]")


def _progress_characters(lines: list[str]) -> str:
    """Every result character from the progress region, markers removed.

    Collection stops at the first line that is not pure progress: the summary lines that follow
    (``FAILED tests/x.py::y - ...``) contain letters such as ``F``/``E`` that would otherwise be
    counted as results.
    """
    out: list[str] = []
    for line in lines:
        stripped = _MARKER.sub("", line)
        chars = [ch for ch in stripped if not ch.isspace()]
        if not chars:
            continue
        if not all(ch in RESULT_CHARS for ch in chars):
            break
        out.extend(chars)
    return "".join(out)


def _collection_order(root: Path) -> list[str]:
    """The test ids pytest will run, in order -- from the tree ``root``."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=root, capture_output=True, text=True,
        # The one runner's hidden-window flags: the output is captured, so hiding the window
        # changes nothing about the answer -- and the wiring guard checks this mechanically
        # for every subprocess call under ``tools/``.
        **hidden_kwargs(),
    )
    return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip().startswith("tests/")]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("progress", nargs="?", type=Path,
                        help="a captured `pytest -q` stdout (summary may be missing)")
    parser.add_argument("--collect", action="store_true",
                        help="print the collection order and exit")
    parser.add_argument("--root", type=Path, default=ROOT,
                        help="the tree the run happened in (default: this tool's own tree). "
                             "The data root and the pin tree collect different sets, so a run "
                             "captured in one must be mapped against that same tree.")
    args = parser.parse_args(argv)

    order = _collection_order(args.root)
    if args.collect:
        print("\n".join(order))
        print(f"# {len(order)} test id(s)")
        return 0

    if args.progress is None:
        parser.error("give a captured progress file, or --collect")
    text = args.progress.read_text(encoding="utf-8", errors="replace")
    stream = _progress_characters(text.splitlines())

    print(f"collected : {len(order)}")
    print(f"stream    : {len(stream)} result character(s)")
    if len(stream) != len(order):
        print("NOTE: counts differ -- the run may be incomplete, or the order differs.",
              file=sys.stderr)

    failures: list[tuple[str, str]] = []
    for index, char in enumerate(stream):
        if char in ("F", "E") and index < len(order):
            failures.append((char, order[index]))
    print(f"failures  : {len(failures)}")
    for char, test in failures:
        print(f"  {char}  {test}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
