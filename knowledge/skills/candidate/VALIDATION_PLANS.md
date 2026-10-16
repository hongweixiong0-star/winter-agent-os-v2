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


---

# 批 3（r203）：联盟活动链 **首验实测结果**（更新 CHECK_ALLIANCE_EVENT）

> 实测（10:18-10:20，设备 [DIW]xhw；MAA 通道 4/4 成功）：

**已证实**：
- **联盟页（ALLIANCE）直接列出今日活动**（原文：`1.【联盟大作战】&【军备竞演】` `2.【联盟争霸赛】`
  `10月16日·周五`）⇒ `event_identity` 判据 **✓**（免点击可读）。
- **「联盟战争」面板**=三页签 `集结` / `单人` / `活动`：
  - `集结` 页实测：正在进行的集结（**等级8 深渊龙龟**，[DIW]阿九发起，`1/15`，倒计时 `00:02:52`）+
    **`开启后自动加入冰原巨兽集结`（自动加入开关）** ← **ALLIANCE_MOBILIZATION_ICEFIELD_BEAST 的现场**；
  - `活动` 页实测：**`当前暂无战事`**（空态）⇒ **timer 判据当前无法验（无活动=天然无 timer）**，如实记录。
- **`BTN_ALLIANCE_WAR` 模板已存在**（`vision.py:2461`——即"熊入口可见性"判定所用）⇒
  CHECK_ALLIANCE_EVENT 的入口语义**已具备**（无需新模板）。
- **新页面候选**：「联盟战争」面板（三页签）——现被记为 `UNKNOWN`；**待注册**（下次收编批次，
  附本轮帧 `dataset/exploration/20261016T021932` 等 4 组）。

**刷新后的 CHECK_ALLIANCE_EVENT 判据**：identity（联盟页列表）✓ 实测；timer=**待有活动时**再验。

---

# 批 3（r205）：其余 19 份 · 按族并入（全部候选至此覆盖）

> 覆盖：CLAIM_VIP_FREE / READ_FREE_ATTEMPTS / OPEN_BUILDING / OPEN_RESEARCH / OPEN_TRAINING /
> PROMOTE_TROOPS / READ_DAILY_PROGRESS / OPEN_EVENT / READ_EVENT_{LIST,PROGRESS,REWARD_TIERS,RULES,TIMER} /
> READ_INTEL_LIST / SELECT_INTEL / EXECUTE_INTEL / JOIN_POLAR_TERROR_RALLY / VERIFY_ARENA_RESULT /
> VERIFY_LABYRINTH_RESULT。

## 15. EVENT 读取族（7 份——EVENT_MINIMUM_GUARANTEE 的"读取面"开门砖）
`OPEN_EVENT`（EVENT 页导航）+ `READ_EVENT_{LIST,RULES,PROGRESS,TIMER,REWARD_TIERS}`（五读取）。
- **目标**：读面五件套逐一成立（该 goal 的 MISSING 恰在此）。
- **需采事实**：活动页每张卡打开后的"规则/进度/时间/奖励层"文本样例（≥1 活动全链）。
- **成功判据**：五读数互不矛盾且与视觉交叉（照片级）。
- **风险**：纯只读为主；**不点任何"领取/购买"**（领取另由 CLAIM_EVENT_TIER 验）。**停止**：页面无对应区 → 记录布局事实。

## 16. INTEL 族（3 份——注意与已 VERIFIED 的 INTEL 链并存）
`READ_INTEL_LIST` / `SELECT_INTEL` / `EXECUTE_INTEL`。
- **目标**：与既有 VERIFIED 链（OPEN_INTEL→SELECT_INTEL_BEAST_MISSION→…）**对照**，确认这 3 份是"同链候选实现"还是"更泛化实现"；**先对表再验**（别造第二条链）。
- **需采事实**：灯塔 Intel 列表页元素；选择行为差异点。
- **成功判据**：若与既有链重复 → **标记 `SUBSET_OF_EXISTING`**（撤销候选而非重复建设）；若更泛化 → 按 plan 验。
- **风险**：只读+选择；**停止**：确认冗余即止。

