"""Gate a replacement template for the city daily-entry button over the corpus.

`BTN_OPEN_DAILY` is the tap target for `OPEN_DAILY` (HOME -> DAILY).  On
2026-09-16T13:10Z the live client answered `SEMANTIC_TARGET_NOT_VERIFIED` for it:
the registered crop was taken on 2026-09-08 and scores distance 18 against
today's frame while the other city buttons still hit (exploration d=0, mail
d=8..20 with its own higher gate, alliance d=8).

Two things changed between the two frames and this tool measures how much each
one costs:

* the red claimable badge that sat on the icon's top-right is gone;
* the city behind the button is a different city (level/season).

The candidate crops below are cut from the *live* frame and evaluated against
the whole corpus, not against their own parent, because a template that is only
ever compared with the frame it was cut from proves nothing (distance 0 is
circular).

Reported per candidate:
  * hits among frames where the city/HUD bottom-nav button also matches -- that is
    recall.  The proxy is deliberately described as "HUD frames", not "city frames":
    the city and the world map share the same left button column and bottom nav, and
    the daily-entry icon is drawn on BOTH (measured 2026-09-16), so the proxy cannot
    separate them.
  * hits among all other frames, each one classified with the production page
    classifier and printed for manual review -- that is the false-positive surface,
    which matters because `OPEN_DAILY` taps whatever this semantic resolves to.

Read-only.

Usage
-----
    python tools/probe_daily_entry_gate.py
    python tools/probe_daily_entry_gate.py --corpus dataset/raw --threshold 8
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from winter_agent_v2.image_hash import hamming, phash  # noqa: E402

MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"

# Provenance frames: today's live HOME frame (no badge) and the 2026-09-08 frame
# the current template was cut from (badge present).
LIVE_HOME = ROOT / "dataset" / "raw" / "live_runtime" / "live_runtime_step_002_before_20260916T131040296670.png"
LIVE_HOME2 = ROOT / "dataset" / "raw" / "live_runtime" / "live_runtime_step_001_after_20260916T131031271889.png"
OLD_PARENT = ROOT / "dataset" / "raw" / "live_20260908_offline_after.png"

# Candidate regions, normalized (x, y, w, h).
# The icon's circle is centred on (0.0583, 0.8219) with a radius of ~32 px.
CANDIDATES: dict[str, tuple[float, float, float, float]] = {
    # whole circle, badge area included
    "full_circle": (10 / 720, 1022 / 1280, 64 / 720, 64 / 1280),
    # lower band of the circle: starts below the badge's bottom edge (y=1039)
    "lower_band": (12 / 720, 1040 / 1280, 60 / 720, 46 / 1280),
    # left half of the circle -- the scroll artwork, badge corner excluded
    "left_half": (12 / 720, 1026 / 1280, 38 / 720, 58 / 1280),
}

SAVE_DIR = ROOT / "dataset" / "probe_output" / "daily_entry"


def crop_for(frame: Path, rect: tuple[float, float, float, float]) -> Image.Image:
    x, y, w, h = rect
    with Image.open(frame) as image:
        width, height = image.size
        bounds = (
            round(x * width), round(y * height),
            round((x + w) * width), round((y + h) * height),
        )
        return image.convert("RGB").crop(bounds)


def best_record_distance(frame: Path, rows: list[dict]) -> int | None:
    scored: list[int] = []
    for row in rows:
        path = Path(row["template_path"])
        if not path.exists():
            continue
        try:
            with Image.open(row["template_path"]) as template:
                target = phash(template)
            scored.append(hamming(phash(crop_for(frame, (
                row["roi_norm"]["x_norm"], row["roi_norm"]["y_norm"],
                row["roi_norm"]["w_norm"], row["roi_norm"]["h_norm"],
            ))), target))
        except Exception:
            continue
    return min(scored) if scored else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default="dataset/raw")
    parser.add_argument("--threshold", type=int, default=8)
    args = parser.parse_args()

    import json

    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rows = payload["records"]
    daily_rows = [r for r in rows if r["semantic"] == "BTN_OPEN_DAILY"]
    nav_rows = [r for r in rows if r["semantic"] == "BTN_OPEN_EXPLORATION"]

    source = LIVE_HOME if LIVE_HOME.exists() else LIVE_HOME2
    templates: dict[str, object] = {}
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    print("source frame:", source.name)
    for name, rect in CANDIDATES.items():
        crop = crop_for(source, rect)
        crop.save(SAVE_DIR / f"candidate__{name}.png")
        templates[name] = phash(crop)
        print(f"  candidate {name:<12} size={crop.size}")

    print("\nprovenance frames (min distance per semantic):")
    for label, frame in [("live 2026-09-16", LIVE_HOME),
                         ("live 2026-09-16 (2)", LIVE_HOME2),
                         ("2026-09-08 parent", OLD_PARENT)]:
        if not frame.exists():
            print(f"  {label:<20} MISSING")
            continue
        parts = [f"existing={best_record_distance(frame, daily_rows)}"]
        for name, rect in CANDIDATES.items():
            parts.append(f"{name}={hamming(phash(crop_for(frame, rect)), templates[name])}")
        print(f"  {label:<20} " + "  ".join(parts))

    corpus = Path(args.corpus)
    if not corpus.is_absolute():
        corpus = ROOT / corpus
    frames = sorted(corpus.rglob("*.png"))
    print(f"\ncorpus={corpus} frames={len(frames)} threshold={args.threshold}")

    home_proxy: list[Path] = []
    other: list[Path] = []
    per_candidate: dict[str, Counter] = {name: Counter() for name in CANDIDATES}
    per_candidate["existing"] = Counter()
    home_hits: dict[str, list[Path]] = {name: [] for name in CANDIDATES}
    home_hits["existing"] = []
    other_hits: dict[str, list[Path]] = {name: [] for name in CANDIDATES}
    other_hits["existing"] = []

    for frame in frames:
        try:
            with Image.open(frame) as image:
                width, height = image.size
        except Exception:
            continue
        if width < 400:
            continue
        d_nav = best_record_distance(frame, nav_rows)
        is_home = d_nav is not None and d_nav <= args.threshold
        (home_proxy if is_home else other).append(frame)

        results: dict[str, int | None] = {
            "existing": best_record_distance(frame, daily_rows)
        }
        for name, rect in CANDIDATES.items():
            try:
                results[name] = hamming(phash(crop_for(frame, rect)), templates[name])
            except Exception:
                results[name] = None
        for name, distance in results.items():
            if distance is None:
                continue
            bucket = home_hits if is_home else other_hits
            if distance <= args.threshold:
                bucket[name].append(frame)
                per_candidate[name]["hit"] += 1
            else:
                per_candidate[name]["miss"] += 1

    print(f"\nHUD-proxy frames (BTN_OPEN_EXPLORATION <= {args.threshold}): {len(home_proxy)}")
    print(f"frames without that nav button                           : {len(other)}")
    print("\ncandidate                recall(hud)   hits(outside)   misses(hud)")
    for name in ["existing"] + list(CANDIDATES):
        rec = len(home_hits[name])
        fp = len(other_hits[name])
        miss = len(home_proxy) - rec
        pct = (rec / len(home_proxy) * 100) if home_proxy else 0.0
        print(f"  {name:<14} {rec:>6} ({pct:5.1f}%) {fp:>14} {miss:>14}")

    # Hits outside the proxy are not automatically false positives: the proxy only
    # sees frames where that one nav button resolves.  Classify each one and print
    # it, so the verdict is "which page was it", not "the count was small".
    review = sorted({f for name in CANDIDATES for f in other_hits[name]}
                    | set(other_hits["existing"]))
    if review:
        from winter_agent_v2.vision import SemanticWorldVision

        vision = SemanticWorldVision(MANIFEST, max_distance=args.threshold)
        print(f"\nhits outside the proxy, classified ({len(review)} frame(s)):")
        for frame in review:
            if not frame.is_file():
                continue
            try:
                page = vision.observe(frame).page.value
            except Exception as exc:  # pragma: no cover - diagnostic only
                page = f"ERROR:{type(exc).__name__}"
            which = [name for name in list(CANDIDATES) + ["existing"]
                     if frame in other_hits[name]]
            print(f"   {frame.relative_to(ROOT)}  page={page}  matches={which}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
