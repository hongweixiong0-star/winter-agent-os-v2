# 00 — MASTER RULES

**这些是长期硬规则，不随会话变化。任何接手本项目的新账号必须先读完本文件再动手。**
本文件由人工维护（不是自动生成），修改它等同于修改项目宪法。

---

## 0. 项目是什么

《无尽冬日》(Whiteout Survival) 国服客户端的**截图驱动自动化 Agent**。
MuMu 模拟器 + ADB，分辨率 720×1280，包名 `com.gof.china`。

最终产品目标只有一个：**打开指挥中心 → 点「自动运行」→ 不再人工干预 → Agent 自己长期玩**。
近期验收：连续 **72 小时**无人值守，`unexpected_worker_exits = 0`；通过后进入 5–7 天 Soak。

判断一次开发是否有效的唯一标准：

> 它是否让**真实客户端**更可靠 / 更快 / 覆盖更多 Goal / 恢复能力更强 / 人工干预更少？
> 全部为「否」→ 本次开发价值接近 0。

---

## 1. 最高事实原则（优先级，不可颠倒）

```
LIVE CLIENT
  > PRODUCTION EVIDENCE
  > VERIFIER RESULT
  > CURRENT CODE
  > REPLAY
  > TEST
  > DOCUMENT
  > PRIOR KNOWLEDGE
```

以下**都不算**功能完成：pytest PASS、函数 `return True`、Skill 已注册、Candidate 已生成、
README 说支持、外部项目说支持、Simulation PASS、Replay PASS、文档写「已完成」。

**真正完成 = 真实客户端 + 真实动作 + 真实状态变化 + Verifier PASS + 可追溯 Evidence。**

冲突时的裁决顺序（START_HERE.md 也要求核对）：
1. Handoff 文档与代码冲突 → **代码优先**
2. 代码与 Production Evidence 冲突 → **Production Evidence 优先**

---

## 2. V2 顶层架构冻结

保持**唯一主链**，不允许出现第二条：

```
Screenshot → Vision → WorldState → Goal/Brain → Single Scheduler
→ Single Skill Registry → Universal Skill → Executor → MAA/ADB → Game
→ Verifier → Recovery → Knowledge/Experience/Learning
```

允许**增强**现有模块。**禁止新增**：

- 第二 Scheduler
- 第二 WorldState
- 第二 Registry
- 第二 Goal Engine
- 平行 Manager 系统
- 活动专属 Scheduler
- 复杂 Orchestrator
- 大量新 Gate
- Legacy 风格的多套执行链

原则：**少架构、少抽象、少 Manager；多真实执行、多真实截图、多 Verifier、多 Recovery、
多 Evidence、多 Failure Analysis。**

- **Single Scheduler**：只有 `winter_agent_v2/scheduler.py` 的 `Scheduler` 决定下一个动作。
- **Single WorldState**：只有 `winter_agent_v2/models.py::WorldState` 描述世界。
- **Single Registry**：只有 `winter_agent_v2/skills.py::v2_registry()`。新能力只能加进它。
- **运行态唯一真相源**：`learning/runtime_snapshot.json`。GUI 只读，不写业务状态。

---

## 2b. 工具优先（HARD RULE，2026-09-14 增补）

**先找工具，再写代码。**

任何开发任务开始前必须先做一次 TOOL CHECK，并在汇报里给出这五行：

```
AVAILABLE_TOOLS             机器上已安装且已验证可用的工具（见 docs/AVAILABLE_TOOLING.md）
BEST_EXISTING_TOOL          其中最适合解决本问题的那个
EXISTING_IMPLEMENTATION     项目内/外部是否已有实现
WHY_NOT_USE_EXISTING_TOOL   如果不用它，具体原因（不能是"我想自己写"）
CUSTOM_CODE_NEEDED          真正必须自研的部分
```

**解释不了"为什么成熟工具不能解决"，就不许开始自研底层。**

固定优先级：

```
项目内成熟能力 → 已安装成熟框架 → 外部成熟开源实现 → 成熟第三方库
→ 最小 Adapter / Glue Code → 最后才允许自行重造
```

### 各层定位（不可互换）

| 层 | 负责 |
|---|---|
| **V2** | Brain / Goal / Strategy / WorldState / Knowledge / Experience / Verifier |
| **MAA**（已安装，`MaaExecutorAdapter`） | 高速取帧、Template / Feature / Colour Match、ROI、点击、滑动、等待、重试、页面流程 |
| **ADB** | 设备层、连接、基础控制、**fallback**、应急恢复 |
| **Verifier** | 唯一事实裁判（MAA 返回 SUCCESS ≠ Skill Success） |

### 两个轴，分开决定（2026-09-14 活体实测）

- **取帧轴：MAA 明显更好，已切换。** 真机交替 20 次：MAA（MuMu EmulatorExtras）
  **8.92 ms** vs ADB `exec-out screencap -p` **324.12 ms**，**36.3 倍**。
