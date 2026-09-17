"""The production interpreter guard.

Regression under test (2026-09-17)
----------------------------------
``Start-Winter-Agent-V2.ps1`` pinned a generic runtime python that ships
``numpy``/``PIL`` and nothing else, and ``tools/control_panel.py`` spawned its
worker with ``Path(sys.executable).with_name("python.exe")``.  The panel running
at the time had been started with that interpreter (verified from the live
process command line), and its worker's piped stdout -- the only thing written
into ``learning/control_panel/latest.log`` -- carried
``MAA_IMPORT_FAILED:ModuleNotFoundError ... observations stay on ADB``.

Stated exactly: ``learning/executor_backend.jsonl`` shows no *executed* step in
those runs belonged to one of the ten skills promoted to MAA, so the 324 ms ADB
capture path had not been paid for yet -- the defect was latent.  What it was
not is visible: the ledger records executed steps, the degradation lived in a
worker's stdout, and nothing compared the two.  ``matchers.py`` also imports
``cv2`` at module scope, which that interpreter lacked, so the ``.ps1`` launcher
running ``tools/run_live.py`` could not run at all.

The guard is ``winter_agent_v2/runtime_env.py``: name what production needs,
probe a child interpreter for it, resolve the interpreter that has it, and let
the launcher refuse instead of silently degrading.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import runtime_env  # noqa: E402


class RequirementTableTest(unittest.TestCase):
    def test_maa_is_required_only_while_the_maa_backend_is_enabled(self):
        with_maa = {r.module for r in runtime_env.required_modules(maa_enabled=True)}
        without = {r.module for r in runtime_env.required_modules(maa_enabled=False)}
        self.assertIn("maa", with_maa)
        self.assertNotIn("maa", without)

    def test_every_requirement_names_the_axis_it_serves(self):
        for req in runtime_env.REQUIREMENTS:
            self.assertTrue(req.role, req.module)
            self.assertTrue(req.why, req.module)

    def test_the_modules_the_code_imports_are_covered(self):
        # matchers.py imports cv2 at module scope and ocr.py's only backend is
        # rapidocr_onnxruntime, so both are production requirements, not taste.
        modules = {r.module for r in runtime_env.REQUIREMENTS}
        for name in ("numpy", "PIL", "cv2", "maa", "rapidocr_onnxruntime"):
            self.assertIn(name, modules)


class PathDerivationTest(unittest.TestCase):
    def test_venv_is_recovered_from_the_configured_ocr_module_path(self):
        derived = runtime_env.venv_from_ocr_module_path(r"E:\some-venv\Lib\site-packages")
        # Only a real venv layout is accepted; a bare directory must not be.
        if derived is not None:
            self.assertTrue((derived / "Scripts" / "python.exe").is_file()
                            or (derived / "bin" / "python").is_file())

    def test_missing_or_blank_module_path_is_tolerated(self):
        self.assertIsNone(runtime_env.venv_from_ocr_module_path(None))
        self.assertIsNone(runtime_env.venv_from_ocr_module_path("   "))

    def test_pythonw_is_never_used_to_probe_or_spawn(self):
        # pythonw has no console: an import error there is invisible rather than
        # loud, which is exactly the failure mode this module exists to remove.
        self.assertEqual(
            runtime_env._as_python_exe(Path(r"C:\somewhere\Scripts\pythonw.exe")),
            Path(r"C:\somewhere\Scripts\python.exe"),
        )

    def test_a_directory_candidate_resolves_to_its_interpreter(self):
        exe = runtime_env._as_python_exe(runtime_env.PROJECT_VENV)
        self.assertEqual(exe.name.lower(), "python.exe")
        self.assertIn("Scripts", exe.parts)


class ProbeTest(unittest.TestCase):
    def test_probe_imports_in_a_child_and_names_the_failure(self):
        errors = runtime_env.probe_interpreter(
            Path(sys.executable), ["sys", "winter_agent_no_such_module_xyz"]
        )
        self.assertEqual(errors.get("sys"), "")
        self.assertIn("ModuleNotFoundError", errors.get("winter_agent_no_such_module_xyz", ""))

    def test_probe_of_a_missing_interpreter_says_so(self):
        errors = runtime_env.probe_interpreter(Path("Z:/nope/python.exe"), ["maa"])
        self.assertEqual(errors.get("maa"), "INTERPRETER_MISSING")

    def test_check_reports_a_missing_interpreter_as_not_ok(self):
        report = runtime_env.check(Path("Z:/nope/python.exe"))
        self.assertFalse(report.ok)
        self.assertTrue(report.reason.startswith("INTERPRETER_MISSING"))
        self.assertIn("maa", report.missing)

    def test_check_uses_the_requirements_that_apply(self):
        # With MAA switched off in config, a host without MAA is not a blocker;
        # the point is that the verdict follows the configuration.
        with patch.object(runtime_env, "probe_interpreter", return_value={}):
            report = runtime_env.check(Path(sys.executable), maa_enabled=False)
        self.assertNotIn("maa", report.present + report.missing)
        self.assertNotIn("maa", [r.module for r in runtime_env.required_modules(maa_enabled=False)])


class ResolveTest(unittest.TestCase):
    """A wrong interpreter must be skipped and *recorded*, never silently used."""

    @patch.object(runtime_env, "candidate_interpreters")
    @patch.object(runtime_env, "probe_interpreter")
    def test_first_ready_candidate_wins_and_the_skip_is_recorded(self, probe, candidates):
        bogus = Path("Z:/nope/python.exe")
        ready = Path(sys.executable)
        candidates.return_value = (bogus, ready)
        probe.return_value = {name: "" for name in
                              ("numpy", "PIL", "cv2", "rapidocr_onnxruntime")}

        report = runtime_env.resolve(root=None, configured=None, maa_enabled=False)

        self.assertTrue(report.ok)
        self.assertEqual(report.python_exe, ready)
        self.assertEqual(report.fell_back_from, bogus)

    @patch.object(runtime_env, "candidate_interpreters")
    @patch.object(runtime_env, "probe_interpreter")
    def test_nothing_ready_reports_the_gap_instead_of_pretending(self, probe, candidates):
        candidates.return_value = (Path(sys.executable),)
        probe.return_value = {"numpy": "", "PIL": "", "cv2": "ModuleNotFoundError: No module named 'cv2'",
                              "maa": "ModuleNotFoundError: No module named 'maa'",
                              "rapidocr_onnxruntime": ""}

        report = runtime_env.resolve(root=None, configured=None, maa_enabled=True)

        self.assertFalse(report.ok)
        self.assertEqual(report.reason, "MISSING_MODULES:cv2,maa")
        self.assertIn("cv2", report.missing)
        self.assertIn("maa", report.missing)

    @patch.object(runtime_env, "candidate_interpreters")
    @patch.object(runtime_env, "probe_interpreter")
    def test_the_probed_candidates_are_kept_for_the_report(self, probe, candidates):
        candidates.return_value = (Path(sys.executable),)
        probe.return_value = {"numpy": "", "PIL": "", "cv2": "", "maa": "",
                              "rapidocr_onnxruntime": ""}
        report = runtime_env.resolve(root=None, configured=None, maa_enabled=True)
        self.assertEqual([exe for exe, _ in report.candidates], [str(Path(sys.executable))])

    def test_config_defaults_to_maa_enabled_when_the_file_is_unreadable(self):
        self.assertTrue(runtime_env.maa_enabled_from_config(Path("Z:/nope")))
        self.assertIsNone(runtime_env.configured_python_path(Path("Z:/nope")))


class ControlPanelWiringTest(unittest.TestCase):
    """The panel must spawn the worker with the proved interpreter."""

    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "tools/control_panel.py").read_text(encoding="utf-8")

    def test_the_worker_interpreter_is_resolved_not_inherited(self):
        self.assertNotIn('Path(sys.executable).with_name("python.exe")', self.source)
        self.assertIn("runtime_python_path()", self.source)

    def test_every_worker_spawn_uses_the_resolved_interpreter(self):
        unified = self.source[self.source.index("    def _run_unified_worker"):
                              self.source.index("    def _ensure_device")]
        self.assertIn("runtime_python_path()", unified)
        # The goal-button workers spawn from a shared list of commands.
        self.assertNotIn("str(PYTHON_PATH)", self.source)

    def test_starting_work_is_gated_on_a_production_ready_interpreter(self):
        start = self.source[self.source.index("    def start(self)"):
                            self.source.index("    def _run_unified_worker")]
        self.assertIn("runtime_env_blocker()", start)
        self.assertIn("RUNTIME_ENV_STOP_REASON", start)
        for where in ("    def _run_unified_worker", "    def _run_worker"):
            body = self.source[self.source.index(where):self.source.index(where) + 600]
            self.assertIn("runtime_env_blocker()", body)

    def test_refusing_to_start_is_an_environment_failure_not_a_crash(self):
        from tools import control_panel

        self.assertIn(control_panel.RUNTIME_ENV_STOP_REASON, control_panel.ENVIRONMENT_FAILURES)
        self.assertEqual(
            control_panel.classify_worker_failure(
                f"{control_panel.RUNTIME_ENV_STOP_REASON}: MISSING_MODULES:maa"),
            "ENVIRONMENT",
        )

    def test_blocker_and_path_come_from_the_same_cached_report(self):
        from tools import control_panel

        report = runtime_env.InterpreterReport(
            python_exe=Path("Z:/nope/python.exe"), exists=False, missing=("maa",)
        )
        with patch.object(control_panel, "_INTERPRETER_REPORT", report):
            self.assertEqual(control_panel.runtime_python_path(), str(Path("Z:/nope/python.exe")))
            self.assertEqual(control_panel.runtime_env_blocker(), report.reason)

    def test_a_ready_report_produces_no_blocker(self):
        from tools import control_panel

        report = runtime_env.InterpreterReport(python_exe=Path(sys.executable), exists=True)
        with patch.object(control_panel, "_INTERPRETER_REPORT", report):
            self.assertIsNone(control_panel.runtime_env_blocker())


class PreflightCommandTest(unittest.TestCase):
    """The command reads the same resolver and never writes anything."""

    def test_preflight_is_importable_and_reads_the_ledger_read_only(self):
        from tools import preflight

        summary = preflight.ledger_summary(limit=50)
        self.assertIn("rows", summary)
        self.assertIn("used_backend", summary)

    def test_preflight_exit_code_follows_the_verdict(self):
        from tools import preflight

        ready = runtime_env.InterpreterReport(python_exe=Path(sys.executable), exists=True)
        # The device probe is stubbed: since 2026-09-18 the device is part of the
        # core verdict, and a test that reached for the real emulator would pass or
        # fail depending on whether MuMu happened to be up -- measured 2026-09-18,
        # this test failed in a batched run with DEVICE_NOT_CONNECTED for exactly
        # that reason.
        up = {"ok": True, "serial": "127.0.0.1:7555", "resolution": [720, 1280],
              "foreground": "com.gof.china"}
        with patch.object(preflight, "device_report", return_value=up), \
             patch.object(preflight.runtime_env, "resolve_for_project", return_value=ready):
            self.assertEqual(preflight.main(["--json"]), 0)

        blocked = runtime_env.InterpreterReport(
            python_exe=Path("Z:/nope/python.exe"), exists=False, missing=("maa",)
        )
        with patch.object(preflight, "device_report", return_value=up), \
             patch.object(preflight.runtime_env, "resolve_for_project", return_value=blocked):
            self.assertEqual(preflight.main([]), 1)

    def test_the_device_is_core_but_the_gateway_is_not(self):
        """启动 GUI 要求核心环境正常；网关异常只标记自动开发不可用。

        Operator directive 2026-09-18, requirements 2 and 3: AUTO may not start
        without the game environment, and a refusing WorkBuddy gateway must never
        stop it.  Both halves are the exit code of the launcher's own command, so
        this is where they have to hold.
        """
        from tools import preflight

        ready = runtime_env.InterpreterReport(python_exe=Path(sys.executable), exists=True)
        up = {"ok": True, "serial": "127.0.0.1:7555", "resolution": [720, 1280],
              "foreground": "com.gof.china"}
        down = {"ok": False, "error": "DEVICE_NOT_CONNECTED"}
        refusing = {"ok": False, "reason": "AUTH_REJECTED", "base_url": "http://127.0.0.1:8080"}

        with patch.object(preflight.runtime_env, "resolve_for_project", return_value=ready):
            with patch.object(preflight, "device_report", return_value=down):
                self.assertEqual(preflight.main([]), 1, "a dead device must refuse AUTO")
            with patch.object(preflight, "device_report", return_value=up), \
                 patch.object(preflight, "gateway_report", return_value=refusing):
                self.assertEqual(preflight.main([]), 0,
                                 "a refusing gateway must not stop AUTO")


if __name__ == "__main__":
    unittest.main()
