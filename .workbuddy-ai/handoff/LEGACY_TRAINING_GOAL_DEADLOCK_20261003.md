# 训练链 492 次 0 进展：完整因果链（2026-10-03 第十八轮）

> 第十七轮把问题收敛到"两处页判断不一致"。本轮读了那两处，
> **代码是对的** —— 而这恰恰证明了问题的性质。

---

## 一句话

`KEEP_TRAINING_PRODUCTIVE` 只能��**训练页**上被发现，而训练页上被选的 7 个目标里**没有它**。
**它永远到不了那个页面 ⇒ 永远发现不了自己。** 一次完整的自我封闭。

---

## 一、两处页判断都是对的

`brain.py`（训练路线）：

```python
if world.page is Page.MAP:
    if world.resource_search_open: return Decision("BACK", ...)
    return Decision("OPEN_HOME", "training_goal_requires_home", ...)     # 在 MAP 上要回 HOME
if world.page is not Page.TRAINING:
    return Decision("SAFE_STOP", "training_entry_not_verified", ...)     # 不在训练页则停
```

**注意第二段的含义：在 `Page.TRAINING` 上，这一路会落到下面去（不是 SAFE_STOP）。**
而 `goal_library:2340` 在训练页上给它的是 `available_skills=("TRAIN_TROOPS",)`。
⇒ **两处对"我在哪一页"的判断完全一致，没有矛盾。** 第十七轮那个猜测是错的。

**实测印证**：`training_entry_not_verified` / `SAFE_STOP` 在全量账本里 **0 次**。
它从没走到那个分支。

---

## 二、真正的封闭在哪里

`goal_library.py:2339` 决定它**能否被发现**：

```python
if legacy_camp is None and world.training and world.training.get("status"):
```

而 `world.training.status` **只在训练页被完整读取**（HOME 上只有导航字段）。

⇒ **它只能被发现在训练页上。**

而训练页上被选的目标（86 步全量）：

```
AVOID_STAMINA_WASTE       40
MARKSMAN_CAMP_TRAINING     13
LANCER_CAMP_TRAINING       12
SHIELD_CAMP_TRAINING       12
KEEP_BUILDING_PRODUCTIVE    8
DAILY_ACTIVITY_TARGET       2
CLEAR_INTEL                 1
```

**`KEEP_TRAINING_PRODUCTIVE` 一次都没有**（它在训练页上的步数 = **0**）。

**闭环：**

```
它只在训练页可被发现
训练页上它从没被选中
⇒ 没人执行 OPEN_HOME 去训练页（那是它唯一会发的动作）
⇒ 训练页到不了
⇒ world.training.status 读不到
⇒ （回到第一行）
```

---

## 三、训练页是能到的 —— 别人带去的

`KEEP_BUILDING_PRODUCTIVE` 在训练页上 8 步，往前看一步：

```
LANCER_CAMP_TRAINING   OPEN_INFANTRY_TRAINING  -> page TRAINING
MARKSMAN_CAMP_TRAINING TAP_FOCUSED_TRAINING_CAMP_MARKSMAN -> page HOME
LANCER_CAMP_TRAINING   TAP_FOCUSED_TRAINING_CAMP_LANCER -> page HOME
```

**per-camp 目标把页面带到了训练页。** 训练页完全可达 ——
**只是它自己永远到不了。**

⚠ 而 `KEEP_BUILDING_PRODUCTIVE` 在训练页上的 8 步**全部是
`TRY_ORDINARY_CONTROL` / `FAILURE` / `goal_TRAIN_has_only_BACK_left_on_this_page`**
⇒ 它站在训练页上**无事可做**（`brain` 在该页不给它 `TRAIN_TROOPS`，
而 `goal_library` 只在 `legacy_camp is None` 时才给它 `TRAIN_TROOPS`）。

---

## 四、这条路的性质：已退役 + 被死锁

| 证据 | 出处 |
|---|---|
| per-camp 已取代它，"survives only as the label for a legacy" | `goal_library.py:50` |
| 它只是"per-camp 没有对应兵营时"的回退 | `goal_library.py:2336-2338` |
| 它的发现条件要求"per-camp 归不了属" | `goal_library.py:2339` `legacy_camp is None` |
| 而 per-camp 目标健康（240 次 / 25 次真进展） | 本会话第十七轮实测 |
| 它 492 次被选、`gp_true` 恒为 0 | 同上 |

⇒ **它的存在条件（`legacy_camp is None`）在今天的客户端上几乎从不为真**，
因为 per-camp 目标能覆盖三个兵营。而一旦它被产出，它又只能产在训练页上
—— 那里的 `brain` 不给它动作。**产出条件与可用条件互斥。**

⚠ 它同时是 `--goal KEEP_TRAINING_PRODUCTIVE` 的兼容标签
（`goal_library.py:72-75` 记着 argparse 曾因此报错），
**所以"退休"不等于"删除"**。

---

## 五、本轮的结论：这里不该有一个"修复"

我花了三轮追这个 492 次。**结论是它不该被修**：

- 它是被取代的遗留路径（代码注释自己写着）；
- 修活它 = 给一条退役的路重新接线，而它**无法损失任何真进展**（492 次 `gp_true=0`）；
- 而**真正的训练能力（per-camp）本来就在产出**（240 次 / 25 次真进展）。

**这 492 次占全量生产时间约 1%**（492/10128 步），
它们不是"训练没做"，是**一条死路在消耗调度**。

⇒ 该做的**不是**让这条路活过来，而是**让它安静**（不再被排上 board、
或被排在现行目标之后），并把注意力放回真正有价值的地方。
⚠ 但这一步涉及 `--goal` 兼容路径，**不是纯代码问题**，需要确认那条命令行用法是否仍在用。

---

## 六、下一轮该做什么（换方向）

本会话已连续三轮停在这条路上，且结论是"它不该被修"。
按持久开发指令第 64 条，**该换一个能真正提升 KPI 的题目**：

回到那张全局有效率表里**还没碰过、且真进展率低的**目标上：

```
CLEAR_INTEL            n=1343  t=   2   0.1%   ← 真·大头
AUTO_DISCOVERY         n= 121  t=   0   0%
KEEP_RESEARCH_PRODUCTIVE n=  46  t=   0   0%
PET_TREASURE           n=  44  t=   0   0%
EVENT_MINIMUM_GUARANTEE n=  42  t=   0   0%
HERO_RECRUIT_ADVANCED  n=  38  t=   0   0%
```

其中 `CLEAR_INTEL` 是全项目被选第二多、几乎零进展的目标，
且它与 `KEEP_TRAINING_PRODUCTIVE` 共享那 374 次 `OPEN_HOME` 的**另一侧**
（第十六轮量到 `CLEAR_INTEL` 从 HOME 出发 `OPEN_MAP` 332 次）。

**下一轮第一件事：量 `CLEAR_INTEL` 那 1343 次的页分布与技能分布，
看它是不是第二个"存在条件与可用条件互斥"的目标。**

---

## 七、本轮状态

- **零代码改动。** 生产 pin `291ede58`，AUTO 正常运行。
- 分支 `workbuddy/page-residency-20261003` = `266e20a3`。
- 本文件**推翻了第十七轮"两处页判断不一致"的猜测**（代码一致），
  并给出了完整的自我封闭链条。
