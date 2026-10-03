# 活锁的真正形状：日历目标赢麻了，但没人告诉它"该读哪一个"（2026-10-03 第九轮）

> 前两轮补上了两环（识别 `aab0dbb8`、记账 `a70db034`），真机确认链已闭环。
> 本轮量到第三件事：**闭环了也不会收敛**，因为没有任何机制让 V2 去读某个特定活动。

---

## 一句话

`DISCOVER_EVENT_CALENDAR` 在 HOME/MAP 上以 `base=1000` **压倒性获胜**（247 次全部如此，
第二名只有 300–480），而它每次获胜做的事是"去 EVENT 打开日历"——
**读不读某个欠债活动，完全不由这个决策决定**。所以债务会一直挂着。

---

## 一、前两环确实闭环了（真机证据）

`a70db034` 部署后，角色 `1061663148`：

```
strip entries      = ['CANYON_CLASH', 'STATE_VS_STATE', 'ALLIANCE_MOBILIZATION']
strip read_entries = ['CANYON_CLASH']        ← 记账链在生产上写进去了
EVENT_DETAIL       = CANYON_CLASH  credited=CANYON_CLASH  at 06:46:53
欠债 = ('ALLIANCE_MOBILIZATION', 'STATE_VS_STATE')   ← 从 3 个降到 2 个
```

`ALLIANCE_MOBILIZATION` 是**真实条目**，不是噪声：

```
{"event_id": "ALLIANCE_MOBILIZATION", "display_name": "联盟总动员",
 "title_confidence": 0.999234, "title_registered": true,
 "tap_norm": [0.775, 0.1332], "start": null, "end": null, "preview_only": true}
```

有 0.999 的置信度和真实的点击位置 ⇒ 债务是真实的，客户端确实宣告了它。

---

## 二、新发现：闭环了也不会收敛

决策日志（最近 5 次日历目标被选）：

```
page=HOME  CAL: base=1000  total=960  repeat_failure=-40   | top3: CAL 960.0 / 建筑 480.0 / CLEAR_INTEL 466.7
page=HOME  CAL: base=1000  total=980  repeat_failure=-20   | top3: CAL 980.0 / 面板 352.9 / 探索 166.8
page=HOME  CAL: base=1000  total=1000 repeat_failure=0     | top3: CAL 1000.0 / 面板 353.0 / 探索 166.8
page=HOME  CAL: base=1000  total=940  repeat_failure=-60   | top3: CAL 940.0 / 面板 300.0 / 探索 185.3
```

**被选 247 次，全部在 MAP(137)/HOME(110) 上发生。**

两个事实合起来构成问题：

1. **它不是抢不过，是压倒性获胜。** `base=1000` vs 第二名 300–480，
   连 `repeat_failure=-60` 都压不下去（940 仍然第一）。
2. **它获胜后做的事与"哪个活动欠债"无关。** 它发的是
   `OPEN_EVENT_CALENDAR_FROM_HOME` / `_FROM_MAP` —— 即"去 EVENT 打开日历"，
   然后由 `brain` 在 EVENT 上决定下一步。而 `brain` 在 EVENT 上看到的是
   `regular_events_hub` 或 `CALENDAR_GRID`，**它不会去点横条上某个具体活动**。

⇒ **欠债的 `ALLIANCE_MOBILIZATION` / `STATE_VS_STATE` 没有任何路径会被主动读**
⇒ `advertised_but_unread_activities` 永远非空
⇒ `calendar_scan_due` 永远 True
⇒ 活锁还在，只是现在它的成因从"两环都断"变成了"**第三环断：没有指定读哪一个**"。

---

## 三、为什么之前没看到

前两轮的判据都是"**读到之后**有没有被记账"，两环都通过了。
**没有任何一轮问过"那个欠债的活动会不会被读到"** ——
这与本会话早先那次"看形状不看分母"是同一类错误：
量了链子上的环节，**没量链条的驱动力**。

判据本该是：**债务要清空，需要每个欠债活动各被读一次**。
这个"一次"由谁保证，至今无人回答。

---

## 四、下一步（先量，不先改）

`STATE_VS_STATE` 与 `CANYON_CLASH` 的详情页**都已经被读到过**
（`EVENT_DETAIL` 记录过 `STATE_VS_STATE`，06:36:33）。
所以"能不能读到"不是能力问题，**是"会不会去读"**。

要查清三件事，都只能先看：

1. **`ALLIANCE_MOBILIZATION` 的详情页在客户端上怎么进？**
   横条 `tap_norm=[0.775, 0.133]` 就在那 ⇒ 大概是点它。
   但**点它是纯导航吗**（会切到该活动页），还是可能触发报名/领奖？
   —— 与峡谷会战同样的问题，而那个问题当时的答案是"进入是纯导航，页面上有 `商店`/`编队` 可消费"。
2. **有没有现成的横条点击动作？** `skills.py` / `verifier.py` 里
   上一轮查过：**没有**。
3. **如果点了，谁决定点哪个？** 现在 `brain` 在 EVENT 上没有"还欠着谁"这个输入，
   `regular_events_hub` 里也没有 `read_entries` ⇒ 需要把债务传到决策处，
   而**不能**让 brain 自己去读一个 JSON（那是第二份真值）。

### 三点里第 2 点已量化：`tap_norm` 一直被读、从未被用

```
全量 10061 步中，点在横条带（y_norm 0.06–0.20）的步数 = 0
```

而两个活动**确实被"读过"**——但原因是**客户端当时恰好停在那页**，不是 V2 点开的：

```
1061663148  CANYON_CLASH           tap_norm=[0.174, 0.184]   已读（被路过）
1061663148  STATE_VS_STATE         tap_norm=[0.223, 0.134]   未读
1061663148  ALLIANCE_MOBILIZATION  tap_norm=[0.775, 0.133]   未读
1063040265  STATE_VS_STATE         tap_norm=[0.181, 0.189]   已读（被路过）
1063040265  CANYON_CLASH           tap_norm=[0.742, 0.134]   未读
```

注意同一角色下 `CANYON_CLASH` 与 `STATE_VS_STATE` 的 `tap_norm` **x 相差很大**
（0.174 vs 0.223）——**横条的顺序会随页面状态变化**，所以任何"点第一个"或"点最左"
的规则都会点错。必须由事件身份驱动，而不是位置或次序。

**这解释了为什么前两轮的真机验收是"被路过"而不是"主动读"**：
记账链闭环了，但触发它的是客户端的停留，不是 V2 的选择。

**在这三问有答案之前不要写代码。** 这是本会话连续四轮"先看再改"守下的规则，
至今它是对的：前三次没守的时候，改的三个方向全错。

---

## 五、本轮状态

- **零代码改动。**
- 生产 pin `a70db034`，AUTO 正常，`worker_exits` 19 未增长。
- 分支 `workbuddy/page-residency-20261003` = `262fab6b`。
- 前两环的真机验收已写入
  `READ_ENTRIES_HAS_NO_WRITER_20261003.md` 与 `DETAIL_PREDICATE_NEEDS_PAGE_IDENTITY_20261003.md`。
