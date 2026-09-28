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
from winter_agent_v2.rally import RallyTarget  # noqa: E402
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
    """Shared rally skills are enabled through the target-aware verifier path."""
    runtime = _runtime_class()
    assert skill_id in runtime.DYNAMIC_TARGET_SKILLS
    assert skill_id not in runtime.VERIFIED_ATOMIC, (
        "rally actions must not retain a target-free, hard-coded Bear verifier"
    )


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
    from winter_agent_v2.runtime import _verify_rally_action
    before = _bear_frame(march_used=1, alliance={"rally": {"target_type": "BEAR"}})
    after = _bear_frame(march_used=2, alliance={"rally": {"target_type": "BEAR"}})

    result = _verify_rally_action("JOIN_RALLY", before, after, RallyTarget.BEAR)
    assert result.ok, (
        "a queue that went 1 -> 2 with the frame still reading BEAR is a proven join; "
        f"got {result.reason}"
    )


def test_a_join_that_changed_nothing_is_not_proven():
    """The verifier's whole purpose: the tap landing is not the join happening."""
    from winter_agent_v2.runtime import _verify_rally_action
    same = {"rally": {"target_type": "BEAR"}}
    before = _bear_frame(march_used=1, alliance=same)
    after = _bear_frame(march_used=1, alliance=same)

    result = _verify_rally_action("JOIN_RALLY", before, after, RallyTarget.BEAR)
    assert not result.ok, "no queue change and no member state must not be reported as joined"
    assert result.reason == "RALLY_JOIN_NOT_PROVEN"


def test_a_join_against_another_target_is_refused():
    """The constitution's §三 case: 普通集结 must not pass as 巨熊集结.

    The frame reports a different ``target_type``, which is exactly how a live frame states
    what it is looking at.  The bound verifier must refuse even though the queue moved.
    """
    from winter_agent_v2.runtime import _verify_rally_action
    before = _bear_frame(march_used=1, alliance={"rally": {"target_type": "FORTRESS"}})
    after = _bear_frame(march_used=2, alliance={"rally": {"target_type": "FORTRESS"}})

    result = _verify_rally_action("JOIN_RALLY", before, after, RallyTarget.BEAR)
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
    from winter_agent_v2.runtime import _verify_rally_action

    owned = _bear_frame(alliance={"rally": {"target_type": "BEAR", "ownership": "SELF",
                                           "remaining_seconds": 300}})
    before = _bear_frame(alliance={"rally": {"target_type": "BEAR"}})
    assert _verify_rally_action("START_RALLY", before, owned, RallyTarget.BEAR).ok, (
        "own rally with a live countdown proves creation"
    )

    before_special = _bear_frame(bear_rally_special_available=True,
                                 alliance={"rally": {"target_type": "BEAR"}})
    after_special = _bear_frame(bear_rally_special_available=False,
                                alliance={"rally": {"target_type": "BEAR"}})
    assert _verify_rally_action(
        "START_RALLY", before_special, after_special, RallyTarget.BEAR
    ).ok, (
        "for BEAR, consuming the special rally slot is also a proof of creation"
    )


def test_a_creation_that_changed_nothing_is_not_proven():
    """Clicking 发起集结 is not starting a rally."""
    from winter_agent_v2.runtime import _verify_rally_action
    same = {"rally": {"target_type": "BEAR"}}
    frame = _bear_frame(alliance=same, bear_rally_special_available=True)

    result = _verify_rally_action("START_RALLY", frame, frame, RallyTarget.BEAR)
    assert not result.ok, "an unchanged frame must not certify a created rally"
    assert result.reason == "RALLY_CREATE_NOT_PROVEN"


def test_a_creation_against_another_target_is_refused():
    """The same §三 guard on the leader side."""
    from winter_agent_v2.runtime import _verify_rally_action
    owned = _bear_frame(alliance={"rally": {"target_type": "POLAR_TERROR",
                                            "ownership": "SELF", "remaining_seconds": 300}})
    before = _bear_frame(alliance={"rally": {"target_type": "POLAR_TERROR"}})

    result = _verify_rally_action("START_RALLY", before, owned, RallyTarget.BEAR)
    assert not result.ok, "a self-owned POLAR_TERROR rally must not certify a BEAR creation"


@pytest.mark.parametrize(
    ("skill_id", "target", "raw"),
    [
        ("JOIN_RALLY", RallyTarget.ICEFIELD_BEAST, "POLAR_TERROR"),
        ("START_RALLY", RallyTarget.ICEFIELD_BEAST, "ICEFIELD_BEAST"),
    ],
)
def test_generic_rally_verifier_uses_the_goal_target(skill_id, target, raw):
    from winter_agent_v2.runtime import _verify_rally_action

    if skill_id == "JOIN_RALLY":
        before = _bear_frame(march_used=1, alliance={"rally": {"target_type": raw}})
        after = _bear_frame(march_used=2, alliance={"rally": {"target_type": raw}})
    else:
        before = _bear_frame(alliance={"rally": {"target_type": raw}})
        after = _bear_frame(alliance={"rally": {
            "target_type": raw, "ownership": "SELF", "remaining_seconds": 300,
        }})
    assert _verify_rally_action(skill_id, before, after, target).ok


def test_rally_verifier_refuses_an_unknown_goal_target():
    from winter_agent_v2.runtime import _verify_rally_action

    frame = _bear_frame(alliance={"rally": {"target_type": "BEAR"}})
    result = _verify_rally_action("JOIN_RALLY", frame, frame, None)
    assert not result.ok
    assert result.reason == "RALLY_TARGET_UNKNOWN"
