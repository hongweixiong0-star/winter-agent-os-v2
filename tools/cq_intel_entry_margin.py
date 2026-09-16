"""Measure the RAW best distance on both populations, past the threshold.

``find`` returns the best match only when it is inside the threshold, so the
replay can say "0 false positives" but not "how close did a negative come".  A
threshold chosen without that number is a guess.  This raises the threshold for
measurement only -- nothing on disk is changed -- and reports the distributions.
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
    semantic = vision.semantic
    print("configured threshold:", semantic.semantic_max_distance.get(SEMANTIC))
    semantic.semantic_max_distance[SEMANTIC] = 999  # measurement only

    positives: dict[str, str] = {}
    negatives: dict[str, str] = {}
    for row in load():
        page = (row.get("state_before") or {}).get("page")
        path = resolve(row.get("before_screenshot") or "")
        if not page or path is None:
            continue
        if row.get("skill") == "OPEN_INTEL" and page == "MAP":
            positives.setdefault(path.name, str(path))
        elif page != "MAP" and page not in MAP_DERIVED:
            negatives.setdefault(path.name, "%s|%s" % (path, page))

    def distances(paths: dict[str, str]) -> list[tuple[int, str]]:
        out = []
        for name, value in paths.items():
            match = semantic.find(Path(value.split("|")[0]), SEMANTIC)
            out.append((match.distance if match else 999, value))
        out.sort()
        return out

    pos = distances(positives)
    neg = distances(negatives)

    print()
    print("POSITIVE raw distances (worst 10):")
    for distance, value in pos[-10:]:
        print("   %3d  %s" % (distance, Path(value).name[:64]))
    print()
    print("NEGATIVE raw distances (best 10):")
    for distance, value in neg[:10]:
        print("   %3d  page=%-14s %s" % (distance, value.split("|")[1], Path(value.split("|")[0]).name[:48]))
    print()
    print("POSITIVE: n=%d  min=%d  median=%d  max=%d"
          % (len(pos), pos[0][0], pos[len(pos) // 2][0], pos[-1][0]))
    print("NEGATIVE: n=%d  min=%d  median=%d  max=%d"
          % (len(neg), neg[0][0], neg[len(neg) // 2][0], neg[-1][0]))
    print()
    print("separation: worst positive %d vs best negative %d -> gap %d"
          % (pos[-1][0], neg[0][0], neg[0][0] - pos[-1][0]))
    print("suggested threshold (midpoint): %d" % ((pos[-1][0] + neg[0][0]) // 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
