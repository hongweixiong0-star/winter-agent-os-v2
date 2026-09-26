"""The bear rally skills must be dispatchable AND must not certify the wrong target.

Two failures are possible here and they pull in opposite directions, which is why they are
tested together.

**Undeliverable.**  Before 2026-09-24 ``JOIN_RALLY`` and ``START_RALLY`` were registered
with a verifier *name* that had no entry in ``LiveRuntime.VERIFIED_ATOMIC``, so ``run``
refused them at ``decision.skill not in self.VERIFIED_ATOMIC`` and ended the step with
``SKILL_NOT_ENABLED_FOR_LIVE_LOOP``.  Their ``Action`` kinds (``START_RALLY`` /
``JOIN_RALLY``) were also not among the four ``Executor.execute`` implements, so they would
have fallen through to ``DEVICE_ADAPTER_NOT_CONNECTED`` even if dispatched.  Two
independent dead ends on the one activity with a 30-minute window.

**Over-deliverable.**  The fix must not make the skills *too* willing.  ``verify_rally_*``
take a ``target`` and compute

    identity_ok = str(rally.get("target_type", target)).upper() == target.upper()

so binding them with a target is a claim about the frame's own reading.  If the binding were
loose -- or if the identity check were dropped -- the chain could certify a 普通集结 or a
player attack as a bear rally, which is the exact confusion the constitution forbids:

    §三  尤其不能将普通集结误认成巨熊集结，不能将玩家攻击按钮误认成巨熊参与按钮

Both halves are asserted below.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402

BEAR_SKILLS = ("JOIN_RALLY", "START_RALLY")

#: The semantic each bear skill must tap.  Named here as data so the test states the
#: expected control rather than restating the implementation.
EXPECTED_TARGET = {
    # CHANGED 2026-09-27 from "BTN_JOIN_ROW".  That name stood for a picture of the
    # green +, and a picture of a plus cannot say which rally it belongs to, so two
    # joinable rows on one frame were indistinguishable and the first won regardless
    # of its countdown -- the limit the skill's own comment used to record.  The rally
    # reader now exists (rally.read_rally_list_image, replayed on four archived live
    # frames), so the semantic names the LIST the tap is chosen from.
    #
    # BTN_JOIN_ROW is not gone: it is the node's ``fallback_semantic`` and answers when
    # the frame carries no 集结中 header, so the tap is still a single TAP_SEMANTIC
    # through the one executor either way -- which is what this test is about.
    "JOIN_RALLY": "RALLY_ROW_JOIN_BUTTON",
    "START_RALLY": "BTN_START_RALLY",
}


def _runtime_class():
    from winter_agent_v2.runtime import LiveRuntime
    return LiveRuntime


# --------------------------------------------------------------- dispatchability


@pytest.mark.parametrize("skill_id", BEAR_SKILLS)
def test_the_rally_skill_is_enabled_for_the_live_loop(skill_id):
    """The registered-not-enabled defect, pinned directly.

    ``run`` gates on ``decision.skill not in self.VERIFIED_ATOMIC``; an entry here is
    literally the difference between "the loop may dispatch this" and "the step ends".
    """
    verified = _runtime_class().VERIFIED_ATOMIC
    assert skill_id in verified, (
        f"{skill_id} is not in VERIFIED_ATOMIC, so LiveRuntime.run will refuse it with "
        f"SKILL_NOT_ENABLED_FOR_LIVE_LOOP no matter how good the templates are"
    )
    assert callable(verified[skill_id]), "the value must be a callable verifier"


@pytest.mark.parametrize("skill_id", BEAR_SKILLS)
def test_the_rally_skill_uses_the_single_tap_path(skill_id):
    """The action must be one ``Executor.execute`` can actually carry out.

    Enumerating the supported kinds here rather than importing a private list: the
    assertion is about the *contract*, and if the executor grows a fifth kind this test
    should notice and be updated deliberately rather than pass by accident.
    """
    registry = {s.id: s for s in v2_registry().all()}
    assert skill_id in registry, f"{skill_id} must be in the registry"
    action = registry[skill_id].action
    assert action.kind in {"TAP_SEMANTIC", "PRESS_BACK", "SWIPE", "OBSERVE"}, (
        f"{skill_id} carries kind {action.kind!r}, which Executor.execute does not implement "
        f"-- it would fall through to DEVICE_ADAPTER_NOT_CONNECTED"
    )
    assert action.kind == "TAP_SEMANTIC", (
        "the bear controls are located on the frame, so the action must be a semantic tap"
    )
    assert action.target == EXPECTED_TARGET[skill_id], (
        f"{skill_id} must tap {EXPECTED_TARGET[skill_id]!r}, the control registered from the "
        f"live bear frame; got {action.target!r}"
    )


def test_no_second_execution_path_was_introduced():
    """§二: the fix must reuse the one executor, not add a rally-specific one.

    If these skills had been made dispatchable by teaching ``Executor`` a new kind, that
    would be a second execution chain by another name.  The kind list is therefore pinned
    to what the module actually handles.
    """
    from winter_agent_v2 import executor as executor_module

    source = executor_module.__file__
    body = Path(source).read_text(encoding="utf-8")
    for kind in ('action.kind == "TAP_SEMANTIC"', 'action.kind == "PRESS_BACK"',
                 'action.kind == "SWIPE"', 'action.kind == "OBSERVE"'):
        assert kind in body, f"Executor lost its {kind} branch"
    assert 'action.kind == "JOIN_RALLY"' not in body, (
        "Executor must not grow a rally-specific kind: that is a second execution path"
    )
    assert 'action.kind == "START_RALLY"' not in body, (
        "Executor must not grow a rally-specific kind: that is a second execution path"
    )


# ------------------------------------------------------------------- correctness


def _bear_frame(**over) -> WorldState:
    body = dict(page=Page.ALLIANCE, confidence=0.99)
    body.update(over)
    return WorldState(**body)


def test_a_join_is_proven_by_the_march_queue_or_the_member_state():
    """What ``verify_rally_joined`` demands, and why a click is not enough."""
    verified = _runtime_class().VERIFIED_ATOMIC
    before = _bear_frame(march_used=1, alliance={"rally": {"target_type": "BEAR"}})
    after = _bear_frame(march_used=2, alliance={"rally": {"target_type": "BEAR"}})

    result = verified["JOIN_RALLY"](before, after)
    assert result.ok, (
        "a queue that went 1 -> 2 with the frame still reading BEAR is a proven join; "
        f"got {result.reason}"
    )


def test_a_join_that_changed_nothing_is_not_proven():
    """The verifier's whole purpose: the tap landing is not the join happening."""
    verified = _runtime_class().VERIFIED_ATOMIC
    same = {"rally": {"target_type": "BEAR"}}
    before = _bear_frame(march_used=1, alliance=same)
    after = _bear_frame(march_used=1, alliance=same)

    result = verified["JOIN_RALLY"](before, after)
    assert not result.ok, "no queue change and no member state must not be reported as joined"
    assert result.reason == "RALLY_JOIN_NOT_PROVEN"


