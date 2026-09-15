# Review Requests

当前没有未决 Codex Review Request。

## 已裁决

- `RR-001`：批准最小修复。新任务 `WB-R19-RUNTIME-EXIT-SEMANTICS` 已明确授权修改 `tools/control_panel.py` 与 `winter_agent_v2/runtime_snapshot.py`；历史 `unexpected_worker_exits=15` 保留不变。
- `WB-0AZ`：不允许主动点击 power-blocked 大师悬赏的「前往查看」制造测试状态。改为等待自然复现；当前 runtime-level replay 与真实 verifier 证据 KEEP。

只有以下情况再追加：需要改变冻结架构；触及支付/账号安全/不可恢复数据；Production Evidence 与 Current Code 无法裁决；任务 timebox 到期仍无法形成 Root Cause、Blocker 或 Rollback。
