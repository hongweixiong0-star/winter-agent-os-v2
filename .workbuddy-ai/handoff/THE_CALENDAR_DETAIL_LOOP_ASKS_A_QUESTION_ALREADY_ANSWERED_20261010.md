# 日历详情那个循环，在反复问一个**已知答案**的问题

> 状态：**归因完成，未改行为**。日期 2026-10-10。基线 `f29b2bfd`（生产 pin 工作树）。
> 本文是三件事的合并：step 4 的归因、一个**测量出来的**判据、以及一个**我决定不做的修法**及理由。

## 1. step 4 的归因：它走的是另一条路，而且那条路只有一把工具

step 3 与 step 4 是同一轮里紧邻的两步，`skill` 相同、`action` 相同，但名字不同：

| step | failure_type | verifier_ok | decision_reason | recognition_error |
|---|---|---|---|---|
| 3 | `EVENT_CALENDAR_DETAIL_NOT_PROVEN` | `false` | `open_next_uninspected_visible_calendar_entry` | `RESOLVER:CALENDAR_DETAIL_PANEL_ALREADY_VISIBLE` |
| 4 | `SEMANTIC_TARGET_NOT_VERIFIED` | `null` | `ONLINE_UNKNOWN_NAVIGATION:EVENT_CALENDAR_DETAIL_NOT_PROVEN` | `UNKNOWN_NAV:PROVIDER_ANSWERED_NOTHING` |

`ONLINE_UNKNOWN_NAVIGATION:` 这个前缀只在 `runtime.py:7049` 产生，来自
`_take_failed_navigation_retry`（`runtime.py:7036`）。而它被**排队**的地方是
`runtime.py:10954`，注释写着：

> 「A located navigation control can still fail its real verifier. After existing settle/retry
> recovery, give this selected Goal **one fresh model-grounded attempt**…」

排队条件是 `before.page == after.page`（页面没变）且 `skill` 以 `OPEN_` 开头 —— step 3 的
verifier 失败正好满足，于是 step 4 就是那次"model-grounded attempt"。

**关键**：`resolve` 里被强制的那一支（`runtime.py:10042-10048`）**只调
`_unknown_navigation_target`**，从不调 `_resolve_semantic_target`。所以这条恢复路径
**不重试项目自己的首选读者**，它只有顾问一把工具。而 `_unknown_navigation_target`
产点的唯一来源就是那一次 `_advised_control(frame.page.value, "", frame_path, frame, …)`
（`runtime.py:7018` 一带）。

## 2. 判据：**顾问有没有可答的路，取决于该语义是否在语义字典里**（48 条实测）

`_advised_control` 的两条路是「客户自己印出来的名字」（`knowledge/ui/semantic_dictionary.json`，
201 条）与一次模型调用。一个**字典里没有**的语义，就只剩模型调用 —— 而这类控件是靠
**测量出来的几何**定位的（哪一行还没被查看过），模型无从知道。

实测全流（`tools/probe_the_model_only_navigation_retry.py`，48 条走这条路的 episode）：

| 语义 | 在字典里 | 顾问作答 | 顾问沉默 |
|---|---|---|---|
| `QUICK_PANEL_ROW_BUILDING` | ✅ | 2 | 2 |
| `QUICK_PANEL_ROW_LANCER_CAMP_ENTRY` | ✅ | 2 | 0 |
| `REGULAR_EVENT_ENTRY` | ✅ | 0 | 2 |
| `BTN_OPEN_HOME` | ✅ | 0 | 0 |
| **`BEAST_SEARCH_TAB`** | ❌ | **0** | **18** |
| **`EVENT_CALENDAR_NEXT_DETAIL`** | ❌ | **0** | **11** |
| **`BTN_OPEN_INTEL_WILD_HUD`** | ❌ | **0** | 3 |

```
字典里没有的语义   →  32 条里作答 0 次
字典里有的语义     →   8 条里作答 4 次
```

> **判据：这条路对"字典里没有"的语义，把一步花在问一个答案早已在案的
> `PROVIDER_ANSWERED_NOTHING` 上。** 32/32 沉默，且机制清楚（只有一次模型调用）。

