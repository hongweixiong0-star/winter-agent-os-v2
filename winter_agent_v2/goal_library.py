from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .camp_training import CAMP_LABELS, CAMP_ORDER, TROOP_TO_CAMP
from .models import Page, WorldState
from . import entry_badges
from . import event_goal
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

#: Training queues are the first productive-work objective: a never-read camp must be
#: inspected, and an idle camp must claim/restart before lower-value exploration consumes
#: the cycle. Time-critical event deadlines still outrank this ordinary development value.
TRAINING_CAMP_VALUE = 1200.0
RESEARCH_PRODUCTIVE_VALUE = 1100.0
BUILDING_PRODUCTIVE_VALUE = 1050.0

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
    # A live event with a current UI reading uses the same bounded ordinary-control
    # path as the EVENT page itself; no calendar guess or event-specific click is implied.
    "EVENT_MINIMUM_GUARANTEE": "EVENT",
    "DISCOVER_EVENT_CALENDAR": "EVENT",
    # Building upgrades already have a page-local action and verifier; they were unreachable because
    # the queue goal had no route and no selected-building entry step.
    "KEEP_BUILDING_PRODUCTIVE": "BUILDING",
    # The three camps are three goals and share the one route: the route is the training
    # *page*, and which camp it opens is the brain's decision driven by ``goal_id``.  A
    # second route name would be a second implementation of the same page.
    "SHIELD_CAMP_TRAINING": "TRAIN",
    "LANCER_CAMP_TRAINING": "TRAIN",
    "MARKSMAN_CAMP_TRAINING": "TRAIN",
    "MAIL_ROUTINE": "MAIL",
    "DAILY_ACTIVITY_TARGET": "DAILY",
    "HERO_RECRUIT_ADVANCED": "DAILY",
    "HERO_RECRUIT_EPIC": "DAILY",
    "HERO_RECRUIT_FEEDBACK": "DAILY",
    "HERO_RECRUIT_RETURN": "DAILY",
    "DISCOVER_QUICK_PANEL_TASKS": "DAILY",
    "SCROLL_QUICK_PANEL_TASKS": "DAILY",
    "MY_REWARDS": "DAILY",
    "PET_TREASURE": "DAILY",
    "PET_TREASURE_RETURN": "DAILY",
    "ALLIANCE_ROUTINE": "ALLIANCE",
    "ALLIANCE_DONATION": "ALLIANCE",
    # A badge on the current Alliance HOME tile licenses only a zero-cost visit to
    # the live rally list. Participation still needs fresh role and queue evidence.
    "DISCOVER_BEAR_RALLY_LIST": "ALLIANCE",
    "PARTICIPATE_BEAR": "ALLIANCE",
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
    "EXPLORATION", "DAILY", "ALLIANCE", "RESEARCH", "TRAIN", "BUILDING", "EVENT",
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
    """Whether a task **exists** and whether it can be **acted on now** are two facts.

    Operator directive 2026-09-23 §一 names six semantics and asks for them to be mapped onto what
    this project already has rather than turned into a second task system.  The mapping, and where
    each one is produced:

    ==========================  ================  ==========================================
    directive                   status here       produced by
    ==========================  ================  ==========================================
    CURRENTLY_ACTIONABLE        ``READY``         the frame's own reading (as before)
    SCHEDULED_NOT_OPEN          same name         a known activity whose window has not opened
    OPEN_BUT_NOT_READY          ``BLOCKED``       the capability gate / a queue that is busy
    WAITING_GAME_CONDITION      ``BLOCKED``       ``retry_after`` + ``evidence["condition"]``
    UNKNOWN_AVAILABILITY        ``UNKNOWN``       a page that could not be read
    COMPLETED                   ``COMPLETE``      the work was done
    EXPIRED                     same name         a limited-time window that closed
    ==========================  ================  ==========================================

    ``SCHEDULED_NOT_OPEN`` and ``EXPIRED`` are the two that had no home, and their absence was not
    harmless.  Measured 2026-09-23 with the real library (``learning/_probe_existence.py``):

    * a bear hunt opening in **two hours** was emitted as ``READY`` with ``priority 5000`` -- it
      outbid the sweep tickets (ageing to 180) and sat level with ``CLEAR_INTEL`` (500), so "exists
      but not open yet" was being treated as fully actionable;
    * an **ended** hunt was emitted as ``COMPLETE``, which is the statement "本次任务实际完成" --
      so a closed window and a finished task were the same record, and §五's "某次活动已经结束，
      不等于以后不再有同类活动" had nowhere to live.

    Both are excluded from ranking exactly like ``COMPLETE``/``BLOCKED``/``UNKNOWN`` -- see
    ``NOT_ACTIONABLE`` -- so this is not a re-pricing, it is a change to what may be executed.
    """

    DISCOVERED = "DISCOVERED"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"
    #: Known to exist, and its window has not opened yet.  Kept on the board so the plan and the
    #: preparation survive the gap, and never selected: §二/§三 -- record it, do not go looking for
    #: an entrance that is not there.
    SCHEDULED_NOT_OPEN = "SCHEDULED_NOT_OPEN"
    #: This occurrence's window closed.  Distinct from ``COMPLETE`` on purpose: the knowledge is
    #: kept for the next occurrence (§三/§五), and no stale advice or coordinate may be replayed.
    EXPIRED = "EXPIRED"


#: The statuses that mean "not this frame", each for its own reason, in one place so a new status
#: cannot be forgotten by the one comparison that decides executability (``GoalState.priority``).
NOT_ACTIONABLE: frozenset[GoalStatus] = frozenset({
    GoalStatus.COMPLETE, GoalStatus.BLOCKED, GoalStatus.UNKNOWN,
    GoalStatus.SCHEDULED_NOT_OPEN, GoalStatus.EXPIRED,
})

#: An activity window, in this project's goal vocabulary.  One table, so a window state that is not
#: listed is a ``KeyError`` at the only place that maps them rather than a silently wrong status.
_WINDOW_STATUS: dict[event_goal.WindowState, GoalStatus] = {
    event_goal.WindowState.OPEN: GoalStatus.READY,
    event_goal.WindowState.SCHEDULED_NOT_OPEN: GoalStatus.SCHEDULED_NOT_OPEN,
    event_goal.WindowState.EXPIRED: GoalStatus.EXPIRED,
    event_goal.WindowState.UNKNOWN: GoalStatus.UNKNOWN,
}


