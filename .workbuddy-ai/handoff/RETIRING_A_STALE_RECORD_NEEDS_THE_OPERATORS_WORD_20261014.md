# 「退役不再可复现的记录」这件事：影响面已量完，只差操作者一个词（2026-10-14）

> 第166轮我把"给台账加一个诚实的 outcome"写成建议但**没量影响面**。
> 本轮把它量完了。结论是：**改动很小（1 处机械 + 1 处真决定 + 1 处存在性断言 + 测试）**，
> 而且**它是操作者的职权**（有先例），不是我能代做的。

---

## 一、词表是封闭的：`ALL_OUTCOMES` 只有 8 个词

`winter_agent_v2/escalation_queue.py:366-369`：

```python
ALL_OUTCOMES: tuple[str, ...] = (
    CODE_CHANGED, TEST_PASS, VERSION_ACTIVATION_PENDING, REPLAY_PASS, LIVE_TRIED,
    LIVE_VERIFIED, OUTCOME_BLOCKED, NO_IMPROVEMENT,
)
```

里面**没有**任何一个词能表达"这条记录的前提已经不成立、而且没有任何 job 跑过"。
（`NO_IMPROVEMENT` 最接近，但它断言"某个 job 跑过并发现没有改进" —— 与事实相反。）

## 二、逐处量出来的影响面（每处都读到 file:line）

| # | 位置 | 加一个词会怎样 | 需要改吗 |
|---|---|---|---|
| 1 | `escalation_queue.py:366-369` `ALL_OUTCOMES` | 词表是封闭元组 | **要**（机械加一个） |
| 2 | `escalation_queue.py:343-350` `UNFINISHED_TRACE_STATES` / `UNFINISHED_TRACE_OUTCOMES` | 只含 `LIVE_TRIED, LIVE_VERIFIED` | **不用改** —— 新词自然**不在**里面，`unfinished_trace()` 会正确判"这条 trace 已结束"，允许同一能力再开新 job。**这是正确行为，不是巧合** |
| 3 | **`capability_bootstrap.py:3050-3054`** outcome → 知识校准的映射 | `LIVE_VERIFIED → confirm_from_live`；`("BLOCKED","NO_IMPROVEMENT","FAILED") → CALIBRATION_FAILED + "PRIOR_VS_LIVE_DIFF owed"`；其余走 `else` | ⚠️ **这一处是真决定** —— 退役一条记录**绝不能**把它的知识记成"校准失败"（那条记录的知识可能完全没问题）。新词必须显式走"**什么都不做**"的分支 |
| 4 | `capability_gate.py:349` `if record.outcome == LIVE_VERIFIED` | 只认 LIVE_VERIFIED | 不用改 |
| 5 | `capability_gate.py:378/390/406` 的提示语 | 会打印 `outcome {record.outcome or 'unknown'}` | 不用改，可读 |
| 6 | `tools/check_wiring.py:1652-1656` | 那条断言只检查五个**闸门常量存在** | **不用改**（存在性断言）；若想让新词也被钉住，才是可选加一条 |
| 7 | `tools/escalations.py:140-178` `--correct` | 接受 `--outcome`，fold 不做取值校验 | 不用改（加词后它就能诚实地用了） |
| 8 | `tests/test_escalation_queue.py` | 状态机的大测试套 | 要跑（有 `test_superseded_version.py`，名字接近但**语义不同**见下） |

⇒ 所以**只有第 3 处需要判断**，其余是机械的。

## 三、⚠️ 命名约束：`SUPERSEDED` 这个字**已经被占了**

`capability_bootstrap.py:824` 现在已经写：

```python
"outcome": "SUPERSEDED",
```

并在 `:941` 用 `str(g.get("outcome")) == "SUPERSEDED"` 读它 —— 但那是
**bootstrap 计划（plan）层面的"被新计划取代"**，与"台账里一条记录不再可复现"**不是同一件事**。

⇒ 若把队列的退役也叫 `SUPERSEDED`，**一个名字会有两个含义**（正是本项目反复吃过的那种坑）。
需要**另一个词**（例如 `NO_LONGER_REPRODUCIBLE`）。

## 四、为什么本轮**不**实现 —— 先例说这是操作者的职权

`escalation_queue.py:259-262` 的原文：

> "**The two rungs the operator added on 2026-09-18 evening** (§一/§八). Declared here,
> above ``ALL_STATES`` … — `VERSION_ACTIVE` / `REJOINED`"

⇒ **上一次往这套阶梯/词表里加东西的是操作者**。这与第156轮"改 `Episode` 字段"那次的判断**正好相反**，
而理由也是同一条尺子：

- 改 `Episode` 字段：**先例是同一个 dev agent 单独加过**（`WB-1002-11`），半径 = 一个字段 ⇒ **做了**。
- 加一个 outcome 词：**先例是操作者加的**，且它改的是**唯一台账的语义**与闸门 ⇒ **只交决定，不动手**。

（这与第157轮不动 P0 写入守卫是同一类判断。）

## 五、**零语义变更**、现在就能帮到操作者的一件事

闸门 `detail` 现在只报一句：

```
17 record(s) the device already proved are waiting on the queue
```

而实测这 17 条里 **11 条无法通过重跑消掉**（6 条前提已被证伪 + 3 条点名技能 0 次
+ 2 条 goal 从未跑）、**6 条要真机**。把这一行拆成两个数（"可复现的 Gap" / "不可复现的记录"）
**不改任何判定**，只是让操作者看到的东西是诚实的。**本轮也没有做** —— 它仍要动闸门那个函数，
按同一把尺子（改唯一闸门的输出语义）还是交给操作者过目更稳；但它的影响面**明显小于**加词。

## 六、交付给操作者的一句话

**要让主路线能动，需要的不是更多分析，而是两个决定：**
① 设备是否解锁（6 条要真机）；② 是否给台账加一个诚实的退役词（让 11 条不可复现的记录能被合法移出待办）。
**本文件把 ② 的影响面量到了 file:line，只差操作者给那个词命名。**

## 七、未做

没加 outcome 词、没改 `--correct`、没改 `preload_gate`、没退役任何记录、没动 `ALL_OUTCOMES`。
