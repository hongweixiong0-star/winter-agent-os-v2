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
* No second exploration bonus for *runnable* goals.  §四.7's "DISCOVERED gets a fair chance but
  may not occupy real work's resources" is **already** the sweep design: ``_sweep_value`` prices
  an unread page at 80-180, above routine gathering and below any claim.  Adding a bonus on top of
  it would double-count the same signal.

  The observation ticket is a different thing rather than a second copy of it: it applies only
  where the sweep cannot reach -- a goal whose ``priority`` is ``-inf`` and which therefore never
  entered the ranking at all.  Operator directive 2026-10-02 §5 forbids leaving such a goal
  permanently invisible ("启用Goal → UNKNOWN → priority=-inf → 永远没人再看"), and §11 requires its
  value to come from what the goal is worth rather than from whether a skill happens to exist.
  ``observation_ticket`` is that decision; see its docstring for what bounds it, and
  ``tools/invariant_review.py`` for the measurement that showed it was needed.
* No invented experience.  A route with no measured attempts scores zero, not a guess
  (operator §四.8).  The measured numbers come from
  ``knowledge/strategy/stamina_routes.json``, which until now **no code read** -- the
  card existed, its ``live_success_rate`` and ``cost_per_success`` were measured from
  ``learning/episodes.jsonl``, and the Scheduler never saw them.
* No displayed costs.  The card's own warning is binding here: the client shows 10 for
  a beast and the measured spend is 7, so only ``cost_per_success`` is ever used.
