"""Can a battle/transition screen be told apart from an ordinary unknown page?

READ EVIDENCE step for WB-R19-BATTLE-UNKNOWN-RECOVERY.

The risk being addressed: runtime.py:472-485 answers ``unknown_page`` by pressing
the system Back key immediately, then re-observing, up to twice per run.  On an
ordinary unrecognised screen that is the right call.  On a live battle the effect
of Back is unmeasured, and the order forbids manufacturing one to find out.

So the question this probe has to answer from frames that already exist is
narrow: is a battle screen (a) recognised as something, or (b) unrecognised in a
way that is *distinguishable* from the unrecognised screens the recovery was
designed for.  If neither, the honest answer is the run-scoped alternative and
this probe says so rather than inventing a classifier.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

MANIFEST = ROOT / "dataset/candidate/template_manifest.json"

FRAMES = {
    "BATTLE (known from 2026-09-15 15:14:46)": "dataset/raw/control_panel/probe/live_page_20260915_151446.png",
    "home (known, control)": "dataset/raw/control_panel/probe/live_page_20260915_151524.png",
    "hero_live6 step003 before": "dataset/raw/control_panel/runtime_auto/hero_live6_20260914/hero_live6_20260914_step_003_before_20260914T141537530422.png",
    "hero_live6 step003 after": "dataset/raw/control_panel/runtime_auto/hero_live6_20260914/hero_live6_20260914_step_003_after_20260914T141549441348.png",
    "hero_live6 step004 after": "dataset/raw/control_panel/runtime_auto/hero_live6_20260914/hero_live6_20260914_step_004_after_20260914T141557894818.png",
    "hero_live6 step005 after": "dataset/raw/control_panel/runtime_auto/hero_live6_20260914/hero_live6_20260914_step_005_after_20260914T141601552798.png",
    "hero_live5 step001 after": "dataset/raw/control_panel/runtime_auto/hero_live5_20260914/hero_live5_20260914_step_001_after_20260914T141216615654.png",
    "hero_live3 step001 after": "dataset/raw/control_panel/runtime_auto/hero_live3_20260914/hero_live3_20260914_step_001_after_20260914T140454335231.png",
}


def main() -> int:
    vision = SemanticWorldVision(MANIFEST)
    print("%-36s %-14s %-6s %s" % ("frame", "page", "conf", "details"))
    for tag, rel in FRAMES.items():
        path = ROOT / rel
        if not path.exists():
            print("%-36s MISSING" % tag)
            continue
        state = vision.observe(path)
        details = []
        for key in ("popup", "battlefield", "rewards", "battle"):
            value = getattr(state, key, None)
            if value:
                details.append("%s=%s" % (key, json.dumps(value, ensure_ascii=False)[:60]))
        print("%-36s %-14s %-6s %s" % (tag, state.page, state.confidence, "; ".join(details)[:90]))
    print()
    print("available pages:", [p.value if hasattr(p, "value") else str(p) for p in __import__("winter_agent_v2.models", fromlist=["Page"]).Page])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
