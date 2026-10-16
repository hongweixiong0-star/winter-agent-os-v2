# SKILL_GAP_INVENTORY.md — 统一缺口清单 v1（2026-10-16）

> 生成：WorkBuddy 会话（r190 盘点批）· 依据：**真实工作区读取 + 真实工具运行**（非文档照抄）
> 数据源：`SKILL_COVERAGE.md`/`SKILL_CATALOG.md`（口径）· `tools/full_auto_coverage_audit.py`（run）·
> `tools/build_capability_coverage.py`（run）· `learning/runtime_snapshot.json`（运行态）·
> `knowledge/skills/`（31 spec）· `knowledge/goals/`（3 映射）· `capability_bootstrap`（经测试文件确认接口）

## 0. 运行态（P0 事实）

| 项 | 实测值 |
|---|---|
| 面板进程 | **活着**（PID 15300"无尽冬日 AI 指挥中心"） |
| **AUTO 运行时** | ⚠️ **已停**——snapshot：`runtime_thread_alive=false` / `scheduler_loop_alive=false`（最后 tick 10-15 20:38） |
| 停止原因链 | `ROLE_SWITCH_FAILED:1061663148:TARGET_ROLE_HOME_NOT_OBSERVED` → abort（20:36-20:38，**与本会话首次接管设备时段重合**——如实记录） |
| 重启路径 | 面板"开始自动运行"按钮 / `schtasks /Run /TN "WinterAgentV2Panel"`（⚠️ 本会话沙箱禁止 schtasks.exe——**重启动作待授权与时机**） |
| watchdogs | `watchdog_restart_count=67`（历史累计） |

## 1. 七类缺口（指令分类 × 实测映射）

| # | 类别 | 实测发现 | 量 |
|---|---|---|---|
| 1 | **玩法存在，无 Skill** | BLOCKED 4 Goal 的**无实现 capability**：`USE_FREE_ARENA_ATTEMPTS`（3 个：OPEN/READ/SELECT）+ `LABYRINTH_DAILY`（全）+ `TRAVEL_SUPPLY`（全）+ `ALLIANCE_TIMED_EVENTS`（3 个）+ `EVENT_MINIMUM_GUARANTEE` 的 5/7（OPEN_PAGE/READ_RULES/READ_PROGRESS/READ_TIMER/CLAIM_TIER）+ `PARTICIPATE_BEAR` 的 2 个（CHECK_BEAR_PHASE/SELECT_TROOP_PRESET）+ `DAILY` 的 READ_DAILY_PROGRESS | **~15 capability** |
| 2 | Skill 存在，未注册 | **初步 0**（`full_auto` 的 BOARD_ONLY_NO_SKILL=0）；**待一轮 registry×map 对表复核** | 0? |
| 3 | 已注册，无完整执行链 | **CANDIDATE 类**（有实现、live 未验证）：READ_INTEL_LIST / VERIFY_GATHERING / START_BUILD / OPEN_RESEARCH / START_RESEARCH / DISMISS_MAIL_REWARD / ALLIANCE_TECH_CONTRIBUTE / PLAY_NORMAL_FISHING_LEVEL / READ_FISHING_STATE(LIVE_TRIED 1-0) 等 | **~9-12** |
| 4 | 缺页面/控件证据 | bootstrap projection `MISSING_OBSERVATION=63` + BLOCKED-"无实现"面 | 63（投影） |
| 5 | 缺前置/Verifier/Recovery | ⭐ **bootstrap projection `MISSING_VERIFIER=115`**（最坏情况投影——**最大缺口面**） | 115（投影） |
| 6 | 未接 Goal/Scheduler | `BOARD_ONLY_STATUS=5`（明细待展）+ `NEVER_TRIED_GOALS=4`（KEEP_RESEARCH / MOBILIZATION_ICEFIELD / FISHING×2）；3 个 `ON_BOARD_OBSERVATION_ONLY_NO_SKILL`（LABYRINTH/FISHING_TOURNAMENT/ARENA——**chooser 打分但 skills=0**） | 5+4+3 |
| 7 | 执行失败（已有能力） | **DEGRADED 5**：⭐`SPEND_STAMINA_ON_BEAST`（**189 试 / 41 成 = 22%**）· `OPEN_BUILDING_PAGE`（132/100）· `DISMISS_DAILY_REWARD`（37/27）· `DISMISS_FREE_REWARD_POPUP`（71/56）· Goal 级 `CLAIM_FREE_REWARDS`（DEGRADED） | 5 |

## 2. 四层覆盖率（`build_capability_coverage.py` 实测）

- Goal 20：**FULLY_LIVE_VERIFIED 2**（TRAINING / EXPLORATION_IDLE）· PARTIAL 9 · NEVER_TRIED 4 · BLOCKED 4 · DEGRADED 1
- **mean implementation 70.8% / mean live 40.1%**
- 最高 live：MARCHES 86% / INTEL 83% / MAIL 75% / TRAINING 100%
- 最低 live：RESEARCH 0% / MOBILIZATION 0% / FISHING×2 0% / ARENA·LABYRINTH·TRAVEL_SUPPLY 0%（BLOCKED）/ BEAR 25% / EVENT 17% / ALLIANCE_TIMED 0%

## 3. 优先级计算（指令 §5 顺序 × 实测）

| 序 | 项 | 理由 |
|---|---|---|
| **P0** | `SPEND_STAMINA_ON_BEAST` 22% 的**确定性缺陷** | 指令第 1 优先=修复已有能力的确定性缺陷；且它是高频消耗（189 次） |
| **P1** | 3 个 `ON_BOARD_OBSERVATION_ONLY_NO_SKILL` 的**接线缺陷**（chooser 可选中却 skills=0） | 指令第 1 优先的"接线"面；LABYRINTH/FISHING/ARENA |
| **P2** | CANDIDATE 类的 **Verifier/live 补全**（~9-12 个） | 指令第 3 优先 |
| **P3** | BLOCKED 类的**按需采集**（ARENA/LABYRINTH/EVENT 规则面的页面证据） | 指令第 4 优先（定向采集） |
| **P4** | NEVER_TRIED 低频（RESEARCH 被队列阻塞=环境性 / FISHING 需活动窗口） | 指令第 5 优先 |
| **P0'** | AUTO 运行时重启 | **待授权与时机**（设备当前归采集会话；schtasks 被沙箱禁止）——**不做假设** |

## 4. 下一步（自动执行建议）

1. **P0 根因**：读 `SPEND_STAMINA_ON_BEAST` / `SELECT_BEAST_TARGET_MAMMOTH` 的失败 episode 与 Verifier 日志——**定位 22% 的确定性缺陷**（离线可做）
2. **P1 接线**：读 3 个 no-skill goal 的 `goal_capability_map` 条目与 chooser 路径——判断是"缺 step 映射"还是"缺 skill 实现"
3. **类 2 复核**：registry × capability_skill_map 对表（确认"未注册"是否真为 0）
