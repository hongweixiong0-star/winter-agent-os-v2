"""The panel as the gateway's lifecycle host (P0 §二).

The operator's requirement is one sentence: starting the window must be the only action.
That makes the window responsible for a process it did not own before -- and the two ways
that goes wrong are both about *when* to start: never (the manual ``codebuddy --serve`` this
replaces) and twice (two instances fighting over 8080).  These tests pin both.

Every test here redirects ``PANEL_LOG_PATH``.  That is not tidiness: the first version of
this file did not, and running it wrote a fake lifecycle -- pid 31337, a launch out of a
pytest temp directory -- into the production ``learning/control_panel/gateway.json``.  The
project had already recorded this exact failure ("a value that a test wrote is not a
measurement of anything"), which is why both probe paths are *derived* from the log path at
call time rather than stored as constants.  A test that does not redirect them is a test
that overwrites the operator's evidence.
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from tools import control_panel as cp
from winter_agent_v2 import gateway_service as gs
from winter_agent_v2.workbuddy_bridge import Availability


class _Spawns:
    def __init__(self, pid=31337):
        self.calls = 0
        self.pid = pid

    def __call__(self, plan):
        self.calls += 1
        return self.pid


class _FakeBridge:
    """The panel measures health itself; this is that measurement, made controllable.

    Returns the *real* ``Availability`` rather than a lookalike: the panel reads it with
    ``bool(probe)``, and a ``SimpleNamespace`` stand-in is always truthy -- which made the
    first version of these tests report HEALTHY for a gateway that was down.  A fake that
    does not share the interface it fakes is a fake that tests nothing.
    """

    available = True
    reason = "OK"

    def __init__(self, *args, **kwargs):
        pass

    def is_available(self):
        return Availability(available=type(self).available, reason=type(self).reason)

    def status(self, job_id):
        raise AssertionError("no job should be watched in a lifecycle test")


def _probes(tmp, *, health, port=(0, ""), alive=False, intent="RUNNING", spawns=None):
    """A probe loop over a real ``GatewayService``, with every effect and path replaced."""
    tmp = Path(tmp)
    (tmp / "cli" / "bin").mkdir(parents=True, exist_ok=True)
    (tmp / "cli" / "bin" / "codebuddy").write_text("x", encoding="utf-8")
    service = gs.GatewayService(
        tmp,
        state_path=tmp / "gateway_service.json",
        log_path=tmp / "gateway.log",
        env={gs.ENV_PASSWORD: "x", gs.ENV_APP_PATH: str(tmp)},
        spawn=spawns or _Spawns(),
        port_owner=lambda: port,
        probe=lambda: (health, "seam"),
        alive=lambda pid: alive,
        # Hermetic: the suite must not depend on a real desktop being installed, nor on a
        # real process table being queried by the identity check.
        runs=lambda pid, needle: True,
        desktop_exe=lambda: "",
        clock=lambda: 1000.0,
    )
    probes = cp.PanelProbes(tmp, device=None, gateway_service=service)
    return probes, service


class _Redirected(unittest.TestCase):
    """Base: every probe path lands in a temp directory, never in production."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._paths = patch.multiple(
            cp,
            PANEL_LOG_PATH=self.tmp / "panel.log",
        )
        self._paths.start()
        self.addCleanup(self._paths.stop)
        self.addCleanup(self._tmp.cleanup)
        self._intent = patch.object(cp, "load_operator_intent", return_value="RUNNING")
        self.intent = self._intent.start()
        self.addCleanup(self._intent.stop)

    def _run(self, *, health, port=(0, ""), alive=False, spawns=None):
        _FakeBridge.available = health
        _FakeBridge.reason = "OK" if health else "GATEWAY_UNREACHABLE"
        with patch("winter_agent_v2.workbuddy_bridge.WorkBuddyBridge", _FakeBridge):
            probes, service = _probes(self.tmp, health=health, port=port, alive=alive,
                                      spawns=spawns)
            probes._poll_gateway()
        return probes, service

    def probe_file(self) -> dict:
        return json.loads((self.tmp / "gateway.json").read_text(encoding="utf-8"))


