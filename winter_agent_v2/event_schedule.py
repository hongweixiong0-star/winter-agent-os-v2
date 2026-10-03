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
import re
from copy import deepcopy
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "learning/timed_event_schedule.json"
DEFAULT_PATH = STATE_PATH
GLOBAL_CALENDAR_SCOPE = "UNSCOPED_CLIENT"
CALENDAR_SCAN_INTERVAL_SECONDS = 24 * 60 * 60


class ReadinessPhase(str, Enum):
    """How close the clock says we are.  Ordered: IDLE < T30 < T15 < T5 < T1 < OPEN."""

    IDLE = "IDLE"
    T30 = "T30"
    T15 = "T15"
    T5 = "T5"
    T1 = "T1"
    OPEN = "OPEN"


class LiveWindowState(str, Enum):
    """What the current role actually observed in the client, independent of its clock."""

    UNKNOWN = "UNKNOWN"
    SCHEDULED_NOT_OPEN = "SCHEDULED_NOT_OPEN"
    OPEN = "OPEN"
    EXPIRED = "EXPIRED"


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
    live_window_state: str = LiveWindowState.UNKNOWN.value
    live_window_observed_at: str | None = None
    live_window_source: str = "UNKNOWN"
    time_zone: str | None = None
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
            "live_window_state": self.live_window_state,
            "live_window_observed_at": self.live_window_observed_at,
            "live_window_source": self.live_window_source,
            "time_zone": self.time_zone,
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
            live_window_state=str(payload.get("live_window_state") or LiveWindowState.UNKNOWN.value),
            live_window_observed_at=(str(payload["live_window_observed_at"])
                                     if payload.get("live_window_observed_at") else None),
            live_window_source=str(payload.get("live_window_source") or "UNKNOWN"),
            time_zone=(str(payload["time_zone"]) if payload.get("time_zone") else None),
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


def seconds_until_next_transition(
    schedules: Mapping[str, RoleSchedule], now: datetime | None = None
) -> float | None:
    """Seconds until the next real event-readiness boundary across all roles.

    The single AUTO loop normally sleeps between runs.  A reservation already recorded from a
    live client countdown must shorten that sleep to the next T-30/T-15/T-5/T-1/open boundary;
    otherwise its priority bonus is only discovered at the next ordinary poll.  Unknown or
    expired reservations produce no wake.  The thresholds are the same ladder consumed by
    ``readiness_phase`` and ``Scheduler.readiness``.
    """
    moment = now or datetime.now(timezone.utc)
    thresholds = (30 * 60, 15 * 60, 5 * 60, 60, 0)
    candidates: list[float] = []
    for schedule in schedules.values():
        start = schedule.start_datetime()
        if start is None:
            continue
        remaining = (start - moment).total_seconds()
        # Once open, the ordinary AUTO polling cadence owns retries during the window.  This
        # prevents a persisted reservation from creating a zero-delay restart loop.
        if remaining <= 0:
            continue
        future_boundaries = [remaining - threshold for threshold in thresholds
                             if remaining - threshold > 0]
        if future_boundaries:
            candidates.append(min(future_boundaries))
    return min(candidates) if candidates else None


def bounded_poll_delay_seconds(
    ordinary_delay_seconds: float,
    schedules: Mapping[str, RoleSchedule],
    now: datetime | None = None,
) -> float:
    """Keep the ordinary loop delay unless a known event boundary arrives sooner."""
    base = max(0.0, float(ordinary_delay_seconds))
    wake = seconds_until_next_transition(schedules, now)
    return min(base, wake) if wake is not None else base


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
    # Calendar observations share this existing store. Updating reservations
    # must preserve observations (and other source metadata), not erase them.
    payload = _schedule_payload(target)
    payload.update({
        "schema_version": "1.1",
        "_read_me": (
            "按角色的活动预约时钟与实时开放观测分开保存。reserved_start 仅来自可信时间来源；"
            "live_window_state 仅来自该角色当前客户端观测。未知当前倒计时不得清除预约或推断开放。"
        ),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "roles": [schedule.as_json() for schedule in schedules.values()],
    })
    return _write_schedule_payload(payload, target)