## 3. 我**决定不做**那个"顺理成章"的修法，以及为什么

最自然的改动是：在排队的条件里加一句「语义必须在字典里」，于是那 32 步就不再发生。
**我不做，理由有三条，第二条是主要的：**

1. **它会让账本变安静，而不是让系统变好。** 这条恢复路径是本项目排名第二、第三的失败来源；
   把它的步数砍掉，`FAILURE` 会变少，看起来像进展，而**循环本身没被修** ——
   `calendar_scan_due` 仍然一直为真，`DISCOVER_EVENT_CALENDAR` 仍会被反复选中。
   本项目的规矩是"不要用更安静代替更好"（`MEMORY.md` 已记过同型错误）。
2. **真正的问题不是"该不该重试"，而是"这一步该做什么"。** 那些帧上有一个面板正盖着网格，
   "开下一个详情"在物理上做不到。此时正确的动作是**退回日历**还是**把这次观察当作已读记账**，
   是一个需要设计的动作选择，不是重试策略能回答的。
3. **它是对决策链的改动，而明晚 20:30 有一个已武装的窗口。** 窗口本身不依赖它
   （预约已在册，见 `tools/probe_the_armed_reservation_reaches_the_ladder.py`），
   所以没有理由在窗口前引入未验证的调度行为。

## 4. 真正该设计的那个决定

当 `calendar.details_visible is True` 而 `events` 里没有 `calendar_detail` 时：

- **候选 A —— 退回日历**（`RETURN_EVENT_CALENDAR`，技能已存在）。
  条件已经能被本帧读数判定（`calendar.details_visible`），
  但现在 `brain.py:670` 只认 `detail.recognized`，所以这条分支进不去。
  ⇒ 最小改动是让"退回"的条件接受 `details_visible` 作为"有面板"的证据。
- **候选 B —— 把这次观察当作已读记账**（写 `read_entries`）。
  更贴合"点一下之后落点就是该活动自己的页面"这个实测事实，但它等于**断言**
  那次点名活动已被查看，而当前帧并没有给出该活动的身份（`calendar_detail` 缺席）。
  ⇒ 证据不足，**不建议**。

**首选是 A**，因为它只依赖本帧能读到的东西（一个面板盖着网格），不断言任何身份。
**但 A 必须先过 §4b 的那一个判据** —— 如果面板其实是目标活动自己的页面，A 就是有害的。

**A 的验收判据（离线先过）：**
- 以 `20261010_083724_834222_step_004_before_20261010T003807199241.png` 为输入，
  `brain.decide` 必须给出 `RETURN_EVENT_CALENDAR`，而不是 `OPEN_EVENT_CALENDAR_DETAIL`；
- 以同轮 step_003 的帧（`details_visible=False`）为输入，必须**仍然**给出
  `OPEN_EVENT_CALENDAR_DETAIL`（不能把正常情况也退回去）；
- `advertised_but_unread_activities` 的集合**不得因此变大**。

**A 的风险（先说清，再测）：** `details_visible` 由 `event_calendar.py:906` 算出
（`date_range or _COUNTDOWN_RE.search(detail_text) or "活动详情" in detail_text`）。
若它在**纯网格帧**上出现假阳性，退回就会把正常的一次扫描踢出去。

**已测（`tools/probe_whether_the_detail_flag_fires_on_a_plain_grid.py`）：没有观察到假阳性。**

```
frame                                   recognized  details_visible  calendar_detail  entries
step_003_before（网格）                  True        False            False            6
step_004_before（点击之后）              True        True             False            5
```

连续 **5 轮**（00:46 / 00:49:40 / 00:50 / 00:54:20 / 00:54:50 各一轮）**逐字重复**同一形状：

- `details_visible=True` 只出现在 **5 张 step_004 帧**上；5 张 step_003 网格帧**全是 False**；
- 同一个信号还有**独立旁证**：`entries` 从 **6 掉到 5** —— 面板确实盖住了一行，
  不是 OCR 噪声；
- 其余 10 张常规活动 / 巨熊页帧 `recognized=False`，不参与判定。

