# P0 事实审计：Goal → Scheduler → Learning → Executor 全链路

审计时间 2026-10-02T21:20 (Asia/Shanghai)　审计时 HEAD `cd35aad`
方法：只读。不改任何生产代码。所有数字来自生产账本，不来自设计文档。

---

## 结论先行（一句话）

**"Goal 已发现但没进入可执行/可学习链"这个前提，在生产事实上是错的。**
Scheduler **已经**把这些目标选了 141 次、产出了 129 条 episode。
真正的断点不是"进不去"，而是**"进去了，但产出的动作与目标无关"**——
选中之后没有任何一层把 `observation-ticket` 兑现成一次真正的**观察**，
于是 brain 落进通用分支，去做了 `OPEN_MAP` / `SELECT_RESOURCE`（采集），
这些动作与 `SCHEDULED_*` 目标没有任何关系，却因为 verifier 只检查"页面切换是否发生"
而被记成 **89 次 SUCCESS**。

**这是一个比"0 次尝试"更坏的状态：它在账本上看起来是成功。**

---

## 一、生产事实重建（实测数字）

### 1.1 面板显示的 23 行"未知/待规划"，后端实际状态

面板渲染代码 `tools/control_panel.py:4462-4466`：
```python
skills = ", ".join(goal.get("available_skills", ())) or "待发现"
... (goal.get("available_skills") or ["待规划"])[0] ...
```
⇒ **面板的"下一动作"列不是 `next_action` 字段，它就是 `available_skills[0]`。**
后端 `learning/goal_state.json` 里**根本没有 `next_action` 这个键**（31 个 goal 全量键集已核对）。
所以面板显示"待规划"是**如实反映后端**：后端确实没有 next_action，因为后端没有产生过。
按指令第九节，这属于"backend 本身就是 next_action=None ⇒ 修 Scheduler/Planner"，**不是 UI 问题**。

### 1.2 但 Scheduler 已经选了它们 —— 与"待规划"矛盾

生产账本 `learning/decisions.jsonl`（2000 行，2026-10-01T02:19 → 2026-10-02T13:17）：

| 指标 | 实测值 |
|---|---|
| 因 `observation-ticket` 被选中的决策数 | **141** |
| 涉及的 SCHEDULED/UNKNOWN 目标 | 24 个 |
| `ALLIANCE_TIMED_EVENTS` | 38 次 |
| `LABYRINTH_DAILY` | 32 次 |
| `USE_FREE_ARENA_ATTEMPTS` | 30 次 |
| `SCHEDULED_*` 合计 | 41 次 |

选中时页面分布：MAP 57 / HOME 51 / MARCH 16 / RESOURCE_DETAIL 6 / 其他 11。
**没有一个是在活动页（日历）上被选中的。**

### 1.3 这些选择产出了 129 条 episode —— 但内容与目标无关

`learning/episodes.jsonl`（10475 行）中 goal_id 属于该族的有 **129 条**：

| 实际执行的技能 | 次数 |
|---|---|
| `OPEN_MAP` | 43 |
| `SELECT_RESOURCE` | 38 |
| `START_GATHER` | 12 |
| `CLEAR_GATHER_HEROES` | 11 |
| `SUBMIT_RESOURCE_SEARCH` | 10 |
| `INTEL_HERO_DISPATCH` | 8 |
| `DISPATCH_MARCH` | 3 |
| 其余 | 4 |

`result`: **SUCCESS 89 / FAILURE 40**；`verifier_ok`: True 89 / None 39 / False 1。
`recognition_error`: 空 82 / `UNKNOWN_NAV:NOT_A_NAVIGATION_ACTION` **21** / `MAA_TEMPLATE:NO_MATCH` 8。

**读法**：一个"兄弟手臂活动"目标被选中后，系统去点"打开地图"和"选资源"，
89 次被 verifier 判为 SUCCESS。**这些 SUCCESS 对该目标的推进贡献为零。**

---

## 二、真实生产链（按代码实际调用关系重建）

| 层 | 文件:函数 | 输入 | 输出 | Gate | 失败状态 | 调用者 |
|---|---|---|---|---|---|---|
| Goal 发现 | `goal_library.GoalLibrary.discover` | WorldState | Goal 列表 | — | 字段未填⇒分支不可达 | `runtime` 动作循环 |
| 定价 | `goal_utility.utility` → `observation_ticket` | Goal | base=50.0 | status==UNKNOWN **且** `required_observation` 非空 | 否则 `-inf` 且被 `rank` 丢弃 | `goal_utility.rank` |
| 排序 | `goal_utility.rank:631` | goals+ledger | 有序列表 | `if not available_skills and ticket<=0: continue` | 无技能**且**无票⇒出局 | `runtime._selectable` |
| 选择 | `runtime._selectable:1134` | 排序结果 | 可选集 | `route_for(id) is None` ⇒ 具名拒收 | `MISSING_NAVIGATION` 叙述 | `runtime` 动作循环 |
| 同步 | `runtime._sync_brain_goal:1404` | best_goal | `brain.current_goal = route_for(id)` | 同上 route 门 | route=None ⇒ brain 默认分支 | brain |
| **规划** | **`brain.RuleBrain.decide:619`** | world+registry | Decision | 按 `world.page` 与 `current_goal` 分支 | **★断点★** | `runtime` |
| 执行 | `executor_router` → MAA/ADB | Decision | episode | — | — | `runtime` |
| 校验 | `verifier` | before/after 帧 | ok/fail | 只校验该技能自身的语义 | **★污染★** | `runtime` |
| 学习 | `unknown_learning.record_verified_step` | episode | CandidateStep | — | — | `learning_funnel` |

