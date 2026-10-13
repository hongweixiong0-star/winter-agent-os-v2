# 最主要的 worker 崩溃模式：**修过之后还在发生**，而现场记录settle不了原因（2026-10-14）

> `learning/control_panel/crashes/` 里 **52** 个现场。**34 个（65%）是同一种**：
> `WORKER_RESULT_MISSING`（exit=1: 20 · exit=3: 14）。
> 它有一条**已记录的成因、已在 10-08 修过**，但 **10-10 又发生了 3 次**。
> 而现场记录的"最后 20 条日志"**来自 MAA/模拟器那条 log**，不是 worker 自己的最后动作 ——
> 所以**从记录判不出这 3 次是同一个成因没修干净，还是第二个成因。**

---

## 一、量出来的分布（全部 52 个现场）

| 类型 | 条数 |
|---|---:|
| **`WORKER_RESULT_MISSING: exit=1`** | **20** |
| **`WORKER_RESULT_MISSING: exit=3`** | **14** |
| `等待 MuMu 连接超时` | 7 |
| `WORKER_TIMEOUT: exit=130` | 3 |
| WinError5 / `PermissionError`（原子重命名） | 3 |
| 其它（`TypeError: int()`、`DEVICE_AMBIGUOUS`、`AttributeError`） | 5 |

**按天**（只看 `RESULT_MISSING`）：`10-03:4 · 10-05:3 · 10-06:7 · **10-08:17** · **10-10:3**`
⇒ **不是一次性事故，是持续发生的模式；10-08 修过之后仍有。**

（⚠️ 我先只看了"最新那个文件"，得出"主因是 WinError5 重命名"——**错了**，那只有 3 条。
  先看一条再下结论，是这一轮我自己的第一个错。）

## 二、已记录的成因与修法（项目自己找到的，2026-10-08）

`winter_agent_v2/runtime.py:5213-5219` 原文：

> "``except OSError`` alone was not enough … **measured 2026-10-08 at 08:36:46, 08:37:06 and
> 08:37:40, three `WORKER_RESULT_MISSING: exit=1` crashes inside a minute**, each one with
> **the host's own line as the worker's last log entry** —
> ``[safe-delete][SAFE_DELETE_BULK_CONFIRM_REQUIRED] {"count":50,"threshold":50,"scope":"turn"}``
> … The gate reports a refusal as **`SystemExit`, which `OSError` cannot see, so it escaped and
> took the worker with it**; the panel spent its recovery budget and paused AUTO.
> **Losing a discard never ends a step, so a *refused* discard must not end the run either.**"

两处都已修：
1. `runtime.py` 现在走 `delete_past_the_hosts_gate(...)` 包住那次删除 ⇒ **被拒绝的丢弃不再结束整轮**；
2. `tools/control_panel.py:238-249` 把删除配额改成**按 turn**（`RETENTION_DELETIONS_PER_TURN = 30`），
   理由是"``_enforce_retention`` 在同一 turn 有两个调用方，30 + 30 到 60 就把 worker 带走了"。

## 三、**但 10-10 又发生了 3 次** —— 而记录判不出为什么

我读了 10-08 与 10-10 的 `RESULT_MISSING` 现场的 `last_20_events`，**最后三条都是这一类的连接噪声**：

```
connect not same day
product: MuMuPlayer-12.0-0
nemu_connect instance_name: ginstance1401070063873131400
```

⇒ 现场记录的 `last_20_events` 每条都带 `"source": "latest.log"` —— 那是 **MAA / 模拟器**那条日志。
**worker 自己（Python 进程）的最后输出不在里面**，而 `traceback` 字段只有面板自己合成的那一行
（`RuntimeError: WORKER_RESULT_MISSING: exit=1`）。

⇒ 于是：**"它又把 worker 带走了"这件事**记录得下来，**"它当时在哪一步、因为什么" 记录不下来**。
10-10 那 3 次，**我不能说**是"同一个成因没修干净"，也**不能说**"是第二个成因" —— 证据不够。

## 四、这条为什么值得写下来

- 它是 `unexpected_worker_exits = 59` 的**主要来源**（34/52），而那个计数器是操作者 **72h 验收**
  读的东西（见同日另一份 handoff：那个门槛本身还不可能满足）。
- 它是**无人值守**（项目头号目标）的直接威胁：**worker 死 → 看门狗重启 → 恢复预算被花掉 →
  AUTO 被暂停**（`control_panel.py:9199-9204` 的 `MAX_CONSECUTIVE_WORKER_CRASH_RESTARTS`）。
- 而它**已经修过一轮却没消掉**，说明"查一次就归档"在这条线上不够。

## 五、具体缺的那一块证据（可做，本轮**未做**）

现场记录已经有 `runtime_snapshot`、`thread_state`、`last_20_events`（来自 MAA 日志）——
**意图就是"保留现场"**，只差**worker 自己的最后若干行输出**。
launch 侧是 `stdout=subprocess.PIPE, stderr=subprocess.STDOUT`（`control_panel.py:8886` 等），
也就是说那些输出**是被接住的**；把它们在崩溃时**落到现场文件里**（与 `last_20_events` 并列），
就能把这一族从"记录得下死亡、记录不下死因"变成可归因。

**本轮没有改**：它动的是崩溃记录的形状与面板的采集路径，属要被单独审阅的一类；
而且按第161/164 轮的教训 —— **先量再改**，本轮只量到"证据缺在哪一块"。

## 六、未做

没改 `crash_root` 的写入、没改面板采集路径、没动 `runtime.py` 的删除包装、没重跑任何崩溃。
