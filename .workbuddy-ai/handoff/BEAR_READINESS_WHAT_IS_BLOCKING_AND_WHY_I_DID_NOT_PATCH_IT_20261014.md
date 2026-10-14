# 巨熊准备度：**卡在哪、需要什么**（2026-10-14 复核）

> 操作者把它列为**最高优先级**（"巨熊活动准时参战"）。本轮把台账与代码逐条复核，
> 结论是：**这条链从未真正跑过；阻塞点已经被精确定位到两处；而它现在缺的东西不在代码里。**

---

## 一、硬事实：**`PARTICIPATE_BEAR` 一次都没被生成过**

`knowledge/events/bear_participation_chain_status.json#the_gap.evidence` （全流统计）：

| 量 | 值 |
|---|---:|
| `state_after` 含 `events.bear` 的记录 | **4**（窗口**确实被真机读到**） |
| `state_before` 含 `events.bear` 的记录 | **0** |
| 生成 `PARTICIPATE_BEAR` 的 episode | **0** |
| 跑过 `START_RALLY` 的 episode | **0** |
| 跑过 `JOIN_RALLY` 的 episode | **0** |
| episode 总数 | 10371 |

⇒ 台账把它归为一句准确的话：**"这是读数传递缺陷，不是运气。"**
（同时台账的 `not_the_cause` 明确排除了三样：reader 词表、加入机制（2026-09-27 真机已验证）、角色能力。）

## 二、阻塞点已被定位到两处（各有 file:line）

### ① `bear_trap_detail` 门**是为"还没开窗"建的**，窗口一开反而失效
`winter_agent_v2/ocr.py:1175-1184`（**本轮实测仍在**）：

```python
bear_trap_detail = (
    "狩猎陷阱" in exact_texts
    and any(marker in text for text in exact_texts
            for marker in ("前往", "距开始", "距离开始", "狩猎陷阱详情"))
)
```

台账 `the_real_shape_of_the_gate_problem.measured_truth` 的对照：
- `special_buildings.png`：**两个条件都满足**（有『狩猎陷阱』也有『前往』）⇒ 门能过；
- `bear_trap_detail.png` / `bear_trap_loaded.png`：**标签被 OCR 读坏**（`o将猎陷阱` / `io将猎陷阱`，
  精确匹配直接不成立），**且一个 marker 都没有** —— 因为**窗口开着时页面给的是『集结』而不是『前往』**
  ⇒ **门必不过**。

**次级问题**：`_explicit_start_seconds`（`ocr.py:820`）只认『距开始/距离开始』，
所以它**不会**把窗口内的 `00:13:54`（**到结束**）读成 `seconds_to_start`。
台账写明：**要做窗口内那一次，必须读成 `remaining_seconds`。**

### ② 排期那一半**没有生产读者**
台账 `the_wake_half_exists_and_has_no_feeder_20261010`：
唤醒字段（`event_schedule.RoleSchedule.reserved_start`）**存在、已接线、也被消费**，
但 `record_live_countdown` **全仓库只有一个调用点**（`runtime.py:5022`），
它的输入是**当前活动面板**印的倒计时 ⇒ **"巨熊印刷排期的那句话"没有任何生产读者**。

## 三、⚠️ 上一轮**明确拒绝**打这个补丁 —— 理由我同意，所以本轮也没动

台账 `why_i_did_not_patch_it` 原文：

> "把标签匹配改成宽容（例如按三字核心『猎陷阱』匹配）是我能写的最小改动，但
> **【手上没有任何一帧能证明补了它就会生效】**：那两帧的 marker 子句本来就不过。
> 在没有可证明的样本上改识别，正是本会话三次更正（`cc97315b` → `782823b4` → 更正到第一版诊断）
> 都源于的同一个错误。"

→ 这与本项目"先量再改"以及我本轮一直用的那把尺子**是同一条**。**所以本轮不改识别。**

**它需要什么（台账自己写的）**：**一次真机取帧，覆盖狩猎陷阱页的两个状态** ——
「开窗前」（应出现『前往』/『距开始』）与「窗口内」（应出现『集结』+ 到结束的倒计时）。
有了这两帧，**宽容匹配**与**`remaining_seconds` 读法**都能被证明或证伪。

## 四、于是"准时参战"现在缺的是**两件，都不在代码里**

| 缺什么 | 归谁 |
|---|---|
| **两帧真机**（开窗前 + 窗口内）—— ①的补丁在那之前都是猜 | **设备**（而设备锁在 MANUAL） |
| **窗口时间真的到点时 AUTO 在跑** —— 见第五节 | **操作者**（解除 MANUAL） |

台账也点名了下一个能力：**`READ_BEAR_TIMER`**（项目自己 `highest_leverage` 第 3 项，
同时卡着 `ALLIANCE_TIMED_EVENTS` 与 `PARTICIPATE_BEAR`），走**相对量** `remaining_seconds`，
比"常规活动"那条路便宜（后者仍卡在**为客户端声明时区**上）。**它的 `blocked_on` 写的就是：设备。**

## 五、一个可核验的"错过"：最近一次已知窗口落在 AUTO 停止之后

- 2026-10-10 的提交 `fc1c691f feat(bear): the bear schedule read live from the current client
  -- **2026-10-11 20:30**` ⇒ 最近一次已知窗口 = **10-11 20:30**；
- 而生产 episode 流的**最后一条是 2026-10-11T09:29:00**（10436 条，本轮实测），之后 `MODE_STATE`
  在 10-12 转 MANUAL。
⇒ **那个窗口落在"生产已停"之后，不是被门挡掉的。** 也就是说这条链有两个**互相独立**的阻塞：
**识别门**（要两帧）与**到点时真的在跑**（要操作者）。

## 六、未做

没改 `ocr.py` 的识别、没改 `_explicit_start_seconds`、没改 `record_live_countdown` 的接线、
没改 `event_schedule`、没动设备、没改任何预算（见台账另一节
`the_budget_that_has_no_run_boundary`，它的 `status` 是 `NOT_FIXED_NEEDS_OPERATOR_DECISION`）。
