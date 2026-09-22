"""A run that has looked everywhere stops; it does not walk back and forth.

Measured 2026-09-23.  Since 16:00Z, **18 of 75 runs** were nothing but ``OPEN_MAP`` / ``OPEN_HOME`` /
``OPEN_MAP``: the client went to the map, came home, and went to the map again, and the run ended
having observed nothing and changed nothing.  ``tools/replay_run_decisions.py`` reproduces run
``20260923_062948_568906`` 3/3 on the recorded frames with the production reader and the production
brain, and names both emitters:

    HOME -> MAP   OPEN_MAP    brain.decide            first_ready_p0_skill
    MAP  -> HOME  OPEN_HOME   runtime._deferral_replan deferred_..._left_nothing_to_do_here
    HOME -> MAP   OPEN_MAP    brain.decide            first_ready_p0_skill

Two layers, opposite directions, each right on its own and neither aware of the other.  The tests
below pin the rule that ends it, and the four edges of that rule.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2 import observation_store  # noqa: E402
from winter_agent_v2.capability_gate import DEFERRED, Deferral  # noqa: E402
from winter_agent_v2.models import Decision, Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.runtime_snapshot import NON_FATAL_STOPS, is_fatal_stop  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402

LOOK_AROUND = LiveRuntime.PAGE_HOPS_THAT_ONLY_LOOK_FOR_GOALS
STOPPED = LiveRuntime.NOTHING_LEFT_TO_LOOK_AT


def _runtime() -> LiveRuntime:
    """A runtime with only what the guard reads (no device, no run)."""
    runtime = object.__new__(LiveRuntime)
    runtime._barren_pages = set()
    runtime.registry = v2_registry()
    runtime.brain = SimpleNamespace(current_goal=None)
    return runtime


def _decide(runtime: LiveRuntime, page: Page, skill: str, *, goal=None) -> Decision:
    decision = Decision(skill, f"{skill}_asked_for", 0.9, "whatever")
    return runtime._stop_instead_of_looking_again(
        WorldState(page=page, confidence=0.99), decision, goal
    )


class TheMeasuredChainTest(unittest.TestCase):
    """The three hops of the recorded run, taken in its own order.

    The rule cuts one step earlier than the recorded run's third hop: the moment the run is on the
    map with nothing there and HOME already looked at, the hop home is a repeat too, and the honest
    answer is the stop.  So the chain becomes two steps, not three -- the second of the recorded hops
    is where the walk ends.
    """

    def test_the_hop_back_is_where_the_walk_ends(self):
        runtime = _runtime()
        # step 1, 22:30:26, HOME: nothing selectable, so the fallback aims at the map, and the map is
        # the one page this run has not looked at.
        first = _decide(runtime, Page.HOME, "OPEN_MAP")
        self.assertEqual(first.skill, "OPEN_MAP", "the first look-around is what looking is")
        # step 2, 22:31:28, MAP: nothing here either, and HOME was already found fruitless.
        second = _decide(runtime, Page.MAP, "OPEN_HOME")
        self.assertEqual(second.skill, "SAFE_STOP")
        self.assertEqual(second.reason, STOPPED)
        self.assertEqual(second.expected_result, "no_action", "a stop issues no input")

    def test_the_walk_is_symmetric(self):
        """Starting on the map instead of the city must not change the answer."""
        runtime = _runtime()
        self.assertEqual(_decide(runtime, Page.MAP, "OPEN_HOME").skill, "OPEN_HOME")
        self.assertEqual(_decide(runtime, Page.HOME, "OPEN_MAP").skill, "SAFE_STOP")

    def test_the_pages_the_run_found_nothing_on_are_the_ones_that_matter(self):
        runtime = _runtime()
        self.assertEqual(runtime._barren_pages, set())
        _decide(runtime, Page.HOME, "OPEN_MAP")
        self.assertEqual(runtime._barren_pages, {"HOME"},
                         "the page the run was standing on when nothing was selectable is the finding")
        _decide(runtime, Page.MAP, "OPEN_HOME")  # refused, so MAP is not recorded by the refusal
        self.assertEqual(runtime._barren_pages, {"HOME"})
        _decide(runtime, Page.MAP, "CHECK_MARCH")
        self.assertEqual(runtime._barren_pages, {"HOME", "MAP"},
                         "reading the map is what records it -- refused hops do not")


class TheEdgesTest(unittest.TestCase):
    """Each of the four edges is a deliberate boundary, so each gets its own case."""

    def test_a_hop_carrying_a_goal_is_untouched(self):
        """``OPEN_MAP`` for a committed INTEL route is that route's business, not a look-around."""
        runtime = _runtime()
        runtime._barren_pages = {"HOME", "MAP"}
        goal = SimpleNamespace(goal_id="CLEAR_INTEL")
        decision = _decide(runtime, Page.HOME, "OPEN_MAP", goal=goal)
        self.assertEqual(decision.skill, "OPEN_MAP")
        self.assertEqual(decision.reason, "OPEN_MAP_asked_for",
                         "the guard must not rename a decision it did not make")
        self.assertEqual(runtime._barren_pages, {"HOME", "MAP"},
                         "and a step with a goal says nothing about the page's fruitfulness")

    def test_a_page_is_recorded_even_when_the_step_is_not_a_hop(self):
        runtime = _runtime()
        decision = _decide(runtime, Page.MAP, "CHECK_MARCH")
        self.assertEqual(decision.skill, "CHECK_MARCH")
        self.assertIn("MAP", runtime._barren_pages,
                      "reading the map and finding nothing is the same finding as hopping there")

    def test_a_destination_that_was_never_fruitless_is_still_worth_a_look(self):
        runtime = _runtime()
        runtime._barren_pages = {"ALLIANCE"}
        self.assertEqual(_decide(runtime, Page.MAP, "OPEN_HOME").skill, "OPEN_HOME")

    def test_only_the_two_look_around_hops_are_judged(self):
        """Every other skill is returned byte-for-byte, however empty the run is."""
        runtime = _runtime()
        runtime._barren_pages = {"HOME", "MAP"}
        for skill in ("SEARCH_RESOURCE", "TRY_ORDINARY_CONTROL", "CLOSE_POPUP", "SAFE_STOP"):
            with self.subTest(skill=skill):
                decision = _decide(runtime, Page.MAP, skill)
                self.assertEqual(decision.skill, skill)
                self.assertEqual(decision.reason, f"{skill}_asked_for")

    def test_the_table_says_what_the_two_names_mean(self):
        """Pinned against the registry rather than trusted as a literal.

        ``OPEN_MAP`` is the skill you can use *on HOME* and it lands on the map; ``OPEN_HOME`` is the
        one you can use *on MAP* and it lands in the city.  If either skill is moved to another page,
        this guard's idea of where the hop goes is wrong, and it must fail here rather than in the
        live stream.
        """
        registry = v2_registry()
        self.assertEqual(LOOK_AROUND, {"OPEN_MAP": "MAP", "OPEN_HOME": "HOME"})
        self.assertEqual(registry.get("OPEN_MAP").required_page, Page.HOME)
        self.assertEqual(registry.get("OPEN_HOME").required_page, Page.MAP)
        self.assertEqual(Page(LOOK_AROUND["OPEN_MAP"]), Page.MAP)
        self.assertEqual(Page(LOOK_AROUND["OPEN_HOME"]), Page.HOME)

    def test_the_stop_reason_is_registered_and_is_not_fatal(self):
        self.assertIn(STOPPED, NON_FATAL_STOPS)
        self.assertFalse(is_fatal_stop(STOPPED),
                         "a run that found nothing is not the device leaving, and must not be "
                         "classified as one")
        self.assertFalse(STOPPED.endswith(("_NOT_PROVEN", "_NOT_VERIFIED")),
                         "and it is not a UI-unread reason: nothing here was unreadable")


