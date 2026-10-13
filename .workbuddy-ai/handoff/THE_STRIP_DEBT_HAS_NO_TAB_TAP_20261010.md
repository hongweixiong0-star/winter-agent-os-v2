# 常规活动条带欠着的那一笔，缺的是「点某个具名页签」——而且只有一个动作

> 状态：**设计已定，未实现**。日期 2026-10-10。代码基线 `84b4be3c`（生产 pin 工作树）。
> 走的是「目标接入阶梯」的第 1–3 步；第 4 步（实现）尚未开始。

## 搜索产物（硬性前置门）

```
=== 搜索产物 ===
任务/问题：让 AUTO 自己走到常规活动的巨熊页签上，从而自己写出 BEAR_HUNT 的预约
          （现在只能靠人手用 tools/record_a_printed_reservation_from_a_frame.py 记）

搜索关键词：DISCOVER_EVENT_CALENDAR / OPEN_EVENT_CALENDAR_TAB / tab_positions_norm /
          advertised_but_unread_activities / calendar_scan_due / read_entries /
          EVENT_CALENDAR_TAB / BEAST_SEARCH_TAB / route_for(PARTICIPATE_BEAR)

搜索结果（全部来自生产 pin 工作树的代码与今日真机帧，非记忆）：
  1. tools/reuse_check.py：OPEN_EVENT_CALENDAR_TAB 存在（CANDIDATE, Page.EVENT,
     Action TAP_SEMANTIC/EVENT_CALENDAR_TAB），brain.py:697 与 :714 有路由；
     SELECT_EVENT_TAB 与 READ_PRINTED_RESERVATION 都不存在。
  2. goal_library.py:2177-2191：站在 EVENT hub 上时，DISCOVER_EVENT_CALENDAR 只给
     OPEN_EVENT_CALENDAR_TAB（日历）或 SCROLL_REGULAR_EVENT_TABS。没有别的页签分支。
  3. event_calendar.py:694-697：hub 读数已经产出 tab_positions_norm = {label: [x_norm, y_norm]}。
  4. runtime.py:5453-5474：EVENT_CALENDAR_TAB 的语义目标写死读 calendar_tab_tap_norm，
     不通用。全仓库没有 TAB_BY_LABEL / SELECT_TAB 之类的通用动作。
  5. runtime.py:5837-5881 BEAST_SEARCH_TAB 是最近的同类先例：按本帧 OCR 读到的标签点页签，
     格子被裁时返回 None 让调用方去滑，而不是给一个裁掉一半的点。
  6. event_schedule.py:463-519 advertised_but_unread_activities **已经覆盖条带**：
     ACTIVITY_STRIP 的 entries 算「已展示」，read_entries 算「已读」，债务 = 展示 − 已读 − 今日不可进。
     其 docstring 明写：六条真网格行都带 tap_norm 与 details_observed，**「条带是唯一还欠着的一笔」**。
     【注：这句 docstring 描述的是它写作当时的状态；下面「实测推翻了上面那句的一半」一节
      会用今天的真实债务说明它现在已经不成立。此处保留原文以存真。】
  7. event_schedule.py:767-808：条带行唯一的记账入口是「该活动的 EVENT_DETAIL 读数且
     calendar_origin != GRID_ENTRY」。
  8. 今日真机帧实测（tools/probe_what_the_event_strip_exposes.py，走生产入口
     _regular_event_hub_on_frame）：巨熊行动 出现在 3 张帧的 tab_positions_norm 里，
     tap_norm = [0.25556, 0.13359]（[决战王城,巨熊行动] 两页签帧）与
     [0.32153, 0.13398]（[存戏,巨熊行动,决战王城,堡垒争夺] 四页签帧）。

假设：缺口是**一件**东西 —— 一个「点常规活动条带上某个具名页签」的能力。
     读几何（tab_positions_norm）已有、滑出页签（SCROLL_REGULAR_EVENT_TABS）已有、
     点下去之后的读者与写预约的接线已有。不需要新目标，也不需要新读者。

不确定性：
  a) 点中页签后产生的是「hub 且选中巨熊行动」，**未必**是一条 calendar_detail 读数，
     因此条带的 read_entries 可能仍不被记账 ⇒ 债务不清 ⇒ 24 秒重选循环回来
     （event_schedule.py:417-433 记过同一个循环）。这条必须在新能力里一并解决。
  b) 页签格子被裁一半时，OCR 框中心可能落在邻居上（runtime.py:5858-5869 记过同类事故：
     点 野兽 的可见窄条，选中的是 冰原巨兽）。所以位置必须来自本帧且要在条带 band 内。
  c) 巨熊页签与 决战王城/堡垒争夺 并排，不在最左；需要先滑出来，且方向要能来回。
=== 结束 ===
```

## 分流判定：**不是新目标**，是既有目标缺能力

