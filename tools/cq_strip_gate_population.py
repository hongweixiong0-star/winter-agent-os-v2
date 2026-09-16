"""Build the two populations the strip gate has to separate.

The gate is ``own <= 6.0 and runner_up - own >= 4.0``.  Measurement showed a live
frame where the geometry is demonstrably right (the bracket is on tab index 1, and
index 3 = 生肉 is visibly at the predicted x=486) and the only thing refused is the
absolute gate: own = 6.49 against a limit of 6.0.  The identity margin there is
8.00, twice the required 4.0, so discrimination is not the issue -- the ceiling is.

Before moving that ceiling, build the distributions it sits between:

  * CORRECT population   - a predicted position of tab T scored against template T;
  * WRONG population     - the SAME cell scored against the other templates, and
                           every non-templated tab (BEAST / 野兽 / 冰原巨兽) scored
                           against all templates.

The non-templated tabs matter most: three of the seven slots are snow-covered
creatures or huts and they are the false-positive risk if the ceiling is raised.
Every frame's offset is taken from its measured bracket, so nothing is assumed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from winter_agent_v2.vision import (  # noqa: E402
    SemanticWorldVision,
    _cell_signature,
    _cell_template_signature,
    _signature_distance,
)

MANIFEST = ROOT / "dataset/candidate/template_manifest.json"

# Frames with an explicit, verified anchor.  Using the first or smallest stroke pair
# is WRONG on the live frames: measured on 2026-09-15T23:37 the candidates are
# [37, 45, 115, 172, 261.5] and the real bracket is 172, not 37 -- taking the
# smallest produced a garbage offset and a garbage distribution on the first
# attempt at this script.  For the calibration frames the bracket is the only
# stroke pair, so the value is unambiguous; for the live frames it was established
# by inspection plus the check that the resulting predictions land on the tabs the
# frame visibly shows (MEAT predicted at 486, and 生肉 is there).
FRAMES = [
    ("resource_cells select_MEAT", "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_002_select_MEAT.png", 3, 87.0),
    ("resource_cells select_WOOD", "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_003_select_WOOD.png", 4, 244.0),
    ("resource_cells select_COAL", "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_004_select_COAL.png", 5, 402.0),
    ("resource_cells select_IRON", "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_005_select_IRON.png", 6, 559.0),
    ("availability select_MEAT", "dataset/truth_audit/resource_availability_20260914_124753/20260914_124753_select_MEAT.png", 3, 287.0),
    ("availability select_WOOD", "dataset/truth_audit/resource_availability_20260914_124753/20260914_124753_select_WOOD.png", 4, 444.0),
    ("live 233727 (bracket 172)", "dataset/raw/live_runtime/live_runtime_step_003_before_20260915T233727132656.png", 1, 172.0),
    ("live 233739 (bracket 172)", "dataset/raw/live_runtime/live_runtime_step_001_before_20260915T233739598714.png", 1, 172.0),
    ("live 160609 (bracket 282.5)", "dataset/raw/live_runtime/live_runtime_step_003_before_20260915T160609443785.png", 2, 282.5),
    ("good MEAT anchor 20260914", "dataset/raw/control_panel/runtime_auto/accept_20260914_142516_run01/accept_20260914_142516_run01_step_003_before_20260914T062618228437.png", 3, 87.0),
]


def main() -> int:
    vision = SemanticWorldVision(MANIFEST)
    semantic = vision.semantic
    templates = {
        name: [_cell_template_signature(Path(p)) for p in paths]
        for name, paths in semantic.resource_tab_cell_templates.items()
    }

    correct: list[tuple[float, str]] = []
    wrong_same_cell: list[tuple[float, str]] = []
    untemplated: list[tuple[float, str]] = []

    for title, rel, anchor_index, left in FRAMES:
        path = ROOT / rel
        if not path.exists():
            print("MISSING %s" % rel)
            continue
        with Image.open(path) as opened:
            image = opened.convert("RGB")
        width, height = image.size
        anchor = semantic.resource_tab_order[anchor_index]
        nominal = (semantic.resource_tab_first_left
                   + anchor_index * semantic.resource_tab_pitch) * width
        offset = left - nominal
        y0, y1 = semantic._tab_band_rows(height)
        cell_px = round(semantic.resource_tab_cell * width)
        print("%-38s bracket=%.1f anchor=%-12s offset=%+.1f" % (title, left, anchor, offset))

        for index, name in enumerate(semantic.resource_tab_order):
            x0 = round((semantic.resource_tab_first_left + index * semantic.resource_tab_pitch) * width + offset)
            if x0 < 0 or x0 + cell_px > width:
                continue
            probe = _cell_signature(image.crop((x0, y0, x0 + cell_px, y1)))
            distances = {
                other: min(_signature_distance(probe, s) for s in signatures)
                for other, signatures in templates.items()
            }
            own = distances.get(name)
            if name in templates:
                best_other = min(v for k, v in distances.items() if k != name)
                correct.append((own, "%s @ %s (own template)" % (title, name)))
                wrong_same_cell.append((best_other, "%s @ %s (right cell, %s template)"
                                        % (title, name, min(
                                            (v, k) for k, v in distances.items() if k != name)[1])))
            else:
                untemplated.append((min(distances.values()),
                                    "%s @ %s (%s vs nearest template %s)"
                                    % (title, name, name,
                                       min(distances.items(), key=lambda kv: kv[1])[0])))

    def summarise(name: str, values: list[tuple[float, str]]) -> None:
        if not values:
            print("%s: empty" % name)
            return
        values = sorted(values)
        print()
        print("%s: n=%d  min=%.2f  median=%.2f  max=%.2f"
              % (name, len(values), values[0][0], values[len(values) // 2][0], values[-1][0]))
        for value, label in values[-4:]:
            print("    highest: %6.2f  %s" % (value, label[:96]))

    print()
    print("=" * 78)
    summarise("CORRECT (predicted position vs its own template)", correct)
    summarise("WRONG (right cell, wrong template)", wrong_same_cell)
    summarise("WRONG (non-gatherable tab vs any template)", untemplated)

    print()
    print("=" * 78)
    if correct and untemplated:
        print("separating ceiling must satisfy: max(CORRECT) < gate < min(WRONG non-templated)")
        print("    max CORRECT          = %.2f" % max(v for v, _ in correct))
        print("    min WRONG untemplated= %.2f" % min(v for v, _ in untemplated))
        print("    currently configured = %.2f" % semantic.resource_tab_max_distance)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
