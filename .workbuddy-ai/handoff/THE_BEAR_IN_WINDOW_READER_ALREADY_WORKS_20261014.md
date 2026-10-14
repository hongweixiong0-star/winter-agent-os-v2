# ⚠️ 更正：巨熊**窗口内的识别早就做好了，而且我刚在真机帧上跑通**（2026-10-14）

> 我在这之前的三轮里（第171/172/174轮）反复把"**窗口一开认不出**"当成巨熊的主要阻塞，
> 并说"修法可以写、只是缺一帧"。**这个框架是错的。**
> 本轮实测：`rally.read_bear_popup_countdown` **已经存在、页无关、并且在这帧上跑通** ——
> `remaining_seconds=834` → `bear_phase(...) = **ACTIVE**`。
> 那条链**不需要**经过 `ocr.py` 的 `bear_trap_detail` 门。

---

## 一、实测（当前代码 × 项目自己的帧）

```
bear_trap_detail.png   popup={'event_id': 'BEAR_HUNT', 'name': '巨熊行动',
                              'remaining_seconds': 834, 'source': 'LIVE_CLIENT_BEAR_POPUP_COUNTDOWN'}
     bear_phase(None, None, 834) = BearPhase.ACTIVE          ← 成了
bear_trap_loaded.png   popup=None    ← 它的表被读坏（`剩余时间：00：142`）⇒ 读者**拒绝回答**而不是编数
special_buildings.png  popup=None    ← 开窗前，正确地不回答
bear_rally_panel.png   popup=None    ← 集结面板，正确地不回答
```

## 二、那条链是**现成的**（`ocr.py:1381-1393` + `rally.py:758-803`）

`ocr.py` 里写着：

```python
# The map's 巨熊 popup is the OPEN window: it draws 等级N变异巨熊 and 剩余时间：HH:MM:SS.
# 剩余时间 is a duration, so this reading needs no timezone, and rally.bear_phase
# answers ACTIVE for any positive remainder -- which is what puts PARTICIPATE_BEAR on the
# board READY with JOIN_RALLY instead of leaving the window unread.
# Page-independent on purpose -- the popup is drawn over the map, not on the alliance page
from .rally import read_bear_popup_countdown
popup = read_bear_popup_countdown(eligible)
if popup is not None:
    events["bear"] = {**(events["bear"] ...), **popup}
```

而 `rally.read_bear_popup_countdown`（`rally.py:758-798`）：
- **两半都必需**：`identity`（token 里有 变异巨熊/巨熊）+ `clock`（有 `剩余时间` **且** 完整 `HH:MM:SS`）；
- **docstring 明写它 2026-10-10 就是在 `bear_trap_detail.png` 上量的**
  （`等级1变异巨熊` 0.999、`剩余时间：00:13:54` 0.930）；
- 并明写"**`goal_library` 已经读 `world.events.bear.remaining_seconds`** —— 所以这一个数就是把
  一个看得见的窗口变成 **READY + JOIN_RALLY** 的 `PARTICIPATE_BEAR` 的东西"。

⇒ **所以"窗口内那次"不是缺的、不是要新写的、也不是"只差一帧"** —— 它**实现于 2026-10-10，并在同一帧上量过**。

## 三、我要更正的三件事

| 我在第171/172/174轮说的 | 实际 |
|---|---|
| "`ocr.py:1175` 那道门是阻塞" | 那道门服务的是**联盟页那条路**（开窗前的 `seconds_to_start`）。**窗口内走的是另一条路**（`read_bear_popup_countdown`，**页无关**）⇒ 门在窗口内不过**不是阻塞** |
| "台账 `the_gate_is_built_for_the_wrong_state_20261010` 是当前诊断" | **被同一天（10-10）的 `read_bear_popup_countdown` 取代了** —— 那份小节记的是"门形状不对"，而绕开门的读者当天就写了并在同一帧上量了 |
| "修法可以写、可用这两帧回放" | **修法 2026-10-10 就写好了**；我这一轮只是**复现了它成功** |

**错在哪（值得记）**：我**从台账的一节出发**（`the_gate_is_built_for_the_wrong_state`），
把那节当成当前诊断，**没有先问"这一节之后有没有人已经绕开它"**。
同一份台账的**另一节**（`next_capability: READ_BEAR_TIMER`）说的正是这件事，
而它的 `blocked_on: 设备` 我照抄了 —— 却没去**读代码确认它是否已经实现**。

## 四、那么巨熊**现在**真正的阻塞是什么（照本文件能证的写）

1. **排期/唤醒那一半**：台账 `the_wake_half_exists_and_has_no_feeder_20261010` 记着
   `record_live_countdown` 全仓库只有一个调用点（`runtime.py:5022`），输入是**当前活动面板**的倒计时
   ⇒ **"巨熊印刷排期的那句话"没有生产读者**。**这一条本轮没有复核**（仍是台账的说法）。
2. **真机确认**：以上全部是**离线复现**（2026-09-09 的帧）。要证明**当前**客户端仍然如此，需要一帧新捕获。

**本轮没有说**：排期那一半就是唯一阻塞（我没有复核它），也没有说巨熊可以准时参战了。

## 五、未做

没改任何代码（本轮不需要 —— 那条链已经存在）、没改 `ocr.py`、没改 `rally.py`、
没改 `event_schedule`、没接线、没动设备。
