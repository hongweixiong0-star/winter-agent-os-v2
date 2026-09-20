"""Corpus gate for the shared 获得奖励 dialog detector.

Why this exists
---------------
`winter_agent_v2/vision.py` decides "this is the client's shared 获得奖励
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

It also measures the CONTENT signals -- the banners, grids and title bands the
other reward-dialog branches consult.  Those were the blind spot that let the
2026-09-20 mail-inbox false positive outlive an earlier "zero false positives"
claim: the tool measured the two signals it was told about, so
`POPUP_INTEL_REWARD_TITLE`, the signal that actually fired, was never measured.
Every signal those branches consult is listed here now, positive or negative
control alike, and each is reported with its raw distance as well as its gate
verdict -- a signal that only *barely* fits its tolerance is the tell that the
tolerance is doing the work instead of the crop.

Usage
-----
    python tools/probe_reward_popup_gate.py
    python tools/probe_reward_popup_gate.py --json out_reward_gate.json
    python tools/probe_reward_popup_gate.py --stride 4      # cheap subsample

The corpus is ~6k frames and one pHash is pure Python, so the scan is chunked
across processes; `--stride` and `--limit` shrink the frame set if that is still
too slow.  Any subsample is printed with the stride so the numbers are never
mistaken for a whole-corpus count.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from winter_agent_v2.image_hash import hamming, phash  # noqa: E402
from winter_agent_v2.models import Page  # noqa: E402
from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"
CORPUS = ROOT / "dataset" / "raw"

# The footer and the banner are the two source-independent signals the detector
# uses.  Both are measured here so a future change to either is visible.
SIGNALS = ("BTN_DISMISS_INTEL_REWARD", "POPUP_GENERIC_REWARD_HEADER")

# Everything the remaining reward-dialog branches consult.  These may *confirm*
# a dialog the pair above already found; none of them may be the only evidence,
# because each is cut from artwork that varies with what the dialog contains.
# `POPUP_INTEL_REWARD_TITLE` is the one that proved it: on 2026-09-20 the mail
# inbox measured d=20 against its 22 tolerance, the AUTO loop spent ~20 rounds
# dismissing a popup that was not on the frame, and every dismiss returned
# SEMANTIC_TARGET_NOT_VERIFIED without tapping.
CONTENT_SIGNALS = (
    "POPUP_INTEL_REWARD_TITLE",
    "POPUP_INTEL_REWARD",
    "POPUP_MAIL_REWARD",
    "POPUP_DAILY_REWARD_CURRENT",
    "POPUP_EXPLORATION_REWARD",
)

# A page identity a content signal must never be able to overrule.  It matches
# the 2026-09-20 frame at distance 0, and the content signal still won.
PAGE_IDENTITY = "PAGE_MAIL"

# What a correct observation of a frame carrying this dialog looks like.
REWARD_POPUP = "GENERIC_REWARD"

MEASURED = SIGNALS + CONTENT_SIGNALS + (PAGE_IDENTITY,)

_CANDIDATES: dict[str, list[tuple[dict, str]]] = {}
_GATES: dict[str, int] = {}
_DEFAULT_GATE = 8


def _load() -> None:
    """Pre-hash every template and read the declared tolerances, once per worker."""
    global _CANDIDATES, _GATES, _DEFAULT_GATE
    vision = SemanticWorldVision(MANIFEST)
    _DEFAULT_GATE = vision.semantic.max_distance
    _GATES = dict(vision.semantic.semantic_max_distance)
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for name in MEASURED:
        candidates = []
        for row in payload["records"]:
            if row.get("semantic") != name or row.get("matcher") == "ccoeff":
                continue
            template = Path(row["template_path"])
            if not template.exists():
                continue
            with Image.open(template) as opened:
                candidates.append((row["roi_norm"], phash(opened.convert("RGB"))))
        _CANDIDATES[name] = candidates


def _scan(frame: str) -> dict:
    """Raw distance for every measured signal on one frame.

    The image is opened once per frame rather than once per ``find`` call
    because ``find`` re-opens it, and the corpus is 6k frames.
    """
    distances: dict[str, int | None] = {}
    with Image.open(frame) as opened:
        image = opened.convert("RGB")
        width, height = image.size
        for name in MEASURED:
            best = None
            for roi, template_hash in _CANDIDATES.get(name, ()):
                box = (
                    round(roi["x_norm"] * width),
                    round(roi["y_norm"] * height),
                    round((roi["x_norm"] + roi["w_norm"]) * width),
                    round((roi["y_norm"] + roi["h_norm"]) * height),
                )
                try:
                    distance = hamming(phash(image.crop(box)), template_hash)
                except Exception:  # pragma: no cover - diagnostic only
                    continue
                best = distance if best is None else min(best, distance)
            distances[name] = best
    return {"frame": frame, "distance": distances}


def _within(name: str, distance: int | None) -> bool:
    return distance is not None and distance <= _GATES.get(name, _DEFAULT_GATE)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=0,
                        help="stop after N frames (0 = no limit)")
    parser.add_argument("--stride", type=int, default=1,
                        help="measure every Nth frame (a documented subsample; "
                             "the default 1 measures the whole corpus)")
    parser.add_argument("--workers", type=int, default=0,
                        help="scan processes (0 = one per CPU, capped at 12)")
    args = parser.parse_args()

    frames = sorted(CORPUS.rglob("*.png"))
    if args.stride > 1:
        frames = frames[:: args.stride]
    if args.limit:
        frames = frames[: args.limit]
    print(f"corpus frames: {len(frames)}"
          + (f" (stride {args.stride})" if args.stride > 1 else ""))

    workers = args.workers or min(12, os.cpu_count() or 1)
    _load()  # the parent needs the declared tolerances for the report below
    distances: dict[str, dict[str, int | None]] = {}
    with ProcessPoolExecutor(max_workers=workers, initializer=_load) as pool:
        for index, row in enumerate(pool.map(_scan, [str(f) for f in frames], chunksize=8), 1):
            distances[row["frame"]] = row["distance"]
            if index % 1000 == 0:
                print(f"  ... {index}/{len(frames)}")

    hits: Counter[str] = Counter()
    hit_frames: dict[str, list[str]] = {name: [] for name in MEASURED}
    for frame, per_frame in distances.items():
        for name, distance in per_frame.items():
            if _within(name, distance):
                hits[name] += 1
                hit_frames[name].append(frame)

    # The production decision, only where the source-independent pair fired.
    vision = SemanticWorldVision(MANIFEST)
    source_frames = [f for f in distances
                     if any(_within(name, distances[f][name]) for name in SIGNALS)]
    states: dict[str, str] = {}
    false_positives: list[dict[str, str]] = []
    for frame in source_frames:
        try:
            state = vision.observe(Path(frame))
        except Exception:  # pragma: no cover - diagnostic only
            continue
        label = state.popup or f"<page={state.page.value}>"
        states[frame] = label
        if not (state.page is Page.POPUP and state.popup == REWARD_POPUP):
            false_positives.append({
                "frame": str(Path(frame).relative_to(ROOT)),
                "page": state.page.value,
                "popup": state.popup or "",
                "signals": ",".join(
                    f"{name}={distances[frame][name]}"
                    for name in MEASURED if _within(name, distances[frame][name])
                ),
            })

    def summary(values: list[int]) -> str:
        if not values:
            return "none"
        values = sorted(values)
        return f"min {values[0]:>3}  p50 {values[len(values) // 2]:>3}  max {values[-1]:>3}"

    def distribution(name: str) -> str:
        return summary([d for d in (distances[f][name] for f in hit_frames[name]) if d is not None])

    print()
    print("source-independent signals (these are allowed to declare the dialog):")
    for name in SIGNALS:
        print(f"  {name:<30} matched {hits[name]:>5}   {distribution(name)}")
    print(f"  {'any of the pair':<30} {len(source_frames):>5}")
    print(f"  {'observed as GENERIC_REWARD':<30} {len(source_frames) - len(false_positives):>5}")
    print(f"  {'FALSE POSITIVES':<30} {len(false_positives):>5}")
    print("\nobservations on pair frames:")
    for label, count in Counter(states.values()).most_common():
        print(f"   {count:>5}  {label}")

    # The content table is deliberately gate-independent.  Reporting "how many
    # frames are inside the tolerance" is what hid this defect: when the trap
    # signal has no tolerance of its own its gate falls back to the default and
    # the overlap disappears from the report.  The distance over the dialog
    # frames against the distance over everything else is the measurement that
    # cannot be made to look clean by a gate.
    print("\ncontent signals (may only confirm a dialog, never be the only "
          "evidence); distance on the frames the pair above fired on (the "
          "dialogs) vs everywhere else:")
    source_set = set(source_frames)
    content_report: dict[str, dict[str, object]] = {}
    for name in CONTENT_SIGNALS + (PAGE_IDENTITY,):
        on_dialog = [distances[f][name] for f in source_set if distances[f][name] is not None]
        elsewhere = [distances[f][name] for f in distances
                     if f not in source_set and distances[f][name] is not None]
        gate = _GATES.get(name, _DEFAULT_GATE)
        content_report[name] = {
            "declared_gate": gate,
            "on_dialog_frames": summary(on_dialog),
            "everywhere_else": summary(elsewhere),
            "matched_at_gate": hits[name],
        }
        print(f"  {name:<30} gate {gate:>2}   on dialogs {summary(on_dialog)}"
              f"   elsewhere {summary(elsewhere)}")
        print(f"       matched at gate: {hits[name]:>5} of which NOT a dialog: "
              f"{hits[name] - sum(1 for f in hit_frames[name] if f in source_set):>5}")
    print("  A content signal whose 'elsewhere' reaches into its 'on dialogs' "
          "range cannot be separated by any tolerance, and one whose matches are "
          "mostly NOT a dialog must never be the only reason a popup is "
          "declared: the trap documented in knowledge/failure_patterns/vision/"
          "TEMPLATE_CROP_COVERS_THE_VARIABLE.md.")

    if false_positives:
        print("\nfalse positives (a signal fired but the frame is not a reward dialog):")
        for entry in false_positives[:40]:
            print(f"   {entry['page']:<10} {entry['popup']:<14} "
                  f"{entry['signals']:<40} {entry['frame']}")
        if len(false_positives) > 40:
            print(f"   ... and {len(false_positives) - 40} more")

    if args.json:
        args.json.write_text(json.dumps({
            "corpus_frames": len(frames),
            "stride": args.stride,
            "signal_hits": {k: v for k, v in hits.items()},
            "content_signals": content_report,
            "false_positive_count": len(false_positives),
            "false_positives": false_positives,
            "observations": dict(Counter(states.values())),
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nwrote {args.json}")

    return 0 if not false_positives else 1


if __name__ == "__main__":
    raise SystemExit(main())
