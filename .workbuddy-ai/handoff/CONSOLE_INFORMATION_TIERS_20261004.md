# 控制台逐页审计与信息分层（2026-10-04）

操作者要求两层审计：**第一层查 bug**（页面 → 数据源 → 新鲜度 → 归类），
**第二层审设计**（使用者视角：充分 / 诚实 / 可操作 / 冗余）。然后按
L1 常驻 / L2 按需 / L3 默认折叠 归位，异常自动浮到 L1。

本文所有数字都是**当场实测**的（2026-10-04 15:0x），不是读代码猜的。

---

## 一、页面清单（实测：7 个，不是 12 个）

`TAB_GROUP` 声明了 12 个页签；`_build()` 只调用 7 个页面构建方法。
逐方法可达性用 AST 从 `_build` 做闭包，结果是 **7 可达 / 13 个含 `self._tab()` 的方法**：

| 页签 | 构建方法 | 可达 | 主要数据源 |
|---|---|---|---|
| 总览 | `_overview` (4699) | ✔ | runtime_snapshot / episodes / executor_backend / capability_catalog / workbuddy_escalations |
| 运行·目标 | `_goals` (4944) | ✔ | `learning/goal_state.json` |
| 运行·策略 | `_strategy` (4874) | ✔ | `config/policy_state.json` |
| 运行·活动 | `_event_goal` (5095) | ✔ | `learning/event_goal_state.json` + `fishing_state.json` / `fishing_runs.jsonl` |
| 能力 | `_capabilities` (5431) | ✔ | `knowledge/game/capability_catalog.json` + v2_registry + episodes |
| 自动开发 | `_auto_development` (5577) | ✔ | workbuddy_escalations / workbuddy_model_stats / capability_skill_map |
| 系统 | `_system` (5784) | ✔ | runtime_snapshot / global_scheduler_state / role_inventory / task_completion_matrix |

**★不可达（6 个，代码在、页签不在）**：
`_tasks`(4861)、`_coverage`(5306)、`_skills`(5555)、`_knowledge`(5565)、`_logs`(6406)、`_settings`(6413)。

这是**有意退休**的，`tests/test_control_panel.py:369` 已有一条守卫
`test_command_center_has_exactly_seven_primary_tabs` 断言 `_build` 里不出现它们。
但那条守卫有两个缺口（见 §四 R3）：
1. **手写名单漏了 `_skills`** —— 它同样不可达，同样建页签（第二个"能力"），却不在名单里。
2. 它只断言"没被调用"，**没有任何东西断言 `TAB_GROUP` 声明的 12 个名字与实际存在的 7 个一致**。
   所以标签表可以永久撒谎。

---

## 二、数据源与新鲜度（实测 28 个源）

不是"有没有在更新"，而是**每个源的最后写入时间**：

### 新鲜（< 5 分钟，AUTO 正在跑）
`runtime_snapshot.json` · `episodes.jsonl` · `goal_state.json` · `global_scheduler_state.json`
· `task_completion_matrix.json` · `executor_backend.jsonl` · `auto_uptime.jsonl`
· `workbuddy_escalations.jsonl` · `role_identity.json` · `config/control_panel_state.json`
· `learning/control_panel/`

### 过期（按各自应有的节奏判断）
| 数据源 | 年龄 | 谁在显示它 |
|---|---|---|
| `learning/goal_coverage.json` | **24.9 天** | 无（消费它的页面已退休） |
| `knowledge/ui/icons/manifest.json` | **29.0 天** | 无（消费它的页面已退休） |
| `knowledge/game/capability_catalog.json` | **7.6 天** | 总览 8 个 KPI 卡 · 能力页两张表 · `state_truth` 的 coverage |
| `knowledge/roles/role_inventory.json` | 5.6 天 | 系统页 · 角色仲裁 |
| `knowledge/ui/semantic_dictionary.json` | 4.6 天 | `count_knowledge`（页面已退休） |
| `learning/fishing_runs.jsonl` | 4.0 天 | 活动页 · 钓鱼 |
| `learning/workbuddy_model_stats.jsonl` | 2.7 天 | 自动开发页 · 模型战绩 |
| `learning/fishing_state.json` | 2.6 天 | 活动页 · 钓鱼 |
| `dataset/candidate/template_manifest.json` | 2.3 天 | `count_knowledge`（已退休） |
| `knowledge/goals/capability_skill_map.json` | 1.8 天 | 自动开发页 · Goal 覆盖 |
| `config/v2.json` | 15.7 小时 | 设备/包名配置（长期不变，正常） |

### 结论（这是本次最重要的发现）
**除了活动低保那一条，控制台没有任何一格显示过它数字的来源年龄。**

实测证据：全文件里搜"年龄/过期"词汇，只有 `_refresh_event_goal_display`（活动页）
与 `_refresh_truth`（角色/活动状态）出现；`STALE` 只出现在 `gateway_cell` / `workbuddy_header`。
28 个源里 **27 个的年龄是隐形的** —— 一个 25 天前的覆盖率和 5 秒前的运行快照长得一模一样。

这正是上一个提交只修了一个页面的那条规则，**没有升级成机制**。

---

## 三、第一层 bug 归类

### A. 数据过期（源停了，界面照旧显示）
- `capability_catalog.json` 7.6 天，喂给总览 8 个 KPI 卡 + 能力页两张表 + coverage。**没有任何年龄标注。**
- `capability_skill_map.json` 1.8 天 → 自动开发页"Goal 覆盖"。
- `workbuddy_model_stats.jsonl` 2.7 天 → 自动开发页"模型战绩"。
- `fishing_state.json` / `fishing_runs.jsonl` 2.6 / 4.0 天 → 活动页钓鱼。
- `role_inventory.json` 5.6 天 → 系统页角色仲裁。

### B. 未接上（有显示、无写入方）
- 活动页 **`estimated_cost` / `estimated_completion`**：活动记录 14 个键里**没有**这两个，
  全树也没有任何写入方（`goal_library.py:1443` 读的是另一处的 goal spec）。
  界面上永远显示"待计算"—— 两个格子永远填不上。
- `learning/goal_coverage.json`：读它的 `_refresh_coverage()` 每轮都被调用，
  但它要的 `coverage_tree` 只存在于已退休的 `_coverage()` 里，
  所以函数**第一行就 return** —— 数据管线是死的，文件停在 25 天前。

### C. 逻辑错（一个字段被两个不同问题的写入方共写）
- **`RuntimeSnapshot.confidence` 的属主会变**。实测 4 个写入点：
  `runtime.py:9018 confidence=before.confidence`（**整帧识别**）、
  `:10392 confidence=after.confidence`（**整帧识别**）、
  `:9070 / :9385 confidence=decision.confidence`（**决策**）。
  而面板把它印在总览"当前决策"列里，标签就叫"置信度"。
  同一格在相邻周期里可能是两个不同问题的答案 —— **与上一个提交修的"99%"完全同族**。
  界面上还有第二处同病：`values["confidence"]` 同时被 `_apply_world`（帧）与
  `_refresh_runtime_snapshot`（快照）写。
- `RuntimeSnapshot.confidence` 字段本身**没有一句注释说明它是谁的置信度**。

### D. 显示层问题
- `TAB_GROUP` 声明 12 个页签，实际 7 个（声明 ≠ 存在）。
- 目标页 10 列里的"置信度"列，33+ 行**全部是"未计算"** —— 一列没有任何信息。
- 6 个已退休页面构建器 + `_refresh_coverage` 仍在源码里（≈90 行），
  其中 `_refresh_coverage` 每 1.5 秒被执行一次并立即返回。
- 同一个值重复出现在两页：`wb_state`/`wb_gateway`/`wb_result` 在总览与自动开发页各一份；
  WorkBuddy 的 8 个格子在两页都画了一遍。

### E. 状态机卡住
- 无新增。`KEEP_BUILDING_PRODUCTIVE` 的"READY 却被 gate 延期"已在上一提交把原因接到界面上。

---

## 四、共享根因（不是逐个页面打补丁）

| # | 根因 | 影响面 |
|---|---|---|
| **R1** | **一个派生数字旁边没有它来源的年龄与过期裁决。** 规则只写在活动页一个函数里，没有机制 | 27/28 个源 |
| **R2** | **一个字段被语义不同的写入方共写，且字段没有属主声明** | `RuntimeSnapshot.confidence` + `values["confidence"]` |
| **R3** | **界面"声明"与"存在"没有一致性检查**：`TAB_GROUP` 可以列 12 个而只建 7 个；退休守卫靠手写名单，漏了 `_skills` | 页签体系 + 退休守卫 |
| **R4** | **"永远填不上"的格子照常占位**：没有任何检查问"这个字段有没有写入方" | 活动页 2 格 + 目标页 1 列 |

---

## 五、第二层：使用者视角（A 充分 / B 诚实 / C 可操作 / D 冗余）

