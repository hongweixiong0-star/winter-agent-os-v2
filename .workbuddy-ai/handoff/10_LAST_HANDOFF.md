# 10 — LAST HANDOFF

> 本文件是「上一个账号停在哪里」的快照。
> **它只是恢复加速器，不是唯一事实源。** 如果上一个账号突然断线没来得及写它，
> 新账号必须能仅靠 git / episodes / evidence / runtime snapshot / logs / registry /
> goal state 重建全部事实——`AUTO:last_handoff` 块正是这样生成的。
>
> `AUTO:last_handoff` 由 `tools/update_workbuddy_handoff.py` 重写；手写块不会被覆盖。

<!-- AUTO:last_handoff -->
HANDOFF TIME: 2026-09-17T08:51:23+00:00
LAST GOOD COMMIT: e4fd245
WORKING TREE: 11 dirty file(s)
  ['M .workbuddy-ai/handoff/00_MASTER_RULES.md', ' M .workbuddy-ai/memory/2026-09-17.md', ' M .workbuddy/memory/2026-09-17.md', ' M learning/control_panel/latest.log', ' M learning/episodes.jsonl', ' M learning/executor_backend.jsonl', ' M learning/goal_state.json', ' M learning/runtime_snapshot.json', '?? knowledge/failure_patterns/architecture/', '?? tests/test_verifier_binding_audit.py']

WHAT FINISHED (machine-visible): 25 skills live verified, 29 stable, 123 commit(s) in history
WHAT LIVE VERIFIED: see 01_CURRENT_TRUTH.md section D (skills with >=1 production success)
WHAT NOT VERIFIED: 19 skills never executed, 10 never succeeded

CURRENT TASK: see 03_NEXT_ACTION.md
STOPPED AT: agent_state=IDLE stop_reason=mail_all_clear
LAST PRODUCTION EPISODE: {"skill": "OPEN_MAP", "result": "FAILURE", "recorded_at": "2026-09-17T08:48:22.009081+00:00", "episode_id": "20260917_164719_351898", "before_screenshot": "E:\\无尽冬日智能体\\dataset\\raw\\control_panel\\runtime_auto\\20260917_164719_351898\\20260917_164719_351898_step_001_before_20260917T084719820763.png", "after_screenshot": "E:\\无尽冬日智能体\\dataset\\raw\\control_panel\\runtime_auto\\20260917_164719_351898\\20260917_164719_351898_step_001_after_20260917T084739016698.png"}
TOP FAILURE: {"failure_type": "SEMANTIC_TARGET_NOT_VERIFIED", "count": 130, "recent": 14, "last_seen": "2026-09-17T04:45:23.361291+00:00", "dates": {"2026-09-12": 36, "2026-09-13": 37, "2026-09-14": 8, "2026-09-15": 15, "2026-09-16": 2, "2026-09-17": 1}, "undated": 31, "top_skills": [["SELECT_RESOURCE", 44], ["SEARCH_RESOURCE", 32], ["OPEN_MAIL", 13]]}
NEXT EXACT STEP: Implement the highest-leverage missing skill listed in `highest_leverage` inside knowledge/goals/capability_skill_map.json, then REPLAY -> LIVE -> VERIFY -> EVIDENCE.
DIRTY FILES: 11
TEST STATUS: not run by this script — run `python -m pytest tests -q`
LIVE STATUS: PASS (unexpected_worker_exits=15)

GIT SYNC (is the public mirror current?):
SYNC STATE at 2026-09-17T08:51:23+00:00
remote            : https://github.com/hongweixiong0-star/winter-agent-os-v2.git
branch            : main
local_head        : 92a6f27c9432d5917d5a8f3ebe2a761696ee08ad
remote_head       : 92a6f27c9432d5917d5a8f3ebe2a761696ee08ad   (local remote-tracking ref; run tools/git_sync.py status to refresh)
unpushed_commits  : 0   (behind: 0)
git_dirty         : True (11 path(s))
last_push_at      : 2026-09-17T08:40:26.595742+00:00
last_push_status  : PUSHED
verdict           : GitHub mirrors the local tree

KNOWN RISKS:
- Live Verified depends on screenshots that are NOT in git (see .gitignore); they are machine-local.
- `unexpected_worker_exits` is a BARE COUNTER WITH TWO WRITERS, both in tools/control_panel.py. The classified path counts only `WORKER_CRASH` and promises a traceback under learning/control_panel/crashes/; the unclassified fallback `_handle_runtime_error` counts EVERY non-fatal error whatever its cause. No crash reports exist and latest.log is 0 bytes, so the historical total cannot be read as 'worker crashes' and must not be zeroed.

