# Winter Agent OS V2 修复改进计划（2026-09-24）

## 目标与边界

本计划依据 2026-09-24 全面审计和《项目宪法与巨熊限时活动自动化工程任务书》编制。附件作为验收标准；本轮用户请求是制定修复计划，因此 WorkBuddy 任务限定为核实、代码修复、离线回放和运行安全基线，不包含真实巨熊发车/上车、消耗体力、改角色或其他游戏内操作。真机 Bear 闭环需另行在真实活动窗口安排。

计划已拆成 10 个 Work Orders，合计 720 分钟（12 小时）。任务逐单执行；遇到超时或自然状态/活动不可用时，记录 BLOCKED 并转下一单，不等待活动或人为制造测试状态。

## 当前基线

- HEAD：`789271789ae0b691d97435b26fe64861b3719595`；本地 `main` 相对 `origin/main` 的关系由 WorkBuddy 首单重新核对。
- 工作树：最近核验有 711 个 dirty/untracked 路径。不可清理、覆盖或归属他人的现存改动。
- `learning/runtime_snapshot.json` 2026-09-24 17:35:49 更新：`agent_state=IDLE`，worker/scheduler loop 均未运行，页为 EXPLORATION，原因 `exploration_income_not_ready`；`march_used`、`march_max` 为 null。
- Commander 队列和执行态不同步：旧队列生成于 9/21、旧基线 `5868d1e`；`EXECUTION_STATE` 将 `WB-0921-01` 标为 IN_PROGRESS（9/21 开始），但无近期结果。首单必须先对账该任务和共享工作树，再决定保留、接续或标记过期；Codex 不代写 WorkBuddy 的执行态。
- 9/24 巨熊审计的稳定结论：Episode 中没有 `START_RALLY` / `JOIN_RALLY`；rally reader/policy 有离线实现但未接入生产链；事件预约文件缺失；最新 march capacity 未知；停止状态下只有 Scheduler readiness 排序加权，不能单独唤醒 worker。
- 报告中的 89 项离线测试通过，不作为 live 验收；当前不安排全量 pytest 或 Bear 真机操作。

## 分阶段修复路径

| 阶段 | 任务 | 目标 | 验收门槛 |
|---|---|---|---|
| A. 收敛基线 | 01–03 | 认领正确 revision/工作归属；解释为何运行循环退出；修正日志分析器，建立可靠前后指标 | 不覆盖现存改动；运行状态/退出原因有来源；ledger 与 Episode schema 有可验证关联 |
| B. 宪法与调度 | 04–05 | 消除固定滑动手势漏检；让已有单 Scheduler 在预约临近时通过 runtime 生命周期获得唤醒机会 | 所有生产手势有可审计锚点/明确例外；无第二套 Scheduler；无预约仍保持 IDLE、不猜时间 |
| C. 角色与队列 | 06 | 将角色身份、新鲜度、Capacity/Occupancy/Reservation 分离并在角色变化时失效旧观测 | 未知容量保持 UNKNOWN；切换后不继承前角色；不硬编码队伍数或固定保留队数 |
| D. 巨熊链路 | 07–09 | 将已有 reader/policy 接到现有 Goal/Skill/Verifier；补 joiner/leader 的回放与边界 | 点击不算成功；必须有状态变化 verifier；活动不可用时只完成离线准备，不制造状态 |
| E. 稳定性收尾 | 10 | 检查回归、覆盖矩阵、版本和证据可归因性，交接剩余 live blocker | 只对真实完成项宣告完成，尚无真机证据则状态保持待验证 |

## 执行顺序和任务边界

1. **当前状态与旧在途单对账**（60 分钟，P0）：读取旧单结果、共享工作树、HEAD 和实际进程；不抢设备、不重置 WorkBuddy 执行态。
2. **Worker 生命周期/停止原因归因**（90 分钟，P0）：解释 IDLE/循环停止的状态写入路径；修复可复现的生命周期缺陷，历史 `unexpected_worker_exits` 不改写。不启动 AUTO 点击流程。
3. **Episode/Executor 证据关联与审计工具修复**（60 分钟，P0）：读取当前 ledger schema，修正 `audit_coord_production.py` 等陈旧字段解析，加入输入 schema 检查；不篡改历史 Episode。
4. **固定 SWIPE 宪法检查**（60 分钟，P1）：检查 `skills.py` 固定地图滑动向量，改为可识别容器锚定，或给出基于当前 UI 语义的明确例外；静态检查必须能捕捉固定 gesture。
5. **Timed-event readiness 生命周期接线**（90 分钟，P0）：沿用现有 `event_schedule` 与 Scheduler，明确进程运行/空闲/停止时的触发路径；缺少可信预约时不唤醒、不猜测时间、不新增 Scheduler。
6. **Role-scoped March State**（90 分钟，P0）：核对现有 WorldState/Knowledge/Reservation 实现，将 capacity、occupancy、reservation 独立表示并定义过期/角色切换失效规则；测试 2 队/6 队历史夹具但不将数字写成常量。
7. **Rally list reader 生产接线（先回放）**（90 分钟，P0）：把当前 OCR row reader、行选择策略和通用 JOIN_RALLY 计划接入现有链路；以固定离线样本验证多行/满员/未知/滚动边界；不得凭旧固定坐标点击。
8. **Joiner verifier 与失败分支**（60 分钟，P0）：验证成功加入、按钮失效/满员、容量未知、角色不符；失败必须安全退出或返回观察，不能只按按钮记成功。没有实时活动时 live 阶段标 BLOCKED。
9. **Leader START_RALLY / 编队就绪路径**（90 分钟，P1）：复用现有技能/模板/队列模型，补 leader 入口、特殊发起槽与编队身份的离线覆盖；不假设预约 UI 存在，不操作真实队列。
10. **回归矩阵与交接**（30 分钟，P1）：运行任务相关测试/回放，汇总改动、revision、结果/阻塞项；确认无第二 Scheduler、无新固定队伍数、无历史证据篡改。

## 停止条件

- 任意现存文件/任务所有权不清：先记录冲突并停止相关编辑；不可重置/清理。
- 无设备租约或当前真实角色无法确认：禁止设备控制、角色切换和任何资源/行军操作。
- Bear 活动窗口未开放：只做离线验证；不等待数小时，不模拟线上成功。
- 一个 UI 假设 15 分钟没有新证据：转工具/数据检查；到达任务 timebox 且无根因或可复现修复时标 BLOCKED 并继续下一项。
- 任何 verifier 只证明动作发出而未证明目标状态变化：不接受为能力完成。

## 本轮结束后仍需独立排期的生产验证

只有在真实 Bear 活动窗口、当前角色身份被新鲜验证、设备租约归属明确、普通/特殊行军状态可观测后，才安排受控 `joiner → VERIFY_JOINED → 持续观察` 和 `leader → VERIFY_RALLY_CREATED`。实际战斗报告/伤害归因、多个角色在真实窗口的参与覆盖，以及 72 小时 unattended soak 均不包含在这 12 小时离线改进批次中；没有证据前均保持未完成。
