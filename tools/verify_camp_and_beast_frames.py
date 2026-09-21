"""Acceptance evidence: run the PRODUCTION vision entry point over the live frames.

This is the same object the runtime builds (``HybridVision(template, ocr)``), not a
substitute: the point is to show what production reads, on real frames, for

  * the client's own beast search chain (search_before / search_after / beast_tab /
    beast5_found), and
  * each of the three training camps, independently.

Run:  .venv/Scripts/python.exe .probe_acceptance_frames.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from winter_agent_v2.ocr import HybridVision, OCRService, RapidOCRBackend  # noqa: E402
from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

MANIFEST = ROOT / "dataset/candidate/template_manifest.json"

SEARCH_FRAMES = [
    "search_before.png",
    "search_after.png",
    "beast_tab.png",
    "beast_tab_verify.png",
    "beast5_found.png",
]

CAMP_FRAMES = [
    # The shield camp has no dedicated tab capture yet: its frame is the one the
    # camp panel was first measured on.  Lancer and marksman each have a tab frame
    # and a verify frame taken separately, so a misread cannot be a stale file.
    "live_train_selection_available.png",
    "live_train_lancer_tab.png",
    "live_train_lancer_tab_verify.png",
    "live_train_marksman_tab.png",
    "live_train_marksman_tab_verify.png",
]


def build():
    """The same chain production builds: template layer fused with the OCR layer."""
    template = SemanticWorldVision(MANIFEST)
    ocr = OCRService(RapidOCRBackend())
    return HybridVision(template, ocr)


def main() -> int:
    vision = build()
    out: dict[str, object] = {}

    print("=" * 78)
    print("BEAST SEARCH CHAIN  (dataset/raw/beast_search_exploration/)")
    print("=" * 78)
    search_dir = ROOT / "dataset/raw/beast_search_exploration"
    for name in SEARCH_FRAMES:
        path = search_dir / name
        if not path.exists():
            print(f"  {name:24s} MISSING")
            continue
        world = vision.observe(path)
        row = {
            "page": world.page.value,
            "resource_search_open": world.resource_search_open,
            "resource_beast_tab": world.resource_beast_tab,
            "resource_selected": world.resource_selected,
            "beast_search_submitted": world.beast_search_submitted,
            "beast_name": (world.beast or {}).get("name"),
            "beast_attack_card": (world.beast or {}).get("attack_card"),
            "stamina": world.stamina.get("current"),
            "marches": f"{world.march_used}/{world.march_max}",
        }
        out[name] = row
        print(f"  {name:24s} page={row['page']:12s} open={row['resource_search_open']!s:5s} "
              f"beast_tab={row['resource_beast_tab']!s:5s} submitted={row['beast_search_submitted']!s:5s} "
              f"beast={row['beast_name']} card={row['beast_attack_card']}")
    print("  (beast_tab / submitted are the pair SUBMIT_BEAST_SEARCH verifies)")

    print()
    print("=" * 78)
    print("THREE TRAINING CAMPS, read independently")
    print("=" * 78)
    raw = ROOT / "dataset/raw"
    for name in CAMP_FRAMES:
        path = raw / name
        if not path.exists():
            print(f"  {name:32s} MISSING (no live frame under this name)")
            continue
        world = vision.observe(path)
        camps = {
            camp: {
                "running": (state or {}).get("running"),
                "idle_queue": (state or {}).get("idle_queue"),
                "status": (state or {}).get("status"),
            }
            for camp, state in sorted((world.camps or {}).items())
        }
        row = {
            "page": world.page.value,
            "training": dict(world.training or {}),
            "troop_type": (world.training or {}).get("troop_type"),
            "camp_ids": sorted(camps),
            "camps": camps,
        }
        out[name] = row
        named = ", ".join(camps) or "(none)"
        print(f"  {name:34s} page={row['page']:10s} troop={str(row['troop_type']):10s} "
              f"camps=[{named}]")
        for camp, state in camps.items():
            print(f"      {camp:14s} {state}")

    dest = ROOT / ".acceptance_frames.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(f"written: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
