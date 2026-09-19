"""The closure ladder's git call must go through the one runner, not a bare subprocess.

The operator saw a modal Windows box --
``[出现错误 2147942632 (0x800700e8) (启动"git log "--format=%h %cI" -40"时)]`` -- raised
from the panel.  ``0x800700E8`` is Win32 error 232, ``ERROR_NO_DATA``.

That argv appears in exactly one code path: ``tools/unattended_closure.heads()``, which
``tools/control_panel.py`` calls on the refresh path that draws the closure card, in a
process that runs under a console-less ``pythonw``.  A console tool spawned from there
without ``CREATE_NO_WINDOW`` makes Windows attach a console to the Git-for-Windows shim, and
that launch fails outright -- the shim's own directory is the window title in the operator's
screenshot.

``heads()`` absorbs the ``OSError`` on purpose: a crash there takes the whole refresh with
it, and a card that raises is worse than a card that is wrong.  So the failure is silent by
design -- ``heads()`` returns ``()``, and ``build()`` then reports "no commit landed after
the submission" over a submission the operator did commit.  The hidden-window flags are the
only thing between the call and that silence, which is why it is pinned here.

What these tests defend
-----------------------
* ``heads()`` really returns commits: obeying the rule is worthless if the command is broken.
* The call site is not flagged by the rule the GUI/AUTO path already lives under.
* ``unattended_closure.py`` is **not** on ``HUMAN_TERMINAL_TOOLS``.  It was -- reasoned as an
  "operator-run closure ladder" -- and that exemption is exactly what let ``check_wiring``
  report ``problems: 0`` while the panel raised dialog boxes at the operator.
* No other exempted tool is imported by code, and the rule still *detects* a bare call, so a
  green result means something rather than meaning the check was neutered.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(ROOT / "tools"))

import check_wiring  # noqa: E402
import unattended_closure as closure  # noqa: E402

#: ``<sha> <ISO-8601>``, which is what ``--format=%h %cI`` produces.
HEAD_LINE = re.compile(r"^[0-9a-f]{7,40} \d{4}-\d{2}-\d{2}T")


class HeadsRunsHiddenTests(unittest.TestCase):
    def test_heads_returns_the_commit_list(self):
        """The rule is worth nothing if the command it governs does not work."""
        heads = closure.heads()
        self.assertTrue(heads, "heads() returned nothing: the git call or the runner is broken")
        for line in heads:
            self.assertRegex(line, HEAD_LINE)

    def test_the_closure_ladder_is_not_flagged_by_the_hidden_process_rule(self):
        """The GUI/AUTO path's own rule must be satisfied, not merely exempted."""
        findings = [label for label, _detail in check_wiring.unhidden_process_calls()
                    if "unattended_closure.py" in label]
        self.assertEqual(findings, [], f"unattended_closure still spawns unhidden: {findings}")

    def test_the_closure_ladder_is_not_exempted_as_a_human_terminal_tool(self):
        """The exemption was the bug: the panel imports this module."""
        exempt = {name for name, _reason in check_wiring.HUMAN_TERMINAL_TOOLS}
        self.assertNotIn("unattended_closure.py", exempt)

    def test_no_exempted_tool_is_imported_by_the_code(self):
        """Otherwise the next exemption quietly re-opens the same hole."""
        findings = [f"{label} | {detail}" for label, detail in check_wiring.reached_tools()]
        self.assertEqual(findings, [], f"an exempted terminal tool is imported by code: {findings}")

    def test_the_hidden_process_rule_still_detects_a_bare_call(self):
        """Guard the guard: a check that cannot fail is not a check."""
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "leaky.py").write_text(
                "import subprocess\n"
                "\n"
                "\n"
                "def go():\n"
                '    return subprocess.run(["git", "status"], capture_output=True)\n',
                encoding="utf-8")
            found = [label for label, _detail in check_wiring.unhidden_process_calls(pkg=root)]
        self.assertTrue(found, "the hidden-process rule stopped detecting bare calls")

    def test_a_git_that_cannot_start_is_silent_rather_than_a_crash(self):
        """Pins the behaviour that makes the flags load-bearing.

        ``heads()`` returning ``()`` is the documented degradation -- it is what lets the
        refresh survive git being unavailable.  The cost is that a broken spawn is
        indistinguishable from a repository with no commits, so this asserts the silence is
        deliberate rather than discovering it by accident later.
        """
        original = closure.winproc.run

        def refuse(*_args, **_kwargs):
            raise OSError(232, "The pipe is being closed")

        closure.winproc.run = refuse
        try:
            self.assertEqual(closure.heads(), [])
        finally:
            closure.winproc.run = original

    def test_heads_asks_git_through_the_one_runner(self):
        """Not a bare ``subprocess.run``: that is the whole defect."""
        calls: list[list[str]] = []
        original = closure.winproc.run

        def spy(argv, **kwargs):
            calls.append(list(argv))
            return original(argv, **kwargs)

        closure.winproc.run = spy
        try:
            closure.heads()
        finally:
            closure.winproc.run = original
        self.assertEqual(calls, [["git", "log", "--format=%h %cI", "-40"]])

    def test_a_bare_subprocess_import_is_not_left_behind(self):
        """The module no longer imports ``subprocess`` at all."""
        source = (ROOT / "tools" / "unattended_closure.py").read_text(encoding="utf-8")
        self.assertNotIn("import subprocess", source)


if __name__ == "__main__":
    unittest.main()
