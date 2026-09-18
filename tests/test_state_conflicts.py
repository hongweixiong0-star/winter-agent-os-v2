"""Four contradictions the window must name instead of resolving quietly.

Operator §9.  Three of the four were measured on 2026-09-18 in a single screenshot, which is why
the rule is not "these are unlikely" but "a page holding two contradictory facts has already
failed, and the failure is silent because a reader picks whichever one they saw first".

Each rule is tested by handing it the two contradictory values rather than by reproducing the
situation that produced them -- the point of keeping the checker pure.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.consistency import (  # noqa: E402
    LOST_JOB_SHOWN_AS_VERIFYING, RELEASED_LEASE_SHOWN_AS_HOLDER, REUSE_WITHOUT_VERIFICATION,
    TRACE_DISAGREEMENT, render_conflicts, state_conflicts,
)


def _kinds(facts: dict) -> set[str]:
    return {f["kind"] for f in state_conflicts(facts)}


def test_a_consistent_page_reports_nothing():
    """And says so in words: a blank cell reads as "not checked"."""
    assert state_conflicts({}) == ()
    assert "无 STATE_CONFLICT" in render_conflicts(())
    assert "无 STATE_CONFLICT" in render_conflicts(state_conflicts({
        "closure_trace_id": "A|F|S", "development_trace_id": "A|F|S",
        "verified_episode_id": "ep-v", "reuse_episode_id": "ep-r",
        "job_state": "WORKING", "displayed_phase": "开发中",
    }))


def test_reuse_before_verification_is_a_conflict():
    """The measured one: 生产复用 ✓ beside LIVE VERIFIED 等待."""
    assert _kinds({"reuse_episode_id": "ep-r", "verified_episode_id": ""}) == {
        REUSE_WITHOUT_VERIFICATION}


def test_reuse_after_verification_is_not_a_conflict():
    """The legitimate order must stay quiet, or the check becomes noise."""
    assert _kinds({"reuse_episode_id": "ep-r", "verified_episode_id": "ep-v"}) == set()


def test_two_current_traces_is_a_conflict():
    """The measured one: two regions, two capabilities, both calling themselves current."""
    assert _kinds({"closure_trace_id": "A|F|S", "development_trace_id": "B|F|S"}) == {
        TRACE_DISAGREEMENT}
    assert _kinds({"closure_trace_id": "A|F|S", "development_trace_id": "A|F|S"}) == set()


def test_one_side_missing_is_not_a_disagreement():
    """With nothing current there is nothing to disagree with -- that is §7's None, not a fault."""
    assert _kinds({"closure_trace_id": "A|F|S", "development_trace_id": ""}) == set()


def test_a_lost_job_displayed_as_verifying_is_a_conflict():
    """The measured one: 状态=验证中 beside Job 状态=DONE · 网关 JOB_LOST."""
    for phase in ("验证中", "等待真机验证", "VERSION_ACTIVE", "等待校准"):
        assert _kinds({"job_state": "JOB_LOST", "displayed_phase": phase}) == {
            LOST_JOB_SHOWN_AS_VERIFYING}, phase
    # A lost job shown as lost is honest, and must not be flagged.
    assert _kinds({"job_state": "JOB_LOST", "displayed_phase": "已丢失"}) == set()


def test_a_released_lease_shown_as_the_holder_is_a_conflict():
    """The measured one: the device row showed a lease released hours earlier."""
    assert _kinds({
        "lease_released_at": "2026-09-18T18:05:03+00:00",
        "lease_current_holder": "",
        "lease_displayed_holder": "V2控制中 · DEVELOPMENT_VALIDATION released",
    }) == {RELEASED_LEASE_SHOWN_AS_HOLDER}
    # While a lease is actually held, showing it is correct.
    assert _kinds({
        "lease_released_at": "2026-09-18T18:05:03+00:00",
        "lease_current_holder": "OWNER_DEVELOPMENT_VALIDATION",
        "lease_displayed_holder": "OWNER_DEVELOPMENT_VALIDATION",
    }) == set()


def test_every_finding_carries_both_values_and_an_explanation():
    """The rule is "do not quietly choose": each finding has to show what disagreed and why."""
    findings = state_conflicts({
        "reuse_episode_id": "ep-r", "verified_episode_id": "",
        "closure_trace_id": "A|F|S", "development_trace_id": "B|F|S",
        "job_state": "JOB_LOST", "displayed_phase": "验证中",
        "lease_released_at": "2026-09-18T18:05", "lease_current_holder": "",
        "lease_displayed_holder": "released",
    })
    assert len(findings) == 4
    for finding in findings:
        assert finding["kind"] and finding["values"] and finding["note"], finding
    rendered = render_conflicts(findings)
    for finding in findings:
        assert finding["kind"] in rendered


def test_the_page_shows_the_check_rather_than_a_default():
    """Structural: the cell must start as 未检查 and be filled by the refresh."""
    source = (ROOT / "tools/control_panel.py").read_text(encoding="utf-8")
    assert '"consistency": "未检查（等待首次刷新）"' in source, (
        "a page that has not compared anything must not claim consistency"
    )
    assert 'self.values["consistency"].set(render_conflicts(findings))' in source
    assert "state_conflicts({" in source
