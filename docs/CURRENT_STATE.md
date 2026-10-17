# CURRENT STATE — 当前项目状态（快照）

> **本文件是快照，不是事实源。而且它会过期得很快。**
>
> ⚠️ **`learning/runtime_snapshot.json` 与 `learning/goal_state.json` 由运行时持续重写（约每 30 秒）。**
> 本文整理过程中，两次读数相隔约 4 分钟，`role_id`、`agent_state`、Goal 板分布**全都变了**
> （见 §2 的「两次读数的差异」）。所以：**下面每一个数字都必须连同它的 `read_at` 一起引用。**
>
> ⚠️ **Goal 板是「按角色」的**：项目有双角色调度器（`1063040265` / `1061663148`），
> `goal_state.json` 里既有当前 `active_role_id` 也有 `roles` 分块。
> **说「当前 Goal 状态」而不说角色，等于没说话。**
> 背景见 `docs/dual_role/GLOBAL_DUAL_ROLE_SCHEDULER_PHASE0_AUDIT.md`。
>
> | 事实 | 权威来源 | 怎么重算 |
> |---|---|---|
> | 运行时状态 / 页面 / 当前目标 | `learning/runtime_snapshot.json` | 运行时自己写 |
> | Goal 板 / 阻塞点 | `learning/goal_state.json` | 运行时自己写 |
> | 全部「重算型」统计（episode 数、成功率、Top failures、技能台账、覆盖度） | **`docs/CURRENT_TRUTH.md`**（机器版 `learning/current_truth.json`） | `python tools/truth_audit.py` |
> | 当前生产提交 | `E:\WinterAgent\.worktrees\winter-prod-pinned\PRODUCTION_PIN.json` | — |
>
> `docs/CURRENT_TRUTH.md` 开头写着：「Everything below is recomputed by `python tools/truth_audit.py`.
> **Do not trust numbers in older Markdown files.**」
> ← **这句话同样适用于本文件**，而且适用于 `CURRENT_TRUTH.md` 自己：
> 它最近一次重算的时间戳是 **2026-10-01T15:38:51Z —— 距今约 4 天**（见 §6.1）。
>
> **本文快照时间：`2026-10-05T01:27:30Z`**（本地 2026-10-05 09:27 GMT+8）

---

## 1. 一句话

**AUTO 在跑，但有降级。** 页面 HOME，`agent_state = DEGRADED`，
当前目标 `HERO_RECRUIT_ADVANCED`（技能 `OPEN_TASK_FROM_QUICK_PANEL_HERO_RECRUIT`），verifier `PASS`。
35 个 Goal：**COMPLETE 4 · DISCOVERED 3 · READY 5 · UNKNOWN 23 · BLOCKED 0**。
两条最值得动的线：**23 个 `SCHEDULED_*` 事件目标全是 UNKNOWN（观测缺口）**，
以及 **6 条阻塞里有 3 条的解锁时间早已过期却仍然锁着**。

---

## 2. 运行时（`learning/runtime_snapshot.json`，`updated_at 2026-10-05T01:27:28Z`）

| 字段 | 值（01:27:28Z） | 4 分钟前（01:23:49Z） |
|---|---|---|
| `agent_state` | **`DEGRADED`** | `GOAL_RUNNING` |
| `mode` | `AUTO` | `AUTO` |
| `page` | `HOME` | `HOME` |
| `role_id` | **`1061663148`**（`[DIW]xhw`） | `1063040265`（`[ioi]零氪纯盾流`） |
| `current_goal` | `HERO_RECRUIT_ADVANCED` | `DISCOVER_QUICK_PANEL_TASKS` |
| `current_skill` | `OPEN_TASK_FROM_QUICK_PANEL_HERO_RECRUIT` | `OPEN_QUICK_PANEL` |
| `verifier` | `PASS` | `PASS` |
| `reason` | `quick_panel_hero_recruit_row_is_the_current_daily_goal` | `collapsed_quick_panel_handle_and_pending_daily_board_scan` |
| `last_fatal_error` | `None` | `None` |

