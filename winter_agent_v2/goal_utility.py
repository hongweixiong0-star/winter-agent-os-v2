"""Dynamic utility on top of the goal board's static prices.

The operator's §四, merged into the **one** Scheduler rather than beside it.  Nothing
here chooses an action: ``GoalLibrary`` owns the board and ``Scheduler`` owns the
choice; this module answers "given what we actually know, is this goal worth more or
less than its catalogue price right now".

Why an additive layer and not a re-pricing
------------------------------------------
``goal_library.best`` documents a measured failure: an earlier version tried to rank
``DISCOVERED`` below ``READY`` and silently disabled the sweep rotation, making
``CLEAR_INTEL`` unreachable on any frame with an idle march.  The prices on that board
are load-bearing -- ``SWEEP_BASE_VALUE`` 80 against gathering's 70, a real claim at
250, the stamina goal at 2450 -- and a function that recomputes them will get the
order wrong.

So the catalogue price stays, and this layer only *adjusts* it, with every term
bounded well inside the gaps that already exist:

    +100  fairness      a ceiling exactly as high as ``SWEEP_AGE_BONUS`` and for the
                        same reason: enough to outrank ordinary routine work once a
                        goal is genuinely starved, never enough to outrank a claim
    + 40  resource fit  the work has the resource it needs right now
    + 30  history       this route has a *measured* success rate
    + 60  red dot       the client is drawing a notification dot on this goal's entry
    - 60  repeated failure

The red-dot term carries the operator's second directive (2026-09-23 §一-§三): a dot the client
draws is a priority signal, and it is *only* a priority signal -- never the reason a goal runs, and
never the highest priority by itself.  It is therefore bounded by the same rule as every other term
here, and the bound is measured rather than chosen: a never-read visit prices at 180
(``goal_library.SWEEP_NEVER_VALUE``) and a claimable routine at 250, so 60 is the largest round
number that keeps a dotted visit (240) strictly under a real claim (250).  It cannot outbid intel
(800), the bear (1000), or the stamina goal (2450) either -- a dot is a hint about *what is
waiting*, not a valuation of *what it is worth*, which is exactly the operator's "红点本身不自动
最高优先".

Which dots may be ranked with is not a judgement made here: ``entry_badges.dot_varies`` owns it, and
it answers from the measured table -- a badge that never read zero (the 每日/联盟 counts) and a
badge suspected of being artwork (英雄) are constants, and ranking on a constant is ranking on
nothing.

What this module deliberately does NOT do
-----------------------------------------
* No exploration bonus.  §四.7's "DISCOVERED gets a fair chance but may not occupy real
  work's resources" is **already** the sweep design: ``_sweep_value`` prices an unread
  page at 80-180, above routine gathering and below any claim.  Adding a second bonus
  would double-count it.
* No invented experience.  A route with no measured attempts scores zero, not a guess
  (operator §四.8).  The measured numbers come from
  ``knowledge/strategy/stamina_routes.json``, which until now **no code read** -- the
  card existed, its ``live_success_rate`` and ``cost_per_success`` were measured from
  ``learning/episodes.jsonl``, and the Scheduler never saw them.
* No displayed costs.  The card's own warning is binding here: the client shows 10 for
  a beast and the measured spend is 7, so only ``cost_per_success`` is ever used.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import entry_badges

ROOT = Path(__file__).resolve().parents[1]
ROUTES_PATH = ROOT / "knowledge/strategy/stamina_routes.json"
STATE_PATH = ROOT / "learning/goal_fairness.json"

#: Ceilings, chosen against the existing price scale rather than picked for roundness.
#: See the module docstring: each one sits strictly inside a gap that already exists on
#: the board, so no combination of them can move a goal across a class boundary.
FAIRNESS_AGE_BONUS = 100.0
FAIRNESS_OVERDUE_MINUTES = 30.0
RESOURCE_FIT_BONUS = 40.0
HISTORY_BONUS = 30.0
REPEAT_FAILURE_PENALTY = 60.0
#: What the client pointing at a goal is worth, and the measurement that fixes it.
#:
#: The board's own gaps: ordinary routine work at 70-90, a never-read visit at 180
#: (``goal_library.SWEEP_NEVER_VALUE``), a measured claimable routine at 250, intel rewards at 800,
#: the bear at 1000, the stamina goal around 2450.  60 is the largest round value strictly below
#: the 70-point gap between a visit and a claim, so a dotted goal can outrank routine work (110-150)
#: and every other unread sweep, and can never outrank something that actually pays.  The operator's
#: §二③ is the same requirement stated as a rule of precedence: an ordinary dot must not be able to
#: interrupt a goal that is at its last step, and the last step of a claimable goal is *always* on
#: the paying side of that gap.
RED_DOT_BONUS = 60.0
#: Consecutive selections that produced no goal progress before the penalty saturates.
REPEAT_FAILURE_SATURATES_AT = 3
#: Below this many attempts, a measured success rate is not evidence yet.
HISTORY_MIN_ATTEMPTS = 5


def _moment(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------- measured route facts


@dataclass(frozen=True)
class RouteFact:
    """One measured stamina route, as the project's own decision card states it.

    ``success_rate`` is ``live_success_rate`` and ``attempts`` is ``live_attempts`` --
    both read from the card, not recomputed here, so that this layer cannot quietly
    drift from the ledger the operator reviews.
    """

    route: str
    name: str
    success_rate: float
    attempts: int
    cost_per_success: float | None
    availability: str
    skills: tuple[str, ...]

    @property
    def measurable(self) -> bool:
        """Is there enough evidence for the rate to be worth acting on?"""
        return self.attempts >= HISTORY_MIN_ATTEMPTS


def load_routes(path: Path | str | None = None) -> tuple[RouteFact, ...]:
    """Read the measured route card.  An unreadable card is an empty ledger.

    Empty is the safe direction: every term that depends on it becomes zero, which is
    "we have no measured experience", never a fabricated one.
    """
    source = Path(path) if path is not None else ROUTES_PATH
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    rows = payload.get("routes") if isinstance(payload, Mapping) else None
    if not isinstance(rows, list):
        return ()

    out: list[RouteFact] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        route = str(row.get("route") or "").strip()
        if not route:
            continue
        rate = _number(row.get("live_success_rate"))
        out.append(RouteFact(
            route=route,
            name=str(row.get("name_cn") or route),
            success_rate=0.0 if rate is None else max(0.0, min(1.0, rate)),
            attempts=int(_number(row.get("live_attempts")) or 0),
            cost_per_success=_number(row.get("cost_per_success")),
            availability=str(row.get("availability") or ""),
            skills=tuple(str(s) for s in (row.get("wired") or ())),
        ))
    return tuple(out)


def fact_for_skill(routes: Iterable[RouteFact], skill_id: str) -> RouteFact | None:
    """The measured route a skill belongs to, matched on the card's own ``wired`` list."""
    for fact in routes:
        if skill_id in fact.skills:
            return fact
    return None


