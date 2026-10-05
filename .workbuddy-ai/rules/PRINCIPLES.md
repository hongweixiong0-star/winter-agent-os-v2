# PRINCIPLES — 原则层规则（《FINAL》+《不许停》可执行版）

**本文件是《WorkBuddy 持续自主开发总指令 FINAL》73 条与《持续开发，不许停》8 节的权威可执行版。**
逐字原文在 `FINAL_FULL.md` / `PERSISTENT_DEVELOPMENT.md`；措辞有争议时**以逐字原文为准**。

建立：2026-10-06。依据：`docs/RULES_AUDIT_2026-10-05.md`。
**节号原样保留**——代码里有 100+ 处 `section NN` 引用，重新编号会切断这条线索。

标签：`[A]` 核心必须留　`[B]` 留但已改写　`[废止]` 已失效，见文末清单　`[并入§N]` 内容移到该节

---

## 一、《FINAL》§0–§72

**§0 发送前须知 / 最高治理规则** `[A]`
冲突按 9 级阶梯裁决（见 `README.md §2`，2026-10-06 补入宪法 A/B）。
模块名、状态设计、调度规则、优先级、权重、阈值、流程、伪代码都是
**DESIGN INTENT / IMPLEMENTATION SUGGESTION，不是机械规格**。

**§1 项目最终目标** `[A]` 长期无人值守自主运行，人工干预越来越少。KPI 见 §70。

**§2 当前核心架构不变量** `[A]`
ONE Global Scheduler / ONE Executor / ONE WorldState / ONE Goal Library /
ONE Skill Registry / ONE Runtime local model。
MAA 只执行；Verifier 是成功唯一裁判；UI-Venus 只提案，没有 Promotion 权限。

**§3 开发前必须做 Architecture Review** `[A]` 12 问：
Goal 还能被发现／还能进 Scheduler／还有机会被选中／不会做时还有 Learning 入口／
失败后还能 Retry／Verifier 仍可达／一个 Goal 失败会不会阻塞整个 AUTO／
一个角色失败会不会阻塞另一角色／UI-Venus 离线时 AUTO 是否继续／
会不会形成永久不可达／会不会让高价值 UNKNOWN 饥饿／会不会制造第二套状态真值。

**§4 永久反例：UNKNOWN 黑洞** `[A]`
任何"因为现在不会，所以永远不做"的路径都是缺陷。与 §19、§20 是同一不变量的三种机制，不合并。

**§5 Goal Value 与 Execution Readiness 必须解耦** `[A]`
价值评分不得因当前不可执行而降为 0 或从盘面消失。

**§6 所有启用 Goal 必须属于 AUTO** `[A]` 只要用户没禁用这个 Goal，它就在 AUTO 里。

**§7 AUTO 不是 Skill Runner** `[A]` AUTO 是目标驱动的仲裁循环，不是技能清单执行器。

**§8 AUTO 统一包含三种工作** `[B]`
生产 / 发现 / 学习三类工作并存，不得只做一类（原 §41 已并入本节）。

**§9 当前阶段：CAPABILITY_EXPANSION** `[废止]` 时间性阶段标记，无日期无退出条件；
其优先原则已由 §58 完整表达。

**§10 Learning Budget — 至少 50%** `[B]`
学习投入不低于一半。**判定缺失**：`learning_share` 等符号全仓 0 命中，
补出度量前不得引用（见 `README.md §7`）。

**§11 Learning Budget 不是机械时间切片** `[废止]` 纯解释 §10。

**§12 Learning 何时让路** `[A]` 有硬 Deadline、高损失任务、严重队列浪费时学习让路。

**§13 高价值 UNKNOWN 是一等公民** `[废止]` §14 给定义、§31 给动作，本条只剩口号。

**§14 High-Value UNKNOWN 定义** `[A]` 升权与预算的前提，定义见逐字原文。

**§15 Unknown 动态 Learning Score** `[A]` 落点 `winter_agent_v2/goal_utility.py`。

**§16 长期不解决要升权，短期失败要退避** `[A]`