- **识别轴：不是"越 MAA 越好"，逐语义按证据决定。** 同一批帧上旧 V2 匹配器
  34.5 ms、MAA 113.0 ms（MAA 更慢），但两侧都是 20/20 命中、中心偏差 0.3 px。
  因此 MAA 识别的价值在**旧路径结构性做不到的地方**：位置未知/漂移、
  页面模型多锚点、以及需要多阈值多尺度搜索时。**不为了"必须用 MAA"而伪造更好结论。**

任何把某个 skill 设为 `preferred_backend = MAA` 的改动，必须在
`knowledge/execution/backend_routing.json` 里同时写入它的 `evidence`
（阳性/阴性样本科数与结果、中心误差、延迟），否则该提升等于没有依据。

### 止损规则（防止一个按钮吃掉半天）

- 单个 UI 元素：**最多 15 分钟**用现有 V2 Vision 调试。超时立即做 TOOL CHECK。
- 单个 Skill / Failure / Goal：**最多 90 分钟**。90 分钟内必须至少得到以下之一：
  Live 成功率改善 / 明确 Root Cause / 明确具体 Blocker / 证明方案错误并回滚。
- 某个变体（Intel、Event、Resource 的某一类）持续失败但主系统正常：标
  `PARTIAL` / `DEGRADED` 并登记 Open Issue，**不要阻塞其他 Skill、其他 Goal、
  整个 AUTO 和整个项目开发**。

### 仍然属于我们自己要建的东西

MaaFramework 只提供引擎，**不提供《无尽冬日》的游戏知识**。模板、页面模型、
锚点及其证据仍然是我们的工作，且必须按 Production 标准管理：
来自独立真机帧、带 Positive / Negative 样本、阈值标定、页面上下文，并记录
precision / false positive / false negative。**禁止模板自己裁自己再自匹配。**

仍然禁止：新增第二 Scheduler / Registry / WorldState / Goal Engine / 平行 Manager。
MAA 接入只是**补齐现有 Executor Boundary**（`MaaExecutorAdapter` + Executor Router
backend 支持），不是新架构。

---



## 2c. 三层分工与统一生产链（2026-09-17 操作者指令）

项目的开发与运行按三层分工，**三层不可互换**：

| 层 | 回答什么 | 负责 |
|---|---|---|
| **External Knowledge** | 别人已经知道怎么玩 | 页面入口 / 跳转顺序 / 页签结构 / 按钮区域 / ROI / 行距 / OCR 文本 / enabled·disabled / 成功后的页面变化 / 前置条件 / 队列逻辑 / 免费次数 / 冷却 / Rally·Bear·Arena·Pet·Alliance 等玩法机制 / 失败恢复方式 |
| **MAA**（默认 UI Engine） | 怎么可靠地看和点 | Screenshot / Fast Capture / TemplateMatch / FeatureMatch / ColorMatch / ROI Search / Button Locate / Page Detect / Click / Swipe / Back / Wait Page / Wait Button Appear·Disappear / Retry / UI Recovery / Debug Draw |
| **V2** | 为什么做、做什么、是否成功 | WorldState / Goal / Strategy / Planner·Gameplay Commander / ResourceBank / Event Planning / Scheduler / Skill semantics / Verifier / Recovery policy / Knowledge / Experience·Learning / Capability Lifecycle |

优先使用既有接入：`MaaExecutorAdapter` + `ExecutorRouter` + `backend_routing.json`；
默认 **MuMu EmulatorExtras Capture + MAA Action**。

**禁止重新实现** `ADB screenshot` / `ADB tap` / 手写全屏模板搜索 / 手写 retry loop /
手写 wait-page / 手写 wait-disappear —— **除非 MAA 真实失败且有证据**。
文字·数字 → **RapidOCR**（当前 MAA OCR bundle 不完整）；图标·页面·按钮·颜色 → MAA。
**禁止让 Qwen 做像素级定位。**

⚠ 识别轴仍按 **§2b 的实测结论**逐语义、按证据决定：MAA 全帧识别比 V2 固定 ROI 慢 3.3×，
且 `OPEN_INTEL` 有过一次真实回归。本节说"MAA 负责识别"是指**能力已具备、默认入口**，
不是要求每一处都强制切换。**不为了"必须用 MAA"而伪造更好结论。**

标准生产链（唯一）：

```
External / Local Knowledge → WorldState prior → V2 Goal/Planner/Brain
→ V2 Skill semantic → MAA Capture → MAA Recognition → RapidOCR（如需文字）
→ MAA Action → V2 Verifier → WorldState Update → Replan
```

一句话：**Knowledge 告诉它「怎么可能做」，V2 决定「现在做不做」，
MAA 负责「把动作可靠执行出来」，Verifier 证明「到底成功没」。**

### 外部知识的定位：Prior，不是 Production Truth

**允许**：同游戏、同分辨率（720×1280）的外部测量**直接作为 Candidate Prior**
——坐标 / ROI / 行距 / 页签顺序 / 按钮区域。先在当前客户端验证：
**对 → 采用；偏 → 校准；错 → 淘汰。**

