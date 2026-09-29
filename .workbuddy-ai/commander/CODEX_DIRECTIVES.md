# Codex Directives — 2026-09-24

本轮为全面审计后的修复计划。正式 WorkBuddy 接口为 `WORK_QUEUE.json`；10 个 Work Orders 共 720 分钟。当前只允许代码核查、离线修复与回放；不操作游戏 UI、不控制设备、不切角色、不消耗体力/队列、不发起或加入巨熊。

## 当前基线
- HEAD `789271789ae0b691d97435b26fe64861b3719595`；核验时工作树 711 个 dirty/untracked 路径。
- 运行快照 2026-09-24 17:35:49：IDLE，runtime thread 与 scheduler loop 均停止；EXPLORATION / `exploration_income_not_ready`；march capacity UNKNOWN。
- 旧队列 9/21；旧 `WB-0921-01` 在 `EXECUTION_STATE` 中仍 IN_PROGRESS。首单必须先对账任务所有权、结果、实际进程/租约和共享 diff；不覆盖、不清理、不代写 WorkBuddy 执行态。旧队列已归档，旧结果保留。
- 巨熊 parser/policy 已有离线实现但无生产调用链；历史没有 START_RALLY/JOIN_RALLY episode。Readiness 仅在已有 Scheduler tick 内加分，不等于 worker wake。

## 执行顺序与验收
按队列顺序 01–10，依赖未满足时不做依赖的 live 计划，转下一个独立任务。每单到时限收口；UI/数据假设 15 分钟无新证据即 TOOL CHECK；不等待自然活动、不制造状态。普通任务 30–60 分钟，复杂最多 90 分钟。

Read evidence → Tool check → Minimal implementation → Targeted test → Offline replay → Verify → Before/after → Result → Next。动作发出不等于能力成功；verifier 必须证明状态变化。未知角色、容量或 UI 目标一律保持 UNKNOWN 并拒绝动作。

## 架构与安全边界
- 复用既有 WorldState、Knowledge、Goal、单 Scheduler、Brain、Vision、MAA Executor；禁止第二套 Manager/Scheduler。
- Capacity、Occupancy、Reservation 分离并 role-scoped；角色切换后清空上个角色的瞬时观测；禁止固定 march_slots 或 reserve 常量。
- 所有坐标/手势从当前帧与可识别控件/容器派生；不能证明时安全拒绝。历史坐标不是 fallback。
- 不重写历史 Episode，不把 unit/replay 结果标为 LIVE_VERIFIED，不把旧统计当当前事实；记录真实 revision、样本和 blocker。
- WorkBuddy 只维护 `EXECUTION_STATE.json`、`results/`、`BLOCKED_QUEUE.json`、`REVIEW_REQUESTS.md`。不得改写 Codex 原 Work Order。Codex 维护 `WORK_QUEUE.json`、本文件和 `LAST_CODEX_REVIEW.md`。

## 外部活动窗口
真实 Joiner/Leader Bear 测试不在本队列授权范围。当前批次只离线准备；活动窗口、当前 role 身份、设备租约、队列状态未确认时绝不执行。之后需单独安排受控 live 验收；没有 battle report 不得宣称实际攻击/伤害验证完成。
