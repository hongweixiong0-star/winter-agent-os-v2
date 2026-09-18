"""One question, one answer: which trace is current?

Operator §7, from a measured defect.  The window had two selectors -- the development page took
the first active-or-awaiting record, the closed-loop card took whichever chain
``unattended_closure`` called newest -- and on 2026-09-18 23:14 it named
``OPEN_MARCH_FORMATION``/``06271322`` in one region and ``SPEND_STAMINA_ON_BEAST``/``5b525aa4``
in the other.  Both said "current".  That is a conflict by construction.

The ranking is the operator's, and so is the rule that a finished trace may never displace an
open one.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.escalation_queue import (  # noqa: E402
    DONE, FAILED, LIVE_VERIFIED, LIVE_VERIFY_PENDING, NEW, QUEUED, REJOINED, SUBMITTED,
    VERSION_ACTIVE, WORKING, EscalationRecord, EscalationSnapshot, current_development_trace,
)

NOW = datetime(2026, 9, 18, 23, 0, tzinfo=timezone.utc)


def _record(capability: str, state: str, *, minutes_ago: float = 0.0, job: str = "",
            outcome: str = "", tag: str = "") -> EscalationRecord:
    """One record.  ``tag`` distinguishes two records for the *same* capability, because the
    snapshot is keyed by trace and two identical keys would collapse into one."""
    seen = NOW - timedelta(minutes=minutes_ago)
    return EscalationRecord(
        key=f"{capability}|F{tag}|S", capability=capability, skill="S", state=state,
        job_id=job or f"job-{capability}{tag}", outcome=outcome,
        first_seen=seen, last_seen=seen, submitted_at=seen,
    )


def _snapshot(*records: EscalationRecord) -> EscalationSnapshot:
    return EscalationSnapshot({r.key: r for r in records})


def test_nothing_open_means_no_current_trace():
    """``None`` is a real answer: a reader must not be handed a finished trace as the present."""
    assert current_development_trace(_snapshot()) is None
    assert current_development_trace(_snapshot(
        _record("A", DONE, outcome=LIVE_VERIFIED), _record("B", FAILED))) is None


def test_an_agent_editing_right_now_outranks_everything():
    """The operator's first rank."""
    chosen = current_development_trace(_snapshot(
        _record("WAITING", LIVE_VERIFY_PENDING),
        _record("EDITING", WORKING),
        _record("LOADED", VERSION_ACTIVE),
        _record("FRESH", NEW),
    ))
    assert chosen.capability == "EDITING"


def test_the_full_ladder_in_the_operators_order():
    """WORKING/SUBMITTED -> LIVE_VERIFY_PENDING -> VERSION_ACTIVE -> REJOINED -> NEW/QUEUED.

    Asserted as one invariant rather than seven expectations: adding a *lower*-ranked open trace
    never displaces a higher-ranked one, whatever else is present.  That is the property the
    ranking is for, and it is the one a future edit is most likely to break.
    """
    ladder = [
        ("W", WORKING), ("S", SUBMITTED), ("V", LIVE_VERIFY_PENDING), ("A", VERSION_ACTIVE),
        ("R", REJOINED), ("N", NEW), ("Q", QUEUED),
    ]
    present: list[EscalationRecord] = []
    for capability, state in ladder:
        present.append(_record(capability, state, minutes_ago=len(present)))
        chosen = current_development_trace(_snapshot(*present))
        assert chosen.capability == "W", (
            f"adding {capability}({state}) displaced the highest-ranked open trace"
        )
    # And with the top ranks removed, the next one down takes over.
    assert current_development_trace(_snapshot(*present[1:])).capability == "S"
    assert current_development_trace(_snapshot(*present[2:])).capability == "V"
    assert current_development_trace(_snapshot(*present[3:])).capability == "A"
    assert current_development_trace(_snapshot(*present[4:])).capability == "R"
    assert current_development_trace(_snapshot(*present[5:])).capability == "N"
    assert current_development_trace(_snapshot(*present[6:])).capability == "Q"


def test_a_finished_trace_never_displaces_an_open_one():
    """The rule the operator stated outright: DONE/FAILED must not cover an unfinished trace."""
    chosen = current_development_trace(_snapshot(
        _record("OLD_WIN", DONE, minutes_ago=1, outcome=LIVE_VERIFIED),
        _record("RECENT_FAIL", FAILED, minutes_ago=0),
        _record("STILL_OPEN", NEW, minutes_ago=600),
    ))
    assert chosen.capability == "STILL_OPEN", (
        "an open trace outranks a fresher finished one, however recent"
    )


def test_ties_inside_a_rank_go_to_the_most_recent_activity():
    chosen = current_development_trace(_snapshot(
        _record("STALE", WORKING, minutes_ago=30),
        _record("FRESH", WORKING, minutes_ago=1),
    ))
    assert chosen.capability == "FRESH"


def test_a_capability_has_at_most_one_current_trace_by_construction():
    """Two records for one capability can exist; only one may be returned."""
    chosen = current_development_trace(_snapshot(
        _record("SAME", WORKING, minutes_ago=5, tag="a"),
        _record("SAME", LIVE_VERIFY_PENDING, minutes_ago=1, tag="b"),
    ))
    assert chosen.capability == "SAME"
    assert chosen.state == WORKING, "the higher rank wins even for the same capability"


def test_the_panel_and_the_card_share_the_selector():
    """Structural: a second selector is how the two regions disagreed in the first place."""
    panel = (ROOT / "tools/control_panel.py").read_text(encoding="utf-8")
    assert "current_development_trace" in panel
    # The old independent picks must be gone.
    assert '"current": active[0] if active else None' not in panel, (
        "the development page must not keep its own selector"
    )
    assert "chain = chains[-1]" not in panel, (
        "the card must not keep its own 'newest' pick"
    )
    assert "is_current" in panel, (
        "a page showing history must say that is what it is"
    )
