import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from tools import control_panel as cp
from tools.control_panel import NO_WINDOW_FLAGS, _background_popen, _background_run, bootstrap_recovery_action, human_reason, load_continuous_selection, load_task_selection, parse_runtime_result, panel_clock_owner, save_task_selection, summarize_runtime_result, task_toggle_label
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
    def test_pump_persists_the_frozen_runtime_and_control_plane_build_identities(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "pump.json"
            frozen = SimpleNamespace(token="14a+test")
            with patch.object(cp, "PUMP_STATE_PATH", path), \
                 patch.object(cp, "CONTROL_PLANE_SOURCE_SHA256", "panel-source-sha256"), \
                 patch("winter_agent_v2.version_identity.process_revision", return_value=frozen):
                pump = cp.QueuePump(interval=60)
                pump._persist()
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["runtime_loaded_revision"], frozen.token)
        self.assertTrue(payload["runtime_loaded_at"])
        self.assertEqual(payload["control_plane_loaded_sha256"], "panel-source-sha256")

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

    def test_role_switch_failure_restarts_a_fresh_global_cycle_after_backoff(self):
        # A prior Goal may have a verifier failure even though it yielded. The role
        # switch cooldown prevents hammering the target; the next cycle must still
        # observe the current role and continue its work.
        self.assertTrue(cp.should_continue_auto_cycle(
            healthy=False, reason="ROLE_SWITCH_FAILED:ROLE_A:SOURCE_ROLE_HOME_NOT_CONFIRMED",
            continuous=True, stop_requested=False, paused=False, fatal=False,
        ))
        self.assertEqual(cp.ROLE_SWITCH_RETRY_DELAY_MS, 15_000)

    def test_confirmed_role_handoff_restarts_even_after_prior_goal_failure(self):
        for reason in (
            "ROLE_SWITCHED_TO:ROLE_B",
            "ROLE_IDENTITY_CHANGED:ROLE_B",
        ):
            with self.subTest(reason=reason):
                self.assertTrue(cp.should_continue_auto_cycle(
                    healthy=False, reason=reason, continuous=True,
                    stop_requested=False, paused=False, fatal=False,
                ))

    def test_operator_pause_and_fatal_stop_still_suppress_role_switch_retry(self):
        args = {
            "healthy": False,
            "reason": "ROLE_SWITCH_FAILED:ROLE_A:SOURCE_ROLE_HOME_NOT_CONFIRMED",
            "continuous": True,
            "stop_requested": False,
            "paused": False,
        }
        self.assertFalse(cp.should_continue_auto_cycle(**{**args, "paused": True}, fatal=False))
        self.assertFalse(cp.should_continue_auto_cycle(**args, fatal=True))

    def test_non_handoff_runtime_failure_does_not_auto_restart(self):
        self.assertFalse(cp.should_continue_auto_cycle(
            healthy=False, reason="DEVICE_FATAL", continuous=True,
            stop_requested=False, paused=False, fatal=False,
        ))

    def test_unknown_page_is_not_reported_as_success(self):
        payload = {"stop_reason": "unknown_page", "steps": [{"decision": {"skill": "SAFE_STOP"}}]}
        summary = summarize_runtime_result(payload, 0)
        self.assertFalse(summary["ok"], "a capability gap is not a completed game task")
        self.assertTrue(summary["healthy"], "a safe refusal is not a runtime failure")
        self.assertEqual(summary["stop_category"], "CAPABILITY_GAP")
        self.assertEqual(summary["agent_state"], "SAFE_STOP")

    def test_fruitless_stop_is_a_normal_no_action_cycle(self):
        payload = {"stop_reason": "every_page_this_run_was_fruitless",
                   "steps": [{"decision": {"skill": "SAFE_STOP"},
                              "execution": None, "verification": None}]}
        summary = summarize_runtime_result(payload, 0)
        self.assertTrue(summary["ok"])
        self.assertTrue(summary["healthy"])
        self.assertEqual(summary["stop_category"], "EXPECTED_NO_ACTION")
        self.assertEqual(summary["agent_state"], "IDLE")

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

    def test_the_event_records_age_has_exactly_one_rule(self):
        """``event_goal_is_current`` was a second, contradicting rule for one fact.

        It read ``item["updated_at"]`` while the record writes ``verified_at``, so it answered
        False for every input -- and its only test asserted that False, which is why a
        permanently-wrong function survived.  The one rule is the audit's
        (``state_truth.legacy_event_row_for``): it reads ``verified_at``, checks the recorded
        countdown against the clock, and carries the verdict on the row.
        """
        source = (Path(__file__).resolve().parents[1] / "tools/control_panel.py").read_text(encoding="utf-8")
        self.assertNotIn("def event_goal_is_current", source)
        self.assertIn("legacy_event_row_for", source)

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


