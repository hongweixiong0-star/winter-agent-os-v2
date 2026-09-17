from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import traceback
import ctypes
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tkinter import ttk
from typing import Any

from PIL import Image, ImageDraw, ImageTk

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import runtime_env
from winter_agent_v2.device import ADBDevice
from winter_agent_v2.escalation_queue import (
    AUTO_ESCALATION_CONDITIONS,
    DEFAULT_LEDGER,
    EscalationLedger,
)
from winter_agent_v2.models import MarchState, Page, SkillState, WorldState
from winter_agent_v2.retention import prune_runtime_screenshots
from winter_agent_v2.runtime_reload import REQUEST_KIND, ReloadSignal, default_path as reload_path
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.runtime_snapshot import (
    UNCLASSIFIED_EVENT,
    AgentState,
    RuntimeSnapshotStore,
    counts_as_unexpected_worker_exit,
    is_fatal_stop,
)

CONFIG_PATH = ROOT / "config/v2.json"
PANEL_STATE_PATH = ROOT / "config/control_panel_state.json"
RUNTIME_PATH = ROOT / "tools/run_live.py"

# Raised when the panel is asked to start work on an interpreter that cannot run
# the production loop.  It is classified as an environment failure (see
# ENVIRONMENT_FAILURES) so refusing to start is never counted as a worker crash.
RUNTIME_ENV_STOP_REASON = "RUNTIME_ENV_NOT_PRODUCTION_READY"

# How long to wait before re-checking a deferred start.  Each cycle is a fresh
# subprocess, so "reload" here means "do not import a half-written tree" -- there
# is no in-process hot swap to perform (see winter_agent_v2/runtime_reload.py).
RELOAD_RETRY_MS = 5000

_ESCALATION_LEDGER_PATH = ROOT / DEFAULT_LEDGER


def reload_deferral() -> tuple[ReloadSignal, object]:
    """Should this start be postponed because a development agent just wrote code?

    Returns the signal so the caller can clear it once the wait is over.  Reads
    the escalation ledger for in-flight jobs, because a marker whose job is still
    working must keep the runtime off the tree for longer than a plain settle
    window -- but never longer than the signal's own ceiling, so a hung agent
    cannot stall AUTO.
    """
    signal = ReloadSignal(reload_path(ROOT))
    try:
        active = len(EscalationLedger(_ESCALATION_LEDGER_PATH).snapshot().active_jobs())
    except Exception:  # noqa: BLE001 - an unreadable ledger must not block a start
        active = 0
    return signal, signal.evaluate(active_jobs=active)


_INTERPRETER_LOCK = threading.Lock()
_INTERPRETER_REPORT: runtime_env.InterpreterReport | None = None


def runtime_interpreter_report() -> runtime_env.InterpreterReport:
    """The interpreter the worker will be spawned with, probed exactly once.

    ``PYTHON_PATH`` used to be derived from the panel's own ``sys.executable``,
    which made the worker inherit whichever interpreter launched the panel.  The
    panel running on 2026-09-17 had been launched with a generic runtime python
    without ``maa`` or ``cv2``, and the worker said so in its piped stdout
    ("MAA_IMPORT_FAILED:ModuleNotFoundError ... observations stay on ADB").  No
    *executed* step in those runs belonged to a skill promoted to MAA, so nothing
    was measured through the slow path yet -- but the next AUTO run would have
    taken ADB capture at 324 ms where MAA EmulatorExtras costs 8.92 ms, and the
    run would still have looked healthy.  The interpreter is now resolved and
    *proved* before it is used.
    """
    global _INTERPRETER_REPORT
    if _INTERPRETER_REPORT is None:
        with _INTERPRETER_LOCK:
            if _INTERPRETER_REPORT is None:
                _INTERPRETER_REPORT = runtime_env.resolve_for_project(ROOT)
    return _INTERPRETER_REPORT


def runtime_python_path() -> str:
    """The production interpreter as an executable path, for spawning the worker."""
    return str(runtime_interpreter_report().python_exe)


def runtime_env_blocker() -> str | None:
    """``None`` when production can run here, otherwise why it cannot."""
    report = runtime_interpreter_report()
    return None if report.ok else report.reason
CAPTURE_ROOT = ROOT / "dataset/raw/control_panel"
LOG_ROOT = ROOT / "learning/control_panel"
CRASH_ROOT = LOG_ROOT / "crashes"
RUNTIME_SNAPSHOT_PATH = ROOT / "learning/runtime_snapshot.json"
MUMU_PATH = Path(r"D:\Program Files\Netease\MuMu Player 12\nx_main\MuMuNxMain.exe")
MUMU_MANAGER_PATH = Path(r"D:\Program Files\Netease\MuMu Player 12\nx_main\MuMuManager.exe")
MUMU_VM_INDEX = "0"
BG, PANEL, PANEL2 = "#0b1118", "#111b26", "#172432"
TEXT, MUTED, ACCENT = "#e7edf4", "#8fa1b3", "#53b7ff"
GOOD, WARN, BAD = "#52d49a", "#f0b35a", "#ef6b73"
NO_WINDOW_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_INSTANCE_MUTEX: int | None = None


def _acquire_single_instance() -> bool:
    """Keep desktop double-clicks from creating competing control panels."""
    global _INSTANCE_MUTEX
    if os.name != "nt":
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateMutexW(None, False, "Local\\WinterAgentOSV2ControlPanel")
    if not handle:
        return False
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return False
    _INSTANCE_MUTEX = handle
    return True


def _background_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    """Run a console utility without leaking a black Windows console window."""
    return subprocess.run(command, creationflags=NO_WINDOW_FLAGS, **kwargs)


def _background_popen(command: list[str], **kwargs: Any) -> subprocess.Popen[str]:
    """Launch a runtime child fully backgrounded."""
    return subprocess.Popen(command, creationflags=NO_WINDOW_FLAGS, **kwargs)


# Environment failures the worker raises on purpose when the emulator, the ADB
# link, or the operator gets in the way.  They are recoverable by waiting and
# retrying, and they are NOT evidence of a worker defect, so they must not be
# counted as an unexpected worker exit.  Anything else that escapes the worker
# thread is a real crash and is counted, with a full report.
ENVIRONMENT_FAILURES = (
    "DEVICE_NOT_CONNECTED", "DEVICE_AMBIGUOUS", "ADB_DISCOVERY_FAILED", "ADB_FAILED",
    "MuMu 未连接", "MuMu 实例启动失败", "等待 MuMu 连接超时", "用户已停止",
    "SCREENSHOT_NOT_PNG", "SCREENSHOT_DAMAGED", RUNTIME_ENV_STOP_REASON,
)


def classify_worker_failure(message: str) -> str:
    """Return ``ENVIRONMENT`` or ``WORKER_CRASH`` for a worker failure message."""
    text = str(message or "")
    return "ENVIRONMENT" if any(marker in text for marker in ENVIRONMENT_FAILURES) else "WORKER_CRASH"


def write_worker_crash_report(*, where: str, exc: BaseException, snapshot: Any) -> Path:
    """Persist the evidence needed to find the real root cause of a worker exit.

    Previously the worker caught ``Exception`` and forwarded only ``str(exc)``,
    so every crash arrived as one unhelpful line and the counter could not be
    acted on.  This records the exception type, the full traceback, the runtime
    state at the moment of death, and the live thread inventory.
    """
    CRASH_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    report = {
        "at": datetime.now(timezone.utc).isoformat(),
        "where": where,
        "exception_type": type(exc).__name__,
        "exception_message": str(exc),
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        "classification": classify_worker_failure(str(exc)),
        "thread_state": [
            {"name": thread.name, "alive": thread.is_alive(), "daemon": thread.daemon}
            for thread in threading.enumerate()
        ],
        "runtime_snapshot": snapshot.__dict__ if hasattr(snapshot, "__dict__") else str(snapshot),
    }
    path = CRASH_ROOT / f"{stamp}_{where}.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path

PAGE_ZH = {"HOME": "主城", "MAP": "世界地图", "RESOURCE_DETAIL": "资源点", "MARCH": "行军编队",
           "MARCH_QUEUE": "行军队列", "BUILDING": "建筑", "RESEARCH": "科技", "TRAINING": "训练",
           "INTEL": "情报", "BEAST": "野怪", "DAILY": "日常", "ALLIANCE": "联盟", "MAIL": "邮件",
           "EXPLORATION": "探险", "HERO": "英雄", "POPUP": "弹窗", "UNKNOWN": "页面未识别"}
SKILL_ZH = {"GATHER_RESOURCE": "资源采集", "BUILDING_UPGRADE": "建筑升级", "RESEARCH": "科技研究",
            "TRAIN_TROOPS": "训练部队", "INTEL_CLAIM_REWARDS": "情报奖励", "BEAST_HUNT": "野怪狩猎",
            "DAILY_HERO_RECRUIT": "每日招募", "DAILY_CLAIM_REWARDS": "日常奖励",
            "ALLIANCE_TECH_CONTRIBUTE": "联盟科技", "ALLIANCE_HELP": "联盟帮助",
            "ALLIANCE_GIFTS": "联盟礼物", "MAIL_CLAIM_REWARDS": "邮件奖励",
            "OPEN_POWER_OVERVIEW": "打开战力总览", "OPEN_POWER_DETAILS": "打开实力详情",
            "NAVIGATE_INFANTRY_CAMP": "定位盾兵营", "OPEN_INFANTRY_TRAINING": "打开盾兵训练",
            "TRAIN_TROOPS": "训练盾兵",
            "OPEN_MAIL": "打开邮件", "SELECT_MAIL_ALLIANCE_TAB": "联盟邮件", "SELECT_MAIL_SYSTEM_TAB": "系统邮件",
            "SELECT_MAIL_REPORT_TAB": "报告邮件", "DISMISS_MAIL_REWARD": "关闭邮件奖励",
            "EXPLORATION_IDLE_CLAIM": "探险收益", "OPEN_MAP": "前往世界地图",
            "OPEN_HOME": "返回主城", "SEARCH_RESOURCE": "搜索资源", "SELECT_RESOURCE": "选择资源",
            "SUBMIT_RESOURCE_SEARCH": "查找资源点", "START_GATHER": "开始采集",
            "OPEN_EXPLORATION": "打开探险", "EXPLORATION_IDLE_CLAIM": "打开挂机收益",
            "CONFIRM_EXPLORATION_IDLE_CLAIM": "领取挂机收益", "DISMISS_EXPLORATION_REWARD": "关闭探险奖励",
            "OPEN_DAILY": "打开每日任务", "DAILY_CLAIM_REWARDS": "领取每日奖励", "DISMISS_DAILY_REWARD": "关闭每日奖励",
            "DISMISS_MAIL_GENERIC_REWARD": "关闭邮件奖励",
            "DISPATCH_MARCH": "派遣行军", "CLOSE_POPUP": "关闭弹窗",
            "OPEN_INTEL": "打开情报", "SELECT_INTEL_BEAST_MISSION": "选择情报兽任务", "SELECT_INTEL_FIREBEAST_MISSION": "选择炽红巨兽情报",
            "SELECT_INTEL_RESCUE_SURVIVORS": "选择营救幸存者", "OPEN_INTEL_RESCUE_SURVIVORS_TARGET": "查看营救目标", "EXECUTE_INTEL_RESCUE_SURVIVORS": "执行营救",
            "OPEN_INTEL_BEAST_TARGET": "查看情报目标", "INTEL_BEAST_START_MARCH": "情报兽编队",
            "DISPATCH_INTEL_BEAST": "派遣情报兽", "DISMISS_INTEL_REWARD": "关闭情报奖励"}
REASON_ZH = {"no_idle_march": "没有空闲行军，已安全等待", "reserved_march_for_stamina": "已为体力任务预留1支行军", "max_actions_reached": "本轮动作上限已到",
             "target_skill_verified": "任务已通过验证", "UNKNOWN_PAGE": "页面未识别",
             "unknown_page": "页面未识别", "DEVICE_BUSY": "设备忙", "VISION_FAILURE": "视觉识别失败",
             "PAGE_NOT_FOUND": "未找到目标页面", "SKILL_NOT_ENABLED_FOR_LIVE_LOOP": "能力尚未接入实机主循环",
             "mail_all_clear": "邮件奖励已全部清空", "mail_state_unknown": "邮件状态未识别"}
MARCH_ZH = {MarchState.IDLE: "空闲", MarchState.MARCHING: "行军中", MarchState.GATHERING: "采集中",
            MarchState.RETURNING: "返回中", MarchState.UNKNOWN: "未识别"}


def parse_runtime_result(text: str) -> dict:
    for line in reversed(text.splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and "stop_reason" in payload:
            return payload
    return {}


def summarize_runtime_result(payload: dict, exit_code: int = 0) -> dict[str, Any]:
    steps = payload.get("steps", []) if isinstance(payload, dict) else []
    steps = steps if isinstance(steps, list) else []
    executed = verified = failures = 0
    for step in steps:
        if not isinstance(step, dict):
            continue
        execution, verification = step.get("execution") or {}, step.get("verification")
        executed += int(isinstance(execution, dict) and execution.get("executed") is True)
        if isinstance(verification, dict):
            verified += int(verification.get("ok") is True)
            failures += int(verification.get("ok") is False)
    reason = payload.get("stop_reason", "暂无结构化结果") if isinstance(payload, dict) else "暂无结构化结果"
    successful_stops = {"TARGET_SKILL_VERIFIED", "target_skill_verified", "MAX_ACTIONS_REACHED", "max_actions_reached", "no_idle_march", "reserved_march_for_stamina", "mail_all_clear", "exploration_income_not_ready", "daily_state_unknown_or_not_actionable", "daily_no_claimable_rewards", "alliance_action_not_needed", "training_queue_busy"}
    return {"steps": len(steps), "executed": executed, "verified": verified, "failures": failures,
            "reason": reason, "ok": exit_code == 0 and failures == 0 and reason in successful_stops}


def human_reason(value: Any) -> str:
    if value is None or value == "":
        return "暂无数据"
    text = str(value)
    return REASON_ZH.get(text, text.replace("_", " "))


LIVE_PANEL_TASKS = frozenset({"采集", "野怪", "Intel", "邮件", "探险", "日常", "联盟", "训练"})


def event_goal_is_current(item: dict[str, Any], now: datetime | None = None) -> bool:
    """Only label a saved event result as today's fact when it was updated today."""
    stamp = item.get("updated_at") if isinstance(item, dict) else None
    if not isinstance(stamp, str):
        return False
    try:
        updated = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    current = now or datetime.now().astimezone()
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=current.tzinfo)
    return updated.astimezone(current.tzinfo).date() == current.date()
GATHER_RUNTIME_PAGES = frozenset({
    Page.HOME,
    Page.MAP,
    Page.RESOURCE_DETAIL,
    Page.BEAST,
    Page.MARCH,
    Page.POPUP,
})


def bootstrap_recovery_action(world: WorldState, unknown_streak: int) -> str:
    """Choose a bounded, non-guessing recovery before the Gather live loop.

    A first UNKNOWN frame is commonly a launch/transition frame, so observe it
    once more without touching the client. Known pages outside the Gather
    route, and persistent UNKNOWN frames, may be backed out safely.
    """
    if world.page in GATHER_RUNTIME_PAGES:
        return "READY"
    if not world.known and unknown_streak <= 1:
        return "WAIT"
    return "BACK"


def task_toggle_label(name: str, enabled: bool, available: bool = True) -> str:
    """Unambiguous user-facing task state; never use a cross for enabled."""
    if not available:
        return f"◇ {name} · 待接入"
    return f"✓ {name} · 已启用" if enabled else f"○ {name} · 未启用"


def load_task_selection(path: Path, names: tuple[str, ...]) -> dict[str, bool]:
    defaults = {name: name == "采集" for name in names}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults
    saved = payload.get("task_enabled", {}) if isinstance(payload, dict) else {}
    if not isinstance(saved, dict):
        return defaults
    return {
        name: bool(saved.get(name, defaults[name])) if name in LIVE_PANEL_TASKS else False
        for name in names
    }


