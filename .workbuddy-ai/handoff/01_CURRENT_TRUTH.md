# 01 — CURRENT TRUTH

- generated_at: `2026-10-02T11:25:04+00:00`
- source: `tools/update_workbuddy_handoff.py` (reads git, registry, capability map, episode stream, snapshot, logs)
- commit: `5a04821` on `main`

> This file is regenerated. Never hand-edit it; edit the project instead.

## A. Version control

- repository: yes
- last good commit: `e4fd245`
- commits: 884
- HEAD: `5a04821` — fix(routing): the node that answered 0 times in 10 is not the router's first choice (2026-10-02T19:12:16+08:00)
- working tree: 1477 dirty file(s)
  - `M .workbuddy-ai/commander/CODEX_DIRECTIVES.md`
  - ` M .workbuddy-ai/commander/EXECUTION_STATE.json`
  - ` M .workbuddy-ai/commander/LAST_CODEX_REVIEW.md`
  - ` M .workbuddy-ai/commander/README.md`
  - ` M .workbuddy-ai/commander/WORK_QUEUE.json`
  - ` M .workbuddy-ai/memory/2026-09-30.md`
  - ` M START_HERE.md`
  - ` M dataset/candidate/autogen/regular_event_entry__autogen_5d2c9a0f.png`
  - ` M dataset/candidate/template_manifest.json`
  - ` M docs/CAPABILITY_COVERAGE.md`
  - ` M docs/CURRENT_TRUTH.md`
  - ` M docs/TOP_FAILURES.md`
  - ` M knowledge/analysis/top_failures.json`
  - ` M knowledge/goals/capability_skill_map.json`
  - ` M knowledge/perception/candidates/INDEX.json`
  - ` M knowledge/perception/pages/INDEX.json`
  - ` M knowledge/preload/INDEX.json`
  - ` M knowledge/preload/TROOP_SELECT.json`
  - ` M knowledge/ui/page_transitions.json`
  - ` M learning/current_truth.json`

### A2. Public mirror

The repository is PUBLIC, so 'is the mirror current' is part of the truth this file
reports, not a side note. `remote_head` is the local remote-tracking ref: it is as
fresh as the last fetch, and `tools/git_sync.py status` is what refreshes it.

```
SYNC STATE at 2026-10-02T11:25:04+00:00
remote            : https://github.com/hongweixiong0-star/winter-agent-os-v2.git
branch            : main
local_head        : 5a04821a745dc0aaa073d59d3c7b16d75510b2ac
remote_head       : 5a04821a745dc0aaa073d59d3c7b16d75510b2ac   (local remote-tracking ref; run tools/git_sync.py status to refresh)
unpushed_commits  : 0   (behind: 0)
git_dirty         : True (1477 path(s))
last_push_at      : 2026-10-02T06:58:22.838057+00:00
last_push_status  : PUSHED
verdict           : GitHub mirrors the local tree
```

## B. Runtime

- agent_state: `GOAL_RUNNING`
- runtime_thread_alive: True / scheduler_loop_alive: True
- unexpected_worker_exits: 18
- watchdog_restart_count: 24
- last_fatal_error: None
- stop_reason: None
- page: MAP  march: 0/None
- updated_at: 2026-10-02T11:25:06.037783+00:00

## C. Episode stream

- rows: 10114 (production 10114)  modes: {'PRODUCTION': 10114}
- success / failure: 9092 / 772
- success rate over decided: **0.9217**
- mixed-case `result` rows (normalise on read, never rewrite): 0
- last episode: `{"skill": "OPEN_MAP", "result": "SUCCESS", "recorded_at": "2026-10-02T11:24:58.913823+00:00", "episode_id": "20261002_192152_626057", "before_screenshot": "C:\\Users\\xhw\\.codex\\worktrees\\winter-prod-pinned\\无尽冬日智能体\\dataset\\raw\\control_panel\\runtime_auto\\20261002_192152_626057\\20261002_192152_626057_step_014_before_20261002T112444979208.png", "after_screenshot": "C:\\Users\\xhw\\.codex\\worktrees\\winter-prod-pinned\\无尽冬日智能体\\dataset\\raw\\control_panel\\runtime_auto\\20261002_192152_626057\\20261002_192152_626057_step_014_after_refresh_1_20261002T112453072851.png"}`

