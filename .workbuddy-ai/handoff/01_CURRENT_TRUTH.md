# 01 — CURRENT TRUTH

- generated_at: `2026-10-13T16:40:13+00:00`
- source: `tools/update_workbuddy_handoff.py` (reads git, registry, capability map, episode stream, snapshot, logs)
- commit: `d54d9e9f` on `main`

> This file is regenerated. Never hand-edit it; edit the project instead.

## A. Version control

- repository: yes
- last good commit: `e4fd245`
- commits: 1249
- HEAD: `d54d9e9f` — docs(memory): the machine is parked in MANUAL, and only the operator can release it (2026-10-14T00:37:37+08:00)
- working tree: 1389 dirty file(s)
  - `M .gitignore`
  - ` M .workbuddy-ai/commander/CODEX_DIRECTIVES.md`
  - ` M .workbuddy-ai/commander/LAST_CODEX_REVIEW.md`
  - ` M .workbuddy-ai/commander/README.md`
  - ` M .workbuddy-ai/handoff/01_CURRENT_TRUTH.md`
  - ` M .workbuddy-ai/handoff/02_CURRENT_PROGRESS.md`
  - ` M .workbuddy-ai/handoff/03_NEXT_ACTION.md`
  - ` M .workbuddy-ai/handoff/04_OPEN_ISSUES.md`
  - ` M .workbuddy-ai/handoff/05_RECENT_CHANGES.md`
  - ` M .workbuddy-ai/handoff/08_LIVE_METRICS.json`
  - ` M .workbuddy-ai/handoff/09_RUNTIME_STATE.json`
  - ` M .workbuddy-ai/handoff/10_LAST_HANDOFF.md`
  - ` M .workbuddy-ai/memory/2026-10-03.md`
  - ` M .workbuddy-ai/memory/2026-10-05.md`
  - ` M .workbuddy-ai/memory/MEMORY.md`
  - ` M .workbuddy/memory/2026-10-03.md`
  - ` M .workbuddy/memory/2026-10-05.md`
  - ` M START_HERE.md`
  - ` M _capture_panel_window.py`
  - ` D backups/dataset_cleanup_20261006/template_manifest.json.bak`

### A2. Public mirror

The repository is PUBLIC, so 'is the mirror current' is part of the truth this file
reports, not a side note. `remote_head` is the local remote-tracking ref: it is as
fresh as the last fetch, and `tools/git_sync.py status` is what refreshes it.

```
SYNC STATE at 2026-10-13T16:40:13+00:00
remote            : https://github.com/hongweixiong0-star/winter-agent-os-v2.git
branch            : main
local_head        : d54d9e9f3721431ecc442e86ef5e9852287f214e
remote_head       : 297af0d1c1d4ebfac2635f279c5f4cc0233ed936   (local remote-tracking ref; run tools/git_sync.py status to refresh)
unpushed_commits  : 138   (behind: 0)
git_dirty         : True (1389 path(s))
last_push_at      : 2026-10-05T13:19:05.233600+00:00
last_push_status  : PUSHED
verdict           : LOCAL IS AHEAD by 138 commit(s) -- run `python tools/git_sync.py push`
```

## B. Runtime

- agent_state: `IDLE`
- runtime_thread_alive: False / scheduler_loop_alive: False
- unexpected_worker_exits: 59
- watchdog_restart_count: 62
- last_fatal_error: None
- stop_reason: manually_owned_by_workbuddy
- page: HOME  march: None/None
- updated_at: 2026-10-13T13:47:43.054938+00:00

## C. Episode stream

- rows: 10436 (production 10436)  modes: {'PRODUCTION': 10436}
- success / failure: 9488 / 943
- success rate over decided: **0.9096**
- mixed-case `result` rows (normalise on read, never rewrite): 0
- last episode: `{"skill": "BACK", "result": "SUCCESS", "recorded_at": "2026-10-11T09:29:00.345277+00:00", "episode_id": "20261011_172738_866458", "before_screenshot": "E:\\无尽冬日智能体_worktrees\\winter-prod-pinned\\无尽冬日智能体\\dataset\\raw\\control_panel\\runtime_auto\\20261011_172738_866458\\20261011_172738_866458_step_004_before_20261011T092853016380.png", "after_screenshot": "E:\\无尽冬日智能体_worktrees\\winter-prod-pinned\\无尽冬日智能体\\dataset\\raw\\control_panel\\runtime_auto\\20261011_172738_866458\\20261011_172738_866458_step_004_after_20261011T092854351456.png"}`