**在这两次读数之间不变、因而更可信的字段**：

| 字段 | 值 |
|---|---|
| `watchdog_restart_count` | **29** |
| `unexpected_worker_exits` | **23** |
| `fairness_write_skipped` | **`ROLE_IDENTITY_UNCONFIRMED`** |
| `last_fatal_error` | `None` |

**两次读数的差异说明了三件事**（这比数字本身更重要）：

1. **角色在切。** `role_id` 从 `1063040265` 变成 `1061663148` —— 双角色调度器在工作。
2. **`agent_state` 在动。** `GOAL_RUNNING` → `DEGRADED`。
   **没有 fatal error，却是 DEGRADED** → 这是一个需要单独查的状态，不是崩溃。
3. **任何单一时刻的 Goal 板都只代表那一刻的那个角色。**

---

## 3. Goal 板（`learning/goal_state.json`，`written_at 2026-10-05T01:27:25Z`）

`active_role_id 1061663148` · `page HOME` · **共 35 个 Goal**

| 状态 | 个数 |
|---|---:|
| COMPLETE | **4** |
| READY | **5** |
| DISCOVERED | **3** |
| UNKNOWN | **23** |
| BLOCKED | **0** |
| **合计** | **35** |

### 3.1 COMPLETE（4）

`AVOID_STAMINA_WASTE` · `KEEP_RESEARCH_PRODUCTIVE` · `CLAIM_EXPLORATION_IDLE` ·
`DISCOVER_QUICK_PANEL_TASKS`

### 3.2 可调度候选（READY / DISCOVERED，按 priority 降序）

| Goal | 状态 | priority |
|---|---|---:|
| `KEEP_BUILDING_PRODUCTIVE` | READY | **500.0** |
| `DAILY_ACTIVITY_TARGET` | READY | **500.0** |
| `HERO_RECRUIT_ADVANCED` | READY | **250.0** |
| `KEEP_TRAINING_PRODUCTIVE` | DISCOVERED | 180.0 |
| `MAIL_ROUTINE` | DISCOVERED | 173.50 |
| `CLEAR_INTEL` | DISCOVERED | 138.61 |
| `SCROLL_QUICK_PANEL_TASKS` | READY | 100.0 |
| `OBSERVE_FISHING_STATE` | READY | 0.0 |

### 3.3 UNKNOWN（23，全部 completion 0.0）

**这 23 个不是「做不了」，是「还没在真机上被观测到」。** 在 `runtime_snapshot.json` 的
`capability_discovery` 里，它们绝大多数是 `reason: MISSING_OBSERVATION` /
`gap_type: OBSERVATION_GAP`，而 `provider_emits` / `route_exists` / `skill_exists` /
`verifier_exists` 多为 `true` —— 能力链是齐的，**缺的是一次真实观测**。
（例外：`ALLIANCE_TIMED_EVENTS` / `USE_FREE_ARENA_ATTEMPTS` / `LABYRINTH_DAILY`
连 `route_exists` 与 `skill_exists` 都是 `false`，属于真正的实现缺口。）

> ⚠️ **2026-10-05 实测更正："缺的是一次真实观测"这句话对 `SCHEDULED_*` 是错的。**
> 观测**被尝试了 40 次**，不是没试过：`READ_EVENT_CALENDAR` 执行 40 次、
> `verifier_ok` **40/40 = False**，`calendar_recognized=false / visible_dates=[] / entry_count=0`，
> 每次都站在 `regular_events_hub` 子状态上；**全历史没有一个 `SCHEDULED_*` 见过已识别日历**。
> 根因是**问错了页面**：票唯一的技能读**日历网格**，而那批静态活动活在
> **「常规活动」枢纽的 tab 条**里（实测 tab 标签 `最强王国`/`峡谷会战`/`兵工厂争夺战`/
> `佣兵荣耀`/`联盟总动员`/`军备竞演`）。活板上 20 张票里 **14 张连日历行都没有**，
> 有行的 6 张**全部 `details_observed=True`**。
> ⇒ 这不是"缺一次观测"，是**观测手段与目标页面不匹配**。
> 详见 `.workbuddy-ai/memory/MEMORY.md` §88–§89。