**禁止**：把外部实现当成已完成的 Production 路径；外部只提供
`Navigation / Recognition / Action / Verification / Recovery` 五要素作先验，
必须在当前客户端用真机探针过一遍。复制外部**代码**仍受 §10 约束（许可证优先）。

### 新 Capability 默认五步

```
1 Local Reuse Check     skill / brain route / verifier / knowledge / legacy evidence / MAA node
                        → 已有成熟实现：直接复用（先跑 tools/reuse_check.py <CAPABILITY>）
2 External Prior Check  knowledge/external/external_capability_map.json
                        → 读记录的 source_files，提取
                          Navigation / Recognition / Action / Verification / Recovery
3 MAA Fast Probe        只验证：入口对不对 / 按钮在哪 / 页面顺序 / 模板是否匹配 /
                        颜色·文字是否一致 / 成功状态是什么 —— 不重新探索整个 UI
4 Minimal V2 Adaptation 只补真正缺的：Skill / WorldState field / Brain decision / Verifier / Recovery
                        （禁止新增第二 Scheduler / Vision Engine / Registry / 无必要 Manager）
5 Live Verify           真实动作 + 真实页面变化 + Verifier PASS + Evidence
                        → LIVE_VERIFIED → catalog → commit → push → 下一 Capability
```

### 时间预算（Lane）

| Lane | 范围 | 预算 |
|---|---|---|
| **Fast** | 免费领取 / 打开页面 / 切页签 / Mail / VIP / Alliance Help / Pet 免费日常 / Arena 免费次数 | **20–45 分钟** |
| **Normal** | BUILD / RESEARCH / TRAIN / HEAL / PROMOTE / GATHER / RALLY | **45–90 分钟** |
| **Strict** | 真钱 / 账号安全 / 不可逆操作 / 大额宝石 / 高风险 PvP / 状态转移 | 门禁不放宽（§8） |

**15 分钟规则**：任何 UI Capability，15 分钟后仍在「找按钮 / 猜页面 / 写截图逻辑 /
写点击逻辑 / 写 retry / 写模板搜索」→ **立即 STOP**，转 External Prior Check + MAA Tool Check。
**禁止继续手搓。**

### AI 指挥中心（Gameplay Commander）的边界

只决定：当前做什么 / 今天做什么 / 活动何时插队 / 资源怎么分配 / 哪个 Goal 优先 /
哪些任务延期 / 哪些状态触发 Replan。

**不得**：点坐标 / 写 UI 流程 / 替代 Scheduler / 替代 Skill / 替代 MAA。

```
Gameplay Commander → Goal Plan → 唯一 Scheduler → Skill → MAA → Verifier
```

---

## 3. Goal 与 Skill 的边界

- **Goal = WHAT**（`GoalLibrary` / `RuleBrain` 决定做什么）
- **Skill = HOW**（Skill 定义怎么做）
- **Vision 与 Qwen 永不点击。** 点击只能由 `Executor` 经 Skill 发出。

禁止把两者重新混回去：不要在 Skill 里写业务目标，也不要在 Goal 里写像素坐标。

---

## 4. Universal Skill 原则

Skill 认识的是**语义 / 状态 / 目标 / 参数**，不是固定像素。

- 正确：`SELECT_RESOURCE(resource_type)`
- 错误：`CLICK_WOOD_AT_840_305`

Skill schema 至少包含：
`skill_id, semantic_goal, parameters, context, preconditions, semantic_requirements,
vision_evidence, execute, verifier, recovery, resource_cost, risk, latency_class,
unknown_policy, ui_change_tolerance, lifecycle`。

**Lifecycle 严格分级**（禁止跳过）：
`MISSING → DEFINED → CANDIDATE → LIVE_TRIED → LIVE_VERIFIED → STABLE`，另有 `BLOCKED`/`DEGRADED`。

- `STABLE` 必须来自：足量真实尝试 + 高成功率 + 可靠 Verifier + Recovery + 低误报。
- 禁止 `CODE EXISTS → STABLE`。
- 禁止用「已实现 / 完成 / 稳定 / 生产可用」描述没有真机证据的能力。

---

## 5. Vision：Semantic First（但不是不要 Template）

正确优先顺序：

```
Page Context → Semantic Anchor → Relative Layout → Button State → OCR
→ Template / Icon → Historical ROI → Absolute Coordinate
```

- 成熟稳定的 **Template + ROI 允许直接作为 Production Fast Path**。
- Semantic Vision 负责泛化与 UI Drift。Qwen 只处理最后的 ambiguity。
- OCR 角色固定为 `TEXT_RECOGNITION_ONLY`。
- **坐标必须可自证**：能用锚点+相对布局推出的，不要写死。
  （本项目已因写死页签坐标付出代价：`SELECT_RESOURCE` 44 次只成功 3 次。）
- 任何「选中/未选中」判断必须有页面门控，否则会在无关页面上产生高置信误报。

## 6. Verifier First

**绝对禁止「点击成功 = Skill 成功」。** 必须：

```
Action → State Change → Verification
```

