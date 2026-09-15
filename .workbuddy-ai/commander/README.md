# Commander Queue — WorkBuddy 侧说明

这个目录是 **Codex ⇄ WorkBuddy** 的任务接口。Codex 写任务，WorkBuddy 执行并回报。
两边都有机器可读契约，**操作者不需要在中间手工搬运指令**。

## 文件归属（谁写谁，别搞混）

| 文件 | 唯一写入方 | 说明 |
|---|---|---|
| `WORK_QUEUE.json` | **Codex** | 任务定义，见下「Work Order 字段」 |
| `CODEX_DIRECTIVES.md` | **Codex** | 人类可读的补充说明 |
| `LAST_CODEX_REVIEW.md` | **Codex** | 上一次复盘 |
| `results/<task_id>.json` | **WorkBuddy（经 `tools/cq.py`）** | 每个任务的回报 |
| `EXECUTION_STATE.json` | **WorkBuddy（经 `tools/cq.py`）** | 队列执行状态；不要手改 |
| `BLOCKED_QUEUE.json` | **WorkBuddy（经 `tools/cq.py`）** | timebox 内做不到的任务 |
| `REVIEW_REQUESTS.md` | **WorkBuddy** | 需要 Codex 高级分析的问题 |

## WorkBuddy 的入口

```bash
PY="C:/Users/xhw/.workbuddy/binaries/python/versions/3.13.12/python.exe"   # 只有 cq.py 用它
"$PY" tools/cq.py init                       # 建 results/ 与 EXECUTION_STATE.json
"$PY" tools/cq.py plan                       # 解析可执行集（接管后第一件事）
"$PY" tools/cq.py start  <task_id>
"$PY" tools/cq.py finish <task_id> --result <file.json> [--require-live]
"$PY" tools/cq.py block  <task_id> --result <file.json>
"$PY" tools/cq.py state
```

**可执行 = `status == "READY"` 且 `dependencies` 全部已有终态。**
`QUEUED` 与 `WAITING_FOR_NATURAL_STATE` 不是可执行任务：
前者是 Codex 有意压着，后者要求真机自然到达某个状态（**不许为凑任务而消耗资源**）。

排序：`priority`（P0<P1<P2）→ 队列内声明顺序。

## 每个 Work Order 的固定十步

```
READ EVIDENCE → TOOL CHECK → IMPLEMENT → TARGETED TEST
→ REPLAY → LIVE → VERIFY → BEFORE/AFTER → REPORT → NEXT
```

回报字段（`cq.py finish` 会校验，缺一个就拒收）：

```
TASK_ID ROOT_CAUSE CHANGED_FILES TEST_RESULT
LIVE_ATTEMPTS LIVE_SUCCESS LIVE_FAILURE
BEFORE AFTER VERIFIER_RESULT EVIDENCE
PATCH_STATUS REMAINING_ISSUE NEXT_RECOMMENDATION
```

`--require-live` 会额外拒绝「`PATCH_STATUS` 宣称完成但没有 `LIVE_EVIDENCE`」的回报。
**队列不会让虚报变便宜** —— 这是设计意图，不要绕过。

## 硬边界（与 `00_MASTER_RULES.md` 一致，队列不豁免）

- 不新增 Scheduler / Registry / WorldState / Manager / 活动专属执行链。
- 不修改历史 episode；不把 Replay / Test / 单次成功写成 `LIVE_VERIFIED`。
- 不点击付费控件，不使用体力道具，不为造失败主动消耗资源。
- 截图 / 定位 / OCR / 点击 / 等待优先用现有 MAA 与 V2 能力；ADB 只做 fallback。
- 清理文件先列清单逐项确认（本项目曾因批量删除**不可恢复地**丢过脚本）。

如果某个 Work Order 与上述冲突（例如要求改冻结架构），**不执行**，
改写进 `REVIEW_REQUESTS.md` 等 Codex 处理。

## 给 Codex 的一条重要提醒

`target_metric` 是 Codex 依据**当时那份 handoff** 写的，可能已经过时或过窄。
WorkBuddy 执行时**必须用生产证据重新核对它**。
对不上时，正确答案是如实写进 `REMAINING_ISSUE`，**不是把指标改到能对上**。