## D. Registry and lifecycle

- registry total: 152  by_state: {'CANDIDATE': 101, 'VERIFIED': 47, 'BLOCKED': 4}
- live dispatchable (verifier-backed): 140
- BLOCKED skills: ['ALLIANCE_HELP', 'COLLECT_FINISHED_TRAINING_LANCER', 'COLLECT_FINISHED_TRAINING_MARKSMAN', 'COLLECT_FINISHED_TRAINING_SHIELD']
- live_verified: **11**  stable: 57  degraded: 11  only_failed: 5  never_executed: 71

### Never executed

- `ALLIANCE_ALLY_GIFT_CLAIM` (VERIFIED)
- `ALLIANCE_GIFTS` (VERIFIED)
- `ALLIANCE_HELP` (BLOCKED)
- `ALLIANCE_TECH_CONTRIBUTE` (VERIFIED)
- `ASSIGN_GATHER_HERO` (CANDIDATE)
- `BEAR_AUTO_JOIN` (CANDIDATE)
- `BEAST_HUNT` (VERIFIED)
- `BUILDING_UPGRADE` (VERIFIED)
- `CANCEL_DUPLICATE_TARGET` (VERIFIED)
- `CHECK_MARCH` (VERIFIED)
- `CLAIM_LOGIN_GIFT` (CANDIDATE)
- `CLAIM_REWARD` (CANDIDATE)
- `CLOSE_ALLIANCE_TECH_DONATION_DETAILS` (CANDIDATE)
- `CLOSE_POPUP` (VERIFIED)
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
- `DISMISS_REAL_MONEY_OFFER` (CANDIDATE)
- `FREE_HERO_RECRUIT_ADVANCED` (CANDIDATE)
- `GATHER_RESOURCE` (VERIFIED)
- `JOIN_RALLY` (CANDIDATE)
- `LEAVE_FOREIGN_LAYER` (VERIFIED)
- `NAVIGATE_INFANTRY_CAMP` (CANDIDATE)
- `NAVIGATE_RESEARCH_LAB` (CANDIDATE)
- `NAVIGATE_TO` (CANDIDATE)
- `OPEN_ALLIANCE_GIFTS` (CANDIDATE)
- `OPEN_ALLIANCE_RECOMMENDED_TECH_NODE` (CANDIDATE)
- `OPEN_ALLIANCE_TECH_FROM_HOME` (CANDIDATE)
- `OPEN_GATHER_HERO_PICKER` (CANDIDATE)
- `OPEN_LOGIN_GIFT` (CANDIDATE)
- `OPEN_POWER_DETAILS` (CANDIDATE)
- `OPEN_POWER_OVERVIEW` (CANDIDATE)
- `OPEN_RESEARCH` (CANDIDATE)
- `OPEN_TASK_FROM_QUICK_PANEL_ALLIANCE_DONATION` (CANDIDATE)
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
- `SELECT_MARCH_TO_RECALL` (CANDIDATE)
- `SELECT_REWARD_OPTION` (CANDIDATE)
- `SELECT_TRAINING_CAMP` (CANDIDATE)
- `SEND_MARCH` (CANDIDATE)
- `START_RALLY` (CANDIDATE)
- `USE_ACTIVITY_ATTEMPT` (CANDIDATE)
- `VERIFY_GATHERING` (VERIFIED)
- `WAIT` (CANDIDATE)
- `WAIT_FOR_CAMP_MENU` (VERIFIED)

### Only ever failed

