# 01 — CURRENT TRUTH

- generated_at: `2026-10-02T05:30:55+00:00`
- source: `tools/update_workbuddy_handoff.py` (reads git, registry, capability map, episode stream, snapshot, logs)
- commit: `3989c52` on `main`

> This file is regenerated. Never hand-edit it; edit the project instead.

## A. Version control

- repository: yes
- last good commit: `e4fd245`
- commits: 841
- HEAD: `3989c52` — fix(planner): ask the model the question the caller wrote, and read the id it named (2026-10-02T13:26:31+08:00)
- working tree: 1415 dirty file(s)
  - `M .workbuddy-ai/commander/BLOCKED_QUEUE.json`
  - ` M .workbuddy-ai/commander/CODEX_DIRECTIVES.md`
  - ` M .workbuddy-ai/commander/EXECUTION_STATE.json`
  - ` M .workbuddy-ai/commander/LAST_CODEX_REVIEW.md`
  - ` M .workbuddy-ai/commander/README.md`
  - ` M .workbuddy-ai/commander/WORK_QUEUE.json`
  - ` M .workbuddy-ai/memory/2026-09-30.md`
  - ` M .workbuddy-ai/memory/2026-10-02.md`
  - ` M .workbuddy/memory/2026-10-02.md`
  - ` M .workbuddy/memory/MEMORY.md`
  - ` M START_HERE.md`
  - ` M dataset/candidate/autogen/regular_event_entry__autogen_5d2c9a0f.png`
  - ` M dataset/candidate/template_manifest.json`
  - ` M docs/CAPABILITY_COVERAGE.md`
  - ` M docs/CURRENT_TRUTH.md`
  - ` M docs/TOP_FAILURES.md`
  - ` M evidence/INDEX.json`
  - ` M knowledge/analysis/top_failures.json`
  - ` M knowledge/execution/backend_routing.json`
  - ` M knowledge/goals/capability_skill_map.json`

### A2. Public mirror

The repository is PUBLIC, so 'is the mirror current' is part of the truth this file
reports, not a side note. `remote_head` is the local remote-tracking ref: it is as
fresh as the last fetch, and `tools/git_sync.py status` is what refreshes it.

```
SYNC STATE at 2026-10-02T05:30:55+00:00
remote            : https://github.com/hongweixiong0-star/winter-agent-os-v2.git
branch            : main
local_head        : 3989c520ac7ea2bf960be85f6fe0ef4ed6bc8ae9
remote_head       : 3989c520ac7ea2bf960be85f6fe0ef4ed6bc8ae9   (local remote-tracking ref; run tools/git_sync.py status to refresh)
unpushed_commits  : 0   (behind: 0)
git_dirty         : True (1415 path(s))
last_push_at      : 2026-10-02T05:26:57.825362+00:00
last_push_status  : PUSHED
verdict           : GitHub mirrors the local tree
```

## B. Runtime

- agent_state: `IDLE`
- runtime_thread_alive: False / scheduler_loop_alive: False
- unexpected_worker_exits: 18
- watchdog_restart_count: 24
- last_fatal_error: None
- stop_reason: MAX_ACTIONS_REACHED
- page: HOME  march: None/None
- updated_at: 2026-10-02T05:30:15.641014+00:00

## C. Episode stream

- rows: 10487 (production 10487)  modes: {'PRODUCTION': 10487}
- success / failure: 9479 / 758
- success rate over decided: **0.926**
- mixed-case `result` rows (normalise on read, never rewrite): 0
- last episode: `{"skill": "SCROLL_QUICK_PANEL_TASKS", "result": "SUCCESS", "recorded_at": "2026-10-02T05:30:12.442489+00:00", "episode_id": "20261002_132503_871869", "before_screenshot": "C:\\Users\\xhw\\.codex\\worktrees\\winter-prod-pinned\\无尽冬日智能体\\dataset\\raw\\control_panel\\runtime_auto\\20261002_132503_871869\\20261002_132503_871869_step_023_before_20261002T053004873106.png", "after_screenshot": "C:\\Users\\xhw\\.codex\\worktrees\\winter-prod-pinned\\无尽冬日智能体\\dataset\\raw\\control_panel\\runtime_auto\\20261002_132503_871869\\20261002_132503_871869_step_023_after_20261002T053009311656.png"}`

