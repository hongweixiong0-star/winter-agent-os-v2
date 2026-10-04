"""The console may only declare, draw and age what the tree can actually produce.

The 2026-10-04 two-layer audit found five families of defect behind the seven pages.  Four of
them share a shape: **something was declared that nothing backs**.  A tab family of twelve
names for seven real pages.  A column whose every cell read 未计算.  Two rows reading 待计算
forever.  A confidence cell filled by whichever of four writers ran last.  And, underneath all
of them, twenty-seven of twenty-eight data files whose age no page could state.

Each class below asserts the *mechanism*, not one instance of it, because a test that pins a
single example passes again the moment the example is re-spelled:

* the tab list is **derived** from ``_build`` rather than typed out a second time
* the record keys the activity page reads must exist in the record, or be declared optional
  with a reason -- a key that is neither is the 待计算 defect
* ``SourceAge`` must not escalate when AUTO is down, or the notice becomes noise
* ``frame_confidence`` and ``confidence`` must stay two fields with two owners
* the new 需不需要干预 cell must answer "I could not check" differently from "nothing is wrong"
"""

from __future__ import annotations

import ast
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from winter_agent_v2 import source_freshness as sf

ROOT = Path(__file__).resolve().parents[1]
PANEL_PATH = ROOT / "tools" / "control_panel.py"
NOW = datetime(2026, 10, 4, 6, 30, tzinfo=timezone.utc)


def _panel_source() -> str:
    return PANEL_PATH.read_text(encoding="utf-8")


def _module_function(qualname: str):
    """Call a module-level function out of the panel script without importing Tk."""
    return getattr(_module_panel(), qualname)