- `CLAIM_REWARD`：执行前 `claimable=true`，执行后 `claimable=false`（或按钮消失/红点变化/物品变化）。
- `SEND_MARCH`：成功意味着 **march state 实际变化**，不是 ADB 没报错。
- 活动评分动作必须验证 `points_before → action → points_after`，且 `points_after > points_before`。
  不要因为「训练成功」就默认「活动积分成功」。
- Verifier 不应把无关的观测塞进自己的条件里（会让一个脆弱读取拖垮整条判定）。
- 失败原因必须**可区分**：两个根因不同的缺陷不得共用同一个 reason 字符串。

## 7. Recovery 与 AUTO 不中断

以下全部**不能**停止整个 Agent：

```
NOT_PROVEN / NOT_VERIFIED / SEMANTIC_TARGET_NOT_FOUND / TARGET_NOT_FOUND
UNKNOWN_PAGE / UNKNOWN_POPUP / NOT_REFRESHED / QUEUE_FULL / MARCH_FULL
RESOURCE_SHORTAGE / EVENT_CLOSED / CANDIDATE_FAILED / VERIFY_FAILED / ENVIRONMENT_BLOCK
```

正确流程：`Recover → Bounded Retry → Defer/Skip → Next Goal`

只有以下允许停止 AUTO：用户主动 Stop、不可恢复 ADB、不可恢复 MuMu、游戏无法恢复、
Runtime Fatal、真实支付风险、账号安全风险、不可恢复数据破坏。

**普通 Skill Failure 不允许杀死 AUTO。** Watchdog 可以重启 Worker，但
watchdog 不得掩盖根因——每次异常退出都必须保留完整证据
（exception type / message / traceback / current goal / skill / last screenshot /
last worldstate / thread state / runtime state）。

`unexpected_worker_exits` 只能统计**真实的 worker 线程崩溃**，
环境类失败（模拟器未连、ADB 掉线、用户停止）不计入。**禁止为了数字好看而清零。**

## 8. 安全红线（永久）

必须阻止并要求确认：

- 真实货币支付 / 真实购买  → **永久阻断**，不可由配置放开
- 账号删除 / 角色删除 / 账号安全修改
- 系统级高风险破坏操作

用户策略：**只要是免费、无选择、无成本奖励，直接领**，无需先认识奖励名字/图标/数量。
`UNKNOWN_REWARD ≠ UNKNOWN_ACTION`。但真实支付永不触碰。

游戏资源可策略性使用（普通资源 / 加速 / 钻石 / 活动资源 / 道具），
每次支出必须记 `resource, amount, reason, expected_value, before, after`。

## 8b. DEVELOPMENT_VALIDATION 权限策略（2026-09-17 操作者指令）

**当前项目处于开发与真机验证阶段。** 开发阶段的优先目标是
**快速发现问题 / 快速触发真实状态 / 快速完成 Capability Live Verify**，
**不得用 Production 级保守策略阻塞开发**。

### 风险等级（T0–T4）

| 等级 | 内容 | 开发阶段行为 |
|---|---|---|
| **T0** | 观察、导航、领取免费奖励 | 自动执行 |
| **T1** | 普通日常、免费次数、联盟帮助 | 自动执行 |
| **T2** | 体力、普通资源、训练、研究、建筑、普通道具 | 开发阶段**自动执行** |
| **T3** | 较大 Gem 消耗、PvP、重要行军召回、Teleport、高价值稀有道具 | **允许"有界尝试"**：单次预算 + 明确目的 + Evidence + Verifier |
| **T4** | 真钱、账号安全、删除、不可恢复账号操作 | **永久禁止**（§8 不变） |

### 开发阶段允许主动做（不再需要等自然状态）

打开/关闭页面 · 点击未知但低风险 UI · 切换页签 · 浏览活动/商店/背包/英雄/建筑/科技/联盟页面 ·
领取免费奖励 · 使用免费次数 · **为验证消耗体力** · 打野兽 · 做情报 · 采集 · 派遣行军 ·
**主动召回采集行军** · 重新派遣 · 开始普通训练 · 晋升士兵 · 治疗伤兵 · 开始普通研究 ·
开始普通建筑升级 · 联盟帮助 · 联盟科技贡献 · 加入 Rally · 发起普通 Rally ·
Arena 免费挑战 · Pet 免费日常 · Exploration · Labyrinth · 正常使用普通游戏资源 · 正常使用加速道具 ·
**为验证功能主动腾出队列**。

允许 `dispatch → verify → recall → verify → next test`，**不必等数小时自然返回**。

### 资源权限（开发阶段放宽）

普通资源 / 体力 / 普通加速 / 普通道具：允许为 Capability 验证主动消耗。
Gem：允许**小额、可控、可追踪**使用。

**每一次支出都必须记** `reason / amount / capability / before / after`（§8 的 ledger 要求不放宽）。
**不要因为"可能消耗一点资源"就完全不测试功能。**

### 主动制造验证条件（§五）

开发阶段允许主动创造：空闲行军槽 / 空闲训练队列 / 空闲研究队列 / 空闲建筑队列 /
Arena 可执行状态 / Rally 测试状态 / Gather 测试状态。

