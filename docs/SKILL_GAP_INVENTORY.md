# SKILL_GAP_INVENTORY.md — 统一缺口清单 v1（2026-10-16）

> 生成：WorkBuddy 会话（r190 盘点批）· 依据：**真实工作区读取 + 真实工具运行**（非文档照抄）
> 数据源：`SKILL_COVERAGE.md`/`SKILL_CATALOG.md`（口径）· `tools/full_auto_coverage_audit.py`（run）·
> `tools/build_capability_coverage.py`（run）· `learning/runtime_snapshot.json`（运行态）·
> `knowledge/skills/`（31 spec）· `knowledge/goals/`（3 映射）· `capability_bootstrap`（经测试文件确认接口）

## 0. 运行态（r191 修正 —— 不是"断链"，是设计内的用户闩锁）

> **修正说明**（2026-10-16 第二轮调查，`learning/MODE_STATE.json` + `learning/control_panel/latest.log`/`panel.log` 为证）：
> AUTO 停轮**不是缺陷**——是模式状态机的正常转换。

| 项 | 实测值 |
|---|---|
| 面板进程 | **活着**（PID 15300"无尽冬日 AI 指挥中心"） |
| **模式** | **`MANUAL` / initiator=`USER` / `user_latch=true`**（`MODE_STATE.json`） |
| 切 Manual 时刻 | **10-15 20:37:17**（reason："work buddy 使用"；expected 180000s） |
| AUTO 停轮机制 | 面板日志原文：**"⏹ 未进入下一轮：机器归 WorkBuddy 使用（Manual 模式）：AUTO 不进入下一轮，交还后自动恢复"**（20:38:00） |
| 三次切号失败 | 20:35 `SOURCE PROFILE IDENTITY NOT VERIFIED` → 20:36 `ROLE MANAGEMENT ENTRY NOT OBSERVED` → 20:37 `TARGET ROLE HOME NOT OBSERVED`（**与采集会话操作时段重叠**——均为观察被干扰，非代码缺陷） |
| 历史同型先例 | 10-11 条目原文："用户指令把机器交给 WorkBuddy 采集玩法证据库缺失界面的实机截图"（**与本日情形同类**） |
| 恢复条件 | **用户在控制台交还**（`user_latch` 需用户发起；10-07 有"用户明确指令→WorkBuddy 代切回"先例）——**当前用户指令="不交还、不冻结" ⇒ 保持 MANUAL 为预期状态** |

⇒ **原"P0 运行断链"条目撤销**（不虚报）。真正 P0 回到 §3 的 `SPEND_STAMINA_ON_BEAST` 缺陷。

## 1. 七类缺口（指令分类 × 实测映射）

| # | 类别 | 实测发现 | 量 |
|---|---|---|---|
| 1 | **玩法存在，无 Skill** | BLOCKED 4 Goal 的**无实现 capability**：`USE_FREE_ARENA_ATTEMPTS`（3 个：OPEN/READ/SELECT）+ `LABYRINTH_DAILY`（全）+ `TRAVEL_SUPPLY`（全）+ `ALLIANCE_TIMED_EVENTS`（3 个）+ `EVENT_MINIMUM_GUARANTEE` 的 5/7（OPEN_PAGE/READ_RULES/READ_PROGRESS/READ_TIMER/CLAIM_TIER）+ `PARTICIPATE_BEAR` 的 2 个（CHECK_BEAR_PHASE/SELECT_TROOP_PRESET）+ `DAILY` 的 READ_DAILY_PROGRESS | **~15 capability** |
| 2 | Skill 存在，未注册 | **复核通过：0**（r200 源码级对表：skills.py 注册 **136** 个；capability_skill_map 编排引用 38 个；`map 有但 registry 无`=**0**。其余 98 个为原子/工具层 skill——正常分层，非断链） | **0** |
| 3 | 已注册，无完整执行链 | **CANDIDATE 类**（有实现、live 未验证）：READ_INTEL_LIST / VERIFY_GATHERING / START_BUILD / OPEN_RESEARCH / START_RESEARCH / DISMISS_MAIL_REWARD / ALLIANCE_TECH_CONTRIBUTE / PLAY_NORMAL_FISHING_LEVEL / READ_FISHING_STATE(LIVE_TRIED 1-0) 等 | **~9-12** |
| 4 | 缺页面/控件证据 | bootstrap projection `MISSING_OBSERVATION=63` + BLOCKED-"无实现"面 | 63（投影） |
| 5 | 缺前置/Verifier/Recovery | ⭐ **bootstrap projection `MISSING_VERIFIER=115`**（最坏情况投影——**最大缺口面**） | 115（投影） |
| 6 | 未接 Goal/Scheduler | `BOARD_ONLY_STATUS=5`（明细待展）+ `NEVER_TRIED_GOALS=4`（KEEP_RESEARCH / MOBILIZATION_ICEFIELD / FISHING×2）；3 个 `ON_BOARD_OBSERVATION_ONLY_NO_SKILL`（LABYRINTH/FISHING_TOURNAMENT/ARENA——**chooser 打分但 skills=0**） | 5+4+3 |
| 7 | 执行失败（已有能力） | **DEGRADED 5**：⭐`SPEND_STAMINA_ON_BEAST`（**189 试 / 41 成 = 22%**）· `OPEN_BUILDING_PAGE`（132/100）· `DISMISS_DAILY_REWARD`（37/27）· `DISMISS_FREE_REWARD_POPUP`（71/56）· Goal 级 `CLAIM_FREE_REWARDS`（DEGRADED） | 5 |

