"""0bc: which PAGE_* anchors actually fire on a HOME frame versus a MAP frame?

The 0bc note claims PAGE_MAP templates were cropped from HOME frames at the same
ROI as BTN_OPEN_HOME (the 城镇 button), which would make "is this the map?" rest
on a widget the client draws on both pages.  But the vision reports HOME 0.98 and
MAP 0.99 on the two live frames, so the claim needs measuring rather than
asserting: find out which page anchors each frame actually matches, and whether
the PAGE_MAP ROI is really the 城镇 button.

Read-only.
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

HOME_FRAME = ROOT / "dataset/raw/control_panel/probe/live_page_20260915_151524.png"
MAP_FRAME = ROOT / "dataset/raw/control_panel/probe/live_page_20260915_133152.png"


def main() -> None:
    manifest = json.loads((ROOT / "dataset/candidate/template_manifest.json").read_text(encoding="utf-8"))
    records = manifest["records"]

    print("=== every PAGE_* / BTN_OPEN_HOME / BTN_OPEN_MAP anchor in the manifest ===")
    wanted = []
    for r in records:
        sem = str(r.get("semantic") or "")
        if sem.startswith("PAGE_") or sem in {"BTN_OPEN_HOME", "BTN_OPEN_MAP"}:
            wanted.append(r)
            print(
                "  %-34s status=%-9s roi=%s"
                % (sem, r.get("status"), json.dumps(r.get("roi_norm"), ensure_ascii=False))
            )

    page_semantics = sorted({str(r.get("semantic")) for r in wanted if str(r.get("semantic")).startswith("PAGE_")})
    print()
    print("page semantics to probe:", page_semantics)

    vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    semantic = vision.semantic

    print()
    print("=== matches on each frame ===")
    for label, frame in (("HOME (city)", HOME_FRAME), ("MAP (world)", MAP_FRAME)):
        if not frame.exists():
            print("%-14s MISSING %s" % (label, frame))
            continue
        print("-- %s : %s" % (label, frame.name))
        for sem in page_semantics:
            try:
                hit = semantic.find(frame, sem)
            except Exception as exc:  # noqa: BLE001
                print("     %-22s ERROR %s" % (sem, exc))
                continue
            print("     %-22s %s" % (sem, "HIT %s" % (hit.center_norm,) if hit else "miss"))
        for sem in ("BTN_OPEN_HOME", "BTN_OPEN_MAP"):
            try:
                hit = semantic.find(frame, sem)
            except Exception:  # noqa: BLE001
                hit = None
            print("     %-22s %s" % (sem, "HIT %s" % (hit.center_norm,) if hit else "miss"))


if __name__ == "__main__":
    main()
