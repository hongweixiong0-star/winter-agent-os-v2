# 01 — CURRENT TRUTH

- generated_at: `2026-10-18T04:25:58+00:00`
- source: `tools/update_workbuddy_handoff.py` (reads git, registry, capability map, episode stream, snapshot, logs)
- commit: `7dd7bb9c` on `main`

> This file is regenerated. Never hand-edit it; edit the project instead.

## A. Version control

- repository: yes
- last good commit: `e4fd245`
- commits: 1541
- HEAD: `7dd7bb9c` — docs(memory): navigation matrix 待办收口 -- 派生文件 vs 能力提升的判据 (2026-10-18T11:55:44+08:00)
- working tree: 15 dirty file(s)
  - `M .workbuddy-ai/handoff/01_CURRENT_TRUTH.md`
  - ` M .workbuddy-ai/handoff/02_CURRENT_PROGRESS.md`
  - ` M .workbuddy-ai/handoff/03_NEXT_ACTION.md`
  - ` M .workbuddy-ai/handoff/04_OPEN_ISSUES.md`
  - ` M .workbuddy-ai/handoff/05_RECENT_CHANGES.md`
  - ` M .workbuddy-ai/handoff/08_LIVE_METRICS.json`
  - ` M .workbuddy-ai/handoff/09_RUNTIME_STATE.json`
  - ` M .workbuddy-ai/handoff/10_LAST_HANDOFF.md`
  - ` M docs/CAPABILITY_COVERAGE.md`
  - ` M evidence/INDEX.json`
  - ` M knowledge/goals/capability_skill_map.json`
  - ` M tests/test_evidence_integrity.py`
  - ` M tools/update_workbuddy_handoff.py`
  - ` M winter_agent_v2/retention.py`
  - `?? tests/test_the_handoff_agrees_with_the_evidence_ledger.py`

### A2. Public mirror

The repository is PUBLIC, so 'is the mirror current' is part of the truth this file
reports, not a side note. `remote_head` is the local remote-tracking ref: it is as
fresh as the last fetch, and `tools/git_sync.py status` is what refreshes it.

```
SYNC STATE at 2026-10-18T04:25:58+00:00
remote            : https://github.com/hongweixiong0-star/winter-agent-os-v2.git
branch            : main
local_head        : 7dd7bb9ca90e1054b4d6530cb890439f770fdcf5
remote_head       : 3805b7e4faf4cbfeaef8a80d82e69a347a1fa2f0   (local remote-tracking ref; run tools/git_sync.py status to refresh)
unpushed_commits  : 12   (behind: 0)
git_dirty         : True (15 path(s))
last_push_at      : 2026-10-15T10:29:32.618849+00:00
last_push_status  : PUSHED
verdict           : LOCAL IS AHEAD by 12 commit(s) -- run `python tools/git_sync.py push`
```

## B. Runtime

- agent_state: `AUTO_RUNNING`
- runtime_thread_alive: True / scheduler_loop_alive: True
- unexpected_worker_exits: 66
- watchdog_restart_count: 69
- last_fatal_error: None
- stop_reason: None
- page: HOME  march: None/None
- updated_at: 2026-10-17T01:37:18.634185+00:00

## C. Episode stream

- rows: 10223 (production 10223)  modes: {'PRODUCTION': 10223}
- success / failure: 9122 / 1096
- success rate over decided: **0.8927**
- mixed-case `result` rows (normalise on read, never rewrite): 0
- last episode: `{"skill": "TRY_ORDINARY_CONTROL", "result": "FAILURE", "recorded_at": "2026-10-16T23:57:43.134368+00:00", "episode_id": "20261017_075609_006189", "before_screenshot": "E:\\WinterAgent\\dataset\\raw\\control_panel\\runtime_auto\\20261017_075609_006189\\20261017_075609_006189_step_008_before_20261016T235738888141.png", "after_screenshot": ""}`

## D. Registry and lifecycle

- registry total: 156  by_state: {'CANDIDATE': 105, 'VERIFIED': 47, 'BLOCKED': 4}
- live dispatchable (verifier-backed): 144
- BLOCKED skills: ['ALLIANCE_HELP', 'COLLECT_FINISHED_TRAINING_LANCER', 'COLLECT_FINISHED_TRAINING_MARKSMAN', 'COLLECT_FINISHED_TRAINING_SHIELD']
- live_verified: **7**  stable: 56  degraded: 19  only_failed: 7  never_executed: 70

