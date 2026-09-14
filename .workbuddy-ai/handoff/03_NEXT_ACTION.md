# 03 — NEXT ACTION

> 本文件必须保持**短小、具体**。目标：新账号不读完整历史也能继续当前任务。
> `AUTO:next_action` 块由 `tools/update_workbuddy_handoff.py` 重写；
> 其余手写内容不会被自动覆盖。

<!-- AUTO:next_action -->
CURRENT PRIORITY: fill the missing skills that block 4 goal(s)
CURRENT TASK: implement `CHECK_ALLIANCE_EVENT` — missing from the registry, blocks 2 goal(s): ['ALLIANCE_TIMED_EVENTS', 'PARTICIPATE_BEAR']

WHY: 4 goal(s) BLOCKED, 8 PARTIAL, mean implementation coverage 0.54. The blocked goals share one small set of never-implemented skills, so one skill purchase can move several goals at once.

CURRENT ROOT CAUSE: SEMANTIC_TARGET_NOT_VERIFIED x104
LAST GOOD COMMIT: d3f974a
CURRENT DIRTY FILES: 1
LAST PRODUCTION EPISODE: {"skill": "DISPATCH_MARCH", "result": "SUCCESS", "recorded_at": "2026-09-14T04:11:59.146784+00:00", "episode_id": "live_gather_run2", "before_screenshot": "dataset\\raw\\control_panel\\runtime_auto\\live_gather_run2\\live_gather_run2_step_001_before_20260914T041144038962.png", "after_screenshot": "dataset\\raw\\control_panel\\runtime_auto\\live_gather_run2\\live_gather_run2_step_001_after_20260914T041148263346.png"}
TOP FAILURE: {"failure_type": "SEMANTIC_TARGET_NOT_VERIFIED", "count": 104, "top_skills": [["SELECT_RESOURCE", 40], ["SEARCH_RESOURCE", 32], ["OPEN_MAIL", 13]]}

BLOCKED GOALS: ['KEEP_RESEARCH_PRODUCTIVE', 'ALLIANCE_TIMED_EVENTS', 'USE_FREE_ARENA_ATTEMPTS', 'LABYRINTH_DAILY']
MISSING SKILLS BY LEVERAGE: [('CHECK_ALLIANCE_EVENT', 2), ('CLAIM_EVENT_TIER', 2), ('JOIN_RALLY', 2), ('READ_BEAR_TIMER', 2), ('READ_COUNTER', 2), ('READ_TIMER', 2), ('USE_ACTIVITY_ATTEMPT', 2), ('ALLIANCE_HELP', 1), ('ALLIANCE_TECH_CONTRIBUTE', 1), ('OPEN_ARENA', 1)]
NEVER EXECUTED SKILLS (first 12): ['CANCEL_DUPLICATE_TARGET', 'CHECK_MARCH', 'CLAIM_REWARD', 'DISMISS_ALLIANCE_GENERIC_REWARD', 'DISMISS_EXPLORATION_REWARD', 'DISMISS_INTEL_GENERIC_REWARD', 'EXECUTE_INTEL_RESCUE_SURVIVORS', 'JOIN_RALLY', 'NAVIGATE_TO', 'OPEN_ALLIANCE_GIFTS', 'OPEN_INTEL_RESCUE_SURVIVORS_TARGET', 'READ_COUNTER']

NEXT EXACT ACTION: Add `CHECK_ALLIANCE_EVENT` to winter_agent_v2/skills.py v2_registry() AND register a post-action verifier in LiveRuntime.VERIFIED_ATOMIC (a skill without a verifier is never dispatched). It unblocks: ALLIANCE_TIMED_EVENTS, PARTICIPATE_BEAR. Requirement side: knowledge/goals/goal_capability_map.json lists it as an alternative for the blocked capability. Then REPLAY -> LIVE -> VERIFY -> EVIDENCE.

ACCEPTANCE: production episode + passing verifier + screenshot evidence, and the named goal(s) move off BLOCKED (live coverage increases).

DO NOT: re-architect, rename goals, or touch anything already live-verified without new failure evidence.
<!-- /AUTO:next_action -->

---

## 手写：当前任务的上下文

