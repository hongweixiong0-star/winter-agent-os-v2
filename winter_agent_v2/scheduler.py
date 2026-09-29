from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from .global_scheduler_state import GlobalSchedulerStateStore

from .brain import RuleBrain
from .executor import Executor
from .models import Decision, ExecutionResult, LatencyClass, WorldState
from .skills import SkillRegistry
from .event_goal import event_priority_modifier
from .operations_policy import operational_priority
from .goal_library import GoalLibrary
from .candidate_policy import CandidateAttemptPool
from . import entry_badges
from . import event_schedule

#: The goal whose skills a time-based readiness boost may promote.
#:
#: Named once, and the *skills* are read from the goal library rather than listed here, so the
#: two cannot drift: a skill added to ``PARTICIPATE_BEAR`` is promoted automatically, and one
#: removed stops being promoted.
BEAR_GOAL_ID = "PARTICIPATE_BEAR"

#: The two page entries a task may only be entered through because its own badge said so
#: (operator directive 2026-09-23 §六: 增加最后一道动作出口保护).
#:
#: ``Scheduler.tick`` is the one place every decision passes through on its way to the executor --
#: brain routes, page-driven branches, and anything a future caller adds -- so a check here cannot be
#: bypassed by an older path that still believes a mail sweep is due.  Measured before it existed: a
#: ``MAIL_ROUTINE`` goal opened the gifts page 9 times in the production corpus, which is exactly the
#: kind of cross-path entry this backstop is for.
#:
#: The check is a *refusal*, not a correction: it does not rewrite the decision, it declines to run
#: it and settles the step as "nothing new here", so the cycle goes to another goal.  And it refuses
#: on UNKNOWN as well as ABSENT -- §四: an unreadable entry is not permission to open a page in order
#: to find out.
ENTRY_GATED_SKILLS: dict[str, str] = {
    "OPEN_MAIL": "MAIL_ROUTINE",
    "OPEN_ALLIANCE_GIFTS": "ALLIANCE_ROUTINE",
    "OPEN_BEAR_RALLY_LIST": "DISCOVER_BEAR_RALLY_LIST",
}


@dataclass(frozen=True)
class TickResult:
    decision: Decision
    execution: ExecutionResult | None


@dataclass(frozen=True)
class TaskSelection:
    index: int | None
    decision: Decision
    skipped: tuple[Decision, ...]
    role_id: str = ""
    selection_reason: str = ""
    next_wakeup: str | None = None
    goal_id: str = ""
    score: float | None = None
    credited_goal_ids: tuple[str, ...] = ()
    role_statuses: tuple[dict[str, Any], ...] = ()
    goal_metrics: tuple[GoalScheduleInfo, ...] = ()
    requires_role_refresh: bool = False
    requested_skill: str = ""
    candidate_explanations: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class GoalScheduleInfo:
    """Comparable scheduling facts for one role-scoped Goal.

    GoalLibrary remains the source of truth.  This is only the view the one Scheduler
    uses to compare work across roles; it does not create another queue or lifecycle.
    """

    goal_id: str
    role_id: str
    priority: float
    deadline: str | None
    ready_now: bool
    blocked: bool
    wait_until: str | None
    estimated_duration: float | None
    resource_cost: float
    risk: float
    progress: float
    completion: float
    switch_cost: float
    expected_value: float

@dataclass(frozen=True)
class RoleObservation:
    """One role's independently observed state offered to the global Scheduler.

    ``confirmed_role_id`` must come from the current client observation. Cached Goal
    summaries can guide when to wake, but a stale or mismatched live state can never
    authorize an action for another account.
    """

    role_id: str
    confirmed_role_id: str
    world: WorldState | None
    observed_at: str | datetime | None = None
    decision: Decision | None = None
    goals: tuple[Any, ...] = ()
    next_action_at: str | datetime | None = None
    runnable_count: int | None = None
    blocked_count: int | None = None
    switch_cost: float = 0.0
    failure_streak: int = 0
    switch_blocked_until: str | datetime | None = None
    needs_initial_refresh: bool = False

    def freshness(self, *, now: datetime, max_age_seconds: float) -> tuple[bool, str]:
        if not self.role_id or self.confirmed_role_id != self.role_id:
            return False, "role_identity_not_confirmed_for_snapshot"
        if self.world is None:
            return False, "role_has_no_live_world_state"
        stamp = _as_datetime(self.observed_at) or _as_datetime(self.world.timestamp)
        if stamp is None:
            return False, "role_observation_timestamp_missing"
        age = (now - stamp).total_seconds()
        if age < -5.0 or age > max_age_seconds:
            return False, f"role_observation_stale:{max(0.0, age):.1f}s"
        return True, "fresh_role_observation"


@dataclass
class ActiveRoleLiveState:
    """The live UI cache for the one account currently on the device.

    Persistent Goal summaries belong to their role.  Frame-derived data does not survive
    an account switch: every listed field is cleared until the new account is observed.
    """

    active_role_id: str = ""
    live: dict[str, Any] = field(default_factory=dict)
    invalidated_fields: tuple[str, ...] = (
        "page", "frame", "ocr", "march_rows", "rally_rows", "formation",
        "queue_state", "event_state", "resource_state", "auto_join_state",
    )

    def switch_to(self, role_id: str) -> tuple[str, ...]:
        target = str(role_id or "").strip()
        if not target:
            raise ValueError("cannot activate an unconfirmed role")
        changed = target != self.active_role_id
        self.active_role_id = target
        if changed:
            self.live = {key: None for key in self.invalidated_fields}
        return self.invalidated_fields if changed else ()

    def observe(self, confirmed_role_id: str, values: dict[str, Any]) -> None:
        if not self.active_role_id or confirmed_role_id != self.active_role_id:
            self.live = {key: None for key in self.invalidated_fields}
            raise ValueError("live observation role does not match active role")
        self.live = {key: None for key in self.invalidated_fields}
        self.live.update(values)