### A. 信息是否充分 —— **过度充分，反而答不上来**
总览一页有 **12 个信息块**：角色卡 + 今日 Goal 摘要 7 行 + 游戏画面 + 当前决策 9 行 +
KPI 8 卡 + WorkBuddy 8 格 + 队列 7 卡 + 4 个事实卡 + 2 个下排卡 + 进度行 + 控制条 + 最近事件。
操作者要回答的 5 个问题里：
- ✅ 系统现在在干什么 —— 有（当前 Goal / Skill / 页面）
- ✅ 为什么是这个 —— 有（为什么执行 / Preconditions）
- ✅ 下一步 —— 有
- ⚠️ **有没有卡住** —— 有 `why_idle`，但它和 7 个 KPI 卡、8 个 WorkBuddy 格**平权**排在一起
- ❌ **需要我干预吗** —— **没有这一格**。只有 `attention`（P0 告警）和 `mode`，两者相隔很远

### B. 信息是否诚实
- ❌ 过期冒充新鲜：见 §三 A（27 个源无年龄）
- ❌ 假数字：`confidence` 属主漂移（§三 C）
- ⚠️ `—` 掩盖未知：能力页 `blocked`/`rate` 用 `—`（可接受，同列有上下文），
  但目标页"阻塞原因"用 `—` 表示"状态 UNKNOWN 且无 gate 行"，与"没有被拦"同形（上一提交已区分 READY/DISCOVERED）
- ✅ 角色/活动状态已是诚实格式（`上次已知` + 年龄 + 来源）

### C. 信息是否可操作
- ❌ 看到红灯之后的入口：总览"需要关注"只给**一句话**，不给"去哪里、按什么"。
  系统页有"打开日志/截图/Evidence"按钮，但那是**另一个页签**。
- ✅ 有"为什么"（`reason` 行）
- ⚠️ 下一步有，但它是**系统**的下一步，不是**操作者**的下一步

### D. 冗余 / 缺失
- 冗余：目标页置信度列（永远"未计算"）；活动页 2 格（永远"待计算"）；
  WorkBuddy 8 格重复两处；总览 7 个队列卡与系统页 8 个看门狗格长期不变；
  能力页 `runtime_quality` 4 格（健康时的资源计数）
- 缺失：**"需不需要干预"**（唯一缺失的 L1 项）；**任一数字的来源年龄**；
  **"花钱/不可逆操作正在进行"**（策略页有规则，但运行时没有一格显示"此刻有没有在花"）

---

## 六、L1 / L2 / L3 归位（逐字段，含理由）

判定三问：**看到它会不会改变行为？看不到会不会做错决策？它是不是一直不变？**
三条全中 → L3 折叠。

### 顶栏 9 格 → 6 常驻 + 3 折叠
（本行原写「4 常驻 + 3 折叠」，与下表逐格判据不符：下表把 V2/MAA/MuMu/游戏、AUTO、时间
六格都判成 L1，4+3 只等于 7，漏了两格。以逐格判据为准 —— **数字写在散文里会漂，判据不会**。）
| 格 | 层 | 理由 |
|---|---|---|
| V2 / MAA / MuMu / 游戏 | **L1** | 用户点名"系统当前状态（正常/异常/降级）"必须常驻；它们是物理底座 |
| AUTO | **L1** | "有没有在跑"是决策前提 |
| 时间 | **L1** | 它是所有"最近 N 分钟"读数的换算基准，缺了别的数无法解释 |
| WorkBuddy | **L3 → 异常浮 L1** | 内部开发平台；健康时用户不据此决策，且长期不变 |
| 本地模型 | **L3 → 异常浮 L1** | 同上（可替换算力） |
| 预载 | **L3 → 异常浮 L1** | 同上 |

### 总览
| 块 | 层 | 理由 |
|---|---|---|
| 当前状态 + 模式 + 控制按钮 | **L1** | 干什么 / 能不能动 |
| **新增：需不需要干预** | **L1（当前缺失）** | 唯一缺的 L1 项 |
| 现在为什么不动（`why_idle`） | **L1** | "有没有卡住" |
| 需要关注（`attention`） | **L1** | 异常必须常驻 |
| 当前 Goal / Skill / 页面 | **L1** | "现在在干什么" |
| 为什么执行 / 下一步 / 风险 | **L2** | 想深究才看 |
| Preconditions / Verifier | **L2** | 执行细节 |
| 决策置信度 | **L2** | 需要时看 |
| 游戏实时画面 | **L2 → 卡住时 L1** | 原始证据，占位最大；异常时是唯一能看懂的 |
| 今日 Goal 摘要 7 行 | **L2** | 与"目标"页重复 |
| 队列 7 卡 | **L2** | 长期不变；积压时浮 L1 |
| KPI 8 卡（catalog 派生） | **L3** | 长期不变的资源计数，且源自 7.6 天前文件 |
| WorkBuddy 8 格 + 最近结果 | **L3** | 内部平台细节；与自动开发页重复；异常/有任务时浮 L1 |
| 执行器/预载/覆盖 事实卡 | **L2** | 想深究才看 |
| 看门狗与版本 | **L3** | 内部；异常浮 L1 |
| 本次启动统计（`stats`） | **L3** | 会话级计数，用户不据此决策 |
| 最近事件 3 行 | **L3** | 日志摘要 |
| 进度行（动作成功 vs 目标进展） | **L1** | "有没有真的在推进" —— 操作者自己的区分 |

### 目标页（10 列）
| 列 | 层 | 理由 |
|---|---|---|
| 目标 / 状态 / 阻塞原因 | **L1** | 卡在哪 |
| 优先级 / 剩余 | **L1** | 限时性决定是否干预 |
| 进度/目标 | **L2** | |
| 下一动作 | **L2** | |
| 类别 | **L3** | 一直不变（由 goal_id 推导） |
| 贡献能力（skills） | **L3** | 内部实现 |
| **置信度** | **删除** | 永远"未计算"，零信息 |

### 活动页
| 字段 | 层 | 理由 |
|---|---|---|
| name / current / target / missing / remaining / status / rewards | **L1** | 限时活动是用户主动关注的对象 |
| plan | **L2** | |
| tier / phase | **L2** | |
| source / last_verified | **L1** | 诚实性要求：必须能看出这是哪一次读数 |
| confidence | **L3** | 永远 `—` |
| resource_spent / verified_points_gain | **L2** | |
| **estimated_cost / estimated_completion** | **删除** | 永远"待计算"，无写入方 |
| 钓鱼（bait / next_bait_at / points / pressure） | **L2** | 子玩法，按需 |

### 能力页
| 块 | 层 | 理由 |
|---|---|---|
| 4 个 summary 卡 | **L2** | 覆盖度是"要不要开发"的依据 |
| Capability 覆盖表 | **L2** | |
| Skill 执行注册表 | **L3** | 内部注册表 |
| runtime_quality 4 格 | **L3（异常浮 L1）** | 健康时的资源计数；`unexpected_worker_exits` 非 0 必须浮上来 |

### 自动开发页
| 块 | 层 | 理由 |
|---|---|---|
| 自主开发闭环（loop_card / 断点） | **L1 当有断点**，否则 L3 | "卡在哪一步"是这个页面的存在理由 |
| 队列状态条 + 升级条件分桶 | **L2（积压超阈值浮 L1）** | |
| 队列消费泵 / 设备所有权 | **L2** | 只在异常时可解释"为什么不动" |
| 最近失败分类 | **L2（次数超阈值浮 L1）** | |
| WorkBuddy 状态 8 格 | **L3** | |
| Job 历史 / 模型战绩 | **L3** | |

### 系统页
| 块 | 层 | 理由 |
|---|---|---|
| 当前角色 | **L1** | 一切资源的范围 |
| 最近决策 / 下一唤醒 | **L2** | |
| Runtime Watchdog 8 格 | **L3（异常浮 L1）** | |
| 角色仲裁其余 11 行 | **L3** | |
| 顶部状态的真实依据 6 行 | **L3** | |
| 日志文本框 | **L3** | |
| 打开目录按钮 | **L3** | |

（本表原写「角色仲裁其余 12 行」。实数是 15 行减去 L1 的 2 行、L2 的 2 行 = **11** 行；
与上面顶栏那条同理 —— 散文里的数字会漂，判据不会。落地成代码时这一块直接叫
「角色仲裁 · 单 Scheduler（其余各项）」，标题里不再写会漂的数。）

