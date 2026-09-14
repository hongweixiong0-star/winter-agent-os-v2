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

from winter_agent_v2.device import ADBDevice
from winter_agent_v2.models import MarchState, Page, SkillState, WorldState
from winter_agent_v2.retention import prune_runtime_screenshots
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.runtime_snapshot import AgentState, RuntimeSnapshotStore, is_fatal_stop

CONFIG_PATH = ROOT / "config/v2.json"
PANEL_STATE_PATH = ROOT / "config/control_panel_state.json"
PYTHON_PATH = Path(sys.executable).with_name("python.exe")
RUNTIME_PATH = ROOT / "tools/run_live.py"
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
    "SCREENSHOT_NOT_PNG", "SCREENSHOT_DAMAGED",
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
        defaults = {"agent": "● 等待", "device": "检查中", "game": "暂无数据", "page": "页面未识别",
                    "mode": "停止", "qwen": "按需待命", "vision": "等待截图", "clock": "--:--:--",
                    "march": "行军：暂无数据", "task_cn": "等待启动", "skill": "暂无数据",
                    "reason": "尚未产生决策", "preconditions": "未知 / 待识别", "next": "截图并识别当前页面", "risk": "未知",
                    "confidence": "暂无数据",
                    "verifier": "等待任务执行", "result": "尚未运行", "stats": "本次启动：0 轮 · 0 动作"}
        self.values = {k: tk.StringVar(value=v) for k, v in defaults.items()}
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
        for i, (label, key) in enumerate((("智能体", "agent"), ("MuMu", "device"), ("游戏", "game"), ("页面", "page"),
                                          ("模式", "mode"), ("Qwen", "qwen"), ("Vision", "vision"), ("时间", "clock"))):
            cell = ttk.Frame(status, style="Card.TFrame"); cell.grid(row=0, column=i, padx=7, sticky="w")
            ttk.Label(cell, text=label, style="Muted.TLabel", background=PANEL).pack(anchor="w")
            ttk.Label(cell, textvariable=self.values[key], background=PANEL).pack(anchor="w")
        self.tabs = ttk.Notebook(shell); self.tabs.pack(fill="both", expand=True, pady=(10, 0))
        self._overview(); self._goals(); self._strategy(); self._event_goal(); self._capabilities(); self._learning_center(); self._system()

    def _tab(self, name: str) -> ttk.Frame:
        f = ttk.Frame(self.tabs, padding=10); self.tabs.add(f, text=name); return f

    def _overview(self) -> None:
        tab = self._tab("总览"); tab.rowconfigure(0, weight=1); tab.columnconfigure(1, weight=1)
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
            self.today[task] = tk.StringVar(value="未知 / 待识别")
            ttk.Label(row, textvariable=self.today[task], style="Muted.TLabel", background=PANEL).pack(side="right")
        bar = ttk.Frame(center, style="Card.TFrame"); bar.pack(fill="x", pady=(0, 8))
        ttk.Label(bar, text="游戏实时画面", style="Section.TLabel", background=PANEL).pack(side="left")
        choice = ttk.Combobox(bar, textvariable=self.preview_mode, values=("原始画面", "Vision", "OCR", "识别结果"), width=12, state="readonly")
        choice.pack(side="right"); choice.bind("<<ComboboxSelected>>", lambda _e: self._render_preview())
        self.preview = tk.Label(center, text="正在获取 MuMu 截图…", bg="#070b10", fg=MUTED, font=("Microsoft YaHei UI", 11))
        self.preview.pack(fill="both", expand=True); self.preview.bind("<Configure>", lambda _e: self._render_preview())
        self.preview_meta = tk.StringVar(value="暂无识别数据")
        ttk.Label(center, textvariable=self.preview_meta, style="Muted.TLabel", background=PANEL).pack(anchor="w", pady=(8, 0))
        ttk.Label(right, text="当前决策", style="Section.TLabel", background=PANEL).pack(anchor="w")
        for label, key, style in (("当前 Goal", "task_cn", "Value.TLabel"), ("当前 Universal Skill", "skill", "Muted.TLabel"),
                                  ("当前状态", "page", "Value.TLabel"), ("为什么执行", "reason", "TLabel"),
                                  ("Preconditions", "preconditions", "TLabel"), ("Verifier", "verifier", "TLabel"),
                                  ("下一步", "next", "TLabel"), ("风险", "risk", "TLabel"),
                                  ("置信度", "confidence", "Value.TLabel")):
            ttk.Label(right, text=label, style="Muted.TLabel", background=PANEL).pack(anchor="w", pady=(12, 1))
            ttk.Label(right, textvariable=self.values[key], style=style, background=PANEL, wraplength=235, justify="left").pack(anchor="w")
        ttk.Label(right, textvariable=self.values["stats"], style="Muted.TLabel", background=PANEL, wraplength=235).pack(anchor="w", side="bottom")
        cards = ttk.Frame(tab, style="Card.TFrame", padding=10); cards.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        self.queues: dict[str, tk.StringVar] = {}
        for i, name in enumerate(("行军", "建筑", "科技", "训练", "Intel", "联盟", "活动")):
            card = ttk.Frame(cards, style="Card2.TFrame", padding=(14, 8)); card.grid(row=0, column=i, sticky="ew", padx=4); cards.columnconfigure(i, weight=1)
            ttk.Label(card, text=name, style="Muted.TLabel", background=PANEL2).pack(anchor="w")
            self.queues[name] = tk.StringVar(value="未知 / 待识别"); ttk.Label(card, textvariable=self.queues[name], style="Value.TLabel", background=PANEL2).pack(anchor="w")
        bottom = ttk.Frame(tab, style="Card.TFrame", padding=10); bottom.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(10, 0))
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
        statuses = {"READY":"待执行", "IN_PROGRESS":"进行中", "COMPLETE":"✓ 完成", "BLOCKED":"暂时阻塞", "UNKNOWN":"未知", "DISCOVERED":"已发现"}
        goals = snapshot.get("goals", [])
        if not goals:
            self.goal_board.insert("", "end", values=("等待下一次可验证 Goal", "运行时", "—", "未知 / 待识别", "—", "—", "观察 WorldState", "当前页面信息不足", "Vision / GoalLibrary", f"{float(snapshot.get('confidence',0)):.0%}"))
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
        tab = self._tab("活动")
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
        tab = self._tab("能力")
        ttk.Label(tab, text="Universal Skill 与自动化覆盖", style="Title.TLabel").pack(anchor="w", pady=(5, 4))
        ttk.Label(tab, text="默认展示 Universal Skill；组合能力、活动适配器、Legacy 仅作为折叠分层，不定义主架构。", style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        summary = ttk.Frame(tab, style="Card.TFrame", padding=12); summary.pack(fill="x")
        self.capability_summary = {key: tk.StringVar(value="待统计") for key in ("live", "stable", "coverage", "success")}
        for index, (key, label) in enumerate((("live", "Live Verified Skills"), ("stable", "Stable Skills"), ("coverage", "P0/P1 Goal Coverage"), ("success", "Real Success Rate"))):
            card = ttk.Frame(summary, style="Card2.TFrame", padding=12); card.grid(row=0, column=index, sticky="ew", padx=4); summary.columnconfigure(index, weight=1)
            ttk.Label(card, text=label, style="Muted.TLabel", background=PANEL2).pack(anchor="w")
            ttk.Label(card, textvariable=self.capability_summary[key], style="Value.TLabel", background=PANEL2).pack(anchor="w")
        self.skill_tree = ttk.Treeview(tab, columns=("layer", "skill", "goal", "params", "verifier", "recovery", "risk", "latency", "lifecycle", "live", "robust"), show="headings", height=16)
        columns = (("layer", "层级", 105), ("skill", "Universal Skill", 185), ("goal", "Semantic Goal", 170),
                   ("params", "Parameters", 110), ("verifier", "Verifier", 140), ("recovery", "Recovery", 110),
                   ("risk", "Risk", 70), ("latency", "Latency", 70), ("lifecycle", "Lifecycle", 95),
                   ("live", "Live Success", 90), ("robust", "语义稳健性", 110))
        for key, title, width in columns: self.skill_tree.heading(key, text=title); self.skill_tree.column(key, width=width, anchor="w")
        self.skill_tree.pack(fill="both", expand=True, pady=(10, 0))
        runtime_quality = ttk.Frame(tab, style="Card.TFrame", padding=8); runtime_quality.pack(fill="x", pady=(8, 0))
        self.runtime_quality_vars = {key: tk.StringVar(value="待统计") for key in ("success24", "recovery", "exit", "latency")}
        for index, (key, label) in enumerate((("success24", "24h Skill Success"), ("recovery", "Recovery Success"), ("exit", "Unexpected Worker Exit"), ("latency", "Average Realtime Latency"))):
            ttk.Label(runtime_quality, text=label, style="Muted.TLabel", background=PANEL).grid(row=0, column=index, sticky="w", padx=8)
            ttk.Label(runtime_quality, textvariable=self.runtime_quality_vars[key], background=PANEL).grid(row=1, column=index, sticky="w", padx=8); runtime_quality.columnconfigure(index, weight=1)
        self._refresh_capabilities()

    def _refresh_capabilities(self) -> None:
        if not hasattr(self, "skill_tree"): return
        universal_ids = {"CLAIM_REWARD", "NAVIGATE_TO", "SEND_MARCH", "START_RALLY", "JOIN_RALLY", "START_BUILD", "START_RESEARCH", "TRAIN_OR_PROMOTE", "USE_ACTIVITY_ATTEMPT", "READ_EVENT_STATE", "OPEN_HOME", "OPEN_MAP", "BACK", "CLOSE_POPUP", "DISPATCH_MARCH"}
        episodes: dict[str, list[bool]] = {}
        recent_results: list[bool] = []
        recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        try:
            for line in (ROOT / "learning/episodes.jsonl").read_text(encoding="utf-8").splitlines():
                item = json.loads(line); success = item.get("result") == "SUCCESS"; episodes.setdefault(str(item.get("skill")), []).append(success)
                try:
                    recorded = datetime.fromisoformat(str(item.get("recorded_at", "")).replace("Z", "+00:00"))
                    if recorded >= recent_cutoff: recent_results.append(success)
                except ValueError: pass
        except (OSError, json.JSONDecodeError): pass
        for row in self.skill_tree.get_children(): self.skill_tree.delete(row)
        live_verified = stable = 0
        for skill in self.registry.all():
            layer = "Universal" if skill.id in universal_ids else ("Event Adapter" if any(k in skill.id for k in ("BEAR", "EVENT")) else "Composite")
            results = episodes.get(skill.id, [])
            live = (f"{sum(results)}/{len(results)}" if results else "未实机")
            if results and any(results): live_verified += 1
            if skill.state is SkillState.STABLE: stable += 1
            verifier = "状态变化" if skill.id in getattr(__import__("winter_agent_v2.runtime", fromlist=["LiveRuntime"]).LiveRuntime, "VERIFIED_ATOMIC", {}) else "待接入"
            robust = "通过" if skill.state is SkillState.STABLE else ("警告：待语义 Gate" if layer == "Universal" else "—")
            self.skill_tree.insert("", "end", values=(layer, skill.id, skill.description, "参数化", verifier, "标准恢复", skill.risk, "按场景", skill.state.value, live, robust))
        total_results = [ok for values in episodes.values() for ok in values]
        self.capability_summary["live"].set(str(live_verified)); self.capability_summary["stable"].set(str(stable))
        self.capability_summary["success"].set(f"{sum(total_results)/len(total_results):.1%}" if total_results else "无真实样本")
        if hasattr(self, "runtime_quality_vars"):
            durations = []
            try:
                for line in (ROOT / "learning/episodes.jsonl").read_text(encoding="utf-8").splitlines():
                    episode = json.loads(line)
                    if isinstance(episode.get("duration"), (int, float)): durations.append(float(episode["duration"]))
            except (OSError, json.JSONDecodeError): pass
            snapshot = self.runtime_store.read()
            self.runtime_quality_vars["success24"].set(f"{sum(recent_results)}/{len(recent_results)}" if recent_results else "无24h时间戳样本")
            self.runtime_quality_vars["recovery"].set(f"{snapshot.watchdog_restart_count} 次重启")
            self.runtime_quality_vars["exit"].set(str(snapshot.unexpected_worker_exits))
            self.runtime_quality_vars["latency"].set(f"{sum(durations)/len(durations):.1f}s" if durations else "待统计")
        try:
            audit = json.loads((ROOT / "learning/goal_coverage.json").read_text(encoding="utf-8")); value = audit.get("summary", {}).get("automated_percent")
            high = [goal for goal in audit.get("goals", []) if int(goal.get("goal_priority", 0)) >= 9]
            high_verified = sum(goal.get("status") == "AUTOMATED_VERIFIED" for goal in high)
            self.capability_summary["coverage"].set(f"{high_verified}/{len(high)}" if high else "待统计")
        except (OSError, json.JSONDecodeError, TypeError, ValueError): self.capability_summary["coverage"].set("待统计")

    def _skills(self) -> None:
        tab = self._tab("能力"); ttk.Label(tab, text="能力目录", style="Title.TLabel").pack(anchor="w", pady=(5, 10))
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

    def _learning(self) -> None:
        tab = self._tab("学习"); ttk.Label(tab, text="学习与改进", style="Title.TLabel").pack(anchor="w", pady=(5, 4))
        ttk.Label(tab, text="来自现有 Episode；这里不直接修改 Production。", style="Muted.TLabel").pack(anchor="w", pady=(0, 16))
        text = tk.Text(tab, bg=PANEL, fg=TEXT, relief="flat", font=("Microsoft YaHei UI", 10), padx=16, pady=14); text.pack(fill="both", expand=True)
        counts: Counter[str] = Counter(); total = 0
        try:
            for line in (ROOT / "learning/episodes.jsonl").read_text(encoding="utf-8").splitlines():
                item = json.loads(line); total += 1
                if item.get("failure_type"): counts[str(item["failure_type"])] += 1
        except (OSError, json.JSONDecodeError): pass
        lines = [f"已记录 Episode：{total}", "", "最近失败分类"] + ([f"  {human_reason(k)}  {v}" for k, v in counts.most_common(8)] or ["  暂无失败数据"])
        text.insert("1.0", "\n".join(lines)); text.configure(state="disabled")

    def _learning_center(self) -> None:
        tab = self._tab("学习")
        ttk.Label(tab, text="学习与问题优先级中心", style="Title.TLabel").pack(anchor="w", pady=(5, 4))
        counts = count_knowledge()
        quality = ttk.Frame(tab, style="Card.TFrame", padding=12); quality.pack(fill="x")
        ttk.Label(quality, text="Knowledge Quality", style="Section.TLabel", background=PANEL).grid(row=0, column=0, columnspan=6, sticky="w")
        labels = (("LIVE_CLIENT", counts.get("Replay", 0)), ("VERIFIED", counts.get("UI 语义", 0)),
                  ("PRIOR", counts.get("游戏知识", 0)), ("CONFLICT", "待审计"), ("OUTDATED", "待审计"), ("UNKNOWN", "运行中发现"))
        for index, (name, value) in enumerate(labels):
            card = ttk.Frame(quality, style="Card2.TFrame", padding=10); card.grid(row=1, column=index, sticky="ew", padx=3, pady=(8, 0)); quality.columnconfigure(index, weight=1)
            ttk.Label(card, text=name, style="Muted.TLabel", background=PANEL2).pack(anchor="w"); ttk.Label(card, text=str(value), background=PANEL2).pack(anchor="w")
        notes = ttk.Frame(tab, style="Card.TFrame", padding=12); notes.pack(fill="x", pady=(10, 0))
        for i, (label, value) in enumerate((("最近学会", "从 Live Verifier 成功记录更新"), ("最近纠正", "从 Knowledge correction 记录更新"),
                                            ("当前冲突", "待 Knowledge Audit 刷新"), ("阻塞 Goal 的 UNKNOWN", "从 Runtime Failure 自动聚合"))):
            ttk.Label(notes, text=label, style="Muted.TLabel", background=PANEL, width=22).grid(row=i, column=0, sticky="w", pady=3)
            ttk.Label(notes, text=value, background=PANEL).grid(row=i, column=1, sticky="w", pady=3)
        self.failure_tree = ttk.Treeview(tab, columns=("type", "count", "goals", "priority", "last", "status", "repair"), show="headings", height=10)
        for key, title, width in (("type", "问题", 245), ("count", "次数", 60), ("goals", "影响目标", 170), ("priority", "优先级", 75), ("last", "最近出现", 160), ("status", "状态", 90), ("repair", "修复状态", 130)):
            self.failure_tree.heading(key, text=title); self.failure_tree.column(key, width=width, anchor="w")
        self.failure_tree.pack(fill="both", expand=True, pady=(10, 0)); self._refresh_learning_center()

    def _refresh_learning_center(self) -> None:
        if not hasattr(self, "failure_tree"): return
        rows: dict[str, dict[str, Any]] = {}
        try:
            for line in (ROOT / "learning/episodes.jsonl").read_text(encoding="utf-8").splitlines():
                item = json.loads(line); failure = item.get("failure_type")
                if not failure: continue
                row = rows.setdefault(str(failure), {"count": 0, "last": "—", "goals": set()}); row["count"] += 1
                row["last"] = item.get("created_at", item.get("timestamp", "最近")); row["goals"].add(str(item.get("goal", "当前 Goal")))
        except (OSError, json.JSONDecodeError): pass
        for item in self.failure_tree.get_children(): self.failure_tree.delete(item)
        for failure, row in sorted(rows.items(), key=lambda pair: pair[1]["count"], reverse=True)[:15]:
            priority = "P0" if row["count"] >= 10 else ("P1" if row["count"] >= 3 else "P2")
            self.failure_tree.insert("", "end", values=(human_reason(failure), row["count"], ", ".join(row["goals"]), priority, row["last"], "已分类", "待候选修复"))

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
        self.values["agent"].set(names.get(snapshot.agent_state, snapshot.agent_state))
        self.values["page"].set(PAGE_ZH.get(snapshot.page, snapshot.page or "未知 / 待识别"))
        self.values["task_cn"].set("自动目标发现" if snapshot.current_goal == "AUTO_DISCOVERY" else (snapshot.current_goal or "未知 / 待识别"))
        self.values["skill"].set(snapshot.current_skill or "未知 / 待识别")
        self.values["reason"].set(human_reason(snapshot.reason)); self.values["preconditions"].set(" · ".join(snapshot.preconditions) or "待 Runtime 提供")
        self.values["verifier"].set(human_reason(snapshot.verifier)); self.values["next"].set(human_reason(snapshot.next_action)); self.values["risk"].set(snapshot.risk)
        self.values["confidence"].set(f"{snapshot.confidence:.0%}")
        self.values["mode"].set("自动运行" if snapshot.agent_state in {"AUTO_RUNNING", "GOAL_RUNNING", "RECOVERING"} else ("暂停" if snapshot.agent_state == "PAUSED" else "等待"))
        self.values["vision"].set("● 正常" if snapshot.vision == "READY" else "● 待识别")
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
        self._refresh_capabilities(); self._refresh_learning_center()
        if schedule_next: self.root.after(1500, self._refresh_runtime_snapshot)

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
        self._append("已从统一 Runtime Snapshot 刷新；GUI 未调用 OCR/Qwen。")

    def take_screenshot(self) -> None:
        self._append("截图由 Runtime 统一采集；已显示最新 Runtime Evidence。"); self.refresh()

    def _refresh_worker(self) -> None:
        self.events.put(("note", "状态由 Runtime Snapshot 统一提供。"))

    def start(self) -> None:
        if self.process is not None or self.starting: return
        self.starting = True
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
            self.active_panel_task = "AUTO"
            self._ensure_device()
            if self.stop_requested: return
            LOG_ROOT.mkdir(parents=True, exist_ok=True); CAPTURE_ROOT.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            command = [str(PYTHON_PATH), str(RUNTIME_PATH), "--max-actions", "24",
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
            cmd = [str(PYTHON_PATH), str(RUNTIME_PATH), "--max-actions", "12", "--goal", goal, "--capture-dir", str(CAPTURE_ROOT / capture_name / run_stamp)]
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
                fallback = [str(PYTHON_PATH), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "DAILY", "--capture-dir", str(CAPTURE_ROOT / "runtime_daily" / fallback_stamp)]
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
                fallback = [str(PYTHON_PATH), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "ALLIANCE", "--capture-dir", str(CAPTURE_ROOT / "runtime_alliance" / fallback_stamp)]
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
                fallback = [str(PYTHON_PATH), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "EXPLORATION", "--capture-dir", str(CAPTURE_ROOT / "runtime_exploration" / fallback_stamp)]
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
                fallback = [str(PYTHON_PATH), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "ALLIANCE", "--capture-dir", str(CAPTURE_ROOT / "runtime_alliance" / fallback_stamp)]
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
                fallback = [str(PYTHON_PATH), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "EXPLORATION", "--capture-dir", str(CAPTURE_ROOT / "runtime_exploration" / fallback_stamp)]
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
                fallback = [str(PYTHON_PATH), str(RUNTIME_PATH), "--max-actions", "10", "--goal", "TRAIN", "--capture-dir", str(CAPTURE_ROOT / "runtime_training" / fallback_stamp)]
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
                fallback = [str(PYTHON_PATH), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "EXPLORATION", "--capture-dir", str(CAPTURE_ROOT / "runtime_exploration" / fallback_stamp)]
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
                fallback = [str(PYTHON_PATH), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "EXPLORATION", "--capture-dir", str(CAPTURE_ROOT / "runtime_exploration" / fallback_stamp)]
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
                fallback = [str(PYTHON_PATH), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "INTEL", "--stop-after", "DISPATCH_INTEL_BEAST", "--capture-dir", str(CAPTURE_ROOT / "runtime_intel" / fallback_stamp)]
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
                fallback = [str(PYTHON_PATH), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "INTEL", "--stop-after", "DISPATCH_INTEL_BEAST", "--capture-dir", str(CAPTURE_ROOT / "runtime_intel" / fallback_stamp)]
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
                fallback = [str(PYTHON_PATH), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "INTEL", "--stop-after", "DISPATCH_INTEL_BEAST", "--capture-dir", str(CAPTURE_ROOT / "runtime_intel" / fallback_stamp)]
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
                fallback = [str(PYTHON_PATH), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "BEAST_HUNT", "--stop-after", "DISPATCH_BEAST", "--capture-dir", str(CAPTURE_ROOT / "runtime_beast" / fallback_stamp)]
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
                fallback = [str(PYTHON_PATH), str(RUNTIME_PATH), "--max-actions", "12", "--goal", "GATHER_RESOURCE", "--stop-after", "DISPATCH_MARCH", "--capture-dir", str(CAPTURE_ROOT / "runtime" / fallback_stamp)]
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
        counts_as_exit = classification == "WORKER_CRASH" and not fatal and not self.stop_requested
        self.runtime_store.update(
            agent_state=AgentState.FATAL_STOPPED.value if fatal else AgentState.DEGRADED.value,
            runtime_thread_alive=False, scheduler_loop_alive=False, stop_reason=message,
            last_fatal_error=message if fatal else previous.last_fatal_error,
            unexpected_worker_exits=previous.unexpected_worker_exits + (1 if counts_as_exit else 0),
        )
        self.values["vision"].set("异常"); self.values["result"].set(message)
        self._append(f"⚠ {message}（{classification}）")
        if report: self._append(f"  根因证据：{report}")
        self._idle_buttons(); self._clear_running_task_labels()
        if self.continuous.get() and not fatal and not self.stop_requested and not self.paused:
            self.runtime_store.update(watchdog_restart_count=previous.watchdog_restart_count + 1)
            self.repeat_after_id = self.root.after(5000, self.start)
            self._waiting_buttons(); self._append("Watchdog 将在 5 秒后恢复唯一 Runtime。")

    def _handle_runtime_error(self, message: str) -> None:
        fatal = is_fatal_stop(message)
        previous = self.runtime_store.read()
        self.runtime_store.update(
            agent_state=AgentState.FATAL_STOPPED.value if fatal else AgentState.DEGRADED.value,
            runtime_thread_alive=False, scheduler_loop_alive=False, stop_reason=message,
            last_fatal_error=message if fatal else previous.last_fatal_error,
            unexpected_worker_exits=previous.unexpected_worker_exits + (0 if fatal else 1),
        )
        self.values["vision"].set("异常"); self.values["result"].set(message); self._append(f"⚠ {message}")
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
        self.values["page"].set(PAGE_ZH.get(world.page.value, world.page.value)); self.values["vision"].set("● 正常" if world.known else "● 未识别")
        self.values["confidence"].set(f"{world.confidence:.0%}")
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
        if not value: return "未知 / 待识别"
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
