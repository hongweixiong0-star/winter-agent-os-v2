"""The GUI's own acceptance soak: the twelve conditions, and what "unmeasured" must mean.

The distinction this file mostly defends is that **not measured is not satisfied**.  A soak
whose console counter is unavailable, or whose window never saw AUTO run, must not come out
PASS: the operator asked for evidence, and a verdict that treats a missing measurement as a
passing one is the failure mode every other rule in this project exists to prevent.
"""

from __future__ import annotations

import json

import pytest

from winter_agent_v2 import gateway_soak as gs


GOOD = {
    "gui_pid": 4242,
    "gateway_pid": 99,
    "gateway_identity": True,
    "port_8080_owner": 99,
    "port_8080_name": "node.exe",
    "health": True,
    "lifecycle_state": "HEALTHY",
    "restart_count": 0,
    "duplicate_gateway_count": 0,
    "queue_pump_heartbeat": 12.0,
    "current_job_id": "d8ea0e44",
    "job_state": "WORKING",
    "auto_running": True,
    "topbar_word": "正常",
}


def _soak(tmp_path, *, window=900.0, contexts=None, consoles=None, launch_context="production"):
    """A soak fed from a scripted list of fact dicts, with no port, process or clock."""
    state = {"i": 0}

    def facts():
        seq = contexts or [GOOD]
        value = seq[min(state["i"], len(seq) - 1)]
        state["i"] += 1
        return dict(value)

    counter = None
    if consoles is not None:
        seq_c = list(consoles)

        def counter():  # noqa: F811 - the seam is optional
            return seq_c.pop(0) if len(seq_c) > 1 else (seq_c[0] if seq_c else 0)

    return gs.GatewaySoak(
        tmp_path,
        facts=facts,
        window_seconds=window,
        sample_every=1,
        evidence_path=tmp_path / gs.EVIDENCE_RELATIVE,
        console_counter=counter,
        launch_context=launch_context,
        clock=lambda: 1000.0,
    )


def _fill(soak, count, **overrides):
    for _ in range(count):
        soak.observe(overrides or None)
    return soak


# --------------------------------------------------------------------- the honest zero


def test_a_window_with_no_samples_is_incomplete_not_pass(tmp_path):
    """0 samples is the one case where every condition is unknown, and unknown is not met."""
    soak = _soak(tmp_path)
    verdict = soak.verdict()
    assert verdict["overall"] == gs.INCOMPLETE
    assert set(verdict["conditions"]) == {name for name, _ in gs.CONDITIONS}
    assert all(item["ok"] is None for item in verdict["conditions"].values())


def test_unmeasured_conditions_do_not_pass(tmp_path):
    """A fact nobody could read is unproven, not satisfied and not failed."""
    unreadable = dict(GOOD, auto_running=None, topbar_word="")
    soak = _fill(_soak(tmp_path, consoles=None), 5)
    soak.samples.clear()
    for _ in range(5):
        soak.observe(unreadable)
    verdict = soak.verdict()
    assert verdict["conditions"]["auto_gameplay"]["ok"] is None
    assert verdict["conditions"]["no_black_console"]["ok"] is None
    assert verdict["conditions"]["topbar_agrees"]["ok"] is None
    assert verdict["overall"] == gs.INCOMPLETE
    assert "未测量" in verdict["conditions"]["no_black_console"]["reason"]


def test_auto_measured_and_not_running_is_a_failure(tmp_path):
    """The operator asked for "AUTO继续Gameplay": readable-but-stopped is a real answer."""
    soak = _fill(_soak(tmp_path, consoles=[0]), 4)
    soak.samples.clear()
    for _ in range(4):
        soak.observe(dict(GOOD, auto_running=False))
    verdict = soak.verdict()
    assert verdict["conditions"]["auto_gameplay"]["ok"] is False
    assert verdict["overall"] == gs.FAIL


# --------------------------------------------------------------------- a good window


def test_a_clean_window_passes_all_twelve(tmp_path):
    soak = _fill(_soak(tmp_path, consoles=[0]), 12)
    verdict = soak.verdict()
    assert verdict["overall"] == gs.PASS, {
        name: item for name, item in verdict["conditions"].items() if not item["ok"]}


def test_the_sample_records_every_field_the_operator_listed(tmp_path):
    """§一 names the fields; a soak that omits one cannot answer §二's condition about it."""
    soak = _fill(_soak(tmp_path, consoles=[0]), 1)
    sample = soak.samples[0]
    for key in ("gui_pid", "gateway_pid", "gateway_identity", "port_8080_owner", "health",
                "restart_count", "duplicate_gateway_count", "queue_pump_heartbeat",
                "current_job_id", "job_state", "auto_running", "black_console_count"):
        assert key in sample, key


# --------------------------------------------------------------------- the failures


def test_a_second_gateway_is_a_failure_not_a_nuisance(tmp_path):
    """§二 condition 3.  Measured: a probe that fails once was answered by a second gateway."""
    soak = _fill(_soak(tmp_path, consoles=[0]), 5)
    bad = dict(GOOD, duplicate_gateway_count=1)
    soak.observe(bad)
    verdict = soak.verdict()
    assert verdict["conditions"]["single_gateway"]["ok"] is False
    assert verdict["overall"] == gs.FAIL


def test_a_port_held_by_something_else_is_a_failure(tmp_path):
    soak = _fill(_soak(tmp_path, consoles=[0]), 3)
    soak.observe(dict(GOOD, port_8080_owner=555))
    assert soak.verdict()["conditions"]["port_owner_legal"]["ok"] is False


