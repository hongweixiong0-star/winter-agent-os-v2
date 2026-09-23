# 快捷面板作为城内任务主要状态与导航入口 —— 2026-09-23

操作者指令：**快捷面板优先提供城内状态；优先提供对应功能入口；当前页面能直接完成的任务直接完成；
面板不可用才走其他可靠路径；做完一项继续下一项，不再反复绕路检查。**

一份可复算的取证：

```
python tools/measure_quick_panel_priority.py --out dataset/truth_audit/quick_panel_priority_20260923
python learning/_probe_panel_entries.py        # 面板行进入到底到达了什么（用每一步自己的验证器判）
python tools/measure_panel_row_badges.py       # 既有工具：面板行的角标
```

---

## 一、真机断点：两处，都是"读数到手又丢掉"

### (a) 面板说了状态，目标层一个字都看不到

`_with_quick_panel`（`ocr.py`）只把面板的 `camps` 并进 `WorldState`。实测**面板展开的 57 帧**：

| 面板区块 | 有读数的帧 | `WorldState` 对应字段有读数 |
|---|---|---|
| 建筑队列（`building`） | **56** | **0** |
| 科技研究（`research`） | **57** | **0** |

⇒ 读到了、丢了。于是训练/科研目标"不知道"队列忙闲，只能去**加成总览→实力详情**问一遍。

### (b) 那个"问一遍"的绕路：20 步，**全部失败**

| 理由 | 步数 | 结果 |
|---|---|---|
| `train_goal_power_overview` | 10 | **全 FAILURE**（`POWER_DETAILS_NOT_PROVEN`） |
| `research_goal_power_overview` | 10 | **全 FAILURE** |
| `training_goal_requires_power_route` | 2 | — |
| `research_goal_requires_power_route` | 3 | — |

全史 `OPEN_POWER_OVERVIEW` **131** 步 + `OPEN_POWER_DETAILS` **139** 步 = **270** 步（占 7168 步的 **3.77%**）。

**一条完整的浪费链**（run `20260923_215819_292688`，6 步里 4 步是绕路与善后）：

```
13:59:25 TRY_ORDINARY_CONTROL  SUCCESS  展开面板
13:59:41 OPEN_POWER_OVERVIEW   SUCCESS  面板已开、4 行已读（三兵营 已完成 / 科技研究 空闲中）
13:59:41   理由 = quick_panel_shield_camp_is_idle   ← 面板已经回答了状态，却去开加成总览
14:00:21 OPEN_POWER_DETAILS    FAILURE  POWER_DETAILS_NOT_PROVEN → 落到 UNKNOWN 页
14:00:32 TRY_ORDINARY_CONTROL  FAILURE  在 UNKNOWN 页上再花一步
14:01:00 CLOSE_POPUP           SUCCESS  收拾残局
14:01:27 OPEN_MAP              SUCCESS
```

同一个 `quick_panel_<camp>_is_idle` 理由在 270 步里出现 **5** 次，每一次后面都是那个 100% 失败的绕路。

### (c) 顺带查出行身份错了

`goal=LANCER_CAMP_TRAINING` 那一帧被回以 **`quick_panel_shield_camp_is_idle`** —— **盾兵**那一行。
原因是那条扫描取"字典序第一个空闲兵营"。§二/§四 要求的正是"确定目标任务行"。

---

## 二、改了什么（四处，都是"优先级与判据"，没有新系统）

1. **`ocr.py::_with_quick_panel`**：把面板的 `building` / `research` 也并进 `WorldState`，**页面读到的不被覆盖**
   （面板是叠层，页面是底下的东西；与既有 camps 的规则同一条）。§一.2：如果 WorldState 已有新鲜可信的状态，直接复用。
2. **`brain.py` 空闲兵营分支**：空闲兵营**先取目标自己的那一个**（`_goal_camp()`），再退到字典序。§二/§四。
3. **`brain.py::_without_an_enter_control`（新，一处一条规则）**：三种"看起来一样"的情形分开——
   - **没有这一行** / **控件槽是空的（`NONE`）** / **已点过而页面没开（次数用尽）** → §一.6 允许的旧路线兜底，理由写明是哪一种；
   - **画了控件但那是个已量到的死点（`DONE` 绿勾）** → **让位**（非致命 `SAFE_STOP`），**不再绕路**。
     理由：绿勾中心被点过、什么都没收到（`_QUICK_PANEL_ROW_CLAIM_SKILL` 上方记录着这次测量）；
     而 `DONE` 对**队列行**的含义是"队列跑完了"，兵营可用，只是"从这里怎么用"本项目还没有证过的控件。
