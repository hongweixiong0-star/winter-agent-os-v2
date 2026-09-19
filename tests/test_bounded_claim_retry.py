"""One claim attempt, then the panel is left.  A live livelock, and its bound.

Measured 2026-09-19, from the episode stream: the client sat on the ``GET_MORE_STAMINA`` popup
with ``free_claim_available: true`` while the loop chose ``CLAIM_FREE_STAMINA`` every ~45 seconds

    05:07:57  goal=CLEAR_INTEL              skill=CLAIM_FREE_STAMINA
    05:10:09  goal=CLEAR_INTEL              skill=CLAIM_FREE_STAMINA
    05:10:55  goal=KEEP_TRAINING_PRODUCTIVE skill=CLAIM_FREE_STAMINA
    05:11:44  goal=KEEP_TRAINING_PRODUCTIVE skill=CLAIM_FREE_STAMINA
    05:12:30  goal=KEEP_TRAINING_PRODUCTIVE skill=CLAIM_FREE_STAMINA
    05:13:15  goal=KEEP_RESEARCH_PRODUCTIVE skill=CLAIM_FREE_STAMINA

six times, across three different goals, and the popup never changed -- the episode carried no
verification, so nothing was proved.  Worse than a wasted action: this branch precedes every goal
route, so the goals that had asked to go somewhere else never got their turn, and the sweep the
whole change exists for could not reach the intel, training or research pages at all.

A second sighting of the same unclaimed panel is evidence that tapping it does not work, so the
honest response is to stop and leave.  This is the operator's §六 "不出现重复选择同一个无进展 Goal
的死循环", and the bound is the smallest one that can work: one attempt per run.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.brain import RuleBrain  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402


def popup(free: bool) -> WorldState:
    return WorldState(page=Page.POPUP, popup="GET_MORE_STAMINA",
                      stamina={"free_claim_available": free}, confidence=0.99)


def test_the_first_sighting_still_claims():
    """The branch exists to claim a free gift; it must keep doing that."""
    decision = RuleBrain().decide(popup(True), v2_registry())
    assert decision.skill == "CLAIM_FREE_STAMINA"
    assert decision.reason == "free_stamina_gift_claimable"


def test_the_second_sighting_leaves_instead_of_tapping_again():
    brain = RuleBrain()
    brain.decide(popup(True), v2_registry())
    second = brain.decide(popup(True), v2_registry())
    assert second.skill == "BACK", "a tap that did not change the panel cannot fix it by repeating"
    assert "still_unclaimed" in second.reason
    assert second.expected_result == "map_restored"


def test_it_leaves_every_time_after_that_rather_than_alternating():
    """The bound must be one attempt total, not one per goal or one per pair of sightings."""
    brain = RuleBrain()
    brain.decide(popup(True), v2_registry())
    for _ in range(4):
        assert brain.decide(popup(True), v2_registry()).skill == "BACK"


def test_a_panel_without_a_free_gift_is_unchanged():
    decision = RuleBrain().decide(popup(False), v2_registry())
    assert decision.skill == "BACK"
    assert decision.reason == "stamina_panel_without_a_free_gift"


def test_the_counter_is_per_run_not_per_goal():
    """A new run starts fresh: the panel may genuinely be claimable again next cycle."""
    first = RuleBrain()
    first.decide(popup(True), v2_registry())
    assert first.decide(popup(True), v2_registry()).skill == "BACK"
    assert RuleBrain().decide(popup(True), v2_registry()).skill == "CLAIM_FREE_STAMINA"
