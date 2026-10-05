# 规则文档诊断报告

> 审计对象：`docs/MASTER_RULES.md`（用户指定）
> 报告性质：**诊断，不改文档**。`docs/MASTER_RULES.md` 的 md5 与审计开始时一致
> （`66a2abb4a4d62c67eaef37411294ce52`），本轮**未做任何修改**。
> 生成时间：2026-10-05 23:56

---

## 0. 先修正审计范围：三件文件层面的事实

用户让我审两份文档。事实是：

### 0.1 `docs/WorkBuddy_Persistent_Development.md` 不存在

```
ls: cannot access 'docs/WorkBuddy_Persistent_Development.md': No such file or directory
```

它的内容不是独立文件，而是 `docs/MASTER_RULES.md` 的 **`# 第二节 ·《持续开发，不许停》全文`**（第 3411–3524 行）。
依据：`docs/CURRENT_STATE.md:272` 把该文件名登记为「两份全文的逐字副本」。

**所以「两份文档」实际是「一个文件里的两节」。**

### 0.2 这个副本不是当前生效的规则全集 —— **本次审计最重要的发现**

仓库里有 **两套编号互不相同、内容不互相包含**的规则：

| 文件 | 规模 | 编号体系 | 定位 |
|---|---|---|---|
| `.workbuddy-ai/commander/WORKBUDDY_AUTONOMOUS_DEVELOPMENT_FINAL.md` | 42,761 B | `# 0.`–`# 72.` = **73 条** | 《FINAL》原文 |
| `docs/MASTER_RULES.md` 第一节 | 51,771 B（含第二节） | `# 0.`–`# 72.` = **73 条** | 上面那份的**忠实副本**（编号逐条对齐，无增无减） |
| `.workbuddy-ai/handoff/00_MASTER_RULES.md` | 60,125 B | `## 0.`–`## 28.` + `24.1–24.6 / 25.1–25.6 / 26.1–26.5 / 27.1–27.5 / 28.1–28.6` = **29 个规则块** | **另一套规则**，2026-09-14 ~ 10-04 逐条增补 |

`docs/MASTER_RULES.md` **不包含**下面这些只存在于 handoff 文件的规则（实测 0 命中）：

| handoff 规则 | 自述优先级 | `docs/MASTER_RULES.md` 命中数 |
|---|---|---|
| §24 项目宪法 A：禁止坐标硬编码 | 自标 **「优先级最高」** | `禁止坐标硬编码` → **0** |
| §25 项目宪法 B：UI 元素是基本单位 | 与 A 同次修订 | `项目宪法` → **0** |
| §2d 四层核心架构 | **「禁止再重构顶层架构」** | `四层核心架构` → **0** |
| §2b 工具优先 | **HARD RULE** | `工具优先` → **0** |
| §8b DEVELOPMENT_VALIDATION 权限策略（T0–T4） | 开发期资源权限 | `DEVELOPMENT_VALIDATION` / `T0` → **0** |
| §18b 记忆写入路由 | 防双事实源 | `记忆写入路由` → **0** |
| §15 REALTIME 延迟等级 | — | `REALTIME` → **0** |
| §22 72 小时验收标准 | — | `72 小时` → **0** |
| §26/§27/§28 存储路径 / 分支主线 / 指令翻译 | 2026-10-04 指令 | `时间预算` / `五步` → **0** |

**结论：你让我审的这份，是规则的「半套」。** 另外半套（29 块）在 handoff 文件里，而且
**项目自己的记忆指针就指向它** —— `.workbuddy/memory/MEMORY.md` 写的是
「规则全文见 `.workbuddy-ai/handoff/00_MASTER_RULES.md`」。

这不是文书瑕疵，是**已发生的实际后果**：本会话我在做巨熊探针时写死了 `(669,173)` 去点
「常规活动」页签。按 handoff §24.2 硬禁止第 1 条，那是**生产路径禁止的固定像素坐标**，
而 handoff §24 自标「优先级最高、不设生产点击例外」；
按 `docs/MASTER_RULES.md`，**这条约束根本不存在**，我据此判定自己没有违规。
两套规则给了相反答案，而我当时只读了其中一套。

### 0.3 `docs/MASTER_RULES.md` 未纳入 git