### Never executed

- `ALLIANCE_GIFTS` (VERIFIED)
- `ALLIANCE_HELP` (BLOCKED)
- `ALLIANCE_TECH_CONTRIBUTE` (VERIFIED)
- `ASSIGN_GATHER_HERO` (CANDIDATE)
- `BEAR_AUTO_JOIN` (CANDIDATE)
- `BEAST_HUNT` (VERIFIED)
- `BUILDING_UPGRADE` (VERIFIED)
- `CANCEL_DUPLICATE_TARGET` (VERIFIED)
- `CHECK_ALLIANCE_EVENT` (CANDIDATE)
- `CHECK_MARCH` (VERIFIED)
- `CLAIM_LOGIN_GIFT` (CANDIDATE)
- `CLAIM_OFFLINE_REWARDS` (CANDIDATE)
- `CLAIM_REWARD` (CANDIDATE)
- `CLOSE_ALLIANCE_TECH_DONATION_DETAILS` (CANDIDATE)
- `COLLECT_FINISHED_TRAINING_LANCER` (BLOCKED)
- `COLLECT_FINISHED_TRAINING_MARKSMAN` (BLOCKED)
- `COLLECT_FINISHED_TRAINING_SHIELD` (BLOCKED)
- `COLLECT_MY_REWARDS_ROW` (CANDIDATE)
- `COLLECT_TRAINING_BATCH` (CANDIDATE)
- `DAILY_HERO_RECRUIT` (VERIFIED)
- `DISMISS_ALLIANCE_GENERIC_REWARD` (CANDIDATE)
- `DISMISS_BATTLEFIELD_REVIVAL` (CANDIDATE)
- `DISMISS_BATTLE_VICTORY` (CANDIDATE)
- `DISMISS_DAILY_REWARD` (CANDIDATE)
- `DISMISS_EXPLORATION_REWARD` (VERIFIED)
- `DISMISS_INTEL_REWARD` (VERIFIED)
- `DISMISS_MAIL_GENERIC_REWARD` (CANDIDATE)
- `DISMISS_MAIL_REWARD` (VERIFIED)
- `GATHER_RESOURCE` (VERIFIED)
- `JOIN_RALLY` (CANDIDATE)
- `NAVIGATE_INFANTRY_CAMP` (CANDIDATE)
- `NAVIGATE_RESEARCH_LAB` (CANDIDATE)
- `NAVIGATE_TO` (CANDIDATE)
- `OPEN_ALLIANCE_GIFTS` (CANDIDATE)
- `OPEN_ALLIANCE_TECH_FROM_HOME` (CANDIDATE)
- `OPEN_EVENT` (CANDIDATE)
- `OPEN_GATHER_HERO_PICKER` (CANDIDATE)
- `OPEN_POWER_DETAILS` (CANDIDATE)
- `OPEN_POWER_OVERVIEW` (CANDIDATE)
- `OPEN_RESEARCH` (CANDIDATE)
- `OPEN_TASK_FROM_QUICK_PANEL_ALLIANCE_DONATION` (CANDIDATE)
- `OPEN_TASK_FROM_QUICK_PANEL_LANCER` (CANDIDATE)
- `OPEN_TASK_FROM_QUICK_PANEL_MY_REWARDS` (CANDIDATE)
- `OPEN_TASK_FROM_QUICK_PANEL_RESEARCH` (CANDIDATE)
- `OPEN_TECH_TREE` (CANDIDATE)
- `PLAY_NORMAL_FISHING_LEVEL` (CANDIDATE)
- `READ_COUNTER` (CANDIDATE)
- `READ_EVENT_CALENDAR` (CANDIDATE)
- `READ_INTEL_LIST` (CANDIDATE)
- `READ_REGULAR_EVENT_CARD` (CANDIDATE)
- `READ_TIMER` (CANDIDATE)
- `RECALL_MARCH` (CANDIDATE)
- `RECOVER_HOME` (CANDIDATE)
- `REINFORCE_TARGET` (CANDIDATE)
- `RELAX_RESOURCE_LEVEL` (CANDIDATE)
- `RESEARCH` (CANDIDATE)
- `SELECT_BEAST_TARGET` (VERIFIED)
- `SELECT_DAILY_TAB` (CANDIDATE)
- `SELECT_GATHER_HERO` (CANDIDATE)
- `SELECT_INFANTRY_CAMP` (CANDIDATE)
- `SELECT_INTEL_FIREBEAST_MISSION` (VERIFIED)
- `SELECT_INTEL_RESCUE_SURVIVORS` (VERIFIED)
- `SELECT_MARCH_TO_RECALL` (CANDIDATE)
- `SELECT_RESEARCH_NODE` (CANDIDATE)
- `SELECT_REWARD_OPTION` (CANDIDATE)
- `SEND_MARCH` (CANDIDATE)
- `USE_ACTIVITY_ATTEMPT` (CANDIDATE)
- `VERIFY_GATHERING` (VERIFIED)
- `WAIT` (CANDIDATE)
- `WAIT_FOR_CAMP_MENU` (VERIFIED)

