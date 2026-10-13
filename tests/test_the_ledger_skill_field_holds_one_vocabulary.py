# -*- coding: utf-8 -*-
"""The ledger's ``skill`` field carries three vocabularies.  One owner declares them; this checks it.

Measured 2026-10-10 over 10,381 ledger rows: 88 distinct values in ``skill``, of which **4 are not
registry skills** -- 172 rows, one row in sixty.  The names and what they really are:

| value | rows | what it actually is |
|---|---|---|
| `PRINTED_TAP` | 140 | a **session step kind** -- `session_adapters.STEP_PRINTED_TAP` |
| `SAFE_STOP` | 21 | a **decision outcome** -- `brain.Decision("SAFE_STOP", …)` |
| `OBSERVE_ONLY` | 10 | a **session step kind** -- `session_adapters.STEP_OBSERVE_ONLY` |
| `SELECT_QUICK_PANEL_CITY_TAB` | 1 | in no source file at all (2026-10-05, unresolved) |

**This was not only an analysis problem.** ``capability_gate`` collected every ``skill`` value into a
Goal's attempted set with no filter, ``capability_for_skill`` returns an unknown name unchanged, and the
resulting ``touched`` set is compared against escalation records -- so a *decision to stop* could move a
Goal's restart boundary and **reset its no-progress streak**.  Measured over 17,413 escalation rows,
``skill`` holds ``SAFE_STOP`` 90 times and ``capability`` holds it 11 times, so the collision was real:
14 of 47 Goals were affected.

The names live in ``skills.NON_SKILL_LEDGER_VALUES`` (production, because production has to filter on
them).  The *reasons* live here, and this file asserts the two do not drift apart.  The records are not
rewritten: §1 forbids altering a historical Episode, and a 140-row edit would destroy this trace.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from winter_agent_v2.capability_gate import attempted_skills
from winter_agent_v2.skills import NON_SKILL_LEDGER_VALUES, v2_registry

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "learning" / "episodes.jsonl"

#: Why each declared value is not a skill.  The **names** are owned by the production constant; this
#: mapping adds the reason and is asserted to cover exactly the same set.
WHY_NOT_A_SKILL: dict[str, str] = {
    "PRINTED_TAP": "session step kind (session_adapters.STEP_PRINTED_TAP)",
    "OBSERVE_ONLY": "session step kind (session_adapters.STEP_OBSERVE_ONLY)",
    "SAFE_STOP": "decision outcome (brain.Decision), not an action that ran",
    # The one entry that does NOT fit "it is a step kind": nothing in the tree defines this name.
    "SELECT_QUICK_PANEL_CITY_TAB": "absent from every source file; one row, 2026-10-05 -- unresolved",
}

#: The measured ceiling.  A guard that can absorb new values silently is not a guard.
MAX_NOT_A_SKILL = 4


def _ledger_skill_values() -> dict[str, int]:
    if not LEDGER.is_file():
        return {}
    counts: dict[str, int] = {}
    for line in LEDGER.open("r", encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        value = str(row.get("skill") or "")
        if value:
            counts[value] = counts.get(value, 0) + 1
    return counts


# --------------------------------------------------------------------- the declaration and its reason

def test_the_reasons_cover_exactly_the_declared_names():
    """Names in production, reasons here; a drift either way fails."""
    assert set(WHY_NOT_A_SKILL) == set(NON_SKILL_LEDGER_VALUES)
    assert len(NON_SKILL_LEDGER_VALUES) <= MAX_NOT_A_SKILL


def test_every_ledger_skill_is_registered_or_declared():
    values = _ledger_skill_values()
    if not values:
        pytest.skip(f"no ledger on disk: {LEDGER}")
    known = {str(getattr(s, "id", "") or "") for s in v2_registry().all()}
    unowned = sorted(v for v in values if v not in known and v not in NON_SKILL_LEDGER_VALUES)
    assert unowned == [], (
        "the ledger names values in `skill` that are neither registry skills nor declared non-skills: "
        f"{unowned}"
    )


def test_no_declaration_has_since_become_a_real_skill():
    known = {str(getattr(s, "id", "") or "") for s in v2_registry().all()}
    stale = sorted(n for n in NON_SKILL_LEDGER_VALUES if n in known)
    assert stale == [], f"these are registry skills now, so their declarations are stale: {stale}"


def test_the_declaration_is_not_doing_the_whole_job():
    values = _ledger_skill_values()
    if not values:
        pytest.skip(f"no ledger on disk: {LEDGER}")
    known = {str(getattr(s, "id", "") or "") for s in v2_registry().all()}
    real = sum(n for v, n in values.items() if v in known)
    declared = sum(n for v, n in values.items() if v in NON_SKILL_LEDGER_VALUES)
    assert real > declared, (
        f"declared non-skills ({declared} rows) are not the minority against real skills ({real} rows)"
    )


def test_the_two_session_step_kinds_are_real_step_kinds():
    from winter_agent_v2 import session_adapters

    kinds = {str(getattr(session_adapters, name, "")) for name in
             ("STEP_PRINTED_TAP", "STEP_OBSERVE_ONLY")}
    assert kinds == {"PRINTED_TAP", "OBSERVE_ONLY"}


# --------------------------------------------------------------------- the consumer that had no filter

def test_attempted_skills_drops_declared_non_skills():
    rows = [
        {"goal_id": "G1", "skill": "OPEN_MAP"},
        {"goal_id": "G1", "skill": "SAFE_STOP"},
        {"goal_id": "G1", "skill": "PRINTED_TAP"},
        {"goal_id": "G2", "skill": "SELECT_QUICK_PANEL_CITY_TAB"},
        {"goal_id": "G2", "skill": "OBSERVE_ONLY"},
    ]
    got = attempted_skills(rows)
    assert got == {"G1": {"OPEN_MAP"}}
    assert "G2" not in got, "a Goal whose only values are non-skills must not appear as having tried"


def test_attempted_skills_keeps_a_name_that_is_simply_unknown():
    """Dropping unknown names silently would hide the next vocabulary instead of exposing it."""
    got = attempted_skills([{"goal_id": "G1", "skill": "__NOT_DECLARED__"}])
    assert got == {"G1": {"__NOT_DECLARED__"}}


def test_attempted_skills_ignores_rows_without_a_goal_or_a_skill():
    got = attempted_skills([
        {"goal_id": "", "skill": "OPEN_MAP"},
        {"goal_id": "G1", "skill": ""},
        {"skill": "OPEN_MAP"},
        {"goal_id": "G1"},
    ])
    assert got == {}


def test_the_real_ledger_no_longer_puts_a_non_skill_into_an_attempted_set():
    values = _ledger_skill_values()
    if not values:
        pytest.skip(f"no ledger on disk: {LEDGER}")
    got = attempted_skills(
        {"goal_id": "G", "skill": v} for v in values if v in NON_SKILL_LEDGER_VALUES
    )
    assert got == {}
