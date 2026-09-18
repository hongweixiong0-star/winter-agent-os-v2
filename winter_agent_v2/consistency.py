"""Four ways the window can hold two facts that cannot both be true.

Operator §9, and the point is not that these are unlikely -- three of them were measured on
2026-09-18 in a single screenshot.  The point is that a window which shows two contradictory
facts has *already* failed, and the failure is silent: a reader picks whichever one they saw
first.  So the rule is "do not quietly choose an answer", and the mechanism is a named finding.

This is a checker, not a store.  Every value it compares comes from an artifact or from a
selector that already exists -- notably ``escalation_queue.current_development_trace``, because
comparing two independently-chosen "current" traces is what produced the conflict it now
catches.  It holds no state and is deliberately pure, so each rule can be tested by giving it the
two contradictory values rather than by reproducing the situation that produced them.
"""

from __future__ import annotations

from typing import Any, Mapping

#: The finding kinds.  Named so a reader can look one up, and so a test can assert the specific
#: contradiction rather than merely that *something* was reported.
REUSE_WITHOUT_VERIFICATION = "REUSE_WITHOUT_VERIFICATION"
TRACE_DISAGREEMENT = "TRACE_DISAGREEMENT"
LOST_JOB_SHOWN_AS_VERIFYING = "LOST_JOB_SHOWN_AS_VERIFYING"
RELEASED_LEASE_SHOWN_AS_HOLDER = "RELEASED_LEASE_SHOWN_AS_HOLDER"

#: Phases that assert an examination is in progress.  A lost job may not be displayed as any of
#: them: the work is gone, and "waiting for its result" is the one thing it is not.
VERIFYING_PHASES = frozenset({
    "验证中", "等待真机验证", "LIVE_VERIFY_PENDING", "VERSION_ACTIVE", "等待校准",
})

#: The job states that mean the work will never report again.
LOST_JOB_STATES = frozenset({"JOB_LOST", "FAILED", "STOPPED"})


def state_conflicts(facts: Mapping[str, Any]) -> tuple[dict[str, str], ...]:
    """Every contradiction in one page's worth of facts.  ``()`` means consistent.

    ``facts`` is assembled by the window from what it is *about to display*, which is what makes
    this useful: a check against the artifacts would pass while the window showed something
    else.  Each finding carries its kind, the two values, and one sentence saying which of them
    is not to be trusted yet.
    """
    findings: list[dict[str, str]] = []

    verified = str(facts.get("verified_episode_id") or "")
    reuse = str(facts.get("reuse_episode_id") or "")
    if reuse and not verified:
        # Measured: the closed-loop card ticked 生产复用 while LIVE VERIFIED still read 等待.
        findings.append({
            "kind": REUSE_WITHOUT_VERIFICATION,
            "values": f"reuse_episode={reuse}, verified_episode=(空)",
            "note": ("生产复用已记录，但没有 LIVE VERIFIED 的 episode —— 复用不能早于验证。"
                     "两个值都显示，不替读者挑一个。"),
        })

    closure_trace = str(facts.get("closure_trace_id") or "")
    development_trace = str(facts.get("development_trace_id") or "")
    if closure_trace and development_trace and closure_trace != development_trace:
        # Measured: two regions named different capabilities, both calling themselves current.
        findings.append({
            "kind": TRACE_DISAGREEMENT,
            "values": f"闭环卡={closure_trace}, 开发页={development_trace}",
            "note": ("同一页两个区域对「当前 trace」给了两个答案。两者都列出："
                     "在它们一致之前，页面上的任何「当前」都不可信。"),
        })

    job_state = str(facts.get("job_state") or "").upper()
    phase = str(facts.get("displayed_phase") or "")
    if job_state in LOST_JOB_STATES and phase in VERIFYING_PHASES:
        findings.append({
            "kind": LOST_JOB_SHOWN_AS_VERIFYING,
            "values": f"job_state={job_state}, 显示阶段={phase}",
            "note": ("Job 已不会再有结果，页面却显示它在验证中。"
                     "Job 传输状态与验证生命周期是两件事，必须分别显示。"),
        })

    released_at = str(facts.get("lease_released_at") or "")
    holder = str(facts.get("lease_current_holder") or "")
    displayed = str(facts.get("lease_displayed_holder") or "")
    if released_at and displayed and not holder and displayed:
        # Measured: the device-ownership row showed a *released* lease as the current owner.
        findings.append({
            "kind": RELEASED_LEASE_SHOWN_AS_HOLDER,
            "values": f"最后一次已释放于 {released_at}，当前无 holder，页面显示 {displayed}",
            "note": ("已释放的租约是历史，不是当前所有者。当前无 holder 时应当这么说，"
                     "历史放「最近一次校准租约」。"),
        })

    return tuple(findings)


def render_conflicts(findings: tuple[dict[str, str], ...] | list[dict[str, str]]) -> str:
    """One line per finding, or an explicit "nothing contradictory" -- never a blank."""
    if not findings:
        return "无 STATE_CONFLICT（页面上没有互相矛盾的事实）"
    return " ｜ ".join(f"STATE_CONFLICT·{f['kind']}：{f['values']}" for f in findings)


__all__ = [
    "REUSE_WITHOUT_VERIFICATION", "TRACE_DISAGREEMENT", "LOST_JOB_SHOWN_AS_VERIFYING",
    "RELEASED_LEASE_SHOWN_AS_HOLDER", "VERIFYING_PHASES", "LOST_JOB_STATES",
    "state_conflicts", "render_conflicts",
]
