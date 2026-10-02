"""WB-1002-22 probe.

Question: on the live frame where OPEN_BUILDING_UPGRADE failed, does the frame itself declare
where the upgrade control is, and does the MAA template node even look there?

Read-only: production vision reader (no device), production routing table, no writes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent
FRAME = ROOT / (
    "dataset/raw/control_panel/runtime_auto/20261002_184532_133866/"
    "20261002_184532_133866_step_003_before_20261002T104606635912.png"
)


def node_roi(skill: str, semantic: str):
    from winter_agent_v2.executor_router import RoutingTable

    table = RoutingTable.load()
    node = table.recognition_node(skill, semantic)
    return node


def main() -> int:
    from PIL import Image

    with Image.open(FRAME) as image:
        width, height = image.size
    print(f"frame {FRAME.name}")
    print(f"  size {width}x{height}")
    print()

    node = node_roi("OPEN_BUILDING_UPGRADE", "BTN_SELECTED_BUILDING_UPGRADE")
    roi = node.get("roi") if node else None
    print("routing node for OPEN_BUILDING_UPGRADE / BTN_SELECTED_BUILDING_UPGRADE")
    print(f"  kind={node.get('kind')} template={node.get('template')} threshold={node.get('threshold')}")
    print(f"  roi={roi}")
    if roi:
        x, y, w, h = (int(v) for v in roi)
        print(f"  roi in pixels  x {x}..{x + w}   y {y}..{y + h}")
        print(f"  roi normalised x {x / width:.4f}..{(x + w) / width:.4f}"
              f"   y {y / height:.4f}..{(y + h) / height:.4f}")
    print()

    # What does the frame itself say?  Use the sanctioned production stack, not a
    # hand-built reader -- the building identity lives in HybridVision (ocr.py), and the
    # semantic layer alone silently answers "no building".
    sys.path.insert(0, str(ROOT / "tests"))
    from live_stack import production_vision

    vision = production_vision()
    if vision is None:
        print("production_vision() unavailable -- refusing to answer from a lesser reader")
        return 1
    state = vision.observe(FRAME)
    building = state.building or {}
    print("the frame's own reading")
    print(f"  page            {state.page}")
    print(f"  building.name   {building.get('name')}")
    print(f"  building.level  {building.get('level')} -> {building.get('target_level')}")
    print(f"  identity_source {building.get('identity_source')}")
    print(f"  identity_conf   {building.get('identity_confidence')}")
    print(f"  upgrade_tap_norm {building.get('upgrade_tap_norm')}")
    point = building.get("upgrade_tap_norm")
    if isinstance(point, (list, tuple)) and len(point) == 2 and roi:
        px, py = float(point[0]) * width, float(point[1]) * height
        x, y, w, h = (int(v) for v in roi)
        inside = (x <= px <= x + w) and (y <= py <= y + h)
        print(f"  that point in pixels ({px:.0f}, {py:.0f})")
        print(f"  INSIDE the node's roi? {inside}")
    print()

    # And what does the resolver actually answer?
    from winter_agent_v2.models import Page
    from winter_agent_v2.runtime import LiveRuntime

    runtime = object.__new__(LiveRuntime)
    runtime.semantic_vision = vision
    runtime._frame_semantic = None
    point = LiveRuntime._resolve_semantic_target(
        runtime, "BTN_SELECTED_BUILDING_UPGRADE", state, frame_path=FRAME
    )
    print("runtime._resolve_semantic_target('BTN_SELECTED_BUILDING_UPGRADE')")
    print(f"  -> {point}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
