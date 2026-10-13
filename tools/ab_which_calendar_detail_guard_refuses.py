# -*- coding: utf-8 -*-
"""A/B: which of the six guards inside EVENT_CALENDAR_NEXT_DETAIL actually refuses?

The resolver (runtime.py:5419-5452) returns ``None`` from six distinct places, and the
episode records all six as one constant -- ``UNKNOWN_NAV:PROVIDER_ANSWERED_NOTHING``.
That is the same shape as the defect fixed in 4c62e600 ("a named cause must not be erased
by the question-level refusal"), one layer out: the *resolver's* own causes are erased.

This replays real before_screenshots through the exact same reader the resolver uses --

    read_event_calendar(ocr.recognize(frame).tokens, frame_size=..., frame_path=frame)

-- and reports, guard by guard, which one refuses.  Failing frames and succeeding frames
from the same skill are run side by side, because "it refuses" is only meaningful next to
"and here is a frame where it does not".

Offline only: it reads saved PNGs and never touches the device.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from winter_agent_v2 import event_schedule as es  # noqa: E402
from winter_agent_v2.ocr import OCRService, OCRPageClassifier, RapidOCRBackend  # noqa: E402
from winter_agent_v2.runtime import (  # noqa: E402
    RESOLVER_LOCATOR_MISSED, LiveRuntime, _prefer_the_cause, read_frame_size,
)
from winter_agent_v2.event_calendar import read_event_calendar  # noqa: E402

EPISODES = ROOT / "learning" / "episodes.jsonl"
SKILL = "OPEN_EVENT_CALENDAR_DETAIL"


def load_episodes() -> list[dict]:
    rows: list[dict] = []
    with EPISODES.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("skill") == SKILL:
                rows.append(row)
    return rows


def verdict(frame: Path, role_id: str, ocr: OCRService) -> dict:
    """Run the resolver's guard chain verbatim and name the first one that refuses."""
    out: dict = {"frame": frame.name, "role": role_id}
    if not frame.is_file():
        out["guard"] = "FRAME_MISSING"
        return out
    try:
        result = ocr.recognize(frame)
        current = read_event_calendar(result.tokens, frame_size=read_frame_size(frame),
                                      frame_path=frame)
    except Exception as exc:  # noqa: BLE001 -- this is a diagnostic, it reports what it saw
        out["guard"] = f"READER_RAISED:{type(exc).__name__}"
        out["detail"] = str(exc)[:120]
        return out

    out["recognized"] = current.get("recognized")
    out["details_visible"] = current.get("details_visible")
    entries = current.get("entries") or ()
    out["entries"] = len(entries)
    out["visible_dates"] = current.get("visible_dates_raw")

    # Guard 1 and 2 (page and detail are checked by the caller; here they are inputs).
    if current.get("recognized") is not True:
        out["guard"] = "GUARD_current_not_recognized"
        return out
    if current.get("details_visible") is True:
        out["guard"] = "GUARD_detail_overlay_open"
        return out

    row = es.calendar_next_entry(role_id, list(entries))
    if not isinstance(row, dict):
        out["guard"] = "GUARD_next_entry_None"
        out["why"] = ("no row with details_observed != True and tap_norm and event_id"
                      f" among {len(entries)} entries")
        out["row_ids"] = [r.get("event_id") for r in entries if isinstance(r, dict)]
        return out

    out["chosen"] = row.get("display_name")
    out["chosen_id"] = row.get("event_id")
    # Guards 3, 4, 5 -- the resolver's own field test on the CHOSEN row.
    if not row.get("occurrence_key"):
        out["guard"] = "GUARD_no_occurrence_key"
        return out
    if not row.get("event_id"):
        out["guard"] = "GUARD_no_event_id"
        return out
    if not row.get("title_box"):
        out["guard"] = "GUARD_no_title_box"
        return out
    point = row.get("tap_norm")
    if not isinstance(point, (list, tuple)) or len(point) != 2:
        out["guard"] = "GUARD_tap_norm_not_a_point"
        out["tap_norm"] = point
        return out
    target = tuple(float(v) for v in point)
    out["tap_norm"] = point
    if not all(0.0 <= v <= 1.0 for v in target):
        out["guard"] = "GUARD_point_outside_frame"
        return out
    out["guard"] = "PASS"
    return out


