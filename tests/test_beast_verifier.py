import json
import unittest
from pathlib import Path

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import (
    verify_beast_hunt,
    verify_beast_march_open,
    verify_intel_beast_march_open,
)
from winter_agent_v2.vision import ReplayVision


ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "tests" / "replay" / "labels.json"
ROUTING_ARCHIVE = (
    ROOT / "dataset" / "truth_audit" / "beast_intel_target_routing_20260915"
)
RECORDED_EPISODE = (
    ROUTING_ARCHIVE / "recorded_episode_20260915T021052Z.json"
)

# 麝牛 / level 9 is the *map wilderness* beast.  vision.py emits `available` on
# Page.BEAST from this dialog alone (`DIALOG_BEAST_MUSK_OX_9`), and that dialog
# carries no mission id -- which is the only honest discriminator between the
# two targets that share this page.
WILDERNESS_TARGET = WorldState(
    page=Page.BEAST,
    march_used=1,
    march_max=6,
    beast={"name": "麝牛", "level": 9, "available": True,
           "recommended_power": 9000, "stamina_cost_displayed": 10},
    confidence=0.99,
)


def _live_states() -> list[WorldState]:
    vision = ReplayVision(LABELS)
    names = [
        "live_beast_intel_world_target.png",
        "live_beast_march_selection.png",
        "live_beast_marching.png",
        "live_beast_return_complete.png",
        "live_beast_intel_completed.png",
    ]
    return [vision.observe(ROOT / "dataset" / "raw" / name) for name in names]


def _recorded_episode() -> dict:
    return json.loads(RECORDED_EPISODE.read_text(encoding="utf-8"))


def _state(raw: dict) -> WorldState:
    """Rebuild a WorldState from a recorded episode's serialized state."""
    from winter_agent_v2.models import MarchState

    data = dict(raw)
    data["page"] = Page(data["page"]) if data.get("page") else Page.UNKNOWN
    data["marches"] = tuple(MarchState(m) for m in data.get("marches") or ())
    data.pop("timestamp", None)
    return WorldState(**data)


class BeastIntelTargetRoutingTests(unittest.TestCase):
    """`Page.BEAST` is shared by two different targets.

    The map wilderness beast (麝牛/9, no mission id) and the intel beast target
    (INTEL_BEAST_10 / 大角鹿/22, with a mission id) render the same layout and
    the same 出征 button, but only the intel one carries a mission id.

    Until 2026-09-15 the intel route was additionally gated on
    `current_goal == "INTEL"`.  With any other goal the intel target fell
    through to `BEAST_HUNT` -- the skill documented as "Defeat a normal
    *wilderness* Beast" and verified by `verify_beast_march_open`, which binds
    麝牛/9.  The tap was identical, so the action succeeded and was still
    recorded as FAILURE.  These tests pin the identity-based route instead.
    """

    def test_the_intel_target_is_routed_by_mission_id_not_by_goal(self) -> None:
        target = _live_states()[0]
        self.assertEqual(target.page, Page.BEAST)
        self.assertEqual(target.beast.get("mission_id"), "INTEL_BEAST_10")
        for goal in (None, "INTEL", "HOME", "BEAST_HUNT"):
            decision = RuleBrain(current_goal=goal).decide(target, v2_registry())
            self.assertEqual(
                decision.skill,
                "INTEL_BEAST_START_MARCH",
                f"goal={goal!r} must not change the identity of an intel target",
            )

    def test_the_wilderness_target_still_routes_to_beast_hunt(self) -> None:
        self.assertNotIn("mission_id", WILDERNESS_TARGET.beast)
        for goal in (None, "BEAST_HUNT"):
            decision = RuleBrain(current_goal=goal).decide(
                WILDERNESS_TARGET, v2_registry()
            )
            self.assertEqual(decision.skill, "BEAST_HUNT", f"goal={goal!r}")

    def test_an_intel_target_is_never_dispatched_to_beast_hunt(self) -> None:
        """The regression guard: this exact pairing produced the live failure."""
        target = _live_states()[0]
        self.assertNotEqual(
            RuleBrain(current_goal="HOME").decide(target, v2_registry()).skill,
            "BEAST_HUNT",
        )

    def test_the_verifiers_disagree_which_is_why_the_route_matters(self) -> None:
        """Both verifiers judge the same pair; only one binds the right target."""
        target = _live_states()[0]
        march = _live_states()[1]
        self.assertFalse(verify_beast_march_open(target, march).ok)
        self.assertEqual(
            verify_beast_march_open(target, march).reason, "BEAST_MARCH_NOT_PROVEN"
        )
        self.assertTrue(verify_intel_beast_march_open(target, march).ok)