### Only ever failed

- `ALLIANCE_ALLY_GIFT_CLAIM` attempts=1 failure=1
- `OBSERVE_ONLY` attempts=4 failure=0
- `OPEN_ALLIANCE_RECOMMENDED_TECH_NODE` attempts=1 failure=1
- `OPEN_BEAST_SEARCH_TAB` attempts=28 failure=28
- `READ_FISHING_STATE` attempts=1 failure=1
- `SAFE_STOP` attempts=6 failure=6
- `START_RALLY` attempts=1 failure=1

### Stable

- `ATTACK_BEAST_CARD` success=6 rate=0.8571
- `BACK` success=2187 rate=0.9842
- `CLAIM_FREE_STAMINA` success=10 rate=1.0
- `CLEAR_GATHER_HEROES` success=29 rate=1.0
- `CONFIRM_EXPLORATION_IDLE_CLAIM` success=32 rate=0.9143
- `DAILY_CLAIM_REWARDS` success=16 rate=0.8889
- `DISMISS_EXPLORATION_GENERIC_REWARD` success=25 rate=0.8333
- `DISMISS_INTEL_GENERIC_REWARD` success=118 rate=1.0
- `DISMISS_SHARED_REWARD` success=50 rate=0.9615
- `DISPATCH_BEAST` success=7 rate=1.0
- `DISPATCH_INTEL_BEAST` success=69 rate=0.9324
- `DISPATCH_MARCH` success=12 rate=1.0
- `EXECUTE_INTEL_RESCUE_SURVIVORS` success=29 rate=0.9062
- `FOLLOW_DAILY_TASK` success=11 rate=1.0
- `FREE_HERO_RECRUIT_ADVANCED` success=16 rate=0.9412
- `INTEL_BEAST_START_MARCH` success=101 rate=0.9528
- `INTEL_CLAIM_REWARDS` success=140 rate=0.9929
- `INTEL_HERO_DISPATCH` success=48 rate=0.96
- `INTEL_HERO_START_MARCH` success=79 rate=0.9875
- `MAIL_CLAIM_REWARDS` success=54 rate=0.9818
- `OPEN_ALLIANCE` success=18 rate=1.0
- `OPEN_BEAR_RALLY_LIST` success=24 rate=1.0
- `OPEN_BUILDING_UPGRADE` success=37 rate=0.9024
- `OPEN_COMPLETED_TRAINING_CAMP_MARKSMAN` success=13 rate=1.0
- `OPEN_COMPLETED_TRAINING_CAMP_SHIELD` success=15 rate=1.0
- `OPEN_DAILY` success=35 rate=0.9211
- `OPEN_EVENT_CALENDAR_TAB` success=29 rate=0.8788
- `OPEN_EXPLORATION` success=43 rate=0.9556
- `OPEN_HOME` success=299 rate=0.826
- `OPEN_INFANTRY_TRAINING` success=51 rate=0.9808
- `OPEN_INTEL` success=1193 rate=0.9811
- `OPEN_INTEL_BEAST_TARGET` success=108 rate=0.8438
- `OPEN_INTEL_HERO_JOURNEY_TARGET` success=94 rate=1.0
- `OPEN_LOGIN_GIFT` success=16 rate=1.0
- `OPEN_MAIL` success=35 rate=0.9722
- `OPEN_MAP` success=880 rate=0.9865
- `OPEN_QUICK_PANEL` success=857 rate=1.0
- `OPEN_STAMINA_SOURCES` success=21 rate=0.9545
- `OPEN_TASK_FROM_QUICK_PANEL_HERO_RECRUIT` success=15 rate=1.0
- `OPEN_TASK_FROM_QUICK_PANEL_PET_TREASURE` success=42 rate=1.0
- `PRINTED_TAP` success=108 rate=0.9076
- `RECONNECT_SESSION` success=5 rate=1.0
- `RETURN_EVENT_CALENDAR` success=32 rate=1.0
- `SCAN_MAP_FOR_BEAST` success=10 rate=1.0
- `SCROLL_QUICK_PANEL_TASKS` success=142 rate=0.953
- `SEARCH_RESOURCE` success=267 rate=0.9536
- `SELECT_GIANT_BEAST_TAB` success=187 rate=0.9842
- `SELECT_INTEL_BEAST_MISSION` success=6 rate=0.8571
- `SELECT_INTEL_PIN` success=710 rate=0.9889
- `SELECT_MAIL_ALLIANCE_TAB` success=11 rate=1.0
- `SELECT_MAIL_SYSTEM_TAB` success=8 rate=1.0
- `SELECT_RESOURCE` success=39 rate=0.975
- `START_GATHER` success=17 rate=1.0
- `SUBMIT_BEAST_SEARCH` success=6 rate=1.0
- `SUBMIT_RESOURCE_SEARCH` success=199 rate=1.0
- `TRAIN_TROOPS` success=33 rate=0.9167

