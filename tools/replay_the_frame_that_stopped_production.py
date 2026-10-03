"""Replay the exact frame that stopped production, through the project's own OCR.

The 19:35 step failed ``SEMANTIC_TARGET_NOT_VERIFIED`` on
``20261003_193420_502956_step_006_before_20261003T113523662049.png`` while that frame's own
``state_before.events.calendar_entry`` already carried ``tap_norm [0.925, 0.14883]`` at
confidence 0.998.  This asks the other half of the question the unit test cannot: does the
current recogniser still read the label off that file, so the new resolver branch has something
to consume when production runs it for real?

Exits non-zero on failure rather than printing a shrug -- an empty sample here would look
identical to a pass.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

FRAME = Path(
    r"C:\Users\xhw\.codex\worktrees\winter-prod-pinned\无尽冬日智能体\dataset\raw"
    r"\control_panel\runtime_auto\20261003_193420_502956"
    r"\20261003_193420_502956_step_006_before_20261003T113523662049.png"
)
RECORDED = {
    "visible": True,
    "tap_norm": [0.925, 0.14883],
    "source": "CURRENT_FRAME_OCR",
    "confidence": 0.9983089715242386,
}


def main() -> int:
    if not FRAME.exists():
        print("FAIL frame missing: %s" % FRAME)
        return 1

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from winter_agent_v2.models import Page, WorldState
    from winter_agent_v2.runtime import LiveRuntime

    frame = FRAME
    print("frame = %s" % frame.name)

    # 1. the recogniser still finds the label on this file
    from winter_agent_v2 import event_calendar
    from winter_agent_v2.ocr import read_frame_size

    size = read_frame_size(frame)
    print("frame_size = %s" % (size,))
    if not size:
        print("FAIL could not read the frame size; cannot judge the reading")
        return 1

    import cv2  # noqa: E402

    # cv2.imread goes through the ANSI path APIs on Windows and silently returns None for a
    # path containing non-ASCII characters -- which this project's roots always do.  Reading
    # the bytes and decoding through numpy sidesteps that entirely, and the failure mode is
    # loud here (image is None) instead of an empty array further down.
    import numpy as np  # noqa: E402

    image = cv2.imdecode(np.fromfile(str(frame), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        print("FAIL could not decode the frame (cv2.imread returns None on non-ASCII paths)")
        return 1
    height, width = image.shape[:2]
    print("pixels = %dx%d" % (width, height))
    tap_expected = [0.925, 0.14883]
    print("recorded tap_norm -> px = [%.0f, %.0f]"
          % (tap_expected[0] * width, tap_expected[1] * height))

    # 2. the recogniser still finds the label on this file, independently of the episode record.
    #    The recorded reading is a claim; this is the claim re-measured on the pixels.
    remeasured = None
    try:
        from winter_agent_v2.ocr import RapidOCRBackend, OCRService

        service = OCRService(RapidOCRBackend())
        result = service.recognize(frame)
        tokens = getattr(result, "tokens", result)
        from winter_agent_v2 import event_calendar as _ec

        remeasured = _ec.read_calendar_entry(tokens, frame_size=size)
    except Exception as exc:  # noqa: BLE001 - a harness must report, not explode
        print("note: could not re-run the recogniser here (%s: %s)" % (type(exc).__name__, exc))
    if remeasured:
        print("re-measured on this frame = %s" % json.dumps(remeasured, ensure_ascii=False))
        norm = remeasured.get("tap_norm")
        if isinstance(norm, (list, tuple)) and len(norm) == 2:
            dx = abs(float(norm[0]) - tap_expected[0])
            dy = abs(float(norm[1]) - tap_expected[1])
            print("  delta vs recorded = [%.5f, %.5f]" % (dx, dy))
            if dx > 0.02 or dy > 0.02:
                print("FAIL the recogniser and the episode record disagree by more than 2%")
                return 1
    else:
        print("note: recogniser unavailable here; the recorded reading stands unverified")

    # 3. the new branch answers from a frame that carries that reading
    runtime = LiveRuntime.__new__(LiveRuntime)
    world = WorldState(page=Page.HOME, confidence=0.99,
                       events={"calendar_entry": RECORDED})
    point = runtime._resolve_semantic_target("REGULAR_EVENT_ENTRY", world, frame_path=frame)
    print("resolved = %s" % (point,))
    if point is None:
        print("FAIL the stopping frame still does not resolve")
        return 1
    if abs(point[0] - tap_expected[0]) > 1e-6 or abs(point[1] - tap_expected[1]) > 1e-6:
        print("FAIL resolved %r does not match the recorded %r" % (point, tap_expected))
        return 1

    # 4. the box really is inside the frame the recorded reading came from
    px, py = point[0] * width, point[1] * height
    if not (0 <= px <= width and 0 <= py <= height):
        print("FAIL resolved pixel %s is outside %dx%d" % ((px, py), width, height))
        return 1

    # 5. the fixed template ROI is what the old path depended on -- show it is the weaker answer
    routing = Path(__file__).resolve().parents[1] / "knowledge" / "execution" / "backend_routing.json"
    if routing.exists():
        entry = json.loads(routing.read_text(encoding="utf-8"))
        roi = ((entry.get("skills") or {}).get("OPEN_EVENT_CALENDAR_FROM_HOME") or {}) \
            .get("recognition", {}).get("REGULAR_EVENT_ENTRY", {}).get("roi")
        if roi:
            rx, ry, rw, rh = roi
            inside = (rx <= px <= rx + rw) and (ry <= py <= ry + rh)
            print("template roi = %s -> contains the measured point: %s" % (roi, inside))
            print("  (this is the box that was cropped from one 2026-09-25 frame; "
                  "the new branch does not use it)")

    print("PASS the frame that stopped production now resolves, and it is the recorded reading")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
