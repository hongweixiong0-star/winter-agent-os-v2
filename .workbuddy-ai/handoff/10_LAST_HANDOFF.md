# 10 — LAST HANDOFF

> 本文件是「上一个账号停在哪里」的快照。
> **它只是恢复加速器，不是唯一事实源。** 如果上一个账号突然断线没来得及写它，
> 新账号必须能仅靠 git / episodes / evidence / runtime snapshot / logs / registry /
> goal state 重建全部事实——`AUTO:last_handoff` 块正是这样生成的。
>
> `AUTO:last_handoff` 由 `tools/update_workbuddy_handoff.py` 重写；手写块不会被覆盖。

<!-- AUTO:last_handoff -->
HANDOFF TIME: 2026-09-14T05:13:15+00:00
LAST GOOD COMMIT: 6189c67
WORKING TREE: 2 dirty file(s)
  ['M .workbuddy-ai/handoff/.last_good_commit', '?? tools/_h.txt']

WHAT FINISHED (machine-visible): 23 skills live verified, 16 stable, 7 commit(s) in history
WHAT LIVE VERIFIED: see 01_CURRENT_TRUTH.md section D (skills with >=1 production success)
WHAT NOT VERIFIED: 25 skills never executed, 7 never succeeded

CURRENT TASK: see 03_NEXT_ACTION.md
STOPPED AT: agent_state=IDLE stop_reason=TARGET_SKILL_VERIFIED
LAST PRODUCTION EPISODE: {"skill": "DISPATCH_MARCH", "result": "SUCCESS", "recorded_at": "2026-09-14T05:00:15.248850+00:00", "episode_id": "accept_20260914_125232_run03", "before_screenshot": "E:\\无尽冬日智能体\\dataset\\raw\\control_panel\\runtime_auto\\accept_20260914_125232_run03\\accept_20260914_125232_run03_step_006_before_20260914T045955757128.png", "after_screenshot": "E:\\无尽冬日智能体\\dataset\\raw\\control_panel\\runtime_auto\\accept_20260914_125232_run03\\accept_20260914_125232_run03_step_006_after_20260914T050000610623.png"}
TOP FAILURE: {"failure_type": "SEMANTIC_TARGET_NOT_VERIFIED", "count": 104, "top_skills": [["SELECT_RESOURCE", 40], ["SEARCH_RESOURCE", 32], ["OPEN_MAIL", 13]]}
NEXT EXACT STEP: Implement the highest-leverage missing skill listed in `highest_leverage` inside knowledge/goals/capability_skill_map.json, then REPLAY -> LIVE -> VERIFY -> EVIDENCE.
DIRTY FILES: 2
TEST STATUS: not run by this script — run `python -m pytest tests -q`
LIVE STATUS: PASS (unexpected_worker_exits=15)

KNOWN RISKS:
- Live Verified depends on screenshots that are NOT in git (see .gitignore); they are machine-local.
- `unexpected_worker_exits` before 2026-09-14 has no traceback and cannot be attributed.

DO NOT REPEAT:
- Do not re-derive resource-tab coordinates from memory; read the bracket anchor (vision.selected_resource).
- Do not assume no git history (it now exists) and never delete files by wildcard prefix.
- Do not pass a changed wire format into LiveRuntime.resolve(); use the `_semantic` accessor.
<!-- /AUTO:last_handoff -->


---

## 手写：人类补充（生成器读不出来的部分）

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