### Degraded

- `CLOSE_POPUP` success=6 failure=4 rate=0.6
- `DISMISS_DAILY_GENERIC_REWARD` success=27 failure=8 rate=0.7714
- `EXPLORATION_IDLE_CLAIM` success=34 failure=9 rate=0.7907
- `OPEN_COMPLETED_TRAINING_CAMP_LANCER` success=15 failure=7 rate=0.6818
- `OPEN_EVENT_CALENDAR_DETAIL` success=32 failure=46 rate=0.4103
- `OPEN_EVENT_CALENDAR_FROM_HOME` success=57 failure=70 rate=0.4488
- `OPEN_EVENT_CALENDAR_FROM_MAP` success=11 failure=9 rate=0.55
- `OPEN_INTEL_RESCUE_SURVIVORS_TARGET` success=23 failure=6 rate=0.7931
- `OPEN_TASK_FROM_QUICK_PANEL_BUILDING` success=50 failure=22 rate=0.6944
- `SCROLL_QUICK_PANEL_BACK` success=9 failure=14 rate=0.3913
- `SCROLL_REGULAR_EVENT_TABS` success=6 failure=22 rate=0.2143
- `SELECT_BEAST_TARGET_LABELLED` success=6 failure=3 rate=0.6667
- `SELECT_BEAST_TARGET_MAMMOTH` success=12 failure=142 rate=0.0779
- `SELECT_MAIL_REPORT_TAB` success=5 failure=2 rate=0.7143
- `SUBMIT_GIANT_BEAST_SEARCH` success=43 failure=161 rate=0.2108
- `TAP_FOCUSED_TRAINING_CAMP_LANCER` success=11 failure=11 rate=0.5
- `TAP_FOCUSED_TRAINING_CAMP_MARKSMAN` success=11 failure=11 rate=0.5
- `TAP_FOCUSED_TRAINING_CAMP_SHIELD` success=10 failure=11 rate=0.4762
- `TRY_ORDINARY_CONTROL` success=93 failure=247 rate=0.2735

## E. Top failures

Failure | Count | Top skills
---|---:|---
`SEMANTIC_TARGET_NOT_VERIFIED` | 376 | TRY_ORDINARY_CONTROL(245), OPEN_HOME(34), OPEN_EVENT_CALENDAR_DETAIL(23)
`EVENT_CALENDAR_NOT_OPEN` | 76 | OPEN_EVENT_CALENDAR_FROM_HOME(68), OPEN_EVENT_CALENDAR_FROM_MAP(8)
`REGULAR_EVENT_TABS_SCROLL_NOT_PROVEN` | 22 | SCROLL_REGULAR_EVENT_TABS(22)
`ORDINARY_CONTROL_ALREADY_USED_THIS_RUN` | 1 | TRY_ORDINARY_CONTROL(1)
`GIANT_BEAST_SEARCH_NOT_PROVEN` | 161 | SUBMIT_GIANT_BEAST_SEARCH(161)
`BEAST_TARGET_SELECTION_NOT_PROVEN` | 145 | SELECT_BEAST_TARGET_MAMMOTH(142), SELECT_BEAST_TARGET_LABELLED(3)
`SAFE_BACK_NOT_PROVEN` | 35 | BACK(35)
`FOCUSED_CAMP_ACTION_BAR_NOT_PROVEN` | 33 | TAP_FOCUSED_TRAINING_CAMP_MARKSMAN(11), TAP_FOCUSED_TRAINING_CAMP_SHIELD(11), TAP_FOCUSED_TRAINING_CAMP_LANCER(11)
`OPEN_HOME_NOT_PROVEN` | 29 | OPEN_HOME(29)
`EVENT_CALENDAR_DETAIL_NOT_PROVEN` | 23 | OPEN_EVENT_CALENDAR_DETAIL(23)

