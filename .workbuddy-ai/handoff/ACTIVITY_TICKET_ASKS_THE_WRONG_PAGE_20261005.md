# 活动票问错了页面：`SCHEDULED_*` 卡在 UNKNOWN 的实测根因（2026-10-05）

> **本轮零代码改动。** 结论是"缺口在上一轮描述的位置之外"，而修复需要 0→1 的真机标定，
> 不是能顺手补的改动 —— 与 `STRIP_ALREADY_OPEN_20261003.md` 同一类收尾。
> 要点已进事实源：`.workbuddy-ai/memory/MEMORY.md` §88–§89、
> `.workbuddy-ai/memory/2026-10-05.md` §19。

---

## 一句话

**20 个 `SCHEDULED_*` 目标卡在 `UNKNOWN`，不是"缺一次真观测"，而是观测被尝试了 40 次、
每次都问错页面：票唯一的技能读日历网格，而那批活动活在「常规活动」枢纽的 tab 条里。**

`docs/CURRENT_STATE.md` 原话是"能力链是齐的，**缺的是一次真实观测**"—— 本轮实测推翻了它。

---

## 一、四组可复跑的实测数字

数据源都是 `learning/episodes.jsonl`（当时 10,374 步）。

| 观测 | 数字 |
|---|---|
| `READ_EVENT_CALENDAR` 执行次数 | **40** |
| 其中 `verifier_ok = False` | **40 / 40** |
| 那 40 次的 `verifier_evidence` | `calendar_recognized=false, visible_dates=[], entry_count=0`（40/40 逐字相同） |
| 那 40 次站的位置 | 每次都在 `events.regular_events_hub`（`calendar_tab_visible=false`） |
| 全历史有过**已识别日历**的 `SCHEDULED_*` 目标 | **0** |
| 活板上 20 张票里有 `calendar_observation` 的 | **6 / 20**（且这 6 张全部 `details_observed=True`） |

`event_goal.known_activities()` 的 17 个静态活动（`BEAR_HUNT`、`STATE_VS_STATE`、
`ARMAMENT_COMPETITION`、`CANYON_CLASH`、`ALLIANCE_MOBILIZATION` …）**一个都不在日历网格里**。
日历网格里是另一批：`冰封的宝藏` / `寻宝特训` / `秘宝商行` / `庆典对对碰` / `狮舞盛会` / `盛会商铺`。

---

## 二、票要问的东西住在哪 —— 枢纽 tab 条

全历史 `regular_events_hub.tab_signature` 的标签词频：

```
最强王国 1060 · 峡谷会战 867 · 兵工厂争夺战 574 · 佣兵荣耀 454
联盟总动员 273 · 军备竞演 47 · 士官计划 10
```

**这些正是那批静态活动。** 所以正确形态是走枢纽 tab 条：
滚动 → 按**活动名/别名**匹配 tab 标签 → 点它 → 读卡身。

---

## 三、两张真帧（都是真机实拍，不是推断）

1. **失败帧**（`READ_EVENT_CALENDAR` 的落点）
   `dataset/raw/control_panel/runtime_auto/20261004_232756_520045/…_step_009_after_refresh_2_20261004T152935384566.png`
   —— 标题 `常规活动`，tab 条 + `士官计划` 详情（`1天 00:30:25` / `我的排名：未上榜` /
   `我的积分：0` / 四档 `目标积分`）。**屏幕上没有日历。**
2. **成功帧**（到达网格）
   `dataset/raw/control_panel/runtime_auto/20261003_073827_567877/…_step_002_after_settle_retry_20261002T233854235592.png`
   —— **同一个 `常规活动` 页**，但选中 **日历** tab：7 个日期锚 `10/01…10/07` + 6 条活动。

⇒ **两帧是同一个页面的不同 tab** —— 这张对照就是"枢纽 vs 网格"的全部答案。

---

## 四、机制：为什么会"选得出、跑得动、永远不过"

- `_ACTIVITY_OBSERVATION_SKILLS = ("READ_EVENT_CALENDAR",)`（`goal_library.py:322`），
  票的 `available_skills` 只有它一个；
- 它的 verifier（`verifier.py:1946`）要求 `calendar.recognized` **且 ≥2 个不同的日期锚**
  **且 ≥1 条 entry** —— 即**日历网格**；
