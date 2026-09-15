# Codex Directives — Round 19

生成时间：2026-09-16 07:17（Asia/Shanghai）

`WORK_QUEUE.json` 是 Codex → WorkBuddy 的正式机器接口。按 `priority` 与数组顺序执行；仅当依赖任务已有终态时启动。用户只需启动 WorkBuddy。

每项任务严格执行：

`READ EVIDENCE → TOOL CHECK → MINIMAL PATCH → TARGETED TEST → REPLAY → LIVE → VERIFY → BEFORE/AFTER → RESULT → NEXT`

工具顺序：项目已有能力 → MAA → Legacy Verified Evidence → 成熟外部实现 → OpenCV/OCR/ADB → 最小自研。

本轮技术决定：

- MAA MuMuExtras 已是生产取帧路径；战斗按钮已有真实 `recognition/action/executor=MAA` 证据，KEEP。
- `SELECT_RESOURCE` 保持 V2 bracket + relative layout，MAA 负责取帧、滑动、点击。整条资源栏模板不能解决动态偏移。
- `OPEN_INTEL` 允许一次 60 分钟修复，因为近期连续 6 次失败已阻塞 AUTO；完成后停止继续深挖 Intel。
- RR-001 已批准最小修复，可修改 `tools/control_panel.py`；历史 `unexpected_worker_exits=15` 永不清零。
- 不主动点击 power-blocked 大师悬赏的「前往查看」制造 BLOCKED 卡；等待自然复现。

硬边界：不新增 Scheduler、Registry、WorldState、Manager；不修改历史 episode；不点击付费控件；不使用体力道具；不为验证主动消耗资源。超过 timebox 且没有 Live Improvement、明确 Root Cause、明确 Blocker 或有效 Rollback，立即停止、写 `BLOCKED_QUEUE.json`，继续下一 READY 任务。

每项结果写入 `.workbuddy-ai/commander/results/<task_id>.json`，字段至少包含：`TASK_ID ROOT_CAUSE CHANGED_FILES TEST_RESULT REPLAY_RESULT LIVE_ATTEMPTS LIVE_SUCCESS LIVE_FAILURE BEFORE AFTER VERIFIER_RESULT EVIDENCE_PATH PATCH_STATUS REMAINING_ISSUE`。