### 异常浮到 L1 的规则（阈值化，共用一套）
| 触发 | 浮上来的内容 |
|---|---|
| 任一数据源超过 TTL **且** AUTO 在跑 | 该源被哪些格子使用 → 那些格子显示「待重新观测」，并在"需要关注"里点名 |
| `unexpected_worker_exits` > 0 · `watchdog_restart_count` 增长 | 看门狗块浮到 L1 |
| WorkBuddy 网关非正常，或队列有活跃 Job | WorkBuddy 块浮到 L1 |
| 预载/本地模型非正常 | 对应顶栏格与详情行浮到 L1 |
| 目标队列积压（同 `state` ≥ 阈值）或失败次数 ≥ 阈值 | 对应块浮到 L1 |
| 任一"花钱 / 不可逆"操作在进行 | 策略页的 🔒 行 + 资源策略浮到 L1 |
| `attention` 非空 | `attention` 块本身常驻 L1（不折叠） |

**注意**：AUTO 未在运行时，源变旧是**预期**（没有写入者就没有新数据），
不得报成异常 —— 否则就是"狼来了"，那正是 `needs_reload` 自己警告过的失败模式。

---

## 七、修了什么 / 还留着什么（本轮执行记录）

按操作者的顺序：**先归类（§六）→ 报告（本文）→ 不等确认 → 改 UI**。
只修 P0/P1，P2 与 P1 同批（多为加字段），P3 只记录不动。**不逐个页面打补丁，修共享根因。**

### 已修（4 条根因）

| 根因 | 改法 | 落点 |
|---|---|---|
| **R1** 派生数字旁边没有来源年龄 | 新建**唯一**一张表 `winter_agent_v2/source_freshness.py`（26 源，含 TTL 与消费方）。总览四张事实卡的来源行现在自带年龄；「需要关注」会在 AUTO 运行时点名过期源 | `source_freshness.py`（新）+ `_freshness` / `_source_age_note` / `_attention_with_sources` / `OVERVIEW_FACTS` |
| **R2** 一个字段被语义不同的写入方共写 | 拆成两个字段：`confidence`（**决策的**）/ `frame_confidence`（**整帧识别的**），四个写入方各归其位；窗口印成「决策置信度」，识别置信度只出现在画面旁 | `runtime_snapshot.py` + `runtime.py`(9018/10392) + 面板 `confidence_decision` / `confidence_frame` |
| **R3** 声明与存在没有一致性检查 | `TAB_GROUP` 12 → **7**；测试改为**从 `_build` 派生**（AST），断言"死页为零"且"标签集合 == `TAB_GROUP` 键集合"；`check_wiring.py` 那条旧检查改成"新标签在、退休标签不在" | `control_panel.py` + `tests/test_console_shows_only_what_it_can_fill.py` |
| **R4** "永远填不上"的格子照常占位 | 删目标页「置信度」列（33+ 行全"未计算"）与活动页「预计成本」「预计完成」（全仓无写入者）；活动页读的每个记录键现在要么在记录里、要么在 `OPTIONAL_EVENT_KEYS` 里带理由 | `control_panel.py` + 新测试 |

**顺带修掉的 P1（第二层 §五）**：

- **唯一缺失的 L1 项「需不需要干预」**：新增 `intervention_of()` 与总览**第 1 行**的常驻卡片，
  一次回答四件事——**结论 / 原因 / 此刻会不会花钱或不可逆 / 去哪里看**。
  花钱那条读 `config/policy_state.json`（`real_money: PERMANENTLY_BLOCKED` + 7 个禁用 Goal），
  **不是**假设出来的零。审计不可用时它说"未知（审计不可用）"而**不会**留下"不需要"。
- **红灯之后的入口**：卡片末行直接指路（策略页「运行方式」有截图/证据/日志入口 + 顶部 AUTO 指示器）。
- **6 个已退休页面构建器 + `_refresh_coverage` + 5 个标签名**：删除（不是打补丁）。
  `count_knowledge()` 也删。**删的是"声明"，不是"数据"**：`goal_coverage.json` 留在盘上，
  并在新鲜度表里登记为 `RETIRED`，所以它的年龄**有解释**。
- **`self.continuous` 的唯一控件**从"永不构建的 `_settings` 页"移到策略页「运行方式」卡
  （它被 4 处代码读取并持久化，操作者却改不到）。
- `self.resource_policy`（5 个 StringVar，无人读）与 `task_enabled`/`LIVE_PANEL_TASKS` 的接线一起清理。

### 还留着（已登记，本轮不动）

- **P3 冗余**：WorkBuddy 8 格在总览与自动开发页各一份；目标页 7 行摘要与目标页重复；
  7 个队列卡 / 8 个看门狗格长期不变。**归 L3，折叠是下一步 UI 工作**（已在 §十 落地），
  本轮不删，因为折叠与删除是两件事（删了就没法展开）。
- **两个新发现的独立缺陷**（都不是本轮引入）：
  1. **控制面重载标记不会退休（已修）**：`learning/CONTROL_PLANE_RELOAD_REQUIRED.json`
     只有一个写入端（`control_panel.py` 的 `stale` 分支），活代码里**没有任何调用者把它删掉** ——
     重启后它仍写着"本窗口加载的代码已被取代"，而进程已经在跑新代码。
     改法：在 `not stale` 那一支调 `control_plane_signal().clear("superseded_claim_resolved")`
     —— **动词早就有**（`ReloadSignal.clear(reason="consumed")`，worker 那条链一直在用），
     缺的是**调用者**。`tests/test_control_plane_reload.py` 用一条**驱动式**测试锁住：
     不 stale 时标记消失、stale 时标记留存。
     **不用手工删除掩盖**（见 MEMORY §48，包括我在这一条上先犯的假阴性错误）。
  2. **`event_goal_is_current`（死代码 + 第二套互相矛盾的新鲜度规则）—— 已删**：
     它读 `item["updated_at"]`，而记录写的是 `verified_at`，所以**对任何输入都返回 False**；
     它唯一的那条测试断言的正是这个 False（"用一条测试证明缺陷是稳定的"）。
     唯一规则是 `state_truth.legacy_event_row_for`（读 `verified_at`、比对记录的倒计时、
     **把裁决挂在行上**）。原测试换成更强的性质：断言该函数不存在、且审计函数仍在用。
- 早先已识别、仍需自己的 A/B：`capability_gate.EPISODE_TAIL` 的字节窗口
  （`limit * 4096` 实际只读到约 127 行）；`_probe_lapsed` 的锚点让一个过期 blocker
  对一个持续产出 episode 的 Goal 永久生效；把 `no_progress_streak` 改成**速率**。
- **`CONTROL_PLANE_PATHS` 的边界问题（记录，未改）**：按该常量自己写下的判据
  （"这个窗口是否在自己的进程里执行它？"），`winter_agent_v2/runtime.py` 也应当在内 ——
  面板在第 5579 行 `from winter_agent_v2.runtime import LiveRuntime`，第 5616 行读
  `LiveRuntime.VERIFIED_ATOMIC`（能力页用来标"已实测绑定"的集合）。
  本轮**只加了 `runtime_snapshot.py`**（窗口用它**解析**快照，字段被静默丢弃，见提交信息），
  没加 `runtime.py`：它是全仓改动最频繁的文件，把它加进去会让通知几乎每次提交都亮，
  而这正是 `needs_reload` 自己警告的"教会操作者忽略通知"。
  这需要一次**有意识的决定**，不是顺手加一行 —— 所以留在这里，不偷渡。

### 新增守卫（防复发）

- `tests/test_console_shows_only_what_it_can_fill.py`：27 条，六个类（含"7 个页面在真 `tk.Tk` 上
  真的构建得起来"），分别锁 **R3 派生页签集合**、**R4 记录键可取性**、**R1 不报狼来了 + 裁决不缓存**、
  **R2 两个字段两个属主**、**P1 干预卡在两种情况下都诚实**。
- `tools/check_wiring.py` 新增 3 条（来源年龄机制存在 / 干预卡存在 / 两个置信度两个名字），
  并把旧页签检查改成新事实。改后 `problems: 2`（与改前的两条**同一组**，无新增红）。

## 八、A/B 证据（本轮改动是否真的净收益）