- 而 `READ_EVENT_CALENDAR` 自己声明在 `Page.EVENT` 上，**`Page.EVENT` 同时覆盖"枢纽"与"网格"
  两个子状态** ⇒ 站在枢纽上也满足"页面要求" ⇒ 技能被选中、被下发、必然失败。
- 票自己的 `required_observation` 写的是 *"this event's own page once opened"*，
  **而它唯一的技能读的是日历** —— 声明与手段自相矛盾。

这是 MASTER_RULES §0 反例清单里的 **"Verifier 永远不可达"**，也是 §20 说的
"UNKNOWN 的原因必须被解释"里被解释错了的那一类：这些票不是 `MISSING_OBSERVATION`
（能力链齐、也确实在跑），而是 **观测手段与目标页面不匹配**。

---

## 五、下一步（范围已收窄到**一个技能**）

要新增的是：**"在「常规活动」枢纽 tab 条上，按活动名/别名点中目标 tab，并读它的卡身"**。

- 已有零件：`regular_events_hub.tab_positions_norm`（坐标）、`tab_signature`（OCR 标签）、
  `read_regular_event_activity_strip`。
- **缺的是**：按标签定位并点击 —— 现成的 `OPEN_EVENT_CALENDAR_TAB` 只点**日历**那一个 tab，
  不能参数化到别的活动。⇒ 这是 0→1，需要真机标定。
- **必须先处理的陷阱**：OCR 把 `兵工厂争夺战` 读成 `兵工广争夺战`（574 vs 463）——
  按名字匹配 tab 前先归一化。
- **必须保持的分离**（`read_regular_event_activity_strip` 的既有约束）：
  卡身文字可以当**已读标记**，**不能**当 `start`/`end` ——
  "a preview must never become a battle clock"。

**在这些标定做完之前不要改代码。** 项目已经用代价记下过这条纪律
（`STRIP_ALREADY_OPEN_20261003.md` §七）：**"在没有落地观察过那个页面的情况下改代码"
是连续三轮改错方向的同一个根子。**

---

## 六、本轮踩到并已记入事实源的两个"拿成功率当观察"的错

1. 我看到 `SCROLL_REGULAR_EVENT_TABS` **349 次、`calendar_tab_visible` 从未变 True**，
   先写了"滚动无效"。实测 **`tab_signature` 349/349 都变了**，滚动后 `日历` tab 出现
   （全历史 `calendar_tab_visible=True` 966 次）。**"没成功" ≠ "没起作用"。**
2. 我写了"到不了日历"。实测 40 次**都到了 `Page.EVENT`**，只是另一个子状态。
   **"页面不对" ≠ "没到页面"。**

⇒ 判据：对任何"反复做同一件事"的技能，**先比 before/after 状态**，再看 verifier。
`before == after` 才是"没做事"；`before != after` 而 `verifier=False` 是"做了但没到终点"——
两者要修的函数完全不同。（`MEMORY.md` §89）

---

## 七、补完（同日）：verifier 是对的，缺陷是**两个子系统的边界不匹配**

第五节当时写"下一步是标定一个新技能"。**这一节推翻了它**——先做了两步判定，结论是
"换技能"这条路走不通。

### 7.1 重放判决：verifier 在它该跑的地方 100% 通过

`verify_event_calendar_read` 只读两个东西（`after.page`、`after.events["calendar"]`），
两者都被逐字记进 episode，所以可以直接重放（`_replay_event_calendar_read.py`，仓库根）：

```
captured frames carrying a recognized calendar: 979   (全部 page=EVENT)
verify_event_calendar_read PASSED on 979/979
那 40 次实际执行：40/40 站在 regular_events_hub
```

⇒ **verifier 正确、技能正确，缺陷纯粹是"位置"。** `READ_EVENT_CALENDAR` 从未在它被写下来的
状态上被评估过——40 次的 `verifier_evidence` 当然一直是 `calendar_recognized=false`。

### 7.2 但"换个技能"走不通：bootstrap 不允许那两种动作

那 40 次的驱动路径是 **`CAPABILITY_BOOTSTRAP:OBSERVATION_GAP`**（40/40，`PRODUCTION` 模式，
目标 `SCHEDULED_BEAR_HUNT`×32 / `SCHEDULED_STATE_VS_STATE`×8）——**capability bootstrap 按票声明的
`available_skills` 直接下发技能**，绕过了 brain 在枢纽帧上本来会做的选择
（`brain.py:671-680`：`OPEN_EVENT_CALENDAR_TAB` / `SCROLL_REGULAR_EVENT_TABS` / `SAFE_STOP`）。

