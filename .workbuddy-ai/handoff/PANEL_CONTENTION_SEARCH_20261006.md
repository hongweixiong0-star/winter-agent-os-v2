# 搜索产物 — 两个目标争用同一面板状态（2026-10-06）

> 按 `docs/DEVELOPMENT_FLOW.md` §五 硬门格式。**本次搜索的价值在于：先例里有可证明的机制，
> 而且三个来源的处方互相印证。**

```
=== 搜索产物 ===
任务/问题：两个各自合理的目标轮流抢同一个快捷面板，导致单轮 80% 的动作被"重新开面板"吃掉，
        整体却零进展。要找一个不会互相抵消的结构性修法，而不是给某个目标打补丁。

搜索关键词：
  - utility-based agent behavior arbitration oscillation hysteresis commitment prevent thrashing
    near-equal utility

搜索结果（4 篇一手/综述，都带实测数字）：

  ① 【最接近的同类缺陷，且有**可证明**的修法】"Taming the Agentic RAN…
     Stability-Guaranteed Arbitration of Autonomous AI Agents in O-RAN"（pith.science/paper/2609.18857）
     原文："two autonomous agents with individually reasonable objectives interact through a
     **shared resource partition** to produce a **limit cycle**: opposing, recurring excursions that
     neither agent would cause alone."
     根因："**stale observations in a delayed feedback loop**"。
     处方：一层薄仲裁层，对**每个动作**强制三条 ——
       (i) **feasibility invariant**：动作后的共享状态必须满足一个约束；
       (ii) **per-variable dwell time（停留时间）**，且必须 **τ_d > 控制环延迟 τ_loop**：
            "any variable modified by the action must not have been changed within the past dwell time"；
       (iii) **deadband（死区）**：幅度小于 ε 的动作一律挡住。
     实测：共享状态摆幅 8.4 → 0.4（×20），跨切片饿死 40–55% → 0.3%。

  ② 【滞回带 + 最短驻留】"Hysteresis-Based Role Stabilization"（moltbook.com/post/a5f79b17）
     根因与我们的数字同形："tiny fluctuations in a single metric could shift the optimal match from
     role A to role B, and the next cycle would flip back when the metric rebounded."
     处方：**upper/lower 双阈值**（进一个状态的阈值高于退出它的阈值）+ **最短驻留 15 秒**
     （"Even after crossing a threshold, we enforced a 15-second minimum residence… This filtered out
     transient spikes that still slipped through the hysteresis band."）+ 把 thrash 率当健康指标。
     实测：切换/分钟 4.2 → 0.7；延迟 212 → 168 ms；网络抖动 1.8 MB → 0.4 MB。

  ③ 【最短任期 + 衰减效用】"Dynamic Role Reassignment in Heterogeneous Agent Swarms"
     （moltbook.com/post/b889b63c）
     处方：**minimum role tenure**（切换后锁 T 秒，T 按任务平均时长调）+ **衰减效用**
     e^(−Δt/τ)：最近做过的角色拿到的效用更低。
     实测：切换 4.6 → 0.9 次/小时；时延 −43%。

  ④ 【根因命名：等权重即数学上欠定】"Decision Paralysis / Multi-Objective Oscillation"
     （agentpatternscatalog.org/patterns/decision-paralysis）
     "**Equally-weighted goal sets are mathematically under-specified.** … the agent oscillates between
     solutions without converging." 处方：预定义优先级/矩阵，把"决策者"降为"决策执行者"。

  ⑤ 【成本归属是前提】"Multi-Agent Negotiation Protocols"（omnithium.ai）
     "If you cannot **track which agent spent which credit on which resource**, your negotiation
     protocol will collapse into a tragedy of the commons."

假设（基于搜索，我认为应该怎么做）：
  A. **我们的缺陷与此完全同形**，而且原因就在报告里被点名了：**陈旧观察 + 迟滞反馈环**。
     实测数字对得上 —— `learning/decisions.jsonl` 里两个目标的 `runner_up_gap` 是
     **142.2 → 142.3（差 0.1）**，正是来源 ② 说的"微小的度量波动就足以让最优匹配在两个角色间翻面"。
  B. **最省的杠杆是 deadband，而不是新建"归属"机制。**
     来源 ②/④ 都指向同一个判断：等权重/极小差距的分差是**欠定**的，应该由规则把它定下来。
     差 0.1 时任何 ε > 0.1 的死区都能一刀切断交替。项目**已经有** `runner_up_gap` 这个量在记，
     所以这是接现有机制，不是新框架（§2 ONE-*、§57 优先接现有系统）。
  C. **其次是 dwell time**（来源 ①/②/③ 都开这一味），而且来源 ① 给了可判定的取值条件：
     **τ_d 必须大于控制环延迟**。我们的环延迟是"一步动作 ≈ 5–10 秒"（实测相邻行为间隔），
     所以 τ_d 应取**一次性**的尺度，而不是零。
  D. **不做**来源 ⑤ 的完整成本归属（记录"面板为谁而开"）。它是对的、也是更彻底的，
     但它要动共享状态的所有权，属于"另建机制"；先用 B+C 看能否解决，**留作 B+C 无效时的下一步**。
  E. 来源 ① 的第 (i) 条（feasibility invariant）在本项目已有对应物：`page-residency`
     与"面板必须为即将使用它的目标而开"。可以在同一个死区里一并表达。

不确定性（哪些还没搞清）：
  1. **死区应该设多大？** 来源 ② 说 δ 取容量的 5–10%，但那是"能力向量"的量纲；
     我们这里是效用分差。**0.1 的分差太小、142 的分差量纲不明**，需要先量一个分差分布
     再取值 —— 我会先量再定，不拍脑袋。
  2. **dwell time 与 `_yielded_goals` 会不会冲突？** 项目已有"本轮不再选这个目标"的集合
     （`runtime.py` 里 `_yielded_goals`，run-scoped）。死区是**跨步**的偏好，
     两者语义不同，需要确认叠加后不会造成新的饥饿（§36/§38 要同时证明安全与活性）。
  3. **fairness_bonus 是不是必须同时改？** 交替的直接推手是公平性补偿把落后者不断抬回来。
     只加死区可能压住交替但让"落后目标"长期落后 —— 这会撞上 `PRINCIPLES §16`（长期不解决要升权）。
     这一条我要在改之前先想清楚，否则会用一个新的不公换掉一个旧的振荡。
=== 结束 ===
```

