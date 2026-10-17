# RULES — 真源、优先级、与引用解析

**这是规则层的唯一入口。** 任何"规则说……"的判断，都必须能落到本目录里的某一行。

建立日期：2026-10-06　依据：`docs/RULES_AUDIT_2026-10-05.md`（诊断报告）
本次改动**不改任何用户措辞的含义**，只做四件事：定真源、定优先级、销歧义、把只存在一份的东西存进 git。

---

## 1. 真源（四个文件，各司其职，不互相包含）

| 文件 | 是什么 | 性质 |
|---|---|---|
| `PRINCIPLES.md` | 《WorkBuddy 持续自主开发总指令 FINAL》+《持续开发，不许停》的**权威可执行版** | 原则型 |
| `OPERATIONAL.md` | 存储/分支/指令翻译/宪法 A·B/权限分级等**操作判据型**规则（原 `.workbuddy-ai/handoff/00_MASTER_RULES.md`） | 判据型 |
| `FINAL_FULL.md` | 《FINAL》**逐字原文**（存档，供溯源与措辞争议） | 存档 |
| `PERSISTENT_DEVELOPMENT.md` | 《持续开发，不许停》**逐字原文**（存档） | 存档 |

**分工规则**：`PRINCIPLES.md` 说"为什么要这样"，`OPERATIONAL.md` 说"怎么判、用什么命令判"。
两者冲突时 —— 见 §2 优先级阶梯，**不按文件分高下**。

### 为什么必须建这个目录（2026-10-05 实测）

审计发现：**《FINAL》与《不许停》两份全文当时都不在 git 里，而且全机各只有一份，
就在 `E:\WinterAgent` 这个工作树的未跟踪文件里。**

| 文件 | 改之前 | 风险 |
|---|---|---|
| `.workbuddy-ai/commander/WORKBUDDY_AUTONOMOUS_DEVELOPMENT_FINAL.md` | 未跟踪，主线不存在 | 一条 `git clean -fd` 就没有了 |
| `docs/MASTER_RULES.md`（含《不许停》全文） | 未跟踪，主线不存在 | 同上；且它是《不许停》的**唯一**副本 |
| `.workbuddy-ai/handoff/00_MASTER_RULES.md` | 已跟踪 | 安全 |

现在两份全文都已进 git（`FINAL_FULL.md` / `PERSISTENT_DEVELOPMENT.md`，逐字）。
`docs/MASTER_RULES.md` 与 `00_MASTER_RULES.md` 已改为指针，**不再承载正文**。

---

## 2. 优先级阶梯（冲突时按此裁决，不按文件）

`PRINCIPLES.md §0` 原有 8 级。2026-10-06 补入**项目宪法 A/B**——它自标"优先级最高"，
但在原阶梯里**完全不存在**（`禁止坐标硬编码` 在该文件命中 0），
这正是 2026-10-05 我在巨熊探针里写死 `(669,173)` 却判定自己没违规的原因。

| 级 | 内容 | 出处 |
|---:|---|---|
| 1 | 用户最终项目目标 | `PRINCIPLES.md §1` |
| 2 | **真钱 / 不可逆账号风险** ＋ **用户明确固定策略**（含 Fishing ONLY NORMAL BAIT） | `PRINCIPLES §39 §69`、`OPERATIONAL §8` |
| 3 | **项目宪法 A：禁止坐标硬编码**／**宪法 B：UI 元素是基本单位** | `OPERATIONAL §24 §25` |
| 4 | ONE Scheduler / ONE Executor / ONE WorldState 等核心架构不变量 | `PRINCIPLES §2` |
| 5 | AUTO 活性与长期无人值守 | `PRINCIPLES §61` |
| 6 | 能力持续学习与覆盖率扩大 | `PRINCIPLES §10 §14 §31` |
| 7 | 当前真实 Production 证据 | `PRINCIPLES §45 §60` |
| 8 | 当前开发目标 | `PRINCIPLES §42 §65` |
| 9 | 示例代码、字段名、推荐阈值 | `PRINCIPLES §0` 末段 |

**第 3 级放在第 2 级之下，是判断，不是引用**：宪法 A/B 管的是"怎么点"，
它不可能高于"真钱永不触碰"和用户显式策略。若操作者认为宪法 A/B 应在第 2 级以上，改这一行即可。

---

## 3. `§N` 引用解析表（重要）

代码注释大量使用裸 `§N`。**两份规则文件的节号是重叠的（都有 §1–§28）**，
所以裸 `§N` 在 N ≤ 28 时**不可解析**，而且实测还有至少两份同族的专题文档也在被裸引用。

| 引用形态 | 解析为 | 依据 |
|---|---|---|
| `section 30`、`section 36-38`、`section 47`…（英文 `section` + 数字 > 28） | `PRINCIPLES.md` | OPERATIONAL 只到 §28 |
| `§24.2`、`§24.3`、`§25.x`、`§26.x`、`§27.x`、`§28.x`（带小数点） | `OPERATIONAL.md` | 只有它有子编号 |
| `00_MASTER_RULES.md §N`（显式点名文件） | `OPERATIONAL.md §N` | 原文件名 |
| `§N`（裸，N ≤ 28） | **有歧义** | 下节 |
| `FISHING POLICY V2 §N`、`TASK THROUGHPUT V1 §N`、`directive §N` | **另属专题文档，不在本目录** | 实测见下 |

### 3.1 裸 `§N` 的歧义已被实测确认

同一批代码里，同一个 `§N` 指向不同文档：

```
winter_agent_v2/...:  (``00_MASTER_RULES.md`` §5)     -> OPERATIONAL §5
winter_agent_v2/...:  FISHING POLICY V2 §3 / §14 / §15 -> 专题文档，非本目录两份
winter_agent_v2/...:  TASK THROUGHPUT V1 §23/§24       -> 专题文档，非本目录两份
winter_agent_v2/...:  directive §17（switch-quality / session-duration） -> 与 PRINCIPLES §17（Cooldown）无关
```

