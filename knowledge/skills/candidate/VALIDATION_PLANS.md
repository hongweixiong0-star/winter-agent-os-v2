# candidate/ VALIDATION_PLANS.md — CANDIDATE 池的 live 验证计划（r201）

> 目的：把 `knowledge/skills/candidate/` 的"待验证"变成**可执行清单**——每份计划写明
> **验证目标 / 需采事实 / 成功判据 / 操作与风险 / 停止条件**（对应指令 §2 的七要素精神）。
> 本轮先行 6 份（ARENA×3 + LABYRINTH×3——同为"每日免费次数"类高频玩法）。

## 共同前置（六份共用一个瓶颈）

**入口语义模板未制作**：`BTN_OPEN_ARENA` / `BTN_OPEN_LABYRINTH` 在 `vision.py` 中**无定义**
（grep 已核）。⇒ 每份计划的第一块都是 **"定位入口 → 制作模板"**。
**入口定位法（按序）**：① 目标页/首页 observe 全 OCR；② 已知容器（探险/活动/每日任务）内找；
③ 外部先验（workflow_priors 已存 arena-wsco / wosguru-labyrinth）；④ 仍不得 → `NEEDS_ENTRY` 挂起。

## 1. OPEN_ARENA

- **验证目标**：`BTN_OPEN_ARENA` 的真实位置与外观；HOM→ARENA 页面转移可复现。
- **需采事实**：入口所在页（HOME 或二级面板）；点击后落点页面（`page_is_arena` 判定依据：页面特征元素）。
- **成功判据**：连续 2 次 `page_is_arena` 为真（含落点页截图）。
- **操作与风险**：仅"找入口+打开"（**不开战**）；低风险。
- **停止条件**：3 次尝试未现入口 → NEEDS_ENTRY 挂起（外部先验除外）。
- **背景事实（外部先验）**：Arena=Furnace Lv.8+；每日 ~5 免费次数；需预设防守阵容。

## 2. SELECT_ARENA_OPPONENT

- **验证目标**：对手卡（`ARENA_OPPONENT_CARD`+`POWER`）的读取与"高胜率选择"可执行。
- **需采事实**：对手列表形态（数量/每卡字段）；`防守阵容查看`路径（FAQ：点头像）。
- **成功判据**：选中后有明确的"被选中"视觉态（opponent_selected）。
- **操作与风险**：只读 + 选择（不消耗次数）；低风险。
- **停止条件**：列表字段缺失关键数值 → 记 `POWER_UNREADABLE`。

## 3. START_ARENA

- **验证目标**：`BTN_ARENA_CHALLENGE_FREE` 存在；免费次数可见且≥1；开战被系统接受。
- **需采事实**：免费次数计数控件（OCR 计数器）；开战后状态（战斗/结算）。
- **成功判据**：`battle_started`（有战斗页/结算页证据）**且**次数计数 −1。
- **操作与风险**：**消耗 1 次"免费"次数**（符合"用免费次数"目标；`defer_if`：只提供付费刷新时退避）；**不买任何付费项**。
- **停止条件**：只出付费按钮 / 次数不可见 → 退避（spec 已声明 defer_if）。

## 4. OPEN_LABYRINTH

- **验证目标**：`BTN_OPEN_LABYRINTH` 位置与外观；HOM→LABYRINTH。
- **需采事实**：入口页；落点页特征（`page_is_labyrinth`）。
- **成功判据**：连续 2 次页面转移为真。
- **操作与风险**：仅打开；低风险。
- **停止条件**：3 次未现 → NEEDS_ENTRY。
- **背景事实（外部先验）**：wosguru 注 2026-04 迷宫更新（解锁/ZONE 名/次数/重置态需 live 读）。

## 5. READ_LABYRINTH_ATTEMPTS

- **验证目标**：次数计数器可 OCR（`LABYRINTH_ATTEMPTS`）；**不同重置态**下的读数稳定。
- **需采事实**：计数器位置样例（≥2 帧）；重置前后（如可得）。
- **成功判据**：`attempts_known` 且与 UI 视觉一致（交叉核读）。
- **操作与风险**：纯只读。
- **停止条件**：计数器不可稳定读 → 记 `COUNTER_UNREADABLE`。

## 6. START_LABYRINTH

- **验证目标**：`LABYRINTH_START` 可执行；免费次数扣减与 MARCH/战斗页转移。
- **需采事实**：开战前/后帧；次数 −1 或 `attempt_started` 证据。
- **成功判据**：`attempt_started` + 状态变化证据。
- **操作与风险**：消耗 1 次免费尝试；不付费。
- **停止条件**：同 START_ARENA 的 defer_if。

---

**执行序（下批起）**：① ARENA 入口（v3：按定位法①-③——**含 wosguru 迷宫页对新假设的复核**）
→ ② 模板制作（ui-asset-pipeline）→ ③ 按 1→3 顺序真机验证 → ④ Labyrinth 同型。
**入册条件**（沿用现有生命周期）：live_evidence 非空 + success_conditions 两次复现 → 提交注册评估。