## D. Registry and lifecycle

- registry total: 152  by_state: {'CANDIDATE': 101, 'VERIFIED': 47, 'BLOCKED': 4}
- live dispatchable (verifier-backed): 140
- BLOCKED skills: ['ALLIANCE_HELP', 'COLLECT_FINISHED_TRAINING_LANCER', 'COLLECT_FINISHED_TRAINING_MARKSMAN', 'COLLECT_FINISHED_TRAINING_SHIELD']
- live_verified: **18**  stable: 54  degraded: 12  only_failed: 5  never_executed: 66

### Never executed

- `ALLIANCE_ALLY_GIFT_CLAIM` (VERIFIED)
- `ALLIANCE_GIFTS` (VERIFIED)
- `ALLIANCE_HELP` (BLOCKED)
- `ASSIGN_GATHER_HERO` (CANDIDATE)
- `BEAR_AUTO_JOIN` (CANDIDATE)
- `BEAST_HUNT` (VERIFIED)
- `BUILDING_UPGRADE` (VERIFIED)
- `CANCEL_DUPLICATE_TARGET` (VERIFIED)
- `CHECK_MARCH` (VERIFIED)
- `CLAIM_LOGIN_GIFT` (CANDIDATE)
- `CLAIM_REWARD` (CANDIDATE)
- `CLEAR_GATHER_HEROES` (CANDIDATE)
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
- `FREE_HERO_RECRUIT_ADVANCED` (CANDIDATE)
- `FREE_HERO_RECRUIT_EPIC` (CANDIDATE)
- `GATHER_RESOURCE` (VERIFIED)
- `JOIN_RALLY` (CANDIDATE)
- `NAVIGATE_INFANTRY_CAMP` (CANDIDATE)
- `NAVIGATE_RESEARCH_LAB` (CANDIDATE)
- `NAVIGATE_TO` (CANDIDATE)
- `OPEN_ALLIANCE_GIFTS` (CANDIDATE)
- `OPEN_GATHER_HERO_PICKER` (CANDIDATE)
- `OPEN_LOGIN_GIFT` (CANDIDATE)
- `OPEN_POWER_DETAILS` (CANDIDATE)
- `OPEN_POWER_OVERVIEW` (CANDIDATE)
- `OPEN_RESEARCH` (CANDIDATE)
- `OPEN_TASK_FROM_QUICK_PANEL_ALLIANCE_DONATION` (CANDIDATE)
- `OPEN_TASK_FROM_QUICK_PANEL_HERO_RECRUIT_EPIC` (CANDIDATE)
- `OPEN_TASK_FROM_QUICK_PANEL_MY_REWARDS` (CANDIDATE)
- `PLAY_NORMAL_FISHING_LEVEL` (CANDIDATE)
- `READ_COUNTER` (CANDIDATE)
- `READ_EVENT_CALENDAR` (CANDIDATE)
- `READ_INTEL_LIST` (CANDIDATE)
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
- `SELECT_REWARD_OPTION` (CANDIDATE)
- `SEND_MARCH` (CANDIDATE)
- `START_RALLY` (CANDIDATE)
- `USE_ACTIVITY_ATTEMPT` (CANDIDATE)
- `VERIFY_GATHERING` (VERIFIED)
- `WAIT` (CANDIDATE)
- `WAIT_FOR_CAMP_MENU` (VERIFIED)

### Only ever failed

- `OPEN_BUILDING_UPGRADE` attempts=3 failure=3
- `READ_FISHING_STATE` attempts=2 failure=2
- `REALTIME` attempts=27 failure=8
- `SELECT_BEAST_TARGET_MAMMOTH` attempts=30 failure=30
- `SELECT_MARCH_TO_RECALL` attempts=1 failure=1

