# 待操作者裁决的决定 —— 汇总包（2026-10-14）

> **为什么要这个文件**：主路线现在**不会自己动**，堵点不是"没活干"，而是**一批决定只有操作者能下**。
> 这些决定此前**散在至少六份 handoff 里**（`RETIRING_…` / `THE_72H_…` / `THE_LEARNING_BUDGET_…` /
> `THE_PRELOAD_ROUTE_…` / `04_OPEN_ISSUES.md` / `03_NEXT_ACTION.md`），操作者要逐份读才能裁决。
> 本文件把它们收进**一页**：每条都给「问题 / 证据（file:line）/ 选项与后果 / 我的建议（**不具约束力**）/
> 不决定的代价」。
>
> **本文件不替任何一条做决定** —— 按项目既有尺子，凡是改**唯一台账的语义、闸门语义、操作者验收标准、
> 项目宪法**的，都是操作者的职权（先例：词表/阶梯上一次是操作者亲手加的，`escalation_queue.py:259-262`）。
>
> **复核基准**：`check_mainline.py = MAINLINE_OK`；pin==manifest==镜像 `7b8c973b`；镜像 `in_sync`；
> 设备仍 MANUAL。所有 file:line 均为本轮实读。

---

## 一、卡住**主路线**的两个决定（先看这两条）

### D-A · 是否解除 MANUAL，解锁设备

| 项 | 内容 |
|---|---|
| **问题** | 是否把 `learning/MODE_STATE.json` 从 `MANUAL` 切回 `AUTO`（释放 `user_latch`）？ |
| **证据** | `user_latch=true`，`started_at=2026-10-12T12:22:30Z`，`reason` 写明是操作员为"人工真机校准会话"让出设备。**一切真机验证**都卡在这；17 条待办里 6 条指名要一帧真机。**⚠️ 2026-10-14 复核补充：AUTO 线程本身也没在跑** —— `learning/runtime_snapshot.json` 实读 `runtime_thread_alive=False`、`scheduler_loop_alive=False`、`agent_state=IDLE`、最后 tick 停在切 MANUAL 的那一刻（`2026-10-12T12:21:24Z`）。**面板 / 模拟器 / adb 都活着**（`pythonw`×3、`MuMuVMMHeadless`、5037 LISTENING）⇒ **只翻 `MODE_STATE` 不会恢复 AUTO**（mode 只管权限）；缺的是**总览页点「开始自动运行」**（`control_panel.py:6015`）；**验收看 `runtime_thread_alive` 与 `scheduler_loop_alive` 都变 true**（不是看 mode==AUTO）。见 `AUTO_IS_DOWN_THE_BEAR_PROVIDER_IS_INERT_AND_A_BUDGET_TEST_PINS_A_FICTION_20261014.md` §一。 |
| **选项** | ① 现在解锁；② 等这次真机校准会话结束再解锁；③ 只在**一个受控窗口**内解锁（例如下一个巨熊窗口）。 |
| **建议（非约束）** | 若近期目标就是「巨熊准时参战」，**③ 最省**：链路在代码里已齐（见 D-B 同源 handoff `THE_BEAR_CHAIN_IS_BUILT_AND_HAS_NEVER_RUN_20261014.md`），只差"活的窗口 × AUTO 同框"一次。 |
| **不决定的代价** | 主路线**冻结**：所有"下一步"都退化成设备侧，离线只能做诊断，不能产生 LIVE 证据。 |

### D-B · 是否给台账加一个**诚实的"退役"outcome 词**

