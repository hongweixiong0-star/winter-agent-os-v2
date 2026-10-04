# 循环检测器：它拿到的从来不是那个事实

日期：2026-10-04
状态：**根因已定，判据已预登记，修复未实施**
影响面：全局（AUTO 主循环），非某一个技能

---

## 一、一句话

`LoopDetector` 的算术是对的，判据是对的，模块边界是对的。
它从上线到现在，在真实生产数据上**一次都没有触发过**——因为喂给它的
`progress` 字段，取自全系统唯一**没有**测量目标进度的那条路径。

同一批真实数据，只换这一个字段：

| 规则 | 回放步数 | 触发次数 | 形态 |
|---|---|---|---|
| A 今天线上用的规则（`progress_from_outcome(result)`） | 3963 | **0** | — |
| B 那一行自己已经算好的测量值（`goal_progress`） | 3963 | **191** | AAA 181 / SAME_ACTION_NO_PROGRESS 6 / ABAB 4 |

A 抓到而 B 漏掉的：**无**。B 严格更严更全。

复现脚本：`E:\无尽冬日智能体_panelperf_scratch\replay_loop_honest_progress.py`
（只读账本，不改生产，可直接重跑）。

---

## 二、机制：三道门，每道都关着

### 门 1 —— 检测器只在会话里跑

`winter_agent_v2` 里 `SessionEngine()` 只有**一个**调用点：`runtime.py:8302`，
在 `_run_goal_session` 内。`runtime.py` 对 `LoopDetector` / `LoopSignature` /
`loop_detector` 的引用数：**0**。

会话覆盖 8 个有 `GOAL_ROUTES` 路由的目标（`CLEAR_INTEL`、`AVOID_STAMINA_WASTE`、
`KEEP_TRAINING_PRODUCTIVE`、`KEEP_RESEARCH_PRODUCTIVE`、`MAIL_ROUTINE`、
`DAILY_ACTIVITY_TARGET`、`ALLIANCE_ROUTINE`、`CLAIM_EXPLORATION_IDLE`）。
**其余目标走 `runtime.py` 的普通原子路径，那条路径上根本没有检测器。**

实测：30MB 尾部窗口内，会话行 30 行 / 全部行 2101 行 = **1.4%**。
循环发生在另外 98.6% 上。

### 门 2 —— 会话里的 `progress` 是"结果"冒充"进度"

`session_engine.py:1093/1102`：

```python
declared = getattr(verdict, "progress", None)
...
progress=declared if declared is not None else progress_from_outcome(outcome),
```

`progress_from_outcome("SUCCESS") is True`。而全仓 **33** 处 `StepVerdict(` 构造，
**0** 处传了 `progress=`。

于是每一行会话的 `progress` 恒等于 `result`。实测会话行（30 行）：

| result | goal_progress |
|---|---|
| SUCCESS (7) | True 7 |
| FAILURE (23) | False 23 |

**没有任何一行是 SUCCESS + False。** 而 `no_progress_block` 要求
`all(s.progress is False)`。一个"每一步都成功"的循环，在检测器眼里是**诚实劳动**。

同一个错误在账本落盘处也写了一遍 —— `session_host.py:380`：

```python
# 注释原文："The session's own verdict is the progress statement for this step;
#            a step that ran and verified is progress, ..."
goal_progress=bool(str(getattr(report, "outcome", "")).upper() in ("SUCCESS", "PROGRESS")),
```

`StepVerdict.progress` 自己的 docstring 早就预言了这个案子（"每天领奖循环里每一次点击
都验证通过（`SUCCESS`），而 `goal_progress` 整圈都是 False"），只是没人给它赋过值。

### 门 3 —— 就算前两道都修好，主路径上仍然没有这个事实的**载体**

主路径的目标级事实**已经**在算，而且算得很干净 —— `runtime.py:9920-9946`：

```python
goal_progress_by_id = {
    attached_id: progress_moved(self._goal_meters, goals_after, attached_id)
    for attached_id in attached_goal_ids
}
progress = goal_progress_by_id.get(step_goal)
```

`progress_moved` 是三态 `bool | None`：`None` = 这一轮没观测到（不是"没进步"）。
刚打开的注释（9943-9945）就是同一条教训："验证器通过 = 动作落地了。这不等于**目标**
动了 —— 2026-09-18 有 58 步验证通过而体力一动不动。"

主路径的 `goal_progress` 分布（30MB 窗口，2071 行主路径行）：

