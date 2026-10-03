# 训练链的死锁：它只在训练页上被自我发现（2026-10-03 第十七轮）

> 第十六轮把因果链收敛到"页错了"。本轮读完了那条链，
> **找到了闭环的起点，而且它是项目自己写下的一行代码。**
> 本轮零代码改动 —— 因为这一处的修法有真实的取舍，必须先说清代价。

---

## 一句话

`KEEP_TRAINING_PRODUCTIVE` **只在 `world.training.status` 存在时才会出现在 board 上**，
而 `world.training.status` **只在训练页被完整读取**。
**训练页要靠它在 HOME 上被选中才能到 —— 于是它永远到不了。**

---

## 一、代码位置与原文

`goal_library.py:2336-2341`：

```python
# The legacy single reading, when it named a camp the per-camp model has nothing for,
# is still worth keeping: it is a real reading of a real page, just one the camp model
# could not attribute.  Reported under the page's own name so it is visible.
if legacy_camp is None and world.training and world.training.get("status"):
    self._append_queue_goal(goals, "KEEP_TRAINING_PRODUCTIVE", world.training,
                            ("TRAIN_TROOPS",), TRAINING_CAMP_VALUE)
```

**`world.training.get("status")` 是这个目标存在的唯一条件。**

而 `goal_library.py:50` 已经说明它是被什么取代的：

> "per-camp goals; `KEEP_TRAINING_PRODUCTIVE` survives only as the label for a legacy"

---

## 二、实测：`status` 只在训练页上有

HOME 帧的 `training` 字段形状（2833 个 HOME 帧里 176 个带 `training`）：

```
77  camp_focus_source, camp_focus_tap_norm, navigation
34  camp, camp_label, menu_open, source, train_tap_norm
28  camp_focus_current_frame, camp_focus_reference_frame, camp_focus_retry_attempt, …
19  building, camp, camp_label, menu_open, queue_available, source, status, train_tap_norm
 9  camp_focus_source, camp_focus_tap_norm, camp_tap_norm, navigation, queue_available
 9  camp_tap_norm, navigation, queue_available
```

⇒ **HOME 上的 `training` 主要是导航信息**（`camp_focus_*` / `train_tap_norm`），
**只有 19 帧带 `status`**，而且那还是"面板已打开"的状态。

对照训练页（TRAINING 页 86 步）：`troop_type` / `status` / `queue_available` / `timer`
**每帧都有**。

---

## 三、于是出现这个数

```
训练链在 HOME 上出现在决策 = 0 次      （决策日志）
训练链在 HOME 上被选      = 4 次 / 2833 帧（0.14%）（账本）
而 MARKSMAN_CAMP_TRAINING 在 HOME 上被选 = 77 次
```

**具体的兵营目标在 HOME 上有发现（77 次），通用的 `KEEP_TRAINING_PRODUCTIVE` 没有（0 次）。**

⚠ 这个对比还纠正了我自己：`MARKSMAN_CAMP_TRAINING` 等
`MARKSMAN/LANCER/SHIELD_CAMP_TRAINING` 是**项目当前实际使用的训练目标**
（`CAMP_GOAL_FOR`），它们走 `_append_camp_training_goals`（2334 行以上），
**不依赖 `status`**。而我追了两轮的那个通用目标是**遗留回退路径**。

---

## 四、闭合的因果链

```
HOME 帧：world.training 没有 status
  ⇒ goal_library:2340 的 if 不成立
  ⇒ KEEP_TRAINING_PRODUCTIVE 不出现在 board 上
  ⇒ 它无法在 HOME 上被选中
  ⇒ 没人执行 OPEN_HOME 去训练页
  ⇒ 训练页永远到不了
  ⇒ world.training.status 永远读不到
  ⇒ （回到第一行）
```

**这是一个真正的自我封闭，不是排序问题。**

## 四、真正的死锁在哪：per-camp 目标是有产出的

本轮末尾量了那个"必答问题"，**答案推翻了本文件的前半段**：

```
MARKSMAN_CAMP_TRAINING  n=90  gp_true=10   HOME 77 / TRAINING 13
LANCER_CAMP_TRAINING     n=75  gp_true=7    HOME 63 / TRAINING 12
SHIELD_CAMP_TRAINING     n=75  gp_true=8    HOME 63 / TRAINING 12
```

