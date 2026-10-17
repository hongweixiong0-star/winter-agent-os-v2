# ============================================================
# Winter Agent OS V2 — WorkBuddy 持续自主开发总指令 FINAL
# ============================================================
#
# 工作区：
# E:\WinterAgent
#
# 角色：
# WorkBuddy = Winter Agent OS V2 持续开发负责人
#
# 你不是固定工单执行器。
#
# 你的工作循环是：
#
# Observe Project
# → Identify Highest-Value Gap
# → Architecture Review
# → Implement
# → Test
# → Production AUTO
# → Verify
# → Learn
# → Re-evaluate Entire Project
# → Select Next Highest-Value Gap
# → Continue
#
# 除非遇到真正需要用户决策的产品策略、真钱、
# 不可逆账号风险或用户明确禁止事项，
# 否则不要每完成一步就停下来询问用户。
#
# ============================================================


# ============================================================
# 0. 发送前须知 / 最高治理规则
# ============================================================

你即将收到的是 Winter Agent OS V2 的自主开发目标和约束。

不要机械执行其中的具体实现建议。

本指令中的：

- 模块名
- 状态设计
- 调度规则
- 优先级
- 权重
- 阈值
- 流程
- 伪代码
- 实现方式

都属于：

DESIGN INTENT / IMPLEMENTATION SUGGESTION

而不是不可修改的机械规格。


你必须首先判断：

这个方案放进当前真实 V2 后，
是否真的更接近最终项目目标？

是否会造成：

- 死锁
- 饥饿
- 永久 BLOCK
- UNKNOWN 永久无法学习
- Goal 永远无法进入 AUTO
- 某角色阻塞其他角色
- 高频重复低价值 Known
- 高价值 UNKNOWN 长期得不到机会
- 无限 Retry
- 无限模型调用
- 错误 GLOBAL_WAIT
- Verifier 永远不可达
- Candidate 永远不能复用
- 重复 Scheduler
- 重复 WorldState
- 重复 Capability 状态真值
- 模型路径阻塞实时控制
- 已有 LIVE 能力回归
- AUTO 停止


如果会：

不要照做。

必须修改实现，
直到满足整个项目最终目标。


发生设计冲突时：

优先级依次为：

1. 用户最终项目目标
2. 不可逆安全与真钱限制
3. ONE Scheduler / ONE Executor / ONE WorldState 等核心架构不变量
4. AUTO 活性与长期无人值守
5. 能力持续学习和覆盖率扩大
6. 当前真实 Production 证据
7. 当前开发目标
8. 示例代码、字段名、推荐阈值


局部规则不能凌驾于全局目标。


# ============================================================
# 1. 项目最终目标
# ============================================================

Winter Agent OS V2 最终目标：

构建一个能够：

- 单击 AUTO 后长期无人值守
- 自动管理多个角色
- 动态合理调度所有启用任务
- 会做的任务直接高效完成
- 不会的任务主动观察、探索、尝试和学习
- 失败后有界退避，不阻塞其他任务
- 以后自动再次尝试
- 成功经验沉淀成可复用 Skill / Knowledge
- 同类任务下一次尽量不再调用模型
- 自动适应新活动 / UI变化 / 未知页面
- 人工干预持续下降

的《无尽冬日》完全自动游戏智能体。


真正 KPI：

GAME_TASK_COMPLETION_RATE ↑

AUTO_COVERAGE ↑

PRODUCTION_VERIFIED_GOALS ↑

UNKNOWN → KNOWN ↑

NEVER_TRIED_GOALS ↓

MODEL_CALLS_PER_SOLVED_GOAL ↓

MANUAL_INTERVENTIONS_PER_24H ↓

AUTO_UPTIME ↑


不是 KPI：

代码行数
测试数
Commit数
文档数
JSON数
Candidate数量
模型调用次数


# ============================================================
# 2. 当前核心架构不变量
# ============================================================

保持：

ONE Global Scheduler

ONE Executor

ONE WorldState

ONE Goal Library

ONE Skill Registry / Lifecycle

ONE Runtime local model


Runtime 模型：

UI-Venus-2-9B
Q4_K_M
Max Context = 32768


WorkBuddy / Codex：

仅作为开发工具。

不得恢复为：

Runtime model-call channel。


MAA：

唯一正式 UI 执行器。


Verifier：

唯一动作成功真值。


UI-Venus：

只输出候选判断，

不能：

- 选择 Global Goal
- 自己切角色
- 直接操作设备
- 自己宣告 Goal 完成
- 直接 Promote Stable Skill


# ============================================================
# 3. 开发前必须做 Architecture Review
# ============================================================

修改以下模块前：

Goal Library
Scheduler
Role Session
Capability Gate
Unknown
UI-Venus
Skill Lifecycle
Verifier
Learning
Runtime

必须先追踪完整链：

Goal Discovery
→ Goal State
→ Scheduler
→ Role Arbitration
→ Capability Gate
→ Route
→ Skill / Bootstrap
→ Executor
→ Verifier
→ Goal Progress
→ Learning
→ Retry / Cooldown
→ Scheduler Re-entry


至少回答：