**方法**：同一份 89 文件清单、同一条命令，**唯一变量是本轮改动的 12 个文件**。
先备份这 12 个文件（`E:\无尽冬日智能体_backups\20261004_console_tiers\mine\` + `md5sum`），
对 8 个受版本控制的非数据文件执行 `git checkout --` 回到 `90a9990`，跑基线，
再用 `md5sum -c` 恢复并逐条校验。**没有用 `git stash`** —— 这个仓同时是数据根，
有 66+ 个数据文件是脏的，stash 会动到它们。两种状态各跑一次，`--basetemp` 一律指到仓外。

| 状态 | 结果 |
|---|---|
| 基线 `90a9990` | 122 failed · 1452 passed · 11 errors · 231 subtests |
| 本轮改动（12 文件） | 122 failed · 1452 passed · 11 errors · 231 subtests |

`comm` 双向对比：**只在基线红 = 空；只在本轮红 = 空**。
即：本轮**没有修掉任何本来就红的**（诚实），也**没有弄红任何本来是绿的**。
那 122 条基线红是既有问题，不是本轮引入 —— 报告它们时必须这么写。

**中途一轮的噪声（已排除，记录以免下次重复困惑）**：中间有一次整跑多出一条红
`tests/test_evidence_integrity.py::test_runtime_captures_are_still_prunable`，
下一轮又绿、且 `comm` 证明它不在"只在本轮红"里。它读的是活数据
（`dataset/raw/control_panel/runtime_auto` 下 27,514 个正在被 AUTO 增删的截图）。
那一轮用了 `--tb=no`，**没有回溯所以不下机制结论**；能确认的只有"它不是本轮改动造成的"。
**方法上的教训：判断"是不是我改坏的"必须比集合（`comm`），不能比计数** ——
同一份清单的 passed 数在四次运行里出现过 1452 / 1477 / 1451 / 1452。

### 这一轮额外重新瞄准的两条检查（§46）

| 检查 | 为什么必须改 | 改成什么 |
|---|---|---|
| `test_state_truth.py::test_every_flat_tab_is_regrouped` | 它断言"12 个平铺页签名都在 `TAB_GROUP` 的键里" —— 也就是**要求这张表继续宣传 5 个 `_build` 早就不建的页面**。守住一条已退休的要求，比没有检查更糟：它正是没人发现"表和窗口已经漂开"的原因 | 改成派生守卫**答不出的另一半**：操作者真正读到的**值** —— 非空、互不相同、且每个值要么就是页签名，要么是该页签名加**唯一**前缀 `运行·`。纯结构断言，不引入第二张手写名单 |
| `tools/gui_wiring_verify.py::_stub` | 它按自己的注释约定（"绑定成 unbound，**跑的是真实现**"）给 stub 补方法；`_refresh_truth` 新增了三个辅助函数，stub 没跟上 → **那个"用来源而不是用自己的说法去验窗口"的校验器直接停摆** | 补上 `_freshness` / `_source_age_note` / `_attention_with_sources`，并显式 `process=None`（stub 里没有 AUTO，"不升级报警"才是**正确读数**）：报警那半正确地空着，**陈述那半照常真跑**，所以过期源仍被验到 |

### 一个必须写下来的环境陷阱：宿主的批量删除闸门

新加的两条"标记必须能退休"的测试，**单独跑 33 条全绿**，但在 89 文件整跑里曾变红。
回溯明确指出：不是代码错 —— 是宿主 shim 拦截 `Path.unlink`，**同一个工具调用内删除超过 50 个文件**
后抛 `SystemExit(1)` 并打印自己的 `SAFE_DELETE_BULK_CONFIRM_REQUIRED`。
（同一条闸门之前还杀过两次整跑：pytest 会话收尾会一次性删掉 50+ 临时文件，
于是**摘要行来不及打印**，看起来像"没有结果"。`--basetemp` 指到仓外只能缓解，不能免除。）

处理方式：加一个**极窄**的容忍器 `_past_the_hosts_delete_gate()`，
**两半证据同时成立**才吞：① 闸门环境变量在（它说自己武装着），**且** ② 文件确实还在（删除没发生）。
- 代码自己抛 `SystemExit` → 照旧失败；
- `clear()` 静默没删 → 照旧失败；
- 而这份容忍本身也有驱动测试（`test_the_delete_gate_tolerance_cannot_swallow_a_real_failure`），
  三种组合逐一验证 —— 否则"唯一一处不报错的地方"会变成"唯一一处不再报错的地方"。
- 在正常（非沙箱）环境里这个辅助函数是透明的，**删除本身就是断言**。

**教训（写入 MEMORY §51）**：一条绿了的测试，也可能是环境替它绿的；
把"失败"和"环境拒绝"分开的唯一办法，是让**拒绝的发起者自己署名**，并让容忍**可被证伪**。

## 九、落地记录（commit → repin → 重启 → 实测）

操作者授权「1. 自己 commit 2. 自己 repin 3. 自己重启面板 4. 自己验证 5. 自己清掉过期标记」。
下面按这五步记，**每一步都带可复算的证据**。

### 1. commit

| sha | 内容 |
|---|---|
| `c024e88b` | 控制台两层审计的修复：R1–R4 四条共享根因 + P1「需不需要干预」+ 重载标记退休 + `runtime_snapshot.py` 进 `CONTROL_PLANE_PATHS`；15 文件，+2067/−256 |
| `b9f4573e` | `tools/repin_production.py` 的路径从**盘符字面量**改回派生（见下"顺带找到的第三个缺陷"）；2 文件 |

### 2. repin

```
repin --check-only : [BEFORE] HEAD = 90a9990c   outside_data_dirs=0   → CLEAN_OUTSIDE_DATA
repin --to b9f4573 : [AFTER_RESET]  outside_data_dirs=17（index 动了、工作树还没动）
                     [AFTER_CHECKOUT] outside_data_dirs=0
                     [manifest] 90a9990ca5eb → b9f4573e2fc2
