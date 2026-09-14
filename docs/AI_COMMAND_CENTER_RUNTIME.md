# AI 指挥中心与 Runtime 单一真相源

AI 指挥中心只展示和配置现有 V2 数据，不选择 Goal、不选择 Universal Skill，也不维护游戏业务状态。

主链保持：

`Policy → GoalLibrary / GoalState → Brain → 单一 Scheduler → Universal Skill → Executor → Verifier → Learning`

控制台开始按钮只启动 `tools/run_live.py`。它不传入固定 Goal；当前 Goal 和 Skill 由现有 Runtime、GoalLibrary、RuleBrain 与 Scheduler 决定。

## Runtime Snapshot

唯一运行状态文件为 `learning/runtime_snapshot.json`，由 Runtime 原子写入，GUI 每 1.5 秒只读刷新。

状态限定为：`AUTO_RUNNING`、`IDLE`、`GOAL_RUNNING`、`RECOVERING`、`DEGRADED`、`SAFE_STOP`、`FATAL_STOPPED`、`PAUSED`。

任何运行态必须同时满足 `runtime_thread_alive=true` 与 `scheduler_loop_alive=true`；否则 Snapshot 自动归一为 `DEGRADED`，因此不会再出现“顶部自动运行、后台已退出”或 `SAFE_STOP` 与 `AUTO_RUNNING` 同时成立。

## 失败隔离

普通 Goal/Skill 失败只分类为 defer、skip、recover 或 degraded，并由 watchdog 启动下一轮。只有以 `FATAL_`、`ACCOUNT_`、`PAYMENT_` 开头的硬阻断会退出无人值守 AUTO。

## 七个主页面

1. 总览
2. 目标
3. 策略
4. 活动
5. 能力
6. 学习
7. 系统

完整英文日志、Vision Debug、Replay、目录入口与 Watchdog 指标集中在“系统”。知识质量与失败优先级集中在“学习”。
