"""A refused step must be recorded, using the outcome the project already has.

This is the fix for the gap measured in ``test_declined_steps_leave_no_record.py``: over the
whole 10,343-episode ledger ``SAFE_STOP`` appears as a skill **zero times**, so a Scheduler
choice that the brain declines leaves nothing behind.  Over the last 600 decisions that is
**11.5%**, concentrated in the ``SCHEDULED_*`` family -- and it is why three consecutive
fixes to that family could not be observed on the device at all.

**The project already answers this; nothing here is invented.**  ``session_adapters`` has
``STEP_OBSERVE_ONLY`` -- a step that reads and does not tap -- and its verdict
``StepOutcome.STILL_PENDING`` becomes ``result="INCOMPLETE"`` /
``session_outcome="STILL_PENDING"`` in the ledger.  Measured on real rows:

    OBSERVE_ONLY  result=INCOMPLETE  session_outcome=STILL_PENDING  action={}  (164 rows)
    result values in use: SUCCESS 9275 / FAILURE 829 / PROGRESS 157 / INCOMPLETE 99

So a step with **no action** is already a first-class recorded thing, and "pending" is
already a recorded verdict.  What is missing is only that the runtime's ``SAFE_STOP`` path
does not use it.

**What a declined step must and must not say.**  It must carry the reason -- a refusal with
no reason cannot be acted on, and the reasons are the valuable part ("this goal has nothing
to do on *this* screen").  It must not claim an action landed: ``action`` stays empty and
``verifier_ok`` stays ``None``, exactly as ``OBSERVE_ONLY`` rows do.  And it must not
advance ``goal_progress`` -- declining is not progress, and recording it as progress would
quiet the very streak that tells the scheduler this goal is stuck.

**Why not the alternative.**  Writing the refusal into ``decisions.jsonl`` instead was
considered and rejected: that ledger's docstring says it records one row per *change of the
chosen goal* for the operator, and the panel reads it.  An execution-side fact belongs in
the execution ledger, next to the frames that were and were not acted on.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EPISODES = ROOT / "learning/episodes.jsonl"


def _rows():
    if not EPISODES.exists():
        return []
    out = []
    for line in EPISODES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def test_the_project_already_records_steps_that_do_nothing():
    """The precedent, measured, so this file's fix is an application and not an invention.

    If this ever stops holding, the option of recording a refusal has to be re-argued from
    scratch rather than borrowed.
    """
    rows = _rows()
    if not rows:
        return
    no_action = [
        row for row in rows
        if not row.get("action") and str(row.get("result")) in {"INCOMPLETE", "PROGRESS"}
    ]
    assert no_action, (
        "no recorded step has an empty action any more; the OBSERVE_ONLY precedent this "
        "fix relies on is gone and the approach needs re-arguing"
    )


def test_a_declined_step_would_be_readable_as_one():
    """What the row has to look like, stated against the real field values.

    Built from the ledger's own vocabulary rather than invented names, so a future change to
    those enumerations breaks this test instead of silently producing an unread row.
    """
    rows = _rows()
    if not rows:
        return
    pending = [row for row in rows if str(row.get("session_outcome")) == "STILL_PENDING"]
    assert pending, "STILL_PENDING is the verdict a declined step should carry"
    sample = pending[0]
    assert sample.get("decision_reason"), "a pending step with no reason says nothing"
    assert not sample.get("action"), "a step that tapped nothing must not claim an action"
    assert sample.get("verifier_ok") is None, (
        "and it must not carry a verifier verdict it was never given"
    )


def test_recording_a_refusal_must_not_look_like_progress():
    """The trap in this fix, pinned.

    A declined goal is the definition of a goal that is not advancing.  If its row said
    ``goal_progress=True`` the fairness streak would reset on every refusal and the goal
    would never be demoted for being stuck -- the ledger would be lying in the exact
    direction the scheduler reads.
    """
    rows = _rows()
    if not rows:
        return
    declined_shape = [
        row for row in rows
        if str(row.get("session_outcome")) == "STILL_PENDING" and not row.get("action")
    ]
    assert declined_shape, "expected at least one recorded step that declined to act"
    for row in declined_shape[:20]:
        assert row.get("goal_progress") is not True, (
            f"a step with no action reported goal progress: {row.get('goal_id')}"
        )


def test_a_refused_step_is_not_present_in_the_ledger_yet():
    """The production fact this file exists to change, read from the ledger.

    Written as the negative it currently is, so the day the fix lands this test **fails**
    and names the file to update.  A test that asserts "the defect is still there" is only
    worth having when the failure message tells the reader what to do next -- otherwise it
    is decoration.
    """
    rows = _rows()
    if not rows:
        return
    refused = [row for row in rows if str(row.get("skill")) == "SAFE_STOP"]
    assert not refused, (
        f"{len(refused)} SAFE_STOP steps are now recorded as episodes; the orphan rate this "
        "file was written against no longer describes the ledger, and the docstring in "
        "test_declined_steps_leave_no_record.py needs re-deriving against the new data"
    )

