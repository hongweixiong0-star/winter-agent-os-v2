# Bootstrap 闸门被 6 条「已经修好」的队列记录挡着（2026-10-14）

> 17 条待投递的「真实 Gap」里，**6 条所描述的前提已被生产数据证伪** —— 它们的 goal 在
> 记录归档**之后**确实开始记进展了。但队列没有「陈旧/作废」状态，`--correct` 又只能纠正
> **已有 outcome**，于是 Bootstrap 闸门（`reason=REAL_GAP_WAITING`）继续为空转的目标让路。

---

## 一、怎么撞上的

`tools/bootstrap_scan.py --status` 的闸门：

```
armed        : True  (MAIN_LOOP_P0_PASS)
GATE allowed : False  reason: REAL_GAP_WAITING
  detail     : 17 record(s) the device already proved are waiting on the queue
```

主闭环已经过了，预载却仍被拒。查这 17 条的来历，落到 `CapabilityGate`：
「连续 N 轮**每步 verifier 都过、但目标零进展**」→ 记
`deferral(source=NO_GOAL_PROGRESS, sig="<cap>|NO_GOAL_PROGRESS|<skill>")`，30 分钟重探一次。
这是一枚**设计好的死循环断路器**，不是 bug。

## 二、根因：这一类失败的一句话前提，是可被生产数据直接检验的

`NO_GOAL_PROGRESS` 的记录声称的是「**没有任何一部分在推进**」。这句话能被
`learning/episodes.jsonl` 直接证伪：只要该 goal 在工作**归档之后**的任一 episode 上
`goal_progress is True`，前提就不成立。

而 `CLEAR_INTEL` 这条根因**已经修好，并且在生产树里**：

| 证据 | 读数 |
|---|---|
| `goal_library.py:1370-1373` | 发现层把 `world.intel["untried_pins"]` 搬进 `evidence`（2026-10-03 那篇文档说"缺一次搬运"） |
| `goal_library.py:2854-2858` | `_observation_meter` 读它并返回 `-float(untried)` |
| 主树 vs pin 树 `goal_library.py` | **md5 相同** `5c67c930ccd8f58e0375cb59e8f5190b` ⇒ 修复确实在运行时 |
| 生产 episode 实测 | `CLEAR_INTEL` `goal_progress=True` **550 次**；修复前该文档实测 **2 次** |

## 三、17 条的分档（`tools/audit_escalation_premises.py`）

```
by premise : {'FALSIFIED_SINCE_FILING': 6, 'GOAL_NEVER_RAN': 2,
              'HOLDS_NEVER_ADVANCED': 3, 'RECOGNITION_CLAIM_NEEDS_A_FRAME': 6}
```

| 档 | 条数 | 含义 | 代表 |
|---|---:|---|---|
| `FALSIFIED_SINCE_FILING` | **6** | goal 在归档后开始记进展 ⇒ 前提不成立 | `CLEAR_INTEL`×2（550/3876）、`AVOID_STAMINA_WASTE`×1（681/2808）、`CLAIM_EXPLORATION_IDLE`×3（34/198） |
| `GOAL_NEVER_RAN` | 2 | goal 整个流里不存在 —— 卡在 deferral 闸门，从未跑过 | `LABYRINTH_DAILY`、`USE_FREE_ARENA_ATTEMPTS` |
| `HOLDS_NEVER_ADVANCED` | 3 | 全流零进展，前提**仍成立** | `KEEP_RESEARCH_PRODUCTIVE`(0/31)、`KEEP_TRAINING_PRODUCTIVE`(0/346)、`KEEP_MARCHES_PRODUCTIVE`(0/337) |
| `RECOGNITION_CLAIM_NEEDS_A_FRAME` | 6 | `*_NOT_PROVEN`：前提是"客户端画了什么读不出"，**进展测不了它** | `ALLY_GIFT_CLAIM_NOT_PROVEN`、`INTEL_MISSION_SELECTION_NOT_PROVEN` … |

**第一次跑这个审计时它把 6 条 `UNKNOWN_UI` 也判成了"已修好"** —— 因为它们和
`NO_GOAL_PROGRESS` 记录落在同一个 goal 上，而"目标有进展"对一条**识别**主张什么也没说。
这正是项目付过学费的"两个根因共用一个 reason"。工具已按 `failure_type` 分流，并用
`tests/test_escalation_premise_audit.py` 把这条边界钉住（4 项，全绿）。

