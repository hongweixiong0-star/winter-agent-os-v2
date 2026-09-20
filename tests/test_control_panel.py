import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from tools import control_panel as cp
from tools.control_panel import NO_WINDOW_FLAGS, _background_popen, _background_run, bootstrap_recovery_action, event_goal_is_current, human_reason, load_continuous_selection, load_task_selection, parse_runtime_result, panel_clock_owner, save_task_selection, summarize_runtime_result, task_toggle_label
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.skills import v2_registry


NOW = datetime(2026, 9, 18, 8, 40, 0, tzinfo=timezone.utc)


class OneWindowOwnsTheClock(unittest.TestCase):
    def test_the_probe_path_follows_the_log_path_it_is_derived_from(self):
        """A probe file that stays in production while tests redirect the log is how a
        test came to write the file the next audit read "gateway 正常" out of."""
        with TemporaryDirectory() as tmp:
            redirected = Path(tmp) / "panel.log"
            with patch.object(cp, "PANEL_LOG_PATH", redirected):
                self.assertEqual(cp.gateway_probe_path(), Path(tmp) / "gateway.json")
                self.assertEqual(cp.panel_pid_path(), Path(tmp) / "panel.pid")
    """Two panels in one minute, measured 2026-09-18: pump.json named pid 26428 at
    16:34:52, a console start was logged at 16:35:19, pump.json then named pid 16508 at
    16:36:22.  Two pumps and two would-be AUTOs on one device -- the Single UI Owner
    rule had no equivalent at the window layer."""

    def _owner(self, payload, *, path):
        with patch.object(cp, "PUMP_STATE_PATH", path):
            return panel_clock_owner(now=NOW)

    def test_a_fresh_heartbeat_names_its_owner(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "pump.json"
            path.write_text(json.dumps(
                {"process": 4242, "written_at": (NOW - timedelta(seconds=12)).isoformat()}
            ), encoding="utf-8")
            self.assertEqual(self._owner(None, path=path), (4242, 12.0))

    def test_a_stale_heartbeat_is_still_reported_with_its_age(self):
        # Reported, not hidden: the caller decides, and the age is the evidence.
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "pump.json"
            path.write_text(json.dumps(
                {"process": 4242, "written_at": (NOW - timedelta(seconds=600)).isoformat()}
            ), encoding="utf-8")
            pid, age = self._owner(None, path=path)
            self.assertEqual(pid, 4242)
            self.assertGreater(age, cp.PANEL_CLOCK_MAX_AGE_SECONDS)

    def test_a_clock_that_never_ticked_has_no_owner(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(self._owner(None, path=Path(tmp) / "pump.json"), (0, float("inf")))

    def test_an_unparseable_stamp_cannot_be_read_as_recent(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "pump.json"
            path.write_text(json.dumps({"process": 4242, "written_at": "not a time"}),
                            encoding="utf-8")
            # Neither half is offered: a pid the caller cannot date is not an owner.
            self.assertEqual(self._owner(None, path=path), (0, float("inf")))

    def test_a_missing_pid_is_not_a_owner(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "pump.json"
            path.write_text(json.dumps({"written_at": NOW.isoformat()}), encoding="utf-8")
            self.assertEqual(self._owner(None, path=path), (0, float("inf")))

    def test_the_losing_window_does_not_consume_the_queue(self):
        stub = SimpleNamespace(_other_instance=4242, operator_intent="RUNNING")
        self.assertTrue(cp.observes_only(stub))
        self.assertFalse(cp.ControlPanel._auto_development_allowed(stub))

    def test_the_owning_window_still_consumes_unless_the_operator_stopped(self):
        running = SimpleNamespace(_other_instance=0, operator_intent="RUNNING")
        stopped = SimpleNamespace(_other_instance=0, operator_intent="STOPPED")
        self.assertFalse(cp.observes_only(running))
        self.assertTrue(cp.ControlPanel._auto_development_allowed(running))
        self.assertFalse(cp.ControlPanel._auto_development_allowed(stopped))

    def test_a_gate_answers_for_an_object_that_has_never_heard_of_it(self):
        """An existing stub (``SimpleNamespace(operator_intent=...)``) crashed the first
        version of this gate.  A guard that raises on an unexpected object is worse than
        one that assumes ownership: assuming ownership is what the window does anyway."""
        bare = SimpleNamespace(operator_intent="RUNNING")
        self.assertFalse(cp.observes_only(bare))
        self.assertTrue(cp.ControlPanel._auto_development_allowed(bare))

    def test_three_gates_consult_it_and_the_window_says_so(self):
        """Source-level, because each gate is one early return in a long method."""
        source = (Path(__file__).resolve().parents[1] / "tools/control_panel.py").read_text(
            encoding="utf-8"
        )
        for gate in ("def _auto_development_allowed", "def _maybe_validate",
                     "def _maybe_autostart", "def _narrate_pump"):
            body = source[source.index(gate):]
            body = body[:body.index("\n    def ", 1)] if "\n    def " in body else body
            self.assertIn("observes_only(self)", body, gate)
        self.assertIn("panel_clock_owner()", source)
        self.assertIn("只读", source)
        # The pump is started only by the window that owns the clock.
        start = source.index("self.pump = QueuePump(")
        self.assertIn("else:\n            self.pump.start()", source[start:start + 900])


class SwitchSemantics(unittest.TestCase):
    """Operator P1, 2026-09-18: the strategy switches rendered as bare checkbuttons whose
    indicator read as a ✕ -- a glyph this project reserves for 关闭/取消/失败/拒绝."""

    def test_a_cross_never_means_enabled(self):
        for enabled in (True, False):
            label = cp.policy_toggle_label("日常低保", enabled)
            self.assertNotIn("✕", label)
            self.assertNotIn("×", label)

    def test_the_label_states_the_state(self):
        self.assertIn("已启用", cp.policy_toggle_label("日常低保", True))
        self.assertIn("未启用", cp.policy_toggle_label("日常低保", False))

    def test_a_safety_rule_says_it_cannot_be_edited(self):
        label = cp.policy_toggle_label("真实支付", True, editable=False)
        self.assertIn("永久禁止", label)
        self.assertIn("🔒", label)

    def test_the_strategy_page_uses_it_and_repaints_on_toggle(self):
        source = (Path(__file__).resolve().parents[1] / "tools/control_panel.py").read_text(
            encoding="utf-8"
        )
        strategy = source[source.index("def _strategy"):source.index("def _toggle_policy")]
        self.assertIn("policy_toggle_label(", strategy)
        self.assertIn("self._toggle_policy(", strategy)
        self.assertNotIn("ttk.Checkbutton(grid, text=name", source)


class ControlPanelTests(unittest.TestCase):
    def test_parse_runtime_result_uses_final_json_line(self):
        output = '启动中\n{"steps": [], "stop_reason": "no_idle_march"}\n'
        self.assertEqual(parse_runtime_result(output)["stop_reason"], "no_idle_march")

    def test_parse_runtime_result_rejects_unrelated_json(self):
        self.assertEqual(parse_runtime_result('{"status":"ok"}'), {})

    def test_summary_counts_real_execution_and_verification(self):
        payload = {
            "stop_reason": "target_skill_verified",
            "steps": [
                {"execution": {"executed": True}, "verification": {"ok": True}},
                {"execution": {"executed": False}, "verification": None},
            ],
        }
        summary = summarize_runtime_result(payload)
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["executed"], 1)
        self.assertEqual(summary["verified"], 1)

    def test_summary_marks_verifier_failure(self):
        payload = {"stop_reason": "VERIFIER_UNKNOWN", "steps": [{"verification": {"ok": False}}]}
        self.assertFalse(summarize_runtime_result(payload)["ok"])

    def test_unknown_page_is_not_reported_as_success(self):
        payload = {"stop_reason": "unknown_page", "steps": [{"decision": {"skill": "SAFE_STOP"}}]}
        self.assertFalse(summarize_runtime_result(payload, 0)["ok"])

    def test_user_visible_status_is_chinese(self):
        self.assertEqual(human_reason("DEVICE_BUSY"), "设备忙")

    def test_task_toggle_label_never_uses_cross_for_enabled(self):
        self.assertEqual(task_toggle_label("采集", True), "✓ 采集 · 已启用")
        self.assertEqual(task_toggle_label("采集", False), "○ 采集 · 未启用")
        self.assertEqual(task_toggle_label("建筑", False, False), "◇ 建筑 · 待接入")

    def test_only_real_panel_tasks_are_restored(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "panel.json"
            save_task_selection(path, {"采集": False, "建筑": True})
            restored = load_task_selection(path, ("采集", "建筑"))
            self.assertEqual(restored, {"采集": False, "建筑": False})

    def test_mail_is_a_real_panel_task(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "panel.json"
            save_task_selection(path, {"邮件": True, "建筑": True})
            restored = load_task_selection(path, ("邮件", "建筑"))
            self.assertEqual(restored, {"邮件": True, "建筑": False})

    def test_exploration_is_a_real_panel_task(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "panel.json"
            save_task_selection(path, {"探险": True})
            self.assertEqual(load_task_selection(path, ("探险",)), {"探险": True})

    def test_alliance_is_a_real_panel_task(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "panel.json"
            save_task_selection(path, {"联盟": True})
            self.assertEqual(load_task_selection(path, ("联盟",)), {"联盟": True})

    def test_training_is_a_real_panel_task(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "panel.json"
            save_task_selection(path, {"训练": True})
            self.assertEqual(load_task_selection(path, ("训练",)), {"训练": True})

    def test_mail_all_clear_is_a_successful_zero_click_stop(self):
        payload = {"stop_reason":"mail_all_clear", "steps":[{"decision":{"skill":"SAFE_STOP"}, "execution":None, "verification":None}]}
        self.assertTrue(summarize_runtime_result(payload, 0)["ok"])

    def test_exploration_not_ready_is_a_successful_zero_click_stop(self):
        payload = {"stop_reason":"exploration_income_not_ready", "steps":[{"decision":{"skill":"SAFE_STOP"}}]}
        self.assertTrue(summarize_runtime_result(payload, 0)["ok"])

    def test_alliance_no_action_is_a_successful_zero_click_stop(self):
        payload = {"stop_reason":"alliance_action_not_needed", "steps":[{"decision":{"skill":"SAFE_STOP"}}]}
        self.assertTrue(summarize_runtime_result(payload, 0)["ok"])

    def test_training_queue_busy_is_a_successful_zero_click_stop(self):
        payload = {"stop_reason":"training_queue_busy", "steps":[{"decision":{"skill":"SAFE_STOP"}}]}
        self.assertTrue(summarize_runtime_result(payload, 0)["ok"])

    def test_old_event_record_is_not_presented_as_today(self):
        item = {"updated_at":"2026-09-05T23:52:00+08:00"}
        now = datetime.fromisoformat("2026-09-07T18:00:00+08:00")
        self.assertFalse(event_goal_is_current(item, now))

    def test_continuous_mode_defaults_on_and_is_persisted(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "panel.json"
            self.assertTrue(load_continuous_selection(path))
            save_task_selection(path, {"采集": True}, continuous=False)
            self.assertFalse(load_continuous_selection(path))

    def test_bootstrap_waits_once_for_unknown_launch_frame(self):
        unknown = WorldState()
        self.assertEqual(bootstrap_recovery_action(unknown, 1), "WAIT")
        self.assertEqual(bootstrap_recovery_action(unknown, 2), "BACK")

    def test_bootstrap_only_accepts_pages_supported_by_gather_runtime(self):
        self.assertEqual(bootstrap_recovery_action(WorldState(page=Page.HOME), 0), "READY")
        self.assertEqual(bootstrap_recovery_action(WorldState(page=Page.MAP), 0), "READY")
        self.assertEqual(bootstrap_recovery_action(WorldState(page=Page.POPUP), 0), "READY")
        self.assertEqual(bootstrap_recovery_action(WorldState(page=Page.EVENT), 0), "BACK")

    def test_mail_goal_never_inherits_gather_actions(self):
        brain = RuleBrain(current_goal="MAIL")
        resource = WorldState(page=Page.RESOURCE_DETAIL, resource_available=True, confidence=0.99)
        march = WorldState(page=Page.MARCH, resource_target="WOOD", confidence=0.99)
        # A resource panel is not this goal's panel, and since 2026-09-19 the brain takes one
        # Back off it (``_leave_foreign_page_once``) instead of stopping on the spot: measured
        # live, a run had stopped with ``goal_page_mismatch`` while the client was still
        # standing on this goal's own panel, so the next run could not hop home.  What this
        # test has always guarded is unchanged -- the goal must not start gathering -- and the
        # assertion is now stricter, because it pins the reason as well as the skill.
        leave = brain.decide(resource, v2_registry())
        self.assertEqual(leave.skill, "BACK")
        self.assertEqual(leave.reason, "mail_goal_leaves_a_panel_it_does_not_own")
        self.assertEqual(brain.decide(march, v2_registry()).skill, "SAFE_STOP")
        self.assertEqual(brain.decide(WorldState(page=Page.MAP, confidence=0.99), v2_registry()).skill, "OPEN_HOME")
        search = WorldState(page=Page.MAP, resource_search_open=True, confidence=0.99)
        self.assertEqual(brain.decide(search, v2_registry()).skill, "BACK")
        # The Back is taken once per run, so the honest stop still follows rather than a loop.
        self.assertEqual(brain.decide(resource, v2_registry()).skill, "SAFE_STOP")

    def test_single_unknown_active_mail_category_selects_badged_tab_first(self):
        state = WorldState(page=Page.MAIL, mail={"status":"CLAIMABLE", "active_tab":None, "tab_badges":{"ALLIANCE":24}}, confidence=0.99)
        decision = RuleBrain(current_goal="MAIL").decide(state, v2_registry())
        self.assertEqual(decision.skill, "SELECT_MAIL_ALLIANCE_TAB")

    def test_multiple_unknown_active_mail_categories_navigate_first(self):
        state = WorldState(page=Page.MAIL, mail={"status":"CLAIMABLE", "active_tab":None, "tab_badges":{"WAR":3, "SYSTEM":2}}, confidence=0.99)
        decision = RuleBrain(current_goal="MAIL").decide(state, v2_registry())
        self.assertEqual(decision.skill, "SELECT_MAIL_SYSTEM_TAB")

    def test_intel_goal_never_inherits_gather_actions(self):
        brain = RuleBrain(current_goal="INTEL")
        resource = WorldState(page=Page.RESOURCE_DETAIL, resource_available=True, confidence=0.99)
        # Same one-shot leave as the mail goal: a resource panel is not this goal's panel, so
        # the brain backs off it once and then stops honestly (see the sibling test above).
        leave = brain.decide(resource, v2_registry())
        self.assertEqual(leave.skill, "BACK")
        self.assertEqual(leave.reason, "intel_goal_leaves_a_panel_it_does_not_own")
        self.assertEqual(brain.decide(resource, v2_registry()).skill, "SAFE_STOP")

    def test_intel_goal_leaves_completed_exploration_page(self):
        brain = RuleBrain(current_goal="INTEL")
        exploration = WorldState(page=Page.EXPLORATION, exploration={"status":"CLAIMED"}, confidence=0.99)
        self.assertEqual(brain.decide(exploration, v2_registry()).skill, "BACK")

    @patch("tools.control_panel.subprocess.run")
    def test_console_utilities_are_backgrounded(self, run):
        _background_run(["adb", "devices"], capture_output=True)
        self.assertEqual(run.call_args.kwargs["creationflags"], NO_WINDOW_FLAGS)

    @patch("tools.control_panel.subprocess.Popen")
    def test_runtime_children_are_backgrounded(self, popen):
        _background_popen(["python.exe", "run_live.py"])
        self.assertEqual(popen.call_args.kwargs["creationflags"], NO_WINDOW_FLAGS)

    def test_command_center_has_exactly_seven_primary_tabs(self):
        source = (Path(__file__).resolve().parents[1] / "tools/control_panel.py").read_text(encoding="utf-8")
        build = source[source.index("    def _build(self)"):source.index("    def _tab(self")]
        self.assertIn("self._overview(); self._goals(); self._strategy(); self._event_goal(); self._capabilities(); self._auto_development(); self._system()", build)
        for legacy in ("self._tasks()", "self._coverage()", "self._knowledge()", "self._logs()", "self._settings()", "self._learning()"):
            self.assertNotIn(legacy, build)

    def test_header_shows_the_frozen_layers_and_no_provider(self):
        # Operator directive 2026-09-18: the status row is V2 / MAA / MuMu / 游戏 / AUTO /
        # WorkBuddy / 预载 / 时间, one word each.  It grew long sentences (页面 和 模式 moved
        # into the panels that own them) and prose in a top bar cannot be scanned; what
        # must not change is that Qwen is not a layer (it is an optional offline provider)
        # and recognition is MAA's job, so neither may appear as a first-class status.
        source = (Path(__file__).resolve().parents[1] / "tools/control_panel.py").read_text(encoding="utf-8")
        build = source[source.index("    def _build(self)"):source.index("    def _tab(self")]
        self.assertIn("for i, (label, key) in enumerate(SYSTEM_INDICATORS):", build)
        for label, key in (("V2", "dot_v2"), ("MAA", "dot_maa"), ("MuMu", "dot_mumu"),
                           ("游戏", "dot_game"), ("AUTO", "dot_auto"),
                           ("WorkBuddy", "dot_wb"), ("预载", "dot_boot"), ("时间", "clock")):
            self.assertIn(f'("{label}", "{key}")', source)
        for gone in ('("Qwen", "qwen")', '("Vision", "vision")'):
            self.assertNotIn(gone, build)

    def test_the_header_cells_are_painted_from_one_vocabulary(self):
        """One word per cell, from ``state_truth.health_of`` -- never a sentence."""
        source = (Path(__file__).resolve().parents[1] / "tools/control_panel.py").read_text(encoding="utf-8")
        self.assertIn("self._set_health(", source)
        self.assertIn("DOT_TEXT.get(colour, DOT_UNKNOWN)", source)

    def test_the_panel_names_no_model(self):
        # Same boundary the rest of the package holds: a model is WorkBuddy's
        # replaceable compute, so the window may display whatever name the ledger
        # recorded but must not contain a literal of its own.  Comments are exempt
        # (they explain history); code is not.
        import ast

        tree = ast.parse((Path(__file__).resolve().parents[1] / "tools/control_panel.py").read_text(encoding="utf-8"))
        words = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                words.add(node.value.lower())
            elif isinstance(node, ast.Name):
                words.add(node.id.lower())
        for model in ("deepseek", "glm-", "hy4", "qwen", "gpt", "claude"):
            self.assertFalse([w for w in words if model in w], model)

    def test_the_status_defaults_cover_every_header_and_workbuddy_cell(self):
        from tools import control_panel as panel_module

        defaults = panel_module.status_defaults()
        for key in ("agent", "maa", "device", "game", "page", "mode", "workbuddy", "clock"):
            self.assertIn(key, defaults)
        for key in ("wb_state", "wb_capability", "wb_reason", "wb_job", "wb_model", "wb_duration",
                    "wb_job_state", "wb_improvement", "wb_result"):
            self.assertIn(key, defaults)
        self.assertNotIn("qwen", defaults)


    def test_gui_launches_unified_runtime_without_selecting_goal(self):
        source = (Path(__file__).resolve().parents[1] / "tools/control_panel.py").read_text(encoding="utf-8")
        worker = source[source.index("    def _run_unified_worker"):source.index("    def _ensure_device")]
        self.assertNotIn('"--goal"', worker)
        self.assertIn("RUNTIME_PATH", worker)


if __name__ == "__main__":
    unittest.main()