---

## 三、标记（按指令第三节的六种标记）

### `UNKNOWN_LEARNING_GAP` —— **确认存在，且是最高价值瓶颈**

`observation_ticket` 有**生产者**（`goal_utility.utility:583`）和**消费者**（`rank:631` 的过滤条件），
但**没有任何一层把票兑现成一次观察**。全仓搜索 `required_observation` 的消费者只有 4 处，
全部是**报告/诊断**，没有一处驱动执行：

- `capability_bootstrap.py:181` —— 统计诊断
- `task_completion.py:193,199` —— 生成人类可读原因
- `goal_library.py` —— 生产者

`learning/observation_state.json` 里有 `domains: {stamina, alliance, ...}`，
最后写入时间 **2026-09-30**，而决策账本已经跑到 **2026-10-02T13:17**。
⇒ **观察存储三天没动。**票在发，观察没做。

⇒ **`observation_ticket` 是一条只到 Scheduler 就断掉的线。**
Scheduler 把它当成一个普通目标选了，然后 brain 对 `SCHEDULED_*` 的 route（`EVENT`）
只有 `Page.EVENT` 上的分支；实际选中时页面是 MAP/HOME/MARCH，
于是 `decide` 一路穿过所有 `if` 落到末尾的 `registry.ready(world)` 兜底
（`brain.py:2903`），取第一个非 WAIT 技能——那就是 `OPEN_MAP`。

### `VERIFICATION_GAP` —— **确认存在，形式特殊**

不是"没有 verifier"，是 **verifier 判据与目标无关**：
`OPEN_MAP` 的 verifier 问"是否到了 MAP 页"，到了就 PASS。
它无法回答"这次点击是否推进了 SCHEDULED_BROTHERS_IN_ARMS"。
⇒ **89 次 SUCCESS 是 verifier 说谎，不是系统做了事。**
`learning_funnel` 把这些 SUCCESS 当作学习素材，会把无关动作固化成"已学到的步骤"。

### 不成立的标记（据实排除，避免误修）

- ❌ `DEAD_GOAL_PATH` —— 不成立。24 个目标全部到达了 Scheduler（141 次选中）。
- ❌ `SCHEDULER_STARVATION` —— 不成立。fairness 账本显示 `ALLIANCE_TIMED_EVENTS` 等
  `offered=0/selected=0`，但那是**测试夹具写进生产账本的污染**（见第五节），
  生产决策账本里它们合计被选 100 次。**不能用 fairness 账本判断饥饿。**
- ❌ `EXECUTION_WIRING_GAP` —— 不成立。executor 正常执行。

---

## 四、死锁环（指令第十节）

**没有 A→B→C→A 的环路。**真实的是一个**开环**：

```
observation_ticket 发票(50.0)
   → rank 放行 → _selectable 放行(route 已补)
   → brain.decide 对 EVENT route 在 MAP/HOME/MARCH 上无分支
   → 落到 registry.ready() 兜底 → OPEN_MAP
   → verifier 判 SUCCESS（只验页面切换）
   → 观察从未发生 → 目标永远 UNKNOWN → 票永远 50.0 → 永远重复
```

**解除条件**：在 `brain.decide` 里为"持有 observation ticket 的目标"提供一个
**页面无关的观察动作**（打开日历/进入活动页读一次真实状态），
或者在 runtime 层把 ticket 兑现为一次 `DISCOVER_*` 类动作。
**当前没有任何一层做这件事。**

---

## 五、两条证据完整性问题（必须记录，否则会误导后续判断）

### 5.1 生产公平性账本被测试夹具污染 —— P0

`learning/goal_fairness.json`（66 个目标）中，20 个 SCHEDULED 目标的
`last_block_reason` 是**测试代码里的字面量**：

```
"the test defers every path: nothing is selectable anywhere"
"held out of the way by this test"
```

