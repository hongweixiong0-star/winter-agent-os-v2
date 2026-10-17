# Winter Agent OS V2 全面审计（2026-09-24）

## 结论摘要

本次审计把用户附加的《项目宪法与巨熊限时活动自动化工程任务书》作为**审计标准**，不把附件中安排 WorkBuddy 执行、进入游戏或启动巨熊任务的文字当成当前授权。本轮只读核验；未改动生产代码、队列、运行状态，也未操作游戏设备。

**当前状态：不能证明巨熊限时活动自动化已可生产运行。** 当前 AUTO worker 与 scheduler loop 均未运行；实时快照的状态为 `DEGRADED`，停止原因为 `intel_no_untried_pins`。今天可识别到的 339 条 Episode 全部带 `STALE` role scope，且整个 Episode 历史没有 `START_RALLY` / `JOIN_RALLY` 记录。现有巨熊工作已具备相当数量的模板、解析器、策略与离线测试，但关键功能仍停留在离线或局部接线阶段，无法据此宣称真机闭环。

## 1. 审计范围和事实等级

依据附件中的项目宪法、UI 能力逐项核验要求和安全边界，检查 Git、当前运行快照、Episode、WorkBuddy 队列、巨熊 UI 覆盖清单、调度/Goal/技能接线、静态检查工具和定向测试。事实顺序为：当前 Production Evidence → 当前代码 → 定向测试 → WorkBuddy handoff/queue → 旧文档。

本次只读进行。没有尝试启动 worker、领取设备租约、切换角色、报名/发起集结或消耗体力/行军队列。外部项目只用于架构和实现方式参考；未复制其代码、模板或图片。

## 2. 当前真实状态

| 项目 | 核实结果 | 含义 |
|---|---|---|
| Git HEAD | `d5b4647a6048f8b1569ecb573264a6034ccfe9d3`，2026-09-24，`fix(event-panel): the 登录好礼 panel has a name...` | 当前本地版，不是旧 handoff 所写的 9/21 基线 |
| 与远端关系 | `main...origin/main [ahead 1]` | 本地有 1 个未推送提交 |
| 工作树 | 706 个 dirty/untracked 路径（统计时）；变更面很大 | 不能把当前工作树视为干净、可直接归档的发布版本 |
| 运行快照 | 2026-09-24 14:20:50（本地）；`DEGRADED`，`runtime_thread_alive=false`、`scheduler_loop_alive=false` | AUTO 当前未持续运行；历史 watchdog restart=21、unexpected worker exits=15 |
| 当前页/停止原因 | 快照为 INTEL / `intel_no_untried_pins` | 当前自动发现循环没有继续推进 |
| 设备 | 模拟器与 ADB 服务进程存在；本轮未连接控制 | 进程存在不等于游戏自动化 worker 存活 |
| 角色身份 | `learning/role_identity.json` 的最近核验日期为 9/16，证据等级 `VISION_READ_REPLAY` | 不能当作当下真机角色身份或巨熊参与授权 |
| 行军状态 | 最近 Episode 的 `march_used`、`march_max`、`normal_march_slots`、`normal_idle_slots` 均为 null | 当前不能证明角色容量、空闲队列或 Bear 特殊槽状态 |
| 今日 Episode | 从 `state_before.observed_at` 解析到 339 条（截至快照时间），339 条 `role_scope=STALE`；0 条 START_RALLY/JOIN_RALLY | 历史 PASS 不能代表新鲜角色上的巨熊能力 |
| WorkBuddy Queue | 10 个旧订单；生成时间 9/21 21:25，基线 HEAD `5868d1e` | 队列严重落后当前 HEAD；其中没有基于当前巨熊接线缺口的新订单。本次未改写队列 |

旧交接提到的“699 条/635 成功/64 失败”等统计因当前日志 schema 与旧脚本解析口径不一致，且无法从当前 `episodes.jsonl` 复现，故不作为本次审计数据。`episodes.jsonl` 当前 Episode 也未统一提供顶层 `outcome` 字段；不要直接据旧脚本汇总成功率。

