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
import types
from datetime import datetime, timedelta, timezone
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


def _page_builders() -> tuple[dict, set, set]:
    """``(every FunctionDef, the pages ``_build`` calls, every method that opens a tab)``.

    Lifted out of the tab-family guard so the tiering guard reads the **same** derivation: two
    answers to "what counts as a page" is the drift this whole file is about, one level up.
    """
    methods = {node.name: node for node in ast.walk(ast.parse(_panel_source()))
               if isinstance(node, ast.FunctionDef)}

    def self_calls(node) -> set:
        return {n.func.attr for n in ast.walk(node)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "self"}

    built = {name for name in self_calls(methods["_build"])
             if name in methods and "_tab" in self_calls(methods[name])}
    every = {name for name, node in methods.items() if "_tab" in self_calls(node)}
    return methods, built, every


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

    def _builders(self):
        # Delegates to the module-level derivation so "what is a page" has one answer; the two
        # helpers that used to do it here are gone rather than left as a second copy.
        return _page_builders()

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

    def _write_json(self, root: Path, relative: str, payload: dict,
                    *, age_seconds: float) -> None:
        import os

        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        stamp = NOW.timestamp() - age_seconds
        os.utime(path, (stamp, stamp))

    def test_every_row_declares_which_writer_keeps_it_fresh(self):
        """The writer is what decides whether an age is an alarm, so no row may inherit the
        default: a new row that forgot would silently take the loop's gate and start escalating
        a file nothing was ever going to write."""
        text = Path(sf.__file__).read_text(encoding="utf-8")
        rows = text[text.index("SOURCES: tuple[Source, ...] = ("):].split("\n    Source(")[1:]
        assert len(rows) == len(sf.SOURCES), "the table and the source file disagree"
        for row, source in zip(rows, sf.SOURCES):
            assert "writer=" in row, f"{source.key} does not declare its writer"
            assert source.writer in sf.WRITERS, f"{source.key} names an unknown writer"

    def test_a_builder_written_file_is_named_but_cannot_ask_for_attention(self, tmp_path):
        """``capability_catalog.json`` is rebuilt by hand, and its own history already holds a gap
        longer than its budget.  §六 wants the file named; nothing wants it counted."""
        self._write(tmp_path, "knowledge/game/capability_catalog.json", age_seconds=10 * 86400)
        ages = sf.all_ages(tmp_path, now=NOW)
        assert sf.stale_among(ages, auto_running=True) == ()
        assert [age.key for age in sf.statement_among(ages)] ==             ["knowledge/game/capability_catalog.json"]
        lines = sf.statement_lines(tmp_path, now=NOW)
        assert lines and "没有按时钟运行的写入者" in lines[0]

    def test_a_loop_written_file_still_escalates_while_auto_runs(self, tmp_path):
        self._write(tmp_path, "learning/runtime_snapshot.json", age_seconds=7200)
        self._write(tmp_path, "knowledge/game/capability_catalog.json", age_seconds=10 * 86400)
        assert [age.key for age in sf.stale_while_running(tmp_path, auto_running=True, now=NOW)] == \
            ["learning/runtime_snapshot.json"], "the loop's own file is the alarm"
        assert sf.stale_while_running(tmp_path, auto_running=False, now=NOW) == ()

    def test_the_two_halves_partition_every_aged_file_that_has_a_consumer(self, tmp_path):
        """No aged file may fall between them -- it would vanish from the console -- and none may
        fall in both, which would print it twice."""
        for key, age in (("learning/runtime_snapshot.json", 7200),
                         ("knowledge/game/capability_catalog.json", 10 * 86400),
                         ("learning/workbuddy_model_stats.jsonl", 4 * 86400),
                         ("learning/local_gui_model_calls.jsonl", 4 * 86400),
                         ("learning/fishing_state.json", 4 * 86400),
                         ("learning/goal_coverage.json", 40 * 86400)):
            self._write(tmp_path, key, age_seconds=float(age))
        ages = sf.all_ages(tmp_path, now=NOW)
        aged = {age.key for age in ages.values()
                if age.status == sf.STALE and age.source.used_by}
        due = {age.key for age in sf.stale_among(ages, auto_running=True)}
        stated = {age.key for age in sf.statement_among(ages)}
        assert due | stated == aged, "an aged file fell between the two answers"
        assert due & stated == set(), "an aged file was given both answers"

    def test_a_call_ledger_measures_use_and_not_health(self, tmp_path):
        """``mtime`` on a file appended per model call answers "how long since anything needed
        this".  Measured on the live tree: 174 rows at 12.5 a day, last three outcomes succeeded."""
        self._write(tmp_path, "learning/workbuddy_model_stats.jsonl", age_seconds=4 * 86400)
        ages = sf.all_ages(tmp_path, now=NOW)
        assert sf.stale_among(ages, auto_running=True) == ()
        assert "按调用追加" in sf.statement_lines(tmp_path, now=NOW)[0]

    def test_a_window_written_file_is_left_alone_once_its_window_closes(self, tmp_path):
        """The fishing record declares its own deadline, and the live file's age equals the time
        since that deadline passed to the minute: it had been written as recently as the event
        allowed, so its silence is the off-season rather than a stopped writer."""
        self._write_json(tmp_path, "learning/fishing_state.json",
                         {"roles": {"ROLE_A": {"role_id": "1",
                                               "event_end_at": (NOW - timedelta(days=2)).isoformat()}}},
                         age_seconds=2 * 86400)
        ages = sf.all_ages(tmp_path, now=NOW)
        assert ages["learning/fishing_state.json"].window_open is False
        assert sf.stale_among(ages, auto_running=True) == ()
        assert "窗口已经结束" in sf.statement_lines(tmp_path, now=NOW)[0]

    def test_a_window_written_file_is_an_alarm_while_its_window_is_open(self, tmp_path):
        """The complement has to hold, or the rule is a silencer rather than a distinction: with the
        window open and a writer due, a record that has not moved is exactly §六's fault."""
        self._write_json(tmp_path, "learning/fishing_state.json",
                         {"roles": {"ROLE_A": {"role_id": "1",
                                               "event_end_at": (NOW + timedelta(days=1)).isoformat()}}},
                         age_seconds=3 * 86400)
        ages = sf.all_ages(tmp_path, now=NOW)
        assert ages["learning/fishing_state.json"].window_open is True
        assert [age.key for age in sf.stale_among(ages, auto_running=True)] == \
            ["learning/fishing_state.json"]
        assert sf.stale_among(ages, auto_running=False) == (), "a stopped AUTO has no writer either"

    def test_the_recorded_flag_cannot_open_the_window(self, tmp_path):
        """``event_live_open`` says what was true when the record was written; the live file still
        reads ``true`` 2.85 days after its own deadline passed.  The deadline is the fact."""
        self._write_json(tmp_path, "learning/fishing_state.json",
                         {"roles": {"ROLE_A": {"role_id": "1", "event_live_open": True,
                                               "event_end_at": (NOW - timedelta(days=3)).isoformat()}}},
                         age_seconds=3 * 86400)
        assert sf.age_of(tmp_path, "learning/fishing_state.json", now=NOW).window_open is False

    def test_the_card_names_a_statement_without_counting_it(self, tmp_path, monkeypatch):
        """One reading, three answers: the card prints both, the verdict counts only the first, and
        the real fault keeps its seat in the 原因 line."""
        import importlib.util

        self._write(tmp_path, "learning/runtime_snapshot.json", age_seconds=7200)
        self._write(tmp_path, "knowledge/game/capability_catalog.json", age_seconds=10 * 86400)
        spec = importlib.util.spec_from_file_location("cp_attention_under_test", PANEL_PATH)
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
        stub.process = type("P", (), {"poll": lambda self: None})()
        display, counted, notices = stub._attention_with_sources(["⚠ STATE_CONFLICT：真的那一个"])
        assert len(display) == 3
        assert "capability_catalog" in " ".join(display), "a statement must still be named"
        assert "capability_catalog" in " ".join(notices)
        assert "capability_catalog" not in " ".join(counted)
        assert "STATE_CONFLICT" in " ".join(counted)
        assert "runtime_snapshot" in " ".join(counted), "a stopped writer is still counted"


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

        early_return = body[:body.index("        role = report.by_name")]
        assert 'self.values["intervene"].set(' in early_return
        assert "审计不可用" in early_return

    def test_the_count_is_what_the_operator_could_act_on(self):
        """Measured 2026-10-04: two permanent entries were counted *and* printed as the 原因, and
        the real fault never reached the line."""
        text = _module_function("intervention_of")(
            problems=["⚠ STATE_CONFLICT：a"],
            notices=["⚠ 数据源已过期：knowledge/game/capability_catalog.json（7.8 天前）· x"],
            auto_running=True, policy=None,
        )
        assert "（1 项）" in text
        assert "STATE_CONFLICT" in text, "the actionable item keeps the 原因 seat"

    def test_statements_alone_do_not_ask_for_attention(self):
        text = _module_function("intervention_of")(
            problems=[],
            notices=["⚠ 数据源已过期：a", "⚠ 数据源已过期：b"],
            auto_running=True, policy=None,
        )
        assert "不需要你干预" in text
        assert "2 个数据源" in text

    def test_the_notices_argument_is_optional(self):
        """The cell is also called with one list, and that call must still mean what it meant."""
        text = _module_function("intervention_of")(
            problems=["⚠ x"], auto_running=True, policy=None)
        assert "（1 项）" in text


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
            "preview": panel.L2,
            "kpi": panel.L3, "workbuddy": panel.L3, "watchdog": panel.L3,
            "stats": panel.L3, "events": panel.L3,
        }
        open_on_first_paint = [key for key, fold in harness._folds.items() if fold.expanded]
        assert open_on_first_paint == [], (
            f"{open_on_first_paint} are open before the operator touches anything -- and "
            f"``preview`` is included deliberately: §六 raises the live image only *while* the "
            f"progress line reads 无目标进展, so it is shut on a fresh window"
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

    # §六's exception table, as *declared*: every row that says a block opens itself.  The one row
    # with no implementation yet (队列积压) is named here rather than left out, so the gap is
    # written next to the rule instead of existing only as a missing badge -- and so that
    # implementing it forces an edit here rather than sliding in unnoticed.
    #
    # This set used to carry a second placeholder, ``"boot"``, labelled 「预载非正常 —— 尚未实现」.
    # Both halves of that entry were wrong, and 2026-10-04 measured it: there is no fold named
    # ``boot`` anywhere, and 预载's row is **already covered** by ``facts``'s annotation -- which
    # reads ``stale_among(..., auto_running=)`` for exactly this file, so the 事实卡 header names the
    # heartbeat the moment it ages out while AUTO is running.  It is a *mark* rather than an opener
    # because that block also watches a file, and the assertion below pins 「one block, one kind of
    # rule」; opening it would have traded a hard-won invariant for one saved click, while the
    # operator already gets three signals (the floating cell, the 需要关注 line, the marked header).
    SIX_TABLE_OPENERS = frozenset({
        "watchdog",          # unexpected_worker_exits > 0 · watchdog_restart_count 增长
        "runtime_watchdog",  # the same rule, on the 系统 page's own block
        "cap_runtime",       # the same field again, on the 能力 page -- one source, one standard
        "workbuddy",         # 网关非正常，或队列有活跃 Job
        "dev_wb",            # the same source again, on the 自动开发 page
        "dev_loop",          # 自主开发闭环「L1 当有断点」
        "dev_failures",      # 最近失败分类「次数超阈值」-- 用项目自己的 P0 分桶
        "preview",           # 总览「游戏实时画面 L2 → 卡住时 L1」-- 判据是进度行那条「无目标进展」
        "queues",            # 队列积压 —— 故意不实现：面板没有声明过的积压阈值（见 INERT_FOLDS）
        # 预载非正常 needs no entry: it is served by ``facts``'s annotation, not by an opener.
    })

    def test_the_block_that_opens_and_the_block_that_marks_are_not_the_same_rule(self):
        """Pins the split itself, because merging the two is the specific error that was made and
        the two rules look identical from a distance.

        Every block with an *opening* rule must be one §六 names for it (看门狗 / WorkBuddy /
        队列 / 预载 非正常，或队列有活跃 Job).  Everything else that watches a file only *marks*
        its header.  A block never gets both.
        """
        panel = self._panel()
        declared = self._declared_folds()
        opening = sorted(key for key, spec in declared.items() if spec["escalated"])
        illegal = sorted(key for key in opening if key not in self.SIX_TABLE_OPENERS)
        assert illegal == [], (
            "only the blocks §六 lists may float themselves to L1; these do not: "
            f"{illegal} (declared openers: {opening})"
        )
        assert opening, "one block must still be able to open itself, or this rule is dead"
        marking = sorted(key for key, spec in declared.items() if spec["annotated"])
        assert marking == ["facts", "kpi"], (
            "the stale-source row marks the cells and names the file, it does not open the "
            f"block; found {marking}"
        )
        assert not (set(opening) & set(marking)), "one block, one kind of rule"

    def test_no_page_opens_as_a_stack_of_shut_headers(self):
        """A page whose first widget is a collapsed header reads as an empty page.

        §六 assigns tiers per field, and on 系统 and 能力 the mechanical reading leaves almost
        nothing at L1 -- so applying it literally produces a page that opens as a column of shut
        bars.  The rule that catches that is structural: before a page's *first* fold, something
        the reader can actually read must already have been created **and placed**.  Checking the
        source order rather than counting L1 folds is deliberate: 总览 keeps 需要关注 and 手动干预
        outside the fold mechanism entirely, and 系统 keeps the role there, so "has an L1 fold" is
        the wrong question.
        """
        source = _panel_source()
        for builder in EveryPageBuildsOnARealTkRootTests.PAGE_BUILDERS:
            start = source.index(f"    def {builder}")
            nxt = source.find("\n    def ", start + 1)
            body = source[start:nxt if nxt != -1 else len(source)]
            first_fold = body.find("self._fold(")
            if first_fold == -1:
                continue
            head = body[:first_fold]
            assert "ttk.Label(" in head or "ttk.Frame(" in head, (
                f"{builder} declares folds but creates nothing before the first one; it would "
                f"open as a stack of shut headers"
            )
            assert ".pack(" in head or ".grid(" in head, (
                f"{builder} creates widgets before its first fold but never places them"
            )

    def test_no_two_blocks_share_a_fold_key(self):
        """``_fold`` keeps blocks in one dict, so a repeated key silently disables a block.

        The second declaration overwrites the first in ``self._folds``: the first container and
        its header still exist, but no rule ever runs for it, so it sits at its default tier with
        a badge nothing updates.  ``_declared_folds()`` cannot see this -- it returns a dict, and
        the dict is exactly what hides the collision -- so the keys are collected from the AST as
        a *list*.
        """
        keys = [
            kw.value.value
            for node in ast.walk(ast.parse(_panel_source()))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute) and node.func.attr == "_fold"
            for kw in node.keywords
            if kw.arg == "key" and isinstance(kw.value, ast.Constant)
        ]
        dupes = sorted({key for key in keys if keys.count(key) > 1})
        assert dupes == [], (
            f"two fold declarations share the key(s) {dupes}; the second would overwrite the "
            f"first and leave it with a badge nothing updates"
        )

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

    def test_a_breakpoint_opens_the_development_loop_and_a_clean_pass_does_not(self):
        """§六: 「自主开发闭环 **L1 当有断点**，否则 L3」.  The "when" has three exclusions and each
        one is a way this could become a permanently open block -- the failure mode MEMORY §57 is
        about -- so all four states are pinned rather than just the happy one.
        """
        import types

        panel = self._panel()
        stub = types.SimpleNamespace()
        rule = types.MethodType(panel.ControlPanel._escalate_dev_loop, stub)

        stub._closure_card = None
        assert rule() == "", "no card at all is a fresh install, not a breakpoint"
        stub._closure_card = {"ok": False, "reason": "台账里还没有一轮"}
        assert rule() == "", "a loop that never ran has no breakpoint to be stuck at"
        stub._closure_card = {"ok": True, "breakpoint": ""}
        assert rule() == "", "a card with no breakpoint is a PASS -- the one state that must fold"
        stub._closure_card = {"ok": True, "breakpoint": "VERSION_ACTIVE：等待真机校准"}
        said = rule()
        assert "VERSION_ACTIVE" in said, f"a real breakpoint must name itself: {said!r}"

    def test_the_failure_rule_opens_only_on_a_p0_and_uses_the_projects_own_threshold(self):
        """§六's 「失败次数 ≥ 阈值」 is implementable *without inventing a number* only because the
        project already buckets failures P0/P1/P2.  This pins both halves: the rule reads that
        bucketing rather than a constant of its own, and a P1 does not open the block.
        """
        import types
        from collections import Counter

        panel = self._panel()
        stub = types.SimpleNamespace()
        rule = types.MethodType(panel.ControlPanel._escalate_dev_failures, stub)

        # ``_module_panel()`` re-executes the script, so patching this module attribute is local to
        # this test rather than leaking into the others.
        assert panel.failure_priority(10) == "P0" and panel.failure_priority(9) == "P1"
        assert _panel_source().count("count >= 10") == 1, (
            "the P0 cut-off may appear exactly once -- inside failure_priority -- or the 优先级 "
            "column and the rule that opens this block can disagree about what P0 means"
        )

        panel.live_failure_counts = lambda: Counter({"技能未绑定": 3})
        assert rule() == "", "3 occurrences is a P1; §六 says the threshold, and P1 is not it"
        panel.live_failure_counts = lambda: Counter({"技能未绑定": 3, "模板缺失": 11})
        said = rule()
        assert "模板缺失" in said and "11" in said, f"the worst P0 must be named: {said!r}"

    def test_the_two_blocks_that_show_worker_exits_share_one_reading(self):
        """A block on the 系统 page and a block on the 能力 page watch the same field.  §57 was the
        lesson that reading it literally goes wrong; this is the guard that the *correction* is
        shared too, so the next page that shows it cannot quietly get the old behaviour back."""
        source = _panel_source()
        for name in ("_escalate_watchdog", "_escalate_capability_runtime"):
            start = source.index(f"    def {name}")
            end = source.find("\n    def ", start + 1)
            body = source[start:end if end != -1 else len(source)]
            assert "_worker_exits_since_window()" in body, (
                f"{name} must read the shared helper, not the raw cumulative counters"
            )

    def test_the_tier_of_a_block_is_keyed_by_tier_not_by_block(self):
        """A block must not be able to privately choose a different default from its tier."""
        panel = self._panel()
        assert panel.FOLD_DEFAULT_OPEN == {panel.L1: True, panel.L2: False, panel.L3: False}
        for spec in self._declared_folds().values():
            assert spec["level"] in panel.FOLD_DEFAULT_OPEN

    def test_a_cumulative_counter_is_read_as_growth_not_as_a_total(self):
        """§六's watchdog row is written ``unexpected_worker_exits > 0``, and that literal was
        implemented first and then killed by measurement on this machine.

        Both fields are cumulative -- ``previous.unexpected_worker_exits + 1``, persisted in the
        runtime store -- and the live values here are 22 and 28.  ``> 0`` therefore opens the
        block **forever** on any host whose workers have ever died once, which is the 狼来了
        failure mode that already had to be fixed once for stale sources.  The rule reads growth
        against the value this window first saw, and this test pins that with the real cumulative
        numbers rather than with tidy ones, because 22 is exactly the number the literal got wrong.
        """
        import types

        panel = self._panel()
        stub = types.SimpleNamespace(
            _watchdog_value=None,
            _unexpected_exits=22, _exits_baseline=22,
            _restart_count=28, _restart_baseline=28,
        )
        # The baseline arithmetic now lives in the shared helper the 能力 page's rule also calls,
        # so the stub needs both halves -- which is itself the point of extracting it: one
        # implementation of "growth since this window opened" instead of two.
        stub._worker_exits_since_window = types.MethodType(
            panel.ControlPanel._worker_exits_since_window, stub)
        rule = types.MethodType(panel.ControlPanel._escalate_watchdog, stub)

        assert rule() == "", (
            "22 exits and 28 restarts, all of them older than this window, is not a fault now"
        )
        stub._unexpected_exits = 23
        grew_by_one = rule()
        assert "1 次" in grew_by_one and "22" not in grew_by_one.split("累计")[0], (
            f"the badge must lead with the growth and keep the total as context: {grew_by_one!r}"
        )
        stub._unexpected_exits = 22
        stub._restart_count = 30
        assert "28" in rule(), "the restart half also reports growth against the baseline"
        stub._restart_count = 28
        assert rule() == "", "and it clears, so the alarm can shut itself again"

    def test_the_watchdog_rule_does_not_compare_a_cumulative_counter_to_zero(self):
        """The source-level half of the test above: a later edit could re-introduce the literal
        without breaking the behaviour test, by writing ``if exits:`` -- which is the same defect
        in a different spelling.

        Scoped to the method bodies rather than the whole module, so an unrelated comment that
        happens to contain the phrase cannot fail this, and a *real* re-introduction inside the
        rule cannot hide behind one.  Both the rule and the shared helper are checked, because
        moving the arithmetic into a helper is exactly how such a pin can be quietly defeated.
        """
        source = _panel_source()

        def body_of(name: str) -> str:
            start = source.index(f"    def {name}")
            end = source.find("\n    def ", start + 1)
            return source[start:end if end != -1 else len(source)]

        helper = body_of("_worker_exits_since_window")
        assert "_exits_baseline" in helper and "now - base" in helper, (
            "the unexpected-exit half must be read against the window's own baseline; §六's "
            "literal '> 0' measures the machine's history, not the present"
        )
        rule = body_of("_escalate_watchdog")
        assert "_worker_exits_since_window()" in rule, (
            "the watchdog rule must read that helper rather than the raw counters, or the 能力 "
            "page's rule could drift to a different standard for the same field"
        )
        assert "if unexpected:" not in rule and "if exits:" not in rule, (
            "that spelling is the literal again: it fires on any non-zero total"
        )

    # -- the three pages the rollout reached last (策略 / 目标 / 活动) --------------------------
    #
    # 目标 declares no folds at all, and that is the finding rather than an omission: §六 assigns
    # its tiers per *column*, and a single expanding ``Treeview`` has no vertical slack for a fold
    # to give back (measured: 338 px either way).  So §六 is honoured by column order there, and
    # the guards below pin the order instead of pinning folds that would not exist.

    def test_the_goal_board_draws_its_l1_columns_first(self):
        """§六's per-column tiers, honoured as order because a table cannot be folded.

        Worth pinning because the failure is silent: the board still renders, with the columns the
        reader decides on pushed off to the right behind two L3 ones.
        """
        panel = self._panel()
        tiers = [tier for _key, _title, _width, tier in panel.GOAL_COLUMNS]
        runs = [tier for index, tier in enumerate(tiers) if index == 0 or tiers[index - 1] != tier]
        assert runs == [panel.L1, panel.L2, panel.L3], (
            f"the columns must read L1, then L2, then L3, with no tier resumed after a later one; "
            f"got {tiers}"
        )
        assert [key for key, _t, _w, tier in panel.GOAL_COLUMNS if tier == panel.L1] == [
            "goal", "priority", "status", "deadline", "blocked"], (
            "§六 L1 on this page is 目标 / 优先级 / 状态 / 剩余 / 阻塞原因 -- the columns that "
            "answer 「卡在哪、要不要干预」"
        )

    def test_every_goal_column_is_named_by_the_row_builder(self):
        """The heading/value pairing is positional, so both sides must come from one declaration.

        Checked per declared key rather than by rendering, because the edit this forbids -- add a
        column and forget its value -- reaches the operator as a blank cell, and a blank reads as
        "unknown".  That is the same defect the 置信度 column was deleted for.
        """
        source = _panel_source()
        start = source.index("    def _refresh_goal_board")
        body = source[start:source.find("\n    def ", start + 1)]
        for key, title, _width, _tier in self._panel().GOAL_COLUMNS:
            assert f'"{key}":' in body, (
                f"the goal row builder never supplies a value for the {title!r} column "
                f"({key!r}), so it would render as a blank cell"
            )
        assert "values=(" not in body, (
            "rows must be built through _goal_row(): a positional tuple is exactly what couples "
            "the cells to the columns by index"
        )

    def test_the_activity_record_splits_the_way_the_audit_says(self):
        """§六 puts nine of the activity record's fields at L1 and five at L2, and the split *is*
        the change -- so it is pinned as data rather than left implicit in the page's layout.

        The second assertion is the one that matters: the two halves have to be exactly the keys
        the page writes.  A field dropped from both would vanish from the screen while every
        statement about "the L1 fields" still passed, and the page would raise on the next
        refresh -- ``_refresh_event_goal_display`` writes each key straight into
        ``event_goal_vars``, so its key set and this declaration are two halves of one contract.
        """
        panel = self._panel()
        l1 = [key for _label, key in panel.EVENT_L1_FIELDS]
        l2 = [key for _label, key in panel.EVENT_L2_FIELDS]
        assert l1 == ["name", "source", "last_verified", "current", "target", "missing",
                      "remaining", "status", "rewards"], (
            "§六 L1 on this page is the activity, its provenance, and where it stands -- including "
            f"数据来源 / 最后验证, which it keeps at L1 under 诚实性要求; got {l1}"
        )
        assert l2 == ["phase", "tier", "plan", "resource", "verified"], (
            f"§六 L2 is how it got there; got {l2}"
        )
        assert not set(l1) & set(l2), "a field cannot sit in both halves"

        source = _panel_source()
        start = source.index("    def _refresh_event_goal_display")
        body = source[start:source.find("\n    def ", start + 1)]
        assert "self.event_goal_vars[key].set(value)" in body, (
            "the writes no longer go through the loop this test reasons about; re-anchor it "
            "before trusting the key comparison below"
        )
        # Parsed from the whole module and located by name rather than by slicing the text: a
        # slice starts mid-indentation, so ``ast.parse`` on it raises IndentationError and the
        # guard would fail for a reason that has nothing to do with what it checks.
        written: set = set()
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.FunctionDef) or node.name != "_refresh_event_goal_display":
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.Assign) and any(
                        isinstance(target, ast.Name) and target.id == "values"
                        for target in inner.targets):
                    written = {key.value for key in inner.value.keys
                               if isinstance(key, ast.Constant) and isinstance(key.value, str)}
        assert written, "the key extraction found nothing -- this test would be vacuous"
        assert set(l1 + l2) == written, (
            f"the page writes {sorted(written)} but declares {sorted(set(l1 + l2))}; a key in one "
            f"and not the other is either a blank row or a KeyError on the next refresh"
        )

    def test_the_new_folds_hide_statements_and_never_a_control(self):
        """The 策略 page exists so the operator can change the switches, so the switches must not
        end up behind a header -- while the policy *statements* fold.

        Written as a source-order check because that is the only place the distinction lives: both
        are created by the same method, and a tier applied to the wrong one looks identical in the
        running window until someone goes looking for a control that is no longer there.
        """
        source = _panel_source()
        start = source.index("    def _strategy")
        body = source[start:source.find("\n    def ", start + 1)]
        switches = body.index("for index, (name, var) in enumerate(self.policy_enabled.items())")
        assert switches < body.index("self._fold("), (
            "the Goal Category switches are the page's only controls and must be created -- and "
            "placed -- before the first fold, or the page hides the thing it exists for"
        )
        assert body.count("Checkbutton") >= 2, (
            "the switches and the 运行方式 checkbox both stay outside the folds"
        )
        declared = self._declared_folds()
        for key in ("policy_reward", "policy_resource", "policy_forbidden",
                    "event_detail", "event_fishing"):
            assert key in declared, (
                f"{key} is no longer declared, so the statement it was hiding is back on the "
                f"page by default"
            )

    def test_the_live_image_opens_on_the_projects_own_stuck_predicate(self):
        """§六's 「游戏实时画面 L2 → 卡住时 L1」, and 卡住 is a predicate that already existed.

        ``_progress_line`` prefixes ``⚠ 无目标进展`` when the last steps succeeded as actions
        without moving a Goal -- the operator's own distinction.  The block opens on that same
        judgement rather than on a threshold invented for it, which is why §六's row was
        implementable at all (the same reason ``failure_priority`` served the 失败次数 row).

        All four states are exercised, because the one that matters is the one that does *not*
        open: with no reading yet, or with nothing having run, there is no evidence of being
        stuck -- only of not having started.
        """
        panel = self._panel()
        stalled = panel.progress_is_stalled
        assert stalled([]) is False, "nothing observed is not evidence of being stuck"
        assert stalled([{"verifier_ok": True, "goal_progress": True}]) is False, (
            "an action that moved a Goal is progress, not a stall"
        )
        assert stalled([{"verifier_ok": False, "goal_progress": False}]) is False, (
            "a step that failed its verifier did not succeed as an action, so it is not the "
            "predicate -- it is the failure path, which has its own block"
        )
        assert stalled([{"verifier_ok": True, "goal_progress": False}]) is True, (
            "actions succeeding with no Goal moving is exactly what §六 calls 卡住"
        )

    def test_the_progress_line_and_the_image_rule_share_one_predicate(self):
        """One judgement, two readers -- so they cannot drift into two opinions about 卡住.

        Checked in the source rather than by rendering, and both halves are checked: the line that
        paints ``⚠ 无目标进展`` and the rule that opens the image must both go through
        ``progress_is_stalled``, and neither may re-implement the comparison inline.
        """
        source = _panel_source()

        def body_of(name: str) -> str:
            start = source.index(f"    def {name}")
            end = source.find("\n    def ", start + 1)
            return source[start:end if end != -1 else len(source)]

        line = body_of("_progress_line")
        rule = body_of("_escalate_preview")
        assert "progress_is_stalled(rows)" in line, (
            "the progress line must derive ⚠ 无目标进展 from the shared predicate"
        )
        assert "_progress_stalled" in rule, (
            "the rule must read the window's own last verdict rather than re-reading the episode "
            "tail a second time on every tick"
        )
        assert "verifier_ok" not in rule, (
            "the rule must not re-implement the comparison; that is the second opinion this "
            "shares the predicate to avoid"
        )