4. **`brain.py::_panel_answered_this_goals_state`（新）**：面板这一帧已经答过这个目标的状态时，
   训练/科研的 HOME 兜底不再去开加成总览；旧路线只留给"面板没在给这个目标干活"（§一.6），
   且理由从 `*_goal_requires_power_route` 改成 `panel_did_not_serve_this_goal_so_the_power_route_is_the_fallback`。

### 关于那颗绿勾：**不是**点它

面板上三兵营读 `已完成` 时，客户端在**按钮列的同一个小方框**里画绿勾
（`done_box_norm` x=0.5333 w=0.0569，与科技研究行扫到的 `arrow_box_norm` x=0.5333 w=0.0569 **同一格**）。
但**它的中心已经被点过**（404,556）：面板关了、没有奖励弹窗，17:53:39 重读该行**仍是 `已完成`/`DONE`**（`brain.py` 该表上方逐字记录）。
所以本轮**没有**把绿勾当成可点控件——`_QUICK_PANEL_ROW_CLAIM_SKILL` 仍是空集。

---

## 三、真机验收（§八 逐条）

| # | 项 | 状态与证据 |
|---|---|---|
| 1 | 训练状态主要从面板读，不再周期绕实力详情 | **已改**：面板答过就绕路（`_panel_answered_this_goals_state`）；面板行有可用按钮就走行 |
| 2 | 至少一个空闲兵营**真正**通过面板行进入并开始训练 | **本轮之前就已成立**，实测 `07:27:02 OPEN_TASK_FROM_QUICK_PANEL_LANCER` →（`verifier_ok=True`，到达**城内兵营动作条**）→ `07:27:27 OPEN_INFANTRY_TRAINING` → `07:27:50 TRAIN_TROOPS` **SUCCESS on TRAINING** → `07:28:15 SELECT_TRAINING_CAMP` |
| 3 | 科研真正通过面板行进入并启动 | **部分成立**：10 次面板行进入到达**实验室动作条**（如 `13:50:17 → 13:50:33 OPEN_RESEARCH → RESEARCH`）；"启动符合条件的研究"未在语料里见到成功证据 |
| 4 | 联盟捐献 / 免费招募 / 我的奖励 能进入并完成 | **未打通**：三个区块在 2026-09-22 22:02 那一次探索里读到（`可捐献25/25`、`免费招募`），但**当前语料里各只有 1 帧**，且**没有任何一次进入步** |
| 5 | 三兵营均忙碌时不重复进入 | **已成立**：所有兵营 `IN_PROGRESS` → 无空闲兵营 → 非致命 `SAFE_STOP`，让位其他任务 |
| 6 | 目标行不在可见区域时滚动查找，不误判成不存在 | **未做**（见下） |
| 7 | 已在正确任务页时不无故回主城 | **已成立**：真机训练页帧（`status=AVAILABLE`/`trainable`）→ `TRAIN_TROOPS`；盾兵目标在射手页 → `SELECT_TRAINING_CAMP` |
| 8 | 旧路线只在面板不可用或确有必要时用，并记录原因 | **已改**：四个旧理由字符串全部退役，换成说明"是哪种兜底"的理由 |

**面板行进入的实际到达率**（35 步 `OPEN_TASK_FROM_QUICK_PANEL_*`）：

- 带验证器证据的 **14** 步：**12 步到达该任务的城内动作条**，2 步什么都没到；
- 其余 **21** 步为早期记录、`verifier_evidence` 为空，**无法据此判断**（不当作成功也不当作失败）。

---

## 四、没做的 / 不知道的

* **§一.5 / §八.6 面板内部滚动：未做。** 2026-09-22 22:02 的既有探索（`_panel_scroll.py`，未入版本库）在面板内滑动 5 次，每次读数**完全相同**——这既可能是"已经到底"，也可能是"滑动没有生效"，**两者无法从日志区分**，需要设备上的一次测量（而 AUTO 正占着设备）。
  另：三兵营行都在场时，面板的可见窗口只覆盖 建筑队列 / 部队训练 / 科技研究，**下三个区块在窗口外**——`entry_badges.quick_panel_badges` 已把"没读到的行"记成 `UNKNOWN` + `row_not_read_this_frame`（**不是 ABSENT**，§二已满足），所以滚动是**发现能力**的缺口，不是正确性的缺口。