| 项 | 内容 |
|---|---|
| **问题** | 是否为升级台账增加一个能如实表达「**前提已不成立、且没有任何 job 跑过**」的 outcome（例 `NO_LONGER_REPRODUCIBLE`），并让新词在下游映射处显式走「**什么都不做**」分支？ |
| **证据** | ① `winter_agent_v2/escalation_queue.py` `ALL_OUTCOMES` 只有 8 个词，**没有一个能表达"前提已不成立且无 job 跑过"**（`NO_IMPROVEMENT` 最接近，但它断言"某 job 跑过且无改进"——与事实相反）。② `--correct` 机制上**能**把一条 `NEW` 移出待办（`tools/escalations.py:140-178`），但**每个可用 outcome 都在说假话**。③ `SUPERSEDED` 这个字**已被占用**（bootstrap 计划层，`capability_bootstrap.py:824/941`，语义不同）。④ 审计实测：17 条待办里 **11 条无法靠"再跑一次"消掉**（6 条前提已被生产数据证伪 + 3 条点名技能全流 0 次 + 2 条 goal 从未跑）。 |
| **影响面（已逐处量到 file:line）** | **只有一处是真决定**——`capability_bootstrap.py:3050-3054` 的 outcome→知识校准映射：新词**绝不能**把记录的知识记成"校准失败"（那条记录的知识可能完全没问题），必须显式走"什么都不做"。其余是机械的：`ALL_OUTCOMES` 加一个词 + 一条存在性断言 + 跑测试。`UNFINISHED_TRACE_OUTCOMES`（`:343-350`）**不用改**——新词自然不在里面，`unfinished_trace()` 会正确判"这 trace 已结束"，允许同能力再开新 job。 |
| **选项** | ① 加词（并让映射处显式 no-op）；② **只**把闸门 `detail` 那行拆成两个计数（"可复现的 Gap" / "不可复现的记录"）——**零语义变更**，不改任何判定；③ 什么都不做。 |
| **建议（非约束）** | **①＋②一起做**。②的影响面**明显小于**①（只改输出文案），且现在就能让操作者看到诚实数字；①让 11 条能被**合法**移出。 |
| **⚠️ 注意** | 闸门是**零容忍**的（`capability_bootstrap.py:1133` `pending_records > 0` 即不派单）⇒ **单退役 11 条不会打开闸门**（还剩 6 条要真机）。退役是**必要条件，不是充分条件**。 |

---

## 二、操作者**自己的标准**（改的是他们写下的验收/设计）

### D-C · 72h 验收的**算术**（在构造上不可能满足）

| 项 | 内容 |
|---|---|
| **问题** | 把 `.workbuddy-ai/rules/OPERATIONAL.md:14` 与 `docs/PROGRESS_2026_09_14.md:81` 的 `unexpected_worker_exits = 0` 改成「**相对某基线只增**（验收窗口内不增长）」，还是明文规定"验收前重置/记录基线"？ |
| **证据** | 计数器**只增不减**：`tools/control_panel.py:9191/9237` 都是 `previous + (1 if counts_as_exit else 0)`；**全仓库无重置路径**；历史值**有意保留**（`.workbuddy-ai/commander/REVIEW_REQUESTS.md:72`）；现值 **59**（`learning/runtime_snapshot.json`，本轮实读）。⇒ 一台**历史上死过 worker** 的机器，`= 0` **永远不再成立**。 |
| **同源先例** | 面板看门狗**已**用"相对本窗口首见值的增长"，docstring 原文：`the literal was implemented first and measurement killed it on this very machine … > 0 therefore measures the machine's history rather than the present`（`tools/control_panel.py:5723-5735`）。⇒ 改标准 = 用**面板已经用过的同一把尺子**。 |
| **选项** | ① 改成 growth-relative；② 保留字面 `= 0` 但明文加"验收前记录基线/重置"步骤；③ 不改。 |
| **建议（非约束）** | ①，与面板先例一致，且保住本意（"一次意外退出就是信号"），只修**算术**。 |
| **不决定的代价** | 这道门**永远不会开**——不是系统不可靠，而是**累计计数器被拿来和 0 比**。下一个读到 `59` 的人会自己猜它是不是"59 次崩溃"。 |

### D-D · `max_bootstrap_visits_per_run` 这条**声明存在、行为不存在**的预算

| 项 | 内容 |
|---|---|
| **问题** | 删掉那条死支（**诚实化，不改行为**），还是给 `visits_this_run` 一个**真正的运行边界**？ |
| **证据** | `DEFAULT_BUDGET["max_bootstrap_visits_per_run"] = 1`（`capability_bootstrap.py:102`）**被声明却在生产里从不生效**——读它的唯一生产调用方传的是 `_bootstrap_state()` 过滤后的字典，而 `_bootstrap_state()`（`runtime.py:2214-2219`）**只保留带 `cooldown_until` 的条目**⇒ 无 `cooldown_until` 的 `__run__` **被丢掉**⇒ `run.get("visits_this_run")` 恒为 `None`⇒ `0 >= 1` 恒假。 |
| **⚠️ 看起来该做的修法是错的** | 自然修法"让载入器保留 `__run__`"**不要做**：`visits_this_run` **被永久写成 1**、**无任何复位点**⇒ 一旦真被读到 `1 >= 1` **恒真**⇒ **学习窗口被永久关掉**——而 `runtime.py:2232-2233` 的 docstring 记的正是这个后果（`The learning window was closed permanently and nothing said so.`）。 |
| **选项** | ① 删掉死支（`capability_bootstrap.py:198` 的 `visits_this_run` 项）——只是诚实化，不改行为；② 给它一个真边界——但那要先定义"一次 run"是什么（worker **每循环换进程**，所以"进程"≠"run"）。 |
| **建议（非约束）** | ①：最低风险、与"声明应与行为一致"一致。② 在"run"被定义之前不做。 |
| **相关** | `tests/test_runtime_capability_discovery_lane.py` 钉着这条巷子。 |

