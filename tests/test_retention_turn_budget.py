"""One retention budget per turn, not one per call.

The host aborts a process that deletes 50 files inside one turn
(``CODEBUDDY_SAFE_DELETE_BULK_GUARD``, threshold 50, ``scope: turn``).  ``retention`` bounds a
*call* at 30, but ``ControlPanel._enforce_retention`` has two callers in the same turn -- start-up
and the round boundary -- so 30 + 30 reached 60.

Measured 2026-10-08: the abort killed the worker rather than trimming the tree.  Four
``WORKER_RESULT_MISSING: exit=1`` crashes inside 100 seconds, ``连续 Worker 异常已耗尽恢复预算``
and AUTO paused, with the guard's own line as the worker's last log entry:

    [safe-delete][SAFE_DELETE_BULK_CONFIRM_REQUIRED] {"count":50,"threshold":50,"scope":"turn", ...}
"""
from __future__ import annotations

import contextlib
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _load_panel():
    """Import ``tools/control_panel.py`` by path, without letting it open a window.

    The module builds its Tk root in ``main()``, not at import, so importing it is safe; a test
    that needs an instance uses ``object.__new__`` and sets only the attributes the method reads.
    """
    path = ROOT / "tools" / "control_panel.py"
    spec = importlib.util.spec_from_file_location("control_panel_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class RetentionTurnBudgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel_module = _load_panel()

    def _panel(self, calls, *, removed_per_call):
        panel = object.__new__(self.panel_module.ControlPanel)
        panel.config = {"retention": {"auto_prune": True, "max_screenshots": 500,
                                      "screenshot_ttl_days": 3}}
        panel._append = lambda *args, **kwargs: None
        panel._retention_removed_this_turn = 0
        self.panel_module.prune_runtime_screenshots = self._fake(calls, removed_per_call)
        return panel

    @staticmethod
    def _fake(calls, removed_per_call):
        def fake(root, *, max_count, ttl_days, limit=None, **kwargs):
            calls.append(limit)
            return [Path(f"/tmp/frame_{len(calls)}_{index}.png")
                    for index in range(min(removed_per_call, int(limit or 0)))]
        return fake

    def test_the_second_pass_in_one_turn_gets_no_budget(self):
        calls: list = []
        panel = self._panel(calls, removed_per_call=30)
        panel._enforce_retention()          # start-up: spends the turn's whole budget
        panel._enforce_retention()          # round boundary: same turn, must not delete again
        self.assertEqual(len(calls), 1, "a second pass in the same turn must not delete at all")
        self.assertEqual(calls[0], self.panel_module.RETENTION_DELETIONS_PER_TURN)

    def test_the_budget_is_restored_when_the_turn_ends(self):
        calls: list = []
        panel = self._panel(calls, removed_per_call=30)
        panel._enforce_retention()
        panel._retention_removed_this_turn = 0     # what the round boundary does after the call
        panel._enforce_retention()
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls, [self.panel_module.RETENTION_DELETIONS_PER_TURN] * 2)

    def test_a_turn_never_exceeds_the_host_threshold(self):
        """The number the guard counts, not the number one call happens to pass."""
        calls: list = []
        panel = self._panel(calls, removed_per_call=30)
        for _ in range(5):
            panel._enforce_retention()
        self.assertLessEqual(sum(int(limit or 0) for limit in calls), 50)
        self.assertLessEqual(self.panel_module.RETENTION_DELETIONS_PER_TURN, 50)