- `OPEN_BUILDING_UPGRADE` attempts=12 failure=12
- `READ_FISHING_STATE` attempts=2 failure=2
- `REALTIME` attempts=27 failure=8
- `SELECT_BEAST_TARGET_LABELLED` attempts=4 failure=4
- `SELECT_BEAST_TARGET_MAMMOTH` attempts=32 failure=32

### Stable

- `ATTACK_BEAST_CARD` success=5 rate=1.0
- `BACK` success=849 rate=0.9826
- `CLAIM_FREE_STAMINA` success=11 rate=1.0
- `CLEAR_GATHER_HEROES` success=5 rate=1.0
- `CONFIRM_EXPLORATION_IDLE_CLAIM` success=53 rate=1.0
- `DAILY_CLAIM_REWARDS` success=19 rate=1.0
- `DISMISS_EXPLORATION_GENERIC_REWARD` success=43 rate=0.9556
- `DISMISS_INTEL_GENERIC_REWARD` success=98 rate=0.9899
- `DISMISS_SHARED_REWARD` success=34 rate=1.0
- `DISPATCH_INTEL_BEAST` success=49 rate=0.9245
- `EXECUTE_INTEL_RESCUE_SURVIVORS` success=17 rate=0.85
- `EXPLORATION_IDLE_CLAIM` success=56 rate=0.8235
- `FOLLOW_DAILY_TASK` success=14 rate=0.9333
- `INTEL_BEAST_START_MARCH` success=58 rate=1.0
- `INTEL_CLAIM_REWARDS` success=97 rate=1.0
- `INTEL_HERO_DISPATCH` success=35 rate=1.0
- `INTEL_HERO_START_MARCH` success=42 rate=1.0
- `MAIL_CLAIM_REWARDS` success=78 rate=0.9873
- `OPEN_ALLIANCE` success=9 rate=1.0
- `OPEN_BEAR_RALLY_LIST` success=22 rate=0.9565
- `OPEN_COMPLETED_TRAINING_CAMP_MARKSMAN` success=15 rate=0.8333
- `OPEN_COMPLETED_TRAINING_CAMP_SHIELD` success=101 rate=1.0
- `OPEN_EVENT_CALENDAR_DETAIL` success=1358 rate=0.9985
- `OPEN_EVENT_CALENDAR_FROM_HOME` success=129 rate=0.9021
- `OPEN_EVENT_CALENDAR_TAB` success=127 rate=1.0
- `OPEN_EXPLORATION` success=64 rate=0.9846
- `OPEN_HOME` success=605 rate=0.9483
- `OPEN_INFANTRY_TRAINING` success=53 rate=1.0
- `OPEN_INTEL` success=396 rate=1.0
- `OPEN_INTEL_BEAST_TARGET` success=56 rate=0.918
- `OPEN_INTEL_HERO_JOURNEY_TARGET` success=52 rate=1.0
- `OPEN_INTEL_RESCUE_SURVIVORS_TARGET` success=17 rate=0.85
- `OPEN_MAIL` success=51 rate=1.0
- `OPEN_MAP` success=754 rate=0.9987
- `OPEN_QUICK_PANEL` success=1150 rate=1.0
- `OPEN_STAMINA_SOURCES` success=16 rate=0.9412
- `OPEN_TASK_FROM_QUICK_PANEL_LANCER` success=16 rate=0.9412
- `OPEN_TASK_FROM_QUICK_PANEL_MARKSMAN` success=22 rate=1.0
- `OPEN_TASK_FROM_QUICK_PANEL_PET_TREASURE` success=29 rate=1.0
- `OPEN_TASK_FROM_QUICK_PANEL_SHIELD` success=12 rate=1.0
- `OPEN_TECH_TREE` success=10 rate=1.0
- `RETURN_EVENT_CALENDAR` success=1234 rate=0.9992
- `SCAN_MAP_FOR_BEAST` success=6 rate=1.0
- `SCROLL_QUICK_PANEL_TASKS` success=53 rate=0.9815
- `SCROLL_REGULAR_EVENT_TABS` success=165 rate=0.994
- `SEARCH_RESOURCE` success=233 rate=0.9628
- `SELECT_GIANT_BEAST_TAB` success=84 rate=0.9438
- `SELECT_INTEL_BEAST_MISSION` success=11 rate=0.9167
- `SELECT_INTEL_PIN` success=205 rate=0.9903
- `SELECT_MAIL_ALLIANCE_TAB` success=17 rate=1.0
- `SELECT_MAIL_REPORT_TAB` success=8 rate=1.0
- `SELECT_MAIL_SYSTEM_TAB` success=6 rate=1.0
- `SELECT_RESEARCH_NODE` success=10 rate=1.0
- `START_GATHER` success=6 rate=1.0
- `SUBMIT_BEAST_SEARCH` success=9 rate=1.0
- `SUBMIT_RESOURCE_SEARCH` success=8 rate=1.0
- `TRAIN_TROOPS` success=23 rate=0.92

