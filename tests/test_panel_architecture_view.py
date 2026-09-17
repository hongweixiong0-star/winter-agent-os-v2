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
import unittest
from pathlib import Path

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

    def test_a_complete_interpreter_is_normal(self):
        self.assertEqual(panel.maa_cell(_Report(), {}), panel.MAA_NORMAL)

    def test_a_missing_maa_module_is_the_adb_fallback_not_a_crash(self):
        # The live defect of 2026-09-17: the production interpreter could not import
        # maa, so MAA was nominally default and actually absent.  ADB still worked,
        # so 异常 would be wrong, and 正常 is the silent degradation the doctrine bans.
        self.assertEqual(panel.maa_cell(_Report(missing=("maa",)), {}), panel.MAA_ADB_FALLBACK)

    def test_a_step_that_asked_for_maa_and_got_adb_is_degraded_even_if_maa_imports(self):
        axis = {"degraded": True}
        self.assertEqual(panel.maa_cell(_Report(), axis), panel.MAA_ADB_FALLBACK)

    def test_a_missing_module_other_than_maa_is_broken_not_degraded(self):
        # cv2 missing means the worker cannot run the production loop at all.
        self.assertEqual(panel.maa_cell(_Report(missing=("cv2",)), {}), panel.MAA_BROKEN)

    def test_no_interpreter_at_all_is_broken(self):
        self.assertEqual(panel.maa_cell(_Report(exists=False), {}), panel.MAA_BROKEN)


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

    def test_a_noticed_but_unsubmitted_gap_is_queued(self):
        from winter_agent_v2.escalation_queue import QUEUED

        label, _ = panel.workbuddy_cell({"current": self._record(state=QUEUED)}, {"available": True})
        self.assertEqual(label, panel.WORKBUDDY_LABELS["QUEUED"])

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

    def test_the_six_labels_are_the_operators_six_words(self):
        self.assertEqual(set(panel.WORKBUDDY_LABELS.values()),
                         {"● 待命", "● 排队", "● 开发中", "● 验证中", "● Blocked", "● 不可用"})


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


if __name__ == "__main__":
    unittest.main()
