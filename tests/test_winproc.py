"""Background processes: hidden, decodable, and started in exactly one place.

Operator P0, 2026-09-18: the control panel flashed a black console window every few
seconds.  ADB was already hidden everywhere -- the source was ``state_truth._head()``,
running ``git rev-parse`` on every refresh with no creation flags.  These tests defend
the two things that made it possible and the two that make it stay fixed:

* **hidden** -- a child gets ``CREATE_NO_WINDOW`` *and* ``STARTF_USESHOWWINDOW``/``SW_HIDE``
  (the second pair is what covers a parent that owns a console), unless the operator
  explicitly asks to watch consoles with ``V2_SHOW_BACKGROUND_CONSOLES``.
* **decodable** -- console tools print the OEM codepage while this environment sets a
  UTF-8 default for Python's own I/O.  Measured: ``netstat -ano`` raised
  ``UnicodeDecodeError: 'utf-8' codec can't decode byte 0xbb``, i.e. the diagnostic failed
  exactly when something was wrong.
* **one place** -- the AST guard flags any ``subprocess.*``/``os.system`` call in the
  package or in ``tools/`` that does not pass the flags, with an explicit, reasoned
  whitelist for one-shot tools a human runs in a terminal.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(ROOT / "tools"))

from winter_agent_v2 import winproc as w  # noqa: E402
import check_wiring  # noqa: E402


class HiddenByDefault(unittest.TestCase):
    def test_the_flags_cover_a_parent_that_owns_a_console(self):
        if os.name != "nt":
            self.skipTest("Windows-only flags")
        kwargs = w.hidden_kwargs()
        self.assertTrue(kwargs["creationflags"] & getattr(w.subprocess, "CREATE_NO_WINDOW"))
        startup = kwargs["startupinfo"]
        self.assertTrue(startup.dwFlags & w.subprocess.STARTF_USESHOWWINDOW)
        self.assertEqual(startup.wShowWindow, w.subprocess.SW_HIDE)

    def test_the_operator_can_ask_to_watch_consoles(self):
        # The escape hatch must exist and must be opt-in: a developer watching a window is
        # a decision, not something a call site makes for itself.
        with unittest.mock.patch.dict(os.environ, {w.SHOW_CONSOLES_ENV: "1"}):
            self.assertTrue(w.show_consoles())
            self.assertEqual(w.hidden_kwargs(), {})
        with unittest.mock.patch.dict(os.environ, {w.SHOW_CONSOLES_ENV: "0"}):
            self.assertFalse(w.show_consoles())

    def test_shell_is_never_inherited_or_enabled_by_run(self):
        source = (ROOT / "winter_agent_v2/winproc.py").read_text(encoding="utf-8")
        self.assertIn('"shell": False', source)
        self.assertIn("subprocess.DEVNULL", source)
        # shell=True exists in exactly one place -- run_shell -- and it still applies the
        # hidden flags.  A keyword that only exists to be misused is a liability.
        self.assertEqual(source.count('"shell": True'), 1)
        self.assertIn("def run_shell(", source)


class OutputIsAlwaysDecodable(unittest.TestCase):
    def test_a_console_tool_cannot_make_the_caller_raise(self):
        # ``python -c`` printing one byte of the OEM high range: the default UTF-8
        # environment would raise on this, which is exactly what netstat did.
        code = "import sys; sys.stdout.buffer.write(b'\\xbb\\xbf OK')"
        result = w.run([sys.executable, "-c", code], timeout=30)
        self.assertEqual(result.returncode, 0)
        self.assertIn("OK", result.stdout)

    def test_the_encoding_is_pinned_not_inherited(self):
        self.assertEqual(w.default_encoding(), "oem" if os.name == "nt" else "utf-8")


class TheGuardKeepsItFixed(unittest.TestCase):
    def test_the_tree_has_no_unhidden_background_process(self):
        self.assertEqual(check_wiring.unhidden_process_calls(), [])

    def test_the_guard_is_not_vacuous(self):
        """A synthetic bare call must be flagged, or the check above proves nothing."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "offender.py").write_text(
                "import subprocess\n\n\n"
                "def go():\n"
                "    return subprocess.run(['git', 'status'], capture_output=True, text=True)\n",
                encoding="utf-8",
            )
            (root / "shelly.py").write_text(
                "import subprocess\n\n\n"
                "def go():\n"
                "    return subprocess.run('dir', shell=True, capture_output=True,\n"
                "                          creationflags=1)\n",
                encoding="utf-8",
            )
            (root / "fine.py").write_text(
                "from winter_agent_v2 import winproc\n\n\n"
                "def go():\n"
                "    return winproc.run(['git', 'status'])\n",
                encoding="utf-8",
            )
            found = check_wiring.unhidden_process_calls(extra_roots=(root,))
            labels = " ".join(label for label, _ in found)
            self.assertIn("offender.py", labels)
            # shell=True is flagged even when the flags are present.
            self.assertIn("shell-process", labels)
            self.assertIn("shelly.py", labels)
            self.assertNotIn("fine.py", labels)

    def test_every_whitelisted_tool_names_its_reason(self):
        reasons = dict(check_wiring.HUMAN_TERMINAL_TOOLS)
        for name, reason in check_wiring.HUMAN_TERMINAL_TOOLS:
            with self.subTest(tool=name):
                self.assertTrue(reason.strip(), name)
                self.assertIn(name, reasons)


class PortOwnershipIsMeasured(unittest.TestCase):
    """The operator asked for one gateway and one owner of 8080 (P0 §五).  Nothing in this
    project starts the service, so what can be proven is the measurement, not a spawn."""

    def test_nobody_listening_is_an_answer_not_an_error(self):
        pid, name = w.port_owner(9)
        self.assertEqual((pid, name), (0, ""))

    def test_the_query_survives_this_windows_locale(self):
        # netstat output is OEM-encoded; the helper must return, not raise.
        pid, name = w.port_owner(8080)
        self.assertIsInstance(pid, int)
        self.assertIsInstance(name, str)


if __name__ == "__main__":
    unittest.main()