## 量完之后：**我的首选修法（死区）被自己的数据否掉了**

搜索产物写"必须先量分差分布与交替间隔"。量了，结论是**假设 A/B 都错**：

```
runner_up_gap 分布（重启后 35 条决策）：中位 142.2 · 最小 −10.0 · 最大 387.0
**切换时的分差：中位 142.2**（不是 0.1）
相邻决策间隔：中位 8.6s · p90 51.0s · max 76.0s
```

**切换发生在 gap ≈ 142 的地方，不在 0.1。** 原因是我读错了量纲：`runner_up_gap` = (第1名 − 第2名)，
而两个争用者**都不是对方的第 2 名**（第 2 名一直是 `CLAIM_EXPLORATION_IDLE`）。
所以"142.2 vs 142.3"不是两个目标的差距，是**两条相邻决策各自与同一个第三名之间的差距** ——
我把它读成了并列，**它是稳定的巨大差距**。**按 `runner_up_gap` 加死区会挡住所有正常切换，而不碰这个缺陷。**

### 真正的机制（`decisions.jsonl` 的 `board` 字段）

```
17:04:24  #1 KEEP_BUILDING_PRODUCTIVE  READY       base≈10x  skills=[OPEN_BUILDING_UPGRADE, BUILDING_UPGRADE, TRY_ORDINARY_CONTROL]
17:04:40  #1 DISCOVER_QUICK_PANEL_TASKS READY      base=260
          #5 KEEP_BUILDING_PRODUCTIVE  **DISCOVERED** base=80.1  skills=[TRY_ORDINARY_CONTROL]   ← 掉到第 5
17:04:45  #1 KEEP_BUILDING_PRODUCTIVE  READY       base≈10x                                          ← 回到第 1
17:04:50  #1 DISCOVER_QUICK_PANEL_TASKS READY      base=260                                          ← 又掉下去
```

**不是并列，是「建筑目标在自己动作之后，readiness 从 READY 掉到 DISCOVERED、base 从 ~10x 掉到 80.1」。**
于是那个 base=260 的目标每次填进空出来的第 1 位。

**项目已有的 `page-residency +40.0 (already standing on its page)` 激励顶不住 260 的新来者。**
把这两条并排看就是缺陷本身：**"你已经在正确的页面上"值 40 分，而"另一个目标想开面板"值 260 分。**

### 修法方向（改自搜索来源 ①②③ 的"最短任期"，而不是死区）

来源 ①②③ 的共同处方是**承诺/驻留**，不是阈值：一旦一个目标开了自己的多步序列，
就该在接下来的决策里**保持承诺**，而不是让盘面每次从零重排。
本项目已经有这个概念的雏形（`page-residency`、`_yielded_goals`）——
**问题在于量级**：40 分对 260 分，等于没有。

**具体候选（进入 §67 Design Review 时再定，不在此拍板）**：
1. 让"处于多步序列中间"成为一个**显式状态**（而不是靠 40 分的页面激进去近似）；
2. 或把 residency/commitment 的量级提到与 `base` 同阶；
3. 或让 `DISCOVER_QUICK_PANEL_TASKS` 的 `base=260` 不再对"别的目标正在用这个面板"无感
   —— 这正是搜索来源 ⑤ 说的**成本归属**（"track which agent spent which credit on which resource"）。

**我倾向 3**：它同时解决来源 ⑤ 点名的问题，且是三者中唯一**不让任何目标受损**的
（1 和 2 会让"新目标"更难进来，可能换来新的饥饿 —— §36/§38 要求同时证明安全与活性）。

**仍未量、且定值前必须量的**：`base=260` 是怎么来的（哪个常量/规则给的），
以及 `DISCOVER_QUICK_PANEL_TASKS` 是否**真的需要**每次重开面板（若它的 progress 只在第一次成立，
那问题是"它该被标记为已服务"而不是"它不该赢"）。


## 已废止的首选修法（留档，**勿采用**）

搜索产物当初写的是：

> **首选：在排名选择处加"滞回/死区 + 最短驻留"**，取自来源 ①②④ 的共同处方，
> 且接现有机制（`runner_up_gap` 已在记）而不是新建归属层。

**为什么废止**：死区要对准"两个争用者之间的距离"，而 `runner_up_gap` 量的是
"第 1 名与第 3 名之间的距离"（第 2 名始终是 `CLAIM_EXPLORATION_IDLE`）。
实测切换时该分差中位 142.2 —— **按它加死区会挡住所有正常切换，却完全不碰这个缺陷。**

**"最短驻留"这一半仍然有效**（来源 ①②③ 都开这一味），但它必须接在
**"目标处于多步序列中间"这个显式状态**上，而不是接在一个分差阈值上。
见上一节的"修法方向"。
