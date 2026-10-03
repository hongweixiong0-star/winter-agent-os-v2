# 全局审计结论：上一轮的根因判断是错的（2026-10-03 第三轮）

> **本文件推翻上一轮 handoff 的核心结论。** 按持久开发指令第 51 条 F
> （同一子系统连续两次修改后出现新循环 ⇒ 停止局部优化、重新审计）写下。

---

## 一句话

**`DISCOVER_EVENT_CALENDAR` 没有"自我抹除"，它的链跑得好好的（3108 步真实产出）。
真正的问题是 `calendar_scan_due` 让它永远 due，于是每 24 秒重新导航一次。**

---

## 一、我上一轮错在哪

### 错误 1：把"设计正确的行"当成缺陷

我写：

> "COMPLETE 的目标从 board 上消失 ⇒ 自我抹除"

实际重放那一帧（`79cb572c`，`05:53:13`）：

```
discover 总目标数: 27
DISCOVER_EVENT_CALENDAR  COMPLETE  prio=-inf  skills=()
```

行**在** board 上（第 7/27 位）。`priority=-inf` 是**正确**的：
`COMPLETE ∈ NOT_ACTIONABLE`，完成的目标本来就不该被调度。

我把"`DISCOVER_QUICK_PANEL_TASKS` 需要 `served_by` 才能记账"
错误地推广成"COMPLETE 行必须留在 board 上才能工作"。
**前者说的是账本，后者说的是调度——两件事，我混成了一件。**

### 错误 2：把"缺席"当成"在 EVENT 页上被排除"

我用旧数据算出"日历目标在 EVENT 页 209/209 次决策中 0 次在 board 上"，
据此断定它在 EVENT 上被排除。

**但那是 COMPLETE 行的正常表现**——完成的扫描在 EVENT 上不参与竞争，
所以它当然不会出现在 `chosen` 分布里。**我用"没被选中"反推"被排除"，
这一步推理本身就不成立。**

### 错误 3：把"导航后被赶走 13/13"当成致命证据

真实形状是：

```
129x  OPEN_EVENT_CALENDAR_FROM_HOME -> SCROLL_REGULAR_EVENT_TABS  (它自己继续)
 81x  OPEN_EVENT_CALENDAR_FROM_HOME -> OPEN_EVENT_CALENDAR_TAB    (它自己继续)
  9x  -> OPEN_QUICK_PANEL          (别的目标)
  3x  -> BACK                      (别的目标)
  2x  -> OPEN_MAP                  (别的目标)
```

**210/227（93%）是它自己往前走。** 我只看了"被赶走"那 3 次
（因为它们构成了 `HOME→EVENT→HOME` 的可见循环），
**却没算全量**——这正是"看形状不看分母"的典型错误。

---

## 二、真正的根因

### 证据 1：它的导航频率高得离谱

```
被选总次数: 213
再次被选间隔: 中位 0.4 分钟 / 最小 0.2 分钟 / 最大 42.8 分钟
被选时的决策页: MAP 129 次, HOME 84 次（从不在 EVENT）
```

**中位 24 秒一次。** 这不是"优先级高所以常被选中"，
这是**每 24 秒重新判断一次"该不该扫日历"，每次都答"该"**。

### 证据 2：这条链真实产出很好

在 EVENT 页上的 3108 步：

```
OPEN_EVENT_CALENDAR_DETAIL   1365 步  gp=False
RETURN_EVENT_CALENDAR       1239 步  gp=True   ← 真产出
OPEN_EVENT_CALENDAR_TAB      337 步  gp=False
SCROLL_REGULAR_EVENT_TABS    166 步  gp=False
```

**1239 次 `gp=True`。** 它在工作。

### 证据 3：到期判定的 docstring 自己写明了这个行为

`event_schedule.calendar_scan_due`（第 5 行起）：

> "An activity the last screen **advertised but nobody opened** keeps it due,
> however complete the rows it did open are. Measured 2026-10-02: with six grid rows
> all opened at 05:35-05:58Z, both roles answered `False` for the rest of the day,
> `DISCOVER_EVENT_CALENDAR` was never selected again, and no episode on the new
> revisions ever stood on `Page.EVENT` — so the strip reader, correct as it was, was
> never called once."

**"advertised 但没人打开 ⇒ 永远 due" 是一个刻意设计、且有实测记录的判据。**
它带来的是"每 24 秒重扫一次"，而不是"读不到活动"。
**这个取舍本身需要重新评估，但它不是我上一轮改的那一处。**

---

## 三、所以循环的完整因果链

```
HOME:  calendar_scan_due == True（因为有"广告了但没打开"的活动）
       ⇒ DISCOVER_EVENT_CALENDAR base=1000，全场最高，必胜
       ⇒ 导航到 EVENT
EVENT: 打开日历 ⇒ 5 个条目全部 details_observed=True ⇒ COMPLETE
       ⇒ 合理让位给别的目标（这是正确行为）
       ⇒ 被 BACK 回 HOME
HOME: calendar_scan_due 仍然是 True（那些活动还是"没打开"）
       ⇒ 又是 base=1000 必胜 ⇒ 又是 24 秒后重扫
```

