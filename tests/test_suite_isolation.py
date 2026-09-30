"""No test may write the AUTO's live runtime state by default.

Operator directive 2026-09-22 §九: "开发测试使用独立目录，不能覆盖或回滚正式 AUTO 的学习资产".
``tests/conftest.py`` enforces that.  These tests are the guard for it.

History, because each entry below was a measured defect rather than a precaution
--------------------------------------------------------------------------------
*2026-09-30 03:41* -- the pump's heartbeat was the reason AUTO would not start:

    03:41:11  另一个实例正在运行（pid 3168）：本窗口只读，不消费队列、不启动 AUTO、不申请设备租约。
    03:42:00  不自动启动 AUTO：另一个实例（pid 3168）正在运行。本窗口只读。

``QueuePump._persist`` writes ``PUMP_STATE_PATH`` and stamps it with ``os.getpid()``.  That path
resolved to the live ``learning/control_panel/pump.json`` in a plain test process, so any test
ticking a real pump became the panel's "other instance" -- and pid 3168 was a test process that had
already exited, leaving the panel permanently refusing to start AUTO.  Sampled every 20 s during the
outage the live file named three different owners in ninety seconds (3168, then 29048 which was a
running pytest, then the panel's own pid), none of them consistently the panel.

*2026-09-30 P0* -- a write tripwire run over the whole suite found **seventeen** writes on **eleven**
live paths, including ``config/policy_state.json``: a test constructing a real ``ControlPanel``
calls ``_save_policy_state`` from ``__init__``, so a suite run rewrote the operator's own policy
file.  That is the file whose erasure had to be repaired by hand hours earlier.

So the assertions here are not "the constant is redirected" -- a redirected constant can still be
bypassed by a test that builds the live path itself.  Every test below measures a *write*, or a
byte-level comparison of the live file, because that is what did the damage.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import control_panel  # noqa: E402

import conftest  # noqa: E402

if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import build_runtime_state_manifest as manifest  # noqa: E402


def _live_tree(value: object) -> bool:
    """Is this path inside the checkout -- i.e. the live production tree?"""
    return str(value).startswith(str(control_panel.ROOT))


class TheHeartbeatIsNotTheLiveFile(unittest.TestCase):
    def test_the_pump_path_is_redirected_out_of_the_live_tree(self):
        live = control_panel.ROOT / "learning/control_panel/pump.json"
        self.assertNotEqual(Path(control_panel.PUMP_STATE_PATH), live)
        self.assertFalse(
            str(control_panel.PUMP_STATE_PATH).startswith(str(control_panel.ROOT)),
            f"the pump heartbeat still points inside the live tree: {control_panel.PUMP_STATE_PATH}",
        )

    def test_a_default_pump_writes_its_heartbeat_where_the_test_session_says(self):
        # The write is the thing that did the damage, so assert on the write, not the constant.
        pump = control_panel.QueuePump(enabled=lambda: False)
        pump._persist()
        written = Path(control_panel.PUMP_STATE_PATH)
        self.assertTrue(written.exists(), "the pump wrote no heartbeat at all")
        payload = json.loads(written.read_text(encoding="utf-8"))
        self.assertEqual(
            int(payload["process"]), os.getpid(),
            "a default pump must stamp its own pid into the redirected file",
        )
        live = control_panel.ROOT / "learning/control_panel/pump.json"
        self.assertNotEqual(written, live)

    def test_the_panel_log_pid_and_probe_are_redirected_with_it(self):
        # ``panel_pid_path`` and ``gateway_probe_path`` are derived from the log path, so
        # redirecting the log is what keeps a test from writing a pid the restart tool would
        # then try to kill.
        for path in (control_panel.PANEL_LOG_PATH,
                     control_panel.panel_pid_path(),
                     control_panel.gateway_probe_path()):
            self.assertFalse(
                _live_tree(path), f"still points inside the live tree: {path}"
            )


class EveryRedirectedStoreLeavesTheLiveTree(unittest.TestCase):
    """The table in ``conftest`` is the first mechanism; this keeps it honest.

    A new runtime-mutable path added to the manifest, or a constant renamed so a redirect entry
    silently stops matching, would otherwise be noticed only by the guard failing a *different*
    test later.  Checking the whole table at once names the entry.
    """

    def test_no_entry_still_points_into_the_checkout(self):
        offenders = []
        for module_name, attribute, live_relative, _seed in conftest._REDIRECTS:
            module = __import__(module_name, fromlist=["_"])
            if not hasattr(module, attribute):
                offenders.append(f"{module_name}.{attribute} (attribute is gone)")
                continue
            value = getattr(module, attribute)
            if _live_tree(value):
                offenders.append(f"{module_name}.{attribute} -> {value}")
        self.assertEqual(offenders, [], "these redirects did not take effect: " + "; ".join(offenders))

    def test_every_entry_targets_the_one_test_runtime_root(self):
        for module_name, attribute, live_relative, _seed in conftest._REDIRECTS:
            module = __import__(module_name, fromlist=["_"])
            value = Path(getattr(module, attribute))
            self.assertTrue(
                str(value).startswith(str(conftest.TEST_RUNTIME_ROOT)),
                f"{module_name}.{attribute} -> {value} is not under TEST_RUNTIME_ROOT",
            )

    def test_the_device_lease_default_is_not_the_live_root(self):
        """``DeviceLease()`` with no argument is the shape production helpers use.

        Before ``DEFAULT_ROOT`` existed that shape resolved to the checkout, so a test could take
        the real MuMu's lock -- and every subsequent production action would read the device as
        owned by a process that no longer existed.
        """
        from winter_agent_v2 import device_lease

        self.assertFalse(
            _live_tree(device_lease.DEFAULT_ROOT),
            f"a default DeviceLease would write the live tree: {device_lease.DEFAULT_ROOT}",
        )
        lease = device_lease.DeviceLease()
        self.assertFalse(_live_tree(lease.path), f"live lease path: {lease.path}")

    def test_the_operator_intent_file_is_not_the_live_one(self):
        """One word in ``config/control_panel_state.json`` is the difference between AUTO
        running and AUTO stopped, so a test must not be able to write it."""
        self.assertFalse(
            _live_tree(control_panel.PANEL_STATE_PATH),
            f"a test could stop the production AUTO: {control_panel.PANEL_STATE_PATH}",
        )

    def test_the_policy_file_is_not_the_live_one(self):
        """``ControlPanel.__init__`` rewrites it, so this is the write that actually happened."""
        self.assertFalse(
            _live_tree(control_panel.POLICY_STATE_PATH),
            f"a test could rewrite the operator's policy: {control_panel.POLICY_STATE_PATH}",
        )


class TheGuardRefusesLiveRuntimeWrites(unittest.TestCase):
    """The second mechanism: the manifest's own enumeration, enforced at write time."""

    def test_the_classifier_agrees_with_the_manifest(self):
        # Positive controls, taken from ``RUNTIME_MUTABLE_GLOBS``.
        for relative in ("learning/goal_state.json",
                         "learning/control_panel/pump.json",
                         "learning/device_leases.jsonl",
                         "config/policy_state.json",
                         "learning/roles/ROLE_A/state.json"):
            self.assertEqual(
                manifest.classify(relative), manifest.RUNTIME_MUTABLE, relative
            )
            self.assertIsNotNone(
                conftest.classify_production_write(control_panel.ROOT / relative),
                f"the guard would let a test write {relative}",
            )

    def test_the_guard_is_broader_than_the_manifest_on_purpose(self):
        """A path the manifest does *not* name is still live state, and still refused.

        ``classify`` falls back to ``VERSIONED_EVIDENCE`` for anything under ``learning/`` that no
        glob names, so a manifest-only guard would have let ``learning/goal_fairness.json`` -- a
        file the panel rewrites at every start-up -- be written by a test, and would have left a
        newly introduced runtime path invisible until somebody remembered to add a glob.  The first
        version of this guard had exactly that hole; this is the regression for it.
        """
        unlisted = "learning/_isolation_probe_should_not_exist.json"
        self.assertNotEqual(manifest.classify(unlisted), manifest.RUNTIME_MUTABLE)
        self.assertEqual(
            conftest.classify_production_write(control_panel.ROOT / unlisted), unlisted
        )

    def test_a_scratch_path_is_not_refused(self):
        """The guard must not fire on the scratch tree, or every test would fail."""
        self.assertIsNone(conftest.classify_production_write(
            conftest.TEST_RUNTIME_ROOT / "learning/control_panel/pump.json"))
        self.assertIsNone(conftest.classify_production_write(
            control_panel.ROOT / "winter_agent_v2/runtime.py"))
        self.assertIsNone(conftest.classify_production_write("/tmp/not-this-repo/x.json"))

    def test_the_guard_raises_before_writing(self):
        victim = control_panel.ROOT / "learning/_isolation_probe_should_not_exist.json"
        before = victim.read_bytes() if victim.exists() else None
        with conftest.probe_ledger() as ledger:
            with self.assertRaises(conftest.ProductionRuntimeWriteError):
                victim.write_text("{}", encoding="utf-8")
            self.assertEqual([row["path"] for row in ledger],
                             ["learning/_isolation_probe_should_not_exist.json"])
        after = victim.read_bytes() if victim.exists() else None
        self.assertEqual(after, before, "the guard raised but the write landed anyway")

    def test_a_test_that_swallows_the_error_still_leaves_no_mark(self):
        """The raise happens *before* the write, so ``except Exception`` cannot undo it."""
        victim = control_panel.ROOT / "learning/_isolation_probe_should_not_exist.json"
        before = victim.read_bytes() if victim.exists() else None
        with conftest.probe_ledger():
            try:
                victim.write_text("{}", encoding="utf-8")
            except Exception:  # noqa: BLE001 - deliberately swallowed, as a careless test would
                pass
        after = victim.read_bytes() if victim.exists() else None
        self.assertEqual(after, before, "a swallowed refusal still wrote the file")

    def test_the_refusal_is_not_recorded_against_the_session(self):
        """A deliberate probe must not make the metric unreachable."""
        before = list(conftest.PRODUCTION_WRITES)
        with conftest.probe_ledger():
            try:
                (control_panel.ROOT / "learning/_probe.json").write_text("{}", encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
        self.assertEqual(conftest.PRODUCTION_WRITES, before)


class TheProductionSentinelSurvives(unittest.TestCase):
    """The operator's P0 acceptance, run as a real regression rather than a one-off script.

    ``process = 123456`` and ``sentinel = KEEP_ME`` are the operator's own values.  Two deliberate
    deviations, both because a literal reading causes the outage it is meant to prevent:

    *The sentinel is not planted at the live ``learning/control_panel/pump.json``.*  That file is
    read to decide who owns the clock, so a file naming pid 123456 makes the running panel treat
    itself as the second instance and refuse to start AUTO -- the 2026-09-30 03:41 failure verbatim.
    AUTO is live while this suite runs.  The sentinel sits beside it, under the same manifest rule
    (``learning/control_panel/**`` -> RUNTIME_MUTABLE), shaped exactly like a heartbeat so the
    comparison is like for like.

    *The sentinel is planted by the harness, not by a test.*  ``conftest`` creates it once with the
    guard still uninstalled -- an idempotent, never-read positive control -- so that the test itself
    writes nothing to the live tree and the metric stays a real zero.
    """

    SENTINEL = control_panel.ROOT / "learning/control_panel" / "autotest_isolation_sentinel.json"
    EXPECTED = {"process": 123456, "sentinel": "KEEP_ME"}

    def test_the_sentinel_is_in_place_and_is_a_test_artefact(self):
        self.assertTrue(self.SENTINEL.exists(),
                        "conftest did not plant the positive control; the test below would be vacuous")
        # It must be classified runtime-mutable, or it proves nothing about the guard.
        relative = self.SENTINEL.relative_to(control_panel.ROOT).as_posix()
        self.assertEqual(manifest.classify(relative), manifest.RUNTIME_MUTABLE, relative)

    def test_the_sentinel_is_byte_identical_after_a_tick_and_the_heartbeat_is_in_tmp(self):
        before = self.SENTINEL.read_bytes()
        payload = json.loads(before.decode("utf-8"))
        self.assertEqual(payload["process"], 123456)
        self.assertEqual(payload["sentinel"], "KEEP_ME")

        # Tick a real pump, the same way a QueuePump test does, and drive three more redirected
        # stores through a real write, so the comparison covers more than the heartbeat.
        pump = control_panel.QueuePump(enabled=lambda: False)
        pump._persist()

        from winter_agent_v2 import device_lease, event_schedule, goal_utility

        goal_utility.save({})
        event_schedule.save({})
        device_lease.DeviceLease().acquire(owner=device_lease.OWNER_GAMEPLAY)

        self.assertEqual(
            self.SENTINEL.read_bytes(), before,
            "a production sentinel changed during a test run: "
            "PRODUCTION_RUNTIME_FILES_TOUCHED_BY_TESTS is not 0",
        )
        heartbeat = Path(control_panel.PUMP_STATE_PATH)
        self.assertTrue(
            str(heartbeat).startswith(str(conftest.TEST_RUNTIME_ROOT)),
            f"the test heartbeat did not go to the tmp directory: {heartbeat}",
        )
        self.assertTrue(heartbeat.exists())

    def test_the_live_pump_heartbeat_is_not_this_sessions_pid(self):
        """The outage in one assertion: the live heartbeat must never name the test process."""
        live = control_panel.ROOT / "learning/control_panel/pump.json"
        if not live.exists():
            self.skipTest("no live heartbeat in this checkout")
        try:
            payload = json.loads(live.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.skipTest("the live heartbeat is being rewritten right now")
        self.assertNotEqual(
            int(payload.get("process") or 0), os.getpid(),
            "this test process became the AUTO clock's owner; the pump path leaked",
        )


class NoTestWroteTheLiveRuntimeState(unittest.TestCase):
    """P0's own metric.

    Read through the module rather than a pytest fixture: a fixture cannot be injected into a
    ``unittest.TestCase`` method, and this project's suite is unittest-shaped.  The session-level
    teardown in ``conftest`` re-checks the same ledger after the very last test, so a violation in a
    file that sorts after this one is reported too.
    """

    def test_the_guard_recorded_nothing(self):
        violations = conftest.PRODUCTION_WRITES
        self.assertEqual(
            violations, [],
            "PRODUCTION_RUNTIME_FILES_TOUCHED_BY_TESTS != 0:\n"
            + "\n".join(f"    {row['op']}({row['path']})" for row in violations),
        )


if __name__ == "__main__":
    unittest.main()
