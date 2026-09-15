"""Measure which beast-identity templates fire on the shared 出征 formation page.

Read-only.  Answers one question with pixels: the formation page (``Page.MARCH``)
is shared by the map wilderness beast (麝牛 / level 9) and the intel beast
target (大角鹿 / level 22), and ``SemanticWorldVision`` reports a different beast
name/level depending on which template happened to match.  If those templates
are crops of *the same on-screen control* taken from two different live frames,
then the reported identity is decided by frame-to-frame pixel noise and is a
fabrication -- not a measurement.

The probe prints, for every (frame, semantic) pair, the perceptual-hash
distance, so the two populations can be compared directly instead of inferred
from a single run.

Usage::

    python tools/probe_beast_formation_identity.py
    python tools/probe_beast_formation_identity.py --frame <png> [--frame <png>]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from winter_agent_v2.image_hash import hamming, phash  # noqa: E402
from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"

# The four semantics that can decide the identity of the shared formation page.
IDENTITY_SEMANTICS = (
    "BTN_BEAST_DISPATCH_MUSK_OX_9",
    "BTN_BEAST_DISPATCH",
    "STATUS_VICTORY_ASSURED_MUSK_OX_9",
    "STATUS_VICTORY_ASSURED",
    "STATUS_BEAST_LOW_WIN_PROBABILITY",
    "PAGE_BEAST_MARCH",
)

# The two live frames the templates were cut from.
DEFAULT_FRAMES = (
    "dataset/raw/live_beast_march_selection.png",          # intel beast formation
    "dataset/raw/stamina_emergency/beast9_round3_march.png",  # wilderness 麝牛/9
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frame", action="append", default=[])
    args = parser.parse_args()

    frames = [Path(p) for p in (args.frame or DEFAULT_FRAMES)]
    frames = [p if p.is_absolute() else ROOT / p for p in frames]

    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    by_semantic: dict[str, list[dict]] = defaultdict(list)
    for row in payload["records"]:
        if row["semantic"] in IDENTITY_SEMANTICS:
            by_semantic[row["semantic"]].append(row)

    print("semantic                          parent                          roi(y,h)")
    for name in IDENTITY_SEMANTICS:
        for row in by_semantic.get(name, []):
            roi = row["roi_norm"]
            print(
                f"  {name:<32} {Path(row['parent_screenshot']).stem:<30} "
                f"({roi['y_norm']:.3f}, {roi['h_norm']:.3f})"
            )

    vision = SemanticWorldVision(MANIFEST, max_distance=8)

    for frame in frames:
        if not frame.exists():
            print(f"\nMISSING {frame}")
            continue
        print(f"\n=== {frame.relative_to(ROOT)}")
        state = vision.observe(frame)
        print(f"    production observe -> page={state.page.value} beast={state.beast}")
        with Image.open(frame) as image:
            width, height = image.size
            for name in IDENTITY_SEMANTICS:
                rows = by_semantic.get(name, [])
                if not rows:
                    print(f"    {name:<32} NOT IN MANIFEST")
                    continue
                best = None
                for row in rows:
                    template_path = Path(row["template_path"])
                    if not template_path.exists():
                        continue
                    roi = row["roi_norm"]
                    bounds = (
                        round(roi["x_norm"] * width),
                        round(roi["y_norm"] * height),
                        round((roi["x_norm"] + roi["w_norm"]) * width),
                        round((roi["y_norm"] + roi["h_norm"]) * height),
                    )
                    with Image.open(template_path) as template:
                        value = hamming(phash(image.crop(bounds)), phash(template))
                    best = value if best is None else min(best, value)
                threshold = vision.semantic.semantic_max_distance.get(name, 8)
                verdict = "MATCH" if best is not None and best <= threshold else "no match"
                print(f"    {name:<32} distance={best!s:<4} threshold={threshold:<3} {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