- 具名事件 17 个：`SCHEDULED_BEAR_HUNT`、`SCHEDULED_STATE_VS_STATE`、
  `SCHEDULED_ARMAMENT_COMPETITION`、`SCHEDULED_ALLIANCE_MOBILIZATION`、
  `SCHEDULED_OFFICER_PROJECT`、`SCHEDULED_DEFEAT_NEARBY_BEASTS`、
  `SCHEDULED_BROTHERS_IN_ARMS`、`SCHEDULED_CANYON_CLASH`、`SCHEDULED_FORTRESS_CONTEST`、
  `SCHEDULED_ARMAMENT_FACTORY_EVENT`、`SCHEDULED_UNDERGROUND_EXPLORATION`、
  `SCHEDULED_FISHING_TOURNAMENT`、`SCHEDULED_ICEBOUND_TREASURE`、
  `SCHEDULED_MOONLIGHT_FESTIVAL_SHOP`、`SCHEDULED_EXCLUSIVE_GEAR_FORGE`、
  `SCHEDULED_ICEBOUND_TREASURE_TRAINING`、`SCHEDULED_ICEBOUND_TREASURE_MYSTERY_SHOP`
- 自动发现的未命名事件 3 个：`SCHEDULED_DISCOVERED_EVENT_4178AC2F00` /
  `..._BB2077C97D` / `..._E1FB4AC23A`
- 其余 3 个：`ALLIANCE_TIMED_EVENTS`、`USE_FREE_ARENA_ATTEMPTS`、`LABYRINTH_DAILY`

---

## 4. 当前阻塞点（`learning/goal_state.json` → `blockers`，6 条）

### 4.1 修复预算用尽（3 条，`source: ESCALATION_QUEUE`）

原因逐字都是 **`repair budget exhausted (2/2) after CODE_CHANGED`** ——
2 次修复机会用完后仍未通过，于是升级队列把该 capability 锁住。

| Goal | capability | 锁到（`until`） |
|---|---|---|
| `KEEP_BUILDING_PRODUCTIVE` | `START_BUILD` | 2026-09-30T17:39:30Z |
| `MAIL_ROUTINE` | `READ_MAIL_TABS` | 2026-09-28T14:20:26Z |
| `DAILY_ACTIVITY_TARGET` | `READ_DAILY_PROGRESS` | 2026-09-23T14:42:13Z |

> 🔴 **三个 `until` 全都已经过期**（最晚的一个是 09-30，现在是 10-05，过了约 5 天），
> **但它们仍然躺在阻塞表里**。这意味着「时间到了就解锁」这条路径**没有把它们放出去**——
> 三个目标等于是**永久停摆**。这不是个案，是机制性的（见 §6）。**本文未下结论，只记录现象。**
>
> ✅ **2026-10-05 09:xx 已结案，结论相反：不是永久停摆，是"每 180 分钟一次探测"。**
> `_probe_lapsed` 的锚点是目标**自己最近一次尝试**（`last or fallback_anchor`），
> 而板子印的是账本的 `cooldown_until` —— **印的是输入，门用的是算出来的那个**，差 12 天。
> 实测三个目标几小时内一直在跑（间隔 40–152 分），其中两个还记了 `goal_progress=True`。
> 已修（提交 `d913dc95`）：`blocks()` 改为公布 `anchor + 窗口`，板子现在写
> `2026-10-05T04:57 / 04:46 / 04:55`（各自 `last + 180 分`）。
> 细节见 `.workbuddy-ai/memory/MEMORY.md` §86 与 `.workbuddy-ai/memory/2026-10-05.md` §18。
> **⇒ 本节与 §5 第 2 行"永久停摆"的读法作废；§5 的优先排序要按下面那条注释重排。**

