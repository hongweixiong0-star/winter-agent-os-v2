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
from tools import panel_window as window  # noqa: E402

#: The codepage cmd.exe reads a batch file in on this machine.  cmd has no
#: encoding sniffing and no BOM support at all: it decodes every byte with the
#: system OEM codepage, so that -- not UTF-8 -- is the codec a launcher test has
#: to use.  Chinese Windows is 936, which is also what PowerShell 5.1 uses for a
#: BOM-less script and what the .lnk on the desktop stores its path in.
BATCH_CODEPAGE = "cp936"


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


def fake_sections(*, interpreter: bool = True, device: bool = True, gateway: bool = True,
                  device_detail: dict | None = None) -> dict:
    return {
        "interpreter": {"ok": interpreter, "exe": r"E:\x\python.exe", "reason": "OK",
                        "present": [], "missing": [] if interpreter else ["maa"],
                        "errors": {}, "fell_back_from": None},
        "device": {"ok": device, "serial": "127.0.0.1:7555", "resolution": [720, 1280],
                   "foreground": "com.gof.china", "error": None if device else "DEVICE_NOT_CONNECTED",
                   **(device_detail or {})},
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
    _ledger_patch = None
    _pump_patch = None
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
        # And the escalation ledger, because the window now owns a queue pump that
        # writes to it.  A test window must not be able to submit a real development
        # job, which is the sharpest form of the same production-pollution rule.
        cls._ledger_patch = mock.patch.object(
            module, "_ESCALATION_LEDGER_PATH",
            Path(cls._tmp.name) / "learning/workbuddy_escalations.jsonl")
        cls._pump_patch = mock.patch.object(
            module, "PUMP_STATE_PATH", Path(cls._tmp.name) / "pump.json")
        cls._state_patch.start()
        cls._log_patch.start()
        cls._ledger_patch.start()
        cls._pump_patch.start()
        try:
            cls.root = tk.Tk()
        except Exception as exc:  # noqa: BLE001 - no display
            cls._state_patch.stop()
            cls._log_patch.stop()
            cls._ledger_patch.stop()
            cls._pump_patch.stop()
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
            try:
                cls.panel_obj.pump.stop()
            except Exception:  # noqa: BLE001
                pass
        if cls.root is not None:
            cls.root.destroy()
        if cls._state_patch is not None:
            cls._state_patch.stop()
        if cls._log_patch is not None:
            cls._log_patch.stop()
        if cls._ledger_patch is not None:
            cls._ledger_patch.stop()
        if cls._pump_patch is not None:
            cls._pump_patch.stop()
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

    def test_a_repairable_device_reaches_auto_instead_of_the_retry_loop(self):
        """The deadlock this rule exists to prevent, measured 2026-10-01 07:26.

        The emulator answered, sat on the Android launcher, and ``com.gof.china``
        was not running.  ``_ensure_device`` is what launches the game, and it runs
        *inside* the worker -- so an auto-start gate that refuses on the device
        refuses the only path that would have made the device ready.  Preflight kept
        returning the same answer, the retry kept re-running it, and the system
        could not converge by construction.

        A device the runtime can repair is therefore not a blocker; it is reported
        as recovering, and AUTO starts so the repair gets its chance.
        """
        self.panel_obj.operator_intent = "RUNNING"
        self._preflight({
            "core_ok": True, "blockers": [], "recovering": ["device"],
            "sections": fake_sections(
                device=False,
                device_detail={"not_ready_reason": "GAME_NOT_FOREGROUND", "repair": "LAUNCH_GAME"},
            ),
        })
        self.panel_obj._maybe_autostart()
        self.assertEqual(self.started, [True], "the worker is what repairs the device")
        self.assertIsNone(self.panel_obj.repeat_after_id)
        # The narration lands in the patched PANEL_LOG_PATH for this class, and a
        # recovery must not read as a clean pass: the operator has to be able to tell
        # "AUTO started because everything was fine" from "AUTO started and is about
        # to launch the game".
        self.assertIn("可恢复", panel.PANEL_LOG_PATH.read_text(encoding="utf-8"))

    def test_an_unrepairable_device_still_schedules_a_retry(self):
        # The other half of the same rule, so the fix cannot be read as "the device
        # never blocks anything": a condition the runtime cannot reach is still a
        # refusal with a bounded retry behind it.
        self.panel_obj.operator_intent = "RUNNING"
        self._preflight({"core_ok": False, "blockers": ["device"], "recovering": [],
                         "sections": fake_sections(device=False)})
        self.panel_obj._maybe_autostart()
        self.assertEqual(self.started, [])
        self.assertIsNotNone(self.panel_obj.repeat_after_id)

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


class LaunchGateWiringTest(unittest.TestCase):
    """The file the operator double-clicks must ask the gate these tests pin.

    Regression for the 2026-10-01 startup failure, and it is a *wiring* failure,
    which is why it needs a test that reads the launcher rather than a test of
    preflight alone.

    ``Start-Winter-Agent-V2.cmd`` treats a non-zero preflight exit code as "do not
    open the window".  Preflight's exit code became ``core_ok`` on 2026-09-18, and
    core grew a device section in that same commit -- so from then on the launcher
    refused to open the window on a device that only the window could repair
    (``_ensure_device`` launches MuMu and foregrounds the client, and it runs
    inside the AUTO worker).  Every test passed throughout: preflight's gates were
    each correct, and the launcher is not imported by anything, so no test of a
    pure function could see *which* gate the operator's entry point asked for.
    The two files disagreed in silence for two weeks.
    """

    LAUNCHER = ROOT / "Start-Winter-Agent-V2.cmd"

    def _preflight_invocations(self) -> list[str]:
        """Lines that *run* preflight, as opposed to comments and diagnosis hints.

        ``诊断：python tools\\preflight.py`` is part of the failure text the launcher
        prints, and the comment block above the gate names the flag on purpose, so
        both would answer "does this file mention --launch-gate" with a misleading
        yes either way.

        Read in the codepage cmd.exe actually reads batch files in, not UTF-8: the
        launcher's operator-facing text is CP936, and reading it as UTF-8 with
        ``errors="replace"`` is how a test can look straight at a mis-encoded
        launcher and still see nothing wrong.
        """
        text = self.LAUNCHER.read_bytes().decode(BATCH_CODEPAGE, errors="replace")
        out = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or "preflight.py" not in stripped:
                continue
            if stripped.lower().startswith(("rem ", "rem\t", "echo ", "@echo", "::")):
                continue
            out.append(stripped)
        return out

    def test_the_launcher_runs_preflight_exactly_once(self):
        # Two invocations would mean two verdicts, and the second one is the one
        # nobody tested.  The literal flag is asserted rather than the constant:
        # renaming the constant without updating the launcher is exactly the drift
        # this class exists to catch.
        self.assertEqual(self._preflight_invocations(), [
            '"%WINTER_PYTHON%" "tools\\preflight.py" --launch-gate',
        ])

    def test_the_launcher_asks_the_window_question(self):
        for line in self._preflight_invocations():
            self.assertIn(preflight.LAUNCH_GATE_FLAG, line,
                          "the launcher gates *opening the window*; a device the "
                          "runtime can repair is not a reason to refuse it")

    def test_preflight_recognises_the_flag_the_launcher_passes(self):
        # A flag the parser rejects exits 2, and the launcher's ``if errorlevel 1``
        # reads that as a failed preflight -- the same visible outcome as the
        # deadlock, with no message that distinguishes them.
        flag = self._preflight_invocations()[0].split()[-1]
        args = preflight.build_parser().parse_args([flag])
        self.assertTrue(getattr(args, flag.lstrip("-").replace("-", "_")))
        with self.assertRaises(SystemExit) as caught:
            preflight.build_parser().parse_args(["--definitely-not-a-flag"])
        self.assertEqual(caught.exception.code, 2)

    def test_the_two_gates_are_asked_separately(self):
        # The launcher's question and AUTO's must stay different questions: if the
        # launch gate ever grew the device again, ``test_the_window_opens_even_when_auto_may_not``
        # would still pass on preflight while the operator's own entry point refused.
        self.assertEqual(preflight.LAUNCH_GATE_SECTIONS, ("interpreter",))
        self.assertNotEqual(preflight.LAUNCH_GATE_SECTIONS, preflight.CORE_SECTIONS)
        self.assertIn("device", preflight.CORE_SECTIONS)


class LauncherEncodingTest(unittest.TestCase):
    """The launcher has to survive the codepage its reader uses, not the one we wish it used.

    Regression for the 2026-10-01 09:43 failure -- the *second* one in the same
    file, and the one the fixes of the morning did not touch.  ``LauncherGateWiringTest``
    was already reading this file and it was green, because it read it as UTF-8
    with ``errors="replace"``: the bytes a Windows shell cannot parse are exactly
    the bytes that decoding choice papers over.

    What the operator saw on a double-click, reproduced by running the file:

        文件名、目录名或卷标语法不正确。
        [Winter Agent OS V2] 找不到生产解释器：%WINTER_PYTHONW

    The file was UTF-8 and cmd.exe read it as CP936.  cmd has no BOM support and
    no sniffing, so the Chinese bytes of the project path were decoded as CP936
    pairs -- which shifts byte alignment by one and lets a Chinese character
    *swallow* the ASCII byte that follows it.  Measured on the real file and on a
    minimal probe: the closing quote of ``cd /d "E:\\<project>"`` was eaten (hence
    the syntax error, not "path not found"), the backslash before ``.venv`` was
    eaten (``if not exist`` then said the interpreter was missing), and the ``%``
    opening ``%WINTER_PYTHONW%`` was eaten (hence the literal variable name in the
    message).  Nothing in the process could report any of it: the launcher is not
    imported by anything, and it never reached the gate.

    Two independent defences, and the tests pin both:

    * encoding -- the batch file is written in ``BATCH_CODEPAGE``; the PowerShell
      sibling is UTF-8 *with* BOM, because 5.1 honours the BOM and otherwise uses
      the same ANSI codepage (measured: the same Chinese path lost the same
      backslash and ``Test-Path`` returned False);
    * structure -- every line that decides control flow is pure ASCII, and the
      root is ``%~dp0`` / ``$ProjectRoot`` instead of a literal.  A path expanded
      at runtime has no bytes to re-decode, so re-encoding the file degrades the
      *messages* instead of the *mechanism*.
    """

    BATCH = ROOT / "Start-Winter-Agent-V2.cmd"
    SHELL = ROOT / "Start-Winter-Agent-V2.ps1"

    #: Statements whose job is to talk to the operator, and which are therefore
    #: allowed to carry non-ASCII.  Anything else has to be ASCII: a translated
    #: path or a translated parameter is what the codepage corrupts.
    MESSAGE_VERBS = ("echo", "Write-Host", "throw", "Read-Host", "rem", "::")

    @staticmethod
    def _comments_and_messages(line: str) -> bool:
        return line.strip().lower().startswith(tuple(v.lower() for v in LauncherEncodingTest.MESSAGE_VERBS))

    def test_the_batch_launcher_is_written_in_the_codepage_cmd_reads(self):
        raw = self.BATCH.read_bytes()
        self.assertFalse(
            raw.startswith(b"\xef\xbb\xbf"),
            "cmd.exe has no BOM support: it would try to run the BOM as a command",
        )
        try:
            text = raw.decode(BATCH_CODEPAGE)
        except UnicodeDecodeError as exc:
            self.fail(
                f"Start-Winter-Agent-V2.cmd is not decodable in {BATCH_CODEPAGE}, so cmd.exe "
                f"will misread it exactly as it did on 2026-10-01: {exc}. Save the file in "
                f"{BATCH_CODEPAGE}, and keep every control-flow line ASCII."
            )
        # A file that decodes two ways is the silent case: the codepage read and
        # the UTF-8 read disagree, and only one of them is what the shell does.
        try:
            as_utf8 = raw.decode("utf-8")
        except UnicodeDecodeError:
            as_utf8 = None
        if as_utf8 is not None:
            self.assertEqual(
                text, as_utf8,
                "this file decodes differently as UTF-8 and as the codepage cmd.exe uses; "
                "the launcher must not depend on which one the reader picks",
            )

    def test_no_control_flow_line_carries_bytes_the_codepage_can_corrupt(self):
        # The structural half of the fix, and the half that does not depend on
        # anyone remembering the encoding rule: if the mechanism is ASCII, a
        # future re-encoding can garble the messages but cannot stop the launch.
        raw = self.BATCH.read_bytes()
        offenders = []
        for number, line in enumerate(raw.decode(BATCH_CODEPAGE).splitlines(), start=1):
            if any(ord(ch) > 127 for ch in line) and not self._comments_and_messages(line):
                offenders.append((number, line.strip()))
        self.assertEqual(
            offenders, [],
            "these batch lines carry non-ASCII outside a comment or an echo, so a "
            "mis-decoded Chinese character can swallow the ASCII byte that follows "
            "it and change what the file does:\n"
            + "\n".join(f"  line {n}: {t}" for n, t in offenders),
        )

    def test_the_batch_launcher_takes_its_root_from_its_own_location(self):
        # This is what makes the test above hold: `%~dp0` is expanded by cmd from
        # the command line in UTF-16, so the project's Chinese path never appears
        # in the file's bytes at all.
        text = self.BATCH.read_bytes().decode(BATCH_CODEPAGE)
        self.assertIn('set "WINTER_ROOT=%~dp0"', text)
        self.assertIn('cd /d "%WINTER_ROOT%"', text)
        self.assertIn('set "WINTER_PYTHON=%WINTER_ROOT%.venv\\Scripts\\python.exe"', text)
        self.assertIn('set "WINTER_PYTHONW=%WINTER_ROOT%.venv\\Scripts\\pythonw.exe"', text)

    def test_the_powershell_launcher_is_utf8_with_a_bom(self):
        # 5.1 uses the system ANSI codepage for a BOM-less script, so without the
        # BOM this file has the batch file's bug.  Measured 2026-10-01 09:46 on a
        # three-file probe: no BOM -> the interpreter path lost its backslash and
        # Test-Path said False; with BOM -> True.
        raw = self.SHELL.read_bytes()
        self.assertEqual(
            raw[:3], b"\xef\xbb\xbf",
            "Start-Winter-Agent-V2.ps1 must keep its UTF-8 BOM: Windows PowerShell 5.1 "
            "reads a BOM-less script in the system ANSI codepage",
        )
        raw.decode("utf-8")  # and it must be UTF-8 after the BOM

    def test_the_powershell_launcher_derives_its_paths_instead_of_spelling_them(self):
        raw = self.SHELL.read_bytes()
        self.assertEqual(raw[:3], b"\xef\xbb\xbf")
        text = raw[3:].decode("utf-8")
        self.assertIn('$PythonPath = Join-Path $ProjectRoot ".venv\\Scripts\\python.exe"', text)
        offenders = []
        for number, line in enumerate(text.splitlines(), start=1):
            if any(ord(ch) > 127 for ch in line) and not self._comments_and_messages(line):
                offenders.append((number, line.strip()))
        self.assertEqual(
            offenders, [],
            "the PowerShell launcher must keep non-ASCII inside its messages:\n"
            + "\n".join(f"  line {n}: {t}" for n, t in offenders),
        )

    def test_the_encoding_rules_are_written_down_where_the_next_editor_looks(self):
        # These files are edited by tools that rewrite them as UTF-8 no-BOM by
        # default, which is how this bug is going to come back. The rule has to be
        # in the file itself, not only in a test the editor does not read.
        for path, keyword in ((self.BATCH, "cp936"), (self.SHELL, "BOM")):
            head = path.read_bytes()[:1200]
            head = head[3:] if head[:3] == b"\xef\xbb\xbf" else head
            self.assertIn(keyword.lower(), head.decode("utf-8", errors="replace").lower(),
                          f"{path.name} should document its own encoding rule near the top")


class ExistingPanelVisibilityTest(unittest.TestCase):
    """A second double-click must open something when a panel already owns the lock.

    Two mechanisms make the repeat launch silent, and both were measured on 2026-10-01:
    the scheduled task is registered IgnoreNew, so schtasks starts nothing at all; and
    when the task was not the thing that started the panel, the new instance hits the
    single-instance mutex and (before this) returned 0.  In both cases the operator saw
    no window, no log line, and a launcher that still printed 成功.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.pid_path = self.tmp / "panel.pid"

    def _install(self, *, pid: int | None = 4321, alive: bool = True,
                 windows: tuple[int, ...] = (99,), responding: bool = True):
        """Wire the probe so the test exercises the decision, not Win32."""
        if pid is not None:
            self.pid_path.write_text(str(pid), encoding="utf-8")
        patchers = {
            "alive": mock.patch.object(window.winproc, "alive", return_value=alive),
            "windows": mock.patch.object(window, "top_level_windows", return_value=list(windows)),
            "responding": mock.patch.object(window, "window_is_responding", return_value=responding),
            "activate": mock.patch.object(window, "activate_window"),
            "notify": mock.patch.object(window, "notify_operator"),
        }
        started = {}
        for name, patcher in patchers.items():
            started[name] = patcher.start()
            self.addCleanup(patcher.stop)
        return started

    # -- reading what the running panel recorded -----------------------------

    def test_the_pid_comes_from_the_file_the_panel_writes_for_itself(self):
        self.pid_path.write_text("12345", encoding="utf-8")
        self.assertEqual(window.read_panel_pid(self.pid_path), 12345)

    def test_a_missing_or_unreadable_pid_reads_as_absent(self):
        self.assertEqual(window.read_panel_pid(self.pid_path), 0)
        self.pid_path.write_text("not-a-pid", encoding="utf-8")
        self.assertEqual(window.read_panel_pid(self.pid_path), 0)

    def test_the_default_path_lives_under_the_checkout_the_module_runs_from(self):
        # The pinned launcher mounts the shared data directories into its own tree, so
        # deriving the path here reaches the same file the panel writes.
        self.assertEqual(window.panel_pid_path(),
                         window.ROOT / "learning" / "control_panel" / "panel.pid")

    # -- the decision --------------------------------------------------------

    def test_the_window_probe_does_not_use_the_abort_flag(self):
        # Measured 2026-10-01 21:03 on the live panel: SMTO_ABORTIFHUNG reports a
        # *minimised* window as hung -- it returned 0 after the full 2000 ms -- while
        # SMTO_NORMAL answered that same window in 219 ms.  Minimised is exactly the
        # state an operator is in when they double-click, so this must not come back.
        self.assertEqual(window.WINDOW_PROBE_FLAGS, window.SMTO_NORMAL)
        self.assertNotEqual(window.WINDOW_PROBE_FLAGS, window.SMTO_ABORTIFHUNG)

    def test_a_live_panel_with_a_window_is_brought_to_the_front(self):
        hooks = self._install()
        code, reason = window.focus_existing_panel(self.pid_path)
        self.assertEqual(code, window.SHOWN)
        self.assertIn("4321", reason)
        hooks["activate"].assert_called_once_with(99)

    def test_a_dead_pid_is_absent_because_its_lock_died_with_it(self):
        # This is the shape that must still be allowed to start a panel: the process is
        # gone, so the mutex is free even though panel.pid still names it.
        hooks = self._install(alive=False)
        code, _ = window.focus_existing_panel(self.pid_path)
        self.assertEqual(code, window.ABSENT)
        hooks["activate"].assert_not_called()

    def test_a_busy_window_is_still_raised_and_the_answer_says_so(self):
        # A panel mid-round blocks its own message loop while it waits on the worker, so a
        # "no response" probe must not stop the window coming up -- the operator asked to
        # see the panel, and a decorated answer is more useful than a refusal.  Measured
        # 2026-10-01 21:05: the first probe after minimising timed out, and the next
        # answered that same window in 219 ms.
        hooks = self._install(responding=False)
        code, reason = window.focus_existing_panel(self.pid_path)
        self.assertEqual(code, window.SHOWN)
        self.assertIn("没有响应", reason)
        hooks["activate"].assert_called_once_with(99)

    def test_a_process_with_no_window_is_unavailable(self):
        hooks = self._install(windows=())
        code, _ = window.focus_existing_panel(self.pid_path)
        self.assertEqual(code, window.UNAVAILABLE)
        hooks["activate"].assert_not_called()

    def test_no_pid_file_means_nothing_is_running(self):
        self._install(pid=None)
        code, _ = window.focus_existing_panel(self.pid_path)
        self.assertEqual(code, window.ABSENT)

    # -- the post-start confirmation -----------------------------------------

    def test_wait_reports_success_as_soon_as_a_window_appears(self):
        with mock.patch.object(window, "panel_is_showing", return_value=True):
            code, _ = window.wait_for_panel(5.0, self.pid_path)
        self.assertEqual(code, window.SHOWN)

    def test_wait_names_the_likely_cause_when_nothing_starts(self):
        # schtasks exits 0 both when it starts the task and when IgnoreNew discards the
        # request, so this timeout is the only place that can be said out loud.
        code, reason = window.wait_for_panel(0.01, self.pid_path)
        self.assertEqual(code, window.UNAVAILABLE)
        self.assertIn("panel.pid", reason)

    def test_wait_does_not_call_a_stale_pid_a_started_panel(self):
        self.pid_path.write_text("4321", encoding="utf-8")
        with mock.patch.object(window.winproc, "alive", return_value=False):
            code, reason = window.wait_for_panel(0.01, self.pid_path)
        self.assertEqual(code, window.UNAVAILABLE)
        self.assertIn("4321", reason)

    # -- how control_panel consumes it ---------------------------------------

    def test_control_panel_asks_about_its_own_pid_file(self):
        expected = self.tmp / "panel.pid"
        with mock.patch.object(panel, "PANEL_LOG_PATH", str(self.tmp / "panel.log")), \
             mock.patch.object(panel.panel_window, "focus_existing_panel",
                               return_value=(window.SHOWN, "")) as focused:
            panel._report_existing_panel()
        self.assertEqual(focused.call_args.args[0], expected)

    def test_control_panel_says_nothing_when_the_window_comes_up(self):
        with mock.patch.object(panel.panel_window, "focus_existing_panel",
                               return_value=(window.SHOWN, "")), \
             mock.patch.object(panel.panel_window, "notify_operator") as notify:
            panel._report_existing_panel()
        notify.assert_not_called()

    def test_control_panel_tells_the_operator_the_reason_and_the_next_step(self):
        with mock.patch.object(panel.panel_window, "focus_existing_panel",
                               return_value=(window.UNAVAILABLE, "进程 4321 的窗口没有响应")), \
             mock.patch.object(panel.panel_window, "notify_operator") as notify:
            panel._report_existing_panel()
        message = notify.call_args.args[0]
        self.assertIn("4321", message)
        self.assertIn("任务管理器", message)

    def test_a_failing_probe_still_tells_the_operator_something(self):
        # This runs on the way out of a launch that is about to return 0: an exception
        # here would restore the silent second-click the whole change exists to remove.
        with mock.patch.object(panel.panel_window, "focus_existing_panel",
                               side_effect=OSError("no window station")), \
             mock.patch.object(panel.panel_window, "notify_operator") as notify:
            panel._report_existing_panel()
        self.assertIn("no window station", notify.call_args.args[0])

    # -- the wiring the defect lived in --------------------------------------

    def test_a_second_launch_reports_instead_of_returning_early(self):
        with mock.patch.object(panel, "_acquire_single_instance", return_value=False), \
             mock.patch.object(panel, "_report_existing_panel") as reported, \
             mock.patch.object(panel.tk, "Tk") as tk_factory:
            self.assertEqual(panel.main(), 0)
        reported.assert_called_once_with()
        tk_factory.assert_not_called()

    def test_a_first_launch_does_not_look_at_the_pid_file(self):
        # On a cold start panel.pid names the panel that died last; acting on it would
        # raise a corpse's window.
        with mock.patch.object(panel, "_acquire_single_instance", return_value=True), \
             mock.patch.object(panel, "_report_existing_panel") as reported, \
             mock.patch.object(panel, "ControlPanel"), \
             mock.patch.object(panel.tk, "Tk"):
            panel.main()
        reported.assert_not_called()


class SecondLaunchWiringTest(unittest.TestCase):
    """The batch file is where the IgnoreNew half has to be answered.

    When a panel is already running, schtasks starts nothing and control_panel is
    never loaded, so no amount of care inside main() can reach the operator.  The
    launcher itself has to ask before starting the task, and confirm after.
    """

    LAUNCHER = Path(__file__).resolve().parents[1] / "Start-Winter-Agent-V2.cmd"

    def _lines(self) -> list[str]:
        return [l.strip() for l in self.LAUNCHER.read_bytes().decode(BATCH_CODEPAGE).splitlines()]

    def _commands(self) -> list[str]:
        return [l for l in self._lines()
                if l and not l.lower().startswith(("rem", "echo", "::", "@echo"))]

    def _index_of(self, needle: str) -> int:
        return next(i for i, l in enumerate(self._commands()) if needle in l)

    def test_the_launcher_asks_whether_a_panel_is_already_running(self):
        focus = [l for l in self._commands() if "panel_window.py" in l and "--focus" in l]
        self.assertEqual(len(focus), 1)
        # It must run before the task: the task is IgnoreNew, so once it has started a
        # panel a later /Run starts nothing and the question can never be asked again.
        self.assertLess(self._index_of("--focus"), self._index_of("schtasks"))

    def test_the_launcher_confirms_a_window_actually_appeared(self):
        waits = [l for l in self._commands() if "panel_window.py" in l and "--wait" in l]
        self.assertEqual(len(waits), 1)
        self.assertGreater(self._index_of("--wait"), self._index_of("schtasks"))

    def test_the_launcher_branches_on_both_nonzero_answers(self):
        lines = self._lines()
        self.assertTrue(any("errorlevel 2" in l for l in lines),
                        "the unavailable answer needs its own branch and message")
        self.assertTrue(any("errorlevel 1" in l for l in lines),
                        "the absent answer has to fall through to starting a panel")

    def test_every_goto_has_a_label(self):
        lines = self._lines()
        labels = {l for l in lines if l.startswith(":")}
        # ``goto :label`` carries its own colon in this file, so the target is taken
        # verbatim rather than prefixed -- otherwise this test would look like it was
        # checking the labels when it was only checking its own string building.
        targets = [l.split("goto", 1)[1].strip()
                   for l in lines if " goto " in f" {l} "]
        self.assertTrue(targets, "the branches above are gotos, so they must exist")
        for target in targets:
            self.assertIn(target, labels, f"dangling {target}")


if __name__ == "__main__":
    unittest.main()