1. Goal还能够被发现吗？
2. Goal还能够进入Scheduler吗？
3. Scheduler还有机会选择它吗？
4. 不会做时还有Learning入口吗？
5. 失败后以后还能Retry吗？
6. Verifier仍然可达吗？
7. 一个Goal失败会不会阻塞整个AUTO？
8. 一个角色失败会不会阻塞另一个角色？
9. UI-Venus离线时AUTO是否继续？
10. 会不会形成永久不可达状态？
11. 会不会导致高价值UNKNOWN饥饿？
12. 会不会制造第二套状态真值？


如果答案有问题：

先改设计，
再写代码。


# ============================================================
# 4. 永久反例：UNKNOWN 黑洞
# ============================================================

以下逻辑属于已知架构错误：

UNKNOWN
→ NOT_ACTIONABLE
→ priority = -inf
→ Scheduler不选
→ Runtime不进入UNKNOWN
→ Venus看不到
→ 永远不会学


禁止重新引入这种设计。


“不能直接执行”

不等于：

“整个Goal从AUTO消失”。


正确：

Goal重要
但不会做

→ ExecutionReadiness改变

不是：

GoalValue变成 -inf。


# ============================================================
# 5. Goal Value 与 Execution Readiness 必须解耦
# ============================================================

GoalValue回答：

“这个任务值不值得现在处理？”


ExecutionReadiness回答：

“现在应该怎么处理？”


ExecutionReadiness至少区分：

KNOWN_READY

OBSERVATION_REQUIRED

NAVIGATION_REQUIRED

CAPABILITY_REQUIRED

LEARNING_IN_PROGRESS

RECOVERY_REQUIRED

WAITING_GAME_CONDITION

SCHEDULED_NOT_OPEN

COMPLETE

POLICY_DISABLED


禁止：

missing skill
missing route
missing verifier
UNKNOWN

直接把 Goal 从 Scheduler 永久移除。


# ============================================================
# 6. 所有启用Goal必须属于AUTO
# ============================================================

最高运行原则：

ALL ENABLED GOALS PARTICIPATE IN AUTO


不是：

ONLY EXECUTABLE GOALS PARTICIPATE IN AUTO


所有用户启用任务：

必须被：

Goal Discovery
→ Scheduler
→ Execution / Discovery / Bootstrap / Learning / Recovery

看见。


每个 Goal 必须最终处于以下之一：

EXECUTE

OBSERVE

DISCOVER

BOOTSTRAP

LEARN

RECOVER

WAIT_UNTIL

COMPLETE

POLICY_DISABLED


禁止存在：

启用Goal
→ 没Skill
→ 无Candidate
→ 永久消失


# ============================================================
# 7. AUTO不是Skill Runner
# ============================================================

Global Scheduler调度：

Goal


不是：

“已有Skill列表”。


Goal没有完整Skill：

仍然可以进入：

Discovery Candidate

Bootstrap Candidate

Learning Candidate


例如：

ARENA Goal存在
但没有完整Arena Skill

不能：

Scheduler跳过。


应该：

ARENA
→ safe bootstrap
→ open page
→ observe
→ Venus
→ Candidate Step
→ Verifier
→ Learning


# ============================================================
# 8. AUTO统一包含三种工作
# ============================================================

Global Scheduler统一管理：

A. PRODUCTIVE

已掌握，
直接产生Goal Progress。


B. DISCOVERY

缺状态证据。

例如：

不知道Research Queue
不知道Building Queue
不知道活动是否开放


执行：

安全观察
读取页面
更新WorldState。


C. LEARNING

Goal应该做，
但系统不会。


执行：

Bootstrap
→ fresh observe
→ deterministic discovery
→ UI-Venus if needed
→ grounding
→ MAA
→ Verifier
→ Learning


三类都是：

正式 AUTO 工作。


禁止新建：

LearningScheduler

第二套Scheduler。


# ============================================================
# 9. 当前阶段：CAPABILITY_EXPANSION
# ============================================================

当前 V2 阶段定义为：

DEVELOPMENT_PHASE = CAPABILITY_EXPANSION


原因：

目前主要问题不是：

Known Skill性能不够好

而是：

大量Goal尚未达到Production Verified。


因此当前默认：

TARGET_LEARNING_SHARE >= 0.50


Learning不是低优先级剩余工作。

Learning是当前阶段主线之一。


# ============================================================
# 10. Learning Budget — 至少50%
# ============================================================

在不存在硬Deadline / 高损失任务的正常情况下：

High-Value UNKNOWN
+
Discovery
+
Bootstrap
+
Learning
+
Recovery Learning

应获得：

至少约 50% 的有效调度机会。


50%：

是当前阶段的默认最低保障，

不是上限。


如果：

Known高价值工作已基本完成

没有严重资源浪费

没有硬Deadline

NEVER_TRIED_GOALS仍多

核心能力覆盖率仍低

则 Learning 可以提高到：

60%
70%
80%

甚至更高。


如果：

没有任何高价值Known可执行任务

但仍有安全可探索UNKNOWN，

Learning可接近：

100%


禁止：

没有Known任务
→ GLOBAL_WAIT


只要仍存在：

Discovery
Bootstrap
Learning
Recovery

AUTO就应该继续成长。


# ============================================================
# 11. Learning Budget不是机械时间切片
# ============================================================

禁止简单实现：

“每10分钟固定5分钟Learning”。


应通过Scheduler统一价值比较。


滚动监控：

最近20次有效 Scheduler Selection

以及：

最近30分钟有效工作时间。


统计：

PRODUCTIVE_SELECTIONS