⇒ **候选 A 的前置条件在当前证据下成立**，而且这个循环是**可逐轮复现的**
（每轮都做同样两步、同样失败），所以修好之后的效果可以用"轮数"直接量。

**仍未测的部分（动手前要补）**：`details_visible=True` 却**真的**是纯网格的情形。
目前样本里没有，但样本只有 10 张识别帧 —— **不能把"没见过"当成"不存在"**。
补法：把 `read_event_calendar` 跑在一批更早的 grid 帧上（`dataset/raw/` 里有历史），
确认 flag 与 entries 下降的对应关系仍然成立。

## 4b. 第三个候选 C，它**可能才是真的**，而且会让 A 变成有害的

回头看 step_003 的**完整**记录（`20261010_084940_792088` 那轮的 step_003）：

```
after_screenshot   = ..._step_003_after_refresh_2_....png     ← 点了之后重新观察过（不止一次）
observed_change    = PROGRESS_CHANGED
verifier_evidence  = expected_event_id   = DISCOVERED_EVENT_DC53E03FB8   ← 目标（除雪）
                     actual_event_id     = ""                            ← 读不出身份
                     attributed_event_id = ""
failure_type       = EVENT_CALENDAR_DETAIL_NOT_PROVEN
```

配合上面 §4 的帧表（step_003 网格 6 行 → step_004 有面板、5 行），可以拼出这条链：

1. 解析器在网格上**拿到了点**（所以 verifier 跑了，`verifier_ok=false`）；
2. 点下去**确实开了东西** —— 面板盖住一行，`entries` 6→5，`observed_change=PROGRESS_CHANGED`；
3. 但**读不出那是哪一个活动** —— `actual_event_id=""`，且 `calendar_detail` 在整个 events 里缺席；
4. verifier 因此判 `NOT_PROVEN`，那一行**没有被记账**；
5. 债务不降 ⇒ `calendar_scan_due` 仍为真 ⇒ 下一轮再来一次（**逐轮复现，5/5**）。

⇒ **候选 C —— 缺的不是"该不该点"，而是"点开之后读不出它是什么活动"。**

**若 C 成立，则 A 是错的修法**：它把"点开之后读不出身份"变成"永远不再点开"，
于是那一行**永远拿不到记账** —— 账本不再报错，债务却更不可能还清。
这正是本文 §3 拒绝那个重试闸门的同一条理由。

**三者的取舍必须由这一个测量定下来：**

> **点开之后那个面板，到底是不是目标活动（除雪 / `DISCOVERED_EVENT_DC53E03FB8`）的页面？**
>
> - **是** ⇒ 缺的是**读者**（候选 C）：要补的是"从活动自己的页面读出身份"，A 有害、不许做；
> - **不是** ⇒ 点是错的行或点到了别处 ⇒ A"退回"或"重新定位"才是对的。

## 4c. 判据已做完：**是目标活动的页面**（我直接看了那张帧）⇒ 候选 C 成立，A 出局

`.../20261010_084940_792088/..._step_004_before_*.png` 的图像内容是：

```
页头：常规活动            页签条：最强王国 | 变革的乐章
2026-10-10 08:50:39      ← 客户端自己的时钟
网格（背后仍在画）：星期四10/08 … 星期六10/10(选中) … 星期三10/14
网格上浮着一张卡：
    除雪小分队
    2026-10-13 00:00 - 2026-10-15 24:00
    带上除雪器，开始一场酣畅淋漓的除雪行动吧！
    奖励
    距离开始：2 天 15:09:21
```

**三条结论：**

1. **点对了。** 目标是 `DISCOVERED_EVENT_DC53E03FB8`（`display_name="除雪"`），
   浮起来的是**「除雪小分队」** —— 同一个活动。
   ⇒ **候选 A（面板在就退回）出局**：那会把一张**刚刚正确打开的**卡退掉，
   并让这一行永远拿不到记账。
2. **浮起来的不是"详情页"，是一张预览卡（overlay）**。它盖在网格上，所以
   网格背后的行仍然读得到（5 行而不是 6 行），`calendar_detail` 因此缺席。