def load_continuous_selection(path: Path) -> bool:
    """AUTO_EXECUTION defaults to unattended repeat unless explicitly disabled."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    return bool(payload.get("continuous", True)) if isinstance(payload, dict) else True


def save_task_selection(path: Path, values: dict[str, bool], continuous: bool | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if continuous is None:
        continuous = load_continuous_selection(path)
    payload = {
        "schema_version": "1.1",
        "task_enabled": {
            name: bool(enabled) for name, enabled in values.items() if name in LIVE_PANEL_TASKS
        },
        "continuous": bool(continuous),
        "updated_at": datetime.now().astimezone().isoformat(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def count_knowledge() -> dict[str, int]:
    def records(path: Path) -> int:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return 0
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict):
            for key in ("entries", "items", "records", "semantics", "templates", "icons", "samples"):
                if isinstance(data.get(key), list):
                    return len(data[key])
            return len(data)
        return 0
    return {
        "游戏知识": sum(records(p) for p in (ROOT / "knowledge/game").glob("*.json")),
        "UI 语义": records(ROOT / "knowledge/ui/semantic_dictionary.json"),
        "Template": records(ROOT / "dataset/candidate/template_manifest.json"),
        "Icon": records(ROOT / "knowledge/ui/icons/manifest.json"),
        "Replay": records(ROOT / "tests/replay/labels.json"),
    }


# ------------------------------------------------------- architecture status layer
#
# The four layers this panel displays, frozen by the operator on 2026-09-17:
#
#     MAA        = eyes + hands          (UI perception and execution)
#     V2         = gameplay brain        (state, goals, scheduling, verification)
#     WorkBuddy  = development platform  (turns a capability gap into a capability)
#     models     = replaceable compute   (inside WorkBuddy -- never a V2 component)
#
# Everything in this section is a *derivation* from files that already exist: the
# capability catalog, the skill registry, the episode log, the executor backend
# ledger, the runtime snapshot and the escalation ledger.  Nothing here owns
# state, so the window cannot become a second source of truth -- if a number here
# is wrong, the file it came from is where to fix it.  That is why there is no
# new Manager, Registry or Scheduler behind any of it.

# Two different kinds of "we don't know", deliberately spelled differently.  The
# panel used to print "未知 / 待识别" for both, which reads as if V2 had looked and
# failed -- nine times out of ten it had simply never looked.  The operator's
# wording: only a genuine unknown may say 未知.
PENDING = "未读取"
NO_DATA = "暂无数据"
UNKNOWN_NOW = "未知（识别中）"
# A stop reason the panel cannot classify while nothing is running.  Distinct from
# UNKNOWN_NOW because nothing is being recognised at that moment -- the honest
# reading is that the reason itself is unclassified, not that a look is in flight.
UNKNOWN_STOP = "未知（原因未分类）"

CATALOG_PATH = ROOT / "knowledge/game/capability_catalog.json"
EPISODES_PATH = ROOT / "learning/episodes.jsonl"
BACKEND_LEDGER_PATH = ROOT / "learning/executor_backend.jsonl"
MODEL_STATS_PATH = ROOT / "learning/workbuddy_model_stats.jsonl"

MAA_NORMAL, MAA_ADB_FALLBACK, MAA_BROKEN = "● 正常", "● 降级ADB", "● 异常"
WORKBUDDY_LABELS = {
    "IDLE": "● 待命", "QUEUED": "● 排队", "WORKING": "● 开发中",
    "VERIFYING": "● 验证中", "BLOCKED": "● Blocked", "UNAVAILABLE": "● 不可用",
}

# Stop reasons that mean "come back later", not "something is broken".  A runtime
# sitting on one of these is *waiting*, which is a real state the operator asked
# to see by name instead of a blanket unknown.
RUNTIME_WAITING_STOPS = frozenset({
    "no_idle_march", "reserved_march_for_stamina", "training_queue_busy", "research_queue_busy",
    "NOT_REFRESHED", "EVENT_CLOSED", "QUEUE_BUSY", "RALLY_FULL", "DEVICE_BUSY",
    "DEVICE_TEMPORARILY_BUSY", "mail_all_clear", "exploration_income_not_ready",
    "daily_no_claimable_rewards", "alliance_action_not_needed", "intel_not_available",
    "verified_beast_target_not_visible", "WAITING_FOR_NATURAL_STATE",
})

CATALOG_META = {
    "observed": ("已读取特性", "capability_catalog.json · 角色可用性或真机尝试已读到"),
    "implemented": ("已实现", "capability_catalog.json · implementation_status=EXISTING"),
    "tried": ("Live Tried", "capability_catalog.json · live_attempts>0"),
    "verified": ("Live Verified", "capability_catalog.json · lifecycle=LIVE_VERIFIED"),
    "stable": ("Stable", "Skill Registry · SkillState.STABLE"),
    "never": ("从未尝试", "capability_catalog.json · MISSING 且 0 次真机"),
    "blocked": ("Blocked", "capability_catalog.json · 带 blocked_reason"),
    "queue": ("WorkBuddy Queue", "workbuddy_escalations.jsonl · 活跃 / 累计"),
}

_CACHE_LOCK = threading.Lock()
_CATALOG_CACHE: tuple[float, dict[str, Any]] | None = None
# Keyed by (mtime, scan dict): one entry holds the per-skill tally, the durations,
# the timestamped outcomes and the failure histogram from a single pass.
_EPISODE_CACHE: tuple[float, dict[str, Any]] | None = None

# The five conditions that may summon a development agent, in Chinese.  They come
# from winter_agent_v2.escalation_queue.AUTO_ESCALATION_CONDITIONS -- the panel
# only translates them, so it cannot drift from what the queue actually accepts.
CONDITION_ZH = {
    "CAPABILITY_MISSING": "能力缺失",
    "UNKNOWN_UI": "未识别界面",
    "UNKNOWN_GAME_MECHANIC": "未知玩法机制",
    "REPEATED_LIVE_FAILURE": "真机反复失败",
    "STUCK_15_MIN": "15 分钟未解决",
    "（不升级）": "不升级（普通状态）",
}

STATE_ZH = {
    "NEW": "新建", "QUEUED": "排队", "SUBMITTED": "已提交", "WORKING": "开发中",
    "DONE": "完成", "FAILED": "失败", "BLOCKED": "Blocked", "COOLDOWN": "冷却",
}


def tail_jsonl(path: Path, limit: int = 60, *, max_bytes: int = 96_000) -> list[dict[str, Any]]:
    """The last ``limit`` JSON objects of a JSONL file, without reading all of it.

    ``learning/executor_backend.jsonl`` is a few hundred KB and growing, and the
    panel polls every 1.5 s, so reading the whole file each time would be pure
    waste.  A partial first line (from seeking into the middle of a record) is
    dropped rather than parsed.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return []
    offset = max(0, size - max_bytes)
    try:
        with path.open("rb") as handle:
            if offset:
                handle.seek(offset)
            blob = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = blob.splitlines()
    if offset and lines:
        lines = lines[1:]
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            out.append(parsed)
    return out


def capability_catalog(root: Path | None = None) -> dict[str, Any]:
    """The capability coverage table, cached until the file changes.

    Read-only and mtime-keyed: the file is regenerated by tooling, and the panel
    must show the new numbers the moment it is.
    """
    global _CATALOG_CACHE
    path = (root / "knowledge/game/capability_catalog.json") if root else CATALOG_PATH
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return {"capabilities": [], "summary": {}}
    with _CACHE_LOCK:
        if _CATALOG_CACHE is not None and _CATALOG_CACHE[0] == stamp:
            return _CATALOG_CACHE[1]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"capabilities": [], "summary": {}}
    if not isinstance(payload, dict):
        payload = {"capabilities": [], "summary": {}}
    with _CACHE_LOCK:
        _CATALOG_CACHE = (stamp, payload)
    return payload


def episode_scan(root: Path | None = None) -> dict[str, Any]:
    """One cached pass over the episode log, with everything the panel needs from it.

    ``episodes.jsonl`` is 3.3 MB and the runtime appends to it while AUTO runs, so a
    caller that reads it directly pays a full parse on every refresh -- which is what
    the capability page used to do every 1.5 s.  Parsed once per change instead, and
    the per-skill tally, the durations and the timestamped outcomes all come from the
    same pass so they cannot disagree with each other.

    The split between live rows and imported ones is the catalog's own evidence
    policy: only rows carrying ``recorded_at`` count.
    """
    global _EPISODE_CACHE
    path = (root / "learning/episodes.jsonl") if root else EPISODES_PATH
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return {"index": {}, "durations": [], "results": []}
    with _CACHE_LOCK:
        if _EPISODE_CACHE is not None and _EPISODE_CACHE[0] == stamp:
            return _EPISODE_CACHE[1]
    scan: dict[str, Any] = {"index": {}, "durations": [], "results": [], "failures": Counter()}
    index: dict[str, dict[str, Any]] = scan["index"]
    failures: Counter = scan["failures"]
    for line in _iter_jsonl(path):
        skill = str(line.get("skill") or "")
        if skill:
            entry = index.setdefault(skill, {"live": 0, "claims": 0, "verified": 0, "failed": 0, "last": ""})
            if line.get("recorded_at"):
                entry["live"] += 1
                entry["verified"] += int(line.get("verifier_ok") is True)
                entry["failed"] += int(line.get("verifier_ok") is False)
                entry["last"] = str(line.get("recorded_at"))[:19]
            else:
                entry["claims"] += 1
        if isinstance(line.get("duration"), (int, float)):
            scan["durations"].append(float(line["duration"]))
        if line.get("recorded_at"):
            scan["results"].append((str(line["recorded_at"]), line.get("result") == "SUCCESS"))
            if line.get("failure_type"):
                failures[str(line["failure_type"])] += 1
    with _CACHE_LOCK:
        _EPISODE_CACHE = (stamp, scan)
    return scan


