# 预留行军把整轮 AUTO 停在一轮 1 步（2026-09-21T03:17:51Z）

## 一、操作者看到的现场

| 项 | 值 |
|---|---|
| 行军队列 | **2/3**（游戏内显示） |
| 体力 | **175** |
| Goal | `KEEP_MARCHES_PRODUCTIVE` |
| Skill | `SAFE_STOP` |
| 等待理由 | **`reserved_march_for_stamina`** → GUI 显示「已为体力任务预留1支行军」 |
| 角色 | `PERSISTED`（GUI 显示 UNKNOWN/STALE） |

那一轮的运行记录（面板 `[steps]`，已在本会话读到并记录）：

```
step 1  EXECUTE_INTEL_RESCUE_SURVIVORS   SUCCESS   stamina 187 -> 175
step 2  SAFE_STOP  reserved_march_for_stamina   expected_result = stamina_task_slot_preserved
        before: marches=["GATHERING","RETURNING"]  march_used=2  march_max=3   ← 空闲 1 格
stop_reason: reserved_march_for_stamina
deferrals:  CLEAR_INTEL / AVOID_STAMINA_WASTE(DEVELOPMENT_PENDING, job=2d5c3dd5) /
            KEEP_TRAINING_PRODUCTIVE / ALLIANCE_ROUTINE / CLAIM_EXPLORATION_IDLE 共 5 条
```

⇒ **一轮只做了一件事就结束**。帧目录：`dataset/raw/control_panel/runtime_auto/20260921_111732_651445/`
（`step_002` **只有 before、没有 after** —— 因为那一步没有任何动作）。

## 二、预留队列是否真的空闲：是，而且它就是被预留的那一格

在患者帧（`key/01_*`）上用**生产链**读出来的世界状态：

| 量 | 值 |
|---|---|
| `page` | MAP |
| `marches` | `GATHERING`, `RETURNING` |
| `march_used` / `march_max` | **2 / 3** |
| `idle_marches` | **1** |
| `reserved_slots`（生产意图 `reserve_for_stamina=2`，容量 3 ⇒ `min(2, 3-2)=1`） | **1** |

⇒ `idle(1) <= reserved(1)` 成立 ⇒ 停下。**预留机制本身是对的**：它挡住了采集占用最后一格。

## 三、根因：不是预留挡住体力路线，而是"拒绝"被写成了"结束整轮"

同一个患者帧，用生产链跑 `RuleBrain.decide`（生产 reserve=2）：

```
goal=None / GATHER_RESOURCE  ->  SAFE_STOP  reserved_march_for_stamina
goal=BEAST_HUNT              ->  SCAN_MAP_FOR_BEAST      ← 它会去扫描
```

⇒ **体力路线本来就能用那一格**（`BEAST_HUNT` 只在 `idle_marches <= 0` 时拒绝）。
⇒ **预留从来没有挡住 `AVOID_STAMINA_WASTE`**。挡住它的是**运行时的处理方式**：
`SAFE_STOP` 在 `runtime.py` 里记 `DEGRADED` 并 `return finish(reason)` ⇒ **结束整轮**。
于是一个任务"不拿这一格"，把**其他所有任务**一起停了；而且没有任何动作把客户端挪出地图，
**下一轮开局还在同一屏**，再停一次。

**为什么当时跑的是采集目标而不是体力目标**：`KEEP_MARCHES_PRODUCTIVE` **不在这份文件的
goal→route 映射里**（`runtime.py:880` 的 8 条映射没有它），所以 `brain.current_goal = None`，
而 `reserved_march_for_stamina` 两个分支的条件正好是 `current_goal in {None, "GATHER_RESOURCE"}`
⇒ 采集分支先回答。与此同时 `AVOID_STAMINA_WASTE` 被一个开发作业
（`SPEND_STAMINA_ON_BEAST = DEVELOPMENT_PENDING`，`job=2d5c3dd5`）挡住，
而它是**该帧上优先级最高的可调度目标（825）** —— 门禁一放行（03:26:03Z）它立刻被选中并开始跑。

### 该帧上"打野"的真实阻塞原因（不是预留）

看 `key/03_*` 的放大图：地图上那只兽**只有 `22` 等级徽标、没有名字**。
生产链在这一帧上 `beast = {}`（整帧 OCR 也找不到任何已注册兽名）⇒
**"没有可识别的目标"**，属于 §三 里"没有安全目标 / 目标解析失败"，**与预留无关**。

## 四、修法：拒绝仍然拒绝，但把这一轮**交给下一个目标**

`runtime.py` 的 `SAFE_STOP` 分支里，只针对这一个理由，改用项目已有的
`_yield_to_next_goal`（Rule A 的既有实现，与"技能不可执行"那条路径同一个机制）：

* **不是**把 `SAFE_STOP` 换成另一个状态名 —— 循环会 `continue`，重新取帧、重选目标；
* 范围**精确限定**在该理由（守卫会因"扩到所有 SAFE_STOP"而变红）；
* 两道既有边界都在：`index < max_actions`（没有下一次迭代时仍然停机，不浪费预算）、
  同一个 goal 一轮只让位一次（不会自旋）。

## 五、验证（离线，真实帧 + 真实配置）

`tests/test_march_reservation_handover.py`，7 条：

| 在**本树**（已修） | 在**未修的 HEAD** |
|---|---|
| **7 passed** | **3 failed / 4 passed** |

未修树上红的三条正是这条缺陷：`run.stop_reason == reserved_march_for_stamina`、
让位后循环没有发出任何真实步骤（没出现 `OPEN_HOME`）、零次让位叙事。
另外 4 条（预留仍拒绝采集、拒绝需要"有空格且被预留"两个条件同时成立、体力路线不被拒绝、
没有迭代时仍停机）**两侧都过** ⇒ 它们钉的是**不变的行为**。

守卫新增 5 条（`tools/check_wiring.py`）：容量 1/2/3/4/6 下预留不吞掉整个军队（既有）、
采集仍被拒绝、**体力目标不被拒绝**、让位存在、**让位被限定在该理由上**。`problems: 0`。

## 六、未验证 / 仍未做（不许当已完成）

- **真机未复跑**：本修复尚未在设备上执行过一次。要看到的是：同一状态不再以
  `reserved_march_for_stamina` 结束整轮。
- **`KEEP_MARCHES_PRODUCTIVE` 缺路由**：**本轮没有补**，因为它不是无副作用的改动 ——
  `current_goal is not None` 在 `brain.py` 的 274 / 534 / 1055 行会新激活三条分支
  （终端页让位、`goal_page_mismatch`、联盟页让位）。补它等于同时打开这三条，
  必须单独测。已记入 04_OPEN_ISSUES。
- **角色身份**：`learning/role_identity.json` 的最后一次观测是 **2026-09-16T10:44:08Z**
  （已过 112.8 小时），且 `verification = VISION_READ_REPLAY`（**回放**，不是真机读）。
  生产把它作为**标记**打在每条 episode 上（`[role] 1171757165 (PERSISTED)`），
  **不参与调度门控**、也不会把队列或体力写进别的角色 ⇒ 它是**展示层过期**，
  但"没有任何生产路径重新读它"是**真实缺口**（`record_role` 只被操作者工具
  `tools/state_truth_audit.py --record-role` 调用）。

## 七、复现

```bash
"E:/无尽冬日智能体/.venv/Scripts/python.exe" -m pytest tests/test_march_reservation_handover.py -q
"E:/无尽冬日智能体/.venv/Scripts/python.exe" tools/check_wiring.py | grep -i reservation
```
