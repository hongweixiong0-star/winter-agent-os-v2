"""WB-1002-22 probe 2.

Run the production reader over every frame of the episode whose OPEN_BUILDING_UPGRADE step failed,
and ask which frames carry the building identity the ledger says the step had.

Also ask the gate directly: `_building_is_selected` on the failing before-frame.

Read-only.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

EPISODE = ROOT / "dataset/raw/control_panel/runtime_auto/20261002_184532_133866"


def main() -> int:
    from live_stack import production_vision

    vision = production_vision()
    if vision is None:
        print("production_vision() unavailable")
        return 1

    frames = sorted(EPISODE.glob("*.png"))
    print(f"{len(frames)} frames in {EPISODE.name}")
    print()
    print("%-62s %-12s %-8s %-6s %-8s %s" % ("frame", "page", "name", "lvl", "tgt", "upgrade_tap_norm"))
    for frame in frames:
        state = vision.observe(frame)
        building = state.building or {}
        point = building.get("upgrade_tap_norm")
        print("%-62s %-12s %-8s %-6s %-8s %s" % (
            frame.name[:62], str(state.page).split(".")[-1], str(building.get("name"))[:8],
            str(building.get("level")), str(building.get("target_level")), point,
        ))
    print()

    failing = EPISODE / "20261002_184532_133866_step_003_before_20261002T104606635912.png"
    print("the gate on the failing before-frame:")
    print(f"  _building_is_selected -> {vision._building_is_selected(failing)}")
    tokens = [t for t in vision.ocr.recognize(failing).tokens if t.confidence >= 0.80]
    print(f"  OCR tokens above 0.80: {len(tokens)}")
    for token in sorted(tokens, key=lambda t: -t.confidence)[:24]:
        centre = token.centre
        print("     %-14s conf=%.4f centre=(%.0f, %.0f) norm=(%.3f, %.3f)" % (
            token.text.strip()[:14], token.confidence, centre[0], centre[1],
            centre[0] / 720.0, centre[1] / 1280.0,
        ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
