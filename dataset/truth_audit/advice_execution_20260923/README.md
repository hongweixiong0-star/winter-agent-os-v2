# AI 建议 → 实际游戏动作：链路审计（2026-09-23）

对象：**唯一一条真实 AUTO 取回的 AI 答案**。
工具：`tools/probe_advice_replay.py`（只读，无设备，把答案放回它自己的帧上用生产视觉重跑）。

## 一、这条答案是什么

| | |
|---|---|
| request_id | `unknown__control__b6546e80` |
| 提问时刻 | `2026-09-22T08:31:06Z`（真实 AUTO 在 燃霜矿区 屏上问的，当时 goal=DAILY） |
| 屏幕 | `UNKNOWN::燃霜矿区`（页面模型读作 UNKNOWN，标题 OCR 读出"燃霜矿区" confidence 0.9959） |
| 答案落盘 | `2026-09-22T10:12:39Z`（**1 小时 41 分后**） |
| 建议 | `ORDINARY_CONTROL[奖励入口]`，`target_anchor={text:"奖励", dy_norm:-0.03, w_norm:0.06, h_norm:0.035}`，`expected_result="奖励列表或奖励预览面板打开"` |

盘上总量：**6 个提问，1 个答案**（另 5 个从未有答案：任务被 45 分钟 timebox 取消 / 单并发槽位排队）。

## 二、把答案放回它的帧上重跑：一路通过

```
today the frame reads UNKNOWN / title '燃霜矿区' -> request_id unknown__control__b6546e80
the answer is taken: True   (regions on this frame: 17)
staleness: (fresh)
anchor grounding: 奖励 (0.8486,0.3094) + offset(0,-0.03) -> box (0.8519,0.2733,0.06,0.035)
risk: (none refused)
[advisor] ...: the answer's anchor '奖励' is on this frame -> {...}
[printed] ... AI_ADVICE[ORDINARY_CONTROL[奖励入口]] located by the on-demand analysis ... at 0.8819,0.2908
_advised_control -> [0.8819, 0.2908]   (_last_advice set: True)
```

⇒ **消费侧没有断点**：id 对得上、不 stale、锚点在本帧 OCR 读到的字上、风险闸门过、最终给出可点的落点。
（`grounded_region` 单独调用时会退回 `OCR_BOX[奖励]`，而 `_advised_control` 用的是**锚点推出的礼盒图标**——两者都合 §三，方法用的是更强的那条。）

## 三、第一个实际断点：**可达性**，不在执行链里

`request_id = stem__control__sha256(page_key)[:8]`，即**答案按屏命名**；`take()` 只在
`_advised_control` 里被调用，而 `_advised_control` 只在**当前帧就是那一屏**时才被走到。

事实：`knowledge/perception/pages` 里 燃霜矿区 这条记录 `attempt_count=0`、
`last_seen_at=2026-09-22T08:31:07` —— **它第一次被看到的那一秒，此后再没有被访问过**。
`ai_advice` 在 16 条屏记录里 **0 次**，在 6900+ 条 episode 里 **0 次**。

⇒ 答案从来没被执行，**不是因为被拒**，而是因为 **AUTO 再也没有走到那一屏**，消费点根本没有被进入。
而且系统里**没有任何东西**会把"某屏上有一条待用答案"变成一次可调度的访问：
`unknown_advisor.pending()` / `unknown_dispatch.pending()` 的调用者只有 dispatcher / worker / 工具，
运行时的调度层完全不读它。

**顺带发现的脆弱点（未修，已登记）**：id 由 **OCR 读出的标题**参与哈希，
所以同一屏若某次把标题读成别的字（盘上就有 `常规活动` 与 `燃霜矿区` 两条不同标题的记录），
id 就变、答案即被孤立。这也是"通知/入口/动作"三层必须分开的同一个问题：
**身份认错，后面全错。**

## 四、修法（本轮选定，尚未落地）

不加第二套调度器、不改红点语义：把"某屏有一条待用答案"变成该 Goal 上的**一次访问**，
复用现有的 Goal/访问（sweep）机制 —— 即让已存在的"去没看过的页面看看"这条机制
知道"这一屏上还有一个已经回答过的问题待用"。落地前先在真机上验证：
一次访问 → 取到答案 → 落点 → MAA 点击 → 后帧验证。

## 五、新指令的三层次：代码现状审计

| 层次 | 代码事实 | 结论 |
|---|---|---|
| NOTIFICATION | `EntryBadge(entry,page,state,observed_at,goal,task_state,pixels,box_norm,reason)` —— **没有任何 point/centre/tap 字段**；`box_norm` 只是读数证据 | 已经成立 |
| ENTRY_CONTROL | 面板行有具名控件 `OPEN_TASK_FROM_QUICK_PANEL_<ROW>`（联盟捐献/英雄招募/我的奖励/科研都有）；三行兵营走共用路径 `OPEN_POWER_OVERVIEW → NAVIGATE_*_CAMP → OPEN_*_TRAINING` | 已经成立 |
| TASK_ACTION | 进入后的动作由目标页自身的读数决定（现有 verifier 各自负责） | 已经成立 |
| AI 建议必须区分四件事 | `Advice` 有 `proposed_action/action_kind/target_semantics/candidate_semantics/expected_result`，但**没有**"这条建议是关于哪个通知/入口"的字段 | **缺口**（本轮未改，登记） |

不变量已钉进测试：`tests/test_red_dot_is_a_notification_not_a_target.py`（8 项 / 33 subtests）——
红点不得有可点坐标、"消费点只有排序层"（第三个消费者出现即失败）、行必须有具名入口控件、
无帧读数必须是 UNKNOWN 而不是 ABSENT。

## 六、验收清单（§六 + 新指令）

必须**分别**证明，且不得用"点击红点附近"冒充"红点任务已处理"：

1. 哪条 request_id 的建议被正式 AUTO 真正执行
2. 执行了什么新操作、游戏产生了什么实际变化（后帧 evidence）
3. 哪个红点真实影响了 Goal 选择并触发有效操作（notification → score → chosen goal → action 四段齐全）
4. 哪项原本没有完整 Skill 的任务实际完成
5. 对应免费奖励是否实际领取（IN_PROGRESS / TASK_COMPLETED / REWARD_CLAIMABLE / REWARD_CLAIMED / RESULT_UNKNOWN 分开判）
6. 未完成事项的第一个执行断点

**不得冒充成功的**：测试通过、红点读数增加、排序分数变化、AI 答案生成、候选点击坐标产生。

## 复算

```
E:\无尽冬日智能体\.venv\Scripts\python.exe -u tools/probe_advice_replay.py
```

（约 1 分钟：一帧的生产 OCR。帧与答案本体在 `learning/unknown_requests/` 与 `dataset/raw/`。）