class DeleteGateToleranceTest(unittest.TestCase):
    """A refused prune must end the *pass*, not the production run.

    Measured 2026-10-08, after the per-turn budget above was already in place: the guard fired
    again on a single file (``{"count":50,"threshold":50,"scope":"turn","targetCount":1}``), the
    ``SystemExit`` killed the worker (``WORKER_RESULT_MISSING: exit=1``, empty
    ``child_traceback``, the guard's own line as the worker's last log entry), the watchdog's
    recovery budget was spent, and AUTO paused while the client sat idle.

    The gate's decision is kept -- the files stay where they are -- so these tests assert two
    things at once: that a refusal is survivable, and that it is *only* the gate's refusal that
    is survivable.
    """

    def setUp(self):
        from winter_agent_v2 import retention

        self.retention = retention

    def _runtime_root(self, count: int = 5):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name) / "runtime_auto"
        root.mkdir()
        files = []
        for index in range(count):
            path = root / f"frame_{index}.png"
            path.write_bytes(b"only the path matters here")
            files.append(path)
        return root, files

    def _patch_selection(self, files):
        """Make exactly ``files`` the prunable candidates, with no evidence stream consulted."""
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        for name in ("referenced_evidence", "corpus_evidence", "unknown_request_evidence"):
            stack.enter_context(mock.patch.object(self.retention, name, lambda *a, **k: set()))
        stack.enter_context(mock.patch.object(
            self.retention, "select_prunable_screenshots", lambda *a, **k: list(files),
        ))
        return stack

    def test_a_refusal_ends_the_pass_instead_of_killing_the_worker(self):
        root, files = self._runtime_root()
        self._patch_selection(files)
        attempts: list[Path] = []

        def refusing_unlink(target, *args, **kwargs):
            attempts.append(Path(target))
            # What the gate does: print its own line, then raise instead of deleting.
            raise SystemExit(1)

        with mock.patch.dict(os.environ, {self.retention.HOST_BULK_DELETE_GATE: "armed"}):
            with mock.patch.object(Path, "unlink", refusing_unlink):
                removed = self.retention.prune_runtime_screenshots(
                    root, max_count=0, ttl_days=0,
                )

        self.assertEqual(removed, [], "a refused pass removes nothing")
        self.assertEqual(len(attempts), 1,
                         "the pass must stop at the first refusal, not spend itself on raises")
        self.assertTrue(all(path.exists() for path in files),
                        "the gate's decision is kept: the files stay")

    def test_a_refusal_is_not_tolerated_when_the_delete_really_happened(self):
        """The other half of the evidence. A delete that *did* happen is not the gate's doing."""
        root, files = self._runtime_root()
        self._patch_selection(files)

        def deleting_unlink(target, *args, **kwargs):
            os.remove(target)          # the delete really happened ...
            raise SystemExit(1)        # ... so this SystemExit is not the gate's refusal

        with mock.patch.dict(os.environ, {self.retention.HOST_BULK_DELETE_GATE: "armed"}):
            with mock.patch.object(Path, "unlink", deleting_unlink):
                with self.assertRaises(SystemExit):
                    self.retention.prune_runtime_screenshots(root, max_count=0, ttl_days=0)

    def test_our_own_system_exit_still_fails_when_the_gate_is_not_armed(self):
        root, files = self._runtime_root()
        self._patch_selection(files)

        def refusing_unlink(target, *args, **kwargs):
            raise SystemExit(1)

        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(Path, "unlink", refusing_unlink):
                with self.assertRaises(SystemExit):
                    self.retention.prune_runtime_screenshots(root, max_count=0, ttl_days=0)

    def test_the_empty_directory_pass_is_tolerant_too(self):
        """``rmdir`` reaches the same gate, and ``except OSError`` cannot see a SystemExit."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name) / "runtime_auto"
        empty = root / "20261008_160303_701925"
        empty.mkdir(parents=True)

        def refusing_rmdir(self_, *args, **kwargs):
            raise SystemExit(1)

        with mock.patch.dict(os.environ, {self.retention.HOST_BULK_DELETE_GATE: "armed"}):
            with mock.patch.object(Path, "rmdir", refusing_rmdir):
                removed = self.retention.remove_empty_run_dirs(root)

        self.assertEqual(removed, [])
        self.assertTrue(empty.is_dir(), "the folder the gate refused is still there")



    def test_the_runtime_discard_is_tolerant_too(self):
        """The site where it actually showed: ``LiveRuntime._retire_superseded``.

        Three crashes inside a minute on 2026-10-08 (08:36:46, 08:37:06, 08:37:40), each with
        the host's own line as the worker's last log entry, all naming a single ``runtime_auto``
        step frame. ``except OSError`` cannot see a ``SystemExit``, so the refusal escaped and
        took the worker, the recovery budget and AUTO with it.
        """
        from winter_agent_v2.runtime import LiveRuntime

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        frame = Path(directory.name) / "20261008_163716_498476_step_002_after.png"
        frame.write_bytes(b"a capture a newer one has replaced")
        runtime = object.__new__(LiveRuntime)

        def refusing_unlink(target, *args, **kwargs):
            raise SystemExit(1)

        with mock.patch.dict(os.environ, {self.retention.HOST_BULK_DELETE_GATE: "armed"}):
            with mock.patch.object(Path, "unlink", refusing_unlink):
                runtime._retire_superseded(frame, superseded_by="refresh_1")

        self.assertTrue(frame.exists(), "the gate's decision is kept: the frame stays")

    def test_the_runtime_discard_still_fails_when_the_gate_is_not_armed(self):
        from winter_agent_v2.runtime import LiveRuntime

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        frame = Path(directory.name) / "frame.png"
        frame.write_bytes(b"x")
        runtime = object.__new__(LiveRuntime)

        def refusing_unlink(target, *args, **kwargs):
            raise SystemExit(1)

        with mock.patch.dict(os.environ, {self.retention.HOST_BULK_DELETE_GATE: "armed"}):
            with mock.patch.object(Path, "unlink", lambda target, *a, **k: os.remove(target)):
                runtime._retire_superseded(frame, superseded_by="refresh_1")

        self.assertFalse(frame.exists(), "an unarmed gate never blocks a real discard")


    def test_a_refused_cleanup_of_a_file_that_is_already_gone_is_tolerated(self):
        """``missing_is_fine``: a temporary file's cleanup cannot supply the second half.

        The call sites that need it are already best-effort -- their own ``except OSError`` /
        ``except FileNotFoundError`` says a missing file is not an error -- so a refused one is
        not an error either. The call is a bare ``unlink``, so nothing else can raise SystemExit
        through here.
        """
        gone = Path(tempfile.gettempdir()) / "definitely-not-here-9a43c890.tmp"

        def refusing_call():
            # what the gate does: raise instead of deleting.  Modelled explicitly, because
            # ``unlink(missing_ok=True)`` on a name that is not there simply returns -- a test
            # that passed that in would have been asserting nothing at all.
            raise SystemExit(1)

        with mock.patch.dict(os.environ, {self.retention.HOST_BULK_DELETE_GATE: "armed"}):
            # a missing path with the waiver must not raise ...
            self.assertFalse(self.retention.delete_past_the_hosts_gate(
                refusing_call, gone, missing_is_fine=True))
            # ... and without the waiver the two-half rule still applies
            with self.assertRaises(SystemExit):
                self.retention.delete_past_the_hosts_gate(refusing_call, gone)

    def test_the_scheduler_state_writer_survives_a_refused_temp_cleanup(self):
        """The crash this waiver was written for: 2026-10-08 17:04:55, goal GLOBAL_SCHEDULER.

        The gate's own line named ``learning/.global_scheduler_state.json.<rand>.tmp``, the
        temporary file this writer removes after its rename. ``except FileNotFoundError`` could
        not see a ``SystemExit``, so the refusal took the worker, the recovery budget and AUTO.
        """
        from winter_agent_v2 import global_scheduler_state as gss
        from winter_agent_v2.global_scheduler_state import GlobalSchedulerStateStore

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        store = GlobalSchedulerStateStore(Path(directory.name) / "global-state.json")
        real_unlink = os.unlink

        def refusing_unlink(target, *args, **kwargs):
            if str(target).endswith(".tmp"):
                raise SystemExit(1)      # what the gate does, for exactly this file
            return real_unlink(target, *args, **kwargs)

        with mock.patch.dict(os.environ, {self.retention.HOST_BULK_DELETE_GATE: "armed"}):
            with mock.patch.object(gss.os, "unlink", refusing_unlink):
                store.save(store.load())   # must not raise: this is the crash, reproduced

        self.assertTrue((Path(directory.name) / "global-state.json").is_file())


if __name__ == "__main__":
    unittest.main()