## 17. 生产族（5 份——与既有 VERIFIED 重叠度核验）
`OPEN_BUILDING` / `OPEN_RESEARCH` / `OPEN_TRAINING` / `PROMOTE_TROOPS` / `READ_DAILY_PROGRESS`。
- **目标**：**先核冗余**（BUILDING_UPGRADE/TRAIN_TROOPS/OPEN_DAILY 已 VERIFIED）——这些候选是"同功能候选实现"吗？
- **成功判据**：分组标记：`SUBSET_OF_EXISTING`（撤）/ `NEW_CAPABILITY`（按 plan 验）。
- **风险**：核验以**源码+文档对照**为主（零设备）；仅 NEW 才排真机。**停止**：分组完成即止。

## 18. JOIN_POLAR_TERROR_RALLY
- **目标**：与 JOIN_BEAR_RALLY **同构核验**（北极恐怖 vs 巨熊）——复用其判据（MARCHING/头像/计数）。
- **需采事实**：Polar Terror 集结条目（开放时）；与 bear 集结的界面差异。
- **风险**：同 bear 规则（开放时才做、不付费）。**停止**：同 bear。
- **注**：其 goal（ALLIANCE_MOBILIZATION_ICEFIELD_BEAST 类）与深渊龙龟现场（r203）关联。

## 19. VERIFY 双子（VERIFY_ARENA_RESULT / VERIFY_LABYRINTH_RESULT）
- **目标**：两战斗的结果判据（页态/计数/记录）。
- **依赖**：**在 START_ARENA / START_LABYRINTH 验证之后**执行（本双子紧随其后）。
- **成功判据**：结果态与次数计数互证（照片级）。
- **风险**：只读（结果页）。

## 20. VIP·FREE 双子（CLAIM_VIP_FREE / READ_FREE_ATTEMPTS）
- **CLAIM_VIP_FREE**：**VIP 页"免费"项**的识别与领取（**同 OPEN_VIP 的缰绳：严禁购买**；无 FREE 标识不点）。
- **READ_FREE_ATTEMPTS**：各玩法"免费次数"读法的**泛化器**（Arena/Labyrinth/VIP 共用计数读法）——
  以 ARENA/LABYRINTH 的实采为训练集，**先读数后泛化**。

---

# 批 3·核验实测（r205）：INTEL 族 / 生产族冗余对表结果

> 方法：spec 语义 vs `skills.py` 注册表逐条对表（零设备）。**结论先行：8 份中 7 份为既有能力重述。**

| candidate | 既有注册对照 | 判定 |
|---|---|---|
| `READ_INTEL_LIST` | **同名同 id 已注册**（skills.py:222, CANDIDATE） | **SUBSET_OF_EXISTING**（重复文件） |
| `SELECT_INTEL` | SELECT_INTEL_BEAST/FIREBEAST/RESCUE + `SELECT_INTEL_PIN`（均已注册） | **SUBSET_OF_EXISTING** |
| `EXECUTE_INTEL` | EXECUTE_INTEL_RESCUE_SURVIVORS 等链（已注册） | **SUBSET_OF_EXISTING** |
| `OPEN_BUILDING` | OPEN_TASK_FROM_QUICK_PANEL_BUILDING（已注册） | **SUBSET_OF_EXISTING** |
| `OPEN_RESEARCH` | **同名同 id 已注册**（skills.py:374, CANDIDATE） | **SUBSET_OF_EXISTING**（重复文件） |
| `OPEN_TRAINING` | OPEN_INFANTRY_TRAINING / OPEN_POWER_OVERVIEW（已注册/CANDIDATE） | **SUBSET_OF_EXISTING** |
| `PROMOTE_TROOPS` | TRAIN_TROOPS（已 VERIFIED，含 promote） | **SUBSET_OF_EXISTING** |
| **`READ_DAILY_PROGRESS`** | **注册表无**（同时是 `DAILY_ACTIVITY_TARGET` 的 BLOCKED 面） | **⭐ NEW_CAPABILITY（真缺口）** |

