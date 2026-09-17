"""Startup semantics: 启动 GUI = 启动整个无人值守系统.

Operator directive 2026-09-18, in ten requirements.  Three of them are about the
*order* the window starts in and about what the operator's own stop has to
survive, and neither is visible to a pure function:

* a GUI restart must not undo a stop ("点停止 → 刷新/重启 → 又自动开起来" was
  named as unacceptable) -- so the intent is on disk and the auto-start reads it;
* a refusing WorkBuddy gateway must not stop the game -- so the gateway is an
  *auxiliary* preflight section and the core verdict ignores it;
* closing the window must not leave an orphan AUTO worker -- and the worker the
  panel holds is a venv stub whose child is the one really driving the device,
  so terminating the stub is not enough.

Every fake below says which measurement it came from.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import control_panel as panel  # noqa: E402
from tools import preflight  # noqa: E402


class OperatorIntentStateTest(unittest.TestCase):
    """The one piece of operator intent that outlives the window."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "control_panel_state.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_fresh_install_is_running(self):
        self.assertEqual(panel.load_operator_intent(self.path), "RUNNING")

    def test_a_stop_and_a_pause_both_survive_a_restart(self):
        panel.save_operator_intent(self.path, "STOPPED", "user pressed stop")
        self.assertEqual(panel.load_operator_intent(self.path), "STOPPED")
        panel.save_operator_intent(self.path, "PAUSED", "user pressed pause")
        self.assertEqual(panel.load_operator_intent(self.path), "PAUSED")

    def test_an_unknown_value_is_not_guessed(self):
        # A hand-edited or future value must not be read as "run" by accident.
        self.path.write_text(json.dumps({"operator_intent": "WHATEVER"}), encoding="utf-8")
        self.assertEqual(panel.load_operator_intent(self.path), "RUNNING")
        self.assertRaises(ValueError, panel.save_operator_intent, self.path, "WHATEVER")

    def test_the_two_writers_do_not_erase_each_other(self):
        # Task selection and operator intent are written from different controls;
        # a whole-file writer would silently drop the other field.
        panel.save_operator_intent(self.path, "STOPPED", "user pressed stop")
        panel.save_task_selection(self.path, {"采集": True, "邮件": False}, continuous=True)
        self.assertEqual(panel.load_operator_intent(self.path), "STOPPED")
        self.assertTrue(panel.load_continuous_selection(self.path))
        self.assertTrue(panel.load_task_selection(self.path, ("采集", "邮件"))["采集"])

    def test_saving_the_intent_keeps_the_task_selection(self):
        panel.save_task_selection(self.path, {"采集": True, "邮件": False}, continuous=False)
        panel.save_operator_intent(self.path, "PAUSED", "user pressed pause")
        self.assertFalse(panel.load_continuous_selection(self.path))
        self.assertFalse(panel.load_task_selection(self.path, ("采集", "邮件"))["邮件"])


def fake_sections(*, interpreter: bool = True, device: bool = True, gateway: bool = True) -> dict:
    return {
        "interpreter": {"ok": interpreter, "exe": r"E:\x\python.exe", "reason": "OK",
                        "present": [], "missing": [] if interpreter else ["maa"],
                        "errors": {}, "fell_back_from": None},
        "device": {"ok": device, "serial": "127.0.0.1:7555", "resolution": [720, 1280],
                   "foreground": "com.gof.china", "error": None if device else "DEVICE_NOT_CONNECTED"},
        "gateway": {"ok": gateway, "reason": "OK" if gateway else "AUTH_REJECTED",
                    "base_url": "http://127.0.0.1:8080", "detail": {}},
    }