阶梯的判据是「`discover()` 会不会产出这条 goal」。会 —— `DISCOVER_EVENT_CALENDAR` 在
`calendar_scan_due` 为真时就被产出，而条带债务让它**已经**为真（`event_schedule.py:549`）。
所以缺的是它手上没有那个技能，**不要加第二个目标**。

> 外部先验也支持这个形状：`knowledge/events/timed_event_readiness.json` 把这件事建模成
> **排期 + 触发**（`reservation_scope: PER_ROLE`、`next_open_condition`），不是 goal。
> 与本项目既有的判断一致（巨熊是「排期 + 触发 + 抢占」）。

## 缺口，一句话

> **运行时会走到那条条上、会读它、会滑它，但永远只选「日历」那一个页签，
> 因此条带上其它活动永远是「已展示、未读」，那笔债永远还不上。**

## ⚠ 但实测推翻了上面那句的一半（同一次会话内自查）

写成上面那句之后我去量了**真实债务**，结果是：

| 角色 | 网格 6 行里已打开 | 条带 entries | 条带 read_entries | 实际 DEBT |
|---|---|---|---|---|
| 1063040265 | **1** | `[STATE_VS_STATE]` | `[STATE_VS_STATE, CANYON_CLASH]` | 4 个**网格** id |
| 1061663148 | **1** | `[STATE_VS_STATE]` | `[CANYON_CLASH, ALLIANCE_MOBILIZATION, STATE_VS_STATE]` | 同上 4 个 |

```
DEBT = ('DISCOVERED_EVENT_2CED2A762E', 'DISCOVERED_EVENT_A33B0DC6E9',
        'DISCOVERED_EVENT_DC53E03FB8', 'EXCLUSIVE_GEAR_FORGE')   # 两个角色相同
calendar_scan_due = True
```

**结论修正：**
1. **条带今天一笔都不欠** —— `STATE_VS_STATE` 已在 `read_entries` 里。
   所以 `event_schedule.py:463` 的 docstring 那句「条带是唯一还欠着的一笔」**已经过时**
   （它描述的是当时的状态，现在不是）。
2. 让 `calendar_scan_due` 一直为真的是**网格行**：6 行都有 `tap_norm`，只有 1 行
   `details_observed=True`，其余 4 个 id 从未被打开。
3. 所以「加一个点条带页签的动作」**不会**清掉当前这笔债，也就不会让扫描收敛。
   它解决的是**另一半**（让 AUTO 能读到巨熊排期），但当前 `scan_due=True` 的成因不是它。

**这条修正对设计的影响：** 第 4 步实现时，那个关键危险（债务不清 ⇒ 24 秒重选循环）
的**当前实例是网格行**，不是条带。两个问题都要处理，但**先量清是哪一个**，
不要因为设计文档里写着「条带」就把网格的账记到条带上。

### 顺带量到的两件事（下一步的入口）

- `calendar_next_entry`（`event_schedule.py`）**永远取第一行**未观察的：
  `next(row for row if details_observed is not True and tap_norm and event_id)`。
  当前两角色都取 `DISCOVERED_EVENT_DC53E03FB8`（`tap_norm=[0.87431, 0.38047]`）。
- 全流 10004 条 episode 里，提到 `OPEN_EVENT_CALENDAR_DETAIL` /
  `EVENT_CALENDAR_DETAIL_OPEN` 的只有 **49** 条；其中 7 条带
  `UNKNOWN_NAV:PROVIDER_ANSWERED_NOTHING`（最近一条 2026-10-10T00:38:10Z）。
- 每个网格行的 `title_raw` **都是 `None`** —— 网格读出了 `event_id` 与 `occurrence_key`，
  却没留下被画出来的那个标题。诊断时看不到「这一行是什么活动」。


## 复用图（改之前先确认这些已经在）

| 需要的东西 | 已经存在 | 位置 |
|---|---|---|
| 具名页签的坐标 | `tab_positions_norm[label]` | `event_calendar.py:694-697` |
| 生产入口（含裁图补读） | `_regular_event_hub_on_frame` | `runtime.py:2504` |
| 滑出屏幕外的页签 | 技能 `SCROLL_REGULAR_EVENT_TABS` | `skills.py:287` |
| 条带 ROI 带（防止点出带外） | `tabstrip_roi_norm` | `event_calendar.py:698` |
| 债务判定 | `advertised_but_unread_activities` | `event_schedule.py:463-519` |
| 债务 → 扫描到期 | `calendar_scan_due` | `event_schedule.py:545-551` |
| 条带行记账 | `read_entries` 合并 | `event_schedule.py:797-808` |
| 点中后写预约 | hub→bear 分支 + `record_live_countdown` | `ocr.py` hub 分支 / `runtime.py:5043-5070` |
| 唤醒与加成 | `bounded_poll_delay_seconds` + `_event_readiness_bonus` | `control_panel.py:1316` / `runtime.py:1715` |

