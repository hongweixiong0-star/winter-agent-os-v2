# Review Requests

当前有 **2 个**未决 Codex Review Request（都来自 R19 第 2 批队列；都是**已落盘 schema / 安全边界的决定**，故只报告未动手）。

## RR-002 —— 删除账本里的 `capture_backend` 键（消除同名两义）

**来源**：`WB-R19-BACKEND-PROVENANCE-TRUTH`（DONE，见 `results/` 与 `out_backend_truth_report.json`）。

**事实**：`capture_backend` 这一个名字在两个产物里指**两个不同的事实**：
- `winter_agent_v2/runtime.py:346` 写的是**观测设备** —— 「本 episode 的 before/after 帧是哪个通道取的」；
- `winter_agent_v2/executor_router.py:401` 写的是**执行器设备** —— 「实际跑的那个 backend 接的是哪个设备」。

两者只在**两设备不同时**才不等，而这正是 HYBRID 的常态：本轮 **34 步**全部是
`episode=MAA_MUMU_EXTRAS / ledger=ADB_EXEC_OUT`。**两个值都不错，名字错** ——
单看任一侧都无法判断该步的帧来自哪个通道。

**建议（一行改动）**：账本该键**完全由 `used_backend` 决定**（ADB→`ADB_EXEC_OUT`，MAA→`MAA_MUMU_EXTRAS`），
**不携带任何账本自身没有的信息**。⇒ 直接删掉账本的 `capture_backend`，帧来源一律从 episode 读（在那里该字段已在自己回答自己的问题）。

**为什么没动手**：改动已落盘 schema，且历史行会保留旧键 ⇒ 需要明确「只对新行生效」还是「保留兼容旧键」的策略。

## RR-003 —— 给「在 `VERIFIED_ATOMIC` 内但**没有 verifier**」的技能补 verifier

**来源**：`WB-R19-LOW-RISK-GOAL-ATTEMPT`（BLOCKED：`NO_SAFE_CANDIDATE`）与 `WB-R19-BACKEND-PROVENANCE-TRUTH` 两个方向指向同一个缺口。

**事实**：对 20 个从未执行的技能做三重过滤后只剩 1 个候选（`RECALL_MARCH`），且它需要**自然存在的行军**（当前 `marches=[]`）。
淘汰原因是**硬门槛而非风险**：
- 6 个（`NAVIGATE_TO`/`RECOVER_HOME`/`READ_TIMER`/`READ_COUNTER`/`CLAIM_REWARD`/`SEND_MARCH`）**不在 `VERIFIED_ATOMIC`** ⇒ 真机循环直接拒执行；
- 6 个（`READ_INTEL_LIST`/`SELECT_INFANTRY_CAMP`/`SELECT_INTEL_RESCUE_SURVIVORS`/`CANCEL_DUPLICATE_TARGET`/`DISMISS_ALLIANCE_GENERIC_REWARD`/`RELAX_RESOURCE_LEVEL`）**在 `VERIFIED_ATOMIC` 内但根本没有 verifier**；
- 2 个 Rally 类在禁区且 `MEDIUM_COMBAT`。

**同一缺口的第二个症状**：`DISPATCH_BEAST` 与 `DISPATCH_INTEL_BEAST` **已经被执行过**，却**没有 verifier**
⇒ 其 episode 天生没有可审计的验证结果；也正因为没有 verifier，**Beast 战斗无法武装** `WB-R19-BATTLE-UNKNOWN-RECOVERY` 新加的防误按保护。

**建议**：先给**一个**读/导航形态、零花费的技能补真实 verifier（`READ_INTEL_LIST` 或 `SELECT_INFANTRY_CAMP`），
`WB-R19-LOW-RISK-GOAL-ATTEMPT` 即可在不触碰安全边界（`VERIFIED_ATOMIC` 不动）的前提下变为可达。
⚠ 请**不要**以「把技能加进 `VERIFIED_ATOMIC`」的方式解决 —— 那张表就是安全边界本身。

## 已裁决

- `RR-001`：批准最小修复。新任务 `WB-R19-RUNTIME-EXIT-SEMANTICS` 已明确授权修改 `tools/control_panel.py` 与 `winter_agent_v2/runtime_snapshot.py`；历史 `unexpected_worker_exits=15` 保留不变。
- `WB-0AZ`：不允许主动点击 power-blocked 大师悬赏的「前往查看」制造测试状态。改为等待自然复现；当前 runtime-level replay 与真实 verifier 证据 KEEP。

只有以下情况再追加：需要改变冻结架构；触及支付/账号安全/不可恢复数据；Production Evidence 与 Current Code 无法裁决；任务 timebox 到期仍无法形成 Root Cause、Blocker 或 Rollback。