而到网格恰好要用那两个技能，它们**不在发现动作集合里**：

```
_DISCOVERY_ACTIONS = {SELECT_TAB, CLOSE_POPUP, OPEN_PAGE, BACK, READ, SCROLL,
                      OPEN_KNOWN_PAGE, OBSERVE, READ_TIMER, READ_COUNTER, OPEN}

READ_EVENT_CALENDAR       kind=OBSERVE        ← 唯一准入的
SCROLL_REGULAR_EVENT_TABS kind=SWIPE          ← 不在集合里
OPEN_EVENT_CALENDAR_TAB   kind=TAP_SEMANTIC   ← 不在集合里
```

**所以这是一个边界决策，不是一个补丁。** 两条候选都是架构级（§3 要先做 Architecture Review）：

- **A**：让票在"其技能不可能通过的子状态"上**不被 bootstrap 观察路径驱动**，
  把这段走路的责任交回已存在、按页判定的 route/brain；
- **B**：把一种**不花钱的导航动作**放进发现集合 —— 那是在放宽一条被 `check_wiring`
  18 条断言钉住的安全边界。

### 7.3 完整因果链（下一轮直接用）

```
20 个 SCHEDULED_* 的 window 未知 ⇒ UNKNOWN
  ⇒ observation ticket，available_skills = ("READ_EVENT_CALENDAR",)
  ⇒ 票在 Page.EVENT 被选中，而 Page.EVENT 同时覆盖"枢纽"与"网格"
  ⇒ 站在枢纽：技能准入（OBSERVE ∈ 发现动作）但 verifier 不可能过（40/40）
  ⇒ 而"枢纽 → 网格"需要的动作（SWIPE / TAP_SEMANTIC）结构性不可作发现步
  ⇒ 零观测、零进展，20 个目标永久停在 UNKNOWN
```

### 7.4 第五节里被推翻的那句

第五节写"缺的是**标定一个新技能**"。**不准确**：缺的第一个东西不是新技能，
而是**决定这段走路归谁负责**（A 还是 B）。在新技能能被用上之前，那个边界必须先定。

---

## 八、A/B 的答案：**两个都不是**；20 张票拆成两类缺口（同日补完）

### 8.1 A 与 B 都不成立

```
calendar_scan_due('1063040265') = False          ← 那条走路今天被闸关着
calendar_scan_due('1061663148') = False
DISCOVER_EVENT_CALENDAR 不在 Goal 板上
advertised_but_unread_activities(两角色) = ()
今天(10-05) 落在 page EVENT 的 episode = 0
```

- **A 不成立**：把走路交回 route/brain 也没用 —— 那条路今天**根本没开**。
- **B 不够**：把 `SWIPE`/`TAP_SEMANTIC` 放进发现集合，只让票**能**走到网格；
  而 20 张票里 **14 张连日历行都没有**，走到网格也读不到它们。

### 8.2 缺的那一环：项目对"看得见、进不去"已经有名字

`event_schedule.py:417` `_unreachable_today()` 的整段注释就是操作者 2026-10-03 的观察：
`STATE_VS_STATE`（最强王国）**满了**，能在活动横条上看到、**永远进不去**；
账本实测它在 `activity_strip.entries` 里出现 **1109 次**、在 `read_entries` 里 **0 次**。
**这是真实的游戏状态，不是缺陷。** 项目也确实在记录那条横条
（`latest_calendar_snapshot(role, kind="ACTIVITY_STRIP")` 是独立的快照种类）。

⇒ **票的 `required_observation` 写的是"打开活动自己的页面"，而对"广告了但不让进"的活动，
这个观测在客户端上根本不存在。** 缺的不是能力，是**票看错了地方**。

### 8.3 分类表（本轮实量，两个角色）