DO NOT REPEAT:
- Do not re-derive resource-tab coordinates from memory; read the bracket anchor (vision.selected_resource).
- Do not assume no git history (it now exists) and never delete files by wildcard prefix.
- Do not pass a changed wire format into LiveRuntime.resolve(); use the `_semantic` accessor.
<!-- /AUTO:last_handoff -->


---

## 手写：人类补充（生成器读不出来的部分）

### 🔄 情报任务已做完 + 常驻循环自动化（第六轮，2026-09-14 17:00）— 读这一节就够了

> ⏸️ **最新状态覆盖本节（2026-09-15 18:37 GMT+8）**：**操作者已主动要求取消「情报定时循环」**，
> 当前自动化 **`43aef0ad-d5bc-4d79-9291-0a4da0b0dc27`「Winter V2 情报循环（每小时）」= `PAUSED`**
> （已用接口 `list` 复核）。**这是人为停用，不是 `0ap` 那个"说在跑其实没跑"的病，也不是它丢了。**
> ⇒ 看不到新的自动化 episode 时**先查 status**，不要当故障去重建；要恢复把 status 置回 `ACTIVE` 即可。
> 本节下面关于 id 的三次更正（`1a07567f` / `7c1c18c1` / `e3485d0c`）**都仍是有价值的教训**：
> 判断自动化是否存在只能靠**当次接口查询**。

操作者指令「循环进行，把情报任务做完再做其他任务」的执行结果：

1. **情报列表已排空**（`tools/run_intel_loop.py` 真机 3 轮全部 `intel_not_available`，exit 0；
   证据 `evidence/intel_loop_20260914_085752.log`）。任务在第五轮已全部消化：
   最后一个巨兽派出（-10 体力）、奖励已领、弹窗已关。
2. **下批任务在 ~23:51**（本地）：真机读到的刷新倒计时 `下次刷新：06:56:37`（16:54 时点）。
3. **常驻自动化**「Winter V2 情报循环（每小时）」：新任务出现即自动派出巨兽（-10 体力/次）、
   自动领取奖励；含付费控件硬边界。**操作者可通过 automations 界面暂停/删除。**
   ⚠️ **第九轮更正**：本节原先记录的 id `1a07567f-2868-4414-9010-2b411ae3a85d`
   **在自动化接口里查不到（not found），即它并不存在** —— 也就是说这段时间**没有任何无人值守在跑**。
   第九轮已用当前 id **`7c1c18c1-94ca-4051-a2ca-7a1614cb3979`**（每小时 `tools/run_intel_loop.py 6`）
   重建并置 ACTIVE。**以后要判断自动化是否真的存在，必须用自动化接口查询，不要只信 handoff。**
4. 顺手修掉 `parse_stamina_number` 的丢位缺陷（HUD 把 295 读成 29——OCR 把数字拆成
   `'29'+'9'+'5'` 三个重叠碎片，旧代码取第一个）。已几何合并修复 + 真机 fixture 回归。

### ✅ 情报巨兽链路已 LIVE VERIFIED（第五轮补齐，2026-09-14 16:28）

情报列表刷新出任务后，`run6` 一次跑通全链，**四步 verifier 全部 PASS**，episode 可追溯
（`episode_id = live_intel_full_run6`）：

| step | 技能 | 结果 | 关键证据 |
|---|---|---|---|
| 1 | `SELECT_INTEL_BEAST_MISSION` | SUCCESS | INTEL → POPUP/INTEL_BEAST_MISSION |
| 2 | `OPEN_INTEL_BEAST_TARGET` | **SUCCESS** | → BEAST，level 22（就是此前一直 `NOT_PROVEN` 的那一步） |
| 3 | `INTEL_BEAST_START_MARCH` | SUCCESS | → MARCH 编队页 |
| 4 | `DISPATCH_INTEL_BEAST` | **SUCCESS** | → MAP，`marches=['MARCHING']`，**体力 305→295** |

随后 `run7` 领取已完成任务奖励（修复后 SUCCESS）、`run8` 关掉奖励弹窗（SUCCESS），
情报列表清空后以 `intel_not_available` 停止（**exit 0**）。

