# 自动化记忆：Winter Agent OS V2 运行时健康 + 巨熊窗口盯盘

任务 ID：0a15208e-b16a-477d-a95e-af0b7c1d8599
性质：**只读盯盘**，不修改任何代码/状态文件。

## 检查口径（固定，每次照做）
- 快照 `learning/runtime_snapshot.json`：`agent_state` / `runtime_thread_alive` / `scheduler_loop_alive` / `stop_reason` **/ `updated_at`**。
  **updated_at 是关键**：>5 分钟可疑，>30 分钟判停。必须与 `learning/control_panel/panel.log` 末尾交叉验证。
- `panel.log` 自上次检查起是否出现 `bear`/`巨熊`/`rally`/`participate`（出现=巨熊窗口关键时刻，头号目标）。
- `learning/episodes.jsonl` 行数是否 > 10436。
- `learning/control_panel/gateway.json` 的 `available`。
- `learning/workbuddy_escalations.jsonl` pending 数是否 > 6。**实测口径：pending 数取 `learning/control_panel/pump.json`
  的 `last_line`（形如 `[escalation] skipped N`）与 `preload_note` 里的 `REAL_GAP_WAITING: N record(s)`**；
  escalations.jsonl 本身是事件流（event=escalation_created/pending_consumed/cancel…），无 status 字段，不能直接数 pending。

## 基线
- episodes.jsonl 基线 = **10436 行**（预载闸门被 6 条需真机记录关着，AUTO 每轮只做角色仲裁 ⇒ 停在 10436 是**预期**，不是故障）。
- escalations pending 基线 = **6**（2026-10-15 退役 11 条后）。
- 巨熊窗口历史约 14:00 前后；窗口没出现不是异常。
- 面板连续运行 = 约 58s 一轮的角色切换循环（1063040265 ↔ 1061663148），日志末尾会长这样，属正常。

## 历次执行
### 2026-10-15 20:00（首次记录）
- 5 项检查全部正常：快照 updated_at=20:00:02（新鲜）、panel.log 尾部无「面板关闭/worker 已停止」、
  bear 关键词 0 命中、episodes=10436（=基线）、gateway available=true/HEALTHY（17:58 的 HTTP_502 已恢复）、
  pending=6（=基线）。
- **唯一异常**：今日 5 次 WORKER_CRASH（均被 Watchdog ~5s 内自愈）：
  4 次 `WORKER_RESULT_MISSING: exit=3`（07:20 / 08:00 / 18:08 / 18:23 本地），
  1 次 `PermissionError WinError 5` 原子重命名 `global_scheduler_state.json` 失败（18:58:27 本地）。
  18:58:33 起至 20:00 约 62 分钟无新崩溃。判为**非致命、自恢复、当前稳定**，按只读口径仅报告。
- 恢复步骤（仅报告不执行）：操作员**双击 `Start-Winter-Agent-V2.cmd`**（计划任务路径）；`schtasks` 与脱离式启动被本机安全策略挡着。

### 2026-10-15 22:00（有变化，展开）
- **变化①：AUTO 已停机，但属「设计内让权」，非崩溃。** 快照 agent_state=IDLE / runtime_thread_alive=false /
  scheduler_loop_alive=false，updated_at=20:38:00 本地（距今约 84 分钟 ⇒ 按口径判停）。
  快照这次**如实**反映状态（不是「过期读数撒谎」那个坑），与日志时刻一致。
  panel.log 末尾：「20:37:17 机器归属：已切到 Manual（用户）· work buddy 使用 · 预计 3000 分钟」→
  「20:38:00 ⏹ 未进入下一轮：机器归 WorkBuddy 使用（Manual 模式）：AUTO 不进入下一轮，**交还后自动恢复**」。
  ⇒ 中午 12:06:02 的「面板关闭 / worker 已停止」（panel.log 行 184-185）是旧事件，**本次末尾无崩溃关闭印记**。
- **变化②：gateway 回落 DOWN（异常，重点）。** gateway.json available=false / reason=GATEWAY_UNREACHABLE /
  state=DEGRADED / consecutive_failures=42 / restart_attempts=20 / backoff 300s / last_ok_at 空，
  checked_at 21:57:46。对比 20:00 的 available=true/HEALTHY ⇒ **回落到不可达**。
  旁证：pump.json 仍活跃（written_at=22:02:02，last_tick=22:02:02，process=15300），
  unknown_note 显示问答已走「本地 planner 在轮内兜底」，故网关断未阻断问答通道。
  ⇒ 结论：**面板 AUTO 让权停机 ≠ 全停**，升级泵仍在跑。
