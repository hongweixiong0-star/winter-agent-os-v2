"""A round that executed nothing is not a system failure, and the device shows it.

Measured 2026-10-03 07:22 local, after 206 consecutive healthy rounds: the panel had been
silent for **five hours**, and ``tools/measure_auto_uptime.py`` said why --

    [panel] 02:28:11  本轮结束：NO EXECUTION
    [panel] 02:29:15  未进入下一轮：本轮被判定为系统故障：NO_EXECUTION

    last_round_at  2026-10-02T18:29:15Z   current_consecutive_continues  0
    stop_category  SYSTEM_FAILURE          healthy  False
    halt_reason    本轮被判定为系统故障：NO_EXECUTION

``NO_EXECUTION`` is in none of the three declared tables, so ``classify_stop_reason`` fell
through to ``SYSTEM_FAILURE``, the panel read ``healthy=False``, and the cycle never started
again.  Verified directly:

    classify_stop_reason("NO_EXECUTION", decision_skill=..., action_executed=False)
      -> StopCategory.SYSTEM_FAILURE

This is the **third** time this project has been stopped by a reason missing from a table,
and the module already says so twice, in detail, for two other reasons:

* ``GLOBAL_WAIT`` -- "It was listed as NON_FATAL but never as EXPECTED, so
  ``classify_stop_reason`` fell through to SYSTEM_FAILURE and the panel's ``healthy`` became
  false -- which stopped AUTO, so that scheduled wakeup could never run."
* ``ACTIVE_ROLE_NO_CANDIDATE_REOBSERVE`` -- "Missing from this set, it fell through
  ``classify_stop_reason`` to SYSTEM_FAILURE, which made the panel's ``healthy`` false and
  stopped AUTO entirely; measured on pin 7055f02, 2026-09-30, the device then sat idle."

Both of those were reasons that *planned nothing on purpose*.  ``NO_EXECUTION`` is the same
kind of statement -- the brain declined and no action was issued -- and it is the reason
``_failure_type_from`` already uses for a step that did not execute.  So it belongs in
``CAPABILITY_GAP_STOPS`` beside them, next to ``skill_not_ready`` and ``no_ready_skill``,
which are the other two ways a run can decide there is nothing to do.

Why CAPABILITY_GAP and not EXPECTED_NO_ACTION: it says something went wrong on the way to
a decision (a skill was named and could not run), whereas EXPECTED_NO_ACTION is for
"nothing needed doing", which is not what happened -- something was attempted at the
decision level and did not execute.
"""

import pytest

from winter_agent_v2.runtime_snapshot import (
    CAPABILITY_GAP_STOPS,
    COMPLETED_STOPS,
    EXPECTED_NO_ACTION_STOPS,
    StopCategory,
    classify_stop_reason,
)


def test_no_execution_is_declared_somewhere_rather_than_falling_through():
    """The defect as one assertion: it used to be in no table, so it fell through."""
    assert "NO_EXECUTION" not in EXPECTED_NO_ACTION_STOPS, (
        "it is not 'nothing needed doing' -- a skill was named and could not run, which is "
        "what skill_not_ready and no_ready_skill already say"
    )
    assert "NO_EXECUTION" in CAPABILITY_GAP_STOPS, (
        "it must be declared, beside the other two ways a run can decide there is nothing "
        "to do: skill_not_ready and no_ready_skill"
    )
    assert "NO_EXECUTION" not in COMPLETED_STOPS
    assert classify_stop_reason("NO_EXECUTION", decision_skill="BACK", action_executed=False) is (
        StopCategory.CAPABILITY_GAP
    ), (
        "an undeclared reason classifies as SYSTEM_FAILURE, the panel reads healthy=False, "
        "and the cycle does not start again -- measured five hours of idle device on "
        "2026-10-02T18:29:15Z"
    )


def test_a_declared_reason_survives_the_colon_suffix_form():
    """The other half of the same trap, and it has bitten this module before.

    Reasons carry detail after a colon -- ``ROLE_SWITCHED_TO:1061663148``,
    ``SESSION_DOMAIN_STUCK:AAA: the same signature 3x running (ab12cd34ef)`` -- and matching
    only the bare token lets a declared reason fall through anyway.  ``_declares`` exists for
    exactly this, so the declaration has to be checked in the form it is emitted in.
    """
    for reason in ("NO_EXECUTION", "NO_EXECUTION:SKILL_NOT_READY", "NO_EXECUTION:dry_run"):
        assert classify_stop_reason(reason, decision_skill="BACK", action_executed=False) is (
            StopCategory.CAPABILITY_GAP
        ), f"{reason!r} fell through the classifier"


@pytest.mark.parametrize(
    "reason",
    [
        # The two already fixed, kept as the regression this file's case belongs to.
        "GLOBAL_WAIT",
        "ACTIVE_ROLE_NO_CANDIDATE_REOBSERVE",
        "SESSION_DOMAIN_STUCK",
        # The third one.
        "NO_EXECUTION",
    ],
)
def test_no_declared_reason_stops_auto(reason):
    """The invariant, stated over every reason that has ever caused this.

    Each of these was a round that ended deliberately, and each one cost the device a
    stretch of idle time when the classifier called it a fault.  A new entry added to any
    table must not be able to reintroduce it, so the assertion is over the union rather than
    over today's three.
    """
    category = classify_stop_reason(reason, decision_skill="BACK", action_executed=False)
    assert category is not StopCategory.SYSTEM_FAILURE, (
        f"{reason} is classified as a system failure, which stops the cycle entirely"
    )
    assert category is not StopCategory.OTHER if hasattr(StopCategory, "OTHER") else True