```
git status --porcelain docs/MASTER_RULES.md  →  ?? docs/MASTER_RULES.md
```

**未被 git 跟踪。** 意味着这份文档无法 diff、无法追溯是哪个版本、也无法证明它和
commander 原文是否一致（本次靠 `# 0.`–`# 72.` 逐条对齐人工确认的）。

---

## 1. 当前规则总数

| 计数口径 | 数量 |
|---|---|
| `docs/MASTER_RULES.md` 第一节《FINAL》编号规则 | **73**（`0.`–`72.`） |
| `docs/MASTER_RULES.md` 第二节《持续开发，不许停》分节 | **8**（一~八） |
| **用户指定审计范围合计** | **81** |
| handoff `00_MASTER_RULES.md` 规则块 | **29** |
| **工作区实际在用的规则块合计** | **110**（81 + 29，无编号重叠） |
| 另有 3 份互不同步的规则文件 | 42,761 B / 60,125 B / (副本) |

---

## 2. 三类分类结果

### 计数

| 类 | 含义 | 第一节(73) | 第二节(8) | 合计 |
|---|---|---|---|---|
| **A** | 核心，必须留 | 56 | 5 | **61** |
| **B** | 有用，但要简化 | 8 | 0 | **8** |
| **C** | 过期 / 冗余 / 冲突，应删 | 9 | 3 | **12** |
| | | 73 | 8 | **81** |

### 2.1 C 类明细（12 条，建议删除）

| 编号 | 规则名 | 删除理由 |
|---|---|---|
| §9 | 当前阶段：CAPABILITY_EXPANSION | 阶段标记写进"永久规则"里，无日期、无退出条件；同一优先原则 §58 已完整表达 |
| §11 | Learning Budget 不是机械时间切片 | 纯解释 §10，无任何可执行内容 |
| §13 | 高价值 UNKNOWN 是一等公民 | §14 是它的定义、§31 是它的动作；本条只剩口号 |
| §28 | Capability Coverage Matrix（13 状态） | 13 个状态中 8 个在代码里**零命中**；被实际实现的 6 值枚举取代（见冲突 C3） |
| §37 | Scheduler 模拟验收 | 与 §36 是同一件事的两份验收清单，且 §37 的两角色盘面被 §36 的 A–Q 完全覆盖 |
| §41 | 生产与学习同时进行 | 与 §8「AUTO 统一包含三种工作」同义；只剩一句"不要建分离世界" |
| §56 | 当前重点覆盖对象（18 项目标） | 手写清单，与 Goal Library 重复且已失真：实际代码报 **20 个 Goal**，命名体系完全不同 |
| §63 | MuMu GPU 分配 | `780M`/`Radeon` 全仓**只出现在规则文档里**；条件分支从未触发，从未测量 |
| §71 | 最终行为定义 | 逐句是 §61/§16/§34/§30/§6/§13/§24 的复述；只有最后一句愿景有独立价值，并入 §72 即可 |
| 第二节 二 | 每轮循环必须完整走完 | §42 已逐字列出同一 11 步；本节唯一增量（"不许在 Evaluate/Choose Next 停下"）应并入 §65 |
| 第二节 四 | 连续 3 轮无真实变化 = 自我审计 | 与 §44 B/C 判据重复，阈值还不同（见冲突 C8） |
| 第二节 八 | 自我驱动问题（每轮必问） | 与 §65 是同一个问题、同一串 KPI，字面几乎相同 |

### 2.2 B 类明细（8 条，保留但必须改写）

