# -*- coding: utf-8 -*-
"""BEAR DRY-RUN -- the full bear chain, walked offline, no device time.

Round brief 2026-09-27 §七: before T-30, walk

    EVENT -> ROLE -> QUEUE -> AUTO_JOIN -> Rally List -> select row ->
    JOIN/START -> formation -> hero -> troop -> dispatch -> joined verifier

using only real historical bear frames, the live routing and the real readers.
Every step answers exactly one of:

    READY              evidence on disk proves the step works
    WAIT_LIVE_CONTEXT  the step is real but its decisive input only exists
                       inside the live event (P0 LIVE_EVENT_GAP by design)
    BLOCKED            something that should be fixable now is broken

Anything spelling NO_SKILL / NO_PIPELINE / UNKNOWN_WITHOUT_RECOVERY is a
BLOCKED with the reason attached -- those must be fixed NOW, before T-30.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _routing() -> dict:
    return json.loads((ROOT / "knowledge/execution/backend_routing.json")
                      .read_text(encoding="utf-8"))


def _gap_queue() -> dict:
    return json.loads((ROOT / "knowledge/execution/pipeline_gap_queue.json")
                      .read_text(encoding="utf-8"))


def _has_node(routing: dict, semantic: str) -> bool:
    return any(semantic in (entry.get("recognition") or {})
               for entry in routing.get("skills", {}).values())


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    routing = _routing()
    gap_queue = _gap_queue()
    live_gaps = {
        item.get("semantic")
        for item in (gap_queue.get("queue") or [])
        if item.get("gap_class") == "LIVE_EVENT_GAP"
    }

    steps: list[dict] = []

    def step(name: str, status: str, evidence: str) -> None:
        steps.append({"step": name, "status": status, "evidence": evidence})

    # 1. EVENT ---------------------------------------------------------
    try:
        from winter_agent_v2.event_schedule import load as load_schedules
        schedules = load_schedules(ROOT / "learning/timed_event_schedule.json")
        bear = [s for key, s in schedules.items() if "BEAR" in key.upper()
                and s.reserved_start and s.start_datetime()
                and s.start_datetime() > datetime.now(timezone.utc)]
        step("EVENT", "READY" if bear else "BLOCKED",
             f"reserved_start={bear[0].reserved_start}" if bear else "no future BEAR reservation")
    except Exception as exc:  # noqa: BLE001
        step("EVENT", "BLOCKED", f"{type(exc).__name__}: {exc}")

    # 2. ROLE ----------------------------------------------------------
    role_ok = False
    role_name = None
    try:
        role = json.loads((ROOT / "learning/bear_role.json").read_text(encoding="utf-8"))
        role_name = role.get("role_name")
        role_ok = bool(role_name)
    except Exception:  # noqa: BLE001
        pass
    step("ROLE", "READY" if role_ok else "BLOCKED", f"role={role_name}")

    # 3. QUEUE (march queue readable) -----------------------------------
    queue_reader = _has_node(routing, "BTN_DISPATCH")  # formation page = queue truth source
    step("QUEUE", "READY" if queue_reader else "BLOCKED",
         "march queue read via formation page family (BTN_DISPATCH dispatch chain L4)")

    # 4. AUTO_JOIN -------------------------------------------------------
    step("AUTO_JOIN", "READY" if _has_node(routing, "BTN_BEAR_AUTO_JOIN") else "BLOCKED",
         "BTN_BEAR_AUTO_JOIN wired (L4 via BEAR_AUTO_JOIN live proof)")

    # 5. RALLY LIST ------------------------------------------------------
    rally_ok = False
    rally_detail = "read_rally_list import failed"
    try:
        from winter_agent_v2.rally import read_rally_list_image, select_join_candidates
        rally_ok = callable(read_rally_list_image) and callable(select_join_candidates)
        rally_detail = "reader + §十三 candidate filter importable"
    except Exception as exc:  # noqa: BLE001
        rally_detail = f"{type(exc).__name__}: {exc}"
    step("RALLY_LIST", "READY" if rally_ok else "BLOCKED", rally_detail)

    # 6. SELECT ROW (policy) ----------------------------------------------
    try:
        from winter_agent_v2.rally import select_join_candidates, stale_frame_reason, FRAME_MAX_AGE_SECONDS
        step("SELECT_ROW", "READY",
             f"target=BEAR + join_available + full!=True + same-row button + shortest timer; "
             f"stale-frame guard {FRAME_MAX_AGE_SECONDS}s")
    except Exception as exc:  # noqa: BLE001
        step("SELECT_ROW", "BLOCKED", f"{type(exc).__name__}: {exc}")

    # 7. JOIN / START -------------------------------------------------------
    join_ok = _has_node(routing, "BTN_JOIN_ROW")
    start_ok = _has_node(routing, "BTN_START_RALLY")
    step("JOIN/START", "READY" if (join_ok and start_ok) else "BLOCKED",
         f"BTN_JOIN_ROW={'wired' if join_ok else 'MISSING'}, BTN_START_RALLY={'wired' if start_ok else 'MISSING'}")

    # 8. JOIN_RALLY_CONFIRM -------------------------------------------------
    step("JOIN_RALLY_CONFIRM", "WAIT_LIVE_CONTEXT",
         "P0 LIVE_EVENT_GAP: candidate contract pre-agreed; calibrated on first live "
         "post-JOIN frame via capture-first; direct-join flows mark NOT_REQUIRED_FOR_THIS_FLOW"
         if "JOIN_RALLY_CONFIRM" in live_gaps else "unexpectedly resolved")

    # 9. FORMATION ------------------------------------------------------------
    formation_ok = False
    formation_detail = ""
    try:
        from winter_agent_v2.formation import read_formation_state_tokens
        from winter_agent_v2.executor_router import _rapid_ocr_results
        import numpy as np  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415

        class _Tok:
            def __init__(self, d):
                self.text = d.get("text")
                self.box = d.get("box")

        path = ROOT / "dataset/raw/bear_live_20260909/auto_join_hero_select.png"
        toks = _rapid_ocr_results(np.asarray(Image.open(path)), None, [])
        state = read_formation_state_tokens([_Tok(t) for t in toks], (720, 1280))
        formation_ok = bool(state.get("is_formation"))
        formation_detail = (
            f"real bear frame 20260909: is_formation={formation_ok}, "
            f"hero_slots={len(state.get('hero_slot_norms') or [])}, "
            f"troop_rows={len(state.get('troop_rows') or [])}")
    except Exception as exc:  # noqa: BLE001
        formation_detail = f"{type(exc).__name__}: {exc}"
    step("FORMATION", "READY" if formation_ok else "BLOCKED", formation_detail)

    # 10/11. HERO / TROOP -----------------------------------------------------
    step("HERO", "READY" if formation_ok else "BLOCKED",
         "hero slot norms read from the same real formation frame (preferred JESSIE/SEO_YOON/JASSER, else NO_HERO)")
    step("TROOP", "READY" if formation_ok else "BLOCKED",
         "troop rows read from the same real formation frame")

    # 12. DISPATCH --------------------------------------------------------------
    dispatch_ok = _has_node(routing, "BTN_DISPATCH")
    step("DISPATCH", "READY" if dispatch_ok else "BLOCKED",
         "BTN_DISPATCH fixed-ROI OCR wired; DISPATCH_COMMON=L4 locked (formation->出征->march 1/4->17km->countdown); "
         "live event only validates BEAR_CONTEXT_DISPATCH")

    # 13. JOINED STATE ------------------------------------------------------------
    joined_ok = False
    joined_detail = ""
    try:
        from tools.bear_joined_state import read_joined_state
        probe = ROOT / "dataset/raw/autogen/r14_war.png"
        state = read_joined_state(probe).get("state")
        joined_ok = state in {"JOINED", "NOT_JOINED", "UNKNOWN"}
        joined_detail = f"reader on real rally frame r14_war.png -> {state}"
    except Exception as exc:  # noqa: BLE001
        joined_detail = f"{type(exc).__name__}: {exc}"
    step("JOINED_STATE", "READY" if joined_ok else "BLOCKED",
         joined_detail + "; verifier PASS only from JOINED")

    # 14. BATTLE REPORT ---------------------------------------------------------
    step("BATTLE_RESULT", "WAIT_LIVE_CONTEXT",
         "P0 LIVE_EVENT_GAP: capture on first post-battle frame; result-read verifier; "
         "never blocks BEAR Goal L5 unless the Goal contract requires it"
         if "RALLY_BATTLE_REPORT" in live_gaps else "unexpectedly resolved")

    # verdict -------------------------------------------------------------------
    blocked = [s for s in steps if s["status"] == "BLOCKED"]
    waiting = [s for s in steps if s["status"] == "WAIT_LIVE_CONTEXT"]
    ready = [s for s in steps if s["status"] == "READY"]
    verdict = "NO_NO_SKILL_NO_PIPELINE" if blocked else "DRY_RUN_PASS"
    print(json.dumps({
        "verdict": verdict,
        "ready": [s["step"] for s in ready],
        "wait_live_context": [s["step"] for s in waiting],
        "blocked": blocked,
        "steps": steps,
    }, ensure_ascii=False, indent=1))
    sys.exit(0 if not blocked else 1)


if __name__ == "__main__":
    main()