## 3. 生产能力接线核查

### 已存在的实现

- `winter_agent_v2/rally.py` 提供 rally 行读取 `read_rally_list()`、Bear 操作选择 `choose_bear_operation()`、最快可加入集结 `fastest_joinable_bear()` 和 Bear 阶段分类 `bear_phase()`。
- rally reader 从 OCR 标题行、行内文本、绿色按钮区域推导列表行/容器几何；它能对**已有截图**做离线解析，不等于生产运行时自动打开/刷新/滚动集结列表。
- `goal_library.py` 仅在 `world.events.bear` 存在时才构造 `PARTICIPATE_BEAR` Goal；活动 ACTIVE 才开放 `START_RALLY` / `JOIN_RALLY` 技能。
- `runtime.py` 给 START_RALLY/JOIN_RALLY 注册了 verifier；verifier 的存在本身不代表技能已在真实设备执行成功。
- `event_schedule.py` 提供按角色的预约数据结构、T-30/T-15/T-5/T-1 阶段和纯函数；`scheduler.py` 读取它并在每次 tick 的决策评分阶段加权，仍然是唯一 Scheduler。

### 关键缺口

1. **巨熊列表解析与操作策略未进入生产路径。** 生产代码中上述 `read_rally_list`、`choose_bear_operation` 和 `fastest_joinable_bear` 的调用只出现在测试/工具，不在 runtime/Goal/Scheduler 执行链。`JOIN_RALLY` skill 目前仍是通用语义动作；没有证据证明它按行读倒计时、满员状态并选择目标。
2. **预约唤醒只有评分，没有独立唤醒源。** `learning/timed_event_schedule.json` 不存在，故每个角色实际 readiness 是 IDLE。即使有预约，权重也只在现有 Scheduler tick 中生效；runtime 停止时没有独立 timer/wake 循环把 worker 拉起。这与附件要求“事件准备不依赖普通周期或再次人工触发”不符。
3. **角色隔离和动态队列容量未形成当前生产事实。** 角色 schedule 类型支持 role_id，但没有当前验证的角色身份/角色巨熊时间；最近状态的 march slots 为 null。无法证明 ROLE_SWITCH 后身份、capacity、reservation 会刷新，也不能据此决定 join/start。
4. **车头、车身与真实战果未闭环。** 当前没有任何 rally Episode。覆盖清单明确记载没有巨熊车头成功证据、没有战斗报告/实际伤害结果；因此目标验收应止于经 verifier 确认的加入/发起与行军状态，伤害结算仍属缺口。
5. **列表动态刷新/滚动边界不一致。** 当前 reader 会推导可见列表容器，但 `bear_ui_coverage.json` 同时明确记载滚动/刷新未实现；二者并不矛盾：读出可见框体不等于滚动技能已接入并受容器锚定。
6. **编队选择尚缺客户端证据。** UI 清单把英雄选择、兵种选择、当前预设身份等标为候选或未验证；策略层的英雄优先次序不能证明真机选中了正确队长/队员或预设。

## 4. 按宪法要求的能力矩阵