def _registered_activity_flow(activity: event_goal.Activity) -> dict[str, Any]:
    """Resolve an activity definition to existing Goal/Skill IDs without making it runnable.

    The event registry already carries task IDs and, for some event families, a generic flow.
    Preserve those bindings on the single activity Goal so calendar discovery, live state, and
    red-dot discoveries can converge on the same existing execution Goal. This is metadata only:
    the enclosing activity remains UNKNOWN until its current client conditions are observed.
    """
    from .skill_factory import GOAL_REQUIREMENTS
    from .skills import v2_registry

    registry = v2_registry()
    goal_ids: list[str] = ["DISCOVER_EVENT_CALENDAR"]
    skill_ids: list[str] = []
    missing_skill_ids: list[str] = []
    tasks = list(activity.tasks)
    if activity.generic_flow:
        generic_goal = (
            "ALLIANCE_TIMED_EVENTS"
            if "ALLIANCE" in str(activity.event_type or "").upper()
            else "EVENT_MINIMUM_GUARANTEE"
        )
        tasks.append(generic_goal)
        # Unknown live event controls use the existing bounded current-frame/Qwen path.
        tasks.append("TRY_ORDINARY_CONTROL")
    for task in tasks:
        task_id = str(task or "").strip()
        if not task_id:
            continue
        if task_id in GOAL_REQUIREMENTS:
            goal_ids.append(task_id)
            required = list(GOAL_REQUIREMENTS[task_id])
            if task_id == "EVENT_MINIMUM_GUARANTEE":
                # This current-page fallback is the existing executable path for a newly read
                # event; dedicated rule/progress/tier skills remain visible as actual gaps.
                required.append("TRY_ORDINARY_CONTROL")
            for skill_id in required:
                (skill_ids if registry.get(skill_id) is not None else missing_skill_ids).append(skill_id)
        elif registry.get(task_id) is not None:
            skill_ids.append(task_id)
        else:
            missing_skill_ids.append(task_id)
    for skill_id in GOAL_REQUIREMENTS.get("DISCOVER_EVENT_CALENDAR", ()):
        (skill_ids if registry.get(skill_id) is not None else missing_skill_ids).append(skill_id)
    registered_skills = list(dict.fromkeys(
        skill_ids
    ))
    missing_skills = list(dict.fromkeys(missing_skill_ids))
    return {
        "activity_goal_id": f"SCHEDULED_{activity.event_id}",
        "registered_goal_ids": list(dict.fromkeys(goal_ids)),
        "registered_skill_ids": registered_skills,
        "unregistered_skill_ids": missing_skills,
        "flow_registration_state": (
            "PARTIAL_GENERIC_FALLBACK_REGISTERED_WAITING_FOR_LIVE_CONDITIONS"
            if missing_skills else "REGISTERED_WAITING_FOR_LIVE_CONDITIONS"
        ),
    }


def _registered_event_candidate_skills() -> list[str]:
    """Existing generic event route offered to a calendar-only candidate after live reading."""
    from .skill_factory import GOAL_REQUIREMENTS
    from .skills import v2_registry

    registry = v2_registry()
    candidates = [
        *GOAL_REQUIREMENTS.get("DISCOVER_EVENT_CALENDAR", ()),
        *GOAL_REQUIREMENTS.get("EVENT_MINIMUM_GUARANTEE", ()),
        "TRY_ORDINARY_CONTROL",
    ]
    return list(dict.fromkeys(
        skill_id for skill_id in candidates
        if skill_id == "TRY_ORDINARY_CONTROL" or registry.get(skill_id) is not None
    ))


def _unregistered_event_candidate_skills() -> list[str]:
    """Existing event-goal requirements that still lack a production Skill implementation."""
    from .skill_factory import GOAL_REQUIREMENTS
    from .skills import v2_registry

    registry = v2_registry()
    return list(dict.fromkeys(
        skill_id for skill_id in GOAL_REQUIREMENTS.get("EVENT_MINIMUM_GUARANTEE", ())
        if registry.get(skill_id) is None
    ))


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
        if self.status in NOT_ACTIONABLE:
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
    #: Discovery opportunities can be priced by the route. Queue reads with no evidence yet
    #: must not outrank currently executable work; the established panel sweep keeps its
    #: higher value so unread routines continue to rotate.
    discovery_value: float = 180.0


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
#: Building queues are emitted from a current reading and use the existing selected-building reader,
#: upgrade skill, resource policy and verifier.  The BUILDING route owns the minimal navigation glue.
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
        # An unread panel is only an observation ticket. Once a live queue reading
        # confirms available work, _append_queue_goal assigns RESEARCH_PRODUCTIVE_VALUE.
        discovery_value=SWEEP_NEVER_VALUE,
    ),
    PanelRoutine(
        "KEEP_BUILDING_PRODUCTIVE", "building",
        work=("IDLE", "AVAILABLE"), done=("IN_PROGRESS", "UPGRADING", "QUEUE_FULL"),
        work_skills=("OPEN_BUILDING_UPGRADE", "BUILDING_UPGRADE", "TRY_ORDINARY_CONTROL"),
        # A safe, bounded observation step. The BUILDING route only spends once
        # a selected building and its current-frame upgrade control are identified.
        entry_skill="TRY_ORDINARY_CONTROL",
        # A live idle queue is emitted by _append_queue_goal at productive-work priority.
        # A safe, bounded observation step. The BUILDING route only spends once
        # a selected building and its current-frame upgrade control are identified.
        # Until then, it must not pull AUTO home while an already executable task is available.
        discovery_value=20.0,
    ),
)