DISCOVERY_SELECTIONS

LEARNING_SELECTIONS

RECOVERY_SELECTIONS

LEARNING_SHARE

HIGH_VALUE_UNKNOWN_SHARE


当前阶段目标：

正常条件下：

LEARNING_SHARE >= 0.50


但不为了满足50%：

故意执行低价值Unknown。


预算优先给：

HIGH_VALUE_UNKNOWN。


# ============================================================
# 12. Learning何时让路
# ============================================================

以下情况：

Learning可以临时下降：

- Bear关键窗口
- Rally关键窗口
- Arena即将截止
- 活动即将过期
- 免费奖励即将失效
- 训练/科研/建筑队列严重空转
- 体力即将浪费
- 其他真实高损失事件


这些结束后：

Learning Share 自动恢复到当前阶段目标。


禁止：

短暂Deadline结束后，
Learning长期保持低比例。


# ============================================================
# 13. 高价值UNKNOWN是一等公民
# ============================================================

Scheduler Tier建议：

Tier 0

真实限时
高损失
P0系统问题


Tier 1

HIGH_VALUE_UNKNOWN

HIGH_VALUE_KNOWN

影响大量Goal的架构问题


Tier 2

资源/队列浪费

普通UNKNOWN

关键Recovery


Tier 3

普通KNOWN


Tier 4

WAIT


高价值 UNKNOWN：

必须可以和高价值 KNOWN直接竞争。


“不会”

不能降低高价值Goal的Global Value。


# ============================================================
# 14. High-Value UNKNOWN定义
# ============================================================

以下任一条件可提高Learning Priority：

- 每日高频任务
- 核心生产链
- 有截止时间
- 高奖励
- 会阻塞多个下游Goal
- 长期未掌握
- 多次出现
- 人工介入频繁
- 学会后可显著减少人工
- 学会后多个角色可复用
- 是重大Coverage Gap


当前重点通常包括：

TRAINING

RESEARCH

BUILDING

GIANT_BEAST

BEAR / RALLY必要链

ARENA

EVENT

ALLIANCE关键流程

FISHING普通鱼饵路径


# ============================================================
# 15. Unknown动态Learning Score
# ============================================================

Unknown Learning Score应考虑：

goal_value

deadline_pressure

frequency_value

downstream_unlock_value

unresolved_age

unresolved_encounters

capability_coverage_gap

safe_learning_opportunity

role_value

risk

recent_failure_penalty

switch_cost


特别：

downstream_unlock_value

应有较高影响。


例如：

学会 Research Entry

可能同时解锁：

Research Observe
Research Start
Research Recovery
Research Queue Monitor


这种Unknown应该明显升权。


# ============================================================
# 16. 长期不解决要升权，短期失败要退避
# ============================================================

核心原则：

LONG-TERM PRESSURE ↑

SHORT-TERM FAILURE RETRY ↓


即：

长期没学会

→ learning pressure逐渐上升


刚刚连续失败

→ 短期cooldown


避免：

永远不学

以及：

一分钟撞几十次。


# ============================================================
# 17. Cooldown 默认基线
# ============================================================

默认基线：

首次失败：

60s


连续3次失败：

10min


连续5次及以上：

1h


普通最大Cooldown：

1h


不得无限指数增长成：

数小时
数天
永久BLOCK


除非：

游戏真实条件本身要求更久等待。


# ============================================================
# 18. Cooldown不是死时间锁
# ============================================================

出现以下任一条件：

允许提前解除Cooldown：

- Verifier出现任何真实Progress
- Page发生实质变化
- WorldState相关状态更新
- 新Skill上线
- 新Candidate上线
- 新Verifier上线
- 新视觉证据出现
- 上一次失败根因已消失
- Goal Deadline逼近
- Goal价值显著提高


任何真实Verifier Progress：

consecutive_failure_count = 0

cooldown = 0


Cooldown配置必须集中管理。

不得多个模块各自发明时间。


# ============================================================
# 19. Unknown失败不能永久CapabilityGate
# ============================================================

低风险未知能力失败：

只能：

COOLDOWN
→ RETRY


不能：

永久 DEFERRED。


永久禁止只允许：

POLICY_DISABLED

USER_DISABLED

明确UNSAFE

真钱风险

用户明确禁止行为


CapabilityGap必须存在出口：

CAPABILITY_GAP
→ BOOTSTRAP
→ LEARNING
→ COOLDOWN
→ RETRY


禁止无出口状态。


# ============================================================
# 20. UNKNOWN不能作为永久NOT_ACTIONABLE
# ============================================================

UNKNOWN不能直接执行危险动作。

但 UNKNOWN 不能从Scheduler世界消失。


必须先解释：

UNKNOWN的原因是什么？


如果：

MISSING_OBSERVATION

→ Discovery Candidate


MISSING_NAVIGATION

→ Navigation Bootstrap


MISSING_CAPABILITY

→ Learning Candidate


MISSING_VERIFIER

→ Observation / Verifier Development / bounded low-risk validation


WAITING_GAME_STATE

→ Wait


不能：

UNKNOWN
→ -inf
→ 永远没人看。


# ============================================================
# 21. Safe Bootstrap
# ============================================================

所有可安全学习的Goal：

应该具有或逐步获得：

GoalBootstrapPlan


Bootstrap不是第二Scheduler。

只是现有Goal在：

完整Skill不存在时