def classifier_view(frame: Path, ocr: OCRService, classifier: OCRPageClassifier) -> dict:
    """What the runtime's own page classifier says about the two flags that decide the hop.

    ``brain.decide`` routes to RETURN_EVENT_CALENDAR only when ``calendar_detail.recognized``
    is True, while the resolver refuses to tap when the CALENDAR reading's ``details_visible``
    is True.  Those are two different readers' opinions.  When they disagree the run is asked
    to open a detail it is already standing on, and the resolver's refusal is then recorded as
    the generic PROVIDER_ANSWERED_NOTHING.
    """
    try:
        world = classifier.classify(ocr.recognize(frame), frame_size=read_frame_size(frame))
    except Exception as exc:  # noqa: BLE001 -- diagnostic
        return {"classifier": f"RAISED:{type(exc).__name__}:{str(exc)[:80]}"}
    events = world.events or {}
    calendar = events.get("calendar") if isinstance(events.get("calendar"), dict) else {}
    detail = events.get("calendar_detail") if isinstance(events.get("calendar_detail"), dict) else {}
    return {
        "page": getattr(world.page, "value", world.page),
        "calendar_recognized": calendar.get("recognized"),
        "calendar_details_visible": calendar.get("details_visible"),
        "calendar_detail_present": "calendar_detail" in events,
        "calendar_detail_recognized": detail.get("recognized"),
        "hub_recognized": (events.get("regular_events_hub") or {}).get("recognized")
        if isinstance(events.get("regular_events_hub"), dict) else None,
        # ocr.py:1333 is an ``elif``: when the branch above it (the active-event /
        # minimum_guarantee case) fires, ``events["calendar_detail"]`` is NEVER set even
        # though the detail reader may have recognised the panel.  These two keys say
        # whether that suppression is what removed the key.
        "active_event": events.get("active_event"),
        "minimum_guarantee_present": "minimum_guarantee" in events,
        "events_keys": sorted(events),
    }


def ledger_code(frame: Path, role_id: str, classifier: OCRPageClassifier,
                ocr: OCRService) -> tuple[str, str]:
    """What the episode row actually carries, before and after the naming change.

    ``resolve`` reads ``locator_cause = self._resolution_error or RESOLVER_LOCATOR_MISSED``
    after the resolver declines, then lets ``_prefer_the_cause`` choose between that and the
    advisor's reply.  This runs that composition for real on a real frame, so the claim
    "the row will now carry the true cause" is measured rather than read off a docstring.
    """
    world = classifier.classify(ocr.recognize(frame), frame_size=read_frame_size(frame))
    rt = object.__new__(LiveRuntime)
    rt.role_id = role_id
    rt.role_scope = "FRESH_RUNTIME"
    rt.vision = SimpleNamespace(ocr=ocr)
    rt._resolution_error = ""
    point = rt._resolve_semantic_target("EVENT_CALENDAR_NEXT_DETAIL", world,
                                        frame_path=Path(frame))
    # Before the change this branch named nothing, so the resolver read the family fallback.
    before = _prefer_the_cause(RESOLVER_LOCATOR_MISSED, "UNKNOWN_NAV:PROVIDER_ANSWERED_NOTHING")
    after = _prefer_the_cause(rt._resolution_error or RESOLVER_LOCATOR_MISSED,
                              "UNKNOWN_NAV:PROVIDER_ANSWERED_NOTHING")
    assert point is None, "this frame was expected to be refused"
    return before, after


def main() -> int:
    rows = load_episodes()
    print(f"{SKILL}: {len(rows)} episodes, "
          f"{Counter(r.get('result') for r in rows)}")
    print()

    ocr = OCRService(RapidOCRBackend())
    classifier = OCRPageClassifier()
    # Newest first, and only frames that are actually on disk.
    usable = [r for r in rows if (r.get("before_screenshot") or "").strip()]
    failures = [r for r in usable if r.get("result") == "FAILURE"][-4:]
    successes = [r for r in usable if r.get("result") == "SUCCESS"][-4:]

    counts: Counter = Counter()
    for label, group in (("FAILURE", failures), ("SUCCESS", successes)):
        print("=" * 100)
        print(f"{label} frames")
        print("=" * 100)
        for row in group:
            frame = Path(row["before_screenshot"])
            got = verdict(frame, str(row.get("role_id") or ""), ocr)
            counts[(label, got["guard"])] += 1
            print(f"  {row.get('recorded_at')}  role={got['role']}  err={row.get('recognition_error')!r}")
            print(f"    frame   : {frame.name}")
            print(f"    reader  : recognized={got.get('recognized')} "
                  f"details_visible={got.get('details_visible')} entries={got.get('entries')} "
                  f"dates={got.get('visible_dates')}")
            if got.get("chosen") is not None:
                print(f"    chosen  : {got.get('chosen')!r} ({got.get('chosen_id')}) "
                      f"tap_norm={got.get('tap_norm')}")
            if got.get("why"):
                print(f"    why     : {got['why']}")
                print(f"    ids     : {got.get('row_ids')}")
            if got.get("detail"):
                print(f"    detail  : {got['detail']}")
            print(f"    GUARD   : {got['guard']}")
            if got["guard"] != "PASS" and frame.is_file():
                before, after = ledger_code(frame, str(row.get("role_id") or ""),
                                            classifier, ocr)
                print(f"    LEDGER  : recorded before = {before}")
                print(f"              recorded now    = {after}")
            view = classifier_view(frame, ocr, classifier)
            print(f"    RUNTIME : {view}")
            if (view.get("calendar_details_visible") is True
                    and view.get("calendar_detail_recognized") is not True):
                print("    ^^ DISAGREEMENT: the calendar reading says a detail is visible, "
                      "the detail reader does not recognise one.")
                print("       brain.decide needs calendar_detail.recognized to route BACK, so it "
                      "asks for the next detail instead; the resolver then refuses.")
            print()

    print("=" * 100)
    print("summary")
    print("=" * 100)
    for key, value in sorted(counts.items()):
        print(f"  {key[0]:8s} -> {key[1]:36s} {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
