"""Which reviewed template makes this frame that page, and at what distance?

The page identity comes from ``SemanticWorldVision`` by template matching, so "the recogniser calls
the 登录好礼 panel ALLIANCE" has a concrete answer: some ``semantic`` in the manifest returned a
match inside its threshold.  This prints every match on the frame with its distance, in manifest
order, plus the resulting ``WorldState`` -- so the claim can be checked rather than believed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.ocr import (  # noqa: E402
    OCRService, RapidOCRBackend, ResilientOCRBackend, HybridVision,
)
from winter_agent_v2.vision import SemanticROIVision, SemanticWorldVision  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame", required=True)
    parser.add_argument("--manifest", default="dataset/candidate/template_manifest.json")
    parser.add_argument("--max-distance", type=int, default=8)
    parser.add_argument("--only", default="", help="substring filter on the semantic name")
    args = parser.parse_args()

    frame = Path(args.frame)
    manifest = Path(args.manifest)
    if not frame.is_file():
        print("frame absent:", frame)
        return 2

    raw = SemanticROIVision(ROOT / manifest, max_distance=args.max_distance)
    records = getattr(raw, "records", None) or []
    print(f"frame    : {frame}")
    print(f"manifest : {manifest}  records={len(records)}")

    hits: list[tuple[str, int, str]] = []
    for record in records:
        semantic = str(record.get("semantic") or "")
        if args.only and args.only.lower() not in semantic.lower():
            continue
        try:
            found = raw.find(frame, semantic)
        except Exception as exc:  # noqa: BLE001 - a diagnostic reports, it does not fail the run
            print(f"  {semantic:44} ERR {type(exc).__name__}: {exc}")
            continue
        if found is None:
            continue
        centre = getattr(found, "center_norm", None)
        if callable(centre):
            centre = centre()
        hits.append((semantic, int(getattr(found, "distance", -1)), str(centre)))

    print(f"matches  : {len(hits)}")
    for semantic, distance, centre in hits:
        print(f"  d={distance:3}  {semantic:46} centre={centre}")

    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(cfg["ocr"]["module_path"]))))
    hybrid = HybridVision(SemanticWorldVision(ROOT / manifest, max_distance=args.max_distance), ocr)
    state = hybrid.observe(frame)
    print()
    print("WorldState:")
    print("  page       :", getattr(state.page, "value", state.page))
    print("  confidence :", state.confidence)
    print("  known      :", getattr(state, "known", None))
    print("  alliance   :", getattr(state, "alliance", None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
