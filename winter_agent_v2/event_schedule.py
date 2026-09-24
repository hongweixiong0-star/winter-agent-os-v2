"""When a timed event is expected, per role -- a state file plus pure helpers.

Why this exists
---------------
Task book §五 is precise about what was missing:

    当前 bear_phase() 和 REALTIME 优先级不能代替真正的时间唤醒。

and it is right, and the reason is the direction of the dependency.  Everything the project
had until now read the bear out of **the current frame**: ``rally.bear_phase`` takes
``seconds_to_start`` that the client printed, and ``scheduler._deadline_active`` raises a
rally's priority when the frame already says ``READY``/``ACTIVE``.  Both are correct and both
are *reactive* -- they can only answer once the client is already showing the event, which is
exactly the moment the 30-minute window has started and the preparation time is gone.

A preparation window needs a fact that survives without a frame: "this role's bear is
expected at T".  That is a clock, and a clock is not derivable from a screenshot.

Why it is not a second scheduler
--------------------------------
It is the same shape as ``observation_store``, ``control_experience``, ``stamina_supply`` and
``resource_rotation``: **a JSON state file plus pure functions over it**.  It decides nothing.
It answers one question -- "how far from the event are we, by the clock" -- and the *existing*
``Scheduler`` remains the only thing that ranks goals.  No loop, no timer thread, no second
executor, no parallel manager.

The honesty rule the ledger already states is enforced here rather than restated: a reservation
that was never read stays ``None`` and the phase stays ``IDLE``.  This module will not invent a
start time, because a fabricated clock is worse than no clock -- it would spend real
preparation on a wrong minute.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "learning/timed_event_schedule.json"


class ReadinessPhase(str, Enum):
    """How close the clock says we are.  Ordered: IDLE < T30 < T15 < T5 < T1 < OPEN."""

    IDLE = "IDLE"
    T30 = "T30"
    T15 = "T15"
    T5 = "T5"
    T1 = "T1"
    OPEN = "OPEN"


#: The ladder from the task book §七.2, as machine values.  ``T-30`` is the first rung because
#: that is the earliest preparation the book asks for; the numbers are minutes *before* the
#: reserved start.
#:
#: **Ordered tightest-first, and the order is load-bearing.**  ``readiness_phase`` returns the
#: first rung whose threshold contains the remaining time, so a loosest-first list answers T30
#: for 12 minutes and for 3 minutes alike -- which is not a cosmetic slip: T5 is the rung whose
#: instruction is "ordinary tasks yield at a safe boundary", and returning T30 there means the
#: runtime never yields.  Caught by ``tools/probe_readiness_phase.py`` on the first run.
#:
#: These are the book's defaults, not measurements of this client.  The book says the lead
#: times should be adjusted by the measured cost of a role switch and a queue preparation --
#: ``RoleSchedule.lead_overrides`` is where that adjustment goes once it is measured, and
#: nothing here pretends to have measured it yet.
_PHASE_LADDER: tuple[tuple[int, ReadinessPhase], ...] = (
    (1, ReadinessPhase.T1),
    (5, ReadinessPhase.T5),
    (15, ReadinessPhase.T15),
    (30, ReadinessPhase.T30),
)

#: What each phase is worth to the single Scheduler's ranking.
#:
#: The magnitudes follow the existing convention in ``event_goal.deadline_level`` (a deadline
#: P0 is worth 10x a NORMAL one).  ``T5`` and tighter are deliberately large: at that point the
#: book's instruction is that ordinary work *yields*, and a bonus that only nudges would let a
#: mail sweep outrank the one activity with a 30-minute window.
PHASE_PRIORITY: dict[ReadinessPhase, float] = {
    ReadinessPhase.IDLE: 0.0,
    ReadinessPhase.T30: 40.0,
    ReadinessPhase.T15: 200.0,
    ReadinessPhase.T5: 2000.0,
    ReadinessPhase.T1: 2000.0,
    ReadinessPhase.OPEN: 4000.0,
}


@dataclass
class RoleSchedule:
    """One role's expectation about one event.

    ``reserved_start`` is the only field that can produce a wake, and it is ``None`` until the
    client's own countdown/cooldown has actually been read.  ``source`` records where it came
    from so a reader can tell a client-read reservation from a table someone typed.
    """

    role_id: str
    event_id: str
    reserved_start: str | None = None
    role: str = "AUTO"                      # LEADER | JOINER | AUTO
    alliance: str | None = None
    source: str = "UNKNOWN"
    observed_at: str | None = None
    lead_overrides: dict[str, int] = field(default_factory=dict)
    notes: str = ""

    def start_datetime(self) -> datetime | None:
        if not self.reserved_start:
            return None
        try:
            moment = datetime.fromisoformat(self.reserved_start)
        except ValueError:
            return None
        return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)

    def phase_at(self, now: datetime | None = None) -> ReadinessPhase:
        return readiness_phase(self.minutes_to_start(now))

    def minutes_to_start(self, now: datetime | None = None) -> float | None:
        start = self.start_datetime()
        if start is None:
            return None
        return (start - (now or datetime.now(timezone.utc))).total_seconds() / 60.0

    def priority_bonus(self, now: datetime | None = None) -> float:
        return PHASE_PRIORITY[self.phase_at(now)]

    def as_json(self) -> dict[str, Any]:
        return {
            "role_id": self.role_id,
            "event_id": self.event_id,
            "reserved_start": self.reserved_start,
            "role": self.role,
            "alliance": self.alliance,
            "source": self.source,
            "observed_at": self.observed_at,
            "lead_overrides": dict(self.lead_overrides),
            "notes": self.notes,
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "RoleSchedule":
        overrides = payload.get("lead_overrides")
        return cls(
            role_id=str(payload.get("role_id") or ""),
            event_id=str(payload.get("event_id") or ""),
            reserved_start=(str(payload["reserved_start"])
                            if payload.get("reserved_start") else None),
            role=str(payload.get("role") or "AUTO"),
            alliance=(str(payload["alliance"]) if payload.get("alliance") else None),
            source=str(payload.get("source") or "UNKNOWN"),
            observed_at=(str(payload["observed_at"]) if payload.get("observed_at") else None),
            lead_overrides={str(k): int(v) for k, v in (overrides or {}).items()},
            notes=str(payload.get("notes") or ""),
        )


def readiness_phase(minutes_to_start: float | None) -> ReadinessPhase:
    """Which rung of the §七.2 ladder the clock is on.

    ``None`` -- no trustworthy reservation -- is ``IDLE``, and that is the whole point: the
    honest answer when nothing has been read is "not preparing", never a guess.
    """
    if minutes_to_start is None:
        return ReadinessPhase.IDLE
    if minutes_to_start <= 0:
        return ReadinessPhase.OPEN
    for threshold, phase in _PHASE_LADDER:
        if minutes_to_start <= threshold:
            return phase
    return ReadinessPhase.IDLE


def phase_instruction(phase: ReadinessPhase) -> str:
    """The task book's own wording for each rung, so a log line explains itself."""
    return {
        ReadinessPhase.IDLE: "无预约或未到准备时间",
        ReadinessPhase.T30: "确认预约、设备、角色、预设、队列和执行链",
        ReadinessPhase.T15: "提前处理必要队列，检查导航及角色切换",
        ReadinessPhase.T5: "正确角色 READY，普通任务安全让位",
        ReadinessPhase.T1: "轻量观察倒计时，禁止长时间开发与巡检",
        ReadinessPhase.OPEN: "立即进入车头或车身执行链",
    }[phase]


