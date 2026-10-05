# -*- coding: utf-8 -*-
"""Let the project's own Verifier judge a daily-panel observation, from two frames.

Why a separate tool
-------------------
The new-content chain requires that the *Verifier* decides whether an action worked, never the
model that took it.  ``winter_agent_v2.verifier`` already holds the verdicts for this page --
``verify_open_daily`` and ``verify_daily_tab_selected`` -- and they take exactly two
``WorldState``s.  So the whole job is: turn two saved frames into two states through the
**production** entry point (``HybridVision.observe``) and hand them over.  This re-implements no
rule; a verdict printed here is the same verdict the runtime would compute.

Both criteria are independent of the action that produced them, which is what makes them a
verification rather than a restatement:

  * ``verify_open_daily`` -- HOME before, a task-board page after.
  * ``verify_daily_tab_selected`` -- the *drawn* tab state changed, read from the tab pill's own
    pixels (the client draws the selected tab as a light pill, the unselected as a dark one).

Read-only: two files in, text out, no device.

Usage
-----
    python tools/verify_daily_observation.py --before <home>.png --after <panel>.png
    python tools/verify_daily_observation.py --before a.png --after b.png --verifier all
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MANIFEST = "dataset/candidate/template_manifest.json"

#: The verifiers this tool can run, and what each pair of frames means for it.
VERIFIERS = {
    "open_daily": "HOME -> a task-board page (verify_open_daily)",
    "daily_tab_selected": "an unselected tab -> the 每日任务 tab drawn selected "
                          "(verify_daily_tab_selected)",
}


def _state_for(frame: Path, cfg: dict, max_distance: int):
    from winter_agent_v2.ocr import (
        HybridVision,
        OCRService,
        RapidOCRBackend,
        ResilientOCRBackend,
    )
    from winter_agent_v2.vision import SemanticWorldVision

    ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(cfg["ocr"]["module_path"]))))
    hybrid = HybridVision(SemanticWorldVision(ROOT / MANIFEST, max_distance=max_distance), ocr)
    return hybrid.observe(frame)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--max-distance", type=int, default=8)
    parser.add_argument("--verifier", default="all",
                        choices=(*VERIFIERS, "all"), help="which verdicts to ask for")
    args = parser.parse_args()

    before_path = Path(args.before)
    after_path = Path(args.after)
    if not before_path.is_absolute():
        before_path = ROOT / before_path
    if not after_path.is_absolute():
        after_path = ROOT / after_path
    for path in (before_path, after_path):
        if not path.is_file():
            print("frame absent:", path)
            return 2

    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    before = _state_for(before_path, cfg, args.max_distance)
    after = _state_for(after_path, cfg, args.max_distance)

    print(f"before : {before_path.name}")
    print(f"  page={getattr(before.page, 'value', before.page)}"
          f" conf={before.confidence}"
          f" tab={(before.daily or {}).get('tab')}")
    print(f"after  : {after_path.name}")
    print(f"  page={getattr(after.page, 'value', after.page)}"
          f" conf={after.confidence}"
          f" tab={(after.daily or {}).get('tab')}")
    print()

    from winter_agent_v2.verifier import verify_daily_tab_selected, verify_open_daily

    asked = list(VERIFIERS) if args.verifier == "all" else [args.verifier]
    runners = {"open_daily": verify_open_daily, "daily_tab_selected": verify_daily_tab_selected}

    failures = 0
    for name in asked:
        result = runners[name](before, after)
        print(f"[{name}] {VERIFIERS[name]}")
        print(f"   verdict : {'OK' if result.ok else 'NOT PROVEN'}")
        print(f"   reason  : {result.reason}")
        print(f"   evidence: {json.dumps(result.evidence, ensure_ascii=False)}")
        print()
        if not result.ok:
            failures += 1

    print(f"{len(asked) - failures}/{len(asked)} verifier(s) returned OK")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