本区由人维护。生成器不会碰它。写「为什么是这个任务」以及「坑在哪」。

### 为什么当前优先级是「补齐缺失技能」而不是继续修采集

2026-09-14 用新的能力模型核实后的结论：

- `NEVER_TRIED` 的 Goal = **0 个**。旧文档怀疑的 5 个（Arena / Labyrinth / Event /
  AllianceTimed / Bear）**不是「没试过」，而是「没有实现」**——它们要求的技能
  在注册表里根本不存在，只在 `knowledge/skills/candidate/*.json` 里有设计稿。
- 因此继续在采集链路上打磨收益递减；真正卡住 4 个 BLOCKED Goal 的，是同一小批缺失技能。
- 反过来，采集链路**必须**先守住：它是当前唯一每天真实运行的产出。

所以并行两条线：
1. **守住** 已 Live 的链路（Intel / Mail / Train / 采集），不要回归；
2. **补齐** 缺失技能，把 BLOCKED Goal 变成 PARTIAL → FULLY_LIVE_VERIFIED。

### 缺失技能清单（按 blocked_goals 排序，来自 capability_skill_map.json）

- `CHECK_ALLIANCE_EVENT`  → 卡 PARTICIPATE_BEAR + ALLIANCE_TIMED_EVENTS
- `READ_BEAR_TIMER`       → 卡 PARTICIPATE_BEAR + ALLIANCE_TIMED_EVENTS
- `CLAIM_EVENT_TIER`      → 卡 EVENT_MINIMUM_GUARANTEE + ALLIANCE_TIMED_EVENTS
- `JOIN_RALLY` / `START_RALLY` → 卡 PARTICIPATE_BEAR + AVOID_STAMINA_WASTE
- `OPEN_ARENA` `READ_FREE_ATTEMPTS` `SELECT_ARENA_OPPONENT` `START_ARENA`
  `VERIFY_ARENA_RESULT` → 卡 USE_FREE_ARENA_ATTEMPTS
- `OPEN_LABYRINTH` `READ_LABYRINTH_ATTEMPTS` `START_LABYRINTH`
  `VERIFY_LABYRINTH_RESULT` → 卡 LABYRINTH_DAILY
- `OPEN_EVENT` `READ_EVENT_PROGRESS` `READ_EVENT_TIMER` → 卡 EVENT_MINIMUM_GUARANTEE
- `OPEN_RESEARCH` → 卡 KEEP_RESEARCH_PRODUCTIVE（`RESEARCH` 本身已注册但为 BLOCKED）

### 坑（必须知道）

1. **不要写死坐标。** 资源页签带会滚动，客户端会把当前选中页签重新居中。
   已经实测到两种滚动偏移（0 与 +400px）。必须走
   `SemanticROIVision.selected_resource` 的白色角标锚点 + 相对布局。
2. **`run_live.py` 与 `control_panel.py` 传入的 vision 对象不是同一种。**
   用 `LiveRuntime._semantic` 访问器，不要直接 `self.semantic_vision.semantic`。
3. **新增 Skill 必须同时提供 verifier**，否则 `LiveRuntime.VERIFIED_ATOMIC` 不含它，
   就永远不会被 live loop 调度（`capability_coverage` 会把它算成「未实现」）。
4. **不要用通配符批量删文件。** 项目目录曾经不是 git 仓库；现在已经有了，
   但删除前仍必须逐项确认。
5. Bash 工具在本机**没有 coreutils**（`ls/cat/head/sleep/wc/date` 都不可用），
   PowerShell 工具**stdout 不回传**。所有命令都用
   `"E:/dongri-mumu-bot/.venv/Scripts/python.exe" -c "..."` 配合重定向 + Read 读取。

### 真机环境（当前实测）

- MuMu 默认不启动。启动：
  `"D:/Program Files/Netease/MuMu Player 12/nx_main/MuMuManager.exe" control -v 0 launch -pkg com.gof.china`
  然后 `adb connect 127.0.0.1:7555`。
- 真机可用时：720×1280，前台包 `com.gof.china`。
- 跑项目脚本必须用项目 venv：`E:\dongri-mumu-bot\.venv\Scripts\python.exe`（含 PIL / rapidocr）。
  托管 Python 3.13 **没有 PIL**。
