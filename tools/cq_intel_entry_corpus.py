"""Build and measure the OPEN_INTEL recognition corpus (positives + negatives).

Work order WB-R19-OPEN-INTEL-MAA-RECOVERY requires >=3 independent positives and
>=3 negatives before any route change, and forbids fixing this by lowering a
threshold.  So this script:

1. assembles positives (every frame the runtime saw while it decided OPEN_INTEL on
   a MAP page) and negatives (frames from episodes whose page was NOT MAP, where
   the control must not be reported);
2. scores each with the search-based ccoeff matcher over the right HUD band;
3. prints the two distributions and the gap, so the threshold is chosen from
   measurement rather than taste.

Read-only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from winter_agent_v2.matchers import match_ccoeff  # noqa: E402

TEMPLATE = ROOT / "dataset/candidate/intel_wild_entry_v2/btn_open_intel_wild_hud__wild_fresh_before__0.png"
BAND = {"x_norm": 0.70, "y_norm": 0.28, "w_norm": 0.30, "h_norm": 0.62}

EXTRA_POSITIVES = [
    "dataset/raw/control_panel/runtime_auto/intel_pins_20260915_230510_nav_00/intel_pins_20260915_230510_nav_00_step_002_before_20260915T230548379879.png",
    "dataset/raw/control_panel/runtime_auto/intel_pins_20260915_230510_nav_00/intel_pins_20260915_230510_nav_00_step_001_before_20260915T230612978098.png",
    "dataset/raw/control_panel/runtime_auto/intel_pins_20260915_230510_nav_00/intel_pins_20260915_230510_nav_00_step_001_before_20260915T230638196592.png",
    "dataset/raw/control_panel/runtime_auto/intel_pins_20260915_230917_nav_01/intel_pins_20260915_230917_nav_01_step_004_before_20260915T231036773155.png",
    "dataset/raw/control_panel/runtime_auto/intel_pins_20260915_230917_nav_01/intel_pins_20260915_230917_nav_01_step_001_before_20260915T231108075082.png",
    "dataset/raw/control_panel/runtime_auto/intel_pins_20260915_230917_nav_01/intel_pins_20260915_230917_nav_01_step_001_before_20260915T231134984875.png",
    "dataset/raw/live_runtime/live_runtime_step_001_before_20260915T133445437576.png",
    "dataset/raw/control_panel/runtime_auto/codex_0ba_0bb_live_20260915/codex_0ba_0bb_live_20260915_step_005_before_20260915T123128206616.png",
]


def episodes() -> list[dict]:
    path = ROOT / "learning/episodes.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def norm(path_text: str) -> Path | None:
    if not path_text:
        return None
    candidate = Path(path_text)
    if not candidate.is_absolute():
        candidate = ROOT / path_text
    return candidate if candidate.exists() else None


def main() -> int:
    rows = episodes()

    # Positives: frames the runtime observed on MAP just before an OPEN_INTEL decision.
    positives: dict[str, str] = {}
    for row in rows:
        if row.get("skill") != "OPEN_INTEL":
            continue
        before = (row.get("state_before") or {}).get("page")
        if before != "MAP":
            continue
        path = norm(row.get("before_screenshot") or "")
        if path is not None:
            positives[path.name] = str(path)

    # Negatives: frames whose recorded page is NOT MAP.  The control lives on the
    # world-map HUD, so on any other page it must not be reported.
    negatives: dict[str, tuple[str, str]] = {}
    for row in rows:
        page = (row.get("state_before") or {}).get("page")
        if not page or page == "MAP":
            continue
        path = norm(row.get("before_screenshot") or "")
        if path is not None:
            negatives.setdefault(path.name, (str(path), page))

    for rel in EXTRA_POSITIVES:
        path = ROOT / rel
        if path.exists():
            positives.setdefault(path.name, str(path))

    def score(path_text: str) -> tuple[float, tuple[float, float]]:
        found = match_ccoeff(Path(path_text), TEMPLATE, BAND)
        return (found.score, found.center_norm) if found else (0.0, (0.0, 0.0))

    print("POSITIVES (%d)" % len(positives))
    p_scores: list[float] = []
    for name, path_text in sorted(positives.items()):
        value, centre = score(path_text)
        p_scores.append(value)
        print("  %5.3f @ (%.4f, %.4f)  %s" % (value, centre[0], centre[1], name[:64]))

    print()
    print("NEGATIVES (%d)" % len(negatives))
    n_scores: list[float] = []
    for name, (path_text, page) in sorted(negatives.items()):
        value, centre = score(path_text)
        n_scores.append(value)
        print("  %5.3f @ (%.4f, %.4f)  page=%-12s %s" % (value, centre[0], centre[1], page, name[:52]))

    print()
    if p_scores and n_scores:
        print("positive min = %.3f   negative max = %.3f   gap = %.3f"
              % (min(p_scores), max(n_scores), min(p_scores) - max(n_scores)))
        print("distance at ccoeff score: (1-s)*64 -> positive max %d, negative min %d"
              % (round((1 - min(p_scores)) * 64), round((1 - max(n_scores)) * 64)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
