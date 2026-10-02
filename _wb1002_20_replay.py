"""Acceptance on the four frames the refusals were decided on, with the point drawn.

The ledger cannot be replayed by itself here: the tab centres were never recorded, which is the
defect.  So the replay goes frame -> production observation -> resolver, and then draws the point
the resolver returns so it can be looked at -- the project's own rule for a click target.

    .venv/Scripts/python.exe _wb1002_20_replay.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

RUNS = {
    "20261002_182040_468682": (
        "step_003_before_20261002T102114362188.png",
        "step_004_before_20261002T102121466286.png",
    ),
    "20261002_182322_031915": (
        "step_004_before_20261002T102416498776.png",
        "step_005_before_20261002T102423277816.png",
    ),
}
TARGET = "MEAT"
OUT = ROOT / "out/resource_tab_point"


def the_failures():
    path = ROOT / "learning" / "episodes.jsonl"
    size = path.stat().st_size
    with path.open("rb") as stream:
        stream.seek(max(0, size - 6_000_000))
        for line in stream.read().decode("utf-8", "replace").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if (row.get("skill") == "SELECT_RESOURCE" and row.get("result") == "FAILURE"
                    and str(row.get("repo_revision") or "").startswith("76a5e90")):
                yield row


def main() -> int:
    from PIL import Image, ImageDraw

    from tests.live_stack import production_vision
    from winter_agent_v2.runtime import LiveRuntime

    print("the refusals this is answering:")
    for row in the_failures():
        state = row.get("state_before") or {}
        print(f"   {str(row.get('recorded_at'))[11:19]}  target={state.get('resource_target')}  "
              f"kinds={state.get('resource_tab_kinds')}  offset={state.get('resource_tab_offset')}  "
              f"duration={row.get('duration'):.2f}s  after_frame={bool(row.get('after_screenshot'))}")
    print()

    vision = production_vision()
    if vision is None:
        print("production OCR stack unavailable")
        return 1

    class _DeadGeometry:
        """The measured geometry layer on these frames: nothing resolved."""

        resource_tab_offset = None
        anchored_tab_kind = None

        def resource_cell_center_norm(self, _resource):
            return None

    runtime = object.__new__(LiveRuntime)
    runtime.semantic_vision = _DeadGeometry()

    OUT.mkdir(parents=True, exist_ok=True)
    resolved = 0
    total = 0
    for episode, names in RUNS.items():
        for name in names:
            frame_path = ROOT / "dataset/raw/control_panel/runtime_auto" / episode / f"{episode}_{name}"
            total += 1
            if not frame_path.is_file():
                print(f"   {name[:34]}  FRAME MISSING")
                continue
            observed = vision.observe(frame_path)
            point = runtime._resolve_semantic_target("RESOURCE_DYNAMIC", observed, resource=TARGET)
            centres = dict(getattr(observed, "resource_tab_label_norm", {}) or {})
            print(f"   {name[:34]}  page={observed.page.value} panel={observed.resource_search_open} "
                  f"kinds={observed.resource_tab_kinds}")
            print(f"      centres={{{', '.join(f'{k}: ({v[0]:.4f}, {v[1]:.4f})' for k, v in sorted(centres.items()))}}}")
            print(f"      resolved {TARGET} -> {point}")
            if point is None:
                continue
            resolved += 1
            with Image.open(frame_path) as opened:
                image = opened.convert("RGB")
                width, height = image.size
                draw = ImageDraw.Draw(image)
                x, y = round(point[0] * width), round(point[1] * height)
                draw.line((x - 22, y, x + 22, y), fill=(255, 0, 0), width=3)
                draw.line((x, y - 22, x, y + 22), fill=(255, 0, 0), width=3)
                dest = OUT / f"{name.replace('.png', '')}_point.png"
                # The strip, so the drawing can be read without the whole frame.
                image.crop((0, round(0.64 * height), width, round(0.78 * height))).resize(
                    (width * 2, round(0.14 * height) * 2)).save(dest)
            print(f"      wrote {dest.relative_to(ROOT)}  (tap pixel {x},{y} of {width}x{height})")
    print()
    print(f"frames that now resolve the tab they wanted: {resolved}/{total}")
    return 0 if resolved == total and total else 1


if __name__ == "__main__":
    raise SystemExit(main())
