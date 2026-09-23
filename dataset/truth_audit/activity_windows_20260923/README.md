# 任务存在性、活动窗口与执行资格 —— 2026-09-23

操作者指令：**先判断任务是否存在及当前是否具备执行条件，再对真正可执行的任务排序。**

这一份回答指令要求的五个问题，全部来自磁盘上的产物与代码。可复算的一条命令：

```
python tools/measure_activity_windows.py --out dataset/truth_audit/activity_windows_20260923
python learning/_probe_existence.py                 # 只用真 GoalLibrary 量存在性与状态
python tools/measure_red_dot_gating.py              # 无红点巡检的 before/after
```

---

## Q1 任务存在性与执行资格在哪一层被混淆

**层：`GoalLibrary.discover`（`winter_agent_v2/goal_library.py`）。而且是同一个地方、
两个相反方向的错误。**

**(a) 存在性只从当前帧读出来。** `world.events` 全项目只有**一处**写入（`ocr.py`，
写的是当前页面印出来的东西），而 `PARTICIPATE_BEAR` / `EVENT_MINIMUM_GUARANTEE` 只在
那个字段有值时才会被生成。

实测（7200 条 episode 以上的正式语料）：

| 读数 | 数量 |
|---|---|
| 有任何 `events` 读数的步骤 | **4** |
| 其中带 `bear` 的 | **0** |

⇒ **"我没站在印它的那一屏" 和 "这个任务不存在" 是同一个世界状态。** 于是没有任何东西
可供提前准备，没有可等待的对象，也没有"某次窗口关闭了"的记录。

**(b) 执行资格完全无视窗口。** `bear_phase` 早就分得出 `SCHEDULED / PREPARING / READY /
ACTIVE / FINISHED / DISCOVERED`，而生成目标那一行把**除 FINISHED 以外的所有相位**都写成
`GoalStatus.READY`。同一个库、同一帧，前后对比：

| 场景 | 改前 | 改后 |
|---|---|---|
| 巨熊正在打 | `READY` priority **16000** | `READY` priority 16000 |
| 巨熊**两小时后**开始 | `READY` priority **5000** | **`SCHEDULED_NOT_OPEN`** priority −inf |
| 巨熊**已经结束** | `COMPLETE` | **`EXPIRED`** priority −inf |
| 本帧没有任何读数 | **目标根本不存在** | `SCHEDULED_BEAR_HUNT`（保留计划，不可调度） |

两小时后开的活动带 `priority 5000`，压过会随年龄涨到 180 的巡检票，并和 `CLEAR_INTEL`（500）
平级 ⇒ **"存在但未开放" 被当成了可执行工作，还排得进前列。**

**(c) 同一处还有一个方向的混淆：等待被记成完成。** 队列忙、兵营在训练、行军槽用完，
都曾写成 `GoalStatus.COMPLETE` —— 那是指令 §一 的"本次任务实际完成"。于是
"客户端还不让我开工" 和 "已经没有要做的了" 是同一条记录，§六 的"记录具体恢复条件"
无处可记。

### 顺带查出的第三个：`reusable` 读数绕过了准入闸门

第 5 轮把准入闸门放在"没有任何有效读数"分支里，漏掉了**复用读数**那条路。实测：入口红点
`ABSENT`、手上有一条新鲜的 `{"status": "CLAIMABLE"}` 存储读数时，库**仍然**发出
`MAIL_ROUTINE / READY` 及领取技能 ⇒ 目标存在、能赢下目标板、却执行不了（运行不在那一屏上，§六
的出口闸门又会拒绝进页）。现在闸门只管一件事：**这个决定是否建立在"本帧读到的"读数上**；
不是，就必须有 PRESENT 的入口读数。

---

## Q2 当前哪些周期活动已经能够提前准备

复用既有活动知识库 `knowledge/events/event_registry.json`（它的 `policy` 原本就规定了新条目
从 `DISCOVERED` 进、生产要求 `VERIFIED`），按 §二 补齐了：适用角色、周期、下一次开放条件、
参与条件、知识、历史成功路径、**提前准备事项**、本次的完成与领取状态。

| 活动 | gate | 周期 | 窗口 | 下一次开放条件（客户端自己印的） | 准备事项 |
|---|---|---|---|---|---|
| `BEAR_HUNT` 巨熊行动 | REVIEWED | RECURRING_COOLDOWN | `EXPIRED` | 冷却 `1天22:57:12`（狩猎陷阱页印的，读作 `world.events.bear.seconds_to_start`） | 3 条 |
| `STATE_VS_STATE` 最强王国 | DISCOVERED | UNKNOWN | — | 只有阶段倒计时，**没有**下次开放时间 | — |

- `STATE_VS_STATE` 是 `DISCOVERED`（未复核的线索），按注册表自己的政策**不进计划**。
- **没有任何活动有可靠的 `start` / `end`** —— 本项目从未量到过。按 §二 **保留 null，不编造时间**；
  窗口由"客户端印了什么"回答，不由时钟回答。

**真机已生效**：`learning/goal_state.json`（13:57:21Z，当时站在 `MAIL` 页——一屏完全看不到
狩猎陷阱）里已经有：

```
SCHEDULED_BEAR_HUNT   EXPIRED   priority=None   window=EXPIRED   prepare=3
```

⇒ **不在那一屏，计划也在；不可调度，所以不会去反复找不存在的入口。**

---

## Q3 活动开放后多久开始首次有效操作

**从现有材料答不出来，工具如实说答不出来：**

```
activity-instance steps in the corpus: 0
NOT ANSWERABLE from what is on file: this project has never been present for an activity window
```

