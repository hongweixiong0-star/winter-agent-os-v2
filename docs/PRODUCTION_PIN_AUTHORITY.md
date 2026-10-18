# 生产 pin 的唯一权威位置

> 2026-10-18 定稿。此前同一个 pin 被三个工具用三种写法各自推导，主仓启动因此失败。

## 一、唯一位置

```
E:\WinterAgent\.worktrees\prod\PRODUCTION_PIN.json
```

- **定义处只有一处**：`config/paths.py` 的 `PRODUCTION_PIN`（以及 `PRODUCTION_TREE`、
  `PRODUCTION_WORKTREE`、`PRODUCTION_LAUNCH_LOG`）。它们都从 `MAIN_REPO` 派生，
  没有第二个 `E:\WinterAgent` 字面量。
- **manifest 必须在 worktree 之外**：`repin_production.py` 用 `git reset --mixed` 移动 HEAD，
  pin 若在 checkout 内会被改写。

## 二、四个消费者

| 消费者 | 用途 | 取值方式 |
|---|---|---|
| `tools/launch_pinned_production.py` | 生产启动校验 | `paths` 优先，缺失时向上找 `.worktrees/prod` |
| `tools/check_mainline.py` | 主线三方对账 | `paths.PRODUCTION_PIN` |
| `tools/repin_production.py` | repin 并回写 `expected_commit` | `paths.PRODUCTION_PIN` |
| `config/paths.py` | 唯一定义 | `MAIN_REPO / ".worktrees" / "prod"` |

`MAIN_REPO` 之所以在 worktree 内也解析到主仓，是因为 worktree 的 `config/` 是指向主仓的
**目录 junction**（`config/paths.py` 的 `_self_repo()` 用 `Path.resolve()` 跟随它）。

## 三、launcher 的解析优先级

1. `--manifest <path>`（测试与人工排查）
2. 环境变量 `WINTER_PRODUCTION_PIN`
3. 向上逐层查找 `<ancestor>/.worktrees/prod/PRODUCTION_PIN.json`（**规范位置，优先命中**）
4. `<ancestor>/PRODUCTION_PIN.json`（2026-10-17 之前的旧布局，仅兼容）

解析只看 `__file__`，**从不看 `Path.cwd()`**：计划任务、桌面双击、任意 shell 启动得到的
是同一个文件。

## 四、启动链路（正常入口）

```
E:\Desktop\Winter Agent OS V2.lnk
  -> E:\WinterAgent\Start-Winter-Agent-V2.cmd      （preflight --launch-gate）
  -> schtasks /Run /TN "WinterAgentV2Panel"
  -> pythonw E:\WinterAgent\.worktrees\prod\repo\tools\launch_pinned_production.py
       cwd = E:\WinterAgent\.worktrees\prod\repo
  -> verify_pin: commit == expected_commit, 四个 mounts 与 data_root 同源, 代码树干净
  -> WINTER_AGENT_DATA_ROOT=E:\WinterAgent, runpy tools/control_panel.py
```

生产**代码**树是 `.worktrees\prod\repo`（钉在 commit），生产**数据**根是 `E:\WinterAgent`。
两者不是同一个目录，这是设计，不是重复。

## 五、2026-10-18 的故障与修复

**症状**：`E:\PRODUCTION_LAUNCH.log` 反复出现
`PinError: production pin manifest unreadable: E:\PRODUCTION_PIN.json: [Errno 2] ...`

**根因**：launcher 用 `CODE_ROOT.parent / "PRODUCTION_PIN.json"` 推导 manifest。

| 从哪启动 | CODE_ROOT | 得到的 manifest | 结果 |
|---|---|---|---|
| 计划任务（worktree） | `...\.worktrees\prod\repo` | `...\.worktrees\prod\PRODUCTION_PIN.json` | 正确 |
| 主仓（开发/排查） | `E:\WinterAgent` | `E:\PRODUCTION_PIN.json` | 不存在，失败 |
| 旧 pin 遗留 | — | `C:\Users\xhw\PRODUCTION_PIN.json`（data_root 指向已删除的空壳） | 过时 |

**修复**：manifest 解析改为一处定义 + 向上查找；失败日志跟随 pin（`.worktrees/prod/`），
不再写盘根；`.workbuddy/` 与会话记忆加入"可脏路径"（宿主每天追加，主仓启动因此永远过不了
干净门槛）；`check_mainline` 与 `repin` 改用同一批常量。旧 pin 与盘根日志归档到
`materials/experiments/retired_20261018/` 后删除。

## 六、验收命令

```bash
# 三个不同 cwd，输出必须完全一致
E:\WinterAgent\.venv\Scripts\python.exe E:\WinterAgent\tools\launch_pinned_production.py --check-only
cd C:\ && E:\WinterAgent\.venv\Scripts\python.exe E:\WinterAgent\tools\launch_pinned_production.py --check-only
cd E:\ && E:\WinterAgent\.venv\Scripts\python.exe E:\WinterAgent\tools\launch_pinned_production.py --check-only

# 预期：CODE_COMMIT=<sha> WORKTREE_CLEAN=true DATA_ROOT=E:\WinterAgent
E:\WinterAgent\.venv\Scripts\python.exe E:\WinterAgent\tools\check_mainline.py
# 预期：RESULT: MAINLINE_OK
```

## 七、禁止事项

- 不要在 `E:\WinterAgent\PRODUCTION_PIN.json` 或盘根放第二份 pin。
- 不要用 `git checkout` 直接切换 worktree 分支来替代 `repin_production.py`：
  四个数据目录是 junction，checkout 会透过 junction 回滚真实数据（2026-09-29 已付代价）。
- 不要把 `expected_commit` 手改成主仓 HEAD 而不跑 repin：worktree 与 pin 必须同 commit。
