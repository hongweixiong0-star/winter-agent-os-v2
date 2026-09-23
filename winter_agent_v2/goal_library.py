from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .camp_training import CAMP_LABELS, CAMP_ORDER, TROOP_TO_CAMP
from .models import WorldState
from . import entry_badges
from . import goal_utility
from .rally import BearPhase, bear_phase

#: The operator's stamina floor: the spend goal is satisfied once stamina is BELOW it.
#:
#: 30 itself does NOT qualify.  The requirement is worded as "stamina under 30" and the
#: operator confirmed the boundary explicitly -- "体力达到30时仍未低于30" -- so the
#: comparison is ``< 30``, not ``<= 30``.  It used to be ``> 30`` for READY, which stopped
#: the goal one point early and called it COMPLETE at exactly 30; the distance meter was
#: ``stamina - 30``, which read 0 at the same moment.  Kept as one constant because it is
#: the same number in the goal's status, its completion, its loss estimate and its
#: distance, and four copies of a boundary is how they drift apart.
STAMINA_FLOOR = 30

#: One training goal per barracks (open issue #86).
#:
#: The client has three camps on one page.  A single goal reading a single queue made one
#: running camp close the whole check, so the other two were never opened.  These are the
#: per-camp goals; ``KEEP_TRAINING_PRODUCTIVE`` survives only as the label for a legacy
#: reading that names no camp.  The ids are stable and are what the panel and the episode
#: stream report, so "which camp was blocked" is answerable from the record.
CAMP_GOAL_FOR: dict[str, str] = {
    "SHIELD_CAMP": "SHIELD_CAMP_TRAINING",
    "LANCER_CAMP": "LANCER_CAMP_TRAINING",
    "MARKSMAN_CAMP": "MARKSMAN_CAMP_TRAINING",
}

#: What a camp's training is worth when it has work, matching the old single goal's 90 so
#: the change is about *which camp* and not about re-pricing training against everything
#: else on the board.
TRAINING_CAMP_VALUE = 90.0

#: The goal id -> brain route translation, in one place.
#:
#: This started life inside ``LiveRuntime`` as a local dict, because that was the only caller
#: that needed it.  Measured 2026-09-21: it is not.  The panel's Development Validation cycle
#: passes a goal **id** on the command line while ``run_live.py --goal`` accepts only the
#: route **domains**, so the calibration was launched as
#: ``--goal KEEP_TRAINING_PRODUCTIVE`` and argparse rejected it before the device was ever
#: touched --
#:
#:     run_live.py: error: argument --goal: invalid choice: 'KEEP_TRAINING_PRODUCTIVE'
#:     (choose from HOME, GATHER_RESOURCE, BEAST_HUNT, INTEL, MAIL, EXPLORATION, DAILY,
#:      ALLIANCE, RESEARCH, TRAIN)
#:
#: Every calibration run exited 2 in under a second, took the device lease anyway, and the
#: panel narrated it as "验证运行结束（EXIT_2），停止原因 未知" -- a real failure reported as an
#: unknown one.  A second copy of the map would have had the same gap as soon as a goal was
#: added, which is precisely what happened to the camp goals, so the translation lives here
#: and both callers read it.
GOAL_ROUTES: dict[str, str] = {
    "CLEAR_INTEL": "INTEL",
    "AVOID_STAMINA_WASTE": "BEAST_HUNT",
    "KEEP_TRAINING_PRODUCTIVE": "TRAIN",
    "KEEP_RESEARCH_PRODUCTIVE": "RESEARCH",
    # The three camps are three goals and share the one route: the route is the training
    # *page*, and which camp it opens is the brain's decision driven by ``goal_id``.  A
    # second route name would be a second implementation of the same page.
    "SHIELD_CAMP_TRAINING": "TRAIN",
    "LANCER_CAMP_TRAINING": "TRAIN",
    "MARKSMAN_CAMP_TRAINING": "TRAIN",
    "MAIL_ROUTINE": "MAIL",
    "DAILY_ACTIVITY_TARGET": "DAILY",
    "ALLIANCE_ROUTINE": "ALLIANCE",
    "CLAIM_EXPLORATION_IDLE": "EXPLORATION",
    # Measured 2026-09-21: this one was missing, and it was the only goal ``discover`` can
    # emit that ``route_for`` answered ``None`` for.  It still worked -- ``RuleBrain`` with
    # ``current_goal=None`` falls into its gather branch, and 145 production episodes carry
    # this goal id -- but that is the default branch, not a decision.  The default happens to
    # agree today; the moment the gather branch moves or a second goal also goes unrouted,
    # "no route" stops meaning "gather" and the goal goes quietly inert (which is exactly how
    # four panel routines stayed invisible).  Named here so the route is chosen rather than
    # inherited, and ``test_every_goal_has_a_route`` keeps it that way.
    "KEEP_MARCHES_PRODUCTIVE": "GATHER_RESOURCE",
}

#: The domains ``run_live.py --goal`` accepts.  Kept beside :data:`GOAL_ROUTES` because the
#: two are the same question asked from opposite ends, and a test asserts every mapped route
#: is one of these -- a route ``run_live`` cannot accept is the EXIT_2 bug above.
ROUTE_DOMAINS: tuple[str, ...] = (
    "HOME", "GATHER_RESOURCE", "BEAST_HUNT", "INTEL", "MAIL",
    "EXPLORATION", "DAILY", "ALLIANCE", "RESEARCH", "TRAIN",
)


