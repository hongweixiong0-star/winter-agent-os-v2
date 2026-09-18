"""Truth Source Audit: a displayed state must name its source, or say it does not know.

What these tests defend
-----------------------
The operator found the window printing ``当前角色 xhw`` while the client was logged in as
something else.  The value was not a stale cache: it was a **string literal** in the panel
(``text="xhw"``), next to another literal (``text="● 在线"``) that claimed the device was
online no matter what.  A constant is worse than a blank, because a blank cannot be
mistaken for a measurement.

So the rules under test are the operator's ladder:

    LIVE OBSERVED > fresh verified runtime state > persisted last-known > requested

with a cached value allowed to help recovery but never allowed to impersonate a current
one, and with a disagreement recorded as ``STATE_CONFLICT`` instead of silently resolved.

The last class here is the one that matters most: it reads the *panel source* and fails if
a state cell is written as a literal again.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import state_truth as st  # noqa: E402

NOW = datetime(2026, 9, 18, 5, 0, 0, tzinfo=timezone.utc)
PANEL = ROOT / "tools/control_panel.py"


def write(root: Path, relative: str, payload) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, (list, tuple)):
        path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in payload) + "\n",
            encoding="utf-8",
        )
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def episode(stamp: str, *, page: str = "MAP", goal: str = "AUTO_DISCOVERY",
            skill: str = "OPEN_MAP", verifier: bool = True, revision: str = "abc1234",
            resources=None, tag: str = "") -> dict:
    """One synthetic row.  ``tag`` keeps ``episode_id`` unique across a batch.

    Uniqueness matters: the role-scope check asks "is this foreign row among the *recent*
    ones", and an id derived only from the timestamp makes every row in a batch the same
    episode -- so the check saw one id and called all of history current.
    """
    return {
        "episode_id": stamp.replace("-", "").replace(":", "") + (f"_{tag}" if tag else ""),
        "recorded_at": stamp, "repo_revision": revision, "verifier_ok": verifier,
        "skill": skill, "goal_id": goal, "result": "SUCCESS",
        "state_after": {"page": page, "resources": resources or {}},
    }


class EveryStateNamesItsSource(unittest.TestCase):
    """No value may be returned without provenance -- that is the whole mechanism."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        write(self.tmp, st.SNAPSHOT, {
            "updated_at": NOW.isoformat(), "page": "MAP", "agent_state": "GOAL_RUNNING",
            "current_goal": "AUTO_DISCOVERY", "current_skill": "OPEN_MAP",
            "march_used": 1, "march_max": 3, "queues": {},
        })
        write(self.tmp, st.EPISODES, [episode(NOW.isoformat())])

    def report(self):
        return st.TruthAudit(self.tmp, now=NOW).report()

    def test_the_audit_answers_for_every_key_state_the_operator_listed(self):
        names = {v.name for v in self.report().values}
        for required in (
            "current_role", "current_page", "current_goal", "current_skill",
            "auto_state", "march_capacity", "resources", "queues", "feature_unlock",
            "event_state", "executor_backend", "version_active", "verifier",
            "workbuddy_jobs", "device_lease", "capability_lifecycle",
        ):
            self.assertIn(required, names, required)
        self.assertEqual(tuple(sorted(names)), tuple(sorted(st.audited_names())))

    def test_nothing_is_ever_returned_as_assumed(self):
        """A literal or a default is a defect, not a state."""
        for value in self.report().values:
            self.assertNotEqual(value.status, st.ASSUMED, value.name)

    def test_every_value_carries_a_source(self):
        for value in self.report().values:
            self.assertTrue(value.source, f"{value.name} has no source")
            if value.status in (st.FRESH_RUNTIME, st.LIVE_OBSERVED):
                self.assertTrue(value.observed_at, f"{value.name} claims freshness with no stamp")

    def test_a_missing_artifact_reads_unknown_rather_than_confident(self):
        bare = Path(tempfile.mkdtemp())
        report = st.TruthAudit(bare, now=NOW).report()
        for value in report.values:
            self.assertNotIn(value.status, (st.FRESH_RUNTIME, st.LIVE_OBSERVED), value.name)

    def test_an_empty_queue_reads_as_not_read_not_as_none(self):
        value = self.report().by_name("queues")
        self.assertEqual(value.status, st.UNKNOWN)
        self.assertIn("没读到", value.note)


class FreshnessIsNotWishful(unittest.TestCase):
    """An old observation must lose its confidence, not keep its value."""

    def test_a_fresh_snapshot_is_fresh_and_an_old_one_is_stale(self):
        tmp = Path(tempfile.mkdtemp())
        write(tmp, st.SNAPSHOT, {"updated_at": NOW.isoformat(), "page": "MAP"})
        fresh = st.TruthAudit(tmp, now=NOW).report().by_name("current_page")
        self.assertEqual(fresh.status, st.FRESH_RUNTIME)

        old = NOW - timedelta(days=30)
        write(tmp, st.SNAPSHOT, {"updated_at": old.isoformat(), "page": "MAP"})
        stale = st.TruthAudit(tmp, now=NOW).report().by_name("current_page")
        self.assertEqual(stale.status, st.STALE)
        self.assertIn("已过期", stale.display)
        self.assertIn(stale, st.TruthAudit(tmp, now=NOW).report().worst())

    def test_a_live_episode_keeps_a_longer_budget_than_a_runtime_republish(self):
        """Six hours behind a real frame is still an observation; two minutes of a
        runtime snapshot that stopped is not."""
        tmp = Path(tempfile.mkdtemp())
        when = NOW - timedelta(hours=2)
        write(tmp, st.EPISODES, [episode(when.isoformat())])
        value = st.TruthAudit(tmp, now=NOW).report().by_name("verifier")
        self.assertEqual(value.status, st.LIVE_OBSERVED)
        self.assertEqual(value.verification, "PASS")


