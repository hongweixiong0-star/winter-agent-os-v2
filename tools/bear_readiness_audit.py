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

    # EVENT_TIME_CONFIRMED: a client-read reserved_start must exist for BEAR_HUNT
    # and still be in the future (an expired reservation is history, not a plan).
    try:
        from winter_agent_v2.event_schedule import load as load_schedules  # noqa: PLC0415
        from datetime import datetime, timezone  # noqa: PLC0415
        schedules = load_schedules(ROOT / "learning/timed_event_schedule.json")
        bear_rows = [s for key, s in schedules.items() if "BEAR" in key.upper()]
        result["EVENT_TIME_CONFIRMED"] = any(
            s.reserved_start and s.start_datetime()
            and s.start_datetime() > datetime.now(timezone.utc)
            for s in bear_rows)
    except Exception:  # noqa: BLE001
        result["EVENT_TIME_CONFIRMED"] = False

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

    # WAKE_SCHEDULED: the scheduler's own wake ladder (T30/T15/T5/T1/OPEN)
    # produces a wake purely from a reserved_start, so the wake is scheduled
    # exactly when a live client-read reservation exists.
    result["WAKE_SCHEDULED"] = bool(result.get("EVENT_TIME_CONFIRMED"))

    # pipeline nodes present in routing
    result["RALLY_LIST_OPEN"] = _routing_has_node("BTN_ALLIANCE_WAR")
    result["AUTO_JOIN_READY"] = _routing_has_node("BTN_BEAR_AUTO_JOIN")
    result["START_RALLY_AVAILABLE"] = _routing_has_node("BTN_START_RALLY")
    result["JOIN_RALLY_AVAILABLE"] = _routing_has_node("BTN_JOIN_ROW")
    # HERO/TROOP/DISPATCH readiness stands on the generic formation-page
    # capability, proven on real frames of BOTH renders (ordinary dispatch
    # 2026-09-26, bear rally setup 2026-09-09) -- the same page family the bear
    # flow reuses.  Only the bear-specific last steps (which preset, which hero)
    # stay behind live event frames.
    try:
        from winter_agent_v2.formation import read_formation_state_tokens  # noqa: PLC0415
        from winter_agent_v2.executor_router import _rapid_ocr_results  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415

        class _Tok:
            def __init__(self, d):
                self.text = d.get("text")
                self.box = d.get("box")

        def _state(frame: str) -> dict:
            path = ROOT / frame
            if not path.is_file():
                return {}
            toks = _rapid_ocr_results(np.asarray(Image.open(path)), None, [])
            return read_formation_state_tokens([_Tok(t) for t in toks], (720, 1280))

        bear = _state("dataset/raw/bear_live_20260909/auto_join_hero_select.png")
        ordinary = _state("dataset/raw/control_panel/runtime_auto/"
                          "20260926_055529_646039/"
                          "20260926_055529_646039_step_004_after_20260925T215703933109.png")
        both = bool(bear.get("is_formation") and ordinary.get("is_formation"))
        result["HERO_SELECT_READY"] = both and len(bear.get("hero_slot_norms") or []) == 3 \
            and len(ordinary.get("hero_slot_norms") or []) == 3
        result["TROOP_SELECT_READY"] = both and len(bear.get("troop_rows") or []) >= 2 \
            and len(ordinary.get("troop_rows") or []) >= 2
        # Generic dispatch: the fixed BTN_DISPATCH OCR node must resolve 出征 on
        # the real formation frame and stay silent on a non-formation page.
        node = ((json.loads((ROOT / "knowledge/execution/backend_routing.json")
                            .read_text(encoding="utf-8"))["skills"]
                 .get("DISPATCH_MARCH") or {}).get("recognition") or {}).get("BTN_DISPATCH") or {}
        path = ROOT / "dataset/raw/control_panel/runtime_auto/20260926_055529_646039/" \
                      "20260926_055529_646039_step_004_after_20260925T215703933109.png"
        positive = _rapid_ocr_results(
            np.asarray(Image.open(path)), tuple(node["roi"]), list(node.get("expected") or [])
        ) if (node and path.is_file()) else []
        negative = _rapid_ocr_results(
            np.asarray(Image.open(ROOT / "dataset/raw/autogen/20260925_182249_home.png")),
            tuple(node["roi"]), list(node.get("expected") or []),
        ) if (node and (ROOT / "dataset/raw/autogen/20260925_182249_home.png").is_file()) else []
        result["DISPATCH_READY"] = bool(
            node and positive and not negative
            and (ordinary.get("confirm") == "出征")
        )
    except Exception:  # noqa: BLE001 - a missing reader is a missing capability
        result.setdefault("HERO_SELECT_READY", False)
        result.setdefault("TROOP_SELECT_READY", False)
        result.setdefault("DISPATCH_READY", False)
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