**顺带纠正上一轮的一个错误猜测**：`BTN_BEAST_DISPATCH` 在旧帧上距离 36，我曾判断「很可能同样过期」——
**实测它是好的**，编队页派兵一次成功。那次距离是用**地图帧**量的，而它只在编队页出现，
属于测量对象选错。教训：没有对应页面的帧，就不要断言某个模板过期。

- **WHAT NOT VERIFIED（别当成已完成）**
  - 巨兽链路修复后只验证了 **1 次**完整派兵；`DISPATCH_INTEL_BEAST` 历史 12 次成功属于修复前。
    离 `STABLE` 还差样本。
  - 情报奖励领取修复后也只跑了 1 次。
  - 体力 350→295 中只有 **-10 可归因**（run6 派兵），其余 -45 仍无法归因（`04_OPEN_ISSUES.md` 0g）。
- **NEXT EXACT STEP**：情报下次刷新后（倒计时从 `07:22:25` 起算）再跑几次 `--goal INTEL`，
  把 `DISPATCH_INTEL_BEAST` 的样本量做上去。

---

### ⏱ 上一轮（第四轮）停止点

- **WHAT FINISHED**：修掉体力出口链路断裂的两层根因。
  1. 巨兽目标卡模板整体过期（`BTN_BEAST_START_MARCH` 距离 30 ≫ 阈值 8）→ 按真机帧重采。
     点击坐标没错，错的是「点完之后客户端把目标卡画在地图上，模板层认不出」。
  2. 情报列表「空」在视觉层没有分支 → 用实测证据（卡片=有 `前往查看`；空=只有 `下次刷新`）
     新增该状态，且**明确拒绝**用「模板没匹配」来推断空列表。
- **WHAT LIVE VERIFIED（有帧为证）**
  - 巨兽目标卡：该帧判为 `Page.BEAST`，beast 字段 = `{INTEL_BEAST_10, 大角鹿, 22, available, 推荐实力 5107044, 10}`，
    `verify_intel_target_open` 复算 **OK**，负向对照（普通地图）不误报。
    证据：`dataset/truth_audit/intel_beast_target_20260914/` + `tests/test_beast_target_card.py`（9 项）。
  - 情报空列表：真机 `run5` → `stop_reason=intel_not_available`、`list_read=True`、**exit 0**
    （此前是 `intel_state_unknown` / exit 2）。
- **WHAT NOT VERIFIED（别当成已完成）**
  - **巨兽链路仍未端到端跑通**：修好后情报列表恰好空了（`下次刷新 07:59:21` 已过未刷新），
    没有任务可点。**待列表出现任务后重跑 `run_live.py --goal INTEL`**，预期链路：
    `SELECT_INTEL_BEAST_MISSION → OPEN_INTEL_BEAST_TARGET → INTEL_BEAST_START_MARCH → DISPATCH_INTEL_BEAST`。
  - `BTN_BEAST_DISPATCH`（编队页派兵按钮）实测距离 **36**，**很可能同样过期但尚无真机帧可采**；
    一旦链路走到编队页就会暴露——届时应像本轮一样用真机帧重采，不要凭猜改坐标。
  - 体力 350→305（-45）无法归因（episode 流无对应记录），见 `04_OPEN_ISSUES.md` 0g。
- **NEXT EXACT STEP**：情报列表刷新出任务后，重跑 `--goal INTEL` 走到编队页；
  若 `DISPATCH_INTEL_BEAST` 失败，就用新帧重采 `BTN_BEAST_DISPATCH`。
- **DO NOT REPEAT**：不要用「模板没匹配」推断页面的**语义**（空/无任务/不可用）——
  本轮刚被模板过期坑过；语义判定必须有独立正向证据。

---

### ⏱ 上一轮（第三轮）停止点

- **WHAT FINISHED**：操作者的「体力优先 + 可随时撤回」策略从**声明**变成**可执行**。
  - 体力在地图上可观测（`HUD_STAMINA_ROI`，**必须单独 ROI OCR**，全屏会漏）。
  - 免费体力领取：新建 `OPEN_STAMINA_SOURCES` + `CLAIM_FREE_STAMINA`（都有 verifier）。
  - 撤回：拆成 `SELECT_MARCH_TO_RECALL` + `RECALL_MARCH`，都有 verifier，都已进
    `VERIFIED_ATOMIC`。
  - 删除「行军计数由常量编造」的旧行为（实测会把 6/6 报成 1/6 = 5 个假空闲槽）。
