"""Role-scoped fishing bait/points state and the per-run ledger.

Why this exists
---------------
The operator's directive FISHING TOURNAMENT — NORMAL BAIT MAX SCORE POLICY V2 (2026-09-30)
moved the goal of this event.  It is no longer "play a level" or even "dive deeper"; it is

    MAXIMIZE_EVENT_POINTS_TOTAL  ==  MAXIMIZE_POINTS_PER_NORMAL_BAIT

under a deliberately narrow budget: **NORMAL_BAIT is the only resource this agent may spend.**
Special bait, treasure tickets, Treasure Mode and every free special attempt are forbidden
(§4), and gems / real money were already permanently blocked.

That turns bait into the scarce quantity and points into the objective, so three questions
have to be answerable at any instant, per role, from a file that survives a restart:

* **How much bait is left, and when does the next one arrive?**  ``normal_bait_current`` /
  ``bait_cap`` / ``next_bait_at``.  Bait is a *timer resource* -- exactly like the free
  stamina gift in :mod:`winter_agent_v2.stamina_supply`, which is the precedent this module
  follows: store the instant the client printed, never a cadence guessed from samples.
* **Are we about to waste one?**  ``NORMAL_BAIT_WASTED_BY_CAP`` (§2) and
  ``NORMAL_BAIT_LEFT_AT_EVENT_END`` (§2/§15) are the two acceptance numbers, and both are
  *counted from observations*, never asserted.
* **Is that bait earning points?**  ``points_per_bait`` (§1) is the core metric, and a run
  that lowered the bait counter without raising the score is a ``ZERO_SCORE_RUN`` (§13).

What this is not
----------------
It is not a scheduler, a WorldState, or a second goal engine.  It owns no device, opens no
lease, and never decides whether to play.  It is a *record plus derived arithmetic*, in the
same shape as ``stamina_supply.py``: the single Scheduler asks it a question, and the answer
is a number rather than a decision.

Role scoping is absolute
------------------------
Bait, gear, points and collections are per-role and are never shared.  The file already
carries that note from the first live reading (``ROLE_A`` was measured; ``ROLE_B`` was not),
and the code keeps the two apart rather than defaulting one to the other: ``ROLE_B``'s bait
is ``None`` until it is read, and ``None`` means *unknown*, never *zero* and never *A's*.

Honest limits, stated rather than hidden
---------------------------------------
* The regeneration cadence ``regen_seconds`` starts as the operator's prior ("~3h per
  recovery, cap 10") and is tagged ``OPERATOR_PRIOR``.  Every derived "by event end" figure
  says so in its own field, because a prior and a measurement must not be confused.
* ``seconds_per_run`` is only known once real runs have been recorded.  Until then
  :meth:`RoleFishingState.endgame` reports ``known=False`` instead of inventing a deadline
  it cannot compute.  Guessing here would spend the operator's bait on a fiction.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping

DEFAULT_PATH = Path("learning/fishing_state.json")
#: The per-run ledger, one JSON object per line, appended and never rewritten: a run that
#: happened stays a fact even when a later policy makes it look wrong (§8 asks for exactly
#: that history, because the scoring model has to be derived from real results, not guessed).
DEFAULT_LEDGER_PATH = Path("learning/fishing_runs.jsonl")

SCHEMA_VERSION = 2

#: §2's two acceptance numbers and §1's core metric, named once so a report cannot reword them.
KPI_BAIT_USED = "NORMAL_BAIT_USED"
KPI_BAIT_WASTED = "NORMAL_BAIT_WASTED"
KPI_BAIT_REMAINING = "NORMAL_BAIT_REMAINING"
KPI_TOTAL_POINTS = "TOTAL_POINTS"
KPI_POINTS_PER_BAIT_AVG = "POINTS_PER_BAIT_AVG"
KPI_POINTS_PER_BAIT_P50 = "POINTS_PER_BAIT_P50"
KPI_BEST_POINTS_PER_BAIT = "BEST_POINTS_PER_BAIT"
KPI_AVG_DEPTH = "AVG_DEPTH"
KPI_BEST_DEPTH = "BEST_DEPTH"
KPI_AVG_FISH_CAUGHT = "AVG_FISH_CAUGHT"
KPI_COLLISION_RATE = "COLLISION_RATE"

#: Operator prior from the first live reading.  Kept as the *default* only, and tagged as a
#: prior wherever it is used as one -- `knowledge/events/fishing_tournament_rules.json` says
#: "read LIVE every time", so a measured value always wins.
PRIOR_REGEN_SECONDS = 3 * 3600
REGEN_SOURCE_PRIOR = "OPERATOR_PRIOR"
REGEN_SOURCE_LIVE = "LIVE_OBSERVED"

#: §15 gives the endgame its own safety margin: the last runs must not be started so late
#: that the event closes mid-level.  Ten minutes is deliberately generous, because the real
#: risk is asymmetric -- leaving bait unspent is an acceptance failure, one wasted attempt
#: is not.
DEFAULT_SAFETY_MARGIN_SECONDS = 600.0

#: How deep into a role's run history the rolling efficiency looks.  Ten runs is roughly one
#: full bait cap, so the figure keeps moving while a session spends the resource, and does not
#: go stale across the multi-hour recovery gaps.
ROLLING_WINDOW = 10


class BaitPressure(str, Enum):
    """What the bait situation argues for, before any scheduler sees it.

    Ordered by urgency, and the order is a decision rather than a sort: an endgame outranks a
    full counter because the endgame cannot be recovered from, while a full counter still can
    (the next tick is merely wasted, not the event).
    """

    #: Nothing has been read for this role.  Not "zero" and not another role's number.
    UNKNOWN = "UNKNOWN"
    #: Read, and there is no bait to spend.
    NO_BAIT = "NO_BAIT"
    #: §15: the remaining window is shorter than the time the remaining bait needs.
    ENDGAME = "ENDGAME"
    #: §2: ``bait == cap``, so the next regeneration instant produces nothing.
    CAP_FULL = "CAP_FULL"
    #: Read, below cap, and not yet in the endgame.
    NORMAL = "NORMAL"


def parse_instant(value: Any) -> datetime | None:
    """An ISO instant, or ``None``.  A naive timestamp is refused, not assumed to be UTC.

    Same rule as ``event_goal.Activity.window``: a local timestamp without an offset cannot
    drive an unattended wake, so it is not a time this project is willing to act on.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else None
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat(timespec="seconds") if isinstance(moment, datetime) else None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except (TypeError, ValueError):
            return None
    return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    if isinstance(value, str):
        try:
            parsed = float(value.strip())
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None
    return None