* **§八.4 的三个区块**：技能表（`ALLIANCE_DONATION` / `HERO_RECRUIT` / `MY_REWARDS`）与行键都已存在，但**从未在可见窗口里出现过**，因此没有任何一次进入步可验。
* **`_QUICK_PANEL_ROW_CLAIM_SKILL` 仍为空**：收集"已完成"那一行需要先找到一个真正能收的控件；绿勾中心已证是死点。
* **本轮改后窗口很小**：`brain.py` 落盘后语料只多了 5 步（0 次实力详情路线、0 次只为查状态的进入），
  **不足以单独支撑"减少量"的结论**；上面的 before 数字是结论的主力。
* 本轮的 `AB_QUICK_PANEL_STATE=off` 是逐站点复现旧行为（含两个旧理由字符串），不是近似。

---

## 五、改后窗口追出来的第五处：**面板打开预算被别的目标花掉**

改后窗口只有 14 步，但里面有一条完整链（**同一个 run** `20260923_223022_643420`）：

```
14:32:40 TRY_ORDINARY_CONTROL  SUCCESS  训练目标   handle COLLAPSED   ← 训练目标问第 1 次
14:33:47 OPEN_MAP              SUCCESS  AUTO_DISCOVERY  panel OPEN + building + camps ← 面板开成、已读
14:34:16 OPEN_HOME             SUCCESS  训练目标
14:34:30 TRY_ORDINARY_CONTROL  FAILURE  邮件目标   handle COLLAPSED   ← 邮件目标花掉共享预算且失败
14:34:46 OPEN_POWER_OVERVIEW   SUCCESS  训练目标   handle COLLAPSED   ← 训练目标问不到 → 旧路
14:35:29 OPEN_POWER_DETAILS    FAILURE  训练目标                        ← #113 再失败
```

`MAX_ORDINARY_ATTEMPTS` 是**每轮**计数、**跨目标共享**，所以邮件目标的一次失败把训练目标的面板问掉了 ——
而 §一.3 说的正是"当前可以进入快捷面板时优先展开"。**已改**：面板把手那一处改成**按路由计一次**
（`MAX_PANEL_OPEN_ATTEMPTS_PER_GOAL = 1` + `_panel_open_attempts`），仍然记账进 `ordinary_attempts` 但不再被它门控。
依据：把手是**已验证的控件**（`basis: HANDLE_TRIANGLE_SCAN`，带本帧 `box_norm`），不是"找一个没试过的控件"那种扫描——
后者才是 `MAX_ORDINARY_ATTEMPTS` 存在的理由。每问一次仍花一步，且同一路由问过就不再问（循环不可能），运行本身由 `max_actions` 兜底。

## 六、§一.2 的跨帧复用：**已通，且有活的证据**

改 `_with_quick_panel` 的另一个后果，比"当帧能看见"更重要：面板读数现在会**进观察库**。

`learning/observation_state.json` 里那条 `research`：

```
checked_at: 2026-09-23T14:33:19
reading:    {"name": "科技研究", "status": "IDLE", "queue_available": true, "source_word": "空闲中"}
frame:      ...20260923_223022_643420_step_010_before_20260923T143319683190.png
```

那一帧 `quick_panel.open=True, rows=4` ⇒ **存下来的就是面板自己的读数**，30 分钟 TTL 内后续帧可复用。

## 七、仍未打通：`building` 有当帧、没有跨帧

`_record_observations` 只遍历 `PANEL_ROUTINES + SWEEP_ROUTINES` 的字段，而 `building` 既不是面板例行项、
也不在 `SWEEP_ROUTINES` 里（`KEEP_BUILDING_PRODUCTIVE` 是刻意不入那表的），所以：

- 面板帧上 `WorldState.building` **现在有读数**（本轮改的）⇒ `KEEP_BUILDING_PRODUCTIVE` 当帧能看见；
- 但它**不进观察库**，且 `discover` 读 `world.building` 而不读 `observations["building"]`
  （`_append_queue_goal` 不收 observations）⇒ **跨帧复用要动目标层**，本轮不改，登记为下一轮的第一件事。

`observation_store.DEFAULT_TTL_SECONDS` 里 `building` 的 30 分钟 TTL **本来就有** —— 说明这个域是设计过的，只是没人写它。
