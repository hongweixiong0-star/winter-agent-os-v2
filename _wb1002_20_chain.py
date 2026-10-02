"""What does the reading chain actually know about the resource strip on a real frame?

Four SELECT_RESOURCE steps on the deployed revision failed in 0.11-0.14 s with
`SEMANTIC_TARGET_NOT_VERIFIED`, and their own before-states say the odd thing:

    resource_search_open = True
    resource_target      = MEAT
    resource_tab_kinds   = ['BEAST', 'GIANT_GIANT', 'MEAT', 'WOOD']   <- MEAT is ON SCREEN
    resource_tab_offset  = None
    anchored_tab_kind    = None
    resource_selected_tab= None

So the identity layer knows the tab is there and the geometry layer resolves nothing.  This prints
every layer's answer on those frames, side by side with the tab centres a person can see.

    .venv/Scripts/python.exe _wb1002_20_chain.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

FRAMES = (
    ("step3", "dataset/raw/control_panel/runtime_auto/20261002_182040_468682/"
              "20261002_182040_468682_step_003_before_20261002T102114362188.png"),
    ("step4", "dataset/raw/control_panel/runtime_auto/20261002_182040_468682/"
              "20261002_182040_468682_step_004_before_20261002T102121466286.png"),
    ("L4", "dataset/raw/control_panel/runtime_auto/20261002_182322_031915/"
            "20261002_182322_031915_step_004_before_20261002T102416498776.png"),
    ("L5", "dataset/raw/control_panel/runtime_auto/20261002_182322_031915/"
            "20261002_182322_031915_step_005_before_20261002T102423277816.png"),
)


def main() -> int:
    from winter_agent_v2.ocr import RapidOCRBackend, read_resource_tab_labels
    from winter_agent_v2.vision import SemanticWorldVision

    world = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    semantic = world.semantic
    print(f"resource_tab_order : {semantic.resource_tab_order}")
    print(f"resource_tab_band  : {getattr(semantic, 'resource_tab_band', None)}")
    print(f"tab cell templates : {sorted(getattr(semantic, 'resource_tab_cell_templates', {}) or {})}")
    print()
    ocr = RapidOCRBackend()

    for label, relative in FRAMES:
        path = ROOT / relative
        print(f"== {label}  {path.name}")
        if not path.is_file():
            print("   frame missing\n")
            continue
        try:
            labels = read_resource_tab_labels(path, ocr) if _takes_ocr() else read_resource_tab_labels(path)
        except TypeError:
            labels = read_resource_tab_labels(path)
        print(f"   OCR tab labels        : {json.dumps(labels, ensure_ascii=False)}")
        print(f"   resource_tab_offset   : {semantic.resource_tab_offset}")
        print(f"   anchored_tab_kind     : {semantic.anchored_tab_kind}")
        print(f"   selected_resource     : {semantic.selected_resource}")
        for resource in ("MEAT", "WOOD", "COAL", "IRON", "BEAST", "GIANT_BEAST"):
            try:
                centre = semantic.resource_cell_center_norm(resource)
            except Exception as exc:  # noqa: BLE001
                centre = f"raised {type(exc).__name__}"
            print(f"   cell_center_norm({resource:<11}) : {centre}")
        print()


def _takes_ocr() -> bool:
    return False


if __name__ == "__main__":
    raise SystemExit(main())
