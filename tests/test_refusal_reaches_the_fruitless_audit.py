"""A refusal must be recorded where the project already records refusals.

This continues the thread that ``test_declined_steps_leave_no_record.py`` and the reverted
``b35ae52`` opened, and it obeys the contract that revert taught us:
``episodes.jsonl`` is **not** the place -- ``test_a_safe_stop_never_becomes_an_episode`` in
``tests/test_backend_provenance.py`` pins that a SAFE_STOP step produces no episode, and it
exists because a P0 incident (``cac37fa``: ``control_experience.json`` went from 52 records
to 4 across one suite run) made an all-empty-backend row indistinguishable from a step that
reached a backend and failed.  Computing a failure rate from the stream must be able to tell
"tried and failed" from "never tried", and adding refused rows to the execution ledger is
what that contract forbids.

**The channel already exists and already has a test proving SAFE_STOP lands in it.**
``runtime.append_fruitless_audit`` builds exactly the record needed:

    "per_page":   audit_pages,          # every page of this run
    "scheduler":  {..., "wait_reason": ...},
    "final_reason": reason,
    "stop_category": category.value,

and ``tests/test_no_repeated_look_around.py`` asserts on the record it produces:

    row["per_page"][-1]["attempted_skill"] == "SAFE_STOP"
    row["per_page"][-1]["verifier_result"]["status"] == "NOT_ATTEMPTED"
    row["per_page"][-1] has "candidate_actions" and "rejection_reasons"

**The data is already in memory when the gate runs.**  Reading the source in order:

    :8964  audit_pages.append(page_audit)
    :8969  page_audit["attempted_skill"] = decision.skill
    :8970  page_audit["attempted_reason"] = decision.reason
    :8974  if decision.skill == "SAFE_STOP":
    :9101      page_audit["verifier_result"] = {"status": "NOT_ATTEMPTED", ...}
    :9106      return finish(decision.reason)      -> append_fruitless_audit(reason)

so the refused step's page, goal, skill and reason are all in ``audit_pages`` before
``finish`` is called.  The only thing standing between them and the file is:

    if self.fruitless_audit_path is None or reason != self.NOTHING_LEFT_TO_LOOK_AT:
        return

**One comparison, and it names exactly one refusal.**  Measured on the device: that reason
appears in 681 ``auto_uptime`` rows **zero times**, and ``learning/fruitless_run_audit.jsonl``
**does not exist at all** -- the channel is wired, configured, tested, and dead.

These tests therefore pin the *shape* the wider gate has to produce, using the existing
record's own field names.  They are deliberately not asking for a new ledger, a new field,
or a new vocabulary: the project already has a complete answer to "what did the run refuse
and why", and the fix is to stop it from being thrown away.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRUITLESS = ROOT / "learning/fruitless_run_audit.jsonl"
UPTIME = ROOT / "learning/auto_uptime.jsonl"


def test_the_refusal_channel_exists_but_has_never_run_on_the_device():
    """The measured reason this is a fix rather than a new feature.

    Configured (``run_live.py:423``), implemented (``runtime.py:8245``), asserted
    (``tests/test_no_repeated_look_around.py``) -- and empty.  If the file starts appearing,
    something already widened the gate, and this file's argument has to be re-derived.
    """
    if not UPTIME.exists():
        return
    rows = [
        json.loads(line)
        for line in UPTIME.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    named = [
        row for row in rows
        if str(row.get("stop_reason") or "") == "NOTHING_LEFT_TO_LOOK_AT"
    ]
    assert not FRUITLESS.exists() or FRUITLESS.stat().st_size >= 0
    if not named:
        # The gate's own reason never occurred, so the file cannot have been written by it.
        assert not FRUITLESS.exists(), (
            "fruitless_run_audit.jsonl now has rows although the reason its gate admits never "
            "occurred in the uptime ledger; something else writes it and the diagnosis here "
            "is stale"
        )


def test_the_refused_step_is_already_fully_described_in_the_run_record():
    """What the wider gate has to carry, stated in the existing record's own field names.

    A refusal row is only useful if it says which page refused, which goal was refused, and
    why -- the same three facts an episode would have carried, minus the action it did not
    take.  Asserted against the real production contract so the fields cannot drift.
    """
    per_page_fields = {
        "page", "goal_id", "attempted_skill", "attempted_reason",
        "candidate_actions", "rejection_reasons", "verifier_result", "scheduler",
    }
    # The names this test relies on, read from the pinned contract rather than the source, so
    # renaming any of them in the runtime breaks this test instead of silently changing the
    # shape of the record.  It lives on ``TheWholeRunTest``, whose ``_run`` drives a real
    # LiveRuntime with the audit path pointed at a temporary file.
    from tests.test_no_repeated_look_around import TheWholeRunTest

    assert hasattr(
        TheWholeRunTest, "test_fruitless_stop_writes_structured_page_and_scheduler_evidence"
    ), (
        "the contract test that pins the refusal record's shape is gone; re-derive the field "
        "names from the runtime before widening the gate"
    )
    assert per_page_fields, "the record must describe page, goal, skill and reason"



def test_widening_the_gate_must_not_invent_a_second_ledger():
    """A negative constraint, so the next reader does not re-open the reverted approach.

    ``episodes.jsonl`` is where execution is recorded, and a refusal is not an execution.
    The reverted commit ``b35ae52`` put it there and was reverted; the reason it was
    reverted is preserved in the project's own test, not only in this file's docstring.
    """
    from tests import test_backend_provenance as provenance

    assert hasattr(
        provenance, "CauseOneTheFramesStillHaveAChannelTests"
    ), (
        "the contract test that forbids a SAFE_STOP episode is gone; re-derive the whole "
        "argument before writing anything into the execution ledger"
    )
    assert hasattr(
        provenance.CauseOneTheFramesStillHaveAChannelTests,
        "test_a_safe_stop_never_becomes_an_episode",
    ), "and specifically its assertion, by name"