## 最小改动（第 4 步，五处）

1. **`skills.py`**：新增 `OPEN_REGULAR_EVENT_TAB`，
   `Action("TAP_SEMANTIC", "REGULAR_EVENT_TAB_BY_LABEL")`，`Page.EVENT`，
   `state=CANDIDATE`，`verifier=REGULAR_EVENT_TAB_OPEN`，
   `unknown_policy`：本帧读数里没有该标签 ⇒ 不点。
2. **`runtime.py` `_resolve_semantic_target`**：新增
   `REGULAR_EVENT_TAB_BY_LABEL` 分支，读**本帧**的
   `fresh_hub["tab_positions_norm"][label]`；标签不在 ⇒ 返回 `None`（让调用方去滑），
   再校验点落在 `tabstrip_roi_norm` 的带内 —— 与 `EVENT_CALENDAR_TAB`（:5453-5474）
   同形，与 `BEAST_SEARCH_TAB`（:5837-5881）同纪律。
3. **`goal_library.py:2177-2191`**：hub 分支的技能选择加一档 —— 当条带暴露了
   **在债务里**（或语义上属于需排期活动）的页签时，给 `OPEN_REGULAR_EVENT_TAB`
   并把标签带进 evidence；否则维持现状。
4. **`brain.py`**：把该 skill 映成一条 `Decision`，标签来自 goal evidence，
   **不新增第二套页签表**。
5. **verifier**：`REGULAR_EVENT_TAB_OPEN` —— 点后本帧 hub 的
   `display_name`/`tab_signature` 变成被点的那个活动；拿不到就说没有，
   参照 `verify_event_calendar_tab_open`（`verifier.py:1912` 一带）。

### 必须同时做的那一件（否则前功尽弃）

条带行要被记账，需要一条 `calendar_origin != GRID_ENTRY` 的 EVENT_DETAIL 读数
（`event_schedule.py:767`）。**如果点中页签只产生「hub 选中该活动」而没有 detail 读数，
债务不会清，`calendar_scan_due` 会一直为真，`DISCOVER_EVENT_CALENDAR` 会每 ~24 秒被重选**
—— 这正是 `event_schedule.py:417-433` 与 `tools/strip_credit_convergence_check.py`
记录过的那个循环。

> **判据：新能力的验收必须包含「债务下降且**不再回升**」，不能只验收「点到了那个页签」。**
> `tools/strip_credit_convergence_check.py` 已经是这条的现成检查器，用它。

## 验收（离线先过，再谈真机）

**离线（用今天的帧，不需要设备）：**
- 以 `bear_tab_visible_on_strip.png` 为输入：解析出的点必须等于
  `tab_positions_norm["巨熊行动"] = [0.25556, 0.13359]`，且落在该帧的 band
  （`y_norm=0.05121, h_norm=0.11168` ⇒ y ∈ [0.05121, 0.16289]；0.13359 在带内）之内。
- 以 `regular_activity_before_swipe.png`（页签只有 `[变革的乐章, 日历]`）为输入：
  解析器必须返回 `None`，**不是**编一个点。
- 以 `bear_page_live_20261010.png`（hub 未识别）为输入：同样返回 `None`。

**真机（设备门之后，见下）：**
- episode 流出现以条带页签为来源的 detail 读数；
- `advertised_but_unread_activities(role)` 的集合**变小且不再回升**；
- 巨熊那一帧之后，`learning/timed_event_schedule.json` 里该角色的
  `BEAR_HUNT.reserved_start` 不再为 `None`，且 source 不是人手工具那个值。

## 设备门（阶梯第 3 步末尾、第 7 节）

真机验收前必须确认设备归属：`episodes.jsonl` 新鲜度 + 两帧对比。
**AUTO 常驻在跑**（本文件写作时 `pump.json` 08:31:37、`episodes.jsonl` 08:31:58），
所以真机部分要排在窗口之外，并且要先取 lease。

## 不在范围内（明确不做）

- **不加新目标**。`DISCOVER_EVENT_CALENDAR` 已经会被产出。
- **不新增第二套页签表 / 页签枚举**。几何一律来自本帧读数。
- **不动 `tab_positions_norm` 的生产者**。它已经对了（今日 8/9 帧有逐页签坐标）。
- **不动那个 `>= 2` 标签的滑动守卫**。它被 4 条既有测试钉着，理由成立（见 MEMORY.md）。

## 与「明晚窗口」的关系

明晚 20:30 的唤醒**已经**由在册预约保证（`tools/probe_the_armed_reservation_reaches_the_ladder.py`
已验证 T30/T15/T5/T1 的加成与边界唤醒）。**本次改动不是那个窗口的前提**，
所以可以按自己的节奏做，不必赶在窗口前落地。