class BeastRecordedEpisodeReplayTests(unittest.TestCase):
    """Replay the recorded production episode that exposed the misroute.

    Source: `learning/episodes.jsonl`, episode `ally_prep_20260915` step 3,
    2026-09-15T02:10:52Z, goal HOME, `BEAST_HUNT` / `BEAST_MARCH_NOT_PROVEN`.
    The fixture under `dataset/truth_audit/` keeps the two states verbatim so
    this proof does not depend on the append-only episode log.
    """

    def test_the_fixture_is_the_production_record(self) -> None:
        episode = _recorded_episode()
        provenance = episode["_provenance"]
        self.assertEqual(provenance["kind"], "LIVE_PRODUCTION_EPISODE")
        self.assertEqual(provenance["goal_id"], "HOME")
        self.assertEqual(provenance["skill_recorded"], "BEAST_HUNT")
        self.assertEqual(
            provenance["failure_type_recorded"], "BEAST_MARCH_NOT_PROVEN"
        )
        self.assertEqual(provenance["mode"], "PRODUCTION")

    def test_the_recorded_before_state_is_an_intel_target(self) -> None:
        before = _state(_recorded_episode()["state_before"])
        self.assertEqual(before.page, Page.BEAST)
        self.assertEqual(before.beast.get("mission_id"), "INTEL_BEAST_10")
        self.assertEqual(before.beast.get("level"), 22)

    def test_the_route_that_produced_the_failure_is_gone(self) -> None:
        episode = _recorded_episode()
        before = _state(episode["state_before"])
        self.assertEqual(
            RuleBrain(current_goal="HOME").decide(before, v2_registry()).skill,
            "INTEL_BEAST_START_MARCH",
        )

    def test_the_same_recorded_states_now_verify(self) -> None:
        episode = _recorded_episode()
        before = _state(episode["state_before"])
        after = _state(episode["state_after"])
        self.assertEqual(after.page, Page.MARCH)
        self.assertTrue(after.beast.get("victory_assured"))

        result = verify_intel_beast_march_open(before, after)
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(result.reason, "OK")

    def test_the_old_verifier_still_rejects_it_so_the_fix_is_in_the_route(self) -> None:
        """Guards against 'fixing' this by loosening the verifier instead."""
        episode = _recorded_episode()
        before = _state(episode["state_before"])
        after = _state(episode["state_after"])
        self.assertFalse(verify_beast_march_open(before, after).ok)


class BeastVerifierTests(unittest.TestCase):
    def test_live_beast_intel_hunt_cycle(self) -> None:
        states = _live_states()
        # This assertion used to read `BEAST_HUNT`, which is what pinned the
        # misroute: the frame is named `..._intel_...` and its label carries
        # `mission_id=INTEL_BEAST_10`, so `INTEL_BEAST_START_MARCH` is the skill
        # whose verifier actually binds it.  `verify_beast_hunt` below is the
        # intel full-cycle verifier (it requires level 22 and an INTEL
        # completion), so the two are consistent.
        self.assertEqual(
            RuleBrain().decide(states[0], v2_registry()).skill,
            "INTEL_BEAST_START_MARCH",
        )
        self.assertTrue(verify_beast_hunt(*states).ok)

    def test_beast_hunt_rejects_missing_intel_completion(self) -> None:
        states = _live_states()
        target, march, returning, idle = states[:4]
        self.assertFalse(verify_beast_hunt(target, march, returning, idle, idle).ok)


if __name__ == "__main__":
    unittest.main()