### 4.2 零推进（3 条，`source: NO_GOAL_PROGRESS`，`streak: 3`）

两句不同措辞，严重程度不同：

**(a)「每步都过了自己的 verifier，但目标零推进」**

| Goal | capability | last_skill | failure_signature |
|---|---|---|---|
| `CLEAR_INTEL` | `READ_INTEL_LIST` | `INTEL_BEAST_START_MARCH` | `READ_INTEL_LIST\|NO_GOAL_PROGRESS\|INTEL_BEAST_START_MARCH` |
| `SCHEDULED_BEAR_HUNT` | （空） | `OPEN_HOME` | `\|NO_GOAL_PROGRESS\|OPEN_HOME` |

**(b)「发出的动作被自己的 verifier 拒了，且目标零推进」← 比 (a) 更严重**

| Goal | capability | last_skill | failure_signature |
|---|---|---|---|
| `OBSERVE_FISHING_STATE` | `READ_FISHING_STATE` | `PRINTED_TAP` | `READ_FISHING_STATE\|NO_GOAL_PROGRESS\|PRINTED_TAP` |

`CLEAR_INTEL` **不是**「情报读不到」——它是「读到了、也打了、但目标一步没动」。
机制原因已在 `knowledge/game/intel.json` → `round_state` 里讲清楚
（见 [`docs/GAME_KNOWLEDGE.md`](GAME_KNOWLEDGE.md) §2.3）：
本轮板子只剩打不过的 `BLOCKED` 悬赏，而 `untried_pins` 又被反复算作「还有情报」。

### 4.3 两个视图不是一回事（重要）

同一时刻：

- `goal_state.json` 的 **`goals[]`** 里 **一个 BLOCKED 都没有**（COMPLETE 4 / READY 5 / DISCOVERED 3 / UNKNOWN 23）
- `goal_state.json` 的 **`blockers{}`** 里却有 **3 条 BLOCKED**
- `runtime_snapshot.json` 的 **`deferred_goals[]`** 里同样是 6 条，但用 **capability** 记而不是 Goal

也就是说这是**三套不同的投影**（Goal 层状态 / capability 层阻塞 / 运行时推迟队列），
**用同一套 `reason` 文案，覆盖面却不同。**
引用阻塞情况时**必须说清用的是哪一个**，否则会得出「有 0 个阻塞」或「有 6 个阻塞」两种相反结论。

> 本条只记录现象与差异，**不判断是设计还是缺陷**。查它属于 §6 的工作。

---

## 5. 当前真正卡住的是什么（按影响排序）

| # | 卡点 | 为什么值得优先 |
|---|---|---|
| 1 | **23 个 `SCHEDULED_*` 全是 UNKNOWN / `MISSING_OBSERVATION`** | **面最大的一块**。能力链多数已齐，缺一次真机观测。UNKNOWN → KNOWN 的成本最低、收益最广 |
| 2 | ~~**过期的 `until` 没被清出阻塞表**（§4.1）~~ | ⚠️ **2026-10-05 作废**：实测是"每 180 分钟一次探测"，不是永久停摆（见 §4.1 的红框更正）。它仍是一条**真缺陷**，但性质是「板子公布的是输入而不是结论」，属报告层，不属活性层。降为**已修**（`d913dc95`） |
| 3 | **`agent_state = DEGRADED` 但没有 fatal error**（§2） | 跑到一半自己降级却不报错，比崩溃更难发现 |
| 4 | **`OBSERVE_FISHING_STATE` 的动作被自己的 verifier 拒**（§4.2b） | 「发出去了但验证不过」比「什么都没做」更难发现；且它与 §69 点名的「Fishing ONLY NORMAL BAIT」是同一功能域 |
| 5 | **`CLEAR_INTEL` 的目标零推进** | 机制已查明，但语义有被读错的历史风险：**它曾被误判成 `CLEAR_INTEL=COMPLETE` 并永久收工** |
| 6 | **`watchdog_restart_count 29` / `unexpected_worker_exits 23`** | 不是当前故障，但在无 fatal error 的情况下还在涨，是长期稳定性的欠账 |
| 7 | **`fairness_write_skipped: ROLE_IDENTITY_UNCONFIRMED`** | 角色身份确认不稳 → 公平性数据写不进去。与 §2 的「角色在切」很可能是同一条线 |