### Stable

- `BACK` success=1040 rate=0.9811
- `CLAIM_FREE_STAMINA` success=12 rate=1.0
- `CONFIRM_EXPLORATION_IDLE_CLAIM` success=58 rate=1.0
- `DAILY_CLAIM_REWARDS` success=20 rate=1.0
- `DISMISS_EXPLORATION_GENERIC_REWARD` success=47 rate=0.9592
- `DISMISS_INTEL_GENERIC_REWARD` success=123 rate=0.9919
- `DISMISS_SHARED_REWARD` success=34 rate=1.0
- `DISPATCH_INTEL_BEAST` success=62 rate=0.9394
- `DISPATCH_MARCH` success=8 rate=1.0
- `EXECUTE_INTEL_RESCUE_SURVIVORS` success=22 rate=0.9167
- `EXPLORATION_IDLE_CLAIM` success=61 rate=0.8356
- `FOLLOW_DAILY_TASK` success=15 rate=0.8824
- `INTEL_BEAST_START_MARCH` success=62 rate=1.0
- `INTEL_CLAIM_REWARDS` success=115 rate=1.0
- `INTEL_HERO_DISPATCH` success=43 rate=1.0
- `INTEL_HERO_START_MARCH` success=45 rate=1.0
- `MAIL_CLAIM_REWARDS` success=78 rate=0.9873
- `OPEN_ALLIANCE` success=9 rate=1.0
- `OPEN_BEAR_RALLY_LIST` success=12 rate=1.0
- `OPEN_COMPLETED_TRAINING_CAMP_MARKSMAN` success=16 rate=0.8421
- `OPEN_COMPLETED_TRAINING_CAMP_SHIELD` success=107 rate=0.9907
- `OPEN_EVENT_CALENDAR_DETAIL` success=1350 rate=0.9985
- `OPEN_EVENT_CALENDAR_FROM_HOME` success=128 rate=0.8649
- `OPEN_EVENT_CALENDAR_TAB` success=126 rate=1.0
- `OPEN_EXPLORATION` success=67 rate=0.971
- `OPEN_HOME` success=607 rate=0.9574
- `OPEN_INFANTRY_TRAINING` success=61 rate=0.9839
- `OPEN_INTEL` success=512 rate=0.9942
- `OPEN_INTEL_BEAST_TARGET` success=67 rate=0.9437
- `OPEN_INTEL_HERO_JOURNEY_TARGET` success=58 rate=1.0
- `OPEN_INTEL_RESCUE_SURVIVORS_TARGET` success=23 rate=0.92
- `OPEN_MAIL` success=67 rate=1.0
- `OPEN_MAP` success=750 rate=0.9973
- `OPEN_QUICK_PANEL` success=1039 rate=1.0
- `OPEN_STAMINA_SOURCES` success=18 rate=0.9474
- `OPEN_TASK_FROM_QUICK_PANEL_LANCER` success=16 rate=0.9412
- `OPEN_TASK_FROM_QUICK_PANEL_MARKSMAN` success=28 rate=1.0
- `OPEN_TASK_FROM_QUICK_PANEL_PET_TREASURE` success=28 rate=1.0
- `OPEN_TASK_FROM_QUICK_PANEL_SHIELD` success=14 rate=1.0
- `OPEN_TECH_TREE` success=14 rate=1.0
- `RETURN_EVENT_CALENDAR` success=1227 rate=0.9992
- `SCAN_MAP_FOR_BEAST` success=39 rate=1.0
- `SCROLL_QUICK_PANEL_TASKS` success=46 rate=0.9388
- `SCROLL_REGULAR_EVENT_TABS` success=163 rate=0.9939
- `SEARCH_RESOURCE` success=264 rate=0.9263
- `SELECT_GIANT_BEAST_TAB` success=64 rate=0.9275
- `SELECT_INTEL_BEAST_MISSION` success=10 rate=0.9091
- `SELECT_INTEL_PIN` success=234 rate=0.9791
- `SELECT_MAIL_ALLIANCE_TAB` success=17 rate=1.0
- `SELECT_MAIL_SYSTEM_TAB` success=8 rate=1.0
- `START_GATHER` success=6 rate=1.0
- `SUBMIT_BEAST_SEARCH` success=17 rate=1.0
- `SUBMIT_RESOURCE_SEARCH` success=10 rate=1.0
- `TRAIN_TROOPS` success=25 rate=0.9259