def _as_datetime(value: str | datetime | None) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

def _goal_schedule_info(goal: Any, role_id: str, *, now: datetime,
                        switch_cost: float = 0.0) -> GoalScheduleInfo:
    remaining = getattr(goal, "remaining_seconds", None)
    deadline = (now + timedelta(seconds=max(0, int(remaining)))) if remaining is not None else None
    status = str(getattr(getattr(goal, "status", ""), "value", getattr(goal, "status", ""))).upper()
    wait_until = getattr(goal, "retry_after", None)
    evidence = getattr(goal, "evidence", {})
    if isinstance(evidence, dict):
        wait_until = wait_until or evidence.get("next_action_at") or evidence.get("wait_until")
    expected = sum(float(getattr(goal, name, 0.0) or 0.0) for name in (
        "reward_value", "daily_loss", "event_synergy", "development_value",
    ))
    completion = float(getattr(goal, "completion", 0.0) or 0.0)
    progress = completion
    if isinstance(evidence, dict):
        explicit_progress = evidence.get("progress")
        if isinstance(explicit_progress, (int, float)) and not isinstance(explicit_progress, bool):
            progress = float(explicit_progress)
        elif isinstance(explicit_progress, dict):
            current = explicit_progress.get("current")
            target = explicit_progress.get("target")
            if isinstance(current, (int, float)) and isinstance(target, (int, float)) and target > 0:
                progress = float(current) / float(target)
    return GoalScheduleInfo(
        goal_id=str(getattr(goal, "goal_id", "")),
        role_id=role_id,
        priority=float(getattr(goal, "priority", 0.0) or 0.0),
        deadline=deadline.isoformat() if deadline else None,
        ready_now=status in {"READY", "DISCOVERED", "RUNNABLE"},
        blocked=status in {"BLOCKED", "UNKNOWN", "DEFERRED", "WAITING_GAME_CONDITION"},
        wait_until=str(wait_until) if wait_until else None,
        estimated_duration=(float(evidence["estimated_duration_seconds"])
                            if isinstance(evidence, dict)
                            and evidence.get("estimated_duration_seconds") is not None else None),
        resource_cost=float(getattr(goal, "resource_cost", 0.0) or 0.0),
        risk=float(getattr(goal, "risk", 0.0) or 0.0),
        progress=max(0.0, min(1.0, progress)),
        completion=completion,
        switch_cost=max(0.0, float(switch_cost or 0.0)),
        expected_value=expected,
    )




