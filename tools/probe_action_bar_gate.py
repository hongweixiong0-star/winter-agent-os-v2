"""Find a cheap pixel gate for "the client drew a selected building's action bar".

Why a gate is needed before the OCR pass, and not just the OCR pass.

``tests/test_ocr.py::test_hybrid_is_template_first`` pins a contract this codebase
kept until now: **a page the template layer fully resolves is not OCR'd**, because HOME
is the most common frame in the loop and an OCR pass on all of them would tax every
cycle for a reading that usually has nothing on it.  The measured 2026-09-22 regression
was exactly that -- reading the action bar on every HOME frame took the backend calls
from 0 to 1 -- so the reader must be gated on something cheap first.

No template can serve as the gate: on the action-bar frames every registered control
scores NO MATCH (measured, including ``BTN_UPGRADE``, which is the gate the 仓库 render
uses).  So the gate has to be pixels, the same way ``_quick_panel_is_drawn`` gates the
quick panel.

This probe measures candidate signals over the bar's own measured band, on the frames
that HAVE the bar and on HOME frames that do not, so a threshold is chosen from two
populations rather than from one.

    band      y 0.69-0.76, x 0.20-0.80   (where 详情/升级/训练 are drawn)
    signal    fraction of pixels whose MIN channel is above ``BRIGHT`` -- the three
              controls are pale plates on a dimmed city, which is what makes them bright
              where the city behind them is not.

Prints one row per frame; the two groups must not overlap for this to be usable.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BAND = {"x0": 0.20, "x1": 0.80, "y0": 0.69, "y1": 0.76}
BRIGHT = 185


def measure(path: Path) -> dict:
    with Image.open(path) as source:
        rgb = np.asarray(source.convert("RGB"))
    height, width = rgb.shape[:2]
    y0, y1 = int(BAND["y0"] * height), int(BAND["y1"] * height)
    x0, x1 = int(BAND["x0"] * width), int(BAND["x1"] * width)
    window = rgb[y0:y1, x0:x1].astype(int)
    minimum = window.min(axis=2)
    bright = (minimum >= BRIGHT).mean()
    return {
        "bright_fraction": round(float(bright), 4),
        "mean_min_channel": round(float(minimum.mean()), 1),
        "mean_luma": round(float(window.mean()), 1),
        "p99_min_channel": int(np.percentile(minimum, 99)),
    }


def positives() -> list[tuple[str, Path]]:
    rows = []
    for line in (ROOT / "learning/episodes.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            episode = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(episode.get("execution_mode")) != "PRODUCTION":
            continue
        if str(episode.get("skill")) != "NAVIGATE_INFANTRY_CAMP":
            continue
        recorded = str(episode.get("recorded_at") or "")
        if recorded < "2026-09-21T16:00" or not episode.get("after_screenshot"):
            continue
        rows.append((f"BAR  {recorded[11:16]}", Path(str(episode["after_screenshot"]))))
    return rows[:6]


def negatives() -> list[tuple[str, Path]]:
    """PRODUCTION frames that ended on HOME *without* the action bar.

    Half of them are the gold-ring render (a camp selected the old way) and the rest are
    ordinary city frames, because a gate tuned only against ordinary frames would fire on
    every camp selection and one tuned only against the ring would fire on nothing else.
    """
    rows = []
    for line in (ROOT / "learning/episodes.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            episode = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(episode.get("execution_mode")) != "PRODUCTION":
            continue
        if str(episode.get("skill")) == "NAVIGATE_INFANTRY_CAMP":
            continue
        after = episode.get("state_after") or {}
        if after.get("page") != "HOME" or not episode.get("after_screenshot"):
            continue
        recorded = str(episode.get("recorded_at") or "")
        rows.append((f"HOME {recorded[5:16]}", Path(str(episode["after_screenshot"]))))
    # Keep a spread rather than the first N: every frame a goal produces looks alike.
    return rows[::max(1, len(rows) // 8)][:8]


def main() -> int:
    print(f"band {BAND}  bright = min channel >= {BRIGHT}")
    for label, group in (("HAS THE BAR", positives()), ("NO BAR", negatives())):
        print("=" * 66)
        print(label)
        for tag, path in group:
            if not path.exists():
                print(f"   {tag}  MISSING ON DISK")
                continue
            stats = measure(path)
            print(f"   {tag}  bright={stats['bright_fraction']:.4f}"
                  f"  mean_min={stats['mean_min_channel']:>6}"
                  f"  mean_luma={stats['mean_luma']:>6}"
                  f"  p99_min={stats['p99_min_channel']:>4}"
                  f"  {path.name[-46:]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