## D. Registry and lifecycle

- registry total: 153  by_state: {'CANDIDATE': 102, 'VERIFIED': 47, 'BLOCKED': 4}
- live dispatchable (verifier-backed): 141
- BLOCKED skills: ['ALLIANCE_HELP', 'COLLECT_FINISHED_TRAINING_LANCER', 'COLLECT_FINISHED_TRAINING_MARKSMAN', 'COLLECT_FINISHED_TRAINING_SHIELD']
- live_verified: **8**  stable: 58  degraded: 16  only_failed: 7  never_executed: 67

### Never executed

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
- `OPEN_BEAST_SEARCH_TAB` attempts=30 failure=30
- `READ_FISHING_STATE` attempts=1 failure=1
- `SAFE_STOP` attempts=6 failure=6
- `START_RALLY` attempts=1 failure=1

### Stable

- `ATTACK_BEAST_CARD` success=6 rate=0.8571
- `BACK` success=2268 rate=0.9839
- `CLAIM_FREE_STAMINA` success=10 rate=1.0
- `CLEAR_GATHER_HEROES` success=30 rate=1.0
- `CONFIRM_EXPLORATION_IDLE_CLAIM` success=34 rate=0.9189
- `DAILY_CLAIM_REWARDS` success=16 rate=0.8889
- `DISMISS_EXPLORATION_GENERIC_REWARD` success=29 rate=0.8529
- `DISMISS_INTEL_GENERIC_REWARD` success=120 rate=1.0
- `DISMISS_SHARED_REWARD` success=52 rate=0.963
- `DISPATCH_BEAST` success=7 rate=1.0
- `DISPATCH_INTEL_BEAST` success=70 rate=0.9091
- `DISPATCH_MARCH` success=12 rate=1.0
- `EXECUTE_INTEL_RESCUE_SURVIVORS` success=31 rate=0.9118
- `EXPLORATION_IDLE_CLAIM` success=36 rate=0.8
- `FOLLOW_DAILY_TASK` success=11 rate=1.0
- `FREE_HERO_RECRUIT_ADVANCED` success=18 rate=0.9474
- `INTEL_BEAST_START_MARCH` success=105 rate=0.9545
- `INTEL_CLAIM_REWARDS` success=144 rate=0.9931
- `INTEL_HERO_DISPATCH` success=49 rate=0.9608
- `INTEL_HERO_START_MARCH` success=80 rate=0.9877
- `MAIL_CLAIM_REWARDS` success=56 rate=0.9825
- `OPEN_ALLIANCE` success=19 rate=1.0
- `OPEN_BEAR_RALLY_LIST` success=25 rate=1.0
- `OPEN_COMPLETED_TRAINING_CAMP_MARKSMAN` success=13 rate=1.0
- `OPEN_COMPLETED_TRAINING_CAMP_SHIELD` success=15 rate=1.0
- `OPEN_DAILY` success=34 rate=0.9189
- `OPEN_EVENT_CALENDAR_FROM_HOME` success=98 rate=0.9703
- `OPEN_EVENT_CALENDAR_TAB` success=96 rate=0.96
- `OPEN_EXPLORATION` success=43 rate=0.9556
- `OPEN_HOME` success=311 rate=0.8249
- `OPEN_INFANTRY_TRAINING` success=51 rate=0.9623
- `OPEN_INTEL` success=1204 rate=0.9813
- `OPEN_INTEL_BEAST_TARGET` success=112 rate=0.8485
- `OPEN_INTEL_HERO_JOURNEY_TARGET` success=95 rate=1.0
- `OPEN_INTEL_RESCUE_SURVIVORS_TARGET` success=25 rate=0.8065
- `OPEN_LOGIN_GIFT` success=16 rate=1.0
- `OPEN_MAIL` success=35 rate=0.9722
- `OPEN_MAP` success=898 rate=0.9868
- `OPEN_QUICK_PANEL` success=889 rate=1.0
- `OPEN_STAMINA_SOURCES` success=20 rate=0.9524
- `OPEN_TASK_FROM_QUICK_PANEL_HERO_RECRUIT` success=17 rate=1.0
- `OPEN_TASK_FROM_QUICK_PANEL_PET_TREASURE` success=42 rate=1.0
- `PRINTED_TAP` success=107 rate=0.9068
- `RECONNECT_SESSION` success=5 rate=1.0
- `RETURN_EVENT_CALENDAR` success=43 rate=1.0
- `SCAN_MAP_FOR_BEAST` success=10 rate=1.0
- `SCROLL_QUICK_PANEL_TASKS` success=152 rate=0.956
- `SEARCH_RESOURCE` success=271 rate=0.9509
- `SELECT_GIANT_BEAST_TAB` success=189 rate=0.9844
- `SELECT_INTEL_BEAST_MISSION` success=6 rate=0.8571
- `SELECT_INTEL_PIN` success=720 rate=0.989
- `SELECT_MAIL_ALLIANCE_TAB` success=12 rate=1.0
- `SELECT_MAIL_SYSTEM_TAB` success=8 rate=1.0
- `SELECT_RESOURCE` success=40 rate=0.9524
- `START_GATHER` success=17 rate=1.0
- `SUBMIT_BEAST_SEARCH` success=6 rate=1.0
- `SUBMIT_RESOURCE_SEARCH` success=202 rate=1.0
- `TRAIN_TROOPS` success=33 rate=0.9167