### Degraded

- `DISMISS_DAILY_GENERIC_REWARD` success=31 failure=17 rate=0.6458
- `OPEN_BEAST_SEARCH_TAB` success=13 failure=56 rate=0.1884
- `OPEN_COMPLETED_TRAINING_CAMP_LANCER` success=30 failure=10 rate=0.75
- `OPEN_DAILY` success=37 failure=10 rate=0.7872
- `OPEN_TASK_FROM_QUICK_PANEL_BUILDING` success=27 failure=29 rate=0.4821
- `OPEN_TASK_FROM_QUICK_PANEL_RESEARCH` success=19 failure=6 rate=0.76
- `PRINTED_TAP` success=97 failure=62 rate=0.6101
- `SELECT_MAIL_REPORT_TAB` success=8 failure=5 rate=0.6154
- `SELECT_RESEARCH_NODE` success=10 failure=5 rate=0.6667
- `SELECT_RESOURCE` success=8 failure=54 rate=0.129
- `SUBMIT_GIANT_BEAST_SEARCH` success=40 failure=53 rate=0.4301
- `TRY_ORDINARY_CONTROL` success=25 failure=118 rate=0.1748

## E. Top failures

Failure | Count | Top skills
---|---:|---
`SEMANTIC_TARGET_NOT_VERIFIED` | 313 | TRY_ORDINARY_CONTROL(118), SELECT_RESOURCE(54), SELECT_BEAST_TARGET_MAMMOTH(30)
`NO_EXECUTION` | 122 | OBSERVE_ONLY(65), PRINTED_TAP(37), TAP_FOCUSED_TRAINING_CAMP_SHIELD(6)
`GIANT_BEAST_SEARCH_NOT_PROVEN` | 48 | SUBMIT_GIANT_BEAST_SEARCH(48)
`BEAST_SEARCH_TAB_NOT_PROVEN` | 49 | OPEN_BEAST_SEARCH_TAB(49)
`PANEL_BUILDING_QUEUE_NOT_PROVEN` | 27 | OPEN_TASK_FROM_QUICK_PANEL_BUILDING(27)
`FOCUSED_CAMP_ACTION_BAR_NOT_PROVEN` | 32 | TAP_FOCUSED_TRAINING_CAMP_SHIELD(11), TAP_FOCUSED_TRAINING_CAMP_LANCER(11), TAP_FOCUSED_TRAINING_CAMP_MARKSMAN(10)
`DAILY_REWARD_ADVANCE_NOT_PROVEN` | 17 | DISMISS_DAILY_GENERIC_REWARD(17)
`SAFE_BACK_NOT_PROVEN` | 20 | BACK(20)
`COMPLETED_CAMP_INSPECTION_NOT_PROVEN` | 13 | OPEN_COMPLETED_TRAINING_CAMP_LANCER(10), OPEN_COMPLETED_TRAINING_CAMP_MARKSMAN(2), OPEN_COMPLETED_TRAINING_CAMP_SHIELD(1)
`FISHING_FRAME_ADVANCED` | 11 | PRINTED_TAP(11)

## F. Goal capability coverage

- model: Goal -> Canonical Capability -> Registered Skill -> Production Evidence
- summary: {"total": 20, "fully_live_verified": 3, "partial": 9, "never_tried": 4, "blocked": 4, "degraded": 0, "missing": 0, "fully_live_verified_percent": 15.0, "never_tried_percent": 20.0, "automation_coverage_mean": 0.7083, "live_coverage_mean": 0.4137}

