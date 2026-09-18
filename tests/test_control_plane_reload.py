"""The window must notice when the code under it has been replaced.

Measured 2026-09-18: the gateway fix was committed, and the running window went on showing
"WorkBuddy 异常".  Nothing was wrong with the fix -- the process had imported the old
`gateway_service` / `workbuddy_bridge` / `control_panel` at start-up, and no path ever told it
the files had changed.  A worker reload would not have helped: the stale code was in the
window.

Three questions are separated here on purpose, because conflating them is how a reload turns
into either a no-op or a nuisance:

  needs_reload        is this window running something else than the disk?
  safe_to_reload      may it be replaced *now*?
  reload_reason       what does the operator read?
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import control_plane_reload as cpr  # noqa: E402

LOADED = "a" * 40
DISK = "b" * 40


# --------------------------------------------------------------------- is it stale?


def test_a_control_plane_change_demands_a_reload():
    assert cpr.needs_reload(LOADED, DISK, ["winter_agent_v2/gateway_service.py"]) is True


def test_a_non_control_plane_change_does_not():
    """A new template or knowledge file changes the next cycle, not this window.

    Telling the operator to restart for one would train them to ignore the notice -- which is
    worse than not showing it.
    """
    assert cpr.needs_reload(LOADED, DISK, ["knowledge/game/beasts.json",
                                           "dataset/candidate/template_manifest.json"]) is False


def test_an_unchanged_version_demands_nothing_even_if_files_are_dirty():
    """Equal versions mean equal code, whatever list the caller passed in."""
    assert cpr.needs_reload(LOADED, LOADED,
                            ["winter_agent_v2/gateway_service.py"]) is False


def test_a_window_that_never_recorded_its_version_does_not_claim_to_be_stale():
    assert cpr.needs_reload("", DISK, ["winter_agent_v2/gateway_service.py"]) is False
    assert cpr.needs_reload(LOADED, "", ["winter_agent_v2/gateway_service.py"]) is False


def test_every_named_control_plane_file_is_recognised():
    """The list is the reason a reader can agree with the notice, so it must be complete."""
    for path in ("tools/control_panel.py", "winter_agent_v2/workbuddy_bridge.py",
                 "winter_agent_v2/gateway_service.py", "winter_agent_v2/escalation_queue.py",
                 "winter_agent_v2/device_lease.py"):
        assert path in cpr.CONTROL_PLANE_PATHS, path
        assert cpr.needs_reload(LOADED, DISK, [path]) is True, path


def test_paths_are_matched_regardless_of_separator_or_leading_dot_slash():
    """git reports forward slashes; a Windows caller may not."""
    assert cpr.touched_control_plane(["winter_agent_v2\\gateway_service.py"]) == (
        "winter_agent_v2/gateway_service.py",)
    assert cpr.touched_control_plane(["./tools/control_panel.py"]) == ("tools/control_panel.py",)


# --------------------------------------------------------------------- may it happen now?


def test_a_safe_point_allows_the_reload():
    ok, why = cpr.safe_to_reload(atomic_step_running=False, lease_holder="",
                                 operator_intent="RUNNING")
    assert ok is True and why


@pytest.mark.parametrize("intent", ["STOPPED", "PAUSED", "stopped"])
def test_the_operators_stop_outranks_the_reload(intent):
    """Named explicitly by the operator: a watchdog must not override a human."""
    ok, why = cpr.safe_to_reload(atomic_step_running=False, lease_holder="",
                                 operator_intent=intent)
    assert ok is False
    assert "STOP" in why or "PAUSE" in why.upper()


def test_an_atomic_step_in_flight_defers_the_reload():
    ok, why = cpr.safe_to_reload(atomic_step_running=True, lease_holder="",
                                 operator_intent="RUNNING")
    assert ok is False and "安全边界" in why


def test_a_held_device_lease_defers_the_reload():
    ok, why = cpr.safe_to_reload(atomic_step_running=False,
                                 lease_holder="OWNER_DEVELOPMENT_VALIDATION",
                                 operator_intent="RUNNING")
    assert ok is False and "租约" in why


def test_a_read_only_second_window_never_restarts_the_real_one():
    ok, why = cpr.safe_to_reload(atomic_step_running=False, lease_holder="",
                                 operator_intent="RUNNING", panel_owned=False)
    assert ok is False and "唯一持有者" in why


# --------------------------------------------------------------------- the marker


def test_the_marker_is_its_own_file_not_the_workers():
    """Distinct kind and distinct path: neither request may consume the other."""
    from winter_agent_v2 import runtime_reload

    assert cpr.CONTROL_PLANE_KIND != runtime_reload.REQUEST_KIND
    assert cpr.control_plane_path(ROOT) != runtime_reload.default_path(ROOT)
    signal = cpr.control_plane_signal(ROOT)
    assert isinstance(signal, runtime_reload.ReloadSignal), (
        "it must reuse the project's reload machinery, not a second one"
    )


def test_the_reason_names_both_versions_and_the_files(tmp_path):
    text = cpr.reload_reason(LOADED, DISK, ["winter_agent_v2/gateway_service.py"])
    assert cpr.CONTROL_PLANE_KIND in text
    assert LOADED[:12] in text and DISK[:12] in text
    assert "gateway_service.py" in text


def test_the_reason_is_empty_when_nothing_is_owed():
    assert cpr.reload_reason(LOADED, LOADED, ["winter_agent_v2/gateway_service.py"]) == ""
    assert cpr.reload_reason(LOADED, DISK, ["knowledge/game/beasts.json"]) == ""
    assert "无法判断" in cpr.reload_reason("", DISK, ["tools/control_panel.py"])


# --------------------------------------------------------------------- the window's wiring


def test_the_window_checks_itself_on_the_refresh_that_shows_the_gateway_cell():
    """Structural: the check sits where the measured symptom appeared.

    The stale cell was the gateway one, so the staleness check belongs on the same refresh --
    a separate slow timer would leave the window confidently wrong for up to a full period.
    """
    source = (ROOT / "tools/control_panel.py").read_text(encoding="utf-8")
    assert "def _check_control_plane_reload" in source
    assert "_check_control_plane_reload()" in source
    check_at = source.find("self._check_control_plane_reload()")
    soak_at = source.find('self.values["soak"].set(render_soak(')
    assert 0 < soak_at < check_at, "the check must follow the gateway/soak refresh"
    # And it must freeze its own version, or it has nothing to compare against.
    assert "freeze_process_revision(ROOT)" in source
    # The restart is delegated to the existing launcher, not reimplemented.
    assert "panel_restart.py" in source
    assert "--restart" in source
