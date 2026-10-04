"""The local model must stay resident, and must never be reloaded for nothing.

Measured 2026-10-04: nothing supervised ``llama-server``, so it was down for 24 hours while
the panel polled ``/health`` every fifteen seconds and reported the outage it could not fix.
These tests pin the four decisions that make a supervisor safe to run unattended: adopt rather
than reload, never judge a launch before it can load, never let a failed spawn become a storm,
and do nothing at all when the operator has switched the planner off.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from winter_agent_v2 import gui_model_service as module
from winter_agent_v2.gui_model_service import (
    ACT_PASSIVE, ACT_REUSE, ACT_START, ACT_WAIT,
    BACKOFF, DISABLED, HEALTHY, STARTUP_GRACE_SECONDS, STARTING,
    GuiModelService, plan_from_config,
)

ENDPOINT = "http://127.0.0.1:18080"


def write_config(root: Path, *, enabled: bool = True, endpoint: str = ENDPOINT) -> Path:
    config = root / "config" / "v2.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        json.dumps({"local_planner": {"enabled": enabled, "endpoint": endpoint,
                                      "model": "UI-Venus-2-9B"}}),
        encoding="utf-8",
    )
    return config


class Harness:
    """A service with every effect stubbed, so no test needs a port, a process or a GPU."""

    def __init__(self, tmp_path: Path, *, enabled: bool = True, endpoint: str = ENDPOINT,
                 health: bool | None = False, reason: str = "URLError",
                 spawn_raises: bool = False) -> None:
        self.root = tmp_path
        self.config = write_config(tmp_path, enabled=enabled, endpoint=endpoint)
        self.now = 1000.0
        self.spawned: list[list[str]] = []
        self.spawn_raises = spawn_raises
        self.health = health
        self.reason = reason
        self.probes = 0
        self.service = GuiModelService(
            tmp_path,
            config_path=self.config,
            state_path=tmp_path / "learning" / "gui_model_service.json",
            log_path=tmp_path / "learning" / "launcher.log",
            launcher=tmp_path / "tools" / "launch_gui_model_server.py",
            python="PY",
            probe=self._probe,
            spawn=self._spawn,
            port_owner=lambda port: (4321, "llama-server.exe"),
            clock=lambda: self.now,
        )

    def _probe(self) -> tuple[bool | None, str]:
        self.probes += 1
        return self.health, self.reason

    def _spawn(self, argv: list[str], log_path: Path) -> int:
        self.spawned.append(list(argv))
        if self.spawn_raises:
            raise OSError("no VRAM")
        return 4242

    def pass_once(self) -> dict:
        return self.service.ensure()


# -- adopt rather than reload -----------------------------------------------------------

def test_a_healthy_model_is_adopted_and_never_started(tmp_path: Path) -> None:
    """The reason the model is resident at all: a repin must not cost a 5.5 GB reload."""
    h = Harness(tmp_path, health=True, reason="")
    record = h.pass_once()
    assert record["state"] == HEALTHY
    assert record["action"] == ACT_REUSE
    assert h.spawned == []
    assert record["port_pid"] == 4321, "a healthy service records the pid it can verify"


def test_repeated_healthy_passes_never_claim_a_spawn(tmp_path: Path) -> None:
    """Every pass over a resident model must read as adoption, not as a restart."""
    h = Harness(tmp_path, health=True, reason="")
    records = [h.pass_once() for _ in range(5)]
    assert h.spawned == []
    assert [r["action"] for r in records] == [ACT_REUSE] * 5
    assert not any(r["spawned"] for r in records)


# -- never judge a launch before it can load --------------------------------------------

def test_a_down_model_is_started_exactly_once(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    first = h.pass_once()
    assert first["action"] == ACT_START
    assert first["state"] == STARTING
    assert h.spawned == [["PY", str(tmp_path / "tools" / "launch_gui_model_server.py")]]


def test_a_second_pass_inside_the_grace_does_not_start_a_second_server(tmp_path: Path) -> None:
    """The one way this service could make the machine worse: two 5.9 GB servers."""
    h = Harness(tmp_path)
    h.pass_once()
    h.now += 5.0                       # the probe's own cadence; the model is still loading
    second = h.pass_once()
    assert len(h.spawned) == 1, "a launch in flight must not be joined by another"
    assert second["action"] == ACT_WAIT
    assert second["state"] == STARTING


def test_the_grace_is_long_enough_for_a_cold_load(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.pass_once()
    h.now += STARTUP_GRACE_SECONDS - 1.0
    assert h.pass_once()["action"] == ACT_WAIT
    assert len(h.spawned) == 1


# -- a failed attempt climbs a bounded ladder -------------------------------------------

def test_a_still_down_model_climbs_the_ladder_instead_of_hammering(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.pass_once()
    waits: list[float] = []
    for _ in range(4):
        h.now = h.service.record()["next_attempt_at"] + 0.1
        record = h.pass_once()
        waits.append(round(record["next_attempt_at"] - h.now, 1))
    assert all(step >= STARTUP_GRACE_SECONDS for step in waits), waits
    assert waits == sorted(waits), f"the ladder must not shorten: {waits}"
    assert len(h.spawned) == 5


def test_the_ladder_is_bounded(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.pass_once()
    for _ in range(12):
        h.now = h.service.record()["next_attempt_at"] + 0.1
        h.pass_once()
    assert h.service.record()["consecutive_failures"] <= 100
    ceiling = h.service.record()["next_attempt_at"] - h.now
    assert ceiling <= max(*module.START_BACKOFF, STARTUP_GRACE_SECONDS) + 1.0


def test_a_spawn_that_raises_is_reported_and_still_paces_itself(tmp_path: Path) -> None:
    """A machine out of VRAM must not be asked again on the next fifteen-second pass."""
    h = Harness(tmp_path, spawn_raises=True)
    record = h.pass_once()
    assert record["state"] == BACKOFF
    assert "OSError" in record["detail"]
    assert record["next_attempt_at"] > h.now
    h.now += 1.0
    assert h.pass_once()["action"] == ACT_WAIT


def test_a_model_that_comes_back_resets_the_ladder(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.pass_once()
    h.now = h.service.record()["next_attempt_at"] + 0.1
    h.pass_once()
    assert h.service.record()["consecutive_failures"] == 2
    h.health = True
    h.reason = ""
    record = h.pass_once()
    assert record["action"] == ACT_REUSE
    assert record["consecutive_failures"] == 0
    assert record["next_attempt_at"] == 0.0


# -- the operator's off switch is absolute ----------------------------------------------

def test_a_disabled_planner_is_never_started(tmp_path: Path) -> None:
    h = Harness(tmp_path, enabled=False)
    record = h.pass_once()
    assert record["state"] == DISABLED
    assert record["action"] == ACT_PASSIVE
    assert h.spawned == []


def test_an_unreadable_config_reads_as_disabled_rather_than_a_guess(tmp_path: Path) -> None:
    plan = plan_from_config(tmp_path)
    assert plan.enabled is False
    assert plan.actionable is False


def test_an_endpoint_with_no_port_is_not_actionable(tmp_path: Path) -> None:
    plan = plan_from_config(tmp_path, write_config(tmp_path, endpoint="http://127.0.0.1"))
    assert plan.endpoint == "http://127.0.0.1"
    assert plan.port == 0
    assert plan.actionable is False


def test_the_configured_endpoint_supplies_the_port(tmp_path: Path) -> None:
    assert plan_from_config(tmp_path, write_config(tmp_path)).port == 18080


# -- the caller's own answer is used, not re-asked --------------------------------------

def test_the_panels_own_health_answer_is_reused(tmp_path: Path) -> None:
    """The panel already polled ``/health``; asking again would be a second round trip."""
    h = Harness(tmp_path, health=True, reason="")
    record = h.service.ensure(observed=(True, ""))
    assert record["state"] == HEALTHY
    assert h.probes == 0


def test_a_caller_supplied_outage_still_starts_the_model(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    record = h.service.ensure(observed=(False, "ConnectionRefusedError"))
    assert record["action"] == ACT_START
    assert record["health_reason"] == "ConnectionRefusedError"


# -- the record is evidence -------------------------------------------------------------

def test_the_record_is_durable_and_names_what_it_is_about(tmp_path: Path) -> None:
    h = Harness(tmp_path, health=True, reason="")
    h.pass_once()
    written = json.loads(
        (tmp_path / "learning" / "gui_model_service.json").read_text(encoding="utf-8")
    )
    assert written["endpoint"] == ENDPOINT
    assert written["model"] == "UI-Venus-2-9B"
    assert written["port"] == 18080
    assert written["launcher"].endswith("launch_gui_model_server.py")
    assert written["checked_at"]
    assert written["state"] == HEALTHY


def test_a_missing_record_is_not_an_error(tmp_path: Path) -> None:
    service = GuiModelService(tmp_path, config_path=write_config(tmp_path))
    assert service.record() == {}


def test_a_corrupt_record_is_read_as_nothing_known(tmp_path: Path) -> None:
    service = GuiModelService(tmp_path, config_path=write_config(tmp_path),
                              state_path=tmp_path / "broken.json")
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    assert service.record() == {}


# -- it runs on the probe thread, so it may not raise -----------------------------------

@pytest.mark.parametrize("boom", [OSError, ValueError, RuntimeError])
def test_a_probe_or_spawn_that_explodes_never_reaches_the_probe_thread(
    tmp_path: Path, boom: type[Exception]
) -> None:
    """This runs beside the gateway and device probes; an exception here freezes the window."""
    def exploding_probe() -> tuple[bool | None, str]:
        raise boom("nope")

    def exploding_spawn(argv: list[str], log_path: Path) -> int:
        raise boom("nope")

    service = GuiModelService(
        tmp_path, config_path=write_config(tmp_path),
        state_path=tmp_path / "s.json", log_path=tmp_path / "l.log",
        probe=exploding_probe, spawn=exploding_spawn, clock=lambda: 1.0,
    )
    record = service.ensure()
    assert record["state"] == BACKOFF
    assert boom.__name__ in record["detail"]


def test_the_spawn_uses_the_wrapper_that_decides_about_consoles() -> None:
    """``tools/check_wiring.py`` fails the build for a raw ``subprocess`` call; this pins it."""
    source = (Path(module.__file__)).read_text(encoding="utf-8")
    assert "winproc.spawn_detached" in source
    assert "subprocess.Popen(" not in source
