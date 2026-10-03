from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping
import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .camp_training import CAMP_LABELS, CAMP_ORDER, TROOP_TO_CAMP
from .models import Page, WorldState
from . import entry_badges
from . import event_goal
from . import fishing_pressure
from . import goal_utility
from . import ocr
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

_QUEUE_COUNTDOWN_RE = re.compile(
    r"(?:(?:\d+)\s*(?:天|d)\s*)?\d{1,3}:\d{2}:\d{2}",
    re.IGNORECASE,
)


def _queue_countdown_text(state: Mapping[str, Any]) -> str | None:
    """Keep a real queue countdown even when OCR only populated ``source_word``."""
    for key in ("timer", "source_word"):
        value = str(state.get(key) or "").strip()
        if value and _QUEUE_COUNTDOWN_RE.fullmatch(value):
            return value
    return None

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
    "USE_NORMAL_FISHING_BAIT": "FISHING",
    "USE_FISHING_BAIT": "FISHING",
    "OBSERVE_FISHING_STATE": "FISHING",
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
    # Mobilization is a role-local Goal provider. Its accepted task is translated
    # to an existing route; it does not own a Scheduler or executor.
    "ALLIANCE_MOBILIZATION_TROOP_TRAINING_120K": "TRAIN",
    "ALLIANCE_MOBILIZATION_ICEFIELD_BEAST": "GIANT_BEAST",
    "ALLIANCE_MOBILIZATION_LARGE_GATHER": "GATHER_RESOURCE",
    "ALLIANCE_MOBILIZATION_BEAST": "BEAST_HUNT",
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
    "EXPLORATION", "DAILY", "ALLIANCE", "RESEARCH", "TRAIN", "BUILDING", "EVENT", "FISHING",
    "GIANT_BEAST",
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
    if value.startswith("SCHEDULED_"):
        # Every activity row the calendar emits is ``SCHEDULED_{event_id}``, and the id is generated
        # per discovered event, so no table can hold it.  This is a **declared** route rather than a
        # convenient one: the rows carry ``registered_goal_ids``, and the ones that name a goal name
        # ``DISCOVER_EVENT_CALENDAR`` and ``EVENT_MINIMUM_GUARANTEE`` -- both ``EVENT``.  Without it
        # they were unroutable, so together with no ``required_observation`` they were priced at
        # ``-inf`` and never observed: measured 2026-10-02, 20 rows on a live board, every one
        # classified ``MISSING_NAVIGATION`` with ``route_exists=False``.
        return "EVENT"
    if value.startswith("CLAIM_FREE_"):
        # The current reward reader emits page-scoped goals. Reuse the page's
        # existing reward route; unknown pages must not inherit Gather by default.
        reward_page = value.removeprefix("CLAIM_FREE_")
        if reward_page in {"MAIL", "DAILY", "ALLIANCE", "EXPLORATION", "INTEL", "EVENT"}:
            return reward_page
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

#: The five goals the fishing provider owns (Production Sprint NEXT P3, 2026-09-30).
#:
#: ``USE_NORMAL_FISHING_BAIT`` is the normal lane and the *only* lane.  The special-mode ids the
#: operator forbade are deliberately absent from this tuple: they are ``POLICY_DISABLED_BY_USER``,
#: they have no provider, and the point of §P1 is that nothing is to be developed for them.
#: Their exact spelling lives in ``config/policy_state.json#disabled_goals`` and in the registry's
#: ``policy_disabled_tasks`` -- the readers that must refuse them -- and is *not* repeated here.
#: Enumerating them in an execution module, even to skip them, would leave them one typo away from
#: being emitted, and ``tests/test_fishing_policy_v2.py`` fails any code path that names one.
FISHING_GOAL_IDS: tuple[str, ...] = (
    "USE_NORMAL_FISHING_BAIT",
    "CLAIM_FISHING_FREE_REWARD",
    "UPGRADE_FISHING_KIT",
    "CLAIM_FISHING_DAILY_REWARD",
    "CLAIM_FISHING_COLLECTION_REWARD",
)

#: What each of those goals still needs read off the client before it can be carried out.  Used as
#: ``evidence["required_observation"]`` so the board answers "blocked *by what*" instead of "blocked".
#:
#: ``USE_NORMAL_FISHING_BAIT`` is the exception: the provider knows the bait counter, which is the
#: only reading that decides it.  It still owes a *Skill* -- there is no production fishing Skill
#: yet, which is why it is emitted as a record (no ``available_skills``) rather than as selectable
#: work.  That is a capability gap, and it is named rather than hidden.
FISHING_REQUIRED_OBSERVATIONS: dict[str, str] = {
    "CLAIM_FISHING_FREE_REWARD": "the fishing page's free-reward state",
    "UPGRADE_FISHING_KIT": "gear level, upgrade cost and free event currency owned (§5/P11)",
    "CLAIM_FISHING_DAILY_REWARD": "the fishing page's daily-reward state",
    "CLAIM_FISHING_COLLECTION_REWARD": "the fishing collection progress and its reward state",
}

#: The Skill the normal lane needs and does not have.  Named once so the gap is greppable.
FISHING_LANE_SKILL = "PLAY_NORMAL_FISHING_LEVEL"


def _as_iso(value: object) -> str | None:
    """A timestamp the client printed, as an ISO string, or ``None``.

    ``None`` is the honest answer for "we do not know when", and the caller must keep it: the
    fishing provider hands this to ``GoalState.retry_after``, where a substituted clock would read
    as a real recovery time and let a role with no bait be scheduled.
    """
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None:
        return None
    text = str(value).strip()
    return text or None

#: An activity window, in this project's goal vocabulary.  One table, so a window state that is not
#: listed is a ``KeyError`` at the only place that maps them rather than a silently wrong status.
_WINDOW_STATUS: dict[event_goal.WindowState, GoalStatus] = {
    event_goal.WindowState.OPEN: GoalStatus.READY,
    event_goal.WindowState.SCHEDULED_NOT_OPEN: GoalStatus.SCHEDULED_NOT_OPEN,
    event_goal.WindowState.EXPIRED: GoalStatus.EXPIRED,
    event_goal.WindowState.UNKNOWN: GoalStatus.UNKNOWN,
}

