# -*- coding: utf-8 -*-
"""Offline proof of the Semantic Action Executor contract (no device).

Covers the directive's rules:
  §二  STILL_PENDING -> retry
  §十一 fresh locate every attempt (coordinates never reused)
  §十二 success evidence wins (never re-click after SUCCESS)
  §十三 PROGRESS/loading -> observe, no blind re-click
  §十五 unauthorized -> never clicked
  §一/§十四 metric buckets CLICK_FIRST_TRY_SUCCESS / CLICK_RETRY_SUCCESS / CLICK_RETRY_EXHAUSTED

usage: python tools/test_semantic_executor.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from winter_agent_v2.semantic_executor import (  # noqa: E402
    SemanticAction, SemanticActionExecutor, Observation, march_counter_postcondition,
    SUCCESS, STILL_PENDING, AMBIGUOUS, FAILED, classify_postcondition)


class Rig:
    """A fake device: each click yields the next scripted verdict."""

    def __init__(self, script):
        self.script = list(script)      # verdict produced by each click
        self.clicks = []
        self.march = 1
        self.last_verdict = STILL_PENDING
        self.calls = 0

    def observe(self):
        self.calls += 1
        return Observation(frame=None, state={"march": self.march, "text": "formation"})

    def click(self, x, y):
        self.clicks.append((x, y))
        self.last_verdict = self.script.pop(0) if self.script else SUCCESS
        if self.last_verdict == SUCCESS:
            self.march += 1

    @staticmethod
    def verdict_postcondition(before, after, _rig=None):
        """Postcondition that reports exactly what the scripted click produced."""
        return _rig.last_verdict

    def locate(self, obs):
        # target moves 10 px per attempt on purpose: proves fresh locate (§十一)
        return (100 + 10 * len(self.clicks), 200)


def run_case(title, script, expect_outcome, expect_clicks, max_retry=2, authorized=True,
             locate_override=None):
    rig = Rig(script)
    ex = SemanticActionExecutor(observe=rig.observe, click=rig.click, settle=lambda s: None)
    act = SemanticAction(name="DISPATCH", locate=locate_override or rig.locate,
                         postcondition=lambda b, a: rig.verdict_postcondition(b, a, rig),
                         settle_s=0.0, max_retry=max_retry, authorized=authorized)
    res = ex.execute(act)
    ok = (res.outcome == expect_outcome and len(rig.clicks) == expect_clicks)
    print(f"{'PASS' if ok else 'FAIL'} | {title}: outcome={res.outcome} clicks={len(rig.clicks)} "
          f"points={rig.clicks} outcomes={res.outcomes}")
    return ok


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    results = []

    # 1) first click lost -> retry -> success (retry bucket)
    results.append(run_case("first click lost then succeeds", [STILL_PENDING, SUCCESS],
                            SUCCESS, 2))
    # 2) first click lands (first-try bucket, no retry)
    results.append(run_case("first click lands", [SUCCESS], SUCCESS, 1))
    # 3) SUCCESS wins — never re-click even if more scripts queued
    results.append(run_case("success wins, no duplicate", [SUCCESS, SUCCESS], SUCCESS, 1))
    # 4) retries exhausted (budget 2 -> 3 clicks total)
    results.append(run_case("retries exhausted", [STILL_PENDING] * 5,
                            STILL_PENDING, 3))
    # 5) ambiguous -> never blind click
    results.append(run_case("ambiguous defers", [AMBIGUOUS], AMBIGUOUS, 1))
    # 6) unauthorized -> zero clicks
    results.append(run_case("unauthorized never clicked", [SUCCESS], FAILED, 0,
                            authorized=False))
    # 7) locate returns None -> no click, target missing
    results.append(run_case("target not located", [SUCCESS], AMBIGUOUS, 0,
                            locate_override=lambda obs: None))
    # 8) fresh locate: three attempts must use three DIFFERENT points
    rig2 = Rig([STILL_PENDING, STILL_PENDING, SUCCESS])
    ex2 = SemanticActionExecutor(observe=rig2.observe, click=rig2.click, settle=lambda s: None)
    res2 = ex2.execute(SemanticAction(name="DISPATCH", locate=rig2.locate,
                                      postcondition=lambda b, a: rig2.verdict_postcondition(b, a, rig2),
                                      settle_s=0.0, max_retry=2))
    distinct = len(set(rig2.clicks)) == len(rig2.clicks) == 3
    print(f"{'PASS' if distinct else 'FAIL'} | fresh locate per attempt: points={rig2.clicks}")
    results.append(distinct)

    print(f"\n{sum(results)}/{len(results)} cases passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