def _schedule_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_schedule_payload(payload: dict[str, Any], target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=target.parent, delete=False, suffix=".tmp", encoding="utf-8"
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        temp_name = handle.name
    Path(temp_name).replace(target)
    return target


def _calendar_scope(role_id: str) -> str:
    return str(role_id or "").strip() or GLOBAL_CALENDAR_SCOPE


def _calendar_moment(value: datetime | str | None) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def latest_calendar_snapshot(
    role_id: str, path: Path | str | None = None, *, kind: str = "CALENDAR_GRID",
) -> dict[str, Any] | None:
    """Read only this role's observation; unconfirmed identity has its own bucket."""
    payload = _schedule_payload(Path(path) if path is not None else STATE_PATH)
    scopes = payload.get("calendar_observations") or {}
    scope = scopes.get(_calendar_scope(role_id), {}) if isinstance(scopes, dict) else {}
    result = scope.get(kind) if isinstance(scope, dict) else None
    return deepcopy(result) if isinstance(result, dict) else None


def calendar_scan_pending(role_id: str, path: Path | str | None = None) -> bool:
    grid = latest_calendar_snapshot(role_id, path)
    return bool(grid and any(
        isinstance(row, dict) and row.get("tap_norm") and row.get("details_observed") is not True
        for row in grid.get("entries") or ()
    ))


def strip_read_stale_against_grid(
    role_id: str, path: Path | str | None = None,
) -> bool:
    """True when the grid has been read **more recently** than the strip beside it.

    The strip is a second region of the same screen, and ``_record_calendar_observation``
    writes both from **one** call with **one** ``stamp``, so equal timestamps mean "this
    frame produced both".  A strictly newer grid therefore means the last look at that screen
    did not include the strip, which is the state measured on the live device 2026-10-02
    23:15: both roles had a grid from 05:58Z, no ``ACTIVITY_STRIP`` at all, and
    ``calendar_scan_due`` answering False -- so the strip reader had never run.

    Two shapes this must **not** become, both of which a previous version of this predicate
    was rejected for:

    * "``ACTIVITY_STRIP`` is absent" -- a role whose only reading is a grid would then be due
      forever, and four existing tests that assert convergence would turn red.  A missing
      record is not evidence of staleness; it is evidence of a code path older than the
      strip, and those fixtures are exactly that.  **A reader cannot discover that it has
      never been called by asking whether it has been called.**
    * "the registry has an unread activity" -- 17 registered, 6 read, permanently true, and
      a 23-hour convergence becomes an infinite one.

    So the test is strictly comparative and needs both readings to exist.  Where the strip
    has never been recorded this answers False, and what opens the gate in that case is the
    ordinary interval plus ``advertised_but_unread_activities`` -- a role that has genuinely
    never read its strip still has to reach this screen through the same path every other
    first observation does, and forcing it here would have been the third version of a
    predicate that two rounds of existing tests had already rejected.
    """
    grid = latest_calendar_snapshot(role_id, path)
    strip = latest_calendar_snapshot(role_id, path, kind="ACTIVITY_STRIP")
    if not grid or not strip:
        return False
    grid_at = _calendar_moment(grid.get("observed_at"))
    strip_at = _calendar_moment(strip.get("observed_at"))
    if grid_at is None or strip_at is None:
        return False
    return grid_at > strip_at


def advertised_but_unread_activities(
    role_id: str, path: Path | str | None = None,
) -> tuple[str, ...]:
    """Activities this role's last observation **advertised** and never had opened.

    This is the second half of the scan rule, and the shape matters more than the size.

    The first version of this asked a different question -- "which *registered* activities
    has this role never read?" -- and it was wrong in a way four existing tests caught
    immediately (``test_the_scan_converges_after_one_read_per_row`` among them).  Being in
    the registry is not evidence that the client is showing the activity: on 2026-10-02 the
    registry held 17 and the grid read 6, so "unread registered" was a permanent 11 and the
    scan could never converge, which is the one thing ``calendar_scan_pending`` exists to
    guarantee it eventually does.  Converting that into a 23-hour regression is worse than
    the original silence.

    The predicate is deliberately about **what the client drew and can actually open**,
    never about what the registry contains, and it uses the same "has a tap point" test
    ``calendar_scan_pending`` already uses.  Both halves were forced by evidence:

    * registry-based ("which registered activity is unread") was written first and rejected
      by four existing tests -- the registry holds 17 and the grid shows 6, so it is
      permanently true and the scan can never converge;
    * "listed but no tap point" was rejected by
      ``test_calendar_storage_is_role_scoped_due_after_a_day_and_does_not_set_reserved_time``,
      whose row carries neither ``tap_norm`` nor ``details_observed``: a row the client drew
      without a clickable position is not something this run *could* have opened, so calling
      it an unpaid debt would re-open the calendar forever over a row that cannot be read.

    That matches the live state exactly: all six real grid rows carry ``tap_norm=True`` and
    ``details_observed=True``, so the strip is the only thing left owing anything.
    """
    grid = latest_calendar_snapshot(role_id, path)
    if not grid:
        return ()
    read: set[str] = set()
    advertised: dict[str, None] = {}
    for row in grid.get("entries") or ():
        if not isinstance(row, Mapping):
            continue
        event_id = str(row.get("event_id") or "")
        if not event_id or row.get("tap_norm") is None:
            continue
        advertised.setdefault(event_id, None)
        if row.get("details_observed") is True:
            read.add(event_id)
    strip = latest_calendar_snapshot(role_id, path, kind="ACTIVITY_STRIP") or {}
    for row in strip.get("entries") or ():
        if isinstance(row, Mapping) and str(row.get("event_id") or ""):
            advertised.setdefault(str(row["event_id"]), None)
    for row in strip.get("read_entries") or ():
        if isinstance(row, Mapping) and str(row.get("event_id") or ""):
            read.add(str(row["event_id"]))
    return tuple(sorted(set(advertised) - read))


def calendar_scan_due(
    role_id: str, *, now: datetime | None = None, path: Path | str | None = None,
    interval_seconds: float = CALENDAR_SCAN_INTERVAL_SECONDS,
) -> bool:
    """A completed read stays fresh for a day; an interrupted scan can continue.

    And an activity the last screen **advertised but nobody opened** keeps it due, however
    complete the rows it did open are.  Measured 2026-10-02: with six grid rows all opened
    at 05:35-05:58Z, both roles answered ``False`` for the rest of the day,
    ``DISCOVER_EVENT_CALENDAR`` was never selected again, and no episode on the new
    revisions ever stood on ``Page.EVENT`` -- so the strip reader, correct as it was, was
    never called once.

    The predicate is deliberately about **what the client drew**, never about what the
    registry contains.  A registry-based version was written first and rejected by four
    existing tests: the registry holds 17 activities and the grid shows 6, so "registered
    and unread" is permanently true and the scan could never converge.
    """
    grid = latest_calendar_snapshot(role_id, path)
    observed = _calendar_moment((grid or {}).get("observed_at"))
    moment = _calendar_moment(now) or datetime.now(timezone.utc)
    if observed is None or observed > moment + timedelta(seconds=5):
        return True
    if calendar_scan_pending(role_id, path):
        return True
    if strip_read_stale_against_grid(role_id, path):
        return True
    if advertised_but_unread_activities(role_id, path):
        return True
    return (moment - observed).total_seconds() >= interval_seconds


def _calendar_row_days(row: Mapping[str, Any]) -> tuple[str, ...]:
    values = row.get("calendar_dates_raw") or (
        row.get("calendar_date_raw"), row.get("calendar_end_date_raw"),
    )
    return tuple(str(value) for value in values if value)


def _calendar_day_key(token: Any) -> tuple[int, int] | None:
    """``(month, day)`` from either spelling the client prints, or ``None`` if it is not a day.

    The grid strip and the detail page spell the same day differently -- ``10/04`` is what the
    live detail's occurrence key carried on 2026-10-02, while the older grid fixtures use
    ``9月26日`` -- so both are parsed into numbers before anything is compared.  A token that is
    not a date at all (``WRONG``) answers ``None``, which is what keeps a malformed key from
    being read as evidence.
    """
    text = str(token or "").strip()
    match = (re.fullmatch(r"(\d{1,2})\s*/\s*(\d{1,2})", text)
             or re.fullmatch(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", text))
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def _row_carrying_the_details_dates(
    occurrence: str, old_rows: list[dict], event_id: str,
) -> dict | None:
    """The one uninspected row of this event whose own dates carry every date the detail named.

    This is the date-containment reading of "which occurrence was that detail?".  It is
    deliberately closed on both sides:

    * it never guesses -- the detail must have named at least one real day, and exactly one row
      must carry them all; two rows that fit is a coin flip and a coin flip credits nothing;
    * it can never credit a second occurrence from the first occurrence's detail, because the
      row it credits stops being uninspected and so stops being a candidate.
    """
    wanted = {key for key in (_calendar_day_key(part) for part in str(occurrence).split("|"))
              if key is not None}
    if not wanted:
        return None
    candidates: list[dict] = []
    for row in old_rows:
        if str(row.get("event_id") or "") != event_id:
            continue
        if row.get("details_observed") is True or not row.get("tap_norm"):
            continue
        row_days = {key for key in (_calendar_day_key(day) for day in _calendar_row_days(row))
                    if key is not None}
        if wanted <= row_days:
            candidates.append(row)
    return candidates[0] if len(candidates) == 1 else None


def _prior_calendar_row(row: Mapping[str, Any], old_rows: list[dict]) -> dict | None:
    key = row.get("occurrence_key")
    exact = [old for old in old_rows if key and old.get("occurrence_key") == key]
    if len(exact) == 1:
        return exact[0]
    # Do not carry a past occurrence's outcome just because its event name
    # repeats. Date evidence is required when OCR changes an identifier.
    days = _calendar_row_days(row)
    if not days:
        return None
    name = str(row.get("display_name") or "").strip()
    matching = [old for old in old_rows if _calendar_row_days(old) == days and (
        old.get("event_id") == row.get("event_id")
        or (name and name in {
            str(old.get("display_name") or "").strip(),
            str((old.get("detail_observation") or {}).get("display_name") or "").strip(),
        })
    )]
    return matching[0] if len(matching) == 1 else None


def annotate_calendar_observation(
    role_id: str, observation: Mapping[str, Any], path: Path | str | None = None,
) -> dict[str, Any]:
    """Merge inspected status into fresh rows without importing saved geometry."""
    result = deepcopy(dict(observation))
    grid = latest_calendar_snapshot(role_id, path) or {}
    old_rows = [row for row in grid.get("entries") or () if isinstance(row, dict)]
    rows = [dict(row) for row in result.get("entries") or () if isinstance(row, Mapping)]
    for row in rows:
        old = _prior_calendar_row(row, old_rows)
        if old:
            row.update({key: deepcopy(old[key]) for key in (
                "details_observed", "details_observed_at", "detail_evidence_ref", "detail_observation",
            ) if key in old})
    result["entries"] = rows
    return result


def calendar_next_entry(
    role_id: str, current_entries: list[dict], path: Path | str | None = None,
) -> dict[str, Any] | None:
    """Choose only among current-frame entries; the store supplies no click point."""
    reading = annotate_calendar_observation(role_id, {"entries": current_entries}, path)
    return next((row for row in reading["entries"]
                 if row.get("details_observed") is not True and row.get("tap_norm")
                 and row.get("event_id")), None)


def record_calendar_snapshot(
    *, role_id: str, observation: Mapping[str, Any],
    observed_at: datetime | str | None = None, evidence_ref: str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any] | None:
    """Persist raw calendar evidence without turning previews into battle clocks.

    A detail/partial overlay cannot replace the last full grid. Detail success
    is credited to one observed occurrence, never every same-name row or role.
    This function leaves the existing ``roles`` reservations entirely intact.
    """
    if observation.get("recognized") is not True:
        return None
    target = Path(path) if path is not None else STATE_PATH
    payload = _schedule_payload(target)
    scopes = payload.get("calendar_observations")
    if not isinstance(scopes, dict):
        scopes = {}
        payload["calendar_observations"] = scopes
    scope_key = _calendar_scope(role_id)
    scope = scopes.get(scope_key)
    if not isinstance(scope, dict):
        scope = {}
        scopes[scope_key] = scope
    moment = _calendar_moment(observed_at)
    if observed_at is not None and moment is None:
        return None
    moment = moment or datetime.now(timezone.utc)
    reading = deepcopy(dict(observation))
    kind = str(reading.get("kind") or (
        "CALENDAR_GRID" if "entries" in reading or "visible_dates_raw" in reading else "EVENT_DETAIL"
    ))
    if kind == "CALENDAR_GRID" and reading.get("details_visible") is True:
        kind = "CALENDAR_GRID_OVERLAY"
    previous = _calendar_moment((scope.get(kind) or {}).get("observed_at"))
    if previous is not None and moment < previous:
        return deepcopy(scope[kind])
    snapshot = {
        **reading,
        "kind": kind, "scope_key": scope_key,
        "scope": "ROLE" if role_id else GLOBAL_CALENDAR_SCOPE,
        "role_id": str(role_id) if role_id else None,
        "observed_at": moment.isoformat(), "evidence_ref": evidence_ref,
        "source": str(reading.get("source") or "UNKNOWN"),
        "observation": reading,
    }
    grid = scope.get("CALENDAR_GRID") or {}
    old_rows = [row for row in grid.get("entries") or () if isinstance(row, dict)]
    if kind == "CALENDAR_GRID":
        rows = annotate_calendar_observation(role_id, reading, target)["entries"]
        snapshot["entries"] = rows
        scope["detail_return"] = {"pending": False, "observed_at": moment.isoformat(),
                                   "reason": "fresh_full_calendar_grid", "evidence_ref": evidence_ref}
    elif kind == "ACTIVITY_STRIP":
        # A fresh reading of the strip replaces the whole snapshot for this kind at the end of
        # this function, and what the client draws is not the list of activities already read.
        # Measured 2026-10-03, one hour after the credit shipped: role 1063040265's strip had
        # no ``read_entries`` key at all while its EVENT_DETAIL carried
        # ``strip_activity_credited='STATE_VS_STATE'``.  The credit had been written into the
        # previous strip dict and the next strip reading on the following calendar visit
        # discarded it -- so the debt came back, and the credit was the thing being lost.
        #
        # Carried forward here rather than re-derived, because the client cannot tell us which
        # activities a previous run opened; only this ledger can.
        previous = scope.get("ACTIVITY_STRIP") or {}
        carried = [
            row for row in previous.get("read_entries") or () if isinstance(row, Mapping)
        ]
        if carried:
            merged = list(carried)
            known = {str(row.get("event_id") or "") for row in merged}
            for row in reading.get("read_entries") or ():
                if isinstance(row, Mapping):
                    event = str(row.get("event_id") or "")
                    if event and event not in known:
                        merged.append(dict(row))
                        known.add(event)
            snapshot["read_entries"] = merged
            snapshot["read_entries_carried"] = len(carried)
    elif kind == "EVENT_DETAIL":
        occurrence = str(reading.get("matched_occurrence_key") or "")
        event_id = str(reading.get("matched_event_id") or reading.get("event_id") or "")
        matched = next((row for row in old_rows if occurrence
                        and row.get("occurrence_key") == occurrence), None)
        if matched is None and occurrence:
            # The keys disagree for a mundane reason: they are different derivations of the
            # same idea.  The grid row's key is the first and last date of its visible strip;
            # the detail page prints its own dates.  So a key that matches no row is *not*
            # evidence that a different occurrence was read, and the dates the detail does
            # carry are the evidence that says which row it belongs to.
            #
            # Measured 2026-10-02, sanctioned pinned panel, 4.4 unattended hours: role
            # 1061663148's grid held ``ICEBOUND_TREASURE_TRAINING|10/02|10/06`` while every
            # detail it opened read ``ICEBOUND_TREASURE_TRAINING|10/04|10/04`` -- and 10/04 is
            # inside the row's ``calendar_dates_raw``.  The old code matched on key equality
            # only, so nothing was ever credited, ``calendar_scan_pending`` stayed true,
            # ``calendar_scan_due`` had to stay true, and AUTO re-opened the same six entries
            # 668 times: 84% of every run, for hours.  The other role finished its scan on the
            # same grid only because its last detail happened to yield a key equal to its row's.
            matched = _row_carrying_the_details_dates(occurrence, old_rows, event_id)
        if matched is None and not occurrence and event_id:
            # The frame offered no key at all, so there is no date evidence either.  Unchanged
            # from before: the Brain opens the *first* uninspected visible row, so crediting
            # that one is what advances the scan, and a credited row is never chosen again.
            matched = next((row for row in old_rows if row.get("event_id") == event_id
                            and row.get("details_observed") is not True), None)
        if matched is not None:
            matched.update({"details_observed": True, "details_observed_at": moment.isoformat(),
                            "detail_evidence_ref": evidence_ref, "detail_observation": reading})
            snapshot["matched_occurrence_key"] = matched.get("occurrence_key")
        elif event_id and reading.get("calendar_origin") != "GRID_ENTRY":
            # An activity that lives only on the strip above the grid has no row to credit,
            # and that is what kept the calendar permanently due.  Measured 2026-10-03 on live
            # revision aab0dbb8: both roles had EVENT_DETAIL readings of a strip activity --
            # CANYON_CLASH with calendar_origin=None for 1061663148, STATE_VS_STATE likewise
            # for 1063040265 -- while ``advertised_but_unread_activities`` still returned them
            # plus ALLIANCE_MOBILIZATION, so ``calendar_scan_due`` stayed True and
            # DISCOVER_EVENT_CALENDAR was re-selected every 24 seconds.  The credit has to
            # land somewhere, and the strip's own ``read_entries`` is the place its reader
            # already looks (see ``advertised_but_unread_activities``).
            #
            # What this records is "this activity's page was observed".  It is not a claim
            # that anything was acted on: the page also carries 商店 and 编队, and a refused
            # spend must not turn into a permanent debt, which is the operator's section 7 --
            # safety and liveness are separate, and refusing here would re-create the loop
            # this line exists to end.
            #
            # The credit is put on the snapshot itself, not only into ``scope`` in place.
            # Measured 2026-10-03, one hour after this line shipped: role 1063040265's strip
            # had **no** ``read_entries`` key while its EVENT_DETAIL carried
            # ``strip_activity_credited='STATE_VS_STATE'`` -- the two contradicted each other.
            # The cause is the line below that ends this function, ``scope[kind] = snapshot``:
            # every observation replaces the whole snapshot for its kind, so a credit written
            # into the previous strip dict is discarded the next time the strip is read
            # again, which it is on every calendar visit.  Role 1061663148 still had its
            # credit only because no strip read had happened since.
            #
            # So the credit is merged into the strip's own snapshot, because that is the dict
            # ``advertised_but_unread_activities`` reads, and because writing it into ``scope``
            # alone put it somewhere no reader looks.
            strip = dict(scope.get("ACTIVITY_STRIP") or {})
            known = {
                str(row.get("event_id") or "")
                for row in strip.get("read_entries") or () if isinstance(row, Mapping)
            }
            if event_id not in known:
                strip["read_entries"] = [
                    *(strip.get("read_entries") or ()), {"event_id": event_id},
                ]
            strip["observed_at"] = moment.isoformat()
            scope["ACTIVITY_STRIP"] = strip
            snapshot["strip_activity_credited"] = event_id
        if matched is not None or reading.get("calendar_origin") == "GRID_ENTRY":
            scope["detail_return"] = {"pending": True, "observed_at": moment.isoformat(),
                                       "evidence_ref": evidence_ref}
    scope[kind] = snapshot
    payload["updated_at"] = moment.isoformat()
    _write_schedule_payload(payload, target)
    return deepcopy(snapshot)


def record_calendar_detail(**kwargs: Any) -> dict[str, Any] | None:
    """The same store entry point, explicitly naming the already-read detail."""
    observation = dict(kwargs.pop("observation"))
    observation["kind"] = "EVENT_DETAIL"
    return record_calendar_snapshot(observation=observation, **kwargs)


def calendar_detail_return_pending(
    role_id: str, path: Path | str | None = None, *, now: datetime | None = None,
) -> bool:
    """A recent opened detail needs a bounded return, not a permanent BACK goal."""
    payload = _schedule_payload(Path(path) if path is not None else STATE_PATH)
    state = (payload.get("calendar_observations") or {}).get(_calendar_scope(role_id), {}).get("detail_return", {})
    observed = _calendar_moment(state.get("observed_at"))
    moment = _calendar_moment(now) or datetime.now(timezone.utc)
    return state.get("pending") is True and observed is not None and 0 <= (moment - observed).total_seconds() <= 1800


def clear_calendar_detail_return_pending(
    role_id: str, *, observed_at: datetime | str | None = None, reason: str,
    evidence_ref: str | None = None, path: Path | str | None = None,
) -> bool:
    target = Path(path) if path is not None else STATE_PATH
    payload = _schedule_payload(target)
    scope = (payload.get("calendar_observations") or {}).get(_calendar_scope(role_id), {})
    state = scope.get("detail_return") or {}
    if state.get("pending") is not True:
        return False
    moment = _calendar_moment(observed_at) or datetime.now(timezone.utc)
    prior = _calendar_moment(state.get("observed_at"))
    if prior is not None and moment < prior:
        return False
    scope["detail_return"] = {"pending": False,
        "observed_at": moment.isoformat(),
        "reason": reason, "evidence_ref": evidence_ref}
    _write_schedule_payload(payload, target)
    return True


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


def record_live_countdown(
    schedules: dict[str, RoleSchedule],
    *,
    role_id: str,
    event_id: str,
    seconds_to_start: int,
    source: str,
    role: str = "AUTO",
    alliance: str | None = None,
    now: datetime | None = None,
) -> RoleSchedule:
    """Turn a positive client countdown into a role-scoped absolute reservation.

    The absolute time is derived only from a live countdown and its observation timestamp.  This
    is not a recurring-calendar prediction; a later client observation replaces or clears it.
    """
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    start = moment + timedelta(seconds=max(0, int(seconds_to_start)))
    schedule = record_reservation(
        schedules,
        role_id=role_id,
        event_id=event_id,
        reserved_start=start.isoformat(),
        source=source,
        role=role,
        alliance=alliance,
        now=moment,
    )
    schedule.live_window_state = (
        LiveWindowState.SCHEDULED_NOT_OPEN.value if int(seconds_to_start) > 0
        else LiveWindowState.OPEN.value
    )
    schedule.live_window_observed_at = moment.isoformat()
    schedule.live_window_source = source
    schedule.time_zone = _time_zone_label(moment)
    return schedule


def _time_zone_label(moment: datetime) -> str:
    """Record the observed offset without inventing an IANA zone from an offset alone."""
    offset = moment.utcoffset()
    if offset is None:
        return "UTC"
    seconds = int(offset.total_seconds())
    sign = "+" if seconds >= 0 else "-"
    seconds = abs(seconds)
    return f"UTC{sign}{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}"


def record_live_window_observation(
    schedules: dict[str, RoleSchedule],
    *,
    role_id: str,
    event_id: str,
    state: LiveWindowState | str,
    source: str,
    role: str = "AUTO",
    alliance: str | None = None,
    now: datetime | None = None,
) -> RoleSchedule:
    """Update current client evidence without changing a trusted reservation clock."""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    state_value = state.value if isinstance(state, LiveWindowState) else str(state).upper()
    if state_value not in {item.value for item in LiveWindowState}:
        state_value = LiveWindowState.UNKNOWN.value
    key = f"{role_id}|{event_id}"
    schedule = schedules.get(key) or RoleSchedule(role_id=role_id, event_id=event_id)
    schedule.live_window_state = state_value
    schedule.live_window_observed_at = moment.isoformat()
    schedule.live_window_source = source
    schedule.role = role
    if alliance is not None:
        schedule.alliance = alliance
    if schedule.time_zone is None:
        schedule.time_zone = _time_zone_label(moment)
    schedules[key] = schedule
    return schedule
