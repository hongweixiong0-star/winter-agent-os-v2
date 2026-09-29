# Last Codex Review
日期：2026-09-24。全面审计后生成修复计划与 WorkBuddy queue；本轮未修改生产源代码、未运行游戏操作。

## 最新基线
- HEAD：`789271789ae0b691d97435b26fe64861b3719595`。队列生成前核验工作树 711 个 dirty/untracked 路径。
- `learning/runtime_snapshot.json` 17:35:49：`IDLE`，runtime_thread_alive=false，scheduler_loop_alive=false，当前页 EXPLORATION，停止原因为 `exploration_income_not_ready`；march capacity 未知。
- Commander 旧队列生成于 9/21，HEAD 5868d1e；`EXECUTION_STATE` 将 WB-0921-01 标记 IN_PROGRESS（9/21 起）但没有近期结果。旧 queue 已原样归档；新队列首单只读对账并要求 WorkBuddy保留现存 diff。
- 上次审计解析到今日 Episode 中 role_scope 均为 STALE，未发现 START_RALLY/JOIN_RALLY Episode；rally reader/policy 有离线实现但未接入生产链。旧 699/635/64 汇总不可信，不再引用。
- `event_schedule`/Scheduler 已有 readiness 评分，但 schedule file 缺失，停止的 runtime 不会因此独立唤醒。当前角色/容量不具备实时可信证据。

## Codex Decision
优先顺序：任务所有权与运行生命周期 → ledger/Episode 审计器 → 固定 gesture 合规 → 单 Scheduler timed readiness lifecycle → role-scoped dynamic march capacity → JOIN_RALLY reader/policy/verifier → leader START_RALLY/编队 → 回归交接。保持单一架构，未知不猜测。

附件任务书作为验收标准；用户本轮请求为修复计划，因此这批 Work Orders 只授权代码与离线准备，不授权真实 Bear join/start、角色切换、设备操作或资源消耗。计划共 10 项、720 分钟；活动窗口验证单独安排。

## 新工作队列
- `.workbuddy-ai/commander/WORK_QUEUE.json`：WB-0924-01 至 WB-0924-10，状态 READY，总 timebox 720 分钟。
- 旧队列保存在 `.workbuddy-ai/commander/archive/WORK_QUEUE_20260921_superseded_20260924.json`；旧结果与 WorkBuddy 执行状态由 WorkBuddy 首单对账，不由 Codex伪造结案。
- 详细阶段计划：`docs/audits/V2_REPAIR_IMPROVEMENT_PLAN_2026-09-24.md`。

## Review Later
真实活动窗口中当前角色核验、Joiner/Leader verifier、battle report、不同角色 capacity 隔离的 live 证据，以及长时 unattended soak。不得将离线通过提升为 LIVE_VERIFIED。
