# Codex Directives

生成时间：2026-09-15 20:45（Asia/Shanghai）

WorkBuddy 按 `WORK_QUEUE.json` 的 priority 顺序执行。该文件是 Codex → WorkBuddy 的正式机器可读任务接口；用户只需启动 WorkBuddy，不需要手工复制任务。每个任务严格走：

`READ EVIDENCE → TOOL CHECK → MINIMAL PATCH → TARGETED TEST → REPLAY → LIVE → VERIFY → EVIDENCE → NEXT`

硬边界：
- 不新增 Scheduler、Registry、WorldState、Manager 或活动专属执行链。
- 不修改历史 episode，不把 Replay/Test/单次成功写成 LIVE_VERIFIED。
- 不点击任何付费控件，不使用体力道具，不为制造失败主动消耗资源。
- 涉及截图、定位、OCR、点击、等待时，先用现有 MAA/V2 能力；ADB 只做 fallback。
- 超过 timebox 且没有真机改善、明确根因、明确 blocker 或可回滚错误方案，立即停下并记录 `BLOCKED_QUEUE.json`。

每项任务必须读取并执行字段：`task_id priority objective why_now current_evidence recommended_tool preferred_backend root_cause_or_hypothesis files_scope do_not_touch implementation_hint test_plan live_plan acceptance timebox_minutes stop_condition dependencies`。

每项任务只回报：`TASK_ID ROOT_CAUSE CHANGED_FILES TEST_RESULT LIVE_ATTEMPTS LIVE_SUCCESS LIVE_FAILURE BEFORE AFTER VERIFIER_RESULT EVIDENCE PATCH_STATUS REMAINING_ISSUE NEXT_RECOMMENDATION`。