| result | goal_progress | 行数 |
|---|---|---|
| SUCCESS | **False** | **1216** |
| SUCCESS | True | 416 |
| SUCCESS | None | 213 |
| FAILURE | False | 215 |

**58.7% 的"成功"没有推动目标。** 这就是循环的燃料，检测器一滴都没喝到。

---

## 三、代价：不是理论，是账

近 24h 窗口（3961 行，2026-10-03T04:24 → 2026-10-04T03:16）逐目标
`goal_progress` 分布：

| 目标 | 行数 | True | False | None |
|---|---|---|---|---|
| DISCOVER_QUICK_PANEL_TASKS | 534 | 325 | 1 | 208 |
| DISCOVER_EVENT_CALENDAR | 858 | 331 | 524 | 3 |
| CLAIM_EXPLORATION_IDLE | 102 | 23 | 79 | 0 |
| DAILY_ACTIVITY_TARGET | 75 | 7 | 68 | 0 |
| **HERO_RECRUIT_ADVANCED** | **171** | **0** | **171** | **0** |
| KEEP_TRAINING_PRODUCTIVE | 204 | 0 | 204 | 0 |
| KEEP_BUILDING_PRODUCTIVE | 306 | 0 | 306 | 0 |
| **CLEAR_INTEL** | **556** | **0** | **556** | **0** |
| AVOID_STAMINA_WASTE | 739 | 121 | 618 | 0 |
| SCROLL_QUICK_PANEL_TASKS | 79 | 0 | 68 | 11 |

`HERO_RECRUIT_ADVANCED`：**171 步连续 `goal_progress=False`，而 `result` 全是
SUCCESS。** 那是教科书的 `SAME_ACTION_NO_PROGRESS`，输入完美对齐检测器的判据
（每一步 `progress is False`），而检测器一次都没看见 —— 因为它不在那条路上。

回放判据 B 时，这个目标在 171 步里触发 **127 次**。

---

## 四、第二个缺陷：粗粒度补救被"周期性"打败

检测器之外还有一层更粗的补救，已经在线：`goal_utility.repeat_failure_penalty`，
`-60 · min(streak,3)/3`，由 `runtime.py:9928-9933` 维护：

```python
if attached_progress is True:   row.no_progress_streak = 0
elif attached_progress is False: row.no_progress_streak += 1
```

它在跑 —— 日志里看得见（`learning/control_panel/latest.log`）：

```
[utility] chose KEEP_BUILDING_PRODUCTIVE (480; repeat-failure -60.0, page-residency +40.0 ...)
[utility] chose SCROLL_QUICK_PANEL_TASKS (137; fairness +56.5, repeat-failure -60.0, ...)
[utility] chose HERO_RECRUIT_ADVANCED   (290; fairness +59.7, repeat-failure -60.0, ...)
```

但注意**同一条日志的另一半**：

```
[utility] chose DISCOVER_QUICK_PANEL_TASKS (300; page-residency +40.0 ...)   ← 无 repeat-failure
[utility] chose DISCOVER_QUICK_PANEL_TASKS (300; page-residency +40.0 ...)   ← 一轮里第三次
```

活跃角色的实时账本 `learning/roles/1063040265/goal_fairness.json`
（49 个目标，写入 2026-10-04T03:15）：

| 目标 | selected | no_progress_streak |
|---|---|---|
| CLEAR_INTEL | 1263 | **1142** |
| DISCOVER_QUICK_PANEL_TASKS | 829 | **0** |
| DISCOVER_EVENT_CALENDAR | 797 | **0** |
| AVOID_STAMINA_WASTE | 712 | 15 |
| KEEP_TRAINING_PRODUCTIVE | 564 | 329 |
| CLAIM_EXPLORATION_IDLE | 326 | **0** |
| KEEP_BUILDING_PRODUCTIVE | 261 | 174 |
| SCROLL_QUICK_PANEL_TASKS | 162 | 68 |
| DAILY_ACTIVITY_TARGET | 130 | **0** |
| HERO_RECRUIT_ADVANCED | 65 | 52 |

**四个 streak 为 0 的目标，恰好就是那几个刷屏的**（829 / 797 / 326 / 130 次被选中，
streak 全是 0）。机制没坏 —— 同一份账本里别的目标是 1142 / 329 / 174。

原因是 **streak 是"连续"量，而循环是"周期"量**：
看 `DISCOVER_QUICK_PANEL_TASKS` 的分布 325 True / 1 False / 208 None ——
它每轮真读到一个新行（一个 True），紧接着一堆 False，一个 True 就把计数器清零。
**一次相邻的进步，抵消二十次空转。** 惩罚看不见循环。