check_mainline     : OK 1. / OK 2. / OK 3.  →  RESULT: MAINLINE_OK
```

**关键细节**：`reset --mixed` 之后有 17 个"数据目录之外"的脏文件 —— 那是**预期**的
（index 已到新提交、工作树还是旧内容），`checkout <sha> -- .` 把它们同步到新提交后归零。
**判据：repin 成功的标志是 `outside_data_dirs=0`，不是某个 rc。**

### 3. 重启面板（发现并绕过了一个陷阱）

**陷阱**：`tools/panel_restart.py --start` 自己 docstring 里就写着 ——
"本宿主会在调用进程结束 turn 时回收它 detached 子进程的整棵树（2026-09-18 实测：
窗口 +19s 写了 pump.json，+25s 就没了），所以请从**长活任务**启动"。
⇒ 所以**没有**用 `--restart`，而是：`--stop --force` + `Start-ScheduledTask WinterAgentV2Panel`。

**过程中一个需要解释的现象**：`--stop --force` 报"nothing to stop" —— 因为面板**在那一刻已经
自己没了**（panel.log 最后一行 16:45:24，正落在我 repin 改写生产树 `tools/control_panel.py`
的时间点上）。**没有崩溃行、没有异常**。这不是我杀掉的，也不是我改坏的；
但它意味着**在我操作的那一分钟里 AUTO 是停的**（约 2 分半）。
面板起来后：`pid 26364 alive · AUTO_RUNNING · workers 1 · 预检通过`。

**这条要记住**：改生产树的文件 → 正在跑的面板**可能**在下一轮自行退出；
所以"改代码"和"确认面板还活着"必须是同一个动作，不能假设"重启前它还活着"。

### 4. 实测（全部在生产树上跑，不是开发树）

| 声明 | 实测输出 |
|---|---|
| 7 个页签 | `{'总览':'总览','策略':'运行·策略','目标':'运行·目标','活动':'运行·活动','能力':'能力','自动开发':'自动开发','系统':'系统'}` |
| 7 个页面在真 `tk.Tk` 上真的建得起来 | 生产树跑 `tests/test_console_shows_only_what_it_can_fill.py tests/test_check_mainline.py` → **39 passed** |
| 窗口每一个动态字段都接在真来源上 | 生产树跑 `tools/gui_wiring_verify.py` → **18/18 wired and matching, 0 mismatched, 0 unconfirmed**（exit 0） |
| 「需不需要干预」有真内容 | 「结论：**需要你看一眼（1 项）** / 原因：⚠ WORKBUDDY_QUEUE_STUCK：12 条仍未被消费（NEW/QUEUED）——不得显示成「开发中」 / 此刻会不会花钱：真钱：**永久禁止 🔒** · 已禁用 Goal 7 个 / 去哪里：策略页「运行方式」…」 |
| 事实卡的来源行带年龄 | 能力覆盖 → `…capability_catalog.json　（能力目录7.6 天前，已过期）`；另外三张是新的，所以**正确地**不写年龄（空字符串＝没事） |
| 两个置信度是两个字段 | `runtime_snapshot.json` 里 `confidence = 0.99`、`frame_confidence = 0.99` 同时存在；面板 5956/5958 行分别从决策与 `snapshot.frame_confidence` 取值，7744 行另有实时帧的写法 |
| **过期标记被真实删除** | `learning/CONTROL_PLANE_RELOAD_REQUIRED.json` 16:46:55 存在（866 B，`reason` 里写着"本进程加载的 90a9990ca5eb 已被 b9f4573e2fc2 取代"）→ 新面板 16:47:53 起来后 **`ls` 报 No such file**，且 panel.log **没有**再出现新的"控制面已变更"行 |

**最后一条是这次最重要的证据**：标记不是被我手工删的，是**新的那一支**
（`_check_control_plane_reload` 的 `if not stale:` → `control_plane_signal().clear("superseded_claim_resolved")`）
在**真实进程里**删掉的。上一轮只证明了"调用者存在"，这一轮证明"它真的会跑"。

### 5. 过期标记

已由代码清掉（见上）。**没有手工 `rm`** —— 手工删只会掩盖"没有退休者"这个缺陷本身。

### 顺带找到的第三个缺陷（已修，`b9f4573e`）

`tools/repin_production.py` 用**盘符字面量**（`C:\Users\xhw\.codex\worktrees\...`）指生产工作树，
而 `tools/check_mainline.py` 是**派生**的（`MAIN_REPO.parent`，它自己的注释就引 §26.3
"derived, never a drive literal"）。两者**只是碰巧一致**：2026-10-03 迁到 E 盘时在旧路径留了
junction（`C:\Users\xhw\.codex\worktrees` → `E:\无尽冬日智能体_worktrees`）。
这就是 R3 的同一形状 —— **同一个事实被声明了两次，靠没人碰它才一致**。
junction 一没，后果不是崩溃而是**"报告 repin 成功、却钉在了另一个目录"**。
已改回派生，并加两条测试：一条**解析后比对**（不是比字符串，因为 junction 下两种拼法不同而目录必须相同），
一条走 AST 拒绝任何盘符字面量（走 AST 而非文本，所以注释里**解释**旧路径不算违规）。

### 新登记（本轮发现，不修）

1. **控制面标记的 `kind` 字段名不符实（P2）**：`CONTROL_PLANE_RELOAD_REQUIRED.json` 里
   `"kind": "RUNTIME_RELOAD_REQUIRED"` —— 文件名说这是控制面的，内容说这是 worker 的。
   `CONTROL_PLANE_KIND` 这个常量**只用在 reason 文案里**，没有进 `kind` 字段。
   **为什么不当场改**：两种标记共用 `ReloadSignal`，而 `pending()` 的判据是
   `payload.get("kind") != REQUEST_KIND` —— 真把 `kind` 写成控制面的值，`pending()` 会返回 None，
   整个控制面机制反而失效。要改得先让 `ReloadSignal` 知道自己是哪一种（或让 `pending()` 收一个集合），
   那是**设计改动**，不是顺手一行。**当前危害有限**：分发靠**路径**不靠 `kind`（全仓没有任何代码
   glob 这个目录），操作者看到的是 reason 文案（正确）。所以归 P2，登记不修。
2. **测试临时目录落在数据根里**：`learning/pytest_tmp_nav/` 下面有整份 `winter_agent_v2/` 副本，
   于是**任何全仓 grep 都会重复命中 5 遍**（我自己这一轮就被它干扰过）。
   `out/index_verify_*` 同理。⇒ 仓内扫描之前必须先确定"要不要包含 learning/out"，
   或者把这些目录纳入 `.gitignore` + 清理。**本轮不动**（不是本轮引入）。

---

## 十、信息分层的落地（第二遍：折叠与下钻）

第一遍（§七）修的是"格子能不能说实话"；操作者真正抱怨的是**"东西太多"**。§六 已经把
每个字段归到了 L1/L2/L3，本节是**按那张表动 UI** 的记录。

### 做了什么：一个机制，不是九个补丁

`_fold(...)` 是唯一的折叠原语，它返回 **"内容该画进哪个 frame"**，所以每个块里原有的
`pack`/`grid` 一行没改 —— 这是给它不变成"第二套布局系统"的关键。每个块在**声明处**写四件事：

| 声明 | 含义 |
|---|---|
| `level=L1/L2/L3` | 默认开还是合。由 `FOLD_DEFAULT_OPEN` 按**层**决定，块不能另选默认值 |
| `sources=(...)` | 它显示的数字来自哪些文件（守卫测试保证这些 key 在新鲜度表里有行） |
| `escalate=...` | 什么情况**把块打开**（异常浮到 L1） |
| `annotate=...` | 什么情况**只在标题栏标记**（块不展开） |

`_sync_folds()` 在每次 tick 上跑（`_refresh_workbuddy` 里紧跟 `_refresh_truth`），
四个行为全部有守卫测试：有 escalate 就自己打开；只有 annotate 就只标记；警报开的块在原因消失后
自己合上，但**操作者手开的块不会被夺回去**；**原因永远写在标题栏**，无论开合。

### 实测（真 `tk.Tk`，用窗口自己的构建函数；脚本 `_measure_console_tiers.py`）

| 读数 | 值 |
|---|---|
| 按声明渲染 | **1065 px** |
| 九块全部展开 | 1996 px |
| 分层挡掉的 | **931 px（47%）** |
| 首次绘制时打开的块 | **0 / 9**（`test_the_overview_folds_what_the_audit_folded` 断言的就是这个） |
| 真实数据根 + AUTO 在跑时自动打开的块 | **1 / 9** |

### 必须写下来的一个错误：我把"标记"和"打开"合成了一条规则

第一版只写了一条规则："这个块用到的源过期了 → 打开它 + 标题栏说明"。**实测证明它让折叠白做**：

```
对真实数据根实测（修正前）：
    L3  kpi        open=True   ⚠ 能力目录 已停更（7.7 天前）…
    L2  facts      open=True   ⚠ 能力目录 已停更（7.7 天前）…
```

`capability_catalog.json` 的预算是 7 天，而它是**开发工作**写的、不是 AUTO 写的 ——
所以"过期"是它的**常态**，一旦触发打开，这两块就**永久**敞着，而它们正是操作者抱怨的那两块。
更糟的是长出一头"狼来了"：永远亮着的警报等于教人忽略警报（`source_freshness` 自己的
docstring 就在警告这件事）。

**判据**：§六 那张阈值表逐行读，问的是**谁浮上来**：

| 表里那一行 | 浮上来的是 | 实现 |
|---|---|---|
| 任一数据源超过 TTL **且** AUTO 在跑 | **那些格子**显示「待重新观测」+ **"需要关注"里点名** | `annotate`（只标记） |
| 看门狗 / WorkBuddy / 队列 / 预载 非正常，或队列有活跃 Job | **那个块** | `escalate`（自己展开） |

修正后实测（真实数据根，AUTO 在跑）：

```
    L3  kpi        open=False ⚠ 能力目录 已停更（7.7 天前），这一块的数字不是当前读数
    L3  workbuddy  open=True  ⚠ WorkBuddy 网关异常
    L2  facts      open=False ⚠ 能力目录 已停更（7.7 天前），这一块的数字不是当前读数
    …其余 6 块 open=False，无标记
    -> 1 / 9 自动打开