class NextCycleDelayLadder(unittest.TestCase):
    """TASK THROUGHPUT V1 §23/§24.

    A round that spent its action budget, stalled on a target, handed the device to
    another role, or asked to re-observe the same role has more of this cycle to do and
    must restart at once.  Everything else keeps the breather that stops the panel from
    becoming a tight restart loop on an environmental failure.
    """

    def _summary(self, reason, executed=0):
        return {"reason": reason, "executed": executed}

    def test_a_role_re_observation_restarts_at_once(self):
        # Measured live: a round on pin 7055f02 ended 03:14:37 with this reason after
        # three successful actions and the panel then idled 30 s.  The device was idle
        # while the account still had runnable Goals (DEVICE_IDLE_WHILE_WORK_EXISTS).
        delay = cp.next_cycle_delay(
            reason=cp.ROLE_REOBSERVE_REASON,
            summary=self._summary(cp.ROLE_REOBSERVE_REASON),
            role_handoff=False, retryable_role_switch=False,
        )
        self.assertTrue(delay.immediate)
        self.assertEqual(delay.delay_ms, 0)
        self.assertEqual(delay.delay_text, "立即")

    def test_a_spent_action_budget_restarts_at_once(self):
        delay = cp.next_cycle_delay(
            reason="MAX_ACTIONS_REACHED",
            summary=self._summary("MAX_ACTIONS_REACHED", executed=24),
            role_handoff=False, retryable_role_switch=False,
        )
        self.assertTrue(delay.immediate)
        self.assertEqual(delay.delay_ms, 0)

    def test_a_stalled_target_restarts_at_once(self):
        delay = cp.next_cycle_delay(
            reason="SEMANTIC_TARGET_NOT_VERIFIED",
            summary=self._summary("SEMANTIC_TARGET_NOT_VERIFIED"),
            role_handoff=False, retryable_role_switch=False,
        )
        self.assertTrue(delay.immediate)

    def test_a_role_handoff_restarts_at_once_with_its_own_wording(self):
        delay = cp.next_cycle_delay(
            reason="ROLE_SWITCHED_TO:ROLE_B",
            summary=self._summary("ROLE_SWITCHED_TO:ROLE_B"),
            role_handoff=True, retryable_role_switch=False,
        )
        self.assertTrue(delay.immediate)
        self.assertEqual(delay.delay_text, "立即刷新角色")

    def test_an_empty_action_budget_keeps_the_breather(self):
        # ``executed == 0`` means the round resolved no target at all; that is the
        # environmental-failure shape the breather exists to contain.
        delay = cp.next_cycle_delay(
            reason="MAX_ACTIONS_REACHED",
            summary=self._summary("MAX_ACTIONS_REACHED", executed=0),
            role_handoff=False, retryable_role_switch=False,
        )
        self.assertFalse(delay.immediate)
        self.assertEqual(delay.delay_ms, 30_000)
        self.assertEqual(delay.delay_text, "30 秒")

    def test_a_retryable_role_switch_keeps_its_cooldown(self):
        delay = cp.next_cycle_delay(
            reason="ROLE_SWITCH_FAILED:ROLE_A:SOURCE_ROLE_HOME_NOT_CONFIRMED",
            summary=self._summary("ROLE_SWITCH_FAILED:ROLE_A:SOURCE_ROLE_HOME_NOT_CONFIRMED"),
            role_handoff=False, retryable_role_switch=True,
        )
        self.assertFalse(delay.immediate)
        self.assertEqual(delay.delay_ms, cp.ROLE_SWITCH_RETRY_DELAY_MS)

    def test_the_reason_that_stopped_auto_lets_the_next_round_start(self):
        # The live outage, end to end: a round on pin 553d8df ended 03:14:37 for this
        # reason after three successful actions, the classifier called it a system
        # failure, ``should_continue_auto_cycle`` then said no, and AUTO never started
        # another round -- the device sat idle while the account still had runnable
        # Goals.  Both halves of that chain are asserted here.
        summary = summarize_runtime_result({
            "stop_reason": cp.ROLE_REOBSERVE_REASON,
            "steps": [{"decision": {"skill": "OPEN_MAIL"},
                       "execution": {"executed": True}, "verification": {"ok": True}}],
        }, 0)
        self.assertNotEqual(summary["stop_category"], "SYSTEM_FAILURE")
        self.assertTrue(summary["healthy"])
        self.assertTrue(cp.should_continue_auto_cycle(
            healthy=summary["healthy"], reason=cp.ROLE_REOBSERVE_REASON, continuous=True,
            stop_requested=False, paused=False, fatal=False,
        ))

    def test_a_missing_activity_clock_falls_back_to_the_unbounded_wait(self):
        from winter_agent_v2 import event_schedule

        def broken(_seconds, _schedule):
            raise RuntimeError("event clock unreadable")

        with patch.object(event_schedule, "bounded_poll_delay_seconds", broken):
            bounded = cp.activity_bounded_wait_ms(600_000)
        self.assertEqual(bounded, 600_000, "an unreadable clock must keep ordinary polling")
        delay = cp.next_cycle_delay(
            reason="no_idle_march", summary=self._summary("no_idle_march"),
            role_handoff=False, retryable_role_switch=False, bound_ms=cp.activity_bounded_wait_ms,
        )
        self.assertEqual(delay.delay_ms, 600_000)
        self.assertEqual(delay.delay_text, "10 分钟")

    def test_the_wait_is_capped_at_the_next_activity_node(self):
        delay = cp.next_cycle_delay(
            reason="GLOBAL_WAIT", summary=self._summary("GLOBAL_WAIT"),
            role_handoff=False, retryable_role_switch=False, bound_ms=lambda _ms: 12_345,
        )
        self.assertEqual(delay.delay_ms, 12_345)
        self.assertEqual(delay.delay_text, "活动节点前 12 秒")