**活锁在 `calendar_scan_due` 与"广告≠已读"这条判据上，不在 board 排序，
也不在 COMPLETE 行。** 我上一轮改的 `served_by` 只是让账本能记账
（这一点本身有用，可保留），但它**不解除活锁**。

---

## 四、按指令第 51 条，本轮停止局部修复

已触发 **F 条**："连续两次修改同一子系统后出现新的死锁、饥饿、永久 BLOCK、
错误 GLOBAL_WAIT ⇒ 立即重新审查该子系统。"

日历子系统已被本会话连改两次（`79cb572c` 的 `served_by`，以及上一轮的
`page_residency`），而乒乓**仍在**（第 23 行实测重现）。
本轮**不再改代码**。

---

## 五、泄漏分支已定位（继续查下去了，没有停在"下一轮再查"）

对两个角色分别调用四个判据：

```
role 1061663148:  observed_at 2026-10-02T05:58Z（1437 分钟前）
                  pending=False  strip_stale=False  advertised_unread=()
                  ⇒ calendar_scan_due = False      ← 机制本身能收敛
role 1063040265:  observed_at 2026-10-03T05:53Z（1.9 分钟前）
                  pending=False  strip_stale=False
                  advertised_unread=('CANYON_CLASH','STATE_VS_STATE')
                  ⇒ calendar_scan_due = True       ← 活锁在这里
```

**角色 A 24 小时不 due，证明不是机制坏了，是这两个具体活动。**

### 那两个活动的真实状态

`ACTIVITY_STRIP`（顶部横条）：

```
STATE_VS_STATE   最强王国  tap_norm=[0.466,0.133]  details_observed=null
CANYON_CLASH     峡谷会战  tap_norm=[0.742,0.134]  details_observed=null
read_entries: 0
```

`CALENDAR_GRID`（日历网格，5 行）：

```
ICEBOUND_TREASURE               tap=True  observed=True
ICEBOUND_TREASURE_MYSTERY_SHOP  tap=True  observed=True
DISCOVERED_EVENT_4178AC2F00     tap=True  observed=True
DISCOVERED_EVENT_BB2077C97D     tap=True  observed=True
DISCOVERED_EVENT_E1FB4AC23A     tap=True  observed=True
```

### 完整因果链（每一环都已实测）

1. 客户端在**顶部横条**宣告了 `最强王国` 和 `峡谷会战`，两者都有 `tap_norm`；
2. 它们**不在日历网格的 5 行里** —— 打开网格进不到它们；
3. `advertised_but_unread_activities` 判据是"客户端画了且点得着、但没读过"，
   它正确地把这两个判为未读；
4. 于是 `calendar_scan_due` **永远 True**；
5. 于是 `DISCOVER_EVENT_CALENDAR` 在 HOME 上永远是 `base=1000` 的必胜者；
6. 于是每 24 秒重扫一次；到 EVENT 后打开网格、5 行全已读 ⇒ COMPLETE ⇒ 让位 ⇒ 回 HOME；
7. 回到第 4 步。

**这是一个真正的 UNKNOWN 黑洞（宪法第 11 条）**：客户端宣告了一个目标，
它点得着，但**当前已知的日历流程到不了它**。
判据本身没错（它的注释里精确记录了两次被否掉的错误版本），
**缺的是"怎么打开横条上的活动"这条路径**。

---

## 六、下一步该做什么（不是"改 due 判定"）

**不要改 `calendar_scan_due`**。它的四个分支都是对的，
把它改成"忽略横条"会丢掉两个真实活动的报名/开战时间，
而这正是 `GOAL_CHAIN_FACT_AUDIT` 那类问题想避免的。

该做的是**补上打开横条活动的路径**：

1. 先在真机上确认 `tap_norm=[0.466,0.133]` 那个点**点击后会发生什么**
   （是否直接打开活动详情？是否需要别的页签？是否被 `ordinary_control` 拒绝）；
2. 确认能打开后，为它建 Verifier（活动详情真的出现了？）
   与路线（`TAP_SEMANTIC` 到横条活动项）；
3. 打通后 `read_entries` 会被填上，`advertised_but_unread` 自然收敛，
   `calendar_scan_due` 也会自然变 False —— **不需要碰判据本身**。

**在看到真机帧之前不要写任何代码。** 这条链的第一步是"看"，
不是"改"。

---

## 七、本轮提交

无代码改动。只有本文件与记忆更新。

`79cb572c` 部署在生产上，AUTO 正常运行。
**`served_by` 的改动保留**（它让完成的扫描能被记账，是真需求），
但**必须明确：它没有解决乒乓，不要当成已修复。**