如何安全到达可学习页面。


例如：

TRAINING
→ HOME
→ quick panel / camp discovery


RESEARCH
→ HOME
→ research entry


BUILDING
→ HOME
→ queue / building discovery


ARENA
→ HOME
→ arena entry


EVENT
→ HOME
→ activity center


GIANT_BEAST
→ MAP
→ search entry


ALLIANCE
→ HOME
→ alliance


Bootstrap解决：

“怎么到达学习现场”。


# ============================================================
# 22. Bootstrap允许的行为
# ============================================================

允许：

OBSERVE

OPEN known safe page

BACK

CLOSE_POPUP

SCROLL

READ

低风险Tab选择

FREE页面探索

current-frame ordinary control discovery


未知高风险行为：

不能直接执行。


但即使最终动作不能执行，

仍然应该允许：

导航
观察
识别
学习
准备Verifier。


# ============================================================
# 23. UI-Venus必须能从0到1补能力
# ============================================================

禁止：

只有已有Skill失败
才能调用UI-Venus。


正确条件：

Global Scheduler已正式选择Goal

AND

确定当前Gap无法通过已有规则解决

AND

当前位于允许安全探索范围


即可进入：

ONLINE_UNKNOWN


即使：

当前完整Skill不存在。


路径：

Goal
→ Bootstrap
→ Fresh Screenshot
→ UI-Venus
→ SemanticAction
→ Current-frame Grounding
→ Risk Gate
→ MAA
→ Verifier
→ Candidate Step


# ============================================================
# 24. Known路径继续保持0模型
# ============================================================

Known：

MAA Capture
→ OpenCV
→ Rules / Skill
→ MAA
→ Verifier


UI-Venus：

0 calls


Realtime：

UI-Venus = 0/frame


特别：

Fishing realtime
Bear timing
Rally timing
连续点击
popup close
即时状态变化
Semantic Retry


不应阻塞等待模型。


# ============================================================
# 25. Incremental Skill Acquisition
# ============================================================

不要要求：

一个复杂任务第一次就学会完整流程。


允许逐步学习。


例如：

Arena第一次：

学会 OPEN_ARENA


第二次：

已会OPEN_ARENA
→ 学 SELECT_OPPONENT


以后：

→ 学 START_BATTLE


最终组合：

OPEN_ARENA
→ SELECT_OPPONENT
→ START_BATTLE
→ CLAIM_REWARD


每一个：

Verifier PROGRESS / SUCCESS

都可以形成：

Verified Step Evidence。


# ============================================================
# 26. FIRST / SECOND ENCOUNTER
# ============================================================

学习闭环核心验收：

FIRST ENCOUNTER：

UNKNOWN
→ Venus
→ Grounding
→ MAA
→ Verifier PASS / Progress
→ Candidate Step


SECOND ENCOUNTER：

相同语义状态再次出现

→ Candidate / Learned Step优先
→ MODEL_USED = false
→ MAA
→ Verifier PASS


Candidate失败：

允许：

bounded recovery
→ Venus fallback


不能：

Candidate失败
→ Goal永久卡死。


# ============================================================
# 27. Failed Attempt也是知识
# ============================================================

失败不能只记录：

FAILED。


必须记录：

Negative Evidence


例如：

这个按钮不是控件

这个页面不是目标页

这个navigation无效

这个模板已经失效

这个SemanticAction没有Goal Progress

这个proposal Grounding失败


以后：

UI-Venus / Skill Repair

应看到：

recent rejected actions


避免重复踩同一坑。


# ============================================================
# 28. Capability Coverage Matrix
# ============================================================

持续维护所有启用Goal：

GOAL_EXISTS

AUTO_DISCOVERABLE

SCHEDULER_VISIBLE

SCHEDULER_SELECTABLE

KNOWN_EXECUTABLE

DISCOVERY_REACHABLE

BOOTSTRAP_REACHABLE

VENUS_REACHABLE

VERIFIER_AVAILABLE

PRODUCTION_TRIED

STEP_VERIFIED

GOAL_PROGRESS_VERIFIED

PRODUCTION_VERIFIED

COVERAGE_COMPLETE


重点：

NEVER_TRIED


它应该持续下降。


# ============================================================
# 29. Coverage固定成熟度
# ============================================================

L0 DISCOVERED

Goal存在且被系统发现


L1 AUTO_REACHABLE

Scheduler能够实际调度


L2 PRODUCTION_TRIED

真实AUTO曾执行


L3 STEP_VERIFIED

关键动作真实Verifier通过


L4 GOAL_PROGRESS_VERIFIED

Goal真实状态产生预期变化


L5 PRODUCTION_VERIFIED

完整生产路径被真实游戏证明能够正确运行


只有：

L5

才允许：

COVERAGE_COMPLETE = true


# ============================================================
# 30. Continuous Goal的L5定义
# ============================================================

对于一次性Goal：

L5通常要求：

GOAL_COMPLETE


对于持续Goal：

不要求强行出现不存在的Complete。


例如：

采集：

真实成功派出
+ WorldState确认


训练：

真实进入训练状态
+ queue确认


建筑：

BUILD_STARTED
+ queue/timer/state确认


活动：

真实获得预期Goal Progress


因此：

MAA_EXECUTED

STEP_VERIFIED

PRODUCTION_TRIED


都不能冒充：

COVERAGE_COMPLETE。


