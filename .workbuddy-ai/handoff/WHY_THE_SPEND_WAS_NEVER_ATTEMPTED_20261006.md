# 生产观察：为什么花钱那一步从来没被尝试过（2026-10-06 01:00–01:10）

> `docs/DEVELOPMENT_FLOW.md §三 观察` 的产物。AUTO 真跑期间**只读**，没有改代码、没有真机实验
> （模式是 AUTO，§12 禁止在 Auto 下改代码；启动原因是验证上一轮的 `b883d1fe`）。

## 先记结果：`b883d1fe` 已被生产证明

```
17:05:02  KEEP_BUILDING_PRODUCTIVE  OPEN_BUILDING_UPGRADE
  result = SUCCESS · verifier_ok = true
  verifier_evidence = {page_before: HOME, page_after: BUILDING, upgrade_dialog_visible: true}
  state_after.building.upgrade_dialog_visible = true
BUILDING_UPGRADE_PANEL_NOT_PROVEN 仍是 104，零新增；OPEN 计数 109 → 110
```

**但 `BUILDING_UPGRADE`（花钱）依然 0 行。** 下面是用证据回答"为什么"。

## 关键事实一：成功的那一次 OPEN，是它那一轮的**最后一个动作**

按 `episode_id` 给行分轮（`episode_id` = 该轮启动时刻）：

```
轮 20261006_010109_436158   24 行   1061663148
轮 20261006_010410_953543    6 行   1061663148   ← 成功 OPEN 在这里，第 6/6 个动作
轮 20261006_010558_682738   18 行   1063040265
```

那 6 行完整序列：

```
1 17:04:38  KEEP_BUILDING_PRODUCTIVE   OPEN_TASK_FROM_QUICK_PANEL_BUILDING  SUCCESS
2 17:04:43  DISCOVER_QUICK_PANEL_TASKS OPEN_QUICK_PANEL                     SUCCESS
3 17:04:48  KEEP_BUILDING_PRODUCTIVE   OPEN_TASK_FROM_QUICK_PANEL_BUILDING  SUCCESS
4 17:04:53  DISCOVER_QUICK_PANEL_TASKS OPEN_QUICK_PANEL                     SUCCESS
5 17:04:58  KEEP_BUILDING_PRODUCTIVE   OPEN_TASK_FROM_QUICK_PANEL_BUILDING  SUCCESS
6 17:05:02  KEEP_BUILDING_PRODUCTIVE   OPEN_BUILDING_UPGRADE                SUCCESS
```

面板日志：`01:05:45 ✓ 本轮结束：已切换到角色 1063040265，正在刷新状态`。
**这一轮不是被动作预算截断的（只有 6 个动作，不是 24），是换角色结束的。**
所以花钱那一步**连一次决策机会都没有** —— 它需要 OPEN 成功之后的**下一个**决策轮。

## 关键事实二：那 6 行是**两个目标在抢同一个快捷面板**

`learning/decisions.jsonl` 的逐条决策（`chosen` / `runner_up_gap`）：

```
17:04:24  chosen=KEEP_BUILDING_PRODUCTIVE    runner=CLAIM_EXPLORATION_IDLE   gap=142.2
17:04:40  chosen=DISCOVER_QUICK_PANEL_TASKS  runner=CLAIM_EXPLORATION_IDLE   gap=142.3
17:04:45  chosen=KEEP_BUILDING_PRODUCTIVE    gap=142.3
17:04:50  chosen=DISCOVER_QUICK_PANEL_TASKS  gap=142.3
17:04:55  chosen=KEEP_BUILDING_PRODUCTIVE    gap=142.3
```

两个目标**分数紧咬（gap 142.2 → 142.3）、轮流被选中**，动作互为前提：
`KEEP_BUILDING_PRODUCTIVE` 点它的行 → `DISCOVER_QUICK_PANEL_TASKS` 又把面板打开一次 →
它再点一次行……**直到第 6 步才轮到 OPEN**。

这就是会话早先刻画过的**公平性乒乓**（`tests/test_two_goals_that_need_each_others_page_ping_pong.py`）。
**同一个根因现在有两个实例**（§43 要求修共享根因，不要逐目标打补丁）：

| 实例 | 争夺的资源 | 互相抵消的动作 |
|---|---|---|
| ① 滚动 | 快捷面板的**滚动位置** | `SCROLL_QUICK_PANEL_TASKS` ↔ `SCROLL_QUICK_PANEL_BACK` |
| ② **本轮新发现** | 快捷面板的**开/关与选中行** | `OPEN_TASK_FROM_QUICK_PANEL_BUILDING` ↔ `OPEN_QUICK_PANEL` |

**共享根因：快捷面板的状态被争用，而没有任何东西记录"这一刻它是为谁开的"。**
于是两个目标交替，谁的进展都不留存 —— 每一步都 SUCCESS，整体却没前进。

## 关键事实三：最需要进展的目标，被自己失败的历史压得最低

最近 400 条决策里带 `repeat-failure` 惩罚的计数：

```
  54  KEEP_BUILDING_PRODUCTIVE     ← 最多
  32  AVOID_STAMINA_WASTE
  31  KEEP_TRAINING_PRODUCTIVE
  29  CLEAR_INTEL
```

`KEEP_BUILDING_PRODUCTIVE` 的 `repeat-failure -60.0` 来自它自己的
`TRY_ORDINARY_CONTROL → SEMANTIC_TARGET_NOT_VERIFIED`（本轮又发生 2 次：17:02:26、17:06:19）。

**这是一个反馈回路**：它失败 → 被扣 60 分 → 排到后面 → 更少轮次 → 更不容易走到花钱那一步 →
继续失败。**"目标因为无法进展而受到惩罚，而惩罚又让它更无法进展。"**

## 一个未解异常（未处理，留给下一轮）

面板日志里有两轮以 `✓ 本轮结束：device leased for development` 结束：

```
01:05:08  ✓ 本轮结束：device leased for development
01:06:12  ✓ 本轮结束：device leased for development
```

而 **`learning/device_leases.jsonl` 里 17:00 之后租约活动为零** —— 没有任何人持有租约。
我自己的探索租约都在 16:54–16:59 且都已 `released_at`（`DEVICE_EXPLORE_STEP`）。
**所以那两轮的让出原因与租约事实不符**，暂时无法解释。可能是：
- `holder()` 对"已过期但未释放"的记录仍然返回；或
- 那个 reason 由别的路径设置（`shop_visit.py:1320` 也定义了同一个字面量
  `LEASE_YIELD_REASON = "device_leased_for_development"` —— **同一个 reason 两处定义**，本身就是可疑形状）。

**没有去改**，因为在 Auto 模式下不改代码，且这条需要单独一轮带真机复现。

## 下一轮（切 Manual 后）该做的三件事，按价值排序

1. **共享根因（§43）**：给快捷面板加"这一刻为谁而开"的概念，让
   `OPEN_TASK_FROM_QUICK_PANEL_BUILDING ↔ OPEN_QUICK_PANEL` 不再互相抵消。
   与滚动那一对同一处修 —— **一次修好两个实例**。
2. **`repeat-failure` 反馈回路**：现在的惩罚让"无法进展的目标"更难进展。
   §16 说的是"长期不解决要升权、短期失败要退避"，而这里是**长期不解决反而一直被退避**。
3. **让花钱那一步有机会发生**：成功 OPEN 之后需要至少再一个决策轮。
   可以先把建筑目标的轮次边界看清楚，再决定是"加预算"还是"改顺序"。
