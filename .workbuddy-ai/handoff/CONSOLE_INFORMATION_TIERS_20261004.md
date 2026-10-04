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

### 顶栏 9 格 → 4 常驻 + 3 折叠
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
| 角色仲裁其余 12 行 | **L3** | |
| 顶部状态的真实依据 6 行 | **L3** | |
| 日志文本框 | **L3** | |
| 打开目录按钮 | **L3** | |

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
- **顶栏 9 格 → 4 常驻 + 3 折叠**（WorkBuddy / 本地模型 / 预载 归 L3，异常浮 L1）。
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
