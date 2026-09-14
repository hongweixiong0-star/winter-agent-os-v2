# 10 — LAST HANDOFF

> 本文件是「上一个账号停在哪里」的快照。
> **它只是恢复加速器，不是唯一事实源。** 如果上一个账号突然断线没来得及写它，
> 新账号必须能仅靠 git / episodes / evidence / runtime snapshot / logs / registry /
> goal state 重建全部事实——`AUTO:last_handoff` 块正是这样生成的。
>
> `AUTO:last_handoff` 由 `tools/update_workbuddy_handoff.py` 重写；手写块不会被覆盖。

<!-- AUTO:last_handoff -->
HANDOFF TIME: 2026-09-14T04:36:31+00:00
LAST GOOD COMMIT: d3f974a
WORKING TREE: 1 dirty file(s)
  ['?? .workbuddy-ai/handoff/.last_good_commit']

WHAT FINISHED (machine-visible): 24 skills live verified, 16 stable, 3 commit(s) in history
WHAT LIVE VERIFIED: see 01_CURRENT_TRUTH.md section D (skills with >=1 production success)
WHAT NOT VERIFIED: 25 skills never executed, 7 never succeeded

CURRENT TASK: see 03_NEXT_ACTION.md
STOPPED AT: agent_state=IDLE stop_reason=TARGET_SKILL_VERIFIED
LAST PRODUCTION EPISODE: {"skill": "DISPATCH_MARCH", "result": "SUCCESS", "recorded_at": "2026-09-14T04:11:59.146784+00:00", "episode_id": "live_gather_run2", "before_screenshot": "dataset\\raw\\control_panel\\runtime_auto\\live_gather_run2\\live_gather_run2_step_001_before_20260914T041144038962.png", "after_screenshot": "dataset\\raw\\control_panel\\runtime_auto\\live_gather_run2\\live_gather_run2_step_001_after_20260914T041148263346.png"}
TOP FAILURE: {"failure_type": "SEMANTIC_TARGET_NOT_VERIFIED", "count": 104, "top_skills": [["SELECT_RESOURCE", 40], ["SEARCH_RESOURCE", 32], ["OPEN_MAIL", 13]]}
NEXT EXACT STEP: Implement the highest-leverage missing skill listed in `highest_leverage` inside knowledge/goals/capability_skill_map.json, then REPLAY -> LIVE -> VERIFY -> EVIDENCE.
DIRTY FILES: 1
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

- `GATHER_RESOURCE` 单条链路：`SUBMIT_RESOURCE_SEARCH` → `START_GATHER` → `DISPATCH_MARCH`
  全部 verifier PASS，`after = MAP` 且 `marches=["MARCHING"]`、`march_used=1`，
  `stop_reason = TARGET_SKILL_VERIFIED`，进程退出码 0。
- 资源页签分类器：22/22 真机帧正确（含 HOME 误报拒绝）。
- 证据：`evidence/live_gather_20260914/`，
  截图在 `dataset/raw/control_panel/runtime_auto/live_gather_run{1,2}/`。
  **注意这些截图不在 git 里**（见 D-013）。

### WHAT NOT VERIFIED（不要当成已完成）

- 「四种资源各 ≥3 次完整闭环、合计 ≥12 次」——**未达成**，本轮只有 1 条完整链路。
- 资源轮换目前不保证能选到四种不同资源（本轮被选中的是 IRON）。
- `MARCH_PAGE_NOT_OPEN` 修复后真机 0 次，但**样本量太小**，不足以宣布解决。
- `DISPATCH_NOT_PROVEN` x28 根因**未定位**。
- 竞技场 / 迷宫 / 限时活动 / Bear / Rally：**所需技能根本未实现**。
- 72h Soak、5–7 天 Soak：**远未开始**。
- 外部项目接入：**0 项**（见 `07_EXTERNAL_REUSE.md`）。

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
- 不要在 `LiveRuntime.resolve` 里直接写 `self.semantic_vision.semantic`——用 `_semantic`。
- 不要新增 Skill 而不提供 verifier（否则 `VERIFIED_ATOMIC` 不含它，永远不会被调度）。
- 不要按目录/通配符批量删文件。**只列具体文件名，逐项确认。**
- 不要把「代码存在」「Replay PASS」「单次成功」写成 `STABLE` 或 `Live Verified`。
- 不要为了让测试全绿而恢复错误行为；先判断测试是否过时。
- 不要在没读 `00_MASTER_RULES.md` 之前改动架构。
