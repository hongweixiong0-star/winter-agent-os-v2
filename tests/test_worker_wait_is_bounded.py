"""One worker that never exits must not end the whole AUTO work cycle.

Measured live 2026-09-21 11:43:24 local.  That round's worker finished its loop -- the runtime
snapshot was written at 03:45:04 with ``runtime_thread_alive`` and ``scheduler_loop_alive`` both
false -- and then never exited.  The panel waits with ``Popen.communicate()``, which returns at EOF
on the child's pipe, and on Windows the process the panel holds is the venv redirector: the real
worker, and anything it leaves behind, is a grandchild that also holds that pipe.  So the wait never
returned:

    panel.log       wrote nothing for thirteen minutes
    last episode    03:44:56Z, no round started after it
    pump.json       still ticking every ~30s -- which is what makes the window look alive
    operator_intent RUNNING the whole time
    recovery        the operator had to restart the window

Sixteen wait sites in ``tools/control_panel.py`` had that shape.  These tests pin the bound, the
honest outcome, and the fact that the outcome keeps the cycle going instead of looking like a round
that simply ended.
"""

from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import control_panel as panel  # noqa: E402


class _Worker:
    """A stand-in for ``subprocess.Popen`` that answers the two calls ``await_worker`` makes."""

    def __init__(self, *, outputs, timeout_error_on=(), returncode=0, pid=4242):
        self._outputs = list(outputs)
        self._timeout_error_on = tuple(timeout_error_on)
        self.returncode = returncode
        self.pid = pid
        self.timeouts: list[float] = []
        self.calls = 0

    def communicate(self, timeout=None):
        self.calls += 1
        self.timeouts.append(timeout)
        if self.calls in self._timeout_error_on:
            raise subprocess.TimeoutExpired(cmd="run_live.py", timeout=timeout)
        output = self._outputs.pop(0) if self._outputs else ""
        return output, None


class AwaitWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.killed: list[int] = []
        self._real_kill_tree = panel.winproc.kill_tree
        panel.winproc.kill_tree = lambda pid, timeout=None: (self.killed.append(pid), True)[1]
        self.addCleanup(lambda: setattr(panel.winproc, "kill_tree", self._real_kill_tree))

    def test_a_worker_that_exits_is_waited_for_and_its_code_kept(self):
        worker = _Worker(outputs=["round output\n"], returncode=2)
        output, code = await_(worker)
        self.assertEqual(output, "round output\n")
        self.assertEqual(code, 2, "the worker's own code must survive unchanged")
        self.assertEqual(self.killed, [], "nothing may be killed when nothing hung")

    def test_the_wait_is_bounded_and_says_so(self):
        worker = _Worker(outputs=["kept this\n"], timeout_error_on=(1,), returncode=0)
        output, code = await_(worker)
        self.assertEqual(worker.timeouts[0], panel.WORKER_WAIT_SECONDS,
                         "the first wait must be the bound, not an unbounded read")
        self.assertEqual(code, panel.WORKER_ABANDONED_CODE,
                         "an abandoned round must not report the worker's code")
        self.assertEqual(self.killed, [worker.pid],
                         "the tree has to go down, not just the stub the panel holds")
        self.assertIn("kept this", output, "what the worker printed is still evidence")
        self.assertIn("did not exit within", output,
                      "latest.log must say the panel gave up, not imply the round ended")

    def test_a_worker_that_ignores_the_kill_still_returns(self):
        """The second read is bounded too, or the bound is only half a fix."""
        worker = _Worker(outputs=[], timeout_error_on=(1, 2))
        output, code = await_(worker)
        self.assertEqual(code, panel.WORKER_ABANDONED_CODE)
        self.assertEqual(len(worker.timeouts), 2)
        self.assertEqual(worker.timeouts[1], panel.WORKER_KILL_GRACE_SECONDS,
                         "the post-kill drain gets a grace period, not another full bound")
        self.assertIn("did not exit within", output)

    def test_the_sentinel_cannot_be_mistaken_for_the_worker(self):
        """The worker's own codes are 0 verified / 2 unverified / 4 wrong version."""
        self.assertNotIn(panel.WORKER_ABANDONED_CODE, {0, 2, 4})

    def test_an_abandoned_round_is_reported_as_abnormal_and_the_cycle_continues(self):
        """Which is what keeps the next round scheduled.

        ``_apply_complete`` continues while ``continuous`` is on and the stop is not fatal; the
        round only reads as abnormal, and it reads that way from the non-zero code rather than
        from a parsed payload -- an abandoned worker may have printed nothing at all.
        """
        summary = panel.summarize_runtime_result({}, panel.WORKER_ABANDONED_CODE)
        self.assertFalse(summary["ok"])
        self.assertFalse(panel.is_fatal_stop(str(summary["reason"])),
                         "an abandoned round is recoverable: the next round may work")

    def test_every_wait_in_the_panel_is_bounded(self):
        """The guard that keeps the sixteenth site from being written the old way."""
        source = (TOOLS / "control_panel.py").read_text(encoding="utf-8")
        bare = re.findall(r"\.communicate\(\s*\)", source)
        self.assertEqual(bare, [], f"unbounded communicate() call(s): {len(bare)}")
        self.assertGreaterEqual(source.count("await_worker("), 16,
                                "every wait site must go through the bounded helper")


def await_(worker) -> tuple[str, int]:
    return panel.await_worker(worker, label="本轮 AUTO")


if __name__ == "__main__":
    unittest.main()