**§17 Cooldown 默认基线** `[B]`
原文 60s / 10min / 1h、正常上限 1h。
**实况（2026-10-06 按 R5 以代码为准）**：无阶梯，只有子系统硬编码
`stamina_supply.py:66 = 1800`、`skill_repair.py:58 = 3600`、`unknown_advisor.py:82 = 3600`。
需要阶梯时由操作者重新指定档位，再动代码。

**§18 Cooldown 不是死时间锁** `[A]` 条件发生变化可以提前重试。

**§19 Unknown 失败不能永久 CapabilityGate** `[A]`

**§20 UNKNOWN 不能作为永久 NOT_ACTIONABLE** `[A]`

**§21 Safe Bootstrap** `[A]` 落点 `winter_agent_v2/capability_bootstrap.py`（2891 行）。

**§22 Bootstrap 允许的行为** `[A]` 导航／观察／读取／构建 Candidate／准备 Verifier。

**§23 UI-Venus 必须能从 0 到 1 补能力** `[A]`

**§24 Known 路径继续保持 0 模型** `[A]`
判定：`learning_funnel.py:577 KNOWN_MODEL_CALLS`（数账本行，而不是断言为 0）。

**§25 Incremental Skill Acquisition** `[A]`
落点 `winter_agent_v2/unknown_learning.py`——`LearnedStepCandidate` / `CandidateSkill`，
只记语义链，永不存坐标。

**§26 FIRST / SECOND ENCOUNTER** `[A]`
SECOND 必须 `MODEL_USED = false`；Candidate 失败走 bounded recovery → Venus fallback，
不得让 Goal 永久卡死。落点 `runtime.py`。

**§27 Failed Attempt 也是知识** `[A]`
失败必须记 Negative Evidence（这个按钮不是控件／这个页面不是目标页／这个 navigation 无效／
这个模板已失效／这个 SemanticAction 没有 Goal Progress／这个 proposal Grounding 失败），
并让 UI-Venus 与 Skill Repair 看到 recent rejected actions。
**落地状态待查**：`negative_evidence` / `rejected_action` 符号全仓 0 命中。

**§28 Capability Coverage Matrix（13 状态）** `[废止]`
13 个状态里 8 个零实现。口径以代码的 6 值为准（R4），见 §29。

**§29 Coverage 固定成熟度 L0–L5** `[B]`
**改写为代码实况**：`FULLY_LIVE_VERIFIED / PARTIAL / NEVER_TRIED / BLOCKED / DEGRADED / MISSING`
（`winter_agent_v2/capability_coverage.py:46-51`）。
原 `COVERAGE_COMPLETE` 代码零命中，**不得作为判据**。

**§30 Continuous Goal 的 L5 定义** `[A]`
`MAA_EXECUTED` / `STEP_VERIFIED` / `PRODUCTION_TRIED` 都不能冒充 `COVERAGE_COMPLETE`。
采集=真实派出+WorldState 确认；训练=进入训练态+queue 确认；建筑=BUILD_STARTED+queue/timer 确认。

**§31 NEVER_TRIED 自动升权** `[A]`
排除：POLICY_DISABLED / SCHEDULED_NOT_OPEN / 明确环境不可用 / 真钱或明确 Unsafe。

**§32 所有过滤逻辑属于高风险代码** `[A]`
每个 `if ...: continue`、`return -inf`、`return []`、`NOT_ACTIONABLE`、`BLOCKED_STATUSES`
都要问：这是"当前不能直接执行"，还是"整个 Goal 应该永远消失"？绝大多数是前者。

**§33 Role Session** `[A]`
角色粘性，但可以因硬 Deadline／高损失任务／队列浪费／高价值学习窗口而切换。
一个角色 Blocked **绝不能**阻塞另一个角色。落点 `winter_agent_v2/role_session.py`。

**§34 GLOBAL_WAIT 严格限制** `[A]`
只要还存在安全可探索的 UNKNOWN，`GLOBAL_WAIT = BUG`。落点 `scheduler.py:1129`。

**§35 Idle 时间必须用于成长** `[A]` 落点 `runtime.py` 的 `LEARNING_WINDOW`。