def route_for(goal_id: str | None) -> str | None:
    """The route ``run_live.py --goal`` will accept for ``goal_id``, or ``None``.

    ``None`` means "no route", and callers must treat it as such rather than pass the goal id
    through: a goal that is scheduled and given no route does nothing at all, and a goal id
    handed to ``--goal`` is rejected outright.

    A route domain is accepted as its own answer.  The ledger's ``goal`` field normally holds a
    goal **id**, but records already written hold domains too -- ``BEAST_HUNT`` is a real one,
    measured 2026-09-21, from the escalation that produced the beast examination -- and
    translating those would mean refusing to calibrate a version that is already pending.  The
    function is therefore idempotent: ids map to domains, domains pass through.
    """
    value = str(goal_id or "")
    if value in ROUTE_DOMAINS:
        return value
    return GOAL_ROUTES.get(value)



class GoalStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class GoalState:
    goal_id: str
    status: GoalStatus
    completion: float = 0.0
    remaining_seconds: int | None = None
    reward_value: float = 0.0
    daily_loss: float = 0.0
    event_synergy: float = 0.0
    development_value: float = 0.0
    resource_cost: float = 0.0
    risk: float = 0.0
    available_skills: tuple[str, ...] = ()
    retry_after: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    # How much is left before this goal is satisfied; smaller is closer, 0 is done.
    # This is the goal's own progress meter and it exists so that "the action's
    # verifier passed" and "the goal advanced" can never be the same statement
    # again.  Measured 2026-09-18: 58 consecutive AVOID_STAMINA_WASTE episodes all
    # passed their verifier while stamina never moved off 457 -- action progress
    # with no goal progress, which the scheduler read as a healthy goal.  Every
    # goal therefore has to answer "how far are you from being satisfied?" in a
    # comparable number, and the number is decided here, in the one place that
    # knows what the goal means.
    distance: float = 0.0

    @property
    def priority(self) -> float:
        if self.status in {GoalStatus.COMPLETE, GoalStatus.BLOCKED, GoalStatus.UNKNOWN}:
            return float("-inf")
        deadline = deadline_pressure(self.remaining_seconds)
        return deadline + self.reward_value + self.daily_loss + self.event_synergy + self.development_value - self.resource_cost - self.risk


def deadline_pressure(seconds: int | None) -> float:
    if seconds is None:
        return 0.0
    if seconds <= 0:
        return -100_000.0
    if seconds < 2 * 3600:
        return 10_000.0
    if seconds < 6 * 3600:
        return 4_000.0
    if seconds < 12 * 3600:
        return 2_000.0
    if seconds < 24 * 3600:
        return 1_000.0
    return 100.0


@dataclass(frozen=True)
class PanelRoutine:
    """A daily panel whose own reading decides whether there is work on it.

    These four goals were defined in ``goal_capability_map.json`` and **impossible to emit**:
    ``discover()`` had no branch for them, so the scheduler never chose to open the panel and
    the Goal Board showed them as 未读取 for ever.  Meanwhile the whole capability already
    existed -- vision reads ``Page.MAIL`` / ``Page.DAILY`` / ``Page.ALLIANCE`` /
    ``Page.EXPLORATION`` into these very fields, the brain has a page route and a MAP->panel
    route for each, and every skill involved is registered with a bound verifier.  What was
    missing was the entry point, not the ability.

    ``work`` and ``done`` are the page's own ``status`` words, copied from what vision writes,
    never invented.  A reading this table does not recognise is reported UNKNOWN, which is a
    capability gap -- distinct from having no reading at all (operator §6).
    """

    goal_id: str
    field: str
    work: tuple[str, ...]
    done: tuple[str, ...]
    work_skills: tuple[str, ...]
    entry_skill: str
    #: Small on purpose.  An unread routine must be *schedulable* (so it gets looked at) but
    #: must never outrank real work: measured 2615 for the stamina goal and 70 for gathering,
    #: against this 20.  So it is picked when nothing better is owed -- which is exactly the
    #: bounded observation sweep the operator asked for, expressed as priority rather than as
    #: a second scheduler.
    discovery_value: float = 20.0


PANEL_ROUTINES: tuple[PanelRoutine, ...] = (
    PanelRoutine(
        "MAIL_ROUTINE", "mail",
        work=("CLAIMABLE", "UNREAD", "HAS_BADGE"),
        done=("CLAIMED", "ALL_CLEAR", "NOT_AVAILABLE"),
        work_skills=("MAIL_CLAIM_REWARDS", "SELECT_MAIL_ALLIANCE_TAB",
                     "SELECT_MAIL_SYSTEM_TAB", "SELECT_MAIL_REPORT_TAB"),
        entry_skill="OPEN_MAIL",
    ),
    PanelRoutine(
        "DAILY_ACTIVITY_TARGET", "daily",
        # ``AVAILABLE`` is deliberately NOT work here.  Two live readings two minutes apart
        # settled it (2026-09-19): ``status=CLAIMABLE, claimable_count=1`` when there was a
        # reward, then ``status=AVAILABLE, claimable_count=0`` after claiming.  AVAILABLE means
        # "the page was read and the task list exists", not "something is claimable", so treating
        # it as work made the goal READY forever and re-opened the panel on every run -- the
        # repeated no-progress selection the operator names in §六.  The numeric count below is
        # the real signal, and it is checked first.
        work=("CLAIMABLE",),
        done=("AVAILABLE", "CLAIMED", "NOT_AVAILABLE"),
        # DAILY_HERO_RECRUIT is registered but has no live-loop verifier bound, and a skill
        # without one dies with SKILL_NOT_ENABLED_FOR_LIVE_LOOP -- so it is deliberately not
        # offered here until its verifier exists.
        work_skills=("DAILY_CLAIM_REWARDS",),
        entry_skill="OPEN_DAILY",
    ),
    PanelRoutine(
        "ALLIANCE_ROUTINE", "alliance",
        work=("CLAIMABLE", "AVAILABLE"),
        done=("CLAIMED", "CONTRIBUTED", "NOT_AVAILABLE"),
        work_skills=("ALLIANCE_GIFTS", "ALLIANCE_ALLY_GIFT_CLAIM"),
        entry_skill="OPEN_ALLIANCE",
    ),
    PanelRoutine(
        "CLAIM_EXPLORATION_IDLE", "exploration",
        work=("CLAIMABLE",),
        done=("CLAIMED", "NOT_READY", "NOT_AVAILABLE"),
        work_skills=("EXPLORATION_IDLE_CLAIM",),
        entry_skill="OPEN_EXPLORATION",
    ),
)


