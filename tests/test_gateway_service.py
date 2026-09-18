"""The gateway lifecycle: the decisions, and the two ways a launcher doubles itself.

The decision table is pure (``gateway_service.decide``), so most of this file needs no
process, no port and no network.  The point of testing it separately is that every branch
is a rule an operator stated, and a rule that lives only in an ``if`` inside a daemon
thread is a rule nothing can check.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from winter_agent_v2 import gateway_service as gs


# --------------------------------------------------------------------- the decision table


def _decide(measurement: gs.Measurement, record=None, **kwargs):
    record = dict(record or {})
    kwargs.setdefault("now", 1000.0)
    return gs.decide(measurement, record, **kwargs)


def test_nothing_running_starts_one_because_gui_start_is_system_start():
    """§二: the operator's one action is starting the window.  No manual ``--serve``."""
    state, action, detail = _decide(gs.Measurement())
    assert action == gs.ACT_START
    assert state == gs.OFFLINE
    assert "§二" in detail


def test_a_healthy_gateway_is_reused_and_never_replaced():
    """§三/§五: one instance.  A running gateway is adopted, not restarted."""
    m = gs.Measurement(port_pid=22268, port_name="node.exe", health=True)
    state, action, _ = _decide(m)
    assert (state, action) == (gs.HEALTHY, gs.ACT_REUSE)


def test_an_unknown_process_on_the_port_is_reported_not_killed():
    """§三 rule 4: a port conflict is a state to surface, not a process to kill."""
    m = gs.Measurement(port_pid=1234, port_name="something.exe", health=False)
    state, action, detail = _decide(m)
    assert (state, action) == (gs.PORT_CONFLICT, gs.ACT_PORT_CONFLICT)
    assert "不强杀" in detail


def test_our_own_process_inside_the_grace_window_is_waited_out():
    """The double-start bug: ``--serve`` has not bound yet, so the port looks free."""
    m = gs.Measurement(port_pid=555, port_name="node.exe", health=False)
    record = {"pid": 555, "launched_at": 990.0}
    state, action, _ = _decide(m, record, now=1000.0)
    assert (state, action) == (gs.STARTING, gs.ACT_WAIT)


def test_our_own_process_that_never_binds_is_restarted_after_the_grace_window():
    """Past the window a wedged process of ours is the one thing we may replace."""
    m = gs.Measurement(port_pid=555, port_name="node.exe", health=False)
    record = {"pid": 555, "launched_at": 800.0, "next_attempt_at": 0.0}
    state, action, detail = _decide(m, record, now=1000.0)
    assert (state, action) == (gs.RESTARTING, gs.ACT_RESTART)
    assert "卡死" in detail


def test_one_timeout_is_information_and_does_not_restart():
    """§六: '不要 一次timeout就重启'.  Two failures is still not a state change."""
    m = gs.Measurement(health=False)
    for failures in (1, 2):
        state, action, detail = _decide(m, {"started_ever": True,
                                            "consecutive_failures": failures})
        assert action == gs.ACT_WAIT, f"failures={failures} must not restart"
        assert state == gs.OFFLINE


def test_consecutive_failures_cross_the_threshold_and_then_restart():
    """§六: 连续 2~3 次失败 → DEGRADED，然后自动重启 → Health PASS."""
    m = gs.Measurement(health=False)
    record = {"started_ever": True, "consecutive_failures": gs.DEGRADED_AFTER_FAILURES}
    state, action, detail = _decide(m, record)
    assert action == gs.ACT_RESTART
    assert f"连续失败 {gs.DEGRADED_AFTER_FAILURES}" in detail


def test_the_restart_ladder_holds_the_next_attempt_until_its_rung():
    """30 → 60 → 120 → 300, and the last rung repeats rather than giving up."""
    m = gs.Measurement(health=False)
    record = {"started_ever": True, "consecutive_failures": 5, "next_attempt_at": 2000.0}
    state, action, detail = _decide(m, record, now=1000.0)
    assert action == gs.ACT_WAIT
    assert state == gs.DEGRADED
    assert "退避中" in detail
    # And once the rung has passed, the attempt happens.
    assert _decide(m, record, now=2000.0)[1] == gs.ACT_RESTART


def test_a_live_process_that_has_not_bound_yet_is_waited_for():
    """Own pid alive, port not taken, inside the window: still starting, not dead."""
    m = gs.Measurement(own_pid_alive=True)
    record = {"pid": 777, "launched_at": 990.0}
    assert _decide(m, record, now=1000.0)[:2] == (gs.STARTING, gs.ACT_WAIT)


def test_stop_from_the_operator_outranks_the_watchdog():
    """§二十五: 'Watchdog 不得覆盖用户STOP'."""
    m = gs.Measurement(health=False)
    state, action, detail = _decide(m, {"started_ever": True, "consecutive_failures": 9},
                                    operator_intent="STOPPED")
    assert action == gs.ACT_PASSIVE
    assert state == gs.PASSIVE_STOPPED
    assert "STOP" in detail
    # A finished job is not a licence to start one either.
    assert _decide(gs.Measurement(), {}, operator_intent="STOPPED")[1] == gs.ACT_PASSIVE


