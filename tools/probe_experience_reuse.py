"""Does the ledger now refuse scratch-frame records, and can a remembered control be reused?

Two questions, both measurable right now on the live files:

1. ``load()`` must drop the records whose ``read_from_frame`` was under the system temp
   directory.  Before the filter: 35 records, 11 of them scratch, six of those filed at one
   coordinate.  After: those 11 must be gone and the 24 real ones must survive.
2. ``LiveRuntime._remembered_control_center`` must return a point for a control the device
   has exercised and refuse one it has not -- otherwise the branch is either dead code or a
   way to tap invented coordinates.

Read-only.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2 import control_experience  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402


def main() -> int:
    raw = json.loads((ROOT / "learning/control_experience.json").read_text(encoding="utf-8"))
    raw_controls = raw.get("controls") or {}
    loaded = control_experience.load()
    print(f"raw records      : {len(raw_controls)}")
    print(f"loaded (filtered): {len(loaded)}")
    print(f"dropped          : {len(raw_controls) - len(loaded)}")
    scratch = [k for k, v in raw_controls.items()
               if not control_experience.measured_on_a_real_frame(
                   control_experience.ControlExperience.from_json(v))]
    print("dropped keys:", scratch)
    print()

    print("=== the six records that shared one coordinate, after filtering ===")
    for key in ("HOME|PAGE_MAP", "MAP|BTN_OPEN_HOME", "EXPLORATION|BTN_HERO_CAMP_FIGHT",
                "POPUP|BTN_CLAIM_FREE_STAMINA"):
        entry = loaded.get(key)
        if entry is None:
            print(f"  {key:34} DROPPED (was a scratch measurement)")
        else:
            print(f"  {key:34} kept, pos={entry.position_norm} known={entry.known_change!r}")
    print()

    print("=== measured_on_a_real_frame on constructed paths ===")
    scratch_dir = Path(tempfile.gettempdir())
    cases = (
        ("project frame", str(ROOT / "dataset/raw/control_panel/x.png"), True),
        ("temp frame", str(scratch_dir / "tmpxyz/captures/a.png"), False),
        ("empty", "", False),
    )
    for name, path, want in cases:
        got = control_experience.measured_on_a_real_frame(
            control_experience.ControlExperience(page="P", control="C", read_from_frame=path))
        print(f"  {name:16} want={want!s:5} got={got!s:5} {'OK' if got is want else 'MISMATCH'}")
    print()

    print("=== would the runtime reuse a remembered control? ===")
    runtime = object.__new__(__import__("winter_agent_v2.runtime", fromlist=["LiveRuntime"]).LiveRuntime)
    runtime._control_ledger = loaded
    runtime._remembered_reuse = []
    runtime._printed_remembered = set()
    for page, semantic in (("HOME", "PAGE_MAP"), ("MAP", "BTN_OPEN_HOME"),
                           ("HOME", "BTN_NEVER_SEEN"), ("INTEL", "PAGE_MAP")):
        frame = WorldState(page=Page(page) if page in Page.__members__ else Page.UNKNOWN)
        frame = WorldState(page=getattr(Page, page, Page.UNKNOWN))
        point = runtime._remembered_control_center(semantic, frame)
        print(f"  {page:12} {semantic:26} -> {point}")
    print()
    print("reuse log:", runtime._remembered_reuse)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
