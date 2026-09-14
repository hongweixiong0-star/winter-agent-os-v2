"""Report which pieces of the stamina/recall wiring are present and executable.

The project files are edited from two places at once, and an external editor has
repeatedly flushed a stale buffer over the tree, silently dropping changes that
a text grep still "finds" elsewhere.  This checks the *executable* surface
instead: imported objects, real decisions on real states, and the config the
runtime reads.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

problems: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(("OK   " if condition else "MISS "), label, detail)
    if not condition:
        problems.append(label)


def main() -> int:
    import dataclasses

    from winter_agent_v2 import models, ocr, runtime, skills, verifier, vision
    from winter_agent_v2.brain import RuleBrain
    from winter_agent_v2.models import MarchState, Page, WorldState

    check("WorldState.stamina field", "stamina" in {f.name for f in dataclasses.fields(WorldState)})
    check("WorldState.normal_idle_slots", "normal_idle_slots" in {f.name for f in dataclasses.fields(WorldState)})

    check("ocr.HUD_STAMINA_ROI", hasattr(ocr, "HUD_STAMINA_ROI"))
    check("ocr.MARCH_COUNT_ROI", hasattr(ocr, "MARCH_COUNT_ROI"))
    check("ocr.read_hud_stamina", hasattr(ocr, "read_hud_stamina"))
    check("ocr.parse_stamina_number", hasattr(ocr, "parse_stamina_number"))
    check("ocr.read_march_count", hasattr(ocr, "read_march_count"))

    geometry = vision.SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json").semantic
    check("semantic.stamina_gauge_center", hasattr(geometry, "stamina_gauge_center"))
    check("semantic.march_row_1_center", hasattr(geometry, "march_row_1_center"))

    for name in (
        "verify_march_recall_dialog_open",
        "verify_march_recalled",
        "verify_stamina_sources_open",
        "verify_free_stamina_claimed",
    ):
        check(f"verifier.{name}", hasattr(verifier, name))

    registered = {skill.id for skill in skills.v2_registry().all()}
    for skill_id in (
        "OPEN_STAMINA_SOURCES",
        "CLAIM_FREE_STAMINA",
        "SELECT_MARCH_TO_RECALL",
        "RECALL_MARCH",
    ):
        check(f"registry.{skill_id}", skill_id in registered)
        check(f"dispatchable.{skill_id}", skill_id in runtime.LiveRuntime.VERIFIED_ATOMIC)

    check("LiveRuntime.OPEN_INTEL verifier", runtime.LiveRuntime.VERIFIED_ATOMIC.get("OPEN_INTEL") is verifier.verify_open_intel)

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    check("config.stamina_policy.claim_free_stamina", config.get("stamina_policy", {}).get("claim_free_stamina") is True)
    check("config.march_policy.recall_on_demand", config.get("march_policy", {}).get("recall_on_demand") is True)
    check("config.reserve_for_stamina", int(config.get("march_policy", {}).get("reserve_for_stamina", 0)) >= 1,
          f"={config.get('march_policy', {}).get('reserve_for_stamina')}")

    registry = skills.v2_registry()

    def decide(state, **kwargs):
        return RuleBrain(**kwargs).decide(state, registry)

    panel_free = WorldState(page=Page.POPUP, popup="GET_MORE_STAMINA",
                            stamina={"current": 200, "free_claim_available": True}, confidence=0.99)
    panel_used = WorldState(page=Page.POPUP, popup="GET_MORE_STAMINA",
                            stamina={"current": 350, "free_claim_available": False}, confidence=0.99)
    check("brain: panel with free gift -> CLAIM_FREE_STAMINA",
          decide(panel_free).skill == "CLAIM_FREE_STAMINA")
    check("brain: panel without free gift -> BACK",
          decide(panel_used).skill == "BACK")

    dialog = WorldState(page=Page.POPUP, popup="MARCH_RECALL", confidence=0.99)
    check("brain: unexplained recall dialog -> CLOSE_POPUP",
          decide(dialog).skill == "CLOSE_POPUP")
    with_intent = RuleBrain(recall_on_demand=True)
    with_intent.pending_recall = True
    check("brain: recall dialog with intent -> RECALL_MARCH",
          with_intent.decide(dialog, registry).skill == "RECALL_MARCH")

    full = WorldState(page=Page.MAP, march_used=6, march_max=6,
                      marches=(MarchState.GATHERING,), confidence=0.99)
    check("brain: full queue freezes gathering when recall is off",
          decide(full).skill == "SAFE_STOP")
    check("brain: full queue recalls a gathering march when allowed",
          decide(full, recall_on_demand=True).skill == "SELECT_MARCH_TO_RECALL")

    map_ready = WorldState(page=Page.MAP, march_used=5, march_max=6,
                           marches=(MarchState.GATHERING,), stamina={"current": 350}, confidence=0.99)
    check("brain: map checks the free gift once per run",
          decide(map_ready, claim_free_stamina=True).skill == "OPEN_STAMINA_SOURCES")

    goals_source = (ROOT / "winter_agent_v2/goal_library.py").read_text(encoding="utf-8")
    check("goal_library reads world.stamina", "world.stamina" in goals_source)

    print(f"\nproblems: {len(problems)}")
    for name in problems:
        print("  -", name)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