Goal | Status | Runtime | design | impl | live | stable | blocked by
---|---|---|---:|---:|---:|---:|---
CLEAR_INTEL | PARTIAL | RUNTIME_DISCOVERED | 100% | 100% | 83% | 83% | -
AVOID_STAMINA_WASTE | PARTIAL | RUNTIME_DISCOVERED | 100% | 100% | 67% | 33% | -
KEEP_MARCHES_PRODUCTIVE | PARTIAL | RUNTIME_DISCOVERED | 100% | 100% | 86% | 71% | -
KEEP_BUILDING_PRODUCTIVE | PARTIAL | RUNTIME_DISCOVERED | 100% | 100% | 50% | 0% | -
KEEP_RESEARCH_PRODUCTIVE | NEVER_TRIED | RUNTIME_DISCOVERED | 100% | 100% | 0% | 0% | -
KEEP_TRAINING_PRODUCTIVE | FULLY_LIVE_VERIFIED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 100% | -
MAIL_ROUTINE | PARTIAL | RUNTIME_DISCOVERED | 100% | 100% | 75% | 75% | -
DAILY_ACTIVITY_TARGET | PARTIAL | RUNTIME_DISCOVERED | 100% | 75% | 75% | 25% | READ_DAILY_PROGRESS
CLAIM_FREE_REWARDS | FULLY_LIVE_VERIFIED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 100% | -
CLAIM_EXPLORATION_IDLE | FULLY_LIVE_VERIFIED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 100% | -
ALLIANCE_ROUTINE | PARTIAL | NOT_A_RUNTIME_GOAL | 100% | 75% | 50% | 25% | ALLIANCE_HELP
EVENT_MINIMUM_GUARANTEE | PARTIAL | RUNTIME_DISCOVERED | 100% | 17% | 17% | 17% | CLAIM_EVENT_TIER, OPEN_EVENT_PAGE, READ_EVENT_PROGRESS, READ_EVENT_RULES, READ_EVENT_TIMER
ALLIANCE_TIMED_EVENTS | BLOCKED | RUNTIME_DISCOVERED | 100% | 0% | 0% | 0% | CHECK_ALLIANCE_EVENT, CLAIM_EVENT_TIER, READ_ALLIANCE_EVENT_TIMER
PARTICIPATE_BEAR | PARTIAL | RUNTIME_DISCOVERED | 100% | 50% | 25% | 25% | CHECK_BEAR_PHASE, SELECT_TROOP_PRESET
ALLIANCE_MOBILIZATION_ICEFIELD_BEAST | NEVER_TRIED | RUNTIME_DISCOVERED | 100% | 100% | 0% | 0% | -
OBSERVE_FISHING_STATE | NEVER_TRIED | RUNTIME_DISCOVERED | 100% | 100% | 0% | 0% | -
USE_NORMAL_FISHING_BAIT | NEVER_TRIED | RUNTIME_DISCOVERED | 100% | 100% | 0% | 0% | -
USE_FREE_ARENA_ATTEMPTS | BLOCKED | RUNTIME_DISCOVERED | 100% | 0% | 0% | 0% | OPEN_ARENA_PAGE, READ_FREE_ATTEMPTS, SELECT_ARENA_OPPONENT, START_ARENA, VERIFY_ARENA_RESULT
LABYRINTH_DAILY | BLOCKED | RUNTIME_DISCOVERED | 100% | 0% | 0% | 0% | OPEN_LABYRINTH_PAGE, READ_LABYRINTH_ATTEMPTS, START_LABYRINTH, VERIFY_LABYRINTH_RESULT
TRAVEL_SUPPLY | BLOCKED | RUNTIME_DISCOVERED | 100% | 0% | 0% | 0% | CLAIM_FREE_TRAVEL_SUPPLY, OPEN_TRAVEL_SUPPLY_COUNTER, OPEN_TRAVEL_SUPPLY_ENTRY