## 四、为什么这一轮**没有**退役任何记录

- 队列的状态机里**没有** `SUPERSEDED` / `STALE`；`NEW` → 只有被 job 消费才离开。
- `tools/escalations.py --correct KEY --outcome … --reason …` 的语义是「纠正一个**已经存在**的
  outcome」；这 17 条是 `NEW`、**没有 outcome**，用它就是滥用通道。
- 退役一条真实 Gap 是**操作者/运维决策**，不是审计工具顺手能做的事。

⇒ 本轮只**报告**，并把判据固化成可复跑的工具，不碰队列。

## 五、顺带确认（**不修**，属于既有登记）

- `check_wiring` 仍报 3 条问题，其中 `proof: a no-progress signature needs a measured move…`
  是**字符串形状过时**，不是不变量缺失：行为都在
  （`PROOF_IS_GOAL_PROGRESS` 在 `escalation_queue.py:102`，门槛在 `:1748`），
  只是断言找的是 `row.get("goal_progress")`，而代码已改用 `fields.goal_progress`。
  **与既有笔记一致，故意不动。**
- 新增文件后 `check_wiring` 的 `dangling calls in tools/`、`tests/` 仍 **OK**。

## 六、未做 / 未裁定

- 没有退役任何队列记录，没有改 `escalation_queue` 状态机。
- `learning/runtime_snapshot.json` 写 `mode=AUTO`，而 `learning/MODE_STATE.json` 写
  `MANUAL` + `user_latch=true`（`stop_reason=manually_owned_by_workbuddy`）。**两处冲突，未裁定**，
  只登记。设备仍只由操作者能切回 AUTO。

---

## 七、这一轮量出来的更大的一件事：**这 17 条不是当前的失败清单**

给审计工具加了频次一列（`n_fail`）之后，结论变了性质。**最近两天（2026-10-10/11，5075 episode，`verifier_ok` 89.6%）的真实失败分布**是：

| failure_type | 近 2 天 | 在 17 条队列里？ |
|---|---:|---|
| `GIANT_BEAST_SEARCH_NOT_PROVEN` | **150** | **不在** |
| `BEAST_TARGET_SELECTION_NOT_PROVEN` | **135** | **不在** |
| `SEMANTIC_TARGET_NOT_VERIFIED` | 77 | 在（但它是**通用**桶，见下） |
| `SAFE_BACK_NOT_PROVEN` | 30 | 不在 |
| `EVENT_CALENDAR_DETAIL_NOT_PROVEN` | 23 | 不在 |

而 17 条里那 6 条 `UNKNOWN_UI` 记录，它们各自的 failure_type 在**整个 10436 条流**里只有
**1 / 1 / 1 / 0 / 0**（`SEMANTIC_TARGET_NOT_VERIFIED` 那条 292 是**通用桶**，属它的份额远小于此）。

⇒ **闸门被一批近乎零频的记录挡着，而真正的头号失败不在队列里。**
两项头号失败也**早已被 handoff 点名**（`01_CURRENT_TRUTH.md:246`、`03_NEXT_ACTION.md:1393` 写作
`CURRENT ROOT CAUSE`），且 `WB-1002-11` 已**证伪**它是识别缺陷：
"…no polar-terror card was drawn … the map had panned to an empty area … **The verifier's
`GIANT_BEAST_SEARCH_NOT_PROVEN` was truthful.**" ⇒ 它是环境/导航问题，不是识别缺口。

**顺带否证的一件事**：全史最大的那簇 `UNKNOWN_NAV:NOT_A_NAVIGATION_ACTION`（157 条）**已经修好**——
按天曲线 `10-05:21 / 10-06:3 / 10-07:3 / **10-08:126**（=被测量的那天）/ 10-10:1 / 10-11:3`，
`_prefer_the_cause` 已接线（`runtime.py:8876`、`:10155`）并有测试
（`tests/test_recognition_error_attribution.py`）。⇒ **不要**把它当成待修项重开。

⚠️ 口径：`n_fail` 数的是 `failure_type`；通用类型
（`SEMANTIC_TARGET_NOT_VERIFIED`）被很多技能共享，那些行的 `n_fail` 该读作**上界**。