**三个 per-camp 目标合计 240 次被选、25 次真进展，而且大多在 HOME 上（203/240）。**
它们的技能分布也是完整的：`TAP_FOCUSED_TRAINING_CAMP_*`、
`OPEN_TASK_FROM_QUICK_PANEL_*`、`OPEN_COMPLETED_TRAINING_CAMP_*`、`TRAIN_TROOPS`。

⇒ **训练能力是活的、在 HOME 上就能推进。**
⇒ **死锁的不是训练，是那个遗留的通用目标 `KEEP_TRAINING_PRODUCTIVE`。**

### 于是全局图景变成

| 目标 | 被选 | gp_true | 性质 |
|---|---|---|---|
| `MARKSMAN/LANCER/SHIELD_CAMP_TRAINING` | 240 | **25** | **当前设计，活的** |
| `KEEP_TRAINING_PRODUCTIVE` | 492 | **0** | **遗留回退路径，卡在发现条件上** |

**我追了两轮的那个 492 次的"大头"，恰恰是应该退休的那条路。**

---

## 五、这个发现如何改变修法取舍

上一节列的 A/B/C 三个改法，**现在有一个明显更好的选项**：

| 改法 | 现在的判断 |
|---|---|
| A. 让 HOME 上的 `training` 产出 `status` | ❌ 仍是编造观测 |
| B. 去掉 `status` 条件让通用目标在 HOME 可见 | ❌ **更糟** —— 那是在给一条**应该退休的路**加燃料 |
| C. 改走 per-camp 目标 | ✅ 方向本来就是它，且它已经在产出 |

### 但先量了一件事，它排除了"选择层压了现行目标"这个可能

```
KEEP_TRAINING_PRODUCTIVE 被选 206 次
  同场有 per-camp 目标 = 0        ← 一次都没有
  同场没有 per-camp     = 206
```

**两者从不在同一块 board 上出现。** 所以不是"遗留目标把现行目标挤掉了"，
而是**它们各自在不同的框里被发现在**。

这与第一节的代码完全吻合：
- 通用目标要求 `world.training.get("status")` ⇒ **只在训练页**被产出；
- per-camp 目标走 `_append_camp_training_goals` ⇒ **在 HOME 上**被产出（快速面板行）。

**它们是两条互不相交的发现路径，各自都被选中 200+ 次，各自 0 与 25 的真进展。**
通用那条在训练页上被选中时，per-camp 那三个根本不在候选里。

⇒ **"退休通用目标"不会影响 per-camp**（它们不同框），
也**不会损失任何真进展**（通用目标 492 次 `gp_true` 恒为 0）。
这让"让它退休"从一个有风险的决定变成一个**几乎无代价**的决定 ——
**但仍需先确认它作为 `--goal` 兼容标签的用途**，那是 `goal_library:72-75` 记着的历史约束。

---

## 六、下一轮的第一件事（已缩到一个问题）

**训练链（通用那条）在训练页上被选中时，它到底想做什么？**
它 76% 发 `OPEN_HOME` —— 但它此刻**已经在能读到 `status` 的那一页上了**。
按 `goal_library:2340` 它给的是 `available_skills=("TRAIN_TROOPS",)`，
而 `brain.py` 的 `training_goal_requires_home` 却在**训练页**上要它回 HOME。

⇒ **这两处对"训练页"的理解不一致**，这才是它在训练页上也只发 `OPEN_HOME` 的原因。
⇒ 要读 `brain.py` 里 `training_goal_requires_home` 那个分支的页判断，
以及它与 `goal_library:2340` 给出 `TRAIN_TROOPS` 时用的页判断是否同一个。

**这是本会话至今最接近"492 次 0 进展"根因的一步。**

---

## 七、本轮状态

- **零代码改动。** 生产 pin `291ede58`，AUTO 正常运行。
- 分支 `workbuddy/page-residency-20261003` = `bffa60f0`。
- 本文件修正了第十六轮与本文件前半段：
  **训练能力本身是有产出的（per-camp 240 次 / 25 次真进展）**，
  卡住的是**被 per-camp 取代后遗留的通用目标**。
- **下一轮第一件事**：量"训练链被选中的 492 次里，per-camp 目标当时在不在 board 上"。