来源：`tests/test_no_repeated_look_around.py:163`、`tests/test_march_reservation_handover.py:139`。
`tests/conftest.py` 的 `WINTER_TEST_RUNTIME_ROOT` 重定向**没有拦住这条路径**。
⇒ **该账本中 20 个 SCHEDULED 目标的 `offered=0` 是假的**，不能用作"从未尝试"的证据。
真实尝试次数必须读 `decisions.jsonl` / `episodes.jsonl`。

### 5.2 `fairness.json` 未被 git 跟踪

`git ls-files learning/goal_fairness.json` → 不在版本控制内。
⇒ 它的污染无法通过 git 回滚修复，也无法通过 diff 发现。

---

## 六、按指令要求统计的十项指标（生产实测）

| # | 指标 | 实测 | 口径 |
|---|---|---|---|
| 1 | GOAL_EXISTS | 34 | `full_auto_coverage_audit` AUTO_DISCOVERABLE |
| 2 | AUTO_DISCOVERABLE | 34 | 同上 |
| 3 | PLANNABLE | 34 | 有 route（WB-1002-24 后 route 缺失已归零） |
| 4 | EXECUTABLE | 33 | verdict=SCHEDULER_CANDIDATE |
| 5 | LEARNABLE | **0** | ★ 无任何学习任务进入执行 ★ |
| 6 | ATTEMPTED | **24 个目标 / 141 次 / 129 episode** | decisions+episodes |
| 7 | PRODUCTION_TRIED | 24 | 同上 |
| 8 | PRODUCTION_VERIFIED | **0** | ★ 89 次 SUCCESS 与目标无关，不计 ★ |
| 9 | BLOCKED | 1（BOARD_ONLY_STATUS） | |
| 10 | NEVER_TRIED | **0**（真实） | 公平性账本的 38 是污染，见 5.1 |

**核心 KPI**
- `UNKNOWN_NEVER_TRIED_RATE` = **0.0**（不是问题；这些目标全都被尝试过）
- `PRODUCTION_TRIED_RATE` = 24/34 = **70.6%**（不是问题）
- **新瓶颈指标 `UNKNOWN_TRIED_BUT_ZERO_MEASURED_PROGRESS_RATE` = 24/24 = 100%**
  —— 每一个被尝试的 UNKNOWN 目标，其观察进度仍然是 0。

**结论：指令诊断的现象是真的，但它归因错了。**不是"进不了链"（0 尝试），
而是"进了链、产出了无关动作、并被 verifier 记成成功"。
**按"尝试次数"驱动的任何验收（指令第八、十二节）此刻都会判定通过——那正是危险所在。**

---

## 七、指令与事实的三处冲突（据实拒绝）

1. **第十二节验收标准第 1 条"至少 3 个 UNKNOWN+NEVER_TRIED 目标被真实 AUTO 尝试"**
   —— 此条件**当前已经满足**（24 个目标 / 141 次）。若照此验收，会得出"链路已通"的错误结论。
   真正的验收必须是"被尝试 **且观察读数发生变化**"。

2. **第十一节 `UNKNOWN_NEVER_TRIED_RATE` 持续下降作为目标**
   —— 该指标已为 0，无可下降。**方向错了**：真正该下降的是
   `UNKNOWN_TRIED_BUT_ZERO_MEASURED_PROGRESS_RATE`。

3. **第八节"0 attempt 不可接受"**
   —— 事实是 0 attempt 从来不是本项目的问题。**把 89 次假 SUCCESS 修成诚实的 0 attempt，
   反而是退步。**必须同时给出观察路径，否则就是把成果退回去。

---

## 八、最高价值瓶颈（单一）

**`observation_ticket` 有票无兑现：`required_observation` 声明了要读什么，但没有任何代码去读。**

解除它需要三件事，按顺序：
1. **观察动作存在**：为持票目标提供一个页面无关的入口动作（进入日历/活动页读一次）。
2. **verifier 绑定到目标**：verifier 必须能回答"该目标的 `required_observation` 是否被读到"，
   否则第 1 步产出的读数不会进账。
3. **观察读数回写**：`observation_store` 写入（当前停在 2026-09-30），
   且 `task_completion` 的 `execution_readiness` 能因观察而改变。

**在这三件事完成前，任何针对单个 Skill 的补丁都是在给一条断掉的线接更长的上游。**

---

## 附：本审计使用的证据文件

- `learning/goal_state.json`（31 goal，最后写 2026-10-02T13:16）
- `learning/decisions.jsonl`（2000 行，2026-10-01 → 2026-10-02T13:17）
- `learning/episodes.jsonl`（10475 行）
- `learning/goal_fairness.json`（**已污染，见 5.1**）
- `learning/observation_state.json`（**停在 2026-09-30**）
- `tools/full_auto_coverage_audit.py` 输出 → `.workbuddy-ai/audit/cov_20261002.json`
- 代码：`goal_utility.py:431/575/631`、`runtime.py:1134/1404`、`brain.py:619/2903`