---

# 批 2（r202）：巨熊×3 / 联盟活动×3 / VIP / 免费奖励 —— 8 份追加计划

> 选批依据：巨熊=生产宪法最高优先；ALLIANCE_TIMED_EVENTS=BLOCKED(0%)；EVENT_MINIMUM=17%；
> CLAIM_FREE_REWARDS=DEGRADED。**与已有资产联动**：JOIN_BEAR_RALLY ↔ `knowledge/combat/bear_ui_checklist.json`
> + `timed-event-readiness`（T-30/15/5/1 时序）；本批验证应与该清单**合并证据**，不另起炉灶。

## 7. JOIN_BEAR_RALLY（最高优先）
- **目标**：验证三判据（`target rally displays MARCHING` / `member avatar appears in rally` / `special march count increases`）至少在 1 次真实加入中同时成立。
- **需采事实**：集结条目态（未满/已满/已出发）；加入按钮与人数/倒计时；加入后 MARCHING 帧；special march 计数前后。
- **成功判据**：≥2 判据同时为真（照片级）；计数 +1 为硬核对。
- **风险**：**加入集结=战斗性动作**（合法目标为"参战"，符合宪法第七条）→ 仅在**巨熊已开放**时执行；**不点付费（加速/买队列）**。
- **停止**：集结已满/已出发（换目标）；2 次未现 MARCHING → 记 `JOIN_NOT_PROVEN`。

## 8. PREPARE_BEAR_MARCH
- **目标**：`MARCH_QUEUE` 可读、`required_march_available` 判据成立（**参战前队列可用性**）。
- **需采事实**：队列占用数/上限（阅读器输出）；与 bear 参与的关系。
- **成功判据**：读数与 UI 计数器交叉一致（≥2 帧）。
- **风险**：纯只读。**停止**：读数不稳 → `QUEUE_UNREADABLE`。

## 9. READ_BEAR_TIMER
- **目标**：`BEAR_TIMER` 读数成立（`bear_start_time_known`）。
- **需采事实**：入口（ALLIANCE/EVENT）；倒计时文本；**只在客户端真的显示时间时才记录**（否则 UNKNOWN——宪法）。
- **成功判据**：OCR 时间两次一致（±1 分钟内）。
- **风险**：纯只读。**停止**：界面无时间 → UNKNOWN（记录"未显示"事实本身）。

## 10. CHECK_ALLIANCE_EVENT
- **目标**：联盟活动入口与身份/时间读取（`event_identity_and_timer_known`）——**ALLIANCE_TIMED_EVENTS 的开门砖**。
- **需采事实**：联盟页内"活动"区；活动名/阶段/倒计时。
- **成功判据**：一次读取同时得到"身份+时间"。
- **风险**：纯只读。**停止**：无活动区 → 记录布局事实。

## 11. READ_ALLIANCE_EVENT_TIMER
- **目标**：`ALLIANCE_EVENT_TIMER` 稳定读数（`remaining_time_known`）。
- **需采事实**：计时器位置样例 ≥2 帧。
- **成功判据**：两次读数递进一致。
- **风险**：纯只读。**停止**：`TIMER_UNREADABLE`。

## 12. CLAIM_EVENT_TIER
- **目标**：`EVENT_TIER_CLAIMABLE` 识别 + 领取后 `tier_state_is_claimed`。
- **需采事实**：可领取态的视觉（高亮/红点）；领取前后 tiers 状态。
- **成功判据**：**只能领"可领取"的层**；领取后该层态变化（照片级）。
- **风险**：领取=正收益（合法）；**不点任何变体付费按钮**。**停止**：无可领取层（记录为正常态）。

## 13. OPEN_VIP
- **目标**：`BTN_OPEN_VIP` 位置；HOME→VIP。
- **需采事实**：入口元素（**可能在右缘/钱包区**）；落点页特征。
- **成功判据**：连续 2 次页面转移为真。
- **风险**：**VIP 页=付费内容页**：**只开页、只读、只领明确免费的**（`CLAIM_VIP_FREE` 另验）；**严禁**任何购买点击。
- **停止**：入口 3 次未现 → NEEDS_ENTRY。

## 14. CLAIM_FREE_REWARD（DEGRADED 修复候选）
- **目标**：`FREE_LABEL+CLAIM_BUTTON` 的识别与 `claim_state_changed`；**优先复核既有 DEGRADED 证据**。
- **需采事实**：免费标签样例（多容器：HOME/EVENT/VIP/ALLIANCE）；领取后态。
- **成功判据**：状态变化照片级 + 与 `claim_feedback` 交叉。
- **风险**：领取=正收益；**先查 FREE 标识**（无 FREE 不点）。**停止**：无免费可领（正常）。
