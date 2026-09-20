"""The gateway's 15-minute acceptance, run by the GUI rather than by a developer's shell.

Why this exists
---------------
The operator's §三 is explicit: the acceptance target must be the *production* GUI process.
Every previous attempt to prove "15 minutes unattended" was made from a development-tool
shell, and every process launched that way was reaped when the call ended -- measured
2026-09-18, panels 24936/25408 and gateways 5184/9576/11960/13764/15140/15552/4088 all dead
with the call that started them.  That is a property of the development host, not of
Winter Agent, and it is recorded here as ``DEVELOPMENT_ENV_LIMITATION`` rather than papered
over with detach or WMI tricks (§九: the product must not grow workarounds for the tooling
that builds it).

So the measurement moves into the product: once the GUI is running from its real launch
path, it samples its own facts for fifteen minutes and writes the verdict itself.  The
operator starts the GUI once; nothing else is asked of them.

What it is not
--------------
Not a second truth store.  Every field comes from an artifact that already exists -- the
panel's gateway probe, ``gateway_service.json``, ``pump.json``, ``runtime_snapshot.json``,
the escalation ledger -- and the output is one evidence file under ``evidence/``, beside
the project's other evidence rather than in a store of its own.  It also decides nothing:
it records and grades, and the twelve conditions it grades are the operator's, quoted.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

#: The operator's §二 window.
WINDOW_SECONDS = 900.0

#: Where the verdict lands.  Under ``evidence/`` so it sits beside the project's other
#: evidence and is picked up by the existing index, rather than in a store of its own.
EVIDENCE_RELATIVE = "evidence/gui_workbuddy_loop/latest.json"

#: A gateway may restart, but not in a loop: §二 condition 5.  Three in fifteen minutes is
#: generous for a service that should restart only when it dies, and small enough that
#: "every sample shows a new pid" is caught.
MAX_RESTARTS = 3

#: Health may dip while a restart is in flight, but the operator asked for "持续可达": 95% of
#: samples reachable, and reachable at the end.
MIN_HEALTH_RATIO = 0.95

#: ``pump.json`` is written every tick (30s); 90s is the same staleness the project already
#: uses for "the panel is running".
PUMP_FRESH_SECONDS = 90.0

#: Names of the twelve conditions, in the operator's order.  Kept as one tuple so the
#: record, the verdict and the GUI card cannot disagree about which one is which.
CONDITIONS: tuple[tuple[str, str], ...] = (
    ("gui_alive", "GUI持续存活"),
    ("gateway_reachable", "Gateway持续可达"),
    ("single_gateway", "同时最多一个合法Gateway"),
    ("port_owner_legal", "8080始终由合法Gateway持有"),
    ("no_restart_loop", "Gateway无重启循环"),
    ("pump_ticking", "QueuePump持续tick"),
    ("auto_gameplay", "AUTO继续Gameplay"),
    ("gateway_fault_does_not_block_auto", "Gateway异常不会阻塞AUTO"),
    ("no_duplicate_job", "不出现重复Capability Job"),
    ("no_extra_spawn_per_refresh", "GUI刷新不spawn额外Gateway"),
    ("no_black_console", "无自动黑色命令行窗口"),
    ("topbar_agrees", "Gateway Health与GUI顶部一致"),
)

PASS = "PASS"
FAIL = "FAIL"
INCOMPLETE = "INCOMPLETE"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class GatewaySoak:
    """Samples the GUI's own facts for a window, then grades the twelve conditions.

    ``facts`` is injected and is the only way anything is observed: the panel already
    measures all of it on its probe thread (one HTTP round trip, one port query, one file
    read), so the soak never re-measures and can never disagree with what the window shows.
    That also makes the whole thing testable without a port, a process or a clock.
    """

    def __init__(
        self,
        root: Path,
        *,
        facts: Callable[[], Mapping[str, Any]],
        window_seconds: float = WINDOW_SECONDS,
        sample_every: int = 2,
        evidence_path: Path | None = None,
        console_counter: Callable[[], int] | None = None,
        rounds_completed: Callable[[], int | None] | None = None,
        launch_context: str = "unknown",
        clock: Callable[[], float] | None = None,
        wall: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = Path(root)
        self._facts = facts
        self.window_seconds = float(window_seconds)
        self.sample_every = max(1, int(sample_every))
        self.evidence_path = Path(evidence_path) if evidence_path else (
            self.root / EVIDENCE_RELATIVE
        )
        self._console_counter = console_counter
        self._rounds_completed = rounds_completed
        self.launch_context = launch_context
        self._clock = clock or time.monotonic
        self._wall = wall or _now
        self.started_at: float | None = None
        self.started_wall: str = ""
        self.samples: list[dict[str, Any]] = []
        self._passes = 0
        self._distinct_gateway_pids: set[int] = set()
        self._distinct_gui_pids: set[int] = set()
        self._console_windows = 0
        self._anomalies: list[str] = []
        self._finished_at: float | None = None

    # -- lifecycle ---------------------------------------------------------

    def started(self) -> bool:
        return self.started_at is not None

    @property
    def anomalies(self) -> list[str]:
        """Everything that went wrong while measuring, oldest first.

        Public because it is part of the evidence, not an internal detail: a window whose
        sampler raised, or in which a second gateway appeared, has to be able to say so.
        """
        return list(self._anomalies)

    def finished(self) -> bool:
        return self._finished_at is not None

    def expired(self) -> bool:
        return self.started() and (self._clock() - float(self.started_at)) >= self.window_seconds

    # -- one observation ---------------------------------------------------

    def observe(self, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Take one sample.  Called from the panel's probe thread; never raises.

        A sampling error is recorded as an anomaly and is *not* silently skipped: a soak
        whose sampler died quietly would produce a short window that still looked complete.
        """
        if not self.started():
            self.started_at = self._clock()
            self.started_wall = self._wall().isoformat()
        self._passes += 1
        if (self._passes - 1) % self.sample_every:
            return {}
        try:
            facts = dict(self._facts())
        except Exception as exc:  # noqa: BLE001
            self._anomalies.append(f"{self._wall().isoformat()} 采样失败：{type(exc).__name__}: {exc}")
            return {}

        sample: dict[str, Any] = {
            "at": self._wall().isoformat(),
            "elapsed": round(self._clock() - float(self.started_at), 1),
            "gui_pid": int(facts.get("gui_pid") or 0),
            "gateway_pid": int(facts.get("gateway_pid") or 0),
            "gateway_identity": facts.get("gateway_identity"),
            "port_8080_owner": int(facts.get("port_8080_owner") or 0),
            "port_8080_name": str(facts.get("port_8080_name") or ""),
            "health": facts.get("health"),
            "lifecycle_state": str(facts.get("lifecycle_state") or ""),
            "restart_count": int(facts.get("restart_count") or 0),
            "duplicate_gateway_count": int(facts.get("duplicate_gateway_count") or 0),
            "queue_pump_heartbeat": facts.get("queue_pump_heartbeat"),
            "current_job_id": str(facts.get("current_job_id") or ""),
            "job_state": str(facts.get("job_state") or ""),
            "auto_running": facts.get("auto_running"),
            # The second source for the same condition.  ``auto_running`` is an
            # instantaneous flag read from a snapshot, and an AUTO round is a fresh
            # process, so the flag is true only while a round is mid-flight -- measured
            # ~10% duty against a ~12.5s sample cadence.  A count of *completed* rounds
            # cannot be missed that way: it only ever moves when a round actually ran to
            # its end.
            "auto_rounds": self._read_rounds(),
            "topbar_word": str(facts.get("topbar_word") or ""),
        }
        if extra:
            sample.update(extra)
        if self._console_counter is not None:
            try:
                sample["black_console_count"] = int(self._console_counter())
            except Exception:  # noqa: BLE001
                sample["black_console_count"] = None
        else:
            sample["black_console_count"] = None

        for pid_key, bucket in (("gui_pid", self._distinct_gui_pids),
                                ("gateway_pid", self._distinct_gateway_pids)):
            value = int(sample.get(pid_key) or 0)
            if value:
                bucket.add(value)
        if sample.get("black_console_count"):
            self._console_windows += int(sample["black_console_count"])
        if sample["duplicate_gateway_count"]:
            self._anomalies.append(
                f"{sample['at']} 检测到 {sample['duplicate_gateway_count']} 个额外网关监听 8080"
            )
        if sample["health"] is False:
            self._anomalies.append(
                f"{sample['at']} health 不可达（lifecycle={sample['lifecycle_state']}）"
            )

        self.samples.append(sample)
        self._write()
        return sample

    def _read_rounds(self) -> int | None:
        """Completed AUTO rounds so far, or ``None`` when nothing can count them.

        Never raises: ``observe`` promises the probe thread that it cannot be taken down by
        a counter, and an unreadable counter has to stay distinguishable from a counter that
        read zero -- zero is a measurement, ``None`` is not.
        """
        if self._rounds_completed is None:
            return None
        try:
            return int(self._rounds_completed())
        except Exception:  # noqa: BLE001
            return None

    # -- grading -----------------------------------------------------------

    def _sorted_samples(self) -> list[dict[str, Any]]:
        return list(self.samples)

    def verdict(self) -> dict[str, Any]:
        """The twelve conditions, each ``True`` / ``False`` / ``None`` with its own reason.

        ``None`` is "not measured", and it is deliberately distinct from ``True``: a window
        with no samples, or a fact nobody could read, must not grade as satisfied.  The
        overall verdict follows §二 -- all satisfied is PASS, any unsatisfied is FAIL, and
        anything left unmeasured is INCOMPLETE.
        """
        samples = self._sorted_samples()
        n = len(samples)
        results: dict[str, dict[str, Any]] = {}

        def put(name: str, value: bool | None, reason: str) -> None:
            results[name] = {"ok": value, "reason": reason}

        if not n:
            for name, _ in CONDITIONS:
                put(name, None, "没有采样：验收窗口尚未开始或采样线程未运行")
            return {"overall": INCOMPLETE, "conditions": results,
                    "note": "窗口内 0 个样本，未测量不等于满足"}

        health_true = sum(1 for s in samples if s.get("health") is True)
        ratio = health_true / n
        duplicates = sum(1 for s in samples if int(s.get("duplicate_gateway_count") or 0) > 0)
        restarts = max(int(s.get("restart_count") or 0) for s in samples)
        pump_ages = [s.get("queue_pump_heartbeat") for s in samples]
        pump_ok = [age for age in pump_ages if isinstance(age, (int, float))]
        auto_seen = [s.get("auto_running") for s in samples]
        auto_true = any(v is True for v in auto_seen)
        auto_measured = any(v is not None for v in auto_seen)
        round_counts = [s.get("auto_rounds") for s in samples if isinstance(s.get("auto_rounds"), int)]
        rounds_advanced = bool(round_counts) and (max(round_counts) - min(round_counts) >= 1)
        # Three answers, not two.  AUTO observed running is True; AUTO *measured* and not
        # running is False (the operator asked for "AUTO继续Gameplay" and it is not
        # continuing); and nothing able to measure it at all is None -- unproven.  Grading
        # the third case as False would call a soak failed for a reason it never tested, and
        # grading it as True is the rounding-up this whole file exists to prevent.
        #
        # A round count is a second, strictly stronger source for the same condition.  The
        # instantaneous flag can be true with no round having finished, and -- because it is
        # only true while a round is in flight -- it is false for ~90% of a window in which
        # AUTO is plainly playing.  A count that only advances when a round completed cannot
        # be fooled either way, so it answers True on its own.  It never lowers the bar: two
        # readable counts that do not differ are a *measurement* that nothing completed, and
        # that grades False, not None.
        if len(round_counts) >= 2:
            auto_measured = True
        auto_verdict: bool | None = True if (auto_true or rounds_advanced) else (
            False if auto_measured else None)
        if auto_true:
            auto_reason = "窗口内观察到 AUTO 运行"
        elif rounds_advanced:
            auto_reason = (f"窗口内 AUTO 实际完成 {max(round_counts) - min(round_counts)} 轮"
                           f"（证据流计数 {min(round_counts)} → {max(round_counts)}）")
        elif auto_measured:
            span = f"{round_counts[0]} → {round_counts[-1]}" if round_counts else "无轮次计数可读"
            auto_reason = ("窗口内既未观察到 AUTO 运行，证据流中的 AUTO 轮次计数也没有前进"
                           f"（{span}）")
        else:
            auto_reason = "窗口内读不到 AUTO 状态（未测量：无设备/游戏未就绪时这是未证明，不是通过）"
        put("auto_gameplay", auto_verdict, auto_reason)
        unhealthy = [s for s in samples if s.get("health") is False]
        pump_during_fault = sum(1 for s in unhealthy if isinstance(s.get("queue_pump_heartbeat"), (int, float))
                                and float(s["queue_pump_heartbeat"]) <= PUMP_FRESH_SECONDS)
        consoles = self._console_windows
        measured_consoles = any(s.get("black_console_count") is not None for s in samples)
        topbar = [s for s in samples if s.get("topbar_word")]
        topbar_ok = [s for s in topbar
                     if (s["topbar_word"] in ("正常",)) == (s.get("health") is True)]

        put("gui_alive", all(int(s.get("gui_pid") or 0) > 0 for s in samples),
            f"{n} 个样本中 GUI pid 均已记录" if all(int(s.get("gui_pid") or 0) > 0 for s in samples)
            else "存在没有 GUI pid 的样本")
        put("gateway_reachable", ratio >= MIN_HEALTH_RATIO and samples[-1].get("health") is True,
            f"health 可达 {health_true}/{n} = {ratio:.1%}（阈值 {MIN_HEALTH_RATIO:.0%}），"
            f"末次={samples[-1].get('health')}")
        put("single_gateway", duplicates == 0,
            "全程未出现第二个监听 8080 的进程" if not duplicates
            else f"{duplicates} 个样本检测到额外网关")
        owner_ok = [s for s in samples if s.get("health") is True
                    and int(s.get("port_8080_owner") or 0) == int(s.get("gateway_pid") or 0)]
        put("port_owner_legal", bool(owner_ok) and len(owner_ok) == health_true,
            f"health 正常时端口持有者与记录的网关 pid 一致 {len(owner_ok)}/{health_true}")
        put("no_restart_loop", restarts <= MAX_RESTARTS,
            f"窗口内重启 {restarts} 次（上限 {MAX_RESTARTS}）")
        stale = [age for age in pump_ok if float(age) > PUMP_FRESH_SECONDS]
        put("pump_ticking", bool(pump_ok) and not stale,
            f"{len(pump_ok)} 个样本读到心跳，过期 {len(stale)} 个（阈值 {PUMP_FRESH_SECONDS:.0f}s）"
            if pump_ok else "没有任何样本读到 QueuePump 心跳")
        put("gateway_fault_does_not_block_auto", (pump_during_fault > 0) if unhealthy else True,
            f"网关异常样本 {len(unhealthy)} 个，其中 QueuePump 仍在心跳 {pump_during_fault} 个"
            if unhealthy else "窗口内网关全程可达，无需证明这一点")
        duplicate_jobs: list[str] = []
        for s in samples:
            for capability in (s.get("duplicate_job_capabilities") or ()):
                duplicate_jobs.append(str(capability))
        put("no_duplicate_job", not duplicate_jobs,
            "台账中没有任何 Capability 同时持有两个活跃 Job" if not duplicate_jobs
            else f"发现重复活跃 Job 的 Capability：{sorted(set(duplicate_jobs))}")
        extra_pids = len(self._distinct_gateway_pids) - 1 - restarts
        put("no_extra_spawn_per_refresh", extra_pids <= 0,
            f"窗口内出现过 {len(self._distinct_gateway_pids)} 个网关 pid，重启 {restarts} 次"
            f"（多出 {max(0, extra_pids)} 个无法用重启解释）")
        put("no_black_console", (consoles == 0) if measured_consoles else None,
            f"累计 {consoles} 个属于本进程树的控制台窗口" if measured_consoles
            else "本机/本进程未提供控制台窗口计数（未测量）")
        put("topbar_agrees", (len(topbar_ok) == len(topbar)) if topbar else None,
            f"{len(topbar_ok)}/{len(topbar)} 个样本中顶部措辞与探针一致" if topbar
            else "没有任何样本读到顶部网关措辞（未测量）")

        values = [r["ok"] for r in results.values()]
        if any(v is False for v in values):
            overall = FAIL
        elif any(v is None for v in values):
            overall = INCOMPLETE
        else:
            overall = PASS
        return {"overall": overall, "conditions": results}

    # -- persistence -------------------------------------------------------

    def _write(self) -> None:
        try:
            self.evidence_path.parent.mkdir(parents=True, exist_ok=True)
            self.evidence_path.write_text(
                json.dumps(self.payload(), ensure_ascii=False, indent=1), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001 - an unwritable evidence file must not kill the GUI
            self._anomalies.append(f"{self._wall().isoformat()} 证据写入失败：{type(exc).__name__}: {exc}")

    def payload(self) -> dict[str, Any]:
        """The evidence file.

        Field names follow ``tools/runtime_soak.py``, the project's existing soak, rather
        than inventing a second convention for "a long unattended window was measured":
        ``started_at`` / ``finished_at`` / ``duration_minutes`` / ``sample_count`` /
        ``samples`` mean here what they mean there.
        """
        elapsed = 0.0
        if self.started_at is not None:
            elapsed = float(self._finished_at if self._finished_at is not None else self._clock()) \
                - float(self.started_at)
        return {
            "kind": "GatewaySoakAcceptance",
            "window_seconds": self.window_seconds,
            "started_at": self.started_wall,
            "finished_at": self._wall().isoformat() if self._finished_at is not None else "",
            "generated_at": self._wall().isoformat(),
            "duration_minutes": round(elapsed / 60.0, 2),
            "complete": bool(self.finished()),
            "launch_context": self.launch_context,
            "development_env_limitation": (
                "" if self.launch_context == "production" else
                "DEVELOPMENT_ENV_LIMITATION：本次 GUI 不是从正式启动路径拉起的，"
                "开发工具宿主会在调用结束时回收子进程 —— 这是工具环境限制，不是产品 Runtime 缺陷"
                "（P0 §九）。这种窗口的结论不构成验收证据。"
            ),
            "sample_count": len(self.samples),
            "distinct_gui_pids": sorted(self._distinct_gui_pids),
            "distinct_gateway_pids": sorted(self._distinct_gateway_pids),
            "black_console_windows": self._console_windows,
            "anomalies": self._anomalies[-40:],
            "verdict": self.verdict(),
            "samples": self.samples,
        }

    def close(self) -> dict[str, Any]:
        """Grade and persist one final time.  Safe to call more than once."""
        if self._finished_at is None:
            self._finished_at = self._clock()
        self._write()
        return self.payload()
