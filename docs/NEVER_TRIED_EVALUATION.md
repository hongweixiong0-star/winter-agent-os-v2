# NEVER_TRIED Goals 可执行性评估（PHASE H）

> 本报告只记录可从证据中确认的事实。凡未真机复验的结论一律标注状态。

## 结论摘要

7 个 `NEVER_TRIED` 目标中，**0 个可以直接执行**。

原因不是"没写代码"，而是每个目标都缺少**至少一个可执行的入口技能**。
技能状态取自 `winter_agent_v2.skills.v2_registry()` 的真实注册表，
模板存在性取自 `dataset/candidate/template_manifest.json`。

## 逐目标评估

| 目标 | 组成 | 缺失的关键技能 | 视觉模板 | 结论 |
| --- | --- | --- | --- | --- |
| `KEEP_RESEARCH_PRODUCTIVE` | ALL_OF | `OPEN_RESEARCH` 未注册 | `BTN_OPEN_RESEARCH` 存在但**被教程手势污染** | 不可执行 |
| `CLAIM_FREE_REWARDS` | ANY_OF | `CLAIM_FREE_REWARD` / `OPEN_VIP` / `CLAIM_VIP_FREE` 全部未注册 | 无 | 不可执行 |
| `USE_FREE_ARENA_ATTEMPTS` | SEQUENCE | `OPEN_ARENA` / `READ_FREE_ATTEMPTS` / `SELECT_ARENA_OPPONENT` / `START_ARENA` 全部未注册 | 无 | 不可执行 |
| `EVENT_MINIMUM_GUARANTEE` | SEQUENCE | `OPEN_EVENT` / `READ_EVENT_*` / `CLAIM_EVENT_TIER` 全部未注册 | 无 | 不可执行 |
| `PARTICIPATE_BEAR` | SEQUENCE | `CHECK_ALLIANCE_EVENT` / `SELECT_TARGET` / `SELECT_TROOP_PRESET` 未注册；`START_RALLY` 为 `CANDIDATE` | 部分 | 不可执行 |
| `LABYRINTH_DAILY` | SEQUENCE | `OPEN_LABYRINTH` / `READ_LABYRINTH_ATTEMPTS` / `START_LABYRINTH` 全部未注册 | 无 | 不可执行 |
| `ALLIANCE_TIMED_EVENTS` | ANY_OF | `CHECK_ALLIANCE_EVENT` / `READ_ALLIANCE_EVENT_TIMER` 未注册 | 无 | 不可执行 |

## 最接近可执行的目标：`KEEP_RESEARCH_PRODUCTIVE`

这是唯一一个"视觉能力已具备、只差入口技能注册"的目标，因此是**首选攻坚对象**。

已确认的事实：

- `Page.RESEARCH` 已被 `SemanticWorldVision.observe()` 识别（`vision.py` 约 615 行）。
- `PAGE_RESEARCH`、`BTN_OPEN_RESEARCH`、`RESEARCH_TAB_GROWTH` / `_ECONOMY` / `_BATTLE`、
  `STATUS_RESEARCH_IN_PROGRESS`、`RESEARCH_QUEUE_TIMER` 等模板均已注册。
- `RESEARCH` 技能存在，但状态为 `SkillState.BLOCKED`，前置页 `Page.RESEARCH` 无法到达，
  因为 **`OPEN_RESEARCH` 技能从未注册**。

阻塞点：`BTN_OPEN_RESEARCH` 的两个模板
（`live_research_power_navigation.png`、`live_20260908_research_navigation_current.png`）
都裁自**同一次教程引导**的相邻帧，ROI `x∈[0.68,0.81], y∈[0.596,0.716]` 内
被一只引导手势大面积遮挡。实测在 `dataset/raw/live_home*.png` / `live_current*.png`
上**命中 0 次**。

因此 `KEEP_RESEARCH_PRODUCTIVE` 的解锁条件是：

1. 真机进入城镇页，在**无教程手势**的状态下重采 `BTN_OPEN_RESEARCH` 的可见样本；
2. 用新样本重建模板（至少 2 个不同视角/状态，避免单点冗余）；
3. 注册 `OPEN_RESEARCH` 技能并接入 verifier（`verify_research_page_open` 一类的页级证明）；
4. 把 `RESEARCH` 技能从 `BLOCKED` 提升到 `CANDIDATE`，再走 Replay → Live → Verify 流程。

**以上 4 步全部依赖真机，当前无法执行。**

## 为什么不能靠"多写几个技能定义"推进

总指令要求 `LIVE CLIENT > PRODUCTION EVIDENCE > CURRENT CODE`。
为这 6 个目标补技能定义，产出的是**代码**，不是**能力**：

- 没有真机 UI 采样就没有可信模板，技能即使注册也是 `CANDIDATE` 且无法通过 verifier；
- 把 `NEVER_TRIED` 改成 `BLOCKED` 只是换了标签，不改变"从未在真机成功过"的事实；
- 总指令明确禁止把"代码存在"当作成功。

因此本阶段对 7 个目标的处置是：**记录事实、锁定首选对象、等待真机窗口**，
而不是批量生成无法验证的技能骨架。

## 建议的执行顺序（维护结束后）

1. `KEEP_RESEARCH_PRODUCTIVE` —— 视觉能力最完整，只需重采 1 个入口模板。
2. `ALLIANCE_TIMED_EVENTS` —— 复用已有的 `OPEN_ALLIANCE`（`VERIFIED`），只缺事件页读取。
3. `PARTICIPATE_BEAR` —— `JOIN_RALLY` / `START_RALLY` 已注册（均为 `CANDIDATE`），缺集会目标选择与事件计时。
4. 其余 4 个 —— 需从零探索对应 UI。