- **正常项：** bear/巨熊/rally/participate 在 panel.log **0 命中**（今日 11:27 起），巨熊窗口未现，属基线内正常；
  episodes=10436（=基线，预期）；pending=`[escalation] skipped 6` + `REAL_GAP_WAITING: 6 record(s)` **=基线 6**。
  今日 WORKER_CRASH 3 次（18:08:40/18:23:49/18:58:27），自 18:58:27 起 3 小时无新崩溃。
- 恢复步骤（仅报告不执行）：AUTO 待**机器交还后自动恢复**；若需立即恢复，操作员**双击根目录 `Start-Winter-Agent-V2.cmd`**（已存在，7150B）。
  网关断由面板/后台生命周期按 300s 退避自愈；若持续 DEGRADED，交还后随面板一并处置。

### 2026-10-16 00:04（有变化，展开）
- **变化①（关键新发现）：网关根因定位。** `C:\Users\xhw\AppData\Local\WinterAgentV2\gateway.log`
  内累计 **50 次 `Error: Cannot find module '../dist/codebuddy'`（MODULE_NOT_FOUND）**，
  源起 pid 12856 的启动命令路径
  `E:\work Buddy国内\WorkBuddy\resources\app.asar.unpacked\cli\bin\codebuddy --serve --port 8080 --session-id winter-agent-v2`。
  该 shim 的同级 `../dist/codebuddy` 不存在 ⇒ **每次拉起即崩**，端口 8080 未监听（netstat 无 :8080）。
  ⇒ 结论：**不是本项目代码/状态问题，属 WorkBuddy CLI 安装态/路径问题**，退避自愈永远不可能成功。
- **变化②：网关退化在加重。** consecutive_failures 42→**90**，restart_attempts 20→**44**，
  available=false / reason=GATEWAY_UNREACHABLE / state=DEGRADED / last_ok_at 空 / checked_at 00:01:57。
  另 20:34:48 日志出现「验收 Soak 窗口结束：GATEWAY_SOAK = FAIL（5 样本 / 17.15 分钟）」。
- **无变化的异常（沿用 22:00 报告）：** AUTO 仍处「Manual 让权」停机（快照 updated_at=20:38:00 本地，
  距 00:04 约 3h26m ⇒ 按口径判停；如实反映状态）。panel.log **mtime 停在 Oct 15 20:38**、之后无新行，
  末尾即 20:38:00「机器归 WorkBuddy 使用（Manual）…交还后自动恢复」；
  `面板关闭/worker 已停止` 仅 12:06:02（行 184-185）**旧事件**。
- **正常项：** bear/巨熊/rally/participate 近 5000 行 **0 命中**；episodes=10436（=基线，预期）；
  pending=`[escalation] skipped 6` + `REAL_GAP_WAITING: 6 record(s)`=基线 6；
  WORKER_CRASH 今日仍 3 次（18:08:40 / 18:23:49 / 18:58:27），自 18:58:27 起约 5h 无新崩溃。
- 旁证：pump.json 仍活跃（written_at/last_tick=00:03:49，process 15300），`unknown_pending=14` 问答等待，
  通道已退役靠「本地 planner 轮内兜底」⇒ 网关断未阻断问答。
- 恢复步骤（仅报告不执行）：**网关这条不是双击 `Start-Winter-Agent-V2.cmd` 能解决的**——
  需操作员核对 WorkBuddy 的 `codebuddy` CLI 是否完整（`...\app.asar.unpacked\cli\bin\codebuddy` 的 `../dist/codebuddy` 缺失），
  必要时修复/重装客户端；AUTO 本身待机器交还（归属预计 3000 分钟，约自 20:37 起）自动恢复。

### 2026-10-16 02:05（无新增变化，简版）
- 五项检查与 00:04 完全一致：快照 updated_at 仍 20:38:00 本地（距今 ~5h27m ⇒ 判停，Manual 让权非崩溃）；
  panel.log mtime 仍 Oct 15 20:38:00、零新行，末尾无崩溃关闭印记（12:06:02 旧事件）；bear/rali/participate 0 命中；
  episodes=10436=基线；pending=skipped 6 + REAL_GAP_WAITING 6 =基线；10-16 无新增 WORKER_CRASH。
- 唯一持续项（无新面貌）：Gateway 仍 DOWN，退避计数单调爬升 consecutive_failures 90→**136**、
  restart_attempts 44→**67**、gateway.log MODULE_NOT_FOUND 50→**73**；端口 8080 仍未监听。
  根因仍为 `E:\work Buddy国内\...\cli\bin\codebuddy` 缺 `../dist/codebuddy`（00:04 已定位，属客户端安装态）。