class DisagreementIsRecordedNotResolved(unittest.TestCase):
    """Two sources answering differently is a finding, not a tie-break problem."""

    def test_a_page_disagreement_becomes_a_state_conflict(self):
        tmp = Path(tempfile.mkdtemp())
        write(tmp, st.SNAPSHOT, {"updated_at": NOW.isoformat(), "page": "HOME"})
        write(tmp, st.EPISODES, [episode(NOW.isoformat(), page="MAP")])
        report = st.TruthAudit(tmp, now=NOW).report()
        conflicts = report.conflicts_for("current_page")
        self.assertTrue(conflicts)
        self.assertIn("STATE_CONFLICT current_page", conflicts[0].describe())
        readings = dict(conflicts[0].readings)
        self.assertIn("HOME", readings.values())
        self.assertIn("MAP", readings.values())

    def test_agreement_is_not_a_conflict(self):
        tmp = Path(tempfile.mkdtemp())
        write(tmp, st.SNAPSHOT, {"updated_at": NOW.isoformat(), "page": "MAP"})
        write(tmp, st.EPISODES, [episode(NOW.isoformat(), page="MAP")])
        self.assertEqual(st.TruthAudit(tmp, now=NOW).report().conflicts_for("current_page"), ())

    def test_a_running_old_tree_is_reported_as_a_version_conflict(self):
        """A live episode from the previous revision must never be credited forward."""
        tmp = Path(tempfile.mkdtemp())
        write(tmp, st.EPISODES, [episode(NOW.isoformat(), revision="deadbee+3")])

        class Pinned(st.TruthAudit):
            def _head(self_inner):
                return "a1b2c3d4e5f6"

        report = Pinned(tmp, now=NOW).report()
        value = report.by_name("version_active")
        self.assertEqual(value.status, st.CONFLICT)
        self.assertIn("新版本的 episode 尚未产生", report.conflicts_for("version_active")[0].note)

    def test_an_impossible_march_reading_is_a_conflict_not_a_value(self):
        """Found live: the snapshot said ``march_used=21`` against ``march_max=3`` and the
        window drew it without complaint."""
        tmp = Path(tempfile.mkdtemp())
        write(tmp, st.SNAPSHOT, {
            "updated_at": NOW.isoformat(), "march_used": 21, "march_max": 3,
        })
        report = st.TruthAudit(tmp, now=NOW).report()
        value = report.by_name("march_capacity")
        self.assertEqual(value.status, st.CONFLICT)
        self.assertIn("超过容量", value.note)
        self.assertIn("STATE_CONFLICT march_capacity", report.conflicts_for("march_capacity")[0].describe())

    def test_a_plausible_march_reading_is_not_a_conflict(self):
        tmp = Path(tempfile.mkdtemp())
        write(tmp, st.SNAPSHOT, {
            "updated_at": NOW.isoformat(), "march_used": 1, "march_max": 3,
        })
        report = st.TruthAudit(tmp, now=NOW).report()
        self.assertEqual(report.by_name("march_capacity").status, st.FRESH_RUNTIME)
        self.assertEqual(report.conflicts_for("march_capacity"), ())

    def test_a_goal_disagreement_is_recorded_with_both_readings(self):
        """The window reads the snapshot; the host reads episodes.  When they disagree the
        reader must see both, not whichever file was read last."""
        tmp = Path(tempfile.mkdtemp())
        write(tmp, st.SNAPSHOT, {"updated_at": NOW.isoformat(), "current_goal": "AVOID_STAMINA_WASTE"})
        write(tmp, st.EPISODES, [episode(NOW.isoformat(), goal="BEAST_HUNT")])
        conflicts = st.TruthAudit(tmp, now=NOW).report().conflicts_for("current_goal")
        self.assertTrue(conflicts)
        readings = dict(conflicts[0].readings)
        self.assertEqual(readings[st.SNAPSHOT], "AVOID_STAMINA_WASTE")
        self.assertIn("BEAST_HUNT", readings.values())