## G. Evidence integrity

- status: **PASS**
- referenced screenshots: 19951  present: 19951
- missing: []
- episodes carrying screenshot references: 10195

## H. Commercial bot parity

- present: True
- summary: {"features_tracked": 21, "features_with_live_success": 10, "parity_fraction": 0.4762}
- features without live evidence: ['VIP', 'ALLIANCE_HELP', 'PROMOTE', 'HEAL', 'RESEARCH', 'ARENA', 'LABYRINTH', 'JOIN_RALLY', 'START_RALLY', 'BEAR', 'PET']

## I. Latest runtime log

- {"path": "E:\\无尽冬日智能体\\learning\\control_panel\\latest.log", "modified_at": "2026-10-02T05:30:44+00:00", "size_bytes": 286320, "last_stop_reason": null}
- recent crash reports: ['E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20260921_092331_166289_unified_worker.json', 'E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20260921_094236_608796_unified_worker.json', 'E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20260930_144623_899653_auto_subprocess.json', 'E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20260930_144831_908327_auto_subprocess.json', 'E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20261001_230253_798994_auto_subprocess.json']

## J. Backend axis (MAA vs ADB)

- source: `learning/executor_backend.jsonl` vs `knowledge/execution/backend_routing.json`
- ledger rows: 20000 (last 200 summarised)
- used_backend: {"ADB": 113, "MAA": 87}
- capture_backend: {"ADB_EXEC_OUT": 113, "MAA_MUMU_EXTRAS": 87}
- promoted to MAA in routing: 41 ['BACK', 'BEAR_AUTO_JOIN', 'CLOSE_POPUP', 'COLLECT_TRAINING_BATCH', 'DAILY_CLAIM_REWARDS', 'DISMISS_BATTLE_VICTORY', 'DISPATCH_MARCH', 'EXPLORATION_IDLE_CLAIM', 'FOLLOW_DAILY_TASK', 'FREE_HERO_RECRUIT_ADVANCED', 'INTEL_CLAIM_REWARDS', 'INTEL_HERO_DISPATCH', 'INTEL_HERO_START_MARCH', 'JOIN_RALLY', 'MAIL_CLAIM_REWARDS', 'OPEN_ALLIANCE', 'OPEN_ALLIANCE_GIFTS', 'OPEN_ALLIANCE_TECH_FROM_HOME', 'OPEN_BEAR_RALLY_LIST', 'OPEN_BUILDING_UPGRADE', 'OPEN_COMPLETED_TRAINING_CAMP_MARKSMAN', 'OPEN_DAILY', 'OPEN_EVENT_CALENDAR_FROM_HOME', 'OPEN_EVENT_CALENDAR_FROM_MAP', 'OPEN_EXPLORATION', 'OPEN_HOME', 'OPEN_INTEL', 'OPEN_MAIL', 'OPEN_POWER_OVERVIEW', 'OPEN_RESEARCH', 'OPEN_TASK_FROM_QUICK_PANEL_HERO_RECRUIT', 'RESEARCH', 'SEARCH_RESOURCE', 'SELECT_MAIL_ALLIANCE_TAB', 'SELECT_MAIL_REPORT_TAB', 'SELECT_MAIL_SYSTEM_TAB', 'SELECT_RESOURCE', 'START_GATHER', 'START_RALLY', 'SUBMIT_BEAST_SEARCH', 'SUBMIT_RESOURCE_SEARCH']
- promoted but RAN ON ADB: {}
- last step: SCROLL_QUICK_PANEL_TASKS via ADB at 2026-10-02T05:30:09.128967+00:00

> used_backend is what the step really did. A skill listed under promoted_but_ran_on_adb took the 324 ms ADB frame path while its own record claims MAA EmulatorExtras at 8.92 ms -- check tools/preflight.py before trusting the run.
