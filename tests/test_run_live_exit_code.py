"""A round's exit code is about the round, not about the misses inside it.

Measured live 2026-09-30, twice, on the pinned production copy -- and it is the same defect both
times: a round that did its job was reported as a system failure and AUTO stopped while the
operator's intent still said ``RUNNING``.

* 11:21 local, pin ``b2cb6f1``: round ``20260930_111430_903715`` issued 24 actions, 23 verified,
  one ``BEAST_SEARCH_TAB`` miss, ended ``MAX_ACTIONS_REACHED``.  ``classify_stop_reason`` tested
  the blanket ``verifier_failed`` short-circuit before the token, so the *snapshot* said
  ``stop_category=SYSTEM_FAILURE``.
* 11:53 local, pin ``f04714e`` (after the 11:50 fix): round ``20260930_115308_285819``, 23 steps,
  22 verified, one miss at step 002, ended ``MAX_ACTIONS_REACHED``.  The classifier and the
  panel's ``healthy`` were fixed by then, so the snapshot correctly said
  ``stop_category=COMPLETED`` -- and AUTO stopped anyway, because ``tools/run_live.py`` still
  gated its exit code on ``verified``.  ``panel.log``:

      ``11:58:23  ⏹ 未进入下一轮：本轮被判定为系统故障：MAX_ACTIONS_REACHED``

  The panel reads a non-zero child exit as ``healthy=False``, so that one line is the whole
  halt.  The 11:50 commit closed two doors and left the third one open.

Why this is not covered by ``tests/test_control_panel.py``: those cases build the run summary
themselves (``self._summary("MAX_ACTIONS_REACHED", executed=24)``) and hand it a ``healthy``
boolean, so they never exercise the value the child process actually returns.  This file drives
the real decision with the real inputs -- including the shared classifier -- instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.runtime_snapshot import (  # noqa: E402
    StopCategory,
    classify_stop_reason,
)

RUN_LIVE = ROOT / "tools" / "run_live.py"


def _exit_code(stop_reason: str, accepted: set[str]) -> int:
    """The production decision, imported lazily.

    ``tools/run_live.py`` pulls in the whole runtime at module scope, which is exactly the cost
    ``tests/test_process_revision_freeze.py`` documents, so the import stays inside the call.
    """
    import importlib

    module = importlib.import_module("tools.run_live")
    return module.run_outcome_exit_code(stop_reason, accepted)


def _accepted_stops() -> set[str]:
    """The set the entry point really uses, read from its own source.

    Re-deriving the whole list here would let the two drift apart silently; every ``add()`` call
    and the inline literal are collected instead.
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
            found.update(
                elt.value for elt in node.value.elts if isinstance(elt, ast.Constant)
            )
        elif (
            isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "add"
            and node.value.args
            and isinstance(node.value.args[0], ast.Constant)
        ):
            found.add(node.value.args[0].value)
    return found


def test_the_measured_round_that_stopped_auto_now_keeps_auto_alive() -> None:
    """The exact 11:53 round, replayed through the real classifier and the real exit code.

    22 of 23 verifiers passed and the round ended in its own declared budget.  The snapshot said
    COMPLETED, the exit code said failure, and the exit code is what stopped AUTO.
    """
    accepted = _accepted_stops()
    assert "MAX_ACTIONS_REACHED" in accepted, (
        "MAX_ACTIONS_REACHED is a declared round end (runtime.py returns it by exhausting the"
        " action budget) and must stay accepted"
    )

    # One miss inside the round -- the real number from episode 20260930_115308_285819.
    category = classify_stop_reason("MAX_ACTIONS_REACHED", verifier_failed=True)
    assert category is StopCategory.COMPLETED, (
        "the shared classifier must not relabel a finished round for a step miss"
    )

    assert _exit_code("MAX_ACTIONS_REACHED", accepted) == 0, (
        "a round that ended MAX_ACTIONS_REACHED must exit 0; any non-zero exit is read by the"
        " panel as healthy=False and stops the next round (measured 2026-09-30 11:58:23)"
    )


def test_a_round_that_ended_somewhere_unaccepted_still_fails() -> None:
    """The other direction: this is a gate, not a rubber stamp.

    An unidentified stop -- the shape a real crash or an unhandled verifier failure leaves --
    must still exit non-zero, or the fix would have bought uptime by hiding failures.
    """
    accepted = _accepted_stops()
    assert _exit_code("SOME_UNRECOGNISED_STOP", accepted) == 2
    assert _exit_code("", accepted) == 2
    assert (
        classify_stop_reason("SOME_UNRECOGNISED_STOP") is StopCategory.SYSTEM_FAILURE
    )


def test_every_declared_round_end_exits_zero() -> None:
    """Each accepted stop is the child's whole message to the panel; all of them must reach it."""
    accepted = _accepted_stops()
    for stop in sorted(accepted):
        assert _exit_code(stop, accepted) == 0, f"{stop} is accepted but exits non-zero"


def test_the_exit_code_is_not_gated_on_every_step_verifying() -> None:
    """Structural, because the ordering is the guarantee.

    ``verified`` is per-step telemetry and stays in the run JSON; the gate must be the round's
    terminal reason.  If someone puts ``verified and`` back into the return, the 11:53 halt
    returns with it.
    """
    source = RUN_LIVE.read_text(encoding="utf-8")
    assert "def run_outcome_exit_code(" in source
    call_at = source.find("return run_outcome_exit_code(")
    assert call_at != -1, "the entry point must decide the exit code through the named rule"
    tail = source[call_at : call_at + 200]
    assert "verified" not in tail, (
        "the exit code must not be gated on every step verifying; that is the defect this"
        " file exists to keep closed"
    )