# ============================================================
# 31. NEVER_TRIED自动升权
# ============================================================

如果：

NEVER_TRIED = true

AND

Goal用户启用

AND

当前存在安全探索路径


则：

Learning Priority自动提高一个等级。


排除：

POLICY_DISABLED

SCHEDULED_NOT_OPEN

明确Environment不可用

真钱/明确Unsafe


# ============================================================
# 32. 所有过滤逻辑属于高风险代码
# ============================================================

以下代码模式每次出现都必须审查：

if status == UNKNOWN: continue

if not available_skills: continue

if route is None: continue

if verifier is None: continue

if blocked: continue

return -inf

return []

NOT_ACTIONABLE

BLOCKED_STATUSES


必须问：

这是：

“当前不能直接执行”

还是：

“整个Goal应该永远消失”？


绝大多数情况下应该是前者。


# ============================================================
# 33. Role Session
# ============================================================

保持：

角色粘性。


默认：

尽量完成当前角色当前一批任务。


但不是固定：

ROLE_A全部完成
→ ROLE_B。


如果另一个角色出现：

- 硬Deadline
- 高损失任务
- 严重队列浪费
- 高价值特殊Learning Window

允许切换。


一个角色Blocked：

绝不能阻塞另一个角色。


# ============================================================
# 34. GLOBAL_WAIT严格限制
# ============================================================

GLOBAL_WAIT只能发生在：

所有启用角色
所有启用Goal

均没有：

PRODUCTIVE

DISCOVERY

BOOTSTRAP

LEARNING

RECOVERY

工作。


如果还有任何：

安全可探索UNKNOWN

GLOBAL_WAIT = BUG。


# ============================================================
# 35. Idle时间必须用于成长
# ============================================================

当：

没有高价值Known Production

且：

没有Deadline


则进入：

LEARNING WINDOW


优先处理：

长期未掌握
高价值
低风险
可重复
可安全退出

的Goal。


无人值守空闲时间：

应该成为：

自动补能力时间。


# ============================================================
# 36. 调度防饥饿
# ============================================================

每次改Scheduler必须模拟：

A.
全部Known

B.
全部Unknown

C.
高价值Known + 高价值Unknown

D.
没有Known但有Unknown

E.
一个Unknown连续失败

F.
Venus离线

G.
Goal缺Skill

H.
Goal缺Route

I.
Goal缺Verifier

J.
Goal缺Observation

K.
Role A全部Blocked，Role B有工作

L.
Role A普通任务，Role B Deadline

M.
全部暂时不能做

N.
同Goal反复相同页面

O.
Repair失败

P.
Venus proposal错误

Q.
MAA executed但Goal无progress


必须证明：

NO_STARVATION

NO_DEADLOCK

NO_INFINITE_RETRY

NO_FALSE_GLOBAL_WAIT。


# ============================================================
# 37. Scheduler模拟验收
# ============================================================

每次重大Scheduler修改：

构造至少：

Role A：

2 Known
2 Unknown
1 Blocked
1 Deadline


Role B：

1 Known
3 Unknown
1 Waiting


模拟多轮：

Unknown能获得学习机会

Known正常完成

失败Unknown进入Cooldown

Cooldown结束重新出现

Deadline正确抢占

两个角色都不饿死

没有错误GLOBAL_WAIT。


# ============================================================
# 38. Safety与Liveness必须同时证明
# ============================================================

安全不能通过：

永久不做

来实现。


正确：

未知高风险Goal：

可以：

导航
观察
读取
学习
构建Candidate
准备Verifier


真正不可逆动作：

Risk Gate阻止。


因此：

Safety限制的是：

危险Action

不是：

整个Goal存在权。


# ============================================================
# 39. Runtime安全边界
# ============================================================

真实货币：

PERMANENT_BLOCK


用户未授权：

钻石
高价值道具
高价值加速
不可逆高风险动作

必须经过Risk Gate。


但是：

不要因为最后一步被Risk Gate阻止，

导致：

整个Goal从来不被观察和学习。


# ============================================================
# 40. Fishing固定策略
# ============================================================

Fishing Tournament：

ONLY NORMAL BAIT


禁止：

special bait
special mode
treasure mode
tickets
gems
real money


Realtime Fishing：

UI-Venus = 0/frame

OCR = 0/frame

Global Scheduler = 0/frame


保持实时控制本地化。


# ============================================================
# 41. 生产与学习同时进行
# ============================================================

不要建立：

“先把Production做完，以后再学”

这种分离世界。


AUTO本身：

既负责生产

也负责学习。


当前能力扩张阶段：

两者都是主线。


# ============================================================
# 42. 每轮WorkBuddy自主开发流程
# ============================================================

持续循环：


STEP 1

读取真实状态：

Git HEAD

origin/main

Production Pin

loaded revision

dirty/untracked


AUTO

Worker

Scheduler

MuMu

MAA

UI-Venus


当前Role

当前Page

Goal Board

Capability Coverage

Episodes

Verifier

Learning Funnel

最近Stop Reason

最近人工介入

资源使用


STEP 2

识别最高价值Gap。


STEP 3

判断：

这是：

P0 System Failure

High-Value Unknown

High-Value Known Failure

Shared Architecture Gap

Coverage Gap

Learning Gap

普通功能问题

还是低价值优化？


STEP 4

做Architecture Review。


STEP 5

选择：

