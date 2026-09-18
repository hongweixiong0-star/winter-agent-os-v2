"""What one Development Validation cycle is allowed to have proved.

Operator §5-§7, and the shape of the ladder is the point: four of the six outcomes are
*refusals*, and each names a different reason.  An examination whose episode matches on four of
five axes is not "mostly verified" -- it is unusable, and collapsing the cases would let a
launch, a screenshot, a SAFE_STOP or a navigation succeed quietly become proof.

The rule the operator restated most often: a production episode is evidence for a different
question and may never be read as the examination's result.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.escalation_queue import (  # noqa: E402
    LIVE_TRIED, LIVE_VERIFIED, VALIDATION_CONTEXT_MISMATCH, VALIDATION_NO_PROOF,
    VALIDATION_VERSION_MISMATCH, validation_settlement,
)

TRACE = "SPEND_STAMINA_ON_BEAST|NO_GOAL_PROGRESS|SCAN_MAP_FOR_BEAST"
JOB = "5b525aa4"
CAPABILITY = "SPEND_STAMINA_ON_BEAST"
SKILL = "SCAN_MAP_FOR_BEAST"
AFTER = "b" * 40


def _episode(**over) -> dict:
    row = {
        "episode_id": "ep-val-1",
        "execution_mode": "DEVELOPMENT_VALIDATION",
        "trace_id": TRACE,
        "job_id": JOB,
        "capability": CAPABILITY,
        "expected_after_version": AFTER,
        "repo_revision": AFTER,
        "skill": SKILL,
        "verifier_ok": True,
        "goal_progress": True,
        "before_screenshot": "dataset/raw/a.png",
        "after_screenshot": "dataset/raw/b.png",
    }
    row.update(over)
    return row


def _settle(rows, **over):
    kwargs = dict(trace_key=TRACE, job_id=JOB, capability=CAPABILITY, skill=SKILL,
                  after_version=AFTER, failure_type="NO_GOAL_PROGRESS")
    kwargs.update(over)
    return validation_settlement(episodes=rows, **kwargs)


def test_a_launch_or_a_safe_stop_is_not_a_try():
    """Counterexample 5: only a DEVELOPMENT_VALIDATION episode counts at all."""
    outcome, why, _ = _settle([])
    assert outcome == VALIDATION_NO_PROOF
    assert "SAFE_STOP" in why


def test_a_production_episode_cannot_stand_in_for_the_examination():
    """§8's rule, at this layer: production evidence answers a different question."""
    outcome, _, _ = _settle([_episode(execution_mode="PRODUCTION")])
    assert outcome == VALIDATION_NO_PROOF


def test_an_episode_from_another_trace_is_not_this_trace_s_attempt():
    """Counterexample 3's shape: named trace, so only that trace may be validated."""
    outcome, why, _ = _settle([_episode(trace_id="OTHER|F|S")])
    assert outcome == VALIDATION_CONTEXT_MISMATCH
    assert "OTHER|F|S" in why


def test_a_matching_trace_with_the_wrong_job_or_capability_is_refused():
    outcome, why, _ = _settle([_episode(job_id="someone-else")])
    assert outcome == VALIDATION_CONTEXT_MISMATCH
    outcome, _, _ = _settle([_episode(capability="SOMETHING_ELSE")])
    assert outcome == VALIDATION_CONTEXT_MISMATCH


def test_running_the_wrong_version_is_a_mismatch_and_never_a_pass():
    """§3/§6: a real attempt on the wrong code proves something about the wrong code."""
    outcome, why, _ = _settle([_episode(repo_revision="c" * 40)])
    assert outcome == VALIDATION_VERSION_MISMATCH
    assert AFTER[:8] in why
    # And the version the cycle *claimed* must match too, or the claim itself is untrustworthy.
    outcome, _, _ = _settle([_episode(expected_after_version="c" * 40)])
    assert outcome == VALIDATION_VERSION_MISMATCH


def test_navigating_without_executing_the_target_skill_is_not_a_try():
    outcome, why, _ = _settle([_episode(skill="OPEN_MAP")])
    assert outcome == VALIDATION_NO_PROOF
    assert SKILL in why


def test_the_target_ran_but_the_verifier_failed_is_LIVE_TRIED_only():
    """Counterexample 6."""
    outcome, why, _ = _settle([_episode(verifier_ok=False)])
    assert outcome == LIVE_TRIED
    assert outcome != LIVE_VERIFIED
    assert "Verifier 未通过" in why


def test_missing_evidence_frames_are_not_a_verification():
    outcome, _, _ = _settle([_episode(after_screenshot="")])
    assert outcome == LIVE_TRIED


def test_action_success_without_goal_progress_is_not_a_verified_goal_capability():
    """Counterexample 7: for a defect whose proof *is* goal progress."""
    outcome, why, _ = _settle([_episode(goal_progress=False)])
    assert outcome == LIVE_TRIED
    assert "Goal Progress" in why


def test_the_same_episode_verifies_when_the_defect_does_not_require_goal_progress():
    """The requirement is per-defect, not blanket: a UI-unknown defect has no goal to move."""
    outcome, _, _ = _settle([_episode(goal_progress=False)], failure_type="UNKNOWN_UI")
    assert outcome == LIVE_VERIFIED


def test_everything_matching_is_a_verification(tmp_path):
    outcome, why, episode = _settle([_episode()])
    assert outcome == LIVE_VERIFIED
    assert episode["episode_id"] == "ep-val-1"
    assert AFTER[:12] in why


def test_the_latest_matching_episode_is_the_one_credited():
    """A bounded cycle can produce several steps; the last one that ran the target decides."""
    rows = [_episode(episode_id="ep-1"),
            _episode(episode_id="ep-2", verifier_ok=False)]
    outcome, _, episode = _settle(rows)
    assert episode["episode_id"] == "ep-2"
    assert outcome == LIVE_TRIED, "the last attempt failed, so the examination did not pass"
