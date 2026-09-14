import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from winter_agent_v2.candidate_policy import CandidateAttemptPool
from winter_agent_v2.executor import Executor
from winter_agent_v2.models import Action, Decision, Page, SkillState, WorldState
from winter_agent_v2.scheduler import Scheduler
from winter_agent_v2.skills import Skill, SkillRegistry


class FixedBrain:
    def decide(self, world, registry):
        return Decision(world.daily["skill"], "ready", 1, "done")


def semantic_candidate(skill_id="C"):
    return Skill(skill_id, "candidate", Page.HOME, Action("OBSERVE"), state=SkillState.CANDIDATE,
                 semantic_goal="Observe a semantic state", semantic_requirements=("state_context",),
                 vision_evidence=("semantic_anchor",), verifier="STATE_CHANGED",
                 recovery=("REFRESH_STATE",), unknown_policy="Unknown action blocks",
                 ui_change_tolerance=("icon", "number", "position", "resolution"))


class CandidatePolicyTests(unittest.TestCase):
    def test_only_complete_safe_candidate_enters_pool(self):
        skill = semantic_candidate()
        pool = CandidateAttemptPool(verifier_skills={"C"}, recovery_skills={"C"})
        self.assertTrue(pool.eligible(skill))
        self.assertFalse(CandidateAttemptPool(verifier_skills={"C"}).eligible(skill))
        fragile = Skill("F", "fragile", Page.HOME, Action("OBSERVE"), state=SkillState.CANDIDATE)
        self.assertFalse(CandidateAttemptPool(verifier_skills={"F"}, recovery_skills={"F"}).eligible(fragile))

    def test_ready_five_cycles_forces_candidate_over_stable(self):
        candidate = semantic_candidate()
        stable = Skill("S", "stable", Page.HOME, Action("OBSERVE"), state=SkillState.STABLE)
        registry = SkillRegistry([candidate, stable])
        with TemporaryDirectory() as folder:
            pool = CandidateAttemptPool(Path(folder) / "pool.json", verifier_skills={"C"}, recovery_skills={"C"}, threshold=5)
            scheduler = Scheduler(FixedBrain(), registry, Executor(), pool)
            candidate_world = WorldState(page=Page.HOME, daily={"skill":"C"})
            stable_world = WorldState(page=Page.HOME, daily={"skill":"S"})
            for _ in range(5):
                selection = scheduler.select_next((stable_world, candidate_world))
                self.assertEqual(selection.decision.skill, "S")
            selection = scheduler.select_next((stable_world, candidate_world))
            self.assertEqual(selection.decision.skill, "C")
            self.assertEqual(pool.cycles["C"], 0)


if __name__ == "__main__": unittest.main()
