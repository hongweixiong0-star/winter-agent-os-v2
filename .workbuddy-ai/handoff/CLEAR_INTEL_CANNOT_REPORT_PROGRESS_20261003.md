# `CLEAR_INTEL`：动作全成功、进展记不上（2026-10-03 第六轮）

> 500 次被选、67 次成功打开情报卡、**2 次真进展**。本文给出根因与两条修法，
> 并说明为什么本轮**没有改代码**。

---

## 一句话

`CLEAR_INTEL` 的 `distance` 是**常量 1.0**，`_observation_meter` 对它返回 `None`
⇒ `progress_moved` 永远判不出进展 ⇒ 每次都记 `False` ⇒
还累加 `no_progress_streak` 把它降权。**它在结构上无法报告进展。**

这与 `_observation_meter` docstring 里已实测记录的 `SCHEDULED_*` 是**同一个病**。

---

## 一、证据

### 1. 动作侧全部健康

近 24h，在 INTEL 页上（102 步）：

```
SELECT_INTEL_PIN            n=67   ok=67   gp=0     ← 全成功，一个都不记进展
INTEL_CLAIM_REWARDS         n=26   ok=26   gp=1
BACK                        n=7    ok=7    gp=0
SELECT_INTEL_BEAST_MISSION  n=1    ok=1    gp=0
```

`verify_intel_pin_opened` 判据是**严格且正确**的：点之前 `page is INTEL` 且 `pins > 0`，
点之后 `page is POPUP` 且 `popup in INTEL_MISSION_POPUPS` ⇒ 67/67 通过说明点击真的有效。

### 2. 记账侧是空的

`SELECT_INTEL_PIN` 之后的下一步：

```
47  OPEN_INTEL_HERO_JOURNEY_TARGET   SUCCESS gp=False
46  OPEN_INTEL_BEAST_TARGET         SUCCESS gp=False
39  BACK                            SUCCESS gp=False
14  OPEN_INTEL_RESCUE_SURVORS_TARGET SUCCESS gp=False
```

**整条链没有一步能记 `True`。** 情报被点了、卡被开了、任务被选了，
但"这条情报被处理掉"从未被记为进展。

### 3. 客户端其实给出了那个数

323 个真机 INTEL 帧里，`intel` 字段随工作变化：

```
10:22:11  untried_pins=8  detected_pins=8
10:22:23  untried_pins=8  detected_pins=8   status=AVAILABLE
10:23:01  untried_pins=7  detected_pins=8   ← 一条情报真的被处理掉了
```

**`untried_pins` 会降，`pins`/`detected_pins` 不会。** 前者就是天然的 meter。

---

## 二、根因定位到一行

`goal_library._observation_meter`：

```python
if not str(goal.goal_id).startswith("SCHEDULED_"):
    return None
```

`CLEAR_INTEL` 不匹配 ⇒ 返回 `None` ⇒ `progress_moved` 走"无 meter"分支 ⇒
拿 `distance`（常量 1.0）比 ⇒ `1.0 < 1.0` 恒为 False。

后果不止"少一次记账"：docstring 已写明 `False` 会 `no_progress_streak += 1`
（`runtime.py:9734`），streak 又喂给 fairness ⇒ **它因自己做不到的事被降权**。

### 为什么本轮没有直接改

我先按 `evidence["intel"]["untried_pins"]` 写了一版，**实测 meter 仍返回 `None`** ——
因为 `CLEAR_INTEL` 的 `evidence` 里只有
`age_minutes / has_actionable_daily_task_rows / incomplete_queue_observation / observed /
overdue / reading / reused`，**根本没有 `intel`**。

`untried_pins` 在 `state_before.intel`（`WorldState` 的感知层），
而 `_observation_meter` 读的是 `GoalState.evidence`（目标层）。
**两者之间缺一次搬运。** 留着一段返回 `None` 的代码不如撤掉，**已撤回**。

---

## 三、两条修法（都需要先定"谁搬运"，不能顺手写）

### A. 发现层把 `untried_pins` 带进 evidence

在构造 `CLEAR_INTEL` 的那处（`goal_library` 里产出 `observed`/`reading` 的分支）
把当帧的 `intel.untried_pins` 记进 `evidence`。**优点**：meter 立刻可用，
与 `SCHEDULED_*` 已有的做法同形。**代价**：必须确认该字段只在 INTEL 页读得到，
否则会拿陈旧值当进展 —— 而这正是 `SCHEDULED_*` 用 `availability_state` 谨慎分级的原因。

### B. 换一个已经在 evidence 里的量

`evidence["observed"]` / `incomplete_queue_observation` 已经在证据里。
若它们能区分"又清了一条"与"没动"，就可以直接当 meter，**不需要搬运**。
**但本轮没查清它们的语义**，不能假设。

⇒ **下一轮第一件事**：读 `CLEAR_INTEL` 的 evidence 那几个字段是怎么算出来的，
判断 B 能不能免掉搬运。不能就做 A，但 A 必须先在真机上量一帧
`evidence["intel"]` 是否真的只在 INTEL 页存在。

---

## 四、本轮顺带确认的另一件事（不是 wiring 能解决的）

"读到活动之后去做什么"**不是接线问题，是边界**：

- 执行侧能力**齐备**：`SCHEDULED_BEAR_HUNT` 的 `registered_skill_ids = ['JOIN_RALLY']`，
  而 `JOIN_RALLY` 在注册表里、runtime 绑到**已实现**的 `verify_rally_joined`
  （要求行军数增加 **或** 成员状态 ∈ {JOINED, MARCHING, ARRIVED}，不接受"点了一下"）。
- **但接不上**：`runtime._verify_rally_action` 要求 `target` 属于
  `RallyTarget{BEAR, POLAR_TERROR, FORTRESS, OTHER, UNKNOWN}`，
  而 `rally_target` 是从 **ALLIANCE 页上下文**取的（`runtime.py:8156` / `9277`）。
  活动票在 `Page.EVENT` 上没有这个上下文 ⇒ 挂上去会每次得到 `RALLY_TARGET_UNKNOWN`
  —— 和被否决的 `READ_TIMER` 一样的"可见但必失败"。

⚠ **另一半不能挂**：多数票的 `registered_skill_ids` 是
`[READ_TIMER, TRAIN_TROOPS, BUILDING_UPGRADE, RESEARCH, TRY_ORDINARY_CONTROL]`
—— **通用队列动作，不是活动参与**。挂上会让"读活动"变成"训练部队"，
与本次修复要解决的是同一个病，**高一层**。
