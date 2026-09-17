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

## RR-004 —— `LIVE_VERIFIED` 把「AUTO 自己在跑」记成「这个 job 修好了」

**来源**：`SCAN_MAP_FOR_BEAST|BEAST_SCAN_NOT_PROVEN|SCAN_MAP_FOR_BEAST` 这次升级（job `859e3787`）。

**事实**：`reconcile_outcome()` 判 `LIVE_VERIFIED` 的条件是
「该 capability 在 `submitted_at` **之后**有 `recorded_at` + `verifier_ok` 的生产 episode」。
但 AUTO **不会因为派了 job 就停下** —— 它继续玩。于是**已经能跑的技能**在 job 期间
照常产出成功 episode，reconcile 会把这些 episode 算成「job 的成果」。

本次就是活例：该 job 于 `14:56:16` 派出，而 `SCAN_MAP_FOR_BEAST` 在 `14:56:26`、
`14:58:40` 等时刻继续产出 verifier 通过的 episode。**这些 episode 与 agent 改了什么毫无关系**
—— agent 改的是升级分类器，不是扫描技能。按现在这段代码，这个 job 极可能被记成 `LIVE_VERIFIED`。

**为什么这是 P0 级诚实性问题**：`LIVE_VERIFIED` 是五个 outcome 里**唯一**表示
「能力真的变好了」的那个，也是**唯一**会关掉修复循环的那个。虚假的 `LIVE_VERIFIED`
比虚假的 `STUCK_15_MIN` 更贵：前者让循环停下并对外宣布成功。

**同一缺陷族**（本轮已修其一）：`classify_condition` 曾只看时钟就宣称
「no verified episode」，从不读 episode 流。**两个缺陷方向相反，根因相同**：
**用了一个不能证明该结论的信号**。

**建议（不自行实施，因为要改的是一条判据的语义）**：`LIVE_VERIFIED` 还要求
episode 证明的是**本 job 改动的东西**。最小可辩护的口径：把 window 从
`submitted_at` 推到 **`settled_at`**（job 结束之后才产生的 episode），
或要求 episode 的 skill ∈ 本 job `repo_head → after` 实际改动的文件所影响的技能集合。
两种都要先决定「技能 ↔ 文件」怎么表达，故不擅自动手。

**已做的最小让步**：本轮只把 `classify_condition` 改为读 episode 流（负向条件），
**没有**动 `LIVE_VERIFIED`（正向条件）。**这个 job 自己的对账结论因此不可采信**，
请以第 4 节的验收证据为准，不要以 reconcile 的 outcome 为准。

## 已裁决

- `RR-001`：批准最小修复。新任务 `WB-R19-RUNTIME-EXIT-SEMANTICS` 已明确授权修改 `tools/control_panel.py` 与 `winter_agent_v2/runtime_snapshot.py`；历史 `unexpected_worker_exits=15` 保留不变。
- `WB-0AZ`：不允许主动点击 power-blocked 大师悬赏的「前往查看」制造测试状态。改为等待自然复现；当前 runtime-level replay 与真实 verifier 证据 KEEP。

只有以下情况再追加：需要改变冻结架构；触及支付/账号安全/不可恢复数据；Production Evidence 与 Current Code 无法裁决；任务 timebox 到期仍无法形成 Root Cause、Blocker 或 Rollback。
