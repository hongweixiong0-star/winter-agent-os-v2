# 第三环的答案在知识库里：点它不是"导航"，是"没有安全流程"（2026-10-03 第十一轮）

> 上一轮把第三环确证为"没有任何机制去点横条上的欠债活动"。
> 本轮去查项目自己的知识库，**发现该活动早已被登记，而且登记里写明没有安全流程。**
> ⇒ 第三环的性质变了：**它不是"缺一个动作"，是"缺一整条活动专属流程"**。

---

## 一句话

`ALLIANCE_MOBILIZATION` 在 `knowledge/events/event_registry.json` 里已有条目：
入口 `ALLIANCE/EVENT` 已知、存在性 `CONFIRMED`（`knowledge/game/alliance.json`，confidence 0.88），
但 `unwired_steps` 明确写着 **"a safe event-specific flow are not connected"**，
`action` 是 `dynamic`、`verification` 要求 `event_task_state` 验证器 —— **而那个验证器没接。**

---

## 一、知识库已经说了什么（逐字）

`knowledge/events/event_registry.json` → `events[3]`：

```
event_id                 ALLIANCE_MOBILIZATION
name                     联盟总动员
entry                    ALLIANCE/EVENT
unwired_steps            ["production event identity, live timer, eligibility,
                           task-state verifier, and a safe event-specific flow
                           are not connected"]
observed_ui_labels       [{"text": "联盟总动员", "role": "navigation_tab_only", ...}]
participation_conditions ["the current client must identify the event and its task state",
                           "role eligibility and any costs must be read from the client"]
next_open_condition      {"source": "LIVE_CLIENT_REQUIRED",
                           "note": "no current client timer or occurrence has been recorded;
                                    read the event identity and timer before scheduling"}
prepare                  ["keep the candidate registered without guessed times",
                           "on a live encounter, capture the active role, timer, task state,
                            costs, and result before enabling actions"]
```

`knowledge/game/alliance.json` → `records[4]`：

```
{"id": "ALLIANCE_MOBILIZATION", "name": "联盟总动员",
 "entry": "ALLIANCE/EVENT", "page": "EVENT",
 "action": "dynamic", "verification": "event_task_state",
 "source": ["official_youtube_bear", "wosforge_main"],
 "confidence": 0.88, "status": "CONFIRMED"}
```

`observed_ui_labels[0].role = "navigation_tab_only"` —— 这一点特别重要：
**知识库早就标注了"联盟总动员在 UI 上只被观测为导航页签"**，
与本会话第十轮在真机上量到的事实完全一致（`tab_signature` 里的高亮项、h_ratio 0.0227 的小页签）。

---

## 二、这改变了什么

上一轮我把第三环描述成"缺一个点击动作"，隐含假设是"点它就像点峡谷会战那样是纯导航"。
**知识库否掉了这个假设**：

| | 峡谷会战 / 最强王国 | 联盟总动员 |
|---|---|---|
| 详情页是否已被观测 | 是（真机帧，两次） | **否**（545 帧全是"返回"） |
| `unwired_steps` | 无（已接通） | **"safe event-specific flow are not connected"** |
| 动作性质 | 纯导航 | **`dynamic`** |
| 需要验证 | 观察到即可记账 | **`event_task_state` 验证器（未接）** |
| 已知成本 | 无 | **`participation_conditions` 要求先读资格与成本** |

⇒ **点开它很可能不是"看一眼"，而是进入一个会消耗资源的流程。**
`prepare` 那句话是项目自己写的规矩：**"on a live encounter, capture the active role,
timer, task state, costs, and result before enabling actions"** ——
**先观测，再谈动作**，而"观测"本身就要先点开它。

**这是一个真·UNKNOWN，不是待接线。** 按宪法第 11 条，
它属于"已知页面出现新按钮/任务入口"型 UNKNOWN，需要的是**安全探索 + 记录**，
不是把它接进 `brain` 就完事。

---

## 三、由此得到的判断（与上一轮不同）

**不该做**：给 `brain` 加一条"若横条有欠债活动就点它"的分支。
那等于用一个未验证的假设（点开是纯导航）去驱动一个已知有成本的活动
（`participation_conditions` 明说要读资格与成本）。这会违反
"安全与活性必须分开"——为了收敛活锁而开出可能消耗的动作。

**该做**：把 `ALLIANCE_MOBILIZATION` 从"永远欠债"这条活锁里**摘出来**，但**不是删掉它**。
依据是它自己的 `prepare` 规矩与 `unwired_steps`：
**一个没有安全流程的活动，不该让整个日历扫描永远 due。**

具体形态待下一轮定，但方向已经清楚：把"**能不能安全地读它**"与"**它有没有被读**"分开，
就像第一环与第二环那样 —— 一个有界的、可回答的观察，而不是一个永假的条件。

---

## 四、本轮状态

- **零代码改动。** 生产 pin `291ede58`，AUTO 正常，`worker_exits` 19 未增长。
- 分支 `workbuddy/page-residency-20261003` = `bf1978f6`。
- credit 修复持续有效：`1061663148` 的 `read_entries_carried=1`，
  说明 `read_entries` 已经熬过一次 strip 重读（修复前会消失）。
- 上一两轮的诊断文档仍然有效：
  `DETAIL_PREDICATE_NEEDS_PAGE_IDENTITY_20261003.md`（第一环）、
  `READ_ENTRIES_HAS_NO_WRITER_20261003.md`（第二环 + credit 覆盖 bug）。