def _badge_present(reading: Mapping[str, Any]) -> bool:
    """Whether the panel's reading shows an unclaimed badge on any tab."""
    badges = reading.get("tab_badges")
    if not isinstance(badges, Mapping):
        return False
    return any(bool(value) for value in badges.values())


#: A due routine's discovery value, and how much age can add to it.
#:
#: Measured 2026-09-19 with a flat 20: the stamina goal priced at 2450 and gathering at 70, so
#: ``best()`` chose them on every run and no panel was ever swept -- the ticket existed and was
#: never selected.
#:
#: The age term is an **asymptote**, not a capped ramp, and that is the whole point.  A capped
#: ramp puts every overdue ticket at the same ceiling, they tie, and ``best()`` returns the first
#: of the tie -- so one ticket is re-selected forever: measured live, ``KEEP_RESEARCH_PRODUCTIVE``
#: was chosen twelve runs in a row to close the same reward popup, never once reaching its own
#: page.  ``ratio / (1 + ratio)`` is strictly increasing in the overdue ratio, so no two tickets
#: with different history are ever equal and the loop rotates to the one that has waited longest.
#: The ceiling stays under a real claim (a claimable routine is 250, intel rewards 500, the
#: stamina goal 2450) so the sweep never competes with work that pays.
SWEEP_BASE_VALUE = 80.0
SWEEP_AGE_BONUS = 100.0
#: What a domain that has **never** been read is worth, and why it is not the base value.
#:
#: Measured live 2026-09-19 on a healthy Goal Board: mail priced 167.5 (104.7 min overdue),
#: daily 157.6, exploration 150.1 -- and training and research sat at exactly 80, because with no
#: record at all their overdue ratio was 0.  So the two pages that had *never once been looked at*
#: were the cheapest tickets on the board, permanently outranked by pages that had merely gone
#: stale, and they were never selected.  That is the operator's §二 stated exactly: "不允许因为
#: WorldState 当前没有某个页面的数据，就永远不去检查该页面."
#:
#: Never-read means waited-for-ever, so it prices above any finite ratio's value (which
#: asymptotes to 180 from below) and still below anything that pays (a claimable routine is 250,
#: intel rewards 500).  Base value stays for the fresh-but-empty case, which is a real zero.
SWEEP_NEVER_VALUE = 180.0


def _sweep_value(overdue_ratio: float) -> float:
    ratio = max(0.0, float(overdue_ratio or 0.0))
    return SWEEP_BASE_VALUE + SWEEP_AGE_BONUS * (ratio / (1.0 + ratio))


#: Domains whose goal only exists **if a reading exists**, and which therefore had no way to be
#: looked at.  This is the same gap the panel routines had, one step further out:
#:
#: * ``CLEAR_INTEL`` is emitted when ``world.intel["status"] != "UNKNOWN"`` -- and nothing ever
#:   read the intel page, so the condition was never true and the goal never existed.
#: * the queue goals return early when their reading is empty (``_append_queue_goal``).
#:
#: Both are honest about what they know and useless as discovery entries.  A reading of "" means
#: *not looked at*, not *nothing to do*, so these get a sweep ticket exactly like the panels --
#: same store, same TTL reuse, same bounded age-scaled value, and their own entry skill (each of
#: which is registered and verifier-bound, which is what makes the ticket runnable).
#:
#: ``KEEP_BUILDING_PRODUCTIVE`` is deliberately **not** here: ``OPEN_BUILDING`` is not registered
#: and ``RuleBrain`` has no BUILD route, so a ticket for it would be a ticket to nowhere.  It
#: needs a skill and a route first, and that is a different piece of work from this one.
SWEEP_ROUTINES: tuple[PanelRoutine, ...] = (
    PanelRoutine(
        "CLEAR_INTEL", "intel",
        work=("AVAILABLE", "CLAIMABLE"), done=("NOT_AVAILABLE", "EXPIRED", "CLAIMED"),
        work_skills=("INTEL_CLAIM_REWARDS", "SELECT_INTEL_BEAST_MISSION"),
        entry_skill="OPEN_INTEL",
    ),
    # ``KEEP_TRAINING_PRODUCTIVE`` was here and has moved to the per-camp branch
    # (``_append_camp_training_goals``), which owns the training page now.  It is no longer
    # listed here because that branch already emits the never-read ticket as ``TRAINING_SWEEP``
    # and leaving both would put two identical tickets on the board for one page.
    PanelRoutine(
        "KEEP_RESEARCH_PRODUCTIVE", "research",
        work=("IDLE", "AVAILABLE"), done=("IN_PROGRESS", "QUEUE_FULL"),
        work_skills=("RESEARCH",),
        entry_skill="OPEN_RESEARCH",
    ),
)

#: The never-read training page, as a routine.  Reachable only when there is no per-camp
#: model and no single reading either; it is the "go and look" ticket for the page itself.
TRAINING_SWEEP = PanelRoutine(
    "KEEP_TRAINING_PRODUCTIVE", "training",
    work=("IDLE", "AVAILABLE"), done=("IN_PROGRESS", "QUEUE_FULL"),
    work_skills=("TRAIN_TROOPS",),
    entry_skill="OPEN_POWER_OVERVIEW",
)