**§36 调度防饥饿** `[A]`
每次改 Scheduler 必须模拟 A–Q 共 17 个场景，证明无饥饿、无死锁、无无限重试、无假 GLOBAL_WAIT。

**§37 Scheduler 模拟验收** `[废止]` 与 §36 是同一件事的第二份清单，已并入 §36。

**§38 Safety 与 Liveness 必须同时证明** `[A]`
安全不能靠"永久不做"实现。Risk Gate 限制的是**危险 Action**，不是 Goal 的存在权。

**§39 Runtime 安全边界** `[A]`
真实货币 = `PERMANENT_BLOCK`；未授权时钻石／高价值道具／高价值加速／不可逆高风险动作必须过 Risk Gate。
落点：`brain.py:958 real_money_action_permanently_blocked`、
`capability_bootstrap.py:934 SEED_REAL_MONEY` / `:981 NONE_ALLOWED`。
**与操作层 §8b 的关系见 `README.md` R2：真钱永久禁止，非真钱资源按 T0–T4 授权。**

**§40 Fishing 固定策略** `[A]`
Fishing Tournament 只允许 NORMAL BAIT；禁止 special bait / special mode / treasure mode / tickets / gems / real money。
Realtime Fishing：UI-Venus、OCR、Global Scheduler 均 0/frame。
落点 `goal_library.py:1686 only_allowed_spend` / `:1766 forbidden_spend`、
`knowledge/events/fishing_tournament_rules.json`。

**§41 生产与学习同时进行** `[废止]` 与 §8 同义。

**§42 每轮 WorkBuddy 自主开发流程** `[A]`
11 步：读真实状态 → 识别最高价值 Gap → 判类型 → Architecture Review → 选最大收益问题 →
最小实现 → Targeted Tests → Safe Repin/Reload → 真实 Production AUTO → Verifier/Goal Progress →
重新扫描整个项目。STEP 11 的"重选工作"以 §65 为准。

**§43 优先修共享根因** `[A]`
同一根因影响多个 Goal 时修根因（如 Scheduler 语义），不给每个 Goal 单独放行。
（原 §66 已并入本节。）

**§44 Direction Error / Global Re-Audit Trigger** `[A]`
满足任一立即停止局部优化、重做全局价值审计：
A 连续 5 个有功能意义的提交 `PRODUCTION_TRIED_GOALS` 没涨；
B 连续 3 个真实 Production 验证周期 `NEVER_TRIED_GOALS` 没降；
C 连续 3 个周期没有新增 `GOAL_PROGRESS_VERIFIED` / `PRODUCTION_VERIFIED`；
D 测试涨但覆盖率/完成率无改善；E 同一根因出现在 3 个不同 Goal；F 同一核心子系统连续两次修改后产生新死锁/饥饿/永久阻塞/假 GLOBAL_WAIT。
（原《不许停》四已并入本节。）

**§45 什么叫 Production 验证周期** `[A]`
真实 AUTO 运行 + 真实 Goal Board + 真实 Episode/Verifier 证据。**单测不能替代。**

**§46 Manual Intervention 长期指标** `[B]`
`MANUAL_INTERVENTIONS_PER_24H` 目标长期下降，不用单次提交的短期变化作硬判断。
**判定缺失**（全仓 0 命中），报告里写"未测量"，不许填 0。

**§47 UI-Venus Learning Funnel** `[A]`
**权威层清单在代码**：`ui_venus_contract.py:623-640` 共 **16 层**
（含 `candidate_replay_pass` / `candidate_shadow_pass`）。
原文列 15 层、漏了 replay 与 shadow，与 §53（要求 Replay/Shadow）自相矛盾——**以代码为准**。
每层必须能带 `trace_id/parent_trace_id/role_id/goal_id/frame_id/episode_id`，回答"模型主要失败在哪一层"。

**§48 同一 UNKNOWN 不能无限烧模型** `[A]`
同一 Screen 默认最多约 2 次 Venus 尝试，超过后 Recovery → Cooldown → Next Goal。