| 编号 | 规则名 | 问题 |
|---|---|---|
| §8 | AUTO 统一包含三种工作 | 作为 §7 的展开存在，60 行枚举；应压成 3 行 + 指向代码常量 |
| §10 | Learning Budget — 至少 50% | **头号规则却无任何度量**：`learning_share` / `LEARNING_SHARE` / `LEARNING_BUDGET` 全仓 0 命中。要么补度量，要么降级为方向 |
| §17 | Cooldown 默认基线 60s/10min/1h | 与代码不符（见冲突 C6）：实际是各子系统硬编码 1800 / 3600，无阶梯、无 60s 档 |
| §29 | Coverage 固定成熟度 L0–L5 | 名称与实现不符：代码是 `FULLY_LIVE_VERIFIED/PARTIAL/NEVER_TRIED/BLOCKED/DEGRADED/MISSING`（见冲突 C3） |
| §46 | Manual Intervention 长期指标 | 指标从未落地（见第 4 节 N1）。原则有效，数字不存在 |
| §62 | GPU / Model 资源原则 | 机器参数（32G/8G/15.6G）与"不许压到 6GB"已全部写进 `config/v2.json` 的实测注释，规则里重复一遍且会漂移 |
| §65 | 每完成一项后必须重新选择工作 | 应作为"重选工作"的**唯一**出处，但需吸收 §42-STEP11 尾、§66、第二节二尾、第二节八 |
| §66 | 不允许固定开发路线 | 独有内容只有"计划写着 Training 也要先修 Scheduler"，应降为 §43 的子条款 |

### 2.3 A 类（61 条，必须留）

第一节 A 类 56 条：
`0` 最高治理规则与 8 级优先级阶梯、`1` 项目最终目标、`2` 核心架构不变量、`3` Architecture Review 12 问、
`4` UNKNOWN 黑洞永久反例、`5` Goal Value/Readiness 解耦、`6` 所有启用 Goal 属于 AUTO、`7` AUTO≠Skill Runner、
`12` Learning 何时让路、`14` High-Value UNKNOWN 定义、`15` 动态 Learning Score、`16` 长期升权/短期退避、
`18` Cooldown 不是死锁、`19` 不能永久 CapabilityGate、`20` 不能永久 NOT_ACTIONABLE、`21` Safe Bootstrap、
`22` Bootstrap 允许行为、`23` UI-Venus 0→1、`24` Known 路径 0 模型、`25` Incremental Skill Acquisition、
`26` FIRST/SECOND ENCOUNTER、`27` Failed Attempt 也是知识、`30` Continuous Goal 的 L5、`31` NEVER_TRIED 升权、
`32` 过滤逻辑属高风险代码、`33` Role Session、`34` GLOBAL_WAIT 严格限制、`35` Idle 用于成长、`36` 调度防饥饿 A–Q、
`38` Safety 与 Liveness 同时证明、`39` Runtime 安全边界（真钱）、`40` Fishing 固定策略、`42` 每轮 11 步流程、
`43` 优先修共享根因、`44` Direction Error 触发器、`45` Production 验证周期定义、`47` Learning Funnel、
`48` 同一 UNKNOWN 不能无限烧模型、`49` Context 规则、`50` 当前帧一致性、`51` Venus 输出安全、
`52` COMPLETE 不能由模型决定、`53` Skill Repair、`54` Offline Learning、`55` Coverage 审计必须回答"为什么没做"、
`57` 可自主补什么、`58` 不要沉迷 95%→97%、`59` 真实验收覆盖不同 Gap、`60` Tests 不是终点、`61` AUTO 活性优先、
`64` Git 纪律、`67` 每轮 Design Review、`68` 每轮 Invariant Review、`69` 用户明确策略不能自行更改、
`70` 最终报告、`72` 最后一条永久原则

第二节 A 类 5 条：`一` 不停的定义、`三` 每轮必须落一个真实变化、`五` 进程异常不许躺下、
`六` 控制台必须实时反映、`七` 禁止"伪持续"

> A 类里有 3 条是**真钱/不可逆安全边界**，无论如何不能动：§39（真钱 PERMANENT 阻止）、
> §69（用户明确策略不可自改，含 Fishing ONLY NORMAL BAIT）、§64（禁止 `reset --hard` / `clean -fd` /
> `checkout .` / `restore .` / `add .`）。

---

## 3. 哪些规则冲突，冲突在哪

### 3.1 跨文件冲突（最严重，因为两套规则都自称权威）