class EveryPageHasBeenThroughTheAuditTests:
    """A page with no tier and a page nobody classified look identical in the source.

    §六 assigned a layer to every block and column of all seven pages.  Six pages carry folds; 目标
    carries none, and that is a *decision with a reason* -- a Treeview has no vertical slack (338 px
    whether or not its columns are grouped), so its layering is done by column order instead.  The
    only thing separating "decided" from "forgotten" is a written-down reason, so this guard demands
    one: a newly built page that folds nothing fails here until somebody says why it needs to fold
    nothing.  The page list is derived from ``_build``, not typed out, for the same reason the tab
    map is -- a new page has to be unable to slip past it.
    """

    # page builder -> why it declares no fold.  Only fold-less pages belong here.
    NO_FOLD_PAGES: dict[str, str] = {
        "_goals": (
            "目标页是一张 Treeview：它没有可折叠的竖向空间（实测 338 px 恒定），所以 §六 给它分的层"
            "由**列序**实现 —— GOAL_COLUMNS 一条声明同时驱动表头与每一行，L1 列在前"
        ),
    }

    def test_every_page_folds_something_or_says_why_it_folds_nothing(self):
        methods, built, every = _page_builders()
        assert len(built) == 7, sorted(built)
        builder_names = {name for name in every if name in built}
        assert set(self.NO_FOLD_PAGES) <= builder_names, (
            f"NO_FOLD_PAGES names something that is not a built page: "
            f"{sorted(set(self.NO_FOLD_PAGES) - builder_names)}"
        )

        def folds_of(name: str) -> int:
            return sum(1 for n in ast.walk(methods[name])
                       if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                       and n.func.attr == "_fold")

        untiered = sorted(name for name in builder_names
                          if folds_of(name) == 0 and name not in self.NO_FOLD_PAGES)
        assert untiered == [], (
            f"these pages declare no fold and no reason: {untiered}.  Either give them §六's tiers "
            f"or add them to NO_FOLD_PAGES with the reason -- 「没有折叠」 and 「没人分过」 must not "
            f"be the same source text"
        )
        for name, reason in self.NO_FOLD_PAGES.items():
            assert len(reason) >= 15, f"{name} must state why, not just that it has none"

    def test_the_page_without_folds_layers_its_columns_instead(self):
        """目标's exemption is only honest if the ordering really is the layering."""
        panel = _module_panel()
        tiers = [tier for _key, _title, _width, tier in panel.GOAL_COLUMNS]
        assert tiers == ["L1"] * 5 + ["L2"] * 2 + ["L3"] * 2, tiers
        assert tiers == sorted(tiers, key=tiers.index), (
            "a later tier appearing before an earlier one would split L1 across the board, and the "
            "operator's eye would have to skip a column to finish reading the things that matter"
        )


