"""Replay BTN_OPEN_INTEL_WILD_HUD recognition over the whole corpus.

This is the corpus gate the work order asks for.  It calls the real production
entry point (``SemanticWorldVision.semantic.find``) rather than a copy of it, so
a passing replay means the route the runtime uses is the route that was measured.

Frames are grouped by what is actually knowable from the episode record:
  * POSITIVE-MAP   - the runtime observed this frame on a MAP page and decided
                     OPEN_INTEL, so the control is the thing it was about to tap;
  * NEG-ABSENT     - the recorded page is not a world-map-derived page (INTEL,
                     popup, HOME, march, resource detail, alliance).  The world-map
                     HUD is not on screen, so reporting the control is a false
                     positive;
  * MAP-DERIVED    - BEAST and EXPLORATION keep the world-map HUD visible while
                     the page is not MAP.  The control really is on screen, so
                     these are reported separately and are not counted as false
                     positives -- they are also never asked for, because the skill
                     is gated on ``Page.MAP``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

MANIFEST = ROOT / "dataset/candidate/template_manifest.json"
SEMANTIC = "BTN_OPEN_INTEL_WILD_HUD"

# Frames confirmed by eye to show the control, from the two runs this order is about.
MUST_HIT = [
    "dataset/raw/control_panel/runtime_auto/intel_pins_20260915_230510_nav_00/intel_pins_20260915_230510_nav_00_step_002_before_20260915T230548379879.png",
    "dataset/raw/control_panel/runtime_auto/intel_pins_20260915_230510_nav_00/intel_pins_20260915_230510_nav_00_step_001_before_20260915T230612978098.png",
    "dataset/raw/control_panel/runtime_auto/intel_pins_20260915_230510_nav_00/intel_pins_20260915_230510_nav_00_step_001_before_20260915T230638196592.png",
    "dataset/raw/control_panel/runtime_auto/intel_pins_20260915_230917_nav_01/intel_pins_20260915_230917_nav_01_step_004_before_20260915T231036773155.png",
    "dataset/raw/control_panel/runtime_auto/intel_pins_20260915_230917_nav_01/intel_pins_20260915_230917_nav_01_step_001_before_20260915T231108075082.png",
    "dataset/raw/control_panel/runtime_auto/intel_pins_20260915_230917_nav_01/intel_pins_20260915_230917_nav_01_step_001_before_20260915T231134984875.png",
]

MAP_DERIVED = {"BEAST", "EXPLORATION"}


def load() -> list[dict]:
    path = ROOT / "learning/episodes.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def resolve(text: str) -> Path | None:
    if not text:
        return None
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = ROOT / text
    return candidate if candidate.exists() else None


def main() -> int:
    vision = SemanticWorldVision(MANIFEST)
    rows = load()

    groups: dict[str, dict[str, str]] = {"POSITIVE-MAP": {}, "NEG-ABSENT": {}, "MAP-DERIVED": {}}
    for row in rows:
        page = (row.get("state_before") or {}).get("page")
        if not page:
            continue
        path = resolve(row.get("before_screenshot") or "")
        if path is None:
            continue
        # Only frames the runtime was actually about to act on as OPEN_INTEL count
        # as positives.  "page == MAP" alone is not enough: a gather run, a cost
        # probe and a stamina panel all record page=MAP while showing a panel that
        # covers the HUD, and there the control is genuinely not visible -- calling
        # those misses would be measuring the wrong thing.
        if row.get("skill") == "OPEN_INTEL" and page == "MAP":
            groups["POSITIVE-MAP"].setdefault(path.name, str(path))
        elif page in MAP_DERIVED:
            groups["MAP-DERIVED"].setdefault(path.name, str(path))
        elif page != "MAP":
            groups["NEG-ABSENT"].setdefault(path.name, "%s|%s" % (str(path), page))

    for rel in MUST_HIT:
        path = ROOT / rel
        if path.exists():
            groups["POSITIVE-MAP"].setdefault(path.name, str(path))

    results: dict[str, list[tuple[int, tuple[float, float]]]] = {}
    for name, paths in groups.items():
        out: list[tuple[int, tuple[float, float]]] = []
        for key, value in sorted(paths.items()):
            target = value.split("|")[0]
            match = vision.semantic.find(Path(target), SEMANTIC)
            if match is None:
                out.append((999, (0.0, 0.0)))
            else:
                out.append((match.distance, match.center_norm))
        results[name] = out
        hit = sum(1 for distance, _ in out if distance != 999)
        print("%-14s frames=%3d  reported=%3d  distance: min=%3d max=%3d"
              % (name, len(out), hit,
                 min(d for d, _ in out) if out else -1,
                 max(d for d, _ in out) if out else -1))

    print()
    pos = results["POSITIVE-MAP"]
    neg = results["NEG-ABSENT"]
    print("POSITIVE-MAP misses:")
    for (name, value), (distance, centre) in zip(sorted(groups["POSITIVE-MAP"].items()), pos):
        if distance == 999:
            print("   MISS %s" % name[:70])
    print("POSITIVE-MAP distances > 8:")
    for (name, value), (distance, centre) in zip(sorted(groups["POSITIVE-MAP"].items()), pos):
        if distance != 999 and distance > 8:
            print("   %3d  %s" % (distance, name[:70]))
    print()
    print("NEG-ABSENT false positives (any reported match):")
    shown = 0
    for (name, value), (distance, centre) in zip(sorted(groups["NEG-ABSENT"].items()), neg):
        if distance != 999:
            print("   %3d @ (%.4f, %.4f) page=%-14s %s" % (distance, centre[0], centre[1], value.split("|")[1], name[:44]))
            shown += 1
    print("   total: %d" % shown)
    print()
    if pos and neg:
        worst_pos = max(d for d, _ in pos if d != 999) if any(d != 999 for d, _ in pos) else 999
        best_neg = min(d for d, _ in neg) if neg else 999
        print("worst POSITIVE distance = %d   best NEGATIVE distance = %s   separation = %s"
              % (worst_pos, best_neg if best_neg != 999 else "none reported",
                 (best_neg - worst_pos) if best_neg != 999 else "n/a"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