> 注：顶层 `learning/goal_fairness.json` 是**过期的**（3 个目标，`last_selected_at`
> 停在 2026-09-30）。实时账本在 `learning/roles/<role_id>/goal_fairness.json`
> （`runtime.py:1644`）。任何按顶层文件下的结论都会是错的 —— 这一条本身值得记。

---

## 五、由此确定的修复（两条，互不替代）

### 修复 A —— 把检测器接到主路径（收益最大，判据已验）

事实载体已经在那儿了：`runtime.py` 的回合循环在 9946 行已经有
`progress = progress_moved(...)`。

必须在**不新增第二套判据**的前提下做。`tests/test_loop_detector_boundary.py` 只钉了：
`loop_detector` 只许 import 标准库、`session_engine` 里
`"state.loop.observe("` 恰好 1 处、四个 adapter 不许出现
`LoopDetector|LoopSignature|RECOVERY_LADDER`。**它没有禁止 `runtime.py` 使用同一个
`LoopDetector`** —— 但"第二个 `observe` 调用点就是第二个'什么叫循环'的定义"这句
设计原话必须被尊重。

因此可接受的做法是**让主路径复用引擎的编排**，而不是复制梯子逻辑：
需要一个新的、把梯子落到主路径既有表面（`OPEN_HOME` 技能、`_yield_to_next_goal`、
重新下发同一技能）上的接缝。**这是一次设计，不是一次编辑。**

### 修复 B —— 让 `no_progress_streak` 记"率"而不是"连续"

周期性循环是 B 的对手。可选项：滑窗比（近 N 次里 False 的占比）、或 **True 只衰减
不清零**。必须保持 `None`（不可观测）不动 streak 的既有语义 ——
`progress_moved` 的 docstring 已经论证过为什么"观测不到"不是"没进步"。

### 已登记、但**不要**顺手改的

- `session_host.py:380` 的 `goal_progress = (outcome == SUCCESS)`。
  改成 `None` 会**降低** `no_progress_streak` 的爬升（会话行现在有 True/False，
  改成 None 就只剩"不动"），是一次有真实副作用的行为变更，必须跟修复 B 一起评估。
- 顶层 `learning/goal_fairness.json` 是否该删/加过期警告。先别动。

---

## 六、预登记判据（部署前写死，部署后照做）

1. **回放**：`replay_loop_honest_progress.py` 在修复后的树上，规则 A 的那一列必须不再是 0；
   且不得出现"B 抓到而 A 漏掉"之外的差异。
2. **`LOOP_FALSE_POSITIVE`**：回放里必须报告出来（B 现在 `LOOP_DETECTED 191 /
   LOOP_FALSE_POSITIVE 0`）。0 假阳性是一个需要被质疑的数字，不是一个可以庆祝的数字 ——
   模块 docstring 已经把 `SCROLL_QUICK_PANEL_TASKS` 记成它自己的假阳性案例
   （`dataset/truth_audit/loop_detector_20260930/`）。
3. **`LOOP_DEFERRED = 92/191` 太高**，要在真机上观察 `LOOP_LADDER_TOP` 是否长期停在
   `defer_goal`；若是，说明梯子在饱和而不是在恢复。
4. **主路径不得因此变慢**：`runtime.py` 的回合循环是热路径。登记
   `episode_write_ms` 与回合时长的前后对照（§17ms 的教训：改完要量，不要声称）。
5. **真机验收**：`HERO_RECRUIT_ADVANCED` 的连续 False 串（今天 171）必须显著变短。

---

## 七、下一步第一件事

按上面"修复 A"做一个设计（含新接缝的边界测试），并且**先只做回放**：
把 `runtime.py` 主循环的 `(page, skill, semantic_target, state_hash, outcome,
progress)` 六元组按线上真实顺序喂进一个 `LoopDetector`，只记录、不执行任何梯子，
跑一轮 AUTO，然后看它报了什么、有没有假阳性。
**先观测，再动作** —— 这与 `loop_detector` 自己的设计（先记录 timeline，再决定 rung）
是同一条纪律。
---

## 八、第二个仪器：真六元组回放（2026-10-04 补测，先观测再动作）

第七节把下一步定成"往 `runtime.py` 加一个只观测的影子探针"。**补测之后这一步不必做**，
理由是量出来的：账本里六元组本来就是齐全的。

### 8.1 为什么原来那个回放只能说"上界"

