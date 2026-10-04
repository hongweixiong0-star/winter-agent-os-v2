"""How old the evidence behind each console number is, from one table.

Measured 2026-10-04.  The console reads 28 data files and exactly **one** of them was ever
checked for age: the activity record, whose TTL was added that same day.  Everything else --
the capability catalog, the coverage map, the model scoreboard, the fishing record -- rendered
identically whether it had been written five seconds ago or twenty-five days ago.  A 24.9-day-old
``goal_coverage.json`` and a fresh ``runtime_snapshot.json`` were the same shade of black.

That is the same defect the activity page had, wearing the general case: **a number whose
source age is invisible**.  This module makes the age a first-class, single-sourced fact so a
page cannot show a derived figure without being able to say how old the thing it derived it
from is.

Two rules are load-bearing and both are here rather than in the panel, because the panel is
where the defect was:

* **A source's age is not a fault by itself.**  When AUTO is stopped nothing writes these
  files, so they age by design.  ``stale_while_running`` escalates an old source only when a
  writer should have been running -- otherwise the console would cry wolf every time the
  operator paused it, which is exactly the failure mode ``needs_reload`` warns about
  ("telling the operator to restart for one would train them to ignore the notice").
* **A retired source is not a stale source.**  ``goal_coverage.json`` is 24.9 days old because
  the page that read it was retired on purpose; reporting it as an anomaly would be a lie about
  why it stopped moving.
* **An age is only an alarm when a writer was due.**  ``stale_among`` gates on one thing -- whether
  AUTO is running -- and that gate is *justified* only for the rows whose writer is AUTO's own loop.
  For the other rows it was right by accident while AUTO happened to be down and wrong while it was
  up, which is how files nothing was ever going to rewrite came to stand on the operator's L1 card
  for good.  §六's stale-source row says "over budget **and** AUTO running"; the assumption buried
  in that "and" is that a writer should have run, so every row now declares who its writer is and
  that assumption is checked rather than assumed.
* **A per-call ledger's age measures use, not health.**  ``mtime`` on a file appended once per model
  call answers "how long since anything needed this", and no such age is a fault.  Measured
  2026-10-04: ``workbuddy_model_stats.jsonl`` holds 174 rows at 12.5 rows a day and its last three
  outcomes are ``"success": true`` -- it is idle, not broken.


"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

# The one budget this table does not choose for itself.  A heartbeat's budget is a property of the
# writer's cadence, and that writer declares it -- see ``HEARTBEAT_BUDGET_SECONDS``.
from .capability_bootstrap import HEARTBEAT_BUDGET_SECONDS

FRESH = "FRESH"
STALE = "STALE"
MISSING = "MISSING"
RETIRED = "RETIRED"

STATUS_ZH = {
    FRESH: "新鲜",
    STALE: "已过期",
    MISSING: "不存在",
    RETIRED: "已退休（无消费方）",
}

# Who keeps a file's cadence.  This is the whole reason one old file is a fault and another is only
# a fact, so every row in the table declares one instead of inheriting a default.
WRITER_LOOP = "loop"
#: ``WRITER_LOOP`` -- the running loop rewrites it, once per cycle.  These are the rows the AUTO
#: gate was written for: while AUTO runs a writer exists, and while it does not, the age is the
#: operator's own choice rather than a fault.
#: ``WRITER_CALL`` -- appended when a decision asks the model for help, not on a cycle.  Its age is
#: "how long since anything needed this", and a budget on that measures usage.
#: ``WRITER_WINDOW`` -- written only while a game event window is open.  The window is declared *by
#: the record itself*, so it can be checked rather than guessed at.
#: ``WRITER_UNSCHEDULED`` -- nothing runs on a clock to write it: a human runs the builder, the
#: operator changes the setting, or no writer exists anywhere in the tree.
WRITER_CALL = "call"
WRITER_WINDOW = "window"
WRITER_UNSCHEDULED = "unscheduled"

WRITERS: tuple[str, ...] = (WRITER_LOOP, WRITER_CALL, WRITER_WINDOW, WRITER_UNSCHEDULED)


@dataclass(frozen=True)
class Source:
    """One data file, the budget its writer is expected to keep, and who shows it."""

    key: str
    label: str
    ttl_seconds: float
    used_by: str = ""
    #: Who keeps this file fresh -- one of ``WRITERS``.  The default is the loop, which is the
    #: conservative direction for an alarm, and the tests pin that every row in the table names its
    #: writer explicitly rather than falling back to it.
    writer: str = WRITER_LOOP
    retired: bool = False

    @property
    def writer_note(self) -> str:
        """Why this file's age may be a statement rather than a fault, in the operator's words."""
        return {
            WRITER_CALL: "它按调用追加，多久没调用都不是故障",
            WRITER_WINDOW: "它只在活动窗口开着时被写",
            WRITER_UNSCHEDULED: "没有按时钟运行的写入者会来刷新它",
        }.get(self.writer, "")


#: The table.  ``ttl_seconds`` is "how long after the last write this file stops being
#: evidence for a *current* reading", chosen from each file's real write cadence rather than
#: from how important it feels.  A file that is written once per game event gets a day; the
#: runtime snapshot, which is written several times a second while AUTO runs, gets minutes.
#: ``writer`` says who keeps that cadence, which is what decides whether being late is a fault.
SOURCES: tuple[Source, ...] = (
    # -- written by the runtime's own loop, once per cycle ------------------------------
    # The rows the AUTO gate was written for: while AUTO runs a writer exists.  Rates below were
    # measured 2026-10-04 by stamping every row of each ledger and dividing by its own span.
    Source("learning/runtime_snapshot.json", "运行态快照", 900, "总览·当前决策 / 系统·看门狗",
           writer=WRITER_LOOP),
    Source("learning/episodes.jsonl", "真机 episode 流", 1800, "总览·进度 / 能力·24h 成功率",
           writer=WRITER_LOOP),                                  # 6 699 rows/day
    Source("learning/goal_state.json", "今日目标板", 900, "运行·目标",
           writer=WRITER_LOOP),
    Source("learning/global_scheduler_state.json", "全局调度状态", 900, "系统·角色仲裁",
           writer=WRITER_LOOP),
    Source("learning/task_completion_matrix.json", "今日完成矩阵", 3600, "系统·今日完成度",
           writer=WRITER_LOOP),
    Source("learning/executor_backend.jsonl", "执行器后端台账", 3600, "总览·执行器实测",
           writer=WRITER_LOOP),                                  # 6 718 rows/day
    Source("learning/auto_uptime.jsonl", "运行时长台账", 3600, "总览·无人值守",
           writer=WRITER_LOOP),                                  # 370 rows/day
    Source("learning/role_identity.json", "角色身份", 86400, "总览·当前角色",
           writer=WRITER_LOOP),
    # Not 21600 like its neighbours: this file is a *heartbeat*, written every 600 s by every
    # controller cycle including the refusals, so its budget is three missed beats rather than an
    # afternoon.  Imported from the module that owns the file so the top bar and this table cannot
    # disagree -- see ``HEARTBEAT_BUDGET_SECONDS`` for the five-and-a-half-hour window that cost.
    Source("learning/knowledge_bootstrap/STATE.json", "预载控制器心跳",
           HEARTBEAT_BUDGET_SECONDS, "总览·自动开发 / 自动开发·能力学习", writer=WRITER_LOOP),
    Source("learning/workbuddy_escalations.jsonl", "升级队列台账", 86400,
           "自动开发 / 总览·WorkBuddy", writer=WRITER_LOOP),        # 627 rows/day
    # -- appended when a decision calls the model, not once per cycle --------------------
    # ``mtime`` on a per-call ledger measures *use*, not health: it answers "how long since
    # anything needed this", and there is no such age that is a fault.  Rates measured 2026-10-04;
    # the scoreboard's own last three outcomes are ``"success": true``.
    Source("learning/local_gui_model_calls.jsonl", "本地模型调用台账", 21600, "系统·顶部状态依据",
           writer=WRITER_CALL),                                  # 75.6 rows/day
    Source("learning/local_planner_steps.jsonl", "本地模型规划台账", 21600, "系统·顶部状态依据",
           writer=WRITER_CALL),                                  # 21.2 rows/day
    Source("learning/workbuddy_model_stats.jsonl", "模型战绩", 172800, "自动开发·模型战绩",
           writer=WRITER_CALL),                                  # 12.5 rows/day, 174 rows
    # -- written only while a game event window is open ----------------------------------
    # The window is not guessed and not read from a recorded flag: the record declares its own
    # ``event_end_at`` and its owner module answers.  Measured 2026-10-04: the live file was 2.85
    # days old, and its declared window had closed exactly 2.85 days earlier -- it had been written
    # as recently as the event allowed.  A 24-hour budget turned that into a permanent alarm.
    Source("learning/fishing_state.json", "钓鱼状态", 86400, "运行·活动·钓鱼",
           writer=WRITER_WINDOW),
    Source("learning/fishing_runs.jsonl", "出钓记录", 86400, "运行·活动·钓鱼",
           writer=WRITER_WINDOW),
    # -- no clock: a builder, the operator, or nothing at all ----------------------------
    # Their age stays visible beside the figures they feed (``_source_age_note``, which ignores
    # AUTO on purpose, and the fold badges).  What they cannot do is ask for attention, because
    # nothing the operator does would make a writer appear.
    #
    # No writer exists anywhere in the tree for this one -- measured twice, by ``state_truth``
    # (595 h old, tree-wide search) and again on 2026-10-04 -- and it is a hand-recorded live
    # observation whose own countdown already expires it.  ``state_truth.legacy_event_row`` grades
    # it HISTORY on the page that reads it; escalating it here as well made one file stand on the
    # card for good.
    Source("learning/event_goal_state.json", "活动低保观测记录", 21600, "运行·活动",
           writer=WRITER_UNSCHEDULED),
    # Rebuilt by hand -- ``tools/build_capability_catalog.py`` -- and its own history already holds
    # a nine-day gap between rebuilds (09-18 -> 09-27), so its seven-day budget would fire on a
    # cadence the file has exhibited.
    Source("knowledge/game/capability_catalog.json", "能力目录", 604800, "总览·KPI / 能力页 / 覆盖",
           writer=WRITER_UNSCHEDULED),
    Source("knowledge/goals/capability_skill_map.json", "Goal→能力映射", 604800,
           "自动开发·Goal 覆盖", writer=WRITER_UNSCHEDULED),
    Source("knowledge/roles/role_inventory.json", "角色清单", 1209600, "系统·角色仲裁",
           writer=WRITER_UNSCHEDULED),        # not tracked by git, and no writer in the tree
    Source("knowledge/ui/semantic_dictionary.json", "UI 语义词典", 2592000, "识别（页面已退休）",
           writer=WRITER_UNSCHEDULED),
    Source("knowledge/ui/icons/manifest.json", "图标清单", 2592000, "识别（页面已退休）",
           writer=WRITER_UNSCHEDULED),        # one commit, 09-14; only this table names it
    Source("dataset/candidate/template_manifest.json", "模板清单", 1209600, "识别",
           writer=WRITER_UNSCHEDULED),
    Source("config/v2.json", "运行配置", 2592000, "设备 / 包名 / 模型",
           writer=WRITER_UNSCHEDULED),
    Source("config/policy_state.json", "策略状态", 2592000, "运行·策略",
           writer=WRITER_UNSCHEDULED),
    Source("config/control_panel_state.json", "面板状态", 604800, "系统·看门狗",
           writer=WRITER_UNSCHEDULED),        # written when a task toggle or 连续运行 changes
    # -- retired on purpose: listed so its age has an explanation, never escalated ------
    Source("learning/goal_coverage.json", "Goal 覆盖率审计", 0,
           "无（消费方 _coverage 页面已于 2026-09 退休）",
           writer=WRITER_UNSCHEDULED, retired=True),
)


@dataclass(frozen=True)
class SourceAge:
    source: Source
    status: str
    age_seconds: float | None
    observed_at: str = ""
    #: For a ``WRITER_WINDOW`` row: whether the window the record declares is still open.  ``None``
    #: for every other writer, and also when nobody could answer -- an unreadable record is not
    #: evidence that a window opened, and guessing "open" would turn a missing file into an alarm
    #: that never clears.
    window_open: bool | None = None

    def writer_note(self) -> str:
        """Why this row's age is or is not an alarm, in one clause, for the console."""
        if self.source.writer == WRITER_WINDOW and self.window_open is False:
            return "它只在活动窗口开着时被写，而窗口已经结束"
        return self.source.writer_note

    @property
    def key(self) -> str:
        return self.source.key

    @property
    def fresh(self) -> bool:
        return self.status == FRESH

    def age_text(self) -> str:
        if self.age_seconds is None:
            return ""
        seconds = float(self.age_seconds)
        if seconds < 3600:
            return f"{seconds / 60:.0f} 分钟前"
        if seconds < 86400:
            return f"{seconds / 3600:.1f} 小时前"
        return f"{seconds / 86400:.1f} 天前"

    def describe(self) -> str:
        """One line: which file, how old, and whether that age is acceptable."""
        if self.status == MISSING:
            return f"源 {self.source.key} 不存在"
        if self.status == RETIRED:
            return f"源 {self.source.key} · {STATUS_ZH[RETIRED]}"
        return (f"源 {self.source.key} · {self.age_text()}"
                f"（预算 {self.source.ttl_seconds / 3600:.0f} 小时，{STATUS_ZH[self.status]}）")


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