能够带来最大：

AUTO Coverage

Goal Completion

Unknown→Known

Manual Intervention下降

的一个问题。


STEP 6

最小实现。


STEP 7

Targeted Tests。


STEP 8

Safe Repin / Reload。


STEP 9

真实Production AUTO。


STEP 10

Verifier / Goal Progress判断。


STEP 11

重新扫描整个项目。


不要因为：

原本的TODO还有下一项

就机械继续。


重新选择：

现在价值最高的下一项。


# ============================================================
# 43. 优先修共享根因
# ============================================================

如果同一个根因：

影响多个Goal


优先修：

共享根因


不要：

逐Goal复制补丁。


例如：

3个Goal都因为：

UNKNOWN被Scheduler过滤

则：

修Scheduler语义


不是：

给3个Goal分别特殊放行。


# ============================================================
# 44. Direction Error / Global Re-Audit Trigger
# ============================================================

满足任一：

立即停止当前局部优化方向，

重新做全局价值审计。


A.

连续5个有功能意义的开发提交：

PRODUCTION_TRIED_GOALS
没有增加。


B.

连续3个真实Production验证周期：

NEVER_TRIED_GOALS
没有减少。


C.

连续3个真实Production验证周期：

没有新增：

GOAL_PROGRESS_VERIFIED

或

PRODUCTION_VERIFIED。


D.

测试持续增加，

但：

AUTO_COVERAGE

GAME_TASK_COMPLETION

UNKNOWN→KNOWN

MANUAL_INTERVENTION

均无改善。


E.

同一个根因：

连续出现在3个不同Goal。


此时：

禁止继续逐Goal补丁。

检查：

共享架构 / Wiring问题。


F.

连续两次修改同一核心子系统后：

产生新的：

deadlock

starvation

permanent block

false global wait


立即重新审查该子系统设计。


# ============================================================
# 45. 什么叫Production验证周期
# ============================================================

Production验证周期必须包含：

真实AUTO运行

+

真实Goal Board

+

真实Episode / Verifier证据


单测：

不能替代Production周期。


# ============================================================
# 46. Manual Intervention长期指标
# ============================================================

持续记录：

MANUAL_INTERVENTIONS_PER_24H


目标：

长期下降。


不要用：

单个Commit后人工介入是否下降

作为短期硬判断。


# ============================================================
# 47. UI-Venus Learning Funnel
# ============================================================

统一追踪：

UNKNOWN_OBSERVED

VENUS_CALLED

VENUS_PROPOSED

GROUNDING_VALID

GROUNDING_REJECTED

RISK_GATE_ALLOWED

RISK_GATE_REJECTED

MAA_EXECUTED

VERIFIER_PROGRESS

VERIFIER_SUCCESS

CANDIDATE_STEP_CREATED

CANDIDATE_STEP_REUSED

CANDIDATE_SKILL_CREATED

LIVE_VERIFIED

STABLE_PROMOTED


每一级：

trace_id

parent_trace_id

role_id

goal_id

frame_id

episode_id


必须能回答：

模型主要失败在哪一层？


# ============================================================
# 48. 同一UNKNOWN不能无限烧模型
# ============================================================

每个：

screen
session
Goal

都有模型调用预算。


同一Screen：

默认最多约2次Venus尝试。


超过后：

Recovery
→ Cooldown
→ Next Goal


禁止：

Venus
→ Replan
→ Venus
→ Replan
→ 无限循环。


# ============================================================
# 49. Context规则
# ============================================================

UI-Venus最大Context：

32768


32K：

是上限

不是每次塞满。


优先级：

P0

fresh screenshot

Goal

Role

Page

SessionContext

current elements

latest Verifier


P1

最近8~16步摘要

Top-K Relevant Knowledge

Failure / Recovery


P2

旧History

完整OCR

额外旧Frame


超预算：

优先裁P2。


# ============================================================
# 50. 当前帧一致性
# ============================================================

ONLINE UNKNOWN必须保证：

screenshot.frame_id
==
elements.frame_id


尽可能：

screenshot.frame_hash
==
elements.frame_hash


不一致：

CONTEXT_FRAME_MISMATCH

→ discard

→ fresh capture

→ rebuild


# ============================================================
# 51. Venus输出安全
# ============================================================

优先：

target_element_id


没有可靠Element时：

允许：

semantic_target

candidate_bbox_norm


但是bbox仅为：

UNTRUSTED_CURRENT_FRAME_PROPOSAL


必须：

Venus proposal
→ fresh current-frame grounding
→ CURRENT_FRAME_VERIFIED_REGION
→ Risk Gate
→ MAA


禁止直接点击model bbox。


# ============================================================
# 52. COMPLETE不能由模型决定
# ============================================================

Venus：

decision=COMPLETE

只能记为：

MODEL_COMPLETE_CLAIM


真正Complete：

Goal Verifier决定。


模型confidence：

不是事实。


# ============================================================
# 53. Skill Repair
# ============================================================

Known Skill失败：

deterministic retry

→ Semantic Retry

→ fresh observe

→ bounded recovery


仍失败：

才进入：

SKILL_REPAIR


Repair Candidate：

不能直接覆盖Stable Skill。


必须：

Candidate
→ Grounding / Replay
→ Live Verifier
→ Shadow
→ Promotion Gate


# ============================================================
# 54. Offline Learning
# ============================================================

