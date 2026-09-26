# -*- coding: utf-8 -*-
"""BEAR_READINESS_AUDIT — hard true/false readiness for the bear hunt.

Every check reads a real store or the live routing; nothing is assumed.
Output is READY_TO_EXECUTE=true/false with the exact list of missing items.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CHECKS = (
    "EVENT_TIME_CONFIRMED",
    "ROLE_CONFIRMED",
    "WAKE_SCHEDULED",
    "DEVICE_HANDOFF_READY",
    "RALLY_LIST_OPEN",
    "START_RALLY_AVAILABLE",
    "JOIN_RALLY_AVAILABLE",
    "HERO_SELECT_READY",
    "TROOP_SELECT_READY",
    "DISPATCH_READY",
    "JOINED_STATE_VERIFIER_READY",
    "AUTO_JOIN_READY",
)


def _routing_has_node(semantic: str) -> bool:
    routing = json.loads((ROOT / "knowledge/execution/backend_routing.json")
                         .read_text(encoding="utf-8"))
    return any(semantic in (e.get("recognition") or {})
               for e in routing.get("skills", {}).values())


def audit() -> dict:
    result: dict[str, object] = {}

    # EVENT_TIME_CONFIRMED: reserved_start must exist in the timed schedule
    try:
        sched = json.loads((ROOT / "learning/timed_event_schedule.json")
                           .read_text(encoding="utf-8"))
    except FileNotFoundError:
        sched = {}
    result["EVENT_TIME_CONFIRMED"] = bool(sched.get("reserved_start"))

    # ROLE_CONFIRMED / DEVICE_HANDOFF_READY: not yet implemented anywhere
    result["ROLE_CONFIRMED"] = False          # no role reader exists
    result["DEVICE_HANDOFF_READY"] = False    # no handoff procedure exists

    # WAKE_SCHEDULED: a wake entry referencing the bear event
    entries = sched.get("entries") or []
    result["WAKE_SCHEDULED"] = any(
        "BEAR" in json.dumps(e).upper() for e in entries)

    # pipeline nodes present in routing
    result["RALLY_LIST_OPEN"] = _routing_has_node("BTN_ALLIANCE_WAR")
    result["AUTO_JOIN_READY"] = _routing_has_node("BTN_BEAR_AUTO_JOIN")
    result["START_RALLY_AVAILABLE"] = _routing_has_node("BTN_START_RALLY")
    result["JOIN_RALLY_AVAILABLE"] = _routing_has_node("BTN_JOIN_ROW")
    result["HERO_SELECT_READY"] = _routing_has_node("RALLY_HERO_SELECT")
    result["TROOP_SELECT_READY"] = _routing_has_node("RALLY_TROOP_SELECT")
    result["DISPATCH_READY"] = _routing_has_node("RALLY_DISPATCH_CONFIRM")
    result["JOINED_STATE_VERIFIER_READY"] = False  # no state reader exists

    missing = [k for k in CHECKS if not result.get(k)]
    return {
        "READY_TO_EXECUTE": not missing,
        "checks": result,
        "missing": missing,
    }


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    out = audit()
    print(json.dumps(out, ensure_ascii=False, indent=1))