**`WAITING_FOR_NATURAL_STATE` 只保留给真正无法安全制造的状态**：
伤兵必须真实存在、活动尚未开放、Bear 尚未开始、特定奖励尚未刷新。
行军槽 / 体力 / 普通采集 / 普通训练 / 普通研究 / 普通建筑 / 普通 Rally / 普通页面状态
**应优先主动构造**，不要等。

### 开发模式与生产模式分开（§七）

| 模式 | 目标 | 允许 |
|---|---|---|
| **DEVELOPMENT_VALIDATION** | Capability Coverage / Root Cause / Live Verify | 主动试错 |
| **PRODUCTION** | 长期稳定 / 资源效率 / 低风险 / 无人值守 | 收紧 Gem 预算、加速使用、资源储备、PvP、Recall、高价值道具 |

⚠ **`config/v2.json` 的 `production: true` 与这里的"模式"不是同一件事**：
前者是**真机动作的解锁互锁**（`run_live.py` 要求 `production=true && dry_run=false`），
关掉它等于不能跑真机。开发/生产的区别体现在**资源预算与风险等级**，不是关掉互锁。
`config/v2.json → development_validation` 是本节的机器可读落点。

### 最高原则（§八）

> 开发阶段：「**可恢复的游戏资源损失**」通常低于「**一个 Capability 永远无法验证**」的成本。

因此：**能恢复 / 能记录 / 非真钱 / 非账号安全 / 非不可逆 → 允许主动尝试。**

---

## 9. Legacy 的正确定位

旧 Winter Agent OS **不允许**成为 V2 基础。**禁止 import 旧生产架构。**

Legacy 只作为**证据矿**（Legacy Miner）：真实截图、模板、图标、ROI、OCR 关键词、
ADB 工具、MuMu Recovery、MAA 执行经验、导航经验、Verifier、真实成功路径、
真实失败日志、Failure Pattern。

禁止恢复：旧 Manager / 旧 Scheduler / 旧 Registry / 旧学习系统 / 旧多角色复杂架构。

## 10. 外部项目：必须真正借鉴

- 外部项目默认 **REFERENCE_ONLY**，不得复制代码/坐标/截图/图标/账号数据。
- 未知许可证 → 仅 REFERENCE_ONLY。
- 允许 Best-of-Breed（A 项目导航 + B 项目 OCR + C 项目 Verifier + Legacy MuMu Recovery + V2 Goal/Scheduler），
  但**不得整套照搬别人架构**。
- 若许可证允许复用纯工具代码，必须保留 `source / license / version-commit / provenance`。
- 研究必须**由真实失败驱动**，不要漫无目的爬 GitHub：先看 Top Failure / Top Failed Skill /
  Top Goal Blocker，再问「别人是否已经解决这个问题」。
- 外部研究的成果定义（至少满足一条）：新增 Live Verified 能力 / 提高成功率 / 降低 latency /
  提高 Recovery / 消除高频 Failure Pattern。
  只增加报告、只下载 repo → **NO_PRODUCT_VALUE**。

## 10b. WorkBuddy 升级通道（2026-09-17 操作者指令）

V2 自己撞墙时（新玩法 / 新 UI / 反复真机失败），可以**把一条 capability 交给本机
WorkBuddy 后台 agent**，而不是耗完 timebox 然后停下。

- 传输 = **官方 HTTP gateway**（`codebuddy --serve` 的 `/api/v1/jobs` 族）。
  **禁止第三方代理**；四个操作只有 `is_available` / `submit` / `status` / `cancel`。
  实测契约见 `knowledge/failure_patterns/integration/WORKBUDDY_GATEWAY_CONTRACT.md`，
  操作步骤见 `docs/WORKBUDDY_BRIDGE.md`。
- **只有五种情况允许升级**：`CAPABILITY_MISSING` / `UNKNOWN_UI` /
  `UNKNOWN_GAME_MECHANIC` / `REPEATED_LIVE_FAILURE` / `STUCK_15_MIN`。
  **普通游戏 Tick 禁止调用 WorkBuddy**，`submit` 在联网前就拒绝。
- 凭据**只存环境变量** `CODEBUDDY_GATEWAY_PASSWORD`。**禁止进入仓库**，
  禁止写进 `config/v2.json`（`workbuddy_bridge.py` 根本不读该文件）。
  注意：**面板进程也要能看到这个变量**，否则 AUTO 只能建单（记为 `QUEUED`）而发不出。
- 工作目录固定 `E:\无尽冬日智能体`；`bgIsolation=none`（否则 agent 的提交落在
  临时 worktree，V2 永远看不到，而升级会"报告成功"）。
- 升级 **不是** 停机理由：gateway 不可达 → 记 `GATEWAY_UNREACHABLE` → 继续本地开发。
- 收到结果后仍须由 **V2 的 verifier + 真机 episode** 判定，升级方自述不算证据。

## 10c. 升级队列：AUTO 发现，队列限流，WorkBuddy 异步修（2026-09-17 操作者指令）

三层分工，**AUTO 永不等待 WorkBuddy**：

