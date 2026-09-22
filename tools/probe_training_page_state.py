"""Read-only probe: what does the training page put into WorldState, and can the tab be located?

Answers the two things the camp-switch route needs before any code is written:
1. what ``WorldState.training`` actually carries on a TRAINING frame (so the verifier and the
   resolver can be written against measured keys rather than assumed ones);
2. whether the printed-word layer locates each of the three tabs on the live frame.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from live_stack import production_vision  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime, _declared_record  # noqa: E402

EVIDENCE = ROOT / "dataset/truth_audit/camp_action_bar_20260922"
TRAINING_FRAME = EVIDENCE / "training_page__three_camp_tabs_and_queue__live_20260921T0953.png"


def main() -> int:
    vision = production_vision()
    state = vision.observe(TRAINING_FRAME)
    print("frame:", TRAINING_FRAME.name)
    print("  page     :", state.page)
    print("  confidence:", round(float(state.confidence or 0), 3))
    print("  training :", state.training)
    print("  camps    :", state.camps)
    print("  quick_panel keys:", sorted((state.quick_panel or {}).keys()))
    print()

    print("the words the three tabs print, as the dictionary declares them:")
    for name in (
        "TRAINING_CAMP_TAB_SHIELD",
        "TRAINING_CAMP_TAB_LANCER",
        "TRAINING_CAMP_TAB_MARKSMAN",
        "BTN_START_TRAINING",
    ):
        print(f"  {name:28} -> _declared_record: {_declared_record(name)}")

    print()
    print("a bare resolver call, to see whether the layer would already locate them:")
    runtime = object.__new__(LiveRuntime)
    runtime.vision = vision
    runtime.semantic_vision = vision.template_vision
    runtime._control_ledger = {}
    runtime._remembered_reuse = []
    runtime._printed_remembered = set()
    runtime._printed_reads = []
    runtime._printed_printed = set()
    for name in (
        "TRAINING_CAMP_TAB_SHIELD",
        "TRAINING_CAMP_TAB_LANCER",
        "TRAINING_CAMP_TAB_MARKSMAN",
        "BTN_START_TRAINING",
    ):
        verdict, point = runtime._client_printed_control(name, state, TRAINING_FRAME)
        print(f"  {name:28} -> {verdict:10} {point}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
