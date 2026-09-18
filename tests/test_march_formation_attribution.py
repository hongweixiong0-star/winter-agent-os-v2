"""OPEN_MARCH_FORMATION: the episode must name the goal that owns the route.

The escalation this file answers was filed as
``OPEN_MARCH_FORMATION|NO_GOAL_PROGRESS|SUBMIT_RESOURCE_SEARCH`` against
``KEEP_MARCHES_PRODUCTIVE``, with ``OPEN_MARCH_FORMATION`` named as the frontier the
route "never reached".  It *had* reached it -- on 2026-09-18 ``START_GATHER`` was
16/16 on the live device -- but the step that opens the formation page runs on
``RESOURCE_DETAIL``, where the project's page-scoped goal discovery finds nothing,
so ``best_goal`` was ``None`` and the episode was written under the synthetic
``AUTO_DISCOVERY`` placeholder instead.  ``OPEN_MARCH_FORMATION`` therefore sat
outside the goal's own ``reached`` set forever, its ``goal_progress`` never once read
``True``, and three verified-but-unattributed runs were enough for the no-progress
rule to defer the goal and file an escalation against a capability that works.

The frames below are the live route's own shapes: ``MAP`` with a readable march
counter selects the goal and drives ``SEARCH_RESOURCE``; ``RESOURCE_DETAIL`` -- the
page the search submit lands on, where no goal is discoverable -- is the step under
test.  ``START_GATHER`` is the skill the project's own table maps to
``OPEN_MARCH_FORMATION`` (``capability_for_skill``), so the goal_id on that row is
what decides which capability the step is credited to.
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from winter_agent_v2.learning import EpisodeStore
from winter_agent_v2.models import MarchState, Page, WorldState
from winter_agent_v2.runtime import LiveRuntime


class FakeMatch:
    center_norm = (0.84, 0.50)


class FakeSemantic:
    """The semantic matcher, reporting a hit for the two controls this route taps."""

    TARGETS = {"BTN_OPEN_RESOURCE_SEARCH", "BTN_GATHER", "PAGE_MAP", "BTN_OPEN_HOME"}

    def find(self, _path, semantic):
        return FakeMatch() if semantic in self.TARGETS else None

    semantic = property(lambda self: self)
    resource_tab_band = (0.0, 1.0)
    resource_level_minus = (0.5, 0.5)
    resource_tab_offset = None

    def resource_cell_center_norm(self, _resource):
        return (0.5, 0.5)

    def resource_tab_swipe_for(self, _resource):
        return 0.0


class FakeVision:
    def __init__(self, states):
        self.states = iter(states)

    def observe(self, _path):
        return next(self.states)


class FakeDevice:
    def __init__(self):
        self.taps = []

    def screenshot(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        return path

    def status(self):
        return type("Status", (), {"connected": True, "resolution": (720, 1280)})()

    def tap(self, x, y):
        self.taps.append((x, y))

    def press_back(self):
        pass

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        raise AssertionError("this route must not need the resource-strip scroll")


def map_frame(**overrides):
    """A MAP frame whose march counter makes KEEP_MARCHES_PRODUCTIVE the best goal.

    Stamina is below the floor on purpose: ``AVOID_STAMINA_WASTE`` is then COMPLETE
    and cannot outrank the gather goal, which is the situation the live evidence
    shows (stamina 577 sat above the floor, but the beast route was already deferred).
    """
    base = dict(
        page=Page.MAP,
        stamina={"current": 10},
        marches=(MarchState.GATHERING,),
        march_used=1,
        march_max=3,
        confidence=0.99,
    )
    base.update(overrides)
    return WorldState(**base)


def episodes_at(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class MarchFormationAttributionTests(unittest.TestCase):
    def test_the_step_that_opens_the_formation_page_carries_the_goal_that_owns_it(self):
        device = FakeDevice()
        states = [
            # step 1 -- MAP.  Idle march slots are readable here, so goal discovery
            # selects KEEP_MARCHES_PRODUCTIVE and the brain opens the search panel.
            map_frame(resource_search_open=False),
            map_frame(resource_search_open=True),
            # step 2 -- RESOURCE_DETAIL, the page the submit lands on.  Nothing here
            # discovers a goal, but the step is still a step of the gather route.
            WorldState(page=Page.RESOURCE_DETAIL, resource_available=True, confidence=0.99),
            WorldState(page=Page.MARCH, confidence=0.99),
        ]
        with TemporaryDirectory() as temp:
            episode_path = Path(temp) / "episodes.jsonl"
            run = LiveRuntime(
                device=device,
                vision=FakeVision(states),
                semantic_vision=FakeSemantic(),
                capture_dir=Path(temp) / "captures",
                sleeper=lambda _seconds: None,
                episode_store=EpisodeStore(episode_path),
            ).run(max_actions=2, allowed_skills={"SEARCH_RESOURCE", "START_GATHER"})
            rows = episodes_at(episode_path)

        self.assertEqual(run.stop_reason, "MAX_ACTIONS_REACHED")
        self.assertEqual([row["skill"] for row in rows], ["SEARCH_RESOURCE", "START_GATHER"])
        self.assertTrue(all(row["verifier_ok"] for row in rows))

        # The route's own goal is the honest label for a step taken on the way to it,
        # even though the page discovers nothing.
        self.assertEqual(rows[1]["goal_id"], "KEEP_MARCHES_PRODUCTIVE")
        self.assertNotEqual(
            rows[1]["goal_id"], "AUTO_DISCOVERY",
            "the placeholder owns no meter, so a step filed under it can be "
            "neither called progress nor called stalled",
        )

    def test_the_formation_step_is_credited_to_the_capability_that_names_it(self):
        """The goal_id is only meaningful because of what it resolves to.

        ``START_GATHER`` is ``OPEN_MARCH_FORMATION`` in the project's own skill ->
        capability table.  Pinned here so a rename on either side cannot quietly
        decouple the episode this fix produces from the capability it evidences.
        """
        from winter_agent_v2.escalation_queue import capability_for_skill

        self.assertEqual(capability_for_skill("START_GATHER"), "OPEN_MARCH_FORMATION")
        self.assertEqual(
            LiveRuntime.VERIFIED_ATOMIC["START_GATHER"].__name__, "verify_march_page_open"
        )

    def test_a_run_that_never_selected_a_goal_keeps_the_placeholder(self):
        """The fallback is a last resort, not something the commitment invents.

        With no goal discoverable on the very first frame there is nothing to commit
        to, and the run is honestly recorded as goal-less rather than being attributed
        to a goal it never chose.
        """
        device = FakeDevice()
        states = [
            WorldState(page=Page.HOME, confidence=0.99),
            WorldState(page=Page.MAP, confidence=0.99),
        ]
        with TemporaryDirectory() as temp:
            episode_path = Path(temp) / "episodes.jsonl"
            LiveRuntime(
                device=device,
                vision=FakeVision(states),
                semantic_vision=FakeSemantic(),
                capture_dir=Path(temp) / "captures",
                sleeper=lambda _seconds: None,
                episode_store=EpisodeStore(episode_path),
            ).run(max_actions=1, allowed_skills={"OPEN_MAP"})
            rows = episodes_at(episode_path)

        self.assertEqual(rows[0]["goal_id"], "AUTO_DISCOVERY")

    def test_the_named_task_mode_still_wins_over_the_commitment(self):
        """``brain.current_goal`` is a launch contract and must not be relabelled.

        The four routes that have a named task mode record their evidence under it;
        letting the committed goal override it would move that evidence.
        """
        from winter_agent_v2.brain import RuleBrain

        with TemporaryDirectory() as temp:
            runtime = LiveRuntime(
                device=FakeDevice(),
                vision=FakeVision([]),
                semantic_vision=FakeSemantic(),
                capture_dir=Path(temp),
                brain=RuleBrain(current_goal="TRAIN"),
                sleeper=lambda _seconds: None,
            )
            runtime._committed_goal = "KEEP_MARCHES_PRODUCTIVE"
            self.assertEqual(runtime._step_goal(None), "TRAIN")


if __name__ == "__main__":
    unittest.main()