class TheRoleScopesEverythingElse(unittest.TestCase):
    """The operator's case: a value belonging to one account shown under another."""

    def test_with_no_observation_the_role_is_unknown_and_says_so(self):
        tmp = Path(tempfile.mkdtemp())
        role = st.TruthAudit(tmp, now=NOW).report().by_name("current_role")
        self.assertEqual(role.status, st.UNKNOWN)
        self.assertEqual(role.value, "")
        self.assertIn("没有任何角色观测记录", role.note)
        self.assertIn("不得用配置名或默认值代替", role.note)

    def test_the_archived_probe_is_a_persisted_observation_not_a_current_fact(self):
        tmp = Path(tempfile.mkdtemp())
        write(tmp, f"{st.ROLE_PROBE_DIR}/probe.json", {
            "stamp": "20260916_184004",
            "candidate_identity_tokens": [
                {"text": "领主档案"}, {"text": "[zoe]xhw小号"}, {"text": "账号：1171757165"},
            ],
        })
        role = st.TruthAudit(tmp, now=NOW).report().by_name("current_role")
        self.assertEqual(role.role_id, "1171757165")
        self.assertIn("xhw小号", role.value)
        self.assertEqual(role.status, st.PERSISTED)
        self.assertEqual(role.observed_at, "2026-09-16T18:40:04+00:00")
        self.assertIn("不是当前真机确认值", role.note)

    def test_a_stale_role_makes_the_march_capacity_report_itself_unscoped(self):
        """March slots are a property of the account -- the corpus has 6 and 2 for two."""
        tmp = Path(tempfile.mkdtemp())
        write(tmp, st.SNAPSHOT, {"updated_at": NOW.isoformat(), "march_used": 1, "march_max": 3})
        write(tmp, f"{st.ROLE_PROBE_DIR}/probe.json", {
            "stamp": "20260916_184004",
            "candidate_identity_tokens": [{"text": "账号：1171757165"}],
        })
        value = st.TruthAudit(tmp, now=NOW).report().by_name("march_capacity")
        self.assertIn("未按当前角色确认", value.note)
        self.assertEqual(value.role_id, "1171757165")

    def test_the_probe_stamp_survives_its_underscore(self):
        """An all-digits test over ``20260916_184004`` silently produced no date at all."""
        self.assertEqual(st._probe_stamp("20260916_184004"), "2026-09-16T18:40:04+00:00")
        self.assertEqual(st._probe_stamp(""), "")
        self.assertEqual(st._probe_stamp("nonsense"), "")


class TheControlCentreIsWired(unittest.TestCase):
    """The layout rules the operator set, checked as structure rather than as pixels."""

    def setUp(self):
        from tools import control_panel

        self.panel = control_panel

    def test_the_top_bar_is_eight_cells_of_one_vocabulary(self):
        keys = [key for _, key in self.panel.SYSTEM_INDICATORS]
        self.assertEqual(len(keys), 8, keys)
        self.assertEqual(len(set(keys)), 8, "two cells sharing a value is a copy that drifts")
        self.assertIn("clock", keys)

    def test_every_indicator_starts_unconfirmed(self):
        """A bar that is green before anything is read lies about its only job."""
        defaults = self.panel.status_defaults()
        for _, key in self.panel.SYSTEM_INDICATORS:
            if key == "clock":
                continue
            self.assertEqual(defaults[key], self.panel.DOT_UNKNOWN, key)

    def test_the_six_words_are_the_whole_palette(self):
        words = {value.split(" ", 1)[-1] for value in self.panel.DOT_TEXT.values()}
        self.assertEqual(words, {"正常", "工作中", "等待", "降级", "异常", "未确认"})

    def test_the_health_palette_maps_onto_real_colours(self):
        listed = {word for word in
                  (v.split(" ", 1)[-1] for v in self.panel.DOT_TEXT.values())}
        self.assertTrue(listed)

    def test_every_flat_tab_is_regrouped(self):
        """Twelve tabs became unreadable; none may be left out of the grouping."""
        for name in ("任务", "策略", "目标", "活动", "自动化覆盖", "能力", "知识",
                     "自动开发", "系统", "日志", "设置", "总览"):
            self.assertIn(name, self.panel.TAB_GROUP, name)

    def test_the_new_panels_have_status_values_and_they_start_empty(self):
        """A panel with a plausible default is the same defect as a literal role."""
        defaults = self.panel.status_defaults()
        for key in ("why_idle", "executor_mix", "progress", "bootstrap", "coverage",
                    "attention", "watchdog"):
            self.assertIn(key, defaults, key)
        self.assertNotIn("xhw", " ".join(str(v) for v in defaults.values()))

    def test_debug_furniture_is_gated_on_a_toggle(self):
        source = (ROOT / "tools/control_panel.py").read_text(encoding="utf-8")
        self.assertIn("self.vision_debug = tk.BooleanVar(value=False)", source)
        self.assertIn("if debug:", source)