---

## 三、数据 / schema 类待裁决

### D-E · 478 行旧 schema episode（占语料 35%）

| 项 | 内容 |
|---|---|
| **问题** | 该给它们标 `mode=LEGACY_SELF_REPORTED`（**保留但降级**），还是**只在新统计里忽略**？ |
| **证据** | `04_OPEN_ISSUES.md` 第 0at 条：478 行无 `recorded_at`，`mode=PRODUCTION` 但**无 `episode_id` / 截图 / `verifier_ok`**，**污染所有历史指标**。总表已加 `evidence_policy` 临时排除；**§18 禁止删历史**。 |
| **建议（非约束）** | 标 `LEGACY_SELF_REPORTED`（保留可追溯 + 让统计口径自解释），不删。 |

### D-F · 本地面板模型的调用超时余量

| 项 | 内容 |
|---|---|
| **问题** | 是否调 `config/v2.json` 的 `local_planner` 超时？ |
| **证据** | `04_OPEN_ISSUES.md` 第 P1-2 条：`DEFAULT_TIMEOUT_S=60` 而实测耗时 **30–37 s**，`LOCAL_GUI_MODEL_UNAVAILABLE` **63 次/日**。属操作者写进 `config/v2.json` 的段。 |
| **建议（非约束）** | 余量偏小（30–37s 对 60s），若那 63 次/日里确有真超时，给到 ~90s 是低风险调整；需操作者确认口径。 |

### D-J · 回归（pytest）从**哪棵树**跑 —— 计数口径（2026-10-14 新增）

| 项 | 内容 |
|---|---|
| **问题** | 把"回归通过"的口径固定下来：从 **pin 树**跑（规范集），还是从**数据根**跑（有 `.venv`）？ |
| **证据** | 实测同一提交 `66bf7630`：**pin 树 5753 条**；**数据根恢复前 5561 条**（其 `tests/` 工作树停在 2026-10-08 之前）、**恢复后 5799 条**（= 5753 ＋ 6 个 untracked 草稿测试的 46 条，其中 **3 条红**）。文档里那条回归命令的 cwd 正是**数据根**（`03_NEXT_ACTION.md:1981`）⇒ 历史"N passed"可能测在**少 192 条**的旧集上。见 `THE_DATA_ROOT_IS_NOT_A_CHECKOUT_OF_ITS_OWN_HEAD_20261014.md`。 |
| **选项** | ① 固定从 **pin 树**跑（用数据根的 venv）；② 从数据根跑但**每次先 `git checkout -- tests/`** 对齐；③ 保持现状，并在引用数字时**注明树与 cwd**。 |
| **建议（非约束）** | **②**：数据根有 venv 与 `--basetemp` 约定，加一步对齐即可得规范集；①亦可。**关键是让"跑了多少条"可复现。** |
| **不决定的代价** | 回归数字**不可比**：同一个"通过"可能是 5753 条，也可能是 5561 条。 |

---

## 四、长尾（**2026-10-14 复核进度**）

> 三条原只在 `03_NEXT_ACTION.md:47`（2026-10-11 段）与 `10_LAST_HANDOFF.md:228` 有记录。
> **2026-10-14 已复核 D-G 与 D-H**（见 §四·补 / §四·补²，两条已在表中划掉）；
> 下面**只剩 D-I 未复核**。每条"之后发生了什么"都写在对应的 §四·补* 里 —— 这正是当年踩过的坑
> （**引用一节 = 有义务问它之后发生了什么**）。