def soonest(schedules: Mapping[str, RoleSchedule], now: datetime | None = None) -> RoleSchedule | None:
    """The role closest to its event among those that actually have one.

    Used by the multi-role arbitration the book asks for: with two roles on one device, the one
    about to miss its first participation is the one to serve, so the answer is "soonest", not
    "first in the file".
    """
    dated = [s for s in schedules.values() if s.start_datetime() is not None]
    if not dated:
        return None
    return min(dated, key=lambda s: s.start_datetime() or datetime.max.replace(tzinfo=timezone.utc))


def load(path: Path | str | None = None) -> dict[str, RoleSchedule]:
    """Read the schedule file.  A missing or unreadable file is an empty schedule, not an error.

    An empty schedule means ``IDLE`` for everyone, which is the correct behaviour for a fresh
    install and much better than refusing to run the runtime because a knowledge file is absent.
    """
    source = Path(path) if path is not None else STATE_PATH
    if not source.is_file():
        return {}
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rows = payload.get("roles") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return {}
    out: dict[str, RoleSchedule] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        schedule = RoleSchedule.from_json(row)
        if schedule.role_id and schedule.event_id:
            out[f"{schedule.role_id}|{schedule.event_id}"] = schedule
    return out


def save(schedules: Mapping[str, RoleSchedule], path: Path | str | None = None) -> Path:
    """Write the schedule atomically, so a crash cannot leave a half-written clock."""
    target = Path(path) if path is not None else STATE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "_read_me": (
            "按角色的限时活动预约。reserved_start 只有在客户端真的读到倒计时/冷却后才允许写入"
            "（source 必须写明来源）。为 null 时 phase_at() 返回 IDLE —— 不许推算时间。"
        ),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "roles": [schedule.as_json() for schedule in schedules.values()],
    }
    with tempfile.NamedTemporaryFile(
        "w", dir=target.parent, delete=False, suffix=".tmp", encoding="utf-8"
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        temp_name = handle.name
    Path(temp_name).replace(target)
    return target


def record_reservation(
    schedules: dict[str, RoleSchedule],
    *,
    role_id: str,
    event_id: str,
    reserved_start: str | None,
    source: str,
    role: str = "AUTO",
    alliance: str | None = None,
    now: datetime | None = None,
) -> RoleSchedule:
    """Set (or clear) one role's reservation, stamping where it came from.

    Clearing is a first-class operation: when the client's countdown disappears or the window
    ends, the honest update is ``reserved_start=None``, not leaving a stale minute in place --
    a stale reservation would wake the runtime for an event that already happened.
    """
    key = f"{role_id}|{event_id}"
    schedule = schedules.get(key) or RoleSchedule(role_id=role_id, event_id=event_id)
    schedule.reserved_start = reserved_start
    schedule.source = source
    schedule.observed_at = (now or datetime.now(timezone.utc)).isoformat()
    schedule.role = role
    if alliance is not None:
        schedule.alliance = alliance
    schedules[key] = schedule
    return schedule