**结论：裸 `§N` 不能当作证据。** 本次审计报告里"规则 vs 代码冲突"的若干条，
有一部分其实是**引错文件**造成的假冲突——这一点在旧报告里被高估了，
以本节为准。

### 3.2 从今往后的写法（硬要求）

新增或修改的注释/文档，引用规则必须写成 **`文件#节号`**，例如：

```
PRINCIPLES §39        （真钱永久阻止）
OPERATIONAL §24.2     （八条硬禁止）
```

**禁止**再新增裸 `§N`。

---

## 4. 本次裁决记录（2026-10-06，操作者授权"自己改"）

| # | 问题 | 裁决 | 理由 |
|---|---|---|---|
| R1 | 规则以哪份为准？ | **两份都在效，按 §2 阶梯裁决** | 两套编号互不包含，谁也不是对方的超集 |
| R2 | 开发阶段能否主动花体力 / Gem？ | **能**。真钱与账号安全=永久禁止；非真钱资源按 `OPERATIONAL §8b` 的 T0–T4 授权，当前阶段是 `DEVELOPMENT_VALIDATION` | `PRINCIPLES §39` 只约束真钱与不可逆动作；`OPERATIONAL §8b` 是阶段性的、更具体的授权。**这条直接解锁真机验证** |
| R3 | 宪法 A「禁止坐标硬编码」是否生效？ | **生效，且在阶梯第 3 级** | 它有机器判据 `tools/check_coordinate_hardcoding.py`，且在轨（见 §5） |
| R4 | 覆盖率用哪套口径？ | **以代码为准**：`FULLY_LIVE_VERIFIED / PARTIAL / NEVER_TRIED / BLOCKED / DEGRADED / MISSING` | `PRINCIPLES §28` 的 13 个状态有 8 个零实现，`§29` 的 `COVERAGE_COMPLETE` 零实现；`OPERATIONAL §21` 用的正是代码这套。**改文档，不改代码** |
| R5 | §17 冷却档位？ | **以代码为准**：实况是 1800 / 3600 硬编码，无 60s/10min 阶梯。文档已改写为实况 | 改文档零风险；补阶梯要动 5 个模块且有行为变化风险 |

### 4.1 执行 R2 的边界（不可越）

允许：为验证 Capability 主动消耗**体力 / 普通资源 / 普通加速 / 普通道具**；Gem 小额可控；
主动腾空队列、主动制造可恢复的验证状态。**每次支出必须记 `reason/amount/capability/before/after`。**

**仍然永久禁止**：真钱与真实购买、账号删除/安全修改、不可逆账号操作、
Fishing 的 special bait / treasure tickets / gems / real money。

---

## 5. 宪法 A 的机器判据现状

```
.venv/Scripts/python.exe tools/check_coordinate_hardcoding.py          # 人工报告
.venv/Scripts/python.exe tools/check_coordinate_hardcoding.py --json   # 机器报告
```

2026-10-06（提交 `1ec68c08`）修复了它的一个**假阳性根因**：`Skill(...)` 的"声明页"映射
用的是只有多行声明才能匹配的写法，导致三个**真的声明了页面**的生产滑动手势被报成
`GESTURE_OWNER_UNRESOLVED`。修复后主线 A/B：`rulings_needed 3 → 0`，`violations 0 → 0`。

**这类缺陷比漏报更隐蔽**：闸门读不出自己该认证的声明，就把作者报成错的。
以后凡"闸门说我的东西有问题"，**先怀疑闸门的读法**，再改自己的代码。

---

## 6. 变更流程

1. 改 `PRINCIPLES.md` / `OPERATIONAL.md`（在**主线 worktree** 里改，见 `OPERATIONAL.md §27`）；
2. 逐字原文（`FINAL_FULL.md` / `PERSISTENT_DEVELOPMENT.md`）**只在操作者给出新原文时替换**，
   不允许就地编辑；
3. 提交时 message 必须写明**改了哪一节、为什么**；
4. 若某条规则与代码不符，**先决定改哪边**，再改——不允许让两者长期不一致。

---

## 7. 目前**无法测量**的量（禁止用作判据）

以下名字在实现目录里命中 0，却被旧规则当作决策依据。**在补出度量之前，
任何"因为 X 下降所以选这项"的理由都不成立。**

| 名字 | 出处 | 实测 |
|---|---|---|
| `MANUAL_INTERVENTIONS_PER_24H` | `PRINCIPLES §46 §70` | 全仓 0 命中（任意拼写） |
| Learning Budget ≥50% 的份额 | `PRINCIPLES §10` | `learning_share` 等 0 命中 |
| `COVERAGE_COMPLETE` | `PRINCIPLES §28 §29` | 代码 0 命中 |
| 控制台 5 字段中的 4 个 | `PERSISTENT_DEVELOPMENT 六` | 只有"阻塞原因"实现了 |

**替代判据**（这些是真实存在的）：`NEVER_TRIED_GOALS`、`PRODUCTION_TRIED_GOALS`、
`GOAL_PROGRESS_VERIFIED`、`learning/learning_funnel.json` 的各层计数、
`tools/invariant_review.py` 的不变量结论。

---

## 8. 审计入口

- 诊断报告：`docs/RULES_AUDIT_2026-10-05.md`（81 条 → A 61 / B 8 / C 12，含冲突与从未使用清单）
- 坐标红线：`tools/check_coordinate_hardcoding.py`
- 不变量自检：`tools/invariant_review.py`
- 主线判据：`tools/check_mainline.py`