#: The rows whose writer is gated on a window the *record itself* declares.  The window's owner is
#: the module that owns the record: ``fishing_state`` parses ``event_end_at`` and is the only place
#: that knows what a fishing window is, so the question is asked there rather than re-derived from
#: the JSON here.
_WINDOW_OWNED_BY_FISHING = (
    "learning/fishing_state.json",
    "learning/fishing_runs.jsonl",
)


def _window_open(root: Path | str, key: str, moment: datetime) -> bool | None:
    """Ask the record's owner whether the window it declares is still open.

    ``None`` when nobody can answer.  Crucially this is *not* read from the record's
    ``event_live_open`` field: that flag says what was true when the record was written, and the
    live file still reads ``true`` 2.85 days after its own ``event_end_at`` passed (measured
    2026-10-04).  The deadline is the fact; the flag is a memory of one.
    """
    if key not in _WINDOW_OWNED_BY_FISHING:
        return None
    try:
        from .fishing_state import FishingState
    except Exception:  # noqa: BLE001 - an import problem must not become a verdict about data
        return None
    base = Path(root) / "learning"
    store = FishingState.load(base / "fishing_state.json", base / "fishing_runs.jsonl")
    return store.window_open(moment)


def age_of(root: Path | str, key: str, *, now: datetime | None = None) -> SourceAge:
    """Grade one source.  An unknown key is reported as MISSING rather than guessed at."""
    source = next((s for s in SOURCES if s.key == key), None)
    if source is None:
        source = Source(key, key, 0.0)
    if source.retired:
        return SourceAge(source, RETIRED, None)
    stamp = _mtime(Path(root) / key)
    if stamp is None:
        return SourceAge(source, MISSING, None)
    moment = now or datetime.now(timezone.utc)
    age = moment.timestamp() - stamp
    status = FRESH if age <= source.ttl_seconds else STALE
    return SourceAge(source, status,
                     age, datetime.fromtimestamp(stamp, tz=timezone.utc).isoformat(),
                     _window_open(root, key, moment))