| # | 事项 | 记录处 |
|---|---|---|
| ~~D-G~~ | ~~`pages.json` 与 `Page` 的 **15 名分歧**~~ → **✅ 2026-10-14 已复核，见 §四·补** | — |
| ~~D-H~~ | ~~**90 个候选无试跑路径**~~ → **✅ 2026-10-14 已复核（逐字复现），见 §四·补²** | — |
| D-I | 设备上**第二个自动化**的处置 | `03_NEXT_ACTION.md:47`、`10_LAST_HANDOFF.md:228` |
| ~~D-K~~（新） | ~~**`BEAR_AUTO_JOIN` 不在可派发集**~~ → **✅ 2026-10-14 已答：链不需要它，不是阻塞点**（见 §四·补³） | — |

### §四·补 · D-G 已复核（2026-10-14）

**结论**：分歧就是 **15 个名字**（`Page` 枚举 22 · `pages.json` 29 · 交 18）——
只在枚举 **4** 个（`LOADING` `MAINTENANCE` `PET_TREASURE` `UNKNOWN`）；
只在清单 **11** 个（`ARENA` `BEAR` `DANGER_TRAVEL` `ENDLESS_JOURNEY` `GIANT_BEAST` `PET` `PROFILE` `SETTINGS` `SNOWFIELD_TRAVEL` `UNDERGROUND_EXPLORATION` `VIP`）。

**要决定的是**：两套里哪一套**权威**。`knowledge/ui/pages.json` 的 `pages` 是
`capability_bootstrap.py:1493-1527` 那个 drift 闸门的**唯一**词表（spec 的 `required_page`
不在其中即报"没有 reader 能读出它"）。而清单比枚举**多 11 个** ⇒ 对那 11 个名字闸门**过宽**：
会放行"声明了、却没人能读出"的 spec。**潜在，不是现行**：今天 **0 条 spec** 声明这 11 个名字
（已逐一实测）；反向那 4 个里 `PET_TREASURE` 是真页面却不在清单 ⇒ 声明它会被**误报**。
见 `THE_PAGE_VOCABULARIES_DIVERGE_BY_FIFTEEN_NAMES_20261014.md`。

**选项**：① 闸门改按 `Page` 枚举（或枚举 ∩ 清单）校验；② 明确 `pages.json` 是"已知/超前清单"、
不作判据，另立字段表达"计划中"；③ 不动，只记录。
**建议（非约束）**：因读取器**只能**返回枚举，**①** 更贴事实；但改的是闸门 → 应单独审。

### §四·补² · D-H 已复核（2026-10-14）

**结论**：D-H **没有被推翻，逐字复现**。用同一条只读脚本
（`knowledge/ui/screenshot_audit/_scripts/measure_candidate_trials_20261010.py`）重跑：
**102 候选 · 12 合格 · 90 被挡 = 78 `semantic_contract_incomplete` + 10 `no_bound_verifier`
+ 2 `risk_not_allowed:MEDIUM_COMBAT`**。出处 `V2_FINAL_ACCEPTANCE_REPORT.md` §12.5
已带 2026-10-11 的更正块。⇒ **处置不变**：让那 78 个可试需**逐条撰写 semantic contract**，
而"按相似度映射＝猜测"被项目禁止 ⇒ 仍是**决策**，不是执行。

**顺路两件（性质不同）**：
- ✅ **候选闸门不挡巨熊链**：`OPEN_BEAR_RALLY_LIST` / `START_RALLY` / `JOIN_RALLY`
  **都在 `LiveRuntime.VERIFIED_ATOMIC`**（虽状态为 CANDIDATE）⇒ 走生产派发，不受候选池限制。
- ⚠ **`BEAR_AUTO_JOIN` 两条路都派不发**：既不在 `VERIFIED_ATOMIC`、也不在 `BEAR_SKILLS`，
  而它有生产状态守卫（`executor_router.py:679`）、巨熊 playbook 前置里要"看 AUTO_JOIN 状态"。
  **是否构成缺口未定论**（手工加入可绕开）——列在 D-I 之后供裁。
- 池里**冻结的变成两个**：`RESEARCH: 566` 与 **`OPEN_QUICK_PANEL: 12`**（§12.5 只点了前者），
  两者都在"12 eligible"名单里 ⇒ §12.5 点名的"blocked candidate is invisible"**仍活**。
见 `THE_NINETY_BLOCKED_CANDIDATES_REPRODUCE_AND_TWO_FREEZE_20261014.md`。

### §四·补³ · D-K 已答（2026-10-14）：巨熊链**不需要** `BEAR_AUTO_JOIN`

