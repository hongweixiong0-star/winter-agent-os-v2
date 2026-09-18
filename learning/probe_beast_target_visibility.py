"""Why a verified beast target was not detected.  Read-only measurement.

For the most recent AVOID_STAMINA_WASTE attempts, print the raw dhash distance each beast
template reaches, where it reaches it, and what the frame was classified as -- so the cause
can be named from A..F instead of guessed:

  A TARGET_OUTSIDE_VIEWPORT   the sprite is nowhere in the searched region
  B MATCH_THRESHOLD_FAIL      it scores, but not under the threshold
  C ROI_WRONG                 the sprite matches, but outside anywhere_regions
  D MAP_SCALE_DRIFT           the sprite matches only at the wrong size
  E TARGET_KIND_MISMATCH      another species is on screen and only one is searched
  F TARGET_VISIBLE_BUT_SELECTOR_BUG  it matches under threshold, yet nothing selected
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from winter_agent_v2.image_hash import dhash, hamming  # noqa: E402
from winter_agent_v2.vision import SemanticROIVision, SemanticWorldVision  # noqa: E402

MANIFEST = ROOT / "dataset/candidate/template_manifest.json"
EPISODES = ROOT / "learning/episodes.jsonl"
BEAR_SEMANTICS = ("TARGET_BEAST_MUSK_OX_9", "TARGET_BEAST_MAMMOTH_5")


def recent_frames(limit: int = 3) -> list[str]:
    """The most recent before-screenshots from runs whose goal was the stamina goal."""
    out: list[tuple[str, str]] = []
    for line in EPISODES.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip().startswith("{"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(row.get("goal_id") or "") != "AVOID_STAMINA_WASTE":
            continue
        before = str(row.get("before_screenshot") or "")
        if before and Path(before).is_file():
            out.append((str(row.get("recorded_at")), before))
    out.sort()
    return [path for _stamp, path in out[-limit:]]


vision = SemanticROIVision(MANIFEST)
world = SemanticWorldVision(MANIFEST)
records = json.loads(MANIFEST.read_text(encoding="utf-8"))["records"]

print("thresholds")
for semantic in BEAR_SEMANTICS:
    print(f"  {semantic:26s} roi_threshold="
          f"{vision.semantic_max_distance.get(semantic, vision.max_distance)}"
          f"  anywhere_threshold={vision.anywhere_max_distance.get(semantic)}"
          f"  anywhere_region={vision.anywhere_regions.get(semantic)}")

frames = recent_frames(3)
print(f"\nframes: {len(frames)}")
for path in frames:
    print("=" * 78)
    print(path)
    with Image.open(path) as image:
        image = image.convert("RGB")
        width, height = image.size
    print(f"  frame size {width}x{height}")
    state = world.observe(Path(path))
    print(f"  classified as page={state.page} beast={state.beast}")

    for semantic in BEAR_SEMANTICS:
        rows = [r for r in records if r["semantic"] == semantic]
        if not rows:
            print(f"  {semantic}: NO TEMPLATE RECORD")
            continue
        x0, y0, x1, y1 = vision.anywhere_regions[semantic]
        best_global = None
        best_region = None
        for row in rows:
            with Image.open(row["template_path"]) as template:
                target = dhash(template, size=16)
                tw = template.width
                th = template.height
            # global sweep: the whole frame, same crop size as the registration
            with Image.open(path) as image:
                image = image.convert("RGB")
                step = max(4, round(width / 90))
                for y in range(0, max(1, height - th + 1), step):
                    for x in range(0, max(1, width - tw + 1), step):
                        d = hamming(target, dhash(image.crop((x, y, x + tw, y + th)), size=16))
                        if best_global is None or d < best_global[0]:
                            best_global = (d, x, y)
                        inside = (x0 * width <= x <= x1 * width) and (y0 * height <= y <= y1 * height)
                        if inside and (best_region is None or d < best_region[0]):
                            best_region = (d, x, y)
            print(f"  {semantic:26s} template {tw}x{th}")
            if best_global:
                print(f"      best global : d={best_global[0]:3d} at ({best_global[1]},{best_global[2]})"
                      f"  norm=({best_global[1]/width:.3f},{best_global[2]/height:.3f})")
            if best_region:
                print(f"      best in ROI : d={best_region[0]:3d} at ({best_region[1]},{best_region[2]})")
            else:
                print("      best in ROI : (nothing inside anywhere_regions)")
