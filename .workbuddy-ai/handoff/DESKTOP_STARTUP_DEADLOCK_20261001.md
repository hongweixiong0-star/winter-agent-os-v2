# 桌面 GUI 启动失败：根因、修复与取证（2026-10-01）

**请求原文**：「桌面GUI启动失败，查找原因并修复」

**一句话结论**：`Start-Winter-Agent-V2.cmd` 用 preflight 的**一个退出码**当开窗闸门，而
2026-09-18 起该退出码的含义已经变成「AUTO 能不能跑」（含设备），于是**设备未就绪 →
拒绝开窗 → 唯一会去启动设备的那段代码永远不运行**，每次 60 秒重试跑同一条检查，
**结构上不可能收敛**。修复：把「AUTO 能不能跑」与「窗口能不能开」拆成两个问题两个裁决；
设备坏是**可修复**的（运行时会 `LAUNCH_GAME` 并退避重试），解释器坏在进程内**不可修复**。

- 修复提交：`b656f81`（行为修复）+ `743d3a2`（反回归测试与接线）
- 生产 pin：`783a219` → `b656f81` → `743d3a2`（两次都 `CLEAN_OUTSIDE_DATA`）
- 验证：修复后 07:41:34 AUTO 首次成功启动；设备被自愈拉起；两个完整轮次
  `15 executed / 13 verified`、`24 executed / 24 verified / 0 failures`

---

## A. 现象

操作员双击桌面入口后窗口不出现，`Start-Winter-Agent-V2.cmd` 打印
「运行环境预检未通过，已阻止启动」并 `pause`；面板进程不存在；`schtasks` 上次结果 = 1。

## B. 现场取证（按时间顺序，全部为原始读数）

1. **preflight 实测 FAIL，且 FAIL 的是设备**（开发树，07:26）：

   ```
   [OK  ] runtime interpreter : E:\无尽冬日智能体\.venv\Scripts\python.exe
   [FAIL] MuMu / device       : 127.0.0.1:7555 [720, 1280] foreground=app.lawnchair
   VERDICT: FAIL - core blocker(s): device
   ```

2. **设备本身是好的，只是游戏没在跑**（adb 直读）：

   ```
   mCurrentFocus=Window{... u0 app.lawnchair}      # 安卓桌面
   # 无 com.gof.china 进程，但包已安装
   ```

   分辨率正确（720×1280）、`127.0.0.1:7555` 可达 —— 即「模拟器在线，游戏没前台」，
   正是 `control_panel._ensure_device()` 会修的那种状态。

3. **`_ensure_device` 是唯一会启动 MuMu / 游戏的地方，而它只能在 AUTO worker 内运行。**
   `_run_unified_worker` 已用
   `retry_until_ready(self._ensure_device, initial_delay_seconds=5.0, max_delay_seconds=60.0)`
   包住它，且 `ENVIRONMENT_FAILURES` 里 `DEVICE_NOT_CONNECTED` / `DEVICE_CONNECT_TIMEOUT` /
   `MUMU_LAUNCH_FAILED` / `MUMU_LAUNCHER_NOT_FOUND` 齐全 —— 也就是说，**项目自己早就把
   设备问题定义成"运行时自愈事件"**，而不是启动闸门。

4. **面板日志复现了闭环**（`learning/control_panel/panel.log`，07:37–07:40，每 60 秒一轮）：

   ```
   07:37:27  启动预检：真实 preflight（MuMu / MAA / RapidOCR / Runtime / WorkBuddy Gateway）
   07:37:28  预检·核心：Runtime OK (...) · MuMu FAIL (127.0.0.1:7555 [720, 1280] 前台 app.lawnchair)
   07:37:28  预检未通过：核心环境不可用（device）；不启动 AUTO，60 秒后重试。
   ...（07:38:31 / 07:39:33 / 07:40:33 三次完全相同）
   ```

5. **修复前最后一个运行段**（`learning/auto_uptime.jsonl`，09-30T23:11:33Z）：

   ```
   "stop_reason": "暂无结构化结果", "stop_category": "SYSTEM_FAILURE",
   "healthy": false, "continues": false, "halt_reason": "收到停止请求（操作员主动停止）",
   "executed": 0, "verified": 0
   ```

   `learning/runtime_snapshot.json`：`agent_state=DEGRADED`、
   `stop_reason=RUNTIME_ENV_NOT_PRODUCTION_READY`、`reason="预检未通过：device"`。

## C. 根因

**接线漂移，不是逻辑错误。**

- 09-17 引入这个闸门时，preflight 只有解释器一项（防的是「解释器不能 import MAA」，
  当日实测：面板跑在通用 Codex runtime python 上，`MAA_IMPORT_FAILED`，每个提升到 MAA 的
  skill 静默降到 ADB、324 ms vs MAA 8.92 ms）。退出码 1 的含义是**解释器坏**。
