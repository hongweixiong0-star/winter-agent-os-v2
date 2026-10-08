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
    kwargs = dict(enabled=True, machine_is_ours=True, already_foregrounded=False,
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
    """Machine ours, window behind, first phase of the round, operator asked -> raise it once."""
    assert panel.should_foreground_emulator(
        enabled=True, machine_is_ours=True, already_foregrounded=False,
        foreground_package="com.android.launcher", want_package="com.gof.china") is True


def test_the_default_is_to_never_raise_the_window():
    """The absolute answer to "无论如何都不能闪屏": nothing automated steals focus by default.

    Measured 2026-10-06: the operator saw dozens of flashes per restart.  ADB input and screencap
    do not need window focus, so the raise bought the runtime nothing -- leaving it off costs
    nothing and removes the whole class.
    """
    assert panel.foreground_emulator_enabled({}) is False
    assert panel.foreground_emulator_enabled({"WINTER_FOREGROUND_EMULATOR": ""}) is False
    assert panel.foreground_emulator_enabled({"WINTER_FOREGROUND_EMULATOR": "0"}) is False
    assert _may(enabled=False) is False


def test_the_operator_can_still_ask_for_it():
    assert panel.foreground_emulator_enabled({"WINTER_FOREGROUND_EMULATOR": "1"}) is True
    assert _may(enabled=True, machine_is_ours=True,
                foreground_package="com.android.launcher") is True


# -- the emulator repair: a launch cannot rebind a dead ADB bridge --------------------------

def _restart(**overrides):
    kwargs = dict(launch_already_requested=True, restart_already_requested=False, failed_attempts=3)
    kwargs.update(overrides)
    return panel.should_restart_the_emulator(**kwargs)


def test_a_dead_bridge_escalates_to_a_restart():
    """Measured 2026-10-09, twice in one evening, on the production pin.

    ``mumu-cli info`` said ``start_finished`` while every serial in ``adb devices`` read ``offline``
    and ``netstat`` showed nothing listening on the ADB ports -- the instance was healthy, its bridge
    was gone.  The panel launched (a no-op on a running instance) and then spent its whole 120-second
    budget retrying ``adb connect`` at a port that was not open, so the run ended as
    ``error: device offline`` and AUTO stopped by design.  ``mumu-cli control -v 0 restart`` restored
    it both times.
    """
    assert _restart() is True


def test_the_restart_waits_for_the_launch_to_have_failed_first():
    """The launch is still the cheaper repair, and it is tried first."""
    assert _restart(launch_already_requested=False) is False
    assert _restart(launch_already_requested=False, failed_attempts=99) is False


def test_the_reconnect_must_have_failed_repeatedly_before_restarting():
    """One refused connect is not evidence that the bridge is gone for good."""
    assert _restart(failed_attempts=0) is False
    assert _restart(failed_attempts=2) is False
    assert _restart(failed_attempts=3) is True


def test_the_restart_happens_at_most_once_per_start():
    """A machine that will not come back must not be restarted in a loop."""
    assert _restart(restart_already_requested=True) is False
    assert _restart(restart_already_requested=True, failed_attempts=99) is False