**X1 — 资源花费权限，方向相反。**
`docs/MASTER_RULES.md` §39 要求「钻石 / 高价值道具 / 高价值加速 / 不可逆高风险动作 必须经过 Risk Gate」，
全文**没有 DEVELOPMENT_VALIDATION 概念**（0 命中）。
`.workbuddy-ai/handoff/00_MASTER_RULES.md` §8b 明确「**当前项目处于开发与真机验证阶段**」，
T2（体力/普通资源/训练/研究/建筑/普通道具）**自动执行**，Gem 允许「小额、可控、可追踪」使用，
并规定最高原则：「可恢复的游戏资源损失」低于「一个 Capability 永远无法验证」的成本。
→ 只读 `docs/MASTER_RULES.md` 会**过度保守而卡死开发**；只读 handoff 会**踩到 §39 的字面**。

**X2 — 优先级阶梯有两套，互不包含。**
`docs/MASTER_RULES.md` §0 的 8 级阶梯是：项目目标 > 不可逆安全与真钱 > ONE-* 不变量 > AUTO 活性 >
能力学习与覆盖率 > Production 证据 > 当前开发目标 > 示例/字段名/阈值。
其中**没有"禁止坐标硬编码"**；而 handoff §24 自标「**优先级最高**」。
handoff §2d 另有「四层核心架构，**禁止再重构顶层架构**」，docs 侧 `四层核心架构` 0 命中。
→ 同一个"最高级"有两个不同的第一名。

**X3 — 汇报格式两套。**
`docs/MASTER_RULES.md` §70 要求 ~25 个字段（HEAD/PROD_PIN/…/MANUAL_INTERVENTIONS_PER_24H/TOP_REAL_BLOCKERS）。
handoff §21 要求的是 `【Runtime】【Goals】【Skills】【Top Failures】【Commercial Bot Parity】【本轮真实新增】`，
且 handoff §28.5 规定「对操作者：**开工前一行**」。
两套格式都自称必须，没有任何一句话说明谁管谁。

**X4 — 外部模板的准入松紧相反。**
handoff §25.4：「不要求每张外部模板都先完成多轮真机验证，也不要求先建完整 Skill」。
`docs/MASTER_RULES.md` §53 + §60 + §26 要求：Candidate → Replay/Shadow → Live Verifier → Promotion Gate
才允许进 stable，且「Tests Passed ≠ 功能完成」。
（作用对象略有差别：模板 vs Skill，但两份文本都没有写这个 carve-out。）

### 3.2 文档内冲突

**C1 — 第二节的三处交叉引用指向已不存在的编号。**（位置精确）

| 位置 | 原文 | 指到哪 | 实际是 |
|---|---|---|---|
| `docs/MASTER_RULES.md:3422` | 「除**第62节**5种情况」 | §62 | 「62. GPU / Model 资源原则」 |
| `:3471` | 「按总指令**第 51 节**做全局审计」 | §51 | 「51. Venus 输出安全」（应为 §44 Direction Error） |
| `:3482` | 「按总指令**第 46 节** Tier 0」 | §46 | 「46. Manual Intervention 长期指标」（§46 无 Tier 0 概念；Tier 0 在 handoff §8b） |

→ 第二节是针对**旧编号**写的。**这三条引用目前全部失效**，且其中两条是"该停还是该继续"的
判定入口 —— 也就是说，触发条件本身不可解析。

**C2 — §36 vs §37：同一件事两份验收清单。**
§36 列 A–Q 共 17 个场景，要求证明 NO_STARVATION / NO_DEADLOCK / NO_INFINITE_RETRY / NO_FALSE_GLOBAL_WAIT。
§37 另给两角色盘面（Role A: 2 Known/2 Unknown/1 Blocked/1 Deadline；Role B: 1 Known/3 Unknown/1 Waiting）。
两份清单不互相覆盖也不互相引用。第三个变体在代码里：`tools/invariant_review.py:328` 的 `simulate()`
用的是 §17 的盘面。**同一概念三份口径。**

**C3 — §28/§29 vs 实际覆盖率模型：四套词汇。**
- §28 要求 13 个命名状态：`GOAL_EXISTS / SCHEDULER_VISIBLE / SCHEDULER_SELECTABLE / DISCOVERY_REACHABLE / BOOTSTRAP_REACHABLE` → **代码里 0 命中**；其余多数 ≤1 文件。
- §29 要求 L0–L5，且「只有 L5 才允许 `COVERAGE_COMPLETE = true`」；`COVERAGE_COMPLETE` 只出现在
  `.workbuddy-ai/commander/WORK_QUEUE.json` 与 `CODEX_DIRECTIVES.md`，**代码零实现**。