def all_ages(root: Path | str, *, now: datetime | None = None) -> dict[str, SourceAge]:
    return {source.key: age_of(root, source.key, now=now) for source in SOURCES}


def writer_was_due(age: SourceAge, *, auto_running: bool) -> bool:
    """Whether the process that keeps this file fresh was expected to run at all.

    The gate is per-row because that is the only way "over budget" can mean "something stopped": a
    builder is never due, a per-call ledger is due exactly when a decision asks the model, and a
    game-event record is due only while its own declared window is open.  Gating every row on AUTO
    -- which is what this used to do -- gave the right answer for the loop's own files, the right
    answer by accident for the rest while AUTO happened to be stopped, and a permanent false alarm
    for the rest while it ran.
    """
    if not auto_running:
        return False
    if age.source.writer == WRITER_WINDOW:
        return bool(age.window_open)
    return age.source.writer == WRITER_LOOP


def stale_among(ages: Mapping[str, SourceAge], *, auto_running: bool) -> tuple[SourceAge, ...]:
    """The escalation rule, over a table the caller already read.

    Split out from ``stale_while_running`` for one reason: a console on a UI tick wants to
    cache the *file stats* (26 ``stat`` calls) without caching the *AUTO verdict*, which can
    change between two ticks.  A caller that memoised both together would suppress the alarm
    for the whole memo window after the operator pressed 开始, and keep it firing for the same
    window after they pressed 停止.  The rule itself must stay in one place, hence this split.
    """
    return tuple(age for age in ages.values()
                 if age.status == STALE and age.source.used_by
                 and writer_was_due(age, auto_running=auto_running))


