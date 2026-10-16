# NEVER_TRIED 5 的真机验证清单（2026-10-16 起草）

**用途**：覆盖率口径（`docs/CAPABILITY_COVERAGE.md`）里 5 个"实现 100%、live 0%"的 goal——
设备时机到来时**照单直跑**，无需重新推导。
**来源**：`goal_capability_map.json`、`session_adapters.py` 的路由表、`goal_library` 的发射分支、
`03_NEXT_ACTION.md` 的历史记录。**不是**新发明；每条都可回溯。

**通用前提**：`MODE_STATE` 切回 AUTO 或 MANUAL 授权（操作员使用中）；`episodes.jsonl` 是唯一证据面。

| # | goal | 先决条件（客户侧） | 第一步技能 | 期望的 live 证据 | 备注 |
|---|---|---|---|---|---|
| 1 | `KEEP_RESEARCH_PRODUCTIVE` | 研究楼空闲（队列可用） | `OPEN_RESEARCH` → 研究起点 | episode：`RESEARCH_STARTED` verifier pass，`research.queue_available` 翻转 | 最"日常"的一条——任何一次 AUTO 周期都可能撞上 |
| 2 | `ALLIANCE_TIMED_EVENTS` | 联盟活动窗口**开放**（等自然时间） | `READ_ALLIANCE_EVENT_TIMER` | episode：计时器读取（`CLAIM_EVENT_TIER` 是第二能力，待窗口） | 闸门 = 窗口；**预约时间**，不用盯 |
| 3 | `ALLIANCE_MOBILIZATION_ICEFIELD_BEAST` | 联盟总动员**开放** + 任务行含 `ICEFIELD_BEAST` | `START_RALLY`（bear adapter） | episode：`RALLY_CREATED` verifier pass（POLAR_TERROR/BEAR 按 sink） | 需要 `alliance_mobilization` 读取 recognized＋role 匹配 |
| 4 | `OBSERVE_FISHING_STATE` | 钓鱼活动**开放**（或未开也要读——stale 分支） | `READ_FISHING_STATE`（fishing adapter） | episode：read-only 读取，`only_allowed_spend=NONE` | 该 goal 本身就是"去读" |
| 5 | `USE_NORMAL_FISHING_BAIT` | 钓鱼活动开放 + 普通鱼饵计数 >0 | `PLAY_NORMAL_FISHING_LEVEL`（fishing adapter） | episode：一次 bounded 钓鱼会话 | 先决：bait counter 已读（`READ_FISHING_STATE` 先行） |

**跑法**（设备时机）：
- **不设专用命令**：正常 AUTO/按需 run 会自行选中（`choose_stamina_goal`/routines 已接线）。
- **想定向验证**：`run_live.py --goal <goal_id>`（若该 goal 有 route；否则用其 session route 的入口技能）。
- **记录**：每次跑后把 episode 行（verifier_reason + state_before/after）贴进本表的"结果"列（新版本文件或直接在此追加）。

**结果记录（跑后追加）**：
| # | 日期 | episode 摘要 | 结果 |
|---|---|---|---|
| — | — | （待设备时机） | — |

**BLOCKED 3 的对照**（不是本单内容，防止混淆）：`USE_FREE_ARENA_ATTEMPTS` / `LABYRINTH_DAILY` /
`TRAVEL_SUPPLY` 是**零起点**（13 个能力 token、registry 0 技能、dataset 0 帧）——它们需要**先探索建技能**，
不在本清单里。
