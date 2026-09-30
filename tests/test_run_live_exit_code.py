"""A round's exit code is about the round, not about the misses inside it.

Measured live 2026-09-30, three times in ninety minutes, each time through a different door and
each time with the same meaning: a round that did its job was reported as a system failure and
AUTO stopped while the operator's intent still said ``RUNNING``.

* 11:21 local, pin ``b2cb6f1``: round ``20260930_111430_903715`` issued 24 actions, 23 verified,
  one ``BEAST_SEARCH_TAB`` miss, ended ``MAX_ACTIONS_REACHED``.  ``classify_stop_reason`` tested
  the blanket ``verifier_failed`` short-circuit before the token, so the *snapshot* said
  ``stop_category=SYSTEM_FAILURE``.
* 11:53 local, pin ``f04714e``: round ``20260930_115308_285819``, 23 steps, 22 verified, ended
  ``MAX_ACTIONS_REACHED``.  The classifier was fixed by then, so the snapshot said
  ``COMPLETED`` -- and AUTO stopped anyway at 11:58:23, because ``tools/run_live.py`` still gated
  its exit code on ``verified``.
* 12:48 local, pin ``5e47f32``: ``SEMANTIC_TARGET_NOT_VERIFIED`` with **every verifier passing**.
  The classifier calls that ``CAPABILITY_GAP`` and the snapshot said ``SAFE_STOP``; the exit gate
  rejected it anyway because the reason was not in this module's own list, and AUTO stopped at
  12:48:39.

The lesson each time was the same, so the fix is structural rather than another special case: the
exit code now takes the category from the one classifier the panel and the snapshot already share,
instead of re-deriving acceptance from a second list that can disagree with it.

Why ``tests/test_control_panel.py`` cannot cover this: those cases build the run summary
themselves (``self._summary("MAX_ACTIONS_REACHED", executed=24)``) and hand it a ``healthy``
boolean, so they never exercise the value the child process actually returns.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.runtime_snapshot import (  # noqa: E402
    StopCategory,
    classify_stop_reason,
    state_for_stop_reason,
)

RUN_LIVE = ROOT / "tools" / "run_live.py"


def _exit_code(stop_reason: str, *, verifier_failed: bool = False,
               decision_skill: str = "", action_executed: bool = False) -> int:
    """The production decision, using the production classifier.

    ``tools/run_live.py`` pulls in the whole runtime at module scope -- the cost
    ``tests/test_process_revision_freeze.py`` documents -- so the import stays inside the call.
    """
    run_live = importlib.import_module("tools.run_live")
    category, _ = state_for_stop_reason(
        stop_reason, decision_skill=decision_skill, action_executed=action_executed,
        verifier_failed=verifier_failed,
    )
    return run_live.run_outcome_exit_code(stop_reason, category)


def _accepted_stops() -> set[str]:
    """The set the entry point really uses, read from its own source.

    Re-deriving the whole list here would let the two drift apart silently; every ``add()`` call
    and the inline literal are collected instead.  It is used for the "declared endings" claim,
    not for the exit decision.
    """
    import ast

    tree = ast.parse(RUN_LIVE.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "accepted_stops" not in targets:
            continue
        if isinstance(node.value, ast.Set):
            found.update(elt.value for elt in node.value.elts if isinstance(elt, ast.Constant))
        elif (
            isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "add"
            and node.value.args
            and isinstance(node.value.args[0], ast.Constant)
        ):
            found.add(node.value.args[0].value)
    return found


class TheMeasuredHaltsDoNotRepeatCase:
    def test_the_11_53_round_that_stopped_auto_now_keeps_auto_alive(self):
        """22 of 23 verifiers passed and the round ended its own declared budget."""
        assert classify_stop_reason("MAX_ACTIONS_REACHED", verifier_failed=True) is StopCategory.COMPLETED
        assert _exit_code("MAX_ACTIONS_REACHED", verifier_failed=True) == 0, (
            "a round that ended MAX_ACTIONS_REACHED must exit 0; any non-zero exit is read by the"
            " panel as healthy=False and stops the next round (measured 2026-09-30 11:58:23)"
        )

    def test_the_12_48_round_that_stopped_auto_now_keeps_auto_alive(self):
        """Every verifier passed; the reason is a capability gap the project says to route around."""
        assert classify_stop_reason("SEMANTIC_TARGET_NOT_VERIFIED") is StopCategory.CAPABILITY_GAP
        assert _exit_code("SEMANTIC_TARGET_NOT_VERIFIED") == 0, (
            "§7 requires a capability gap to become Recover -> Retry -> Defer -> Next Goal, not a"
            " stopped AUTO (measured 2026-09-30 12:48:39)"
        )

    def test_a_capability_gap_with_a_miss_elsewhere_still_continues(self):
        """The two doors are one rule: a declared stop reason decides the round, a miss does not."""
        for reason in ("SEMANTIC_TARGET_NOT_VERIFIED", "no_idle_march", "mail_all_clear",
                       "verified_beast_target_not_visible", "intel_no_untried_pins"):
            assert _exit_code(reason, verifier_failed=True) == 0, reason


class TheGateIsNotARubberStampCase:
    def test_an_undeclared_stop_with_a_miss_still_fails(self):
        assert classify_stop_reason("SOME_UNRECOGNISED_STOP", verifier_failed=True) is StopCategory.SYSTEM_FAILURE
        assert _exit_code("SOME_UNRECOGNISED_STOP", verifier_failed=True) == 2

    def test_an_undeclared_stop_with_no_information_still_fails(self):
        assert _exit_code("SOME_UNRECOGNISED_STOP") == 2
        assert _exit_code("") == 2

    def test_a_fatal_stop_always_fails(self):
        assert _exit_code("FATAL_DEVICE_LOST") == 2

    def test_a_safe_stop_that_acted_nothing_is_a_capability_gap(self):
        assert _exit_code("whatever", decision_skill="SAFE_STOP", action_executed=False) == 0


class TheEntryPointUsesThisRuleCase:
    def test_declared_endings_are_the_ones_the_capability_gap_set_calls_honest(self):
        accepted = _accepted_stops()
        assert "MAX_ACTIONS_REACHED" in accepted, (
            "MAX_ACTIONS_REACHED is a declared round end (runtime.py returns it by exhausting the"
            " action budget) and must stay accepted"
        )
        assert "intel_not_available" in accepted, (
            "a legitimately idle account must still be able to end its run cleanly"
        )

    def test_the_exit_code_is_not_gated_on_every_step_verifying(self):
        """Structural, because the ordering is the guarantee.

        ``verified`` stays per-step telemetry in the run JSON; the gate must be the shared
        classifier's category.  If someone puts ``verified and`` back into the return, the 11:58
        halt returns with it.
        """
        source = RUN_LIVE.read_text(encoding="utf-8")
        call_at = source.find("return run_outcome_exit_code(")
        assert call_at != -1, "the entry point must decide the exit code through the named rule"
        tail = source[call_at : call_at + 200]
        assert "verified" not in tail.split("\n")[0], (
            "the exit code must not be gated on every step verifying"
        )
        assert "state_for_stop_reason(" in source, (
            "the category must come from the shared classifier, not a private second list"
        )
