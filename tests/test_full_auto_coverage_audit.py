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
            # This read ``assert row["skills"]`` until 2026-10-02, and that form is what made the
            # check go red: an UNKNOWN goal that declares what it is waiting to observe is priced
            # by ``goal_utility.observation_ticket`` and carried on the board *without* a skill,
            # which is the deliberate behaviour of ``rank``'s own §5 comment ("a goal with
            # something to observe stays on the board; one with neither a skill nor anything to
            # observe still does not").  The relaxation is recorded rather than silent, as
            # knowledge/failure_patterns/architecture/VERIFIER_SHAPE_MISMATCH.md requires, and it
            # is narrower than it looks: the assertion below still forbids the case that comment
            # forbids -- a candidate with neither.  Which *kind* of candidate it is, and why, is
            # pinned by test_every_row_carries_a_reason_in_the_choosers_vocabulary and
            # test_the_reason_separates_goals_the_catalogue_price_cannot.
            assert row["skills"] or row["observation"] > 0, (
                f"{goal_id} was chosen with neither a skill nor anything declared to observe"
            )


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


def test_a_row_reports_the_choosers_own_numbers_not_the_catalogue_price() -> None:
    """The board's ``priority`` is a *property* that answers ``-inf`` for every non-actionable
    status, so it cannot tell two such goals apart -- and that is exactly what it did.

    Measured 2026-10-02 on the live board: 26 of 33 rows read ``-inf``, including the three the
    chooser actually prices as observation work.  ``goal_utility.utility`` says so itself -- "Its
    static ``priority`` is the base and is never recomputed here" -- and then prices a goal that
    declared what it waits for at ``OBSERVATION_TICKET_FLOOR``.  So a row has to carry the number
    the chooser used, next to the catalogue price, or the report contradicts its own verdict.
    """
    rows, _ = audit.survey()

    candidates = [r for k, r in rows.items()
                  if not k.startswith("<probe") and r["verdict"] == audit.CANDIDATE]
    assert candidates, "the probes must produce at least one chooser candidate"

    for row in candidates:
        assert "chooser_base" in row and "chooser_total" in row, (
            f"{row['goal_id']} reports a verdict without the numbers behind it"
        )
        assert row["chooser_base"] > float("-inf"), (
            f"{row['goal_id']} is on the chooser's board but priced -inf"
        )

    # ...and the two must be allowed to disagree, because for an UNKNOWN goal they do.
    priced_up = [r for r in candidates if r["priority"] == float("-inf")]
    assert priced_up, (
        "no candidate row has a -inf catalogue price, so this test cannot show the two numbers "
        "differ -- if the board really changed, say so here rather than deleting the assertion"
    )
    for row in priced_up:
        assert row["chooser_base"] > 0, (
            f"{row['goal_id']}: the catalogue says -inf and the chooser says "
            f"{row['chooser_base']} -- the row has to carry which one it means"
        )


def test_every_row_carries_a_reason_in_the_choosers_vocabulary() -> None:
    """Operator §二十八: an unknown goal must not be dressed up, and a stated one must say why."""
    rows, _ = audit.survey()

    assert audit.CHOOSER_REASONS, "the reason vocabulary must be declared, not implied"
    for goal_id, row in rows.items():
        if goal_id.startswith("<probe"):
            continue
        assert row.get("reason") in audit.CHOOSER_REASONS, (
            f"{goal_id} carries reason {row.get('reason')!r}, outside {sorted(audit.CHOOSER_REASONS)}"
        )


def test_the_reason_separates_goals_the_catalogue_price_cannot() -> None:
    """The actual target: one unique diagnostic reason per enabled goal.

    Every row sharing ``priority == -inf`` is a row the old report could not describe.  They must
    now fall into at least two different reasons, because they are at least two different facts:
    one is on the chooser's board waiting to observe something, another declared nothing to
    observe and is therefore off it entirely.
    """
    rows, _ = audit.survey()

    flat = [r for k, r in rows.items() if not k.startswith("<probe") and r["priority"] == float("-inf")]
    assert flat, "expected non-actionable rows on the live board"
    reasons = {r["reason"] for r in flat}
    assert len(reasons) >= 2, (
        f"all {len(flat)} -inf rows share one reason {reasons}; the report still cannot "
        "tell them apart"
    )
    # And the on-board/off-board split has to be visible in the reason, not only in the verdict.
    on = {r["reason"] for r in flat if r["verdict"] == audit.CANDIDATE}
    off = {r["reason"] for r in flat if r["verdict"] != audit.CANDIDATE}
    assert on and off and not (on & off), (
        f"the reasons do not separate the two: on={on} off={off}"
    )
