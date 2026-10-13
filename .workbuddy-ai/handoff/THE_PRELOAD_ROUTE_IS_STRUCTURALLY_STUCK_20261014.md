# 预载主路线被**结构性卡住**：闸门要求"零待办"，而待办里有 5 条**永远无法被重新检验**（2026-10-14）

> 三处**实测**：闸门条件、`--correct` 的真实语义、17 条各自的"可行动性"。
> 合起来说明一件操作者需要知道的事：**主路线不会自己动**，而原因不是"没活干"。

---

## 一、闸门条件是**零待办**，不是阈值

`winter_agent_v2/capability_bootstrap.py:1133`：

```python
if pending_records > 0:
    return PreloadGate(False, GATE_REAL_GAP_WAITING,
                       f"{pending_records} record(s) the device already proved are waiting on the queue")
```

⇒ 只要有**一条**真机证实的 Gap 在等，预载就不派单。
所以 **"清掉 6 条陈旧的"不会打开闸门** —— 还剩 11 条。这一条把"退役陈旧记录"从
"高杠杆动作"降级为"诊断信息"。（我先前那轮把它当成最大杠杆，**这里更正**。）

## 二、`--correct` 的真实语义：**机制能做，词表不能说真话**

`tools/escalations.py:140-173`（实测读码）：

- 它 append 一个 `reconciled` 事件，字段 `job_state = q_state(record.state)`；
- 而 `q_state()`（`:176-178`）是 `"FAILED" if state == "FAILED" else "DONE"` ⇒ 对一条
  `NEW` 记录算出来是 **`"DONE"`**，而 fold 里 `job_state in (DONE, FAILED) ⇒ record.state = job_state`
  ⇒ **一条 `NEW` 会因此离开待办集**；
- 工具**明确预料到"本来没有 outcome"**（它打印 `was : {record.outcome or '(none)'}`）；
- 默认 outcome 是 `q.NO_IMPROVEMENT`。

⇒ **机制上，`--correct` 确实可以把一条 NEW 记录移出待办。**

**但词表里没有一个字是真的**：对所有可用的 outcome 常量，写下去都会断言
"某个 job 跑过并得到了这个结果"，而事实是**没有任何 job 跑过**。
⇒ 用它退役陈旧记录 = **往台账里写一句假话**，比留着更糟。

**结论（修正我在第151轮说过的"没有合法通道"）**：不是"没有通道"，
而是**通道存在、但缺一个诚实的词** —— 台账没有"已被取代 / 不再可复现"这个 outcome。

## 三、17 条逐条的可行动性（来自 `tools/audit_escalation_premises.py`）

| 档 | 条数 | 能不能靠"重跑"消掉 |
|---|---:|---|
| `FALSIFIED_SINCE_FILING` | 6 | **不能** —— 前提已被生产数据证伪（goal 归档后确实在进展） |
| `SKILL_NEVER_DISPATCHED` | 3 | **不能** —— 点名的技能在整个流里 0 次；其中 1 条还是**幽灵名字**（`skills.py:109` 记着"in no source file at all"） |
| `GOAL_NEVER_RAN` | 2 | **不能** —— goal 被卡在 deferral 闸门，从未跑过 |
| `HOLDS_NEVER_ADVANCED` | 3 | 能，但需要**先让那个 goal 真的推进**（要真机） |
| `RECOGNITION_CLAIM_NEEDS_A_FRAME` | 3 | 能，但需要**一帧真机** |

⇒ **17 条里有 11 条（6+3+2）无法通过"再跑一次"消掉**，它们描述的要么已经过去、要么永远不会发生。
剩下 6 条要真机。

## 四、于是主路线的真实状态

```
预载闸门：pending > 0 ⇒ 不派单        （零容忍，非阈值）
待办：17 条
其中 11 条：不能被重跑消掉
其中 6 条：需要真机 —— 而设备锁在 MANUAL
```

⇒ **主路线不会自己动。** 它在等的是**操作者**，不是"更多离线分析"。
继续读账本不会让它前进 —— 这本身就是本轮最该写下来的结论。

## 五、建议（**设计决定，本轮没动手**）

按 §三·八 的形状（**一条局部规则正在让整条线不流动**），真正该改的是两处之一：

1. **给台账加一个诚实的 outcome/state**（例如 `SUPERSEDED` / `NO_LONGER_REPRODUCIBLE`），
   让"这条记录的前提已经不成立"能被如实写下；并让 `preload_gate` 能把
   "**欠着一条真实 Gap**"与"**留着一条再也无法被检验的记录**"区分开。
2. 或者，至少让闸门的 `detail` 把"可复现的 Gap"与"不可复现的记录"分开计数 ——
   现在操作者看到的只有一句 `17 record(s)`。

**本轮没有做这两件**：它们改的是**唯一台账**与**闸门语义**，属于要被单独审阅的一类；
而且第161/164 轮的教训是 —— **改之前先量**，这里还没量"哪些 outcome 会被下游消费"。

## 六、未做

没退役任何记录、没改 `--correct`、没改 `preload_gate`、没改任何 outcome 常量、
没动 pin 之外的任何东西。