def statement_among(ages: Mapping[str, SourceAge]) -> tuple[SourceAge, ...]:
    """Aged-out rows whose writer was **not** due, so their age is a statement rather than a fault.

    These are still worth *naming*: §六 asks for the stale file to be visible where the operator can
    see it, and the figures it feeds carry its age either way (``_source_age_note``, and the fold
    badges).  What they are not is a reason to be asked for attention, because nothing the operator
    then does would make a writer appear.

    Deliberately does not consult AUTO: a row whose writer was due belongs to ``stale_among``'s
    question ("should a writer have been running?") in both AUTO states, and answering it here too
    would print it twice.  With AUTO running the two functions partition every aged row that has a
    consumer, which is the invariant the tests pin.
    """
    return tuple(age for age in ages.values()
                 if age.status == STALE and age.source.used_by
                 and not writer_was_due(age, auto_running=True))


def stale_while_running(root: Path | str, *, auto_running: bool,
                        now: datetime | None = None) -> tuple[SourceAge, ...]:
    """Sources that have stopped being written **while a writer should have been running**.

    ``auto_running`` is the caller's verdict on whether AUTO is up, and it is a parameter
    rather than something read here because the panel already owns that answer (it is derived
    from the worker process it started, not from a file a dead worker may have left behind).
    """
    return stale_among(all_ages(root, now=now), auto_running=auto_running)


