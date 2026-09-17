# 给一个"新界面路线"做真机落地 —— 固定流程

> 本文件是**操作流程**，不是事实存放处。事实在 code / handoff / `docs/`。
>
> 为什么需要它：2026-09-17 一天之内用同一套流程把 **训练** 和 **研究** 两个 BLOCKED 目标
> 打成 LIVE（`KEEP_TRAINING_PRODUCTIVE` → FULLY_LIVE_VERIFIED、
> `KEEP_RESEARCH_PRODUCTIVE` → PARTIAL）。剩下 BUILD / ARENA / ALLIANCE_HELP / LABYRINTH
> 是同一形状，照抄即可。**两次都在最后一步之前以为"要从零摸索 UI"，实际上机制早已存在。**

## 第 0 步：先确认"缺的到底是什么"（最省时间的一步）

**先读，别先写。** 按顺序查四件事：

1. **决策**：`grep` 目标名于 `brain.py`。训练与研究都**已经有完整路由**，
   研究只是"没有导航决策"。没有路由 ≠ 没有能力。
2. **verifier**：`LiveRuntime.VERIFIED_ATOMIC` 里有没有该步的绑定。
   两次都是**早就绑好了**（`verify_training_page_open`、`verify_research_page_open` 等）。
3. **技能与契约**：`skill_factory.GOAL_REQUIREMENTS[<goal>]` 点名了这个目标需要哪几个技能；
   `knowledge/skills/<X>_RESEARCH.md` 里往往**已经写着实测路线**（研究那条在第 38 行）。
4. **语义名**：`grep` 技能的 `action.target`。
   ⚠ **同一个控件常有两个语义名**（`BTN_OPEN_POWER_OVERVIEW` 宽裁剪含数字、只能匹配裁它的账号；
   `BTN_OPEN_POWER_OVERVIEW_ICON` 只裁图标、两账号都命中。**技能点的是后者**）。
   **判定控件"坏了"之前，先找到动作真正指向的那个语义名。**

⇒ 结论多半是：**只缺"今天能命中的模板" + "可能缺一两跳决策"**，不是缺能力。

## 第 1 步：有界探针逐跳走（`tools/probe_power_route.py`）

- `--tap x,y` 逐跳，**每跳的坐标都从前一帧量出来**（探针会打印全量 OCR token 供你量下一跳）；
- `--allow-page NAME` 显式声明"我认得这个页"（默认只允许从 HOME 出发）；
- `--leave` 收尾 BACK 一次，把客户端放回已知页，**返回本身也是证据**；
- 硬上限 6 跳；**只点你给的坐标**，绝不盲点。

⚠ **探针会暴露错误假设，那是它的价值**：研究这轮第一跳我以为坏了，其实是我用错了语义名。

## 第 2 步：模板必须以**点击落点**为圆心

执行器只支持 `TAP_SEMANTIC`，**点的是"命中记录的 ROI 中心"**（没有绝对坐标动作）。所以：

- 裁剪**必须**以要点的那个控件为圆心；
- 焦点控件周围常有**动画**（训练/研究按钮上都有引导手指 + 呼吸光圈）⇒
  **裁剪要放大到能把动画吃掉**（训练用 300×300、研究用 340×340，都正好圆心落在按钮上）；
- "最稳的那一块"（如 `详情` 按钮，实测 d=0..2）**不能**当裁剪中心 —— 它不在要点的地方。

## 第 3 步：门禁按**两个总体**定，不按"让候选通过"定

用 `tools/probe_camp_menu_gate.py` 那种全语料扫描，报**正样本分布**与**负样本分布**，
阈值取两者之间的分界。实测两例：