def _append_sweep_when_unobserved(    goals: list[GoalState],
    routine: PanelRoutine,
    reading: Mapping[str, Any] | None,
    observation: Mapping[str, Any] | None = None,
) -> bool:
    """Emit a sweep ticket for one of :data:`SWEEP_ROUTINES`, but only when it is unobserved.

    Returns whether it emitted, so the caller can keep its own reading-based branch untouched:
    with a reading in hand those goals already work, and this only fills the hole where there is
    no reading to decide from.
    """
    if reading:
        return False
    _append_panel_routine(goals, routine, None, observation)
    return True


def _append_panel_routine(
    goals: list[GoalState],
    routine: PanelRoutine,
    reading: Mapping[str, Any] | None,
    observation: Mapping[str, Any] | None = None,
    red_dots: Mapping[str, Any] | None = None,
) -> None:
    """Emit one panel routine from its reading, or as a visit when it is due.

    ``observation`` is the store's record for this domain -- its reading, how old it is, and
    whether that age is past the TTL.  A live reading always wins.  A fresh stored reading is
    reused (operator §五 "已获得且未过期的观察结果可以复用").  An overdue one is not: it becomes a
    visit again, and the visit is priced by how overdue it is (see ``SWEEP_BASE_VALUE``).

    Four honest outcomes, and the distinctions are the point:
      READY      the page says there is something to claim
      COMPLETE   the page says there is not
      UNKNOWN    read, and it said nothing this table can decide from -> OBSERVED_UNKNOWN, a
                 capability gap.  Re-opening a panel that has just reported nothing cannot
                 resolve it, so this is deliberately *not* a visit ticket.
      DISCOVERED never read, or read too long ago to trust -> NOT_OBSERVED_YET: schedulable as
                 the act of going to look, which is what stops "no observation" from meaning
                 "this goal does not exist"
    """
    live = reading or {}
    record = observation or {}
    stored = record.get("reading")
    stored = dict(stored) if isinstance(stored, Mapping) else None
    # A record exists but its age is past the TTL: known once, not known now.
    fresh = bool(record) and not record.get("overdue", False)
    reused = not live and fresh and stored is not None
    effective = live or (stored if fresh else {}) or {}
    status = str(effective.get("status") or "").strip().upper()
    badge = _badge_present(effective)
    # Numeric evidence of something actually waiting, checked before any status word.  A status
    # word says what kind of page this is; a count says whether anything is on it.  Measured
    # 2026-09-19: ``status=AVAILABLE, claimable_count=0`` is an empty panel, and reading it as
    # work re-opened the panel every run until the count was consulted.
    counts = [effective.get("claimable_count"), effective.get("badge_count")]
    waiting = badge or any(isinstance(c, int) and c > 0 for c in counts)
    provenance = {
        "observed": bool(effective) or (fresh and stored is not None),
        "reused": reused,
        # What we saw, even when it is too old to decide with: an overdue reading is not state,
        # but it is evidence, and hiding it would make "this said CLAIMED two hours ago" vanish
        # exactly when someone is asking why the panel was opened again.
        "reading": dict(live or stored or {}),
        "age_minutes": record.get("age_minutes"),
        "overdue": bool(record.get("overdue", False)),
    }

    # "Not looked" is an *empty* reading, not a missing status word: the mail panel reports
    # unclaimed tabs as badges and often prints no status at all, and calling that "never
    # looked" would send the loop to re-open a page it has just read.
    if not effective:
        if fresh:
            # Read recently, and it said nothing usable -> OBSERVED_UNKNOWN, not a visit.
            goals.append(GoalState(
                routine.goal_id, GoalStatus.UNKNOWN, evidence=provenance, distance=1.0,
            ))
            return
        # The periodic ticket, and the one place the operator's 2026-09-23 rule bites.
        #
        # For an **entry-gated** goal (``entry_badges.ENTRY_GATED_GOALS``: 邮件 and 联盟宝箱) the
        # clock is not allowed to create the goal at all.  Measured before this guard, on the real
        # library: with the entry badge ABSENT the routine still emitted ``MAIL_ROUTINE /
        # DISCOVERED / available_skills=('OPEN_MAIL',)``, priced by age alone (180 for never-read,
        # 155 for a reading 3x past its TTL) -- so a screen with nothing behind it outbid real work
        # and the run ended in ``mail_entry_has_no_badge_this_frame``.  That is the operator's
        # "红点不是加分项，而是有没有任务的准入信号": ABSENT removes the goal from the board.
        #
        # UNKNOWN emits nothing either, and that is §四 rather than an oversight: the entry is drawn
        # on a screen the loop stands on constantly, so re-observing costs no step, while opening the
        # page "to find out" spends one every round.  Nothing is lost by waiting for a real reading --
        # the ticket is re-derived from scratch on the next frame that draws the entry.
        #
        # The cost of that is stated rather than hidden: while the loop is **not** on the screen that
        # draws the entry, the goal does not exist.  That is the intended direction -- the entry is
        # the only evidence that anything is behind it, and a run that cannot read it has no reason to
        # go and look.  It is also why the layer has to be live: with no red-dot ledger at all
        # (an older state file, a replay fixture) every gated goal stays off the board.  That is
        # honest and it is checkable, and the alternative -- treating "unreadable" as "go and look" --
        # is the periodic polling this rule exists to remove.
        if routine.goal_id in entry_badges.ENTRY_GATED_GOALS:
            verdict, gated_on = entry_badges.entry_gate(routine.goal_id, red_dots)
            if verdict != entry_badges.PRESENT:
                return
            provenance = {**provenance, "entry": verdict, "entry_on": list(gated_on)}
        goals.append(GoalState(
            routine.goal_id, GoalStatus.DISCOVERED,
            # Never read prices as "waited for ever"; read-and-stale prices by how stale.
            development_value=(
                SWEEP_NEVER_VALUE if not record
                else _sweep_value(record.get("overdue_ratio", 0.0))
            ),
            available_skills=(routine.entry_skill,),
            evidence=provenance,
            distance=1.0,
        ))
        return
    if waiting:
        goals.append(GoalState(
            routine.goal_id, GoalStatus.READY,
            reward_value=250.0, daily_loss=250.0,
            available_skills=routine.work_skills,
            evidence={**provenance, "status": status, "badge": badge}, distance=1.0,
        ))
        return
    if status in routine.done:
        goals.append(GoalState(
            routine.goal_id, GoalStatus.COMPLETE, completion=1.0,
            available_skills=routine.work_skills,
            evidence=provenance, distance=0.0,
        ))
        return
    if status in routine.work:
        goals.append(GoalState(
            routine.goal_id, GoalStatus.READY,
            reward_value=250.0, daily_loss=250.0,
            available_skills=routine.work_skills,
            evidence={**provenance, "status": status, "badge": badge}, distance=1.0,
        ))
        return
    # Read, and it said something this table does not know -- or nothing at all.  Either way the
    # page was seen and the routine cannot be decided from it: OBSERVED_UNKNOWN, which is a
    # capability gap rather than a visit to schedule.
    goals.append(GoalState(
        routine.goal_id, GoalStatus.UNKNOWN,
        evidence=provenance,
        distance=1.0,
    ))