---

## 6. 顺带发现的两处「元数据欠账」

### 6.1 `docs/CURRENT_TRUTH.md` 自己已经 4 天没重算

它的头部写着「**Do not trust numbers in older Markdown files**」，
而它自己 `generated_at_utc = 2026-10-01T15:38:51Z` —— **距本文快照约 4 天**。
里面的 `episodes total 10021`、`success rate 90.1%`、Top failures 表、
`registry 151 个技能`、`capability coverage 2/20 FULLY_LIVE_VERIFIED` **全都是 4 天前的读数**。

→ **重算一次 `python tools/truth_audit.py` 的成本极低，收益是让整套「重算型」引用重新可信。**
本文没有替它重算（那会覆盖一个由工具生成的文件，应由工具做）。

### 6.2 阻塞表里 3 条 `until` 过期仍锁

见 §4.1 —— 放在这里是因为它同时是「状态欠账」和「元数据欠账」。

---

## 7. 最近完成的工作

### 7.1 生产主线（`codex/production-pin-recovery`）

当前生产 pin：`PRODUCTION_PIN.json` → `expected_commit`
**`11b581df696c50a6ae6f0d5c8dfd867e2a37eb7f`**（= 该分支 HEAD）。

按时间倒序：

| 提交 | 类型 | 内容 |
|---|---|---|
| `11b581df` | fix(intel) | 修正 stamp 自己的 docstring，并把它修的那个转换钉进测试 |
| `1132f9de` | fix(intel) | 把 pin 计数**记在「记录了目标的那一帧」**上 |
| `ea349eba` | docs | 仪表修复的生产实测，以及守卫为什么漏掉它 |
| `2cc1da6c` | fix(meter) | 规模守卫只在**一个分支**上问了「kind」 |
| `2d738df1` | docs | 第八批的教训，以及对第七批诊断的更正 |
| `90f7c52c` | feat(intel) | `READ_INTEL_LIST` —— 走到板子，以及让 `CLEAR_INTEL` 读不出数的两个缺陷 |
| `31ec1e2a` | fix(instruments) | **两个把自己的失败藏起来的工具**，以及发现它们的部署尺子 |
| `c1622c3c` | feat(daily) | 在真机读 `每日任务` 面板；`READ_DAILY_PROGRESS` 是 **Step**，不是 Skill |
| `66785ba9` | fix(shop) | 只读的一轮必须关掉自己开的弹窗；新增 `VISIT_ALLIANCE_SHOP` |
| `6bef9082` | fix(shop) | `enter()` 必须保住它最后一次到达的商店页；新增 `VISIT_MYSTERY_SHOP` |
| `82b5a943` | feat(shop) | `VISIT_WANDERING_MERCHANT` —— 从它自己的弹窗读游荡商人，只在政策允许时花钱 |

**两条线**：

- **商店三连**（`82b5a943` → `6bef9082` → `66785ba9`）：三家商店技能做完，
  规则见 [`docs/STORE_POLICY.md`](STORE_POLICY.md)。
  ⚠️ 其中**只有游荡商人的「钻石换统帅经验」被真机证实过**，另两条 BUY 分支从未走完花钱路径。