```
AUTO runtime      发现问题、建单、继续玩
Escalation Queue  去重 / 并发 / 预算 / 冷却 / 状态
WorkBuddy Bridge  异步派发（只传输）
WorkBuddy Agent   自己的进程里干活
```

- **禁止 AUTO 同步等 WorkBuddy**：hook 在 `run()` 返回后（动作已结束）执行，
  **只**做"对账已结束的 job + 交出不超过并发上限的决定"，然后返回。
- **去重键** = `capability | failure_type | skill`，一个键同时只允许一个 active job。
- **`max_concurrent_jobs = 1`**：禁止两个 agent 同时改同一仓库。
- **修复预算**：同一签名第一次免费，之后每次失败算一枪，用尽 → `BLOCKED + COOLDOWN`
  → AUTO 转下一个 Capability。**禁止 Runtime ↔ WorkBuddy 无限修复循环。**
- **普通天气永不升级**（按名拒绝）：`mail_all_clear` / `QUEUE_BUSY` / `NOT_REFRESHED` /
  `RESOURCE_SHORTAGE` / `EVENT_CLOSED` / `RALLY_FULL` / `WAITING_FOR_NATURAL_STATE` 等。
- **job DONE ≠ Capability 成功**：只有"真机 episode（带 `recorded_at` + `verifier_ok` + 证据）
  且时间晚于派发"才算 `LIVE_VERIFIED`；只改代码 + 过闸门只能记 `TEST_PASS`，
  且解释里必须写明"这不是已验证能力"。
- **一个台账** `learning/workbuddy_escalations.jsonl`，状态是事件流的 **fold**。
  禁止再建第二个 store/registry。
- 代码变更 → 写 `RUNTIME_RELOAD_REQUIRED` 标记；面板 `start()` 在标记新鲜或 job 仍活跃时
  延后启动（每轮 worker 是新子进程，代码自然生效，**不需要也不允许新建 Runtime Manager**），
  **但 15 分钟上限后必须放弃延后**，绝不让卡住的开发 agent 拖停游戏运行时。
- 模型路由：**最小阶梯**，不新增 Model Manager。
  `deepseek-v4.1-flash` → `glm-5.3-flash`（长上下文/大日志/跨文件）→
  `hy4-preview-f`（视觉，或前两者失败后的第二意见）→ `deepseek-v4-pro`（兜底）。
  只有当前档在时间盒内**没有 Live Improvement** 才升档；每次 job 记录
  `model / model_reason / escalated_from / duration / result / live_improvement`。

## 11. Candidate 不能永远不执行

若 Candidate 满足：Preconditions 完整 + Execute 已实现 + Verifier 存在 + Recovery 存在 + 风险允许
→ **必须进入 Live Attempt Pool**。低风险自动尝试，中风险限频/限资源，高风险谨慎。

失败处理：`Classify → Recovery → Bounded Retry → Skip → Next Goal`。
不得因为 `NOT_PROVEN` 就永远不尝试。

## 12. 免费奖励 / 资源策略

- 免费 + 无选择 + 无成本 → 自动领取。
- 真实货币 → PERMANENTLY_BLOCKED。
- ResourceBank 至少分：Immediate / Queue Reserve / Event Reserve / Rare Reserve / Daily Cap / Spendable。

## 13. Goal Engine 与 Deadline

Goal 不是固定 Task List。根据 WorldState / Queue / March / ResourceBank / AttemptState /
Active Events / Deadline **动态发现** Goal。

优先级 = `Deadline Pressure + Reward + Daily Loss + Event Synergy + Development Value
- Resource Cost - Risk`

`EVENT_MINIMUM_GUARANTEE` 是**系统 Goal**，不是活动脚本。通用流程：
`DISCOVER → READ RULES → READ PROGRESS → SELECT TARGET → CALCULATE GAP → PLAN → EXECUTE
→ VERIFY POINTS → REPLAN → TARGET COMPLETE → CLAIM`。
活动通过已有 Universal Skills 完成，**禁止大量生成 `EVENT_X_SCRIPT`**。

## 14. Bear / Rally 模型

统一 `START_RALLY(target, context)` 与 `JOIN_RALLY(target, context)`。

- `JOIN_RALLY` 用普通行军队列。
- `START_RALLY(BEAR)` 用 Bear 特殊发起队列。
- **普通行军队列满，不能错误阻止 `START_RALLY(BEAR)`。**

WorldState 需要：`normal_march_slots / normal_idle_slots / bear_rally_special_slot /
bear_rally_special_available`。

## 15. REALTIME 延迟等级

Bear / Rally 等实时操作 `latency_class = REALTIME`。REALTIME 路径**尽量禁止**：
全屏 OCR、外部研究、长时间 Qwen、Auto Improvement、生成报告。
优先：Local ROI / Template / Cached State / Known Layout / Fast Verifier。

## 16. Qwen 的正确角色

Qwen **不负责**：鼠标点击、ADB、MAA、OCR、Template Matching。
Qwen **负责**：Goal Planning、Event Strategy、Resource Strategy、UNKNOWN 解释、
Failure Analysis、Escalation。

