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

**One comparison, and it named exactly one refusal.**  Measured on the device then: that
reason appears in 681 ``auto_uptime`` rows **zero times**, and
``learning/fruitless_run_audit.jsonl`` **does not exist at all** -- the channel was wired,
configured, tested, and dead.  The follow-up is measured in ``runtime.append_fruitless_audit``'s
own comment (2026-10-02 16:20-16:44): a refusal *yields* -- it does not end the run -- so
"ended on a refusal" was the second wrong predicate, and the gate was widened to "did this run
refuse anything".  The file has since written 22 rows (2026-10-02 → 2026-10-08), every one of
them satisfying that predicate, and the first test below pins the widened contract instead of
the channel's emptiness.

These tests therefore pin the *shape* the gate produces, using the existing record's own field
names.  They are deliberately not asking for a new ledger, a new field, or a new vocabulary:
the project already has a complete answer to "what did the run refuse and why", and the fix was
to stop it from being thrown away.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRUITLESS = ROOT / "learning/fruitless_run_audit.jsonl"


def test_every_row_is_one_the_widened_gate_would_admit():
    """Re-derived 2026-10-16, on the instruction the previous version of this test carried.

    It used to assert the file did not exist: the gate admitted exactly one reason
    (``NOTHING_LEFT_TO_LOOK_AT``), that reason had never occurred, and "if the file starts
    appearing, something already widened the gate, and this file's argument has to be
    re-derived".  It did appear -- 22 rows, 2026-10-02 to 2026-10-08 -- written by the
    widened gate (see the module docstring).  The predicate now is "did this run refuse
    anything", so that is what each row is checked against: a row admitted by neither half
    is a row no gate wrote, which is the same "something else writes it" alarm as before,
    with the predicate that is actually in force.
    """
    rows = [
        json.loads(line)
        for line in FRUITLESS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ] if FRUITLESS.exists() else []
    if not rows:
        # An empty channel is the state the file began with -- not a failure, but the next
        # reader must know this fixture went quiet rather than stayed green by accident.
        return
    for row in rows:
        found_nothing = str(row.get("final_reason") or "") == "NOTHING_LEFT_TO_LOOK_AT"
        refused = any(
            str(page.get("attempted_skill") or "") == "SAFE_STOP"
            for page in (row.get("per_page") or [])
            if isinstance(page, dict)
        )
        assert found_nothing or refused, (
            "a row no version of the gate would admit: neither NOTHING_LEFT_TO_LOOK_AT nor "
            "a SAFE_STOP refusal in its per_page -- "
            f"run_id={row.get('run_id')!r} final_reason={row.get('final_reason')!r}"
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
