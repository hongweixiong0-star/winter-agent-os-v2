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
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

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


@dataclass(frozen=True)
class Source:
    """One data file, the budget its writer is expected to keep, and who shows it."""

    key: str
    label: str
    ttl_seconds: float
    used_by: str = ""
    retired: bool = False


#: The table.  ``ttl_seconds`` is "how long after the last write this file stops being
#: evidence for a *current* reading", chosen from each file's real write cadence rather than
#: from how important it feels.  A file that is written once per game event gets a day; the
#: runtime snapshot, which is written several times a second while AUTO runs, gets minutes.
SOURCES: tuple[Source, ...] = (
    # -- written by the runtime while AUTO runs -----------------------------------------
    Source("learning/runtime_snapshot.json", "运行态快照", 900, "总览·当前决策 / 系统·看门狗"),
    Source("learning/episodes.jsonl", "真机 episode 流", 1800, "总览·进度 / 能力·24h 成功率"),
    Source("learning/goal_state.json", "今日目标板", 900, "运行·目标"),
    Source("learning/global_scheduler_state.json", "全局调度状态", 900, "系统·角色仲裁"),
    Source("learning/task_completion_matrix.json", "今日完成矩阵", 3600, "系统·今日完成度"),
    Source("learning/executor_backend.jsonl", "执行器后端台账", 3600, "总览·执行器实测"),
    Source("learning/auto_uptime.jsonl", "运行时长台账", 3600, "总览·无人值守"),
    Source("learning/role_identity.json", "角色身份", 86400, "总览·当前角色"),
    Source("learning/knowledge_bootstrap/STATE.json", "预载控制器心跳", 21600, "总览·自动开发 / 自动开发·能力学习"),
    Source("learning/local_gui_model_calls.jsonl", "本地模型调用台账", 21600, "系统·顶部状态依据"),
    Source("learning/local_planner_steps.jsonl", "本地模型规划台账", 21600, "系统·顶部状态依据"),
    Source("learning/fishing_state.json", "钓鱼状态", 86400, "运行·活动·钓鱼"),
    Source("learning/fishing_runs.jsonl", "出钓记录", 86400, "运行·活动·钓鱼"),
    # -- written by a development/KB job, not by gameplay -------------------------------
    Source("learning/workbuddy_escalations.jsonl", "升级队列台账", 86400, "自动开发 / 总览·WorkBuddy"),
    Source("learning/workbuddy_model_stats.jsonl", "模型战绩", 172800, "自动开发·模型战绩"),
    Source("learning/event_goal_state.json", "活动低保观测记录", 21600, "运行·活动"),
    # -- knowledge / dataset / config: long-lived by construction ------------------------
    Source("knowledge/game/capability_catalog.json", "能力目录", 604800, "总览·KPI / 能力页 / 覆盖"),
    Source("knowledge/goals/capability_skill_map.json", "Goal→能力映射", 604800, "自动开发·Goal 覆盖"),
    Source("knowledge/roles/role_inventory.json", "角色清单", 1209600, "系统·角色仲裁"),
    Source("knowledge/ui/semantic_dictionary.json", "UI 语义词典", 2592000, "识别（页面已退休）"),
    Source("knowledge/ui/icons/manifest.json", "图标清单", 2592000, "识别（页面已退休）"),
    Source("dataset/candidate/template_manifest.json", "模板清单", 1209600, "识别"),
    Source("config/v2.json", "运行配置", 2592000, "设备 / 包名 / 模型"),
    Source("config/policy_state.json", "策略状态", 2592000, "运行·策略"),
    Source("config/control_panel_state.json", "面板状态", 604800, "系统·看门狗"),
    # -- retired on purpose: listed so its age has an explanation, never escalated ------
    Source("learning/goal_coverage.json", "Goal 覆盖率审计", 0,
           "无（消费方 _coverage 页面已于 2026-09 退休）", retired=True),
)


@dataclass(frozen=True)
class SourceAge:
    source: Source
    status: str
    age_seconds: float | None
    observed_at: str = ""

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
                     age, datetime.fromtimestamp(stamp, tz=timezone.utc).isoformat())


def all_ages(root: Path | str, *, now: datetime | None = None) -> dict[str, SourceAge]:
    return {source.key: age_of(root, source.key, now=now) for source in SOURCES}


def stale_among(ages: Mapping[str, SourceAge], *, auto_running: bool) -> tuple[SourceAge, ...]:
    """The escalation rule, over a table the caller already read.

    Split out from ``stale_while_running`` for one reason: a console on a UI tick wants to
    cache the *file stats* (26 ``stat`` calls) without caching the *AUTO verdict*, which can
    change between two ticks.  A caller that memoised both together would suppress the alarm
    for the whole memo window after the operator pressed 开始, and keep it firing for the same
    window after they pressed 停止.  The rule itself must stay in one place, hence this split.
    """
    if not auto_running:
        return ()
    return tuple(age for age in ages.values() if age.status == STALE and age.source.used_by)


def stale_while_running(root: Path | str, *, auto_running: bool,
                        now: datetime | None = None) -> tuple[SourceAge, ...]:
    """Sources that have stopped being written **while a writer should have been running**.

    ``auto_running`` is the caller's verdict on whether AUTO is up, and it is a parameter
    rather than something read here because the panel already owns that answer (it is derived
    from the worker process it started, not from a file a dead worker may have left behind).
    """
    return stale_among(all_ages(root, now=now), auto_running=auto_running)


def attention_lines(root: Path | str, *, auto_running: bool,
                    now: datetime | None = None, limit: int = 3) -> tuple[str, ...]:
    """The console's own one-liners for stale sources, worst first."""
    stale = sorted(stale_while_running(root, auto_running=auto_running, now=now),
                   key=lambda age: -(age.age_seconds or 0.0))
    return tuple(f"数据源已过期：{age.source.key}（{age.age_text()}）· 用于 {age.source.used_by}"
                 for age in stale[:limit])


__all__ = [
    "FRESH", "STALE", "MISSING", "RETIRED", "STATUS_ZH", "Source", "SourceAge", "SOURCES",
    "age_of", "all_ages", "stale_among", "stale_while_running", "attention_lines",
]