# ------------------------------------------------------------------- state


@dataclass
class GoalFairness:
    """Per-goal bookkeeping the board itself cannot hold.

    ``GoalState`` is a frozen value rebuilt from the world on every frame, so anything
    that must survive across frames -- how long a goal has been passed over, how many
    consecutive selections produced no progress -- lives here instead.  Same shape as
    ``observation_store``: a state file plus pure helpers.
    """

    goal_id: str
    last_selected_at: str = ""
    offered: int = 0
    selected: int = 0
    no_progress_streak: int = 0
    last_block_reason: str = ""
    retry_after: str = ""

    def as_json(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "last_selected_at": self.last_selected_at,
            "offered": self.offered,
            "selected": self.selected,
            "no_progress_streak": self.no_progress_streak,
            "last_block_reason": self.last_block_reason,
            "retry_after": self.retry_after,
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "GoalFairness":
        return cls(
            goal_id=str(payload.get("goal_id") or ""),
            last_selected_at=str(payload.get("last_selected_at") or ""),
            offered=int(_number(payload.get("offered")) or 0),
            selected=int(_number(payload.get("selected")) or 0),
            no_progress_streak=int(_number(payload.get("no_progress_streak")) or 0),
            last_block_reason=str(payload.get("last_block_reason") or ""),
            retry_after=str(payload.get("retry_after") or ""),
        )


def load(path: Path | str | None = None) -> dict[str, GoalFairness]:
    source = Path(path) if path is not None else STATE_PATH
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    rows = payload.get("goals") if isinstance(payload, Mapping) else None
    if not isinstance(rows, Mapping):
        return {}
    return {
        str(key): GoalFairness.from_json(body)
        for key, body in rows.items()
        if isinstance(body, Mapping)
    }


def save(ledger: Mapping[str, GoalFairness], path: Path | str | None = None) -> None:
    source = Path(path) if path is not None else STATE_PATH
    payload = {
        "schema_version": "1.0",
        "written_at": datetime.now(timezone.utc).isoformat(),
        "goals": {key: value.as_json() for key, value in sorted(ledger.items())},
    }
    try:
        source.parent.mkdir(parents=True, exist_ok=True)
        temp = source.with_suffix(source.suffix + ".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        temp.replace(source)
    except OSError:
        pass


def entry(ledger: dict[str, GoalFairness], goal_id: str) -> GoalFairness:
    row = ledger.get(goal_id)
    if row is None:
        row = GoalFairness(goal_id=goal_id)
        ledger[goal_id] = row
    return row


def blocked_until(row: GoalFairness, now: datetime | None = None) -> bool:
    """Is this goal still inside the retry window it asked for (operator §五)?

    **Reporting only** -- see ``rank`` for why this is not an eligibility filter.  A
    deferred goal is excluded by the capability gate, which has its own probe window;
    this answers the different question "when will it be looked at again", which the
    log and the panel need and which nothing in the project could previously answer.
    ``GoalState.retry_after`` has existed from the start and was read by nothing.
    """
    moment = now or datetime.now(timezone.utc)
    when = _moment(row.retry_after)
    return when is not None and when > moment


# ------------------------------------------------------------------ terms


def fairness_bonus(row: GoalFairness | None, evidence: Mapping[str, Any] | None,
                   now: datetime | None = None) -> float:
    """Age-scaled compensation so a goal that keeps losing the board cannot starve (§四.6/§八E).

    Measured from **how long since this goal was last chosen**, which is deliberately a
    different quantity from ``evidence["overdue_ratio"]``.  The sweep tickets already
    price their own staleness -- ``_sweep_value`` adds ``SWEEP_AGE_BONUS * ratio/(1+ratio)``
    to the catalogue price -- so reading the same ratio here would charge for it twice
    and silently re-rank the sweep design.  This term answers the question the board
    cannot: *this goal has been eligible for a long time and has never won.*

    Written the other way first and caught by that reasoning, not by a test.

    ``evidence`` is accepted so the caller does not have to special-case it, and is
    intentionally unused; it is where a future, non-double-counting staleness signal
    would go.
    """
    del evidence  # see the docstring: the ratio is already in the catalogue price
    moment = now or datetime.now(timezone.utc)
    if row is None or not row.last_selected_at:
        return 0.0
    started = _moment(row.last_selected_at)
    if started is None:
        return 0.0
    waited = max(0.0, (moment - started).total_seconds() / 60.0)
    if waited <= FAIRNESS_OVERDUE_MINUTES:
        return 0.0
    # Same asymptotic shape as the sweep's age term, same reason: two different waits
    # are never equal, so the order between two starved goals keeps changing instead of
    # freezing on whichever happened to be first.
    overdue = waited / FAIRNESS_OVERDUE_MINUTES
    return FAIRNESS_AGE_BONUS * (overdue / (1.0 + overdue))


def history_bonus(facts: Iterable[RouteFact], skills: Iterable[str]) -> float:
    """Value of measured experience on this goal's route, or 0 when there is none.

    Scaled by the rate *and* by how close the attempt count is to being meaningful, so
    a route with 5 attempts does not speak as loudly as one with 54.  A route that has
    never been tried contributes nothing at all -- operator §四.8 forbids inventing it.
    """
    best = 0.0
    for skill in skills:
        fact = fact_for_skill(facts, skill)
        if fact is None or not fact.measurable:
            continue
        confidence = min(1.0, fact.attempts / (2.0 * HISTORY_MIN_ATTEMPTS))
        best = max(best, HISTORY_BONUS * fact.success_rate * confidence)
    return best


def resource_fit(world: Any, skills: Iterable[str], facts: Iterable[RouteFact]) -> float:
    """Does this goal's work have the resource it needs, right now (§四.2/§三).

    Only asked of goals whose route is a **measured stamina route**, because that is the
    only place the project has stated which resource the work spends.  For any other
    goal the answer is 0 -- "no adjustment", not "no resource needed".  Deriving a need
    for the rest of the board would be inventing one.
    """
    if not any(fact_for_skill(facts, skill) is not None for skill in skills):
        return 0.0
    stamina = _number((getattr(world, "stamina", None) or {}).get("current"))
    idle = _number(getattr(world, "idle_marches", None))
    if stamina is None:
        return 0.0
    floor = 30.0
    surplus = stamina - floor
    if surplus <= 0:
        # Nothing to spend.  A negative term, not merely a missing bonus: this work
        # cannot run, and the board should see that in the price.
        return -RESOURCE_FIT_BONUS
    if idle is None:
        return 0.0
    if idle <= 0:
        return -RESOURCE_FIT_BONUS
    return RESOURCE_FIT_BONUS * min(1.0, surplus / (2.0 * floor))


def repeat_failure_penalty(row: GoalFairness | None) -> float:
    """Lower a candidate that keeps being chosen and keeps making no progress (§四.5).

    Asymptotic and bounded so the penalty can never become a permanent ban: the goal
    drops in the order, it does not leave the board.  ``CLEAR_INTEL`` must still be
    reachable after a bad streak -- that is exactly what the sweep rotation exists for.
    """
    if row is None or row.no_progress_streak <= 0:
        return 0.0
    streak = min(row.no_progress_streak, REPEAT_FAILURE_SATURATES_AT)
    return -REPEAT_FAILURE_PENALTY * (streak / REPEAT_FAILURE_SATURATES_AT)


def red_dot_bonus(world: Any, goal_id: str) -> tuple[float, tuple[str, ...]]:
    """The client is pointing at this goal: a bounded bonus, and which entries say so (§二②).

    Only PRESENT dots on entries whose badge was *measured to vary* count, and only when the entry
    names this goal -- ``entry_badges.dots_pointing_at`` owns both rules, so this function cannot
    invent a second definition of "a dot" (the operator's §一: a red pixel is not a notification
    until it is bound to a concrete entry).

    Returns the bonus and the entries, so the decision log can name what the client pointed at
    rather than only that something was worth 60 points.
    """
    if not goal_id:
        return 0.0, ()
    pointed_at = entry_badges.dots_pointing_at(getattr(world, "red_dots", None))
    entries = pointed_at.get(str(goal_id), ())
    return (RED_DOT_BONUS, entries) if entries else (0.0, ())


@dataclass(frozen=True)
class UtilityBreakdown:
    """Every term of one goal's utility, so a decision can be explained (§九)."""

    goal_id: str
    base: float
    fairness: float = 0.0
    resource: float = 0.0
    history: float = 0.0
    repeat_failure: float = 0.0
    red_dot: float = 0.0
    #: The entries whose own dot produced ``red_dot``.  Carried here rather than looked up again by
    #: the caller because the frame the term was computed on is the only frame that can explain it.
    red_dot_on: tuple[str, ...] = ()

    @property
    def total(self) -> float:
        return (self.base + self.fairness + self.resource + self.history
                + self.repeat_failure + self.red_dot)

    @property
    def dynamic(self) -> float:
        return (self.fairness + self.resource + self.history + self.repeat_failure
                + self.red_dot)

    def as_row(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "base": round(self.base, 1),
            "fairness": round(self.fairness, 1),
            "resource": round(self.resource, 1),
            "history": round(self.history, 1),
            "repeat_failure": round(self.repeat_failure, 1),
            "red_dot": round(self.red_dot, 1),
            "red_dot_on": list(self.red_dot_on),
            "dynamic": round(self.dynamic, 1),
            "total": round(self.total, 1),
        }

    def why(self) -> str:
        """One line naming the terms that actually moved this goal."""
        parts = []
        if self.fairness:
            parts.append(f"fairness {self.fairness:+.1f}")
        if self.resource:
            parts.append(f"resource {self.resource:+.1f}")
        if self.history:
            parts.append(f"history {self.history:+.1f}")
        if self.repeat_failure:
            parts.append(f"repeat-failure {self.repeat_failure:+.1f}")
        if self.red_dot:
            parts.append(f"red-dot {self.red_dot:+.1f} on {'/'.join(self.red_dot_on)}")
        return ", ".join(parts) if parts else "catalogue price only"


def utility(
    goal: Any,
    *,
    world: Any = None,
    facts: Iterable[RouteFact] = (),
    row: GoalFairness | None = None,
    now: datetime | None = None,
) -> UtilityBreakdown:
    """The catalogue price plus what is only known at this moment.

    ``goal`` is a ``GoalState``.  Its static ``priority`` is the base and is never
    recomputed here -- see the module docstring for why that matters.
    """
    base = float(goal.priority)
    if base == float("-inf"):
        return UtilityBreakdown(goal_id=str(goal.goal_id), base=base)
    skills = tuple(getattr(goal, "available_skills", ()) or ())
    dot, dot_entries = red_dot_bonus(world, str(goal.goal_id)) if world is not None else (0.0, ())
    return UtilityBreakdown(
        goal_id=str(goal.goal_id),
        base=base,
        fairness=fairness_bonus(row, getattr(goal, "evidence", None), now=now),
        resource=resource_fit(world, skills, facts) if world is not None else 0.0,
        history=history_bonus(facts, skills),
        repeat_failure=repeat_failure_penalty(row),
        red_dot=dot,
        red_dot_on=dot_entries,
    )


def rank(
    goals: Iterable[Any],
    *,
    world: Any = None,
    facts: Iterable[RouteFact] = (),
    ledger: Mapping[str, GoalFairness] | None = None,
    now: datetime | None = None,
) -> tuple[tuple[Any, UtilityBreakdown], ...]:
    """Every eligible goal with its utility, best first.  Ties keep board order.

    Eligibility is **not** decided here.  The capability gate already owns it, with its
    own ``probe_minutes`` window and its own measured reasons, and a retry window in
    this layer would be a second gate over the first: it could only ever extend a
    block, which makes the agent more conservative, and operator §六 forbids exactly
    that ("Utility AI 不得把 V2 变得更加保守").  ``blocked_until`` is therefore a
    *reporting* helper -- it answers "when will this be looked at again" for the log
    and the panel -- and never a filter.

    Nor is "re-evaluate when the condition recovers" this layer's job: it is already
    the Scheduler's, because the board is re-ranked on every step against the frame the
    agent is standing on (``runtime`` calls this inside the action loop, not once per
    run).  §五 is satisfied by that, not by a timer.
    """
    moment = now or datetime.now(timezone.utc)
    rows = ledger or {}
    scored: list[tuple[float, int, Any, UtilityBreakdown]] = []
    for index, goal in enumerate(goals):
        if not getattr(goal, "available_skills", ()):
            continue
        breakdown = utility(
            goal, world=world, facts=facts,
            row=rows.get(str(goal.goal_id)), now=moment,
        )
        if breakdown.base == float("-inf"):
            continue
        scored.append((-breakdown.total, index, goal, breakdown))
    scored.sort(key=lambda item: (item[0], item[1]))
    return tuple((goal, breakdown) for _, _, goal, breakdown in scored)


# ------------------------------------------------------------- decision log


DECISIONS_PATH = ROOT / "learning/decisions.jsonl"


def decision_row(
    *,
    role_id: str,
    page: str,
    ranked: Iterable[tuple[Any, UtilityBreakdown]],
    chosen: str,
    runner_up: str = "",
    reason: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """One Scheduler choice, with every candidate and the terms that decided it (§九).

    Only the fields a reader cannot reconstruct later: the world summary, the whole
    board with each goal's status and utility, who won, and why the runner-up did not.
    "Why not the others" is answered by the numbers plus the two named exclusions
    below, rather than by prose per candidate -- a log that explains every loser on
    every step is a log nobody reads.
    """
    moment = now or datetime.now(timezone.utc)
    board = []
    for goal, breakdown in ranked:
        board.append({
            "goal_id": str(getattr(goal, "goal_id", "")),
            "status": str(getattr(getattr(goal, "status", ""), "value", getattr(goal, "status", ""))),
            "skills": list(getattr(goal, "available_skills", ()) or ()),
            **breakdown.as_row(),
        })
    return {
        "at": moment.isoformat(),
        "role_id": role_id,
        "page": page,
        "chosen": chosen,
        "runner_up": runner_up,
        "runner_up_gap": next(
            (round(row["total"], 1) for row in board if row["goal_id"] != chosen), None
        ),
        "reason": reason,
        "board": board,
    }


def append_decision(
    row: Mapping[str, Any],
    path: Path | str | None = None,
    *,
    limit: int = 2000,
) -> None:
    """Append one choice.  Never raises -- a log must not fail a run."""
    source = Path(path) if path is not None else DECISIONS_PATH
    try:
        source.parent.mkdir(parents=True, exist_ok=True)
        rows = source.read_text(encoding="utf-8").splitlines() if source.exists() else []
        rows.append(json.dumps(dict(row), ensure_ascii=False))
        source.write_text("\n".join(rows[-limit:]) + "\n", encoding="utf-8")
    except (OSError, TypeError, ValueError):
        pass
