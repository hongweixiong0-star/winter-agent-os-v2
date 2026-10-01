"""The learning window must be reachable while real work exists, and open only once.

Operator directive 2026-10-01 §二十四 ("让无人值守时间变成自动补能力时间").

The rule this replaces was **correct about priority and unreachable in practice**.  It read
``if not known_work:`` -- prepare safe discovery only when nothing runnable exists -- and the
board always has something runnable.  Measured 2026-10-01: the element table was never built,
``capability_bootstrap`` was never handed a candidate step, and
``learning/capability_bootstrap/runtime_discovery.json`` had never been written once in the
project's history.  A permanently closed window that reports no error is the failure mode here.

So the load-bearing assertions are: (1) the gate is not "no known work at all", because that is
the shape that made it unreachable, and (2) the budget number is read from the projection rather
than restated, because a private copy would let the runtime gate on a figure the projection no
longer honours.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.capability_bootstrap import DEFAULT_BUDGET  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402

RUNTIME_SOURCE = ROOT / "winter_agent_v2/runtime.py"
BOOTSTRAP_SOURCE = ROOT / "winter_agent_v2/capability_bootstrap.py"


class _Harness:
    """Just enough of a runtime for the window question, and nothing that touches a device."""

    def __init__(self, state=None):
        self._state = state if state is not None else {}

    def _bootstrap_state(self):
        return self._state


def _open(harness) -> bool:
    return LiveRuntime._learning_window_open(harness)


def test_the_window_opens_once_and_then_stays_shut() -> None:
    harness = _Harness()

    assert _open(harness) is True, "with no visit recorded this run, the window is open"
    assert _open(harness) is False, "the window is one shot per process, not per step"
    assert harness._learning_window_used is True


def test_the_window_respects_the_budget_it_reads_from_the_projection() -> None:
    spent = DEFAULT_BUDGET["max_bootstrap_visits_per_run"]
    harness = _Harness({"__run__": {"visits_this_run": spent}})

    assert _open(harness) is False, (
        "the budget already records the run's visits, so the runtime must not offer another"
    )


def test_an_unreadable_ledger_does_not_open_a_window() -> None:
    class _Boom:
        def _bootstrap_state(self):
            raise OSError("ledger unreadable")

    assert _open(_Boom()) is False, "an unreadable ledger is a closed window, not a wildcard"


def test_the_runtime_reads_the_projection_budget_instead_of_restating_it() -> None:
    source = RUNTIME_SOURCE.read_text(encoding="utf-8")

    assert "DEFAULT_BUDGET[" in source, (
        "the runtime must read the projection's own budget; a private copy of "
        "max_bootstrap_visits_per_run would drift from the number the projection honours"
    )
    assert '"max_bootstrap_visits_per_run": 1' not in source, (
        "runtime.py restates the projection's budget value instead of importing it"
    )
    assert "DEFAULT_BUDGET" in BOOTSTRAP_SOURCE.read_text(encoding="utf-8")


def test_the_discovery_path_is_not_gated_on_no_known_work_at_all() -> None:
    """The gate that made the window unreachable, pinned so it cannot come back.

    ``if not known_work:`` alone is the measured-dead form: the board always has runnable work,
    so the branch never ran.  The condition must also ask the learning window.
    """
    source = RUNTIME_SOURCE.read_text(encoding="utf-8")

    assert "if not known_work or self._learning_window_open():" in source, (
        "the safe-discovery path is gated on 'no known executable work', which measured "
        "2026-10-01 never happens in production -- the learning window would be welded shut "
        "again, and nothing would report it"
    )
