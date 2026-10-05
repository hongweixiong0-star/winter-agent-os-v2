"""Replay intel-page frames through the production observer and through the pin detector.

Why this exists
---------------
``CLEAR_INTEL`` is 已发现 on the console and its blocker names one capability:
``READ_INTEL_LIST`` -- ``state: DEFERRED``, ``source: NO_GOAL_PROGRESS``,
``failure_signature: "READ_INTEL_LIST|NO_GOAL_PROGRESS|OPEN_MAP"``, and the reason is
"3 consecutive production episodes **passed their verifier and advanced no part of this
goal**".

Two files already explain that shape, and this tool checks both on real frames:

  * ``goal_library.py:2594-2614`` -- CLEAR_INTEL's meter is ``untried_pins``, the client's
    own count of pins it has not had tried. Measured over 323 live intel-page frames it
    falls 8 -> 7 when one intel is handled while ``pins``/``detected_pins`` stay put. It is
    the only field that moves. When it is absent the meter returns ``None`` and the goal
    falls back to its constant ``distance`` of 1.0 -- so ``1.0 < 1.0`` is False on every
    step and the goal is demoted for work it cannot report.
  * ``ocr.py:6090-6109`` -- the ``Page.INTEL`` OCR branch writes only ``stamina`` and
    ``refresh``. Its own comment records the falsified claim that "the two states are
    separable by OCR alone": the intel page is a PIN MAP, so a board full of work OCRs as
    nothing but the 情报 / 体力 / 下次刷新 header. Reproduced live 2026-09-15 07:36 with 5
    pins on screen.

So the question this tool answers is: on real intel frames, what does the production
reading actually carry, and does the pin detector see counts the reading does not?

This re-implements nothing. It calls the same ``OCRPageClassifier.classify`` and
``HybridVision.observe`` the runtime calls, and the same ``intel_pin_centers``
``runtime.py:8994`` calls when it stamps ``untried_pins``.

Read-only: no device, no tap, no write.

Usage
-----
    python tools/probe_intel_list.py --limit 60
    python tools/probe_intel_list.py --limit 1 --verbose
    python tools/probe_intel_list.py --json dataset/probe_output/intel_list.json
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.intel_pins import intel_pin_centers  # noqa: E402
from winter_agent_v2.ocr import (  # noqa: E402
    HybridVision,
    OCRService,
    RapidOCRBackend,
    ResilientOCRBackend,
)
from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

CORPUS = (
    ROOT / "dataset" / "truth_audit" / "reward_popup_exit_20260920" / "intel_board_corpus"
)

#: Fields that would answer "how much intel is on the board". The last three are the ones
#: ``runtime.py:8994`` stamps from ``intel_pin_centers``; the first group is what OCR can
#: write. Used only to *name* what was seen -- never to decide anything.
COUNT_FIELDS = ("pins", "detected_pins", "untried_pins", "available_count", "claimable_count")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="stop after N frames (0 = all)")
    parser.add_argument("--corpus", default=str(CORPUS))
    parser.add_argument("--json", default="")
    parser.add_argument("--verbose", action="store_true", help="one line per frame")
    args = parser.parse_args()

    frames = sorted(Path(args.corpus).glob("*.png"))
    if args.limit:
        frames = frames[: args.limit]
    if not frames:
        print("no frames under", args.corpus)
        return 2

    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(cfg["ocr"]["module_path"]))))
    # The production entry point only. ``HybridVision.observe`` runs the template layer
    # first and then the OCR pass the ``Page.INTEL`` branch needs, so calling ``recognize``
    # again here would only double the cost of every frame without changing the verdict.
    hybrid = HybridVision(SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json"), ocr)

    pages = collections.Counter()
    key_sets = collections.Counter()
    field_hits = collections.Counter()
    statuses = collections.Counter()
    pin_hist = collections.Counter()
    #: How the reading's own count compares with what the detector sees on the same frame.
    #: This is the whole question: a reading that says 1 while the board draws 8 is not a
    #: measurement, and CLEAR_INTEL's meter needs a measurement.
    agreement = collections.Counter()
    frames_with_count = 0
    samples: list[dict] = []

    for index, frame in enumerate(frames, 1):
        try:
            state = hybrid.observe(frame)
            pins = intel_pin_centers(frame)
        except Exception as exc:  # noqa: BLE001 - a probe must not die on one bad frame
            print(f"  !! {frame.name[:60]}: {type(exc).__name__}: {exc}")
            continue

        page = str(getattr(state.page, "value", state.page))
        intel = dict(state.intel or {})
        pages[page] += 1
        statuses[str(intel.get("status"))] += 1
        key_sets[tuple(sorted(intel))] += 1
        for field in COUNT_FIELDS:
            if field in intel:
                field_hits[field] += 1
        pin_hist[len(pins)] += 1
        has_count = any(field in intel for field in COUNT_FIELDS)
        if has_count:
            frames_with_count += 1

        # The comparison that decides the hypothesis. ``available_count`` is what the
        # reading claims; ``len(pins)`` is what the board actually draws.
        claimed = intel.get("available_count")
        detected = len(pins)
        if not isinstance(claimed, int):
            verdict = "reading_carries_no_count"
        elif claimed == detected:
            verdict = "agree"
        elif claimed < detected:
            verdict = "UNDERSTATED"
        else:
            verdict = "overstated"
        agreement[verdict] += 1
        if verdict in {"UNDERSTATED", "overstated"} and len(samples) < 12:
            samples.append({
                "frame": frame.name,
                "page": page,
                "status": intel.get("status"),
                "available_count": claimed,
                "pins_field": intel.get("pins"),
                "untried_pins_field": intel.get("untried_pins"),
                "mission_type": intel.get("mission_type"),
                "list_read": intel.get("list_read"),
                "pins_seen_by_detector": detected,
                "intel_keys": sorted(intel),
            })
        if args.verbose or args.limit == 1:
            print(f"  [{page:12s}] pins={detected:2d} claimed={claimed!r} status={intel.get('status')!r} "
                  f"-> {verdict}")
            print(f"      intel={json.dumps(intel, ensure_ascii=False, default=str)}")
        if index % 50 == 0:
            print(f"  ... {index}/{len(frames)}")

    print()
    print(f"frames                 : {len(frames)}")
    print(f"production page        : {dict(pages.most_common())}")
    print(f"production intel status: {dict(statuses.most_common())}")
    print(f"production intel keys  : ")
    for keys, n in key_sets.most_common():
        print(f"    {n:4d}x  {list(keys)}")
    print(f"count-bearing fields   : {dict(field_hits)}")
    print(f"pin count distribution : {dict(sorted(pin_hist.items()))}")
    print()
    print(f"reading says vs board draws : {dict(agreement.most_common())}")
    print(f"frames whose production reading carries ANY count field : {frames_with_count}")
    if samples:
        print("\n  frames where the reading's count disagreed with the board:")
        for s in samples:
            print(f"    {s['frame'][:44]:44s} status={s['status']:12s} "
                  f"available_count={s['available_count']!r:>5} "
                  f"vs detector={s['pins_seen_by_detector']:2d}  "
                  f"untried={s['untried_pins_field']!r}  keys={s['intel_keys']}")

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "frames": len(frames),
            "pages": dict(pages),
            "statuses": dict(statuses),
            "intel_key_sets": {str(k): v for k, v in key_sets.items()},
            "count_field_hits": dict(field_hits),
            "pin_histogram": dict(pin_hist),
            "reading_vs_board": dict(agreement),
            "frames_with_count_field": frames_with_count,
            "samples": samples,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