### Degraded

- `DISMISS_DAILY_GENERIC_REWARD` success=30 failure=17 rate=0.6383
- `DISPATCH_BEAST` success=5 failure=2 rate=0.7143
- `OPEN_BEAST_SEARCH_TAB` success=11 failure=66 rate=0.1429
- `OPEN_COMPLETED_TRAINING_CAMP_LANCER` success=28 failure=10 rate=0.7368
- `OPEN_DAILY` success=30 failure=15 rate=0.6667
- `OPEN_TASK_FROM_QUICK_PANEL_BUILDING` success=39 failure=27 rate=0.5909
- `OPEN_TASK_FROM_QUICK_PANEL_RESEARCH` success=14 failure=6 rate=0.7
- `PRINTED_TAP` success=125 failure=64 rate=0.6614
- `SELECT_RESOURCE` success=7 failure=86 rate=0.0753
- `SUBMIT_GIANT_BEAST_SEARCH` success=50 failure=69 rate=0.4202
- `TRY_ORDINARY_CONTROL` success=25 failure=96 rate=0.2066

## E. Top failures

Failure | Count | Top skills
---|---:|---
`SEMANTIC_TARGET_NOT_VERIFIED` | 327 | TRY_ORDINARY_CONTROL(96), SELECT_RESOURCE(86), OPEN_HOME(33)
`GIANT_BEAST_SEARCH_NOT_PROVEN` | 64 | SUBMIT_GIANT_BEAST_SEARCH(64)
`NO_EXECUTION` | 125 | OBSERVE_ONLY(65), PRINTED_TAP(39), TAP_FOCUSED_TRAINING_CAMP_SHIELD(6)
`BEAST_SEARCH_TAB_NOT_PROVEN` | 54 | OPEN_BEAST_SEARCH_TAB(54)
`PANEL_BUILDING_QUEUE_NOT_PROVEN` | 25 | OPEN_TASK_FROM_QUICK_PANEL_BUILDING(25)
`FOCUSED_CAMP_ACTION_BAR_NOT_PROVEN` | 28 | TAP_FOCUSED_TRAINING_CAMP_LANCER(10), TAP_FOCUSED_TRAINING_CAMP_SHIELD(9), TAP_FOCUSED_TRAINING_CAMP_MARKSMAN(9)
`SAFE_BACK_NOT_PROVEN` | 15 | BACK(15)
`DAILY_REWARD_ADVANCE_NOT_PROVEN` | 17 | DISMISS_DAILY_GENERIC_REWARD(17)
`COMPLETED_CAMP_INSPECTION_NOT_PROVEN` | 12 | OPEN_COMPLETED_TRAINING_CAMP_LANCER(10), OPEN_COMPLETED_TRAINING_CAMP_MARKSMAN(2)
`OPEN_DAILY_NOT_PROVEN` | 15 | OPEN_DAILY(15)

## F. Goal capability coverage