def describe_line(age: SourceAge) -> str:
    """``数据源已过期：<file>（<age>）· <why> · 用于 <consumer>`` -- the console's one-liner.

    The ``why`` clause appears only when the row's writer can explain itself, and those are exactly
    the rows whose age is *not* an alarm -- so the line that asks for attention stays the short one
    and the line that explains itself says why it does not.
    """
    note = age.writer_note()
    middle = f"· {note} · " if note else "· "
    return (f"数据源已过期：{age.source.key}（{age.age_text()}）{middle}"
            f"用于 {age.source.used_by}")


def attention_lines(root: Path | str, *, auto_running: bool,
                    now: datetime | None = None, limit: int = 3) -> tuple[str, ...]:
    """The console's own one-liners for sources that stopped while a writer was due, worst first."""
    stale = sorted(stale_while_running(root, auto_running=auto_running, now=now),
                   key=lambda age: -(age.age_seconds or 0.0))
    return tuple(describe_line(age) for age in stale[:limit])


def statement_lines(root: Path | str, *, now: datetime | None = None,
                    limit: int = 3) -> tuple[str, ...]:
    """One-liners for aged sources nobody was going to refresh, worst first."""
    aged = sorted(statement_among(all_ages(root, now=now)),
                  key=lambda age: -(age.age_seconds or 0.0))
    return tuple(describe_line(age) for age in aged[:limit])


__all__ = [
    "FRESH", "STALE", "MISSING", "RETIRED", "STATUS_ZH", "Source", "SourceAge", "SOURCES",
    "WRITER_LOOP", "WRITER_CALL", "WRITER_WINDOW", "WRITER_UNSCHEDULED", "WRITERS",
    "age_of", "all_ages", "writer_was_due", "stale_among", "stale_while_running",
    "statement_among", "describe_line", "attention_lines", "statement_lines",
]
