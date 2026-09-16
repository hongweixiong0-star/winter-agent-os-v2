"""Write pytest failures to a file the moment they happen.

Why this exists (2026-09-16).  On this host a sandbox shim aborts any bulk delete of
more than ~50 files in one turn, and pytest performs one at the very end of a session
(it removes the session's own `garbage-*` temp root).  The `SystemExit` kills the
process *before* the terminal reporter prints its summary, so the results of a full
917-test run are visible only as progress dots -- a failure has a position but no name
and no traceback.

This plugin is a `pytest_runtest_logreport` hook that appends each failure's node id,
location and longrepr to a file as the test finishes, so the report survives the
aborted summary.  It writes to `WINTER_FAILWATCH_OUT` if that env var is set, else to
`out_failwatch.txt` in the current directory.  It is read-only with respect to the
project and never swallows the failure: the exception still propagates to pytest's own
reporting.

Usage
-----
    PYTEST_PLUGINS=winter_failwatch PYTHONPATH=tools \
        python -m pytest tests -q -o tmp_path_retention_policy=all
"""
from __future__ import annotations

import os
from pathlib import Path


def _target() -> Path:
    return Path(os.environ.get("WINTER_FAILWATCH_OUT", "out_failwatch.txt"))


def pytest_configure(config):  # noqa: D103 - pytest hook
    out = _target()
    try:
        out.write_text("")
    except OSError:
        pass
    print(f"\n[winter_failwatch] failures will be appended to {out}")


def pytest_runtest_logreport(report):  # noqa: D103 - pytest hook
    if report.when != "call" or not report.failed:
        return
    line = (
        f"\n=== {report.nodeid}\n"
        f"    when={report.when} outcome={report.outcome}\n"
        f"    {getattr(report, 'longrepr', '')}\n"
    )
    try:
        with _target().open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass
