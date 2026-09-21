# 三个兵营与训练页：当前真实状态与缺口（2026-09-21）

## 一、三个兵营各自的真实状态

语料 = 生产自己记录为 `page=TRAINING` 的**全部 8 张真机帧**（4 个独立时段：09-16 ×2、09-20、09-21 ×2）。
逐帧用 `OCRPageClassifier` 读（经生产入口 `HybridVision.observe` 复验，见第四节）：

| 兵营 | 当前状态 | 证据 |
|---|---|---|
| **盾兵营**（INFANTRY） | **训练中（IN_PROGRESS）** | **8/8 帧全部是它**，每次都有真实倒计时与批次 |
| **矛兵营**（LANCER） | **UNKNOWN（从未出现过）** | 8 帧里**零帧** |
| **射手营**（MARKSMAN） | **UNKNOWN（从未出现过）** | 8 帧里**零帧** |

盾兵营的**真实读数**（每次都是一个真实倒计时，不是形状）：

| 帧（本目录 `key/`） | 状态 | 倒计时 | 批次 |
|---|---|---|---|
| `04_training_page_infantry_010931_216_20260916T234203`（仅原始目录，见第五节） | IN_PROGRESS | 01:09:31 | 216 |
| 同上时段的后一帧 | IN_PROGRESS | 01:00:00 | 216 |
| `01_training_page_infantry_100008_250_20260920T013348.png` | IN_PROGRESS | **01:00:08** | 250 |
| 同轮后一帧 | IN_PROGRESS | 00:59:58 | 250 |
| `02_training_page_infantry_025945_250_20260920T231851.png` | IN_PROGRESS | **02:59:45** | 250 |
| 同轮后一帧 | IN_PROGRESS | 02:59:33 | 250 |
| `03_training_page_infantry_002515_250_20260921T015321.png` | IN_PROGRESS | **00:25:15** | 250 |
| 同轮后一帧 | IN_PROGRESS | 00:25:05 | 250 |

⇒ **盾兵营的训练队列是长期在跑的**（不同时段倒计时不同 ⇒ 期间有完成/重启）。
⇒ **矛兵营与射手营在全部历史语料里一次都没出现过**，因此**不能**说它们空闲、也不能说它们忙 ——
按项目规则只能记 `UNKNOWN`，要确认必须**在客户端上打开那两页**。

**最新一次真实读数**：`2026-09-21T01:53:21Z`，盾兵营 IN_PROGRESS，剩余 **00:25:15**，批次 250。
（此后 AUTO 停摆，见第六节，故没有更新的帧。）

## 二、三个兵营**不是**被行军队列挡住的

**实测**：`brain.py` 的训练分支**完全不读** `idle_marches` / `reserved_slots` / `reserve_marches`
（全仓 grep 为空）。⇒ 用户的假设"预留行军挡住了兵营训练"**不成立** ——
两者是两个独立的成因，只是**症状都表现为 AUTO 停**。

## 三、真正的根因（都在训练链的上游）

### 3.1 训练页**根本认不出来**（模板层已死）

在生产自己记为 `page=TRAINING` 的那帧上，当前模板层的结论：

| 语义 | 结果 |
|---|---|
| `PAGE_TRAINING_INFANTRY`（3 条记录） | **不匹配** |
| `PAGE_TRAINING_LANCER` | **不匹配** |
| `PAGE_TRAINING_MARKSMAN` | **不匹配** |
| `TRAINING_QUEUE_TIMER`（4 条记录） | **不匹配** |
| `TAB_TRAINING_INFANTRY` | **不匹配**（它是**选中**页签：浅底蓝字，与另外两个不是同一张图） |
| `TAB_TRAINING_LANCER` / `TAB_TRAINING_MARKSMAN` | **都 d=2** —— 两图相同、且都从**未选中**的蓝底格子裁的 ⇒ **即使匹配也分不开这三个兵营** |

这些记录的 `status` 全是 `CANDIDATE`、`source` 全是 `REPLAY_HUMAN_REVIEWED_SCREENSHOT`
⇒ **是从旧截图手裁的、从未在真机校准过**。

⇒ 后果链：模板层认不出页 ⇒ `world.training` **恒为空** ⇒
`TRAIN_TROOPS` 要求 `Page.TRAINING` ⇒ **这个技能永远不可能被满足**。

### 3.2 那个分支还在**把旧截图的常量当读数**

`vision.py` 的模板分支原本写死 `"tier": 10, "batch_count": 806` ——
两个来自某张旧截图的数字，被写成"从当前帧读出来的"。生产里**没有任何消费者**读它们。
**已删除**（本次提交），并加守卫防止回归。

### 3.3 数据模型里**没有兵营维度**（用户 §四/§五 的核心）

- `goal_library` 里训练是**一个**目标 `KEEP_TRAINING_PRODUCTIVE`（一条 sweep 票，
  `work=("IDLE","AVAILABLE")`、`done=("IN_PROGRESS","QUEUE_FULL")`、`work_skills=("TRAIN_TROOPS",)`）；