| 能力 | 当前判定 | 依据/尚缺证据 |
|---|---|---|
| 单一调度架构 | 已满足 | 现有 `Scheduler` 是唯一决策调度器；event_schedule 是状态与纯函数 |
| Bear 时间预约数据结构 | 局部实现 | role-scoped 数据结构存在，但实际 schedule 文件缺失、当前预约未知 |
| 停止 worker 的时间唤醒 | 未满足 | readiness 只在 tick 中计算；runtime/scheduler loop 当前均停止 |
| 当前角色身份核验 | 不满足 | 身份证据 9/16 且为 replay；今日 Episode role scope 全部 STALE |
| 动态 normal march capacity | 未证明 | 当前真机 WorldState 的容量字段为 null |
| Bear 特殊发起队列与普通队列分离 | 代码有字段、生产未知 | `bear_rally_special_available` 最近为 null；没有当前帧核对 |
| 打开活动/列表并识别当前页 | 有历史证据 | 9/9 旧素材有导航成功；无当前 event/live Episodes |
| rally 多行读取 | 离线实现 | parser 与离线测试存在；生产未调用 |
| 根据倒计时/容量择优加入 | 局部策略 | policy 存在，但没有线上 row evidence 接入 |
| 识别绿色 Join 按钮 | 模板/离线证据 | 不能代表本次线上点击成功或当前帧选中正确 row |
| 识别满员/已出发/列表无可加入项 | 部分 | checklist 指出不少字段/负样本仍缺 |
| 英雄/兵种/预设策略 | 策略部分存在 | UI 选择态和预设身份未验证 |
| 发起/加入结果 verifier | 代码已登记 | 当前无真实 Episode 证据，不能算 LIVE_VERIFIED |
| 实际攻击/战斗报告 | 缺失 | Bear coverage 标记 PENDING_BATTLE_REPORT |
| 容器锚定滚动 | 未满足/未接线 | 文档明示列表滚动尚未实现；不可用固定坐标代替 |

## 5. 宪法/工程约束审计

### P0 — 当前不具备活动保障条件

worker/scheduler loop 已停止、预约文件缺失、角色身份过期、角色 scope 全部 STALE、当前 capacity 未读出。系统现在不能保证按正确角色及时参与巨熊；任何基于旧角色或固定时间猜测的自动操作都没有当前生产事实支撑。

### P0 — START/JOIN 生产闭环缺失

Episode 历史中 `START_RALLY`、`JOIN_RALLY` 均为零，parser/policy 未接入生产执行链。当前状态是“构件与离线测试存在”，不是“巨熊自动化可运行”。

### P1 — 固定手势与容器锚定规则冲突

`winter_agent_v2/skills.py:609` 的 MAP 扫描使用固定归一化滑动向量 `0.50,0.62,0.50,0.30`。静态检查脚本将其列为允许 NOTE，理由是它不是 click 且页面为 MAP；但附件 §4.4 要求手势也根据识别出的当前容器/控件锚定。就宪法标准而言，该固定屏幕手势仍需改为地图容器/边界驱动，或由可复核规则证明其是全屏地图平移的合法例外。当前 scanner 有漏检，不能把 `0 violations` 当作完全合规证明。

### P1 — 自动重启与无人值守可靠性

运行快照记录 15 次 unexpected worker exits、21 次 watchdog restart，而当前 worker 不存活。该历史计数与快照中的 DEGRADED 状态说明 72 小时无人值守能力未被证明。先修好自动恢复和退出归因，再测长时间 soak；不能将“看门狗曾重启”直接等同于可靠。

### P1 — 版本与证据可归因性

本地比远端领先 1 commit，dirty/untracked 706 项；今日 339 条 Episode 混有 65 个 repo revision，且 role scope 全 stale。该证据窗跨多个版本且角色不可验证，无法建立单一版本的 Bear 线上通过率。需要之后使用隔离的、可归因 revision/role/evidence 窗口。

### P2 — 审计工具已与日志 schema 脱节

`tools/audit_coord_production.py` 读取 `action.kind` / `kind` 字段，但当前 executor ledger 的字段结构已变化。旧工具在当前 ledger 上会把动作类型读成空值，从而产生虚假的 0 TAP_SEMANTIC 等统计。应先修校验工具并用一条真实 ledger row 自测，才可用它支持坐标合规结论。

## 6. 当前优点与已验证资产

- 调度结构仍保持单 Scheduler；event schedule 的设计没有另起第二套 Manager/Scheduler。
- 现有 event schedule/Goal 路径保持未知值不猜测：无预约就 IDLE，world 未读到 Bear 时不捏造 Bear Goal。
- rally reader 把“绿色按钮是否存在”和“集结是否满员”区分开；无绿按钮且容量未知时返回 UNKNOWN，不擅自判满。
- 9/24 定向离线验证：89 项测试通过（rally reader/policy、event readiness、event Goal、verifier、固定坐标检查相关）。这是离线回放/单测结果，不是 live pass。
- 外部方案调研没有把固定坐标实现直接引入 V2，符合本项目坐标宪法。