class PreflightContractTest(unittest.TestCase):
    """Core decides AUTO; auxiliary is reported and retried."""

    def _report(self, **flags) -> dict:
        sections = fake_sections(**flags)
        with mock.patch.object(preflight, "device_report", return_value=sections["device"]), \
             mock.patch.object(preflight, "gateway_report", return_value=sections["gateway"]), \
             mock.patch.object(preflight.runtime_env, "resolve_for_project",
                               return_value=type("R", (), {
                                   "ok": flags.get("interpreter", True), "reason": "OK",
                                   "python_exe": Path(r"E:\x\python.exe"), "present": (),
                                   "missing": (), "errors": {}, "fell_back_from": None,
                                   "candidates": (),
                               })()):
            return preflight.report()

    def test_the_core_is_the_interpreter_and_the_device(self):
        data = self._report()
        self.assertEqual(data["core_sections"], ["interpreter", "device"])
        self.assertEqual(data["aux_sections"], ["gateway"])

    def test_a_refusing_gateway_does_not_stop_auto(self):
        # The requirement, stated with fakes: everything core is fine, the gateway
        # is refusing, and the answer is still "AUTO may run".
        data = self._report(gateway=False)
        self.assertTrue(data["core_ok"])
        self.assertTrue(data["ready_for_auto"])
        self.assertEqual(data["aux_unavailable"], ["gateway"])
        self.assertEqual(data["blockers"], [])

    def test_a_dead_device_does_stop_auto(self):
        data = self._report(device=False, gateway=True)
        self.assertFalse(data["core_ok"])
        self.assertEqual(data["blockers"], ["device"])

    def test_a_broken_interpreter_does_stop_auto(self):
        data = self._report(interpreter=False)
        self.assertFalse(data["core_ok"])
        self.assertEqual(data["blockers"], ["interpreter"])

    def test_gateway_failure_is_never_a_core_blocker_even_alone(self):
        for flags in ({"gateway": False}, {"gateway": False, "device": False},
                      {"gateway": False, "interpreter": False}):
            with self.subTest(flags=flags):
                self.assertNotIn("gateway", self._report(**flags)["blockers"])


class _FakeProcess:
    """Enough of a ``Popen`` for the tree-kill path."""

    def __init__(self, pid: int = 4321, alive: bool = True) -> None:
        self.pid = pid
        self._alive = alive
        self.terminated = False
        self.waited = False

    def poll(self):
        return None if self._alive else 0

    def terminate(self):
        self.terminated = True
        self._alive = False

    def wait(self, timeout=None):
        self.waited = True
        return 0


class _Recorder:
    """A runtime store that remembers instead of writing production state."""

    def __init__(self) -> None:
        self.updates: list[dict] = []

    def update(self, **changes):
        self.updates.append(changes)

    def read(self):
        return {}


class WorkerTreeTest(unittest.TestCase):
    """Closing must not leave an orphan AUTO worker."""

    def _panel_stub(self):
        stub = panel.ControlPanel.__new__(panel.ControlPanel)
        stub.process = None
        stub.appendices = []
        stub._append = lambda text: stub.appendices.append(text)
        return stub

    def test_the_whole_tree_is_killed_not_just_the_venv_stub(self):
        stub = self._panel_stub()
        stub.process = _FakeProcess()
        calls = []

        def record(command, **kwargs):
            calls.append(command)
            return type("R", (), {"returncode": 0})()

        with mock.patch.object(panel, "_background_run", side_effect=record):
            stub._kill_worker_tree()
        if panel.os.name == "nt":
            self.assertEqual(calls, [["taskkill", "/PID", "4321", "/T", "/F"]])
        self.assertIsNone(stub.process)

    def test_an_already_dead_worker_is_just_forgotten(self):
        stub = self._panel_stub()
        stub.process = _FakeProcess(alive=False)
        with mock.patch.object(panel, "_background_run",
                               side_effect=AssertionError("must not run taskkill")):
            stub._kill_worker_tree()
        self.assertIsNone(stub.process)

    def test_a_failed_tree_kill_still_terminates_the_handle(self):
        stub = self._panel_stub()
        process = _FakeProcess()
        stub.process = process
        with mock.patch.object(panel, "_background_run",
                               return_value=type("R", (), {"returncode": 1})()):
            stub._kill_worker_tree()
        self.assertTrue(process.terminated)
        self.assertIsNone(stub.process)