- 代码实际用（`winter_agent_v2/capability_coverage.py:46-51`）：`FULLY_LIVE_VERIFIED / PARTIAL / NEVER_TRIED / BLOCKED / DEGRADED / MISSING`。
- 第三套：`docs/GOAL_AUTOMATION_COVERAGE.md`；第四套：`learning/goal_coverage.json`（`total/automated/candidate_or_partial`）。
→ **一个概念，四套词汇，其中规则指定的那套恰好是没实现的那套。**
并且 handoff §21 用的正是代码那套（`Fully Live Verified / Partial / Never Tried / Blocked`）
—— 说明 **§28/§29 是被取代的旧口径**。

**C4 — §47 与 §53 对漏斗的定义不一致。**
§47 列 15 级，且**不含** replay / shadow；§53 明确要求
「Candidate → Grounding / **Replay** → Live Verifier → **Shadow** → Promotion Gate」。
代码的权威定义 `winter_agent_v2/ui_venus_contract.py:623-640` 是 **16 层**，含
`candidate_replay_pass` 与 `candidate_shadow_pass`。
→ 文档内两条规则互相矛盾，且两条都与代码不一致。

**C5 — §68 vs 实现：13 项不变量对不上。**
§68 列 13 个名字要每轮检查。`tools/invariant_review.py:311-325` 实际实现 **14 项**，其中：
- 2 项直接返回 `UNMEASURED`：`ONE_EXECUTOR`(L313)、`KNOWN_FAST_PATH_MODEL_CALLS`(L297-307)；
- §68 的 3 个名字**不存在**：`ONE_WORLD_STATE`、`NO_HIGH_VALUE_UNKNOWN_STARVATION`
  （代码叫 `HIGH_VALUE_UNKNOWN_NOT_STARVED`）、`SAFETY_AND_LIVENESS_BOTH_HOLD`（0 命中）。
→「每轮 Invariant Review」**按字面无法执行**；§72 结尾那句"任何保护机制必须同时证明 SAFETY 和 LIVENESS"
在检查表里没有对应项。

**C6 — §17 vs 代码。**
§17 定 60s / 10min / 1h 三档、正常上限 1h。代码没有阶梯，只有各子系统硬编码：
`stamina_supply.py:66 DEFAULT_CLAIM_COOLDOWN_SECONDS = 1800.0`、
`skill_repair.py:58 REPAIR_REQUEST_COOLDOWN_SECONDS = 3600`、
`unknown_advisor.py:82 REQUEST_COOLDOWN_SECONDS = 3600`。
无 60s 档，无 10min 档。

**C8 — §44 vs 第二节四：同一触发器两个阈值。**
§44 B/C 用「**连续 3 个真实 Production 验证周期**」；第二节四用「**连续 3 轮**」
且判据不同（第二节四要"PRODUCTION_TRIED 没涨 + NEVER_TRIED 没降 + 没有新 VERIFIER_PASS"，
§44 B 只看 NEVER_TRIED 没减少）。同一条自我审计，两种计数单位。

**C9 — §70 要求一个不存在的数字。**
§70 报告字段含 `MANUAL_INTERVENTIONS_PER_24H`；该符号全仓（任意拼写）**只出现在两份规则文档里**。
同时 §44 C/D、§58、§65、第二节八都把「MANUAL_INTERVENTION 下降」当作**选择下一项工作的判据**
—— 用不存在的数字做决策。

### 3.3 规则 vs 代码（不是文档内的错，是文档与现实的错位）

| 规则 | 现实 | 位置 |
|---|---|---|
| §29 L0–L5 | 6 值枚举 | `capability_coverage.py:46-51` |
| §28 13 状态 | 8 个零命中 | 全仓 |
| §17 冷却三档 | 1800 / 3600 硬编码 | `stamina_supply.py:66` 等 |
| §68 13 不变量 | 14 项、2 项 UNMEASURED、3 个名字缺失 | `tools/invariant_review.py:311-325` |
| §47 15 级 | 16 层 | `ui_venus_contract.py:623-640` |
| §55 14 个审计原因 | 11 个在用，3 个零命中 | 见第 4 节 N3 |
| §39 `PERMANENT_BLOCK` 这个 token | 0 命中；概念实现在别处 | `brain.py:958` / `capability_bootstrap.py:934` |

