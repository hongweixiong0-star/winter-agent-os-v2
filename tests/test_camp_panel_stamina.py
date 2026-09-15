"""Can the camp panel afford the fight?  Measure it; do not guess.

The Hero Journey camp panel (英雄之旅, a 探险 ⚡10 button) is a **map overlay**:
the world-map HUD stays on screen behind it, so the stamina gauge sits at
exactly the position it does on ``Page.MAP``.

Measured 2026-09-15 on ``dataset/truth_audit/stamina_check_live_20260915``:

* ``01_hero_camp_panel_before_live.png`` -- the camp panel -- and
  ``03_map_before_free_stamina_check_live.png`` -- the map -- both return
  ``('9', 0.999)`` from ``HUD_STAMINA_ROI`` (px 28, 96, 70, 120), character for
  character identical.
* production ``HybridVision.observe`` returned ``stamina={}`` for the camp
  panel and ``{'current': 9, 'source': 'MAP_HUD'}`` for the map, because only
  ``Page.MAP`` / ``Page.RESOURCE_DETAIL`` were OCR-enriched.  The reading was
  measured and then thrown away.

What that cost, from the same live run (``live_run_records.json``, goal INTEL,
``2026-09-15T03:03:57Z``):

    step 1  before  EXPLORATION, exploration={'stamina_cost_displayed': 10},
                    stamina={}                       <- the number was not read
            action  TAP_SEMANTIC BTN_HERO_CAMP_FIGHT
            after   POPUP / GET_MORE_STAMINA          <- the client refused
            verify  ok=true OK                        <- recorded as a fight
                    {"camp_panel": true, "left_panel": true, "after_page": "POPUP"}

The run then spent its remaining three actions opening the stamina panel,
finding no free gift, and backing out.  Four actions, nothing achieved.

``runtime.py`` returns as soon as a verifier fails (``runtime.py:676``), so now
that the refusal is recorded honestly the run would die on step 1 instead --
which is why the gate below has to exist: an unattended loop that starts on a
fight it cannot afford must go and get stamina, not tap the button and die.

Both halves are pinned here: the read (``CampPanelStaminaIsReadTests``) and the
decision (``CampFightAffordabilityGateTests``).
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from tests.live_stack import production_vision

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.skills import v2_registry

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "dataset" / "truth_audit" / "stamina_check_live_20260915"
CAMP_PANEL_FRAME = ARCHIVE / "01_hero_camp_panel_before_live.png"
MAP_FRAME = ARCHIVE / "03_map_before_free_stamina_check_live.png"
# The idle-income exploration page: EXPLORATION with no displayed cost, so the
# camp-panel read must leave it alone.
IDLE_EXPLORATION_FRAME = ROOT / "dataset" / "raw" / "live_exploration_after_claim.png"

CAMP_COST = 10

# A world map frame with a readable stamina readout: the precondition for the
# once-per-run free-stamina check, which is where the affordability gate has to
# deliver the run.
MAP_WITH_STAMINA = WorldState(
    page=Page.MAP,
    march_used=1,
    march_max=6,
    stamina={"current": 9, "source": "MAP_HUD"},
    resource_search_open=False,
    confidence=0.99,
)


def _camp_panel(stamina: dict | None) -> WorldState:
    """The live frame's own state, with the stamina read under test."""
    return WorldState(
        page=Page.EXPLORATION,
        intel={"status": "AVAILABLE", "mission_type": "HERO_JOURNEY", "mission_level": 10},
        exploration={"status": "AVAILABLE", "stamina_cost_displayed": CAMP_COST},
        stamina=stamina or {},
        confidence=0.99,
    )


class CampPanelStaminaIsReadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.vision = production_vision()
        if cls.vision is None:
            raise unittest.SkipTest("OCR runtime unavailable")
        for frame in (CAMP_PANEL_FRAME, MAP_FRAME, IDLE_EXPLORATION_FRAME):
            if not frame.is_file():
                raise unittest.SkipTest(f"missing fixture {frame}")

    def test_the_camp_panel_reads_the_same_number_as_the_map(self) -> None:
        camp = self.vision.observe(CAMP_PANEL_FRAME)
        world_map = self.vision.observe(MAP_FRAME)

        self.assertEqual(camp.stamina.get("current"), 9)
        self.assertEqual(world_map.stamina.get("current"), 9)
        self.assertEqual(camp.stamina["current"], world_map.stamina["current"])

    def test_the_read_names_the_page_it_came_from(self) -> None:
        """A distinct source, so the episode says where the number was read."""
        camp = self.vision.observe(CAMP_PANEL_FRAME)
        self.assertEqual(camp.stamina.get("source"), "CAMP_PANEL_HUD")

    def test_the_read_does_not_disturb_the_page_or_its_cost(self) -> None:
        """The brain routes on these two fields, so they must survive."""
        camp = self.vision.observe(CAMP_PANEL_FRAME)
        self.assertIs(camp.page, Page.EXPLORATION)
        self.assertEqual(camp.exploration.get("stamina_cost_displayed"), CAMP_COST)
        self.assertEqual(camp.intel.get("mission_type"), "HERO_JOURNEY")

    def test_the_idle_income_page_gains_nothing(self) -> None:
        """Negative control: no displayed cost, so no camp-panel read."""
        idle = self.vision.observe(IDLE_EXPLORATION_FRAME)
        self.assertIs(idle.page, Page.EXPLORATION)
        self.assertIsNone(idle.exploration.get("stamina_cost_displayed"))
        self.assertNotEqual(idle.stamina.get("source"), "CAMP_PANEL_HUD")


class CampFightAffordabilityGateTests(unittest.TestCase):
    def _decide(self, world: WorldState, *, claim_free_stamina: bool = True) -> tuple:
        brain = RuleBrain(current_goal="INTEL", claim_free_stamina=claim_free_stamina)
        return brain, brain.decide(world, v2_registry())

    def test_an_unaffordable_camp_panel_goes_for_the_free_stamina(self) -> None:
        brain, decision = self._decide(_camp_panel({"current": 9, "source": "CAMP_PANEL_HUD"}))

        self.assertEqual(decision.skill, "BACK")
        self.assertEqual(decision.reason, "camp_fight_unaffordable_go_get_free_stamina")
        self.assertTrue(brain.unaffordable_camp_panel_left)
        # And it must NOT touch the map's flag: that flag gates the free-stamina
        # check, and this decision exists to send the run to it.
        self.assertFalse(brain.stamina_panel_checked)

    def test_the_route_really_reaches_the_free_stamina_check(self) -> None:
        """The point of the Back, asserted end to end.

        This is the check that catches the tempting wrong guard: reusing
        ``stamina_panel_checked`` for the camp panel would set it on the Back
        and silently cancel the very check the Back was taken for, leaving a
        run that walks to the map and does nothing.
        """
        brain = RuleBrain(current_goal="INTEL", claim_free_stamina=True)
        brain.decide(_camp_panel({"current": 9, "source": "CAMP_PANEL_HUD"}), v2_registry())

        on_map = brain.decide(MAP_WITH_STAMINA, v2_registry())
        self.assertEqual(on_map.skill, "OPEN_STAMINA_SOURCES")
        self.assertEqual(on_map.reason, "free_stamina_gift_not_yet_checked_this_run")

    def test_a_back_that_lands_on_home_still_walks_to_the_map_and_checks(self) -> None:
        """Both measured Back destinations converge on the same check."""
        brain = RuleBrain(current_goal="INTEL", claim_free_stamina=True)
        brain.decide(_camp_panel({"current": 9, "source": "CAMP_PANEL_HUD"}), v2_registry())

        home = brain.decide(WorldState(page=Page.HOME, confidence=0.99), v2_registry())
        self.assertEqual(home.skill, "OPEN_MAP")
        on_map = brain.decide(MAP_WITH_STAMINA, v2_registry())
        self.assertEqual(on_map.skill, "OPEN_STAMINA_SOURCES")

    def test_the_free_gift_is_pursued_only_once_per_run(self) -> None:
        brain, first = self._decide(_camp_panel({"current": 9, "source": "CAMP_PANEL_HUD"}))
        self.assertEqual(first.skill, "BACK")

        # Same frame, same run: the panel was already accounted for, so there is
        # nothing left to try and the run must stop rather than burn actions.
        second = brain.decide(_camp_panel({"current": 9, "source": "CAMP_PANEL_HUD"}), v2_registry())
        self.assertEqual(second.skill, "SAFE_STOP")
        self.assertEqual(second.reason, "camp_fight_unaffordable_and_free_gift_already_checked")

    def test_without_the_operator_directive_it_stops_instead_of_leaving(self) -> None:
        brain, decision = self._decide(
            _camp_panel({"current": 9, "source": "CAMP_PANEL_HUD"}), claim_free_stamina=False
        )
        self.assertEqual(decision.skill, "SAFE_STOP")
        self.assertEqual(decision.reason, "camp_fight_unaffordable_and_free_gift_already_checked")
        self.assertFalse(brain.stamina_panel_checked)
        self.assertFalse(brain.unaffordable_camp_panel_left)

    def test_an_affordable_camp_panel_still_starts_the_fight(self) -> None:
        for current in (CAMP_COST, CAMP_COST + 1, 150):
            with self.subTest(current=current):
                _, decision = self._decide(_camp_panel({"current": current, "source": "CAMP_PANEL_HUD"}))
                self.assertEqual(decision.skill, "INTEL_HERO_START_MARCH")
                self.assertEqual(decision.reason, "intel_hero_camp_panel")

    def test_an_unread_stamina_never_invents_an_affordability_verdict(self) -> None:
        """No reading is not a zero reading.

        The client is the only authority on whether the fight is affordable; a
        missing read must leave the attempt in place (and the honest refusal
        verifier then says what happened), not silently block a fight that was
        payable.
        """
        for stamina in (None, {}, {"source": "CAMP_PANEL_HUD"}, {"current": None}):
            with self.subTest(stamina=stamina):
                _, decision = self._decide(_camp_panel(stamina))
                self.assertEqual(decision.skill, "INTEL_HERO_START_MARCH")