3. **卡上同时印了绝对窗口与倒计时**，而两者自洽：
   `08:50:39 + 2天15:09:21 = 2026-10-13 00:00:00`，与卡上印的 `2026-10-13 00:00` 一致。
   （顺带再证一次"两个时间戳相减"的方法。）

## 4d. 第一个阻塞点：一个**条件写反了的守卫**

> ⚠ **本节标题本节原先写作「缺的那一环，是一行条件」—— 那句话是错的（残缺，不是错）。**
> 量完之后发现是**三个**阻塞点叠在一起，第三个才是债务清不掉的原因。见 §4e。

`ocr.py:1282-1286`：

```python
if (
    page is Page.EVENT
    and calendar_reading.get("recognized") is not True        # ← 要求网格【没被识别】
    and calendar_detail_reading.get("recognized") is not True
):
    ...
    seconds_to_start = self._explicit_start_seconds(eligible)   # :1295
```

而卡帧上 `calendar_reading.recognized` **是 True**（背后 5 行仍被读出）。
于是这一支**根本不执行** ⇒ 卡的「距离开始」永远不会被读 ⇒
`seconds_to_start` 不算、没有记录产生、那一行不被记账、债务不降、下一轮重来。

**读者其实已经写好了**（`ocr.py:820 _explicit_start_seconds`，注释明写
「Read only a timer explicitly labeled 距开始/距离开始」），它也在 `:1295` 被调用 ——
**只是被这一支的门挡住了**。

> **判据：预览卡是一个 overlay，它【不会】让背后的网格变得不可识别。**
> 所以任何以"网格没被识别"为前提的分支，都不可能在卡出现时执行 ——
> 而卡出现恰恰是"点对了一行"之后的状态。
>
> 正确的门应该接受**"有东西盖着网格"**这个事实（本帧可读到的证据就是
> `calendar_reading.details_visible is True` 且 `entries` 从 6 掉到 5），
> 而不是要求网格消失。

**为什么现在仍不动手（与 §3 同一条理由，外加一条）：**
- 改的是 `classify` 在**所有 EVENT 帧**上的分支条件 —— 爆炸半径比前两次都大；
- 明晚有窗口，而这是**存活/效率**问题，不是安全问题；
- 不过离线验收素材已经完美：卡帧（应读到 除雪小分队 + 9000 余秒）、
  网格帧（必须**不**产生 active_event 记录）、巨熊页帧（必须不受影响）三张都在磁盘上。

**候选 C 的验收判据（离线先过）：**
- 以 `..._step_004_before_*.png` 为输入：必须产出一条带
  `display_name`（除雪小分队）与 `seconds_to_start ≈ 2天15:09:21` 的记录；
- 以同轮 step_003 的网格帧为输入：**不得**产生上述记录（否则网格会被误当详情）；
- `advertised_but_unread_activities` 必须**下降**（那一行被记账），且不再回升。

## 4e. ⚠ 上面那条"一行条件"的结论是**残缺的** —— 实测是**三个**阻塞点

`tools/probe_whether_a_card_identity_matches_the_row.py`（用真帧跑）给出：

| # | 阻塞点 | 实测 | 能否靠放宽一个门修好 |
|---|---|---|---|
| 1 | `ocr.py:1282` 的门要求网格**没被识别** | 卡帧 `calendar.recognized=True` ⇒ 整支不执行 | 能（改门） |
| 2 | `read_event_detail` 认不出这张卡 | 卡帧 **`recognized=False`** | 能（教它认这种卡） |
| 3 | **身份不稳定** | 见下 | **不能** |

**阻塞点 3 —— `_event_id` 把 OCR 文本做 sha1：**

```python
digest = hashlib.sha1(label.encode("utf-8")).hexdigest()[:10].upper()
return f"DISCOVERED_EVENT_{digest}"
```

于是**同一个活动**，因为 OCR 这一次读到多少字，会拿到**不同的持久 id** ——
而"卡盖住了一行"恰恰就是让标签被截断的原因：