class PanelLogTest(unittest.TestCase):
    """The window's narration has to be readable from outside the process."""

    def _stub(self):
        stub = panel.ControlPanel.__new__(panel.ControlPanel)
        stub.event_lines = []
        return stub

    def test_the_startup_narration_lands_on_disk(self):
        # The preflight verdict decides whether AUTO starts; taking the window's
        # word for it is not evidence.
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "panel.log"
            with mock.patch.object(panel, "PANEL_LOG_PATH", target):
                stub = self._stub()
                stub._append("预检·核心：Runtime OK · MuMu OK")
                stub._append("自动运行已启动")
            text = target.read_text(encoding="utf-8")
            self.assertIn("预检·核心", text)
            self.assertIn("自动运行已启动", text)

    def test_the_log_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "panel.log"
            with mock.patch.object(panel, "PANEL_LOG_PATH", target), \
                 mock.patch.object(panel, "PANEL_LOG_MAX_BYTES", 200):
                stub = self._stub()
                for index in range(50):
                    stub._append(f"line {index} " + "x" * 20)
            kept = target.read_text(encoding="utf-8").splitlines()
            self.assertLess(len(kept), 60)

    def test_a_log_that_cannot_be_written_never_raises(self):
        with mock.patch.object(panel, "PANEL_LOG_PATH", Path("Z:/nope/panel.log")):
            self._stub()._append("this must not raise")


class RunResultParseTest(unittest.TestCase):
    """The client's own log lines must not swallow the runtime's result."""

    def test_a_result_glued_to_the_emulator_line_is_still_read(self):
        # Measured 2026-09-18, verbatim shape: the MuMu adapter's connect line
        # arrives on the same line as the closing brace, with no newline.
        payload = {"steps": [{"index": 1, "decision": {"skill": "SCAN_MAP_FOR_BEAST"}}],
                   "stop_reason": "verified_beast_target_not_visible"}
        text = json.dumps(payload, ensure_ascii=False) + "product: MuMuPlayer-12.0-0\n"
        self.assertEqual(panel.parse_runtime_result(text).get("stop_reason"),
                         "verified_beast_target_not_visible")

    def test_a_clean_line_still_parses(self):
        payload = {"steps": [], "stop_reason": "research_queue_busy"}
        self.assertEqual(panel.parse_runtime_result(json.dumps(payload)).get("stop_reason"),
                         "research_queue_busy")

    def test_no_result_is_an_empty_dict_not_an_exception(self):
        self.assertEqual(panel.parse_runtime_result("product: MuMuPlayer-12.0-0\n"), {})

    def test_a_result_without_a_stop_reason_is_not_used(self):
        self.assertEqual(panel.parse_runtime_result(json.dumps({"steps": []})), {})


class UnattendedSurvivalTest(unittest.TestCase):
    """A bounded prune, because an unbounded one kills the unattended panel.

    Measured 2026-09-18: the window ran unattended for **6h45m** and then died when
    a single retention pass deleted 50 files at once -- the host's bulk-delete
    threshold -- so the guard intercepted the call and killed the process, taking
    AUTO with it.  That is what makes "启动 GUI = 长期无人值守" true rather than
    hopeful, so the cap is pinned here beside the other startup guarantees.
    """

    def test_a_prune_pass_is_bounded_and_the_backlog_still_drains(self):
        from winter_agent_v2 import retention

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runtime"
            root.mkdir(parents=True)
            for index in range(25):
                frame = root / f"step_{index:03d}_before.png"
                frame.write_bytes(b"x")
                os.utime(frame, (0, 0))  # old enough for any ttl
            missing = Path(tmp) / "none.jsonl"
            passes = [
                len(retention.prune_runtime_screenshots(
                    root, max_count=0, ttl_days=0, episodes_path=missing))
                for _ in range(3)
            ]
            self.assertTrue(all(count <= retention.MAX_DELETIONS_PER_PASS for count in passes),
                            f"a pass exceeded the cap: {passes}")
            self.assertEqual(list(root.rglob("*.png")), [], "the backlog must still drain")