def test_a_restart_loop_is_a_failure(tmp_path):
    soak = _fill(_soak(tmp_path, consoles=[0]), 3)
    soak.observe(dict(GOOD, restart_count=gs.MAX_RESTARTS + 1))
    assert soak.verdict()["conditions"]["no_restart_loop"]["ok"] is False


def test_a_pid_that_changes_without_a_restart_is_a_second_gateway(tmp_path):
    """§二 condition 10: a new pid that no restart explains is a spawn nobody asked for."""
    soak = _soak(tmp_path, consoles=[0])
    _fill(soak, 1)
    soak.observe(dict(GOOD, gateway_pid=1234))
    verdict = soak.verdict()
    assert verdict["conditions"]["no_extra_spawn_per_refresh"]["ok"] is False


def test_unreachable_health_takes_the_ratio_below_the_bar(tmp_path):
    soak = _fill(_soak(tmp_path, consoles=[0]), 10)
    for _ in range(4):
        soak.observe(dict(GOOD, health=False))
    verdict = soak.verdict()
    assert verdict["conditions"]["gateway_reachable"]["ok"] is False
    assert "71.4%" in verdict["conditions"]["gateway_reachable"]["reason"]


def test_a_stale_pump_heartbeat_is_a_failure(tmp_path):
    soak = _fill(_soak(tmp_path, consoles=[0]), 3)
    soak.observe(dict(GOOD, queue_pump_heartbeat=gs.PUMP_FRESH_SECONDS + 30))
    assert soak.verdict()["conditions"]["pump_ticking"]["ok"] is False


def test_a_fault_that_stopped_the_pump_fails_condition_eight(tmp_path):
    """§二 condition 8: gateway trouble must not stop the consumer."""
    soak = _fill(_soak(tmp_path, consoles=[0]), 3)
    soak.observe(dict(GOOD, health=False, queue_pump_heartbeat=None))
    verdict = soak.verdict()
    assert verdict["conditions"]["gateway_fault_does_not_block_auto"]["ok"] is False


def test_a_topbar_that_says_fine_while_the_gateway_is_down_fails_condition_twelve(tmp_path):
    """The operator's original complaint: 「WorkBuddy ● 正常」 while the gateway was gone."""
    soak = _fill(_soak(tmp_path, consoles=[0]), 3)
    soak.observe(dict(GOOD, health=False, topbar_word="正常"))
    assert soak.verdict()["conditions"]["topbar_agrees"]["ok"] is False


def test_two_active_jobs_for_one_capability_is_a_failure(tmp_path):
    soak = _soak(tmp_path, consoles=[0])
    soak.observe(dict(GOOD, duplicate_job_capabilities=["SPEND_STAMINA_ON_BEAST"]))
    verdict = soak.verdict()
    assert verdict["conditions"]["no_duplicate_job"]["ok"] is False
    assert "SPEND_STAMINA_ON_BEAST" in verdict["conditions"]["no_duplicate_job"]["reason"]


# --------------------------------------------------------------------- evidence file


def test_the_evidence_file_follows_the_existing_soak_conventions(tmp_path):
    """``tools/runtime_soak.py`` already defines what a soak record looks like."""
    soak = _fill(_soak(tmp_path, consoles=[0]), 2)
    soak.close()
    payload = json.loads((tmp_path / gs.EVIDENCE_RELATIVE).read_text(encoding="utf-8"))
    for key in ("started_at", "finished_at", "duration_minutes", "sample_count", "samples"):
        assert key in payload, key
    assert payload["sample_count"] == 2
    assert payload["verdict"]["overall"] in (gs.PASS, gs.INCOMPLETE, gs.FAIL)
    assert payload["kind"] == "GatewaySoakAcceptance"


def test_a_development_launch_records_the_limitation_rather_than_hiding_it(tmp_path):
    """§三/§九: a window a development host started is not acceptance evidence."""
    soak = _fill(_soak(tmp_path, consoles=[0], launch_context="development"), 2)
    payload = soak.close()
    assert payload["launch_context"] == "development"
    assert "DEVELOPMENT_ENV_LIMITATION" in payload["development_env_limitation"]


def test_a_production_launch_carries_no_limitation_note(tmp_path):
    soak = _fill(_soak(tmp_path, consoles=[0], launch_context="production"), 2)
    assert soak.close()["development_env_limitation"] == ""


def test_the_window_expires_on_its_own_clock(tmp_path):
    """The soak decides when it is done; nothing outside it has to remember to stop it."""
    moving = {"t": 0.0}
    soak = gs.GatewaySoak(tmp_path, facts=lambda: dict(GOOD), window_seconds=30.0,
                          sample_every=1, evidence_path=tmp_path / "e2.json",
                          clock=lambda: moving["t"])
    soak.observe()
    assert soak.expired() is False, "0 seconds into a 30-second window is not expired"
    moving["t"] = 31.0
    assert soak.expired() is True

    closed = soak.close()
    assert closed["complete"] is True
    assert closed["duration_minutes"] == pytest.approx(31.0 / 60.0, abs=0.01)


def test_a_failing_fact_reader_is_recorded_not_silently_skipped(tmp_path):
    """A sampler that dies quietly would leave a short window that still looked complete."""
    state = {"n": 0}

    def facts():
        state["n"] += 1
        if state["n"] == 2:
            raise RuntimeError("boom")
        return dict(GOOD)

    soak = gs.GatewaySoak(tmp_path, facts=facts, sample_every=1,
                          evidence_path=tmp_path / "e.json", clock=lambda: 1.0)
    soak.observe()
    soak.observe()
    soak.observe()
    assert len(soak.samples) == 2
    assert any("boom" in a for a in soak.anomalies)