#: The one action an activity ticket may carry while it is still waiting to be read.
#:
#: Measured 2026-10-03 on the 24 hours ending then: all 20 SCHEDULED_* tickets were selected
#: 121 times and 284 decisions named one as the winner, and the skills they actually ran were
#: OPEN_MAP 38, INTEL_HERO_DISPATCH 26, START_GATHER 15, SUBMIT_RESOURCE_SEARCH 14 -- none of
#: them about the activity.  The cause was not that the tickets were invisible: the
#: observation ticket prices them (50.0 measured) and ``goal_utility.rank`` keeps any row that
#: price reaches, so they were on the board.  It was that ``available_skills=()`` left the
#: brain with nothing to issue, and the generic fallback then ran whatever the page offered.
#: A ticket that names what it needs to read and carries no way to read it is how a scheduled
#: observation becomes an unrelated action.
#:
#: ``READ_EVENT_CALENDAR`` is the project's own action for this -- ``Action("OBSERVE",
#: "EVENT_CALENDAR")`` on ``Page.EVENT``, verified by the implemented
#: ``verify_event_calendar_read``, which passes only on page EVENT plus a recognised calendar
#: plus at least two distinct date anchors plus at least one entry.  It takes no input and
#: claims nothing: reading is exactly what a ticket blocked on ``required_observation`` is
#: allowed to do, and it cannot spend resources, so it cannot become a way to act on an
#: activity whose live conditions were never read.
#:
#: Deliberately **not** ``READ_TIMER``: it looks like a closer fit, but its declared
#: ``TIMER_READ`` verifier and its execution path do not exist anywhere in the package, so
#: offering it would turn "no action" into "an action certain to fail".
_ACTIVITY_OBSERVATION_SKILLS: tuple[str, ...] = ("READ_EVENT_CALENDAR",)


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


def action_relevant_goal_ids(
    goals: Iterable[GoalState],
    skill_id: str,
    world: WorldState | None,
    *,
    primary_goal_id: str = "",
) -> tuple[str, ...]:
    """Return goals this action can actually advance on the current role/frame.

    Several independent goals can share one generic Skill. Training is the concrete
    example: all three camp Goals use ``TRAIN_TROOPS``, but starting shield training
    cannot advance the lancer or marksman queue. Attaching every same-Skill Goal made
    those untouched camps accumulate false no-progress penalties. Keep generic shared
    credit, while scoping a camp Goal to the camp positively identified on this frame.
    If that identity is unavailable, only the already-selected camp Goal may be tracked.
    """
    skill = str(skill_id or "")
    selected_goal = str(primary_goal_id or "")
    training_goal = _training_goal_for_world(world) if skill == "TRAIN_TROOPS" else None
    camp_goals = set(CAMP_GOAL_FOR.values())
    relevant: list[str] = []
    for goal in goals:
        goal_id = str(getattr(goal, "goal_id", "") or "")
        if not goal_id:
            continue
        skills = tuple(str(item) for item in (getattr(goal, "available_skills", ()) or ()))
        if goal_id in camp_goals:
            if skill != "TRAIN_TROOPS":
                if goal_id != selected_goal:
                    continue
            elif training_goal is not None:
                if goal_id != training_goal:
                    continue
            elif goal_id != selected_goal:
                continue
        elif skill not in skills and goal_id != selected_goal:
            continue
        relevant.append(goal_id)
    return tuple(dict.fromkeys(relevant))