#: The never-read training page, as a routine.  Reachable only when there is no per-camp
#: model and no single reading either; it is the "go and look" ticket for the page itself.
TRAINING_SWEEP = PanelRoutine(
    "KEEP_TRAINING_PRODUCTIVE", "training",
    work=("IDLE", "AVAILABLE"), done=("IN_PROGRESS", "QUEUE_FULL"),
    work_skills=("TRAIN_TROOPS",),
    entry_skill="TRY_ORDINARY_CONTROL",
    # Keep the unobserved-page visit in the sweep rotation. A live free/finished
    # camp still gets TRAINING_CAMP_VALUE in _append_camp_training_goals.
    discovery_value=SWEEP_NEVER_VALUE,
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
    # A queue-page action bar is not a queue reading. Older observations often
    # contain only ``menu_open`` / building identity; treating that as a fresh
    # UNKNOWN suppressed the next research/building inspection indefinitely.
    # Keep the record as provenance, but schedule a fresh observation until the
    # client supplies an actual queue state or availability bit.
    incomplete_queue_reading = (
        routine.field in {"research", "building"}
        and bool(effective)
        and not status
        and not isinstance(effective.get("queue_available"), bool)
        and not isinstance(effective.get("all_queues_busy"), bool)
    )
    if incomplete_queue_reading:
        effective = {}
        fresh = False
        reused = False
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
        "incomplete_queue_observation": incomplete_queue_reading,
    }

    # §一, and this is the whole of it: for the two entry-gated routines the entry's own badge decides
    # whether the task **exists**, not how much it is worth.  So the gate is applied whenever the
    # decision does NOT rest on a reading taken on this frame -- a *live* reading is not gated, because
    # standing on the page with something claimable in front of us is stronger evidence than a badge
    # drawn on another screen.
    #
    # Round 5 placed this inside the no-reading branch only, and the hole that left is measurable on
    # the real library: with the entry badge ABSENT and a fresh stored ``{"status": "CLAIMABLE"}``, the
    # routine still emitted ``MAIL_ROUTINE / READY`` with the claim skills.  The goal therefore existed,
    # could win the board, and could not be carried out -- the run is not on that page, and the
    # executor gate (§六) refuses to enter it -- so the cycle was spent one step at a time on a task
    # that was never eligible.  Same rule, applied to the same readings, in one place instead of two.
    gate: dict[str, Any] = {}
    if routine.goal_id in entry_badges.ENTRY_GATED_GOALS and not live:
        verdict, gated_on = entry_badges.entry_gate(routine.goal_id, red_dots)
        if verdict != entry_badges.PRESENT:
            return
        gate = {"entry": verdict, "entry_on": list(gated_on)}
    provenance = {**provenance, **gate}

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
        # The periodic ticket.  Whether the clock may create it at all is decided by the gate above,
        # which is why nothing here looks at the entry again: the rule has one home.
        #
        # What is left to say is why an unread routine is still a ticket at all -- §二 of the earlier
        # directive and this project's own §6: NOT_OBSERVED_YET is a state, and a routine nobody has
        # read has to be *schedulable* or the loop never looks.  It is priced for that (180 for a
        # never-read routine, aging down) and never above a real claim.
        goals.append(GoalState(
            routine.goal_id, GoalStatus.DISCOVERED,
            # Never read prices as "waited for ever"; read-and-stale prices by how stale.
            development_value=(
                routine.discovery_value if not record
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


def _append_quick_panel_task_goals(goals: list[GoalState], world: WorldState) -> None:
    """Promote currently visible quick-panel errands into the shared Goal board."""
    if world.page is Page.POPUP and world.popup == "HERO_RECRUIT_REWARD":
        goals.append(GoalState(
            "HERO_RECRUIT_FEEDBACK", GoalStatus.READY, reward_value=20,
            available_skills=("DISMISS_SHARED_REWARD",),
            evidence={"source": "LIVE_RECRUIT_REWARD_POPUP", "popup": world.popup},
            distance=0.0,
        ))
        return
    if world.page is Page.HERO:
        rows = [dict(row) for row in (world.rewards or {}).get("hero_recruit_rows", ())
                if isinstance(row, Mapping)]
        available = {str(row.get("key") or ""): row for row in rows
                     if row.get("free_available") is True}
        for key, goal_id in (
            ("HERO_RECRUIT_ADVANCED", "HERO_RECRUIT_ADVANCED"),
            ("HERO_RECRUIT_EPIC", "HERO_RECRUIT_EPIC"),
        ):
            row = available.get(key)
            if row is not None:
                goals.append(GoalState(
                    goal_id, GoalStatus.READY, reward_value=250,
                    available_skills=(f"FREE_{key}",),
                    evidence={"source": "LIVE_HERO_RECRUIT_PAGE",
                              "free_remaining": row.get("free_remaining"),
                              "source_word": row.get("free_source_word")},
                    distance=1.0,
                ))
        if not available:
            # The goal is a one-time errand per panel row, not a loop that spends every
            # remaining daily free draw. Once the requested free recruit is gone, return
            # to the panel so its other rows can be read and scheduled.
            goals.append(GoalState(
                "HERO_RECRUIT_RETURN", GoalStatus.READY, reward_value=10,
                available_skills=("BACK",),
                evidence={"source": "LIVE_HERO_RECRUIT_PAGE",
                          "hero_recruit_rows": rows},
                distance=1.0,
            ))
        return
    panel = world.quick_panel or {}
    if world.page is Page.HOME and panel.get("open") is False:
        handle = panel.get("handle") or {}
        if (isinstance(handle, Mapping) and handle.get("state") == "COLLAPSED"
                and isinstance(handle.get("point_norm"), (list, tuple))):
            goals.append(GoalState(
                "DISCOVER_QUICK_PANEL_TASKS", GoalStatus.READY, reward_value=260,
                available_skills=("OPEN_QUICK_PANEL",),
                evidence={"source": "LIVE_QUICK_PANEL_HANDLE",
                          "handle_state": handle.get("state"),
                          "basis": handle.get("basis")},
                distance=0.5,
            ))
        return
    if world.page is not Page.HOME or panel.get("open") is not True:
        return
    rows = [dict(row) for row in (panel.get("rows") or ()) if isinstance(row, Mapping)]
    by_key = {str(row.get("key") or ""): row for row in rows}
    lower_rows = {"ALLIANCE_DONATION", "HERO_RECRUIT", "HERO_RECRUIT_EPIC",
                  "MY_REWARDS", "PET_TREASURE"}
    if (isinstance(panel.get("scroll_swipe_norm"), (list, tuple))
            and not lower_rows.issubset(set(by_key))):
        goals.append(GoalState(
            "SCROLL_QUICK_PANEL_TASKS", GoalStatus.READY, reward_value=100,
            available_skills=("SCROLL_QUICK_PANEL_TASKS",),
            evidence={"source": "LIVE_QUICK_PANEL_ROWS",
                      "visible_rows": sorted(by_key),
                      "remaining_rows": sorted(lower_rows - set(by_key))},
            distance=0.75,
        ))

    donation = panel.get("alliance_donation") or {}
    donation_row = by_key.get("ALLIANCE_DONATION", {})
    if (str(donation.get("status") or "").upper() == "AVAILABLE"
            and int(donation.get("available") or 0) > 0
            and donation_row.get("badge") == entry_badges.PRESENT):
        goals.append(GoalState(
            "ALLIANCE_DONATION", GoalStatus.READY, reward_value=240,
            available_skills=("OPEN_ALLIANCE", "OPEN_ALLIANCE_TECH_FROM_HOME",
                              "ALLIANCE_TECH_CONTRIBUTE"),
            evidence={"source": "QUICK_PANEL", "available": donation.get("available"),
                      "total": donation.get("total"), "source_word": donation.get("source_word")},
            distance=1.0,
        ))

    recruit_rows = [dict(row) for row in (panel.get("hero_recruit_rows") or ())
                    if isinstance(row, Mapping)]
    for row_key, goal_id in (("HERO_RECRUIT", "HERO_RECRUIT_ADVANCED"),
                             ("HERO_RECRUIT_EPIC", "HERO_RECRUIT_EPIC")):
        panel_row = by_key.get(row_key, {})
        recruit = next((item for item in recruit_rows
                        if str(item.get("key") or "") == row_key), None)
        if recruit is None and row_key == "HERO_RECRUIT":
            recruit = panel.get("hero_recruit") or {}
        if (panel_row.get("badge") == entry_badges.PRESENT
                and isinstance(recruit, Mapping)
                and str(recruit.get("status") or "").upper() == "AVAILABLE"
                and "免费" in str(recruit.get("source_word") or "")):
            skill = ("OPEN_TASK_FROM_QUICK_PANEL_HERO_RECRUIT"
                     if row_key == "HERO_RECRUIT"
                     else "OPEN_TASK_FROM_QUICK_PANEL_HERO_RECRUIT_EPIC")
            goals.append(GoalState(
                goal_id, GoalStatus.READY, reward_value=250,
                available_skills=(skill, "FREE_HERO_RECRUIT_ADVANCED"
                                  if row_key == "HERO_RECRUIT"
                                  else "FREE_HERO_RECRUIT_EPIC"),
                evidence={"source": "QUICK_PANEL", "row": row_key,
                          "state_word": recruit.get("source_word")}, distance=1.0,
            ))

    rewards = by_key.get("MY_REWARDS", {})
    # The green check is a completion marker, not enough by itself to license a
    # second claim attempt. A separate badge must be read on the same row; the
    # live tap history showed that the check can simply close the panel.
    if rewards.get("control") == "DONE" and rewards.get("badge") == entry_badges.PRESENT:
        goals.append(GoalState(
            "MY_REWARDS", GoalStatus.READY, reward_value=250,
            available_skills=("COLLECT_MY_REWARDS_ROW",),
            evidence={"source": "QUICK_PANEL", "state_word": rewards.get("source_word"),
                      "badge": rewards.get("badge", "UNKNOWN")},
            distance=1.0,
        ))

    pet = by_key.get("PET_TREASURE", {})
    if pet.get("badge") == entry_badges.PRESENT and pet.get("control") in {"ARROW", "DONE"}:
        skill = ("OPEN_TASK_FROM_QUICK_PANEL_PET_TREASURE"
                 if pet.get("control") == "ARROW" else "COLLECT_PET_TREASURE_ROW")
        goals.append(GoalState(
            "PET_TREASURE", GoalStatus.READY, reward_value=250,
            available_skills=(skill,),
            evidence={"source": "QUICK_PANEL", "state_word": pet.get("source_word"),
                      "control": pet.get("control")}, distance=1.0,
        ))


class GoalLibrary:
    """Turns observed state into goals. It is knowledge, not another scheduler."""

    def discover(
        self,
        world: WorldState,
        *,
        observations: Mapping[str, Mapping[str, Any]] | None = None,
        training_continuation_goal_id: str = "",
        alliance_continuation_goal_id: str = "",
        role_id: str = "",
        calendar_snapshot: Mapping[str, Any] | None = None,
    ) -> tuple[GoalState, ...]:
        """Every goal the engine can see from this world, plus what is still worth looking at.

        ``observations`` is optional and holds only *fresh* stored readings, keyed by the
        WorldState field they belong to.  Passing nothing means "no reading outlives this
        frame", which is the behaviour before the store existed -- so a caller that does not
        have one is not silently treated as having looked recently.
        """
        goals: list[GoalState] = []
        if world.page is Page.PET_TREASURE:
            # Navigation only: return to Home after safely reading this screen.
            # This does not claim a hunt or reward was completed.
            goals.append(GoalState(
                "PET_TREASURE_RETURN", GoalStatus.READY, reward_value=1,
                available_skills=("BACK",),
                evidence={"source": "LIVE_PET_TREASURE_PAGE",
                          "remaining_attempts": (world.beast.get("pet_treasure") or {}).get("remaining_attempts"),
                          "operation": "RETURN_TO_HOME_ONLY"},
                distance=0.25,
            ))
        if (world.page is Page.ALLIANCE
                and world.alliance.get("section") in {"HOME", "TECHNOLOGY"}):
            section = world.alliance.get("section")
            status = str(world.alliance.get("status") or "UNKNOWN").upper()
            if section == "HOME" and alliance_continuation_goal_id == "ALLIANCE_DONATION":
                # Keep the task discovered from the quick panel alive across
                # the Home -> Alliance navigation hop. The technology screen
                # is re-read before any resource action is offered.
                goals.append(GoalState(
                    "ALLIANCE_DONATION", GoalStatus.READY, reward_value=240,
                    available_skills=("OPEN_ALLIANCE_TECH_FROM_HOME",),
                    evidence={"source": "LIVE_ALLIANCE_HOME_CONTINUATION",
                              "operation": "READ_TECHNOLOGY_DONATION_STATE"},
                    distance=0.5,
                ))
            elif status == "AVAILABLE":
                goals.append(GoalState(
                    "ALLIANCE_DONATION", GoalStatus.READY, reward_value=240,
                    available_skills=("ALLIANCE_TECH_CONTRIBUTE",),
                    evidence={"source": "LIVE_ALLIANCE_TECHNOLOGY",
                              "resource": world.alliance.get("resource"),
                              "cost": world.alliance.get("cost"),
                              "attempts_remaining": world.alliance.get("attempts_remaining")},
                    distance=0.25,
                ))
            elif status == "CONTRIBUTED":
                goals.append(GoalState(
                    "ALLIANCE_DONATION", GoalStatus.COMPLETE, completion=1.0,
                    evidence={"source": "LIVE_ALLIANCE_TECHNOLOGY",
                              "status": status,
                              "attempts_remaining": world.alliance.get("attempts_remaining")},
                    distance=0.0,
                ))
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
        self._append_training_continuation(goals, world, training_continuation_goal_id)
        self._append_queue_goal(
            goals, "KEEP_RESEARCH_PRODUCTIVE", world.research,
            ("SELECT_RESEARCH_NODE", "RESEARCH", "OPEN_TECH_TREE"), RESEARCH_PRODUCTIVE_VALUE,
        )
        self._append_queue_goal(
            goals, "KEEP_BUILDING_PRODUCTIVE", world.building,
            ("OPEN_BUILDING_UPGRADE", "BUILDING_UPGRADE", "TRY_ORDINARY_CONTROL"),
            BUILDING_PRODUCTIVE_VALUE,
        )
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
        # The Alliance bottom-tab badge was present in every sampled HOME frame.
        # It therefore carries no information about Bear availability and must not
        # manufacture a Bear discovery goal.  Bear discovery is emitted below only
        # from the specific live Alliance War tile on Alliance HOME.
        _append_quick_panel_task_goals(goals, world)
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
            # No free slot is a game condition, not a completion: the marches are out and will come
            # back, which is §一's WAITING_GAME_CONDITION and §六's "记录具体恢复条件".  Written as
            # COMPLETE until 2026-09-23, so "every march is busy" and "there is nothing to gather"
            # were the same record.  The one measurable reason to care is the one the directive
            # names: a task that reads as finished can never be woken, so the reason it was not run
            # is lost exactly when someone asks why.
            waiting = idle <= 0
            goals.append(GoalState(
                "KEEP_MARCHES_PRODUCTIVE",
                GoalStatus.BLOCKED if waiting else GoalStatus.READY,
                completion=0.0 if not waiting else 1.0,
                development_value=70,
                available_skills=("DISPATCH_MARCH", "SEARCH_RESOURCE"),
                evidence={"idle_marches": idle, "march_max": world.march_max,
                          "condition": "no_idle_march_slot" if waiting else ""},
                distance=float(max(0, idle)),
            ))
        minimum = world.events.get("minimum_guarantee") if isinstance(world.events, dict) else None
        if isinstance(minimum, dict):
            missing = int(minimum.get("points_missing", 0))
            claimed = bool(minimum.get("all_target_rewards_claimed", False))
            left = _optional_int(minimum.get("remaining_seconds"))
            until_start = _optional_int(minimum.get("seconds_to_start"))
            complete = missing <= 0 and claimed
            # A window that has closed is EXPIRED, not "ready at a negative deadline".  Measured
            # 2026-09-23: ``deadline_pressure(0)`` is -100_000, which pushes such a goal down the
            # board without ever taking it off -- so a closed event stayed selectable, and could
            # still be picked on a frame where nothing else had a price.  EXPIRED is the same fact
            # stated so that ranking excludes it (§一: EXPIRED vs COMPLETED are different records).
            window_closed = left is not None and left <= 0
            # The EVENT page can be visible before the scoring window. Its explicit
            # "distance to start" countdown is stronger than a missing points field:
            # retain the task, but never send the generic live fallback before opening.
            scheduled_not_open = until_start is not None and until_start > 0
            if scheduled_not_open:
                status = GoalStatus.SCHEDULED_NOT_OPEN
            elif complete:
                status = GoalStatus.COMPLETE
            elif window_closed:
                status = GoalStatus.EXPIRED
            elif left is not None and left > 0:
                # A positive scoring-stage timer is current client evidence that this
                # occurrence is open. The event title or a saved appointment alone is not.
                status = GoalStatus.READY
            else:
                # No trustworthy open/close timer: retain the discovered goal, but do not
                # infer that it is actionable from the page title or missing countdown.
                status = GoalStatus.UNKNOWN
            event_id = str(minimum.get("event_id") or "")
            skills = tuple(str(x) for x in minimum.get("available_skills", ()))
            if status is GoalStatus.UNKNOWN:
                skills = ()
            generic_live_fallback = (
                world.page is Page.EVENT
                and bool(event_id)
                and status is GoalStatus.READY
                and not skills
            )
            if generic_live_fallback:
                # User directive: a recognized live event with no dedicated action must
                # enter the existing bounded, spend-screened current-UI control path.  It
                # cannot run away from Page.EVENT or make a waiting/unknown event actionable.
                skills = ("TRY_ORDINARY_CONTROL",)
            goals.append(GoalState(
                "EVENT_MINIMUM_GUARANTEE", status,
                completion=1.0 if complete else 0.0,
                remaining_seconds=left, reward_value=500,
                event_synergy=500, resource_cost=float(minimum.get("estimated_cost", 0)),
                available_skills=skills,
                evidence={"points_missing": missing, "claimed": claimed,
                          "window_closed": window_closed,
                          "seconds_to_start": until_start,
                          "event_id": event_id,
                          "generic_live_fallback": generic_live_fallback},
                distance=float(max(0, missing)),
            ))
        bear = world.events.get("bear") if isinstance(world.events, dict) else None
        if isinstance(bear, dict):
            phase = bear_phase(
                str(bear.get("status")) if bear.get("status") is not None else None,
                _optional_int(bear.get("seconds_to_start")),
                _optional_int(bear.get("remaining_seconds")),
            )
            # The phase already knows the window; this stops it being thrown away.  ``bear_phase``
            # answers SCHEDULED / PREPARING / READY / ACTIVE / FINISHED / DISCOVERED and the previous
            # expression collapsed every non-FINISHED one into ``READY``.  Measured 2026-09-23: a hunt
            # opening in two hours therefore carried ``status=READY`` and ``priority=5000`` -- it
            # outbid the sweep tickets that age to 180 and sat level with CLEAR_INTEL -- so "exists,
            # not open yet" was priced and scheduled as work (§一, SCHEDULED_NOT_OPEN).
            #
            # The distinction is not cosmetic and it is not a re-pricing: both of the two statuses
            # below are in ``NOT_ACTIONABLE``, so the goal leaves the board instead of merely losing
            # an argument about its number.
            if phase is BearPhase.FINISHED:
                status = GoalStatus.EXPIRED
            elif phase in {BearPhase.SCHEDULED, BearPhase.PREPARING}:
                status = GoalStatus.SCHEDULED_NOT_OPEN
            elif phase is BearPhase.DISCOVERED:
                # Seen, with no countdown anywhere: real, and nothing says when.  UNKNOWN_AVAILABILITY
                # -- §四, do not convert it into a visit in order to find out.
                status = GoalStatus.UNKNOWN
            else:
                status = GoalStatus.READY
            actionable = status is GoalStatus.READY
            skills: tuple[str, ...]
            if phase is BearPhase.ACTIVE:
                skills = ("OPEN_BEAR_RALLY_LIST", "START_RALLY", "JOIN_RALLY")
            elif phase in {BearPhase.PREPARING, BearPhase.READY}:
                skills = ("CHECK_MARCH", "SELECT_TROOP_PRESET")
            else:
                skills = ("CHECK_ALLIANCE_EVENT", "READ_BEAR_TIMER")
            goals.append(GoalState(
                "PARTICIPATE_BEAR", status,
                completion=1.0 if status is GoalStatus.EXPIRED else 0.0,
                remaining_seconds=_optional_int(bear.get("remaining_seconds") or bear.get("seconds_to_start")),
                reward_value=1000, daily_loss=5000 if phase in {BearPhase.READY, BearPhase.ACTIVE} else 0,
                available_skills=skills,
                evidence={"phase":phase.value, "reserved_start_time":bear.get("reserved_start_time"),
                          "normal_idle_slots":world.idle_marches,
                          "bear_rally_special_available":world.bear_rally_special_available,
                          # Named, so the plan below is not duplicated for an event already on the
                          # board with a live reading.
                          "event_id": "BEAR_HUNT", "window_open": actionable},
                distance=0.0 if status is GoalStatus.EXPIRED else 1.0,
            ))
        self._append_event_calendar_goal(
            goals, world, role_id=role_id, calendar_snapshot=calendar_snapshot
        )
        self._append_known_activities(goals, calendar_snapshot=calendar_snapshot)
        if (
            world.page is Page.ALLIANCE
            and world.alliance.get("section") == "HOME"
            and world.alliance.get("bear_entry_visible") is True
            and entry_badges.entry_gate(
                "DISCOVER_BEAR_RALLY_LIST", world.red_dots
            )[0] == entry_badges.PRESENT
            and not any(goal.goal_id == "PARTICIPATE_BEAR" for goal in goals)
        ):
            # This read-only discovery hop is not evidence that the event is open.
            # The destination reader must identify a live Bear row before any
            # march action can be offered.
            goals.append(GoalState(
                "DISCOVER_BEAR_RALLY_LIST", GoalStatus.READY,
                reward_value=100, available_skills=("OPEN_BEAR_RALLY_LIST",),
                evidence={
                    "event_id": "BEAR_HUNT",
                    "operation": "READ_CURRENT_RALLY_LIST",
                    "window": "UNKNOWN",
                    "live_entry_visible": True,
                    "participation_allowed": False,
                },
                distance=1.0,
            ))
        self._append_prepared_workflows(goals)
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
    def _append_prepared_workflows(goals: list[GoalState]) -> None:
        """Keep mapped workflows visible until a live observation can make them actionable.

        These records deliberately have no skills. The map currently lacks a production reader
        for attempt counters and alliance event windows, so registering the workflow must not
        invite the scheduler to navigate by guessed controls or prior-only data.
        """
        prepared = (
            ("USE_FREE_ARENA_ATTEMPTS", "world.attempts", "free arena attempts counter"),
            ("LABYRINTH_DAILY", "world.attempts", "Labyrinth attempts counter"),
            ("ALLIANCE_TIMED_EVENTS", "alliance/event producer", "event identity and live timer"),
        )
        existing = {goal.goal_id for goal in goals}
        for goal_id, missing_source, required_observation in prepared:
            if goal_id in existing:
                continue
            goals.append(GoalState(
                goal_id, GoalStatus.UNKNOWN, available_skills=(),
                evidence={
                    "prepared_only": True,
                    "availability": "AWAITING_LIVE",
                    "blocker": f"missing production observation: {missing_source}",
                    "required_observation": required_observation,
                    "live_verified": False,
                },
                distance=1.0,
            ))

    @staticmethod
    def _append_event_calendar_goal(
        goals: list[GoalState], world: WorldState, *, role_id: str,
        calendar_snapshot: Mapping[str, Any] | None = None,
    ) -> None:
        """Schedule a bounded read once per day in the fresh role or unscoped-client bucket."""
        scope = "ROLE" if role_id else "UNSCOPED_CLIENT"
        scoped_role_id = role_id or None
        events = world.events if isinstance(world.events, Mapping) else {}
        if world.page is Page.UNKNOWN and events.get("calendar_detail_return_pending") is True:
            goals.append(GoalState(
                "DISCOVER_EVENT_CALENDAR", GoalStatus.READY,
                reward_value=1200, daily_loss=1200, development_value=1200,
                available_skills=("BACK",),
                evidence={
                    "role_id": scoped_role_id,
                    "scope": scope,
                    "operation": "BOUNDED_BACK_FROM_UNNAMED_PAGE_TO_RESUME_CALENDAR_SCAN",
                    "calendar_detail_return_pending": True,
                    "no_arbitrary_control": True,
                },
                distance=0.0,
            ))
            return
        detail = events.get("calendar_detail")
        if isinstance(detail, Mapping) and detail.get("recognized") is True:
            detail_event_id = str(detail.get("event_id") or "")
            saved_entries = [
                row for row in ((calendar_snapshot or {}).get("entries") or ())
                if isinstance(row, Mapping)
            ]
            from_grid = detail.get("calendar_origin") == "GRID_ENTRY" or any(
                str(row.get("event_id") or "") == detail_event_id
                and row.get("details_observed") is not True
                for row in saved_entries
            )
            next_skill = "RETURN_EVENT_CALENDAR" if from_grid else "OPEN_EVENT_CALENDAR_TAB"
            goals.append(GoalState(
                "DISCOVER_EVENT_CALENDAR", GoalStatus.READY,
                reward_value=300, daily_loss=450, development_value=250,
                available_skills=(next_skill,),
                evidence={
                    "role_id": scoped_role_id,
                    "scope": scope,
                    "operation": (
                        "RETURN_TO_GRID_AFTER_EVENT_DETAIL" if from_grid
                        else "OPEN_CALENDAR_TAB_FROM_REGULAR_EVENTS"
                    ),
                    "event_id": detail.get("event_id"),
                    "event_name": detail.get("display_name"),
                    "activity_open_window": [detail.get("activity_open_start_raw"), detail.get("activity_open_end_raw")],
                    "registration_window": [detail.get("registration_start_raw"), detail.get("registration_end_raw")],
                    "battle_window": [detail.get("battle_start_raw"), detail.get("battle_end_raw")],
                    "countdown_raw": detail.get("countdown_raw"),
                    "current_open_state": detail.get("current_open_state", "UNKNOWN"),
                    "time_zone": detail.get("time_zone"),
                },
                distance=1.0,
            ))
            return
        calendar = events.get("calendar")
        if isinstance(calendar, Mapping) and calendar.get("recognized") is True:
            entries = [dict(row) for row in (calendar.get("entries") or ()) if isinstance(row, Mapping)]
            saved_entries = [
                row for row in ((calendar_snapshot or {}).get("entries") or ())
                if isinstance(row, Mapping)
            ]
            saved_by_key = {
                str(row.get("occurrence_key") or f"{row.get('event_id')}|{row.get('calendar_date_raw') or 'UNKNOWN_DATE'}"): row
                for row in saved_entries
            }
            for row in entries:
                key = str(row.get("occurrence_key") or f"{row.get('event_id')}|{row.get('calendar_date_raw') or 'UNKNOWN_DATE'}")
                saved = saved_by_key.get(key)
                if isinstance(saved, Mapping):
                    row.update({name: saved[name] for name in (
                        "details_observed", "details_observed_at", "detail_evidence_ref", "detail_observation"
                    ) if name in saved})
            pending = [row for row in entries if row.get("details_observed") is not True and row.get("tap_norm")]
            if pending:
                status = GoalStatus.READY
                skills = ("OPEN_EVENT_CALENDAR_DETAIL",)
                completion = 0.0
            else:
                status = GoalStatus.COMPLETE
                skills = ()
                completion = 1.0
            goals.append(GoalState(
                "DISCOVER_EVENT_CALENDAR", status,
                completion=completion, available_skills=skills,
                reward_value=300 if status is GoalStatus.READY else 0,
                daily_loss=450 if status is GoalStatus.READY else 0,
                development_value=250 if status is GoalStatus.READY else 0,
                evidence={
                    "source": calendar.get("source", "LIVE_CLIENT_OCR"),
                    "scope": scope,
                    "role_id": scoped_role_id,
                    "entry_count": len(entries),
                    "details_observed_count": sum(row.get("details_observed") is True for row in entries),
                    "details_pending_count": len(pending),
                    "details_unavailable_count": sum(not row.get("tap_norm") for row in entries),
                    "next_event_id": pending[0].get("event_id") if pending else None,
                    "event_ids": [str(row.get("event_id")) for row in entries
                                  if isinstance(row, Mapping) and row.get("event_id")],
                    "visible_dates_raw": list(calendar.get("visible_dates_raw") or ()),
                    "calendar_read_in_current_frame": True,
                    "calendar_details_are_separate_from_battle_time": True,
                    "activity_times_are_previews": True,
                },
                distance=0.0,
            ))
            return
        if world.page not in {Page.HOME, Page.MAP}:
            return
        try:
            from .event_schedule import calendar_scan_due

            due = calendar_scan_due(role_id)
        except Exception:  # noqa: BLE001 -- calendar maintenance must never stop AUTO
            due = False
        if not due:
            return
        entry_reading = (world.events or {}).get("calendar_entry") if isinstance(world.events, Mapping) else None
        entry_visible = isinstance(entry_reading, Mapping) and entry_reading.get("visible") is True
        if not entry_visible:
            if world.page is Page.MAP:
                goals.append(GoalState(
                    "DISCOVER_EVENT_CALENDAR", GoalStatus.READY,
                    # A due calendar read must be allowed to reach the city HUD even when the
                    # current map frame cannot see its entry. Otherwise unrelated map work can
                    # permanently win the board before the calendar is ever inspected.
                    reward_value=300, daily_loss=450, development_value=250,
                    available_skills=("OPEN_HOME",),
                    evidence={
                        "role_id": scoped_role_id,
                        "scope": scope,
                        "scan_due": True,
                        "page": world.page.value,
                        "operation": "RETURN_TO_CITY_TO_FIND_CALENDAR_ENTRY",
                        "entry_visible": False,
                        "no_event_time_inferred": True,
                    },
                    distance=1.0,
                ))
                return
            goals.append(GoalState(
                "DISCOVER_EVENT_CALENDAR", GoalStatus.UNKNOWN,
                available_skills=(),
                evidence={
                    "role_id": scoped_role_id,
                    "scope": scope,
                    "scan_due": True,
                    "page": world.page.value,
                    "blocker": "current-frame 常规活动 entry not recognized",
                    "no_event_time_inferred": True,
                },
                distance=1.0,
            ))
            return
        skill = (
            "OPEN_EVENT_CALENDAR_FROM_HOME" if world.page is Page.HOME
            else "OPEN_EVENT_CALENDAR_FROM_MAP"
        )
        goals.append(GoalState(
            "DISCOVER_EVENT_CALENDAR", GoalStatus.READY,
            # This is a daily maintenance read for future activities. It should win over
            # background resource work once when due, then disappear for the rest of the day.
            reward_value=300, daily_loss=450, development_value=250,
            available_skills=(skill,),
            evidence={
                "role_id": scoped_role_id,
                "scope": scope,
                "operation": "READ_CURRENT_AND_VISIBLE_FUTURE_EVENT_DATES",
                "scan_due": True,
                "page": world.page.value,
                "entry_visible": entry_visible,
                "activity_times_are_previews": True,
                "no_event_time_inferred": True,
            },
            distance=1.0,
        ))

    @staticmethod
    def _append_known_activities(
        goals: list[GoalState], *, calendar_snapshot: Mapping[str, Any] | None = None
    ) -> None:
        """Put the activities this project already knows about on the board, open or not (§二/§三).

        Before this, an activity existed in the agent's world only as a field on a frame.  Measured
        2026-09-23 over 7593 production episodes: 5 carried ``minimum_guarantee`` and none carried
        ``bear``.  So a limited-time event that was not currently drawn on the screen **did not
        exist** -- and the run could only notice it by happening to stand somewhere that prints it.
        That is the conflation this function removes: 存在性不再只依赖当前帧.

        What it emits is a *registered record*, not currently actionable work:

        * The existing goal and skill IDs are copied into ``registered_goal_ids`` and
          ``registered_skill_ids``. The activity remains ``UNKNOWN``/``SCHEDULED_NOT_OPEN`` until
          the current client supplies its live conditions; no historical verification gate is
          added, and no calendar preview is promoted to an opening or battle clock.
        * ``available_skills=()`` keeps the dormant record out of ordinary dispatch. When a live
          page makes the event actionable, its existing task goal (for example
          ``EVENT_MINIMUM_GUARANTEE`` or ``PARTICIPATE_BEAR``) owns execution and de-duplicates
          this registration by ``event_id``.
        * the status is the window's, so the artifact says which of the six semantics applies.
        * ``evidence["prepare"]`` carries what §三 asks to have ready and ``evidence["knowledge"]``
          the files it lives in.  Preparing is not a page entry, so it is not a skill.

        An activity the live branches already reported is skipped: those tickets carry real readings
        and are the ones that may act, and two records for one event would be two places for the
        answer to disagree.
        """
        reported = {str((goal.evidence or {}).get("event_id") or "") for goal in goals}
        snapshot = calendar_snapshot if isinstance(calendar_snapshot, Mapping) else {}
        calendar_rows = [row for row in (snapshot.get("entries") or ()) if isinstance(row, Mapping)]
        observed_ids = {str(row.get("event_id") or "") for row in calendar_rows}
        static_ids = {activity.event_id for activity in event_goal.known_activities()}
        for activity in event_goal.known_activities():
            current_ids = {activity.event_id, *activity.aliases}
            if not activity.event_id or current_ids.intersection(reported):
                continue
            window = activity.window()
            registered = _registered_activity_flow(activity)
            goals.append(GoalState(
                f"SCHEDULED_{activity.event_id}",
                _WINDOW_STATUS[window],
                completion=1.0 if window is event_goal.WindowState.EXPIRED else 0.0,
                available_skills=(),
                evidence={
                    **activity.plan(),
                    **registered,
                    "calendar_observation": next((dict(row) for row in calendar_rows
                                                   if str(row.get("event_id") or "") == activity.event_id), None),
                    "calendar_observed_at": snapshot.get("observed_at"),
                    "calendar_role_id": snapshot.get("role_id"),
                    "window": window.value,
                    "live_reading": False,
                    "availability_state": "AWAITING_LIVE_CLIENT_READING",
                    "dispatch_rule": "use the registered event flow only after the current client identifies the event and its live conditions",
                    "fallback": "match a registered generic event flow, then use the current UI planner when a step is missing",
                },
                distance=1.0,
            ))
        # New localized names discovered in a calendar remain visible as role-scoped candidates.
        # They carry no guessed mechanics, timing or executable action until a live page supplies
        # those facts; exact IDs are deduplicated with any live event goal already on the board.
        for row in calendar_rows:
            event_id = str(row.get("event_id") or "")
            if not event_id or event_id in static_ids or event_id in reported:
                continue
            goals.append(GoalState(
                f"SCHEDULED_{event_id}", GoalStatus.UNKNOWN,
                available_skills=(),
                evidence={
                    "event_id": event_id,
                    "name": row.get("display_name"),
                    "activity_goal_id": f"SCHEDULED_{event_id}",
                    "registered_goal_ids": ["DISCOVER_EVENT_CALENDAR", "EVENT_MINIMUM_GUARANTEE"],
                    "registered_skill_ids": _registered_event_candidate_skills(),
                    "unregistered_skill_ids": _unregistered_event_candidate_skills(),
                    "flow_registration_state": "PARTIAL_GENERIC_FALLBACK_REGISTERED_WAITING_FOR_LIVE_CONDITIONS",
                    "calendar_observation": dict(row),
                    "calendar_observed_at": snapshot.get("observed_at"),
                    "calendar_role_id": snapshot.get("role_id"),
                    "availability_state": "CALENDAR_PREVIEW_ONLY",
                    "start": None,
                    "end": None,
                    "participation_conditions": "UNKNOWN",
                    "fallback": "match a registered generic event flow after live page and conditions are observed",
                },
                distance=1.0,
            ))

    @staticmethod
    def _append_queue_goal(goals: list[GoalState], goal_id: str, state: dict[str, Any], skills: tuple[str, ...], value: float) -> None:
        """A queue goal, in the right one of §一's two semantics.

        ``busy`` is a *game condition*, not a completion: the work still exists, the client is simply
        not letting it be started yet.  Until 2026-09-23 this wrote ``COMPLETE`` -- which is §一's
        "本次任务实际完成" -- so "the queue is full" and "there is nothing left to train" were the
        same record, and §六's "记录具体恢复条件" had nothing to record against.

        ``WAITING_GAME_CONDITION`` maps onto ``BLOCKED`` + ``retry_after`` (the queue's own timer,
        when the frame printed one) rather than to a new status: both are already excluded from
        ranking, so this is a change to what the artifact *says*, not to what gets executed.  The
        ``completion``/``distance`` numbers are deliberately untouched for the same reason -- the
        progress meter and the capability gate's streak read them, and this change is not about
        either.
        """
        if not state:
            return
        busy = state.get("queue_available") is False or state.get("status") == "IN_PROGRESS" or state.get("all_queues_busy") is True
        goals.append(GoalState(goal_id, GoalStatus.BLOCKED if busy else GoalStatus.READY,
                               completion=1.0 if busy else 0.0, development_value=value,
                               available_skills=skills,
                               retry_after=(str(state.get("timer") or "") or None) if busy else None,
                               evidence={"queue_busy": busy,
                                         "condition": "queue_busy" if busy else ""},
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
        * **positively running** (a countdown was read) -> BLOCKED for that camp only, with the
          countdown kept as its ``retry_after``: the work still exists and is being done by the
          client.  The other two camps are untouched by this, which is the whole point.
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
        if legacy_camp is None:
            camp_key = str((world.training or {}).get("camp") or "").upper()
            camp_label = str((world.training or {}).get("camp_label") or "")
            if camp_key in CAMP_GOAL_FOR:
                legacy_camp = camp_key
            elif camp_label:
                legacy_camp = next((key for key, label in CAMP_LABELS.items() if label == camp_label), None)

        if not camps:
            # No per-camp model yet.  Keep the old single reading as one ticket, but name the
            # camp it belongs to when the troop type identifies one, so the board shows
            # SHIELD_CAMP rather than an anonymous "training".
            training_reading = world.training or {}
            has_queue_or_camp_fact = any(
                key in training_reading
                for key in (
                    "status", "queue_available", "trainable", "claimable", "troop_type",
                    "camp", "camp_label", "menu_open", "all_queues_busy",
                )
            )
            if has_queue_or_camp_fact:
                self._append_queue_goal(
                    goals, CAMP_GOAL_FOR.get(legacy_camp, "KEEP_TRAINING_PRODUCTIVE"),
                    training_reading, ("TRAIN_TROOPS",), TRAINING_CAMP_VALUE,
                )
            elif not world.training:
                # Never read: a sweep ticket, priced like the other unread routines.
                _append_panel_routine(goals, TRAINING_SWEEP, None,
                                      (observations or {}).get("training"))
            return

        for camp in CAMP_ORDER:
            state = dict(camps.get(camp) or {})
            goal_id = CAMP_GOAL_FOR[camp]
            status = str(state.get("status") or "").upper()
            queue_available = state.get("queue_available")
            # The HOME quick panel is a real observation of each barracks, but its reader uses
            # ``status``/``queue_available`` and does not attach the page reader's ``observed``
            # marker.  Treating that vocabulary as unread made all three visible idle camps
            # DISCOVERED, so AUTO kept scheduling an observation instead of the actual training
            # goal.  Derive only from explicit queue facts or an unambiguous queue status; leave
            # missing/unknown readings DISCOVERED rather than guessing.
            observed = (
                state.get("observed") is True
                or isinstance(queue_available, bool)
                or status in {"IDLE", "AVAILABLE", "COMPLETED", "IN_PROGRESS", "BUSY", "TRAINING"}
            )
            busy = state.get("busy")
            if not isinstance(busy, bool):
                if queue_available is False or status in {"IN_PROGRESS", "BUSY", "TRAINING"}:
                    busy = True
                elif queue_available is True or status in {"IDLE", "AVAILABLE"}:
                    busy = False
            evidence = {
                "camp": camp,
                "label": CAMP_LABELS[camp],
                "status": state.get("status", "UNKNOWN"),
                "timer": state.get("timer"),
                "batch_count": state.get("batch_count"),
                "source": state.get("source"),
                "source_word": state.get("source_word"),
                "badge": state.get("badge", "UNKNOWN"),
                "observed": observed,
            }
            if observed and status == "COMPLETED":
                # A completed batch is still actionable work: route to the named barracks
                # and inspect its current client controls. The quick-panel tick itself was
                # disproved as a collection target, so this goal must never click it; keeping
                # the camp BLOCKED here made AUTO unable to discover any alternative path.
                goals.append(GoalState(
                    goal_id, GoalStatus.READY, completion=0.0,
                    development_value=TRAINING_CAMP_VALUE, available_skills=("TRAIN_TROOPS",),
                    evidence={**evidence, "reason": "completed_batch_requires_live_camp_inspection",
                              "condition": "finished_batch_collection_or_restart_due",
                              "collection_verified": False},
                    distance=1.0,
                ))
            elif observed and busy is True:
                # This camp is training: a game condition (§一, WAITING_GAME_CONDITION), not a
                # completion.  Recorded as COMPLETE until 2026-09-23 -- §一's "本次任务实际完成" --
                # which made "this barracks is busy" and "this barracks has nothing to train" the
                # same record and left §六's "记录具体恢复条件" nowhere to live.  BLOCKED is the same
                # fact stated so that it is not a finished task; like COMPLETE it carries no
                # skills and no priority, so nothing about which camp gets worked changes.
                goals.append(GoalState(
                    goal_id, GoalStatus.BLOCKED, completion=1.0,
                    development_value=TRAINING_CAMP_VALUE, available_skills=(),
                    retry_after=(str(state.get("timer") or "") or None),
                    evidence={**evidence, "reason": "this_camp_is_training",
                              "condition": "camp_queue_busy"},
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

    @staticmethod
    def _append_training_continuation(
        goals: list[GoalState], world: WorldState, goal_id: str
    ) -> None:
        """Keep a selected barracks task schedulable across its two UI-only steps.

        A completed quick-panel row closes the panel and leaves HOME on a focused-barracks
        frame. That frame no longer contains the panel's three queue readings, so ordinary
        discovery used to drop the just-selected camp and let an unrelated goal take over
        before the action bar could open. The committed goal identity comes from the row the
        Scheduler selected; the current-frame halo only authorizes this bounded navigation
        continuation. Reward feedback is also an intermediate state after collecting a batch.
        This appends to the existing Goal board and still lets the same Scheduler rank it.
        """
        camp = next((key for key, value in CAMP_GOAL_FOR.items() if value == str(goal_id)), None)
        if camp is None:
            return
        training = world.training or {}
        focused = (
            world.page is Page.HOME
            and training.get("navigation") == "PANEL_CAMP_FOCUSED"
            and isinstance(training.get("camp_focus_tap_norm"), (tuple, list))
            and len(training.get("camp_focus_tap_norm")) == 2
        )
        reward_feedback = world.page is Page.POPUP and world.popup == "GENERIC_REWARD"
        if not (focused or reward_feedback):
            return
        existing_index = next(
            (index for index, item in enumerate(goals) if item.goal_id == goal_id),
            None,
        )
        if existing_index is not None and goals[existing_index].evidence.get("continuation") is True:
            return
        continuation = GoalState(
            goal_id, GoalStatus.READY, completion=0.0,
            development_value=TRAINING_CAMP_VALUE,
            available_skills=("TRAIN_TROOPS",),
            evidence={
                "camp": camp,
                "continuation": True,
                "intermediate_state": "PANEL_CAMP_FOCUSED" if focused else "TRAINING_REWARD_FEEDBACK",
                "source": "CURRENT_GOAL_AND_CURRENT_FRAME",
            },
            distance=1.0,
        )
        if existing_index is None:
            goals.append(continuation)
        else:
            # The current screen is authoritative for this short handoff. A stale
            # DISCOVERED/BLOCKED queue reading must not erase the selected camp task
            # between its quick-panel entry, focus tap, and training page.
            goals[existing_index] = continuation

    def rank(
        self,
        goals: Iterable[GoalState],
        world: WorldState | None = None,
        *,
        fairness: Mapping[str, goal_utility.GoalFairness] | None = None,
        routes: Iterable[goal_utility.RouteFact] | None = None,
        event_readiness: Mapping[str, float] | None = None,
        now: datetime | None = None,
    ) -> tuple[tuple[GoalState, goal_utility.UtilityBreakdown], ...]:
        """The whole board, best first, with every term of each goal's utility (§九).

        ``best`` answers "what next"; this answers "why that, and what lost", which is
        what a decision log has to carry.  Both go through the same ranking so the log
        can never disagree with the choice it is describing.
        """
        return goal_utility.rank(
            goals, world=world, facts=routes or (), ledger=fairness,
            event_readiness=event_readiness, now=now
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