class TheWiringVerifierChecksTheWindowAgainstItsSources(unittest.TestCase):
    """The panel must be verified against the sources, not against itself."""

    def setUp(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import gui_wiring_verify

        self.verifier = gui_wiring_verify

    def test_it_declares_a_source_for_every_field_it_checks(self):
        self.assertTrue(self.verifier.WIRING)
        for field, (state, render) in self.verifier.WIRING.items():
            self.assertTrue(state, field)
            self.assertTrue(callable(render), field)

    def test_it_would_catch_a_field_with_no_source(self):
        rows = self.verifier._source_checks("nothing here")
        self.assertTrue(rows)
        self.assertTrue(all(row["verdict"] == "NO_SOURCE" for row in rows))

    def test_it_reports_matching_when_the_panel_is_wired(self):
        source = (ROOT / "tools/control_panel.py").read_text(encoding="utf-8")
        rows = self.verifier._source_checks(source)
        self.assertTrue(all(row["verdict"] == "OK" for row in rows))

    def test_it_fails_when_a_rendered_value_diverges_from_its_source(self):
        """Otherwise the verifier would agree with whatever the panel believed."""
        stub = self.verifier._stub()
        self.panel_module_refresh(stub)
        stub.values["role"].set("xhw")
        report = stub._report
        expected = report.by_name("current_role").display
        self.assertNotEqual(expected, stub.values["role"].get())

    def panel_module_refresh(self, stub):
        from tools import control_panel

        control_panel.ControlPanel._refresh_truth(stub)


class TheWindowCannotInventAState(unittest.TestCase):
    """The invariant that stops this class of defect coming back.

    Read from the panel *source*, because the failure was a literal in the source -- no
    amount of runtime checking would have caught it, since a literal is perfectly
    well-formed at runtime.  Comments are stripped first: a comment that quotes the old
    literal (to explain why it was removed) is not the defect.
    """

    def setUp(self):
        self.source = code_only(PANEL.read_text(encoding="utf-8"))

    def test_no_state_cell_is_written_as_a_literal(self):
        """Every bare ``text="..."`` must be a fixed label, never a value.

        A literal is allowed for chrome (``"当前角色"``, ``"总览"``).  It is not allowed to
        equal a value the audit actually produces -- that would be a hardcoded fact.
        """
        audit = st.TruthAudit(ROOT).report()
        live_values = {value.value for value in audit.values if value.value}
        live_values.add(audit.role_id)
        live_values.add(audit.head)
        # The role's *name* alone is the exact shape the defect had ("xhw" inside
        # "xhw小号（账号 …）"), so the bare name counts as a displayed value too.
        for value in audit.values:
            if value.value and "（" in value.value:
                live_values.add(value.value.split("（", 1)[0].strip())
        literals = set(re.findall(r'text="([^"{][^"]*)"', self.source))
        offenders = sorted(literal for literal in literals
                           if literal in live_values and len(literal) > 2)
        self.assertEqual(offenders, [], f"a displayed value is hardcoded in the panel: {offenders}")

    def test_the_role_cell_reads_the_audit_instead_of_a_constant(self):
        self.assertNotIn('text="xhw"', self.source)
        self.assertIn('self.values["role"]', self.source)
        self.assertIn('self.values["role_state"]', self.source)

    def test_the_online_claim_is_no_longer_unconditional(self):
        """``text="● 在线"`` asserted a device state nobody had probed."""
        self.assertNotIn('text="● 在线"', self.source)
        self.assertNotIn("● 在线", self.source)
        self.assertIn('self.values["device"]', self.source)

    def test_a_comment_that_quotes_the_old_literal_would_not_hide_the_defect(self):
        """Guards the guard: the stripper must actually remove comments."""
        self.assertNotIn("#", code_only("x = 1  # text=\"xhw\"\n"))
        self.assertNotIn("text=\"xhw\"", code_only("    # text=\"xhw\"\n"))
        self.assertIn("keep = 1", code_only("keep = 1\n"))

    def test_the_panel_does_not_run_the_audit_on_the_ui_thread(self):
        """It walks four megabytes of episodes; a Tk callback must not do that."""
        self.assertIn("def _poll_truth(self)", self.source)
        self.assertIn("self._poll_truth()", self.source)

    def test_the_defaults_do_not_look_like_observations(self):
        """A default that reads like a value is the same mistake in a different place."""
        from tools.control_panel import status_defaults

        defaults = status_defaults()
        for key in ("role", "role_state", "truth"):
            self.assertIn(key, defaults)
        self.assertNotIn("xhw", " ".join(str(v) for v in defaults.values()))


def code_only(source: str) -> str:
    """Source with full-line comments and trailing ``#`` comments removed.

    The invariant tests above exist because a *literal* was doing the damage.  A comment
    quoting that literal is documentation, not the defect, so it must not be able to trip
    (or, worse, hide) the check.
    """
    kept: list[str] = []
    for line in source.splitlines():
        if line.lstrip().startswith("#"):
            continue
        quote_seen = False
        cut = len(line)
        for index, char in enumerate(line):
            if char in "\"'":
                quote_seen = not quote_seen
            elif char == "#" and not quote_seen and index and line[index - 1] in " \t":
                cut = index
                break
        kept.append(line[:cut].rstrip())
    return "\n".join(kept)


class EpisodesAreScopedToARole(unittest.TestCase):
    """The audit's #1 finding: every metric pooled two accounts.

    The corpus already contained 70,206,322 power / 6 march slots and 542,443 / 2, and
    nothing on an episode said which account it came from.  The field is now on the schema,
    so the honest reading of history is "unscoped" and never a guessed name.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        write(self.tmp, f"{st.ROLE_PROBE_DIR}/probe.json", {
            "stamp": "20260916_184004",
            "candidate_identity_tokens": [{"text": "账号：1171757165"}],
        })

    def test_an_episode_carries_the_role_it_was_taken_under(self):
        from winter_agent_v2.learning import Episode

        episode_row = Episode(
            skill="OPEN_MAP", state_before={}, action={}, state_after={},
            result="SUCCESS", failure_type=None, duration=1.0, mode="PRODUCTION",
            role_id="1171757165", role_scope=st.PERSISTED,
        )
        self.assertEqual(episode_row.role_id, "1171757165")
        self.assertEqual(episode_row.role_scope, st.PERSISTED)

    def test_an_episode_with_no_role_says_so_rather_than_guessing(self):
        from winter_agent_v2.learning import Episode

        episode_row = Episode(
            skill="OPEN_MAP", state_before={}, action={}, state_after={},
            result="SUCCESS", failure_type=None, duration=1.0, mode="PRODUCTION",
        )
        self.assertEqual(episode_row.role_id, "")
        self.assertEqual(episode_row.role_scope, "")

    def test_unscoped_history_is_reported_as_unscoped(self):
        write(self.tmp, st.EPISODES, [episode(NOW.isoformat()), episode(NOW.isoformat())])
        value = st.TruthAudit(self.tmp, now=NOW).report().by_name("episode_role_scope")
        self.assertEqual(value.status, st.UNKNOWN)
        self.assertEqual(value.value, "0/2")
        self.assertIn("全部未按角色限定", value.note)

    def test_scoped_episodes_are_counted(self):
        write(self.tmp, st.EPISODES, [
            {**episode(NOW.isoformat()), "role_id": "1171757165", "role_scope": st.PERSISTED},
        ])
        value = st.TruthAudit(self.tmp, now=NOW).report().by_name("episode_role_scope")
        self.assertEqual(value.value, "1/1")
        self.assertEqual(value.role_id, "1171757165")
        self.assertNotEqual(value.status, st.CONFLICT)

    def test_another_account_in_the_same_corpus_is_a_conflict(self):
        """A metric computed across both accounts is an average of two players."""
        write(self.tmp, st.EPISODES, [
            {**episode(NOW.isoformat()), "role_id": "1171757165"},
            {**episode(NOW.isoformat(), goal="OTHER"), "role_id": "9999999999"},
        ])
        report = st.TruthAudit(self.tmp, now=NOW).report()
        self.assertEqual(report.by_name("episode_role_scope").status, st.CONFLICT)
        self.assertIn("分角色的", report.conflicts_for("episode_role_scope")[0].note)

    def test_history_from_a_previous_account_is_not_a_live_conflict(self):
        """The old pooled rows are a fact about history, not a running disagreement.

        The distinction is by recency, not by presence: rows from another account that sit
        far enough back are the corpus's past, while one inside the recent window means the
        two accounts are being mixed *now*.
        """
        foreign = [{**episode(NOW.isoformat(), goal=f"OLD{i}", tag=f"o{i}"), "role_id": "9999999999"}
                   for i in range(250)]
        mine = [{**episode(NOW.isoformat(), goal=f"NEW{i}", tag=f"n{i}"), "role_id": "1171757165"}
                for i in range(250)]
        write(self.tmp, st.EPISODES, foreign + mine)
        report = st.TruthAudit(self.tmp, now=NOW).report()
        self.assertEqual(report.conflicts_for("episode_role_scope"), ())
        self.assertEqual(report.by_name("episode_role_scope").status, st.LIVE_OBSERVED)


class TheControlCentreAnswersItsOwnQuestions(unittest.TestCase):
    """The eight things the operator wants a window to answer in five seconds.

    Each of these is derived from the same reading as everything else, so the window
    cannot hold a second opinion about any of them.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        write(self.tmp, st.SNAPSHOT, {
            "updated_at": NOW.isoformat(), "page": "MAP", "agent_state": "GOAL_RUNNING",
            "current_goal": "AUTO_DISCOVERY", "current_skill": "OPEN_MAP",
            "runtime_thread_alive": True, "scheduler_loop_alive": True,
            "stop_reason": "reserved_march_for_stamina", "reason": "reserved",
            "last_action_time": NOW.isoformat(), "watchdog_restart_count": 13,
        })
        write(self.tmp, st.PUMP, {"written_at": NOW.isoformat(), "process": 1})
        write(self.tmp, st.PANEL_STATE, {"operator_intent": "RUNNING"})
        write(self.tmp, st.EPISODES, [episode(NOW.isoformat())])

    def report(self):
        return st.TruthAudit(self.tmp, now=NOW).report()

    def _executor(self, backends, **extra):
        write(self.tmp, st.EXECUTOR_LEDGER, [
            {"recorded_at": NOW.isoformat(), "used_backend": b, "skill_known": i > 0,
             "fallback_used": False, "capture_backend": f"{b}_X", **extra}
            for i, b in enumerate(backends)
        ])

    def test_maa_is_graded_on_what_actually_ran_not_on_the_config_flag(self):
        """"不能仅因为MAA进程存在就显示正常."."""
        write(self.tmp, "config/v2.json", {"executor": {"maa": {"enabled": True}}})
        self._executor(["MAA"] * 6)
        value = self.report().by_name("maa_state")
        self.assertEqual(value.status, st.LIVE_OBSERVED)
        self.assertIn("真实执行", value.value)

        self._executor(["ADB"] * 6)
        value = self.report().by_name("maa_state")
        self.assertIn("全部 ADB", value.value)
        self.assertNotIn("正常且", value.value)

    def test_a_disabled_maa_is_a_policy_not_a_fault(self):
        write(self.tmp, "config/v2.json", {"executor": {"maa": {"enabled": False}}})
        value = self.report().by_name("maa_state")
        self.assertIn("已关闭", value.value)
        self.assertNotIn(value.status, (st.CONFLICT,))

    def test_a_fallback_surge_is_named_as_a_degradation(self):
        '''"MAA明明正常，但生产实际上一直ADB" -- the exact case the operator named.'''
        write(self.tmp, "config/v2.json", {"executor": {"maa": {"enabled": True}}})
        self._executor(["MAA", "MAA"] + ["ADB"] * 8)
        write(self.tmp, st.EXECUTOR_LEDGER, [
            {"recorded_at": NOW.isoformat(), "used_backend": "MAA", "fallback_used": False},
            {"recorded_at": NOW.isoformat(), "used_backend": "MAA", "fallback_used": False},
        ] + [{"recorded_at": NOW.isoformat(), "used_backend": "ADB", "fallback_used": True}
             for _ in range(8)])
        value = self.report().by_name("maa_state")
        self.assertEqual(value.status, st.CONFLICT)
        self.assertIn("降级", value.value)

    def test_the_executor_mix_says_why_the_rest_went_to_adb(self):
        write(self.tmp, st.EXECUTOR_LEDGER, [
            {"recorded_at": NOW.isoformat(), "used_backend": "MAA", "skill_known": True},
            {"recorded_at": NOW.isoformat(), "used_backend": "ADB", "skill_known": False},
        ])
        value = self.report().by_name("executor_mix")
        self.assertIn("50%", value.value)
        self.assertIn("技能未迁移 MAA", value.note)

    def test_between_rounds_is_not_an_anomaly(self):
        """A stopped worker inside the scheduler's own gap is the design working.

        Asserted on the *runtime* finding specifically: an empty fixture also legitimately
        reports an unread role and a bootstrap that never ran, and those are not what this
        test is about.
        """
        write(self.tmp, st.SNAPSHOT, {
            "updated_at": (NOW - timedelta(seconds=300)).isoformat(),
            "agent_state": "IDLE", "runtime_thread_alive": False,
            "scheduler_loop_alive": False, "stop_reason": "reserved_march_for_stamina",
        })
        report = self.report()
        self.assertIn("正常", report.by_name("watchdog").value)
        self.assertIn("轮次之间", report.by_name("watchdog").note)
        kinds = [a["kind"] for a in report.needs_attention()]
        self.assertNotIn("RUNTIME_NOT_RUNNING", kinds)
        self.assertNotIn("UNEXPLAINED_IDLE", kinds)

    def test_silence_beyond_the_round_gap_is_an_anomaly(self):
        write(self.tmp, st.SNAPSHOT, {
            "updated_at": (NOW - timedelta(hours=2)).isoformat(),
            "agent_state": "IDLE", "runtime_thread_alive": False,
            "scheduler_loop_alive": False,
        })
        report = self.report()
        self.assertEqual(report.by_name("watchdog").status, st.CONFLICT)
        self.assertIn("RUNTIME_NOT_RUNNING", [a["kind"] for a in report.needs_attention()])

    def test_a_user_pause_is_an_intent_not_a_fault(self):
        write(self.tmp, st.PANEL_STATE, {"operator_intent": "PAUSED"})
        write(self.tmp, st.SNAPSHOT, {
            "updated_at": NOW.isoformat(), "agent_state": "PAUSED",
            "runtime_thread_alive": False, "scheduler_loop_alive": False,
        })
        report = self.report()
        self.assertIn("操作者意图 PAUSED", report.by_name("watchdog").note)
        self.assertNotIn("RUNTIME_NOT_RUNNING",
                         [a["kind"] for a in report.needs_attention()])

    def test_the_window_can_say_why_nothing_is_moving(self):
        write(self.tmp, st.SNAPSHOT, {
            "updated_at": NOW.isoformat(), "agent_state": "IDLE",
            "deferred_goals": [{"goal_id": "AVOID_STAMINA_WASTE",
                                "capability": "SPEND_STAMINA_ON_BEAST"}],
            "next_action": "stamina_task_slot_preserved",
        })
        value = self.report().by_name("why_idle")
        self.assertIn("DEFER", value.value)
        self.assertIn("SPEND_STAMINA_ON_BEAST", value.value)

    def test_an_unexplained_standstill_says_so_instead_of_nothing(self):
        '''"不能让用户看到游戏不动以后还要自己猜."'''
        write(self.tmp, st.SNAPSHOT, {
            "updated_at": NOW.isoformat(), "agent_state": "IDLE",
            "last_action_time": (NOW - timedelta(hours=1)).isoformat(),
        })
        report = self.report()
        self.assertEqual(report.by_name("why_idle").value, "UNEXPLAINED_IDLE")
        self.assertIn("UNEXPLAINED_IDLE", [a["kind"] for a in report.anomalies])

    def test_the_coverage_kpi_carries_its_24h_delta(self):
        write(self.tmp, "knowledge/game/capability_catalog.json", {"capabilities": [
            {"lifecycle": "LIVE_VERIFIED", "last_live_verified": NOW.isoformat()},
            {"lifecycle": "LIVE_VERIFIED", "last_live_verified": (NOW - timedelta(days=5)).isoformat()},
            {"lifecycle": "MISSING"},
        ]})
        value = self.report().by_name("coverage")
        self.assertIn("LIVE_VERIFIED 2", value.value)
        self.assertIn("最近24h 新增 1", value.note)

    def test_a_recovered_problem_is_history_not_a_red_light(self):
        report = self.report()
        self.assertTrue(all("auto_recovered" in a for a in report.anomalies))
        self.assertEqual(report.needs_attention(),
                         tuple(a for a in report.anomalies if not a["auto_recovered"]))

    def test_the_six_words_are_the_only_vocabulary(self):
        """Every cell must land on one of the operator's six words -- no cell may invent
        a seventh, which is how a window ends up with three shades of "fine"."""
        allowed = {"正常", "工作中", "等待", "降级", "未确认", "异常"}
        produced = {st.health_of(v)[0] for v in self.report().values}
        self.assertTrue(produced)
        self.assertTrue(produced <= allowed, produced - allowed)
        self.assertEqual({st.health_of(v)[1] for v in self.report().values} <=
                         {"good", "work", "idle", "warn", "unknown", "bad"}, True)

    def test_the_consistency_monitor_compares_field_to_source(self):
        rows = self.report().consistency
        self.assertTrue(rows)
        for row in rows:
            self.assertIn("field", row)
            self.assertIn("source", row)
            self.assertIn("source_value", row)
            self.assertIn(row["agree"], ("yes", "no"))


class WhatIsNotCurrentMayNotBePrintedAsCurrent(unittest.TestCase):
    """The operator's five inequalities, as tests (2026-09-18 P0 review).

    Each of these failed in production in a way a reader could not see: the window was
    well-formed and the values were well-formed.  Only the *claim* was wrong.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def report(self):
        return st.TruthAudit(self.tmp, now=NOW).report()

    # -- P0-2: a 46-hour-old role read is not the logged-in character ----------------

    def test_a_persisted_role_never_heads_a_current_role(self):
        write(self.tmp, st.ROLE_ARTIFACT, {
            "role_id": "1171757165", "role_name": "xhw小号", "observed_at":
            (NOW - timedelta(hours=46)).isoformat(), "verification": "VISION_READ",
            "evidence": ["frame.png"],
        })
        role = self.report().by_name("current_role")
        self.assertEqual(role.headline, st.UNKNOWN)
        self.assertEqual(role.category, "STALE")
        self.assertIn("xhw小号", role.last_known)
        self.assertFalse(role.current)

    def test_a_fresh_role_read_heads_it_with_the_name(self):
        write(self.tmp, st.ROLE_ARTIFACT, {
            "role_id": "1171757165", "role_name": "xhw小号",
            "observed_at": (NOW - timedelta(seconds=12)).isoformat(),
            "verification": "VISION_READ", "evidence": ["frame.png"],
        })
        role = self.report().by_name("current_role")
        self.assertEqual(role.headline, "xhw小号（账号 1171757165）")
        self.assertTrue(role.current)
        self.assertEqual(role.last_known, "")

    # -- P0-1: HISTORY is not a current event ---------------------------------------

    def test_an_event_whose_own_window_elapsed_is_history(self):
        # The measured record: 28 795 s left when verified, nine days ago.
        write(self.tmp, st.EVENT_STATE, {
            "event_id": "KINGDOM_OF_POWER_CURRENT", "name": "最强王国·击败野兽",
            "verified_at": (NOW - timedelta(hours=217)).isoformat(),
            "remaining_seconds_at_verification": 28795,
            "current_points": 11250, "target_points": 80000, "points_missing": 68750,
            "source": "LIVE_CLIENT",
        })
        events = self.report().by_name("events")
        self.assertEqual(events.value, "当前活动尚未实时确认")
        row = next(r for r in events.items if r["event_name"] == "最强王国·击败野兽")
        self.assertEqual(row["status"], st.HISTORY)
        self.assertFalse(row["planner_usable"])
        self.assertEqual(row["confidence"], 0.0)
        self.assertIn("窗口早已结束", row["note"])

    def test_a_record_inside_its_own_window_is_live_and_usable(self):
        write(self.tmp, st.EVENT_STATE, {
            "event_id": "X", "name": "当前活动", "verified_at": (NOW - timedelta(minutes=20)).isoformat(),
            "remaining_seconds_at_verification": 7200, "source": "LIVE_CLIENT",
        })
        row = next(r for r in self.report().by_name("events").items if r["event_id"] == "X")
        self.assertEqual(row["status"], st.LIVE_OBSERVED)
        self.assertTrue(row["planner_usable"])

    def test_knowledge_base_entries_are_never_current(self):
        write(self.tmp, "knowledge/events/bear_hunt.json", {"event_id": "BEAR", "name": "巨熊行动"})
        events = self.report().by_name("events")
        row = next(r for r in events.items if r["event_name"] == "巨熊行动")
        self.assertEqual(row["status"], st.HISTORY)
        self.assertFalse(row["planner_usable"])

    def test_several_activities_can_be_current_at_once(self):
        # The model is a list: a window that can only show one hides the other.
        write(self.tmp, st.EVENT_STATE, {
            "event_id": "A", "name": "活动甲", "verified_at": (NOW - timedelta(minutes=5)).isoformat(),
            "remaining_seconds_at_verification": 7200,
        })
        write(self.tmp, "knowledge/events/b.json", {"event_id": "B", "name": "活动乙"})
        events = self.report().by_name("events")
        self.assertEqual(len([r for r in events.items if r["status"] == st.LIVE_OBSERVED]), 1)
        self.assertEqual(len([r for r in events.items if r["status"] == st.HISTORY]), 1)

    # -- P0-3: jobs ≠ gateway health ------------------------------------------------

    def test_a_working_job_never_makes_the_gateway_healthy(self):
        write(self.tmp, st.ESCALATIONS, [
            {"source": "queue", "event": "escalation_created", "key": "K", "capability": "CAP"},
            {"source": "queue", "event": "submitted", "key": "K", "job_id": "d8ea0e44"},
            {"source": "queue", "event": "job_state", "key": "K", "state": "WORKING"},
        ])
        report = self.report()
        self.assertIn("WORKING", report.by_name("workbuddy_jobs").value)
        gateway = report.by_name("gateway_health")
        self.assertEqual(gateway.status, st.UNKNOWN)
        self.assertIn("不能", gateway.note)

    def test_a_timing_out_gateway_is_a_conflict_with_its_backoff(self):
        write(self.tmp, st.GATEWAY_PROBE, {
            "available": False, "reason": "GatewayUnavailable", "checked_at_utc": NOW.isoformat(),
            "consecutive_failures": 3, "backoff_seconds": 120, "last_ok_at": "",
        })
        gateway = self.report().by_name("gateway_health")
        self.assertEqual(gateway.value, "异常")
        self.assertEqual(gateway.status, st.CONFLICT)
        self.assertIn("连续 3 次失败", gateway.note)
        self.assertIn("退避 120 秒", gateway.note)

    # -- P0-4: AUTO is graded on what it produced ------------------------------------

    def test_a_fresh_episode_makes_auto_running(self):
        write(self.tmp, st.EPISODES, [episode((NOW - timedelta(seconds=40)).isoformat())])
        auto = self.report().by_name("auto_state")
        self.assertEqual(auto.status, st.LIVE_OBSERVED)
        self.assertIn("运行中", auto.value)

    def test_between_rounds_with_a_live_panel_is_waiting_not_broken(self):
        write(self.tmp, st.PANEL_STATE, {"operator_intent": "RUNNING"})
        write(self.tmp, st.PUMP, {"process": 1234, "written_at": NOW.isoformat()})
        write(self.tmp, st.EPISODES, [episode((NOW - timedelta(minutes=22)).isoformat())])
        auto = self.report().by_name("auto_state")
        self.assertEqual(auto.status, st.FRESH_RUNTIME)
        self.assertIn("本轮之间", auto.value)
        self.assertNotIn("未确认", auto.value)

    def test_no_panel_and_no_work_is_unconfirmed_not_normal(self):
        write(self.tmp, st.EPISODES, [episode((NOW - timedelta(hours=9)).isoformat())])
        auto = self.report().by_name("auto_state")
        self.assertEqual(auto.status, st.STALE)
        self.assertEqual(auto.value, "未确认")

    def test_the_legacy_in_process_flags_are_not_the_evidence(self):
        # The snapshot says the thread and scheduler are not running; in this architecture
        # they are written False by the panel itself and can never be evidence.
        write(self.tmp, st.SNAPSHOT, {
            "updated_at": NOW.isoformat(), "agent_state": "IDLE", "mode": "AUTO",
            "runtime_thread_alive": False, "scheduler_loop_alive": False,
        })
        write(self.tmp, st.PUMP, {"process": 1234, "written_at": NOW.isoformat()})
        write(self.tmp, st.EPISODES, [episode((NOW - timedelta(seconds=30)).isoformat())])
        auto = self.report().by_name("auto_state")
        self.assertEqual(auto.status, st.LIVE_OBSERVED)
        self.assertIn("上一代", auto.note)

    # -- the unified vocabulary -----------------------------------------------------

    def test_every_status_maps_into_the_operators_words(self):
        words = {"LIVE_OBSERVED", "FRESH_LAST_KNOWN", "STALE", "HISTORY",
                 "EXPECTED", "REQUESTED", "UNKNOWN", "CONFLICT"}
        for status in st.STATUS_RANK:
            self.assertIn(st.CATEGORY_OF[status], words, status)


if __name__ == "__main__":
    unittest.main()