- 旁证：pump.json 活跃（tick 02:04:52、process 15300、unknown_pending=14）⇒ 问答走本地兜底未受阻。
- 判据更新：**网关该项属「已定位的持续异常」，只要计数单调爬升且根因/现象不变，后续按一句话带过，不再展开。**

### 2026-10-16 04:06（无新增变化，简版）
- 五项与 02:05 完全一致：快照 updated_at 仍 20:38:00 本地（距今 ~7h28m ⇒ 判停，Manual 让权非崩溃）；
  panel.log mtime 仍 Oct 15 20:38:00.962、零新行，末尾即「20:38:00 ⏹ 未进入下一轮：机器归 WorkBuddy 使用（Manual）…交还后自动恢复」，
  无崩溃关闭印记（12:06:02 仅行 184-185 旧事件）；bear/巨熊/rally/participate **0 命中**；episodes=10436=基线；
  pending=`[escalation] skipped 6` + `REAL_GAP_WAITING: 6 record(s)`=基线 6；今日（10-16）无新增 WORKER_CRASH。
- 唯一持续项（无新面貌）：Gateway 仍 DOWN，计数继续单调爬升 consecutive_failures 136→**184**、
  restart_attempts 67→**91**、gateway.log MODULE_NOT_FOUND 73→**97**；端口 8080 仍未监听。
  根因仍为 `E:\work Buddy国内\...\cli\bin\codebuddy` 缺 `../dist/codebuddy`（属客户端安装态，非本项目问题）。
- 旁证：pump.json 活跃（tick 04:05:59、process 15300、unknown_pending=14）⇒ 问答走本地 planner 兜底未受阻。

### 2026-10-16 06:07（无新增变化，简版）
- 五项与 04:06 完全一致：快照 updated_at 仍 20:38:00 本地（距今 ~9h29m ⇒ 判停，Manual 让权非崩溃）；
  panel.log mtime 仍 Oct 15 20:38:00.962、零新行，末尾即「20:38:00 ⏹ 未进入下一轮：机器归 WorkBuddy 使用（Manual）…交还后自动恢复」，
  无崩溃关闭印记（12:06:02 为旧事件）；bear/巨熊/rally/participate **0 命中**；episodes=10436=基线；
  pending=`[escalation] skipped 6` + `REAL_GAP_WAITING: 6 record(s)`=基线 6；10-16 无新增 WORKER_CRASH。
- 唯一持续项（无新面貌）：Gateway 仍 DOWN，计数继续单调爬升 consecutive_failures 184→**230**、
  restart_attempts 91→**114**、gateway.log MODULE_NOT_FOUND 97→**120**；端口 8080 仍未监听。
  根因仍为 `E:\work Buddy国内\...\cli\bin\codebuddy` 缺 `../dist/codebuddy`（属客户端安装态，非本项目问题）。
- 旁证：pump.json 活跃（tick 06:07:18、process 15300、unknown_pending=14）⇒ 问答走本地 planner 兜底未受阻。

### 2026-10-16 08:09（无新增变化，简版）
- 五项与 06:07 完全一致：快照 updated_at 仍 20:38:00 本地（距今 ~11h31m ⇒ 判停，Manual 让权非崩溃）；
  panel.log mtime 仍 Oct 15 20:38:00.962（98116B、999 行）、零新行，末尾即「20:38:00 ⏹ 未进入下一轮：机器归 WorkBuddy 使用（Manual）…交还后自动恢复」，
  无崩溃关闭印记（12:06:02 仅行 184-185 旧事件）；bear/巨熊/rally/participate **0 命中**；episodes=10436=基线；
  pending=`[escalation] skipped 6` + `REAL_GAP_WAITING: 6 record(s)`=基线 6；10-16 无新增 WORKER_CRASH（panel.log 内 3 次全为 10-15 旧事件）。
- 唯一持续项（无新面貌）：Gateway 仍 DOWN，计数继续单调爬升 consecutive_failures 230→**278**、
  restart_attempts 114→**138**、gateway.log MODULE_NOT_FOUND 120→**144**；端口 8080 仍未监听。
  根因仍为 `E:\work Buddy国内\...\cli\bin\codebuddy` 缺 `../dist/codebuddy`（属客户端安装态，非本项目问题）。
- 旁证：pump.json 活跃（tick 08:09:18、process 15300、unknown_pending=14）⇒ 问答走本地 planner 兜底未受阻。