def _module_panel():
    """The panel module itself, executed but never ``main()``-ed.

    Executing it is safe on this host (``import tkinter`` succeeds without a display); building a
    *window* is what needs a real root, and that is what ``EveryPageBuildsOnARealTkRootTests``
    withholds a skip for.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("cp_fill_under_test", PANEL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _string_literals(source: str) -> set:
    """Every string constant in the file.  Comments are exempt on purpose -- they record why a
    field was removed, and that history is the thing that stops it coming back."""
    literals = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            literals.add(node.value)
    return literals


# --------------------------------------------------------------------------------------
# R3 -- the tab family is derived, not declared twice
# --------------------------------------------------------------------------------------


class TheTabFamilyIsDerivedFromBuildTests:
    """Replaces a hand-written name list that had already drifted.

    The old guard named five retired pages as "present but unwanted" and **omitted**
    ``_skills`` -- so a page that was never built could have been re-added without it
    noticing.  All three assertions here are read out of the source, so a new page, a
    retired page or a renamed page fails here instead of shipping.
    """

    def _methods(self):
        tree = ast.parse(_panel_source())
        return {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}

    @staticmethod
    def _self_calls(node) -> set:
        return {n.func.attr for n in ast.walk(node)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "self"}

    def _builders(self):
        methods = self._methods()
        built = {name for name in self._self_calls(methods["_build"])
                 if name in methods and "_tab" in self._self_calls(methods[name])}
        every = {name for name, node in methods.items() if "_tab" in self._self_calls(node)}
        return methods, built, every

    def test_every_page_builder_is_reachable_and_every_reachable_page_is_built(self):
        _methods, built, every = self._builders()
        assert every - built == set(), (
            f"a page builder exists that _build never calls: {sorted(every - built)}"
        )
        assert built - every == set(), (
            f"_build calls something that builds no page: {sorted(built - every)}"
        )

    def test_there_are_exactly_seven_pages(self):
        _methods, built, _every = self._builders()
        assert len(built) == 7, sorted(built)

    def test_the_label_map_matches_the_labels_the_pages_ask_for(self):
        methods, built, _every = self._builders()
        labels = set()
        for name in built:
            for node in ast.walk(methods[name]):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "_tab" and node.args
                        and isinstance(node.args[0], ast.Constant)):
                    labels.add(node.args[0].value)

        tree = ast.parse(_panel_source())
        declared = None
        for node in tree.body:
            target = getattr(node, "target", None)
            if isinstance(node, ast.AnnAssign) and getattr(target, "id", "") == "TAB_GROUP":
                declared = {key.value for key in node.value.keys}
        assert declared is not None, "TAB_GROUP is not a module-level annotated assignment"
        assert declared == labels, (
            f"TAB_GROUP declares {sorted(declared)}; the pages ask for {sorted(labels)}"
        )


# --------------------------------------------------------------------------------------
# R4 -- a field the system cannot fill is not drawn
# --------------------------------------------------------------------------------------


class TheActivityPageOnlyDrawsKeysTheRecordHasTests:
    """The record has no programmatic writer, so its key set is the operator's own.

    ``learning/event_goal_state.json`` is a hand-recorded live observation (``source:
    LIVE_CLIENT``); a tree-wide search finds no code that rewrites it.  That makes "can this
    row ever be filled?" a question with a checkable answer: the key must be in the record, or
    be declared below as optional with the reason it may legitimately be absent.

    The two deletions this class protects -- 预计成本 / 预计完成 -- read 待计算 on every cycle
    forever.  "待计算" is not blank; it is a promise that a calculation is pending, and there
    is no calculation.
    """

    #: Keys the page may read which the operator's record is not required to carry, each with
    #: the reason.  Kept to two on purpose: the point of the list is that it is short enough
    #: to review, so a new phantom row cannot arrive disguised as "optional".
    OPTIONAL_EVENT_KEYS = {
        "event_phase": "阶段. The event schedule defines real phases; the record is the only "
                       "place an observed one could be persisted, so it is allowed to be absent.",
        "target_tier": "目标档位. Written by hand only; the cell falls back to 低保目标档, which "
                       "states that no tier was recorded rather than inventing one.",
    }

    def _page_record_keys(self) -> set:
        """The record keys the activity page reads, taken from its own call sites.

        The slice ends at the next *method* (``\\n    def ``), not at the next ``    def ``:
        the page's own helpers (``def number`` / ``def text``) are indented eight spaces, and
        a four-space search would stop at the first of them and inspect almost nothing.
        """
        import re

        source = _panel_source()
        start = source.index("    def _refresh_event_goal_display")
        body = source[start:source.index("\n    def ", start + 10)]
        keys = set(re.findall(r'(?:number|text)\("([a-z_]+)"', body))
        keys |= set(re.findall(r'raw\.get\("([a-z_]+)"\)', body))
        return keys

    def test_a_row_that_can_never_be_computed_is_not_drawn_at_all(self):
        literals = _string_literals(_panel_source())
        for gone in ("estimated_cost", "estimated_completion"):
            assert gone not in literals, (
                f"{gone} has no writer anywhere in winter_agent_v2/ or tools/, so it must not "
                f"be a row -- that is the 待计算 defect"
            )

    def test_every_record_key_the_page_reads_exists_or_is_declared_optional(self):
        record = json.loads((ROOT / "learning" / "event_goal_state.json").read_text(encoding="utf-8"))
        read = self._page_record_keys()
        assert read, "the key extraction found nothing -- the test would be vacuous"
        undeclared = read - set(record) - set(self.OPTIONAL_EVENT_KEYS)
        assert undeclared == set(), (
            f"the activity page reads {sorted(undeclared)}, which neither the record carries "
            f"nor this test declares optional"
        )

    def test_the_optional_list_is_deliberately_short(self):
        assert set(self.OPTIONAL_EVENT_KEYS) == {"event_phase", "target_tier"}
        for reason in self.OPTIONAL_EVENT_KEYS.values():
            assert len(reason) > 30, "an 'optional' entry without a reason is how it sneaks back"


class EveryDerivedFigureCanNameItsSourcesAgeTests:
    """The 总览 fact cards are the surface that made a stale file look like a live reading.

    Each of the four is a *derived* figure, and until 2026-10-04 none of them could say how old
    the file it came from was.  The cards and the freshness table are two lists, so they are
    checked against each other here -- a card naming a file the table does not know would
    silently render with no age at all, which is the original defect.
    """

    def test_each_fact_card_names_a_source_the_freshness_table_knows(self):
        module = _module_function("OVERVIEW_FACTS")
        known = {source.key for source in sf.SOURCES}
        for title, _key, _label, source_key in module:
            assert source_key in known, f"{title} derives from {source_key}, which has no row"

    def test_the_fact_card_labels_are_not_written_twice(self):
        """The build and the refresh both read ``OVERVIEW_FACTS``, so a hand-typed second copy
        of these labels would be a drift waiting to happen."""
        source = _panel_source()
        start = source.index("    def _overview")
        body = source[start:source.index("\n    def ", start + 10)]
        assert "for column, (title, key, source, source_key) in enumerate(OVERVIEW_FACTS)" in body
        assert "learning/knowledge_bootstrap/STATE.json · WorkBuddy 台账" not in body


# --------------------------------------------------------------------------------------
# R1 -- a source's age is a fact; only a *stopped writer* is a fault
# --------------------------------------------------------------------------------------


class TheFreshnessTableOnlyEscalatesWhileSomethingShouldBeWritingTests:
    """The anti-cry-wolf rule, which is the reason this table is not just "old files".

    When AUTO is stopped nothing writes these files, so their age is the design.  Escalating
    them would be the failure mode ``needs_reload`` already warns about in its own comment:
    a notice that fires when nothing is wrong teaches the operator to ignore it.
    """

    def _write(self, root: Path, relative: str, *, age_seconds: float) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        import os

        stamp = NOW.timestamp() - age_seconds
        os.utime(path, (stamp, stamp))

    def test_the_table_is_not_empty(self):
        assert len(sf.SOURCES) >= 20
        keys = [source.key for source in sf.SOURCES]
        assert len(keys) == len(set(keys)), "one key, one row"

    def test_a_retired_source_is_not_reported_as_stale(self, tmp_path):
        age = sf.age_of(tmp_path, "learning/goal_coverage.json", now=NOW)
        assert age.status == sf.RETIRED
        assert age.fresh is False

    def test_a_stopped_writer_is_an_escalation(self, tmp_path):
        self._write(tmp_path, "learning/runtime_snapshot.json", age_seconds=7200)
        stale = sf.stale_while_running(tmp_path, auto_running=True, now=NOW)
        assert [item.key for item in stale] == ["learning/runtime_snapshot.json"]
        assert "问题" not in stale[0].describe()

    def test_the_same_file_is_not_an_escalation_when_auto_is_down(self, tmp_path):
        self._write(tmp_path, "learning/runtime_snapshot.json", age_seconds=7200)
        assert sf.stale_while_running(tmp_path, auto_running=False, now=NOW) == ()
        assert sf.attention_lines(tmp_path, auto_running=False, now=NOW) == ()

    def test_a_fresh_source_is_never_reported(self, tmp_path):
        self._write(tmp_path, "learning/runtime_snapshot.json", age_seconds=5)
        assert sf.stale_while_running(tmp_path, auto_running=True, now=NOW) == ()

    def test_a_missing_source_is_missing_rather_than_stale(self, tmp_path):
        age = sf.age_of(tmp_path, "learning/runtime_snapshot.json", now=NOW)
        assert age.status == sf.MISSING
        assert "不存在" in age.describe()

    def test_the_rule_lives_in_one_place(self, tmp_path):
        """``stale_while_running`` must be the table read plus ``stale_among``, not a second
        copy of the rule -- a second copy is how two readers come to disagree."""
        self._write(tmp_path, "learning/runtime_snapshot.json", age_seconds=7200)
        ages = sf.all_ages(tmp_path, now=NOW)
        assert sf.stale_while_running(tmp_path, auto_running=True, now=NOW) == \
            sf.stale_among(ages, auto_running=True)
        assert sf.stale_while_running(tmp_path, auto_running=False, now=NOW) == \
            sf.stale_among(ages, auto_running=False) == ()

    def test_the_escalation_follows_the_current_auto_verdict_not_a_cached_one(self, tmp_path, monkeypatch):
        """The console caches the file stats for 30 s, and must not cache the AUTO verdict with
        them: pressing 开始 would otherwise not raise the alarm for up to 30 s, and pressing
        停止 would not clear it for the same window."""
        import importlib.util
        import types

        self._write(tmp_path, "learning/runtime_snapshot.json", age_seconds=7200)
        spec = importlib.util.spec_from_file_location("cp_freshness_under_test", PANEL_PATH)
        panel = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(panel)
        monkeypatch.setattr(panel, "ROOT", tmp_path)

        class _Stub:
            process = None

            def __getattr__(self, name):
                attr = getattr(panel.ControlPanel, name)
                return types.MethodType(attr, self) if callable(attr) else attr

        stub = _Stub()
        assert stub._freshness()[1] == set()
        stub.process = type("P", (), {"poll": lambda self: None})()
        assert stub._freshness()[1] == {"learning/runtime_snapshot.json"}, "开始 must escalate at once"
        stub.process = None
        assert stub._freshness()[1] == set(), "停止 must clear at once"

    def test_every_listed_source_names_the_page_that_shows_it(self):
        """A source with no consumer has no reason to be in this table.

        (The earlier version of this test asserted that a source with an empty ``used_by`` is
        not escalated.  That is dead code today -- all 26 entries declare a consumer -- and a
        test of a branch nothing can reach passes forever without testing anything.  The
        invariant that *is* live is the one below.)
        """
        for source in sf.SOURCES:
            if source.retired:
                continue
            assert source.used_by, f"{source.key} is listed but no page shows it"
            assert source.ttl_seconds > 0, f"{source.key} has no budget, so it can never be fresh"


# --------------------------------------------------------------------------------------
# R2 -- one name, one owner
# --------------------------------------------------------------------------------------


class TheTwoConfidencesHaveTwoOwnersTests:
    """``RuntimeSnapshot.confidence`` had four writers and no owner declaration.

    ``runtime.py`` wrote ``before.confidence`` / ``after.confidence`` -- the *frame's page
    recognition* -- into the same field the two decision sites filled with
    ``decision.confidence``.  The console printed it under 当前决策 as 置信度, so a row about
    a decision could carry a frame's recognition score.  Two fields, two owners.
    """

    def test_the_snapshot_has_both_fields(self):
        from winter_agent_v2 import runtime_snapshot as rs

        fields = rs.RuntimeSnapshot.__dataclass_fields__
        assert "confidence" in fields and "frame_confidence" in fields
        assert fields["confidence"] is not fields["frame_confidence"]

    def test_the_frame_writers_do_not_touch_the_decision_field(self):
        """``confidence=`` preceded by a word character would be a frame write again --
        ``frame_confidence=after.confidence`` contains the offending substring, so a plain
        ``assert x not in source`` cannot tell the two apart."""
        import re

        source = (ROOT / "winter_agent_v2" / "runtime.py").read_text(encoding="utf-8")
        bare = re.findall(r"(?<![_.\w])confidence=(before|after)\.confidence", source)
        assert bare == [], f"the frame's confidence is still written into the decision's field: {bare}"
        framed = re.findall(r"(?<![_.\w])frame_confidence=(before|after)\.confidence", source)
        assert sorted(framed) == ["after", "before"]
        assert len(re.findall(r"(?<![_.\w])confidence=decision\.confidence", source)) >= 2

    def test_the_console_prints_them_under_two_names(self):
        source = _panel_source()
        assert '"confidence": NO_DATA' not in source, "a bare confidence key is the ambiguity"
        assert "confidence_decision" in source and "confidence_frame" in source
        assert '("决策置信度", "confidence_decision"' in source


# --------------------------------------------------------------------------------------
# P1 -- the cell the audit found missing: 需不需要干预
# --------------------------------------------------------------------------------------


class TheInterventionCellAnswersHonestlyTests:
    """The audit's second layer found this slot empty: the window said what *it* was doing but
    nothing said whether the *human* was needed.  It was the only L1 item absent from the
    whole window.  Because its answer changes what the operator does next, "I could not check"
    must never render as "nothing is wrong"."""

    def test_no_problems_with_auto_running_reads_as_no_action_needed(self):
        text = _module_function("intervention_of")(problems=[], auto_running=True, policy=None)
        assert "不需要你干预" in text
        assert "AUTO 正在运行" in text

    def test_several_problems_are_named_with_a_count(self):
        text = _module_function("intervention_of")(
            problems=["⚠ STATE_CONFLICT：a", "⚠ 数据源已过期：b", "⚠ c"],
            auto_running=True, policy=None,
        )
        assert "（3 项）" in text
        assert "STATE_CONFLICT" in text

    def test_the_spend_line_is_read_from_the_policy_file_not_assumed(self):
        text = _module_function("intervention_of")(
            problems=[], auto_running=True,
            policy={"real_money": "PERMANENTLY_BLOCKED", "disabled_goals": {"A": "x", "B": "y"}},
        )
        assert "永久禁止" in text
        assert "已禁用 Goal 2 个" in text

    def test_a_silent_policy_says_undeclared_instead_of_zero(self):
        text = _module_function("intervention_of")(problems=[], auto_running=False, policy=None)
        assert "未声明" in text
        assert "未在运行" in text

    def test_an_unavailable_audit_does_not_keep_a_reassuring_answer(self):
        source = _panel_source()
        start = source.index("    def _refresh_truth")
        body = source[start:source.index("\n    def ", start + 10)]
        early_return = body[:body.index("        role = report.by_name")]
        assert 'self.values["intervene"].set(' in early_return
        assert "审计不可用" in early_return


class EveryPageBuildsOnARealTkRootTests:
    """Build all seven pages for real, on a real Tk root, with the window's own code.

    Why this is not redundant with everything above.  The 2026-10-04 audit had to work out
    reachability with an AST walk because nothing executed the pages.  That same gap let a
    broken edit sit in the tree: a helper was deleted from ``_overview`` without its first line
    being restored, so the method referenced an undefined ``tab`` -- and **every test still
    passed**, because no test ever built a page.  ``ast.parse`` said OK (it is valid Python) and
    ``check_wiring`` said OK (the strings it greps for were still there).

    So: real ``tk.Tk``, real frames, real refreshers, and the panel's own builders -- only the
    probes, the worker and the pump are stubbed, because those touch the device.  A NameError,
    a missing widget attribute, a bad ``grid`` argument or a stubbed-out helper all fail here.
    """

    PAGE_BUILDERS = ("_overview", "_goals", "_strategy", "_event_goal",
                     "_capabilities", "_auto_development", "_system")

    _TK_ROOT = None

    def _root(self):
        """One Tk root for the whole class, made once and **never destroyed between tests**.

        This is not tidiness, it is a repaired guard.  Measured: with a ``Tk()``/``destroy()``
        pair per test, three runs of this file gave *one skip* in the first and none in the other
        two -- ``test_the_overview_folds_what_the_audit_folded`` silently declined to run, on a
        host where Tk works.  A guard that skips one run in three is a guard that is not guarding;
        and because ``pytest.skip`` reads as "environment", the failure mode is invisible.

        The churn was the cause, so the churn is what is removed.  The skip below now means what
        it says -- this host has no display -- and cannot be produced by test ordering.
        """
        tk = pytest.importorskip("tkinter")
        if type(self)._TK_ROOT is None:
            try:
                root = tk.Tk()
            except tk.TclError:  # pragma: no cover - no display on this host
                pytest.skip("no Tk display available")
            root.withdraw()
            type(self)._TK_ROOT = root
        return tk, type(self)._TK_ROOT

    def _harness(self, panel, tk, root, root_dir):
        import types
        import inspect
        from tkinter import ttk

        class _Harness:
            def __init__(self):
                self.root = root
                self.tabs = ttk.Notebook(root)
                self._tab_names = []
                self._tab_refreshers = {}
                self.values = {key: tk.StringVar(value=value)
                               for key, value in panel.status_defaults().items()}
                self.kpi = {}
                self.config = {"device": {"adb_path": "adb", "serial": "unused"},
                               "auto_execution": False}
                self.policy_enabled = {name: tk.BooleanVar(value=True)
                                       for name in panel.POLICY_CATEGORIES}
                self.task_enabled = {}
                self.preview_mode = tk.StringVar(value="原始画面")
                self.continuous = tk.BooleanVar(value=True)
                self.vision_debug = tk.BooleanVar(value=False)
                self.event_text = tk.StringVar(value="")
                self.policy_buttons = {}
                self.session = {}
                self.event_lines = []
                self.registry = panel.v2_registry()
                self.operator_intent = "RUNNING"
                self.startup_preflight = None
                self._other_instance = 0
                self.process = None
                self.runtime_store = panel.RuntimeSnapshotStore(
                    root_dir / "learning/runtime_snapshot.json")

            # Stubbed so a page build cannot touch the config, the queue or the device.
            def _save_panel_state(self, *a, **k):
                raise AssertionError("building a page must not persist the panel state")

            def _save_policy_state(self, *a, **k):
                raise AssertionError("building a page must not write the policy file")

            def _render_preview(self, *a, **k):
                pass

            def _schedule_preview_render(self, *a, **k):
                pass

            def _append(self, *a, **k):
                pass

            def __getattr__(self, name):
                # ``getattr_static`` first: a staticmethod/classmethod re-bound with
                # ``MethodType`` would receive ``self`` twice, which is a harness bug that looks
                # exactly like a panel bug.
                raw = inspect.getattr_static(panel.ControlPanel, name)
                if isinstance(raw, (staticmethod, classmethod)):
                    return getattr(panel.ControlPanel, name)
                attr = getattr(panel.ControlPanel, name)
                return types.MethodType(attr, self) if callable(attr) else attr

        return _Harness()

    def test_all_seven_pages_build(self, tmp_path, monkeypatch):
        import importlib.util

        tk, root = self._root()

        spec = importlib.util.spec_from_file_location("cp_pages_under_test", PANEL_PATH)
        panel = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(panel)
        monkeypatch.setattr(panel, "ROOT", tmp_path)

        harness = self._harness(panel, tk, root, tmp_path)
        built = []
        for name in self.PAGE_BUILDERS:
            getattr(harness, name)()          # the failure under test is raised here
            built.append(name)
        root.update_idletasks()
        assert built == list(self.PAGE_BUILDERS)
        assert harness._tab_names == ["总览", "目标", "策略", "活动", "能力", "自动开发", "系统"]

    def test_the_overview_really_has_its_grid_row_zero(self, tmp_path, monkeypatch):
        """The specific edit that broke and no test noticed: ``_overview`` must create its tab
        before it uses it -- ``tab.rowconfigure(0, ...)`` with no row 0 degrades the whole page
        to a single stacked column, and referencing an undefined ``tab`` raises outright."""
        source = _panel_source()
        start = source.index("    def _overview")
        body = source[start:source.index("\n    def ", start + 10)]
        first = [line for line in body.splitlines()[1:] if line.strip()][0]
        assert first.strip().startswith("tab = self._tab("), (
            f"_overview must open by creating its tab, not by using it: {first.strip()!r}"
        )

    def _build_overview(self, tmp_path, monkeypatch):
        import importlib.util

        tk, root = self._root()
        spec = importlib.util.spec_from_file_location("cp_overview_under_test", PANEL_PATH)
        panel = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(panel)
        monkeypatch.setattr(panel, "ROOT", tmp_path)
        harness = self._harness(panel, tk, root, tmp_path)
        harness._overview()
        root.update_idletasks()
        return panel, harness, root

    def test_the_overview_folds_what_the_audit_folded(self, tmp_path, monkeypatch):
        """The tier map as the real page builds it, not as the table describes it.

        Two things are being pinned, and the second is the one that matters:

        * each block's tier -- so a later edit cannot quietly promote a block into L1 or demote
          the verdict card out of it;
        * **nothing at all is open on first paint.**  That is the operator's complaint measured
          rather than asserted from a table: he said the page showed too much, and the test says
          the page now opens with every L2/L3 block shut by itself.
        """
        panel, harness, root = self._build_overview(tmp_path, monkeypatch)
        assert {key: fold.level for key, fold in harness._folds.items()} == {
            "today": panel.L2, "decision": panel.L2, "queues": panel.L2, "facts": panel.L2,
            "kpi": panel.L3, "workbuddy": panel.L3, "watchdog": panel.L3,
            "stats": panel.L3, "events": panel.L3,
        }
        open_on_first_paint = [key for key, fold in harness._folds.items() if fold.expanded]
        assert open_on_first_paint == [], (
            f"{open_on_first_paint} are open before the operator touches anything"
        )
        # The two blocks the audit named as permanent L1 must not be folds at all: a block that
        # says "a fault exists" may not be the one that can be collapsed.
        assert "attention" not in harness._folds
        assert "intervene" not in harness._folds

    def test_every_fold_only_watches_sources_the_freshness_table_knows(self, tmp_path, monkeypatch):
        """The runtime half of the KPI check: ``sources`` are evaluated values, so this is where
        a fold that watches an unknown file can actually be caught."""
        panel, harness, root = self._build_overview(tmp_path, monkeypatch)
        assert harness._folds, "the overview must declare folds"
        known = {source.key for source in sf.SOURCES}
        for key, fold in harness._folds.items():
            unknown = sorted(set(fold.sources) - known)
            assert unknown == [], f"fold {key} watches {unknown}, which has no freshness row"


# --------------------------------------------------------------------------------------
# The information tiers: a folded block may not stay folded while it is abnormal
# --------------------------------------------------------------------------------------


class _FakeWidget:
    """Just enough of a Tk widget for ``Fold.paint``: packed, or not, and a text."""

    def __init__(self):
        self.packed = False
        self.text = ""

    def pack(self, **_kwargs):
        self.packed = True

    def pack_forget(self):
        self.packed = False

    def configure(self, **kwargs):
        self.text = kwargs.get("text", self.text)

    def bind(self, *_args, **_kwargs):
        pass


class _FakeVar:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


class AFoldedBlockCannotHideAnAbnormalityTests:
    """The operator's rule, in three parts, each of which alone is gameable.

    He asked for the console to show less, with the explicit exception that a block must surface
    itself 「在超过阈值 / 状态异常 / 需要用户决策时」.  A fold that cannot open itself is therefore
    not styling -- it is the mechanism by which a fault becomes invisible, so each half is pinned:

    * every fold the window declares either carries a rule or is named in ``INERT_FOLDS``, so
      "this one cannot open itself" is a decision somebody wrote down;
    * a rule that fires opens its block with no click;
    * a fired rule leaves its reason in the header **whether the block is open or shut** -- that
      third one is what makes it safe to let an abnormal L3 block be folded at all.
    """

    def _panel(self):
        return _module_panel()

    def _stub(self, panel):
        import types

        class _Stub:
            def __init__(self):
                self._folds = {}

            def __getattr__(self, name):
                attr = getattr(panel.ControlPanel, name)
                return types.MethodType(attr, self) if callable(attr) else attr

        return _Stub()

    def _fold(self, panel, stub, key, level, escalate=None, annotate=None):
        widget = _FakeWidget()
        fold = panel.Fold(key=key, title=key, level=level, outer=widget, body=widget,
                          toggle=widget, badge=_FakeVar(), escalate=escalate,
                          annotate=annotate, sources=())
        stub._folds[key] = fold
        fold.paint()
        return fold

    def test_a_block_with_a_reason_opens_itself(self):
        panel = self._panel()
        stub = self._stub(panel)
        fold = self._fold(panel, stub, "kpi", panel.L3, escalate=lambda: "能力目录已停更")
        assert fold.expanded is False, "an L3 block starts folded"
        stub._sync_folds()
        assert fold.expanded is True, "the rule firing must not need a click"
        assert fold.badge.get() == "⚠ 能力目录已停更"

    def test_a_marked_block_stays_folded_but_says_why(self):
        """``annotate`` is not a weaker ``escalate``: it is a different answer to a different
        question, and collapsing the two was a real defect in the first version of this change.

        Measured on live data: with one merged rule, ``capability_catalog.json`` (7.7 days old,
        7-day budget) auto-opened both the KPI block and the 事实卡 block **permanently** -- so the
        两个折叠白做了, and an alarm that is always up is the "狼来了" failure ``source_freshness``
        warns about in its own docstring.  §六's stale-source row asks for the *cells* to read
        待重新观测 and 需要关注 to name the file, which both already do.
        """
        panel = self._panel()
        stub = self._stub(panel)
        fold = self._fold(panel, stub, "kpi", panel.L3,
                          annotate=lambda: "能力目录已停更（7.7 天前），这一块的数字不是当前读数")
        stub._sync_folds()
        assert fold.expanded is False, "a stale source must not open the block"
        assert "7.7 天前" in fold.badge.get(), "but it must say so in the header"
        assert fold.auto_opened is False

    def test_only_the_rule_that_opens_can_shut(self):
        """A marked (never opened) block must not be closed by the clearing of a rule that never
        opened it -- otherwise a block the operator opened by hand is yanked shut by a source
        going fresh."""
        panel = self._panel()
        stub = self._stub(panel)
        state = {"note": "过期"}
        fold = self._fold(panel, stub, "facts", panel.L2, annotate=lambda: state["note"])
        stub._sync_folds()
        stub._toggle_fold("facts")                 # the operator opens it deliberately
        assert fold.expanded is True and fold.auto_opened is False
        state["note"] = ""
        stub._sync_folds()
        assert fold.expanded is True, "the source going fresh must not shut a block the user opened"
        assert fold.badge.get() == ""

    def test_a_block_shuts_itself_when_the_reason_clears(self):
        panel = self._panel()
        stub = self._stub(panel)
        state = {"reason": "坏了"}
        fold = self._fold(panel, stub, "kpi", panel.L3, escalate=lambda: state["reason"])
        stub._sync_folds()
        assert fold.expanded is True
        state["reason"] = ""
        stub._sync_folds()
        assert fold.expanded is False, "an alarm that healed must stop taking the screen"
        assert fold.badge.get() == ""

    def test_a_block_the_operator_opened_is_not_yanked_shut(self):
        """The alarm closes only what the alarm opened."""
        panel = self._panel()
        stub = self._stub(panel)
        fold = self._fold(panel, stub, "queues", panel.L2, escalate=lambda: "")
        stub._toggle_fold("queues")
        assert fold.expanded is True and fold.auto_opened is False
        stub._sync_folds()
        assert fold.expanded is True, "the window must not argue with the person using it"

    def test_a_shut_block_still_carries_its_reason(self):
        """The load-bearing one: folded is allowed, *hidden* is not."""
        panel = self._panel()
        stub = self._stub(panel)
        fold = self._fold(panel, stub, "watchdog", panel.L3, escalate=lambda: "看门狗异常")
        stub._sync_folds()
        stub._toggle_fold("watchdog")          # the operator closes it by hand
        assert fold.expanded is False
        stub._sync_folds()                     # ...and the next tick leaves it shut
        assert fold.expanded is False, "a hand-shut block stays shut for the same fault"
        assert fold.badge.get() == "⚠ 看门狗异常", (
            "shutting a block must not remove the statement that it is abnormal"
        )

    def test_a_new_fault_reopens_a_block_the_operator_had_shut(self):
        """They silenced the previous fault, not the next one."""
        panel = self._panel()
        stub = self._stub(panel)
        state = {"reason": "第一个故障"}
        fold = self._fold(panel, stub, "kpi", panel.L3, escalate=lambda: state["reason"])
        stub._sync_folds()
        stub._toggle_fold("kpi")
        assert fold.expanded is False
        state["reason"] = "第二个故障"
        stub._sync_folds()
        assert fold.expanded is True, "a different fault gets its own chance to surface"

    def test_a_rule_that_raises_is_not_an_all_clear(self):
        """A broken verdict is an abnormal block whose state is unknown, so it must not read as
        "nothing to see" -- that would make the one failure that hides faults the quiet one."""

        def boom():
            raise RuntimeError("predicate broke")

        panel = self._panel()
        stub = self._stub(panel)
        fold = self._fold(panel, stub, "facts", panel.L2, escalate=boom)
        stub._sync_folds()
        assert fold.expanded is True
        assert "异常判定失败" in fold.badge.get()
        assert "RuntimeError" in fold.badge.get()

    # -- the declaration itself --------------------------------------------------------

    def _declared_folds(self) -> dict:
        """Every ``self._fold(...)`` call in the panel: key, tier, and whether it carries a rule.

        Walked with AST rather than grepped, so the comments that *explain* a fold are not
        mistaken for one, and a fold added to any page -- not just 总览 -- is found.

        Both the key and the tier must be spelled out at the call site as a literal or as one of
        the module's own tier constants.  A tier computed at runtime is rejected on purpose: the
        whole point of ``FOLD_DEFAULT_OPEN`` is that a block cannot choose its own default, and a
        tier nobody can read off the call site is how that rule gets worked around.
        """
        panel = self._panel()

        def spelled(node) -> str | None:
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return node.value
            if isinstance(node, ast.Name):
                value = getattr(panel, node.id, None)
                return value if isinstance(value, str) else None
            return None

        found: dict = {}
        for node in ast.walk(ast.parse(_panel_source())):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "_fold"):
                continue
            kwargs = {kw.arg: kw.value for kw in node.keywords}
            key, level = spelled(kwargs.get("key")), spelled(kwargs.get("level"))
            assert key, "a fold must name its key literally"
            assert level in (panel.L1, panel.L2, panel.L3), (
                f"{key} must declare one of L1/L2/L3 at the call site, not a computed tier"
            )
            found[key] = {
                "level": level,
                "escalated": "escalate" in kwargs,
                "annotated": "annotate" in kwargs,
                "has_sources": "sources" in kwargs,
            }
        return found

    def test_every_fold_can_say_something_or_is_declared_inert(self):
        panel = self._panel()
        declared = self._declared_folds()
        assert declared, "the panel must declare at least one fold"
        missing = sorted(key for key, spec in declared.items()
                         if not spec["escalated"] and not spec["annotated"]
                         and key not in panel.INERT_FOLDS)
        assert missing == [], (
            f"{missing} fold and can never say anything about themselves, and nothing says why: "
            f"give them a rule, or name them in INERT_FOLDS with the reason"
        )

    def test_the_block_that_opens_and_the_block_that_marks_are_not_the_same_rule(self):
        """Pins the split itself, because merging the two is the specific error that was made and
        the two rules look identical from a distance.

        The four blocks with an *opening* rule are exactly the four §六 names for it
        (看门狗 / WorkBuddy / 队列 / 预载 非正常，或队列有活跃 Job).  Everything else that watches a
        file only *marks* its header.
        """
        panel = self._panel()
        declared = self._declared_folds()
        opening = sorted(key for key, spec in declared.items() if spec["escalated"])
        assert opening == ["watchdog", "workbuddy"], (
            "only the blocks §六 lists may float themselves to L1; found " f"{opening}"
        )
        marking = sorted(key for key, spec in declared.items() if spec["annotated"])
        assert marking == ["facts", "kpi"], (
            "the stale-source row marks the cells and names the file, it does not open the "
            f"block; found {marking}"
        )
        assert not (set(opening) & set(marking)), "one block, one kind of rule"

    def test_every_kpi_card_declares_which_file_it_derives_from(self):
        """The audit's 「8 个 KPI 卡没有任何年龄标注」, closed: a card either names the file whose age
        it can cite, or is listed with the reason it has no file -- the same shape as the activity
        page's optional keys, so an unageable card is a written decision rather than a gap."""
        panel = self._panel()
        cards = set(panel.CATALOG_META)
        covered = set(panel.CATALOG_FRESHNESS) | set(panel.CATALOG_UNFRESHNESSED)
        assert covered == cards, (
            f"KPI cards with no entry: {sorted(cards - covered)}; "
            f"entries with no card: {sorted(covered - cards)}"
        )
        assert not (set(panel.CATALOG_FRESHNESS) & set(panel.CATALOG_UNFRESHNESSED)), (
            "a card either has a file to age or it does not"
        )
        known = {source.key for source in sf.SOURCES}
        unknown = sorted(set(panel.CATALOG_FRESHNESS.values()) - known)
        assert unknown == [], f"KPI cards cite {unknown}, which have no freshness row"

    def test_the_kpi_source_line_really_gains_the_age(self):
        """The wiring, not the declaration: the age must reach the label the operator reads.

        Measured, because the obvious place to put it is wrong -- the KPI labels are set *after*
        ``_refresh_truth`` in the tick, so an age appended there is overwritten by the static
        label a few lines later and nothing looks broken.
        """
        source = _panel_source()
        assert "_source_age_note(CATALOG_FRESHNESS.get(key" in source, (
            "the KPI source line must append the age of the file the card counted"
        )
        # ...and it must be in the block that sets the KPI labels, i.e. after that set.
        setter = source.index('var.set(kpi.get(key, {}).get("value", NO_DATA))')
        aged = source.index("_source_age_note(CATALOG_FRESHNESS.get(key")
        assert aged > setter, (
            "the age must be appended where the label is written, not earlier where it is "
            "overwritten"
        )

    def test_the_inert_list_names_no_fold_that_no_longer_exists(self):
        """The other direction, because a stale exemption quietly re-permits the defect."""
        panel = self._panel()
        declared = set(self._declared_folds())
        stale = sorted(set(panel.INERT_FOLDS) - declared)
        assert stale == [], f"INERT_FOLDS exempts {stale}, which is not a fold any more"

    def test_each_inert_entry_states_a_reason(self):
        panel = self._panel()
        for key, reason in panel.INERT_FOLDS.items():
            assert len(reason.strip()) >= 15, f"{key} is exempt with no reason worth the name"

    def test_the_kpi_fold_names_only_sources_the_table_knows(self):
        """A fold whose ``sources`` name a file the freshness table has no row for could never
        escalate -- it would look guarded while being permanently unable to open itself.

        Only the *declaration* is checked here.  The sources each fold actually ends up watching
        are evaluated values (``KPI_FOLD_SOURCES``, a tuple built from ``OVERVIEW_FACTS``), so the
        runtime check lives where those values exist: ``EveryPageBuildsOnARealTkRootTests``.
        """
        panel = self._panel()
        known = {source.key for source in sf.SOURCES}
        unknown = sorted(set(panel.KPI_FOLD_SOURCES) - known)
        assert unknown == [], f"the KPI fold watches {unknown}, which has no freshness row"

    def test_why_idle_is_the_one_fact_card_that_stays_open(self):
        """§六 put 现在为什么不动 at L1 -- it is the answer to 「有没有卡住」 -- and it lives in a
        four-card block whose other three members are L2.  Splitting it out is what lets the rest
        fold without hiding an L1 fact, so the split is pinned rather than left implicit."""
        panel = self._panel()
        cards = {row[1] for row in panel.OVERVIEW_FACTS}
        assert set(panel.OVERVIEW_FACT_TIERS) == cards, (
            "every fact card needs a tier and every tier needs a card, or one is untiered"
        )
        staying = sorted(key for key, level in panel.OVERVIEW_FACT_TIERS.items()
                         if level == panel.L1)
        assert staying == ["why_idle"], (
            "exactly one fact card is L1 and it is why_idle; "
            f"found {staying}"
        )

    def test_the_tier_of_a_block_is_keyed_by_tier_not_by_block(self):
        """A block must not be able to privately choose a different default from its tier."""
        panel = self._panel()
        assert panel.FOLD_DEFAULT_OPEN == {panel.L1: True, panel.L2: False, panel.L3: False}
        for spec in self._declared_folds().values():
            assert spec["level"] in panel.FOLD_DEFAULT_OPEN


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
