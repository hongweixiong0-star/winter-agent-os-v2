# AI 兜底通道：第一处真实断点（2026-09-23）

操作者 2026-09-23 指令第 1 项要求：交出**一条真实 Episode**——
`AI request_id → 自动答案 → AUTO 采用 → MAA 实际动作 → 游戏状态变化`。
本目录是这条链的审计与修复证据。所有数字都由仓库内的产物量出，可复算：

```
.\.venv\Scripts\python.exe tools\probe_unknown_channel.py --revisits --out dataset\truth_audit\ai_fallback_20260923
.\.venv\Scripts\python.exe tools\probe_advice_replay.py --out dataset\truth_audit\ai_fallback_20260923
```

## 一、结论先说：断点在哪

**答案不是"没被采用"，而是"没有任何东西把答案送回它被问到的那一屏"。**

三条互相独立的证据，全部来自磁盘产物：

1. **7 个提问的屏，41 次后续 UNKNOWN 步里被问到的那一屏回来了 0 次。**
   `UNKNOWN::燃霜矿区` 的最后一次出现就是提问那一刻（`2026-09-22T08:31:07`）；
   而答案在 `2026-09-22T10:12:39` 才落盘——**晚了 101.5 分钟**。
   判据是**逐帧 OCR 标题**，不是页记录的 `last_seen_at`：后者只在 `stage`/`record_attempt`
   时写入，一次"什么都没解析出来"的重访不会更新它，所以 `last_seen_at` 不变**不能**当作
   "没回来"的证据。（我第一版就是用错判据得出过结论，已改正。）

2. **7485 条 episode 里带 AI 建议的是 0 条**，而站过 UNKNOWN 屏的步骤有 145 条。
   `ai_advice` 是解析器真的带着答案走到那一步时才填的字段 ⇒ 消费点**从未**在"有答案"的情况下运行过。

3. **通道自己的台账**：13 次 `submitted` / 15 次 `reconciled`，**只有 1 条题有答案**
   （`unknown__control__b6546e80`）。其余 6 条题的 job 全部以 `ABANDONED` 收场。

## 二、修好的两处（都在既有主链上，未新增执行器/大脑/调度器）

### 1. 答案已到，就不许被判成"什么都没产出"（`unknown_dispatch.reconcile`）

实测（`learning/unknown_dispatch.jsonl`）：job `13ffdac6` 在 `10:12:39Z` 写出了答案，
台账却在 `10:37:49Z` 记成
`ABANDONED / no result after 45 minutes`，**并且把它取消掉了**。
后台会话干完活之后仍会显示 `working`，直到网关回收它——所以"只看年龄"的时钟会把
**一个已经产出的 job 记成什么都没产出**，并且顺手杀掉它。

修法：`reconcile` 在**非终态**分支里先看产物（`state: "ANSWERED"`，含网关自己的 `verdict`），
产物在就继续用它、不取消。**终态分支一字未改**——网关已经答过的问题，两个词不许打架。

### 2. 被反复提问的题，不许因为"2 次额度用尽"被永久孤立（`unknown_dispatch.candidates`）

实测（`unknown__control__78694f1b`，屏 `UNKNOWN::对战`）：
两次尝试在 `2026-09-22T19:41` 就花光了，而运行时仍在 `2026-09-23T08:30` 重新提问
（`ask` 每次访问该屏都会重写请求文件），**却再也提交不了任何 job** ⇒ 通道悄悄停止回答一个
它仍在被问的问题。而那一屏在 23 小时里被站过 **20 次**——它完全是可以被回答的。

修法：`MAX_ATTEMPTS_PER_REQUEST` 仍然限制**突发**；一条**重新被问**的题再加一次机会。
判据是 `request.created_at`（每次 `ask` 都会刷新）比我们上次尝试的 `updated_at` 更新，
即"自我们放弃以来运行时又问过"。再问的节奏由运行时自己的 `REQUEST_COOLDOWN_SECONDS`（1 小时）
限着，所以这一次机会是**问题**在限，不是我们在限。
另加 `orphans()`：把"没有任何 job 可提交、只能等人"的问题**说出来**，因为"通道是自动的"
只有在"为什么没提交"可见的时候才成立。

## 三、本次选中的验收目标

| | |
|---|---|
| request_id | `unknown__control__78694f1b` |
| 屏 | `UNKNOWN::对战`（战斗页，帧上只有 5 个词：`对战 / 53.6万 / 45.3万 / 自动 / X2`） |
| goal | `INTEL` —— 与运行时真机到该屏时的 `current_goal` 一致（决策原文 `unnamed_page_with_goal_INTEL_may_still_name_an_ordinary_control`）|
| 为什么是它 | 它是"当前仍有效"的题里**唯一一屏会被反复走到**的（23 小时 20 次）；`燃霜矿区` 只出现过一次，答案晚了 101 分钟，其知识按操作者要求保留到下次活动 |
| 真机路径 | `MARCH → INTEL_HERO_DISPATCH(SUCCESS) → 站在 UNKNOWN::对战 → TRY_ORDINARY_CONTROL(FAILURE, SEMANTIC_TARGET_NOT_VERIFIED) → 提问` |

离线确认（`replay.json`）：在该真机帧上，今天的页面模型仍读出 `UNKNOWN / 对战`，
算出的 `request_id` 与答案文件名**完全一致**，解析链要求注册的 5 个区域都在，
`_advised_control` 只因"还没有答案"而返回 `None`（并如实提问）——即链路是通的，缺的是答案。

## 四、真机结果

见 `live.json`（本轮追加）。**未取得真机结果的项不在这里冒充结果。**

---

# 附：第 2 项（实力详情）的真机结果 —— 2026-09-23 12:24:42Z

操作者第 2 项问两件事：**点没点到当前帧的真实按钮**、**后帧有没有真的进入 `POWER_DETAILS`**。
两问的答案都是**是**。这是本轮第一条真正拿到真机的结论。

## 现场（run `20260923_201923_535962`，rev `8e8489f`）

```
12:24:41Z  OPEN_POWER_OVERVIEW   SUCCESS   HOME -> POPUP/POWER_OVERVIEW
12:24:42Z  OPEN_POWER_DETAILS    tap_point=[361,728]   used_backend=ADB
12:25:24Z  OPEN_POWER_DETAILS    FAILURE   POWER_DETAILS_NOT_PROVEN
             verifier_evidence {"overview_before": true, "details_after": false}
             state_after page=UNKNOWN  popup=None
```

**点击落点 `[361,728]` 就是那颗按钮**：上一轮在真机帧上量到的按钮中心是 `(357.5,727.5)`，
OCR 把它的标签读成 `三实力详情`、中心 `(360,728)`。三者相差 ≤3.5 px ⇒ **解析给出的点就是按钮本身**。

**后帧确实进入了「实力详情」**（`step_014_after_refresh_2_20260923T122512050579.png`）：
帧上标题栏写着「实力详情」，下面是大熔炉：18 / 总实力 2,004,198，以及
建筑实力 / 部队实力 / 英雄实力 / 英雄装备实力 / 科技实力 / 宠物实力 六行、每行一个「提升」按钮。
⇒ **动作成功、后帧变化正确，只是它没有被读成 `POWER_DETAILS`。**

## 新的第一处断点：**页面识别**（不是点击，也不是关闭按钮那条链）

`verifier.verify_power_details_open` 要求 `after.page is Page.POPUP and after.popup == "POWER_DETAILS"`，
而 `popup` 由 `vision.py` 的模板链给出（`vision.py:1655` 的 `if match("POPUP_POWER_DETAILS")`）。
实测（阈值 8）：

| 仪器 | 今天的真机帧 | 8 张曾成功识别为 `POWER_DETAILS` 的帧 |
|---|---|---|
| 整面板 phash `popup_power_details__live_20260908_power_details__0` | **d=10**（差 2） | d=0（曾经过）|
| 标题栏 phash `..._20260917_titlebar` | d=24 | d=0 |

**为什么整面板 phash 会差 2**：这是一个 *读数会变* 的面板——`总实力 2,004,198`、
`635,163/907288`、`超过了本王国46%的领主` 每次都不一样，所以整面板的 phash 每次都会偏一点。
这与 issue #109/#110 是同一族：**仪器表达不了它要认的东西**。

**标题栏为什么不能用**：弹窗标题栏是"蓝条 + 居中白字"，**条本身没有区分度**。
实测把标题栏模板用 ccoeff 在带内搜索：今天的帧 0.9764，而**真负样本「欢迎回来」（离线收益弹窗）
也有 0.8761（d=8）**、`加成总览` 0.8535（d=9）⇒ 阈值 8 恰好落在真负样本上，
**若照此注册，离线收益弹窗会被认成实力详情**。所以**本轮没有注册这条记录**。

**为什么没有就此收尾**：整面板模板换 ccoff 也自相矛盾（8 张真样本 0.4933、被误读的那帧 0.8551），
说明"相似度分数"在这里不能替代测量。操作者本轮明确要求"不得把搜索范围内最像 X 的位置当成存在"，
所以**不发布一个分离度没量干净的仪器**。这条留给下一轮用**可复核的裁片**
（例如只含标题字形的裁片，或面板中"六行实力行"这一恒定结构）重新量正负样本后再注册。