## 2. 四层覆盖率（`build_capability_coverage.py` 实测）

- Goal 20：**FULLY_LIVE_VERIFIED 2**（TRAINING / EXPLORATION_IDLE）· PARTIAL 9 · NEVER_TRIED 4 · BLOCKED 4 · DEGRADED 1
- **mean implementation 70.8% / mean live 40.1%**
- 最高 live：MARCHES 86% / INTEL 83% / MAIL 75% / TRAINING 100%
- 最低 live：RESEARCH 0% / MOBILIZATION 0% / FISHING×2 0% / ARENA·LABYRINTH·TRAVEL_SUPPLY 0%（BLOCKED）/ BEAR 25% / EVENT 17% / ALLIANCE_TIMED 0%

## 3. 优先级计算（指令 §5 顺序 × 实测）

| 序 | 项 | 理由 |
|---|---|---|
| **P0** | `SPEND_STAMINA_ON_BEAST` 22% 的**确定性缺陷** | 指令第 1 优先=修复已有能力的确定性缺陷；且它是高频消耗（189 次） |
| **P1** | 3 个 `ON_BOARD_OBSERVATION_ONLY_NO_SKILL` 的**接线缺陷**（chooser 可选中却 skills=0） | 指令第 1 优先的"接线"面；LABYRINTH/FISHING/ARENA |
| **P2** | CANDIDATE 类的 **Verifier/live 补全**（~9-12 个） | 指令第 3 优先 |
| **P3** | BLOCKED 类的**按需采集**（ARENA/LABYRINTH/EVENT 规则面的页面证据） | 指令第 4 优先（定向采集） |
| **P4** | NEVER_TRIED 低频（RESEARCH 被队列阻塞=环境性 / FISHING 需活动窗口） | 指令第 5 优先 |
| **P0'** | AUTO 运行时重启 | **待授权与时机**（设备当前归采集会话；schtasks 被沙箱禁止）——**不做假设** |

## 4. 下一步（自动执行建议）

1. **P0 根因**：读 `SPEND_STAMINA_ON_BEAST` / `SELECT_BEAST_TARGET_MAMMOTH` 的失败 episode 与 Verifier 日志——**定位 22% 的确定性缺陷**（离线可做）
2. **P1 接线**：读 3 个 no-skill goal 的 `goal_capability_map` 条目与 chooser 路径——判断是"缺 step 映射"还是"缺 skill 实现"
3. **类 2 复核**：registry × capability_skill_map 对表（确认"未注册"是否真为 0）

---

## 5. P0 根因调查（r191-195，离线批 —— 结论 v1）

**对象**：`SELECT_BEAST_TARGET_MAMMOTH`（156 条：12 成 / 144 败；全部在 10-05~10-11）。

**调查链（全部有据）**：

