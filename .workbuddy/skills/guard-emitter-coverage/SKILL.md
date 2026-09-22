---
name: guard-emitter-coverage
description: "Find every place Winter Agent OS V2 can issue a given skill before adding or trusting a guard on it: grep the whole package for the skill id, because the brain is not the only decision maker (the runtime issues its own hops), prove coverage per emitter with one test each, and prefer a named refusal over a silently skipped action. Use when a guard 'didn't work' or a failure repeats after a fix that looked complete."
description_zh: "守卫覆盖审计：同一动作的所有发出点都要护到（大脑 ≠ 唯一决策者）"
description_en: "Audit guard coverage across every emitter of a skill, not just the brain"
agent_created: true
---

# 守卫覆盖审计（同一动作的所有发出点）

## 为什么有这条技能

本项目 2026-09-23 的实测：`OPEN_HOME` 的"先关资源搜索面板"守卫**加了七处**，
`brain.py` 里 `OPEN_HOME` 的每一处发出点都补上了。**40 分钟后同类失败又成串出现 8 次**——
因为发出这个动作的地方有**八处**，第八处在运行时（`LiveRuntime._deferral_replan`），
它不在 `brain.decide` 里，所以七处大脑守卫**一处都管不到它**。

那次代价是可量的：**七次"一步长"的运行**（决定回城 → 失败 → 结束 → 面板 30 秒后重启到同一张地图）
= **六分钟死循环**，直到一次无关的平移才把面板关掉。

同一形状的坑还有第二个面：守卫**静默拒绝**（`return None`）时，执行器会把"解析器没给落点"
一律写成 `SEMANTIC_TARGET_NOT_VERIFIED`（"帧上没有这个控件"），于是四种不同根因共用一句话，
统计、分类（`escalation_queue` 的 `UNKNOWN_UI`）和后续修复方向全部被带偏（见项目 issue #103）。

## 一、找全发出点（**不是只找大脑**）

```bash
# 1) 这个动作的所有发出者（Decision(...)、Decision 构造、skill id 字面量）
grep -rn '"<SKILL_ID>"' winter_agent_v2/*.py
# 2) 运行时自己的决策（本项目里是兜底跳转/恢复，不在 brain 里）
grep -n 'return Decision(' winter_agent_v2/runtime.py
# 3) 也看 tools/ 与面板：定时循环、验收工具都可能在补一只手
grep -rn '"<SKILL_ID>"' tools/
```

判据：**每一处 `Decision(<SKILL_ID>, ...)` 都要能在清单里被点名**，包括那些"看起来不可能走到"的
（本项目的第八处就是只在 `best_goal is None` 时才走，而"所有 goal 都被 defer"恰恰是常见状态）。

## 二、每一处都要有**它自己**的守卫 + 一条测试

- 守卫的**条件**取自该处能看到的同一份世界状态（本项目：`world.resource_search_open`），
  而不是靠上游替它判断。
- 守卫要**复用既有的技能与验证器**（本项目：`BACK` + `verify_safe_back` 的 `search_closed` 半），
  不要为守卫新造一个动作。
- 测试**直接测那一处**（函数级）比跑一整轮更可靠：整轮的结果常常取决于机器上的公平台账、
  观测缓存等（本项目已有整类测试因此变成"moving set"）。规则本身与"哪个 goal 赢了"无关。
- **边界也要钉**：没有前置条件时不动、有别的活可干时不动、不在那个页面上时不动。

## 三、失败的"理由"必须由知道原因的那一层给出

- 守卫拒绝时**按名字记**（本项目：`ORDINARY_CONTROL_DECLINES` 一族 + `_failure_type_from()`），
  并把名字写进 episode。**默认的通用字符串会让统计说谎**：本项目 32 次失败里 21 次的理由都是假的。
- 顺带检查三个下游：候选/元素收集器会不会把这个拒绝当成"读不到"入库；
  升级队列会不会按后缀把它分类成 `UNKNOWN_UI`；面板会不会显示成"客户端读不懂"。
- **决策理由要落进语料**（本项目已加 `Episode.decision_reason`）：只写 stdout 的理由会随日志滚动消失，
  下一次同类问题就只能靠排除法定性（本轮正是如此）。

## 四、什么时候算完

- 名单上的每一处都有守卫、有测试；
- 把守卫整个撤掉，测试会失败（**逐处**验证，不是整体绿）；
- 真机/生产证据：修复前后同一状态的失败次数（本项目：八连败 → 该状态不再产生失败步）；
- 理由的真实性可核（不是所有根因共用一句话）。

## 反面清单

- ✗ 只改 `brain.py` 就宣布"守卫加好了"。
- ✗ 用"这一处不可能走到"代替 grep。
- ✗ 守卫静默 `return None`，让执行器替它解释原因。
- ✗ 只测"整轮能跑通"，于是规则挂在哪个 goal 上、是否真的触发都测不到。
- ✗ 把"守卫没生效"当成模板/坐标问题——先问"这一处有没有守卫"。