```
grid '神秘藏宝室' -> DISCOVERED_EVENT_A33B0DC6E9
card '神秘藏'     -> DISCOVERED_EVENT_2AE3F69AE7   DIFFERENT

grid '旅途的收获' -> DISCOVERED_EVENT_2CED2A762E
card '旅途的'     -> DISCOVERED_EVENT_80FDBE61F5   DIFFERENT
```

两帧之间**5 个 id 里只有 2 个存活**（除雪、英雄集结；后者的标签恰好两帧读得一样）。

而**在册的债务正好是按网格帧的 id 记的**（`2CED2A762E` / `A33B0DC6E9` / `DC53E03FB8`）。
⇒ 在任何一个把标签读短的帧上取得的读数，记的是**债务从未听说过的 id**，
`advertised_but_unread_activities` **不可能下降**。

> **判据：只要身份是"OCR 文本的哈希"，它就随读取条件漂移；
> 而"读取条件"包括【有没有东西盖住它】。** 于是"点开一个覆盖物"这个动作
> **系统性地制造不匹配** —— 这不是靠放宽一个守卫能修的。

**因此修法不是一行条件，而是"发现式活动的身份如何得出"**：需要一个跨帧稳定的身份
（候选：日期窗口 + 行槽位，因为 `calendar_dates_raw` 在两帧上是稳定的，
而 `display_name` 不是）。这会改写已存 id 的含义，**必须单独设计、单独验收**，
不能在窗口期顺手做。

**顺带解释了另一个长期现象**：`calendar_scan_due` 长期为真、`DISCOVER_EVENT_CALENDAR`
反复被选中 —— 只要那条链的记账永久不可能匹配，扫描就永久到期。



## 5. 本轮**没有**改行为

`runtime.py`、`brain.py` 均未改动。本轮只新增了一个可复现的量具
（`tools/probe_the_model_only_navigation_retry.py`），把上一轮的命名修复与本文的判据分开记账。

## 6. 一处**未解释**的观察（登记为未结项，不要当作已解释）

step_003 的 episode 带着 `RESOLVER:CALENDAR_DETAIL_PANEL_ALREADY_VISIBLE`，
**但它自己的 before 帧读出来是 `details_visible=False`、`entries=6`** ——
也就是说这一帧上解析器**应该**能拿到点（事实上 verifier 跑了，`verifier_ok=false`）。

那么这个名字是怎么进到这一行的？两种可能，**都没验证**：

1. 该步在 tap **之后**又解析过一次（after 帧有面板），`_resolution_error` 被写上，
   而它随该步落账；
2. 或者落账读的是另一个时间点的 `_resolution_error`。

**在查清之前不要引用 step_003 的 `recognition_error` 作为"面板已可见"的证据** ——
真正的证据是它的 before 帧（`details_visible=False`）与 step_004 的帧（`True`）。
这一条会影响对"命名修复到底覆盖了哪些落账点"的判断。

---

## 7. 已实现：用**日期证据**跨过 id 漂移（本轮唯一改动的代码）

### 失败点定位到**两行**

| 位置 | 代码 | 后果 |
|---|---|---|
| `runtime.py:2424` | `candidates = [row for row in rows if row.get("event_id") == detail.get("event_id") ...]` | 卡自铸的 id 永不匹配 ⇒ 填不上 `matched_occurrence_key` ⇒ **verifier 读的就是这个键** ⇒ 步骤必失败 |
| `event_schedule.py:837` 一带 | 同上的 id 过滤（`_row_carrying_the_details_dates` 按 `event_id` 过滤行） | 库里也不记账 |

**而项目自己早已写下规则**（`_prior_calendar_row` 的注释）：

> 「**Date evidence is required when OCR changes an identifier.**」

我们的情形**正是** "OCR 改变了 identifier"。

### 改动（两处，均以"日期证据"为准，且都保留"唯一才认"）