```

**那唯一打开的块是为一台真故障打开的，不是规则误报**：`gateway_health` 的实测值是
`异常`（`AUTH_REJECTED；连续 53 次失败，已退避 300.0 秒；没有成功通信记录`），
状态 `CONFLICT`。按 §六 那一行，它就该浮上来。
⇒ **"规则能自己打开一个块"必须在真实数据上看到它为真故障打开，否则等于没验证过。**

### 顺带修掉的一个 R1 残留：8 个 KPI 卡仍然没有年龄

审计 §三A 点名的「KPI 8 卡没有任何年龄标注」，上一轮只修到了四张**事实卡**
（`fact_source`）；KPI 卡的来源行读的是 `overview_kpis()` 的静态字符串。
现在每张卡在 `CATALOG_FRESHNESS`（卡 → 新鲜度表 key）里声明它数的是哪个文件，
来源行追加该文件年龄；读进程内 registry 的 `stable` 卡登记在 `CATALOG_UNFRESHNESSED` 里
并写明理由（没有文件就没有可报的年龄，编一个是对"缺失写入者"的断言）。
**落点有个坑**：这段必须在**写 KPI 标签的那一段**里做 —— 它跑在 `_refresh_truth` **之后**，
写在 `_refresh_truth` 里会被几行后的静态标签覆盖，而且**看不出坏**。守卫测试因此同时断言
位置（`aged > setter`）而不只是断言那行字符串存在。

### A/B（同一份 89 文件清单，唯一变量是本轮的 4 个文件）

| 状态 | 结果 |
|---|---|
| 基线 `66c23cb0` | 120 failed · 1456 passed · 15 skipped · 11 errors |
| 本轮 | 120 failed · 1457 passed · 14 skipped · 11 errors |
| `comm`：只在基线红 / 只在本轮红 | **空 / 空** |
| `comm`：只在基线 error / 只在本轮 error | **空 / 空** |

四段全空 = **没弄坏任何绿的，也没修掉任何本来就红的**（那 120 failed / 11 errors 是既有问题，
报告它们时必须这么写）。**这次连 errors 也按名字比了** —— 见下。

**方法上的一个自我修正（必须记）**：第一次 A/B 我只用了 `-rf`，而 `-rf` **不打印 ERROR 段**，
于是"11 errors"只能靠**计数**相等来声称 —— 那正是 §八 自己写下的教训
（"判断是不是我改坏的必须比集合，不能比计数"）。重跑时改成 `-rfE`，errors 也按名字 `comm`，
四段仍全空。**用计数相等顶替集合相等，就是在重复上一次的错。**

**第一次 A/B 里那一条差异**（`test_evidence_integrity.py::test_runtime_captures_are_still_prunable`）
是 §八 已记录的活数据抖动（它读 `dataset/raw/control_panel/runtime_auto` 下正在被 AUTO 增删的
27,514 个截图）；单独重跑**通过**，第二次 A/B 里两侧也都没出现。结论不变：与本次改动无关。

### 这一轮另外两处"顺手但必要"的修

1. **`run_fold_rule` 从 `staticmethod` 搬到模块级**。它原本写成 `@staticmethod`，生产代码没问题，
   但测试里按 `getattr` 绑定的桩给它多传了一个 `self`，**守卫测试死在桩里而不是面板里**。
   它本来就不碰 `self`，所以改成模块级函数 —— 不依赖任何绑定约定（MEMORY §55）。
2. **Tk 测试的 root 改成整类共享一个，不再每个测试 `Tk()`/`destroy()`**。
   实测：三次运行里**有一次**让 `test_the_overview_folds_what_the_audit_folded` 静默
   `skip`（`no Tk display available`）—— 一条守卫三次里跳过一次，等于没有守卫，
   而且 `skip` 读起来像"环境问题"，所以这个失败模式是隐形的。改成一次创建、不再销毁后，
   四次运行 41 passed / 0 skipped。

### 本轮没做（已登记，机制已经在了，剩下是逐页应用）

- **其他 6 页的折叠**：目标 / 策略 / 活动 / 能力 / 自动开发 / 系统。§六 已经把每页的块
  逐条归了层，照着写 `_fold(...)` 即可；本轮只做了操作者天天盯的**总览**，
  理由是**小步验证优于一次性大改**（在已部署的机制上继续，而不是一次交没验证过的大 diff）。
- **顶栏 9 格 → 6 常驻 + 3 折叠**（WorkBuddy / 本地模型 / 预载 归 L3，异常浮 L1）。
  顶栏是 `grid` 里的 9 个 cell，折叠它需要另一种形态（健康时 3 格收起成 1 格汇总），
  与"块"不是同一个几何问题，所以单独一轮做。
- **总览「游戏实时画面」的 L2 → 卡住时 L1**：它在中间列，占位最大，但它同时是"异常时唯一能看懂的东西"，
  折叠它需要和预览渲染的时机一起考虑（折叠着还渲染不渲染？），不是顺手能定的。
- **两条还没实现的「异常浮到 L1」规则**：① 目标队列积压（`state` 相同 ≥ 阈值）→ 对应块；
  ② **"此刻有没有在花钱 / 不可逆操作"** → 策略页的 🔒 行浮到 L1。
  第 ② 条是第二层审计里"缺失"一条，值得下一轮做。

### 新登记（本轮发现，不修）

1. **`escalate` 的"新故障"判据是**文本不相等。**它现在打不到**：三条 escalate 规则的文案都是常量
   （`WorkBuddy 网关异常` / `看门狗异常` / `WORKBUDDY_QUEUE_STUCK：…`），不会自己变形。
   之所以登记：`annotate` 的文案**含年龄**（`7.7 天前` → 过一阵变 `7.8 天前`），
   而 `user_closed` 是靠在"文案变了"时重置的。**如果以后有 escalate 规则也把年龄写进文案**，
   操作者手合上的块会在年龄跳字时自己再开一次。真按身份判断需要给故障一个 id，
   那是设计改动。⇒ 规则：**escalate 的文案必须是常量串**。
2. **`annotate` 的文案每 1.4 小时左右会跳一次字**（同上，`%.1f 天前`）。
   对 `annotate` 无害（它不改变开合），但会让标题栏的字符串偶尔变一下。

---

## 十一、第二批：系统页归层，以及两个守卫（2026-10-04 续）

操作者的顺序是「先归类（§六）→ 报告 → 不等确认 → 改 UI」。这一批是"改 UI"的第二步：
把 §六 已经定好的层，在**系统页**上落成代码（总览在第一批已落）。

### 1. 做了什么

| 项 | 内容 |
|---|---|
| 系统页 | 当前角色 + 角色Session 留成**常驻 L1**（页面的范围）；新增 5 个折叠：`sys_decision`(L2) / `runtime_watchdog`(L3，**会自己打开**) / `arbitration`(L3) / `header_evidence`(L3) / `sys_logs`(L3) |
| 阈值 | 实现了 §六 那条**至今没实现**的看门狗阈值：`unexpected_worker_exits > 0` 或 `watchdog_restart_count` **增长** → 看门狗块自己打开 |
| 一条规则 | 新增的 `runtime_watchdog` 和总览的 `watchdog` **调用同一个 `_escalate_watchdog`**，不是各写一条 |
| 守卫 | 新增 2 条：`test_no_page_opens_as_a_stack_of_shut_headers`、`test_no_two_blocks_share_a_fold_key`；接线检查新增 2 条 |
| 顺带 | 修掉本报告里两处**散文数字**（顶栏 4+3→6+3、系统页 12→11 行） |

**为什么"重启次数增长"必须是相对基线，而不是 `> 0`**：`watchdog_restart_count` 是这台机器上的
累计值。`> 0` 会让这块在**任何曾经重启过一次的机器上永久打开** —— 那就又变成了"狼来了"，
和第一批把 `annotate` 拆出来要解决的是同一个失败模式。基线取窗口第一个 tick 的值，
所以"增长"的读数是**"你看着的时候它涨了"**，这是唯一能让这个阈值说出话的读法。

### 2. 量出来的结果（`_measure_console_tiers.py`，真实 Tk root，窗口自己的 build 代码）

| 页 | 折叠态 | 全开 | 挡掉 |
|---|---|---|---|
| 总览 | **1065 px** | 1996 px | 931 px（47%） |
| 系统 | **341 px** | 1193 px | **852 px（71%）** |

系统页折叠态 341 px 里包含**常驻的当前角色**和 5 条表头 —— 这是这一批真正要守住的性质：
**一个页面不能以"一叠合上的表头"开场**。§六 把系统页几乎每一块都判到 L2/L3，
照字面实现出来的页面打开时会是空的，所以这一条写成了守卫（见下）。

阈值的行为，逐步实测：

```
0 次退出，重启仍是 7        -> expanded=False  badge=''
unexpected_worker_exits=2  -> expanded=True   badge='⚠ 有 2 次意外的 Worker 退出'
重启从 7 涨到 9            -> expanded=True   badge='⚠ 看门狗重启次数从 7 涨到 9'
回到 0 次退出 / 7 次重启    -> expanded=False  badge=''   （报警自己关上了）
```

接线自检：新增两条 `OK gui: the 系统 page keeps the role readable and folds the rest by tier`、
`OK gui: both watchdog blocks grade the watchdog with one rule`；`problems: 2` 与上一批**同两条**，
不是我引入的。守卫测试 `tests/test_console_shows_only_what_it_can_fill.py` **48 passed**。

### 3. 两条新守卫，为什么是这两条

1. **`test_no_page_opens_as_a_stack_of_shut_headers`** —— 这一批的真正风险不是"折叠坏了"，
   而是"照 §六 字面实现出来，页面打开是空的"。判据写成**结构**的：页面的**第一个** `self._fold(`
   之前，必须已经**创建并放置**了能读的东西。故意不去数"有没有 L1 折叠"：总览把
   「需要关注」「手动干预」放在折叠机制之外，系统页把角色放在那里，所以"有没有 L1 折叠"是错的问题。
2. **`test_no_two_blocks_share_a_fold_key`** —— `_fold` 把所有块存在**一个 dict** 里，
   所以重复的 key 会**静默**顶掉前一个：前一个容器和表头都还在屏幕上，但再也没有任何规则跑它，
   它会永远停在自己的默认层、表头永远不更新。`_declared_folds()` **看不见**这个 —— 它返回的就是 dict，
   而 dict 正是藏住碰撞的地方。所以这条守卫从 AST 里收成**列表**再比。key 从 9 个变成 14 个，
   跨 2 个页面，正是这类碰撞开始可能发生的时刻。

### 4. 顺手发现并修掉的一个交付级缺陷（另一次提交，不混进这一批）

查改动范围时发现：**`config/paths.py` 从未进过任何分支**，而已提交的
`tools/check_mainline.py`、`tools/repin_production.py`、`tools/replay_loop_main_path.py`
从 `c6cadfb6`（2026-10-04）起就在 `from config import paths`。

- 复现（不是判断）：把 HEAD 里这几个路径 `git archive` 到干净目录 —— `config/` 下**只有 `v2.json`** ——
  跑同一个工具 → `ImportError: cannot import name 'paths' from 'config'`。
- 影响：**新克隆跑不了**；这个项目的 GitHub 镜像正是这些提交的 SHA 镜像，所以镜像也跑不了
  「审计主线的工具」和「移动 pin 的工具」。所有机器今天能用，只是因为工作树里也**存在**这个
  未跟踪（且未被 ignore）的文件 —— 这就是它一直没被发现的原因。
- 已修：`ee1697a1`，把 `config/paths.py` 入库，连带三个依赖它的文件一起（否则"提交它 import 的模块、
  却把 import 它的文件留在外面"，树只是**碰巧**自洽）。同一条 import 探针 A/B：
  `cfa7c555` → `FAIL ImportError`；`ee1697a1` → `OK -> E:\无尽冬日智能体\.venv\Scripts\pythonw.exe`
  ——正是 `panel_restart.py` 启动面板需要的那个解释器。
- 落地前先验过 `WINTER_MAIN_REPO`：**没有任何地方设置它**（只在本模块自己的文档串和常量里出现）。
  它若被设成一个 worktree，`VENV` 会指向不存在的 `.venv`。生产启动器设的是
  `WINTER_AGENT_DATA_ROOT`，那是**数据**根，不动物理仓。

**教训（写入 MEMORY §56）**：一个"所有机器都能跑"的模块，可能根本不在版本控制里 ——
工作树里有它，就永远不会有人发现。看见它的唯一办法，是**从这个提交本身导出干净副本再跑**。
这类缺陷与"数据文件脏"完全同形，所以判断依据必须是导出，不是本机能不能跑。

### 5. 一处**照字面实现会错**的地方：§六 的 `> 0` 被实测否掉了

§六 的阈值行写的是 `unexpected_worker_exits > 0`。我第一批就是照字面实现的。**部署后查运行状态时
被真实数据打回来**：

```
learning/runtime_snapshot.json:
  watchdog_restart_count    = 28
  unexpected_worker_exits   = 22
```

这两个字段都是**机器累计值**（`previous.unexpected_worker_exits + 1`，持久化在 runtime store 里；
写入点在 `tools/control_panel.py` 的 worker 退出路径上），不是"本轮 / 本期"。所以 `> 0` 量的是
**这台机器的历史**，不是现在 —— 在这台机器上它会让系统页的看门狗块**永久敞开**。

**这与第一批把 `annotate` 从 `escalate` 里拆出来要解决的是同一个失败模式**：一个块因为
"一直为真"的条件永远开着，读者很快就学会忽略它。区别只是第一批是"文件老"，这次是"历史计数大"。

**改法**：两半都读**相对基线的增长**（基线取窗口第一个 tick 的值），并且徽标先写增量、括号里再给累计：
`窗口打开以来有 1 次意外的 Worker 退出（累计 23）`。
**§六 的意图（一次意外退出就是信号）保留，只有它的算术被改成匹配字段真正装的东西。**

实测（用真实的那两个数，不是整齐的假数）：

```
22 次退出 / 28 次重启，无增长   -> expanded=False  badge=''
多一次退出（22 -> 23）        -> expanded=True   badge='⚠ 窗口打开以来有 1 次意外的 Worker 退出（累计 23）'
重启 28 -> 30                -> expanded=True   badge='⚠ 看门狗重启次数从 28 涨到 30'
回到 22 / 28                 -> expanded=False  badge=''  （报警自己关上了）
```

守卫 +2 条：行为一条（用**真实**的 22/28，因为 22 正是那个字面判据算错的数）、
源码一条（防 `if exits:` 这种换一种写法的字面实现；断言**限定在该方法体内**，
不能被别处一句注释误伤、也不能让真正的回退躲在注释后面）。
`tests/test_console_shows_only_what_it_can_fill.py` -> **50 passed**。

**教训（写入 MEMORY §57）**：指令里点名了一个字段，就先去查**这个字段实际装的是什么**，
再决定阈值怎么写。"字段名读起来像现在"和"字段里装的是历史"是两件事，
而后者只有在**真实数据**上跑一次才会露出来。

## 十二、第三批：能力页 / 自动开发页归层，以及 §六 里两条"写了但从没实现"的阈值（2026-10-04 续）

### 1. 本批做了什么

按操作者的顺序（先归类 → 报告 → 不等确认 → 改 UI），继续逐页落地 §六。
本批两页 + 两条阈值 + 三个守卫。

| 页面 | 折叠键 | 层级 | 规则 |
|---|---|---|---|
| 能力 | `cap_catalog` | L2 | 无（`INERT_FOLDS` 记录理由：覆盖表是参考表，不是"现在出事了"） |
| 能力 | `cap_registry` | L3 | 无（同上，Skill 执行注册表同理） |
| 能力 | `cap_runtime` | L3 | **有** — §六「`unexpected_worker_exits` 非 0 必须浮上来」 |
| 自动开发 | `dev_loop` | L3 | **有** — §六「闭环断点必须浮上来」 |
| 自动开发 | `dev_wb` | L3 | **有** — 复用总览那条 `_escalate_workbuddy`（同一个方法，不是第二份判断） |
| 自动开发 | `dev_pump` | L2 | 无（泵 + 设备所有权两行，从 WB 网格里按 §六 拆出来） |
| 自动开发 | `dev_queue` | L2 | 无（状态条 + 条件条合并） |
| 自动开发 | `dev_failures` | L2 | **有** — §六「失败次数 ≥ 阈值」 |
| 自动开发 | `dev_jobs` | L3 | 无（Job 历史 + 模型战绩合并成一块） |

**§六 里两条一直只写在纸上、从没实现的阈值，本批实现了，而且都没有编数字**：
失败阈值复用项目自己那个 P0 分桶（`failure_priority`：`>=10` → `P0`，`>=3` → `P1`，否则 `P2`），
断点判据复用 `closure_card` 自己已有的字段（`ok` / `breakpoint`）。
**"不编第二个意见"和"把 §六 落地"不是矛盾的 —— 前提是先去仓库里找那个已经存在的判断标准。**

### 2. 一处**故意偏离 §六**的地方（有守卫撑腰）

§六 把"覆盖度"归 L2。机械照做的话，能力页**打开时会是三根关着的横条**（+ 一张参考表），
也就是说读者第一屏什么都看不到。所以那**四张摘要卡保持常开**。

这不是偷懒，是那条新守卫要求的：`test_no_page_opens_as_a_stack_of_shut_headers`
（一页不能以"一排关着的标题"开场）。**当 §六 的机械读法和结构守卫冲突时，
守卫赢 —— 而且这次是守卫先存在，才让我看见照抄会出事。**

### 3. 实测：一页少占多少屏

（真实 Tk root，用的是窗口自己的构建函数，不是另画一版）

| 页面 | 按分层打开 | 全部展开 | 分层省下 | 占比 |
|---|---|---|---|---|
| 总览 | 1065 px | 1996 px | 931 px | 47% |
| 系统 | 341 px | 1193 px | 852 px | 71% |
| **能力** | **345 px** | **875 px** | **530 px** | **61%** |
| **自动开发** | **477 px** | **1619 px** | **1142 px** | **71%** |

### 4. 实测：新规则在真实数据上会不会"狼来了"

这是折叠机制存在的全部意义所在 —— **一条在稳态数据上也会打开的规则，比没有规则更坏**。
所以用**真实数据根**跑了一遍：

```
[6] 真实数据根，AUTO 视为运行中
    L3  workbuddy  open=True   ⚠ WorkBuddy 网关异常
    -> 1 of 9 blocks open unasked; 8 folded
    -- 本批三条新规则，同样真实数据 --
    L3  cap_runtime    open=False
    L3  dev_loop       open=False
    L3  dev_wb         open=True   ⚠ WorkBuddy 网关异常
    L2  dev_failures   open=False
```

**四条里只有一条开着，而它开得对**（网关此刻确实异常）。
`cap_runtime` / `dev_loop` / `dev_failures` 在真实数据上全部保持关闭。

`dev_loop` 的四种排除态单独验过：

```
无闭环卡                 -> open=False  badge=''
闭环从没跑过             -> open=False  badge=''
闭环干净 PASS            -> open=False  badge=''
真断点（VERSION_ACTIVE）  -> open=True   badge='⚠ 闭环卡在：VERSION_ACTIVE：等待真机校准'
```

**注意"闭环从没跑过"与"无闭环卡"都**不**打开**：读不到证据 ≠ 有证据证明卡住了。
把这两件事混起来，就是让每个新建的窗口开局先喊一次警。

### 5. `> 0` 那个修正，现在有两处共用一套读数

`_worker_exits_since_window()` 是被抽出来的**唯一**读数（`max(0, now - base)`），
`_escalate_watchdog` 与 `_escalate_capability_runtime` 都调它。
**理由是这一页和那一页显示同一个字段** —— 两份算术就是两个标准，迟早会漂开。
守卫 `test_the_two_blocks_that_show_worker_exits_share_one_reading` 盯住这一点，
`tools/check_wiring.py` 也盯住另一条同形的：`_panel_source.count("escalate=self._escalate_watchdog") == 2`
（看门狗两处共用一个判断）。

### 6. 一处**差点由测量脚本引发的生产事故**（已记 MEMORY §58）

给测量脚本加"用真实数据根评估新规则"那一节时，脚本崩在 `AttributeError: pump`。
harness 的 `__getattr__` 会**从类上重建缺失的名字**，而 `pump` / `_pump_prev` / `probes` /
`control_plane_probe` 全是 `__init__` 里的**实例**属性，`getattr_static` 找不到。

按"缺什么补什么"往下修会连补四个，而**第四个是致命的**：

- 补真 `QueuePump()` → 它没 `start()`、`alive()` 为 `False` →
  `_narrate_pump` 见死时钟就 `revive()` → **起守护线程去消费真实生产队列**。
- 补真 `control_plane_probe` → 脏树（测量时必然是脏树）走 `stale` 分支 →
  `control_plane_signal().request(...)`，而 `MARKER_ROOT = Path(control_plane_reload.__file__).resolve().parents[1]`
  **就是真实仓库** → **一个测量脚本会写下"请正在运行的面板重启自己"的实时标记**，还会调 `_start_control_plane_reload`。

**为什么 pytest 里从没炸过**：把写操作改道的那张表在 `tests/conftest.py` 里
（`MARKER_ROOT` / `POLICY_STATE_PATH` / `_ESCALATION_LEDGER_PATH` / `device_lease.DEFAULT_ROOT`），
**只在 pytest 会话里生效**。根目录那一堆独立 `_xxx.py` 驱动脚本拿到的是**真实根**，四条重定向全部绕过。

**落法**：`_IdlePump`（`alive()` 恒 `True`，`revive()` 直接 `AssertionError`）
+ `_check_control_plane_reload` 覆盖成 no-op 并写明理由。
**验证方式是查那张标记文件确实不存在**（`ls learning/CONTROL_PLANE_RELOAD_REQUIRED.json` → No such file），
不是相信"我覆盖过了"。

### 7. 守卫与检查

- `tests/test_console_shows_only_what_it_can_fill.py` → **53 passed**（50 → 53：新增 3，改 2）
  - 新增 `test_a_breakpoint_opens_the_development_loop_and_a_clean_pass_does_not`（四种态）
  - 新增 `test_the_failure_rule_opens_only_on_a_p0_and_uses_the_projects_own_threshold`
    （`failure_priority(10)=="P0"`、`(9)=="P1"`、`_panel_source().count("count >= 10") == 1` ——
    那个字面量全仓库只能出现一次）
  - 新增 `test_the_two_blocks_that_show_worker_exits_share_one_reading`
  - 改 `test_a_cumulative_counter_is_read_as_growth_not_as_a_total`（算术搬进 helper，桩要绑 helper）
  - 改 `test_the_watchdog_rule_does_not_compare_a_cumulative_counter_to_zero`（helper 钉算术、规则钉调用）
  - `SIX_TABLE_OPENERS` 扩到声明的全套开启者：`{watchdog, runtime_watchdog, cap_runtime,
    workbuddy, dev_wb, dev_loop, dev_failures}`，`queues` / `boot` 标注为"故意不实现"
- `tools/check_wiring.py`：两条与控制台相关的检查通过
  - `gui: watchdog separates current health from a lifetime counter`
  - `gui: both watchdog blocks grade the watchdog with one rule`
  - 余下 2 个 problem（`training` / `proof`）与本批无关，是既有项

## 十三、第三批落地记录（2026-10-04，五步各带证据）

| 步 | 动作 | 证据 |
|---|---|---|
| 1 | commit | `24ecfc2b` — `feat(console): two §六 thresholds had been written down and never built…`；`6 files changed, 612 insertions(+), 65 deletions(-)` |
| 2 | repin | `repin_production.py --to 24ecfc2b` → `RESULT: CLEAN_OUTSIDE_DATA`；`[AFTER_CHECKOUT] outside_data_dirs=0`（`[AFTER_RESET] outside_data_dirs=6` 是预期的"索引新、工作树旧"那 6 个文件） |
| 3 | 重启面板 | pid 17552 → **25560**（venv pythonw，18:48:39）；`panel_restart.py --stop --force` 报 `workers left after the kill: 0` |
| 4 | 验证生效 | 见下 |
| 5 | 清过期标记 | 标记由**旧窗口自己**写下、由**新窗口自己**retire，现已不存在 |

### 步 4：这次用三把独立的尺子，而不是一把

**(a) 窗口自报的提交** —— 两个互不依赖的写入点，结论一致：

```
learning/control_panel/pump.json:
  runtime_loaded_revision = 24ecfc2b3d0fdcecc3f8d2e43c8da2a9c3a2442c+528f87d2d1a85421
  runtime_loaded_at       = 2026-10-04T10:48:42Z   (= 本地 18:48:42，正是新窗口)

learning/control_panel/desktop_startup.log:
  [2026-10-04T18:48:40] CODE_COMMIT=24ecfc2b… WORKTREE_CLEAN=true DATA_ROOT=E:\无尽冬日智能体
```

**(b) 加载的字节 == 提交里的字节** —— 必须用**同一把尺子**，否则会和我上一批一样自己吓自己：

```
1. 窗口记录的                     = 961329dfb55c61598f22f5cefe118e1217bfd507536772331c3383f7e109ed4e
2. 磁盘上的原始字节（CRLF）        = 961329df…            <- 等于 1 ✔
3. 磁盘上剥掉 CR 之后              = 23d9e2ce58867812579becd8e47ef5e49035fd1b8dd4b548982a93b4db2d0cb5
4. 提交 24ecfc2b 里的 blob         = 23d9e2ce…            <- 等于 3 ✔
-> 窗口加载的字节就是提交里的字节：True
```

工作树是 CRLF、blob 是 LF，所以**直接比原始字节必然不等** ——
**"不等"在换错尺子时是假信号**，链条要全程用同一把。

**(c) 行为** —— 三个互相独立的读数：

```
tools/gui_wiring_verify.py         -> wired and matching : 18/18，mismatched 0
   其中 watchdog 行显示：正常 · 状态 GOAL_RUNNING · 历史累计重启 28 · 异常退出 22
   （§57 那个修正的**现场可见证据**：健康与历史累计被分开放）
   其中 dot_wb 显示：异常   <- 正是唯一该浮上来的那块，与 §十二.4 的实测一致

生产树 pytest（test_console_shows_only_what_it_can_fill + test_check_mainline）
                                   -> 65 passed（53 守卫 + 12 主线；+3 正是本批新增）
tools/check_wiring.py（生产树）      -> 两条控制台检查 OK；余 2 problem 是既有的 training/proof

重启之后的日志跨度里                    -> Traceback 0 条
```

`learning/runtime_snapshot.json`：`agent_state = GOAL_RUNNING`，`updated_at = 10:50:17Z`（本地 18:50），
`unexpected_worker_exits = 22` / `watchdog_restart_count = 28`（**与重启前一致，所以增长型规则保持安静**）。

### 步 5：为什么没有手工删标记

面板重启前，**旧窗口（24af0c0b）自己发现磁盘变成了 24ecfc2b、而 `tools/control_panel.py`
是控制面文件**，于是按设计写下 `learning/CONTROL_PLANE_RELOAD_REQUIRED.json`（814 B，18:48）。
新窗口起来后，自己的 `_check_control_plane_reload` 算出 `not stale`，走
`control_plane_signal().clear("superseded_claim_resolved")` 把它 retire 掉。

**这是机制在自己擦自己的过期声明，比人手删更可信** —— 手工删只能证明"我现在删干净了"，
而这条路证明的是**写下它的那条路径同时也具备撤回它的能力**（`24af0c0b` 修的就是"只有写、没有撤"）。

### 一处路径疑点，已查清（不是缺陷）

`Get-CimInstance` 显示面板命令行是 `C:\Users\xhw\.codex\worktrees\winter-prod-pinned\…`，
而 repin 的目标是 `E:\无尽冬日智能体_worktrees\winter-prod-pinned\…`。**两个不同的路径**，
`Get-Module` 层面的 `LinkType` 还报空，看起来像"面板跑在另一个树上"。

查清结论：**同一个文件**。判据是三条独立事实：

```
两边的 git HEAD              = 都是 24ecfc2b（且 git-common-dir 都是 E:/无尽冬日智能体/.git）
两边 control_panel.py 大小/时间 = 519437 字节 / Oct 4 18:47（repin 刚跑完的那一刻）
两边 Get-FileHash            = 相等（Same file as E: tree? True）
```

即 `C:\…\.codex\worktrees\…` 是一条指向 E 盘工作树的联接链，`C:\无尽冬日智能体_worktrees`
这一层已经不存在了（联接目标字符串是残留元数据，实际解析仍落到 E 盘）。
**判据必须是"同一个文件的哈希相等"，不是"LinkType 看起来像不像联接"** ——
`Attributes` 那一栏在这里撒了谎。