- 09-18（`3e27a58`）给 preflight 加了设备段，并让退出码 = `core_ok`（含设备）——
  **但没同步改 `.cmd`**。该 commit 自己的信息写的是「Core failing **refuses AUTO**」，
  不是 refuses the window。
- 于是从那一天起，「设备必须已在前台」在无人察觉的情况下变成了开窗闸门。

**为什么这是死锁、而不是"更严格"**：`_ensure_device()` 只能在 AUTO worker 内运行，
而 AUTO 因设备不满足预检而拒绝启动 → `_ensure_device` 永远不被执行 → 每次重试跑同一条检查。
**收敛所需的那条路径，恰好被那道闸门挡住了。**

**为什么全绿**：`.cmd` 不被任何模块 import。纯函数测试能看见 preflight 有哪些闸门，
**看不见操作员入口问的是哪一个**。两个文件静默地不一致了两周，没有任何东西会变红。

## D. 修复

两个问题，两个裁决（`tools/preflight.py`）：

```
may AUTO run?        interpreter AND a usable-or-repairable device   (默认)
may the window open? interpreter only                                (--launch-gate)
```

| 位置 | 改动 |
|---|---|
| `tools/preflight.py` | 新增 `REPAIRABLE_SECTIONS=("device",)` / `LAUNCH_GATE_SECTIONS=("interpreter",)` / `DEVICE_REPAIRS`；`device_report()` 新增 `not_ready_reason`（`ADB_BINARY_MISSING` / `DEVICE_UNREACHABLE` / `EMULATOR_DOWN` / `RESOLUTION_MISMATCH` / `GAME_NOT_FOREGROUND`）+ `repair` + `repairable`；`report()` 把核心失败拆成 `blockers`（不可修复）与 `recovering`（可修复），新增 `launch_ok` / `launch_blockers`；`main()` 新增 `--launch-gate`，**JSON 与人类可读两条输出路径共用同一个裁决** |
| `Start-Winter-Agent-V2.cmd` | 闸门改问窗口那个问题：`tools\preflight.py --launch-gate` |
| `tools/control_panel.py` | `_log_preflight()` 新增「预检·可恢复」一行，让"恢复"不读成"在坏设备上静默启动" |
| `tools/preflight.py`（743d3a2） | 抽出 `LAUNCH_GATE_FLAG` 常量 + `build_parser()`，使"解析器是否认识启动脚本传的那个开关"可脱离探针被测 |
| `Start-Winter-Agent-V2.ps1` | 无面板的兄弟入口，**同一形状**（先闸门、后启动模拟器）；默认闸门改动顺带修好它；同时订正其失败文案 —— 旧文案「缺少 MAA / OpenCV / RapidOCR 之一」已不再覆盖真实失败面（解释器 / adb 缺失 / 分辨率不匹配） |

**守住边界的两个细节**（都在代码注释里写了为什么）：

1. 探测设备时抛出的 `ImportError` / `ModuleNotFoundError` **不**标为可修复 ——
   那属于解释器，而解释器是唯一真正不可修复的核心失败；若把它算作"运行时会修设备"，
   那一个不可修复的失败就会从"可修复"这个标题下面溜过去。
2. 运行时够不着的两种设备失败（adb 二进制缺失、配置分辨率不符）**仍是 blocker**。

## E. 验证（修复后的真实时间线）

**第一层：闸门裁决**（pin 树，修复后）

```
$ python tools/preflight.py --launch-gate   → exit 0
$ python tools/preflight.py                 → exit 0
VERDICT: PASS_WITH_RECOVERY - AUTO may run: E:\无尽冬日智能体\.venv\Scripts\python.exe ...
         recovering: device is not ready (GAME_NOT_FOREGROUND); the runtime does LAUNCH_GAME and retries with backoff
```

面板读的 JSON（`tools/preflight.py --json`）现在给出：
`core_ok=True`、`blockers=[]`、`recovering=['device']`、
`device.ok=False`、`device.not_ready_reason=GAME_NOT_FOREGROUND`、`device.repair=LAUNCH_GAME`。

**第二层：repin 后不需要重启面板就生效。** 面板在 `control_panel.py:5825` 是把
`tools/preflight.py --json` 当**子进程**跑、再读 JSON 里的 `core_ok` / `blockers`。
repin 后下一轮 60 秒重试自然通过 —— 实测 `panel.log`：

