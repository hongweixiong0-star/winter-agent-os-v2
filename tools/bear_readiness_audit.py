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

    # ROLE_CONFIRMED: a role identity must be stored from a real 领主档案 read
    role_path = ROOT / "learning" / "bear_role.json"
    result["ROLE_CONFIRMED"] = False
    if role_path.is_file():
        try:
            role = json.loads(role_path.read_text(encoding="utf-8"))
            result["ROLE_CONFIRMED"] = bool(role.get("role_name"))
        except (OSError, json.JSONDecodeError):
            pass

    # DEVICE_HANDOFF_READY: the lease mechanism must exist, the store must be
    # readable, and the current lease must not be stuck (released or expired).
    try:
        from winter_agent_v2.device_lease import DeviceLease
        lease_path = ROOT / "learning" / "DEVICE_LEASE.json"
        store_ok = lease_path.is_file()
        unstuck = True
        if store_ok:
            record = json.loads(lease_path.read_text(encoding="utf-8"))
            # A record without released_at is only a problem while unexpired:
            # an expired record is reclaimable by design (TTL).
            if record.get("released_at") is None and record.get("expires_at"):
                from datetime import datetime, timezone
                try:
                    exp = datetime.fromisoformat(record["expires_at"])
                    unstuck = exp <= datetime.now(timezone.utc)
                except ValueError:
                    unstuck = False
        result["DEVICE_HANDOFF_READY"] = bool(store_ok and unstuck)
    except Exception:  # noqa: BLE001
        result["DEVICE_HANDOFF_READY"] = False

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
    # JOINED_STATE_VERIFIER_READY: the joined-state reader must exist and
    # return a valid state enum on the latest real rally frame.  Valid enum:
    # JOINED / NOT_JOINED / UNKNOWN (UNKNOWN never feeds a verifier PASS).
    try:
        from tools.bear_joined_state import read_joined_state  # noqa: PLC0415
        probe = ROOT / "dataset/raw/autogen/r14_war.png"
        if probe.is_file():
            state = read_joined_state(probe).get("state")
            result["JOINED_STATE_VERIFIER_READY"] = state in {"JOINED", "NOT_JOINED", "UNKNOWN"}
        else:
            result["JOINED_STATE_VERIFIER_READY"] = False
    except Exception:  # noqa: BLE001
        result["JOINED_STATE_VERIFIER_READY"] = False

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