- `_append_queue_goal` 对 `world.training` 里的**单个** `status` 判一次：
  `IN_PROGRESS` ⇒ **整个目标标 COMPLETE**。

⇒ **一个兵营忙，就把整个训练检查标成"没事可做"**，另外两个兵营**根本不会被看** ——
这正是用户明令禁止的（"不得因其中一个兵营队列忙，就跳过其他两个兵营"）。
⇒ **这是真实的结构性缺口，本次未修**（见第五节）。

## 四、本次已修：训练页改由 OCR 识别，且数字是读数

同一批帧，`OCRPageClassifier` 读得**又准又全**（整帧 OCR 直接读到
`训练中` / `盾兵营` / `矛兵营` / `射手营` / `正在训练250位英勇盾兵`）：

```
page=TRAINING  training={"troop_type":"INFANTRY","status":"IN_PROGRESS",
                          "queue_available":false,"batch_count":250,"timer":"01:00:08"}
```

⇒ `HybridVision.observe` 现在在**模板层返回 UNKNOWN 且没有训练状态**时咨询该分类器，
且**只在分类器自己也说是 TRAINING** 时采用（与 alliance / daily 的"模板定页面、OCR 补字段"
同一条纪律，只是这里模板层无话可说，所以闸门换成"必须 UNKNOWN"）。

**两个半场都量了**：

| | 结果 |
|---|---|
| 8 张真机训练帧经生产入口 | **8/8 → `TRAINING / INFANTRY / IN_PROGRESS`**，倒计时与批次全部为真实读数 |
| 14 张非训练真机帧经生产入口 | **0/14 变成 TRAINING**（分类器输出 ALLIANCE 或 UNKNOWN，与生产一致） |
| 代价 | 只在 `UNKNOWN` 帧触发；`UNKNOWN` 占最近 790 个页面读数的 **1.5%**，单次全帧 OCR **0.59s** |

守卫 2 条（`check_wiring`）＋ 测试 6 条（`tests/test_training_page_by_ocr.py`）。

## 五、本次**未修**（不许当完成）

| # | 缺口 | 说明 |
|---|---|---|
| 86 | **`world.training` 没有兵营维度，一个兵营忙就结束整个训练检查** | 需要把训练检查做成**三个兵营各自一条**（或一个目标 + 三份子状态），并保证"一个忙不跳过另外两个"。**可行**：三个页签的名字**OCR 全部读得出**（`盾兵营` 1.00 / `矛兵营` 0.99 / `射手营` 1.00）⇒ **切换页签不需要重切模板**。**未做**：这涉及 goal 结构与新技能，且**矛兵营/射手营零帧**，在真机上打开它们之前无法校准——正是"先有帧再实现"。 |
| 87 | **矛兵营/射手营的真机页面从未被观测** | 全部历史语料零帧。⇒ 它们的**队列是否空闲、能否训练、条件是什么**，一律 `UNKNOWN`，不得据名称推断。**需要**：在客户端上分别打开这两页各抓一帧（可复用现有 `TAB_*` 位置之后的 OCR 判定）。 |
| 88 | **`KEEP_TRAINING_PRODUCTIVE` 的进展计量被非训练动作污染** | 157 步里含 `OPEN_ALLIANCE_GIFTS`(3)、`CLAIM_FREE_STAMINA`(3)、`OPEN_MAIL`(1)、`OPEN_MAP`(2) 等**非训练动作**（`_step_goal` 在当轮无可选目标时回落到 `_committed_goal` 标签）。该目标的 deferral 签名正是 `OPEN_TRAINING_PAGE\|NO_GOAL_PROGRESS\|**OPEN_ALLIANCE_GIFTS**`。**但要说清**：它被 DEFERRED 的**主要原因仍是自身**——53 次 `WAIT_FOR_CAMP_MENU` 全零进展（见 `training_stage_a_20260921`）。**未修**：改标签归属会动到 2026-09-18 为修 `AUTO_DISCOVERY` 占位符而定的那条规则，需单独测。 |

## 六、本次真机验收仍被 AUTO 停摆挡住

`11:43:24`（本地）之后 AUTO **再没有起过新轮**，面板进程活着（pump 仍在跳）、
`operator_intent=RUNNING`，而 `panel.log` 13 分钟无输出。
根因已在本次定位并修复（`tools/control_panel.py`：**16 处 `communicate()` 无超时**，
面板在 Windows 上持有的是 venv 转发 stub，真正持管道的是孙进程 ⇒ 管道 EOF 永不到来 ⇒
**一个 worker 不退出就让整个 AUTO 周期结束到人工重启**）。**需要操作者重启一次面板**才能生效并复验。

## 七、复现

```bash
"E:/无尽冬日智能体/.venv/Scripts/python.exe" -m pytest tests/test_training_page_by_ocr.py -q
"E:/无尽冬日智能体/.venv/Scripts/python.exe" -m pytest tests/test_worker_wait_is_bounded.py -q
"E:/无尽冬日智能体/.venv/Scripts/python.exe" tools/check_wiring.py | grep -iE "training:|panel:"
```