1. `event_schedule.row_covering_the_details_window(reading, rows)`（新）
   —— 用**详情卡自己印的**日期（`preview_start_raw` / `activity_open_*` 等）与
   **未查看**且有 `tap_norm` 的行做**相交**；**恰好一行**才返回，否则 `None`。
   - 用**相交**而不是包含：卡印的是整段档期（`2026-10-13 00:00`–`2026-10-15 24:00`），
     而网格行只列它显示的那两天（`10/13`、`10/14`）；要求包含会拒掉**这张卡本身**。
   - 新正则 `_CALENDAR_YMD_RE` 特意**不要求日期后面有东西**：真机原始串是
     `2026-09-2800:00` 与 `2026-10-1124:00`（日期与时钟连在一起、无分隔）。
2. 两处调用：`event_schedule` 的 EVENT_DETAIL 分支（**仅当 `calendar_origin == "GRID_ENTRY"`**，
   即运行时已判定"这个详情来自网格浮层"，条带那条路不动）＋ `runtime.py:2422` 的归属补填。

### 与既有函数的分工（这是重点，不是重复实现）

| 函数 | 解决什么 | 过滤 `event_id` 吗 |
|---|---|---|
| `_row_carrying_the_details_dates` | **同一个 identifier** 的两种**日期推导** | **要**（它自己的 docstring 就是这样） |
| `row_covering_the_details_window`（新） | **同一个活动**的两个 **identifier** | **不要**（要了就等于没写） |

### 验收

```
tests/test_calendar_detail_attribution.py   12 passed
  新增 7 条：卡 id 不同但窗口覆盖 ⇒ 记账；记账要带上 occurrence_key（供 verifier 读）；
            两行都符合 ⇒ 什么都不记（不掷硬币）；卡没印日期 ⇒ 不记；
            已查看过的行不再是候选；没有 tap_norm 的行不算读过；真机原始串能解析

tools/probe_whether_a_card_detail_credits_the_row.py
  改前： debt ('DISCOVERED_EVENT_DC53E03FB8',) -> ('DISCOVERED_EVENT_DC53E03FB8',)  matched=None  exit 1
  改后： debt ('DISCOVERED_EVENT_DC53E03FB8',) -> ()                                matched='...|10/13|10/14'  exit 0
```

### 这个改动**不**做什么

- 不改 `_event_id` 的算法 ⇒ **不需要 id 迁移**，不存在"旧 id 与新 id 互不匹配"的迁移期风险。
- 不动 `ocr.py:1282` 那道门（阻塞点 1）与 `read_event_detail`（阻塞点 2）：
  它们决定"卡上的时间会不会被读出来"，与"这一行会不会被记账"是两件事。
  **本改动让记账能成功；卡的档期仍未被读**（那是下一步，且它的收益是"拿到排期"，不是"停循环"）。

### ⚠ 第一版回退**过宽**，被 A/B 抓到，并补上守卫

第一版的日期窗口回退**只**要求"恰好一行与窗口相交"，结果打破了这条既有测试：

```
tests/test_event_schedule.py::test_a_credit_is_refused_when_two_occurrences_of_one_event_are_uninspected
```

那条测试的细节是：同一活动（`ICEBOUND_TREASURE_TRAINING`）有**两个未查看的行**（`10/02` 与 `11/02`），
详情自印窗口是 `2026-10-0200:00`–`2026-10-0824:00`。我的相交规则命中第一行 ⇒ 记账了；
而规则说**必须什么都不记**。

**原因**：详情印的是**整段档期**（preview 全程），比"哪一次"粗 —— 它会跟**同一个活动的另一次**相撞。
边界就在**标识符有没有被改**：

| 情形 | `detail.event_id` 在行里找得到吗 | 该走哪条 |
|---|---|---|
| 同一 identifier 的两种日期推导 | **找得到** | 既有路径（`_row_carrying_the_details_dates`），**回退不许插手** |
| 同一活动的两个 identifier | **找不到** | 日期窗口回退 |

所以补上守卫 `id_is_known`：**只有当详情的 id 在行里一个都匹配不上时**，回退才允许运行。
（`runtime.py` 那一处同样加了。）

新增一条测试把守卫钉住：
`test_the_window_fallback_never_runs_when_the_id_already_matches_a_row`。
—— 这条测试**第一版也写错了**（没给 `matched_occurrence_key`），于是走到了既有的
"无 key + 有 event_id ⇒ 记第一行"那条路；补上"一个匹配不上的 key"之后才真正测到回退。