class PidLivenessInThePanelsOwnContext(unittest.TestCase):
    """The instance guard must be answerable where the panel actually runs.

    Measured 2026-09-30: the panel runs through ``launch_pinned_production.py`` ->
    ``runpy.run_path`` with ``cwd=CODE_ROOT``, where ``tools/`` is not on ``sys.path``.
    ``_pid_is_live`` used only ``from panel_restart import alive``, which raised
    ``ModuleNotFoundError`` there, and its documented "unanswerable returns True" branch
    then answered "live" for *every* pid.  A stale ``pump.json`` pid therefore blocked
    AUTO for a whole window while reporting a process that did not exist:

        03:41:11  另一个实例正在运行（pid 3168）：本窗口只读，不消费队列、不启动 AUTO
        03:42:00  不自动启动 AUTO：另一个实例（pid 3168）正在运行。本窗口只读。

    ``alive`` was never wrong -- ``alive(3168)`` is False.  Only the name it was looked up
    under was wrong.
    """

    def test_a_dead_pid_is_not_reported_live(self):
        self.assertFalse(cp._pid_is_live(0))
        self.assertFalse(cp._pid_is_live(-1))
        # A pid that cannot exist.  With the bare-name-only import this answered True in the
        # panel's own cwd, which is the whole defect.
        self.assertFalse(cp._pid_is_live(999_999_999))

    def test_a_live_pid_is_reported_live(self):
        import os

        self.assertTrue(cp._pid_is_live(os.getpid()))

    def test_the_answer_survives_the_panels_own_working_directory_and_import_path(self):
        # Reproduce the real context in a subprocess: cwd is the repo root, ``tools/`` is not
        # on the path, so the bare ``panel_restart`` import fails exactly as it does in the
        # panel.  This is the regression test for the fallback spellings.
        import os
        import subprocess
        import sys

        root = Path(__file__).resolve().parents[1]
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        script = (
            "import os, sys\n"
            "from tools.control_panel import _pid_is_live\n"
            "print(_pid_is_live(999999999), _pid_is_live(os.getpid()))\n"
        )
        done = subprocess.run(
            [sys.executable, "-c", script], cwd=str(root), env=env,
            capture_output=True, text=True, timeout=180,
        )
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        self.assertEqual(done.stdout.strip(), "False True", done.stdout + done.stderr[-1000:])