- model: Goal -> Canonical Capability -> Registered Skill -> Production Evidence
- summary: {"total": 20, "fully_live_verified": 2, "partial": 9, "never_tried": 4, "blocked": 4, "degraded": 1, "missing": 0, "fully_live_verified_percent": 10.0, "never_tried_percent": 20.0, "automation_coverage_mean": 0.7083, "live_coverage_mean": 0.4012}

Goal | Status | Runtime | design | impl | live | stable | blocked by
---|---|---|---:|---:|---:|---:|---
CLEAR_INTEL | PARTIAL | RUNTIME_DISCOVERED | 100% | 100% | 83% | 83% | -
AVOID_STAMINA_WASTE | PARTIAL | RUNTIME_DISCOVERED | 100% | 100% | 67% | 33% | -
KEEP_MARCHES_PRODUCTIVE | PARTIAL | RUNTIME_DISCOVERED | 100% | 100% | 86% | 57% | -
KEEP_BUILDING_PRODUCTIVE | PARTIAL | RUNTIME_DISCOVERED | 100% | 100% | 50% | 0% | -
KEEP_RESEARCH_PRODUCTIVE | NEVER_TRIED | RUNTIME_DISCOVERED | 100% | 100% | 0% | 0% | -
KEEP_TRAINING_PRODUCTIVE | FULLY_LIVE_VERIFIED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 100% | -
MAIL_ROUTINE | PARTIAL | RUNTIME_DISCOVERED | 100% | 100% | 75% | 75% | -
DAILY_ACTIVITY_TARGET | PARTIAL | RUNTIME_DISCOVERED | 100% | 75% | 75% | 25% | READ_DAILY_PROGRESS
CLAIM_FREE_REWARDS | DEGRADED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 50% | -
CLAIM_EXPLORATION_IDLE | FULLY_LIVE_VERIFIED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 100% | -
ALLIANCE_ROUTINE | PARTIAL | NOT_A_RUNTIME_GOAL | 100% | 75% | 25% | 25% | ALLIANCE_HELP
EVENT_MINIMUM_GUARANTEE | PARTIAL | RUNTIME_DISCOVERED | 100% | 17% | 17% | 17% | CLAIM_EVENT_TIER, OPEN_EVENT_PAGE, READ_EVENT_PROGRESS, READ_EVENT_RULES, READ_EVENT_TIMER
ALLIANCE_TIMED_EVENTS | BLOCKED | RUNTIME_DISCOVERED | 100% | 0% | 0% | 0% | CHECK_ALLIANCE_EVENT, CLAIM_EVENT_TIER, READ_ALLIANCE_EVENT_TIMER
PARTICIPATE_BEAR | PARTIAL | RUNTIME_DISCOVERED | 100% | 50% | 25% | 0% | CHECK_BEAR_PHASE, SELECT_TROOP_PRESET
ALLIANCE_MOBILIZATION_ICEFIELD_BEAST | NEVER_TRIED | RUNTIME_DISCOVERED | 100% | 100% | 0% | 0% | -
OBSERVE_FISHING_STATE | NEVER_TRIED | RUNTIME_DISCOVERED | 100% | 100% | 0% | 0% | -
USE_NORMAL_FISHING_BAIT | NEVER_TRIED | RUNTIME_DISCOVERED | 100% | 100% | 0% | 0% | -
USE_FREE_ARENA_ATTEMPTS | BLOCKED | RUNTIME_DISCOVERED | 100% | 0% | 0% | 0% | OPEN_ARENA_PAGE, READ_FREE_ATTEMPTS, SELECT_ARENA_OPPONENT, START_ARENA, VERIFY_ARENA_RESULT
LABYRINTH_DAILY | BLOCKED | RUNTIME_DISCOVERED | 100% | 0% | 0% | 0% | OPEN_LABYRINTH_PAGE, READ_LABYRINTH_ATTEMPTS, START_LABYRINTH, VERIFY_LABYRINTH_RESULT
TRAVEL_SUPPLY | BLOCKED | RUNTIME_DISCOVERED | 100% | 0% | 0% | 0% | CLAIM_FREE_TRAVEL_SUPPLY, OPEN_TRAVEL_SUPPLY_COUNTER, OPEN_TRAVEL_SUPPLY_ENTRY