class Scheduler:
    """The single V2 scheduler."""

    def __init__(self, brain: RuleBrain, registry: SkillRegistry, executor: Executor,
                 candidate_pool: CandidateAttemptPool | None = None,
                 global_state_store: GlobalSchedulerStateStore | None = None) -> None:
        self.brain = brain
        self.registry = registry
        self.executor = executor
        self.goals = GoalLibrary()
        self.candidate_pool = candidate_pool
        self.global_state_store = global_state_store
        self._role_brains: dict[str, RuleBrain] = {}
        #: The per-role timed-event schedule, loaded once.  ``None`` means "not loaded yet";
        #: a run is one process, so loading on first use is both correct and free.
        self._schedule: dict[str, event_schedule.RoleSchedule] | None = None
        self._announced_readiness: tuple[str, str] | None = None

    # ------------------------------------------------------------------ readiness
    #
    # Task book §五: 巨熊唤醒不得依赖下一次普通 AUTO 周期、普通任务优先级评分或人工再次发送指令。
    #
    # Nothing here is a second scheduler and nothing here runs on a clock thread.  Each AUTO
    # cycle already asks this Scheduler to rank goals; the only thing that was missing is that
    # the ranking had **no input that survives without a frame**.  ``_deadline_active`` reads the
    # bear out of the picture, so it can only fire once the event is already on screen -- by
    # which time the preparation window the book describes (T-30/15/5/1) has been missed.
    #
    # So this adds one term to the existing sum: when a role's *reserved* start says we are
    # inside the readiness ladder, the bear goal's skills get a dominant bonus.  The clock is
    # the input; the Scheduler is still the only thing that decides.
    #
    # What it deliberately does NOT do is guess a time.  With no reservation read, every role's
    # phase is IDLE and the bonus is 0.0 -- the runtime behaves exactly as before, which is the
    # right behaviour for a project that has never observed a bear start minute.

    def schedule(self) -> dict[str, event_schedule.RoleSchedule]:
        if self._schedule is None:
            self._schedule = event_schedule.load()
        return self._schedule

    def reload_schedule(self) -> dict[str, event_schedule.RoleSchedule]:
        """Re-read the file.  For the panel/CLI to call after writing a reservation."""
        self._schedule = event_schedule.load()
        return self._schedule

    def readiness(self, now=None) -> tuple[float, event_schedule.ReadinessPhase, object | None]:
        """The bonus, the phase, and the role it came from.

        Multi-role arbitration is the ``soonest`` rule the book asks for: with two roles on one
        device the one about to miss its first participation is the one to serve, so the phase is
        the closest role's, not the first one in the file.
        """
        schedules = self.schedule()
        if not schedules:
            return 0.0, event_schedule.ReadinessPhase.IDLE, None
        role = event_schedule.soonest(schedules, now)
        if role is None:
            return 0.0, event_schedule.ReadinessPhase.IDLE, None
        phase = role.phase_at(now)
        return event_schedule.PHASE_PRIORITY[phase], phase, role

    def _bear_goal_skills(self, world: WorldState) -> set[str]:
        """The skills ``PARTICIPATE_BEAR`` can emit on this frame, from the library itself."""
        try:
            for goal in self.goals.discover(world):
                if getattr(goal, "id", None) == BEAR_GOAL_ID:
                    return set(getattr(goal, "available_skills", ()) or ())
        except Exception:
            # A goal library that cannot answer must not take the cycle down; an empty set
            # simply means no promotion this tick, which is the pre-existing behaviour.
            return set()
        return set()

    def _announce_readiness(self, phase, role, bear_skills) -> None:
        """Print the readiness rung once per change, so a run shows why the bear won.

        Once per change rather than once per tick: the runtime makes thousands of selections and
        a line on every one would bury the transition this exists to make visible.  A phase
        change is also the only moment at which the answer differs from the previous tick.
        """
        key = (getattr(phase, "value", str(phase)), getattr(role, "role_id", "") or "")
        if key == self._announced_readiness:
            return
        self._announced_readiness = key
        if not bear_skills:
            return
        if getattr(phase, "value", "") == event_schedule.ReadinessPhase.IDLE.value:
            return
        role_id = getattr(role, "role_id", "?")
        minutes = role.minutes_to_start()
        print(
            f"[readiness] {phase.value} for role {role_id}"
            f"{f' in {minutes:.1f} min' if minutes is not None else ''}"
            f" -> {event_schedule.phase_instruction(phase)}"
            f" (promoting {len(bear_skills)} bear skills)",
            flush=True,
        )

    def tick(self, world: WorldState, decision: Decision | None = None) -> TickResult:
        """Execute one action for ``world``.

        ``decision`` lets the caller hand over a decision it has already made,
        so that the whole step runs on **one** decision.  ``RuleBrain.decide`` is
        not a pure function -- it mutates run-scoped state, e.g.
        ``stamina_panel_checked`` (brain.py:362) -- so calling it twice for the
        same frame does not return the same answer:

            call 1 -> OPEN_STAMINA_SOURCES   (and sets stamina_panel_checked)
            call 2 -> OPEN_INTEL             (the flag is now set)

        Live 2026-09-15T02:31:11Z showed what that cost.  ``runtime.py`` made the
        first decision and built the backend router from it, then ``tick`` made
        the second one and executed *that*.  So the action really performed was
        ``OPEN_INTEL`` (the client did reach the intel page) while the verifier
        applied afterwards was ``verify_stamina_sources_open``, which expects a
        ``GET_MORE_STAMINA`` popup -- and the step was recorded as
        ``OPEN_INTEL`` / ``STAMINA_SOURCES_NOT_OPEN``, aborting the run.  Worse,
        the free-stamina panel was never opened even though the brain had marked
        it checked for this run: a feature reporting "done" without doing it.

        Callers that do not pass a decision keep the previous behaviour, so the
        single-scheduler contract is unchanged.
        """
        if decision is None:
            decision = self.brain.decide(world, self.registry)
        if decision.skill == "SAFE_STOP":
            return TickResult(decision, None)
        # The last exit before the executor, and the backstop the directive asks for.  A page may not
        # be entered unless the entry that leads to it carries a dot *on this frame*: the reading is
        # taken from the same ``WorldState`` the decision was made on, so a decision that was made
        # when the entry was readable cannot be executed after the client moved on either.
        gated_goal = ENTRY_GATED_SKILLS.get(decision.skill)
        if gated_goal is not None:
            verdict, gated_on = entry_badges.entry_gate(gated_goal, getattr(world, "red_dots", None))
            if verdict != entry_badges.PRESENT:
                return TickResult(
                    Decision(
                        "SAFE_STOP",
                        f"{decision.skill}_refused_at_the_entry_gate:"
                        f"{gated_goal}_is_{verdict.lower()}"
                        f"{'_on_' + '/'.join(gated_on) if gated_on else ''}",
                        1.0,
                        "switch_task",
                    ),
                    None,
                )
        skill = self.registry.get(decision.skill)
        if skill is None or not skill.ready(world):
            return TickResult(Decision("SAFE_STOP", "skill_not_ready", 1.0, "no_action"), None)
        if self.candidate_pool and self.candidate_pool.eligible(skill):
            self.candidate_pool.attempted(skill)
        # ``skill_id`` travels with the action so an ExecutorRouter can pick the
        # skill's preferred backend.  A plain Executor ignores the argument, so
        # the single-scheduler contract is unchanged.
        return TickResult(decision, self.executor.execute(skill.action, skill_id=skill.id))

    def select_next(
            self,
            observations: tuple[WorldState, ...] | tuple[RoleObservation, ...],
            *,
            current_role_id: str = "",
            now: datetime | None = None,
            last_switch_at: str | datetime | None = None,
            min_role_dwell_seconds: float = 120.0,
            max_observation_age_seconds: float = 300.0,
            max_cached_goal_age_seconds: float = 1800.0,
            switch_margin: float = 30.0,
        ) -> TaskSelection:
            """Choose the first actionable observed task with no second scheduler.

            Collection/navigation of observations stays outside Scheduler and Vision;
            this method only applies Brain decisions and records why states were skipped.
            """
            if observations and isinstance(observations[0], RoleObservation):
                return self.select_global(
                    observations, current_role_id=current_role_id, now=now,
                    last_switch_at=last_switch_at,
                    min_role_dwell_seconds=min_role_dwell_seconds,
                    max_observation_age_seconds=max_observation_age_seconds,
                    max_cached_goal_age_seconds=max_cached_goal_age_seconds,
                    switch_margin=switch_margin,
                )
            skipped: list[Decision] = []
            candidates: list[tuple[float, int, Decision]] = []
            # Computed once per selection, not per observation: the readiness clock is a property of
            # "now", not of the frame being ranked.
            readiness_bonus, readiness_phase, readiness_role = self.readiness()
            # The bear skill set is the UNION across the frames being ranked, and the union is the
            # right answer rather than a convenience.  ``PARTICIPATE_BEAR`` offers different skills
            # per bear phase -- ("START_RALLY","JOIN_RALLY") when ACTIVE, ("CHECK_MARCH",
            # "SELECT_TROOP_PRESET") when PREPARING/READY, discovery skills otherwise -- so asking a
            # single frame would promote the participation skills on exactly the frames that do not
            # offer them and miss them on the frames that do.
            bear_skills: set[str] = set()
            if readiness_bonus:
                for world in observations:
                    bear_skills |= self._bear_goal_skills(world)
            self._announce_readiness(readiness_phase, readiness_role, bear_skills)
            for index, world in enumerate(observations):
                decision = self.brain.decide(world, self.registry)
                if decision.skill != "SAFE_STOP":
                    priority = event_priority_modifier(world.events, decision.skill)
                    priority += operational_priority(
                        decision.skill, defense=world.defense, hospital=world.hospital, stamina=world.stamina
                    )
                    priority += self.goals.skill_modifier(world, decision.skill)
                    skill = self.registry.get(decision.skill)
                    if skill and skill.latency_class is LatencyClass.REALTIME and _deadline_active(world):
                        priority += 10_000_000.0
                    if self.candidate_pool and self.candidate_pool.starved(skill):
                        priority += 1_000_000.0
                    # Time-based readiness (task book §五).  Added *after* the frame-based REALTIME
                    # term and outside it, because its whole purpose is to fire when the frame has
                    # nothing to say -- if a reservation is live, the bear goal outranks ordinary
                    # work even though no bear UI is on screen yet.
                    if readiness_bonus and decision.skill in bear_skills:
                        priority += readiness_bonus
                    candidates.append((priority, index, decision))
                else:
                    skipped.append(decision)
            if candidates:
                _, index, decision = max(candidates, key=lambda item: (item[0], -item[1]))
                if self.candidate_pool:
                    for _, candidate_index, candidate_decision in candidates:
                        skill = self.registry.get(candidate_decision.skill)
                        if not self.candidate_pool.eligible(skill): continue
                        if candidate_index == index and candidate_decision.skill == decision.skill:
                            self.candidate_pool.attempted(skill)
                        else:
                            self.candidate_pool.wait_cycle(skill)
                return TaskSelection(index, decision, tuple(skipped))
            return TaskSelection(None, Decision("SAFE_STOP", "all_tasks_unavailable", 1.0, "wait_or_refresh"), tuple(skipped))



    def select_global(
        self,
        roles: tuple[RoleObservation, ...],
        *,
        current_role_id: str = "",
        now: datetime | None = None,
        last_switch_at: str | datetime | None = None,
        min_role_dwell_seconds: float = 120.0,
        max_observation_age_seconds: float = 300.0,
        max_cached_goal_age_seconds: float = 1800.0,
        switch_margin: float = 30.0,
        mark_candidate_attempts: bool = True,
    ) -> TaskSelection:
        """Arbitrate fresh role observations through this existing central Scheduler.

        This is the role-aware entrance to the same Goal/Brain/Skill path, not a second
        scheduler. A cached role summary may contribute a wake time, but only a fresh
        observation whose client-confirmed identity matches can produce an action.
        """
        moment = now or datetime.now(timezone.utc)
        current_role_id = str(current_role_id or "")
        candidates: list[dict[str, Any]] = []
        skipped: list[Decision] = []
        wakeups: list[datetime] = []
        role_statuses: list[dict[str, Any]] = []
        goal_metrics: list[GoalScheduleInfo] = []
        fresh_role_count = 0

        # Schedules are scoped by role here. The ordinary single-frame readiness helper
        # intentionally remains compatible with older callers, while the global path
        # never lends ROLE_A's event pressure to ROLE_B.
        schedule_rows = tuple(self.schedule().values())

        for index, role in enumerate(roles):
            fresh, freshness_reason = role.freshness(
                now=moment, max_age_seconds=max_observation_age_seconds
            )
            known_goals = role.goals or (
                self.goals.discover(role.world, role_id=role.role_id)
                if role.world is not None else ()
            )
            goal_metrics.extend(
                _goal_schedule_info(goal, role.role_id, now=moment,
                                    switch_cost=role.switch_cost)
                for goal in known_goals
            )
            known_runnable = sum(
                1 for goal in known_goals
                if str(getattr(getattr(goal, "status", ""), "value", getattr(goal, "status", ""))).upper()
                in {"READY", "DISCOVERED", "RUNNABLE"}
                and any(self.registry.get(str(skill_id)) is not None
                        for skill_id in (getattr(goal, "available_skills", ()) or ()))
            )
            ready_goals = sum(
                1 for goal in known_goals
                if str(getattr(getattr(goal, "status", ""), "value", getattr(goal, "status", ""))).upper()
                in {"READY", "DISCOVERED", "RUNNABLE"}
            )
            known_blocked = sum(
                1 for goal in known_goals
                if str(getattr(getattr(goal, "status", ""), "value", getattr(goal, "status", ""))).upper()
                in {"BLOCKED", "UNKNOWN", "DEFERRED", "WAITING_GAME_CONDITION"}
            )
            stamp = _as_datetime(role.observed_at) or (
                _as_datetime(role.world.timestamp) if role.world is not None else None
            )
            cached_age = (moment - stamp).total_seconds() if stamp else float("inf")
            switch_blocked_until = _as_datetime(role.switch_blocked_until)
            switch_cooldown_active = bool(
                role.role_id != current_role_id
                and switch_blocked_until is not None
                and switch_blocked_until > moment
            )
            waits = [
                parsed for parsed in (
                    _as_datetime(role.next_action_at),
                    *(_as_datetime(getattr(goal, "retry_after", None)) for goal in known_goals),
                ) if parsed and parsed > moment
            ]
            deadlines = [
                int(getattr(goal, "remaining_seconds")) for goal in known_goals
                if getattr(goal, "remaining_seconds", None) is not None
                and int(getattr(goal, "remaining_seconds")) >= 0
            ]
            top_goal = max(known_goals, key=lambda item: float(getattr(item, "priority", 0.0)),
                           default=None)
            role_statuses.append({
                "role_id": role.role_id,
                "top_goal": str(getattr(top_goal, "goal_id", "") or ""),
                "runnable_count": (role.runnable_count if role.runnable_count is not None
                                   else known_runnable),
                "blocked_count": (role.blocked_count if role.blocked_count is not None
                                  else known_blocked),
                "ready_goal_count": ready_goals,
                "runnable_goal_count": known_runnable,
                "capability_gap_count": max(0, ready_goals - known_runnable),
                "wait_until": min(waits).isoformat() if waits else None,
                "next_deadline_seconds": min(deadlines) if deadlines else None,
                "state_fresh": fresh,
                "state_reason": freshness_reason,
                "switch_cooldown_until": _as_datetime(role.switch_blocked_until).isoformat()
                if _as_datetime(role.switch_blocked_until) else None,
                "switch_failure_streak": max(0, int(role.failure_streak or 0)),
                "switch_cooldown_active": switch_cooldown_active,
                # A cached logical board cannot authorize a click, but a recent one
                # can prove that this role was checked and has no immediate work.
                # Treating every inactive role as globally unknown made GLOBAL_WAIT
                # impossible on a one-device/two-account setup.
                "logical_snapshot_usable": bool(
                    not fresh
                    and role.world is None
                    and role.confirmed_role_id == role.role_id
                    and stamp is not None
                    and 0.0 <= (moment - stamp).total_seconds()
                    <= max(0.0, max_cached_goal_age_seconds)
                ),
            })
            suggested_wake = _as_datetime(role.next_action_at)
            if suggested_wake and suggested_wake > moment:
                wakeups.append(suggested_wake)
            for goal in role.goals:
                wake = _as_datetime(getattr(goal, "retry_after", None))
                if wake and wake > moment:
                    wakeups.append(wake)

            # Failed navigation is a temporary switch failure, not permission to
            # retry the same role transition in a tight worker restart loop. The
            # backoff is role-scoped; the current account remains schedulable.
            if switch_cooldown_active and switch_blocked_until is not None:
                wakeups.append(switch_blocked_until)
                skipped.append(Decision(
                    "SAFE_STOP",
                    f"{role.role_id}:role_switch_cooldown_until:{switch_blocked_until.isoformat()}",
                    1.0,
                    "keep_current_role_and_retry_after_bounded_backoff",
                ))
                continue

            if not fresh:
                skipped.append(Decision("SAFE_STOP", f"{role.role_id}:{freshness_reason}", 1.0,
                                        "reobserve_role_before_dispatch"))
                # An inactive role's last observed Goal board can justify switching
                # over to refresh that role, but never authorize an action. It is a
                # logical hint only: caller must switch, confirm identity, discard all
                # live UI data, observe again, and re-arbitrate before dispatch.
                cached_eligible = (
                    role.role_id != current_role_id
                    and role.confirmed_role_id == role.role_id
                    and role.world is None
                    and 0.0 <= cached_age <= max(0.0, max_cached_goal_age_seconds)
                )
                if cached_eligible:
                    by_skill: dict[str, list[Any]] = {}
                    for item in known_goals:
                        status = str(getattr(getattr(item, "status", ""), "value",
                                             getattr(item, "status", ""))).upper()
                        if status not in {"READY", "DISCOVERED", "RUNNABLE"}:
                            continue
                        retry_at = _as_datetime(getattr(item, "retry_after", None))
                        if retry_at and retry_at > moment:
                            continue
                        for skill_id in (getattr(item, "available_skills", ()) or ()):
                            if self.registry.get(str(skill_id)) is not None:
                                by_skill.setdefault(str(skill_id), []).append(item)
                    matching_rows = [row for row in schedule_rows if row.role_id == role.role_id]
                    schedule = min(
                        (row for row in matching_rows if row.start_datetime() is not None),
                        key=lambda row: row.start_datetime() or datetime.max.replace(tzinfo=timezone.utc),
                        default=None,
                    )
                    phase = schedule.phase_at(moment) if schedule else event_schedule.ReadinessPhase.IDLE
                    for skill_id, attached_goals in by_skill.items():
                        primary = max(attached_goals,
                                      key=lambda item: float(getattr(item, "priority", 0.0) or 0.0))
                        deadline_values = [
                            int(value) for value in
                            (getattr(item, "remaining_seconds", None) for item in attached_goals)
                            if value is not None
                        ]
                        remaining = min(deadline_values, default=None)
                        hard_event = (
                            phase in {event_schedule.ReadinessPhase.T15,
                                      event_schedule.ReadinessPhase.T5,
                                      event_schedule.ReadinessPhase.T1,
                                      event_schedule.ReadinessPhase.OPEN}
                            or (remaining is not None and remaining <= 300)
                        )
                        priority = max(float(getattr(item, "priority", 0.0) or 0.0)
                                       for item in attached_goals)
                        if remaining is not None:
                            priority += _deadline_pressure(remaining)
                        priority += max(0, len(attached_goals) - 1) * 25.0
                        priority -= max(0.0, float(role.switch_cost or 0.0))
                        goal_ids = tuple(dict.fromkeys(
                            str(getattr(item, "goal_id", "")) for item in attached_goals
                            if getattr(item, "goal_id", "")
                        ))
                        decision = Decision(
                            skill_id,
                            "cached_role_goal_requires_fresh_observation",
                            0.0,
                            "switch_to_role_then_confirm_identity_and_reobserve",
                        )
                        candidates.append({
                            "index": index,
                            "role": role,
                            "decision": decision,
                            "priority": priority,
                            "hard_event": hard_event,
                            "goal": primary,
                            "goal_info": _goal_schedule_info(
                                primary, role.role_id, now=moment,
                                switch_cost=role.switch_cost,
                            ),
                            "credited_goal_ids": goal_ids,
                            "requires_role_refresh": True,
                        })
                # A registered account with no usable cached Goal board still has
                # to be observed once. This is a refresh request only: it cannot
                # authorize an action. Keep its ordinary value low so a runnable
                # current-role Goal wins, while a hard event on that role can still
                # preempt through the same event schedule.
                if (role.role_id != current_role_id
                        and role.confirmed_role_id == role.role_id
                        and role.world is None
                        and role.needs_initial_refresh):
                    matching_rows = [row for row in schedule_rows if row.role_id == role.role_id]
                    schedule = min(
                        (row for row in matching_rows if row.start_datetime() is not None),
                        key=lambda row: row.start_datetime() or datetime.max.replace(tzinfo=timezone.utc),
                        default=None,
                    )
                    phase = schedule.phase_at(moment) if schedule else event_schedule.ReadinessPhase.IDLE
                    hard_event = phase in {
                        event_schedule.ReadinessPhase.T15,
                        event_schedule.ReadinessPhase.T5,
                        event_schedule.ReadinessPhase.T1,
                        event_schedule.ReadinessPhase.OPEN,
                    }
                    decision = Decision(
                        "SAFE_STOP", "registered_role_requires_initial_observation", 0.0,
                        "switch_to_role_then_confirm_identity_and_observe",
                    )
                    candidates.append({
                        "index": index,
                        "role": role,
                        "decision": decision,
                        "priority": (event_schedule.PHASE_PRIORITY[phase]
                                     if hard_event else 20.0)
                                     - max(0.0, float(role.switch_cost or 0.0)),
                        "hard_event": hard_event,
                        "goal": None,
                        "goal_info": None,
                        "credited_goal_ids": (),
                        "requires_role_refresh": True,
                    })
                continue
            fresh_role_count += 1

            world = role.world
            assert world is not None
            role_brain = self._role_brains.get(role.role_id)
            if role_brain is None:
                role_brain = copy.deepcopy(self.brain)
                # A copied Brain carries run-scoped flags and current_goal. Those
                # belong to the account that produced them; each role starts with
                # its own decision memory while retaining the shared policy knobs.
                role_brain.current_goal = None
                self._role_brains[role.role_id] = role_brain
            decision = role.decision or role_brain.decide(world, self.registry)
            if decision.skill == "SAFE_STOP" or decision.skill == "WAIT":
                skipped.append(Decision(
                    decision.skill,
                    f"{role.role_id}:{decision.reason}",
                    decision.confidence,
                    decision.expected_result,
                ))
                continue

            goals = role.goals or self.goals.discover(world, role_id=role.role_id)
            matching_goals = [
                goal for goal in goals
                if decision.skill in (getattr(goal, "available_skills", ()) or ())
            ]
            goal = max(matching_goals, key=lambda item: float(getattr(item, "priority", 0.0)), default=None)
            goal_info = (_goal_schedule_info(goal, role.role_id, now=moment,
                                             switch_cost=role.switch_cost)
                         if goal is not None else None)

            priority = event_priority_modifier(world.events, decision.skill)
            priority += operational_priority(
                decision.skill, defense=world.defense, hospital=world.hospital,
                stamina=world.stamina,
            )
            # This is the same GoalLibrary marginal value used by the existing path,
            # calculated over this role's own Goal states so shared credit is retained
            # without pooling another account's resources or progress.
            priority += sum(
                float(getattr(item, "priority", 0.0) or 0.0)
                for item in goals
                if decision.skill in (getattr(item, "available_skills", ()) or ())
            )

            matching_schedules = [row for row in schedule_rows if row.role_id == role.role_id]
            plausible_schedules = [
                row for row in matching_schedules
                if row.start_datetime() is not None
                and (row.start_datetime() >= moment
                     or str(row.live_window_state or "").upper() in {"OPEN", "ACTIVE"})
            ]
            role_schedule = min(
                plausible_schedules,
                key=lambda row: row.start_datetime() or datetime.max.replace(tzinfo=timezone.utc),
                default=None,
            )
            phase = role_schedule.phase_at(moment) if role_schedule else event_schedule.ReadinessPhase.IDLE
            timed_skills = {
                skill_id
                for item in goals
                if str(getattr(item, "goal_id", "")).startswith("SCHEDULED_")
                or str(getattr(item, "goal_id", "")) == BEAR_GOAL_ID
                for skill_id in (getattr(item, "available_skills", ()) or ())
            }
            if role_schedule and decision.skill in timed_skills:
                priority += event_schedule.PHASE_PRIORITY[phase]

            skill = self.registry.get(decision.skill)
            deadline_seconds = getattr(goal, "remaining_seconds", None) if goal else None
            hard_event = (
                phase in {event_schedule.ReadinessPhase.T15,
                          event_schedule.ReadinessPhase.T5,
                          event_schedule.ReadinessPhase.T1,
                          event_schedule.ReadinessPhase.OPEN}
                or _deadline_active(world)
                or (deadline_seconds is not None and int(deadline_seconds) <= 300)
            )
            if skill and skill.latency_class is LatencyClass.REALTIME and _deadline_active(world):
                priority += 10_000_000.0
            if self.candidate_pool and self.candidate_pool.starved(skill):
                priority += 1_000_000.0
            # ``switch_cost`` is supplied from observed switching cost in scheduler-score
            # units. It is zero until measured; the dwell guard still suppresses thrash.
            if current_role_id and role.role_id != current_role_id:
                priority -= max(0.0, float(role.switch_cost))

            candidates.append({
                "index": index, "role": role, "decision": decision,
                "priority": priority, "hard_event": hard_event,
                "goal": goal, "goal_info": goal_info,
                "requires_role_refresh": False,
                "credited_goal_ids": tuple(dict.fromkeys(
                    str(getattr(item, "goal_id", "")) for item in matching_goals
                    if str(getattr(item, "goal_id", ""))
                )),
            })

        if not candidates:
            for row in schedule_rows:
                start = row.start_datetime()
                if start and start > moment:
                    wakeups.append(start)
            next_wakeup = min(wakeups).isoformat() if wakeups else None
            any_stale_role = any(
                not row["state_fresh"] and not row.get("logical_snapshot_usable")
                and not row.get("switch_cooldown_active")
                for row in role_statuses
            )
            available_statuses = [row for row in role_statuses
                                  if not row.get("switch_cooldown_active")]
            capability_gaps = sum(int(row.get("capability_gap_count") or 0)
                                  for row in available_statuses)
            unselected_runnable = sum(int(row.get("runnable_goal_count") or 0)
                                      for row in available_statuses)
            if any_stale_role:
                reason = "GLOBAL_REFRESH_REQUIRED_NO_SAFE_CANDIDATE"
                explanation = (
                    "At least one role has no fresh live state; observe the active role and "
                    "rebuild candidates before declaring a global wait"
                )
            elif capability_gaps:
                reason = "GLOBAL_CAPABILITY_GAP_NO_EXECUTABLE_CANDIDATE"
                explanation = (
                    f"{capability_gaps} ready Goal(s) lack a registered executable Skill"
                )
            elif unselected_runnable:
                reason = "GLOBAL_CANDIDATE_GENERATION_GAP"
                explanation = (
                    f"{unselected_runnable} ready Goal(s) have registered Skills but no Brain "
                    "candidate; this is not a global wait"
                )
            else:
                reason = "GLOBAL_WAIT"
                explanation = f"no ready executable Goal across {len(roles)} fresh role(s)"
            self._persist_global_decision({
                "decision": reason,
                "current_role_id": current_role_id,
                "selected_role_id": "",
                "selected_goal_id": "",
                "selected_skill_id": "",
                "requires_role_refresh": reason == "GLOBAL_REFRESH_REQUIRED_NO_SAFE_CANDIDATE",
                "reason": explanation,
                "next_wakeup": next_wakeup,
                "role_statuses": role_statuses,
                "candidates": [],
            })
            return TaskSelection(
                None,
                Decision("SAFE_STOP", reason, 1.0,
                         f"wake_at={next_wakeup}" if next_wakeup else "refresh_all_roles"),
                tuple(skipped),
                selection_reason=explanation,
                next_wakeup=next_wakeup,
                role_statuses=tuple(role_statuses),
                goal_metrics=tuple(goal_metrics),
            )


        current = next((item for item in candidates
                        if item["role"].role_id == current_role_id), None)
        hard_candidates = [item for item in candidates if item["hard_event"]]
        switched_at = _as_datetime(last_switch_at)
        dwell_active = bool(
            current is not None and switched_at is not None
            and (moment - switched_at).total_seconds() < max(0.0, min_role_dwell_seconds)
        )

        dominant_hard = max(hard_candidates, key=lambda item: item["priority"], default=None)
        if dominant_hard is not None:
            selected = dominant_hard
            if selected["role"].role_id == current_role_id:
                reason = (f"KEEP_CURRENT_ROLE: hard deadline/event phase for "
                          f"{selected['decision'].skill}")
            else:
                reason = (f"SWITCH {current_role_id or 'UNKNOWN'}→{selected['role'].role_id}: "
                          f"hard deadline/event phase overrides dwell and switch cost "
                          f"for {selected['decision'].skill}")
        elif current is not None and dwell_active:
            selected = current
            reason = f"KEEP_CURRENT_ROLE: {current_role_id} within minimum dwell and has runnable Goal"
        else:
            selected = max(candidates, key=lambda item: (
                item["priority"], item["role"].role_id == current_role_id,
                -item["index"],
            ))
            if selected["role"].role_id == current_role_id:
                reason = f"KEEP_CURRENT_ROLE: {selected['decision'].skill} remains best after switch cost"
            elif selected["hard_event"]:
                reason = (f"SWITCH {current_role_id or 'UNKNOWN'}→{selected['role'].role_id}: "
                          f"hard deadline/event phase for {selected['decision'].skill}")
            elif current is None:
                reason = (f"SWITCH {current_role_id or 'UNKNOWN'}→{selected['role'].role_id}: "
                          "current role has no fresh runnable Goal")
            elif selected["priority"] >= current["priority"] + max(0.0, switch_margin):
                reason = (f"SWITCH {current_role_id}→{selected['role'].role_id}: "
                          f"higher global value ({selected['decision'].skill})")
            else:
                selected = current
                reason = f"KEEP_CURRENT_ROLE: switch gain is below {switch_margin:.1f}"

        decision = selected["decision"]
        role_id = selected["role"].role_id
        if self.candidate_pool:
            for item in candidates:
                skill = self.registry.get(item["decision"].skill)
                if not self.candidate_pool.eligible(skill):
                    continue
                if item is selected and not item["requires_role_refresh"]:
                    if mark_candidate_attempts:
                        self.candidate_pool.attempted(skill)
                elif item is not selected:
                    # The live runtime asks for arbitration before it creates the
                    # step-scoped executor. It leaves the winner for Scheduler.tick
                    # to mark as attempted, but losing candidates still accrue one
                    # wait cycle so cross-role exploration cannot starve silently.
                    self.candidate_pool.wait_cycle(skill)
        next_wakeup = min(wakeups).isoformat() if wakeups else None
        candidate_explanations = tuple({
            "role_id": item["role"].role_id,
            "goal_id": str(getattr(item["goal"], "goal_id", "") or ""),
            "skill_id": item["decision"].skill,
            "source": "CACHED_GOAL_REFRESH" if item["requires_role_refresh"] else "FRESH_ROLE_BRAIN",
            "ready_now": not item["requires_role_refresh"],
            "score": float(item["priority"]),
            "role_switch_cost": max(0.0, float(item["role"].switch_cost or 0.0)),
            "hard_event": bool(item["hard_event"]),
            "selected": item is selected,
            "selected_reason": reason if item is selected else "",
            "rejected_reason": "selected_candidate_won_global_arbitration" if item is selected
            else ("hard_event_preemption" if dominant_hard is not None and not item["hard_event"]
                  else "lower_score_or_role_hysteresis"),
            "attached_goal_ids": list(item["credited_goal_ids"]),
        } for item in candidates)
        self._persist_global_decision({
            "decision": ("ROLE_REFRESH_REQUIRED" if selected["requires_role_refresh"]
                         else "KEEP_ROLE" if role_id == current_role_id else "SWITCH_ROLE"),
            "current_role_id": current_role_id,
            "selected_role_id": role_id,
            "selected_goal_id": str(getattr(selected["goal"], "goal_id", "") or ""),
            "selected_skill_id": decision.skill,
            "requires_role_refresh": bool(selected["requires_role_refresh"]),
            "reason": reason,
            "score": float(selected["priority"]),
            "role_switch_cost": max(0.0, float(selected["role"].switch_cost or 0.0)),
            "next_wakeup": next_wakeup,
            "role_statuses": role_statuses,
            "candidates": list(candidate_explanations),
        })
        return TaskSelection(
            None if selected["requires_role_refresh"] else selected["index"],
            (Decision("SAFE_STOP", "selected_role_requires_fresh_observation", 1.0,
                      "switch_transaction_then_observe_and_rearbitrate")
             if selected["requires_role_refresh"] else decision),
            tuple(skipped), role_id=role_id, selection_reason=reason,
            goal_id=str(getattr(selected["goal"], "goal_id", "") or ""),
            score=float(selected["priority"]),
            credited_goal_ids=selected["credited_goal_ids"],
            role_statuses=tuple(role_statuses),
            goal_metrics=tuple(goal_metrics),
            requires_role_refresh=bool(selected["requires_role_refresh"]),
            requested_skill=decision.skill,
            next_wakeup=next_wakeup,
            candidate_explanations=candidate_explanations,
        )

    def _persist_global_decision(self, decision: dict[str, Any]) -> None:
        store = getattr(self, "global_state_store", None)
        if store is None:
            return
        try:
            store.record_decision(decision=decision)
        except (OSError, TypeError, ValueError):
            # Diagnostics and restart hints must never take the production loop down.
            return


def _deadline_pressure(remaining_seconds: int) -> float:
    """Fixed, explainable deadline bands used by global role arbitration."""
    seconds = int(remaining_seconds)
    if seconds < 0:
        return -100_000.0
    if seconds < 2 * 60 * 60:
        return 10_000.0
    if seconds < 6 * 60 * 60:
        return 4_000.0
    if seconds < 12 * 60 * 60:
        return 2_000.0
    if seconds < 24 * 60 * 60:
        return 1_000.0
    return 0.0
def _deadline_active(world: WorldState) -> bool:
    bear = world.events.get("bear", {}) if isinstance(world.events, dict) else {}
    return bool(bear.get("status") in {"READY", "ACTIVE"} or bear.get("deadline_active"))