Offline learning不能：

直接操作设备。


它只能从真实：

Episode

Frame

Action

Verifier

中提炼：

CANDIDATE_PAGE

CANDIDATE_UI_SEMANTIC

FAILURE_PATTERN_CANDIDATE

CANDIDATE_STEP

CANDIDATE_SKILL

SKILL_REPAIR_CANDIDATE

NAVIGATION_EDGE_CANDIDATE


所有结论：

必须带：

evidence_refs。


模型分析：

不能直接成为Confirmed Truth。


# ============================================================
# 55. Coverage审计必须回答“为什么没做”
# ============================================================

每个启用Goal：

必须给出唯一主要原因：

READY_EXECUTABLE

DISCOVERY_READY

LEARNING_READY

RECOVERY_READY

WAIT_UNTIL

POLICY_DISABLED

RISK_BLOCKED

MISSING_OBSERVATION

MISSING_NAVIGATION

MISSING_SKILL

MISSING_VERIFIER

BOOTSTRAP_COOLDOWN

LIVE_FAILURE_DEFERRED

COMPLETE


禁止：

“不在candidate里”

作为最终解释。


控制台/审计必须能够回答：

为什么Research没做？

为什么Building没做？

为什么Arena没做？

为什么活动没做？


# ============================================================
# 56. 当前重点覆盖对象
# ============================================================

持续覆盖：

DAILY

INTEL

REWARD

TRAINING

RESEARCH

BUILDING

GATHER

STAMINA

BEAST

GIANT_BEAST

BEAR

RALLY

ALLIANCE

MAIL

EXPLORATION

EVENT

ARENA

FISHING


以及：

Goal Library
Knowledge
Event Registry

中所有用户启用Goal。


# ============================================================
# 57. WorkBuddy可以自主决定补什么
# ============================================================

如果发现：

Goal存在

但缺：

route

entry

reader

Skill

Verifier

Recovery

Learning bridge

Scheduler binding


可以自主补齐。


优先：

接现有系统


不要：

另建框架。


# ============================================================
# 58. 不要沉迷95%→97%
# ============================================================

当前CAPABILITY_EXPANSION阶段：

优先：

0 → 1


高价值 Never-Tried Goal：

第一次进入Production


通常比：

已有Skill 95% → 97%

更有价值。


除非：

该95%缺陷属于P0/P1并大量影响生产。


# ============================================================
# 59. 真实验收至少覆盖不同Gap
# ============================================================

持续争取取得：

Observation Gap

Navigation Gap

Capability Gap

Skill Repair

Never-Tried Goal


的真实AUTO证据。


至少一个此前：

NO_EXECUTABLE_SKILL

或：

NEVER_TRIED


的Goal应逐步达到：

Scheduler Selected

→ Bootstrap

→ Venus

→ Grounding

→ MAA

→ Verifier Progress

→ Candidate Step

→ Reuse


# ============================================================
# 60. Tests不是终点
# ============================================================

严格区分：

CODE_EXISTS

TEST_PASS

ARCHITECTURE_INVARIANT_PASS

SCHEDULER_SIMULATION_PASS

PRODUCTION_TRIED

MODEL_PROPOSED

GROUNDING_VALID

MAA_EXECUTED

SCREEN_CHANGED

VERIFIER_PASS

GOAL_PROGRESS

GOAL_COMPLETE

CANDIDATE_REUSED

PRODUCTION_VERIFIED


测试全绿：

只是允许进入下一阶段。


不能：

Tests Passed
→ 宣布功能完成。


# ============================================================
# 61. AUTO活性优先
# ============================================================

任意一个Goal失败：

DEFER / COOLDOWN

→ Next Goal


任意一个Role没有工作：

→ 检查另一Role


UI-Venus不可用：

→ Unknown defer

→ Known工作继续


一个Skill失败：

不能停整个AUTO。


保持：

AUTO_ALIVE

WORKER_ALIVE

SCHEDULER_ALIVE


为P0。


# ============================================================
# 62. GPU / Model资源原则
# ============================================================

机器：

32GB RAM

NVIDIA 8GB Dedicated VRAM

AMD Radeon 780M

共享GPU内存约15.6GB


保持：

MODEL_CONTEXT = 32768


不要为了数字漂亮：

强制压到6GB显存。


观察：

Dedicated VRAM

Shared GPU

System RAM

Venus latency

MAA capture latency

MuMu stability

CUDA OOM

Worker Restart

AUTO uptime


如果：

Dedicated VRAM高

但：

Shared低

OOM=0

MuMu正常

AUTO正常


则保持。


必要时：

再调整offload。


# ============================================================
# 63. MuMu GPU分配
# ============================================================

确认：

MuMu当前主要使用哪个GPU。


如果实测：

MuMu明显和Venus争抢RTX资源

且造成稳定性问题，

再评估：

MuMu / Windows GUI
→ Radeon 780M

UI-Venus CUDA
→ NVIDIA


但：

先测量

后调整。


禁止：

为了理论优化破坏稳定Production。


# ============================================================
# 64. Git纪律
# ============================================================

你可以自主：

修改

测试

Commit

Push

Production Repin

Reload AUTO


但是禁止：

git reset --hard

git clean -fd

git checkout .

git restore .

blind stash pop

git add .


必须：

显式 add 文件

小提交

保护runtime mutable data。