"""

from __future__ import annotations

import collections
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import entry_badges

ROOT = Path(__file__).resolve().parents[1]
ROUTES_PATH = ROOT / "knowledge/strategy/stamina_routes.json"
STATE_PATH = ROOT / "learning/goal_fairness.json"
#: Where :func:`_residency_table` learns which page a goal's work happens on.  The live
#: ledger, which is the same file the operator reads and the only place that records which
#: skill ran on which page.
LEDGER_PATH = ROOT / "learning/episodes.jsonl"

#: Ceilings, chosen against the existing price scale rather than picked for roundness.
#: See the module docstring: each one sits strictly inside a gap that already exists on
#: the board, so no combination of them can move a goal across a class boundary.
FAIRNESS_AGE_BONUS = 100.0
FAIRNESS_OVERDUE_MINUTES = 30.0
RESOURCE_FIT_BONUS = 40.0
HISTORY_BONUS = 30.0
REPEAT_FAILURE_PENALTY = 60.0
#: What it costs to leave a page we are already standing on, measured 2026-10-03.
#:
#: The ping-pong this bounds is not a tie-break wobble; it is a step that buys nothing.
#: Measured on the live ledger, most recent 400 steps (by ``recorded_at``): 101 of them were
#: ``OPEN_HOME``/``OPEN_MAP``, and **99 of the 101 landed correctly** -- so navigation is not
#: broken.  What the next step did is the whole defect:
#:
#:   29x  land on HOME from CLEAR_INTEL's ``OPEN_MAP``  -> KEEP_BUILDING_PRODUCTIVE -> ``OPEN_HOME``
#:   29x  land on MAP  from KEEP_BUILDING's ``OPEN_HOME`` -> CLEAR_INTEL          -> ``OPEN_MAP``
#:   14x  land on MAP  from KEEP_TRAINING's  ``OPEN_HOME`` -> KEEP_TRAINING      -> ``OPEN_HOME``
#:
#: 58 of the 99 (59%) were paid for and then refunded by the reverse hop, and every one of
#: those steps recorded ``goal_progress=False``.  The agent was not failing to arrive; it was
#: arriving correctly and then being re-ranked off the page it had just bought, because the
#: board is re-ranked every step against the frame it stands on and nothing in the price says
#: "this goal is the reason we are on this page".
#:
#: 40 is measured against the same gaps every other ceiling here is measured against.  The
#: ordinary band runs 70-250 (routine 70-90, an unread visit 180, a measured claim 250), so 40
#: lets a resident goal overtake another goal of its own class and can never reach a claim, the
#: bear (1000) or the stamina goal (2450).  It is deliberately *below*
#: :data:`REPEAT_FAILURE_PENALTY` (60): a goal that is on the right page but failing still
#: loses to one that is on the wrong page and working, so this cannot reward standing still.
PAGE_RESIDENCY_BONUS = 40.0
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


def _page_name(world: Any) -> str:
    """The current page as a plain upper-case name, whether it arrives as an enum or a string.

    ``WorldState.page`` is a ``Page`` enum, but this layer is handed ``Any`` and the string form
    is what a stored ``state_before`` carries (measured 2026-10-03: the ledger's rows hold
    ``{'page': 'HOME'}``, not an enum).  Reading only ``.value`` would answer "" for every
    ledger-shaped frame and the term would be silently inert -- the same failure
    ``observation_ticket`` documents below.  Both forms are accepted; an unrecognised object
    is "" rather than a guess.
    """
    page = getattr(world, "page", None)
    if page is None:
        return ""
    return str(getattr(page, "value", page) or "").strip().upper()


#: Skills that only ever change which page we stand on, and so can never make a goal
#: "resident" anywhere.  Named from the registry's own two page hops rather than invented:
#: ``runtime.PAGE_HOPS_THAT_ONLY_LOOK_FOR_GOALS`` already says these two exist for looking.
#:
#: Why they must be excluded, measured 2026-10-03 on the live ledger: ``Skill.required_page``
#: is the page a skill may be *fired from*, not the page it makes progress on, and for these
#: two it reads backwards -- ``OPEN_HOME`` declares ``MAP`` and ``OPEN_MAP`` declares ``HOME``,
#: because each is the control you press on the *other* page.  Left in, they hand every
#: goal a residency bonus for the page it is trying to leave.  Confirmed in the same window:
#: ``OPEN_MAP`` ran 108 times from HOME and ``OPEN_HOME`` 96 times from MAP, so this is where
#: the traffic actually is, not a corner case.
NAVIGATION_SKILL_IDS = frozenset({"OPEN_HOME", "OPEN_MAP"})

#: How much of a goal's own work has to happen on one page before that page counts as its home.
#:
#: Half, and half is measured rather than chosen.  On the last 2000 ledger steps:
#:
#:   DISCOVER_QUICK_PANEL_TASKS  HOME 231/231 = 100%
#:   MAIL_ROUTINE                MAIL  32/42  =  76%
#:   KEEP_BUILDING_PRODUCTIVE    HOME  45/98  =  46%
#:   CLEAR_INTEL                 MAP   53/242 =  22%   (POPUP 30%, INTEL 28%)
#:   AVOID_STAMINA_WASTE         MAP  104/337 =  31%   (EVENT 42%)
#:
#: The split that matters is not the percentage but the shape: a page-specific goal is nearly
#: all on its page, while a goal that ping-pongs is spread thin across many.  A share-only rule
#: would have to sit below 22% to exclude ``CLEAR_INTEL`` and would then also admit pages where
#: a goal merely passes through, so the test is **both** a majority and a minimum count --
#: a page must be where this goal usually is, and it must be a page this goal has actually
#: done something on more than once.  One lucky step is not a home.
RESIDENCY_PAGE_SHARE = 0.5
RESIDENCY_PAGE_MIN_STEPS = 5

#: The measured table, built once per process.  ``None`` means "not measured yet", which is
#: deliberately distinct from ``{}`` ("measured, and nothing qualifies"): the first pays the
#: ledger scan, the second short-circuits it.
_RESIDENT_PAGES: dict[str, frozenset] | None = None


def _residency_table(ledger_path: Path | None = None) -> dict[str, frozenset]:
    """``{goal_id: {pages its work happens on}}``, measured from the production ledger.

    A capability is *not* a property of a name: ``CLEAR_INTEL`` and ``KEEP_TRAINING_PRODUCTIVE``
    both appear on both pages, and only which skill ran there separates them.  So this reads
    the same rows the operator reads -- ``skill`` together with ``state_before.page`` -- and
    drops the navigation hops, because a page you visited in order to leave it is not a page
    you live on.  A page then has to be a *habitual* page (:data:`RESIDENCY_PAGE_SHARE` of this
    goal's steps, at least :data:`RESIDENCY_PAGE_MIN_STEPS` of them) rather than anywhere the
    goal has ever been seen once.

    An empty result is not a failure to be papered over.  If the ledger cannot be read the
    table is empty, every goal scores 0, and the board is ranked exactly as it was before
    this term existed -- which is the correct direction for a term whose whole purpose is to
    avoid inventing facts.
    """
    global _RESIDENT_PAGES
    if _RESIDENT_PAGES is not None and ledger_path is None:
        return _RESIDENT_PAGES

    counts: dict[str, collections.Counter] = {}
    source = LEDGER_PATH if ledger_path is None else Path(ledger_path)
    try:
        with source.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                goal_id = str(row.get("goal_id") or "")
                skill = str(row.get("skill") or "")
                before = row.get("state_before")
                page = str(before.get("page") or "") if isinstance(before, dict) else ""
                if (goal_id and page and skill
                        and skill not in NAVIGATION_SKILL_IDS
                        and page not in {"UNKNOWN", "LOADING", "MAINTENANCE"}):
                    counts.setdefault(goal_id, collections.Counter())[page] += 1
    except OSError:
        counts = {}

    table: dict[str, frozenset] = {}
    for goal_id, pages in counts.items():
        total = sum(pages.values())
        if total < RESIDENCY_PAGE_MIN_STEPS:
            continue
        habitual = frozenset(
            page for page, seen in pages.items()
            if seen >= RESIDENCY_PAGE_MIN_STEPS and seen / total >= RESIDENCY_PAGE_SHARE
        )
        if habitual:
            table[goal_id] = habitual
    if ledger_path is None:
        _RESIDENT_PAGES = table
    return table


def page_residency(world: Any, skills: Iterable[str], goal_id: str = "") -> float:
    """What it is worth that the page this goal needs is the page we are already on.

    The scheduler re-ranks the whole board on **every step**, against the frame the agent is
    standing on (operator §四/§五).  That is the right design and it is also, by itself, a
    ping-pong generator: nothing in the price records *why* the agent came to this page, so a
    goal that just paid for a hop can be priced off it one step later by a goal of equal worth
    that wants the other page.  Both then alternate forever, and every hop is individually
    correct.

    This is the term that says the page was not free.  It is bounded, it only ever *adds* to a
    goal that is already selectable, and :data:`PAGE_RESIDENCY_BONUS` is held under
    :data:`REPEAT_FAILURE_PENALTY` so a resident-but-failing goal still loses to a visitor
    who can actually work -- this prices being here, never being stuck here.

    Zero is the honest answer in every other case: an unnamed or transient page, no world, no
    skills, a goal with no measured page of its own, or a goal whose only page here was a
    navigation hop.  "We are not on its page" is never penalised; the reverse hop is priced by
    the goal that is standing here, which is the side that already paid.
    """
    del skills  # the goal's own measured pages are the answer; see _residency_table
    if world is None or not goal_id:
        return 0.0
    page = _page_name(world)
    if not page or page in {"UNKNOWN", "LOADING", "MAINTENANCE"}:
        return 0.0
    if page in _residency_table().get(str(goal_id), ()):
        return PAGE_RESIDENCY_BONUS
    return 0.0



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


#: What it is worth to *go and look* at a goal we cannot run yet.
#:
#: Operator directive 2026-10-02 §5 and §11, and the reason this module no longer answers "-inf"
#: for every UNKNOWN: §5 forbids "启用Goal → UNKNOWN → priority=-inf → 永远没人再看", and §11
#: requires GoalValue to be decoupled from ExecutionReadiness.  A goal that cannot be executed
#: this frame is still work -- observation work -- and the board has to be able to say so.
#:
#: Measured 2026-10-02 before this existed: ``tools/invariant_review.py`` reported
#: NO_PERMANENT_UNKNOWN_BLACKHOLE = FAIL and HIGH_VALUE_UNKNOWN_NOT_STARVED = FAIL, and its
#: simulated §17 world selected one goal out of five for a role whose work was entirely UNKNOWN.
#:
#: The ceilings are chosen the same way ``RED_DOT_BONUS`` was -- against the gaps that already
#: exist on the board, never for roundness.  Routine work prices at 70-250, intel at 800, the bear
#: at 1000, the stamina goal near 2455.  300 lets a genuinely valuable UNKNOWN outrank ordinary
#: routine work, which is what §一 asks for ("HIGH_VALUE_UNKNOWN 必须能够和 HIGH_VALUE_KNOWN 直接
#: 竞争"), and still cannot reach the work that pays.  0.5 is the share because looking is worth
#: half of doing: it produces no goal progress, and pricing it at par would let a board of
#: unknowns outrank the work that actually advances the account.
OBSERVATION_TICKET_CEILING = 300.0
OBSERVATION_TICKET_SHARE = 0.5
#: The price of a goal that has declared what it is waiting for but has **never been observed**, so
#: nothing about its value is known yet.  Below the routine band (routine prices at 70-250) on
#: purpose: finding out is worth less than doing, so this can never displace work that pays, while
#: the fairness ledger is what eventually gives such a goal its turn.
OBSERVATION_TICKET_FLOOR = 50.0


def observation_ticket(goal: Any) -> float:
    """What this goal is worth to observe, or 0 when it may not be observed at all.

    Two gates, both of them the project's own existing declarations rather than new policy:

    * the status must be ``UNKNOWN``.  ``COMPLETE``, ``BLOCKED``, ``SCHEDULED_NOT_OPEN`` and
      ``EXPIRED`` keep their ``-inf``: those statuses say "not this frame" for reasons observation
      cannot change, and re-pricing them would be the re-tiering this module exists to avoid.
    * the goal must carry ``evidence["required_observation"]``.  That field already exists and
      already names what has to be read off the client -- ``USE_NORMAL_FISHING_BAIT`` and the
      fishing claims set it.  Requiring it is §5's second half: a goal may stay unreachable only
      while the system can say *what it is waiting to learn*.  A goal with nothing to observe gets
      no ticket and stays off the board, which keeps this from becoming a blanket amnesty.

    A route is deliberately **not** required here.  It was tried, on 2026-10-02, to close the
    separate defect that a priced goal with no route is selected and then given
    ``brain.current_goal = None``; ``tools/invariant_review.py`` refuted it immediately, with three
    invariants -- ``NO_PERMANENT_UNKNOWN_BLACKHOLE``, ``HIGH_VALUE_UNKNOWN_NOT_STARVED`` and
    ``NEVER_OBSERVED_UNKNOWN_STILL_ON_BOARD`` -- all of which define "on the board" as *this
    function's* answer.  So the ticket's job is to make the goal visible even when nothing can act
    on it yet, and refusing to *act* on an unrouted goal belongs at the selection boundary, where
    ``runtime._selectable`` records it by name.  Priced but not selectable is the honest state;
    unpriced and invisible is §5's forbidden blackhole.

    A ticket is **not** permission.  It puts the goal where the Scheduler can see it; whether
    anything may then happen is still decided by ``capability_bootstrap`` (which refuses
    consumption, rally and purchase verbs outright) and by the capability gate.
    """
    status = getattr(goal, "status", None)
    if str(getattr(status, "value", status) or "") != "UNKNOWN":
        return 0.0
    evidence = getattr(goal, "evidence", None)
    if not isinstance(evidence, Mapping) or not evidence.get("required_observation"):
        return 0.0
    # A projection is not an observer.  Some rows are records *about* work rather than work:
    # ``_append_alliance_timed_provider`` builds ``ALLIANCE_TIMED_EVENTS`` with
    # ``available_skills=()`` and ``execution_owner="EXISTING_EVENT_GOALS"``, and its own
    # docstring says it is "a provider record, never a second execution instance".  Such a
    # row may be priced and refused, but it may not hold a ticket, because a ticket is a
    # promise that somebody will go and read what it is waiting for.
    #
    # Measured 2026-10-03 on the live board: that row answered 50.0 while carrying no route
    # and, with ``linked_goal_ids == []``, no owner either -- so it was ranked by a ticket
    # and then refused at the selection boundary with "priced as observable but has no
    # route".  A ticket nobody can act on is the operator's forbidden state reached from a
    # new direction: not "no skill" but "no skill **and no owner**".
    #
    # The test is the row's own ``execution_owner`` rather than a list of goal ids, so a
    # future projection is recognised by declaring itself one instead of by being added to
    # a table here.  ``linked_goal_ids`` is the second half and is deliberately *not* the
    # test: a projection whose owner happens to be on the board is still not the thing that
    # will read anything -- the owner is -- and the observation belongs to the owner's own
    # row.  The row stays visible either way, which is what keeps this from becoming the
    # "unpriced and invisible" black hole the same function's docstring warns about.
    if str(evidence.get("execution_owner") or "").strip().upper() in {
            "EXISTING_EVENT_GOALS", "EXTERNAL_OWNER",
    }:
        return 0.0
    from .goal_library import deadline_pressure  # local: goal_library imports this module

    def number(name: str) -> float:
        return _number(getattr(goal, name, None)) or 0.0

    raw = (deadline_pressure(getattr(goal, "remaining_seconds", None))
           + number("reward_value") + number("daily_loss")
           + number("event_synergy") + number("development_value")
           - number("resource_cost") - number("risk"))
    # A goal nobody has ever observed has no measured value, and that is *why* it is unobserved:
    # every value term on the live board's UNKNOWN entries is 0.0.  Requiring ``raw > 0`` therefore
    # gated the ticket on the very information the ticket exists to obtain.
    #
    # Measured 2026-10-02 on the live board: ``USE_FREE_ARENA_ATTEMPTS`` and ``LABYRINTH_DAILY``
    # are UNKNOWN and declare ``evidence["required_observation"]``, but their reward_value,
    # daily_loss, event_synergy, development_value, resource_cost and risk are all 0.0 -- so the
    # ticket answered 0.0, ``utility`` answered ``-inf``, and ``rank()`` dropped them.  The
    # mechanism was inert for exactly the goals it was written for, and ``tools/invariant_review.py``
    # still reported PASS because every fixture it simulates carries a value.
    #
    # The two gates above remain the licence -- status UNKNOWN *and* a declared observation -- and
    # the value only sets the price.  A goal that has measured nothing yet is priced at the floor,
    # which is below routine work, so it is on the board and observable without being able to
    # displace anything; the fairness ledger rotates it in, exactly as it does for the valuable
    # tickets that reach the ceiling.
    return min(OBSERVATION_TICKET_CEILING,
               max(OBSERVATION_TICKET_FLOOR, raw * OBSERVATION_TICKET_SHARE))


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
    event_readiness: float = 0.0
    #: The page this goal needs is the page we are already standing on, so a hop is not paid
    #: for a second time.  See :func:`page_residency` for the measurement that made it
    #: necessary and :data:`PAGE_RESIDENCY_BONUS` for why it is bounded under the failure
    #: penalty.
    page_residency: float = 0.0
    #: Set when this goal could not run at all and was priced by an observation ticket instead.
    #: In that case it **equals** ``base`` -- recorded separately only so the decision log can say
    #: so, rather than leaving the reader to infer it from an empty ``available_skills`` list.
    #: Deliberately not added into ``total``: the ticket *is* the base, and counting one signal
    #: twice is what this module's own docstring forbids.
    observation: float = 0.0
    #: The entries whose own dot produced ``red_dot``.  Carried here rather than looked up again by
    #: the caller because the frame the term was computed on is the only frame that can explain it.
    red_dot_on: tuple[str, ...] = ()

    @property
    def total(self) -> float:
        return (self.base + self.fairness + self.resource + self.history
                + self.repeat_failure + self.red_dot + self.event_readiness
                + self.page_residency)

    @property
    def dynamic(self) -> float:
        return (self.fairness + self.resource + self.history + self.repeat_failure
                + self.red_dot + self.event_readiness + self.page_residency)

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
            "event_readiness": round(self.event_readiness, 1),
            "page_residency": round(self.page_residency, 1),
            "observation": round(self.observation, 1),
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
        if self.event_readiness:
            parts.append(f"event-readiness {self.event_readiness:+.1f}")
        if self.page_residency:
            parts.append(f"page-residency {self.page_residency:+.1f} (already standing on its page)")
        if self.observation:
            parts.append(f"observation-ticket {self.observation:.1f} (unrunnable, nothing learned "
                         f"yet -- the ticket is the base, not an extra term)")
        return ", ".join(parts) if parts else "catalogue price only"


def utility(
    goal: Any,
    *,
    world: Any = None,
    facts: Iterable[RouteFact] = (),
    row: GoalFairness | None = None,
    event_readiness: float = 0.0,
    now: datetime | None = None,
) -> UtilityBreakdown:
    """The catalogue price plus what is only known at this moment.

    ``goal`` is a ``GoalState``.  Its static ``priority`` is the base and is never
    recomputed here -- see the module docstring for why that matters.
    """
    base = float(goal.priority)
    ticket = 0.0
    if base == float("-inf"):
        # §5/§11: an unrunnable goal is not a nonexistent one.  A goal that has declared what it
        # is waiting to observe is priced as observation work rather than answered "-inf" and
        # dropped from the board; a goal that has declared nothing keeps the old answer exactly.
        ticket = observation_ticket(goal)
        if ticket <= 0:
            return UtilityBreakdown(goal_id=str(goal.goal_id), base=base)
        base = ticket
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
        event_readiness=max(0.0, float(event_readiness)),
        page_residency=(page_residency(world, skills, str(goal.goal_id))
                        if world is not None else 0.0),
        observation=ticket,
    )


def rank(
    goals: Iterable[Any],
    *,
    world: Any = None,
    facts: Iterable[RouteFact] = (),
    ledger: Mapping[str, GoalFairness] | None = None,
    event_readiness: Mapping[str, float] | None = None,
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
        if not getattr(goal, "available_skills", ()) and observation_ticket(goal) <= 0:
            # §5: "no skill" is a different execution strategy, not an exclusion condition.
            # A goal with something to observe stays on the board; one with neither a skill nor
            # anything to observe still does not.
            continue
        breakdown = utility(
            goal, world=world, facts=facts,
            row=rows.get(str(goal.goal_id)),
            event_readiness=(event_readiness or {}).get(str(goal.goal_id), 0.0),
            now=moment,
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