### Degraded

- `CLOSE_POPUP` success=6 failure=4 rate=0.6
- `DISMISS_DAILY_GENERIC_REWARD` success=27 failure=10 rate=0.7297
- `OPEN_BUILDING_UPGRADE` success=39 failure=10 rate=0.7959
- `OPEN_COMPLETED_TRAINING_CAMP_LANCER` success=15 failure=7 rate=0.6818
- `OPEN_EVENT_CALENDAR_DETAIL` success=44 failure=46 rate=0.4889
- `OPEN_EVENT_CALENDAR_FROM_MAP` success=11 failure=9 rate=0.55
- `OPEN_TASK_FROM_QUICK_PANEL_BUILDING` success=61 failure=22 rate=0.7349
- `SCROLL_QUICK_PANEL_BACK` success=15 failure=12 rate=0.5556
- `SELECT_BEAST_TARGET_LABELLED` success=6 failure=3 rate=0.6667
- `SELECT_BEAST_TARGET_MAMMOTH` success=12 failure=144 rate=0.0769
- `SELECT_MAIL_REPORT_TAB` success=5 failure=2 rate=0.7143
- `SUBMIT_GIANT_BEAST_SEARCH` success=42 failure=164 rate=0.2039
- `TAP_FOCUSED_TRAINING_CAMP_LANCER` success=11 failure=11 rate=0.5
- `TAP_FOCUSED_TRAINING_CAMP_MARKSMAN` success=11 failure=11 rate=0.5
- `TAP_FOCUSED_TRAINING_CAMP_SHIELD` success=10 failure=11 rate=0.4762
- `TRY_ORDINARY_CONTROL` success=92 failure=160 rate=0.3651

## E. Top failures

Failure | Count | Top skills
---|---:|---
`GIANT_BEAST_SEARCH_NOT_PROVEN` | 164 | SUBMIT_GIANT_BEAST_SEARCH(164)
`BEAST_TARGET_SELECTION_NOT_PROVEN` | 146 | SELECT_BEAST_TARGET_MAMMOTH(143), SELECT_BEAST_TARGET_LABELLED(3)
`SEMANTIC_TARGET_NOT_VERIFIED` | 292 | TRY_ORDINARY_CONTROL(159), OPEN_HOME(36), OPEN_EVENT_CALENDAR_DETAIL(23)
`SAFE_BACK_NOT_PROVEN` | 37 | BACK(37)
`EVENT_CALENDAR_DETAIL_NOT_PROVEN` | 23 | OPEN_EVENT_CALENDAR_DETAIL(23)
`INTEL_BEAST_TARGET_NOT_PROVEN` | 20 | OPEN_INTEL_BEAST_TARGET(20)
`FOCUSED_CAMP_ACTION_BAR_NOT_PROVEN` | 33 | TAP_FOCUSED_TRAINING_CAMP_MARKSMAN(11), TAP_FOCUSED_TRAINING_CAMP_SHIELD(11), TAP_FOCUSED_TRAINING_CAMP_LANCER(11)
`BEAST_SEARCH_TAB_NOT_PROVEN` | 17 | OPEN_BEAST_SEARCH_TAB(17)
`NO_EXECUTION` | 22 | PRINTED_TAP(11), SAFE_STOP(6), SEARCH_RESOURCE(5)
`OPEN_MAP_NOT_PROVEN` | 9 | OPEN_MAP(9)

