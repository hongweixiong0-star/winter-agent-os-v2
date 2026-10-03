# 全局审计：日历链让位，最大缺口是训练链（2026-10-03 第十二轮）

> 日历子系统已耗五轮。按持久开发指令第 51 条 F（同一子系统连续修改后循环仍在 ⇒ 重新审计）
> 与第 64 条（每轮自问"现在只能修一个问题，哪个最能让 KPI 上升"），
> 本轮做全局审计并换目标。**本轮零代码改动。**

> ## 本节结论已被推翻（2026-10-03 第十三轮）
>
> **"启动了错误的兵种"是错的。** 实测那一帧：`troop_type=INFANTRY`、
> `camp_open_label=盾兵营`、目标 `SHIELD_CAMP_TRAINING` — 而 `INFANTRY` **就是**盾兵
> （`LABEL_TO_TROOP["盾兵营"]="INFANTRY"`、`TROOP_TO_CAMP["INFANTRY"]="SHIELD_CAMP"`）。
> 全 TRAINING 页 86 帧交叉验证：`troop_type` 与 `camp_open_label` **不一致 0 帧**。
> 我当时没查 `TROOP_TO_CAMP` 就下了结论。
>
> **真正根因是验证早了一瞬**：训练**确实启动**（下一步 `IN_PROGRESS` + 计时器，
> 5 次失败里 3 次如此），但 `verify_training_started` 在"点完立刻读"时
> 读到 `status=AVAILABLE`、无计时器 ⇒ 记 `TRAINING_START_NOT_PROVEN`。
>
> **正确结论见 `TRAINING_VERIFY_TOO_EARLY_20261003.md`。**
---

## 一句话

全局 10128 步里，**`CLEAR_INTEL` 被选 1343 次而 `goal_progress=True` 只有 2 次（0.1%）**；
`KEEP_TRAINING_PRODUCTIVE` 被选 492 次、**真进展 0 次**，
其中 **376 次（76%）只是 `training_goal_requires_home` → `OPEN_HOME`**。
**训练链从来没有在 HOME 上训练过。** 这比日历活锁值钱得多。

---

## 一、全局有效率（全量 10128 步）

```
DISCOVER_EVENT_CALENDAR   n=3589  t=1619  45%
AVOID_STAMINA_WASTE       n=1569  t= 494  31%
CLEAR_INTEL               n=1343  t=   2   0%   <== 被选第二多，几乎零进展
DISCOVER_QUICK_PANEL_TASKS n=1097 t=  40   4%
KEEP_TRAINING_PRODUCTIVE  n= 492  t=   0   0%   <== 76% 只是请求导航到 HOME
KEEP_BUILDING_PRODUCTIVE  n= 349  t=   0   0%   <== 118 次 home_opened / 95 次 task_page_open
CLAIM_EXPLORATION_IDLE    n= 222  t=  51  23%
AUTO_DISCOVERY            n= 121  t=   0   0%
KEEP_RESEARCH_PRODUCTIVE  n=  46  t=   0   0%
EVENT_MINIMUM_GUARANTEE   n=  42  t=   0   0%
HERO_RECRUIT_ADVANCED     n=  38  t=   0   0%
```

**五个"被选 ≥38 次而真进展为 0"的目标**，合计约 1046 步 —— 约占全量 10% 的生产时间，
全部落在"被调度、但拿不到第二步"这一类。

---

## 二、`CLEAR_INTEL` 的闭环（最近 12 步原文）

```
POPUP  BACK                          intel_master_bounty_popup_closed   SUCCESS gp=False
INTEL  BACK                          intel_board_exhausted_            SUCCESS gp=False
MAP    OPEN_INTEL                    intel_goal_from_world             SUCCESS gp=False
INTEL  SELECT_INTEL_PIN              intel_board_has_pins              SUCCESS gp=False
POPUP  BACK                          intel_master_bounty_popup_closed   SUCCESS gp=False
INTEL  BACK                          intel_board_exhausted_            SUCCESS gp=False
HOME   OPEN_MAP                      intel_goal_requires_map           SUCCESS gp=False
HOME   OPEN_MAP                      intel_goal_requires_map           SUCCESS gp=False
HOME   OPEN_MAP                      intel_goal_requires_map           SUCCESS gp=False
HOME   OPEN_MAP                      intel_goal_requires_map           SUCCESS gp=False
HOME   OPEN_MAP                      intel_goal_requires_map           SUCCESS gp=False
```

**每一环都 SUCCESS，没有一条 FAIL。** 与第一轮修掉的 `HOME↔MAP` 乒乓同型。

页面转移量（全量）：