class TheWindowStartsTheGateway(_Redirected):
    def test_the_state_path_follows_the_log_path_it_is_derived_from(self):
        """A constant that stays in production while every test redirects the log path is a
        constant that a test writes."""
        self.assertEqual(cp.gateway_service_state_path(), self.tmp / "gateway_service.json")

    def test_the_gateway_log_is_never_inside_the_repository(self):
        """The gateway's banner contains its effective password.

        Measured 2026-09-18: ``codebuddy --serve`` printed ``Password <24 bytes>`` to stdout,
        and the natural destination -- beside ``panel.log`` -- showed up in ``git status`` as
        an untracked file in the tree.  A credential one ``git add`` from being committed is
        a credential in the repository, so this path is the one thing here that is *not*
        derived from the panel's log directory.
        """
        log = cp.gateway_service_log_path()
        repo = Path(cp.__file__).resolve().parents[1]
        self.assertFalse(
            repo == log or repo in log.parents,
            f"the gateway log must live outside {repo}, got {log}",
        )

    def test_a_window_that_finds_no_gateway_starts_one(self):
        """§二.  This is the whole工单: no manual ``codebuddy --serve`` anywhere."""
        spawns = _Spawns()
        probes, _ = self._run(health=False, spawns=spawns)
        self.assertEqual(spawns.calls, 1, "GUI 启动必须自动拉起网关")
        lifecycle = probes.lifecycle()
        self.assertEqual(lifecycle["action"], gs.ACT_START)
        self.assertEqual(lifecycle["pid"], 31337)

    def test_a_healthy_gateway_is_reused_and_never_replaced(self):
        """§五.  One instance: an existing healthy gateway is adopted, not restarted."""
        spawns = _Spawns()
        probes, _ = self._run(health=True, port=(22268, "node.exe"), spawns=spawns)
        self.assertEqual(spawns.calls, 0)
        self.assertEqual(probes.lifecycle()["state"], gs.HEALTHY)
        self.assertEqual(probes.lifecycle()["pid"], 22268)

    def test_the_second_pass_does_not_start_a_second_gateway(self):
        """§五.  ``Gateway probe 失败一次 → 再起一个`` is the failure this forbids."""
        spawns = _Spawns()
        _FakeBridge.available = False
        with patch("winter_agent_v2.workbuddy_bridge.WorkBuddyBridge", _FakeBridge):
            probes, _ = _probes(self.tmp, health=False, alive=True, spawns=spawns)
            probes._poll_gateway()
            probes._gateway_next_at = None  # bypass the probe cadence, not the launch guard
            probes._poll_gateway()
        self.assertEqual(spawns.calls, 1)

    def test_an_unknown_port_owner_is_reported_and_never_killed(self):
        """§三 rule 4.  A conflict is a state to surface, not a process to end."""
        spawns = _Spawns()
        probes, _ = self._run(health=False, port=(999, "other.exe"), spawns=spawns)
        self.assertEqual(spawns.calls, 0)
        self.assertEqual(probes.lifecycle()["state"], gs.PORT_CONFLICT)
        self.assertEqual(self.probe_file()["lifecycle"]["state"], gs.PORT_CONFLICT)

    def test_a_stopped_operator_is_not_overruled_by_the_watchdog(self):
        """§二十五.  STOP outranks the lifecycle owner."""
        self.intent.return_value = "STOPPED"
        spawns = _Spawns()
        probes, _ = self._run(health=False, spawns=spawns)
        self.assertEqual(spawns.calls, 0)
        self.assertEqual(probes.lifecycle()["state"], gs.PASSIVE_STOPPED)

    def test_the_health_file_still_answers_only_the_health_question(self):
        """The truth audit grades this file; a pid or a restart count at its top level would
        let ``gateway_health`` claim more than a health check measured."""
        probes, _ = self._run(health=True, port=(7, "node.exe"))
        published = self.probe_file()
        self.assertIs(published["available"], True)
        self.assertEqual(published["consecutive_failures"], 0)
        # The lifecycle lives beside it, not inside the health verdict.
        self.assertNotIn("pid", published)
        self.assertIn("pid", published["lifecycle"])

    def test_while_a_launch_is_in_flight_the_probe_keeps_looking(self):
        """Backing off during STARTING would be the worst time to stop watching: the point
        of starting the gateway is to see it bind."""
        probes, _ = self._run(health=False, alive=True)
        self.assertEqual(probes.lifecycle()["state"], gs.STARTING)
        self.assertEqual(self.probe_file()["backoff_seconds"],
                         cp.PanelProbes.GATEWAY_STARTING_INTERVAL)

    def test_an_unknown_intent_reads_as_stop_rather_than_start(self):
        """A reader that raises means we do not know what the operator asked for, and the
        passive answer is the safe one."""
        with patch.object(cp, "load_operator_intent", side_effect=ValueError("boom")):
            probes, _ = _probes(self.tmp, health=False)
            self.assertEqual(probes._intent(), "STOPPED")


if __name__ == "__main__":
    unittest.main()
