"""Why does live_train_marksman_tab_verify.png read INFANTRY?

Reads the three camp-title templates out of the manifest and measures each frame
directly, so the answer is a number rather than an inference.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

MANIFEST = ROOT / "dataset/candidate/template_manifest.json"
CAMP_TEMPLATES = ("PAGE_TRAINING_INFANTRY", "PAGE_TRAINING_LANCER", "PAGE_TRAINING_MARKSMAN")

FRAMES = [
    "live_train_selection_available.png",
    "live_train_lancer_tab.png",
    "live_train_lancer_tab_verify.png",
    "live_train_marksman_tab.png",
    "live_train_marksman_tab_verify.png",
]


def main() -> int:
    vision = SemanticWorldVision(MANIFEST)
    raw = ROOT / "dataset/raw"

    for name in FRAMES:
        path = raw / name
        if not path.exists():
            print(f"{name}: MISSING")
            continue
        # ``match`` is a closure inside observe; reach the layer it delegates to so
        # these are the same numbers the decision used, with no reimplementation.
        print(f"\n{name}")
        hits: list[tuple[str, float | None]] = []
        for tpl in CAMP_TEMPLATES:
            found = vision.semantic.find(path, tpl)
            hits.append((tpl, None if found is None else round(float(found.distance), 1)))
        for tpl, dist in hits:
            print(f"   {tpl:26s} d={dist}")
        real = [(tpl, dist) for tpl, dist in hits if dist is not None]
        if real:
            best = min(real, key=lambda pair: pair[1])
            print(f"   -> nearest = {best[0]}  d={best[1]}")
        else:
            print("   -> no camp title matched at all")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