def episode_index(root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Per-skill tally from :func:`episode_scan`."""
    return episode_scan(root)["index"]


def _iter_jsonl(path: Path):
    """Yield each JSON object of a JSONL file, skipping anything unparseable."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            yield row


def live_failure_counts(root: Path | None = None) -> Counter:
    """How often each failure type appeared on a row that carries ``recorded_at``.

    Part of the same cached pass as the per-skill tally, so the panel parses the
    episode log once per change rather than once per question.
    """
    return episode_scan(root)["failures"]


def escalation_buckets(root: Path | None = None) -> dict[str, dict[str, int]]:
    """Distinct failure types and live occurrences per escalation condition.

    Runs ``classify_condition`` -- the same function the AUTO hook calls -- rather
    than re-implementing the rule here.  A panel that decided for itself which
    failures deserve a development agent would be exactly the second state system
    the operator forbids.
    """
    from winter_agent_v2.escalation_queue import (
        CAPABILITY_MISSING, EscalationPolicy, FailureSignature, classify_condition,
    )

    buckets: dict[str, dict[str, int]] = {}
    policy = EscalationPolicy()
    now = datetime.now(timezone.utc)
    for key in (*AUTO_ESCALATION_CONDITIONS, CAPABILITY_MISSING, "（不升级）"):
        buckets[key] = {"types": 0, "episodes": 0}
    for failure_type, occurrences in live_failure_counts(root).items():
        signature = FailureSignature(capability="", failure_type=failure_type, skill="")
        verdict = classify_condition(signature, occurrences=occurrences, first_seen=None, now=now, policy=policy)
        condition = verdict[0] if verdict else "（不升级）"
        entry = buckets.setdefault(condition, {"types": 0, "episodes": 0})
        entry["types"] += 1
        entry["episodes"] += occurrences
    return buckets


def capability_gap_view(root: Path | None = None) -> dict[str, Any]:
    """Goal-level gaps, read from the project's own capability -> skill map.

    This is the second capability table and it is *not* merged with the 522-row
    coverage catalog on purpose: the catalog counts what the game contains, this
    one tracks the 16 goals and which capability blocks each.  Two questions, two
    files, and the panel labels which one it is answering.
    """
    base = Path(root) if root else ROOT
    try:
        payload = json.loads((base / "knowledge/goals/capability_skill_map.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"summary": {}, "goals": (), "highest_leverage": (), "readable": False}
    goals: list[tuple[str, str, int, str]] = []
    for goal in payload.get("goals") or []:
        blocked = [str(c.get("capability")) for c in (goal.get("capabilities") or [])
                   if str(c.get("status") or "").upper() in ("BLOCKED", "DEGRADED")]
        goals.append((str(goal.get("goal")), str(goal.get("status")), len(blocked), "、".join(blocked[:3])))
    return {
        "summary": payload.get("summary") or {},
        "goals": tuple(goals),
        "highest_leverage": tuple(payload.get("highest_leverage") or ()),
        "readable": True,
    }


def backend_axis(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Which of MAA / ADB actually executed the recent steps, and whether that is a fallback.

    The distinction that matters and that a bare backend name hides: several
    skills are *deliberately* still on ADB (they are not migrated yet, and
    ``backend_routing.json`` says so), while a step whose ``preferred_backend``
    was MAA but whose ``used_backend`` is ADB is a real degradation.
    """
    last = rows[-1] if rows else {}
    used = str(last.get("used_backend") or "").upper()
    capture = str(last.get("capture_backend") or "")
    preferred = str(last.get("preferred_backend") or "").upper()
    latency = last.get("latency_ms")
    suffix = f" · {latency:.0f}ms" if isinstance(latency, (int, float)) else ""
    if not last:
        label = PENDING
    elif used == "MAA":
        label = f"MAA · {capture}{suffix}"
    elif preferred == "MAA":
        label = f"ADB 降级 · {capture}{suffix}"
    else:
        label = f"ADB · {capture}（该技能未迁移 MAA）{suffix}"
    mix = Counter(str(row.get("used_backend") or "?") for row in rows)
    return {
        "label": label, "used": used, "capture": capture, "preferred": preferred,
        "latency_ms": latency, "recorded_at": str(last.get("recorded_at") or ""),
        "degraded": bool(used and used == "ADB" and preferred == "MAA")
        or any(row.get("fallback_used") for row in rows),
        "errors": sum(1 for row in rows if row.get("error")),
        "mix": f"MAA {mix.get('MAA', 0)} / ADB {mix.get('ADB', 0)}（近 {len(rows)} 步）",
        "steps": len(rows),
    }


def maa_cell(report: runtime_env.InterpreterReport, axis: dict[str, Any]) -> str:
    """MAA's health as one of the operator's three words.

    降级ADB is the honest label for the defect that was live on 2026-09-17: the
    production interpreter cannot import ``maa``, so MAA is nominally the default
    and actually absent.  It is not 异常 -- ADB still works -- and calling it 正常
    is exactly the silent degradation the doctrine forbids.
    """
    if not getattr(report, "exists", False):
        return MAA_BROKEN
    missing = tuple(getattr(report, "missing", ()) or ())
    if "maa" in missing or axis.get("degraded"):
        return MAA_ADB_FALLBACK
    if missing:
        return MAA_BROKEN
    return MAA_NORMAL


def _records_sorted(snapshot: Any) -> list[Any]:
    records = list(getattr(snapshot, "records", {}).values())
    return sorted(records, key=lambda r: (r.last_seen or r.first_seen or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)


def escalation_view(root: Path | None = None) -> dict[str, Any]:
    """The development escalation queue, folded from its own ledger.

    Uses ``winter_agent_v2.escalation_queue.fold`` rather than re-deriving states
    here: the queue already knows what SUBMITTED means, and a panel that
    recomputed it would be the second source of truth the operator forbids.
    """
    from winter_agent_v2.escalation_queue import (
        BLOCKED, CODE_CHANGED, COOLDOWN, DONE, FAILED, LIVE_VERIFIED, NEW,
        OUTCOME_BLOCKED, QUEUED, REPLAY_PASS, SUBMITTED, TEST_PASS, WORKING,
        EscalationPolicy,
    )

    path = (root / DEFAULT_LEDGER) if root else _ESCALATION_LEDGER_PATH
    try:
        snapshot = EscalationLedger(path).snapshot()
    except Exception:  # noqa: BLE001 - an unreadable ledger shows as empty, never crashes the window
        return {"total": 0, "records": (), "current": None, "counts": {}, "conditions": Counter(),
                "pending_verify": (), "blocked": (), "verified": (), "max_concurrent": 1, "readable": False}
    records = _records_sorted(snapshot)
    active = [r for r in records if r.state in (NEW, QUEUED, SUBMITTED, WORKING)]
    pending_verify = [r for r in records if r.state == DONE and r.outcome in (CODE_CHANGED, TEST_PASS, REPLAY_PASS)]
    blocked = [r for r in records if r.state in (BLOCKED, FAILED, COOLDOWN) or r.outcome == OUTCOME_BLOCKED]
    conditions: Counter[str] = Counter()
    for record in records:
        for condition in [record.condition] if record.condition else []:
            conditions[condition] += 1
    return {
        "total": len(records), "records": tuple(records), "current": active[0] if active else None,
        "active": tuple(active), "counts": snapshot.count_by_state(), "conditions": conditions,
        "pending_verify": tuple(pending_verify), "blocked": tuple(blocked),
        "verified": tuple(r for r in records if r.outcome == LIVE_VERIFIED),
        "max_concurrent": EscalationPolicy().max_concurrent_jobs, "readable": True,
    }


def workbuddy_cell(view: dict[str, Any], gateway: dict[str, Any]) -> tuple[str, str]:
    """``(状态, 说明)`` for the header cell -- WorkBuddy's own state, never a model name.

    Order matters.  A job that is running outranks one waiting for its live
    verification, which outranks a blocked one, which outranks idle.
    """
    from winter_agent_v2.escalation_queue import NEW, QUEUED, SUBMITTED, WORKING

    if gateway.get("available") is False:
        return WORKBUDDY_LABELS["UNAVAILABLE"], str(gateway.get("reason") or "")
    current = view.get("current")
    if current is not None:
        if current.state in (SUBMITTED, WORKING):
            return WORKBUDDY_LABELS["WORKING"], current.job_id or current.key
        if current.state in (NEW, QUEUED):
            return WORKBUDDY_LABELS["QUEUED"], current.key
    if view.get("pending_verify"):
        return WORKBUDDY_LABELS["VERIFYING"], view["pending_verify"][0].key
    if view.get("blocked"):
        return WORKBUDDY_LABELS["BLOCKED"], view["blocked"][0].key
    return WORKBUDDY_LABELS["IDLE"], ""


GATEWAY_REASON_ZH = {
    "NO_CREDENTIAL": "未配置凭据（需在环境变量里设置网关密码，禁止写入仓库）",
    "AUTH_REJECTED": "凭据被拒绝（环境里的密码与正在运行的网关不一致）",
    "GATEWAY_UNREACHABLE": "网关不可达（未启动或端口不同）",
}


def gateway_reason_cn(reason: str) -> str:
    """The escalation gateway's answer, in Chinese.

    Worth translating rather than passing through: NO_CREDENTIAL and
    AUTH_REJECTED look equally like "unavailable" but need different fixes, and
    the 2026-09-17 session found the environment holding a stale password while a
    different one was actually serving -- exactly the case the second string names.
    """
    text = str(reason or "")
    if text in GATEWAY_REASON_ZH:
        return GATEWAY_REASON_ZH[text]
    if text.startswith("HTTP_"):
        return f"网关返回 HTTP {text[5:]}"
    if text.startswith("UNHEALTHY"):
        return f"网关健康检查未通过：{text.split(':', 1)[-1]}"
    return text or "原因未提供"


def duration_label(record: Any, now: datetime | None = None) -> str:
    """How long the job has been running (or ran), in the operator's units."""
    started = getattr(record, "submitted_at", None) or getattr(record, "first_seen", None)
    if started is None:
        return NO_DATA
    ended = getattr(record, "settled_at", None)
    moment = now or datetime.now(timezone.utc)
    seconds = ((ended or moment) - started).total_seconds()
    if seconds < 0:
        return NO_DATA
    if seconds < 60:
        return f"{seconds:.0f} 秒"
    if seconds < 3600:
        return f"{seconds / 60:.0f} 分钟"
    return f"{seconds / 3600:.1f} 小时"


def capability_lifecycle_cn(entry: dict[str, Any], *, skill_state: str = "") -> str:
    """Coverage lifecycle in plain Chinese, from the catalog's own field."""
    if entry.get("blocked_reason"):
        return "Blocked"
    lifecycle = str(entry.get("lifecycle") or "").upper()
    if lifecycle == "LIVE_VERIFIED":
        return "Stable" if skill_state == SkillState.STABLE.value else "Live Verified"
    if lifecycle == "LIVE_TRIED":
        return "Live Tried"
    if lifecycle == "CANDIDATE":
        return "候选"
    if lifecycle == "MISSING":
        return "未实现"
    return PENDING


def capability_state_cn(
    entry: dict[str, Any],
    *,
    skill_state: str = "",
    running_skill: str = "",
    claims: int = 0,
) -> str:
    """The availability half of a capability's status.

    Every branch is a fact from an existing file.  ``claims`` is the number of
    episode rows for this capability's skill that carry no ``recorded_at`` -- the
    catalog's own evidence policy says those cannot support a verification, so
    the honest word is 待刷新 rather than 可执行.
    """
    skill = str(entry.get("existing_skill") or "")
    if str(entry.get("real_money_cost") or "").upper() == "FORBIDDEN":
        return "不可用"
    if str(entry.get("unlock_status") or "").upper() == "LOCKED":
        return "未解锁"
    if running_skill and skill and running_skill == skill:
        return "执行中"
    if entry.get("blocked_reason"):
        return "Blocked"
    if str(entry.get("lifecycle") or "").upper() in ("LIVE_VERIFIED", "LIVE_TRIED"):
        return "可执行"
    if skill and skill_state == SkillState.BLOCKED.value:
        return "Blocked"
    if claims:
        return "待刷新"
    if str(entry.get("implementation_status") or "").upper() == "EXISTING":
        return "可执行"
    if str(entry.get("current_role_available") or "").upper() == "OBSERVED_AVAILABLE":
        return "已识别"
    return PENDING


def runtime_status_cn(stop_reason: str | None, *, running: bool) -> str:
    """What the current runtime state is called in the panel.

    This is where 等待 lives: a runtime sitting on an ordinary-weather stop is
    waiting, which is different from unread and different from broken.
    """
    reason = str(stop_reason or "")
    if reason in RUNTIME_WAITING_STOPS:
        return "等待"
    if running:
        return "执行中"
    if not reason:
        return PENDING
    return UNKNOWN_STOP


def overview_kpis(root: Path | None = None, *, registry: Any = None, view: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """The eight numbers the operator asked to see first.

    Each card carries the file it came from, because a KPI nobody can trace back
    to a source is a number people learn to ignore.
    """
    catalog = capability_catalog(root)
    entries = catalog.get("capabilities") or []
    index = episode_index(root)
    view = view if view is not None else escalation_view(root)
    if registry is None:
        registry = v2_registry()
    skills = registry.all()
    stable = sum(1 for skill in registry.all() if skill.state is SkillState.STABLE)
    # The registry is the only place "Stable" is defined, and today it holds none --
    # showing a bare 0 with no context would read as a bug rather than as the state
    # of the promotion gate, so the card carries the real distribution beside it.
    state_mix = Counter(skill.state.value for skill in skills)
    stable_source = "Skill Registry · " + " / ".join(
        f"{name} {state_mix.get(name, 0)}" for name in ("STABLE", "VERIFIED", "CANDIDATE", "BLOCKED")
    )
    observed = implemented = tried = verified = never = blocked = 0
    for entry in entries:
        lifecycle = str(entry.get("lifecycle") or "").upper()
        attempts = int(entry.get("live_attempts") or 0)
        if (str(entry.get("current_role_available") or "").upper() != "UNKNOWN"
                or str(entry.get("unlock_status") or "").upper() != "UNKNOWN" or attempts):
            observed += 1
        if str(entry.get("implementation_status") or "").upper() == "EXISTING":
            implemented += 1
        if attempts:
            tried += 1
        if lifecycle == "LIVE_VERIFIED":
            verified += 1
        if lifecycle == "MISSING":
            never += 1
        if entry.get("blocked_reason"):
            blocked += 1
    active = len(view.get("active") or ())
    values = {
        "observed": str(observed), "implemented": str(implemented), "tried": str(tried),
        "verified": str(verified), "stable": str(stable), "never": str(never),
        "blocked": str(blocked), "queue": f"{active} 活跃 / {view.get('total', 0)} 累计",
    }
    return {key: {"label": CATALOG_META[key][0], "value": values[key],
                  "source": stable_source if key == "stable" else CATALOG_META[key][1]}
            for key in CATALOG_META}


def status_defaults() -> dict[str, str]:
    """Every status variable the panel owns, with its value before anything is read.

    A function rather than an inline literal because the handler tests need to
    build a stub mapping for ``ControlPanel`` without a Tk window, and a stub that
    hard-codes its own key list silently stops matching the real panel the moment
    a key is added -- which is exactly what happened when MAA and WorkBuddy
    replaced the previous provider and recognition cells in the header.  Deriving
    the stub from here makes the two impossible to desynchronise.
    """
    return {
        "agent": "● 等待", "maa": MAA_NORMAL, "device": "未探测", "game": PENDING, "page": PENDING,
        "mode": "停止", "workbuddy": WORKBUDDY_LABELS["IDLE"], "clock": "--:--:--",
        "march": "行军：暂无数据", "task_cn": "等待启动", "skill": NO_DATA,
        "reason": "尚未产生决策", "preconditions": PENDING, "next": "截图并识别当前页面",
        "backend": PENDING, "backend_detail": PENDING, "risk": PENDING,
        "confidence": NO_DATA, "runtime_state": PENDING,
        "verifier": "等待任务执行", "result": "尚未运行",
        "wb_state": WORKBUDDY_LABELS["IDLE"], "wb_capability": PENDING, "wb_reason": PENDING,
        "wb_job": PENDING, "wb_model": PENDING, "wb_duration": PENDING,
        "wb_job_state": PENDING, "wb_improvement": PENDING, "wb_result": "尚未产生开发任务",
        "wb_gateway": PENDING, "wb_queue_line": PENDING, "wb_gap": PENDING,
        "stats": "本次启动：0 轮 · 0 动作",
    }


class WorkBuddyGatewayCache:
    """Polls the WorkBuddy gateway on a daemon thread so the window never blocks.

    The panel already had to learn this lesson for subprocesses (see
    ``_background_run``): anything that can take seconds must not run inside a Tk
    callback.  The jobs API is HTTP, so it runs here and the UI only reads
    ``snapshot()``.  A gateway that is down is a *reported state*, not an
    exception, and it never blocks AUTO -- same rule as the escalation queue's.
    """

    INTERVAL_SECONDS = 10.0

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or ROOT
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {"available": None, "reason": "", "job": {}, "checked_at": ""}
        self._watch: str = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def watch(self, job_id: str) -> None:
        with self._lock:
            self._watch = job_id or ""

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="workbuddy-gateway-poll", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._poll_once()
            self._stop.wait(self.INTERVAL_SECONDS)

    def _poll_once(self) -> None:
        state: dict[str, Any] = {"available": None, "reason": "", "job": {}, "checked_at": datetime.now().strftime("%H:%M:%S")}
        try:
            from winter_agent_v2.workbuddy_bridge import WorkBuddyBridge

            bridge = WorkBuddyBridge(cwd=self.root)
            probe = bridge.is_available()
            state["available"] = bool(probe)
            state["reason"] = str(getattr(probe, "reason", "") or "")
            with self._lock:
                job_id = self._watch
            if probe and job_id:
                status = bridge.status(job_id)
                state["job"] = {
                    "job_id": status.job_id, "verdict": status.verdict, "state": status.gateway_state,
                    "settled": status.settled, "detail": status.detail, "result": status.result,
                }
        except Exception as exc:  # noqa: BLE001 - a poll must never reach the UI as an exception
            state["available"] = False
            state["reason"] = f"{type(exc).__name__}: {exc}"
        with self._lock:
            self._state = state


class ControlPanel:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Winter Agent OS V2 — 无尽冬日 AI 指挥中心")
        root.geometry("1360x820")
        root.minsize(1080, 680)
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        self.device = ADBDevice(Path(self.config["device"]["adb_path"]), self.config["device"]["serial"], production=True)
        self.registry = v2_registry()
        self.runtime_store = RuntimeSnapshotStore(RUNTIME_SNAPSHOT_PATH)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.process: subprocess.Popen[str] | None = None
        self.starting = False
        self.refreshing = False
        self.stop_requested = self.paused = False
        self.repeat_after_id: str | None = None
        self.latest_world: WorldState | None = None
        self.latest_image_path: Path | None = None
        self.preview_source: Image.Image | None = None
        self.preview_photo: ImageTk.PhotoImage | None = None
        self.session = Counter()
        self.event_lines: list[str] = []
        self.watchdog_restart_pending = False
        defaults = status_defaults()
        self.values = {k: tk.StringVar(value=v) for k, v in defaults.items()}
        self.kpi: dict[str, tk.StringVar] = {}
        # Polls the jobs API off the UI thread; every value below is read from a
        # file that already exists, so the window still owns no state of its own.
        self.gateway = WorkBuddyGatewayCache(ROOT)
        self.gateway.start()
        task_names = ("邮件", "探险", "采集", "建筑", "科技", "训练", "Intel", "联盟", "日常", "野怪", "巨熊")
        saved_tasks = load_task_selection(PANEL_STATE_PATH, task_names)
        self.task_enabled = {n: tk.BooleanVar(value=saved_tasks[n]) for n in task_names}
        self.continuous = tk.BooleanVar(value=True if self.config.get("auto_execution") else load_continuous_selection(PANEL_STATE_PATH))
        self.preview_mode = tk.StringVar(value="原始画面")
        self.resource_policy = {"普通资源": tk.StringVar(value="自动使用"), "普通加速": tk.StringVar(value="自动使用"),
                                "高级加速": tk.StringVar(value="保守"), "钻石": tk.StringVar(value="保守"),
                                "真实支付": tk.StringVar(value="禁止")}
        self.policy_enabled = {name: tk.BooleanVar(value=True) for name in (
            "日常低保", "持续发展", "联盟协作", "限时活动", "PVE", "实时活动", "资源优化", "自动学习"
        )}
        self._build()
        self._save_policy_state()
        self._save_panel_state()
        self._enforce_retention()
        root.after(100, self._drain_events)
        root.after(250, self._tick)
        root.after(1000, self._refresh_runtime_snapshot)
        self.refresh()
        if self.config.get("auto_execution") and self.continuous.get():
            root.after(1800, self.start)

    def _style(self) -> None:
        s = ttk.Style()
        if "clam" in s.theme_names():
            s.theme_use("clam")
        s.configure(".", background=BG, foreground=TEXT, fieldbackground=PANEL2, bordercolor="#263849")
        s.configure("TFrame", background=BG); s.configure("Card.TFrame", background=PANEL); s.configure("Card2.TFrame", background=PANEL2)
        s.configure("TLabel", background=BG, foreground=TEXT, font=("Microsoft YaHei UI", 9))
        s.configure("Muted.TLabel", foreground=MUTED); s.configure("Title.TLabel", font=("Microsoft YaHei UI", 20, "bold"))
        s.configure("Section.TLabel", font=("Microsoft YaHei UI", 11, "bold")); s.configure("Value.TLabel", font=("Microsoft YaHei UI", 12, "bold"))
        s.configure("Accent.TButton", font=("Microsoft YaHei UI", 10, "bold"), padding=(16, 9), background="#1876ac")
        s.configure("TaskEnabled.TButton", font=("Microsoft YaHei UI", 10, "bold"), padding=(16, 12), background="#176b50", foreground="#dcfff1")
        s.configure("TaskDisabled.TButton", font=("Microsoft YaHei UI", 10), padding=(16, 12), background=PANEL2, foreground=MUTED)
        s.configure("TaskUnavailable.TButton", font=("Microsoft YaHei UI", 10), padding=(16, 12), background="#101923", foreground="#607181")
        s.map("TaskEnabled.TButton", background=[("active", "#1d8563")])
        s.map("TaskDisabled.TButton", background=[("active", "#263849")])
        s.configure("TButton", padding=(11, 8), background=PANEL2); s.configure("TNotebook", background=BG, borderwidth=0)
        s.configure("TNotebook.Tab", padding=(16, 9), background=PANEL, foreground=MUTED)
        s.map("TNotebook.Tab", background=[("selected", PANEL2)], foreground=[("selected", TEXT)])
        s.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=27)
        s.configure("Treeview.Heading", background=PANEL2, foreground=TEXT); s.configure("TCheckbutton", background=PANEL)

    def _build(self) -> None:
        self._style()
        shell = ttk.Frame(self.root, padding=(16, 12)); shell.pack(fill="both", expand=True)
        header = ttk.Frame(shell, style="Card.TFrame", padding=(16, 12)); header.pack(fill="x")
        title = ttk.Frame(header, style="Card.TFrame"); title.pack(side="left")
        ttk.Label(title, text="Winter Agent OS V2", style="Title.TLabel", background=PANEL).pack(anchor="w")
        ttk.Label(title, text="《无尽冬日》AI 指挥中心", style="Muted.TLabel", background=PANEL).pack(anchor="w")
        status = ttk.Frame(header, style="Card.TFrame"); status.pack(side="right", expand=True, fill="x", padx=(26, 0))
        # The four frozen layers, in order, and nothing else.  Qwen and Vision used
        # to sit here as first-class components; they are not layers of this
        # architecture (Qwen is an optional offline provider, recognition is MAA's
        # job), so a model or provider name in this row would misstate the design.
        # A model name appears only as WorkBuddy's second-level detail.
        for i, (label, key) in enumerate((("V2大脑", "agent"), ("MAA", "maa"), ("MuMu", "device"), ("游戏", "game"),
                                          ("页面", "page"), ("AUTO", "mode"), ("WorkBuddy", "workbuddy"), ("时间", "clock"))):
            cell = ttk.Frame(status, style="Card.TFrame"); cell.grid(row=0, column=i, padx=7, sticky="w")
            ttk.Label(cell, text=label, style="Muted.TLabel", background=PANEL).pack(anchor="w")
            ttk.Label(cell, textvariable=self.values[key], background=PANEL).pack(anchor="w")
        self.tabs = ttk.Notebook(shell); self.tabs.pack(fill="both", expand=True, pady=(10, 0))
        self._overview(); self._goals(); self._strategy(); self._event_goal(); self._capabilities(); self._auto_development(); self._system()

    def _tab(self, name: str, scroll: bool = False) -> ttk.Frame:
        f = ttk.Frame(self.tabs, padding=10); self.tabs.add(f, text=name)
        return self._scroll_area(f) if scroll else f

    def _scroll_area(self, parent: ttk.Frame) -> ttk.Frame:
        """Wrap tall tab content in a scrollbar.

        Measured rather than guessed: with the 2026-09-17 information architecture
        the 总览 tab requested 1282 px of height, 自动开发 1101 and 能力 912, while the
        window hands the notebook about 660.  Tk does not scroll a notebook tab, so
        everything below the fold -- including the run controls -- was simply
        clipped and unreachable.  This is the standard canvas-plus-inner-frame pair,
        not a second layout system: the frame the tab returns is the same frame it
        would have returned before, so every existing `pack`/`grid` call inside is
        unchanged.

        The wheel binding is scoped to pointer enter/leave so it cannot capture
        scrolling from the treeviews, which scroll themselves.
        """
        canvas = tk.Canvas(parent, bg=BG, highlightthickness=0, borderwidth=0)
        bar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas, padding=10)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y"); canvas.pack(side="left", fill="both", expand=True)
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))

        def on_wheel(event: tk.Event) -> None:
            canvas.yview_scroll(-int(event.delta / 120), "units")

        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", on_wheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))
        return inner

    def _overview(self) -> None:
        tab = self._tab("总览", scroll=True); tab.rowconfigure(0, weight=1); tab.columnconfigure(1, weight=1)
        left = ttk.Frame(tab, style="Card.TFrame", padding=14, width=215); left.grid(row=0, column=0, sticky="nsew", padx=(0, 8)); left.grid_propagate(False)
        center = ttk.Frame(tab, style="Card.TFrame", padding=10); center.grid(row=0, column=1, sticky="nsew")
        right = ttk.Frame(tab, style="Card.TFrame", padding=14, width=270); right.grid(row=0, column=2, sticky="nsew", padx=(8, 0)); right.grid_propagate(False)
        ttk.Label(left, text="当前角色", style="Section.TLabel", background=PANEL).pack(anchor="w")
        ttk.Label(left, text="xhw", style="Value.TLabel", background=PANEL).pack(anchor="w", pady=(10, 0))
        ttk.Label(left, text="● 在线", foreground=GOOD, background=PANEL).pack(anchor="w")
        ttk.Label(left, textvariable=self.values["march"], style="Muted.TLabel", background=PANEL).pack(anchor="w", pady=(3, 16))
        ttk.Separator(left).pack(fill="x", pady=(0, 12)); ttk.Label(left, text="今日 Goal 摘要", style="Section.TLabel", background=PANEL).pack(anchor="w", pady=(0, 8))
        self.today: dict[str, tk.StringVar] = {}
        for task in ("活动低保", "情报", "体力", "训练", "科研", "建筑", "奖励"):
            row = ttk.Frame(left, style="Card.TFrame"); row.pack(fill="x", pady=3)
            ttk.Label(row, text=task, background=PANEL).pack(side="left")
            self.today[task] = tk.StringVar(value=PENDING)
            ttk.Label(row, textvariable=self.today[task], style="Muted.TLabel", background=PANEL).pack(side="right")
        bar = ttk.Frame(center, style="Card.TFrame"); bar.pack(fill="x", pady=(0, 8))
        ttk.Label(bar, text="游戏实时画面", style="Section.TLabel", background=PANEL).pack(side="left")
        choice = ttk.Combobox(bar, textvariable=self.preview_mode, values=("原始画面", "Vision", "OCR", "识别结果"), width=12, state="readonly")
        choice.pack(side="right"); choice.bind("<<ComboboxSelected>>", lambda _e: self._render_preview())
        # Fixed-height holder: inside a scroll area the preview has no leftover space
        # to expand into, so without a declared height it would render at whatever
        # the last label measured and jump when the first screenshot arrived.
        holder = tk.Frame(center, bg="#070b10", height=300)
        holder.pack(fill="both", expand=True); holder.pack_propagate(False)
        self.preview = tk.Label(holder, text="正在获取 MuMu 截图…", bg="#070b10", fg=MUTED, font=("Microsoft YaHei UI", 11))
        self.preview.pack(fill="both", expand=True); self.preview.bind("<Configure>", lambda _e: self._render_preview())
        self.preview_meta = tk.StringVar(value=NO_DATA)
        ttk.Label(center, textvariable=self.preview_meta, style="Muted.TLabel", background=PANEL).pack(anchor="w", pady=(8, 0))
        ttk.Label(right, text="当前决策", style="Section.TLabel", background=PANEL).pack(anchor="w")
        # V2 decides, MAA executes.  The backend is the first thing in this column
        # because "which hands moved" is the fact that makes every other line here
        # trustworthy or not: a measurement taken through the ADB fallback is not
        # the same measurement as one taken through MAA.
        ttk.Label(right, text="执行后端", style="Muted.TLabel", background=PANEL).pack(anchor="w", pady=(10, 1))
        ttk.Label(right, textvariable=self.values["backend"], style="Value.TLabel", background=PANEL, wraplength=235, justify="left").pack(anchor="w")
        ttk.Label(right, textvariable=self.values["backend_detail"], style="Muted.TLabel", background=PANEL, wraplength=235, justify="left").pack(anchor="w")
        ttk.Label(right, text="V2 决定做什么 · MAA 负责执行 · Verifier 判定成功", style="Muted.TLabel", background=PANEL, wraplength=235, justify="left").pack(anchor="w", pady=(2, 0))
        for label, key, style in (("当前 Goal", "task_cn", "Value.TLabel"), ("当前 Universal Skill", "skill", "Muted.TLabel"),
                                  ("当前状态", "runtime_state", "Value.TLabel"), ("为什么执行", "reason", "TLabel"),
                                  ("Preconditions", "preconditions", "TLabel"), ("Verifier", "verifier", "TLabel"),
                                  ("下一步", "next", "TLabel"), ("风险", "risk", "TLabel"),
                                  ("置信度", "confidence", "Value.TLabel")):
            ttk.Label(right, text=label, style="Muted.TLabel", background=PANEL).pack(anchor="w", pady=(10, 1))
            ttk.Label(right, textvariable=self.values[key], style=style, background=PANEL, wraplength=235, justify="left").pack(anchor="w")
        ttk.Label(right, textvariable=self.values["stats"], style="Muted.TLabel", background=PANEL, wraplength=235).pack(anchor="w", side="bottom")
        # Row 1: coverage and verification progress, first thing the eye lands on.
        kpis = ttk.Frame(tab, style="Card.TFrame", padding=10); kpis.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        self.kpi_source: dict[str, tk.StringVar] = {}
        for i, (key, meta) in enumerate(CATALOG_META.items()):
            card = ttk.Frame(kpis, style="Card2.TFrame", padding=(12, 7)); card.grid(row=0, column=i, sticky="ew", padx=4); kpis.columnconfigure(i, weight=1)
            ttk.Label(card, text=meta[0], style="Muted.TLabel", background=PANEL2).pack(anchor="w")
            self.kpi[key] = tk.StringVar(value=NO_DATA)
            ttk.Label(card, textvariable=self.kpi[key], style="Value.TLabel", background=PANEL2).pack(anchor="w")
            self.kpi_source[key] = tk.StringVar(value=meta[1])
            ttk.Label(card, textvariable=self.kpi_source[key], style="Muted.TLabel", background=PANEL2, wraplength=140, justify="left", font=("Microsoft YaHei UI", 7)).pack(anchor="w")
        # Row 2: what the development platform is doing right now.
        wb = ttk.Frame(tab, style="Card.TFrame", padding=(12, 10)); wb.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        head = ttk.Frame(wb, style="Card.TFrame"); head.pack(fill="x")
        ttk.Label(head, text="WorkBuddy 自动开发", style="Section.TLabel", background=PANEL).pack(side="left")
        ttk.Label(head, textvariable=self.values["wb_gateway"], style="Muted.TLabel", background=PANEL).pack(side="right")
        grid = ttk.Frame(wb, style="Card.TFrame"); grid.pack(fill="x", pady=(6, 0))
        for index, (label, key) in enumerate((("状态", "wb_state"), ("当前 Capability", "wb_capability"),
                                              ("Escalation Reason", "wb_reason"), ("Job ID", "wb_job"),
                                              ("当前模型", "wb_model"), ("运行时间", "wb_duration"),
                                              ("Job 状态", "wb_job_state"), ("Live Improvement", "wb_improvement"))):
            cell = ttk.Frame(grid, style="Card.TFrame"); cell.grid(row=index // 4, column=index % 4, sticky="w", padx=(0, 22), pady=2)
            ttk.Label(cell, text=label, style="Muted.TLabel", background=PANEL).pack(anchor="w")
            ttk.Label(cell, textvariable=self.values[key], background=PANEL, wraplength=190, justify="left").pack(anchor="w")
            grid.columnconfigure(index % 4, weight=1)
        result = ttk.Frame(grid, style="Card.TFrame"); result.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        ttk.Label(result, text="最近结果", style="Muted.TLabel", background=PANEL).pack(anchor="w")
        ttk.Label(result, textvariable=self.values["wb_result"], background=PANEL, wraplength=1150, justify="left").pack(anchor="w")
        cards = ttk.Frame(tab, style="Card.TFrame", padding=10); cards.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        self.queues: dict[str, tk.StringVar] = {}
        for i, name in enumerate(("行军", "建筑", "科技", "训练", "Intel", "联盟", "活动")):
            card = ttk.Frame(cards, style="Card2.TFrame", padding=(14, 8)); card.grid(row=0, column=i, sticky="ew", padx=4); cards.columnconfigure(i, weight=1)
            ttk.Label(card, text=name, style="Muted.TLabel", background=PANEL2).pack(anchor="w")
            self.queues[name] = tk.StringVar(value=PENDING); ttk.Label(card, textvariable=self.queues[name], style="Value.TLabel", background=PANEL2).pack(anchor="w")
        bottom = ttk.Frame(tab, style="Card.TFrame", padding=10); bottom.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        controls = ttk.Frame(bottom, style="Card.TFrame"); controls.pack(side="left")
        self.start_button = ttk.Button(controls, text="开始自动运行", style="Accent.TButton", command=self.start); self.start_button.pack(side="left", padx=(0, 4))
        self.pause_button = ttk.Button(controls, text="暂停", command=self.pause, state="disabled"); self.pause_button.pack(side="left", padx=3)
        self.stop_button = ttk.Button(controls, text="停止", command=self.stop, state="disabled"); self.stop_button.pack(side="left", padx=3)
        ttk.Button(controls, text="刷新状态", command=self.refresh).pack(side="left", padx=3)
        ttk.Button(controls, text="截图", command=self.take_screenshot).pack(side="left", padx=3)
        event = ttk.Frame(bottom, style="Card.TFrame"); event.pack(side="left", fill="both", expand=True, padx=(18, 0))
        ttk.Label(event, text="最近事件", style="Muted.TLabel", background=PANEL).pack(anchor="w")
        self.event_text = tk.StringVar(value="控制台已启动，等待真实状态。")
        ttk.Label(event, textvariable=self.event_text, background=PANEL, wraplength=640).pack(anchor="w")

    def _tasks(self) -> None:
        tab = self._tab("任务"); ttk.Label(tab, text="任务设置", style="Title.TLabel").pack(anchor="w", pady=(5, 4))
        ttk.Label(tab, text="绿色 ✓ 已启用＝允许自动执行；灰色 ○ 未启用＝不会执行；◇ 待接入＝尚不能从控制台启动。", style="Muted.TLabel").pack(anchor="w", pady=(0, 16))
        grid = ttk.Frame(tab, style="Card.TFrame", padding=18); grid.pack(fill="x")
        self.task_buttons: dict[str, ttk.Button] = {}
        for i, (name, var) in enumerate(self.task_enabled.items()):
            button = ttk.Button(grid, command=lambda task=name: self._toggle_task(task), width=22)
            button.grid(row=i // 3, column=i % 3, sticky="ew", padx=12, pady=8)
            grid.columnconfigure(i % 3, weight=1)
            self.task_buttons[name] = button
        self._sync_tasks()
        ttk.Label(tab, text="已接入实机主循环：邮件、每日奖励、联盟赠礼、训练、探险收益、Intel、野怪、资源采集。其余能力不会从面板伪启动。", foreground=WARN).pack(anchor="w", pady=16)

    def _strategy(self) -> None:
        tab = self._tab("策略")
        ttk.Label(tab, text="自动化策略", style="Title.TLabel").pack(anchor="w", pady=(5, 4))
        ttk.Label(tab, text="这里只控制 Goal Category / Policy；Universal Skill 由唯一 Scheduler 按 Goal 与实时状态调用。", style="Muted.TLabel").pack(anchor="w", pady=(0, 14))
        grid = ttk.Frame(tab, style="Card.TFrame", padding=18); grid.pack(fill="x")
        for index, (name, var) in enumerate(self.policy_enabled.items()):
            ttk.Checkbutton(grid, text=name, variable=var, command=self._save_policy_state).grid(
                row=index // 4, column=index % 4, sticky="w", padx=18, pady=10)
            grid.columnconfigure(index % 4, weight=1)
        reward = ttk.Frame(tab, style="Card.TFrame", padding=18); reward.pack(fill="x", pady=(12, 0))
        ttk.Label(reward, text="Reward Policy · FREE_CLAIM_FIRST", style="Section.TLabel", background=PANEL).pack(anchor="w")
        ttk.Label(reward, text="免费无选择奖励：自动领取  ·  未知奖励内容：允许领取  ·  有选择奖励：交给 Strategy  ·  有成本：Resource Policy 判断  ·  真实支付：永久禁止 🔒", background=PANEL, wraplength=1050).pack(anchor="w", pady=(8, 0))
        resource = ttk.Frame(tab, style="Card.TFrame", padding=18); resource.pack(fill="x", pady=(12, 0))
        ttk.Label(resource, text="Resource Policy", style="Section.TLabel", background=PANEL).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        policies = (("普通资源", "自动优化"), ("加速", "按 Queue / Deadline / Event Synergy 决定"),
                    ("钻石", "保守"), ("活动道具", "优先截止期"), ("稀缺资源", "Resource Bank 预留"),
                    ("真实支付", "永久禁止 🔒"))
        for row, (name, value) in enumerate(policies, 1):
            ttk.Label(resource, text=name, style="Muted.TLabel", background=PANEL, width=16).grid(row=row, column=0, sticky="w", pady=5)
            ttk.Label(resource, text=value, background=PANEL, foreground=BAD if name == "真实支付" else TEXT).grid(row=row, column=1, sticky="w", pady=5)

    def _save_policy_state(self) -> None:
        path = ROOT / "config/policy_state.json"
        payload = {"schema_version": "1.0", "goal_categories": {k: v.get() for k, v in self.policy_enabled.items()},
                   "reward_policy": "FREE_CLAIM_FIRST", "real_money": "PERMANENTLY_BLOCKED",
                   "updated_at": datetime.now().astimezone().isoformat()}
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    def _goals(self) -> None:
        tab = self._tab("目标")
        ttk.Label(tab, text="今日目标", style="Title.TLabel").pack(anchor="w", pady=(5, 4))
        ttk.Label(tab, text="来自最近一次真实识别；“未知”不是完成，勾选任务也不是完成。", style="Muted.TLabel").pack(anchor="w", pady=(0, 12))
        self.goal_board = ttk.Treeview(tab, columns=("goal", "category", "priority", "status", "progress", "deadline", "next", "blocked", "skills", "confidence"), show="headings")
        for key, title, width in (("goal", "目标", 185), ("category", "类别", 80), ("priority", "优先级", 70), ("status", "状态", 90), ("progress", "进度/目标", 105), ("deadline", "剩余", 80), ("next", "下一动作", 150), ("blocked", "阻塞原因", 120), ("skills", "贡献能力", 190), ("confidence", "置信度", 70)):
            self.goal_board.heading(key, text=title); self.goal_board.column(key, width=width, anchor="w")
        self.goal_board.pack(fill="both", expand=True)
        self.goal_board_meta = tk.StringVar(value="尚无真实 GoalState；运行识别后自动更新。")
        ttk.Label(tab, textvariable=self.goal_board_meta, style="Muted.TLabel").pack(anchor="w", pady=(8, 0))
        self._refresh_goal_board()

    def _refresh_goal_board(self) -> None:
        if not hasattr(self, "goal_board"):
            return
        for item in self.goal_board.get_children(): self.goal_board.delete(item)
        path = ROOT / "learning/goal_state.json"
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        names = {"CLEAR_INTEL":"清空情报", "AVOID_STAMINA_WASTE":"避免体力溢出", "KEEP_TRAINING_PRODUCTIVE":"保持训练", "KEEP_RESEARCH_PRODUCTIVE":"保持研究", "KEEP_BUILDING_PRODUCTIVE":"保持建筑", "EVENT_MINIMUM_GUARANTEE":"活动低保"}
        statuses = {"READY":"待执行", "IN_PROGRESS":"进行中", "COMPLETE":"✓ 完成", "BLOCKED":"暂时阻塞", "UNKNOWN":"未知（引擎未判定）", "DISCOVERED":"已发现"}
        goals = snapshot.get("goals", [])
        if not goals:
            self.goal_board.insert("", "end", values=("等待下一次可验证 Goal", "运行时", "—", PENDING, "—", "—", "观察 WorldState", "当前页面信息不足", "GoalLibrary / Scheduler", f"{float(snapshot.get('confidence',0)):.0%}"))
        for goal in goals:
            remaining = goal.get("remaining_seconds")
            deadline = "—" if remaining is None else f"{int(remaining)//3600:02d}:{int(remaining)%3600//60:02d}"
            goal_id = goal.get("goal_id")
            category = "活动" if "EVENT" in str(goal_id) or "BEAR" in str(goal_id) else ("日常" if "INTEL" in str(goal_id) or "STAMINA" in str(goal_id) else "发展")
            priority_value = goal.get("priority")
            priority = "P0" if isinstance(priority_value, (int, float)) and priority_value >= 2000 else ("P1" if isinstance(priority_value, (int, float)) and priority_value >= 500 else "P2")
            evidence = goal.get("evidence", {}) if isinstance(goal.get("evidence"), dict) else {}
            progress = f"{float(goal.get('completion',0)):.0%}"
            if "points_missing" in evidence: progress += f" · 缺 {evidence['points_missing']}"
            skills = ", ".join(goal.get("available_skills", ())) or "待发现"
            self.goal_board.insert("", "end", values=(names.get(goal_id, goal_id), category, priority,
                statuses.get(goal.get("status"), goal.get("status")), progress, deadline,
                (goal.get("available_skills") or ["待规划"])[0], goal.get("blocked_reason") or "—", skills,
                f"{float(snapshot.get('confidence',0)):.0%}"))
            left_key = {"EVENT_MINIMUM_GUARANTEE": "活动低保", "CLEAR_INTEL": "情报", "AVOID_STAMINA_WASTE": "体力",
                        "KEEP_TRAINING_PRODUCTIVE": "训练", "KEEP_RESEARCH_PRODUCTIVE": "科研", "KEEP_BUILDING_PRODUCTIVE": "建筑"}.get(goal_id)
            if left_key in getattr(self, "today", {}): self.today[left_key].set(statuses.get(goal.get("status"), goal.get("status")))
        self.goal_board_meta.set(f"识别页面：{snapshot.get('page','UNKNOWN')} · 置信度：{float(snapshot.get('confidence',0)):.0%} · 时间：{snapshot.get('observed_at','—')}")

    def _event_goal(self) -> None:
        tab = self._tab("活动", scroll=True)
        ttk.Label(tab, text="活动低保", style="Title.TLabel").pack(anchor="w", pady=(5, 4))
        ttk.Label(tab, text="当前活动页拥有最终事实优先级；外部资料只提供候选先验。", style="Muted.TLabel").pack(anchor="w", pady=(0, 16))
        box = ttk.Frame(tab, style="Card.TFrame", padding=22); box.pack(fill="x")
        fields = (("活动", "name"), ("阶段", "phase"), ("数据来源", "source"), ("最后验证", "last_verified"),
                  ("置信度", "confidence"), ("目标档位", "tier"), ("当前积分", "current"), ("低保目标", "target"), ("积分缺口", "missing"),
                  ("剩余时间（验证时）", "remaining"), ("状态", "status"), ("已执行计划", "plan"),
                  ("预计成本", "estimated_cost"), ("预计完成", "estimated_completion"),
                  ("资源消耗", "resource"), ("积分验证", "verified"), ("奖励", "rewards"))
        self.event_goal_vars = {key: tk.StringVar(value="暂无数据") for _, key in fields}
        for i, (label, key) in enumerate(fields):
            ttk.Label(box, text=label, style="Muted.TLabel", background=PANEL, width=18).grid(row=i, column=0, sticky="nw", pady=6)
            style = "Value.TLabel" if key in {"name", "status"} else "TLabel"
            ttk.Label(box, textvariable=self.event_goal_vars[key], style=style, background=PANEL, wraplength=760).grid(row=i, column=1, sticky="w", pady=6)
        self._refresh_event_goal_display()
        self._refresh_goal_board()

    def _coverage(self) -> None:
        tab = self._tab("自动化覆盖")
        ttk.Label(tab, text="Goal 自动化覆盖", style="Title.TLabel").pack(anchor="w", pady=(5, 4))
        ttk.Label(tab, text="按完整执行路径与真实 Verifier 统计，不按文件数量统计。", style="Muted.TLabel").pack(anchor="w", pady=(0, 12))
        summary = ttk.Frame(tab, style="Card.TFrame", padding=15); summary.pack(fill="x")
        self.coverage_vars = {key: tk.StringVar(value="暂无数据") for key in ("automated", "candidate", "missing")}
        for index, (key, label) in enumerate((("automated", "已自动化"), ("candidate", "验证中"), ("missing", "缺失"))):
            card = ttk.Frame(summary, style="Card2.TFrame", padding=16); card.grid(row=0, column=index, padx=6, sticky="ew"); summary.columnconfigure(index, weight=1)
            ttk.Label(card, text=label, style="Muted.TLabel", background=PANEL2).pack(anchor="w")
            ttk.Label(card, textvariable=self.coverage_vars[key], style="Title.TLabel", background=PANEL2).pack(anchor="w")
        ttk.Label(tab, text="最高杠杆缺口", style="Section.TLabel").pack(anchor="w", pady=(18, 7))
        self.coverage_tree = ttk.Treeview(tab, columns=("skill", "goals", "score"), show="headings", height=12)
        for key, label, width in (("skill", "共享能力", 420), ("goals", "阻塞目标", 130), ("score", "杠杆分", 130)):
            self.coverage_tree.heading(key, text=label); self.coverage_tree.column(key, width=width, anchor="w")
        self.coverage_tree.pack(fill="both", expand=True)
        self._refresh_coverage()

    def _refresh_coverage(self) -> None:
        if not hasattr(self, "coverage_tree"): return
        try: audit = json.loads((ROOT / "learning/goal_coverage.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): return
        summary = audit.get("summary", {})
        self.coverage_vars["automated"].set(f"{float(summary.get('automated_percent',0)):.1f}%")
        self.coverage_vars["candidate"].set(f"{float(summary.get('candidate_percent',0)):.1f}%")
        self.coverage_vars["missing"].set(f"{float(summary.get('missing_percent',0)):.1f}%")
        for row in self.coverage_tree.get_children(): self.coverage_tree.delete(row)
        for item in audit.get("top_leverage", [])[:10]:
            self.coverage_tree.insert("", "end", values=(item.get("skill_id"), item.get("blocked_goals"), item.get("automation_leverage")))

    def _refresh_event_goal_display(self) -> None:
        path = ROOT / "learning/event_goal_state.json"
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        remaining = int(item.get("remaining_seconds_at_verification", 0))
        current_record = event_goal_is_current(item)
        values = {
            "name": item.get("name", "暂无数据"), "current": f"{int(item.get('current_points', 0)):,}",
            "phase": item.get("event_phase", "待识别"),
            "source": item.get("data_source", "LIVE_CLIENT" if current_record else "HISTORY · 仅参考"),
            "last_verified": item.get("last_verified", item.get("updated_at", "待验证")),
            "confidence": f"{float(item.get('confidence', 0)):.0%}", "tier": item.get("target_tier", "低保目标档"),
            "target": f"{int(item.get('target_points', 0)):,}", "missing": f"{int(item.get('points_missing', 0)):,}",
            "remaining": f"{remaining // 3600:02d}:{remaining % 3600 // 60:02d}:{remaining % 60:02d}",
            "status": ("✓ 今日低保完成" if item.get("minimum_guarantee_complete") else "⚠ 未完成") if current_record else "⚠ 历史记录；今日活动待检查",
            "plan": item.get("plan", "暂无数据"), "resource": item.get("resource_spent", "暂无数据"),
            "estimated_cost": item.get("estimated_cost", "待计算"),
            "estimated_completion": item.get("estimated_completion", "待计算"),
            "verified": f"积分增加 {int(item.get('verified_points_gain', 0)):,}",
            "rewards": "全部目标档位已领取" if item.get("all_target_rewards_claimed") else "仍有奖励待领取",
        }
        for key, value in values.items():
            self.event_goal_vars[key].set(value)
        if hasattr(self, "queues") and "活动" in self.queues:
            self.queues["活动"].set(("低保完成" if item.get("minimum_guarantee_complete") else f"缺 {int(item.get('points_missing', 0)):,}") if current_record else "今日待检查")

    def _capabilities(self) -> None:
        tab = self._tab("能力", scroll=True)
        ttk.Label(tab, text="Capability 覆盖与 Skill 执行层", style="Title.TLabel").pack(anchor="w", pady=(5, 4))
        ttk.Label(tab, text="上表是 Capability 覆盖表（capability_catalog.json）——游戏里有什么、验证到哪一步；"
                            "下表是 Skill 执行注册表（v2_registry）——谁能把动作做出来。两张表各自独立，面板不合并、不改写任何一个。",
                  style="Muted.TLabel", wraplength=1250, justify="left").pack(anchor="w", pady=(0, 8))
        summary = ttk.Frame(tab, style="Card.TFrame", padding=10); summary.pack(fill="x")
        self.capability_summary = {key: tk.StringVar(value=NO_DATA) for key in ("implemented", "tried", "verified", "blocked")}
        for index, (key, label) in enumerate((("implemented", "已实现"), ("tried", "Live Tried"),
                                              ("verified", "Live Verified"), ("blocked", "Blocked"))):
            card = ttk.Frame(summary, style="Card2.TFrame", padding=12); card.grid(row=0, column=index, sticky="ew", padx=4); summary.columnconfigure(index, weight=1)
            ttk.Label(card, text=label, style="Muted.TLabel", background=PANEL2).pack(anchor="w")
            ttk.Label(card, textvariable=self.capability_summary[key], style="Value.TLabel", background=PANEL2).pack(anchor="w")
        # The vocabulary is printed, not implied: the whole point of section 5 is that
        # a reader can tell 未读取 from 未知 from Blocked without guessing.
        ttk.Label(tab, text="状态词义：未读取＝没人读过它（不是未知）· 待刷新＝只有未带 recorded_at 的导入记录，不能作为证据 · "
                            "可执行＝已实现且可派发 · 执行中＝正在跑 · Blocked＝有具名阻塞原因 · Live Tried / Live Verified＝真机证据。",
                  style="Muted.TLabel", wraplength=1250, justify="left").pack(anchor="w", pady=(6, 0))
        head = ttk.Frame(tab); head.pack(fill="x", pady=(10, 4))
        ttk.Label(head, text="Capability 覆盖表", style="Section.TLabel").pack(side="left")
        self.show_all_capabilities = tk.BooleanVar(value=False)
        ttk.Checkbutton(head, text="显示全部（默认只看已实现 / 已尝试 / 被阻塞）", variable=self.show_all_capabilities,
                        command=self._refresh_capabilities).pack(side="right")
        self.capability_tree = ttk.Treeview(tab, columns=("id", "code", "category", "lifecycle", "state", "backend", "live", "rate", "blocked"),
                                            show="headings", height=10)
        for key, title, width in (("id", "Capability ID", 105), ("code", "能力", 235), ("category", "分类", 165),
                                  ("lifecycle", "生命周期", 95), ("state", "可用性", 90), ("backend", "首选后端", 70),
                                  ("live", "真机成功/尝试", 95), ("rate", "成功率", 70), ("blocked", "阻塞原因", 260)):
            self.capability_tree.heading(key, text=title); self.capability_tree.column(key, width=width, anchor="w")
        self.capability_tree.pack(fill="both", expand=True, pady=(0, 10))
        ttk.Label(tab, text="Skill 执行注册表", style="Section.TLabel").pack(anchor="w", pady=(0, 4))
        self.skill_tree = ttk.Treeview(tab, columns=("layer", "skill", "verifier", "risk", "state", "live", "claims", "meaning"),
                                       show="headings", height=8)
        for key, title, width in (("layer", "层级", 90), ("skill", "Skill", 200), ("verifier", "Verifier", 130),
                                  ("risk", "风险", 55), ("state", "阶段", 90), ("live", "真机验证/尝试", 95),
                                  ("claims", "无时间戳声明", 100), ("meaning", "说明", 330)):
            self.skill_tree.heading(key, text=title); self.skill_tree.column(key, width=width, anchor="w")
        self.skill_tree.pack(fill="both", expand=True, pady=(0, 8))
        runtime_quality = ttk.Frame(tab, style="Card.TFrame", padding=8); runtime_quality.pack(fill="x", pady=(8, 0))
        self.runtime_quality_vars = {key: tk.StringVar(value=NO_DATA) for key in ("success24", "recovery", "exit", "latency")}
        for index, (key, label) in enumerate((("success24", "24h Skill Success"), ("recovery", "Recovery Success"), ("exit", "Unexpected Worker Exit"), ("latency", "Average Realtime Latency"))):
            ttk.Label(runtime_quality, text=label, style="Muted.TLabel", background=PANEL).grid(row=0, column=index, sticky="w", padx=8)
            ttk.Label(runtime_quality, textvariable=self.runtime_quality_vars[key], background=PANEL).grid(row=1, column=index, sticky="w", padx=8); runtime_quality.columnconfigure(index, weight=1)
        self._refresh_capabilities()

    def _refresh_capabilities(self) -> None:
        if not hasattr(self, "capability_tree"): return
        from winter_agent_v2.runtime import LiveRuntime

        universal_ids = {"CLAIM_REWARD", "NAVIGATE_TO", "SEND_MARCH", "START_RALLY", "JOIN_RALLY", "START_BUILD", "START_RESEARCH", "TRAIN_OR_PROMOTE", "USE_ACTIVITY_ATTEMPT", "READ_EVENT_STATE", "OPEN_HOME", "OPEN_MAP", "BACK", "CLOSE_POPUP", "DISPATCH_MARCH"}
        index = episode_index()
        snapshot = self.runtime_store.read()
        running_skill = str(snapshot.current_skill or "")
        catalog = capability_catalog()
        entries = catalog.get("capabilities") or []
        cataloged_skills = {str(e.get("existing_skill")) for e in entries if e.get("existing_skill")}
        for row in self.capability_tree.get_children(): self.capability_tree.delete(row)
        shown = 0
        for entry in entries:
            skill = str(entry.get("existing_skill") or "")
            tally = index.get(skill, {}) if skill else {}
            interesting = (bool(skill) or int(entry.get("live_attempts") or 0) or bool(entry.get("blocked_reason")))
            if not (self.show_all_capabilities.get() or interesting):
                continue
            shown += 1
            rate = entry.get("success_rate")
            self.capability_tree.insert("", "end", values=(
                entry.get("capability_id"), entry.get("code"), entry.get("name_cn"),
                capability_lifecycle_cn(entry, skill_state=self._skill_state(skill)),
                capability_state_cn(entry, skill_state=self._skill_state(skill), running_skill=running_skill,
                                    claims=int(tally.get("claims") or 0)),
                entry.get("preferred_backend") or PENDING,
                f"{int(entry.get('live_success') or 0)}/{int(entry.get('live_attempts') or 0)}",
                f"{float(rate):.0%}" if isinstance(rate, (int, float)) else "—",
                str(entry.get("blocked_reason") or "—")[:150],
            ))
        for row in self.skill_tree.get_children(): self.skill_tree.delete(row)
        verified_skills = stable_skills = 0
        for skill in self.registry.all():
            layer = "Universal" if skill.id in universal_ids else ("Event Adapter" if any(k in skill.id for k in ("BEAR", "EVENT")) else "Composite")
            tally = index.get(skill.id, {})
            live = f"{tally.get('verified', 0)}/{tally.get('live', 0)}" if tally.get("live") else "未实机"
            if tally.get("live") and tally.get("verified"): verified_skills += 1
            if skill.state is SkillState.STABLE: stable_skills += 1
            bound = skill.id in LiveRuntime.VERIFIED_ATOMIC
            meaning = ("已绑定 verifier，可由 Scheduler 派发" if bound
                       else "未绑定 verifier：写好了但不会被派发（见 VERIFIER_SHAPE_MISMATCH）")
            if tally.get("claims") and not tally.get("live"):
                meaning = f"{tally['claims']} 行导入声明未带 recorded_at，需要一次真机刷新才算证据"
            self.skill_tree.insert("", "end", values=(layer, skill.id, "已绑定" if bound else "未绑定",
                                                      skill.risk, skill.state.value, live,
                                                      str(tally.get("claims") or 0), meaning))
        kpi = overview_kpis(registry=self.registry)
        for key in ("implemented", "tried", "verified", "blocked"):
            self.capability_summary[key].set(kpi[key]["value"])
        if hasattr(self, "runtime_quality_vars"):
            scan = episode_scan()
            recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            recent: list[bool] = []
            for stamp, ok in scan["results"]:
                try:
                    if datetime.fromisoformat(stamp.replace("Z", "+00:00")) >= recent_cutoff:
                        recent.append(ok)
                except ValueError:
                    pass
            durations = scan["durations"]
            self.runtime_quality_vars["success24"].set(f"{sum(recent)}/{len(recent)}" if recent else "无24h时间戳样本")
            self.runtime_quality_vars["recovery"].set(f"{snapshot.watchdog_restart_count} 次重启")
            self.runtime_quality_vars["exit"].set(str(snapshot.unexpected_worker_exits))
            self.runtime_quality_vars["latency"].set(f"{sum(durations)/len(durations):.1f}s" if durations else PENDING)

    def _skill_state(self, skill_id: str) -> str:
        if not skill_id:
            return ""
        try:
            skill = self.registry.get(skill_id)
        except Exception:  # noqa: BLE001 - an unknown skill simply has no state here
            return ""
        return skill.state.value if skill is not None else ""


    def _skills(self) -> None:
        tab = self._tab("能力", scroll=True); ttk.Label(tab, text="能力目录", style="Title.TLabel").pack(anchor="w", pady=(5, 10))
        tree = ttk.Treeview(tab, columns=("name", "id", "state", "risk"), show="headings")
        for key, title, width in (("name", "能力", 220), ("id", "内部标识", 300), ("state", "验证阶段", 140), ("risk", "资源影响", 200)):
            tree.heading(key, text=title); tree.column(key, width=width, anchor="w")
        states = {SkillState.DISCOVERED: "已发现", SkillState.CANDIDATE: "候选", SkillState.VERIFIED: "已验证", SkillState.STABLE: "稳定", SkillState.BLOCKED: "暂不可执行"}
        for skill in self.registry.all():
            tree.insert("", "end", values=(SKILL_ZH.get(skill.id, skill.description), skill.id, states[skill.state], skill.risk))
        tree.pack(fill="both", expand=True)

    def _knowledge(self) -> None:
        tab = self._tab("知识"); ttk.Label(tab, text="知识库", style="Title.TLabel").pack(anchor="w", pady=(5, 4))
        ttk.Label(tab, text="统计直接读取当前 V2 Knowledge 与 Dataset。", style="Muted.TLabel").pack(anchor="w", pady=(0, 16))
        box = ttk.Frame(tab, style="Card.TFrame", padding=15); box.pack(fill="x")
        for i, (name, number) in enumerate(count_knowledge().items()):
            card = ttk.Frame(box, style="Card2.TFrame", padding=16); card.grid(row=0, column=i, padx=5, sticky="ew"); box.columnconfigure(i, weight=1)
            ttk.Label(card, text=name, style="Muted.TLabel", background=PANEL2).pack(anchor="w")
            ttk.Label(card, text=str(number), style="Title.TLabel", background=PANEL2).pack(anchor="w")
        verified = [SKILL_ZH.get(s.id, s.id) for s in self.registry.all() if s.state in (SkillState.VERIFIED, SkillState.STABLE)]
        ttk.Label(tab, text="最近学会", style="Section.TLabel").pack(anchor="w", pady=(22, 8))
        ttk.Label(tab, text=" · ".join(verified[-8:]) or "暂无数据", style="Muted.TLabel", wraplength=1000).pack(anchor="w")

    def _auto_development(self) -> None:
        """The development platform's own page.

        Renamed from 学习 on 2026-09-17: what happens here is not the runtime
        learning from experience, it is a development agent being handed a
        capability gap and returning either a working capability or an honest
        BLOCKED.  Every number on this page comes from the escalation ledger or
        from ``classify_condition`` -- the same rule the AUTO hook uses.
        """
        from winter_agent_v2.escalation_queue import ALL_STATES

        tab = self._tab("自动开发", scroll=True)
        ttk.Label(tab, text="WorkBuddy 自动开发平台", style="Title.TLabel").pack(anchor="w", pady=(5, 4))
        ttk.Label(tab, text="V2 发现能力缺口 → 升级队列（去重 / 并发 1 / 修复预算）→ WorkBuddy 后台开发 → 真机验证。"
                            "模型只是 WorkBuddy 内部的可替换算力，不是 Winter Agent OS 的组件。",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        status = ttk.Frame(tab, style="Card.TFrame", padding=(12, 10)); status.pack(fill="x")
        head = ttk.Frame(status, style="Card.TFrame"); head.pack(fill="x")
        ttk.Label(head, text="WorkBuddy 状态", style="Section.TLabel", background=PANEL).pack(side="left")
        ttk.Label(head, textvariable=self.values["wb_gateway"], style="Muted.TLabel", background=PANEL).pack(side="right")
        grid = ttk.Frame(status, style="Card.TFrame"); grid.pack(fill="x", pady=(6, 0))
        for index, (label, key) in enumerate((("状态", "wb_state"), ("当前 Capability", "wb_capability"),
                                              ("Escalation Reason", "wb_reason"), ("Job ID", "wb_job"),
                                              ("当前模型", "wb_model"), ("运行时间", "wb_duration"),
                                              ("Job 状态", "wb_job_state"), ("Live Improvement", "wb_improvement"))):
            cell = ttk.Frame(grid, style="Card.TFrame"); cell.grid(row=index // 4, column=index % 4, sticky="w", padx=(0, 22), pady=3)
            ttk.Label(cell, text=label, style="Muted.TLabel", background=PANEL).pack(anchor="w")
            ttk.Label(cell, textvariable=self.values[key], background=PANEL, wraplength=280, justify="left").pack(anchor="w")
            grid.columnconfigure(index % 4, weight=1)
        result = ttk.Frame(grid, style="Card.TFrame"); result.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        ttk.Label(result, text="最近结果", style="Muted.TLabel", background=PANEL).pack(anchor="w")
        ttk.Label(result, textvariable=self.values["wb_result"], background=PANEL, wraplength=1150, justify="left").pack(anchor="w")
        queue = ttk.Frame(tab, style="Card.TFrame", padding=(12, 8)); queue.pack(fill="x", pady=(10, 0))
        qhead = ttk.Frame(queue, style="Card.TFrame"); qhead.pack(fill="x")
        ttk.Label(qhead, text="Development Escalation Queue", style="Section.TLabel", background=PANEL).pack(side="left")
        ttk.Label(qhead, textvariable=self.values["wb_queue_line"], style="Muted.TLabel", background=PANEL).pack(side="right")
        strip = ttk.Frame(queue, style="Card.TFrame"); strip.pack(fill="x", pady=(6, 0))
        self.escalation_state_vars: dict[str, tk.StringVar] = {}
        for index, state in enumerate(ALL_STATES):
            card = ttk.Frame(strip, style="Card2.TFrame", padding=(10, 5)); card.grid(row=0, column=index, sticky="ew", padx=3); strip.columnconfigure(index, weight=1)
            ttk.Label(card, text=STATE_ZH.get(state, state), style="Muted.TLabel", background=PANEL2).pack(anchor="w")
            self.escalation_state_vars[state] = tk.StringVar(value="0")
            ttk.Label(card, textvariable=self.escalation_state_vars[state], style="Value.TLabel", background=PANEL2).pack(anchor="w")
        cond = ttk.Frame(tab, style="Card.TFrame", padding=(12, 8)); cond.pack(fill="x", pady=(10, 0))
        chead = ttk.Frame(cond, style="Card.TFrame"); chead.pack(fill="x")
        ttk.Label(chead, text="Capability Gap · 升级条件分桶", style="Section.TLabel", background=PANEL).pack(side="left")
        ttk.Label(chead, text="按 escalation_queue.classify_condition 分类当前真机失败", style="Muted.TLabel", background=PANEL).pack(side="right")
        cstrip = ttk.Frame(cond, style="Card.TFrame"); cstrip.pack(fill="x", pady=(6, 0))
        self.bucket_vars: dict[str, tk.StringVar] = {}
        for index, condition in enumerate((*AUTO_ESCALATION_CONDITIONS, "（不升级）")):
            card = ttk.Frame(cstrip, style="Card2.TFrame", padding=(10, 5)); card.grid(row=0, column=index, sticky="ew", padx=3); cstrip.columnconfigure(index, weight=1)
            ttk.Label(card, text=CONDITION_ZH.get(condition, condition), style="Muted.TLabel", background=PANEL2).pack(anchor="w")
            self.bucket_vars[condition] = tk.StringVar(value=NO_DATA)
            ttk.Label(card, textvariable=self.bucket_vars[condition], style="Value.TLabel", background=PANEL2).pack(anchor="w")
        ttk.Label(tab, text="Job 历史", style="Section.TLabel").pack(anchor="w", pady=(12, 4))
        self.job_tree = ttk.Treeview(tab, columns=("time", "capability", "reason", "state", "model", "outcome", "changed", "duration"),
                                     show="headings", height=6)
        for key, title, width in (("time", "时间", 150), ("capability", "Capability", 210), ("reason", "Escalation Reason", 150),
                                  ("state", "状态", 80), ("model", "模型", 130), ("outcome", "结果", 110),
                                  ("changed", "代码", 70), ("duration", "耗时", 80)):
            self.job_tree.heading(key, text=title); self.job_tree.column(key, width=width, anchor="w")
        self.job_tree.pack(fill="x", pady=(0, 10))
        pair = ttk.Frame(tab); pair.pack(fill="both", expand=True)
        left = ttk.Frame(pair, style="Card.TFrame", padding=8); left.pack(side="left", fill="both", expand=True, padx=(0, 5))
        ttk.Label(left, text="模型战绩（WorkBuddy 内部算力，只读）", style="Muted.TLabel", background=PANEL).pack(anchor="w")
        self.model_tree = ttk.Treeview(left, columns=("model", "task", "jobs", "success", "live", "duration", "cost"),
                                       show="headings", height=6)
        for key, title, width in (("model", "模型", 130), ("task", "任务类型", 130), ("jobs", "样本", 55),
                                  ("success", "成功率", 70), ("live", "Live 改进", 80), ("duration", "平均耗时", 90), ("cost", "成本", 110)):
            self.model_tree.heading(key, text=title); self.model_tree.column(key, width=width, anchor="w")
        self.model_tree.pack(fill="both", expand=True, pady=(4, 0))
        right = ttk.Frame(pair, style="Card.TFrame", padding=8); right.pack(side="left", fill="both", expand=True, padx=(5, 0))
        ttk.Label(right, text="最近失败分类（真机 episode）", style="Muted.TLabel", background=PANEL).pack(anchor="w")
        self.failure_tree = ttk.Treeview(right, columns=("type", "count", "priority", "last"), show="headings", height=6)
        for key, title, width in (("type", "问题", 260), ("count", "次数", 60), ("priority", "优先级", 70), ("last", "最近出现", 160)):
            self.failure_tree.heading(key, text=title); self.failure_tree.column(key, width=width, anchor="w")
        self.failure_tree.pack(fill="both", expand=True, pady=(4, 0))
        self.dev_note = tk.StringVar(value=PENDING)
        ttk.Label(tab, textvariable=self.dev_note, style="Muted.TLabel", wraplength=1250, justify="left").pack(anchor="w", pady=(8, 0))
        ttk.Button(tab, text="打开升级台账", command=lambda: self._open(ROOT / "learning/workbuddy_escalations.jsonl")).pack(anchor="w", pady=(6, 0))
        self._refresh_auto_development()

    def _refresh_auto_development(self) -> None:
        if not hasattr(self, "job_tree"): return
        view = escalation_view()
        buckets = escalation_buckets()
        for state, var in self.escalation_state_vars.items():
            var.set(str((view.get("counts") or {}).get(state, 0)))
        for condition, var in self.bucket_vars.items():
            entry = buckets.get(condition) or {}
            var.set(f"{entry.get('types', 0)} 类 / {entry.get('episodes', 0)} 次" if entry else "0 类 / 0 次")
        for row in self.job_tree.get_children(): self.job_tree.delete(row)
        for record in view.get("records") or ():
            stamp = (record.submitted_at or record.first_seen)
            self.job_tree.insert("", "end", values=(
                stamp.astimezone().strftime("%m-%d %H:%M") if stamp else "—",
                record.capability or record.skill or record.key,
                record.condition or "—",
                STATE_ZH.get(record.state, record.state),
                record.model or PENDING,
                record.outcome or "待对账",
                "已变更" if record.code_changed else "未变更",
                duration_label(record),
            ))
        for row in self.model_tree.get_children(): self.model_tree.delete(row)
        for row in self._model_rows():
            self.model_tree.insert("", "end", values=(row["model"], row["task_type"], row["jobs"], row["success"],
                                                      row["live"], row["duration"], row["cost"]))
        for row in self.failure_tree.get_children(): self.failure_tree.delete(row)
        for failure, count in live_failure_counts().most_common(12):
            priority = "P0" if count >= 10 else ("P1" if count >= 3 else "P2")
            self.failure_tree.insert("", "end", values=(human_reason(failure), count, priority, ""))
        gap = capability_gap_view()
        summary = gap.get("summary") or {}
        leverage = gap.get("highest_leverage") or ()
        notes = [
            f"最近成功开发 Capability：{self._developed_capabilities(view) or '尚无（还没有升级任务达到 Live Verified）'}",
            f"Goal 覆盖：{summary.get('fully_live_verified', 0)}/{summary.get('total', 0)} 完全真机验证"
            f" · 部分 {summary.get('partial', 0)} · 阻塞 {summary.get('blocked', 0)} · 退化 {summary.get('degraded', 0)}"
            f" · 从未尝试 {summary.get('never_tried', 0)}（源：capability_skill_map.json）",
            "最高杠杆缺口：" + ("、".join(
                f"{entry.get('skill_id')}（阻塞 {entry.get('blocked_goals', 0)} 个 Goal）" for entry in leverage[:3]
            ) or "无"),
        ]
        self.dev_note.set("\n".join(notes))

    def _developed_capabilities(self, view: dict[str, Any]) -> str:
        """Capabilities a development job actually pushed to Live Verified."""
        names = [r.capability or r.skill for r in (view.get("verified") or ()) if (r.capability or r.skill)]
        return "、".join(list(dict.fromkeys(names))[:4])

    def _model_rows(self) -> list[dict[str, str]]:
        """Model record, straight from the router's own outcome log.

        Cost is not obtainable: the jobs API exposes no usage field, so the column
        says so instead of inventing an estimate the router might start trusting.
        """
        from winter_agent_v2.workbuddy_model_router import (
            ModelStatsStore, default_stats_path, stats_for,
        )

        try:
            rows = ModelStatsStore(default_stats_path(ROOT)).rows()
        except Exception:  # noqa: BLE001 - an unreadable stats file is an empty table
            return []
        if not rows:
            return []
        out: list[dict[str, str]] = []
        for task_type in sorted({str(row.get("task_type") or "") for row in rows}):
            for model, rung in sorted(stats_for(rows, task_type).items()):
                if not rung.jobs:
                    continue
                out.append({
                    "model": model, "task_type": task_type or PENDING, "jobs": str(rung.jobs),
                    "success": f"{rung.success_rate:.0%}",
                    "live": f"{rung.live_rate:.0%}" if rung.live_verified else "0%",
                    "duration": f"{rung.mean_duration:.0f}s" if rung.mean_duration else "—",
                    "cost": "不可得（jobs API 无用量字段）",
                })
        return out


    def _system(self) -> None:
        tab = self._tab("系统")
        top = ttk.Frame(tab, style="Card.TFrame", padding=12); top.pack(fill="x")
        ttk.Label(top, text="Runtime Watchdog", style="Section.TLabel", background=PANEL).grid(row=0, column=0, columnspan=4, sticky="w")
        self.runtime_detail_vars = {key: tk.StringVar(value="待刷新") for key in ("thread", "scheduler", "tick", "action", "success", "fatal", "restart", "unexpected")}
        names = (("thread", "Runtime Thread"), ("scheduler", "Scheduler Loop"), ("tick", "Last Tick"), ("action", "Last Action"),
                 ("success", "Last Success"), ("fatal", "Last Fatal"), ("restart", "Watchdog Restart"), ("unexpected", "Unexpected Exit"))
        for index, (key, name) in enumerate(names):
            ttk.Label(top, text=name, style="Muted.TLabel", background=PANEL).grid(row=1 + index // 4 * 2, column=index % 4, sticky="w", padx=8, pady=(8, 0))
            ttk.Label(top, textvariable=self.runtime_detail_vars[key], background=PANEL).grid(row=2 + index // 4 * 2, column=index % 4, sticky="w", padx=8)
            top.columnconfigure(index % 4, weight=1)
        bar = ttk.Frame(tab); bar.pack(fill="x", pady=(10, 6))
        ttk.Label(bar, text="完整日志 / Vision Debug / Replay", style="Section.TLabel").pack(side="left")
        for label, path in (("日志目录", LOG_ROOT), ("截图目录", CAPTURE_ROOT), ("Evidence", ROOT / "evidence"), ("Replay", ROOT / "tests/replay")):
            ttk.Button(bar, text=label, command=lambda p=path: self._open(p)).pack(side="right", padx=3)
        self.log = tk.Text(tab, bg="#070b10", fg="#bccbda", relief="flat", font=("Consolas", 9), padx=12, pady=10, wrap="word", height=14); self.log.pack(fill="both", expand=True)
        self._append("控制台已启动。")

    def _refresh_runtime_snapshot(self, schedule_next: bool = True) -> None:
        snapshot = self.runtime_store.read()
        names = {"AUTO_RUNNING": "● 自动运行", "IDLE": "● 空闲", "GOAL_RUNNING": "● Goal 执行中", "RECOVERING": "● 恢复中", "DEGRADED": "● 退化运行", "SAFE_STOP": "● 安全停止", "FATAL_STOPPED": "● 致命停止", "PAUSED": "● 已暂停"}
        running = snapshot.agent_state in {"AUTO_RUNNING", "GOAL_RUNNING", "RECOVERING"}
        self.values["agent"].set(names.get(snapshot.agent_state, snapshot.agent_state))
        self.values["page"].set(PAGE_ZH.get(snapshot.page, snapshot.page or (UNKNOWN_NOW if running else PENDING)))
        self.values["task_cn"].set("自动目标发现" if snapshot.current_goal == "AUTO_DISCOVERY" else (snapshot.current_goal or PENDING))
        self.values["skill"].set(snapshot.current_skill or PENDING)
        self.values["reason"].set(human_reason(snapshot.reason)); self.values["preconditions"].set(" · ".join(snapshot.preconditions) or PENDING)
        self.values["verifier"].set(human_reason(snapshot.verifier)); self.values["next"].set(human_reason(snapshot.next_action))
        self.values["risk"].set(snapshot.risk if snapshot.risk and snapshot.risk != "UNKNOWN" else PENDING)
        self.values["confidence"].set(f"{snapshot.confidence:.0%}")
        self.values["mode"].set("自动运行" if running else ("暂停" if snapshot.agent_state == "PAUSED" else "等待"))
        self.values["runtime_state"].set(runtime_status_cn(snapshot.stop_reason, running=running))
        # MAA / backend axis.  Taken from the executor ledger and the resolved
        # production interpreter, so this cell cannot claim MAA is fine while the
        # worker is quietly running on ADB capture.
        axis = backend_axis(tail_jsonl(BACKEND_LEDGER_PATH, 200))
        self.values["maa"].set(maa_cell(runtime_interpreter_report(), axis))
        self.values["backend"].set(axis["label"])
        self.values["backend_detail"].set(f"{axis['mix']} · 最近错误 {axis['errors']} 次")
        if snapshot.march_used is not None and snapshot.march_max is not None:
            march = f"{snapshot.march_used}/{snapshot.march_max}"; self.values["march"].set(f"行军：{march}"); self.queues["行军"].set(march)
        queue_names = {"建筑": "building", "科技": "research", "训练": "training", "Intel": "intel", "联盟": "alliance", "活动": "events"}
        for label, key in queue_names.items(): self.queues[label].set(self._compact(snapshot.queues.get(key, {})))
        if snapshot.screenshot_path:
            image_path = Path(snapshot.screenshot_path)
            if image_path.exists() and image_path != self.latest_image_path:
                try:
                    self.latest_image_path = image_path; self.preview_source = Image.open(image_path).convert("RGB"); self._render_preview()
                    self.preview_meta.set(f"Runtime Evidence · {PAGE_ZH.get(snapshot.page, snapshot.page)} · {snapshot.confidence:.0%}")
                except OSError: pass
        if hasattr(self, "runtime_detail_vars"):
            vals = {"thread": "存活" if snapshot.runtime_thread_alive else "未运行", "scheduler": "存活" if snapshot.scheduler_loop_alive else "未运行",
                    "tick": snapshot.last_tick_time or "无", "action": snapshot.last_action_time or "无", "success": snapshot.last_success_time or "无",
                    "fatal": snapshot.last_fatal_error or "无", "restart": str(snapshot.watchdog_restart_count), "unexpected": str(snapshot.unexpected_worker_exits)}
            for key, value in vals.items(): self.runtime_detail_vars[key].set(value)
        self._refresh_workbuddy(); self._refresh_capabilities(); self._refresh_auto_development()
        if schedule_next: self.root.after(1500, self._refresh_runtime_snapshot)

    def _refresh_workbuddy(self) -> None:
        """Keep every WorkBuddy surface on one set of derived facts.

        The header cell, the overview card and the development tab all read these
        same values, so they cannot disagree about what the development platform is
        doing -- which is the whole point of not building a second state store.
        """
        view = escalation_view()
        gateway = self.gateway.snapshot()
        label, detail = workbuddy_cell(view, gateway)
        self.values["workbuddy"].set(label)
        self.values["wb_state"].set(label + (f"（{detail}）" if detail else ""))
        if gateway.get("available") is False:
            self.values["wb_gateway"].set(f"网关不可用 · {gateway_reason_cn(gateway.get('reason'))}")
        elif gateway.get("available") is True:
            self.values["wb_gateway"].set(f"网关正常 · 检查于 {gateway.get('checked_at') or '—'}")
        else:
            self.values["wb_gateway"].set("网关状态待测")
        current = view.get("current")
        settled = view.get("pending_verify") or ()
        if current is None and settled:
            current = settled[0]
        self.values["wb_queue_line"].set(
            " · ".join(f"{state} {count}" for state, count in sorted((view.get("counts") or {}).items())) or PENDING
        )
        if current is None:
            self.values["wb_capability"].set(PENDING)
            self.values["wb_reason"].set(PENDING)
            self.values["wb_job"].set(PENDING)
            self.values["wb_model"].set(PENDING)
            self.values["wb_duration"].set(PENDING)
            self.values["wb_job_state"].set(PENDING)
            self.values["wb_improvement"].set(PENDING)
            self.values["wb_result"].set("尚未产生开发任务：升级队列为空。")
            self.gateway.watch("")
        else:
            self.values["wb_capability"].set(current.capability or current.skill or current.key)
            self.values["wb_reason"].set(current.condition or PENDING)
            self.values["wb_job"].set(current.job_id or "尚未提交")
            # The model is WorkBuddy's own compute, read back from the ledger it
            # wrote -- the panel never names one and never chooses one.
            self.values["wb_model"].set(current.model or PENDING)
            # "运行时间" only means something once a job exists.  For a gap that has
            # been noticed but not submitted, the honest reading is how long we have
            # been sitting on it -- calling that a job's runtime would overstate it.
            self.values["wb_duration"].set(
                f"未提交（发现于 {duration_label(current)}前）" if not current.submitted_at
                else duration_label(current)
            )
            job = gateway.get("job") or {}
            self.values["wb_job_state"].set(
                f"{current.state}" + (f" · 网关 {job.get('verdict')}" if job.get("verdict") else "")
            )
            self.values["wb_improvement"].set(
                "是" if current.outcome == "LIVE_VERIFIED" else ("否" if current.outcome else "待对账")
            )
            self.values["wb_result"].set(self._describe_escalation(current))
            self.gateway.watch(current.job_id)
        kpi = overview_kpis(view=view)
        for key, var in self.kpi.items():
            var.set(kpi.get(key, {}).get("value", NO_DATA))
        if hasattr(self, "kpi_source"):
            for key, var in self.kpi_source.items():
                var.set(kpi.get(key, {}).get("source", PENDING))

    def _describe_escalation(self, record: Any) -> str:
        """One honest line about what a finished development job achieved."""
        parts = [f"结果 {record.outcome or '待对账'}"]
        if record.repairs_used:
            parts.append(f"已用修复预算 {record.repairs_used}")
        parts.append("代码已变更" if record.code_changed else "代码未变更")
        if record.notes:
            parts.append(str(record.notes[-1])[:200])
        if record.evidence:
            parts.append(f"证据 {Path(str(record.evidence[0])).name}")
        return " · ".join(parts)

    def _logs(self) -> None:
        tab = self._tab("日志"); bar = ttk.Frame(tab); bar.pack(fill="x", pady=(0, 8))
        ttk.Label(bar, text="完整运行日志", style="Title.TLabel").pack(side="left")
        ttk.Button(bar, text="打开日志目录", command=lambda: self._open(LOG_ROOT)).pack(side="right")
        self.log = tk.Text(tab, bg="#070b10", fg="#bccbda", relief="flat", font=("Consolas", 9), padx=12, pady=10, wrap="word"); self.log.pack(fill="both", expand=True)
        self._append("控制台已启动。")

    def _settings(self) -> None:
        tab = self._tab("设置"); ttk.Label(tab, text="运行与资源策略", style="Title.TLabel").pack(anchor="w", pady=(5, 14))
        box = ttk.Frame(tab, style="Card.TFrame", padding=18); box.pack(fill="x")
        ttk.Checkbutton(
            box,
            text="连续运行（可执行时 30 秒复查；行军已满时 10 分钟复查）",
            variable=self.continuous,
            command=self._save_panel_state,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        for i, (name, var) in enumerate(self.resource_policy.items(), 1):
            ttk.Label(box, text=name, background=PANEL, width=15).grid(row=i, column=0, sticky="w", pady=6)
            choices = ("禁止",) if name == "真实支付" else ("自动使用", "保守", "禁止")
            ttk.Combobox(box, textvariable=var, values=choices, state="readonly", width=18).grid(row=i, column=1, sticky="w")
        ttk.Label(tab, text="硬安全边界：真实充值、账号/角色删除、账号安全设置始终禁止。", foreground=BAD).pack(anchor="w", pady=15)
        row = ttk.Frame(tab); row.pack(fill="x")
        ttk.Button(row, text="打开截图目录", command=lambda: self._open(CAPTURE_ROOT)).pack(side="left", padx=4)
        ttk.Button(row, text="打开证据目录", command=lambda: self._open(ROOT / "evidence")).pack(side="left", padx=4)
        ttk.Button(row, text="打开最新截图", command=self.open_latest).pack(side="left", padx=4)

    def _tick(self) -> None:
        self.values["clock"].set(datetime.now().strftime("%H:%M:%S")); self.root.after(1000, self._tick)

    def _append(self, message: str) -> None:
        line = f"{datetime.now():%H:%M:%S}  {message.rstrip()}"
        if hasattr(self, "log"): self.log.insert("end", line + "\n"); self.log.see("end")
        self.event_lines = (self.event_lines + [line])[-20:]
        if hasattr(self, "event_text"): self.event_text.set("   |   ".join(self.event_lines[-3:]))

    def _sync_tasks(self) -> None:
        running_task = getattr(self, "active_panel_task", None) if (self.process is not None or self.starting) else None
        for name, var in self.task_enabled.items():
            self.today[name].set("运行中" if name == running_task else ("待执行" if var.get() else "等待"))
            button = getattr(self, "task_buttons", {}).get(name)
            if button is not None:
                available = name in LIVE_PANEL_TASKS
                button.configure(
                    text=task_toggle_label(name, var.get(), available),
                    style=("TaskEnabled.TButton" if var.get() else "TaskDisabled.TButton") if available else "TaskUnavailable.TButton",
                    state="normal" if available else "disabled",
                )
        self._save_panel_state()

    def _save_panel_state(self) -> None:
        save_task_selection(
            PANEL_STATE_PATH,
            {name: var.get() for name, var in self.task_enabled.items()},
            self.continuous.get(),
        )

    def _toggle_task(self, name: str) -> None:
        if name not in LIVE_PANEL_TASKS:
            self._append(f"任务“{name}”尚未接入控制台实机主循环，未启用。")
            return
        var = self.task_enabled[name]
        var.set(not var.get())
        self._sync_tasks()
        self._append(f"任务“{name}”已{'启用，允许自动执行' if var.get() else '关闭，不会自动执行'}。")

    def refresh(self) -> None:
        self._refresh_runtime_snapshot(schedule_next=False)
        self._append("已从统一 Runtime Snapshot 刷新；面板只读现有状态文件，不自行识别。")

    def take_screenshot(self) -> None:
        self._append("截图由 Runtime 统一采集；已显示最新 Runtime Evidence。"); self.refresh()

    def _refresh_worker(self) -> None:
        self.events.put(("note", "状态由 Runtime Snapshot 统一提供。"))

    def start(self) -> None:
        if self.process is not None or self.starting: return
        blocker = runtime_env_blocker()
        if blocker is not None:
            # Refuse rather than degrade.  Starting work on an interpreter that
            # cannot import MAA means every measurement afterwards is taken
            # through a path the project already paid to replace, and the run
            # still looks healthy.  See runtime_interpreter_report() above.
            self._append(f"未启动：运行环境不满足生产要求（{blocker}）。")
            for line in runtime_interpreter_report().describe().splitlines():
                self._append(f"    {line}")
            self._append("    诊断：python tools/preflight.py；"
                         "修复：在 config/v2.json 的 runtime.python_path 指定可用解释器。")
            self.runtime_store.update(
                agent_state=AgentState.DEGRADED.value, runtime_thread_alive=False,
                scheduler_loop_alive=False, stop_reason=RUNTIME_ENV_STOP_REASON,
                reason=f"解释器不可用：{blocker}", next_action="修复运行环境后重新启动",
            )
            self.events.put(("note", f"未启动：{blocker}"))
            return
        # A development agent may have just written code.  Each cycle is a fresh
        # subprocess that imports vision/brain/skills from disk, so the new code
        # takes effect by itself -- what must not happen is importing a tree
        # mid-write, which is the failure `run_live.py`'s VERIFIER_MAPPING_CORRUPT
        # guard was added for.  The wait is bounded inside the signal.
        reload_signal, deferral = reload_deferral()
        if deferral:
            self._append(f"延后启动：{deferral.reason}")
            self.events.put(("note", deferral.reason))
            self.runtime_store.update(
                agent_state=AgentState.RECOVERING.value, runtime_thread_alive=False,
                scheduler_loop_alive=False, stop_reason=REQUEST_KIND,
                reason=deferral.reason, next_action="等待代码写入落定后自动继续",
            )
            self.repeat_after_id = self.root.after(RELOAD_RETRY_MS, self.start)
            return
        reload_signal.clear("settled")
        self.starting = True
        self._append(f"运行环境预检通过：{runtime_python_path()}")
        if self.repeat_after_id: self.root.after_cancel(self.repeat_after_id); self.repeat_after_id = None
        self.stop_requested = self.paused = False; self._running_buttons()
        self.runtime_store.update(agent_state=AgentState.RECOVERING.value, runtime_thread_alive=True,
                                  scheduler_loop_alive=False, stop_reason=None, last_fatal_error=None,
                                  current_goal=None, current_skill=None, reason="启动并校准真实客户端",
                                  verifier=None, next_action="启动唯一 Scheduler")
        self._append("自动运行已启动：Goal 与 Universal Skill 由唯一 Scheduler 决定。")
        threading.Thread(target=self._run_unified_worker, daemon=True).start()

    def _run_unified_worker(self) -> None:
        """Lifecycle adapter only; it never selects a Goal or Skill."""
        try:
            blocker = runtime_env_blocker()
            if blocker is not None:
                raise RuntimeError(f"{RUNTIME_ENV_STOP_REASON}: {blocker}")
            self.active_panel_task = "AUTO"
            self._ensure_device()
            if self.stop_requested: return
            LOG_ROOT.mkdir(parents=True, exist_ok=True); CAPTURE_ROOT.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            command = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "24",
                       "--capture-dir", str(CAPTURE_ROOT / "runtime_auto" / stamp), "--serial", self.device.serial]
            self.process = _background_popen(command, cwd=str(ROOT), stdout=subprocess.PIPE,
                                             stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
            output, _ = self.process.communicate(); code = self.process.returncode
            (LOG_ROOT / "latest.log").write_text(output, encoding="utf-8")
            self.events.put(("complete", (code, parse_runtime_result(output), output)))
        except BaseException as exc:
            # Catch everything, including KeyboardInterrupt/SystemExit, so a
            # worker death is never silent.  The full traceback plus the runtime
            # state is written to learning/control_panel/crashes/ before the GUI
            # is told anything; only the classified outcome drives the counters.
            report = write_worker_crash_report(where="unified_worker", exc=exc,
                                               snapshot=self.runtime_store.read())
            self.runtime_store.update(
                agent_state=AgentState.FATAL_STOPPED.value if is_fatal_stop(str(exc)) else AgentState.DEGRADED.value,
                runtime_thread_alive=False, scheduler_loop_alive=False,
                last_fatal_error=str(exc) if is_fatal_stop(str(exc)) else None, stop_reason=str(exc))
            self.events.put(("worker_failure", {
                "message": f"运行失败：{exc}",
                "classification": classify_worker_failure(str(exc)),
                "crash_report": str(report),
            }))
        finally:
            self.process = None; self.starting = False

    def _ensure_device(self) -> None:
        if self.stop_requested:
            raise RuntimeError("用户已停止")
        # A running MuMuNxMain.exe only proves that the multi-instance shell is
        # open.  It does not prove that Android instance 0 is booted or attached
        # to ADB.  First reconnect the configured endpoint, then launch the
        # actual VM through MuMuManager when discovery still fails.
        _background_run([str(self.device.adb_path), "connect", self.device.serial],
                        capture_output=True, text=True, timeout=10, check=False)
        try:
            self.device.resolve_connection()
        except RuntimeError as exc:
            if str(exc) != "DEVICE_NOT_CONNECTED":
                raise
            if not MUMU_MANAGER_PATH.exists() and not MUMU_PATH.exists():
                raise RuntimeError("MuMu 未连接且启动程序不存在")
            if MUMU_MANAGER_PATH.exists():
                launch = _background_run(
                    [str(MUMU_MANAGER_PATH), "control", "-v", MUMU_VM_INDEX,
                     "launch", "-pkg", self.config["device"]["package_name"]],
                    capture_output=True, text=True, timeout=30, check=False,
                )
                if launch.returncode != 0:
                    raise RuntimeError(f"MuMu 实例启动失败：{launch.stderr.strip() or launch.stdout.strip()}")
            else:
                _background_popen([str(MUMU_PATH)])
            for _ in range(60):
                if self.stop_requested: raise RuntimeError("用户已停止")
                threading.Event().wait(2)
                _background_run([str(self.device.adb_path), "connect", self.device.serial],
                                capture_output=True, text=True, timeout=10, check=False)
                try:
                    self.device.resolve_connection()
                    break
                except RuntimeError as exc:
                    if str(exc) != "DEVICE_NOT_CONNECTED":
                        raise
            else: raise RuntimeError("等待 MuMu 连接超时")
        if self.device.status().foreground_package != self.config["device"]["package_name"]:
            self.device.launch(self.config["device"]["package_name"])
            threading.Event().wait(3)
        # Page understanding and recovery belong to Runtime. The GUI lifecycle
        # adapter stops here after making the client reachable and foreground.

    def _run_worker(self) -> None:
        try:
            blocker = runtime_env_blocker()
            if blocker is not None:
                raise RuntimeError(f"{RUNTIME_ENV_STOP_REASON}: {blocker}")
            self._ensure_device()
            if self.stop_requested: return
            LOG_ROOT.mkdir(parents=True, exist_ok=True); CAPTURE_ROOT.mkdir(parents=True, exist_ok=True)
            active_task = getattr(self, "active_panel_task", "采集")
            is_intel = active_task == "Intel"
            is_beast = active_task == "野怪"
            is_mail = active_task == "邮件"
            is_exploration = active_task == "探险"
            is_daily = active_task == "日常"
            is_alliance = active_task == "联盟"
            is_training = active_task == "训练"
            goal = "MAIL" if is_mail else ("DAILY" if is_daily else ("ALLIANCE" if is_alliance else ("TRAIN" if is_training else ("EXPLORATION" if is_exploration else ("INTEL" if is_intel else ("BEAST_HUNT" if is_beast else "GATHER_RESOURCE"))))))
            stop_after = None if (is_mail or is_daily or is_alliance or is_training or is_exploration) else ("DISPATCH_INTEL_BEAST" if is_intel else ("DISPATCH_BEAST" if is_beast else "DISPATCH_MARCH"))
            capture_name = "runtime_mail" if is_mail else ("runtime_daily" if is_daily else ("runtime_alliance" if is_alliance else ("runtime_training" if is_training else ("runtime_exploration" if is_exploration else ("runtime_intel" if is_intel else ("runtime_beast" if is_beast else "runtime"))))))
            # Never overwrite screenshots from an earlier run.  On Windows an
            # open preview, indexer, or virus scanner may hold the old PNG and
            # make os.replace fail with WinError 5.  A unique evidence folder
            # also preserves each unattended run as an auditable episode.
            run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            cmd = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "12", "--goal", goal, "--capture-dir", str(CAPTURE_ROOT / capture_name / run_stamp)]
            if stop_after:
                cmd.extend(["--stop-after", stop_after])
            self.process = _background_popen(cmd + ["--serial", self.device.serial], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
            output, _ = self.process.communicate(); code = self.process.returncode
            first_payload = parse_runtime_result(output)
            if is_mail and first_payload.get("stop_reason") == "mail_all_clear" and self.enabled_task_snapshot.get("日常", False) and not self.stop_requested:
                self.active_panel_task = "日常"
                self.run_chain_tasks.add("日常")
                is_daily, is_mail = True, False
                self.events.put(("note", "邮件奖励已清空，继续检查每日任务奖励。"))
                self._ensure_device()
                fallback_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                fallback = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "DAILY", "--capture-dir", str(CAPTURE_ROOT / "runtime_daily" / fallback_stamp)]
                if self.stop_requested: return
                self.process = _background_popen(fallback + ["--serial", self.device.serial], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                fallback_output, _ = self.process.communicate(); code = self.process.returncode
                output = output.rstrip() + "\n" + fallback_output
                first_payload = parse_runtime_result(output)
            if is_mail and first_payload.get("stop_reason") == "mail_all_clear" and not self.enabled_task_snapshot.get("日常", False) and self.enabled_task_snapshot.get("联盟", False) and not self.stop_requested:
                self.active_panel_task = "联盟"
                self.run_chain_tasks.add("联盟")
                is_alliance, is_mail = True, False
                self.events.put(("note", "邮件奖励已清空，继续检查联盟赠礼。"))
                self._ensure_device()
                fallback_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                fallback = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "ALLIANCE", "--capture-dir", str(CAPTURE_ROOT / "runtime_alliance" / fallback_stamp)]
                if self.stop_requested: return
                self.process = _background_popen(fallback + ["--serial", self.device.serial], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                fallback_output, _ = self.process.communicate(); code = self.process.returncode
                output = output.rstrip() + "\n" + fallback_output
                first_payload = parse_runtime_result(output)
            if is_mail and first_payload.get("stop_reason") == "mail_all_clear" and self.enabled_task_snapshot.get("探险", False) and not self.stop_requested:
                self.active_panel_task = "探险"
                self.run_chain_tasks.add("探险")
                is_exploration, is_mail = True, False
                self.events.put(("note", "邮件奖励已清空，继续检查探险挂机收益。"))
                self._ensure_device()
                fallback_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                fallback = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "EXPLORATION", "--capture-dir", str(CAPTURE_ROOT / "runtime_exploration" / fallback_stamp)]
                if self.stop_requested: return
                self.process = _background_popen(fallback + ["--serial", self.device.serial], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                fallback_output, _ = self.process.communicate(); code = self.process.returncode
                output = output.rstrip() + "\n" + fallback_output
                first_payload = parse_runtime_result(output)
            if is_daily and first_payload.get("stop_reason") in {"daily_state_unknown_or_not_actionable", "daily_no_claimable_rewards"} and self.enabled_task_snapshot.get("联盟", False) and not self.stop_requested:
                self.active_panel_task = "联盟"
                self.run_chain_tasks.add("联盟")
                is_alliance, is_daily = True, False
                self.events.put(("note", "每日奖励已检查，继续检查联盟赠礼。"))
                self._ensure_device()
                fallback_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                fallback = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "ALLIANCE", "--capture-dir", str(CAPTURE_ROOT / "runtime_alliance" / fallback_stamp)]
                if self.stop_requested: return
                self.process = _background_popen(fallback + ["--serial", self.device.serial], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                fallback_output, _ = self.process.communicate(); code = self.process.returncode
                output = output.rstrip() + "\n" + fallback_output
                first_payload = parse_runtime_result(output)
            if is_daily and first_payload.get("stop_reason") in {"daily_state_unknown_or_not_actionable", "daily_no_claimable_rewards"} and self.enabled_task_snapshot.get("探险", False) and not self.stop_requested:
                self.active_panel_task = "探险"
                self.run_chain_tasks.add("探险")
                is_exploration, is_daily = True, False
                self.events.put(("note", "每日奖励已检查，继续检查探险挂机收益。"))
                self._ensure_device()
                fallback_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                fallback = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "EXPLORATION", "--capture-dir", str(CAPTURE_ROOT / "runtime_exploration" / fallback_stamp)]
                if self.stop_requested: return
                self.process = _background_popen(fallback + ["--serial", self.device.serial], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                fallback_output, _ = self.process.communicate(); code = self.process.returncode
                output = output.rstrip() + "\n" + fallback_output
                first_payload = parse_runtime_result(output)
            if is_alliance and first_payload.get("stop_reason") == "alliance_action_not_needed" and self.enabled_task_snapshot.get("训练", False) and not self.stop_requested:
                self.active_panel_task = "训练"
                self.run_chain_tasks.add("训练")
                is_training, is_alliance = True, False
                self.events.put(("note", "联盟赠礼已检查，继续检查部队训练。"))
                self._ensure_device()
                fallback_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                fallback = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "10", "--goal", "TRAIN", "--capture-dir", str(CAPTURE_ROOT / "runtime_training" / fallback_stamp)]
                if self.stop_requested: return
                self.process = _background_popen(fallback + ["--serial", self.device.serial], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                fallback_output, _ = self.process.communicate(); code = self.process.returncode
                output = output.rstrip() + "\n" + fallback_output
                first_payload = parse_runtime_result(output)
            if is_alliance and first_payload.get("stop_reason") == "alliance_action_not_needed" and self.enabled_task_snapshot.get("探险", False) and not self.stop_requested:
                self.active_panel_task = "探险"
                self.run_chain_tasks.add("探险")
                is_exploration, is_alliance = True, False
                self.events.put(("note", "联盟赠礼已检查，继续检查探险挂机收益。"))
                self._ensure_device()
                fallback_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                fallback = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "EXPLORATION", "--capture-dir", str(CAPTURE_ROOT / "runtime_exploration" / fallback_stamp)]
                if self.stop_requested: return
                self.process = _background_popen(fallback + ["--serial", self.device.serial], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                fallback_output, _ = self.process.communicate(); code = self.process.returncode
                output = output.rstrip() + "\n" + fallback_output
                first_payload = parse_runtime_result(output)
            if is_training and first_payload.get("stop_reason") in {"training_queue_busy", "TARGET_SKILL_VERIFIED", "MAX_ACTIONS_REACHED"} and self.enabled_task_snapshot.get("探险", False) and not self.stop_requested:
                self.active_panel_task = "探险"
                self.run_chain_tasks.add("探险")
                is_exploration, is_training = True, False
                self.events.put(("note", "部队训练已检查，继续检查探险挂机收益。"))
                self._ensure_device()
                fallback_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                fallback = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "EXPLORATION", "--capture-dir", str(CAPTURE_ROOT / "runtime_exploration" / fallback_stamp)]
                if self.stop_requested: return
                self.process = _background_popen(fallback + ["--serial", self.device.serial], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                fallback_output, _ = self.process.communicate(); code = self.process.returncode
                output = output.rstrip() + "\n" + fallback_output
                first_payload = parse_runtime_result(output)
            if is_exploration and first_payload.get("stop_reason") == "exploration_income_not_ready" and self.enabled_task_snapshot.get("Intel", False) and not self.stop_requested:
                self.active_panel_task = "Intel"
                self.run_chain_tasks.add("Intel")
                is_intel, is_exploration = True, False
                self.events.put(("note", "探险收益已检查，继续检查情报任务。"))
                self._ensure_device()
                fallback_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                fallback = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "INTEL", "--stop-after", "DISPATCH_INTEL_BEAST", "--capture-dir", str(CAPTURE_ROOT / "runtime_intel" / fallback_stamp)]
                if self.stop_requested: return
                self.process = _background_popen(fallback + ["--serial", self.device.serial], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                fallback_output, _ = self.process.communicate(); code = self.process.returncode
                output = output.rstrip() + "\n" + fallback_output
                first_payload = parse_runtime_result(output)
            if is_mail and first_payload.get("stop_reason") == "mail_all_clear" and self.enabled_task_snapshot.get("Intel", False) and not self.stop_requested:
                self.active_panel_task = "Intel"
                self.run_chain_tasks.add("Intel")
                is_intel, is_mail = True, False
                self.events.put(("note", "邮件奖励已清空，继续检查情报任务。"))
                self._ensure_device()
                fallback_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                fallback = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "INTEL", "--stop-after", "DISPATCH_INTEL_BEAST", "--capture-dir", str(CAPTURE_ROOT / "runtime_intel" / fallback_stamp)]
                if self.stop_requested: return
                self.process = _background_popen(fallback + ["--serial", self.device.serial], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                fallback_output, _ = self.process.communicate(); code = self.process.returncode
                output = output.rstrip() + "\n" + fallback_output
                first_payload = parse_runtime_result(output)
            if is_exploration and first_payload.get("stop_reason") == "exploration_income_not_ready" and self.enabled_task_snapshot.get("Intel", False) and not self.stop_requested:
                self.active_panel_task = "Intel"
                self.run_chain_tasks.add("Intel")
                is_intel, is_exploration = True, False
                self.events.put(("note", "探险收益已检查，继续检查情报任务。"))
                self._ensure_device()
                fallback_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                fallback = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "INTEL", "--stop-after", "DISPATCH_INTEL_BEAST", "--capture-dir", str(CAPTURE_ROOT / "runtime_intel" / fallback_stamp)]
                if self.stop_requested: return
                self.process = _background_popen(fallback + ["--serial", self.device.serial], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                fallback_output, _ = self.process.communicate(); code = self.process.returncode
                output = output.rstrip() + "\n" + fallback_output
                first_payload = parse_runtime_result(output)
            if (
                is_intel
                and first_payload.get("stop_reason") in {"intel_state_unknown", "intel_available_no_claim", "SEMANTIC_TARGET_NOT_VERIFIED"}
                and self.enabled_task_snapshot.get("野怪", False)
                and not self.stop_requested
            ):
                self.active_panel_task = "野怪"
                self.run_chain_tasks.add("野怪")
                self.events.put(("note", "当前没有可验证的蓝色情报兽任务，切换到普通野怪消耗体力。"))
                self._ensure_device()
                fallback_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                fallback = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "BEAST_HUNT", "--stop-after", "DISPATCH_BEAST", "--capture-dir", str(CAPTURE_ROOT / "runtime_beast" / fallback_stamp)]
                if self.stop_requested: return
                self.process = _background_popen(fallback + ["--serial", self.device.serial], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                fallback_output, _ = self.process.communicate(); code = self.process.returncode
                output = output.rstrip() + "\n" + fallback_output
                first_payload = parse_runtime_result(output)
            if (
                (is_beast or getattr(self, "active_panel_task", "") == "野怪")
                and first_payload.get("stop_reason") == "verified_beast_target_not_visible"
                and self.enabled_task_snapshot.get("采集", False)
                and not self.stop_requested
            ):
                self.active_panel_task = "采集"
                self.run_chain_tasks.add("采集")
                self.events.put(("note", "当前画面没有已验证的低等级普通野怪，切换到保留行军位的采集检查。"))
                fallback_stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                fallback = [runtime_python_path(), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "GATHER_RESOURCE", "--stop-after", "DISPATCH_MARCH", "--capture-dir", str(CAPTURE_ROOT / "runtime" / fallback_stamp)]
                if self.stop_requested: return
                self.process = _background_popen(fallback + ["--serial", self.device.serial], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                fallback_output, _ = self.process.communicate(); code = self.process.returncode
                output = output.rstrip() + "\n" + fallback_output
            (LOG_ROOT / "latest.log").write_text(output, encoding="utf-8")
            self.events.put(("complete", (code, parse_runtime_result(output), output)))
        except BaseException as exc:
            report = write_worker_crash_report(where="panel_worker", exc=exc,
                                               snapshot=self.runtime_store.read())
            self.runtime_store.update(
                agent_state=AgentState.FATAL_STOPPED.value if is_fatal_stop(str(exc)) else AgentState.DEGRADED.value,
                runtime_thread_alive=False, scheduler_loop_alive=False,
                last_fatal_error=str(exc) if is_fatal_stop(str(exc)) else None, stop_reason=str(exc))
            self.events.put(("worker_failure", {
                "message": f"运行失败：{exc}",
                "classification": classify_worker_failure(str(exc)),
                "crash_report": str(report),
            }))
        finally:
            self.process = None
            self.starting = False

    def pause(self) -> None:
        self.paused = self.stop_requested = True; self.starting = False; self._cancel_repeat()
        if self.process is not None and self.process.poll() is None: self.process.terminate()
        self.values["agent"].set("● 等待"); self.values["mode"].set("暂停"); self.values["result"].set("已暂停；状态与截图保留")
        self._clear_running_task_labels()
        self.runtime_store.update(agent_state=AgentState.PAUSED.value, runtime_thread_alive=False, scheduler_loop_alive=False, stop_reason="USER_PAUSED")
        self._append("智能体已暂停。"); self._idle_buttons()

    def stop(self) -> None:
        self.stop_requested = True; self.paused = False; self.starting = False; self._cancel_repeat()
        if self.process is not None and self.process.poll() is None: self.process.terminate()
        self.values["agent"].set("● 等待"); self.values["mode"].set("停止"); self.values["result"].set("用户停止")
        self._clear_running_task_labels(); self._append("智能体已停止。"); self._idle_buttons()
        self.runtime_store.update(agent_state=AgentState.IDLE.value, runtime_thread_alive=False, scheduler_loop_alive=False, stop_reason="USER_STOPPED")

    def _cancel_repeat(self) -> None:
        if self.repeat_after_id: self.root.after_cancel(self.repeat_after_id); self.repeat_after_id = None

    def _drain_events(self) -> None:
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "refresh": self._apply_world(*data)
                elif kind == "complete": self._apply_complete(*data)
                elif kind == "note":
                    self._append(str(data))
                elif kind == "worker_failure":
                    self._handle_worker_failure(data)
                else:
                    self._handle_runtime_error(str(data))
        except queue.Empty: pass
        self.root.after(100, self._drain_events)

    def _handle_worker_failure(self, data: dict) -> None:
        """Route a worker death by classification instead of one blunt counter.

        ``ENVIRONMENT`` failures (emulator down, ADB dropped, operator stop) are
        recoverable conditions that the operator has to fix or simply retry, so
        they restart the watchdog but do not inflate ``unexpected_worker_exits``.
        A ``WORKER_CRASH`` is a defect in the worker itself, is counted, and has
        already been written to ``learning/control_panel/crashes/`` with a full
        traceback and the runtime state at the moment of death.
        """
        message = str(data.get("message", ""))
        classification = str(data.get("classification", "WORKER_CRASH"))
        report = data.get("crash_report")
        fatal = is_fatal_stop(message)
        previous = self.runtime_store.read()
        # One rule for the counter, shared with _handle_runtime_error below.
        counts_as_exit = counts_as_unexpected_worker_exit(
            classification=classification, message=message, stop_requested=self.stop_requested
        )
        self.runtime_store.update(
            agent_state=AgentState.FATAL_STOPPED.value if fatal else AgentState.DEGRADED.value,
            runtime_thread_alive=False, scheduler_loop_alive=False, stop_reason=message,
            last_fatal_error=message if fatal else previous.last_fatal_error,
            unexpected_worker_exits=previous.unexpected_worker_exits + (1 if counts_as_exit else 0),
        )
        self.values["runtime_state"].set("异常"); self.values["result"].set(message)
        self._append(f"⚠ {message}（{classification}）")
        if report: self._append(f"  根因证据：{report}")
        self._idle_buttons(); self._clear_running_task_labels()
        if self.continuous.get() and not fatal and not self.stop_requested and not self.paused:
            self.runtime_store.update(watchdog_restart_count=previous.watchdog_restart_count + 1)
            self.repeat_after_id = self.root.after(5000, self.start)
            self._waiting_buttons(); self._append("Watchdog 将在 5 秒后恢复唯一 Runtime。")

    def _handle_runtime_error(self, message: str) -> None:
        """Handle an event that is NOT a worker death.

        This is the fallback for every event kind the drain loop does not
        recognise, so by construction it never carries a worker verdict.  It
        used to increment ``unexpected_worker_exits`` for every non-fatal
        message, which is why the counter could not be driven to zero by fixing
        crashes (RR-001).  It now asks the same question as
        ``_handle_worker_failure`` and answers it honestly: this event has no
        worker classification, so it is not a worker exit.

        The reason is recorded as ``stop_reason`` either way -- declining to
        count something is not the same as hiding it, and the counter is not the
        only record.
        """
        fatal = is_fatal_stop(message)
        previous = self.runtime_store.read()
        counts_as_exit = counts_as_unexpected_worker_exit(
            classification=UNCLASSIFIED_EVENT, message=message, stop_requested=self.stop_requested
        )
        self.runtime_store.update(
            agent_state=AgentState.FATAL_STOPPED.value if fatal else AgentState.DEGRADED.value,
            runtime_thread_alive=False, scheduler_loop_alive=False, stop_reason=message,
            last_fatal_error=message if fatal else previous.last_fatal_error,
            unexpected_worker_exits=previous.unexpected_worker_exits + (1 if counts_as_exit else 0),
        )
        self.values["runtime_state"].set("异常"); self.values["result"].set(message); self._append(f"⚠ {message}")
        self._idle_buttons(); self._clear_running_task_labels()
        if self.continuous.get() and not fatal and not self.stop_requested and not self.paused:
            self.runtime_store.update(watchdog_restart_count=previous.watchdog_restart_count + 1)
            self.repeat_after_id = self.root.after(5000, self.start)
            self._waiting_buttons(); self._append("Watchdog 将在 5 秒后恢复唯一 Runtime。")

    def _apply_world(self, status: Any, world: WorldState, path: Path) -> None:
        self.latest_world, self.latest_image_path = world, path; self.preview_source = Image.open(path).convert("RGB")
        self.values["device"].set("● 已连接")
        expected_package = self.config["device"]["package_name"]
        self.values["game"].set("运行中" if status.foreground_package == expected_package else "未在前台")
        self.values["page"].set(PAGE_ZH.get(world.page.value, world.page.value) if world.known else UNKNOWN_NOW)
        self.values["confidence"].set(f"{world.confidence:.0%}")
        self.values["runtime_state"].set("执行中" if world.known else UNKNOWN_NOW)
        self._refresh_event_goal_display()
        self._refresh_goal_board()
        self._refresh_coverage()
        march = f"{world.march_used}/{world.march_max}" if world.march_used is not None and world.march_max is not None else "暂无数据"
        self.values["march"].set(f"行军：{march}"); self.queues["行军"].set(march)
        for name, value in (("建筑", world.building), ("科技", world.research), ("训练", world.training), ("Intel", world.intel), ("联盟", world.alliance)):
            self.queues[name].set(self._compact(value))
        marches = "、".join(MARCH_ZH.get(m, "未识别") for m in world.marches) or "暂无队列明细"
        self.preview_meta.set(f"页面：{PAGE_ZH.get(world.page.value, world.page.value)} · 行军：{marches}")
        if self.process is None and not self.paused: self.values["agent"].set("● 等待")
        self._render_preview(); self._append(f"识别完成：{PAGE_ZH.get(world.page.value, world.page.value)}，置信度 {world.confidence:.0%}。")

    @staticmethod
    def _compact(value: dict[str, Any]) -> str:
        if not value: return PENDING
        for key in ("status", "state", "available", "claimable", "queue"):
            if key in value: return human_reason(value[key])
        return f"已识别 {len(value)} 项"

    def _apply_complete(self, code: int, payload: dict, output: str) -> None:
        summary = summarize_runtime_result(payload, code); steps = payload.get("steps", []) if isinstance(payload, dict) else []
        last = steps[-1] if steps else {}; decision = last.get("decision", {}) if isinstance(last, dict) else {}; verification = last.get("verification", {}) if isinstance(last, dict) else {}
        skill = decision.get("skill", "GATHER_RESOURCE") if isinstance(decision, dict) else "GATHER_RESOURCE"
        self.values["skill"].set(skill); self.values["task_cn"].set(SKILL_ZH.get(skill, "资源采集")); self.values["reason"].set(human_reason(decision.get("reason") if isinstance(decision, dict) else None))
        self.values["next"].set("等待下一轮状态观察" if summary["ok"] else "进入安全恢复或停止")
        self.values["verifier"].set(("验证通过" if verification.get("ok") else human_reason(verification.get("reason"))) if isinstance(verification, dict) and verification else "本轮无最终验证数据")
        self.values["result"].set(human_reason(summary["reason"])); self.values["agent"].set("● 等待" if summary["ok"] else "● 异常")
        self.session["runs"] += 1; self.session["actions"] += summary["executed"]; self.session["success" if summary["ok"] else "failed"] += 1
        self.values["stats"].set(f"本次启动：{self.session['runs']} 轮 · {self.session['actions']} 动作 · 成功 {self.session['success']} · 异常 {self.session['failed']}")
        self._append(("✓ " if summary["ok"] else "⚠ ") + f"本轮结束：{human_reason(summary['reason'])}")
        # Full structured output belongs only in latest.log. Rendering large
        # JSON blobs in Tk made the UI appear flooded and could stall it.
        self._idle_buttons(); self._enforce_retention(); self.refresh()
        fatal = is_fatal_stop(str(summary["reason"]))
        self.runtime_store.update(agent_state=AgentState.FATAL_STOPPED.value if fatal else (AgentState.IDLE.value if summary["ok"] else AgentState.DEGRADED.value),
                                  runtime_thread_alive=False, scheduler_loop_alive=False, stop_reason=summary["reason"],
                                  last_fatal_error=summary["reason"] if fatal else None)
        if self.continuous.get() and not fatal and not self.stop_requested and not self.paused:
            full_queue = summary["reason"] in {"no_idle_march", "reserved_march_for_stamina"}
            delay_ms = 600000 if full_queue else 30000
            delay_text = "10 分钟" if full_queue else "30 秒"
            self.values["mode"].set("等待")
            self.repeat_after_id = self.root.after(delay_ms, self.start)
            self._waiting_buttons()
            self._append(f"连续运行已启用，{delay_text}后进入下一轮。")

    def _enforce_retention(self) -> None:
        policy = self.config.get("retention", {})
        if not policy.get("auto_prune", False):
            return
        removed = prune_runtime_screenshots(
            CAPTURE_ROOT,
            max_count=int(policy.get("max_screenshots", 500)),
            ttl_days=int(policy.get("screenshot_ttl_days", 14)),
        )
        if removed:
            self._append(f"磁盘保护：已清理 {len(removed)} 张过期或超额运行截图。")

    def _render_preview(self) -> None:
        if self.preview_source is None or not hasattr(self, "preview"): return
        width, height = max(260, self.preview.winfo_width() - 8), max(300, self.preview.winfo_height() - 8)
        image = self.preview_source.copy(); mode = self.preview_mode.get()
        if mode != "原始画面":
            ImageDraw.Draw(image).rectangle((3, 3, image.width - 4, image.height - 4), outline=(83, 183, 255), width=5)
            if mode == "OCR": self.preview_meta.set("OCR：当前 World State 未提供区域坐标；未伪造识别框")
            elif mode == "Vision": self.preview_meta.set("Vision：真实识别摘要；当前结果未提供检测框坐标")
            else: self.preview_meta.set(self._recognition())
        image.thumbnail((width, height), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (width, height), "#070b10"); canvas.paste(image, ((width-image.width)//2, (height-image.height)//2))
        self.preview_photo = ImageTk.PhotoImage(canvas); self.preview.configure(image=self.preview_photo, text="")

    def _recognition(self) -> str:
        w = self.latest_world
        if w is None: return "识别结果：暂无数据"
        parts = [f"页面 {PAGE_ZH.get(w.page.value, w.page.value)}", f"置信度 {w.confidence:.0%}"]
        if w.resource_selected: parts.append(f"资源 {w.resource_selected}")
        if w.popup: parts.append(f"弹窗 {w.popup}")
        return "识别结果：" + " · ".join(parts)

    def _running_buttons(self) -> None:
        self.start_button.configure(state="disabled"); self.pause_button.configure(state="normal"); self.stop_button.configure(state="normal")

    def _idle_buttons(self) -> None:
        self.start_button.configure(state="normal"); self.pause_button.configure(state="disabled"); self.stop_button.configure(state="disabled")

    def _waiting_buttons(self) -> None:
        """A scheduled unattended run must remain cancellable from the UI."""
        self.start_button.configure(state="disabled")
        self.pause_button.configure(state="normal")
        self.stop_button.configure(state="normal")

    def _clear_running_task_labels(self) -> None:
        for name, value in self.today.items():
            if value.get() == "运行中":
                value.set("待识别")

    def _open(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True); os.startfile(path)

    def open_latest(self) -> None:
        if self.latest_image_path and self.latest_image_path.exists(): os.startfile(self.latest_image_path)
        else: self.values["result"].set("暂无可打开的截图")

    def close(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
        # The gateway poller is a daemon thread, so the process would exit anyway --
        # stopping it explicitly keeps a closing window from making one last request.
        self.gateway.stop()
        self._cancel_repeat(); self.root.destroy()


def main() -> int:
    if not _acquire_single_instance():
        return 0
    root = tk.Tk(); panel = ControlPanel(root)
    if panel.config.get("auto_execution", False):
        root.after(1200, panel.start)
    root.mainloop(); return 0


if __name__ == "__main__":
    raise SystemExit(main())
