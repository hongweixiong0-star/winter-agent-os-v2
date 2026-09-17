"""Corpus gate for the generic 获得奖励 dialog detector.

Why this exists
---------------
`winter_agent_v2/vision.py` now decides "this is the client's shared 获得奖励
dialog" from two source-independent signals -- the banner
(`POPUP_GENERIC_REWARD_HEADER`) and the footer `点击任意位置退出`
(`BTN_DISMISS_INTEL_REWARD`, whose name is a misnomer in the manifest: measured
on 103 labelled production frames it matches 102 of them at distance <= 2 and it
is present on every reward dialog whatever produced it).

Reporting GENERIC_REWARD for every reward dialog is only safe if those signals do
NOT also fire on ordinary frames: a false positive turns an ordinary page into
`page=POPUP, popup=GENERIC_REWARD`, and the brain would then run a reward dismiss
on a page that has no dialog at all.

This tool measures that negative surface over the whole corpus and prints every
hit whose own observation is *not* a reward popup.  Read-only.

Usage
-----
    python tools/probe_reward_popup_gate.py
    python tools/probe_reward_popup_gate.py --json out_reward_gate.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.models import Page  # noqa: E402
from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"
CORPUS = ROOT / "dataset" / "raw"

# The footer and the banner are the two source-independent signals the detector
# uses.  Both are measured here so a future change to either is visible.
SIGNALS = ("BTN_DISMISS_INTEL_REWARD", "POPUP_GENERIC_REWARD_HEADER")

# What a correct observation of a frame carrying this dialog looks like.
REWARD_POPUP = "GENERIC_REWARD"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=0,
                        help="stop after N frames (0 = no limit)")
    args = parser.parse_args()

    vision = SemanticWorldVision(MANIFEST)
    semantic = vision.semantic

    frames = sorted(CORPUS.rglob("*.png"))
    if args.limit:
        frames = frames[: args.limit]
    print(f"corpus frames: {len(frames)}")

    counts: Counter[str] = Counter()
    signal_hits: dict[str, list[str]] = {name: [] for name in SIGNALS}
    false_positives: list[dict[str, str]] = []
    observations: Counter[str] = Counter()

    for index, frame in enumerate(frames, 1):
        if index % 500 == 0:
            print(f"  ... {index}/{len(frames)}")
        try:
            hits = {name: semantic.find(frame, name) for name in SIGNALS}
        except Exception as exc:  # pragma: no cover - diagnostic only
            counts[f"error:{type(exc).__name__}"] += 1
            continue
        for name, hit in hits.items():
            if hit is not None:
                signal_hits[name].append(str(frame.relative_to(ROOT)))
        if not any(hit is not None for hit in hits.values()):
            continue
        counts["any_signal"] += 1
        try:
            state = vision.observe(frame)
        except Exception as exc:  # pragma: no cover - diagnostic only
            counts[f"observe_error:{type(exc).__name__}"] += 1
            continue
        observations[state.popup or f"<page={state.page.value}>"] += 1
        if not (state.page is Page.POPUP and state.popup == REWARD_POPUP):
            false_positives.append({
                "frame": str(frame.relative_to(ROOT)),
                "page": state.page.value,
                "popup": state.popup or "",
                "signals": ",".join(
                    f"{name}={hits[name].distance}"
                    for name in SIGNALS if hits[name] is not None
                ),
            })

    print()
    for name in SIGNALS:
        print(f"{name:<32} matched {len(signal_hits[name]):>5} frames")
    print(f"{'any signal':<32} {counts['any_signal']:>5} frames")
    print(f"{'observed as GENERIC_REWARD':<32} "
          f"{len(signal_hits['BTN_DISMISS_INTEL_REWARD']) - len(false_positives):>5} frames")
    print(f"{'FALSE POSITIVES':<32} {len(false_positives):>5} frames")
    print("\nobservations on signal frames:")
    for name, count in observations.most_common():
        print(f"   {count:>5}  {name}")

    if false_positives:
        print("\nfalse positives (a signal fired but the frame is not a reward dialog):")
        for entry in false_positives[:40]:
            print(f"   {entry['page']:<10} {entry['popup']:<14} {entry['signals']:<40} {entry['frame']}")
        if len(false_positives) > 40:
            print(f"   ... and {len(false_positives) - 40} more")

    if args.json:
        args.json.write_text(json.dumps({
            "corpus_frames": len(frames),
            "signal_hits": {k: len(v) for k, v in signal_hits.items()},
            "false_positive_count": len(false_positives),
            "false_positives": false_positives,
            "observations": dict(observations),
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nwrote {args.json}")

    return 0 if not false_positives else 1


if __name__ == "__main__":
    raise SystemExit(main())