本项目**从未在某个活动窗口内出现过**，所以没有可量的实例。不编数字。留在记录上的判据是：
窗口的推进由**客户端自己的倒计时**驱动（`rally.bear_phase`：600s → PREPARING，120s → READY），
而倒计时来自运行**正站着的那一帧** —— 所以第一个有效操作应当发生在倒计时越过阈值后的第一帧，
不是"等某个定时器"。

**无红点那两项是可答的**（§八 要求的口径）：`PRESENT` 出现后到首次有效处理的延迟，见 Q4。

---

## Q4 无红点巡检减少了多少

`tools/measure_red_dot_gating.py`，分隔点 = 落盘时刻：

| | `OPEN_MAIL` | `OPEN_ALLIANCE_GIFTS` |
|---|---|---|
| **改前** | **97** 步（入口读数：`NO_READING` 83 / `PRESENT` 14） | **97** 步（宝箱瓦片：`PRESENT` 4 / **`ABSENT` 93**） |
| **改后**（本轮之后 29 步） | **0** | **0** |

**没有任何一次"入口读数缺失或 ABSENT 时仍进页"被记为正当的** —— 改前这类入口访问合计
**176** 次。改后的验收判据：邮件 `ABSENT`/`UNKNOWN` → 没有 `OPEN_MAIL` 步；宝箱
`ABSENT`/`UNKNOWN` → 没有宝箱进入；被拒的步是 `SAFE_STOP` 且 reason 含 `entry_gate` /
`entry_badge`（非致命，让位其他 Goal）。

`PRESENT` 时仍然照做：改后窗口里 `MAIL_CLAIM_REWARDS` 在 13:56:13 **成功**，随后
`SELECT_MAIL_ALLIANCE_TAB`、第二次 `MAIL_CLAIM_REWARDS` 均成功 ⇒ **PRESENT → 能及时处理**。

---

## Q5 任务暂时不可执行时，AUTO 实际继续做了什么

改后窗口 29 步、2 个运行（分隔点之后），按 goal 统计：

```
AVOID_STAMINA_WASTE 9 · MAIL_ROUTINE 9 · CLAIM_EXPLORATION_IDLE 6
KEEP_TRAINING_PRODUCTIVE 3 · KEEP_RESEARCH_PRODUCTIVE 1 · MAIL 1
```

逐步看：`SEARCH_RESOURCE` → `SUBMIT_BEAST_SEARCH` → `SCAN_MAP_FOR_BEAST` ×5 →
`OPEN_INTEL` → `BACK` → `OPEN_HOME` → 探索闲置领取（4 步成功）→ 训练/科研 → 邮件领取。
**不是全局 `SAFE_STOP`**：不可执行的那一项不在排序里（`priority = -inf`），所以它连
消耗一个周期的机会都没有。

---

## 改了什么（三处，都是"是否允许生成并执行"）

1. **`GoalStatus` 补两个真正缺的状态**：`SCHEDULED_NOT_OPEN`、`EXPIRED`。指令的六种语义
   映射到项目自己的词：`READY` / `SCHEDULED_NOT_OPEN` / `BLOCKED` / `BLOCKED +
   retry_after + evidence["condition"]` / `UNKNOWN` / `COMPLETE` / `EXPIRED`。
   五个非可执行状态收进一个 `NOT_ACTIONABLE` 集合，`GoalState.priority` 只读它一次 ——
   新增状态不会被某处比较漏掉。**没有第二套任务系统。**
2. **窗口按相位如实标注**：`FINISHED → EXPIRED`、`SCHEDULED/PREPARING →
   SCHEDULED_NOT_OPEN`、`DISCOVERED → UNKNOWN`、`ACTIVE/READY → READY`；客户端已过期的
   `EVENT_MINIMUM_GUARANTEE` 也从"负 deadline 的 READY"改成 `EXPIRED`（`deadline_pressure(0)`
   是 −100000，只会把它压低，永远不会把它挪出排序）。
3. **存在性不再只依赖当前帧**：`event_goal.known_activities()` 读既有活动注册表（只认它
   自己 policy 认可的 gate），`GoalLibrary._append_known_activities` 为每个已知活动留一张
   **计划票**：`available_skills=()`、状态取窗口、`evidence` 带上 prepare / knowledge /
   occurrence。已经在本帧被读到的活动不重复发 —— 一个活动一条记录。
4. **等待 = `BLOCKED` + 恢复条件**：队列忙、兵营在训练、行军槽用尽，从 `COMPLETE` 改成
   `BLOCKED` + `retry_after`（队列/兵营自己的倒计时）+ `evidence["condition"]`。
   `completion` / `distance` 一个字没动 ⇒ 排程行为不变，变的是**记录说的是不是真的**。

---

## 未做 / 不知道的

* **Q3 答不出来**：本项目从未在活动窗口内出现过。判据已写进工具输出与交接文件。
* **`goal_library.py` 不在 `CONTROL_PLANE_PATHS` 里**，但 AUTO 的每一轮是
  `tools/run_live.py` 的**子进程**（`control_panel.py:133` 的注释写明"没有进程内热替换"），
  所以本改动**从下一个 spawn 的运行起就在真机上**，本轮改后窗口的 29 步即是证据。
* **`OPEN_POWER_DETAILS` 仍是 #113 那个断点**（点击对、后帧确为实力详情、页面识别读成
  `UNKNOWN`），本轮未动，操作者已接受该定性。
* 五个巡检票在裸 MAP 帧上**同价 180**，谁赢由学到的 `history_bonus`（`stamina_routes.json`）
  与公平账本决定。本轮把测试夹具从这两个机器状态里摘出来（并因此修好 5 条既有红项），但
  **"五路同价" 本身是一个设计弱点**，已单独登记，未在本轮改动。
