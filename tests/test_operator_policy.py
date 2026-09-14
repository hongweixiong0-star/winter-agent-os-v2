"""Operator march/resource policy must be encoded, not implied.

Policy change, 2026-09-14: stamina was full, so stamina spending (INTEL, beasts)
must beat gathering, rewards must be claimed promptly, and gathering is only
allowed to use march slots with no better use.

Before this change `march_policy.reserve_for_stamina` was 0, which let gathering
occupy **all six** march slots.  The march policy already *described* recall-on-
demand, but a description in a config comment changes no behaviour — so these
tests pin the numbers the runtime reads.

Two blockers are deliberately recorded here rather than hidden, because the
config alone cannot produce the requested behaviour:

1. `world.stamina` is never populated.  No STAMINA template exists and the only
   writer is an OCR read of a number on the Intel page, so on the world map the
   agent cannot observe "stamina is full" and cannot choose a stamina sink.
2. `RECALL_MARCH` is registered but absent from `LiveRuntime.VERIFIED_ATOMIC`
   (it has no verifier), so the loop can never dispatch a recall.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONFIG = ROOT / "config/v2.json"


@pytest.fixture(scope="module")
def config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def test_gathering_cannot_occupy_every_march_slot(config: dict) -> None:
    """reserve_for_stamina = 0 was the defect: gathering ate all six slots."""
    reserve = config["march_policy"]["reserve_for_stamina"]
    assert reserve >= 2, (
        f"reserve_for_stamina={reserve}: gathering may take every march slot, so a "
        "stamina task can never run without recalling first"
    )


def test_stamina_spending_is_declared_before_gathering(config: dict) -> None:
    policy = config["resource_policy"]
    assert policy["gather_priority"] == "LAST_RESORT"
    assert policy["stamina_first"] is True
    assert policy["claim_rewards_promptly"] is True
    # The stamina order must still list the verified sinks, in priority order.
    assert config["operations_policy"]["stamina_order"] == ["INTEL", "GIANT_BEAST", "BEAST_HUNT"]


def test_recall_priority_lists_the_stamina_sinks(config: dict) -> None:
    order = config["march_policy"]["recall_priority"]
    assert config["march_policy"]["recall_on_demand"] is True
    for sink in ("INTEL", "GIANT_BEAST", "BEAST_HUNT"):
        assert sink in order, f"{sink} missing from recall_priority"


def test_brain_stops_gathering_when_only_reserved_slots_remain(config: dict) -> None:
    """The reserve must actually change a decision, not just be written down."""
    from winter_agent_v2.brain import RuleBrain
    from winter_agent_v2.models import Page, WorldState
    from winter_agent_v2.skills import v2_registry

    reserve = int(config["march_policy"]["reserve_for_stamina"])
    world = WorldState(page=Page.MAP, march_used=6 - reserve, march_max=6, confidence=0.99)
    decision = RuleBrain(current_goal=None, reserve_marches=reserve).decide(world, v2_registry())
    assert decision.reason == "reserved_march_for_stamina", (
        f"with only {reserve} free slot(s) the brain chose {decision.skill}/{decision.reason} "
        "instead of preserving them for stamina spending"
    )


def test_stamina_observation_and_recall_are_the_open_blockers() -> None:
    """Record the two blockers explicitly so they cannot be forgotten.

    If either assertion starts failing, the blocker has been solved and this test
    should be replaced with a positive check of the new capability.
    """
    from winter_agent_v2.runtime import LiveRuntime

    assert "RECALL_MARCH" not in LiveRuntime.VERIFIED_ATOMIC, (
        "RECALL_MARCH is now dispatchable — update 03_NEXT_ACTION.md and replace this "
        "blocker test with a capability test"
    )
    manifest = json.loads((ROOT / "dataset/candidate/template_manifest.json").read_text(encoding="utf-8"))
    semantics = {str(row.get("semantic", "")) for row in manifest["records"]}
    assert not {name for name in semantics if "STAMINA" in name}, (
        "a STAMINA template now exists — stamina may be observable, so the "
        "AVOID_STAMINA_WASTE goal can be discovered from the map; update the handoff"
    )
