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

    def tick(self, world: WorldState) -> TickResult:
        decision = self.brain.decide(world, self.registry)
        if decision.skill == "SAFE_STOP":
            return TickResult(decision, None)
        skill = self.registry.get(decision.skill)
        if skill is None or not skill.ready(world):
            return TickResult(Decision("SAFE_STOP", "skill_not_ready", 1.0, "no_action"), None)
        if self.candidate_pool and self.candidate_pool.eligible(skill):
            self.candidate_pool.attempted(skill)
        return TickResult(decision, self.executor.execute(skill.action))

    def select_next(self, observations: tuple[WorldState, ...]) -> TaskSelection:
        """Choose the first actionable observed task with no second scheduler.

        Collection/navigation of observations stays outside Scheduler and Vision;
        this method only applies Brain decisions and records why states were skipped.
        """
        skipped: list[Decision] = []
        candidates: list[tuple[float, int, Decision]] = []
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