# ----------------------------------------------------------------------- one run


@dataclass(frozen=True)
class FishingRun:
    """One level played, with the fields §1 names and the two it derives.

    ``bait_cost`` is recorded rather than assumed to be 1.  The first live reading measured one
    bait per level, but a number that is *read* and a number that is *hardcoded* fail
    differently, and the acceptance criterion is an exact zero on special resources.
    """

    run_id: str
    role_key: str
    at: datetime
    bait_cost: int
    points_before: int | None
    points_after: int | None
    depth_m: int | None = None
    fish_caught: int | None = None
    collision_count: int | None = None
    shield_used: int | None = None
    duration_s: float | None = None
    control_hz: float | None = None
    lane: str = "NORMAL"
    level_id: str | None = None
    verifier: Mapping[str, Any] = field(default_factory=dict)
    evidence: str | None = None
    performance: Mapping[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ derived
    @property
    def points_gain(self) -> int | None:
        """The score this run actually added; ``None`` when either reading is missing."""
        if self.points_before is None or self.points_after is None:
            return None
        return int(self.points_after) - int(self.points_before)

    @property
    def points_per_bait(self) -> float | None:
        """§1's core metric.  ``None`` when it cannot be computed -- never 0 by default.

        A missing reading and a zero gain are different findings: the first says the run could
        not be measured, the second says the bait was spent and produced nothing.  Collapsing
        them would hide the failure mode §13 exists to catch.
        """
        gain, cost = self.points_gain, self.bait_cost
        if gain is None or not cost or cost <= 0:
            return None
        return gain / cost

    @property
    def zero_score_run(self) -> bool:
        """§13: the bait went down and the score did not go up."""
        gain = self.points_gain
        return bool(gain is not None and self.bait_cost > 0 and gain <= 0)

    @property
    def special_resource_used(self) -> list[str]:
        """Any non-NORMAL lane is a policy breach, not a bad round (§4)."""
        lane = str(self.lane or "").upper()
        return [] if lane in ("", "NORMAL") else [lane]

    def to_mapping(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "role_key": self.role_key,
            "at": _iso(self.at),
            "lane": self.lane,
            "level_id": self.level_id,
            "bait_cost": self.bait_cost,
            "points_before": self.points_before,
            "points_after": self.points_after,
            "points_gain": self.points_gain,
            "points_per_bait": self.points_per_bait,
            "depth_m": self.depth_m,
            "fish_caught": self.fish_caught,
            "collision_count": self.collision_count,
            "shield_used": self.shield_used,
            "duration_s": self.duration_s,
            "control_hz": self.control_hz,
            "zero_score_run": self.zero_score_run,
            "verifier": dict(self.verifier),
            "evidence": self.evidence,
            "performance": dict(self.performance),
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "FishingRun":
        """Read back a ledger row, including rows written before this schema existed."""
        control = raw.get("control") if isinstance(raw.get("control"), Mapping) else {}
        bait = raw.get("bait") if isinstance(raw.get("bait"), Mapping) else {}
        points = raw.get("points") if isinstance(raw.get("points"), Mapping) else {}
        cost = _as_int(raw.get("bait_cost"))
        if cost is None:
            before, after = _as_int(bait.get("before")), _as_int(bait.get("after"))
            # The historical row recorded before/after; a decrease is the cost, and a row with
            # no decrease is recorded as 0 rather than guessed to be 1.
            cost = max(0, (before - after)) if before is not None and after is not None else 0
        return cls(
            run_id=str(raw.get("run_id") or raw.get("id") or ""),
            role_key=_role_key(raw.get("role_key") or raw.get("role")),
            at=parse_instant(raw.get("at")) or datetime.now(timezone.utc),
            bait_cost=int(cost),
            points_before=_as_int(raw.get("points_before", points.get("before"))),
            points_after=_as_int(raw.get("points_after", points.get("after"))),
            depth_m=_as_int(raw.get("depth_m", raw.get("depth"))),
            fish_caught=_as_int(raw.get("fish_caught", raw.get("fish_count"))),
            collision_count=_as_int(raw.get("collision_count")),
            shield_used=_as_int(raw.get("shield_used")),
            duration_s=_as_float(raw.get("duration_s", control.get("duration_s"))),
            control_hz=_as_float(raw.get("control_hz", control.get("loop_hz_median"))),
            lane=str(raw.get("lane") or ("TREASURE" if "TREASURE" in str(raw.get("level") or "").upper() else "NORMAL")),
            level_id=(str(raw["level_id"]) if raw.get("level_id") else None),
            verifier=raw.get("verifier") if isinstance(raw.get("verifier"), Mapping) else {},
            evidence=(str(raw["evidence"]) if raw.get("evidence") else None),
            performance=raw.get("performance") if isinstance(raw.get("performance"), Mapping) else {},
        )


#: §13's five signals.  All five are required for a run to count as a *verified* level: the
#: directive lists them together precisely so that "the bait went down" cannot be reported as
#: a completed run on its own.
RUN_VERIFIER_SIGNALS: tuple[str, ...] = (
    "MINIGAME_STARTED",
    "CONTROL_SESSION_RAN",
    "RESULT_PAGE",
    "NORMAL_BAIT_DECREASED",
    "POINTS_READ",
)


def _role_key(raw: Any, fallback: str = "ROLE_A") -> str:
    """``ROLE_A`` from anything the file has used for it.

    The first live row wrote ``"ROLE_A (session role)"`` as free text, so the key is taken as
    the first token rather than the whole string -- otherwise that row would be filed under a
    role that does not exist and its numbers would vanish from every per-role total.
    """
    text = str(raw or "").strip()
    if not text:
        return fallback
    token = text.split()[0].split("(")[0].strip().upper()
    return token or fallback


def verify_run(*, bait_before: int | None, bait_after: int | None,
               points_before: int | None, points_after: int | None,
               started: bool, control_ran: bool, result_page: bool) -> dict[str, Any]:
    """§13's verdict for one finished level, plus the efficiency it implies.

    Returns a mapping that is both the stored evidence and the reason string, so an audit reads
    the same object the decision used.  ``COMPLETE`` requires every signal; a run that lowered
    the bait with no score movement is ``ZERO_SCORE_RUN`` and is flagged for failure analysis
    instead of being filed as a quiet success.
    """
    bait_decreased = (
        bait_before is not None and bait_after is not None and bait_after < bait_before
    )
    points_read = points_before is not None and points_after is not None
    signals = {
        "MINIGAME_STARTED": bool(started),
        "CONTROL_SESSION_RAN": bool(control_ran),
        "RESULT_PAGE": bool(result_page),
        "NORMAL_BAIT_DECREASED": bait_decreased,
        "POINTS_READ": points_read,
    }
    gain = (points_after - points_before) if points_read else None
    cost = (bait_before - bait_after) if bait_decreased else 0
    missing = [name for name in RUN_VERIFIER_SIGNALS if not signals[name]]
    if missing:
        status = "INCOMPLETE"
    elif gain is not None and gain <= 0:
        # §13: bait down, points not up -- a real level that earned nothing.
        status = "ZERO_SCORE_RUN"
    else:
        status = "COMPLETE"
    return {
        "status": status,
        "missing": missing,
        "signals": signals,
        "bait_cost": cost,
        "points_gain": gain,
        "points_per_bait": (gain / cost) if (cost > 0 and gain is not None) else None,
        "failure_analysis_required": status == "ZERO_SCORE_RUN",
    }


# ---------------------------------------------------------------- one role's state


@dataclass
class RoleFishingState:
    """One role's bait, gear and points.  Nothing here is ever shared between roles."""

    role_key: str
    role_id: str | None = None
    name: str | None = None
    normal_bait_current: int | None = None
    bait_cap: int | None = None
    next_bait_at: datetime | None = None
    event_end_at: datetime | None = None
    last_fishing_at: datetime | None = None
    points_total: int | None = None
    regen_seconds: float | None = None
    regen_source: str = REGEN_SOURCE_PRIOR
    line_level: int | None = None
    hook_level: int | None = None
    sinker_level: int | None = None
    bait_used: int = 0
    bait_wasted_by_cap: int = 0
    status: str = "STATE_NOT_READ"
    #: Bookkeeping that makes the waste counter exact rather than estimated: what the last
    #: observation saw, and how many runs had been recorded then.  Without the second field a
    #: spend between two observations would be indistinguishable from a regeneration.
    observed_at: datetime | None = None
    observed_bait: int | None = None
    observed_runs: int = 0
    #: Anything from the file this schema does not know about, so a newer writer's fields
    #: survive a round-trip through this process.
    extra: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------- basic reads
    @property
    def state_is_read(self) -> bool:
        return self.normal_bait_current is not None and self.bait_cap is not None

    @property
    def is_full(self) -> bool:
        return bool(self.state_is_read and self.normal_bait_current >= self.bait_cap)

    def regeneration_seconds(self) -> float | None:
        """The cadence to use, and the caller can see whether it was measured."""
        return self.regen_seconds if self.regen_seconds and self.regen_seconds > 0 else None

    def wasted_ticks_between(self, previous_at: datetime | None, now: datetime) -> int:
        """Regeneration instants that passed while the counter was already full.

        Exact, not estimated: a tick is only counted when the previous observation saw the
        counter at cap *and* no run has been recorded since, because then nothing could have
        spent it and the tick provably produced nothing.
        """
        regen = self.regeneration_seconds()
        if regen is None or previous_at is None or self.observed_bait is None:
            return 0
        if self.observed_bait < (self.bait_cap or 0):
            return 0
        elapsed = (now - previous_at).total_seconds()
        if elapsed <= 0:
            return 0
        return int(elapsed // regen)

    # ------------------------------------------------------- derived projections
    def remaining_regeneration_opportunities(self, now: datetime) -> int | None:
        """§2: regeneration instants left before the event closes.  ``None`` if unknowable."""
        regen = self.regeneration_seconds()
        if regen is None or self.event_end_at is None:
            return None
        left = (self.event_end_at - now).total_seconds()
        return max(0, int(left // regen))

    def bait_gainable_by_end(self, now: datetime) -> int | None:
        """How much of that regeneration can actually land, given the cap."""
        opportunities = self.remaining_regeneration_opportunities(now)
        if opportunities is None or not self.state_is_read:
            return None
        headroom = max(0, (self.bait_cap or 0) - (self.normal_bait_current or 0))
        return min(opportunities, headroom)

    def bait_available_until_end(self, now: datetime) -> int | None:
        """Total bait this role can still spend before the window closes."""
        gainable = self.bait_gainable_by_end(now)
        if gainable is None or not self.state_is_read:
            return None
        return int(self.normal_bait_current or 0) + gainable

    def projected_bait_at_end(self, now: datetime) -> int | None:
        """What the counter reads when the event closes *if nothing is spent*.

        This is the number behind ``NORMAL_BAIT_LEFT_AT_EVENT_END``: it is the bait the
        directive calls wasted, and it is stated as a projection so that "we think we will
        leave N unspent" is distinguishable from "N are unspent right now".
        """
        gainable = self.bait_gainable_by_end(now)
        if gainable is None or not self.state_is_read:
            return None
        return min(self.bait_cap or 0, int(self.normal_bait_current or 0) + gainable)

    # --------------------------------------------------------------- the endgame
    def endgame(self, now: datetime, *, seconds_per_run: float | None = None,
                safety_margin_s: float = DEFAULT_SAFETY_MARGIN_SECONDS) -> dict[str, Any]:
        """§15's verdict: is the window shorter than the work left in it?

        ``known=False`` when either the event end or a real run duration is missing.  That is the
        honest answer and the useful one: an endgame guessed from a prior would spend real bait
        against a deadline nobody measured.
        """
        available = self.bait_available_until_end(now)
        if available is None:
            return {"known": False, "active": False, "reason": "EVENT_END_OR_STATE_UNKNOWN",
                    "bait_to_spend": None, "required_seconds": None, "remaining_seconds": None}
        remaining = (self.event_end_at - now).total_seconds() if self.event_end_at else None
        if not seconds_per_run or seconds_per_run <= 0:
            return {"known": False, "active": False, "reason": "RUN_DURATION_UNKNOWN",
                    "bait_to_spend": available, "required_seconds": None,
                    "remaining_seconds": remaining}
        spendable = max(0, available - max(0, (self.bait_cap or 0) - available))
        required = available * float(seconds_per_run) + float(safety_margin_s)
        active = bool(remaining is not None and remaining < required)
        return {
            "known": True,
            "active": active,
            "reason": "WINDOW_SHORTER_THAN_BAIT_LEFT" if active else "WINDOW_STILL_SUFFICIENT",
            "bait_to_spend": available,
            "spendable_now": spendable,
            "required_seconds": required,
            "remaining_seconds": remaining,
            "safety_margin_s": float(safety_margin_s),
            "seconds_per_run": float(seconds_per_run),
        }

    def pressure(self, now: datetime, *, seconds_per_run: float | None = None,
                 safety_margin_s: float = DEFAULT_SAFETY_MARGIN_SECONDS) -> BaitPressure:
        """The one value the Scheduler needs, computed in the documented precedence order."""
        if not self.state_is_read:
            return BaitPressure.UNKNOWN
        if (self.normal_bait_current or 0) <= 0:
            return BaitPressure.NO_BAIT
        if self.endgame(now, seconds_per_run=seconds_per_run,
                        safety_margin_s=safety_margin_s)["active"]:
            return BaitPressure.ENDGAME
        if self.is_full:
            return BaitPressure.CAP_FULL
        return BaitPressure.NORMAL

    # -------------------------------------------------------------- serialisation
    def to_mapping(self) -> dict[str, Any]:
        payload = dict(self.extra)
        payload.update({
            "role_id": self.role_id,
            "name": self.name,
            "normal_bait_current": self.normal_bait_current,
            "bait_cap": self.bait_cap,
            "next_bait_at": _iso(self.next_bait_at),
            "event_end_at": _iso(self.event_end_at),
            "last_fishing_at": _iso(self.last_fishing_at),
            "points_total": self.points_total,
            "regen_seconds": self.regen_seconds,
            "regen_source": self.regen_source,
            "line_level": self.line_level,
            "hook_level": self.hook_level,
            "sinker_level": self.sinker_level,
            "normal_bait_used": self.bait_used,
            "normal_bait_wasted_by_cap": self.bait_wasted_by_cap,
            "status": self.status,
            "observed_at": _iso(self.observed_at),
            "observed_bait": self.observed_bait,
            "observed_runs": self.observed_runs,
        })
        return payload

    @classmethod
    def from_mapping(cls, role_key: str, raw: Mapping[str, Any]) -> "RoleFishingState":
        known = {
            "role_id", "name", "normal_bait_current", "bait_cap", "next_bait_at", "event_end_at",
            "last_fishing_at", "points_total", "regen_seconds", "regen_source", "line_level",
            "hook_level", "sinker_level", "normal_bait_used", "normal_bait_wasted_by_cap",
            "status", "observed_at", "observed_bait", "observed_runs",
            # v1 spellings, kept readable so the first live reading survives the upgrade.
            "bait_current", "points_today", "free_special_attempts", "collection_seen",
            "collection_new", "note",
        }
        bait_current = _as_int(raw.get("normal_bait_current", raw.get("bait_current")))
        cap = _as_int(raw.get("bait_cap"))
        status = str(raw.get("status") or ("READY" if bait_current is not None else "STATE_NOT_READ"))
        return cls(
            role_key=role_key,
            role_id=(str(raw["role_id"]) if raw.get("role_id") else None),
            name=(str(raw["name"]) if raw.get("name") else None),
            normal_bait_current=bait_current,
            bait_cap=cap,
            next_bait_at=parse_instant(raw.get("next_bait_at")),
            event_end_at=parse_instant(raw.get("event_end_at")),
            last_fishing_at=parse_instant(raw.get("last_fishing_at")),
            points_total=_as_int(raw.get("points_total", raw.get("points_today"))),
            regen_seconds=_as_float(raw.get("regen_seconds")),
            regen_source=str(raw.get("regen_source") or REGEN_SOURCE_PRIOR),
            line_level=_as_int(raw.get("line_level")),
            hook_level=_as_int(raw.get("hook_level")),
            sinker_level=_as_int(raw.get("sinker_level")),
            bait_used=_as_int(raw.get("normal_bait_used")) or 0,
            bait_wasted_by_cap=_as_int(raw.get("normal_bait_wasted_by_cap")) or 0,
            status=status,
            observed_at=parse_instant(raw.get("observed_at")),
            observed_bait=_as_int(raw.get("observed_bait")),
            observed_runs=_as_int(raw.get("observed_runs")) or 0,
            extra={k: v for k, v in raw.items() if k not in known},
        )


# --------------------------------------------------------------------- KPIs (§16)


def _summarise_runs(runs: Iterable[FishingRun]) -> dict[str, Any]:
    """The §16 metric block, computed only from runs that produced a number.

    Every average is over the runs that *have* the reading, and the count of those runs travels
    with it -- an average over three of nine runs must not look like an average over nine.
    """
    runs = [run for run in runs if str(run.lane or "").upper() in ("", "NORMAL")]
    efficiencies = [r.points_per_bait for r in runs if r.points_per_bait is not None]
    depths = [r.depth_m for r in runs if r.depth_m is not None]
    fish = [r.fish_caught for r in runs if r.fish_caught is not None]
    collisions = [r.collision_count for r in runs if r.collision_count is not None]
    used = sum(int(r.bait_cost) for r in runs)
    gains = [r.points_gain for r in runs if r.points_gain is not None]
    return {
        KPI_BAIT_USED: used,
        KPI_TOTAL_POINTS: (sum(gains) if gains else None),
        KPI_POINTS_PER_BAIT_AVG: (sum(efficiencies) / len(efficiencies)) if efficiencies else None,
        KPI_POINTS_PER_BAIT_P50: (float(median(efficiencies)) if efficiencies else None),
        KPI_BEST_POINTS_PER_BAIT: (max(efficiencies) if efficiencies else None),
        KPI_AVG_DEPTH: (sum(depths) / len(depths)) if depths else None,
        KPI_BEST_DEPTH: (max(depths) if depths else None),
        KPI_AVG_FISH_CAUGHT: (sum(fish) / len(fish)) if fish else None,
        # Collisions per run, over the runs that recorded the count.  A per-run mean rather
        # than a per-second rate because the level's own length varies: dividing by duration
        # would make a short shallow run look safer than a long deep one for no real reason.
        KPI_COLLISION_RATE: (sum(collisions) / len(collisions)) if collisions else None,
        "runs": len(runs),
        "runs_with_efficiency": len(efficiencies),
        "zero_score_runs": sum(1 for r in runs if r.zero_score_run),
    }


def _median_duration(runs: Iterable[FishingRun]) -> float | None:
    durations = [r.duration_s for r in runs if r.duration_s is not None and r.duration_s > 0]
    return float(median(durations)) if durations else None


# ------------------------------------------------------------------- the store


class FishingState:
    """The role-scoped record plus the run ledger, loaded once and written back atomically.

    Deliberately a *store*, not an engine: it answers questions (``pressure``, ``kpis``,
    ``snapshot``) and records facts (``observe``, ``record_run``).  It never decides whether to
    play, never touches the device, and never picks a goal -- directive §3's role-session policy
    and §8's scheduler locality rules stay in their own single owners.
    """

    def __init__(self, path: Path | str | None = None,
                 ledger_path: Path | str | None = None) -> None:
        # Both defaults are resolved at *call* time rather than bound into the signature.
        # A default argument is evaluated once, when the class body runs, so a test that
        # reassigns ``DEFAULT_PATH`` -- which ``tests/conftest.py`` does, to keep the
        # production bait record out of a test run -- would be silently ignored and the
        # write would land in the live ``learning/`` tree.  Same shape as
        # ``stamina_supply.StaminaSupply``, and for the same measured reason.
        self.path = Path(path) if path is not None else Path(DEFAULT_PATH)
        self.ledger_path = (
            Path(ledger_path) if ledger_path is not None else Path(DEFAULT_LEDGER_PATH)
        )
        self.roles: dict[str, RoleFishingState] = {}
        self.meta: dict[str, Any] = {}
        self._runs_cache: list[FishingRun] | None = None

    # ------------------------------------------------------------------ loading
    @classmethod
    def load(cls, path: Path | str | None = None,
             ledger_path: Path | str | None = None) -> "FishingState":
        """Never raises on a broken file: an unreadable record is "unknown", not a reason to die.

        Same trade ``stamina_supply.py`` makes and for the same reason -- this is an
        optimisation over live readings, and an unknown answer must not spend the operator's
        bait or stop the run.
        """
        store = cls(path, ledger_path)
        try:
            # Read back through the store's own resolved path so the reader and the writer
            # cannot disagree about which file ``None`` meant.
            payload = json.loads(store.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return store
        if not isinstance(payload, Mapping):
            return store
        raw_roles = payload.get("roles")
        if isinstance(raw_roles, Mapping):
            for key, record in raw_roles.items():
                if isinstance(record, Mapping):
                    store.roles[_role_key(key)] = RoleFishingState.from_mapping(_role_key(key), record)
        store.meta = {
            k: v for k, v in payload.items() if k not in ("roles", "schema_version", "note")
        }
        return store

    def role(self, role_key: str) -> RoleFishingState:
        """The role's record, created empty on first use rather than borrowed from another role."""
        key = _role_key(role_key)
        if key not in self.roles:
            self.roles[key] = RoleFishingState(role_key=key)
        return self.roles[key]

    def window_open(self, now: datetime | None = None) -> bool:
        """Is any role's declared event window still open?

        The answer is computed from the deadline rather than read from the record's
        ``event_live_open`` flag, because that flag is a *memory* of the moment the record was
        written: the live ``learning/fishing_state.json`` still reads ``true`` 2.85 days after its
        own ``event_end_at`` passed (measured 2026-10-04).  A role with no deadline cannot answer
        and counts as closed -- silence about a window is not evidence that one is open.

        Asked by ``source_freshness`` to decide whether a silent fishing record is a fault
        (a window open with nobody writing to it) or just the off-season (a closed window, which is
        exactly what the record's age would be anyway).
        """
        moment = now or datetime.now(timezone.utc)
        return any(role.event_end_at is not None and role.event_end_at > moment
                   for role in self.roles.values())

    # ---------------------------------------------------------------- recording
    def observe(self, role_key: str, *, bait_current: int | None = None,
                bait_cap: int | None = None, next_bait_at: datetime | str | None = None,
                event_end_at: datetime | str | None = None,
                regen_seconds: float | None = None, regen_source: str | None = None,
                points_total: int | None = None, role_id: str | None = None,
                name: str | None = None, now: datetime | None = None,
                extra: Mapping[str, Any] | None = None) -> RoleFishingState:
        """Fold a live reading into the record, counting the bait that was wasted reaching it.

        The waste counter is applied *here*, at the moment of observation, because this is the
        only instant at which the two facts it needs are both true: how long the counter has been
        at cap, and that nothing was spent in the meantime.  Doing it later would either
        double-count or miss the gap entirely.
        """
        moment = now or datetime.now(timezone.utc)
        role = self.role(role_key)
        wasted = role.wasted_ticks_between(role.observed_at, moment)
        if wasted:
            role.bait_wasted_by_cap += wasted
        if role_id:
            role.role_id = str(role_id)
        if name:
            role.name = str(name)
        if bait_current is not None:
            role.normal_bait_current = int(bait_current)
        if bait_cap is not None:
            role.bait_cap = int(bait_cap)
        if next_bait_at is not None:
            role.next_bait_at = parse_instant(next_bait_at)
        if event_end_at is not None:
            role.event_end_at = parse_instant(event_end_at)
        if regen_seconds is not None and float(regen_seconds) > 0:
            role.regen_seconds = float(regen_seconds)
            role.regen_source = str(regen_source or REGEN_SOURCE_LIVE)
        if points_total is not None:
            role.points_total = int(points_total)
        if extra:
            role.extra.update(extra)
        role.observed_at = moment
        role.observed_bait = role.normal_bait_current
        role.observed_runs = self.run_count(role_key)
        role.status = "READY" if role.state_is_read else "STATE_NOT_READ"
        return role

    def record_run(self, run: FishingRun) -> dict[str, Any]:
        """Append the run to the ledger and fold its effect into the role's totals.

        Order matters and is not arbitrary: the ledger is written first, because it is the
        evidence, and a total that moved without a row to explain it would be worse than a row
        whose total has not moved yet.
        """
        self._append_ledger(run)
        role = self.role(run.role_key)
        role.bait_used += max(0, int(run.bait_cost))
        role.last_fishing_at = run.at
        if role.normal_bait_current is not None and run.bait_cost:
            role.normal_bait_current = max(0, int(role.normal_bait_current) - int(run.bait_cost))
            role.observed_bait = role.normal_bait_current
        if run.points_after is not None:
            role.points_total = int(run.points_after)
        if run.verifier.get("status") == "ZERO_SCORE_RUN":
            role.extra["zero_score_runs"] = int(role.extra.get("zero_score_runs") or 0) + 1
        return run.to_mapping()

    def _append_ledger(self, run: FishingRun) -> None:
        try:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with self.ledger_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(run.to_mapping(), ensure_ascii=False) + "\n")
        except OSError:
            return
        if self._runs_cache is not None:
            self._runs_cache.append(run)

    # ------------------------------------------------------------------ ledger
    def runs(self, role_key: str | None = None) -> list[FishingRun]:
        """Every run on file, oldest first.  A malformed row is skipped, never repaired."""
        if self._runs_cache is None:
            rows: list[FishingRun] = []
            try:
                text = self.ledger_path.read_text(encoding="utf-8")
            except OSError:
                text = ""
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(raw, Mapping):
                    rows.append(FishingRun.from_mapping(raw))
            self._runs_cache = rows
        if role_key is None:
            return list(self._runs_cache)
        key = _role_key(role_key)
        return [run for run in self._runs_cache if run.role_key == key]

    def run_count(self, role_key: str | None = None) -> int:
        return len(self.runs(role_key))

    def recent_runs(self, role_key: str | None = None,
                    window: int = ROLLING_WINDOW) -> list[FishingRun]:
        runs = self.runs(role_key)
        return runs[-window:] if window and window > 0 else runs

    # ------------------------------------------------------------- derived (§1/§14)
    def points_per_bait_rolling(self, role_key: str, window: int = ROLLING_WINDOW) -> float | None:
        """The efficiency a forecast is allowed to multiply by, or ``None``.

        Normal bait only: a special-mode row would inflate the figure the policy exists to
        protect, so the lane filter is applied before any arithmetic rather than after.
        """
        values = [
            run.points_per_bait for run in self.recent_runs(role_key, window)
            if run.points_per_bait is not None
            and str(run.lane or "").upper() in ("", "NORMAL")
        ]
        return (sum(values) / len(values)) if values else None

    def seconds_per_run(self, role_key: str, window: int = ROLLING_WINDOW) -> float | None:
        """Median real level duration, or ``None``.  §15's deadline needs a measurement."""
        return _median_duration(self.recent_runs(role_key, window))

    def expected_final_points(self, role_key: str, now: datetime,
                              window: int = ROLLING_WINDOW) -> dict[str, Any]:
        """§14's forecast, with every input named so the arithmetic can be checked.

        Reports ``known=False`` rather than a number when an input is missing.  A forecast built
        on a guessed efficiency would move real scheduling priority, which is the one thing §14
        forbids: 禁止因为普通积分Goal频繁打断当前Role Session.
        """
        role = self.role(role_key)
        available = role.bait_available_until_end(now)
        per_bait = self.points_per_bait_rolling(role_key, window)
        basis = role.points_total
        if available is None or per_bait is None or basis is None:
            return {
                "known": False,
                "reason": "MISSING_INPUT",
                "points_total": basis,
                "bait_available": available,
                "points_per_bait_rolling": per_bait,
                "estimated_remaining_bait": available,
                "expected_final_points": None,
            }
        return {
            "known": True,
            "reason": "FORECAST",
            "points_total": basis,
            "bait_available": available,
            "points_per_bait_rolling": per_bait,
            "estimated_remaining_bait": available,
            "expected_final_points": float(basis) + float(available) * per_bait,
            "rolling_window": window,
            "regen_source": role.regen_source,
        }

    # ------------------------------------------------------------------ §16 view
    def kpis(self, role_key: str | None = None, window: int = ROLLING_WINDOW) -> dict[str, Any]:
        """The metric block for one role, or the event total when ``role_key`` is ``None``."""
        runs = self.runs(None if role_key is None else role_key)
        block = _summarise_runs(runs)
        role = self.role(role_key) if role_key is not None else None
        block[KPI_BAIT_WASTED] = role.bait_wasted_by_cap if role is not None else (
            sum(r.bait_wasted_by_cap for r in self.roles.values())
        )
        remaining = role.normal_bait_current if role is not None else sum(
            r.normal_bait_current or 0 for r in self.roles.values()
        )
        block[KPI_BAIT_REMAINING] = remaining
        return block

    def snapshot(self, now: datetime | None = None,
                 safety_margin_s: float = DEFAULT_SAFETY_MARGIN_SECONDS) -> dict[str, Any]:
        """Everything the console needs, per role, with no formatting decisions taken here."""
        moment = now or datetime.now(timezone.utc)
        roles: dict[str, Any] = {}
        for key in sorted(self.roles):
            role = self.roles[key]
            seconds = self.seconds_per_run(key)
            roles[key] = {
                "role_id": role.role_id,
                "name": role.name,
                "bait": (
                    f"{role.normal_bait_current}/{role.bait_cap}"
                    if role.state_is_read else "未读取"
                ),
                "bait_current": role.normal_bait_current,
                "bait_cap": role.bait_cap,
                "next_bait_at": _iso(role.next_bait_at),
                "event_end_at": _iso(role.event_end_at),
                "observed_at": _iso(role.observed_at),
                "points_total": role.points_total,
                "status": role.status,
                "pressure": role.pressure(moment, seconds_per_run=seconds,
                                          safety_margin_s=safety_margin_s).value,
                "endgame": role.endgame(moment, seconds_per_run=seconds,
                                        safety_margin_s=safety_margin_s),
                "regeneration_opportunities": role.remaining_regeneration_opportunities(moment),
                "bait_available_until_end": role.bait_available_until_end(moment),
                "projected_bait_at_end": role.projected_bait_at_end(moment),
                "regen_seconds": role.regen_seconds,
                "regen_source": role.regen_source,
                "seconds_per_run_p50": seconds,
                "kpis": self.kpis(key),
                "expected_final_points": self.expected_final_points(key, moment),
            }
        projected = [r.get("projected_bait_at_end") for r in roles.values()]
        return {
            "event_id": "FISHING_TOURNAMENT",
            "policy": "NORMAL_BAIT_ONLY",
            "at": _iso(moment),
            "roles": roles,
            "event_total": {
                **self.kpis(None),
                "NORMAL_BAIT_LEFT_AT_EVENT_END": (
                    sum(value for value in projected if isinstance(value, int))
                    if any(isinstance(value, int) for value in projected) else None
                ),
            },
        }

    # ------------------------------------------------------------------- writing
    def save(self) -> None:
        """Merge-and-write, atomically, preserving keys this schema does not know.

        Merge-preserving for the same reason the panel's own state files are: an older writer and
        this one must not erase each other's fields, and a third writer (the register tool) has
        already cost this project one overwritten live reading.
        """
        try:
            existing = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
        if not isinstance(existing, Mapping):
            existing = {}
        payload = dict(existing)
        payload.update(self.meta)
        payload["schema_version"] = SCHEMA_VERSION
        payload["policy"] = "NORMAL_BAIT_ONLY"
        payload["only_allowed_spend"] = "NORMAL_BAIT"
        payload.setdefault(
            "note",
            "role-scoped: bait / gear / points / collections are NEVER shared between roles",
        )
        roles = dict(existing.get("roles") or {})
        for key, role in self.roles.items():
            roles[key] = {**(roles.get(key) or {}), **role.to_mapping()}
        payload["roles"] = roles
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
            temporary.replace(self.path)
        except OSError:
            return


__all__ = [
    "BaitPressure",
    "parse_instant",
    "DEFAULT_LEDGER_PATH",
    "DEFAULT_PATH",
    "DEFAULT_SAFETY_MARGIN_SECONDS",
    "FishingRun",
    "FishingState",
    "KPI_AVG_DEPTH",
    "KPI_AVG_FISH_CAUGHT",
    "KPI_BAIT_REMAINING",
    "KPI_BAIT_USED",
    "KPI_BAIT_WASTED",
    "KPI_BEST_DEPTH",
    "KPI_BEST_POINTS_PER_BAIT",
    "KPI_COLLISION_RATE",
    "KPI_POINTS_PER_BAIT_AVG",
    "KPI_POINTS_PER_BAIT_P50",
    "KPI_TOTAL_POINTS",
    "PRIOR_REGEN_SECONDS",
    "REGEN_SOURCE_LIVE",
    "REGEN_SOURCE_PRIOR",
    "ROLLING_WINDOW",
    "RUN_VERIFIER_SIGNALS",
    "RoleFishingState",
    "SCHEMA_VERSION",
    "verify_run",
]