- **情报链**（`90f7c52c` → `2cc1da6c` → `1132f9de` → `11b581df`）：把 `READ_INTEL_LIST`
  做成能走到板子，并修掉让 `CLEAR_INTEL` **读不出数**的缺陷。
  这解释了 §3.2 里 `CLEAR_INTEL` 为什么是 `DISCOVERED` 而不是 `BLOCKED`。

### 7.2 本会话（2026-10-05）新增的文档

在 `docs/` 下新建了 5 个独立文件（本文件是其中之一）：

| 文件 | 内容 |
|---|---|
| `docs/MASTER_RULES.md` | **指针**（2026-10-06 起）。正文迁入 `.workbuddy-ai/rules/`，见下 |
| `docs/GAME_KNOWLEDGE.md` | 用户明确策略 + 已确认的游戏知识 |
| `docs/CURRENT_STATE.md` | 本文件 |
| `docs/THREADING_POLICY.md` | 主线程纪律 + 落地证据（`tools/control_panel.py:行号`） |
| `docs/STORE_POLICY.md` | 三个商店的购买规则 |

> 这 5 个文件都是**汇总副本**，每个都在开头写明了自己的权威来源 ——
> 依据 `knowledge/research/RESEARCH_CHARTER.json` 的 `single_source_of_truth_rule`
> （禁止为调研另建第二套来源库）与 `.workbuddy-ai/handoff/00_MASTER_RULES.md` §18b（记忆写入路由）。
> **它们不新增规则，也不得被当成第二套优先级体系。**

### 7.3 规则层收敛（2026-10-06，依据 `docs/RULES_AUDIT_2026-10-05.md`）

审计发现规则层有三个问题，本批一次解决：

1. **规则全文不在 git 里。** 《FINAL》全文与《不许停》全文当时都只存在于本工作树的**未跟踪**文件里，
   而《不许停》**全机只有一份**（就在 `docs/MASTER_RULES.md` 里）。一条 `git clean -fd` 就能删掉规则。
   → 现已落盘入 git：`.workbuddy-ai/rules/FINAL_FULL.md`、`.workbuddy-ai/rules/PERSISTENT_DEVELOPMENT.md`（逐字）。
2. **规则正文有两套、编号重叠、互相不包含。** `.workbuddy-ai/handoff/00_MASTER_RULES.md`（29 块）
   与《FINAL》（73 条）都有 §1–§28，导致代码里 100+ 处裸 `§N` 引用**不可解析**。
   → 已集中到 `.workbuddy-ai/rules/`，并给出 `§N` 解析表（`rules/README.md §3`）。
   **节号一律未改**，代码引用保持有效。
3. **优先级阶梯漏了"禁止坐标硬编码"**（`OPERATIONAL §24` 自标"优先级最高"，却不在《FINAL》§0 的 8 级里）。
   → 已补为第 3 级（`rules/README.md §2`）。这正是 2026-10-05 巨熊探针写死 `(669,173)` 却判定没违规的根因。

**规则正文现在的唯一去处**：`.workbuddy-ai/rules/`（`README.md` 治理 / `PRINCIPLES.md` 原则 /
`OPERATIONAL.md` 判据 / `FINAL_FULL.md`+`PERSISTENT_DEVELOPMENT.md` 存档）。
`docs/MASTER_RULES.md` 与 `.workbuddy-ai/handoff/00_MASTER_RULES.md` 已改为指针。

### 7.4 双模式运行（2026-10-06，操作者规范）

操作者给出《Winter Agent OS V2 — 双模式运行规范》，逐字落在 `docs/MODE_SYSTEM.md`。

**落地**：`winter_agent_v2/mode_state.py` —— 模式是一份**持久化记录**
（`learning/MODE_STATE.json`），不是第二个锁；切换是对它做一次 **CAS + 单次 `os.replace`**，
崩溃只看到旧状态或新状态。`runtime.run()` 在设备租约守卫**之前**读它：
Manual 时以 `manually_owned_by_workbuddy` 在安全点让出。**没有这个守卫，模式记录只是一份
说了话但不改变任何事的文档。**