**答案：不是阻塞点。** `PARTICIPATE_BEAR` 的路由用
`BEAR_SKILLS = {START_RALLY, JOIN_RALLY, OPEN_BEAR_RALLY_LIST}`（三个都已在
`LiveRuntime.VERIFIED_ATOMIC`），**不含** `BEAR_AUTO_JOIN`。自动加入只是 playbook 的一条
**策略分支**（"auto_join_on → 先观察、JOINED 直接 PASS"）；读不到它只意味着**少一条快路**，
链仍走 LIST_DYNAMIC 手工加入。

**顺带查实**：`ALLIANCE_TIMED_EVENTS` provider 的 `READY` 分支**不可达且惰性** ——
它要的 `auto_join_enabled` / `joinable_rally_count` **生产里零写入**
（前者只有测试造过，后者全仓无键位写入），而 `provider_state` **全仓零消费者**、控制台也不显示；
可用的读取器却在闲置（`rally.RallyListReading.joinable_bears()`、`bear_state.read_state_from_image()`）。
⇒ **没有接线**：接上去的产物无人消费 = churn；要让计数有意义，先得给它一个**真消费者**（设计决定）。
见 `AUTO_IS_DOWN_THE_BEAR_PROVIDER_IS_INERT_AND_A_BUDGET_TEST_PINS_A_FICTION_20261014.md` §二。

### §四·补⁴ · D-D 补充（2026-10-14）：预算有**第二个**生产读者，且测试钉了**虚构**

- **更正**：`max_bootstrap_visits_per_run` **不是"只有一个调用方"** ——
  `runtime.py:2245-2255` 的 `_learning_window_open` **也读它**，而且**它同样读到 0**
  （`_bootstrap_state()` 丢掉 `__run__`）⇒ 每进程第一次调用**恒 True**。
  上一轮结论（"真正的界是 `_learning_window_used`"）**对**，但读数**不完**。
- **假信心**：`tests/test_learning_window.py:56` 用 `_Harness`，而它的 `_bootstrap_state()`
  **只是 `return self._state`**、**绕过**真实过滤器 ⇒ 该测试断言的"预算拒绝"**生产里不可能发生**
  （生产 `visits` 恒 0）。改它触及"预算该不该咬合"这个**设计决定** ⇒ 本轮**未改**。
- ⇒ D-D 的处置因此**多一层**：删死支（①）会**碰红**那个测试 ⇒ 必须先决定预算的去留。

---

## 五、各决定解锁什么（一张表）

| 决定 | 一旦裁决，立刻解锁 | 仍被别的决定挡着 |
|---|---|---|
| **D-A 解锁设备** | 6 条待真机的记录可被重新检验；巨熊窗口可实测；一切 LIVE 验证 | —— |
| **D-B 加退役词** | 11 条不可复现记录可被**合法**移出待办 | 闸门仍被 6 条要真机的记录关着 ⇒ 还要 D-A |
| **D-C 72h 算术** | "近期验收"这道门**第一次变得可满足** | 仍需真实连续运行 |
| **D-D 删死支** | 预算表不再声明一个不生效的项（诚实化） | ——（纯诚实化） |
| **D-E 标 LEGACY** | 历史指标口径自解释 | —— |
| **D-F 超时** | 减少 `LOCAL_GUI_MODEL_UNAVAILABLE`（若确为超时） | —— |
| **D-J 回归口径** | "回归通过"有了**可复现的计数**（树/cwd 固定） | —— |

**已结（无需裁决，只留档）**：**D-G**（两套页面词汇表差 15 名；`pages.json` 是那个 drift 闸门的**唯一**词表，
比 `Page` 枚举多 11 个 ⇒ 那 11 个名字上闸门**潜在过宽**，今天 0 条 spec 受影响）、
**D-H**（90 被挡候选 = 78+10+2 **逐字复现**，处置不变；池里**两个**合格候选被冻结）、
**D-K**（巨熊链**不需要** `BEAR_AUTO_JOIN`）—— 都在 §四·补* 里，**已不是待决项**。

**最省的一条路**：**D-A ＋ D-B** 一起下 ⇒ 主路线的**两个堵点同时解除**（设备 ＋ 台账）。
D-C/D-D/D-E/D-F/D-J 是"标准与诚实化"，不挡主路线，但挡住"验收"与"口径"。

---

## 六、未做

**没有替任何一条做决定**：没加 outcome 词、没改 `--correct`、没改 `preload_gate`、
没改 `OPERATIONAL.md`、没加重置路径、没改预算/载入器、没给旧 episode 打标、没动设备、
没改 `config/v2.json`。本文件**只汇总**，不越权。