if __name__ == "__main__":
    unittest.main()


class TheHaltIsNeverSilent(unittest.TestCase):
    """A cycle that is not continued must say why.

    Measured 2026-09-30 11:21 local.  A 24-action round was relabelled SYSTEM_FAILURE, the
    continuation gate declined, and ``panel.log`` simply stopped after the snapshot refresh --
    the gate had no ``else`` branch at all.  AUTO looked alive while the device sat idle for
    fifteen minutes, and nothing on screen said why.
    """

    def _args(self, **over):
        base = dict(healthy=True, reason="MAX_ACTIONS_REACHED", continuous=True,
                    stop_requested=False, paused=False, fatal=False)
        base.update(over)
        return base

    def test_a_round_that_continues_owes_no_explanation(self):
        self.assertEqual(cp.auto_halt_reason(**self._args()), "")

    def test_a_confirmed_role_handoff_counts_as_continuing(self):
        self.assertEqual(
            cp.auto_halt_reason(**self._args(healthy=False, reason="ROLE_SWITCHED_TO:ROLE_B")),
            "",
        )
        self.assertEqual(
            cp.auto_halt_reason(
                **self._args(healthy=False, reason="ROLE_SWITCH_FAILED:ROLE_A:NO_HOME")),
            "",
        )

    def test_each_way_of_not_continuing_names_itself(self):
        for over, needle in (
            ({"continuous": False}, "连续运行开关"),
            ({"stop_requested": True}, "停止请求"),
            ({"paused": True}, "暂停"),
            ({"fatal": True}, "不可自动恢复"),
        ):
            with self.subTest(declined_by=needle):
                reason = cp.auto_halt_reason(**self._args(healthy=False, **over))
                self.assertTrue(reason, "a halt without a reason is the defect")
                self.assertIn(needle, reason)

    def test_an_unhealthy_round_is_reported_as_a_fault_naming_the_reason(self):
        reason = cp.auto_halt_reason(**self._args(healthy=False, reason="DEVICE_FATAL"))
        self.assertIn("DEVICE_FATAL", reason)
        self.assertIn("系统故障", reason)

    def test_the_note_agrees_with_the_gate_by_construction(self):
        """One rule in one place: the boolean is derived from the reason, never re-decided."""
        for healthy in (True, False):
            for continuous in (True, False):
                for paused in (True, False):
                    for fatal in (True, False):
                        for stop_requested in (True, False):
                            args = self._args(healthy=healthy, continuous=continuous,
                                              paused=paused, fatal=fatal,
                                              stop_requested=stop_requested)
                            self.assertEqual(
                                cp.should_continue_auto_cycle(**args),
                                not cp.auto_halt_reason(**args),
                                args,
                            )