def test_stop_still_reports_a_running_gateway_as_healthy():
    """Stopping gameplay must not make a working service look broken."""
    m = gs.Measurement(port_pid=9, port_name="node.exe", health=True)
    state, action, _ = _decide(m, {}, operator_intent="STOPPED")
    assert (state, action) == (gs.HEALTHY, gs.ACT_PASSIVE)


def test_no_credential_refuses_to_start_rather_than_starting_a_401_machine():
    state, action, detail = _decide(gs.Measurement(), {}, has_credential=False)
    assert (state, action) == (gs.NO_CREDENTIAL, gs.ACT_NO_CREDENTIAL)
    assert gs.ENV_PASSWORD in detail


def test_health_answering_with_no_visible_listener_is_reused_not_duplicated():
    """A port query that lost the race must not become a second gateway."""
    m = gs.Measurement(port_pid=0, health=True)
    assert _decide(m)[1] == gs.ACT_REUSE


# --------------------------------------------------------------------- the launch plan


def test_the_plan_never_pins_a_model_and_never_disables_auth(tmp_path):
    """Only the measured flags.  ``--model`` would override every escalation's own choice."""
    cli = tmp_path / "cli" / "bin" / "codebuddy"
    cli.parent.mkdir(parents=True)
    cli.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    app = tmp_path / "app.asar"
    app.parent.mkdir(parents=True, exist_ok=True)
    app.touch()
    (tmp_path / "app.asar.unpacked" / "cli" / "bin").mkdir(parents=True, exist_ok=True)
    (tmp_path / "app.asar.unpacked" / "cli" / "bin" / "codebuddy").write_text("x", encoding="utf-8")

    env = {gs.ENV_APP_PATH: str(app), gs.ENV_NODE: "node.exe"}
    plan = gs.build_plan(tmp_path, port=8080, log_path=tmp_path / "gw.log", env=env)
    argv = list(plan.argv)
    assert argv[2:] == ["--serve", "--port", "8080", "--session-id", gs.SESSION_ID]
    assert "--model" not in argv
    assert "none" not in argv
    assert "--auth" not in argv


def test_no_cli_on_disk_is_a_refusal_that_says_where_to_look(tmp_path):
    with pytest.raises(gs.GatewayStartRefused) as excinfo:
        gs.build_plan(tmp_path, log_path=tmp_path / "gw.log", env={gs.ENV_APP_PATH: str(tmp_path)})
    assert "WORKBUDDY_GATEWAY_CONTRACT" in str(excinfo.value)


def test_the_persisted_launch_record_carries_no_credential(tmp_path):
    """A password that reaches this file has reached the repository's neighbourhood."""
    plan = gs.LaunchPlan(argv=("node", "codebuddy", "--serve"), cwd=tmp_path,
                         log_path=tmp_path / "gw.log")
    blob = json.dumps(plan.as_record(), ensure_ascii=False)
    assert "password" not in blob.lower()
    assert "CODEBUDDY" not in blob


# --------------------------------------------------------------------- the service pass


class _Spawns:
    """A spawn seam that records the plan instead of starting a process."""

    def __init__(self, pid=4242):
        self.plan = None
        self.calls = 0
        self.pid = pid

    def __call__(self, plan):
        self.calls += 1
        self.plan = plan
        return self.pid


def _service(tmp_path, *, health, port=(0, ""), alive=False, spawn=None, state=None,
             killed=None):
    path = tmp_path / "gateway_service.json"
    if state is not None:
        path.write_text(json.dumps(state), encoding="utf-8")
    service = gs.GatewayService(
        tmp_path,
        state_path=path,
        log_path=tmp_path / "gateway.log",
        env={gs.ENV_PASSWORD: "x", gs.ENV_APP_PATH: str(tmp_path)},
        spawn=spawn or _Spawns(),
        port_owner=lambda: port,
        # The real probe returns ``(answer, reason)``; a seam that returned a bare bool
        # would be testing an interface the service does not have.
        probe=lambda: (health, "seam"),
        alive=lambda pid: alive,
        kill=lambda pid: (killed if killed is not None else []).append(pid) or True,
        clock=lambda: 1000.0,
    )
    # The CLI must exist for a spawn to be attempted; the plan builder is measured above.
    (tmp_path / "cli" / "bin").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cli" / "bin" / "codebuddy").write_text("x", encoding="utf-8")
    return service


def test_a_missing_gateway_is_started_once_and_only_once(tmp_path):
    """The whole P0 §二 in one test: nothing running → one gateway → the record says so."""
    spawns = _Spawns()
    # The spawned process is alive and simply has not bound the port yet -- the normal
    # first seconds of ``--serve``.
    service = _service(tmp_path, health=False, spawn=spawns, alive=True)
    record = service.ensure(operator_intent="RUNNING")
    assert spawns.calls == 1
    assert record["pid"] == 4242
    assert record["state"] == gs.STARTING
    assert record["started_ever"] is True

    # The very next pass, with the port still not bound, must NOT start a second one.
    second = service.ensure(operator_intent="RUNNING")
    assert spawns.calls == 1, "a second pass inside the grace window must not respawn"
    assert second["state"] == gs.STARTING, "still inside the grace window: wait it out"