| 类 | 个数 | Goal | 已记录的观测 | 真因 |
|---|---:|---|---|---|
| **A** | 6 | `ICEBOUND_TREASURE` / `_TRAINING` / `_MYSTERY_SHOP` / `DISCOVERED_EVENT_4178AC2F00` / `_BB2077C97D` / `_E1FB4AC23A` | 网格行 `details_observed=True` | 详情**读过了**，缺的是**窗口**字段 |
| **B** | 3 | `STATE_VS_STATE` / `CANYON_CLASH` / `ALLIANCE_MOBILIZATION` | 在 `read_entries` 里 | 详情**读过了**，票却还在要 `READ_EVENT_CALENDAR` |
| **C** | 11 | `BEAR_HUNT` `ARMAMENT_COMPETITION` `OFFICER_PROJECT` `DEFEAT_NEARBY_BEASTS` `BROTHERS_IN_ARMS` `FORTRESS_CONTEST` `ARMAMENT_FACTORY_EVENT` `UNDERGROUND_EXPLORATION` `FISHING_TOURNAMENT` `MOONLIGHT_FESTIVAL_SHOP` `EXCLUSIVE_GEAR_FORGE` | **无** | 从未被广告、也从未读过 ⇒ **真的没有观测** |

（网格各 6 行；横条各 1 行 = `STATE_VS_STATE`。
`read_entries`：`1063040265` = `[STATE_VS_STATE, CANYON_CLASH]`；
`1061663148` = `[CANYON_CLASH, ALLIANCE_MOBILIZATION, STATE_VS_STATE]`。）

### 8.4 下一轮：两类缺口，两条不同的路

- **A/B（9 张）= 数据链路修复，不是能力缺口。** 真值已经在库里
  （`details_observed` / `read_entries`），**票没消费它**，还在下发一次注定失败或多余的日历读取。
  这与 `CONSOLE_SHOWS_ONLY_MEASURED_NUMBERS_20261004` 是**同一族**（真值存在、链路没接）。
  **小、安全、可离线测**——上面这张表就是 fixture。**这半可以立刻动手。**
- **C（11 张）= 真覆盖缺口。** 它们从未出现在任何客户端读数里。
  下一个问题必须是"**这个客户端这一版到底有没有排期它们**"：
  没排期 ⇒ `UNKNOWN` 是诚实终态，`MISSING_OBSERVATION` 应换成具名的
  `NOT_ADVERTISED_BY_CLIENT`；有排期而没被读到，那才是要补的能力。

**⇒ "20 个目标卡在 UNKNOWN"从此不是一个"能力不够"的故事，而是两个各不相同的、
都有出口的问题。** 别再把它们当一个数字看。

---

## 九、两半各自结案（同日，接第八节）

### 9.1 A/B 那半**已修复并落地**：`d79f6f89`

`fix(events): an activity ticket whose own page is on file stops asking for it`。
**规则**：一张票，如果它要的那个页面**已经在案**
（网格行 `details_observed=True`，或角色的横条 `read_entries` 里有它），
就不再声明 `required_observation`、不再带技能，改为 `condition="waiting_window"`。

- **不是新词汇**：`waiting_window` 在本文件两百行前的联盟供应商就在用；
  能力投影把它映射成 `WAIT_UNTIL`（§55 自己的词表），任务板映射成 `EVENT_NOT_OPEN`。
- **最有力的证据**：`tests/test_event_calendar.py::test_new_calendar_activity_keeps_the_existing_generic_event_route_registered`
  **在改动前就是红的**（单独复跑该文件：`1 failed / 28 passed`），而它断言的正是
  "`details_observed=True` 的行 ⇒ `available_skills == ()`"。
  **项目早就把这条规则钉在测试里，代码漂移了、测试一直红着**；本改动把它恢复。
- **A/B**（21 个 event/goal/bootstrap 文件）：基线 **10 failed** vs 本改动 **9 failed**，
  差的**就是那一条**；其余 9 条（7 条 bootstrap integration + 2 条子失败）两侧完全相同 ⇒ **0 回归**。
  新测试文件**变异验证 10/10 全红**（旧源码下）。
- **生效**：运行时侧，**无需重启面板**；板子已改写为
  `availability_state=LIVE_DETAIL_ALREADY_OBSERVED / condition=waiting_window / skills=[]`
  （实测当时 20 张票里 8 张进入该状态，其余 12 张保持诚实的"待观测"）。

### 9.2 C 那半：按**搜索优先**规则结案 —— 那 11 个是**真实存在的循环活动**

操作者 2026-10-05 定下"不确定就搜"的规则。C 那半正是那个不确定的问题，于是**先搜**：

