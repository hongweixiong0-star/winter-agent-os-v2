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
    import importlib.util

    spec = importlib.util.spec_from_file_location("cp_fill_under_test", PANEL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return getattr(module, qualname)


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

        tk = pytest.importorskip("tkinter")
        try:
            root = tk.Tk()
        except tk.TclError:  # pragma: no cover - no display on this host
            pytest.skip("no Tk display available")
        root.withdraw()

        spec = importlib.util.spec_from_file_location("cp_pages_under_test", PANEL_PATH)
        panel = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(panel)
        monkeypatch.setattr(panel, "ROOT", tmp_path)

        harness = self._harness(panel, tk, root, tmp_path)
        try:
            built = []
            for name in self.PAGE_BUILDERS:
                getattr(harness, name)()          # the failure under test is raised here
                built.append(name)
            root.update_idletasks()
            assert built == list(self.PAGE_BUILDERS)
            assert harness._tab_names == ["总览", "目标", "策略", "活动", "能力", "自动开发", "系统"]
        finally:
            root.destroy()

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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