**两条按规范推导出的裁决**（记在 `docs/MODE_SYSTEM.md` 末节）：

- **Manual 有两种，规矩相反**：用户强制的 Manual，WorkBuddy **完全不能**自己切回（"哪怕任务完成了"）；
  WorkBuddy 自主切的 Manual，它**必须**自己切回。这条最初实现错了，靠端到端冒烟（不是单测）发现。
- **§7 收尾门 vs §10 用户优先**：门保留（§12 把"留未提交代码""回切时生产起不来"列为硬禁止），
  但给一条有记录的否决路径 `--force`，否决以 `OVERRIDDEN BY USER: …` 写入历史。

**未做**：§6 机时分配（依赖一个不存在的"空闲判据"，且 Manual 下整体作废）、§9 面板渲染
（数据层 `console_fields()` 已产出 §9 的七行）、§8 硬门的机器化。
搜索产物：`.workbuddy-ai/handoff/MODE_SYSTEM_SEARCH_20261006.md`。

### 7.5 真机优先开发流程（2026-10-06，操作者规范）

规范逐字落在 **`docs/DEVELOPMENT_FLOW.md`**（含 §八 落地进度与第 1、3 步的实测结论）。
核心是把开发顺序从"写完再试"改成"**先试再写**"：
`搜索 → 真机试 → 观察 → 写代码 → 真机验证 → 完成`，离线测试从**验收**降为**回归保护**。

**§八 只要求先做第 1、3 步，两步都已实测**：

- **单步探索能力：没有。** `tools/` 325 个 `.py` 里 161 个是一次性探针；没有任何工具能
  "执行任意一个动作"。最接近的 `probe_live_operation.py` 仍要事先给 `--goal/--label`，
  `device_l4_session*.py` 把测试清单写死在脚本里。
  **旁证**：2026-10-05 为了走到巨熊页签，我自己新写了 5 个临时脚本。
- **UI 知识库：有，且字段比规范多。** `knowledge/ui/` 12 项存储，
  `semantic_dictionary.json` 201 条记录、字段并集 **41 个**（规范只要求 12 项）。
  **缺三样**：使用限制（次数/冷却）、花费（免费/钻石/道具/不可逆）、联网搜索来源；
  可信度只有 2 档而规范要 4 档。**结构与规范不同**（按语义分片的 JSON，不是逐元素 markdown）。

**我在文档里给的判断（未做，待操作者确认）**：第 4 步**不建议**新建
`knowledge/ui/{pages,panels,controls,popups}/*.md`，而应把缺的四项加进**现有 JSON schema** ——
否则同一个 UI 会有两份记录，而"哪份是真的"正是本项目反复出问题的形状（见 §7.3 与
`docs/RULES_AUDIT_2026-10-05.md` 的冲突 C3/C4）。

**第 1、3 步之外还差一步裁决**：规范 §二 允许"坐标点击"作探索动作，而宪法 A
（`OPERATIONAL §24.2`）硬禁止固定像素坐标点击并自标"不设生产点击例外"。我的读法是
"宪法 A 管生产路径，探索不是生产路径"，**但这是我推导的，动手做第 2 步前应由操作者确认**。

---

## 8. 怎么刷新本文件

```bash
# 1. 重算型统计（注意：会覆盖 docs/CURRENT_TRUTH.md 与 learning/current_truth.json）
python tools/truth_audit.py

# 2. 运行时状态 / Goal 板（持续重写，约每 30 秒；要原子地读两份）
cat learning/runtime_snapshot.json
cat learning/goal_state.json

# 3. 生产提交
cat "E:\WinterAgent\.worktrees\winter-prod-pinned\PRODUCTION_PIN.json"

# 4. 主线近期提交
git log --oneline -15 codex/production-pin-recovery
```

刷新时请**同时更新顶部的「快照时间」与所用的 `active_role_id`** ——
没有角色，Goal 板的数字没有意义。