def test_a_spawn_that_dies_immediately_is_reported_offline_and_not_respawned_at_once(tmp_path):
    """The paired case: pid gone, port free, one failure -- honest OFFLINE, no spawn loop."""
    spawns = _Spawns()
    service = _service(tmp_path, health=False, spawn=spawns, alive=False)
    service.ensure(operator_intent="RUNNING")
    assert spawns.calls == 1
    second = service.ensure(operator_intent="RUNNING")
    assert second["state"] == gs.OFFLINE
    assert second.get("spawned") is False
    assert spawns.calls == 1, "one failure is information (§六), not a licence to respawn"


def test_the_gateway_log_is_never_inside_the_repository():
    """The gateway's banner contains its effective password.

    Measured 2026-09-18 on the first live launch: ``codebuddy --serve`` printed
    ``Password <24 bytes of base64url>`` to stdout.  The natural destination, beside the
    panel's logs, appeared in ``git status`` as an untracked file inside the tree -- one
    ``git add`` from committing a live credential.  This is the one path in the gateway's
    world that is deliberately not derived from the project directory.
    """
    repo = Path(gs.__file__).resolve().parents[1]
    log = gs.default_log_path()
    assert repo not in log.parents, f"the gateway log must live outside {repo}, got {log}"


def test_the_log_location_can_be_moved_for_a_test_or_a_locked_machine(monkeypatch, tmp_path):
    monkeypatch.setenv(gs.ENV_LOG_DIR, str(tmp_path))
    assert gs.default_log_path() == tmp_path / "gateway.log"


def test_the_reason_it_gives_agrees_with_the_count_it_records(tmp_path):
    """The first live acceptance run recorded ``failures: 1`` while its own detail read
    "连续失败 0/3".  A window that contradicts the file an audit reads is the defect class
    this工单 is about, so the ladder advances before the sentence is written."""
    spawns = _Spawns()
    service = _service(tmp_path, health=False, spawn=spawns,
                       state={"started_ever": True, "consecutive_failures": 0})
    record = service.ensure()
    assert record["consecutive_failures"] == 1
    assert "连续失败 1/3" in record["detail"], record["detail"]
    second = service.ensure()
    assert second["consecutive_failures"] == 2
    assert "连续失败 2/3" in second["detail"], second["detail"]


def test_a_healthy_gateway_is_adopted_without_spawning(tmp_path):
    spawns = _Spawns()
    service = _service(tmp_path, health=True, port=(22268, "node.exe"), spawn=spawns)
    record = service.ensure(operator_intent="RUNNING")
    assert spawns.calls == 0
    assert record["state"] == gs.HEALTHY
    assert record["pid"] == 22268


def test_stop_never_spawns(tmp_path):
    spawns = _Spawns()
    service = _service(tmp_path, health=False, spawn=spawns)
    record = service.ensure(operator_intent="STOPPED")
    assert spawns.calls == 0
    assert record["state"] == gs.PASSIVE_STOPPED


def test_the_failure_count_is_advanced_by_the_probe_and_cleared_by_recovery(tmp_path):
    service = _service(tmp_path, health=False)
    first = service.ensure()
    assert first["consecutive_failures"] == 1
    second = service.ensure()
    assert second["consecutive_failures"] == 2

    recovered = _service(tmp_path, health=True, port=(7, "node.exe"),
                         state={"consecutive_failures": 2, "started_ever": True})
    assert recovered.ensure()["consecutive_failures"] == 0


def test_a_port_conflict_is_persisted_and_keeps_the_other_process(tmp_path):
    """No kill path may be reachable for a pid this service did not launch."""
    killed: list[int] = []
    spawns = _Spawns()
    service = _service(tmp_path, health=False, port=(1234, "other.exe"), spawn=spawns,
                       state={"pid": 4242, "started_ever": True, "launched_at": 800.0},
                       killed=killed)
    service.ensure()
    record = service.record()
    assert record["state"] == gs.PORT_CONFLICT
    assert record["port_pid"] == 1234
    assert spawns.calls == 0
    assert killed == [], "an unknown port owner must never be killed"


def test_a_wedged_gateway_of_ours_is_the_only_pid_that_is_killed(tmp_path):
    """The one legitimate kill: our own pid, past its grace window, holding the port."""
    killed: list[int] = []
    spawns = _Spawns(pid=9090)
    service = _service(tmp_path, health=False, port=(4242, "node.exe"), spawn=spawns,
                       state={"pid": 4242, "started_ever": True, "launched_at": 800.0},
                       killed=killed)
    record = service.ensure()
    assert killed == [4242]
    assert record["state"] == gs.STARTING
    assert record["pid"] == 9090
    assert spawns.calls == 1