## F. Goal capability coverage

- model: Goal -> Canonical Capability -> Registered Skill -> Production Evidence
- summary: {"total": 20, "fully_live_verified": 3, "partial": 9, "never_tried": 5, "blocked": 3, "degraded": 0, "missing": 0, "fully_live_verified_percent": 15.0, "never_tried_percent": 25.0, "automation_coverage_mean": 0.7708, "live_coverage_mean": 0.4012}

Goal | Status | Runtime | design | impl | live | stable | blocked by
---|---|---|---:|---:|---:|---:|---
CLEAR_INTEL | PARTIAL | RUNTIME_DISCOVERED | 100% | 100% | 83% | 83% | -
AVOID_STAMINA_WASTE | PARTIAL | RUNTIME_DISCOVERED | 100% | 100% | 67% | 33% | -
KEEP_MARCHES_PRODUCTIVE | PARTIAL | RUNTIME_DISCOVERED | 100% | 100% | 86% | 86% | -
KEEP_BUILDING_PRODUCTIVE | PARTIAL | RUNTIME_DISCOVERED | 100% | 100% | 50% | 0% | -
KEEP_RESEARCH_PRODUCTIVE | NEVER_TRIED | RUNTIME_DISCOVERED | 100% | 100% | 0% | 0% | -
KEEP_TRAINING_PRODUCTIVE | FULLY_LIVE_VERIFIED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 100% | -
MAIL_ROUTINE | PARTIAL | RUNTIME_DISCOVERED | 100% | 100% | 75% | 75% | -
DAILY_ACTIVITY_TARGET | PARTIAL | RUNTIME_DISCOVERED | 100% | 75% | 75% | 50% | READ_DAILY_PROGRESS
CLAIM_FREE_REWARDS | FULLY_LIVE_VERIFIED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 100% | -
CLAIM_EXPLORATION_IDLE | FULLY_LIVE_VERIFIED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 100% | -
ALLIANCE_ROUTINE | PARTIAL | NOT_A_RUNTIME_GOAL | 100% | 75% | 25% | 25% | ALLIANCE_HELP
EVENT_MINIMUM_GUARANTEE | PARTIAL | RUNTIME_DISCOVERED | 100% | 83% | 17% | 17% | CLAIM_EVENT_TIER
ALLIANCE_TIMED_EVENTS | NEVER_TRIED | RUNTIME_DISCOVERED | 100% | 33% | 0% | 0% | CLAIM_EVENT_TIER, READ_ALLIANCE_EVENT_TIMER
PARTICIPATE_BEAR | PARTIAL | RUNTIME_DISCOVERED | 100% | 75% | 25% | 25% | SELECT_TROOP_PRESET
ALLIANCE_MOBILIZATION_ICEFIELD_BEAST | NEVER_TRIED | RUNTIME_DISCOVERED | 100% | 100% | 0% | 0% | -
OBSERVE_FISHING_STATE | NEVER_TRIED | RUNTIME_DISCOVERED | 100% | 100% | 0% | 0% | -
USE_NORMAL_FISHING_BAIT | NEVER_TRIED | RUNTIME_DISCOVERED | 100% | 100% | 0% | 0% | -
USE_FREE_ARENA_ATTEMPTS | BLOCKED | RUNTIME_DISCOVERED | 100% | 0% | 0% | 0% | OPEN_ARENA_PAGE, READ_FREE_ATTEMPTS, SELECT_ARENA_OPPONENT, START_ARENA, VERIFY_ARENA_RESULT
LABYRINTH_DAILY | BLOCKED | RUNTIME_DISCOVERED | 100% | 0% | 0% | 0% | OPEN_LABYRINTH_PAGE, READ_LABYRINTH_ATTEMPTS, START_LABYRINTH, VERIFY_LABYRINTH_RESULT
TRAVEL_SUPPLY | BLOCKED | RUNTIME_DISCOVERED | 100% | 0% | 0% | 0% | CLAIM_FREE_TRAVEL_SUPPLY, OPEN_TRAVEL_SUPPLY_COUNTER, OPEN_TRAVEL_SUPPLY_ENTRY

