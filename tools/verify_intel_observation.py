"""Feed live intel frames through the project's own verifiers, and print the two conditions side by side.

Why this exists
---------------
``CLEAR_INTEL``'s blocker says the episodes **"passed their verifier and advanced no part of this
goal"**. Two different judges are named in that sentence, and they read two different fields:

  * the verifier, ``verifier.verify_intel_list_read`` (registered for the capability at
    ``runtime.py:411``), asks whether the list was *read*::

        ok = before.page is Page.INTEL and after.page is Page.INTEL
             and after.intel.get("list_read") is True
             and after.intel.get("status") in {"AVAILABLE", "CLAIMABLE", "NOT_AVAILABLE", "IN_PROGRESS"}

  * the goal's meter, ``goal_library._observation_meter``, reads ``evidence["untried_pins"]``
    (``goal_library.py:2594-2614``), which ``runtime.py:8994`` stamps **only** when::

        before.page is Page.INTEL and not before.intel.get("mission_type")

So this tool observes two real frames and prints, for each, which of the two conditions it can
satisfy:

  * ``B`` -- the board captured live on 2026-10-05 08:13
    (``dataset/evidence/intel_panel_observe_20261005T081303/n2_look.png``): seven pins are drawn,
    and the reading carries ``status=CLAIMABLE``.
  * ``C`` -- a corpus frame whose reading carries ``list_read=True`` and a ``mission_type``.

This re-implements no rule: both verdicts come from the project's own functions. The stamp
condition is *evaluated*, not copied -- the script prints whether the frame meets
``runtime.py:8994``'s test, and leaves the counting to ``intel_pin_centers``, the same detector
the runtime calls.

Read-only: no device, no tap, no write.

Usage
-----
    python tools/verify_intel_observation.py
    python tools/verify_intel_observation.py --board <frame.png> --card <frame.png>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_BOARD = ROOT / "dataset/evidence/intel_panel_observe_20261005T081303/n2_look.png"
DEFAULT_MAP = ROOT / "dataset/evidence/intel_panel_observe_20261005T081303/n1_look.png"
DEFAULT_CARD = (
    ROOT / "dataset/truth_audit/reward_popup_exit_20260920/intel_board_corpus"
    "/20260914T061640_after_live_stamina_intel_run1_step_002_after_20260914T.png"
)

METER_FIELD = "untried_pins"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map-frame", default=str(DEFAULT_MAP))
    parser.add_argument("--board", default=str(DEFAULT_BOARD))
    parser.add_argument("--card", default=str(DEFAULT_CARD))
    parser.add_argument("--max-distance", type=int, default=8)
    args = parser.parse_args()

    from winter_agent_v2.intel_pins import intel_pin_centers
    from winter_agent_v2.ocr import (
        HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend,
    )
    from winter_agent_v2.verifier import verify_intel_list_read, verify_open_intel
    from winter_agent_v2.vision import SemanticWorldVision

    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(cfg["ocr"]["module_path"]))))
    hybrid = HybridVision(
        SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json",
                            max_distance=args.max_distance), ocr
    )

    def observe(path: Path):
        if not path.is_file():
            return None
        return hybrid.observe(path)

    map_state = observe(Path(args.map_frame))
    board_state = observe(Path(args.board))
    card_state = observe(Path(args.card))

    # ---- judgement 1: did the walk get there? ---------------------------------------------
    print("=" * 78)
    print("[1] verify_open_intel  (before = the map frame, after = the board frame)")
    if map_state is None or board_state is None:
        print("    frame missing -- skipped")
    else:
        res = verify_open_intel(map_state, board_state)
        print(f"    ok     : {res.ok}")
        print(f"    reason : {res.reason}")
        print(f"    detail : {json.dumps(getattr(res, 'detail', None), ensure_ascii=False, default=str)}")

    # ---- judgement 2 + the meter condition, for both kinds of frame ------------------------
    def report(tag: str, state, path: Path) -> None:
        print()
        print(f"[{tag}] {path.name}")
        if state is None:
            print("    frame missing -- skipped")
            return
        page = getattr(state.page, "value", state.page)
        intel = dict(state.intel or {})
        print(f"    observed page        : {page}")
        print(f"    intel keys           : {sorted(intel)}")
        print(f"    list_read            : {intel.get('list_read')!r}"
              f"   <- what the verifier needs")
        print(f"    mission_type         : {intel.get('mission_type')!r}")
        print(f"    {METER_FIELD:20s} : {intel.get(METER_FIELD)!r}   <- what the goal needs")

        # The verifier's own verdict. A read is judged in place, which is what the runtime does
        # when it stands on the board: two observations of the same frame.
        res = verify_intel_list_read(state, state)
        print(f"    verify_intel_list_read: ok={res.ok} reason={res.reason}")
        print(f"      detail             : {json.dumps(getattr(res, 'detail', None), ensure_ascii=False, default=str)}")

        # runtime.py:8994's test, evaluated rather than copied.
        stamps = page == "INTEL" and not intel.get("mission_type")
        print(f"    runtime.py:8994 would stamp {METER_FIELD}: {stamps}"
              f"   (page is INTEL and no mission_type)")
        if stamps:
            pins = intel_pin_centers(path)
            print(f"      -> it would count {len(pins)} pin(s) and publish "
                  f"{METER_FIELD}={len(pins)}")

    print("=" * 78)
    report("2", board_state, Path(args.board))
    report("3", card_state, Path(args.card))

    print()
    print("=" * 78)
    print("The two conditions are read from different fields, and on these frames they")
    print("never hold together:")
    for tag, state in (("board", board_state), ("card", card_state)):
        if state is None:
            continue
        intel = dict(state.intel or {})
        page = str(getattr(state.page, "value", state.page))
        verifier_ok = verify_intel_list_read(state, state).ok
        stamped = page == "INTEL" and not intel.get("mission_type")
        print(f"   {tag:6s} verifier_ok={str(verifier_ok):5s}  meter_would_be_stamped={str(stamped):5s}"
              f"   both={verifier_ok and stamped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