class AutostartGateTest(unittest.TestCase):
    """``_maybe_autostart`` is the only auto-start, and it obeys the intent."""

    panel_obj = None
    root = None
    store = None
    _state_patch = None
    _log_patch = None
    _tmp = None

    @classmethod
    def setUpClass(cls):
        try:
            import tkinter as tk
        except Exception as exc:  # noqa: BLE001
            raise unittest.SkipTest(f"tkinter unavailable: {exc}")
        from tools import control_panel as module

        module.ControlPanel._enforce_retention = lambda self: None
        # The constructor saves the panel state, and that file is the operator's
        # own (it now carries the remembered stop).  A test must not rewrite it.
        # The window's narration is persisted too, and `_maybe_autostart` narrates
        # through it -- measured 2026-09-18: this class wrote its fake interpreter
        # path and its "manual mode" line into the production panel.log, which is
        # the file the startup decision is audited from.  Redirect both.
        cls._tmp = tempfile.TemporaryDirectory()
        cls._state_patch = mock.patch.object(module, "PANEL_STATE_PATH",
                                             Path(cls._tmp.name) / "panel_state.json")
        cls._log_patch = mock.patch.object(module, "PANEL_LOG_PATH",
                                           Path(cls._tmp.name) / "panel.log")
        cls._state_patch.start()
        cls._log_patch.start()
        try:
            cls.root = tk.Tk()
        except Exception as exc:  # noqa: BLE001 - no display
            cls._state_patch.stop()
            cls._tmp.cleanup()
            raise unittest.SkipTest(f"no display: {exc}")
        cls.root.withdraw()
        cls.panel_obj = module.ControlPanel(cls.root)
        cls.store = _Recorder()
        cls.panel_obj.runtime_store = cls.store

    @classmethod
    def tearDownClass(cls):
        if cls.panel_obj is not None:
            try:
                cls.panel_obj.probes.stop()
            except Exception:  # noqa: BLE001
                pass
        if cls.root is not None:
            cls.root.destroy()
        if cls._state_patch is not None:
            cls._state_patch.stop()
        if cls._log_patch is not None:
            cls._log_patch.stop()
        if cls._tmp is not None:
            cls._tmp.cleanup()

    def setUp(self):
        self.store.updates.clear()
        self.panel_obj.config["auto_execution"] = True
        self.panel_obj.continuous.set(True)
        self.panel_obj.starting = False
        self.panel_obj.repeat_after_id = None
        self.started = []
        self.panel_obj.start = lambda: self.started.append(True)

    def _preflight(self, report):
        self.panel_obj._run_startup_preflight = lambda: report

    def test_a_remembered_stop_wins_over_the_config(self):
        # The config says auto_execution=true; the operator said stop.  The stop
        # wins, and nothing is allowed to re-enable AUTO by itself.
        self.panel_obj.operator_intent = "STOPPED"
        self._preflight(fake_sections())
        self.panel_obj._maybe_autostart()
        self.assertEqual(self.started, [])
        self.assertTrue(any("USER_STOPPED" in str(u.get("stop_reason")) for u in self.store.updates))

    def test_a_remembered_pause_also_wins(self):
        self.panel_obj.operator_intent = "PAUSED"
        self._preflight(fake_sections())
        self.panel_obj._maybe_autostart()
        self.assertEqual(self.started, [])

    def test_a_running_intent_with_a_gateway_outage_still_starts_auto(self):
        # Requirement 3, at the window layer: the gateway is down, core is fine,
        # AUTO starts anyway.
        self.panel_obj.operator_intent = "RUNNING"
        self._preflight({"core_ok": True, "blockers": [], "sections": fake_sections(gateway=False)})
        self.panel_obj._maybe_autostart()
        self.assertEqual(self.started, [True])

    def test_a_core_blocker_refuses_to_start_and_schedules_a_retry(self):
        self.panel_obj.operator_intent = "RUNNING"
        self._preflight({"core_ok": False, "blockers": ["device"], "sections": fake_sections(device=False)})
        self.panel_obj._maybe_autostart()
        self.assertEqual(self.started, [])
        self.assertIsNotNone(self.panel_obj.repeat_after_id)
        self.assertTrue(any("预检未通过" in str(u.get("reason", "")) for u in self.store.updates))

    def test_manual_mode_never_starts_itself(self):
        self.panel_obj.config["auto_execution"] = False
        self._preflight(fake_sections())
        self.panel_obj._maybe_autostart()
        self.assertEqual(self.started, [])

    def test_a_preflight_that_cannot_run_does_not_start_auto(self):
        self.panel_obj.operator_intent = "RUNNING"
        self._preflight(None)
        self.panel_obj._maybe_autostart()
        self.assertEqual(self.started, [])


if __name__ == "__main__":
    unittest.main()
