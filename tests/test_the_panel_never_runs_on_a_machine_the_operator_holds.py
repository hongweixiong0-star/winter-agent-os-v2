"""A round touches the device the moment it starts, so the owner is checked before the reason.

Measured 2026-10-06 20:37-20:47 local, on the production pin.  The operator had taken the machine
for 燃霜活动 (``mode_state`` MANUAL, initiator USER, 30-minute window) while the client sat on the
燃霜矿区 activity map -- a screen the project has no route for -- so each round ended as
``ROLE_SWITCH_FAILED:... SOURCE ROLE HOME NOT CONFIRMED``.  ``retryable_role_switch`` is derived
from that string alone, so the panel kept respawning ``run_live.py`` every 15 s, and **every spawn
connects MAA to MuMu, which raises the emulator window**.  The operator saw the screen flicker for
ten minutes and asked why.

The gate that should have stopped it already existed and already named this case:

    auto_halt_reason(... )  ->  on ``manually_owned_by_workbuddy`` returns
                                "机器归 WorkBuddy 使用（Manual 模式）：AUTO 不进入下一轮"

It only matched the round that *ended* as manually owned.  A round that ended on anything else
walked straight past it.  These tests pin the rule that fixes that: the machine's owner outranks
this round's reason, and it is checked first.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import control_panel as panel  # noqa: E402

_HALT = "机器归 WorkBuddy 使用（Manual 模式）：AUTO 不进入下一轮，交还后自动恢复"


def _halt(**overrides):
    kwargs = dict(healthy=True, reason="OK", continuous=True, stop_requested=False,
                  paused=False, fatal=False, machine_is_ours=True)
    kwargs.update(overrides)
    return panel.auto_halt_reason(**kwargs)


def test_a_role_switch_failure_on_the_operators_machine_halts():
    """The exact production shape: healthy round, retryable-looking reason, not our machine."""
    assert _halt(reason="ROLE_SWITCH_FAILED: TARGET ROLE HOME NOT CONFIRMED",
                 machine_is_ours=False) == _HALT


def test_a_healthy_round_on_the_operators_machine_halts_too():
    """Owner, not reason: there is no reason string that makes someone else's device ours."""
    assert _halt(reason="OK", machine_is_ours=False) == _HALT
    assert _halt(reason="MAX_ACTIONS_REACHED", machine_is_ours=False) == _HALT


def test_the_cycle_declines_on_the_operators_machine():
    assert panel.should_continue_auto_cycle(
        healthy=True, reason="ROLE_SWITCH_FAILED: X", continuous=True,
        stop_requested=False, paused=False, fatal=False, machine_is_ours=False) is False


def test_our_own_machine_is_unchanged():
    """The guard must not cost a round when the machine really is ours."""
    assert _halt() == ""
    assert _halt(reason="ROLE_SWITCH_FAILED: X") == ""
    assert panel.should_continue_auto_cycle(
        healthy=True, reason="OK", continuous=True, stop_requested=False,
        paused=False, fatal=False, machine_is_ours=True) is True


def test_the_operator_case_is_still_named_as_before():
    """``manually_owned_by_workbuddy`` keeps its own wording -- this change adds a case, not a
    replacement, so a round that ends that way reads the same as it always did."""
    from winter_agent_v2 import mode_state
    assert _halt(reason=mode_state.MANUAL_STOP_REASON,
                 machine_is_ours=True) == _HALT


def test_defaulting_to_ours_keeps_every_older_caller_working():
    """The parameter defaults to True so the existing tests and call sites keep their meaning."""
    assert panel.auto_halt_reason(healthy=True, reason="OK", continuous=True,
                                  stop_requested=False, paused=False, fatal=False) == ""


# -- the other half of the flicker: the emulator window being raised -----------------------

def _may(**overrides):
    kwargs = dict(machine_is_ours=True, already_foregrounded=False,
                  foreground_package="com.other.app", want_package="com.gof.china")
    kwargs.update(overrides)
    return panel.should_foreground_emulator(**kwargs)


def test_the_emulator_is_never_raised_on_the_operators_machine():
    """The reported flicker: 13+ call sites, each foregrounding, none asking who owns the device."""
    assert _may(machine_is_ours=False) is False
    assert _may(machine_is_ours=False, foreground_package="") is False


def test_the_emulator_is_raised_at_most_once_per_round():
    """One foreground per round, not one per phase -- the flag used to be reset on every call."""
    assert _may(already_foregrounded=False) is True
    assert _may(already_foregrounded=True) is False


def test_a_game_already_in_front_is_left_alone():
    assert _may(foreground_package="com.gof.china") is False


def test_the_case_that_really_needs_it_still_works():
    """Machine ours, window behind, first phase of the round -> raise it once."""
    assert panel.should_foreground_emulator(
        machine_is_ours=True, already_foregrounded=False,
        foreground_package="com.android.launcher", want_package="com.gof.china") is True