## G. Evidence integrity

- status: **PASS**
- referenced screenshots: 20039  present: 19930
- missing: []
- episodes carrying screenshot references: 10219

## H. Commercial bot parity

- present: True
- summary: {"features_tracked": 21, "features_with_live_success": 10, "parity_fraction": 0.4762}
- features without live evidence: ['VIP', 'ALLIANCE_HELP', 'PROMOTE', 'HEAL', 'RESEARCH', 'ARENA', 'LABYRINTH', 'JOIN_RALLY', 'START_RALLY', 'BEAR', 'PET']

## I. Latest runtime log

- {"path": "E:\\WinterAgent\\learning\\control_panel\\latest.log", "modified_at": "2026-10-17T01:37:23+00:00", "size_bytes": 1156, "last_stop_reason": null}
- recent crash reports: ['E:\\WinterAgent\\learning\\control_panel\\crashes\\20261015_180840_190109_auto_subprocess.json', 'E:\\WinterAgent\\learning\\control_panel\\crashes\\20261015_182349_369335_auto_subprocess.json', 'E:\\WinterAgent\\learning\\control_panel\\crashes\\20261015_185827_507369_auto_subprocess.json', 'E:\\WinterAgent\\learning\\control_panel\\crashes\\20261017_001227_841313_auto_subprocess.json', 'E:\\WinterAgent\\learning\\control_panel\\crashes\\20261017_013845_485252_auto_subprocess.json']

## J. Backend axis (MAA vs ADB)

- source: `learning/executor_backend.jsonl` vs `knowledge/execution/backend_routing.json`
- ledger rows: 20000 (last 200 summarised)
- used_backend: {"ADB": 184, "MAA": 16}
- capture_backend: {"ADB_EXEC_OUT": 184, "MAA_MUMU_EXTRAS": 16}
- promoted to MAA in routing: 37 ['BACK', 'BEAR_AUTO_JOIN', 'CLOSE_POPUP', 'COLLECT_TRAINING_BATCH', 'DAILY_CLAIM_REWARDS', 'DISMISS_BATTLE_VICTORY', 'DISPATCH_MARCH', 'EXPLORATION_IDLE_CLAIM', 'FOLLOW_DAILY_TASK', 'FREE_HERO_RECRUIT_ADVANCED', 'INTEL_CLAIM_REWARDS', 'INTEL_HERO_DISPATCH', 'INTEL_HERO_START_MARCH', 'JOIN_RALLY', 'MAIL_CLAIM_REWARDS', 'OPEN_ALLIANCE', 'OPEN_ALLIANCE_GIFTS', 'OPEN_ALLIANCE_TECH_FROM_HOME', 'OPEN_BEAR_RALLY_LIST', 'OPEN_COMPLETED_TRAINING_CAMP_LANCER', 'OPEN_DAILY', 'OPEN_EXPLORATION', 'OPEN_HOME', 'OPEN_INTEL', 'OPEN_MAIL', 'OPEN_POWER_OVERVIEW', 'OPEN_RESEARCH', 'RESEARCH', 'SEARCH_RESOURCE', 'SELECT_MAIL_ALLIANCE_TAB', 'SELECT_MAIL_REPORT_TAB', 'SELECT_MAIL_SYSTEM_TAB', 'SELECT_RESOURCE', 'START_GATHER', 'START_RALLY', 'SUBMIT_BEAST_SEARCH', 'SUBMIT_RESOURCE_SEARCH']
- promoted but RAN ON ADB: {}
- last step: TRY_ORDINARY_CONTROL via ADB at 2026-10-16T23:57:43.000293+00:00

> used_backend is what the step really did. A skill listed under promoted_but_ran_on_adb took the 324 ms ADB frame path while its own record claims MAA EmulatorExtras at 8.92 ms -- check tools/preflight.py before trusting the run.