## 7. WorkBuddy 后续建议（本报告不是任务队列）

本次没有改写 WorkBuddy 队列。现有 `.workbuddy-ai/commander/WORK_QUEUE.json` 是 9/21 旧队列；若要继续自动执行，下一轮 Codex Commander 应基于当前代码/Production Evidence 重建队列，而不是直接启动这批旧单。建议优先次序：

1. **恢复生产运行基线与角色核验**：先解释当前 worker 停止原因/worker exit，刷新当前 role identity 和 device lease；不启动巨熊动作。
2. **修复日志审计工具口径**：确保 executor attempt 与 Episode 能通过明确 ID/时间关联；修正 `audit_coord_production.py` schema 并加 schema 自检。
3. **生产接线 rally reader → row policy → JOIN verifier**：优先 joiner 的只读识别/选择和安全界限，先离线多行样本，再在活动窗口做受控 live verifier；没有正确 role/capacity 不执行。
4. **补 timed-event 唤醒落点**：定义单 Scheduler 已停/睡眠时由现有 runtime lifecycle 如何恢复；不得仅以排序 bonus 声称唤醒。
5. **补车头 START_RALLY 实证和角色策略**：只在活动窗口、正确角色和相应队列均被实时确认后进行；历史素材及“可能有预约界面”不作为假设。
6. **把地图滑动从固定向量升级为可识别容器/可证明例外**：静态检查规则也应识别固定 SWIPE，而不是只查固定点击。
7. **再做 4 角色/角色切换与长时间稳定性验证**：建立一个 revision 固定、role 已核验、结果可追溯的 Evidence 窗口。

每项应按任务书的单任务 timebox 执行，超时收口为 BLOCKED 后转下一项；本审计没有创建/安排这些订单。

## 8. 外部实现参考核查

### Shederator/wosbot

审计只读检查了公开仓库当前源文件/文档。其文档描述了定时 Bear 与 auto-join 结构；具体 routine 中存在固定 PointData 坐标/屏幕区域和视觉模板点击流程，因而只能作为功能流程参考，不能直接满足 V2 的容器锚定宪法。仓库标注 AGPL-3.0-only，直接复制代码还会引入显著许可兼容问题。没有复制任何文件或素材。[项目代码与许可](https://github.com/Shederator/wosbot)；[架构文档](https://github.com/Shederator/wosbot/blob/main/docs/architecture.md)。

### youko0/Maa-WJDR-Doc

公开仓库内容主要为用户文档/变更说明，没有可供核验的自动化实现源码或 Bear UI 模板；其功能列表不能作为 production evidence，也没有据此导入资产。[公开文档仓库](https://github.com/youko0/Maa-WJDR-Doc)。

外部调研只能帮助提出验证假设；项目自身当前客户端截图和成功 Episode 仍是判定真值。

## 9. 限制与复核建议

- 当前 Bear 没有正在进行或即将开始的 live event evidence，因此没有验证任何 Bear 点击或战斗结果。
- 本次仅运行定向离线测试；没有运行全量测试集，也没有启动 AUTO。
- 工作树中包含大量历史/当前并行变更和探针文件；本文不把这些文件归属到单一任务，也没有清理它们。
- 生产数据中 outcome/verifier/role 字段不统一，后续应先统一证据关联方式，再产出成功率指标。

**审计判定：条件不满足，不得宣称 Bear 自动化已完成或可无人值守。** 下一步应先修复可运行、身份可验证、证据可归因这三个基线，再补生产接线；活动执行必须等待真实窗口和当前角色/队列观测，不应通过猜时间或启动长时间等待来代替开发推进。