class _EverythingDeferred:
    """A gate that refuses every goal path, so the board is empty and the deferrals are not."""

    capabilities: dict = {}

    def blocks(self, goal, *, now=None):  # noqa: D102
        return Deferral(goal_id=goal.goal_id, state=DEFERRED,
                        reason="the test defers every path: nothing is selectable anywhere")


class _TwoPageClient:
    """The client as a state machine: the map button opens the map, the city door comes back."""

    #: Where each control sits, normalized.  Far apart on purpose: the device below tells them
    #: apart by which one the tap landed on, so the two must not share a neighbourhood.
    POINTS = {"PAGE_MAP": (0.10, 0.90), "BTN_OPEN_HOME": (0.90, 0.10)}
    SIZE = (720, 1280)

    def __init__(self):
        self.page = Page.HOME
        self.taps = []
        self.backs = []

    # --- the device the executor drives ---
    def screenshot(self, path):
        path.touch()
        return path

    def status(self):
        return type("Status", (), {"connected": True, "resolution": self.SIZE})()

    def tap(self, x, y):
        self.taps.append((x, y))
        width, height = self.SIZE
        landed = min(
            self.POINTS,
            key=lambda semantic: (x - self.POINTS[semantic][0] * width) ** 2
            + (y - self.POINTS[semantic][1] * height) ** 2,
        )
        self.page = Page.MAP if landed == "PAGE_MAP" else Page.HOME

    def press_back(self):
        self.backs.append(len(self.taps))

    def swipe(self, *args, **kwargs):
        self.taps.append("swipe")

    # --- the vision the run asks about it ---
    def observe(self, _path):
        return WorldState(page=self.page, confidence=0.99, march_used=1, march_max=6)

    # --- the semantic vision the executor asks for a point ---
    semantic = property(lambda self: self)
    resource_tab_band = (0.0, 1.0)
    resource_level_minus = (0.5, 0.5)
    resource_tab_offset = None

    def find(self, _path, semantic):
        if semantic not in self.POINTS:
            return None
        return type("Match", (), {"center_norm": self.POINTS[semantic]})()

    def resource_cell_center_norm(self, _resource):
        return (0.5, 0.5)

    def resource_tab_swipe_for(self, _resource):
        return 0.0