## F. Goal capability coverage

- model: Goal -> Canonical Capability -> Registered Skill -> Production Evidence
- summary: {"total": 20, "fully_live_verified": 2, "partial": 9, "never_tried": 4, "blocked": 4, "degraded": 1, "missing": 0, "fully_live_verified_percent": 10.0, "never_tried_percent": 20.0, "automation_coverage_mean": 0.7083, "live_coverage_mean": 0.4012}

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
CLAIM_FREE_REWARDS | DEGRADED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 50% | -
CLAIM_EXPLORATION_IDLE | FULLY_LIVE_VERIFIED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 100% | -
ALLIANCE_ROUTINE | PARTIAL | NOT_A_RUNTIME_GOAL | 100% | 75% | 25% | 25% | ALLIANCE_HELP
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
- referenced screenshots: 20549  present: 20549
- missing: []
- episodes carrying screenshot references: 10432

## H. Commercial bot parity

- present: True
- summary: {"features_tracked": 21, "features_with_live_success": 10, "parity_fraction": 0.4762}
- features without live evidence: ['VIP', 'ALLIANCE_HELP', 'PROMOTE', 'HEAL', 'RESEARCH', 'ARENA', 'LABYRINTH', 'JOIN_RALLY', 'START_RALLY', 'BEAR', 'PET']

## I. Latest runtime log

- {"path": "E:\\无尽冬日智能体\\learning\\control_panel\\latest.log", "modified_at": "2026-10-13T13:47:31+00:00", "size_bytes": 4598, "last_stop_reason": "manually_owned_by_workbuddy"}
- recent crash reports: ['E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20261010_113921_385181_auto_subprocess.json', 'E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20261010_184425_589697_auto_subprocess.json', 'E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20261010_184434_406371_auto_subprocess.json', 'E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20261011_020049_242237_auto_subprocess.json', 'E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20261011_053851_840529_auto_subprocess.json']

## J. Backend axis (MAA vs ADB)

- source: `learning/executor_backend.jsonl` vs `knowledge/execution/backend_routing.json`
- ledger rows: 20000 (last 200 summarised)
- used_backend: {"ADB": 107, "MAA": 93}
- capture_backend: {"ADB_EXEC_OUT": 107, "MAA_MUMU_EXTRAS": 93}
- promoted to MAA in routing: 37 ['BACK', 'BEAR_AUTO_JOIN', 'CLOSE_POPUP', 'COLLECT_TRAINING_BATCH', 'DAILY_CLAIM_REWARDS', 'DISMISS_BATTLE_VICTORY', 'DISPATCH_MARCH', 'EXPLORATION_IDLE_CLAIM', 'FOLLOW_DAILY_TASK', 'FREE_HERO_RECRUIT_ADVANCED', 'INTEL_CLAIM_REWARDS', 'INTEL_HERO_DISPATCH', 'INTEL_HERO_START_MARCH', 'JOIN_RALLY', 'MAIL_CLAIM_REWARDS', 'OPEN_ALLIANCE', 'OPEN_ALLIANCE_GIFTS', 'OPEN_ALLIANCE_TECH_FROM_HOME', 'OPEN_BEAR_RALLY_LIST', 'OPEN_COMPLETED_TRAINING_CAMP_LANCER', 'OPEN_DAILY', 'OPEN_EXPLORATION', 'OPEN_HOME', 'OPEN_INTEL', 'OPEN_MAIL', 'OPEN_POWER_OVERVIEW', 'OPEN_RESEARCH', 'RESEARCH', 'SEARCH_RESOURCE', 'SELECT_MAIL_ALLIANCE_TAB', 'SELECT_MAIL_REPORT_TAB', 'SELECT_MAIL_SYSTEM_TAB', 'SELECT_RESOURCE', 'START_GATHER', 'START_RALLY', 'SUBMIT_BEAST_SEARCH', 'SUBMIT_RESOURCE_SEARCH']
- promoted but RAN ON ADB: {}
- last step: BACK via MAA at 2026-10-11T09:28:54.106520+00:00

> used_backend is what the step really did. A skill listed under promoted_but_ran_on_adb took the 324 ms ADB frame path while its own record claims MAA EmulatorExtras at 8.92 ms -- check tools/preflight.py before trusting the run.
