# Commander — 持续自主开发入口

先读 [WORKBUDDY_AUTONOMOUS_DEVELOPMENT_FINAL.md](WORKBUDDY_AUTONOMOUS_DEVELOPMENT_FINAL.md)、[CODEX_DIRECTIVES.md](CODEX_DIRECTIVES.md) 和 [WORK_QUEUE.json](WORK_QUEUE.json)。WorkBuddy是持续开发负责人；每轮按fresh Production证据重选最高价值根因。

## 文件职责

| 文件 | 写入方 | 用途 |
|---|---|---|
| WORK_QUEUE.json | 有效独占claim后的WorkBuddy；Codex仅获授权的治理交付 | 原单保留，允许追加新ID及记录动态重排；同一个开发backlog |
| 用户FINAL全文与meta | 用户来源的不可变副本 | 不改用户固定策略，校验来源SHA256 |
| CODEX_DIRECTIVES / LAST_CODEX_REVIEW | Codex治理交付 | 当前契约/事实，不是runtime状态真值 |
| EXECUTION_STATE/results/BLOCKED_QUEUE | WorkBuddy经现有cq.py | 执行记账，保留历史 |
| REVIEW_REQUESTS | WorkBuddy | 记录证据不足/确需决策问题；其余可执行工作继续 |

## 现有工具

使用项目 `.venv/Scripts/python.exe tools/cq.py plan` 读取可选集合；需要时init，再start/finish/block/state。该工具按priority/声明顺序静态排序，只是建议。负责人每轮依据deadline、共享根因、学习/覆盖和活性选一项，不固定照单执行。未知文件/资源/设备仍先做TOOL CHECK。

cq.py依赖终态包括DONE与BLOCKED；start不校验ownership；finish按报文形状记DONE，--require-live只校验LIVE_EVIDENCE存在。因此工具不提供独占锁，也不证明生产完成。每次变更仍读task01真实claim、设备租约与文件归属；原报文保留，L5/Live Verified必须有相关真实Verifier/Episode。

结果字段仍为TASK_ID/ROOT_CAUSE/CHANGED_FILES/TEST_RESULT/LIVE_ATTEMPTS/LIVE_SUCCESS/LIVE_FAILURE/BEFORE/AFTER/VERIFIER_RESULT/EVIDENCE/PATCH_STATUS/REMAINING_ISSUE/NEXT_RECOMMENDATION。

## 连续执行

Observe → 价值选择 → Architecture Review → 最小开发/针对性测试 → 安全生产加载 → AUTO/Verifier/学习 → 再评估。每个尝试有界timebox；条件不具备则保存retry/wake并处理别项。八单不是总停止上限；所有启用Goal均须有EXECUTE/DISCOVERY/BOOTSTRAP/LEARNING/RECOVERY/WAIT/COMPLETE/POLICY解释。

保持唯一架构、唯一32K UI-Venus、MAA、Verifier；Known和实时环模型0。runtime WorkBuddy gateway保持退役。真钱、特殊Fishing消耗及未经授权不可逆操作禁止；普通资源依当前Policy。保留dirty/历史数据，显式暂存小提交、不force push。

设计建议与安全/活性冲突时按用户FINAL第0节裁决并记录，不机械等待Codex。缺真实证据不能更改指标声称完成；当前事实/claim与原捕获记录分开。