**处置**：
1. 7 份 SUBSET：**不做真机验证**（计划 16/17 达成预设目的——防止重复建设）；
   候选池清理（标注/归档这 7 份）列入**下批**（另有 33 份全池的同类对表可一并做）。
2. **`READ_DAILY_PROGRESS` 升为当前候选池的第 1 优先真机项**（每日面板的"活跃度计数+奖励层"读取——
   DAILY_ACTIVITY_TARGET 的 75%→100% 缺口所在）。

---

# 全池对表（r207）：33 份的最终分层

**方法**：名字级（skill_id vs `skills.py` 注册表全量）+ 语义级（r205b 已做的 8 份对表）。

| 层 | 数量 | 明细 |
|---|---|---|
| **强重复**（同名已注册） | **2** | `OPEN_RESEARCH` / `READ_INTEL_LIST`——**同名同 id 的重复文件**；清理批次直接归档 |
| **既有链重述**（异名但覆盖） | **5** | `SELECT_INTEL` / `EXECUTE_INTEL` / `OPEN_BUILDING` / `OPEN_TRAINING` / `PROMOTE_TROOPS`（r205b 判定） |
| **有效候选**（待 live 验证） | **26** | ARENA×4 · LABYRINTH×4 · BEAR×2 · POLAR×1 · EVENT 读取×6 · 联盟活动×2 · CLAIM 类×3 · VIP×1 · FREE×2 · DAILY_PROGRESS×1 |

**清理批建议**（下批执行，仅标注不删除）：7 份冗余 → `lifecycle: SUPERSEDED`（附录"被谁覆盖"），
原文保留（审计可回溯）；26 份有效候选维持 `CANDIDATE`。

---

# 批 3·EVENT 读取族 —— 首轮素材实测（r209）

> 实测（10:28-10:31；MAA 通道全程 ±1 次语法失误）：

**已得素材（联盟大作战卡）**：
- **READ_EVENT_PROGRESS**：`我的积分：0` ✓（读取器素材在案）
- **READ_EVENT_REWARD_TIERS**：档次序列 `100 / 37,500 / 75,000 / 125,000 / 187,500` ✓
- **READ_EVENT_RULES**：任务表原文（`护送1次任意品质商旅 10,000点积分` / `拦截1次任意品质商旅 10,000点积分` /
  `领主装备最高评分提升1点（不包含领主宝石） 22点积分`）✓
- **READ_EVENT_LIST**：页签行（常规活动/联盟大作战/凛风攻城战）+ 卡片列表 ✓
- **READ_EVENT_TIMER**：**尚未捕获**（本卡时间区未现于当前视口；待下轮滚动/或其它卡）

**附带捕获（新界面资产候选）**：
- **「上一场赛事取得胜利」结算弹窗**（#4298 vs #4293 · 40,178,410 vs 26,567,867 · `全场最佳 [DIW]向左走` ·
  底部 `点击任意位置继续`）——**注意**：其"点击任意位置"用 tap 两次未关，**BACK 有效**（修维/知识：该弹窗由 BACK 关闭更可靠）。
- 「联盟大作战」卡底部按钮：`历史战绩 / 奖励 / 排行榜`。

---

# 批 3·EVENT 读取族 —— 素材齐备确认（r210）

**READ_EVENT_TIMER ✓**：「凛风攻城战」卡实测——**阶段名+倒计时**：`侦察阶段 13:27:18`；
同伴素材：描述（`调配部队攻守据点，与对手联盟一决胜负！`）、按钮（`奖励/商店/排行`）、
`先锋3阶 x1`、`等级1`、`前往侦察`（行动按钮——**只读采集未点**）。

**⇒ EVENT 读取族 5/5 素材全部到手**：
`LIST`（页签行；**且实测到列表动态**：雪原商路从内容区移入页签行=活动轮换/重排）
· `RULES`（任务表）· `PROGRESS`（我的积分）· `REWARD_TIERS`（五档序列）· `TIMER`（阶段+倒计时）。

**下一站**：为 5 份 READ_EVENT_* 起草读取器规格（vision/OCR 层接线候选）——**待下批**
（本批保持"素材在案"，不动生产代码）。