---

## 4. 哪些规则从没用过

判据：**符号级实测**——该规则要求的东西在实现目录（`winter_agent_v2/ tools/ tests/ knowledge/ learning/`）
里的命中数。命中 0 且只出现在规则文档自身 = 从未落地。

| # | 规则 | 要求的东西 | 实测 | 结论 |
|---|---|---|---|---|
| **N1** | §46 + 第二节八 + §70 | `MANUAL_INTERVENTIONS_PER_24H` | **全仓 0**（任意拼写、`manual_intervention` 小写也 0） | **从未测量过**，却被 4 条规则当决策判据 |
| **N2** | §63 | MuMu 到底用哪个 GPU / 必要时移到 780M | `780M` / `Radeon` **只出现在两份规则文档** | 条件分支**从未触发**，从未测量 |
| **N3** | §55 | `DISCOVERY_READY` / `LEARNING_READY` / `RECOVERY_READY` 三个原因值 | 各 **0**（同清单另 11 个在用：`READY_EXECUTABLE` 17、`WAIT_UNTIL` 16、`POLICY_DISABLED` 17…） | 14 个值里 3 个是死值 |
| **N4** | §10 | 学习预算 ≥50% 的份额 | `learning_share` / `LEARNING_SHARE` / `LEARNING_RATIO` / `LEARNING_BUDGET` **全仓 0** | **头号规则无度量**；只有 §35 的 `LEARNING_WINDOW` 在 `runtime.py` 里 |
| **N5** | 第二节 六 | 控制台必须实时反映的 5 个字段（当前最高价值缺口 / 本轮做了什么 / 上一轮做了什么 / 下一个候选工作 / 阻塞原因） | 只找到 `阻塞原因`（`tools/control_panel.py:2039`）；**另 4 个 0 命中** | 5 项里 4 项从未实现；而该规则写着"不更新等于这一轮没有真正进行" |
| **N6** | §28 | 13 个命名状态中的 8 个 | `GOAL_EXISTS`/`SCHEDULER_VISIBLE`/`SCHEDULER_SELECTABLE`/`DISCOVERY_REACHABLE`/`BOOTSTRAP_REACHABLE` = **0** | 13 状态矩阵从未按此实现 |
| **N7** | §29 | `COVERAGE_COMPLETE` 由 L5 决定 | 代码 **0**，只在 commander 的 JSON/DOC 里 | 从未按此实现 |
| **N8** | 第二节 五 | 「按总指令第 46 节 Tier 0」先修自己 | §46 无 Tier 0；Tier 0 概念在 handoff §8b | 引用的规则**不存在**（但自我修复机制本身是有的：`autogen_repair_events.jsonl`、`autorepair_l4_first_success.json`） |

**明确不算"从未使用"的**（避免误判，我逐条查过等价物）：

- §39 真钱封锁 → 概念在用：`brain.py:958` `real_money_action_permanently_blocked`、
  `capability_bootstrap.py:934 SEED_REAL_MONEY` / `981 == "NONE_ALLOWED"`。死的只是 `PERMANENT_BLOCK` 这个词。
- §40 Fishing 只用普通鱼饵 → 实现在用：`goal_library.py:1686 only_allowed_spend: NORMAL_BAIT`、
  `:1766 forbidden_spend: [gems, real_money, treasure_tickets, special_bait]`、
  `knowledge/events/fishing_tournament_rules.json` 的 `policy`。
- §47 漏斗 → 在用：`learning/funnel` 的 `FUNNEL_LAYERS` 16 层全实现，产物
  `learning/learning_funnel.json` 45,784 B，**今天 23:51 还在更新**。大写名 0 命中只是因为实现用小写。
- §24 已知路径 0 模型 → 在用：`learning_funnel.py:577 KNOWN_MODEL_CALLS`。
- §49/§51/§50/§52 → 在用：`ui_venus_contract.py` 导出 `MAX_MODEL_CONTEXT=32768`、`TRIMMING_ORDER`、
  `UNTRUSTED_PROPOSAL`、`MODEL_COMPLETE_CLAIM`、`frame_consistency`。