```
HOME→MAP 693   MAP→HOME 616   HOME→MAP→HOME（三步环）468
HOME 发 OPEN_MAP 699 次，其中下一步又回 HOME 仅 6 次
```

⇒ **不是"原地导航即回"，而是多步环路。** 完整段（最后两例）：

```
HOME  OPEN_MAP         CLEAR_INTEL              SUCCESS gp=False
MAP   OPEN_HOME        KEEP_TRAINING_PRODUCTIVE SUCCESS gp=False   <== 被抢走
HOME  OPEN_QUICK_PANEL DISCOVER_QUICK_PANEL_... SUCCESS gp=True
HOME  OPEN_MAP         CLEAR_INTEL              SUCCESS gp=False   <== 又来
MAP   OPEN_HOME        KEEP_TRAINING_PRODUCTIVE SUCCESS gp=False   <== 又被抢走
```

**`CLEAR_INTEL` 从 HOME 出发 `OPEN_MAP` 共 332 次，每次都只买到"站在 MAP 上"，
从没拿到第二步。**

---

## 三、抢走它的是训练链，而训练链自己也零进展

`KEEP_TRAINING_PRODUCTIVE`（492 次、`gp_true` **0**）：

```
expected_result : home_opened 402 / resource_search_closed 24 / underlying_page_restored 23 …
skill           : OPEN_HOME 376 / BACK 69 / DISMISS_SHARED_REWARD 23 / TRY_ORDINARY_CONTROL 16
                  OPEN_INFANTRY_TRAINING 2      <== 全程只跑了 2 次
decision_reason : training_goal_requires_home 376
```

**它 76% 的动作是"我现在不在 HOME，请导航过去"，
而 `OPEN_INFANTRY_TRAINING`（真正开始训练的那一步）全程只出现过 2 次。**

`KEEP_BUILDING_PRODUCTIVE` 同型：`home_opened 118` / `task_page_open 95`。

**两者合起来构成一条自我维持的环：**
`CLEAR_INTEL` 付导航成本去 MAP → `KEEP_TRAINING_PRODUCTIVE` 用 `OPEN_HOME` 把它挤回 HOME →
自己也只是发了个 `OPEN_HOME` → 下一个 `CLEAR_INTEL` 再次胜出。
**没有一方在做自己的事，两方都在付对方的路费。**

---

## 四、为什么我第一轮的 `page_residency` 修不了它

实测 `goal_utility._residency_table()`：

```
KEEP_TRAINING_PRODUCTIVE   NOT RESIDENT
KEEP_BUILDING_PRODUCTIVE   ['HOME']
CLEAR_INTEL                NOT RESIDENT
```

**这是我当初如实测量的结果，不是阈值问题。** 它 76% 的步骤都是导航、
从不在任何页上训练 ⇒ 没有"习惯页"可测 ⇒ 驻留项对它返回 0 是**正确的**。

（对比：`KEEP_BUILDING_PRODUCTIVE` 有 `['HOME']`，但它被墙的时间比训练链更长，
`repeat_failure` 把它压下去；而 `CLEAR_INTEL` 同样 NOT RESIDENT。）

**结论：这不是排序层缺陷，是"训练链缺少在 HOME 上的第二步"这个能力缺口。**
排序层已经把能做对的都做对了 —— 剩下的每一次修补都只是换个目标重新描述同一个病。

---

## 五、下一轮该做什么（方向已定，但先量）

要回答的只有一件事：**`OPEN_INFANTRY_TRAINING` 为什么只跑了 2 次？**

三种可能，处理方式完全不同：

1. **`available_skills` 里没有它**（能力没接）⇒ 该接；
2. **有它但选不上**（被墙/被抢）⇒ 该看排序与冷却；
3. **有它、选上了、但执行后没产生 Goal 进展**（缺 Verifier）⇒ 该补验证器，
   而这与第一轮 `DISCOVER_QUICK_PANEL_TASKS` 的记账缺口是同一类。

**先量 ①，再量 ②③。** 不再一次改三处 —— 本会话已经有四次"改了三处方向都错"的记录。

---

## 六、本轮状态

- **零代码改动。** 生产 pin `291ede58`，AUTO 正常，`worker_exits` 19 未增长。
- 分支 `workbuddy/page-residency-20261003` = `3813a82d`。
- 日历链的两环（识别 `aab0dbb8`、记账 `a70db034`+`291ede58`）**保留且已在真机验证**，
  活锁的成因也已定位到"没有机制去点欠债活动"，且知识库写明该活动没有安全流程
  ⇒ **暂停，不是放弃**（见 `ALLIANCE_MOBILIZATION_HAS_NO_SAFE_FLOW_20261003.md`）。