- 不要人为增加 Qwen 调用次数。
- 调用时只提供 `DecisionPacket`：Current WorldState / Active Goals / Deadline / ResourceBank /
  Relevant Knowledge / Recent Failures / Current Decision Problem。
  **禁止塞入**整个日志、整个 Knowledge Base、整个历史对话。
- 输出结构化：`decision, goal, recommended_skill, parameters, confidence, reason_codes,
  alternatives, risk`。
- Qwen timeout / offline / invalid output → **必须 fallback，不能停止 Agent**。

智能层级：L1 Rules → L2 Knowledge+Experience → L3 Local Qwen → L4 External Research。
长期目标：大部分任务走 **L1 + L2**。

**当前不优先微调模型。** 真正瓶颈是 Vision / Skill / Verifier / Recovery / Runtime Reliability。
持续积累未来训练数据即可（WorldState + Knowledge + Goal + Decision + Action + Verifier Result）。

## 17. 测试体系

必须区分：`Unit` / `Replay` / `Regression` / `Evidence Integrity` / `Live`。

- Unit PASS = 代码逻辑正确
- Replay PASS = 历史帧正确
- **只有 Live PASS 可以推进 Live Lifecycle**

**不要为了测试全绿而破坏生产逻辑。** 若旧测试与当前正确设计冲突，先判断测试是否过时；
测试应该保护正确行为，不是为了让 PASS 而恢复错误行为。
历史 Episode 与历史截图**不得篡改**。

## 18. Evidence 与 Retention

- 证据命名必须唯一且自描述：
  `{episode_id}_{step_id}_{before|after}_{timestamp}.png`
- 每个 Episode 保存：`episode_id, goal_id, skill_id, step_id, timestamp, before_screenshot,
  after_screenshot, world_state_before, world_state_after, verifier_result, failure_type,
  recovery_result`。
- 数据生命周期：`RAW → AUTO_LABEL → CANDIDATE → VERIFIED → HARD → REJECTED`
- Retention **永远不能删除**：VERIFIED / Production referenced evidence / Regression fixture /
  Verifier calibration frame。`dataset/verified/` 与 `dataset/production/` 是长期保留区。
- **Evidence Integrity Test：任何被引用证据不存在 → FAIL。**

### 18b. 记忆写入路由（2026-09-14 增补，防双事实源）

项目存在两个记忆路径，职责必须严格区分：

| 路径 | 职责 |
|---|---|
| `.workbuddy-ai/memory/` | **唯一长期事实源**：MEMORY.md（蒸馏后的长期知识）+ YYYY-MM-DD.md（当日流水） |
| `.workbuddy/memory/` | WorkBuddy 宿主注入的会话工作路径：**只写当日流水与自动化记忆，视为缓存** |

规则：

1. 长期知识（架构决定、环境铁律、操作者偏好、蒸馏教训）**只写**
   `.workbuddy-ai/memory/MEMORY.md`；宿主路径不写长期知识。
2. `.workbuddy/memory/MEMORY.md` 只放指针，指向上述事实源。
3. 每日日志追加式；超过 30 天的日志按主题蒸馏进 MEMORY.md，
   原文移入 `.workbuddy-ai/memory/archive/`（移动，不删除）。
4. 当前现场只信 `.workbuddy-ai/handoff/`；`learning/` 是机器态，人只读。
5. 详细分层设计见 `docs/MEMORY_ARCHITECTURE_2026_09_14.md`。

## 19. 知识与模型分离

知识存 `knowledge/`，Qwen 只学「如何根据知识决策」。
以后换模型不应导致游戏知识丢失。知识优先级：

```
LIVE_CLIENT > LIVE_VERIFIED > OFFICIAL > MULTI_SOURCE_CONFIRMED
> COMMUNITY_DATABASE > GUIDE > LEGACY > UNKNOWN
```

**游戏当前客户端永远拥有最高 UI 事实权。**

## 20. 开发方式（重要）

- **失败优先开发**：选任务看 `CurrentFailureImpact × UsageFrequency × AffectedGoalPriority
  × ExternalMaturity × IntegrationEase`。
  不要按文件目录、想到什么做什么、哪个模块代码看起来漂亮来排序。
- **不重复重写已经 Live Verified 的能力。** 现有代码分类为
  `KEEP / IMPROVE / REFERENCE_ONLY / DEAD_CODE / DISCARD`，
  判断标准是真实成功率、Verifier 质量、Recovery 质量、执行延迟、长期稳定性，**不是谁写的**。
- **Live Improvement > Report。** 文档只为 CURRENT TRUTH / Coverage / Failure / Evidence /
  Architecture Boundary 服务。禁止每轮产出大量 Markdown 但 0 Live Try。
- **禁止虚假完成**：Replay Success ≠ Live Success。
- **不逐步询问用户确认。** 不要每完成一个 Skill / Phase 就停下来问「是否继续」。
  自动继续下一最高价值任务。只有真正无法自动判断的危险操作才询问。