| 步骤 | 发现 | 证据 |
|---|---|---|
| 1. 失败码分布 | 143 条 `BEAST_TARGET_SELECTION_NOT_PROVEN`（>99%） | episodes.jsonl 统计 |
| 2. 时间分布 | 93% 集中于 10-10（89败+12成）与 10-11（45败）；全时段散布 | 按天/按时刻统计 |
| 3. 两种失败形态 | ①0.06-0.11s 无动作型（10-05 早批，**已被 7e1711f7「label not sprite」修复**——before 侧现在正常）②14-27s 执行后型（10-10/11 全部） | duration + `recognition_error` |
| 4. 执行后型统一形态 | `verifier_evidence={'before_visible': True, 'after_card': False}` ——**tap 已发出、卡未开** | verifier_evidence 字段 |
| 5. 帧证据 | before 帧：猛犸就在画面中（标签「5 猛犸象」、tap 点正确）；**16.7s 后 after 帧：猛犸原位未动、未消失**——不是"目标跑了" | step_011 before/after 帧（worktree dataset） |
| 6. 成功对照 | 成功均 **~4.5s**（识别→tap→卡开）；**成簇出现**（06:44×2、18:45-48×10 连发） | 12 条 SUCCESS 全量 |
| 7. 排除项 | **版本差异✗**（同一 revision `abe67449` 下 83败/12成）·时段✗（失败全天）·角色✗（两角色都有败/成）·动物移动✗（帧证） | revision×result 矩阵 |

**结论（v1·诚实版）**：**不是单点代码缺陷**——是"同一代码在条件不齐时的执行侧高拒绝率"（88%）：
- before 侧（识别/点位）已由修复保障 ✓
- **after 侧（"点击→卡开"）的物理条件**是最可疑层：候选=①点击落点语义（label 框中心 vs 猛犸本体可点区）②执行通道瞬态（MAA/ADB "connect not same day" 类）③游戏侧"该帧猛犸可选中性"
- **离线证据已到头** ⇒ **升级为真机校准项**（§6）

## 6. 真机校准单（P0，按指令 §3 五要素 · 待执行）

- **对应 Skill 缺口**：`SELECT_BEAST_TARGET_MAMMOTH`（after_card 88% 失败）
- **需要确认的具体事实**：在**当前客户端**上——①点击猛犸**标签框中心**能否开卡；②点击**猛犸本体**能否开卡；③开卡后的控件形态；④连续 3 次点击的开卡率
- **预期采集结果**：一组序列帧（MAP+目标可见 → 点击 → 卡片打开），用于校准 `tap_norm` 语义与"可选中性"判据
- **允许的操作与风险**：地图导航 + 点猛犸（**开卡不耗体力**——低风险）；**不点**「出征」/「集结」；不碰付费；每次操作前重识别
- **成功及停止条件**：成功=拍到"点击→卡开"完整链（≥1 次）；**停止=3 次未开卡或任何异常页面**


---

## 7. 进展更新（2026-10-16 午后）：EVENT_MINIMUM_GUARANTEE 实现覆盖 **17% → 83%**

- **入产链**：`READ_REGULAR_EVENT_CARD`（卡面读取器）注册（CANDIDATE + verifier 绑定）+ `OPEN_EVENT` 注册；
- **映射**：`goal_capability_map` 的 READ_EVENT_{RULES,PROGRESS,TIMER} 三 capability alternatives 更新；
- **coverage 实测轨迹**：17%（基线）→ 67%（r238）→ **83%（r239，5/6）**；
- **余 1/6**：`CLAIM_EVENT_TIER`（领取控件为图形——待图形层批次）；
- **live 覆盖仍 17%**（正确——读取器只跑过回放；真机数据待 AUTO 恢复或自然帧）。

---

## 8. 发现：基线测试滞后（r246——两链改动**无关**的 12 个失败）

**现象**：较大回归集（14+2 文件）跑出 **12 failed / 135 passed**。

**归因（证据链）**：
- 失败**全部为"源码字符串断言"类**（如 `test_alliance_gifts_chain` 断言 vision.py 里存在
  单行 `if match("PAGE_ALLIANCE") and (match(...) or ...):`——而现状已是等价的多行形态）；
- **两链全部 commit（52 个）从未触碰 `vision.py`**（`git log --name-only` 核）；vision.py 亦无未提交修改；
- ⇒ **结论**：这是**早于本时段的基线滞后**（源码演进后旧测试未同步），**与 EVENT/联盟两链改动无关**。

**处置**：不擅自改测试（非本战区；测试是前会话的资产）——**列入 backlog**：
"基线滞后测试同步批次"（需先分清'应更新测试'与'源码应回退'两种情形，逐条裁定）。