| 语义 | 正样本 | 最近的负样本 | 阈值 |
|---|---|---|---|
| `BTN_OPEN_TRAINING_FROM_CAMP`（旧） | 12–16 | ≥20 | 17 ← 但**新裁剪的普通城市帧是 16**，落在里面 ⇒ 会误报 |
| `BTN_OPEN_TRAINING_FROM_CAMP`（新） | 0–8 | 16 / 36 | **12**（收紧） |
| `BTN_OPEN_RESEARCH`（新） | 0/8/8 | 28 | 8（默认） |
| `BTN_OPEN_RESEARCH`（旧） | — | 26–36 | 12 ⇒ 永远赢不了，保留无害 |

⚠ **收紧也是正当的**：跨账号帧若靠它**自己的旧记录**仍命中（d=0），收紧就不丢召回。
⚠ 旧记录的 **ROI 中心可能根本不在控件上**（研究旧中心 (536,840) vs 实测按钮 (478,878)，
偏 ~65px）—— 所以注册新记录后**必须打印"哪条记录赢了、中心落在哪里"**。

## 第 4 步：接线（四件，缺一不可）

1. `skills.py`：导航技能，`required_page` 用**上一跳的结果页**；
2. `verifier.py` + `runtime.py`：**两条** verifier（到达 + 进入下一页），并绑进 `VERIFIED_ATOMIC`；
3. `vision.py`：读"菜单已打开"这个**导航事实**；
4. `brain.py`：goal 路由，顺序 = **先忙/无价值就停 → 再导航**。

⚠ **导航事实 ≠ 队列事实。** 城市帧里**只写 `menu_open`，不要写 `queue_available`**：
隔壁训练分支硬编码了 `queue_available: True`，而 `goal_library` 把它读成"队列空闲"——
从一个导航事实**编造**出一个队列事实。
⚠ 新分支若**提前 return**，会把后面分支本来提供的事实**丢掉**。
研究第一版就丢掉了 `RESEARCH_BUILDING_QUEUE_TIMER` 的队列状态，被既有测试当场抓住
⇒ **要合并，不要抢先返回**。

## 第 5 步：真机验证要找对起点

- `run_live.py --goal <GOAL>`；**注意前置状态**：若上一轮已经把目标菜单打开，
  这次运行会**跳过前几跳**（研究第一轮只走了 2 步）⇒ 用 `--leave` 退回普通 HOME 再跑一遍完整链路。
- 给 goal 补上 `accepted_stops`（`tools/run_live.py`），否则"诚实的停止"会被算成 exit 2。
- **停止原因要具名**：研究原本从后面所有分支掉下去、以无名停止结束；现在叫
  `research_page_no_startable_node`。

## 第 6 步：收尾

- `tests/test_<route>_route_templates.py`：正/负**双向** + **赢家 ROI 落点**在控件框内；
- `tools/check_wiring.py`：决策 + verifier 绑定 + **目标隔离**（"TRAIN 不会走研究那一跳"）；
- 证据进 `dataset/truth_audit/<set>/key/`（`.gitignore` 只白名单 `key/**`，其余留本地）；
- `tools/build_capability_catalog.py` + `tools/build_capability_coverage.py` 重生成覆盖度；
- 记忆 + handoff + `git_sync.py push`。

## 反模式（都实际发生过）

- **用错语义名就宣布控件坏了**（研究第一跳）。⇒ 先 `grep` `action.target`。
- **只裁按钮本身**：动画让它在一次运行里 7 帧只中 3 帧，害 verifier 连刷 21 秒，
  而浮层寿命约 2 秒 ⇒ 下一步观测时已消失 ⇒ **整条路线重走一遍**（训练第一次 7 步）。
  ⇒ **裁剪要吃掉动画，目标是"第一次观测就能通过"**。
- **新分支提前 return** 丢掉别的事实（研究第一版），被既有测试抓住。
- **从导航事实编造队列事实**（训练分支的硬编码 `True`）。
- **提交消息里带双引号** —— shell 会吃掉后半段（`3793a9b` 就断了）；
  用 `git commit -F <file>`，或消息里避开引号。
