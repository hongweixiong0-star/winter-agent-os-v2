# -*- coding: utf-8 -*-
"""The board offers a skill as 下一步动作.  It must be one the system can actually run.

V2-P0 §六 asks for the Registry 缺项 and Verifier 缺失 scenarios.  Measured against the live
snapshot on 2026-10-10 the answer was **zero of each**:

    11 distinct skills offered · all registered · all bound to a verifier

A clean measurement taken once is not a guard, though: the goal library builds these tuples from
several tables, and nothing stopped it from naming an id that no longer exists.  So the invariant is
pinned here and checked against whatever snapshot is on disk.

Two things the test deliberately does NOT do:

* it does not read ``Skill.verifier``.  The binding lives in ``LiveRuntime.VERIFIED_ATOMIC`` (whose
  values ARE the verifier callables) and is empty on most VERIFIED skills -- reading the attribute
  instead would report every one of them as unverified, which is the mass false positive the
  registry's own drift check documents.
* it does not require the skill's ``state`` to be VERIFIED.  The runtime gates dispatch on
  ``VERIFIED_ATOMIC`` membership, not on ``state`` -- measured 2026-10-10, four of the eleven
  offered skills are ``CANDIDATE`` and all four are dispatchable by design.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "learning" / "goal_state.json"


@pytest.fixture(scope="module")
def offered() -> dict[str, list[str]]:
    """``{goal_id: skill names}`` for the Goals on the board that offer at least one skill."""
    if not SNAPSHOT.is_file():
        pytest.skip(f"no live goal snapshot on disk: {SNAPSHOT}")
    try:
        payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        pytest.skip(f"goal snapshot unreadable: {exc}")
    out: dict[str, list[str]] = {}
    for goal in payload.get("goals") or []:
        if not isinstance(goal, dict):
            continue
        names = [str(n) for n in (goal.get("available_skills") or [])]
        if names:
            out[str(goal.get("goal_id"))] = names
    if not out:
        pytest.skip("snapshot carries no Goal that offers a skill")
    return out


def test_every_offered_skill_is_registered(offered):
    from winter_agent_v2.skills import v2_registry

    known = {str(getattr(s, "id", "") or "") for s in v2_registry().all()}
    offenders = [(goal, name) for goal, names in offered.items() for name in names
                 if name not in known]
    assert offenders == [], f"the board offers skills that do not exist: {offenders}"


def test_every_offered_skill_has_a_bound_verifier(offered):
    from winter_agent_v2.runtime import LiveRuntime
    from winter_agent_v2.skills import v2_registry

    known = {str(getattr(s, "id", "") or "") for s in v2_registry().all()}
    bound = set(getattr(LiveRuntime, "VERIFIED_ATOMIC", {}) or {})
    offenders = [(goal, name) for goal, names in offered.items() for name in names
                 if name in known and name not in bound]
    assert offenders == [], (
        "the board offers skills no verifier can confirm -- a step using one cannot be called "
        f"done: {offenders}"
    )


def test_the_check_would_notice_a_bogus_name(offered):
    """The guard is only worth having if it can fail.  Inject a name that cannot exist."""
    from winter_agent_v2.skills import v2_registry

    known = {str(getattr(s, "id", "") or "") for s in v2_registry().all()}
    poisoned = dict(offered)
    poisoned["__PROBE__"] = ["NOT_A_REAL_SKILL_0000"]
    offenders = [(goal, name) for goal, names in poisoned.items() for name in names
                 if name not in known]
    assert offenders == [("__PROBE__", "NOT_A_REAL_SKILL_0000")]