`replay_loop_honest_progress.py` 取不到 `semantic_target`（episode 行没有这个字段），
只能退到 `""`。而 `semantic_target` 是 `action_key` 的成员 —— 把同一个技能的每一次点击
塌成一个动作，只会**合并**区别，也就是只会把触发次数**抬高**。
所以它给出的数是上界，而**上界不能当结论用**。

### 8.2 补测：账本其实全都记着（最后 60 MB，3990 行）

| 六元组里的字段 | 从哪来 | 实测 |
|---|---|---|
| `page` | `state_after["page"]`（after 帧，与引擎同一选择） | 3990/3990 行都有 |
| `skill` | `skill` | ✓ |
| `semantic_target` | `action["target"]`（如 `QUICK_PANEL_ROW_HERO_RECRUIT`） | `control` 与它**逐行相同：不一致 0 行** |
| `state_hash` | `relevant_state_hash(state_after)`（只读 page/popup/march_used/march_max/normal_idle_slots） | ✓ |
| `outcome` | `result` | ✓ |
| `progress` | `goal_progress`（主路径已经算好的那个事实） | 3676/3990 = **92%** 有测量值 |

### 8.3 结论：污染量 = 0（量出来的，不是辩出来的）

| 跑法 | 触发次数 |
|---|---|
| A 今天的规则，目标栏造假 | **0** |
| A 今天的规则，真目标 | **0** |
| B 账本事实，目标栏造假（第一次那个数） | 172 |
| B 账本事实，真目标 | **172** |
| B 账本事实，真目标，每个角色一个检测器 | **172** |

**B 的 172 → 172 说明塌陷没有抬高任何东西。** 原因也看得见：AAA 用的 `key` 本来就含
`state_hash`，而真正在重复的那些步本来就是同一个目标；会被塌陷抬高的那个形态
（`SAME_ACTION_NO_PROGRESS`）本次只触发 2 次。

⇒ 第七节的"影子探针"**不必加**：它要回答的问题，离线已经能如实回答，
而给热路径加第二个 `observe` 调用点，正是设计原话要避免的"第二个'什么叫循环'的定义"。

### 8.4 两条新发现，都比原来的"0 假阳性"更值得记

**（一）`LOOP_FALSE_POSITIVE = 0` 是定义使然，不是测量结果。**
读 `_settle`：计数器只在**同一个动作**后来出现 progress 时才 +1；动作换掉只是"陈旧丢弃"
（docstring 写明：那样计会虚高）。所以"0"的准确含义是
**假阳性率未被测量**，而不是"没有假阳性"。独立探针给出两个桶：
172 次 claim 里 **106 次被后续"同动作且无进步"佐证**、**66 次从未被回答**。
把 66 当成假阳性是错的（它是"没人回答"），把它忽略也是错的（它是"没人回答"）。

**（二）`LOOP_DEFERRED = 92/172 = 53%`：梯子确实在饱和 —— 预登记判据 3 得到确认。**
原因在 `observe`：`_rung_index` 每重复一次同一个 `action_key` 就升一档，只有 progress 才清零。
HERO 那 172 步动作完全相同，所以到第 4 次检测时已经在 `defer_goal`。
⚠ **回放不执行任何一档**，所以它测的是"多早会被发现"，不是"最后会怎么收场" ——
这一点必须写在结论里，否则 92 会被读成"执行了 92 次补救动作"。

### 8.5 对"修复 A"的影响：不改变结论，但去掉一个前提

- 前提成立，而且更干净了：主路径被喂错的**只有 `progress` 这一个字段**；
  A 在真六元组上**仍然是 0**（三道门里，第三道是全部故事）。
  B 严格更全：**A 抓到的 B 全抓到；B 抓到的 A 一个都没抓到**。
- 但"修复 A"仍然是**一次设计**：需要一个新的接缝，把梯子落到主路径既有的表面上。
  补测只是说明 —— **这个接缝不必为了"观测"而先造一个影子调用点**。
- 仪器已经进树：`tools/replay_loop_main_path.py`（`--json` 可机读）。
  预登记判据 1 的"修复后规则 A 的那一列不得再是 0"，就用它量。

### 8.6 一个必须说清的边界

本次补测**没有**验证"检测到之后该怎么办"。它只回答了两个问题：
**该不该被发现**（该，172 次）与**会不会误伤**（假阳性率未测到，但不是 0 的证明）。
真要动手，先按 §8.5 把接缝设计出来，再谈梯子。
