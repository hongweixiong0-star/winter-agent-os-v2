"""The FULL AUTO coverage audit must measure the board the Scheduler sees, not the raw library.

Operator directive 2026-10-01 §三十.  This file exists because of a measured mistake, not a
hypothetical one: the first version of the tool asked ``GoalLibrary.discover`` directly and
reported ``BOARD_ONLY_NO_SKILL = 0``, which reads as "nothing is blocked by a missing skill".
The runtime does not use that board.  It projects it through
``capability_bootstrap.project_runtime_discovery`` first (``runtime._project_capability_discovery``),
and the projection is what decides whether an UNKNOWN goal becomes a safe discovery candidate
or stays unselectable.

So the load-bearing assertion here is not any particular count -- those move as the project
grows.  It is that the projection ran at all.  If someone ever simplifies ``survey()`` back to
"just call discover", the diagnostics go empty and this test says why that is wrong.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import full_auto_coverage_audit as audit  # noqa: E402


def test_the_audit_projects_the_board_instead_of_reading_the_raw_library() -> None:
    rows, diagnostics = audit.survey()

    assert rows, "the probes must produce a board at all"
    assert diagnostics, (
        "no projection reasons were recorded.  That means the audit went back to reading the "
        "raw GoalLibrary, which is not the board the Scheduler chooses from -- and it is exactly "
        "the measurement error that made a blocked goal look unblocked."
    )


def test_a_board_row_carries_the_verdict_the_real_chooser_gives() -> None:
    rows, _ = audit.survey()

    for goal_id, row in rows.items():
        if goal_id.startswith("<probe"):
            continue
        assert row["verdict"] in audit.ORDER, f"{goal_id} has an unknown verdict {row['verdict']!r}"
        # The verdicts are mutually exclusive by construction: a goal the chooser keeps is not
        # also reported as board-only, and vice versa.
        if row["verdict"] == audit.CANDIDATE:
            assert row["skills"], f"{goal_id} was chosen with no available skill"


def test_missing_navigation_is_reported_in_the_runtimes_own_words() -> None:
    """The audit must not invent vocabulary for the gap it is reporting.

    ``MISSING_NAVIGATION`` is ``capability_bootstrap``'s string, produced by the same code the
    runtime runs.  A private paraphrase here would let the audit and the runtime disagree about
    what is blocking a goal while both look consistent on their own.
    """
    _, diagnostics = audit.survey()

    assert any("MISSING" in reason or "READY" in reason or "BOOTSTRAP" in reason
               for reason in diagnostics), (
        f"none of the recorded reasons look like bootstrap's vocabulary: {sorted(diagnostics)}"
    )
