# -*- coding: utf-8 -*-
"""Register the LIVE-verified fishing tournament as production capability.

Run once.  Idempotent: it upgrades the existing registry entry rather than adding
a duplicate, and rewrites the measured rules + role-scoped state from the numbers
actually observed on the device.

.. warning::
   **Do not re-run this as a historical replay.**  It was written before the operator's
   FISHING TOURNAMENT — NORMAL BAIT MAX SCORE POLICY V2 (2026-09-30), and its ``tasks``
   list used to include ``USE_FREE_SPECIAL_FISHING``.  Re-running the old version would
   put a policy-forbidden action back into the registry, which is the one thing §4 says
   must not happen.  The list below has been corrected to match the current policy; if
   this file is ever used again, re-read §4 first and check that
   ``config/policy_state.json`` ``disabled_goals`` is still what the registry agrees with.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------- 1. registry
p = ROOT / "knowledge/events/event_registry.json"
d = json.loads(p.read_text(encoding="utf-8"))
ev = next(e for e in d["events"] if e["event_id"] == "FISHING_TOURNAMENT")
ev.update({
    "name": "钓鱼锦标赛",
    "aliases": ["钓鱼锦标赛", "钓鱼大赛", "冰钓", "Fishing Tournament", "FISHING_TOURNAMENT"],
    "type": "SOLO_MINIGAME_EVENT",
    "generic_flow": ["DISCOVER", "READ_STATE", "CLAIM_FREE", "PREPARE", "FISH",
                     "VERIFY_RESULT", "CLAIM_REWARDS"],
    # POLICY V2 §4: USE_FREE_SPECIAL_FISHING is deliberately absent.  Special-mode fishing is
    # forbidden even when the attempt is free, so it is not a task -- see
    # ``policy_disabled_tasks`` in the registry for where it is recorded instead.
    "tasks": ["CLAIM_FISHING_FREE_REWARD", "USE_FISHING_BAIT", "UPGRADE_FISHING_KIT",
              "CLAIM_FISHING_DAILY_REWARD", "CLAIM_FISHING_COLLECTION_REWARD"],
    "entry": "WORLD_MAP/RIGHT_RAIL/钓鱼锦标赛",
    "entry_geometry_720x1280": {"home_icon": [664, 476], "normal_stage": [500, 1170],
                                "treasure_stage": [200, 1170], "tutorial_tap": [357, 632],
                                "exit_button": [212, 1121]},
    "gate": "VERIFIED",
    "live_timing": {
        "source": "LIVE_CLIENT",
        "read_at": "2026-09-29T22:48:41+08:00",
        "printed_remaining": "2天01:10:45",
        "season": "冬季",
        "calendar_window_from_prior_observation": {
            "start": "2026-09-29 00:00", "end": "2026-10-01 24:00",
            "ref": "knowledge/events/fishing_tournament_live_20260928.json"},
        "note": "NEVER hardcode web-guide dates; read the countdown off the client each time.",
    },
    "readiness": {"EVENT_CONFIRMED_LIVE": True, "ENTRY_REACHABLE": True, "STATE_READABLE": True,
                  "MANUAL_PLAY_VERIFIED": True, "CONTINUOUS_CONTROL": "LIVE_VERIFIED",
                  "RESULT_VERIFIER": True, "BAIT_TIMER": True},
    "resolved_gaps": ["FISHING_MINIGAME_VISION", "MAA_STEERING", "RESULT_VERIFIER"],
})
p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
print("registry upgraded:", ev["event_id"], ev["gate"])

# ------------------------------------------------------------------ 2. rules
rules = {
    "schema_version": "1.0",
    "event_id": "FISHING_TOURNAMENT",
    "source": "LIVE_DEVICE_EXPLORATION_2026-09-29",
    "evidence_root": "dataset/raw/fishing_tournament/",
    "resource_model": {
        "bait": {"observed": "10/10 at first read, then 7/10, then 6/10, 5/10 after two runs",
                 "cap_observed": 10, "consumed_per_level": 1, "is_timer_resource": True,
                 "operator_prior": "start 5, ~3h per recovery, cap 10",
                 "rule": "read LIVE every time; treat bait as a Global Scheduler timer resource"},
        "treasure_tickets": {"observed": 14,
                             "note": "shown next to a + button; buying is POLICY_BLOCKED"},
        "currencies": {"冰钓积分": "per-run score, 0 -> 190 after one run",
                       "coins_shells": "per-run rewards, 10+10 per caught fish"},
    },
    "gear": {"components": ["鱼线", "鱼钩", "鱼坠"], "levels_observed": 1,
             "cost_units": {"鱼线": "100米", "鱼钩": 11, "鱼坠": "0米"},
             "upgrade_currency": "FISHING_TOKENS (event-internal)",
             "policy": "USE_OWNED_ITEM only; gem / real-money purchases are BLOCKED"},
    "levels": {"普通关卡": {"cost": 1, "id": "NORMAL"}, "宝藏关卡": {"cost": 1, "id": "TREASURE"}},
    "level_flow_measured": {
        "1_tutorial": "FIRST ever level only: a large hand points at a circle on the ice; tap (357,632)",
        "2_cutscene": "skip button ~(634,94); ~5-16 s; plays on the first level only",
        "3_ready": "countdown 3-2-1 over the fisherman; HUD 0M/100M appears",
        "4_gameplay": ("a vertical line hangs from the rod; steer LEFT/RIGHT.  HUD: depth 0M/100M, "
                       "fish n/11, shields n/2.  Unsteered, a level ended after ~4 s at 47-62 m"),
        "5_result": "本次收获 / 新纪录 / 下潜深度 NN米 / fish cards / 退出 + 冰钓礼券",
        "6_popup": ("a 图鉴 popup can block afterwards: 恭喜您获得新图鉴 / 点击任意位置继续 "
                    "-> tap anywhere"),
    },
    "vision_measured": {
        "line": {"method": "argmax of dark(<60) pixel count per column in water ROI (120,430)-(620,1180)",
                 "observed": "line_x 350-352, dark count 126-600, runner-up column only 26 => 6-19x separation",
                 "validated": "18/18 real gameplay frames detected; 13/13 non-gameplay frames correctly refused"},
        "hook": {"method": "green glowing marker, HSV (40,120,150)-(85,255,255), blob ~25x34",
                 "observed": "centroid tracks the hook, y 577..1029", "area_px": "396-450"},
        "depth_proxy": "hook_y, and the dark-pixel count which grows with depth — no per-frame OCR needed",
        "fish_obstacles": "warm-hue blobs in the water; below the hook = fish, above = ice scenery",
    },
    "control_measured": {
        "axis": "horizontal only: line x is the control axis, y is fixed",
        "finger_to_line_gain": 0.5,
        "gain_evidence": "finger 382->254 (128 px) moved the line 350->286 (64 px), read from pixels",
        "first_move_absorbed_ticks": 5,
        "first_move_note": "matches the PHASE 4 world-map finding: the client eats the first motion after touch_down",
        "loop_rate_live_hz": 21.28,
        "capture_ms_p50": 13.82, "vision_ms_p50": 3.68, "input_ms_p50": 0.0,
        "capture_hz_max": 59.91, "capture_hz_static_page": 91.3,
    },
    "verifier_signals": {
        "MINIGAME_STARTED": "HUD 0M/100M present",
        "CONTROL_SESSION_RAN": "the servo sent at least one move",
        "RESULT_PAGE": "本次收获 or 下潜深度 present",
        "BAIT_DECREASED": "home bait counter strictly lower after the run",
        "POINTS_INCREASED": "我的冰钓积分 increased (0 -> 190 observed)",
    },
    "policy": {"USE_OWNED_ITEM": "allowed (free bait, tickets already owned)",
               "BUY_ITEM": "BLOCK by default (gems)",
               "REAL_MONEY": "PERMANENTLY_BLOCK",
               "not_verified": "whether exiting mid-level refunds the bait — NOT verified, so NOT relied on"},
    "blockers": [],
}
(ROOT / "knowledge/events/fishing_tournament_rules.json").write_text(
    json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
print("rules written")

# ------------------------------------------------------------- 3. role state
now = datetime.now(timezone.utc)
state = {
    "schema_version": "1.0",
    "note": "role-scoped: bait / gear / points / collections are NEVER shared between roles",
    "roles": {
        "ROLE_A": {"role_id": "1063040265", "name": "[ioi]零氪纯盾流",
                   "bait_current": 5, "bait_cap": 10,
                   "next_bait_at": (now + timedelta(hours=3)).isoformat(timespec="seconds"),
                   "last_fishing_at": now.isoformat(timespec="seconds"),
                   "points_today": 190, "line_level": 1, "hook_level": 1, "sinker_level": 1,
                   "free_special_attempts": "UNKNOWN", "collection_seen": 1, "collection_new": 1,
                   "status": "READY"},
        "ROLE_B": {"role_id": "1061663148", "name": "[DIW]xhw",
                   "bait_current": None, "bait_cap": None, "next_bait_at": None,
                   "last_fishing_at": None, "points_today": None,
                   "line_level": None, "hook_level": None, "sinker_level": None,
                   "status": "STATE_NOT_READ",
                   "note": "ROLE_B fishing state has NOT been read yet — do not assume A's values"},
    },
    "bait_is_a_timer": "bait == cap must raise priority so natural recovery is not wasted",
}
(ROOT / "learning/fishing_state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2),
                                                  encoding="utf-8")
print("state written")

# ------------------------------------------------------------- 4. occurrence
run = {
    "id": "FISHING_RUN_20260929T231017",
    "role": "ROLE_A (session role)",
    "entry": "world map 钓鱼锦标赛 (664,476) -> 普通关卡 (500,1170) -> tutorial tap (357,632)",
    "flow": "MINIGAME_STARTED -> CONTROL_SESSION_RAN -> RESULT_PAGE",
    "controller": "VisualServoSession + FishingSessionController (26 calibrate ticks, then AUTO)",
    "bait": {"before": 6, "after": 5, "decreased": True},
    "points": {"before": 0, "after": 190},
    "depth_m": 54,
    "result_page": True,
    "control": {"frames": 460, "duration_s": 25.047, "moves_sent": 36,
                "loop_hz_median": 21.28, "presses": 1, "touch_stuck": 0},
    "calibration": {"targets": [255, 445],
                    "observed_line_x": [350, 350, 350, 350, 350, 350, 330, 309, 309, 286],
                    "finger_x": [382, 368, 354, 340, 325, 311, 297, 283, 268, 254],
                    "gain": 0.5},
    "verifier": {"MINIGAME_STARTED": True, "CONTROL_SESSION_RAN": True, "RESULT_PAGE": True,
                 "BAIT_DECREASED": True, "POINTS_INCREASED": True, "DEPTH_M": "54"},
    "level": "FISHING_RUN L4",
    "evidence": "dataset/raw/fishing_tournament/run_20260929T231017/",
}
with (ROOT / "learning/fishing_runs.jsonl").open("a", encoding="utf-8") as f:
    f.write(json.dumps(run, ensure_ascii=False) + "\n")
print("occurrence written")