```
07:41:33  启动预检：真实 preflight（MuMu / MAA / RapidOCR / Runtime / WorkBuddy Gateway）
07:41:34  预检·核心：Runtime OK (...) · MuMu FAIL (127.0.0.1:7555 [720, 1280] 前台 app.lawnchair)
07:41:34  运行环境预检通过：E:\无尽冬日智能体\.venv\Scripts\python.exe
07:41:34  自动运行已启动：Goal 与 Universal Skill 由唯一 Scheduler 决定。
```

（`MuMu FAIL` 那行是**展示**读数，`device.ok` 此刻确实为 False，按设计不该被软化；
裁决走的是另一条线。）

**第三层：设备被自愈拉起**（adb 直读，修复后）

```
mCurrentFocus=Window{... u0 com.gof.china/com.unity3d.player.DDUnityLaunchActivity}
pidof com.gof.china → 3666
```

即 `_ensure_device` 真的执行了 `LAUNCH_GAME`，设备从未就绪变成就绪。

**第四层：生产循环恢复干活**（`learning/auto_uptime.jsonl`）

```
23:47:25Z  MAX_ACTIONS_REACHED / COMPLETED / healthy=true / executed=15 / verified=13 / failures=2
23:52:35Z  MAX_ACTIONS_REACHED / COMPLETED / healthy=true / executed=24 / verified=24 / failures=0
```

对照修复前最后一行 `executed=0 / healthy=false`。第二轮 24/24 全过、0 失败。
`runtime_snapshot.json` 的 `reason` 从 `预检未通过：device` 变成真实业务原因
（`collapsed_quick_panel_handle_and_pending_daily_board_scan`、`verified_visible_mammoth_target`）。

## F. 反回归测试（含变异验证）

`tests/test_startup_semantics.py::LaunchGateWiringTest`（4 项）**读启动脚本本体**，
因为被测的就是接线：

- `test_the_launcher_runs_preflight_exactly_once` —— 断言整行逐字等于
  `"%WINTER_PYTHON%" "tools\preflight.py" --launch-gate`（写字面量而非常量：
  改常量名却忘改启动脚本，正是要抓的漂移）。过滤器故意排除 `rem` 与 `echo` 行 ——
  `echo 诊断：python tools\preflight.py` 会让"这个文件提没提 --launch-gate"给出误导性的"提了"。
- `test_the_launcher_asks_the_window_question`
- `test_preflight_recognises_the_flag_the_launcher_passes` —— 未知开关 argparse 退 2，
  而 `.cmd` 的 `if errorlevel 1` 分不出"开关被拒"与"预检失败"，两者可见结果与死锁一模一样。
- `test_the_two_gates_are_asked_separately` —— 断言两道闸门不相等，防止启动闸门再把设备吃回去。

**变异验证（证伪过）**：把 `.cmd` 临时改回裸调用，`LaunchGateWiringTest` **4 项中 3 项变红**；
恢复后与 HEAD 逐字节一致（`git diff --stat` 为空），67 项复跑全绿。

测试计数：`test_startup_semantics.py` 33、`test_runtime_interpreter.py` 34、
启动/面板/运行时组合 **266 passed**。

## G. 未做与遗留（诚实标注）

1. **运行中的面板仍是旧进程代码。** 07:40:51 面板自己报了
   `CONTROL_PLANE_RELOAD_REQUIRED`（本进程加载 `783a219`，磁盘已是 `b656f81`+），
   并说明**自动重载已停用**、要「在安全点手动重启」。这是**设计内的**提示，不是本 bug：
   面板进程内只有 `_log_preflight` 那一行叙述是旧的，其余行为一致（AUTO 启动、设备自愈、
   worker 派生都在子进程里，已全部验证）。
   **我没有重启它** —— 理由：① 该提示明确要求"手动 / 安全点"；② 连续运行已启用，
   轮次之间只有约 3 秒间隙（07:52:35 结束 → 07:52:38 开新轮），没有空闲安全点；
   ③ 杀掉面板会按设计连坐杀掉 worker，中断一个正在进行的 episode。
   下一次操作员重启（`Start-Winter-Agent-V2.cmd`）会自动拿到 `743d3a2` 并清掉该提示。
2. `learning/auto_uptime.jsonl` 的 `repo_revision` 字段**一直为空**（本轮之前就如此，非本轮引入）。
3. `winter_agent_v2/formation_policy.py` 仍未跟踪（历史遗留）。
4. 本轮**没有**动第二 Scheduler / Executor / WorldState / Runtime Model —— 只改了启动闸门语义。

## H. 一句话教训（写给以后的自己）

> **一个退出码不能承载两个问题。** 当"这个检查"被加进一个已有的闸门时，
> 必须同时问：**还有谁在只读它的退出码？** 这里的答案是 `Start-Winter-Agent-V2.cmd`，
> 而它不被任何模块 import —— 所以不会有测试告诉你答案变了。