## G. Evidence integrity

- status: **PASS**
- referenced screenshots: 19188  present: 19188
- missing: []
- episodes carrying screenshot references: 9822

## H. Commercial bot parity

- present: True
- summary: {"features_tracked": 21, "features_with_live_success": 10, "parity_fraction": 0.4762}
- features without live evidence: ['VIP', 'ALLIANCE_HELP', 'PROMOTE', 'HEAL', 'RESEARCH', 'ARENA', 'LABYRINTH', 'JOIN_RALLY', 'START_RALLY', 'BEAR', 'PET']

## I. Latest runtime log

- {"path": "E:\\无尽冬日智能体\\learning\\control_panel\\latest.log", "modified_at": "2026-10-02T11:20:59+00:00", "size_bytes": 24674, "last_stop_reason": null}
- recent crash reports: ['E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20260921_092331_166289_unified_worker.json', 'E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20260921_094236_608796_unified_worker.json', 'E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20260930_144623_899653_auto_subprocess.json', 'E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20260930_144831_908327_auto_subprocess.json', 'E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20261001_230253_798994_auto_subprocess.json']

## J. Backend axis (MAA vs ADB)

- source: `learning/executor_backend.jsonl` vs `knowledge/execution/backend_routing.json`
- ledger rows: 20000 (last 200 summarised)
- used_backend: {"ADB": 109, "MAA": 91}
- capture_backend: {"ADB_EXEC_OUT": 109, "MAA_MUMU_EXTRAS": 91}
- promoted to MAA in routing: 39 ['BACK', 'BEAR_AUTO_JOIN', 'CLOSE_POPUP', 'COLLECT_TRAINING_BATCH', 'DAILY_CLAIM_REWARDS', 'DISMISS_BATTLE_VICTORY', 'DISPATCH_MARCH', 'EXPLORATION_IDLE_CLAIM', 'FOLLOW_DAILY_TASK', 'FREE_HERO_RECRUIT_ADVANCED', 'INTEL_CLAIM_REWARDS', 'INTEL_HERO_DISPATCH', 'INTEL_HERO_START_MARCH', 'JOIN_RALLY', 'MAIL_CLAIM_REWARDS', 'OPEN_ALLIANCE', 'OPEN_ALLIANCE_GIFTS', 'OPEN_ALLIANCE_TECH_FROM_HOME', 'OPEN_BEAR_RALLY_LIST', 'OPEN_DAILY', 'OPEN_EVENT_CALENDAR_FROM_HOME', 'OPEN_EVENT_CALENDAR_FROM_MAP', 'OPEN_EXPLORATION', 'OPEN_HOME', 'OPEN_INTEL', 'OPEN_MAIL', 'OPEN_POWER_OVERVIEW', 'OPEN_RESEARCH', 'OPEN_TASK_FROM_QUICK_PANEL_HERO_RECRUIT', 'RESEARCH', 'SEARCH_RESOURCE', 'SELECT_MAIL_ALLIANCE_TAB', 'SELECT_MAIL_REPORT_TAB', 'SELECT_MAIL_SYSTEM_TAB', 'SELECT_RESOURCE', 'START_GATHER', 'START_RALLY', 'SUBMIT_BEAST_SEARCH', 'SUBMIT_RESOURCE_SEARCH']
- promoted but RAN ON ADB: {}
- last step: OPEN_HOME via MAA at 2026-10-02T11:25:05.937644+00:00

> used_backend is what the step really did. A skill listed under promoted_but_ran_on_adb took the 324 ms ADB frame path while its own record claims MAA EmulatorExtras at 8.92 ms -- check tools/preflight.py before trusting the run.