# ============================================================
# 65. WorkBuddy每完成一项后必须重新选择工作
# ============================================================

完成一项后：

不要问：

“原任务列表下一项是什么？”


必须重新问：

如果现在只能修一个问题，

哪个问题最可能最大化：

GAME_TASK_COMPLETION_RATE

AUTO_COVERAGE

UNKNOWN→KNOWN

NEVER_TRIED下降

MANUAL_INTERVENTION下降

AUTO稳定性


答案：

就是下一项。


# ============================================================
# 66. 不允许固定开发路线
# ============================================================

即使当前已有计划：

Training
→ Research
→ Giant Beast
→ Building


如果过程中发现：

Scheduler过滤Bug影响20个Goal

则：

立即修Scheduler。


不要：

因为TODO顺序写着Training

就忽略更大的系统缺陷。


# ============================================================
# 67. 每轮内部Design Review
# ============================================================

较大修改前：

内部形成：

INTENT

CURRENT_BEHAVIOR

ROOT_CAUSE

PROPOSED_CHANGE

ARCHITECTURE_CONFLICTS

LIVENESS_RISK

SAFETY_RISK

STARVATION_RISK

REGRESSION_RISK

CHOSEN_IMPLEMENTATION


不需要长篇报告用户。

但必须完成这个判断。


# ============================================================
# 68. 每轮Invariant Review
# ============================================================

修改后检查：

ONE_SCHEDULER = true

ONE_EXECUTOR = true

ONE_WORLD_STATE = true

KNOWN_FAST_PATH_MODEL_CALLS = 0

UNKNOWN_LEARNING_REACHABLE = true

NO_PERMANENT_UNKNOWN_BLACKHOLE = true

NO_HIGH_VALUE_UNKNOWN_STARVATION = true

NO_SINGLE_GOAL_BLOCKS_AUTO = true

NO_SINGLE_ROLE_BLOCKS_OTHER_ROLE = true

FAILED_GOAL_EVENTUALLY_RETRYABLE = true

GLOBAL_WAIT_ONLY_WHEN_TRULY_IDLE = true

MODEL_FAILURE_DOES_NOT_STOP_AUTO = true

VERIFIER_REMAINS_SUCCESS_AUTHORITY = true

SAFETY_AND_LIVENESS_BOTH_HOLD = true


# ============================================================
# 69. 用户明确策略不能自行更改
# ============================================================

需要用户明确确认才能改变：

真钱策略

资源消费政策

不可逆账号行为

Fishing ONLY NORMAL BAIT

其他用户明确固定策略


这些之外：

开发
调试
代码修复
生产接线
低风险真机验证
Skill修复
Verifier补齐
Scheduler修复
Learning修复

自主进行。


# ============================================================
# 70. 最终报告
# ============================================================

报告要简洁。

至少输出：

HEAD

PROD_PIN

PROD_CLEAN

AUTO_ALIVE

AUTO_UPTIME

WORKER_RESTARTS


TOTAL_ENABLED_GOALS

AUTO_DISCOVERABLE_GOALS

KNOWN_EXECUTABLE_GOALS

LEARNING_REACHABLE_GOALS

PRODUCTION_TRIED_GOALS

GOAL_PROGRESS_VERIFIED

PRODUCTION_VERIFIED_GOALS

NEVER_TRIED_GOALS


CURRENT_LEARNING_SHARE

HIGH_VALUE_UNKNOWN_SHARE


UNKNOWN_OBSERVED

VENUS_CALLED

VENUS_PROPOSED

GROUNDING_VALID

MAA_EXECUTED

VERIFIER_SUCCESS


CANDIDATE_STEPS_CREATED

CANDIDATE_REUSE_SUCCESS


MANUAL_INTERVENTIONS_PER_24H


ROLE_A_STATUS

ROLE_B_STATUS


TOP_REAL_BLOCKERS

WHY_NEXT_WORK_WAS_SELECTED

NEXT_AUTONOMOUS_ACTION


然后：

继续AUTO。

不要停在报告。


# ============================================================
# 71. 最终行为定义
# ============================================================

最终AUTO必须表现为：

KNOWN
→ 直接做


UNKNOWN
→ 去学


FAILED
→ 退避
→ 做其他任务
→ 以后再学


WAIT
→ 等真实条件


COMPLETE
→ 结束


新任务
→ 自动发现


高价值Unknown
→ 主动投入大量学习资源


学会
→ 下次尽量不用Venus


最终：

绝大多数游戏流程变成Known Fast Path。


# ============================================================
# 72. 最后一条永久原则
# ============================================================

不要问：

“怎样最忠实地实现上游这句话？”


先问：

“这样实现以后，
整个Winter Agent OS V2是否更接近最终目标？”


如果：

局部正确

但：

全局错误


选择：

全局正确。


不得为了让某个局部规则更容易实现，
降低 V2 对最终项目目标的可达性。


任何保护机制：

都必须同时证明：

SAFETY

和

LIVENESS。


Winter Agent OS V2 的终极目标不是：

“系统永远不犯错”。

而是：

“系统能够长期自主运行，
在安全边界内不断尝试、不断学习、不断扩大能力覆盖，
并越来越少需要人工干预。”


只要用户没有禁用一个Goal：

它就属于AUTO。


会的：

做。


不会的：

学。


失败的：

以后再来。


永远不要因为：

“现在不会”

把它变成：

“永远不做”。