class TheUnattendedLoopKeepsTheOperatorCheckTests(unittest.TestCase):
    """``config/v2.json`` asks for the free gift; the loop must not opt out."""

    def test_the_operator_config_still_asks_for_the_free_gift(self) -> None:
        config = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
        self.assertIs(config["stamina_policy"]["claim_free_stamina"], True)
        note = config["stamina_policy"]["note"]
        self.assertIn("丰盛的招待", note)
        self.assertIn("BTN_CLAIM_FREE_STAMINA", note)

    def test_the_pin_loop_does_not_disable_the_free_stamina_check(self) -> None:
        """``--no-stamina-check`` was a workaround for a bug that is fixed.

        It was added to ``run_intel_pins.py`` on 2026-09-14 to stop "repeated
        failed claim attempts", i.e. episodes recorded as
        ``failure_type=STAMINA_SOURCES_NOT_OPEN`` while the skill recorded was
        ``OPEN_INTEL`` and ``state_after.page`` was ``INTEL`` -- a *correct*
        action recorded as a failure.  That is the one-decision-per-step bug
        (``tests/test_one_decision_per_step.py``), and it is fixed.

        The flag never even stopped the noise for the other callers: failures
        of that shape were still recorded at 2026-09-14T23:37 and
        2026-09-15T02:31, both after the flag landed.

        The assertion is structural -- it reads the argv the loop hands to
        ``subprocess.run`` -- because the file is *supposed* to explain the flag
        in a comment, and a text search cannot tell an explanation from a use.
        """
        source = (ROOT / "tools" / "run_intel_pins.py").read_text(encoding="utf-8")
        argv_blocks = re.findall(r"\[\s*sys\.executable.*?\]", source, re.DOTALL)
        self.assertTrue(argv_blocks, "the loop must invoke tools/run_live.py")
        for block in argv_blocks:
            with self.subTest(argv=block[:120]):
                self.assertNotIn(
                    "--no-stamina-check",
                    block,
                    "the unattended intel loop must let the operator's free-stamina check run",
                )


if __name__ == "__main__":
    unittest.main()