def _training_goal_for_world(world: WorldState | None) -> str | None:
    """Resolve the selected training camp from explicit, current-frame identity facts."""
    if world is None:
        return None
    training = world.training if isinstance(world.training, Mapping) else {}
    camps = world.camps if isinstance(world.camps, Mapping) else {}
    identities: set[str] = set()

    def add_camp(value: Any) -> None:
        camp = str(value or "").strip().upper()
        if camp in CAMP_GOAL_FOR:
            identities.add(camp)

    add_camp(training.get("camp"))
    add_camp(TROOP_TO_CAMP.get(str(training.get("troop_type") or "").strip().upper()))
    for key in ("camp_open_label", "camp_label"):
        label = str(training.get(key) or "").strip()
        if label:
            add_camp(next((camp for camp, known in CAMP_LABELS.items() if known == label), None))
    selected = [camp for camp, row in camps.items()
                if isinstance(row, Mapping) and row.get("selected") is True]
    for camp in selected:
        add_camp(camp)
    if len(identities) != 1:
        return None
    return CAMP_GOAL_FOR[next(iter(identities))]


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
    # The step goes to the training page, not to a generic control.  Measured 2026-10-03 on
    # the live ledger: this ticket was selected 561 times and did ``OPEN_HOME`` 425 of them,
    # never training once and never reporting ``goal_progress``; 60% of HOME frames carry no
    # ``camps`` reading, and coming home does not produce one, so the loop sustained itself.
    # Its whole purpose is "go and look at the page that answers this goal", and a generic
    # control resolves to a page that cannot.
    #
    # ``OPEN_INFANTRY_TRAINING`` is the measured answer rather than an assumed one: 57 live
    # attempts, 57 SUCCESS, and every after-frame carried the reading that was missing
    # (``{"MARKSMAN_CAMP": {"status": "AVAILABLE", "queue_available": true, ...}}``), which is
    # what promotes this family from the single coarse ticket to the per-camp goals.
    #
    # It stays a fallback: ``discovery_value=SWEEP_NEVER_VALUE`` is below
    # ``TRAINING_CAMP_VALUE``, so a camp with live work still outranks the visit, and
    # ``_append_camp_training_goals`` keeps the whole family off this ticket whenever a
    # ``camps`` reading exists.
    entry_skill="OPEN_INFANTRY_TRAINING",
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
    actionable_daily_rows = (
        routine.field == "daily"
        and any(
            isinstance(row, Mapping)
            and str(row.get("state") or "").upper() == "AVAILABLE"
            and isinstance(row.get("action_button"), Mapping)
            and row.get("action_button", {}).get("semantic_id") == "BTN_DAILY_TASK_GO"
            for row in effective.get("tasks", ())
        )
    )
    waiting = waiting or actionable_daily_rows
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
        "has_actionable_daily_task_rows": actionable_daily_rows,
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
        work_skills = routine.work_skills
        if actionable_daily_rows:
            work_skills = tuple(dict.fromkeys((
                "OPEN_DAILY", "SELECT_DAILY_TAB", "FOLLOW_DAILY_TASK", *work_skills,
            )))
        goals.append(GoalState(
            routine.goal_id, GoalStatus.READY,
            reward_value=250.0, daily_loss=250.0,
            available_skills=work_skills,
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
    if world.page is Page.HOME and panel.get("open") is True:
        # The sweep has been answered.  Without this row the goal *leaves the board* at
        # exactly the frame that answers it, and both accounting channels miss it:
        # ``progress_moved`` starts from ``next((g for g in after ...), None)`` and returns
        # ``None`` for an absent row -- "unobserved", which neither rewards nor penalises --
        # and ``newly_completed_goal_ids`` needs a COMPLETE row that cannot exist.  Measured
        # 2026-10-03 on the live ledger: 1291 selections (the most-selected goal in the
        # project), 54/54 recent steps succeeded, ``goal_progress`` None 54/54.  The goal
        # was never failing and never idle; the ledger simply had no way to say
        # "asked and answered" for a goal that answers by leaving.
        #
        # The shape is copied, not invented: ``ALLIANCE_DONATION`` below (CONTRIBUTED) and
        # ``CLEAR_INTEL`` (expired window) already keep a finished goal on the board as
        # COMPLETE with ``completion=1.0`` and ``distance=0.0``.
        #
        # No price and no skills, deliberately.  COMPLETE is in ``NOT_ACTIONABLE``, so
        # ``priority`` is ``-inf`` and ``goal_utility.rank`` drops the row -- the Scheduler
        # cannot re-select it.  Pricing it like the READY row would reopen the panel AUTO
        # just opened, forever.  ``served_by`` names the precondition that stopped holding,
        # so "answered" is distinguishable from "never asked" without replaying the frame.
        goals.append(GoalState(
            "DISCOVER_QUICK_PANEL_TASKS", GoalStatus.COMPLETE, completion=1.0,
            evidence={"source": "LIVE_QUICK_PANEL_OPEN",
                      "panel_open": True,
                      "served_by": "OPEN_QUICK_PANEL"},
            distance=0.0,
        ))
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
                              "OPEN_ALLIANCE_RECOMMENDED_TECH_NODE",
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
    # The client's own state word gates this row.  Measured 2026-10-03 on the full ledger
    # (10463 episodes): ``OPEN_TASK_FROM_QUICK_PANEL_PET_TREASURE`` ran 43 times, 43
    # SUCCESS, 0 FAILURE -- and on 37 of those BEFORE frames the row itself already read
    # ``status=COMPLETED`` / ``source_word=已完成``.  Perfect separation, no overlap, so the
    # row was not occasionally stale: the gate below simply never read the field.
    #
    # The 6 ``UNKNOWN`` rows are only legible by pairing -- every one of them is followed
    # 5-7 seconds later by a ``BACK``: the step opened the page and returned.  So **all 43
    # produced no reward** while the episode ledger called every one SUCCESS, because the
    # verifier answered "did the tap land", not "did the row have anything left".
    #
    # ``ocr.QUICK_PANEL_COMPLETED_WORDS`` is the reader's own vocabulary and is used as-is
    # rather than a second list.  ``status`` is checked too because it is what the reader
    # derived from that word: a frame carrying the word without the derived status must not
    # silently resume the 37 wasted taps.
    #
    # This is a **tightening**, so it is provably monotonic in the useful direction: the
    # accepted set only shrinks, and ``UNKNOWN`` (the state that means "we could not read
    # it") is explicitly *not* refused -- opening the page is how that state gets read.
    pet_word = str(pet.get("source_word") or "").strip()
    pet_finished = (
        str(pet.get("status") or "").strip().upper() == "COMPLETED"
        or pet_word in ocr.QUICK_PANEL_COMPLETED_WORDS
    )
    if (not pet_finished
            and pet.get("badge") == entry_badges.PRESENT
            and pet.get("control") in {"ARROW", "DONE"}):
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
        fishing_pressures: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> tuple[GoalState, ...]:
        """Every goal the engine can see from this world, plus what is still worth looking at.

        ``observations`` is optional and holds only *fresh* stored readings, keyed by the
        WorldState field they belong to.  Passing nothing means "no reading outlives this
        frame", which is the behaviour before the store existed -- so a caller that does not
        have one is not silently treated as having looked recently.

        ``fishing_pressures`` is optional and carries the per-role bait verdict (keyed by
        the role id the client printed) that FISHING POLICY V2 §3/§14/§15 derives from the
        bait counter.  Without it the fishing event's deadline is the raw client countdown,
        which is the behaviour that made an open event preempt the running role session on
        nearly every frame.  See ``fishing_pressure.event_goal_terms``.
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
        if (world.page is Page.HOME
                and alliance_continuation_goal_id == "ALLIANCE_DONATION"):
            # The daily task row's 前往 control returns to the city and highlights
            # 联盟; preserve the selected donation Goal across that measured hop.
            # Once on Alliance HOME, the existing branch below continues into its
            # technology node, and the live contribution reader remains the action gate.
            goals.append(GoalState(
                "ALLIANCE_DONATION", GoalStatus.READY, reward_value=240,
                available_skills=("OPEN_ALLIANCE",),
                evidence={"source": "LIVE_DAILY_TASK_CONTINUATION",
                          "operation": "OPEN_ALLIANCE_AFTER_TASK_ROW_NAVIGATION"},
                distance=0.5,
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
            elif (status == "UNKNOWN"
                    and world.alliance.get("recommended_tech_visible") is True):
                goals.append(GoalState(
                    "ALLIANCE_DONATION", GoalStatus.READY, reward_value=240,
                    available_skills=("OPEN_ALLIANCE_RECOMMENDED_TECH_NODE",),
                    evidence={"source": "LIVE_ALLIANCE_RECOMMENDED_TECH_NODE",
                              "operation": "OPEN_NODE_TO_READ_DONATION_OPTIONS"},
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
                      "SELECT_GIANT_BEAST_TAB", "SUBMIT_GIANT_BEAST_SEARCH", "START_RALLY",
                ),
                evidence={"current": stamina, "threshold": STAMINA_FLOOR, "reused": stamina_from_store,
                          "intel_state": dict(world.intel or ((observations or {}).get('intel', {}).get('reading')
                              if not (observations or {}).get('intel', {}).get('overdue', True) else {}) or {}),
                          "idle_marches":world.idle_marches,
                            "own_rally":dict(world.rally if world.rally.get('source') == 'LIVE_MARCH_PANEL' else
                                (world.alliance or {}).get('rally') or
                                ((observations or {}).get('rally', {}).get('reading')
                                 if not (observations or {}).get('rally', {}).get('overdue', True) else {}) or {})},
                # Stamina still at or above the floor is exactly the work left to do, and
                # it is what makes a beast kill progress while a map pan does not.  At the
                # floor itself this is 1 rather than 0, which is the boundary above stated
                # as a number.
                distance=float(max(0, stamina - STAMINA_FLOOR + 1)),
            ))
        elif _optional_int((((observations or {}).get('stamina') or {}).get('reading') or {}).get('current')) is not None:
            # An expired gauge permits returning to the HUD, never spending on its old value.
            goals.append(GoalState('AVOID_STAMINA_WASTE', GoalStatus.READY,
                reward_value=100, available_skills=('BACK', 'OPEN_MAP'), distance=1.0,
                evidence={'current':None, 'requires_live_observation':True}))
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
        if (world.page is Page.ALLIANCE
                and world.alliance.get("section") == "TECHNOLOGY"
                and world.alliance.get("donation_detail_open") is True):
            # Keep the existing daily board Goal alive long enough to close the
            # completed contribution detail and return to the task board. Replace
            # any stale daily visit ticket instead of creating a parallel Goal.
            goals[:] = [goal for goal in goals if goal.goal_id != "DAILY_ACTIVITY_TARGET"]
            goals.append(GoalState(
                "DAILY_ACTIVITY_TARGET", GoalStatus.READY,
                reward_value=500.0, daily_loss=500.0,
                available_skills=("CLOSE_ALLIANCE_TECH_DONATION_DETAILS",),
                evidence={"source": "LIVE_DAILY_TASK_CONTINUATION",
                          "operation": "CLOSE_COMPLETED_DONATION_AND_RETURN_TO_TASK_BOARD"},
                distance=0.5,
            ))
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
        _append_daily_task_goals(goals, world)
        minimum = world.events.get("minimum_guarantee") if isinstance(world.events, dict) else None
        if isinstance(minimum, dict):
            missing = _optional_int(minimum.get("points_missing"))
            claimed = bool(minimum.get("all_target_rewards_claimed", False))
            left = _optional_int(minimum.get("remaining_seconds"))
            until_start = _optional_int(minimum.get("seconds_to_start"))
            complete = missing is not None and missing <= 0 and claimed
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
            elif left is not None and left > 0 and missing is not None:
                # A positive scoring-stage timer is current client evidence that this
                # occurrence is open. The event title or a saved appointment alone is not.
                status = GoalStatus.READY
            else:
                # No trustworthy open/close timer: retain the discovered goal, but do not
                # infer that it is actionable from the page title or missing countdown.
                status = GoalStatus.UNKNOWN
            event_id = str(minimum.get("event_id") or "")
            # FISHING POLICY V2 §3/§14/§15.  The fishing event must not inherit the client's
            # countdown as its urgency: an event open for two days would carry a rising
            # +1000…+10000 for its whole length and take the device from the running Role
            # Session on nearly every frame -- "go fishing now" for no reason except that the
            # event exists.  ``fishing_pressure`` replaces that deadline with one derived from
            # the bait budget: ordinary unless the counter is at cap (§3 A) or the window has
            # become shorter than the bait left to spend in it (§15).  Status, window_closed
            # and the EXPIRED/COMPLETE verdicts are untouched -- they are about the event's
            # window, not about how badly fishing wants the device.
            fishing_terms = fishing_pressure.event_goal_terms(
                event_id,
                fishing_pressure.signal_for_role(fishing_pressures, role_id),
            )
            goal_remaining = left
            goal_synergy = 500.0
            if fishing_terms["applies"] and status is GoalStatus.READY:
                goal_remaining = fishing_terms["remaining_seconds"]
                goal_synergy += float(fishing_terms["synergy_bonus"])
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
                remaining_seconds=goal_remaining, reward_value=500,
                event_synergy=goal_synergy,
                resource_cost=float(minimum.get("estimated_cost", 0)),
                available_skills=skills,
                evidence={"points_missing": missing, "claimed": claimed,
                          "window_closed": window_closed,
                          "seconds_to_start": until_start,
                          "event_id": event_id,
                          "generic_live_fallback": generic_live_fallback,
                          "client_remaining_seconds": left,
                          "fishing_pressure": (fishing_terms if fishing_terms["is_fishing"]
                                               else None)},
                distance=float(max(0, missing)) if missing is not None else 1.0,
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
        self._append_alliance_mobilization_goals(goals, world, role_id=role_id)
        self._append_known_activities(goals, calendar_snapshot=calendar_snapshot)
        self._append_fishing_goals(
            goals, role_id=role_id, fishing_pressures=fishing_pressures
        )
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
        self._append_alliance_timed_provider(goals, world, role_id=role_id)
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
    def _append_fishing_goals(
        goals: list[GoalState],
        *,
        role_id: str,
        fishing_pressures: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        """The fishing tournament's role-scoped goals (Production Sprint NEXT P3).

        Not a scheduler and not a Skill: this is the *provider* half of P3, so that fishing stops
        being invisible to the one Scheduler.  What decides whether it may act is already built --
        ``fishing_pressure`` turns the bait budget into a verdict and ``runtime._fishing_pressures``
        supplies it once per frame; this puts the result on the goal board.

        Four rules, in the operator's words::

            event active AND normal_bait > 0   -> USE_NORMAL_FISHING_BAIT READY
            normal_bait == 0                   -> WAITING_FOR_TIMER + next_action_at
            normal_bait == cap                 -> overflow_pressure 提高
            活动即将结束且 bait > 0              -> deadline pressure 持续提高

        The third and fourth are deliberately *different* mechanisms.  A full counter is a bonus
        (``event_synergy``): regeneration is being thrown away, so fishing deserves a better claim
        on the device, but the event is not closing and §3 asks that the hard-preempt be reserved
        for a closing window.  A closing window is a real ``remaining_seconds``, which
        ``deadline_pressure`` turns into the rising priority §15 wants.

        Every role's numbers come from that role's own verdict.  A role with no reading contributes
        nothing: emitting a goal at all would either invent a bait counter or borrow the other
        account's, and P3 names ``bait / points / gear / timer / progress`` as things roles must
        never share.
        """
        from . import fishing_pressure as fp

        verdict = fp.signal_for_role(fishing_pressures, role_id)
        if verdict is None:
            return
        from datetime import timedelta
        observed = _as_iso((verdict or {}).get("observed_at"))
        try:
            observed_at = datetime.fromisoformat(observed) if observed else None
            fresh = bool(observed_at and observed_at.tzinfo
                         and timedelta(0) <= datetime.now(timezone.utc) - observed_at < timedelta(minutes=10))
        except (ValueError, TypeError):
            fresh = False
        if not fresh or verdict.get("event_live_open") is not True or verdict.get("bait_current") is None:
            goals.append(GoalState(
                "OBSERVE_FISHING_STATE", GoalStatus.READY,
                available_skills=("READ_FISHING_STATE",), distance=1.0,
                evidence={"required_observation": "current role, event open, normal bait, points",
                          "only_allowed_spend": "NONE", "condition": "fresh_fishing_read"},
            ))
            return

        bait = verdict.get("bait_current")
        cap = verdict.get("bait_cap")
        pressure = str(verdict.get("pressure") or fp.UNKNOWN)
        terms = fp.event_goal_terms(fp.FISHING_EVENT_ID, verdict)
        shared: dict[str, Any] = {
            "event_id": fp.FISHING_EVENT_ID,
            "lane": "NORMAL_BAIT",
            "only_allowed_spend": "NORMAL_BAIT",
            "bait_pressure": pressure,
            "bait_current": bait,
            "bait_cap": cap,
            "role_key": verdict.get("role_key"),
            "bait_reason": verdict.get("reason"),
            "client_remaining_seconds": None,
        }

        # ---- 1. spend one normal bait (§1/§2/§15) -------------------------------------
        if bait is None:
            # §2 requires the counter to be read; an unread counter is not "no bait".
            goals.append(GoalState(
                "USE_NORMAL_FISHING_BAIT", GoalStatus.UNKNOWN,
                available_skills=(),
                evidence={**shared, "required_observation": "normal_bait_current / bait_cap",
                          "note": "the current role's bait counter has not been read; "
                                  "an unread counter cannot justify spending or waiting"},
                distance=1.0,
            ))
        elif int(bait) <= 0:
            next_at = _as_iso(verdict.get("next_bait_at"))
            goals.append(GoalState(
                "USE_NORMAL_FISHING_BAIT", GoalStatus.BLOCKED,
                available_skills=(),
                retry_after=next_at,
                evidence={**shared, "condition": "timer", "next_action_at": next_at,
                          "note": "no normal bait left; wait for the counter, do not switch "
                                  "roles for it (§3)"},
                distance=1.0,
            ))
        else:
            endgame = verdict.get("endgame") if isinstance(verdict.get("endgame"), Mapping) else {}
            # §15's deadline and P3's overflow pressure are two different mechanisms and stay
            # distinguishable on the record: one is a closing window, the other a full counter.
            overflow_bonus = float(terms.get("synergy_bonus") or 0.0)
            goals.append(GoalState(
                "USE_NORMAL_FISHING_BAIT", GoalStatus.READY,
                # The registered entry hands control to the existing bounded session.
                available_skills=(FISHING_LANE_SKILL,),
                remaining_seconds=terms.get("remaining_seconds"),
                event_synergy=overflow_bonus,
                evidence={
                    **shared,
                    # Why the goal carries what it carries.  Named ``terms_reason`` rather than
                    # "deadline reason" because for a full counter it explains a *bonus*: the two
                    # mechanisms share one field and must stay distinguishable on the record.
                    "terms_reason": terms.get("reason") if terms.get("applies") else None,
                    "overflow_pressure": overflow_bonus,
                    "endgame": endgame or None,
                    "required_skills": [FISHING_LANE_SKILL],
                    "note": "normal bait available; batches inside the current Role Session "
                            "(§P6), it does not preempt one",
                },
                distance=float(int(bait)),
            ))

        # ---- 2. the three claims: free, daily, collection ------------------------------
        for goal_id in ("CLAIM_FISHING_FREE_REWARD",
                        "CLAIM_FISHING_DAILY_REWARD",
                        "CLAIM_FISHING_COLLECTION_REWARD"):
            goals.append(GoalState(
                goal_id, GoalStatus.UNKNOWN,
                available_skills=(),
                evidence={**shared,
                          "required_observation": FISHING_REQUIRED_OBSERVATIONS[goal_id],
                          "note": "claim state is read off the fishing page; it is not inferred "
                                  "from the bait counter"},
                distance=1.0,
            ))

        # ---- 3. gear, free event currency only (§5/P11) --------------------------------
        goals.append(GoalState(
            "UPGRADE_FISHING_KIT", GoalStatus.UNKNOWN,
            available_skills=(),
            evidence={**shared,
                      "levels": {"line": verdict.get("line_level"),
                                 "hook": verdict.get("hook_level"),
                                 "sinker": verdict.get("sinker_level")},
                      "allowed_spend": "free event-internal currency only",
                      "forbidden_spend": ["gems", "real_money", "treasure_tickets", "special_bait"],
                      "required_observation": FISHING_REQUIRED_OBSERVATIONS["UPGRADE_FISHING_KIT"],
                      "note": "§P11: read level, cost and owned currency LIVE before upgrading, "
                              "and judge the result by points_per_normal_bait"},
            distance=1.0,
        ))

    @staticmethod
    def _append_alliance_mobilization_goals(
        goals: list[GoalState], world: WorldState, *, role_id: str,
    ) -> None:
        """Project explicitly observed accepted Mobilization tasks into the shared Goal pool.

        This adapter intentionally consumes only a current-client reading that is both
        recognized and tagged with the currently confirmed role. It does not infer an
        activity from a red dot or a registry prior, and it reuses ordinary production
        Skills for execution. The event reader may add this mapping when it can identify
        task rows; until then the existing prepared-only event record remains UNKNOWN.
        """
        events = world.events if isinstance(world.events, Mapping) else {}
        reading = events.get("alliance_mobilization")
        if not isinstance(reading, Mapping) or reading.get("recognized") is not True:
            return
        observed_role_id = str(reading.get("role_id") or "").strip()
        if not role_id or not observed_role_id or observed_role_id != str(role_id):
            return
        if str(reading.get("status") or "").upper() not in {"OPEN", "ACTIVE"}:
            return
        tasks = reading.get("tasks")
        if not isinstance(tasks, (list, tuple)):
            return

        task_specs = {
            "TROOP_TRAINING_120K": (
                "ALLIANCE_MOBILIZATION_TROOP_TRAINING_120K", ("TRAIN_TROOPS",), 1200.0,
            ),
            "ICEFIELD_BEAST": (
                "ALLIANCE_MOBILIZATION_ICEFIELD_BEAST", ("START_RALLY", "JOIN_RALLY"), 1000.0,
            ),
            "LARGE_GATHER": (
                "ALLIANCE_MOBILIZATION_LARGE_GATHER", ("GATHER_RESOURCE",), 800.0,
            ),
            "BEAST": (
                "ALLIANCE_MOBILIZATION_BEAST", ("BEAST_HUNT",), 600.0,
            ),
        }
        from .skills import v2_registry

        registry = v2_registry()
        selected_tasks: dict[str, Mapping[str, Any]] = {}
        for task in tasks:
            if not isinstance(task, Mapping):
                continue
            task_type = str(task.get("task_type") or "").strip().upper()
            spec = task_specs.get(task_type)
            if spec is None:
                continue
            goal_id, proposed_skills, priority = spec
            existing = selected_tasks.get(goal_id)
            accepted = (task.get("accepted") is True
                        or str(task.get("status") or "").upper() in {"ACCEPTED", "IN_PROGRESS"})
            existing_accepted = bool(existing) and (
                existing.get("accepted") is True
                or str(existing.get("status") or "").upper() in {"ACCEPTED", "IN_PROGRESS"}
            )
            if existing is None or (accepted and not existing_accepted):
                selected_tasks[goal_id] = task

        for goal_id, task in selected_tasks.items():
            task_type = str(task.get("task_type") or "").strip().upper()
            _goal_id, proposed_skills, priority = task_specs[task_type]
            task_id = str(task.get("task_id") or "").strip()
            if not task_id:
                continue
            task_status = str(task.get("status") or "").upper()
            accepted = task.get("accepted") is True or task_status in {"ACCEPTED", "IN_PROGRESS"}
            skills = tuple(skill_id for skill_id in proposed_skills
                           if registry.get(skill_id) is not None) if accepted else ()
            progress = task.get("progress")
            target = task.get("target")
            try:
                progress_value = max(0.0, float(progress)) if progress is not None else None
                target_value = max(0.0, float(target)) if target is not None else None
            except (TypeError, ValueError):
                progress_value = target_value = None
            complete = task.get("completed") is True or (
                progress_value is not None and target_value is not None
                and target_value > 0 and progress_value >= target_value
            )
            status = (GoalStatus.COMPLETE if complete else
                      GoalStatus.READY if accepted and skills else
                      GoalStatus.UNKNOWN)
            goals.append(GoalState(
                goal_id,
                status,
                completion=1.0 if complete else 0.0,
                remaining_seconds=_optional_int(reading.get("remaining_seconds")),
                event_synergy=priority if accepted and not complete else 0.0,
                available_skills=() if complete else skills,
                evidence={
                    "event_id": "ALLIANCE_MOBILIZATION",
                    "role_id": observed_role_id,
                    "source": str(reading.get("source") or "LIVE_CLIENT"),
                    "task_id": task_id,
                    "task_type": task_type,
                    "task_status": task_status or ("ACCEPTED" if accepted else "UNKNOWN"),
                    "accepted": accepted,
                    "progress": progress_value,
                    "target": target_value,
                    "shared_credit_tags": ["ALLIANCE_MOBILIZATION"],
                    "execution_uses_existing_skills": list(skills),
                    **({'rally_target': 'POLAR_TERROR'} if task_type == 'ICEFIELD_BEAST' else {}),
                },
                distance=(0.0 if complete else
                          max(0.0, target_value - progress_value)
                          if target_value is not None and progress_value is not None else 1.0),
            ))

    @staticmethod
    def _append_alliance_timed_provider(goals: list[GoalState], world: WorldState, *, role_id: str) -> None:
        """Project current alliance event observations onto their existing executable goals.

        This aggregate is a provider record, never a second execution instance. Bear and
        calendar goals retain ownership of their skills, device lease and completion.
        """
        bear = world.events.get("bear") if isinstance(world.events, Mapping) else None
        linked = [goal for goal in goals if goal.goal_id in {
            "PARTICIPATE_BEAR", "DISCOVER_BEAR_RALLY_LIST"}]
        state = "REGISTERED"
        status = GoalStatus.UNKNOWN
        if isinstance(bear, Mapping):
            active = bear.get("status") == "ACTIVE" or (_optional_int(bear.get("remaining_seconds")) or 0) > 0
            if active:
                state = "OPEN"
                if bear.get("auto_join_enabled") is True or bear.get("joinable_rally_count", 0):
                    state = "READY"
            elif any(goal.status is GoalStatus.SCHEDULED_NOT_OPEN for goal in linked):
                state, status = "WAITING_WINDOW", GoalStatus.SCHEDULED_NOT_OPEN
        goals.append(GoalState("ALLIANCE_TIMED_EVENTS", status, available_skills=(),
            evidence={"provider_state": state, "registration_state": "REGISTERED",
                      "role_id": role_id, "source": "CURRENT_WORLDSTATE_ALLIANCE_EVENTS",
                      "linked_goal_ids": [goal.goal_id for goal in linked],
                      "execution_owner": "EXISTING_EVENT_GOALS",
                      "required_observation": None if bear else "current alliance event identity and window",
                      "condition": "waiting_window" if state == "WAITING_WINDOW" else "provider_projection"},
            distance=0.0 if linked else 1.0))

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
        )
        from .skills import v2_registry
        registry = v2_registry()
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
                    **({"missing_registry_skills": [name for name in (
                        "OPEN_ARENA", "READ_FREE_ATTEMPTS", "SELECT_ARENA_OPPONENT",
                        "START_ARENA", "VERIFY_ARENA_RESULT")
                        if registry.get(name) is None],
                        "missing_page_identity": "ARENA" not in Page.__members__}
                       if goal_id == "USE_FREE_ARENA_ATTEMPTS" else {}),
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
                    # When this row is the COMPLETE one, the scan is finished and the goal
                    # answers by leaving.  That answer was unrecordable, and the absence was
                    # measured 2026-10-03 on live revision 58dccc8b over 174 steps:
                    #
                    #   EVENT frames split exactly 19/19.  The 19 carrying
                    #   ``regular_events_hub`` keep the goal on the board and run
                    #   OPEN_EVENT_CALENDAR_TAB.  The 19 without it all read entries=5 with
                    #   details_observed=5 -- this branch, correctly saying the scan is done --
                    #   after which the goal vanished, because COMPLETE carries no skills and
                    #   COMPLETE is in NOT_ACTIONABLE, so ``priority`` is ``-inf`` and
                    #   ``goal_utility.rank`` drops the row.
                    #
                    #   That produced a self-erasing cycle instead of a missing feature:
                    #     HOME --(OPEN_EVENT_CALENDAR_FROM_HOME, gp=True)--> EVENT
                    #          --(OPEN_EVENT_CALENDAR_TAB)--> CALENDAR_GRID: hub gone, goal gone
                    #          --(BACK, "leaves_unrelated_event_session")--> HOME, again.
                    #   19 transitions each way; every navigation step gp=True and every
                    #   return step worthless.  Each hop was individually correct, which is
                    #   why no FAIL ever appeared in the ledger and this ran unnoticed.
                    #
                    #   The row itself was always correct -- COMPLETE with no price and no
                    #   skills is exactly right, and pricing it would reopen the panel AUTO
                    #   just closed.  What was missing is a way to say "asked and answered",
                    #   which is the same gap ``DISCOVER_QUICK_PANEL_TASKS`` had and the same
                    #   fix: name the precondition that stopped holding, so "answered" is
                    #   distinguishable from "never asked" without replaying the frame.
                    "served_by": (None if status is GoalStatus.READY
                                  else "every_visible_entry_already_observed"),
                },
                distance=0.0,
            ))
            return
        hub = events.get("regular_events_hub")
        if world.page is Page.EVENT and isinstance(hub, Mapping) and hub.get("recognized") is True:
            skill = ("OPEN_EVENT_CALENDAR_TAB" if hub.get("calendar_tab_visible") is True
                     else "SCROLL_REGULAR_EVENT_TABS" if hub.get("scroll_to_start_norm") else None)
            goals.append(GoalState(
                "DISCOVER_EVENT_CALENDAR", GoalStatus.READY if skill else GoalStatus.UNKNOWN,
                available_skills=(skill,) if skill else (),
                reward_value=300, daily_loss=450, development_value=250,
                evidence={"role_id": scoped_role_id, "scope": scope,
                          "operation": "CONTINUE_FROM_CURRENT_REGULAR_EVENT_HUB",
                          "navigation_progress_only": True,
                          "required_observation": None if skill else "current_activity_tab_container"},
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
                available_skills=_ACTIVITY_OBSERVATION_SKILLS,
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
                    # The row already says it is waiting for a live reading; this is the field the
                    # observation ticket reads, and without it "waiting" priced at -inf and nothing
                    # was ever scheduled to go and look.
                    "required_observation": (
                        "this event's own page once opened: whether its window is open and what its "
                        "live participation conditions are"
                    ),
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
                available_skills=_ACTIVITY_OBSERVATION_SKILLS,
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
                    # Same declaration as the registered rows, and for the same measured reason: the
                    # calendar preview cannot say whether the window is open or what participating
                    # costs, and those are the facts the ticket exists to go and read.
                    "required_observation": (
                        "this event's own page once opened from the calendar row: whether its window "
                        "is open, what participating in it costs, and its current points"
                    ),
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
        countdown = _queue_countdown_text(state) if busy else None
        goals.append(GoalState(goal_id, GoalStatus.BLOCKED if busy else GoalStatus.READY,
                               completion=1.0 if busy else 0.0, development_value=value,
                               available_skills=skills,
                               retry_after=countdown,
                               evidence={"queue_busy": busy,
                                         "timer": countdown,
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
                    retry_after=_queue_countdown_text(state),
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
        page_camp = TROOP_TO_CAMP.get(str(training.get("troop_type") or "").upper())
        if page_camp is None:
            page_camp = next(
                (key for key, label in CAMP_LABELS.items()
                 if label == str(training.get("camp_open_label") or "")),
                None,
            )
        training_page_continuation = (
            world.page is Page.TRAINING
            and page_camp == camp
            and (
                (
                    training.get("queue_available") is True
                    and training.get("trainable") is True
                )
                or (
                    training.get("claimable") is True
                    and bool(training.get("claim_button_norm"))
                )
            )
        )
        focused = (
            world.page is Page.HOME
            and training.get("navigation") == "PANEL_CAMP_FOCUSED"
            and isinstance(training.get("camp_focus_tap_norm"), (tuple, list))
            and len(training.get("camp_focus_tap_norm")) == 2
        )
        reward_feedback = world.page is Page.POPUP and world.popup == "GENERIC_REWARD"
        if not (focused or reward_feedback or training_page_continuation):
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
                "intermediate_state": (
                    "TRAINING_PAGE_QUEUE_ACTIONABLE" if training_page_continuation
                    else "PANEL_CAMP_FOCUSED" if focused
                    else "TRAINING_REWARD_FEEDBACK"
                ),
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


#: The values ``_observation_meter`` can return.  A rank, not a score: it says *how far
#: along* an activity is towards having been read, and it deliberately cannot be mistaken
#: for a magnitude.
_OBSERVATION_METER_RANKS = frozenset({0.0, 0.5, 1.0})

#: Which meter each goal was last measured by, written by ``runtime._remember_goal_meters``
#: next to the number itself.  Value membership cannot do this job -- a navigation distance
#: of 1.0 is inside the rank set -- so the scale is recorded as a kind and compared as one.
_METER_KINDS: dict[str, str] = {}


def meter_kind(goal: GoalState) -> str:
    """``"observation"`` or ``"distance"``: which number this goal is measured by."""
    return "observation" if _observation_meter(goal) is not None else "distance"


def _observation_meter(goal: GoalState) -> float | None:
    """A second, evidence-derived meter for goals whose ``distance`` is a constant.

    ``distance`` is a navigation cost, and for a goal the system cannot act on yet the
    honest value is a constant -- ``_append_scheduled_activities`` writes a literal
    ``distance=1.0`` (``goal_library.py:2017`` and ``:2053``).  A constant cannot report
    progress: ``1.0 < 1.0`` is False on every step, forever.

    Measured 2026-10-02 over the whole production ledger: eight goal families have ever
    reported ``goal_progress == True`` (``DISCOVER_EVENT_CALENDAR`` 1366 times among them)
    and every ``SCHEDULED_*`` goal has reported False or None, 50 out of 50 on the new
    revisions.  The metric is not broken; this one family cannot feed it.  That matters
    beyond the number, because ``False`` increments ``no_progress_streak``
    (``runtime.py:9734``) and the streak feeds the fairness bonus -- so a goal that is
    structurally unable to report progress is demoted for something it did not do.

    What it *can* be compared on is whether the client has been asked and answered.  Both
    halves of that are facts the goal layer already carries, and both are produced by the
    current-frame readers rather than by anything stored:

    * ``evidence["calendar_observation"]`` -- the activity appeared on a calendar the client
      actually drew.  ``None`` until then, which is the honest "not seen yet";
    * ``evidence["availability_state"]`` -- ``AWAITING_LIVE_CLIENT_READING`` until a live
      reading supplies live conditions.

    Either one appearing is real progress, and neither can appear without a frame that
    proves it.  The value returned is a **rank**, not a score: 0.0 for "advertised but not
    read", 0.5 for "read on the calendar", 1.0 for "a live reading supplied its
    conditions".  A rank is enough for ``<`` to mean something and cannot be mistaken for a
    magnitude the system invented.

    ``None`` for every other goal, which leaves the ``distance`` comparison exactly as it
    was -- this adds a measurement where there was none, and changes nothing where one
    already worked.
    """
    evidence = getattr(goal, "evidence", None)
    if not isinstance(evidence, Mapping):
        return None
    if not str(goal.goal_id).startswith("SCHEDULED_"):
        return None
    if str(evidence.get("availability_state") or "") not in {
            "", "AWAITING_LIVE_CLIENT_READING", "CALENDAR_PREVIEW_ONLY",
    }:
        # A live reading has already supplied this activity's own conditions, which is the
        # furthest of the three states.  Named explicitly rather than by "not the waiting
        # value" so that a future state has to be classified instead of inherited.
        return 1.0
    if evidence.get("calendar_observation") is not None:
        return 0.5
    return 0.0


def _meter_for(goal: GoalState) -> float | None:
    """The one number this goal is measured by, or ``None`` for a goal with no meter.

    Both the writer (``runtime._remember_goal_meters``) and the comparator
    (``progress_moved``) go through here.  They have to: storing ``goal.distance`` while
    comparing ``_observation_meter`` would make "progress" mean "the scale changed", which
    is worse than having no measurement at all.
    """
    reading = _observation_meter(goal)
    return reading if reading is not None else float(getattr(goal, "distance", 1.0))


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

    **The meter is chosen per goal, and a constant ``distance`` is not a measurement.**
    ``_observation_meter`` supplies a second reading for the one family whose ``distance``
    is a hard-coded constant; see its docstring for the measured reason.  A goal with a
    working ``distance`` keeps using it unchanged, and a goal with neither is still
    ``None`` -- unobserved, not stalled.
    """
    now = next((goal for goal in after if goal.goal_id == goal_id), None)
    if now is None:
        return None
    previous = observed.get(goal_id)
    if previous is None:
        return None
    reading = _observation_meter(now)
    if reading is not None:
        # Compare like with like.  The remembered value has to be the same kind of number,
        # or "progress" would be an artefact of switching scales mid-run.
        #
        # The first attempt at this guard was to keep the ranks in a set and test
        # membership, and that does not work: a navigation distance of 1.0 is *also* in the
        # rank set, so a run that read these goals before this meter existed remembered a
        # literal 1.0 and ``0.5 < 1.0`` called every one of them progress on its first step.
        # Verified by running it, not by reading it -- the guard has to distinguish the two
        # scales by **kind**, not by value, and the writer is the only thing that knows.
        #
        # So the writer records the scale alongside the number.  A remembered value with no
        # matching kind was written by the other meter and the honest answer is ``None`` --
        # not measured, which the caller already documents as distinct from "no progress".
        kind = _METER_KINDS.get(goal_id)
        if kind != "observation":
            return None
        # The two meters run in opposite directions, which is why one shared comparison
        # operator cannot serve both.  ``distance`` is a remaining cost -- smaller is closer,
        # so ``<`` is progress.  The observation rank is a depth of reading -- larger means
        # more has been read, so ``>`` is progress.  Getting this backwards is not a subtle
        # slip: it reports a goal being read for the first time as "no progress", which is
        # the exact failure this meter exists to remove, and it was caught by running the
        # two states rather than by reading the comparison.
        return reading > previous
    return now.distance < previous



def newly_completed_goal_ids(
    before: Iterable[GoalState],
    after: Iterable[GoalState],
    attached_goal_ids: Iterable[str],
) -> tuple[str, ...]:
    """Return only attached Goals whose observed status changed to COMPLETE.

    A COMPLETE Goal can remain visible in later WorldState observations. Counting that
    status on every subsequent action would turn a persistent state into repeated
    completion events. Require a known, non-UNKNOWN pre-action row and a post-action
    COMPLETE row so production telemetry records only a transition this step can support.
    """
    attached = {str(item).strip() for item in attached_goal_ids if str(item).strip()}
    if not attached:
        return ()

    def status_of(goal: GoalState) -> str:
        value = getattr(goal, "status", "")
        return str(getattr(value, "value", value)).upper()

    before_status = {
        str(getattr(goal, "goal_id", "")): status_of(goal)
        for goal in before
        if str(getattr(goal, "goal_id", ""))
    }
    completed: list[str] = []
    for goal in after:
        goal_id = str(getattr(goal, "goal_id", ""))
        if goal_id not in attached or status_of(goal) != GoalStatus.COMPLETE.value:
            continue
        prior = before_status.get(goal_id)
        if prior and prior not in {GoalStatus.COMPLETE.value, GoalStatus.UNKNOWN.value}:
            completed.append(goal_id)
    return tuple(dict.fromkeys(completed))


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

    def write(self, world: WorldState, goals: Iterable[GoalState], *, role_id: str = "") -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        current = {
            "observed_at": world.timestamp,
            "written_at": datetime.now(timezone.utc).isoformat(),
            "page": world.page.value,
            "confidence": world.confidence,
            "goals": [self._serialize(goal) for goal in goals],
        }
        try:
            existing = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
        role_snapshots = existing.get("roles") if isinstance(existing, dict) else {}
        if not isinstance(role_snapshots, dict):
            role_snapshots = {}
        role_snapshots = dict(role_snapshots)
        if role_id:
            role_snapshots[str(role_id)] = dict(current)
        payload = {**current, "active_role_id": str(role_id or ""), "roles": role_snapshots}
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def read_roles(self) -> dict[str, dict[str, Any]]:
        """Read per-role logical Goal boards without merging account state."""
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        rows = payload.get("roles") if isinstance(payload, dict) else None
        if not isinstance(rows, dict):
            return {}
        return {str(role_id): dict(value) for role_id, value in rows.items()
                if role_id and isinstance(value, dict)}

    @staticmethod
    def _serialize(goal: GoalState) -> dict[str, Any]:
        value = asdict(goal)
        value["status"] = goal.status.value
        value["priority"] = None if goal.priority == float("-inf") else goal.priority
        return value


_DAILY_ROW_GOAL_PREFIXES: tuple[tuple[str, str], ...] = (
    ("DAILY_ALLIANCE_CONTRIBUTE", "ALLIANCE_DONATION"),
    ("DAILY_INTEL_CLUES", "CLEAR_INTEL"),
    ("DAILY_TRAIN_SHIELD", "SHIELD_CAMP_TRAINING"),
    ("DAILY_TRAIN_LANCER", "LANCER_CAMP_TRAINING"),
    ("DAILY_TRAIN_MARKSMAN", "MARKSMAN_CAMP_TRAINING"),
    ("DAILY_GATHER_", "KEEP_MARCHES_PRODUCTIVE"),
    ("DAILY_RESEARCH", "KEEP_RESEARCH_PRODUCTIVE"),
    ("DAILY_BUILD", "KEEP_BUILDING_PRODUCTIVE"),
)


def _append_daily_task_goals(goals: list[GoalState], world: WorldState) -> None:
    """Turn one live, incomplete daily row into its existing task Goal.

    The task board's 前往 control is the current-frame bridge from a row to its feature.
    OCR could read the rows while the scheduler had no corresponding Goal, so AUTO returned
    RUNNABLE=0 on an actionable board. Reuse feature Goal identities so task-board, red-dot,
    and live-state discoveries converge rather than creating parallel tasks.
    """
    if world.page is not Page.DAILY:
        return
    rows = [
        row for row in (world.daily or {}).get("tasks", ())
        if isinstance(row, Mapping)
        and str(row.get("state") or "").upper() == "AVAILABLE"
        and isinstance(row.get("action_button"), Mapping)
        and row.get("action_button", {}).get("semantic_id") == "BTN_DAILY_TASK_GO"
    ]
    if not rows:
        return

    # Prefer the most progressed actionable task and keep a stable current-frame order
    # for ties. This makes the same near-finished task win across repeated reads.
    rows.sort(key=lambda row: (
        -float((row.get("progress") or {}).get("current", 0) or 0)
        / max(1.0, float((row.get("progress") or {}).get("target", 0) or 0)),
        int(row.get("row_order_on_frame", 0) or 0),
    ))
    by_goal = {goal.goal_id: index for index, goal in enumerate(goals)}
    for row in rows:
        task_id = str(row.get("task_id") or "")
        goal_id = next((goal for prefix, goal in _DAILY_ROW_GOAL_PREFIXES if task_id.startswith(prefix)), "")
        if not goal_id:
            continue
        progress = row.get("progress") if isinstance(row.get("progress"), Mapping) else {}
        current = int(progress.get("current", 0) or 0)
        target = int(progress.get("target", 0) or 0)
        if target > 0 and current >= target:
            continue
        evidence = {"daily_task_id": task_id, "daily_task_row": dict(row),
                    "source": "LIVE_DAILY_TASK_ROW"}
        existing_index = by_goal.get(goal_id)
        if existing_index is not None:
            previous = goals[existing_index]
            goals[existing_index] = GoalState(
                goal_id=previous.goal_id,
                status=GoalStatus.READY,
                completion=previous.completion,
                remaining_seconds=previous.remaining_seconds,
                reward_value=max(previous.reward_value, 500.0),
                daily_loss=max(previous.daily_loss, 500.0),
                event_synergy=previous.event_synergy,
                development_value=previous.development_value,
                resource_cost=previous.resource_cost,
                risk=previous.risk,
                available_skills=tuple(dict.fromkeys(("FOLLOW_DAILY_TASK", *previous.available_skills))),
                retry_after=None,
                evidence={**previous.evidence, **evidence},
                distance=float(max(0, target - current)) if target else max(previous.distance, 1.0),
            )
        else:
            goals.append(GoalState(
                goal_id=goal_id,
                status=GoalStatus.READY,
                reward_value=500.0,
                daily_loss=500.0,
                available_skills=("FOLLOW_DAILY_TASK",),
                evidence=evidence,
                distance=float(max(0, target - current)) if target else 1.0,
            ))
            by_goal[goal_id] = len(goals) - 1
        # One selected row per discovery frame avoids multiple simultaneous task instances.
        break
