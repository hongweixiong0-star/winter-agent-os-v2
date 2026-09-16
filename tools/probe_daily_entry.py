"""Why does OPEN_DAILY fail on the live HOME frame?

`run_live.py --goal DAILY` on 2026-09-16T13:10Z got as far as HOME (verifier OK)
and then `OPEN_DAILY` was rejected with `SEMANTIC_TARGET_NOT_VERIFIED`: the
executor could not resolve the semantic `BTN_OPEN_DAILY` on that frame.

This probe answers the only question that matters before changing anything:
*is the daily entry actually drawn on that frame, and where?*  It reports the
raw best distance for the semantic (not the thresholded answer), saves the
registered ROI as a crop next to the full frame, and prints the page the live
vision stack classified.

Usage:
    python tools/probe_daily_entry.py [frame.png ...]

With no arguments it uses the newest frames under dataset/raw/live_runtime/.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402
from winter_agent_v2.image_hash import hamming, phash  # noqa: E402

MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"
OUT = ROOT / "dataset" / "probe_output" / "daily_entry"

SEMANTICS = [
    "BTN_OPEN_DAILY",
    "BTN_OPEN_EXPLORATION",
    "BTN_OPEN_MAIL",
    "BTN_OPEN_ALLIANCE",
]


def newest_frames(limit: int = 2) -> list[Path]:
    d = ROOT / "dataset" / "raw" / "live_runtime"
    if not d.is_dir():
        return []
    rows = sorted(d.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    return rows[:limit]


def main(argv: list[str]) -> int:
    frames = [Path(a) for a in argv[1:]] or newest_frames()
    if not frames:
        print("no frames found")
        return 1

    vision = SemanticWorldVision(MANIFEST)
    semantic = vision.semantic
    OUT.mkdir(parents=True, exist_ok=True)

    for frame in frames:
        print("=" * 78)
        print("frame :", frame)
        with Image.open(frame) as image:
            width, height = image.size
        print("size  :", width, "x", height)

        world = vision.observe(frame)
        print("page  :", world.page, "popup:", world.popup,
              "daily:", world.daily)

        for name in SEMANTICS:
            rows = [r for r in semantic.records if r["semantic"] == name]
            if not rows:
                print(f"  {name:<26} NOT IN MANIFEST")
                continue
            best = None
            for row in rows:
                roi = row["roi_norm"]
                bounds = (
                    round(roi["x_norm"] * width),
                    round(roi["y_norm"] * height),
                    round((roi["x_norm"] + roi["w_norm"]) * width),
                    round((roi["y_norm"] + roi["h_norm"]) * height),
                )
                with Image.open(frame) as image:
                    if row.get("matcher") == "ccoeff":
                        from winter_agent_v2.matchers import match_ccoeff
                        found = match_ccoeff(
                            frame, Path(row["template_path"]),
                            row.get("search_band") or roi,
                            margin=0 if row.get("search_band") else 40,
                        )
                        if found is None:
                            print(f"  {name:<26} ccoeff UNEVALUABLE "
                                  f"(template {row['template_path'].split('/')[-1]})")
                            continue
                        distance = int(round((1.0 - found.score) * 64))
                        extra = f" score={found.score:.4f} bounds={found.bounds}"
                    else:
                        with Image.open(row["template_path"]) as template:
                            distance = hamming(phash(image.crop(bounds)),
                                               phash(template))
                        extra = ""
                    threshold = semantic.semantic_max_distance.get(
                        name, semantic.max_distance)
                    tag = "HIT " if distance <= threshold else "MISS"
                    print(f"  {name:<26} {tag} d={distance:<3} "
                          f"thr={threshold} roi={roi}{extra}")
                    if best is None or distance < best[1]:
                        best = (row, distance)
                    crop = image.crop(bounds)
                    safe = frame.stem.replace("/", "_")
                    crop.save(OUT / f"{safe}__{name}__{distance}.png")

            if best is not None:
                row, distance = best
                print(f"  -> best template: {row['template_path'].split('/')[-1]}"
                      f"  source={row.get('source')}"
                      f"  parent={Path(row['parent_screenshot']).name}")

    print("=" * 78)
    print("crops written to:", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