> **教训：A/B 的价值就在这里。** 我的回退看起来"已经够保守了"（唯一才认），
> 但"唯一"是按**窗口**算的，而项目的不掷硬币规则是按**活动**算的 —— 两把尺子不一样。

---

## 8. 阻塞点 2 已修，且**在生产里确认生效**；剩下的缺口是"窗口太粗"

### 改动

`event_calendar.read_event_detail` 的识别判据加一条：

```python
or (date_range is not None
    and _COUNTDOWN_RE.search(all_text) is not None
    and any(_candidate_title(text) for _, text in rows))
```

两侧都必需：**日期区间**（纯网格帧没有它 —— 这正是网格 `details_visible=False` 的原因）＋
**距开始/倒计时**（这个模块从不让一个光秃秃的日期区间变成时钟）。
**只用于识别，不用于取名** —— 取名仍走几何（`:1012-1052` 的"紧贴区间上方的标题"）。

### 读者自身的 A/B（同五张帧，只换这一个文件）

| 帧 | 加子句 | HEAD | |
|---|---|---|---|
| CARD（点击之后） | **True** `除雪小分队` | **False** | ← 唯一变化 |
| GRID（点击之前） | False | False | 不变 |
| BEAR 页 | True `巨熊行动` | True | 不变（注册名） |
| HUB 条带 | True `最强王国` | True | 不变（注册名） |
| STRIP 常规活动 | True `最强王国` | True | 不变（注册名） |

**只改变了一张帧，其余四张逐字不变** —— 这是当前素材能给的最强安全证据。

### 生产确认：**卡被认出来了**

`20261010_093019_922115` 那一轮 step 3 的 `verifier_evidence`：

```
expected_event_id   : DISCOVERED_EVENT_DC53E03FB8     ← 被点的那一行（取自 before 帧的日历）
actual_event_id     : DISCOVERED_EVENT_1C9F9BD8F5     ← 卡的 id，说明卡已被读成 detail
attributed_event_id : ""                              ← 归属没填上
detail_recognized   : true                            ← 阻塞点 2 修好了
```

**`detail_recognized: true` 与 `actual_event_id` 有值是生产证据**：以前这里是 false/空。

### 剩下那一步：卡的窗口**太粗**，唯一性规则正确地拒绝了

`row_covering_the_details_window` 要求**恰好一行**相交。按库里的行算：

| 行 | 日期 | 未查看 | 与卡的 10/13–10/15 相交 |
|---|---|---|---|
| 除雪 | 10/13, 10/14 | ✓ | **✓** |
| 专属装备铸炼 | 10/08 … 10/14 | ✓ | **✓** |
| 英雄集结（第二次） | 10/12, 10/13, 10/14 | ✓ | **✓** |
| 神秘藏宝室 | 10/09 … 10/11 | ✓ | ✗ |
| 旅途的收获 | 10/08 … 10/11 | ✓ | ✗ |
| 英雄集结（第一次） | 10/08 … 10/11 | ✗ 已查看 | ✗ |

**三行相交 ⇒ `len(candidates) != 1` ⇒ 拒绝**（按它自己的不掷硬币规则，这是**对的**）。

### 因此下一步的判别依据已经现成：**运行时自己点的那一行**

- 解析器 `EVENT_CALENDAR_NEXT_DETAIL` 在选行时**已经知道**它把 `tap_norm` 算在哪一行上
  （`calendar_next_entry` 返回的那一行）；把它（`occurrence_key`）记在 `self` 上即可。
- 而 **verifier 已经在用同一行**作为 `expected_event_id`（上面就是 `DC53E03FB8`）。
- 所以归属不必"从卡反推是哪一行"，可以"用点它的那一行"，并**加一道内容校验**：
  卡自印的窗口必须与该行日期相交（本次成立）。若不相交 ⇒ 拒绝，
  这样"点飞了"也不会记错账。

**这一步未实现**（它是一个新机制，需要自己的测试与 A/B）。本轮到此为止。