class _FakeCell:
    """A top-bar cell: seated on the strip, or removed from it.

    ``grid_remove`` rather than ``pack_forget`` because the strip is a grid -- the *seat number* is
    what decides where a returned cell lands, and that is the half of the rule the source cannot be
    asked about.
    """

    def __init__(self):
        self.seated = True

    def grid(self, **_kwargs):
        self.seated = True

    def grid_remove(self):
        self.seated = False


class TheTopBarTieringTests:
    """§六's first row: 「顶栏 9 格 → 6 常驻 + 3 折叠」 -- written in the audit, never built.

    Four checks, and each one closes a way the row could be *declared* instead of built.  The six
    come off the one table rather than off a second list.  A hidden cell must still be painted, or
    「收起来」 would quietly become 「没人写」 -- indistinguishable on screen, and the 待计算 defect
    this whole file exists for.  The decision must be made where the cell is painted and nowhere
    else, or the word beside a cell can disagree with whether the cell is there at all.
    """

    def _panel(self):
        return _module_panel()

    def test_the_top_bar_keeps_exactly_the_six_cells_the_audit_kept(self):
        panel = self._panel()
        keys = [key for _, key in panel.SYSTEM_INDICATORS]
        assert len(keys) == 9, "the strip is nine cells; this class is about tiering them"
        assert tuple(panel.HEADER_ALWAYS) == (
            "dot_v2", "dot_maa", "dot_mumu", "dot_game", "dot_auto", "clock"
        ), (
            "§六 kept these six as L1: the four physical layers plus AUTO plus the clock.  The clock "
            "is not decoration -- it is the base every 「最近 N 分钟」 reading is converted against"
        )
        assert tuple(panel.HEADER_FOLD_TO_L1) == ("dot_wb", "dot_model", "dot_boot"), (
            "§六 named exactly these three as L3 with 「异常浮 L1」"
        )
        assert set(panel.HEADER_ALWAYS) | set(panel.HEADER_FOLD_TO_L1) == set(keys), (
            "every cell is either 常驻 or 折叠.  A cell in neither would leave the strip with no "
            "rule at all, which is how the tab map came to advertise five pages nobody builds"
        )
        assert not set(panel.HEADER_ALWAYS) & set(panel.HEADER_FOLD_TO_L1)
        for key, reason in panel.HEADER_FOLD_TO_L1.items():
            assert len(reason) >= 15, (
                f"{key} must say *why* it left the strip, not just that it did -- the same rule "
                f"INERT_FOLDS is held to"
            )

    def test_a_healthy_cell_leaves_the_strip_and_a_sick_one_returns(self):
        """The mechanism, through the real methods, on a stub that records seating.

        Rendering is not needed to answer this one: what is being checked is a decision plus the two
        widget calls it makes.  The painted word is checked too, because the failure mode this guards
        against is 「hidden」 being achieved by simply not writing the cell any more.
        """
        panel = self._panel()
        from winter_agent_v2.state_truth import CONFLICT, LIVE_OBSERVED, TruthValue

        keys = [key for _, key in panel.SYSTEM_INDICATORS]

        class _Stub:
            pass

        stub = _Stub()
        stub.values = {key: _FakeVar() for key in keys}
        stub.indicators = {key: _FakeWidget() for key in keys}
        stub._indicator_cells = {key: _FakeCell() for key in keys}
        for name in ("_set_health", "_show_header_cell"):
            setattr(stub, name, types.MethodType(getattr(panel.ControlPanel, name), stub))

        healthy = TruthValue(name="gateway_health", value="正常", status=LIVE_OBSERVED)
        sick = TruthValue(name="gateway_health", value="不可达", status=CONFLICT)

        stub._set_health("dot_wb", healthy)
        assert stub.values["dot_wb"].get() == panel.DOT_GOOD, (
            "a hidden cell must still be painted: 「收起来」 and 「没人写」 must not look the same"
        )
        assert stub._indicator_cells["dot_wb"].seated is False, (
            "a healthy WorkBuddy gateway is L3 by §六 -- it does not need a seat"
        )

        stub._set_health("dot_wb", sick)
        assert stub._indicator_cells["dot_wb"].seated is True, (
            "异常 is the half of the rule that must work: 异常浮 L1"
        )
        assert stub.values["dot_wb"].get() == panel.DOT_BAD

        stub._set_health("dot_model", None)
        assert stub._indicator_cells["dot_model"].seated is True, (
            "「报告里没有这个来源」 is not health.  If absence could mean either 「正常」 or "
            "「读不到」, absence would answer nothing and a broken reader would look healthy"
        )

        for key in panel.HEADER_ALWAYS:
            stub._set_health(key, healthy)
            assert stub._indicator_cells[key].seated is True, (
                f"{key} is L1 by §六 and must not be removable by any reading"
            )

    def test_a_failed_audit_seats_the_three_instead_of_leaving_them_off(self):
        """The worst reading for a hidden cell is the one where nobody checks.

        If the audit cannot run, the three cells keep whatever verdict they had -- so a cell that was
        healthy when the audit broke would stay off the strip while the bar went on looking complete.
        The failure branch has to put them back as 未确认.
        """
        source = _panel_source()
        start = source.index("    def _refresh_truth")
        end = source.find("\n    def ", start + 1)
        body = source[start:end if end != -1 else len(source)]
        # The 「审计不可用」 branch is everything above its own ``return``; every reading below that
        # point is taken on a report that exists.
        failing = body[:body.index("return")]
        assert "for key in HEADER_FOLD_TO_L1" in failing, (
            "the 「审计不可用」 branch must re-seat the three L3 cells; otherwise the strip's "
            "completeness is itself the thing hiding the failure"
        )
        assert "self._set_health(key, None)" in failing, (
            "re-seated as 未确认 -- passed None so the cell and the seating decision cannot disagree"
        )