- **除非触发明确安全红线，不要停止等待用户确认。**
- 每次 Patch 后必须回答：真实成功率提高了吗？Recovery 提高了吗？Latency 降低了吗？
  Goal Coverage 增加了吗？人工干预减少了吗？
- 清理/删除文件时：**先列清单、逐项确认**，禁止按目录或通配符批量删除。
  （本项目已因按 `_` 前缀批量删除而**不可恢复地**丢失 15 个脚本。）

## 21. 汇报格式

不要先告诉用户改了多少文件。优先报告：

```
【Runtime】真实运行时长 / Unexpected Worker Exits / Watchdog Restarts / Fatal Stop
          / ADB Recovery / MuMu Recovery
【Goals】Fully Live Verified / Partial / Never Tried / Blocked
【Skills】Live Attempts / Success / Failure / Success Rate
          / New Live Verified / Stable / Degraded
【Top Failures】Failure / Count / Affected Goals / Root Cause / Fix / Before / After
【Commercial Bot Parity】x / 21
【本轮真实新增】例如 SELECT_RESOURCE 68% → 97%、MARCH_PAGE_NOT_OPEN 59 → 7
```

## 22. 72 小时验收标准

AUTO 连续运行 ≥72h，且：

- `unexpected_worker_exits = 0`
- 普通 Failure 不停止 Agent；Skill Failure 自动 Recovery / Skip；Goal Failure 自动继续下一 Goal
- 免费奖励正常领取；训练/建筑/科研尽量保持工作；采集持续运行
- Intel 自动执行；竞技场免费次数正常使用；联盟日常正常处理
- Deadline Goal 不严重漏掉；MuMu 与 ADB 小异常可恢复
- UNKNOWN 不执行高风险猜测
- **真实支付永远不会发生**

达成后开始 5–7 天 Soak。

## 23. Codex Commander Queue（2026-09-15 增补）

Codex 是低频的「指挥官」：它不在线时，WorkBuddy 必须能自己把队列跑下去。
接口是机器可读的，**不允许要求操作者手工复制指令**。

`E:\无尽冬日智能体\.workbuddy-ai\commander\`
| 文件 | 谁写 | 作用 |
|---|---|---|
| `WORK_QUEUE.json` | **Codex 写** | 正式任务接口，含 `priority` / `dependencies` / `files_scope` / `do_not_touch` / `acceptance` / `timebox_minutes` / `status` |
| `results/<task_id>.json` | WorkBuddy 写 | 每个 Work Order 的回报 |
| `EXECUTION_STATE.json` | WorkBuddy 写 | 队列执行状态（唯一写入方是 `tools/cq.py`） |
| `BLOCKED_QUEUE.json` | WorkBuddy 写 | timebox 内做不到的任务 |
| `REVIEW_REQUESTS.md` | WorkBuddy 写 | 需要 Codex 高级分析的问题 |

**接管后必做**（`START_HERE.md` 第 3.5 步）：

```bash
"C:/Users/xhw/.workbuddy/binaries/python/versions/3.13.12/python.exe" tools/cq.py init
"C:/Users/xhw/.workbuddy/binaries/python/versions/3.13.12/python.exe" tools/cq.py plan
```

**可执行判据（两个都要满足）**：`status == "READY"` **且** `dependencies` 里每一项都已有终态。
`QUEUED`（Codex 有意压着）与 `WAITING_FOR_NATURAL_STATE`（需要真机自然到达的状态）
**不是可执行任务**，不要为了"完成任务"而去制造那个状态。

**排序**：`priority`（P0<P1<P2）→ 队列内声明顺序。

**每个 Work Order 固定十步**：
`READ EVIDENCE → TOOL CHECK → IMPLEMENT → TARGETED TEST → REPLAY → LIVE → VERIFY → BEFORE/AFTER → REPORT → NEXT`
报文字段固定为：
`TASK_ID ROOT_CAUSE CHANGED_FILES TEST_RESULT LIVE_ATTEMPTS LIVE_SUCCESS LIVE_FAILURE BEFORE AFTER VERIFIER_RESULT EVIDENCE PATCH_STATUS REMAINING_ISSUE NEXT_RECOMMENDATION`

`cq.py finish` 会**拒绝**缺少必填字段的回报；`--require-live` 再拒绝没有 `LIVE_EVIDENCE`
却宣称完成的回报。**队列不会让虚报变便宜。**

**timebox 到了就承认，然后换下一项**：`cq.py block <id> --result <file>`，
内容必须含 `root_cause_found` / `attempts` / `changes_made` / `evidence` / `blocker` /
`recommended_codex_review`。**禁止死磕，禁止停下来问操作者。**

**队列不豁免本文件任何铁律**：架构冻结（§2）、真机证据（§6/§18）、
付费红线（§8）、不伪造完成（§20）在队列任务内**同样生效**。
若队列任务与铁律冲突（例如要求改冻结架构），**不执行**，改写进 `REVIEW_REQUESTS.md`。

**队列任务的 target_metric 由 Codex 依据当时的 handoff 写出，可能过时**：
执行时必须用生产证据核对它。**做不到就如实写 REMAINING_ISSUE，不要为了对齐指标而粉饰。**