- **WHAT LIVE VERIFIED（有帧为证）**
  - **免费体力领取成功**：面板 `200/200` + `领取` → 一次点击 → `350/200`，`领取` 变
    `下次补给 04:52:52`。帧：`dataset/truth_audit/free_stamina_20260914_140601/`。
  - **撤回语义**：确认后队列仍 6/6、该行变「返回中」；13:53 = 6/6 → 14:06 = 5/6（槽位在回城后释放）。
    帧：`dataset/truth_audit/march_recall_20260914_135242/`。
  - 真实 loop 里 `OPEN_STAMINA_SOURCES` 的**安全路径**通过：面板判定「无免费礼包」→ `BACK`，
    verifier PASS（见 `evidence/` 中的 live_stamina 日志）。
  - `reserve_for_stamina=2` **真的改变了行为**：采集扫描在 idle≤2 时返回
    `reserved_march_for_stamina` 并停止（真机，`evidence/gather_acceptance_20260914_142334.json`）。
- **WHAT NOT VERIFIED（别当成已完成）**
  - **撤回的两个技能尚未在真实 loop 里跑通过一次**（触发条件是 `idle==0`，而 reserve=2
    让采集永远不会把队列占满）。`tools/run_recall_e2e.py` 是为验证它而写的实验工具。
  - 免费体力**领取**动作也还没经由 live loop 执行过（本轮是我手动点的那一次）。
  - 行军计数被覆盖层遮住时 `march_used=None`（诚实 unknown），此时派兵/撤回都无法决策。
  - `DISPATCH_NOT_PROVEN` x28 根因仍未定位。
  - 四资源各 ≥3 次闭环验收仍未达成。
- **撤回端到端尝试过一次并失败（诚实记录）**：`tools/run_recall_e2e.py` 把 reserve 临时降到 0
  并连跑 3 次采集想把队列填满，但三次都是 `RESOURCE_NOT_FOUND`（城镇附近当前没有可采节点），
  队列停在 idle=1，触发条件不成立。**所以撤回的两个技能仍未在真实 loop 中跑通过。**
  日志：`evidence/recall_e2e_20260914.log`。
- **NEXT EXACT STEP**：先解决「巨兽目标面板遮住行军计数」（识别为地图覆盖层并关闭），
  再在**确实有 6 条行军在外时**重跑 `tools/run_recall_e2e.py` 让撤回在真实 loop 里通过一次。
- **DO NOT REPEAT**：不要恢复 `calibrated_baseline_used` 这类「捕获时的状态」常量；
  不要把 `NORMAL_IDLE_SLOT_INCREASED` 当成撤回的证明；不要用全屏 OCR 读 HUD 小数字。

---

### WHAT FINISHED（本轮真实完成的）

- 完成接管审计并建立跨账号接力机制（git 基线 + handoff 生成器 + START_HERE）。
- 修掉 **AUTO 主循环完全无法执行语义点击** 的接线错误。
- 重写资源页签识别：写死坐标 → 白色角标锚点 + 相对布局 + 格内模板。
- 修掉 `Page.MARCH` 缺分支导致采集链在编队页死等 `WAIT`。
- 填补证据/保留漏洞：`dataset/verified`、`dataset/production` 此前**不在保护名单内**。
- Worker 崩溃改为写完整 traceback + 运行时快照，环境失败与真实崩溃分开计数。
- 覆盖率模型重建为能力层，纠正 5 个 Goal 的错误分类。

### WHAT LIVE VERIFIED（有真机证据）

- `GATHER_RESOURCE` 完整闭环，**多次**：`SEARCH_RESOURCE → SELECT_RESOURCE →
  SUBMIT_RESOURCE_SEARCH → START_GATHER → DISPATCH_MARCH` 每步 verifier 通过，
  `after = MAP` 且 `marches` 含 `MARCHING` / `RETURNING`，`stop_reason = TARGET_SKILL_VERIFIED`。
  证据：`evidence/gather_acceptance_20260914_123747.json`（MEAT）、
  `evidence/gather_acceptance_20260914_125232.json`（WOOD ×1、MEAT ×1），
  截图在 `dataset/raw/control_panel/runtime_auto/accept_*/`。