class GoalLibrary:
    """Turns observed state into goals. It is knowledge, not another scheduler."""

    def discover(
        self,
        world: WorldState,
        *,
        observations: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> tuple[GoalState, ...]:
        """Every goal the engine can see from this world, plus what is still worth looking at.

        ``observations`` is optional and holds only *fresh* stored readings, keyed by the
        WorldState field they belong to.  Passing nothing means "no reading outlives this
        frame", which is the behaviour before the store existed -- so a caller that does not
        have one is not silently treated as having looked recently.
        """
        goals: list[GoalState] = []
        intel_status = str(world.intel.get("status", "UNKNOWN"))
        if intel_status != "UNKNOWN":
            complete = intel_status in {"NOT_AVAILABLE", "EXPIRED"}
            goals.append(GoalState(
                "CLEAR_INTEL", GoalStatus.COMPLETE if complete else GoalStatus.READY,
                completion=1.0 if complete else 0.0,
                remaining_seconds=_optional_int(world.intel.get("refresh_seconds")),
                reward_value=300, daily_loss=500,
                available_skills=("INTEL_CLAIM_REWARDS", "SELECT_INTEL_BEAST_MISSION", "SELECT_INTEL_RESCUE_SURVIVORS"),
                evidence={"status": intel_status},
                distance=0.0 if complete else 1.0,
            ))
        # Stamina is a HUD reading, not a page, so it is absent from every frame that is not the
        # map or the intel board -- and the goal simply vanished with it.  Measured live
        # 2026-09-19 on a healthy run: `snapshot.stamina = None` and the Goal Board carried no
        # AVOID_STAMINA_WASTE row at all, so the operator's "stamina above 30 means keep spending
        # until it is below 30" could not be scheduled: the scheduler had nothing to prioritise.
        #
        # The last still-fresh reading is used instead, exactly as the routines use theirs, and the
        # value is labelled `reused` so a reader can tell a reading taken now from one taken a few
        # minutes ago.  A *stale* reading is not reused: claiming stamina from an old frame would
        # be the same mistake in the other direction, and the goal can be emitted again as soon as
        # any frame carries the gauge.
        stamina = _optional_int((world.stamina or {}).get("current"))
        stamina_from_store = False
        if stamina is None:
            stored_stamina = (observations or {}).get("stamina") or {}
            if not stored_stamina.get("overdue", True):
                stamina = _optional_int((stored_stamina.get("reading") or {}).get("current"))
                stamina_from_store = stamina is not None
        if stamina is None:
            stamina = _optional_int(world.intel.get("stamina"))
        if stamina is not None:
            # ``< STAMINA_FLOOR`` is the satisfied case, not ``<= STAMINA_FLOOR``: at exactly
            # 30 the requirement is still unmet and the goal still has 1 point of work.
            satisfied = stamina < STAMINA_FLOOR
            goals.append(GoalState(
                "AVOID_STAMINA_WASTE", GoalStatus.COMPLETE if satisfied else GoalStatus.READY,
                completion=1.0 if satisfied else 0.0, reward_value=100,
                daily_loss=max(0, stamina - STAMINA_FLOOR + 1) * 5,
                # The beast route reaches a target through the client's own search
                # before it ever pans the map: SEARCH_RESOURCE taps the world-map
                # magnifier, OPEN_BEAST_SEARCH_TAB selects 冰原巨兽, and
                # SUBMIT_BEAST_SEARCH makes the client locate and centre a
                # matching animal -- the convergence SCAN_MAP_FOR_BEAST never
                # had.  All three must be listed here or the CapabilityGate
                # refuses to schedule a skill the brain has decided on.
                available_skills=(
                    "INTEL_CLAIM_REWARDS", "BEAST_HUNT",
                    "SEARCH_RESOURCE", "OPEN_BEAST_SEARCH_TAB", "SUBMIT_BEAST_SEARCH",
                ),
                evidence={"current": stamina, "threshold": STAMINA_FLOOR, "reused": stamina_from_store},
                # Stamina still at or above the floor is exactly the work left to do, and
                # it is what makes a beast kill progress while a map pan does not.  At the
                # floor itself this is 1 rather than 0, which is the boundary above stated
                # as a number.
                distance=float(max(0, stamina - STAMINA_FLOOR + 1)),
            ))
        self._append_camp_training_goals(goals, world, observations)
        self._append_queue_goal(goals, "KEEP_RESEARCH_PRODUCTIVE", world.research, ("RESEARCH",), 80)
        self._append_queue_goal(goals, "KEEP_BUILDING_PRODUCTIVE", world.building, ("BUILDING_UPGRADE",), 80)
        # Domains whose goal is emitted only from a reading (see SWEEP_ROUTINES).  With a
        # reading the branches above already work; this fills the case where there is none, so
        # "we have never looked at the intel page" stops meaning "there is no intel work".
        for sweep in SWEEP_ROUTINES:
            _append_sweep_when_unobserved(
                goals, sweep,
                getattr(world, sweep.field, None),
                (observations or {}).get(sweep.field),
            )
        # The panel routines.  Their readings decide READY vs COMPLETE, and having no reading
        # at all is a state of its own (DISCOVERED) rather than a reason to stay invisible.
        for routine in PANEL_ROUTINES:
            _append_panel_routine(
                goals, routine,
                getattr(world, routine.field, None),
                (observations or {}).get(routine.field),
                # The entry ledger travels with the world state, so gating a goal on its own entry's
                # badge costs no extra look -- the reading was taken when the frame was.
                getattr(world, "red_dots", None),
            )
        # GATHER, as the operator's goal list names it, in the runtime form the
        # project's own table already describes (KEEP_MARCHES_PRODUCTIVE).
        #
        # Every march slot that could be sent gathering and is not is one unit of
        # work left, so dispatching a march is measurable progress and a route that
        # dispatches nothing advanced nothing.  Measured 2026-09-18: with the beast
        # route deferred, AUTO ran the whole gather chain (SEARCH_RESOURCE ->
        # SELECT_RESOURCE -> SUBMIT_RESOURCE_SEARCH -> START_GATHER -> DISPATCH_MARCH,
        # seven verified steps) under ``goal_id=AUTO_DISCOVERY``, which has no meter --
        # real work the scheduler could neither call progress nor call stalled.
        #
        # Deliberately *not* given a named brain route here.  ``RuleBrain`` serves it
        # through the goal-less sweep, and naming it ``GATHER_RESOURCE`` would send a
        # run standing on TRAINING/RESEARCH down brain.py's named-goal exit instead of
        # letting the page's own branches start the queue item it can see.
        idle = _optional_int(world.idle_marches)
        if idle is not None:
            goals.append(GoalState(
                "KEEP_MARCHES_PRODUCTIVE",
                GoalStatus.READY if idle > 0 else GoalStatus.COMPLETE,
                completion=0.0 if idle > 0 else 1.0,
                development_value=70,
                available_skills=("DISPATCH_MARCH", "SEARCH_RESOURCE"),
                evidence={"idle_marches": idle, "march_max": world.march_max},
                distance=float(max(0, idle)),
            ))
        minimum = world.events.get("minimum_guarantee") if isinstance(world.events, dict) else None
        if isinstance(minimum, dict):
            missing = int(minimum.get("points_missing", 0))
            claimed = bool(minimum.get("all_target_rewards_claimed", False))
            complete = missing <= 0 and claimed
            goals.append(GoalState(
                "EVENT_MINIMUM_GUARANTEE", GoalStatus.COMPLETE if complete else GoalStatus.READY,
                completion=1.0 if complete else 0.0,
                remaining_seconds=_optional_int(minimum.get("remaining_seconds")), reward_value=500,
                event_synergy=500, resource_cost=float(minimum.get("estimated_cost", 0)),
                available_skills=tuple(str(x) for x in minimum.get("available_skills", ())),
                evidence={"points_missing": missing, "claimed": claimed},
                distance=float(max(0, missing)),
            ))
        bear = world.events.get("bear") if isinstance(world.events, dict) else None
        if isinstance(bear, dict):
            phase = bear_phase(
                str(bear.get("status")) if bear.get("status") is not None else None,
                _optional_int(bear.get("seconds_to_start")),
                _optional_int(bear.get("remaining_seconds")),
            )
            finished = phase is BearPhase.FINISHED
            skills: tuple[str, ...]
            if phase is BearPhase.ACTIVE:
                skills = ("START_RALLY", "JOIN_RALLY")
            elif phase in {BearPhase.PREPARING, BearPhase.READY}:
                skills = ("CHECK_MARCH", "SELECT_TROOP_PRESET")
            else:
                skills = ("CHECK_ALLIANCE_EVENT", "READ_BEAR_TIMER")
            goals.append(GoalState(
                "PARTICIPATE_BEAR", GoalStatus.COMPLETE if finished else GoalStatus.READY,
                completion=1.0 if finished else 0.0,
                remaining_seconds=_optional_int(bear.get("remaining_seconds") or bear.get("seconds_to_start")),
                reward_value=1000, daily_loss=5000 if phase in {BearPhase.READY, BearPhase.ACTIVE} else 0,
                available_skills=skills,
                evidence={"phase":phase.value, "reserved_start_time":bear.get("reserved_start_time"),
                          "normal_idle_slots":world.idle_marches,
                          "bear_rally_special_available":world.bear_rally_special_available},
                distance=0.0 if finished else 1.0,
            ))
        for page in world.rewards.get("verified_claimable", ()):
            goals.append(GoalState(
                f"CLAIM_FREE_{page}", GoalStatus.READY, reward_value=250, daily_loss=250,
                available_skills=tuple(world.rewards.get("skills", {}).get(page, ())), evidence={"page": page},
                # Only ever discovered while something is claimable, so the one
                # unit of remaining work is the claim itself.
                distance=1.0,
            ))
        return tuple(goals)

    @staticmethod
    def _append_queue_goal(goals: list[GoalState], goal_id: str, state: dict[str, Any], skills: tuple[str, ...], value: float) -> None:
        if not state:
            return
        busy = state.get("queue_available") is False or state.get("status") == "IN_PROGRESS" or state.get("all_queues_busy") is True
        goals.append(GoalState(goal_id, GoalStatus.COMPLETE if busy else GoalStatus.READY,
                               completion=1.0 if busy else 0.0, development_value=value,
                               available_skills=skills, evidence={"queue_busy": busy},
                               distance=0.0 if busy else 1.0))

    def _append_camp_training_goals(
        self,
        goals: list[GoalState],
        world: WorldState,
        observations: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        """Emit one training ticket per barracks, so one busy camp cannot close the goal.

        The defect this replaces was structural, not a threshold: the goal layer held a single
        ``world.training`` reading and asked one question of it -- is that queue busy -- then
        marked ``KEEP_TRAINING_PRODUCTIVE`` COMPLETE when the answer was yes.  The client has
        three barracks on one page, so::

            shield busy -> "the training queue is busy" -> goal COMPLETE -> 矛兵营/射手营 never read

        Measured evidence for the shape of the client: on every live training frame the three
        camp labels are drawn together at y_norm ~0.945, and each camp's queue state is drawn
        only while that camp's tab is selected -- so the three readings are three separate
        facts, and this emits three separate goals.

        What each camp produces
        -----------------------
        * **positively free** (a trainable queue was read) -> READY, work to do now.
        * **positively running** (a countdown was read) -> COMPLETE for that camp only.  The
          other two camps are untouched by this, which is the whole point.
        * **never read** (no frame has ever shown this camp) -> DISCOVERED, schedulable, so the
          loop goes and opens the tab.  This is the operator's "不得阻止检查另外两个兵营"
          expressed as a ticket rather than as a comment.  Two of the three camps have zero
          frames in the live corpus, so this is the common case today, not an edge case.

        The legacy single ``world.training`` reading is still honoured when a camp model is
        absent entirely (older frames, and the ``page=HOME`` campaign-menu branch), because
        dropping it would lose the one reading those branches do produce.  It is attributed to
        its own troop type when that is known, and to a clearly-labelled ``PAGE`` entry when it
        is not -- never silently to a named camp.
        """
        camps = world.camps or {}
        troop = str((world.training or {}).get("troop_type") or "").upper()
        legacy_camp = TROOP_TO_CAMP.get(troop) if troop else None

        if not camps:
            # No per-camp model yet.  Keep the old single reading as one ticket, but name the
            # camp it belongs to when the troop type identifies one, so the board shows
            # SHIELD_CAMP rather than an anonymous "training".
            if world.training:
                self._append_queue_goal(
                    goals, CAMP_GOAL_FOR.get(legacy_camp, "KEEP_TRAINING_PRODUCTIVE"),
                    world.training, ("TRAIN_TROOPS",), TRAINING_CAMP_VALUE,
                )
            else:
                # Never read: a sweep ticket, priced like the other unread routines.
                _append_panel_routine(goals, TRAINING_SWEEP, None,
                                      (observations or {}).get("training"))
            return

        for camp in CAMP_ORDER:
            state = dict(camps.get(camp) or {})
            goal_id = CAMP_GOAL_FOR[camp]
            busy = state.get("busy")
            observed = state.get("observed") is True
            evidence = {
                "camp": camp,
                "label": CAMP_LABELS[camp],
                "status": state.get("status", "UNKNOWN"),
                "timer": state.get("timer"),
                "batch_count": state.get("batch_count"),
                "source": state.get("source"),
                "observed": observed,
            }
            if observed and busy is True:
                goals.append(GoalState(
                    goal_id, GoalStatus.COMPLETE, completion=1.0,
                    development_value=TRAINING_CAMP_VALUE, available_skills=(),
                    evidence={**evidence, "reason": "this_camp_is_training"},
                    distance=0.0,
                ))
            elif observed and busy is False:
                goals.append(GoalState(
                    goal_id, GoalStatus.READY, completion=0.0,
                    development_value=TRAINING_CAMP_VALUE,
                    available_skills=("TRAIN_TROOPS",),
                    evidence={**evidence, "reason": "this_camp_has_a_free_queue"},
                    distance=1.0,
                ))
            else:
                # Not read.  Distinct from both answers above and schedulable in its own right
                # (DISCOVERED), so "we have not opened this barracks" is work rather than
                # silently no work.  Its value is the sweep value, not the claim value: looking
                # at a camp pays less than a camp that has been seen to have a free queue.
                goals.append(GoalState(
                    goal_id, GoalStatus.DISCOVERED, completion=0.0,
                    development_value=SWEEP_BASE_VALUE,
                    available_skills=("TRAIN_TROOPS",),
                    evidence={**evidence, "reason": "this_camp_has_never_been_opened"},
                    distance=1.0,
                ))

        # The legacy single reading, when it named a camp the per-camp model has nothing for,
        # is still worth keeping: it is a real reading of a real page, just one the camp model
        # could not attribute.  Reported under the page's own name so it is visible.
        if legacy_camp is None and world.training and world.training.get("status"):
            self._append_queue_goal(goals, "KEEP_TRAINING_PRODUCTIVE", world.training,
                                    ("TRAIN_TROOPS",), TRAINING_CAMP_VALUE)

    def rank(
        self,
        goals: Iterable[GoalState],
        world: WorldState | None = None,
        *,
        fairness: Mapping[str, goal_utility.GoalFairness] | None = None,
        routes: Iterable[goal_utility.RouteFact] | None = None,
        now: datetime | None = None,
    ) -> tuple[tuple[GoalState, goal_utility.UtilityBreakdown], ...]:
        """The whole board, best first, with every term of each goal's utility (§九).

        ``best`` answers "what next"; this answers "why that, and what lost", which is
        what a decision log has to carry.  Both go through the same ranking so the log
        can never disagree with the choice it is describing.
        """
        return goal_utility.rank(
            goals, world=world, facts=routes or (), ledger=fairness, now=now
        )

    def best(
        self,
        goals: Iterable[GoalState],
        world: WorldState | None = None,
        *,
        fairness: Mapping[str, goal_utility.GoalFairness] | None = None,
        routes: Iterable[goal_utility.RouteFact] | None = None,
        now: datetime | None = None,
    ) -> GoalState | None:
        """The goal to work on: the highest-priced one that can be advanced this frame.

        Deliberately a single ordered comparison and no tiers.  An earlier version of this
        method tried to rank ``DISCOVERED`` (a page to go and look at) below ``READY`` (work in
        hand), on the theory that a look-around should never outbid real work.  Measured
        2026-09-21, that is wrong, and ``test_sweep_rotation_and_hop`` says why: the sweep
        tickets are *priced* to outbid routine gathering (``SWEEP_BASE_VALUE`` 80-130 against
        ``KEEP_MARCHES_PRODUCTIVE`` 70), aging to a ceiling that stays under a real claim.  That
        ordering is the rotation -- it is what stops one unread page being starved forever by
        whatever is always sitting in the march queue.  A tier that forced ``READY`` first
        silently disabled it and made ``CLEAR_INTEL`` unreachable on any frame with an idle
        march slot.

        The concern that motivated the tier is real but belongs elsewhere: a *sweep* must not
        outrank a goal that is already holding a resource the sweep's owner is waiting on.  That
        is the yield mechanism's job (``_yield_to_next_goal``, Rule A), and it is applied where
        the conflict is visible, not by reordering the whole board here.

        ``world`` / ``fairness`` / ``routes`` add the dynamic layer (operator §四) on top of
        those catalogue prices.  With none of them supplied the answer is byte-identical to
        the original comparison, which is what keeps every existing caller and test valid;
        production supplies all three.  The dynamic terms are bounded inside the gaps the
        catalogue already has -- see ``goal_utility`` for the numbers and why.
        """
        board = tuple(goals)
        if world is None and not fairness and not routes:
            actionable = [goal for goal in board if goal.priority != float("-inf") and goal.available_skills]
            return max(actionable, key=lambda goal: goal.priority, default=None)
        ranked = self.rank(board, world, fairness=fairness, routes=routes, now=now)
        return ranked[0][0] if ranked else None

    def skill_modifier(self, world: WorldState, skill_id: str) -> float:
        # One action may advance several goals (for example Train + Daily + Event).
        # Aggregate marginal value instead of treating goals as isolated jobs.
        return sum(goal.priority for goal in self.discover(world) if skill_id in goal.available_skills)


def _optional_int(value: object) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def progress_moved(
    observed: Mapping[str, float],
    after: Iterable[GoalState],
    goal_id: str,
) -> bool | None:
    """Did the goal itself advance, compared with the last value we actually read?

    The action's verifier answers "did the input land and did the client respond the
    way this skill predicts".  This answers a different question: "is the goal closer
    to satisfied".  A successful swipe that pans the map answers yes to the first and
    no to the second, and conflating them is what let AUTO spend twenty minutes on 58
    passing steps that changed nothing (2026-09-18).

    ``observed`` is the running meter of goals read so far *in this run*, and it is
    carried forward on purpose.  Measured 2026-09-18 on the gather route: the march
    counter is only readable on the MAP page, so the step that consumes a march slot
    (``DISPATCH_MARCH``) has the formation page as its before-frame -- the goal is
    unobservable there, and a strict before/after comparison called every dispatch
    "not measured" while the counter plainly went 1 -> 2 marches used.  Comparing
    against the last real reading is what makes that step show as progress.

    ``None`` means the goal was not observable at all (absent from ``after``, or never
    read in this run).  That is not "no progress": a queue goal does not exist while
    its page is off screen, and calling unobserved work stalled would defer goals for
    being unwatched.
    """
    now = next((goal for goal in after if goal.goal_id == goal_id), None)
    if now is None:
        return None
    previous = observed.get(goal_id)
    if previous is None:
        return None
    return now.distance < previous


@dataclass(frozen=True)
class GoalComposition:
    """How a goal is composed out of capabilities, as the project already maps it.

    ``SEQUENCE`` means every capability is required, so one unavailable capability
    blocks the goal.  ``ANY_OF`` means any single capability satisfies it, so the
    goal is only blocked when *all* of its paths are unavailable -- which is what
    keeps a deferred beast route from also switching off the intel and rally routes
    that reach the same goal.
    """

    goal_id: str
    composition: str
    capabilities: tuple[str, ...]


GOAL_CAPABILITY_MAP = "knowledge/goals/goal_capability_map.json"


def goal_compositions(root: Path | str | None = None) -> dict[str, GoalComposition]:
    """Goal -> capability composition, read from the existing project table.

    Reads ``knowledge/goals/goal_capability_map.json`` (the ``Goal -> Capability``
    input the coverage report is already built from) rather than introducing a
    second mapping.  A goal the table does not describe simply has no composition,
    which the caller must treat as "unknown", never as "nothing required".
    """
    base = Path(root) if root else Path(__file__).resolve().parents[1]
    try:
        payload = json.loads((base / GOAL_CAPABILITY_MAP).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    out: dict[str, GoalComposition] = {}
    for goal_id, entry in (payload.get("goals") or {}).items():
        if not isinstance(entry, dict):
            continue
        capabilities = tuple(
            str(item.get("capability"))
            for item in (entry.get("capabilities") or ())
            if isinstance(item, dict) and item.get("capability")
        )
        out[str(goal_id)] = GoalComposition(
            goal_id=str(goal_id),
            composition=str(entry.get("composition") or "SEQUENCE").upper(),
            capabilities=capabilities,
        )
    return out


class GoalStateStore:
    """Atomic latest-snapshot persistence for the desktop Goal Board."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, world: WorldState, goals: Iterable[GoalState]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "observed_at": world.timestamp,
            "written_at": datetime.now(timezone.utc).isoformat(),
            "page": world.page.value,
            "confidence": world.confidence,
            "goals": [self._serialize(goal) for goal in goals],
        }
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    @staticmethod
    def _serialize(goal: GoalState) -> dict[str, Any]:
        value = asdict(goal)
        value["status"] = goal.status.value
        value["priority"] = None if goal.priority == float("-inf") else goal.priority
        return value
