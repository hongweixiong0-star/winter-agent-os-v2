# STILL_PENDING：为什么「先测量」这一步没有得出一个阈值，而是先修了记录

本文件是任务 #44（`STILL_PENDING 环路不受检测器覆盖（含无界缺陷）`）的测量与设计记录。
它同时**更正**了 `REPORT.md` Part 2 里两处过强的表述——那两处不是笔误，是同一件事的两个面。

任务要求：「改变前应先测『连续 STILL_PENDING 的分布』」。测量做了，并得出一个**阈值**；
但测量同时暴露了一件更基础的事：**这个分布无法从生产账本里测出来**，因为 outcome 根本没被
记录下来。所以本轮的产出顺序是「先修记录 → 再定界」，而不是「先定界」。

---

## 0. 快照与可复现性

账本是**活的**：本次会话期间它从 10,264 行长到 10,296 行（AUTO 在跑）。因此每个数字都带快照。

| 项 | 值 |
|---|---|
| 账本快照（审计时） | 10,272 行 `learning/episodes.jsonl` |
| 会话步 | 108（29 个会话） |
| 代码修订 | `dab79cf3ca514f5fc294c9db31efd7adfe04ac84` |
| 复现命令 | `python dataset/truth_audit/loop_detector_20260930/audit_outcome_persistence.py`<br>`python dataset/truth_audit/loop_detector_20260930/measure_still_pending_runs.py` |
| 产物 | `outcome_persistence_audit.json`、`still_pending_runs.json` |

两个脚本都是**自证的**：关于代码的断言直接对着磁盘上的源码断言（不是注释里的引用），
关于数据的断言对着账本断言。改动任一者，脚本会红，而不是安静地继续给一个旧结论。

---

## 1. 测量：run 长度分布与每个阈值的代价

判据：把 outcome 从 reason 反推（reason→outcome 的每一条都在脚本里标注了产出它的源码行）。
读数分两档，因为 `FISHING_RESULT_PENDING` 被 `session_adapters.py:538` 用**同一个字符串**
同时表达 `PROGRESS` 与 `STILL_PENDING`：

* **STRICT**：只算无歧义的 reason。
* **LOOSE**：把那个被重载的 reason 也算作 `STILL_PENDING`。

### 结果

**STRICT 读数是空的**：整个语料里**没有任何**无歧义的 `STILL_PENDING` 步
（`FISHING_WAITING_FOR_LEVEL` / `STAMINA_STILL_UNREADABLE` 出现 0 次）。
所以一切数字都只能建立在那个被重载的 reason 上——这本身就是一个结论。

**LOOSE 读数**：44 步 / 11 个 run / 11 个会话。

```
run 长度直方图： 1×1, 2×5, 4×1, 5×1, 8×3      （2 与 4 之间有缺口：没有 3、6、7）
最长 run      ： 8  == step_budget(10) − 2
run 的结局    ： 7 个 resolve（后面出现 FISHING_RESULT_LEFT）
                 4 个就是会话的最后一步（死在预算上）
```

### 阈值扫描——这是决策表

| N（连续多少步） | 触发会话 | 触发 run | 其中**本会 resolve** 的 | 误报率 | 放过的最大 run |
|---|---|---|---|---|---|
| 2 | 10 / 11 | 10 | **7** | 0.70 | 1 |
| 3 | 5 | 5 | 2 | 0.40 | 2 |
| 4 | 5 | 5 | 2 | 0.40 | 2 |
| 5 | 4 | 4 | 1 | 0.25 | 4 |
| **6** | **3** | **3** | **0** | **0.00** | 5 |
| 7 | 3 | 3 | 0 | 0.00 | 5 |
| 8 | 3 | 3 | 0 | 0.00 | 5 |

若按**步数**定界，本语料支持的唯一干净阈值是 **N ≥ 6**（零误报，恰好命中三个真卡死）。
N=2 会杀掉 10/11 个会话，其中 7 个本来会正常 resolve——这解释了 `session_engine.py:997`
把 `STILL_PENDING` 排除在检测器之外**为什么是对的**：它是一个必要的误报护栏。

### 但还有一个数字让「按步数定界」本身失效

```
run 内每步墙钟：中位数 0.0372 s
最长 run（8 步）总计：0.345 s
被它等待的那一步（FISHING_CONTROL_SESSION_RAN）：8 – 27 s
路线声明的 time_budget_s：150 s
```

**这个 run 只花了 0.345 秒。** 它不是「在等待」，它是一个 30 ms 的忙旋：
10 步预算是 0.3 秒烧完的，而 150 秒的**时间**预算从头到尾没被碰到。
所以「步数」在这里不是一个物理量——它与机器速度、与是否有 sleep 耦合，跨会话不可比较。