- **资源不可用自动切换**：WOOD 返回 `RESOURCE_NOT_FOUND` 时，运行时标记其不可用并在
  **同一次运行内**换资源完成闭环（2026-09-14 第三轮 run 3，步骤 4–6）。
  此前这一情况会直接结束运行。
- 资源页签分类器：真机 **22/22** 帧正确（含 HOME 误报拒绝），并在至少三种不同滚动偏移下
  正确工作（写死坐标做不到）。
- 等级筛选器：点「+」读数 1→4→8 与真机显示一致（`resource_level_max = 8` 正确）。

### WHAT NOT VERIFIED（不要当成已完成）

- 「四种资源各 ≥3 次完整闭环、合计 ≥12 次」——**远未达成，且受行军槽位硬约束**。
  可追溯已验证闭环：**MEAT 2 / WOOD 2 / COAL 0 / IRON 1 = 5**
  （见 `evidence/gather_closure_tally.json`，另有 27 条旧记录因无证据被排除）。
  账号只有 **6 条行军队列**，每次闭环占用一条数小时；当前 `6/6` 全忙，
  必须跨多个行军返回周期才能继续。
- `DISPATCH_NOT_PROVEN` 的**根因已定位并修复**（地图被 OCR 误判成 EVENT），
  但**修复后还没有产生新的成功闭环证据**——下一次闭环才会验证它。
- 竞技场 / 迷宫 / 限时活动 / Bear / Rally：**所需技能根本未实现**。
- 72h Soak、5–7 天 Soak：**远未开始**。
- 外部项目接入：**0 项**（见 `07_EXTERNAL_REUSE.md`）。
- `RELAX_RESOURCE_LEVEL`：注册了但从未执行。实测失败场景里等级已在最小值，
  正确补救是换资源，所以这个技能可能本身就是多余的设计——需要新证据再判断。
- 32 条 `DISPATCH_MARCH` 成功记录里 27 条无证据（旧代码所写）。
  它们**不得**被用来支撑任何 Live Verified 声明。

### STOPPED AT

本轮结束时状态良好：无 fatal error，工作树被 checkpoint 收纳，
测试全绿（见 `AUTO:last_handoff` 的 TEST STATUS 由你手动补跑后填写）。

### 已知风险（按严重度）

1. **截图证据不进 git** → 换机器会失去 Live Verified 的可追溯性。
2. **`unexpected_worker_exits` 的历史值无法归因** → 真实的 72h 结论要等新数据。
3. **全历史成功率是混合口径**（736 条跨多天多版本）→ 只能看趋势，不能当当前水平。
4. **等级滑条按 max=8 标定，客户端实际是 1~27** → 等级只当 evidence，不要用它做判定。
5. **`tools/` 里可能有名字相近的一对文件**：
   `goal_capability_map.json`（手写输入）vs `capability_skill_map.json`（生成输出）。

### DO NOT REPEAT（踩过的坑）

- 不要凭记忆推导资源页签坐标。读 `SemanticROIVision.selected_resource` 的角标锚点。
  已实测到至少三种滚动偏移（0 / +400px / MEAT 在 0.4993）。
- 不要把等级筛选器当成 1~27。**真机实测是 1..8**；`RESOURCE_NOT_FOUND` 是资源可用性问题，
  不是等级问题——补救动作是**换资源**。
- 不要在 `LiveRuntime.resolve` 里直接写 `self.semantic_vision.semantic`——用 `_semantic`。
- 不要新增 Skill 而不提供 verifier（否则 `VERIFIED_ATOMIC` 不含它，永远不会被调度）。
- **不要用 `registry.ready(world)[0]` 之类的「第一个可执行技能」做兜底**：
  注册表里第一个 `required_page=None` 的是占位技能 `WAIT`，会让循环在任意页面静默卡死。
  （已在 `brain.py` 排除 `WAIT`，但新增占位技能时要保持这个不变量。）
- 不要按目录/通配符批量删文件。**只列具体文件名，逐项确认。**
- 不要把「代码存在」「Replay PASS」「单次成功」写成 `STABLE` 或 `Live Verified`。
- 不要为了让测试全绿而恢复错误行为；先判断测试是否过时。
- 不要在没读 `00_MASTER_RULES.md` 之前改动架构。
- 不要在脚本里调用 `date` / `head` / `tail` / `wc`（本机不存在，会让命令静默失败或产生
  形如 `live_gather_` 的错误目录名）。