**§49 Context 规则** `[A]`
UI-Venus 上限 32768，是上限不是目标。P0 保 fresh screenshot/Goal/Role/Page/SessionContext/
current elements/latest Verifier；超预算先裁 P2。
落点 `winter_agent_v2/context_budget.py`、`ui_venus_contract.py:61`。

**§50 当前帧一致性** `[A]`
`screenshot.frame_id == elements.frame_id`，不一致 → `CONTEXT_FRAME_MISMATCH` → 丢弃重拍重建。

**§51 Venus 输出安全** `[A]`
优先 `target_element_id`；无可靠 Element 时允许 semantic_target + `candidate_bbox_norm`，
但 bbox 只是 `UNTRUSTED_CURRENT_FRAME_PROPOSAL`，**禁止直接点 model bbox**。

**§52 COMPLETE 不能由模型决定** `[A]`
Venus `decision=COMPLETE` 只能记为 `MODEL_COMPLETE_CLAIM`；真正 Complete 由 Goal Verifier 决定。

**§53 Skill Repair** `[A]`
Known Skill 失败：deterministic retry → Semantic Retry → fresh observe → bounded recovery；
仍失败才 SKILL_REPAIR。Repair Candidate **不得**覆盖 Stable Skill，
必须 Candidate → Grounding/Replay → Live Verifier → Shadow → Promotion Gate。

**§54 Offline Learning** `[A]`
不得直接操作设备。只能从真实 Episode/Frame/Action/Verifier 提炼
`CANDIDATE_PAGE` / `CANDIDATE_UI_SEMANTIC` / `FAILURE_PATTERN_CANDIDATE` / `CANDIDATE_STEP` /
`CANDIDATE_SKILL` / `SKILL_REPAIR_CANDIDATE` / `NAVIGATION_EDGE_CANDIDATE`，
且结论必须带 `evidence_refs`。模型分析不得直接成为 Confirmed Truth。

**§55 Coverage 审计必须回答"为什么没做"** `[A]`
每个启用 Goal 给出唯一主因。禁止用"不在 candidate 里"作为最终解释。
**实况**：14 个原因值里 `DISCOVERY_READY` / `LEARNING_READY` / `RECOVERY_READY` 零实现，其余 11 个在用。

**§56 当前重点覆盖对象** `[废止]`
手写 18 项清单，与 Goal Library 重复且已失真（实际 20 个 Goal，命名体系完全不同）。
**以 Goal Library 与 `docs/CAPABILITY_COVERAGE.md` 为准**，不再手维护。

**§57 可以自主决定补什么** `[A]`
Goal 缺 route／entry／reader／Skill／Verifier／Recovery／Learning bridge／Scheduler binding 都可自主补齐；
优先接现有系统，不另建框架。

**§58 不要沉迷 95%→97%** `[A]` 优先 0→1；除非该 95% 缺陷属 P0/P1 且大量影响生产。

**§59 真实验收至少覆盖不同 Gap** `[A]`
Observation / Navigation / Capability / Skill Repair / Never-Tried，各争取真实 AUTO 证据。

**§60 Tests 不是终点** `[A]`
严格区分 CODE_EXISTS … PRODUCTION_VERIFIED 共 13 个状态；测试全绿**只允许进入下一阶段**。

**§61 AUTO 活性优先** `[A]`
`AUTO_ALIVE` / `WORKER_ALIVE` / `SCHEDULER_ALIVE` 为 P0。
一个 Goal 失败 → DEFER/COOLDOWN → Next Goal；UI-Venus 不可用 → Unknown defer、Known 继续。

**§62 GPU / Model 资源原则** `[B]`
机器参数与全部实测数字（`-ngl 30` / f16 KV / 213–265 MiB free / 上下文代价）已写入
`config/v2.json:117` 的注释与 `tools/profile_device_impact.py`。
本节只保留原则：**先测量后调整，禁止为了数字漂亮而破坏稳定 Production。**

**§63 MuMu GPU 分配** `[废止]`
条件分支从未触发——`780M` / `Radeon` 全仓只出现在规则文档里，从未测量过。

