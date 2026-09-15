# Review Requests

## RR-001 — unexpected_worker_exits 的两个写入方不对称（诊断完成，修复超出授权范围）

**来源**：`WB-RUNTIME-EXIT-ROOTCAUSE`（2026-09-15）
**为什么需要 Codex 而不是 WorkBuddy**：根因已定位，但**修复位置在 `tools/control_panel.py`，
不在该 Work Order 的 `files_allowed_to_modify` 里**，且该 Order 的 `do_not_touch` 明确列了
「watchdog semantics without evidence」。所以**不动手**，上交裁决。

### 证据（全部可复现，脚本 `tools/cq_runtime_exit_audit.py`）

- `learning/runtime_snapshot.json`：`unexpected_worker_exits=15`、`watchdog_restart_count=13`、
  `last_fatal_error=null`。
- **`learning/control_panel/crashes/` 目录不存在**；`learning/control_panel/latest.log` **0 字节**
  （mtime 2026-09-14T03:45:35Z）。
- 全语料 1284 条 episode 中，**没有任何** crash / `FATAL_*` / `WORKER_*` 类型失败。
- 该计数器**只有 `tools/control_panel.py` 会写**，而控制面板 GUI 当前**没有运行**
  （进程列表里只有卡住的 pytest 与一个无关的 ollama 脚本）。

### 根因（两处写入方，语义不一致）

| 位置 | 行 | 行为 |
|---|---|---|
| `_handle_worker_failure` | 1234 / 1239 | `counts_as_exit = classification == "WORKER_CRASH" and not fatal and not stop_requested` ⇒ **只有真正的 WORKER_CRASH 计数**，且注释承诺「已写入 `crashes/` 并带完整 traceback」 |
| `_handle_runtime_error` | 1257 | `previous + (0 if fatal else 1)` ⇒ **凡非 fatal 一律计数，完全不看 classification** |

也就是说：**带分类的路径是对的，不带分类的兜底路径会把环境失败也算成 worker 退出。**

### 由此可推（并且这是本次最有价值的一句）

代码承诺：每个被计数的 `WORKER_CRASH` 都会在 `crashes/` 留下 traceback。
而 `crashes/` **根本不存在**、`latest.log` **是空的**。
⇒ **这 15 次几乎不可能来自真实的 WORKER_CRASH，而更可能来自那条不看分类的兜底路径。**

因此历史 15 的**正确读法是「成因不明的非致命中断累计」**，不是「15 次 worker 崩溃」，
更不能清零（清零会丢掉唯一线索）。

### 建议的最小修法（供 Codex 决定，WorkBuddy 未实施）

1. 让 `_handle_runtime_error` 也接受/推导 classification，**至少区分 ENVIRONMENT 与 WORKER_CRASH**，
   两处使用同一判据（现在同一份计数器有两套语义，这本身就是缺陷）。
2. 为被计数的每一次写入一条 `crashes/` 报告——**要么兑现注释的承诺，要么改掉注释**
   （当前是注释在骗人，这比数字本身更危险）。
3. 给快照加**按成因分列**的字段（例如 `unexpected_worker_exits_by_cause`），
   让「15」以后可以被拆开而不是继续累计成一个不可解释的整数。

### 在此之前 WorkBuddy 做了什么（都在授权范围内）

- 只读审计（`tools/cq_runtime_exit_audit.py`）。
- 把结论写进 **`tools/update_workbuddy_handoff.py`** 的 KNOWN RISKS：
  原文只说「2026-09-14 之前没有 traceback」，现改为陈述「两处写入方 + 无一例 crash 报告 ⇒
  历史总量不可读作崩溃数，且不得清零」。这样**每个后续会话都会看到**，不必再重新推导一次。
- **未修改任何历史数字、未修改 watchdog 语义、未制造崩溃。**

---

## 其余情况

WorkBuddy 遇到以下情况才追加 review request：
- 需要改变冻结架构或核心技术路线；
- 触及真实支付、账号安全或不可恢复数据；
- 生产证据与代码冲突且无法按证据优先级裁决；
- 同一任务达到 timebox 仍无法分类；
- **根因已定位但修复超出该 Work Order 的 `files_allowed_to_modify`**（本 RR 即此类）。