def test_a_join_against_another_target_is_refused():
    """The constitution's §三 case: 普通集结 must not pass as 巨熊集结.

    The frame reports a different ``target_type``, which is exactly how a live frame states
    what it is looking at.  The bound verifier must refuse even though the queue moved.
    """
    verified = _runtime_class().VERIFIED_ATOMIC
    before = _bear_frame(march_used=1, alliance={"rally": {"target_type": "FORTRESS"}})
    after = _bear_frame(march_used=2, alliance={"rally": {"target_type": "FORTRESS"}})

    result = verified["JOIN_RALLY"](before, after)
    assert not result.ok, (
        "a queue increase against a FORTRESS rally must not certify a BEAR join -- this is "
        "the 普通集结/巨熊集结 confusion the directive names"
    )


def test_a_creation_is_proven_by_ownership_or_the_special_slot():
    """Two accepted proofs, and the second is bear-specific.

    Bear's rally takes a *special* slot rather than an ordinary march slot, so for this
    target the slot transition is itself evidence -- see the §14 model note in the master
    rules.  A non-bear target has no such shortcut.
    """
    verified = _runtime_class().VERIFIED_ATOMIC

    owned = _bear_frame(alliance={"rally": {"target_type": "BEAR", "ownership": "SELF",
                                           "remaining_seconds": 300}})
    before = _bear_frame(alliance={"rally": {"target_type": "BEAR"}})
    assert verified["START_RALLY"](before, owned).ok, "own rally with a live countdown proves creation"

    before_special = _bear_frame(bear_rally_special_available=True,
                                 alliance={"rally": {"target_type": "BEAR"}})
    after_special = _bear_frame(bear_rally_special_available=False,
                                alliance={"rally": {"target_type": "BEAR"}})
    assert verified["START_RALLY"](before_special, after_special).ok, (
        "for BEAR, consuming the special rally slot is also a proof of creation"
    )


def test_a_creation_that_changed_nothing_is_not_proven():
    """Clicking 发起集结 is not starting a rally."""
    verified = _runtime_class().VERIFIED_ATOMIC
    same = {"rally": {"target_type": "BEAR"}}
    frame = _bear_frame(alliance=same, bear_rally_special_available=True)

    result = verified["START_RALLY"](frame, frame)
    assert not result.ok, "an unchanged frame must not certify a created rally"
    assert result.reason == "RALLY_CREATE_NOT_PROVEN"


def test_a_creation_against_another_target_is_refused():
    """The same §三 guard on the leader side."""
    verified = _runtime_class().VERIFIED_ATOMIC
    owned = _bear_frame(alliance={"rally": {"target_type": "POLAR_TERROR",
                                            "ownership": "SELF", "remaining_seconds": 300}})
    before = _bear_frame(alliance={"rally": {"target_type": "POLAR_TERROR"}})

    result = verified["START_RALLY"](before, owned)
    assert not result.ok, "a self-owned POLAR_TERROR rally must not certify a BEAR creation"


def test_the_bound_verifier_takes_the_two_arguments_the_runtime_passes():
    """``Verifier`` is ``Callable[[WorldState, WorldState], VerificationResult]``.

    The verifiers themselves are three-argument (they are generic over the target), and the
    runtime calls two-argument.  That mismatch is precisely why the binding is a lambda, so
    the arity of the *bound* object is the thing worth pinning.
    """
    import inspect

    verified = _runtime_class().VERIFIED_ATOMIC
    for skill_id in BEAR_SKILLS:
        bound = verified[skill_id]
        params = [
            p for p in inspect.signature(bound).parameters.values()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        ]
        assert len(params) == 2, (
            f"{skill_id}'s bound verifier takes {len(params)} positional parameters; the "
            f"runtime calls it with (before, after)"
        )