**§64 Git 纪律** `[A]`
可以自主修改/测试/Commit/Push/Repin/Reload；**禁止**
`git reset --hard`、`git clean -fd`、`git checkout .`、`git restore .`、blind `stash pop`、`git add .`。
必须显式 add、小提交、保护 runtime mutable data。

**§65 每完成一项后必须重新选择工作** `[B]`
本节是"重选工作"的**唯一**出处（§42-STEP11 尾、《不许停》二与八已并入）。
完成后不问"原列表下一项是什么"，而问：现在只能修一个问题时，哪个最可能最大化
`GAME_TASK_COMPLETION_RATE` / `AUTO_COVERAGE` / `UNKNOWN→KNOWN` / `NEVER_TRIED↓` / `MANUAL_INTERVENTION↓` / `AUTO 稳定性`。
**判据只能用 README §7 里"真实存在"的那几个量。**

**§66 不允许固定开发路线** `[B]` 降为 §43 的子条款。

**§67 每轮内部 Design Review** `[A]`
INTENT / CURRENT_BEHAVIOR / ROOT_CAUSE / PROPOSED_CHANGE / ARCHITECTURE_CONFLICTS /
LIVENESS_RISK / SAFETY_RISK / STARVATION_RISK / REGRESSION_RISK / CHOSEN_IMPLEMENTATION。
不需要长篇报告，但必须完成这个判断。

**§68 每轮 Invariant Review** `[A]`
13 项名：ONE_SCHEDULER / ONE_EXECUTOR / ONE_WORLD_STATE / KNOWN_FAST_PATH_MODEL_CALLS /
UNKNOWN_LEARNING_REACHABLE / NO_PERMANENT_UNKNOWN_BLACKHOLE / NO_HIGH_VALUE_UNKNOWN_STARVATION /
NO_SINGLE_GOAL_BLOCKS_AUTO / NO_SINGLE_ROLE_BLOCKS_OTHER_ROLE / FAILED_GOAL_EVENTUALLY_RETRYABLE /
GLOBAL_WAIT_ONLY_WHEN_TRULY_IDLE / MODEL_FAILURE_DOES_NOT_STOP_AUTO /
VERIFIER_REMAINS_SUCCESS_AUTHORITY / SAFETY_AND_LIVENESS_BOTH_HOLD。
**实况**：`tools/invariant_review.py:311-325` 是 14 项不同名，2 项返回 `UNMEASURED`
（`ONE_EXECUTOR`、`KNOWN_FAST_PATH_MODEL_CALLS`），
`ONE_WORLD_STATE` / `NO_HIGH_VALUE_UNKNOWN_STARVATION`（代码叫 `HIGH_VALUE_UNKNOWN_NOT_STARVED`）/
`SAFETY_AND_LIVENESS_BOTH_HOLD` 三个名字不存在。**对照时按语义，不按名字。**

**§69 用户明确策略不能自行更改** `[A]`
真钱策略 / 资源消费政策 / 不可逆账号行为 / Fishing ONLY NORMAL BAIT / 其他用户固定策略。
这些之外（开发、调试、修复、接线、低风险真机验证、Skill 修复、Verifier 补齐、Scheduler 修复、Learning 修复）**自主进行**。

**§70 最终报告** `[A]` 字段清单见逐字原文。
其中 `MANUAL_INTERVENTIONS_PER_24H` **无度量，必须写"未测量"**。

**§71 最终行为定义** `[废止]`
逐句复述 §61/§16/§34/§30/§6/§13/§24。末句愿景并入 §72。

**§72 最后一条永久原则** `[A]`
先问"这样实现以后，整个 V2 是否更接近最终目标"，局部正确但全局错误时选全局正确。
不得为让某条局部规则更容易实现，降低 V2 对最终目标的可达性。
任何保护机制都必须同时证明 SAFETY 与 LIVENESS。
终极目标不是"系统永不犯错"，而是"长期自主运行、在安全边界内不断尝试学习、越来越少人工干预"。

---

## 二、《持续开发，不许停》八节