- §25/§26 → 在用：`winter_agent_v2/unknown_learning.py`（746 行）实现 `LearnedStepCandidate` / `CandidateSkill` /
  `learned_steps_for`；`SECOND_ENCOUNTER` 出现在 `runtime.py` 与 2 个测试里。
- §21/§22 Safe Bootstrap → 在用：`capability_bootstrap.py`（2,891 行）。
- §33 Role Session → 在用：`winter_agent_v2/role_session.py` 存在且被 scheduler/runtime 引用。
- §35 Idle 用于成长 → 在用：`LEARNING_WINDOW` 在 `runtime.py`。
- §62 GPU/模型资源 → 在用：`config/v2.json:117` 的实测注释（`-ngl 30` / f16 KV / 213-265 MiB free /
  `tools/profile_device_impact.py` / `tools/profile_gui_model_context.py`）。

> 说明：我没有把 H2 的 29 块做成逐条"用没用"表 —— **我只读了它的骨架和 6 个关键块**
> （§2b/§8b/§14/§15/§21/§22/§24/§25），没有读它的全文 1,105 行。
> 给出未读部分的"从未使用"结论就是编。需要的话我另起一轮把 handoff 那 29 块也审一遍。

---

## 5. 重复簇（同一个意思说了几遍）

| 簇 | 说的是同一件事的规则 | 建议留谁 |
|---|---|---|
| 完成后重新选最高价值工作 | §42-STEP11 尾、§65、§66、第二节二 尾、第二节八 | **留 §65**，其余并入 |
| 高价值 UNKNOWN | §13（口号）、§14（定义）、§31（动作）、§15（打分） | 留 §14 + §15 + §31，删 §13 |
| 学习预算 | §10（≥50%）、§11（不是机械切片）、§35（空闲即学习窗口） | 留 §10 + §35，删 §11 |
| 生产与学习不分离 | §8（三种工作）、§41（同时进行） | 留 §8，删 §41 |
| UNKNOWN 不能永久不可达 | §4（黑洞反例）、§19（不能永久 Gate）、§20（不能永久 NOT_ACTIONABLE） | 留 §4 作原则 + §19/§20 作两种机制（**这三条不合并**，因为机制不同，但要在 §4 里显式说明分工） |
| 调度模拟验收 | §36（A–Q 17 场景）、§37（两角色盘面）、代码 `invariant_review.simulate()` | 留 §36，删 §37，§36 补一句"代码落点" |
| 自我审计触发器 | §44 A–F、第二节四 | 留 §44，删第二节四 |
| 覆盖率口径 | §28（13 状态）、§29（L0–L5）、`docs/GOAL_AUTOMATION_COVERAGE.md`、`learning/goal_coverage.json`、`capability_coverage.py` 6 值 | **只留一套**（见第 6 节建议） |
| 保护机制必须同时证明安全与活性 | §38（标题就是它）、§68（`SAFETY_AND_LIVENESS_BOTH_HOLD`）、§72（结尾重复）、§34（GLOBAL_WAIT 特例） | 留 §38 作原则，§68 补上检查项，§72 只留一句引用 |
| 每轮流程 | §42（11 步）、第二节二（11 步同一串） | 留 §42 |
| 竞品对齐 | handoff §21 `Commercial Bot Parity x/21`、§22 72h 验收、docs §45 Production 验证周期 | 三处口径不同，需用户裁决 |

---

## 6. 精简后的规则文档建议

### 6.1 先解决"哪份是真源"（不解决这个，后面都白做）

现状是 **3 个文件、2 套编号、互不同步**，其中一份还没进 git。建议：

1. **定一个真源目录**：`.workbuddy-ai/rules/`，只放文件，不放副本。
2. **两份原文各归其位**：
   - `FINAL.md` ← 现在的第一节（73 条）；**删掉 C 类 9 条，合并成 ~64 条**
   - `OPERATIONAL.md` ← 现在的 handoff 29 块（存储/分支/指令翻译/宪法 A/B —— 这些是**机器判据型**规则，和 FINAL 的"原则型"不是一类，本来就不该塞在一起）
