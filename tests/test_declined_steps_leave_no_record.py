"""A decision that declines to act is still a decision, and it must leave a trace.

Measured 2026-10-03 on the live ledgers, and this is the reason three consecutive fixes
could not be observed at all:

    15:59:30  chose DISCOVER_QUICK_PANEL_TASKS   -> episode OPEN_QUICK_PANEL   15:59:35
    15:59:38  chose SCHEDULED_EXCLUSIVE_GEAR_FORGE  -> (no episode)
    15:59:41  chose SCHEDULED_UNDERGROUND_EXPLORATION -> (no episode)
    15:59:45  chose SCHEDULED_BROTHERS_IN_ARMS       -> (no episode)

Three Scheduler choices, three of them in a row, and **nothing anywhere says they were
declined**.  Over the last 600 decisions the rate is **69/600 = 11.5%**, and the orphans are
concentrated in exactly the goal family that most needs watching: SCHEDULED_*.

**Why there is no record.**  ``RuleBrain`` answers ``SAFE_STOP`` when a goal has nothing to
do on the current screen -- the training queue is busy, the beast is not visible, this
frame draws no activity entry.  ``runtime`` handles that at ``:8975`` and ends the step with
``self._runtime(...); return finish(decision.reason)``.  ``_runtime`` records the agent
state; it is not ``_record_episode``.  Measured over the whole 10,343-episode ledger:
``SAFE_STOP`` appears as a skill **zero times**, and ``WAIT`` zero times.

That silence is deliberate in the original case, and the comment at ``:9040`` is explicit
that a refusal "ends the TASK, not the CYCLE".  The earlier defect was that it ended the
*cycle*; that was fixed.  What was never addressed is that a refusal leaves no row at all,
so the two ledgers cannot be reconciled: ``decisions.jsonl`` says the goal won,
``episodes.jsonl`` has nothing, and no field anywhere says "declined".

**Why it matters more now.**  The EVENT-route branch added in bb2dbb4 answers exactly
``SAFE_STOP`` on the commonest page it can meet -- an activity goal selected in the city
where the client did not draw the 常规活动 entry.  So a branch whose whole purpose is to
send those goals somewhere useful produces, on that path, a decision that is correct and
completely invisible.  A goal that is selected every few steps, declines every time, and
is never written down is indistinguishable from a goal that is never considered -- except
that the fairness ledger counts every one of those selections.

What this pins, and what it refuses to pin:

* the shape of the gap, measured rather than described;
* that ``SAFE_STOP`` is a real answer with reasons worth keeping -- the fix is **not** to
  make it click something;
* that a declined step must be attributable afterwards, which is the property the ledger
  currently lacks.

It deliberately does **not** prescribe the fix, because there are two honest ones (record a
non-executed episode, or record the refusal in the decision ledger) and choosing between
them is a contract question about what an episode is allowed to mean.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EPISODES = ROOT / "learning/episodes.jsonl"
DECISIONS = ROOT / "learning/decisions.jsonl"


def _rows(path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def test_safe_stop_is_never_an_episode_in_the_production_ledger():
    """The structural fact: a refusal is not one of the recorded steps.

    This is not a complaint, it is the measurement the next step needs.  If a future change
    starts recording it, this test is the one that should fail and say why -- because the
    rest of the argument here depends on the silence being real and continuing.
    """
    episodes = _rows(EPISODES)
    if not episodes:
        return  # no production ledger on this machine; nothing to measure
    skills = {str(row.get("skill")) for row in episodes}
    assert "SAFE_STOP" not in skills, (
        "SAFE_STOP now appears as an episode skill; the orphan-rate argument in this file's "
        "docstring has to be re-derived against the new ledger"
    )


def test_the_measured_orphan_rate_is_the_size_of_the_gap():
    """11.5% over the last 600 decisions, measured the way the docstring describes.

    Written as a range rather than an exact figure on purpose: this is a live ledger that
    keeps growing, so pinning the precise number would make the test rot.  What must not
    drift is the order of magnitude -- if orphan decisions become rare, something changed
    and the reasoning here needs revisiting.
    """
    episodes = _rows(EPISODES)
    decisions = _rows(DECISIONS)
    if not episodes or not decisions:
        return
    stamps = [str(row.get("recorded_at") or "") for row in episodes]
    goals = [str(row.get("goal_id") or "") for row in episodes]

    orphans = 0
    for row in decisions[-600:]:
        at = str(row.get("at") or "")
        chosen = str(row.get("chosen") or "")
        start = next((i for i, t in enumerate(stamps) if t >= at), len(stamps))
        if chosen not in goals[start:start + 6]:
            orphans += 1
    rate = orphans / 600.0
    assert 0.03 < rate < 0.35, (
        f"orphan decision rate is {rate:.1%} over the last 600 decisions; the argument in "
        "this file's docstring assumes a double-digit rate concentrated in one family"
    )


def test_a_refusal_still_has_a_reason_worth_keeping():
    """The fix must not turn ``SAFE_STOP`` into a click.

    Its reasons are statements about one goal on one screen -- the queue is busy, the entry
    is not drawn, the target is not visible -- and that is the information worth recording.
    A record of *what was declined and why* is what the ledger is missing; a record that
    implies an action happened would be worse than the silence.
    """
    from winter_agent_v2.brain import RuleBrain
    from winter_agent_v2.models import Page, WorldState
    from winter_agent_v2.skills import v2_registry

    brain = RuleBrain()
    brain.current_goal = "EVENT"
    brain.goal_id = "SCHEDULED_BROTHERS_IN_ARMS"
    decision = brain.decide(WorldState(page=Page.HOME, confidence=0.99), registry=v2_registry())
    assert decision.skill == "SAFE_STOP"
    assert decision.reason, "a refusal with no reason cannot be recorded, attributed, or acted on"
    assert decision.reason != "first_ready_p0_skill", (
        "and it must not be the generic fallback reason, or the record says nothing"
    )