class TheWiringVerifierCanStillRunTheRealRefreshTests:
    """A tool that stubs a panel must be updated the day the panel's refresh grows a call.

    ``gui_wiring_verify`` binds the real ``_refresh_truth`` onto a stub **on purpose** -- so that a
    change to how the panel paints a cell is verified rather than assumed.  The price of that design
    is a failure mode with no warning: add one call inside the refresh and the verifier raises
    ``AttributeError`` and verifies nothing at all.  The tool that exists to catch unwired fields
    becomes an unwired tool.  That is not hypothetical -- it happened on 2026-10-04, when
    ``_set_health`` began seating top-bar cells for §六 and the verifier died on
    ``_show_header_cell``, *after* the change had been measured and committed.

    So this guard is not "the source mentions the new helper".  It runs the verifier's **own stub**
    through the real refresh, which raises exactly the way the tool raises.  A new collaborator of
    ``_refresh_truth`` now fails here the same day instead of the next time somebody hand-runs the
    tool -- and the failure names the tool, which is where the fix belongs.
    """

    def _verifier(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "gui_wiring_verify_under_test", ROOT / "tools" / "gui_wiring_verify.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_the_verifier_stub_runs_the_real_refresh(self):
        module = self._verifier()
        # Raises AttributeError if the stub is missing anything the refresh now calls.
        module.panel.ControlPanel._refresh_truth(module._stub())

    def test_the_verifier_models_a_cell_as_leaving_the_strip_not_as_blank_text(self):
        """The stub has to hide cells the same *way* the window does, or it verifies the opposite."""
        module = self._verifier()
        stub = module._stub()
        assert hasattr(stub, "_show_header_cell"), (
            "the verifier must bind the seating helper: with ``_indicator_cells`` absent the helper "
            "returns early, and the top bar would be reported as verified without the tiering ever "
            "being exercised"
        )
        for _, key in module.panel.SYSTEM_INDICATORS:
            cell = stub._indicator_cells[key]
            assert callable(getattr(cell, "grid_remove", None)), (
                f"{key} is modelled as {type(cell).__name__}; §六's tiering takes the cell *off the "
                f"strip*, and a stub that modelled hiding as an empty string would agree with a "
                f"window that only blanked the text"
            )


class TheAutoVerdictIsTakenOnceAndGatesOnlyTheCellsAutoWritesTests:
    """停止 AUTO 不能变成一条告警 -- §六's own 狼来了 note, applied to the top bar.

    Measured on the real root (2026-10-04), before this gate existed: ``state_truth.bootstrap()``
    grades STALE on **age alone**, so 停止 for 31 minutes put 预载降级 *on the bar* while the 干预卡
    two blocks up was printing 「AUTO 未在运行（这是你的选择，不是故障）」.  One screen, two opposite
    answers to one question -- the P0-3 class the tier table exists to prevent.

    Five checks, each closing a way the fix could be *declared* instead of built.
    """

    def _val(self, name, status, value="x", note=""):
        from winter_agent_v2.state_truth import TruthValue

        return TruthValue(name=name, value=value, status=status, note=note)

    def test_a_stale_cell_whose_only_writer_is_auto_stays_off_while_auto_is_stopped(self):
        panel = _module_panel()
        from winter_agent_v2.state_truth import STALE

        boot = self._val("bootstrap", STALE, value="学习中 · 等待验证 3")
        assert panel.header_cell_is_visible("dot_boot", boot, auto_running=True) is True, (
            "AUTO 在跑、心跳却停了 is precisely the fault §六 asks to surface -- if the gate hid "
            "this too it would be a mute button rather than a gate"
        )
        assert panel.header_cell_is_visible("dot_boot", boot, auto_running=False) is False, (
            "没有写入者就没有新数据: the same split ``source_freshness.stale_among`` already makes "
            "for files, and the reason 停止 must not read as 降级"
        )

    def test_the_gate_names_exactly_the_cells_auto_writes(self):
        panel = _module_panel()
        from winter_agent_v2.state_truth import STALE

        assert panel.header_cell_is_visible(
            "dot_model", self._val("local_model", STALE), auto_running=False) is True, (
            "the model is a service reached over HTTP, not something AUTO's worker writes: its "
            "silence is a fact about the service and must keep its seat"
        )
        assert set(panel.HEADER_CELLS_WRITTEN_BY_AUTO) <= set(panel.HEADER_FOLD_TO_L1), (
            "the gate can only apply to a cell that was already removable -- otherwise it would be "
            "hiding an L1 cell, which no reading may do"
        )
        for key, reason in panel.HEADER_CELLS_WRITTEN_BY_AUTO.items():
            assert len(reason) >= 15, f"{key} must say why its writer is AUTO, not just that it is"

    def test_a_conflict_is_never_explained_away_by_a_stopped_writer(self):
        panel = _module_panel()
        from winter_agent_v2.state_truth import CONFLICT

        bad = self._val("bootstrap", CONFLICT, value="冲突")
        assert panel.header_cell_is_visible("dot_boot", bad, auto_running=False) is True, (
            "异常 is not something a stopped writer can explain; only 降级/未确认 are gated"
        )
        assert panel.header_cell_is_visible("dot_boot", None, auto_running=False) is True, (
            "「the audit has no such source」 is not explained by AUTO being down either -- and "
            "hiding it would let a broken reader look like a healthy system"
        )

    def test_the_auto_verdict_is_taken_once_and_shared(self):
        source = _panel_source()
        start = source.index("    def _refresh_truth")
        body = source[start:source.index("\n    def ", start + 10)]
        assert ("self._auto_running = self.process is not None "
                "and self.process.poll() is None") in body, (
            "the verdict must be taken inside the refresh, from the worker process this window "
            "started -- never from a status file a dead worker may have left behind"
        )
        assert body.count("self.process.poll()") == 1, (
            f"the 干预卡's 「AUTO 未在运行（这是你的选择，不是故障）」 and the top bar's gate must be "
            f"one reading; found {body.count('self.process.poll()')} copies, and two copies is how "
            f"the bar comes to call a fault what the card calls your choice"
        )

    def test_no_rule_re_answers_what_not_normal_means(self):
        """「非正常」 must have one definition, and the guard reads the *code*, not the prose.

        Two rules each carried their own ``colour in ("bad", "warn")`` before this pass, and a third
        was about to.  The needle appears a second time inside ``unhealthy_word``'s own docstring --
        which is history, not a copy, and is exempt for the same reason ``_string_literals`` exempts
        comments.
        """
        tree = ast.parse(_panel_source())
        owners = []
        for func in ast.walk(tree):
            if not isinstance(func, ast.FunctionDef):
                continue
            for node in ast.walk(func):
                if not isinstance(node, ast.Compare):
                    continue
                words = {c.value for c in node.comparators
                         if isinstance(c, (ast.Tuple, ast.List))
                         for c in c.elts if isinstance(c, ast.Constant)}
                if {"bad", "warn"} <= words:
                    owners.append(func.name)
        assert owners == ["unhealthy_word"], (
            f"「非正常」 is answered in {owners}; one definition (``unhealthy_word``) is what stops "
            f"two blocks from grading the same value differently"
        )


class ThePreloadHeartbeatHasOneBudgetTests:
    """One file, one budget -- and it had three readings until this pass.

    Measured 2026-10-04: ``state_truth.bootstrap()`` graded STALE on the literal ``3 * 600``, the
    panel's 系统 page spelled the same rule ``3 * QueuePump.PRELOAD_EVERY * QueuePump.INTERVAL``,
    and ``source_freshness``'s table declared ``21600`` for the same file -- a value its two
    neighbours in the table also carry, i.e. inherited rather than chosen.

    The cost was not academic.  ``source_freshness`` is what feeds the 需要关注 card and the 事实卡
    header, so for five and a half hours after the controller died the top bar said 预载降级 while
    the card said 没有问题: one screen, two answers, and the honest one invisible.
    """

    KEY = "learning/knowledge_bootstrap/STATE.json"

    def _budget(self):
        from winter_agent_v2 import source_freshness as sf

        row = next(s for s in sf.SOURCES if s.key == self.KEY)
        return row.ttl_seconds

    def test_the_table_uses_the_writers_own_budget_not_a_neighbours(self):
        from winter_agent_v2.capability_bootstrap import HEARTBEAT_BUDGET_SECONDS

        assert self._budget() == HEARTBEAT_BUDGET_SECONDS, (
            "the heartbeat's budget is a property of its writer's cadence; a number copied from the "
            "rows beneath it makes the 需要关注 card call a dead controller healthy"
        )

    def test_it_is_three_missed_beats_and_not_an_afternoon(self):
        from winter_agent_v2.capability_bootstrap import (
            HEARTBEAT_BUDGET_SECONDS, HEARTBEAT_SECONDS_PER_BEAT)

        assert HEARTBEAT_BUDGET_SECONDS == 3 * HEARTBEAT_SECONDS_PER_BEAT, (
            "one missed beat is a slow round, three is a stopped controller -- the two named "
            "constants must keep that relation, or the number stops being an argument"
        )
        assert self._budget() < 4 * 3600, (
            "a *heartbeat* is not allowed a multi-hour budget: every controller cycle writes it, "
            "including the refusals, so silence is evidence about the process"
        )

    def test_the_panels_own_derivation_still_equals_the_shared_number(self):
        """The panel spells the rule out of its two cadence constants rather than importing it.

        That spelling is the *argument* for the number, so it is worth keeping -- and worth a guard,
        because a spelling that drifts from the shared constant is exactly the defect above.
        """
        from winter_agent_v2.capability_bootstrap import HEARTBEAT_BUDGET_SECONDS

        panel = _module_panel()
        derived = 3 * panel.QueuePump.PRELOAD_EVERY * panel.QueuePump.INTERVAL
        assert derived == HEARTBEAT_BUDGET_SECONDS, (
            f"the panel derives {derived}s from PRELOAD_EVERY × INTERVAL while the library declares "
            f"{HEARTBEAT_BUDGET_SECONDS}s; one of the two cadences moved"
        )

    def test_the_beat_period_is_what_the_pump_actually_runs(self):
        """``HEARTBEAT_SECONDS_PER_BEAT`` is a *copy* of the pump's cadence, so it is guarded too."""
        from winter_agent_v2.capability_bootstrap import HEARTBEAT_SECONDS_PER_BEAT

        panel = _module_panel()
        assert (panel.QueuePump.PRELOAD_EVERY * panel.QueuePump.INTERVAL
                == HEARTBEAT_SECONDS_PER_BEAT), (
            "the library's beat period must equal the one cycle per PRELOAD_EVERY × INTERVAL the "
            "pump actually runs, or every budget derived from it is fiction"
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