**一 "不停"的定义** `[A]`
禁止 6 种停：完成后等派工／遇到不确定就停下问（除真钱·策略·不可逆风险）／测试全绿就当结束／
连续多轮做同一件低价值事／因"怕改坏"而不动／因"没有明确指令"而空转。
允许的暂停只有三种：真钱/策略/不可逆风险 → 问操作者；系统物理不可用 → 恢复它；
所有角色所有 Goal 真的无事可做 → 这本身就是 Bug，去查。

**二 每轮循环必须完整走完** `[废止]` 与 §42 逐字同一串 11 步；
"不许在 Evaluate / Choose Next 停下"并入 §65。

**三 每轮必须落一个"真实变化"** `[A]`
定义：至少一个 Goal 的 Capability 状态推进一级／或至少一个 KPI 有可观测变化／或至少一个 Tier 0/1 阻塞被消除。
只重构、只补测试、只加日志、只改文档 —— **这一轮不算数**。

**四 连续多轮无真实变化 = 触发自我审计** `[废止]`
与 §44 B/C 重复且阈值口径不同；已并入 §44。

**五 进程异常时不许自己躺下** `[A]`
检测到进程异常／状态机卡死／心跳超时，不允许"等用户来修"：
先修自己 → 修不了自我重启 → 重启不了报告并继续尝试。
（原引用"第 46 节 Tier 0"已失效；Tier 概念在 `OPERATIONAL.md §8b`。）

**六 控制台必须实时反映** `[A]`
每轮结束后必须更新：当前最高价值缺口 / 本轮做了什么 / 上一轮做了什么 / 下一个候选工作 / 阻塞原因（真实原因，不是"待规划"）。
**实况**：只有"阻塞原因"实现了（`tools/control_panel.py:2039`），其余 4 项零命中。
**在该规则落实前，不得声称"控制台反映了本轮"，也不得把它当作轮次完成的证据。**

**七 禁止的"伪持续"** `[A]`
ping 但无真实变化／反复改同一文件却无生产验证／循环重跑同一批测试／
把 TODO 重排序当工作／把生成报告当工作／把控制台美化当工作。
**真正的工作 = 改变真实 AUTO 行为。**

**八 自我驱动问题** `[废止]` 与 §65 是同一个问题、同一串 KPI；已并入 §65。

---

## 三、已废止清单（12 条，保留节号以切断歧义，不再生效）

| 节号 | 名称 | 废止理由 | 现在去哪看 |
|---|---|---|---|
| §9 | 当前阶段 CAPABILITY_EXPANSION | 阶段标记无日期无退出条件 | §58 |
| §11 | Learning Budget 不是机械时间切片 | 纯解释 | §10 |
| §13 | 高价值 UNKNOWN 是一等公民 | 只剩口号 | §14 + §31 |
| §28 | 13 状态 Coverage Matrix | 8/13 零实现 | §29 + 代码 6 值枚举 |
| §37 | Scheduler 模拟验收 | 与 §36 重复 | §36 |
| §41 | 生产与学习同时进行 | 与 §8 同义 | §8 |
| §56 | 当前重点覆盖对象 | 手写清单已失真 | Goal Library + `docs/CAPABILITY_COVERAGE.md` |
| §63 | MuMu GPU 分配 | 条件从未触发、从未测量 | §62 的"先测量" |
| §71 | 最终行为定义 | 逐句复述其他节 | 末句并入 §72 |
| 不许停 二 | 每轮循环完整走完 | 与 §42 逐字重复 | §42 + §65 |
| 不许停 四 | 连续无变化=自我审计 | 与 §44 重复且口径不同 | §44 |
| 不许停 八 | 自我驱动问题 | 与 §65 重复 | §65 |

**废止 ≠ 删除原文**：逐字原文完整保留在 `FINAL_FULL.md` / `PERSISTENT_DEVELOPMENT.md`。
若某条被废止的规则日后重新需要，从原文取回并在此表中移除。

## 四、合并清单（6 处）

| 原处 | 并入 |
|---|---|
| §41 | §8 |
| §66 | §43 |
| §42-STEP11 尾 / 不许停 二 尾 / 不许停 八 | §65 |
| 不许停 四 | §44 |
| §11 | §10 |
| §13 | §14（§31 保持独立，是动作） |
