"""What the window says about the four frozen layers, and how it derives it.

Operator directive 2026-09-17: the GUI had to stop presenting Qwen and Vision as
first-class components, show MAA as 正常 / 降级ADB / 异常, show WorkBuddy as
待命 / 排队 / 开发中 / 验证中 / Blocked / 不可用, and stop printing "未知 / 待识别"
for things nobody had read yet.

The tests below pin the *derivations*, because that is where a display layer can
lie: a cell that says 正常 while the worker runs on ADB capture is worse than no
cell at all.  Every rule here is asserted against a measurement taken from the
real project during the 2026-09-17 session, and each fake input states where the
shape came from.

No Tk window is opened: `status_defaults()` exists precisely so the mapping can be
driven without one, which is also why the panel's own handlers can be tested.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import control_panel as panel  # noqa: E402


class _Report:
    """Stand-in for ``runtime_env.InterpreterReport`` with only what the cell reads."""

    def __init__(self, *, exists: bool = True, missing: tuple[str, ...] = ()) -> None:
        self.exists = exists
        self.missing = missing
        self.present = ()


class MaaCellTest(unittest.TestCase):
    """MAA is 正常 / 降级ADB / 异常 -- and 降级ADB is not a cosmetic warning."""

    def test_a_complete_interpreter_with_execution_history_is_normal(self):
        self.assertEqual(panel.maa_cell(_Report(), {"steps": 10}), panel.MAA_NORMAL)

    def test_a_missing_maa_module_is_unusable_not_merely_degraded(self):
        # The live defect of 2026-09-17: the production interpreter cannot import maa,
        # so MAA cannot come up at all.  That is 不可用 -- "degraded" would suggest it
        # still executes and merely falls back per step, which it cannot.
        axis = {"steps": 10, "maa_at": ""}
        self.assertEqual(panel.maa_cell(_Report(missing=("maa",)), axis), panel.MAA_BROKEN)

    def test_a_step_that_asked_for_maa_and_got_adb_is_degraded_even_if_maa_imports(self):
        axis = {"steps": 10, "degraded": True}
        self.assertEqual(panel.maa_cell(_Report(), axis), panel.MAA_ADB_FALLBACK)

    def test_a_recorded_maa_failure_means_unusable_even_when_the_interpreter_is_fine(self):
        # MAA_CONNECT_FAILED is the adapter saying it could not come up.  The interpreter
        # probe cannot see that, which is why the ledger is consulted as well.
        axis = {"steps": 10, "maa_failures": ("MAA_CONNECT_FAILED",)}
        self.assertEqual(panel.maa_cell(_Report(), axis), panel.MAA_BROKEN)

    def test_a_missing_module_other_than_maa_is_unusable(self):
        # cv2 missing means the worker cannot run the production loop at all.
        self.assertEqual(panel.maa_cell(_Report(missing=("cv2",)), {"steps": 5}), panel.MAA_BROKEN)

    def test_no_interpreter_at_all_is_unusable(self):
        self.assertEqual(panel.maa_cell(_Report(exists=False), {"steps": 5}), panel.MAA_BROKEN)

    def test_no_ledger_rows_at_all_is_uninitialised_not_healthy(self):
        # Nothing has ever executed.  Saying 正常 here would be the config-based guess
        # the operator forbade: the capability may be fine and it is still unproven.
        self.assertEqual(panel.maa_cell(_Report(), {"steps": 0}), panel.MAA_UNINITIALISED)

    def test_a_fresh_maa_execution_is_plain_normal(self):
        now = datetime(2026, 9, 17, 15, 0, tzinfo=timezone.utc)
        axis = {"steps": 10, "maa_last_at": "2026-09-17T14:56:00+00:00"}
        self.assertEqual(panel.maa_cell(_Report(), axis, now=now), "● 正常 · 4 分钟前执行")

    def test_a_stale_maa_execution_says_how_stale(self):
        # The measured live case: 30 MAA-preferred steps that all used MAA, the newest
        # 64 minutes old, while the loop kept working through ADB-only skills.  The
        # probe says the capability is intact; the freshness says the evidence is old.
        now = datetime(2026, 9, 17, 15, 0, tzinfo=timezone.utc)
        axis = {"steps": 200, "maa_used": 30, "maa_last_at": "2026-09-17T13:44:28+00:00"}
        cell = panel.maa_cell(_Report(), axis, now=now)
        self.assertTrue(cell.startswith(panel.MAA_NORMAL), cell)
        self.assertIn("1.3 小时前无 MAA 执行", cell)

    def test_no_maa_execution_ever_recorded_is_normal_with_a_reason_not_a_claim(self):
        cell = panel.maa_cell(_Report(), {"steps": 40, "maa_used": 0})
        self.assertEqual(cell, panel.MAA_NORMAL)
        self.assertIn("没有 MAA 执行记录", panel.maa_note(_Report(), {"steps": 40, "maa_used": 0}))

    def test_the_note_names_the_evidence_for_every_state(self):
        for axis, needle in (
            ({"steps": 0}, "未初始化"),
            ({"steps": 5, "degraded": True}, "降级ADB"),
            ({"steps": 5, "maa_failures": ("MAA_IMPORT_FAILED:X",)}, "MAA_IMPORT_FAILED"),
        ):
            self.assertIn(needle, panel.maa_note(_Report(), axis), axis)


class AutoCellTest(unittest.TestCase):
    """AUTO comes from the control surface, because a status file can outlive its worker."""

    def _cell(self, **kwargs):
        base = dict(starting=False, worker_alive=False, paused=False, stop_requested=False,
                    restart_scheduled=False)
        base.update(kwargs)
        return panel.auto_cell(**base)

    def test_a_live_worker_is_running(self):
        self.assertEqual(self._cell(worker_alive=True), panel.AUTO_RUNNING)

    def test_a_worker_being_spawned_is_starting(self):
        self.assertEqual(self._cell(starting=True), panel.AUTO_STARTING)

    def test_a_paused_loop_is_paused(self):
        self.assertEqual(self._cell(worker_alive=True, paused=True), panel.AUTO_PAUSED)

    def test_a_scheduled_next_round_is_waiting_not_stopped(self):
        self.assertEqual(self._cell(restart_scheduled=True), panel.AUTO_WAITING)

    def test_no_worker_and_no_restart_is_stopped(self):
        self.assertEqual(self._cell(), panel.AUTO_STOPPED)

    def test_an_operator_stop_wins_over_everything(self):
        self.assertEqual(self._cell(worker_alive=True, paused=True, stop_requested=True), panel.AUTO_STOPPED)

    def test_the_cell_never_reads_a_status_file(self):
        # The point of the function: AUTO_RUNNING in runtime_snapshot.json is written by
        # the worker, so a worker that died leaves it behind.  Deriving from it would
        # show a running loop with no process behind it.  Scanned through the AST so the
        # function's own explanation of that mistake does not trip the check.
        import ast

        tree = ast.parse((ROOT / "tools/control_panel.py").read_text(encoding="utf-8"))
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == "auto_cell")
        body = function.body[1:] if (function.body and isinstance(function.body[0], ast.Expr)
                                     and isinstance(function.body[0].value, ast.Constant)) else function.body
        code = ast.dump(ast.Module(body=body, type_ignores=[]))
        for forbidden in ("snapshot", "agent_state", "runtime_store"):
            self.assertNotIn(forbidden, code, forbidden)
        self.assertIn("worker_alive", code)


class DeviceCellTest(unittest.TestCase):
    """MuMu and 游戏 read a real probe; a configured serial is not a connected device."""

    @staticmethod
    def _status(**kwargs):
        base = {"connected": True, "serial": "127.0.0.1:7555", "resolution": (720, 1280),
                "foreground_package": "com.gof.global"}
        base.update(kwargs)

        class _S:
            pass

        status = _S()
        for key, value in base.items():
            setattr(status, key, value)
        return status

    def test_an_unanswered_probe_says_unprobed_not_connected(self):
        # ok=None means the probe has not run yet.
        self.assertEqual(panel.device_cells({"ok": None, "status": None, "error": ""}, "com.gof.global"),
                         ("未探测", panel.PENDING))

    def test_a_failed_probe_is_a_disconnection_not_a_missing_reading(self):
        # Measured by tools/verify_panel_wiring.py against a port nothing serves: the
        # probe stored status=None, and the cell said 未探测 -- silence rendered as
        # "no data yet" when the real fact was "the device is not there".
        state = {"ok": False, "status": None, "error": "adb.exe: device '127.0.0.1:59999' not found"}
        mumu, game = panel.device_cells(state, "com.gof.global")
        self.assertTrue(mumu.startswith("● 未连接"), mumu)
        self.assertIn("not found", mumu)
        self.assertEqual(game, panel.PENDING)

    def test_a_disconnected_status_says_so(self):
        state = {"ok": True, "status": self._status(connected=False), "error": ""}
        mumu, game = panel.device_cells(state, "com.gof.global")
        self.assertEqual(mumu, "● 未连接")
        self.assertEqual(game, panel.PENDING)

    def test_a_connected_device_with_the_game_foreground_reads_running(self):
        state = {"ok": True, "status": self._status(), "error": ""}
        mumu, game = panel.device_cells(state, "com.gof.global")
        self.assertIn("已连接", mumu)
        self.assertIn("127.0.0.1:7555", mumu)
        self.assertIn("720x1280", mumu)
        self.assertEqual(game, "运行中")

    def test_another_app_foreground_names_it_instead_of_guessing(self):
        state = {"ok": True, "status": self._status(foreground_package="com.android.launcher"), "error": ""}
        _, game = panel.device_cells(state, "com.gof.global")
        self.assertIn("未在前台", game)
        self.assertIn("com.android.launcher", game)

    def test_a_connected_device_with_no_focus_is_unread(self):
        state = {"ok": True, "status": self._status(foreground_package=""), "error": ""}
        _, game = panel.device_cells(state, "com.gof.global")
        self.assertEqual(game, panel.PENDING)

    def test_the_probe_is_read_only(self):
        # A status probe must not connect, launch or tap: the operator's AUTO loop owns
        # the client while the panel is open.
        source = (ROOT / "tools/control_panel.py").read_text(encoding="utf-8")
        body = source[source.index("    def _poll_device("):source.index("class ControlPanel:")]
        for forbidden in (".launch(", ".tap(", ".swipe(", "resolve_connection"):
            self.assertNotIn(forbidden, body, forbidden)


class GatewayCellTest(unittest.TestCase):
    """A gateway verdict is only as good as its age."""

    def test_an_unprobed_gateway_is_pending(self):
        self.assertEqual(panel.gateway_cell({}), "网关状态待测")

    def test_a_fresh_verdict_is_shown(self):
        now = datetime(2026, 9, 17, 15, 0, tzinfo=timezone.utc)
        cell = panel.gateway_cell({"available": True, "checked_at": "14:59:57",
                                   "checked_at_utc": "2026-09-17T14:59:57+00:00"}, now=now)
        self.assertIn("网关正常", cell)

    def test_a_stale_verdict_stops_claiming_health(self):
        # The operator asked for a disconnect to show up; a four-minute-old "正常" must
        # not keep presenting itself as the current state.
        now = datetime(2026, 9, 17, 15, 0, tzinfo=timezone.utc)
        cell = panel.gateway_cell({"available": True, "checked_at": "14:56:00",
                                   "checked_at_utc": "2026-09-17T14:56:00+00:00"}, now=now)
        self.assertIn("待测", cell)

    def test_a_rejected_credential_is_named(self):
        now = datetime(2026, 9, 17, 15, 0, tzinfo=timezone.utc)
        cell = panel.gateway_cell({"available": False, "reason": "AUTH_REJECTED", "checked_at": "14:59:58",
                                   "checked_at_utc": "2026-09-17T14:59:58+00:00"}, now=now)
        self.assertIn("网关不可用", cell)
        self.assertIn("不一致", cell)


class BackendAxisTest(unittest.TestCase):
    """执行后端 must separate 'not migrated yet' from 'really degraded'."""

    def test_a_skill_deliberately_on_adb_is_not_called_degraded(self):
        # Live shape, 2026-09-17: SCAN_MAP_FOR_BEAST is P3 and ``backend_routing.json``
        # keeps it on ADB on purpose.  Reading that as a fallback would invent an
        # incident every time the beast route ran.
        rows = [{"used_backend": "ADB", "capture_backend": "ADB_EXEC_OUT", "preferred_backend": "ADB",
                 "latency_ms": 660.7, "fallback_used": False}]
        axis = panel.backend_axis(rows)
        self.assertFalse(axis["degraded"])
        self.assertIn("未迁移", axis["label"])
        self.assertIn("661ms", axis["label"])

    def test_a_step_that_asked_for_maa_and_used_adb_is_degraded(self):
        rows = [{"used_backend": "ADB", "capture_backend": "ADB_EXEC_OUT", "preferred_backend": "MAA"}]
        axis = panel.backend_axis(rows)
        self.assertTrue(axis["degraded"])
        self.assertIn("降级", axis["label"])

    def test_maa_is_named_with_the_capture_path(self):
        rows = [{"used_backend": "MAA", "capture_backend": "MAA_MUMU_EXTRAS", "preferred_backend": "MAA",
                 "latency_ms": 8.9}]
        axis = panel.backend_axis(rows)
        self.assertFalse(axis["degraded"])
        self.assertEqual(axis["label"], "MAA · MAA_MUMU_EXTRAS · 9ms")

    def test_an_explicit_fallback_flag_counts_even_when_the_last_row_looks_fine(self):
        rows = [{"used_backend": "MAA", "capture_backend": "MAA_MUMU_EXTRAS", "preferred_backend": "MAA",
                 "fallback_used": True, "error": "MAA_TAP_FAILED"}]
        self.assertTrue(panel.backend_axis(rows)["degraded"])

    def test_no_rows_is_unread_not_a_backend_name(self):
        axis = panel.backend_axis([])
        self.assertEqual(axis["label"], panel.PENDING)
        self.assertFalse(axis["degraded"])

    def test_the_recent_mix_is_reported(self):
        rows = [{"used_backend": "MAA", "preferred_backend": "MAA"},
                {"used_backend": "ADB", "preferred_backend": "ADB"},
                {"used_backend": "ADB", "preferred_backend": "ADB"}]
        self.assertEqual(panel.backend_axis(rows)["mix"], "MAA 1 / ADB 2（近 3 步）")


class CapabilityVocabularyTest(unittest.TestCase):
    """未读取 / 待刷新 / 不可用 / 未解锁 / 已识别 / 可执行 / 执行中 / Blocked."""

    def test_never_read_says_so_instead_of_unknown(self):
        # 452 of 522 rows are exactly this: MISSING with nothing ever read.  Calling
        # them 未知 claimed a failed look that never happened.
        entry = {"lifecycle": "MISSING", "implementation_status": "MISSING",
                 "unlock_status": "UNKNOWN", "current_role_available": "UNKNOWN"}
        self.assertEqual(panel.capability_state_cn(entry), panel.PENDING)
        self.assertEqual(panel.capability_lifecycle_cn(entry), "未实现")

    def test_a_forbidden_real_money_row_is_unavailable(self):
        entry = {"real_money_cost": "FORBIDDEN", "lifecycle": "MISSING"}
        self.assertEqual(panel.capability_state_cn(entry), "不可用")

    def test_a_locked_unlock_state_is_its_own_word(self):
        entry = {"unlock_status": "LOCKED", "lifecycle": "MISSING"}
        self.assertEqual(panel.capability_state_cn(entry), "未解锁")

    def test_the_skill_being_executed_right_now_is_executing(self):
        entry = {"existing_skill": "OPEN_MAIL", "implementation_status": "EXISTING", "lifecycle": "LIVE_VERIFIED"}
        self.assertEqual(panel.capability_state_cn(entry, running_skill="OPEN_MAIL"), "执行中")

    def test_a_named_blocker_wins_over_the_lifecycle(self):
        entry = {"lifecycle": "CANDIDATE", "implementation_status": "EXISTING",
                 "blocked_reason": "the role cannot put a second march on the map"}
        self.assertEqual(panel.capability_state_cn(entry), "Blocked")
        self.assertEqual(panel.capability_lifecycle_cn(entry), "Blocked")

    def test_imported_episodes_without_timestamps_are_pending_a_refresh(self):
        # The catalog's own evidence policy: rows without ``recorded_at`` cannot
        # support a verification.  So the honest word is 待刷新, not 可执行.
        entry = {"lifecycle": "MISSING", "implementation_status": "EXISTING", "existing_skill": "GATHER_RESOURCE"}
        self.assertEqual(panel.capability_state_cn(entry, claims=4), "待刷新")

    def test_verified_plus_stable_skill_reads_as_stable(self):
        entry = {"lifecycle": "LIVE_VERIFIED", "implementation_status": "EXISTING"}
        self.assertEqual(panel.capability_lifecycle_cn(entry), "Live Verified")
        self.assertEqual(panel.capability_lifecycle_cn(entry, skill_state="STABLE"), "Stable")

    def test_a_live_tried_row_says_live_tried(self):
        entry = {"lifecycle": "LIVE_TRIED", "implementation_status": "EXISTING"}
        self.assertEqual(panel.capability_lifecycle_cn(entry), "Live Tried")

    def test_an_observed_role_availability_is_recognised_not_implemented(self):
        entry = {"lifecycle": "MISSING", "implementation_status": "MISSING",
                 "current_role_available": "OBSERVED_AVAILABLE"}
        self.assertEqual(panel.capability_state_cn(entry), "已识别")


class RuntimeStatusTest(unittest.TestCase):
    """等待 is a real state, and it is not the same as 未读取 or 未知."""

    def test_an_ordinary_weather_stop_reads_as_waiting(self):
        for reason in ("mail_all_clear", "training_queue_busy", "verified_beast_target_not_visible"):
            self.assertEqual(panel.runtime_status_cn(reason, running=False), "等待", reason)

    def test_a_running_runtime_is_executing(self):
        self.assertEqual(panel.runtime_status_cn("target_skill_verified", running=True), "执行中")

    def test_nothing_recorded_is_unread(self):
        self.assertEqual(panel.runtime_status_cn(None, running=False), panel.PENDING)

    def test_a_running_runtime_is_executing_even_on_an_unseen_reason(self):
        # The loop is playing; that is the useful answer, and it is not a claim about
        # the reason string.
        self.assertEqual(panel.runtime_status_cn("SOMETHING_WE_HAVE_NEVER_SEEN", running=True), "执行中")

    def test_an_idle_runtime_with_an_unclassified_reason_says_so(self):
        self.assertEqual(panel.runtime_status_cn("SOMETHING_WE_HAVE_NEVER_SEEN", running=False), panel.UNKNOWN_STOP)

    def test_the_waiting_set_is_taken_from_the_stop_reasons_that_exist(self):
        snapshot = (ROOT / "winter_agent_v2/runtime_snapshot.py").read_text(encoding="utf-8")
        for reason in ("no_idle_march", "reserved_march_for_stamina", "mail_all_clear",
                       "verified_beast_target_not_visible", "training_queue_busy"):
            self.assertIn(reason, snapshot, reason)
            self.assertIn(reason, panel.RUNTIME_WAITING_STOPS, reason)


class WorkBuddyCellTest(unittest.TestCase):
    """待命 / 排队 / 开发中 / 验证中 / Blocked / 不可用 -- computed, never guessed."""

    @staticmethod
    def _record(**kwargs):
        from winter_agent_v2.escalation_queue import NEW, EscalationRecord

        values = {"key": "CAP|TYPE|SKILL", "capability": "CAP", "state": NEW}
        values.update(kwargs)
        return EscalationRecord(**values)

    def test_an_unavailable_gateway_is_reported_as_unavailable(self):
        label, detail = panel.workbuddy_cell({"current": self._record()}, {"available": False, "reason": "AUTH_REJECTED"})
        self.assertEqual(label, panel.WORKBUDDY_LABELS["UNAVAILABLE"])
        self.assertEqual(detail, "AUTH_REJECTED")

    def test_a_running_job_is_developing(self):
        from winter_agent_v2.escalation_queue import WORKING

        record = self._record(state=WORKING, job_id="f465a6c9")
        label, detail = panel.workbuddy_cell({"current": record}, {"available": True})
        self.assertEqual(label, panel.WORKBUDDY_LABELS["WORKING"])
        self.assertEqual(detail, "f465a6c9")

    def test_a_created_but_never_dispatched_gap_is_not_shown_as_queued(self):
        """The operator's 2026-09-18 correction, on the state that caused it.

        A record in ``NEW`` has been noticed and nothing has been sent anywhere.
        Showing it as "● 排队" claimed a job was waiting its turn; the real answer is
        "● 待提交", and the difference matters because the queue's own consumer has to
        drive it from there.
        """
        from winter_agent_v2.escalation_queue import NEW

        label, detail = panel.workbuddy_cell({"current": self._record(state=NEW)}, {"available": True})
        self.assertEqual(label, panel.WORKBUDDY_LABELS["PENDING_SUBMIT"])
        self.assertEqual(detail, "CAP|TYPE|SKILL")

    def test_a_decided_but_unsent_gap_is_queued(self):
        from winter_agent_v2.escalation_queue import QUEUED

        label, _ = panel.workbuddy_cell({"current": self._record(state=QUEUED)}, {"available": True})
        self.assertEqual(label, panel.WORKBUDDY_LABELS["QUEUED"])

    def test_a_gap_with_a_job_id_is_submitted_before_it_is_developing(self):
        """A job id means the gateway took it; 开发中 means an agent is editing."""
        from winter_agent_v2.escalation_queue import SUBMITTED

        label, detail = panel.workbuddy_cell(
            {"current": self._record(state=SUBMITTED, job_id="2934e9cd")}, {"available": True}
        )
        self.assertEqual(label, panel.WORKBUDDY_LABELS["SUBMITTED"])
        self.assertEqual(detail, "2934e9cd")

    def test_a_changed_tree_waiting_for_live_verification_is_verifying(self):
        # CODE_CHANGED means code moved but no production episode proves anything:
        # the honest state is 验证中, and only LIVE_VERIFIED leaves it.
        from winter_agent_v2.escalation_queue import CODE_CHANGED, DONE

        record = self._record(state=DONE, outcome=CODE_CHANGED, job_id="job-1")
        label, detail = panel.workbuddy_cell({"current": None, "pending_verify": (record,)}, {"available": True})
        self.assertEqual(label, panel.WORKBUDDY_LABELS["VERIFYING"])
        self.assertEqual(detail, record.key)

    def test_a_blocked_record_surfaces_as_blocked(self):
        from winter_agent_v2.escalation_queue import BLOCKED

        label, _ = panel.workbuddy_cell({"blocked": (self._record(state=BLOCKED),)}, {"available": True})
        self.assertEqual(label, panel.WORKBUDDY_LABELS["BLOCKED"])

    def test_an_empty_queue_is_idle(self):
        label, detail = panel.workbuddy_cell({}, {"available": True})
        self.assertEqual(label, panel.WORKBUDDY_LABELS["IDLE"])
        self.assertEqual(detail, "")

    def test_an_untested_gateway_does_not_cry_unavailable(self):
        # Before the first poll the answer is unknown, and 不可用 would be a claim.
        label, _ = panel.workbuddy_cell({}, {"available": None})
        self.assertEqual(label, panel.WORKBUDDY_LABELS["IDLE"])

    def test_the_labels_are_the_operators_words_for_each_real_state(self):
        """One distinct word per state: the ladder is 待提交 -> 排队 -> 已提交 -> 开发中."""
        self.assertEqual(
            set(panel.WORKBUDDY_LABELS.values()),
            {"● 待提交", "● 待命", "● 排队", "● 已提交", "● 开发中", "● 验证中",
             "● Blocked", "● 不可用"},
        )
        self.assertEqual(panel.STATE_ZH["NEW"], "待提交")
        self.assertEqual(panel.STATE_ZH["QUEUED"], "排队")
        self.assertEqual(panel.STATE_ZH["SUBMITTED"], "已提交")
        self.assertEqual(panel.STATE_ZH["WORKING"], "开发中")


class GatewayReasonTest(unittest.TestCase):
    """NO_CREDENTIAL and AUTH_REJECTED both look like 'unavailable' and are not."""

    def test_a_missing_credential_names_the_variable(self):
        self.assertIn("环境变量", panel.gateway_reason_cn("NO_CREDENTIAL"))

    def test_a_rejected_credential_names_the_mismatch(self):
        # Measured 2026-09-17: the session's environment held the first launch's
        # random password while a different one was serving on :8080.
        self.assertIn("不一致", panel.gateway_reason_cn("AUTH_REJECTED"))

    def test_an_unknown_reason_is_passed_through_rather_than_invented(self):
        self.assertEqual(panel.gateway_reason_cn("SOMETHING_NEW"), "SOMETHING_NEW")


class KpiTest(unittest.TestCase):
    """The eight numbers, each traceable to the file it came from."""

    def test_the_row_is_exactly_the_operators_eight_and_each_has_a_source(self):
        kpi = panel.overview_kpis()
        self.assertEqual(list(panel.CATALOG_META), ["observed", "implemented", "tried", "verified",
                                                    "stable", "never", "blocked", "queue"])
        for key, entry in kpi.items():
            self.assertTrue(entry["value"], key)
            # A number nobody can trace back to its origin is a number people learn
            # to ignore, so every card names either a file or the live registry.
            self.assertTrue(".json" in entry["source"] or "Registry" in entry["source"], key)

    def test_the_catalog_numbers_come_from_the_catalog(self):
        import json

        catalog = json.loads((ROOT / "knowledge/game/capability_catalog.json").read_text(encoding="utf-8"))
        summary = catalog["summary"]
        kpi = panel.overview_kpis()
        self.assertEqual(int(kpi["verified"]["value"]), summary["by_lifecycle"]["LIVE_VERIFIED"])
        self.assertEqual(int(kpi["implemented"]["value"]), summary["by_implementation"]["EXISTING"])
        self.assertEqual(int(kpi["never"]["value"]), summary["by_lifecycle"]["MISSING"])

    def test_stable_says_what_the_registry_actually_holds(self):
        # Zero today, which is a fact about the promotion gate rather than a bug --
        # so the card carries the distribution instead of a bare 0.
        kpi = panel.overview_kpis()
        self.assertIn("STABLE", kpi["stable"]["source"])
        self.assertIn("VERIFIED", kpi["stable"]["source"])


class EpisodesEvidencePolicyTest(unittest.TestCase):
    """A row without ``recorded_at`` is a claim, and the panel says so."""

    def test_the_index_separates_live_rows_from_imported_ones(self):
        index = panel.episode_index()
        if not index:
            self.skipTest("no episodes recorded yet")
        self.assertTrue(all({"live", "claims", "verified", "failed"} <= set(entry) for entry in index.values()))
        claimed = {skill for skill, entry in index.items() if entry["claims"] and not entry["live"]}
        catalog = panel.capability_catalog().get("capabilities") or []
        states = {panel.capability_state_cn(entry, claims=1)
                  for entry in catalog if str(entry.get("existing_skill") or "") in claimed}
        self.assertNotIn("可执行", states, "a skill whose only rows are imported must not read as 可执行")


class PanelIntegrationTest(unittest.TestCase):
    """Build the real window, refresh it, and read every cell back.

    This is the test that would have caught the first version of ``_model_rows``: it read
    ``Rung.jobs`` and ``Rung.live_verified``, neither of which exists, and nothing noticed
    because the model-stats file did not exist until a real job was reconciled -- at which
    point the 自动开发 tab raised inside a Tk callback and went blank.  Unit tests on the
    pure functions cannot see that class of wiring fault; opening the window does.

    Deliberately never enters ``mainloop``.  Until 2026-09-18 the constructor itself
    scheduled ``start()`` at 1800 ms without keeping the id, so an event loop that ran
    past that would have spawned a real worker while the operator's own AUTO loop owned
    the device.  The auto-start now lives only in ``_maybe_autostart`` (called from
    ``main``), but the rule stands: build the window, read the cells, never loop.
    """

    panel = None
    root = None

    @classmethod
    def setUpClass(cls):
        try:
            import tkinter as tk
        except Exception as exc:  # noqa: BLE001
            raise unittest.SkipTest(f"tkinter unavailable: {exc}")
        from tools import control_panel as module

        module.ControlPanel._enforce_retention = lambda self: None  # never prune evidence here
        # The window narrates through the real ``_append``, which writes the panel log,
        # so a test that builds one used to land its lines in the production
        # learning/control_panel/panel.log -- the file the startup decision is audited
        # from.  Measured 2026-09-18: "控制台已启动" appeared there at 09:13, 09:19 and
        # 09:20 with no window ever having been opened, once per test run.  Redirected
        # next to the state path, same as the other window-building test.
        cls._log_dir = tempfile.TemporaryDirectory()
        cls._log_patch = mock.patch.object(
            module, "PANEL_LOG_PATH", Path(cls._log_dir.name) / "panel.log"
        )
        # The constructor also saves the operator's own state file (it carries their
        # remembered stop), and the window now owns a queue pump whose ledger is the
        # development queue.  Both are redirected for the same reason as the log: a
        # test window must not be able to touch production, and a pump pointed at the
        # live ledger could submit a real job.
        cls._state_patch = mock.patch.object(
            module, "PANEL_STATE_PATH", Path(cls._log_dir.name) / "panel_state.json"
        )
        cls._ledger_patch = mock.patch.object(
            module, "_ESCALATION_LEDGER_PATH",
            Path(cls._log_dir.name) / "learning/workbuddy_escalations.jsonl",
        )
        cls._pump_patch = mock.patch.object(
            module, "PUMP_STATE_PATH", Path(cls._log_dir.name) / "pump.json"
        )
        cls._log_patch.start()
        cls._state_patch.start()
        cls._ledger_patch.start()
        cls._pump_patch.start()
        try:
            cls.root = tk.Tk()
        except Exception as exc:  # noqa: BLE001 - no display
            raise unittest.SkipTest(f"no display: {exc}")
        cls.root.withdraw()
        try:
            cls.panel = module.ControlPanel(cls.root)
        except Exception as exc:  # noqa: BLE001
            cls.root.destroy()
            raise AssertionError(f"the window does not build: {type(exc).__name__}: {exc}") from exc
        cls.panel.continuous.set(False)

    @classmethod
    def tearDownClass(cls):
        if cls.panel is not None:
            try:
                cls.panel.probes.stop()
            except Exception:  # noqa: BLE001
                pass
            try:
                cls.panel.pump.stop()
            except Exception:  # noqa: BLE001
                pass
        if cls.root is not None:
            cls.root.destroy()
        if getattr(cls, "_log_patch", None) is not None:
            cls._log_patch.stop()
        if getattr(cls, "_state_patch", None) is not None:
            cls._state_patch.stop()
        if getattr(cls, "_ledger_patch", None) is not None:
            cls._ledger_patch.stop()
        if getattr(cls, "_pump_patch", None) is not None:
            cls._pump_patch.stop()
        if getattr(cls, "_log_dir", None) is not None:
            cls._log_dir.cleanup()

    def test_every_header_cell_is_populated_after_a_refresh(self):
        self.panel._refresh_runtime_snapshot(schedule_next=False)
        for key in ("agent", "maa", "device", "game", "page", "mode", "workbuddy", "clock"):
            value = self.panel.values[key].get()
            self.assertTrue(value.strip(), key)
            self.assertNotIn("未知 / 待识别", value, key)

    def test_the_decision_column_and_the_workbuddy_card_are_populated(self):
        self.panel._refresh_runtime_snapshot(schedule_next=False)
        for key in ("backend", "backend_detail", "runtime_state", "wb_state", "wb_result", "wb_gateway"):
            self.assertTrue(self.panel.values[key].get().strip(), key)

    def test_the_auto_cell_equals_its_own_derivation_from_the_panel_state(self):
        # Wiring: what the header shows must be the function's answer to the panel's own
        # control state, not a literal written next to it.
        self.panel._refresh_runtime_snapshot(schedule_next=False)
        worker = self.panel.process
        expected = panel.auto_cell(
            starting=self.panel.starting,
            worker_alive=bool(worker is not None and worker.poll() is None),
            paused=self.panel.paused,
            stop_requested=self.panel.stop_requested,
            restart_scheduled=self.panel.repeat_after_id is not None,
        )
        self.assertEqual(self.panel.values["mode"].get(), expected)
        self.assertIn(expected, {panel.AUTO_RUNNING, panel.AUTO_STARTING, panel.AUTO_PAUSED,
                                 panel.AUTO_WAITING, panel.AUTO_STOPPED})

    def test_the_kpi_cards_show_live_numbers_with_their_sources(self):
        self.panel._refresh_runtime_snapshot(schedule_next=False)
        truth = panel.overview_kpis()
        for key, entry in truth.items():
            self.assertEqual(self.panel.kpi[key].get(), entry["value"], key)
            self.assertTrue(self.panel.kpi_source[key].get().strip(), key)

    def test_the_capability_and_skill_tables_are_filled_from_their_sources(self):
        self.panel._refresh_runtime_snapshot(schedule_next=False)
        rows = self.panel.capability_tree.get_children()
        self.assertTrue(rows, "capability table empty")
        catalog = panel.capability_catalog()
        expected = sum(1 for entry in catalog["capabilities"]
                       if entry.get("existing_skill") or entry.get("live_attempts")
                       or entry.get("blocked_reason"))
        self.assertEqual(len(rows), expected)
        self.assertEqual(len(self.panel.skill_tree.get_children()), len(self.panel.registry.all()))

    def test_the_development_tab_refreshes_without_raising(self):
        # The regression this class exists for.
        self.panel._refresh_auto_development()
        self.assertTrue(self.panel.dev_note.get().strip())
        self.assertIn("最近成功开发 Capability", self.panel.dev_note.get())

    def test_the_model_table_handles_the_real_stats_file(self):
        rows = self.panel._model_rows()
        for row in rows:
            self.assertTrue(row["model"])
            self.assertTrue(row["jobs"].isdigit(), row)
            self.assertIn("%", row["success"])
            self.assertEqual(row["cost"], "不可得（jobs API 无用量字段）")

    def test_a_source_change_moves_the_displayed_number(self):
        # Same file, changed on disk -> the cell follows.  Done on a copied tree so the
        # production catalog is never written to.
        import json as _json
        import tempfile

        catalog = panel.capability_catalog()
        baseline = int(panel.overview_kpis()["verified"]["value"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "knowledge/game").mkdir(parents=True)
            (root / "knowledge/goals").mkdir(parents=True)
            (root / "learning").mkdir(parents=True)
            mutated = _json.loads(_json.dumps(catalog))
            for entry in mutated["capabilities"]:
                if entry.get("lifecycle") == "LIVE_VERIFIED":
                    entry["lifecycle"] = "MISSING"
            (root / "knowledge/game/capability_catalog.json").write_text(
                _json.dumps(mutated, ensure_ascii=False), encoding="utf-8")
            changed = int(panel.overview_kpis(root)["verified"]["value"])
        self.assertGreater(baseline, 0)
        self.assertEqual(changed, 0)


if __name__ == "__main__":
    unittest.main()