这直接给出 #44 的答案。

---

## 2. 为什么这个分布测不出来（两个更基础的事实）

**事实一：outcome 不是账本字段。** `_record_episode` 收下 `session_outcome`，只用它挑一个
`result`，然后丢掉。唯一保有真值的 `StepReport.outcome` 被 append 到
`session_host.step_reports`，而那个 list **只被写、从未被读**（`session_host.py:133` 声明、
`:333/:335` 追加，全仓库再无消费点）。审计断言：`step_reports_is_dead_accumulation = True`。

**事实二：`result` 这一列跨修订不可比。** `fa476b6`
（*fix(evidence): distinguish session progress from failed clicks*）之前，
`result` 对**所有**会话步写 `FAILURE`：

| | 会话步数 | 结果 |
|---|---|---|
| `fa476b6` 之前（5 个修订） | **60** | 60/60 全是 `FAILURE`-only |
| `fa476b6` 及之后（3 个修订） | 48 | 有真实的 `PROGRESS` / `SUCCESS` |

推论：任何混合了修订的 `result` 计数，量到的是**记录代码**，不是运行。

**交叉验证——仓库自己已经在报警，而那些报警全部早于修复：**

| 仓库自带的异常判据（源码位置） | pre-fix | post-fix |
|---|---|---|
| `VERIFIER_CONFLICT`：`verifier_ok=True` 且 `result=FAILURE`（`state_truth.py:1532`，面板上的实测信号） | **5** | **0** |
| `goal_progress=True` 且 `result=FAILURE` | **42** | **0** |

那 5 条 `VERIFIER_CONFLICT` **全是** `FISHING_CAST_VERIFIED`——adapter 明确返回 `SUCCESS`
的那一步。也就是说：面板上那个「verifier 过了但 result 说失败」的告警，完全是缺了
`fa476b6` 的产物，修复已经消掉了它。

**而 `fa476b6` 没有堵住的那个洞，今天还在：** 它的映射集合是 `{"PROGRESS","AMBIGUOUS"}`，
不含 `STILL_PENDING`，所以 `STILL_PENDING` 落到默认 `result="FAILURE"`。
在**当前修订** `6ba2ab5` / `014a4df` 上，28 步 `FISHING_RESULT_PENDING` 全部写作
`result=FAILURE` + `failure_type=NO_EXECUTION`。44 行把「钓还在水里」写成了「钓失败了」。

---

## 3. 设计答案（#44 的 (a) 与 (b)）

**(a) 要不要给 `STILL_PENDING` 一条独立命名的界？** 要，**但不挂在 `LOOP_DETECTED` 上。**
两种事实两种补救，混用会把一个指标变成两个意思：

* `LOOP_DETECTED` 的定义是「一个**被答复过的**动作没有改变任何东西」。
* `STILL_PENDING` 是「**还没有答复**」。

把后者喂进检测器，等于把「adapter 在忙旋」改名成「流程在环路」——`session_engine.py:997`
的注释已经反对这件事，而本节的数字证明它是对的（N=2 的误报率 0.70）。
检测器**已经**被四条业务线复用了：它看到四个 adapter 的每一个**被答复的**步。
钓鱼缺的不是检测器覆盖，是**一个真正的等待**。

**(b) 阈值取多少？** 本语料支持 **N ≥ 6**（零误报）。但更重要的是：
**这个界不应该按步数计，应该按「距上次被接受进展的墙钟时长」计。**
证据就是 0.345 s：同样是「6 步」，在 30 ms 自旋下是 0.2 秒，在一个 1 s 轮询下是 6 秒。
按步数定界会把机器的速度写进判据里。

---

## 4. 根因：不是没有界，是这个「等待」根本没有等

`session_engine.py:718-731` 里**已经有**一个带界的等待：`_wait_for_work`
会 `host.sleep()`（50–500 ms 递增）、有 deadline（`spec.max_wait_s`）、有租约检查、有具名终点，
并计入 `state.waits`。它只在 `choose_step` 返回 `None` 时才被走到。

而钓鱼 adapter 的 `choose_step` **从不返回 `None`**：它返回一个
`SessionStep(0, STEP_OBSERVE_ONLY, tags={"wait_result": True})`（`session_adapters.py:464-466`），
即「花一个预算步再看一眼」，**中间没有任何延迟**。

所以：等待的代价 = 每次 30 ms，10 步预算 = 0.3 秒烧完，而引擎自带的那个**会 sleep** 的
有界等待从未被走到。实测 `SESSION_WAITS = 0` 与此一致。

