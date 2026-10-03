# 训练链 0 进展的真正机制：它赢得回合，但回合当场被转交（2026-10-03 第十六轮）

> 第十五轮说"训练链 492 次被选、0 进展，能力是好的、路径不通"。
> 本轮读了调度侧控制流，**并纠正了第十五轮对闭环的描述**。

---

## 一、先纠正：闭环不存在

第十五轮写"`CLEAR_INTEL` 从 HOME 出发 `OPEN_MAP` 332 次，
每次被 `KEEP_TRAINING_PRODUCTIVE` 用 `OPEN_HOME` 挤回"。

**实测不成立。** 两者同场的 701 次决策里：

```
CLEAR_INTEL 赢 = 26
KEEP_TRAINING 赢 = 94
```

而且 `CLEAR_INTEL.total - KEEP_TRAINING.total` 的差**多数为正**
（典型样本 `CLEAR_INTEL` base 500/total 466.7 对训练链 180/120）。

⇒ **训练链不是在"抢"，它是真的赢了。** 上一轮把"它常被选中"
读成了"它抢走了别人的回合"，与数据相反。

---

## 二、真正的机制：它在 MAP 上唯一能发的动作就是 `OPEN_HOME`

训练链那 493 步**自己**做了什么：

```
374  OPEN_HOME               SUCCESS gp=False   ← 76%
 67  BACK                    SUCCESS gp=False
 23  DISMISS_SHARED_REWARD   SUCCESS gp=False
 14  TRY_ORDINARY_CONTROL    FAILURE gp=False
  3  OPEN_INFANTRY_TRAINING  FAILURE gp=False
```

**374 次 `OPEN_HOME` = 76%。** 而它被选时的页：

```
MAP 144 / EVENT 14 / POPUP 11 / PET_TREASURE 8 / HOME 8 / BUILDING 5
```

**它在 MAP 上被选 144 次，而它在 MAP 上唯一能发的就是 `OPEN_HOME`** ——
一句"我现在不在 HOME，请导航过去"。

**所以闭环的真正形状是：**

```
MAP 页：训练链赢 → 只能发 OPEN_HOME → 回到 HOME
HOME 页：训练链又赢 → 这时它能发 OPEN_QUICK_PANEL / OPEN_INFANTRY_TRAINING
        但那一步的 goal_id 常常是 DISCOVER_QUICK_PANEL_TASKS（另一个目标）
        ⇒ 训练链的"在 HOME 上训练"从未发生
```

⚠ **纠正本文件上一版**："回合当场被转交"这个说法**不准确**。
`OPEN_QUICK_PANEL` 那些步的 `goal_id` 确实是 `DISCOVER_QUICK_PANEL_TASKS`，
但它们是**训练链那一步之后的独立一步**，不是"训练链的回合被接管"。
真正的因果是**页错了**（该在 HOME，它在 MAP）。

---

## 三、为什么"在 HOME 上"也不训练

训练链在 HOME 上被选只有 **8 次**（492 步里的 1.6%）。
而它赢时 204 次的技能分布：

```
151  ('TRY_ORDINARY_CONTROL',)   ← 74%
 53  ('OPEN_INFANTRY_TRAINING',)
```

⚠ 这里也纠正一次：`available_skills` 里有 `OPEN_INFANTRY_TRAINING` 的那 53 次，
**并不是**它执行了它 —— 账本里 `OPEN_INFANTRY_TRAINING` 只跑了 **3 次且 3 次都失败**。
技能"被提供"与"被发出"是两件事。

`page_residency` 在它 204 次获胜里：

```
None 182    0.0  22
```

**我的驻留项从未生效过**（182 次连字段都没有）——
因为 `KEEP_TRAINING_PRODUCTIVE` 在 `_residency_table()` 里是 `NOT RESIDENT`，
它压根没有"习惯页"（76% 的步骤是导航，从不在任何页上训练）。

⇒ **与第十三轮的判断一致**：它从来不在任何页上做自己的事，排序层对它无话可说。

---

## 四、三层机制叠在一起

```
第 1 层  它在 MAP 上被选 144 次，而那里它唯一能发的是 OPEN_HOME（374/493 = 76%）
         ⇒ 它把回合全部用来"请求去 HOME"
第 2 层  它在 HOME 上只被选 8 次（1.6%）⇒ "在 HOME 上训练"几乎从未发生
第 3 层  即便执行了第二步，5/27 的 TRAIN_TROOPS 还会被误读成失败
         —— 那个 81% 健康的技能
```

**三层各自的规模（本轮全部实测）：**

| 层 | 规模 | 性质 |
|---|---|---|
| 1 | 374/493 发 `OPEN_HOME`；MAP 上被选 144 次 | **页错了**：该在 HOME，它在 MAP |
| 2 | HOME 上只被选 **8/492 = 1.6%** | 同上 |
| 3 | 27 次里 5 次误读 | 最小的一块（第十五轮已量） |

**第十五轮需要修正**：它说"训练链几乎不被调度"——
准确说法是**它被调度得很勤（492 次），但 76% 的动作是"请求去 HOME"，
而它真正该在的那一页上只出现过 1.6%**。

⇒ **第一、二层其实是同一件事：页错了。**
真正的问题是一个**页面归属**问题，不是调度频率问题、也不是时序问题。

---

## 五、这一轮不写代码的理由

第 1、2 层已合并为"训练链该在 HOME 上，但 98.4% 的时间不在"。

但**它的路由规则我没读**：`brain.py:2243` 附近有
`Decision("OPEN_HOME", "training_goal_requires_home", ...)`，
而 `goal_library.py:111` 把 `KEEP_TRAINING_PRODUCTIVE` 路由到 `"HOME"`。
**两者一致** —— 说明路由是对的，页错发生在**执行途中**
（`CLEAR_INTEL` 去 MAP 把它带走了，或角色切换）。

要判断是"被别人带走"还是"自己算错页"，必须读
`_sync_brain_goal` 如何把 chosen 传进 brain、以及 `Page` 变化后 goal 是否重算。

**没读就改 = 第十五轮之前那三次误诊。** 下一轮第一件事就是这个。

---

## 六、本轮状态

- **零代码改动。** 生产 pin `291ede58`，AUTO 正常运行。
- 分支 `workbuddy/page-residency-20261003` = `e1f94a15`。
- 本文件纠正了第十五轮"TRAINING_VERIFY_TOO_EARLY_20261003.md" 里的闭环描述。
