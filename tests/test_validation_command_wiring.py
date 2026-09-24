"""The GUI's validation command must carry the whole context (§2/§3 wiring).

Operator §2's correction: §1 (acquiring the lease) already exists and is wired -- what was
missing is that `_run_validation_worker` still built its command with only
`--goal/--max-actions/--capture-dir/--serial`, so the five fields added in 2e2ae72 never
reached the runner.  An examination whose episode cannot be attributed to a trace or a version
runs and proves nothing.

These tests are about the command line, which is why they need no device: `validation_command`
is a pure function, and having exactly one place that writes those fields is what makes it
possible to assert that none can be omitted.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import control_panel as cp  # noqa: E402

RECORD = {
    "key": "SPEND_STAMINA_ON_BEAST|NO_GOAL_PROGRESS|SCAN_MAP_FOR_BEAST",
    "job_id": "5b525aa4",
    "capability": "SPEND_STAMINA_ON_BEAST",
    "goal": "BEAST_HUNT",
    "after_version": "b" * 40,
    "state": "LIVE_VERIFY_PENDING",
}


def _pair(command: list[str], flag: str) -> str:
    assert flag in command, f"{flag} missing from the validation command"
    return command[command.index(flag) + 1]


def test_the_command_carries_all_five_validation_fields():
    """§2's exact ask: mode, trace, job, capability, expected version."""
    command = cp.validation_command(RECORD, capture_dir="cap", serial="serial-1")
    assert _pair(command, "--execution-mode") == cp.VALIDATION_MODE == "DEVELOPMENT_VALIDATION"
    assert _pair(command, "--trace-id") == RECORD["key"]
    assert _pair(command, "--job-id") == "5b525aa4"
    assert _pair(command, "--capability") == "SPEND_STAMINA_ON_BEAST"
    assert _pair(command, "--expected-after-version") == "b" * 40
    assert _pair(command, "--lease-id") == ""


def test_validation_command_carries_the_exact_lease_identity():
    command = cp.validation_command(RECORD, capture_dir="cap", serial="s", lease_id="lease-uuid")
    assert _pair(command, "--lease-id") == "lease-uuid"


def test_the_run_still_goes_through_the_one_executor():
    """No second executor: same runner, same goal, still bounded."""
    command = cp.validation_command(RECORD, capture_dir="cap", serial="s")
    assert command[1] == str(cp.RUNTIME_PATH)
    assert _pair(command, "--goal") == "BEAST_HUNT"
    assert _pair(command, "--max-actions") == str(cp.VALIDATION_MAX_ACTIONS)
    assert _pair(command, "--serial") == "s"
    assert _pair(command, "--capture-dir") == "cap"


def test_the_examination_does_not_open_its_own_escalation():
    """Failing the exam must not file a second development job: the queue owns that."""
    assert "--no-escalate" in cp.validation_command(RECORD, capture_dir="c", serial="s")


def test_a_missing_version_is_sent_as_empty_rather_than_left_out():
    """An absent version must be visible on the command line, not implied by a missing flag.

    run_live's gate does nothing when the expected version is empty, so a record with no
    measured after_version cannot silently pass the version check -- and the empty string in
    the command is the evidence that nothing was claimed.
    """
    command = cp.validation_command(
        {**RECORD, "after_version": ""}, capture_dir="c", serial="s")
    assert _pair(command, "--expected-after-version") == ""
    assert _pair(command, "--trace-id") == RECORD["key"], "the trace is still named"


def test_the_worker_builds_its_command_from_the_record_not_only_the_goal():
    """The gap itself: the worker must resolve the record and use the shared builder.

    Structural, because exercising the worker needs a device.  What is asserted is that the
    old hand-built command -- goal, max-actions, capture-dir, serial and nothing else -- is
    gone, and that a record that cannot be resolved stops the run instead of guessing.
    """
    source = (Path(cp.__file__)).read_text(encoding="utf-8")
    worker = source[source.find("def _run_validation_worker"):]
    worker = worker[:worker.find("\n    def ", 10)]
    assert "validation_command(" in worker, "the worker must use the one builder"
    assert "self._pending_validation_record(key)" in worker, (
        "the worker must read the whole record, not just the goal"
    )
    assert '"--goal", goal,' not in worker, "the old hand-built command must be gone"
    assert "VALIDATION_CONTEXT_MISSING" in worker, (
        "an unresolvable record must stop the run rather than fall back to any pending record"
    )


def test_a_goal_id_is_translated_into_a_route_the_runner_accepts():
    """Measured 2026-09-21: this is not a hypothetical.

    The ledger stores a goal **id**; ``run_live --goal`` accepts a route **domain**.  Passing
    the id through unchanged made every calibration die inside argparse before the device was
    touched --

        run_live.py: error: argument --goal: invalid choice: 'KEEP_TRAINING_PRODUCTIVE'

    -- while the lease had already been taken, and the panel narrated the corpse as
    "验证运行结束（EXIT_2），停止原因 未知".  So the two vocabularies are held together here.
    """
    command = cp.validation_command(
        {**RECORD, "goal": "KEEP_TRAINING_PRODUCTIVE"}, capture_dir="c", serial="s")
    assert _pair(command, "--goal") == "TRAIN"
    for camp_goal in ("SHIELD_CAMP_TRAINING", "LANCER_CAMP_TRAINING", "MARKSMAN_CAMP_TRAINING"):
        camp = cp.validation_command({**RECORD, "goal": camp_goal}, capture_dir="c", serial="s")
        assert _pair(camp, "--goal") == "TRAIN", f"{camp_goal} shares the training route"


def test_every_route_the_ledger_can_name_is_one_the_runner_accepts():
    """The two vocabularies cannot drift: this is the assertion that keeps them joined."""
    from winter_agent_v2.goal_library import GOAL_ROUTES, ROUTE_DOMAINS

    for goal_id, route in GOAL_ROUTES.items():
        assert route in ROUTE_DOMAINS, (
            f"{goal_id} routes to {route!r}, which run_live --goal would reject"
        )


def test_a_goal_with_no_route_stops_the_run_instead_of_aiming_at_nothing():
    """A calibration aimed at a nonexistent route would hold the device and prove nothing."""
    with pytest.raises(ValueError):
        cp.validation_command(
            {**RECORD, "goal": "A_GOAL_THAT_HAS_NO_ROUTE"}, capture_dir="c", serial="s")