| 活动 | 排期（多源一致） |
|---|---|
| 巨熊行动 Bear Hunt | **每 2 天一次**（约 47–48h） |
| 堡垒争夺战 | **每周**（周五） |
| 联盟总动员 | 每周一至六，约每月一次 |
| 兵工厂争夺战 | 每 2 周一次，持续 7 天 |
| 最强王国 SVS | 每 4 周一次 |
| 峡谷会战 | 每 4 周一次 |
| 钓鱼锦标赛 | 每 4 周一次，持续 3 天 |
| 冰封的宝藏 | 持续 7 天，每代 2 期 |

来源自己注明：跨服活动**会浮动**、"不同区可能存在 10 天左右误差"、
**"always trust the in-game event timer"**。⇒ **排期是周期，不是窗口。**

**再查保留历史（离线）**：那 11 个 **grid / strip_read / detail 全为 0**；
`STATE_VS_STATE`/`CANYON_CLASH`/`ALLIANCE_MOBILIZATION` 只作为 `calendar_detail` 出现（345/343/90）。

**⇒ 关键**：`BEAR_HUNT` 每 2 天一次，**却在保留的 ~3 天里一次都没出现**。
所以对这 11 个，缺口**不是"时机没赶上"，而是没有一条能查到它们的路**
（票只能读日历；日历经实测到不了；即使到了，日历也只列**可见的那一周**）。
它们的 `UNKNOWN` 是**正确的"我们无法说"**（操作者 §二 明令不得编造活动时间），缺的是**观测手段**。

**风险边界**：周期**绝不能**写成 `start`/`end`——唯一合法用途是"安排下一次观察"。
**未知清单**：士官计划 / 讨伐附近野兽 / 兄弟连心 / 地下探索 / 月光庆典商店**没搜到排期**；
`ARMAMENT_COMPETITION` 的中英名映射不确定；国服与国际服排期是否一致不确定。
（五件产出完整版见 `MEMORY.md` §93。）

**最直接的下一个小缺口**：`knowledge/events/event_registry.json` 的 `cadence` **17 条里 15 条是 `UNKNOWN`**，
而外部资料给得出更多 —— **补的是"查找周期"，不是窗口**。

---

## 十、A/B 的第三个答案（提交 `a4c6301b`，同日）

§八留的是"A 交回 route/brain"还是"B 放宽发现动作集合"。**两条都不需要** —— 第三条路是：
**不改走路的归属，也不放宽边界，只改"这张票交不交那个动作"。**

**判据（可复跑）**：

```
9387 个已记录帧的 EVENT 子状态:  (日历识别, 枢纽识别)
     (False,False) 7724   (False,True) 1173   (True,False) 490      ← 互斥，从不共存
verify_event_calendar_read 在网格帧上重放: 979/979 PASS
READ_EVENT_CALENDAR 的 40 次生产执行:      40/40 站在枢纽上、40/40 失败
```

⇒ 那个 verifier **只在网格上可满足**，而票的技能会在任意 EVENT 帧被下发。
**交出一个在当前帧不可能通过的动作，就是 §0 禁止的"无限重试"。**

**修法**：`_frame_shows_calendar_grid(world)`；只在当前帧是网格时才带那个读。
**这是 §5，不是 §32** —— 票的状态、价格、`required_observation` 三种帧下**完全一致**
（测试断言 17 个注册活动在三种帧下都被发射），只改 ExecutionReadiness。

**生产实测**（板子 04:23:05 重写、`page=HOME`）：**20/20 张票 `available_skills=[]`**
（11 张 `AWAITING_LIVE_CLIENT_READING` + 9 张 `LIVE_DETAIL_ALREADY_OBSERVED`）。

**归因上的一条教训（值得记住）**：先做"回退源码"式变异，结果因**签名不符（`world=`）**而红 ——
**那是假阳性，不算验牙**。改成**保留签名、只把门改成恒真**的行为变异后，**恰好 3 条该红的红了**。
⇒ **变异必须保留签名、只改行为。** A/B（21 个既有文件）：基线 9 failed vs 本改动 9 failed ⇒ **0 回归**。

**诚实交代**：这一轮改的是**浪费与谎报**，**不是覆盖** ——
那 11 个目标仍停在 UNKNOWN，走路仍归 `DISCOVER_EVENT_CALENDAR` 且仍受 `calendar_scan_due` 约束。
**不要把 `a4c6301b` 说成"覆盖提升了"。**

---

