from __future__ import annotations

from dataclasses import dataclass

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


class Scheduler:
    """The single V2 scheduler."""

    def __init__(self, brain: RuleBrain, registry: SkillRegistry, executor: Executor,
                 candidate_pool: CandidateAttemptPool | None = None) -> None:
        self.brain = brain
        self.registry = registry
        self.executor = executor
        self.goals = GoalLibrary()
        self.candidate_pool = candidate_pool
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

    def select_next(self, observations: tuple[WorldState, ...]) -> TaskSelection:
        """Choose the first actionable observed task with no second scheduler.

        Collection/navigation of observations stays outside Scheduler and Vision;
        this method only applies Brain decisions and records why states were skipped.
        """
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


def _deadline_active(world: WorldState) -> bool:
    bear = world.events.get("bear", {}) if isinstance(world.events, dict) else {}
    return bool(bear.get("status") in {"READY", "ACTIVE"} or bear.get("deadline_active"))