3. **`docs/MASTER_RULES.md` 改成一行指针**：
   ```
   规则全文见 .workbuddy-ai/rules/FINAL.md（原则）与 OPERATIONAL.md（操作）。
   本文件不再承载正文。sha256: <两行>
   ```
4. **`docs/WorkBuddy_Persistent_Development.md` 不要再单独存在**；它的 8 条并入 `OPERATIONAL.md`。
5. **把规则文件加进 git**（现在 `docs/MASTER_RULES.md` 是 `??` 未跟踪）。

### 6.2 每一条可执行规则强制带"三件套"

这次审计暴露的最大结构问题是：**规则写得像命令，但没说怎么判、谁判、判完看什么**。
建议把 8 条 B 类改写成下面这个形状（示例是 §17）：

> **§17 Cooldown 基线**
> 判定：失败目标在 cooldown 到期后**必须重新出现在 Goal Board**。
> 落点：`winter_agent_v2/attempt_controller.py:26`（当前实现：1800/3600 硬编码，无阶梯）。
> 判据：`tools/invariant_review.py FAILED_GOAL_EVENTUALLY_RETRYABLE`（已实现）。
> 冲突处理：**以代码为准**，除非用户重新指定档位。

### 6.3 把"**不存在的数字**"集中列一节

现在有 4 条规则在拿不存在的数字做决策（`MANUAL_INTERVENTIONS_PER_24H`、`Learning Budget 50%`、
`COVERAGE_COMPLETE`、控制台 5 字段中的 4 个）。建议文档新增一节：

> **§附. 目前无法测的量（禁止用作判据）**
> 列出这些名字，并写明：在补出度量之前，**任何"因为 X 下降所以选这项"的理由都不成立**。

这一节的价值在于：它把"没实现"变成"显式已知"，而不是让人继续假装它在被追踪。

### 6.4 目标规模

| | 现在 | 建议 |
|---|---|---|
| 文件数 | 3（+1 不存在） | 2 + 1 行指针 |
| 规则块 | 110 | ~92（删 12、合并 6） |
| 字节 | 42,761 + 60,125 + 51,771 | ~55,000（**压掉约 60%**） |
| 带机器判据的规则 | 少量（handoff §26.4/§27.4/§28.6） | **每条可执行规则都有** |

---

## 7. 需要你裁决的 5 件事（我不自己定）

1. **规则以哪份为准？** `docs/MASTER_RULES.md`（73 条）还是 handoff（29 块）？
   特别是：**开发阶段到底能不能主动花体力和 Gem**（handoff §8b 说能，docs §39 说要过 Risk Gate）。
   这条直接决定我下一步能不能真机验证巨熊。
2. **§24「禁止坐标硬编码」是否纳入审计范围？** 它是 handoff 里自标"优先级最高"的一条，
   而 `docs/MASTER_RULES.md` 里没有它。**我本轮已经违反过它一次**（写死 `(669,173)`），需要你明示它是否生效。
3. **覆盖率用哪套口径？** 建议以代码的 6 值为准（`FULLY_LIVE_VERIFIED/PARTIAL/NEVER_TRIED/BLOCKED/DEGRADED/MISSING`），
   废掉 §28 的 13 状态与 §29 的 L0–L5。若你坚持 L0–L5，那就是**要改代码**，工作量不同。
4. **§17 冷却档位**：改代码去对规则（补 60s/10min 档 + 1h 上限），还是改规则去对代码（写实为 1800/3600）？
5. **C 类 12 条，有没有你舍不得删的？** 我按证据判"冗余/过期"，但规则里可能藏着只有你知道的意图 ——
   尤其是 §56（18 个项目标清单）与 §63（MuMu GPU），删之前请确认。

### 我自己的判断（供参考，不代替你决定）

- 最该先动的是 **§0 的优先级阶梯里补进「禁止坐标硬编码」**，因为它是**唯一一条会让我真的做错事**的缺失。
- 其次是 **§46/§70 的 `MANUAL_INTERVENTIONS_PER_24H`**：要么补度量，要么从报告里删掉。
  拿假数字做"下一项做什么"的决策，比没有这个数字更危险。
- 最不该动的是 A 类里那 3 条真钱/不可逆边界（§39 §69 §64）。它们是这份文档存在的理由。