## 十一、第三条（`80ca17aa`，纯数据）：**"解析不到" ≠ "没被广告"**

活动注册表**同时就是标签索引**（`event_goal._event_label_index()` 索引 `name + aliases`）。
客户端画得出、注册表没列的中文标题解析成 `None` ⇒ 读数落到**幽灵 id**。实测：

```
DISCOVERED_EVENT_C0BDCDE401   1027 次，display_name = 士官计划
      ← OFFICER_PROJECT 是**已注册**活动，因为标题解析不出来被当成"新发现的活动"
```

**⇒ 这更正了第八节的分类**：`SCHEDULED_OFFICER_PROJECT` 被列进"C 类：从未被广告"——**错**，
它被广告了 **1027 次**，全部记到垃圾目标上。同形还有 `兵工厂争夺战` 574 次横条读数
（注册表里那条叫 `兵工厂相关活动`）。

**修法**：三条**有来源**的别名，只动 `aliases`——`士官计划`→`OFFICER_PROJECT`（官方任务合集 +
WSCO 双周轮换）、`兵工厂争夺战`/`兵工广争夺战`→`ARMAMENT_FACTORY_EVENT`（官方百科页标题 +
实测 OCR 变体）、`堡垒争夺战`→`FORTRESS_CONTEST`（17173/7724）。
**不改 name、不动 `start`/`end`、不写 `cadence`、不增删目标**（§二：不编造窗口）。
跨活动冲突检查=无；聚焦组 23 文件改动前后**都是 9 failed** ⇒ 数据改动不动测试。
消费者全在运行时侧，**不需要重启面板**。

**教训（可复用）**：**判"从未出现"之前，必须先确认那些标签都能解析** ——
一个活动可以被广告几千次、却因为标签不在索引里一律记到垃圾 id 上，
于是统计看起来就是"从未出现"。**测到的可能是索引的缺口，而不是客户端的沉默。**

**GAP**：`佣兵荣耀`（Mercenary Glory）是**真实活动且注册表里根本没有它**
（官方百科：大熔炉 7 级、开服 11 天首开、持续 3 天、**间隔 2 周周六循环**，周五预告 1 天），
横条实测出现 **454 次**、`tab_positions_norm` 有坐标 —— 但没有注册项就永远记不到任何目标上。
**这是一条有完整来源的新增候选，留独立一轮。**
`DEFEAT_NEARBY_BEASTS` / `BROTHERS_IN_ARMS` 的中文标题**没搜到可信来源 ⇒ 不猜**。

---

## 十二、第四条（`968f66d9`）：`佣兵荣耀` 进入注册表 —— **搜索最大的价值是搜出了矛盾**

按新规则**先搜后写**。多源基本一致的部分：个人挑战（25 段）+ 联盟头目、**3 天**、
侦察 15 + 单打 10 体力（吉娜 4★ 减 2）、全清约 **625**（吉娜 **575**）/ 全集结约 **1000**、
开局送 **5 张佣兵召集令**（结束未用即清除）、奖励含大量**火晶**。

**但周期三源三值**：官方 CN 百科 **2 周**（周六开、周五预告 1 天）／17173 **3 周**／WSCO **4 周**，
**而且没有一个是客户端**。

⇒ **`cadence` 保持 `UNKNOWN`，冲突原文写进 `next_open_condition.note`——绝不挑一个填上。**
`start`/`end` 保持 `null`（文件自己的 `_read_me`："this project has never measured either one
for any event"）。`tasks: []` ⇒ **不绑技能、绝不授权任何尝试**（它花体力；零氪 +
"体力未知则 `OBSERVE_NO_SPEND`"）。**官方页未说明士兵是否损失 ⇒ 记为未知，不当成"不损失"。**

**验收**：注册票 **20 → 21**；`SCHEDULED_MERCENARY_GLORY` 发射为 `UNKNOWN` +
`required_observation` 有值 + **不带技能**（`a4c6301b` 的帧门生效），`route_for = EVENT`；
聚焦组 **25 个**文件仍是同样 9 条既有红 ⇒ 0 回归，**`test_every_goal_has_a_route` 通过**
（新 goal id 必过的守卫）；`MAINLINE_OK`；生产实测 21 张票、0 张带技能。

**未做**：只测到它是横条**标签**（454 次），**从未点开** ⇒ 别名解析是必要条件，
"点开它"仍是第十节那条边界。