class TheWholeRunTest(unittest.TestCase):
    """The guard as it is reached in production, through ``LiveRuntime.run``.

    The recorded runs are ``best_goal is None`` on **both** pages *with deferrals present* -- that is
    what makes ``_deferral_replan`` speak, and it is why the map half of the walk is the runtime's and
    not the brain's.  So the goal engine here is real (it discovers goals from the frame) and the
    *gate* is the stub: it defers every one of them, which is precisely the scheduler state under
    test.  Nothing else is faked -- the client answers with the page its own taps produced, because a
    fake that ignored them would let the run bounce for a reason the real client cannot produce.
    """


    def _run(self, *, max_actions: int = 6):
        client = _TwoPageClient()
        with TemporaryDirectory() as temp:
            temp = Path(temp)
            empty = temp / "observations.json"
            empty.write_text("{}", encoding="utf-8")
            previous = observation_store.STATE_PATH
            observation_store.STATE_PATH = empty
            try:
                runtime = LiveRuntime(
                    device=client,
                    vision=client,
                    semantic_vision=client,
                    capture_dir=temp / "captures",
                    sleeper=lambda _seconds: None,
                    episode_store=None,
                    capability_gate=_EverythingDeferred(),
                )
                result = runtime.run(
                    max_actions=max_actions,
                    allowed_skills=frozenset({"OPEN_MAP", "OPEN_HOME", "BACK"}),
                )
            finally:
                observation_store.STATE_PATH = previous
        return client, result

    def test_a_run_with_nothing_anywhere_stops_instead_of_bouncing(self):
        client, result = self._run()
        skills = [step.decision.skill for step in result.steps]
        # Asserted on the shape rather than on the whole list: which *reading* the run asks for on the
        # map is the registry's business, and this test is about the hop.  What must hold is that the
        # run never goes home and that it ends on its own answer.
        self.assertEqual(skills[0], "OPEN_MAP", f"it starts by looking at the map; it took {skills}")
        self.assertNotIn("OPEN_HOME", skills,
                         f"nothing anywhere means the hop home is not worth taking; it took {skills}")
        self.assertEqual(skills[-1], "SAFE_STOP", f"and it ends there; it took {skills}")
        self.assertEqual(result.stop_reason, STOPPED)
        self.assertEqual(len(client.taps), 1,
                         "one tap: the look at the map.  The second hop must not be taken")
        self.assertEqual(client.page, Page.MAP,
                         "and the client is left where it was last known to have nothing, not "
                         "mid-hop")

    def test_the_run_reaches_the_hop_that_the_recorded_one_reached(self):
        """The chain is the recorded one, so the guard is being asked the recorded question.

        Without this, a run that stopped for some other reason would pass the test above.
        """
        client, result = self._run()
        self.assertTrue(result.deferrals, "the recorded runs deferred, and so must this one")
        self.assertEqual(str(result.steps[0].decision.reason), "first_ready_p0_skill",
                         "the city half of the walk is the brain's goal-less fallback")
        hopped = [step.decision.reason for step in result.steps
                  if step.decision.reason.startswith("deferred_")]
        self.assertEqual(hopped, [], "and the map half is refused, so it is never taken")

    def test_the_unguarded_client_would_have_bounced(self):
        """Negative control, run through the same client: the bounce is real, not imagined.

        The three recorded hops, issued directly, leave the client back on the map with three taps
        spent -- which is what the twenty-step run in the stream ends with.
        """
        client = _TwoPageClient()
        for semantic in ("PAGE_MAP", "BTN_OPEN_HOME", "PAGE_MAP"):
            nx, ny = _TwoPageClient.POINTS[semantic]
            client.tap(nx * 720, ny * 1280)
        self.assertEqual(len(client.taps), 3)
        self.assertEqual(client.page, Page.MAP)
        self.assertEqual(client.backs, [], "no Back was pressed: the walk is all taps")


class TheGateIsAtTheOneCallSiteTest(unittest.TestCase):
    """The guard is only worth having where the loop consults it.

    A rule that nothing calls is the failure this project keeps finding, so the call site is asserted
    rather than remembered: ``run`` must consult it on the same decision the ``SAFE_STOP`` branch
    below it acts on.
    """

    def test_the_loop_consults_the_guard_before_it_acts_on_a_stop(self):
        source = (ROOT / "winter_agent_v2/runtime.py").read_text(encoding="utf-8")
        decides = source.index("decision = leave if leave is not None else self.brain.decide(")
        guarded = source.index("decision = self._stop_instead_of_looking_again(")
        acts = source.index('if decision.skill == "SAFE_STOP":', guarded)
        self.assertLess(decides, guarded,
                        "it guards the decision, so it has to run after the decision is made")
        self.assertLess(guarded, acts,
                        "and before anything acts on it, or a stop it invents is never honoured")


if __name__ == "__main__":
    unittest.main()