**由此产生一个可判定的假设：**

> **H1**：那三个死在预算上的会话不是「鱼一直没来」，而是「轮询只给了客户端 0.3 秒去渲染」。
> 7/11 个 run 在 1–5 次轮询（0.03–0.2 s）内就看到了结果，说明渲染在这些情况下早已完成；
> 而失败的三次里，`FISHING_RESULT_PENDING` 之后会话就死了——我们不知道渲染是 1 秒还是 5 秒。

**判定 H1 的实验**（一次真机即可，无需改代码）：在有结果页的那一竿之后，手工把轮询间隔改为
sleep 1 s，看第 2–10 次轮询是否出现结果页。
若出现 → 这不是环路问题，是**0.3 秒耐心问题**，修法是 adapter 的等待语义；
若不出现 → 才轮到讨论一条按时长计的 `STILL_PENDING` 界。

---

## 5. 本轮改了什么 / 刻意没改什么

**改了（纯记录层，零行为风险，让上面的度量成为可能）：**

| 文件 | 改动 |
|---|---|
| `winter_agent_v2/learning.py` | `Episode.session_outcome` 新字段（缺省 `""` = 不是会话步，不猜） |
| `winter_agent_v2/runtime.py` | 把 verdict 原样写进该列；`STILL_PENDING`/`AMBIGUOUS` → `result="INCOMPLETE"` 且清空 `failure`（什么都没失败）；`session_result` 暴露 `still_pending` |
| `winter_agent_v2/session_host.py` | 不再为「没有人判过」的步伪造 `verifier_ok=False`（该文件自己的 `verify_step` docstring 就是这么规定的） |
| `winter_agent_v2/session_engine.py` | `SessionState.still_pending` + 指标 `SESSION_STILL_PENDING`；不并入 `SESSION_STEPS`，也不并入 `loop_recoveries` |
| `tests/test_session_outcome_persistence.py` | 16 个新测试 |

**刻意没改：等待的时序。** 修法（sleep 多久）取决于 H1，而 H1 需要一次真机读数；
按项目纪律，影响真机行为、又还没有真机依据的改动不做。

---

## 6. 更正：`REPORT.md` Part 2 的两处过强表述

Part 2 用 `result` 反推 outcome，而当时不知道这一列跨修订不可比。更正如下：

**更正一：那 42 行不是运行的性质，是记录代码的性质。**
原文写「42 of the 105 steps 是 `result=FAILURE` 而 `goal_progress=true`（点击没验证过、
目标却前进了）……一个只喂 `result` 的检测器会把 42 次已证实的推进读成『无进展』」。
实测：**42/42 全部早于 `fa476b6`，post-fix 为 0**。它们不是「点击没验证过」，而是
`fa476b6` 之前 `result` 对所有会话步都写 `FAILURE`。这不是一个关于运行的发现。

**更正二：Part 2 的会话级检出数是反事实（counterfactual），不是观测。**
`LOOP_DETECTED 23 / LOOP_RECOVERED 2 / LOOP_DEFERRED 3` 回答的是
「假如这些步被当作 `FAILED` 喂进去，检测器会说什么」，而不是「检测器看到了什么」。
线上引擎对 `S5995DB6CE5` 只喂了 10 步里的 2 步，检出 **0**（Part 4 已如实记录）。
因此 `SA5E9B37CCF` 那张阶梯图不能读作「检测器在那里跑过」——它没跑过。
所以：**会话级回放的检出数不得计入四项指标**；历史 Episode 那一半的 CLI/流计数
（Part 1、Part 3、`revision_audit`、`live_detector_telemetry`）不受此更正影响。

**仍然成立的部分**：Part 1 的 10,253 行全流回放（那些是 goal-driven 步，不是会话步，
不经过这个映射）、Part 3 的 `AUTO_CONTINUED`（读的是运行自己的账本与流）、
Part 4 的真机负结果（读的是 `session_timeline.jsonl`，与 `result` 无关）。

---

## 7. 局限

1. 本文件的一切 `STILL_PENDING` 计数都建立在**一个被重载的 reason**上，因为语料里没有
   无歧义的样本；STRICT 读数是空的。修好记录（本轮已做）后的下一次运行才会有干净样本。
2. `step_budget` 是天花板，而撞到它的那次 run 在账本里**看不见**：
   预算是 `SessionResult` 层级的终点，`finish()` 不写 episode 行。
   所以「run 是被预算杀死的」这一条来自 `steps_after_run == 0` 的推断，不是直接读数。
3. 三个「死在预算上」的会话样本量是 3。足以否决 N=2，不足以把 N=6 当成定论。
4. H1 尚未在真机上判定。
