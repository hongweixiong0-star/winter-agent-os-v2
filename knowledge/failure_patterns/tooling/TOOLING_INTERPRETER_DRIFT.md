# TOOLING_INTERPRETER_DRIFT

- **分类**：`TOOLING_MISSELECTION`（根因大类：`ENVIRONMENT_BLOCK` 的子类——依赖的所有权与启动器漂移）
- **记录日期**：2026-09-17
- **记录者**：winter-agent-v2-dev（寒野），依据活进程命令行、逐模块导入实测、
  `learning/executor_backend.jsonl` 与 `learning/control_panel/latest.log`

## 事实

MAA 一直可用（`MaaFw v5.12.3`），但**跑生产的那条链上解释器里没有它**——
依赖装在一个解释器里，生产用另一个解释器启动，两者之间没有任何检查。

| 项 | 事实 | 来源 |
|---|---|---|
| 正在运行的面板 | `...\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe tools\control_panel.py`（PID 23268） | `Get-CimInstance Win32_Process` |
| 该解释器缺什么 | `maa`、`cv2`、`rapidocr_onnxruntime`、`adbutils` 全部 `ModuleNotFoundError` | 逐模块导入实测 |
| 面板如何派生 worker | `PYTHON_PATH = Path(sys.executable).with_name("python.exe")` ⇒ worker 继承面板解释器 | `tools/control_panel.py:38`（改前） |
| 生产日志里的唯一痕迹 | `[executor] MAA requested but unavailable (MAA_IMPORT_FAILED:ModuleNotFoundError); observations stay on ADB` | `learning/control_panel/latest.log`（只由 worker stdout 写入） |
| `.ps1` 启动器 | 同样 pin 那个解释器，跑 `tools/run_live.py`；而 `winter_agent_v2.matchers` 在模块顶层 `import cv2` ⇒ **该路径根本跑不起来** | `Start-Winter-Agent-V2.ps1:11`（改前） |
| `.cmd` 启动器 | 用 `Python312`（有 maa/cv2/rapidocr，缺 adbutils）⇒ 与上面**又是第三个**解释器 | `Start-Winter-Agent-V2.cmd`（改前） |
| 代价（潜在） | 被提升到 MAA 的技能若在该链上执行，取帧走 ADB `324 ms` 而不是 MAA EmulatorExtras `8.92 ms`（**36×**，20 次交替实测） | `backend_routing.json` device.evidence |

**影响范围的诚实界定**：`learning/executor_backend.jsonl` 全部 521 行中，
`used_backend=ADB` 的每一行都属于**按设计留在 ADB** 的技能；
10 个已提升技能（`BACK / CLOSE_POPUP / DISMISS_BATTLE_VICTORY / INTEL_HERO_DISPATCH /
INTEL_HERO_START_MARCH / OPEN_HOME / OPEN_INTEL / SEARCH_RESOURCE / SELECT_RESOURCE /
START_GATHER`）在执行时**全部走了 MAA**。所以这次**不是已经付出的成本，而是潜在缺陷**：
下一次 AUTO 轮次一旦命中这些技能，就会静默走慢路径，而运行看起来完全正常。

## 根因

1. **依赖的所有权没有写成机器可读的断言**。`docs/AVAILABLE_TOOLING.md` 与
   `tool_registry.json` 记录了"MAA 已装"，但没记录"**在哪个解释器里**"。
2. **启动器把解释器当成路径常量**（`.ps1` / `.cmd` 各写一份，且不一致），
   第三个解释器（Codex 运行时）连启动器都没有出现过——它是被上一个会话直接以
   `sys.executable` 起的，于是绕过了所有文档。
3. **派生 worker 用 `sys.executable`**：把"面板恰好跑在哪个解释器里"这个实现细节
   变成了生产约束，而面板是 GUI，谁起它都合法。
4. **降级只写 stdout**。`executor_router` 把 `unavailable_reason` 写进台账，方向是对的，
   但台账记的是**已执行**的步骤；降级发生在执行之外，所以台账反而证明不了它。
   （同一个教训在 `TOOLING_MISSELECTION_MAA_UNUSED` 里写过一次："协商结果必须落盘记录"，
   那条被遵守了——协商结果**确实**落盘了——但没有人**比对**它。）

## Lesson（写入永久行为）

1. **要求表必须由代码声明**：`winter_agent_v2/runtime_env.py::REQUIREMENTS` 是唯一来源，
   每个模块写明它服务哪条轴、缺了会坏什么。MAA 只在 `config/v2.json →
   executor.maa.enabled=true` 时是硬要求。
2. **解释器必须被证明，不能被假定**：`resolve()` 逐个探测候选（config 覆盖 →
   `ocr.module_path` 反推的 venv → 约定 venv → 当前解释器），返回**第一个真正合格**的，
   并把跳过哪一个记在 `fell_back_from`。探测在**子进程**里做——提问的进程往往正是
   那个 import 不进来的进程。
3. **worker 不许继承 `sys.executable`**：`tools/control_panel.py` 用 `runtime_python_path()`；
   即使面板自己被错误解释器启动，worker 也会被解析到生产解释器（实测：
   拿 Codex 解释器启动面板，worker 仍解析为 venv，blocker=None）。
4. **拒绝优于降级**：面板在解释器不合格时**不启动**，写 `stop_reason =
   RUNTIME_ENV_NOT_PRODUCTION_READY`，并把该 reason 加进 `ENVIRONMENT_FAILURES`
   ——拒绝启动是环境事件，不是 worker 崩溃，不许计入 `unexpected_worker_exits`。
5. **不许用 `pythonw` 探测或派生**：无控制台的解释器会把 import 错误变成不可见。
   `_as_python_exe` 一律把 `pythonw.exe` 映射回 `python.exe`。
6. **降级要能出现在事实文件里**：`01_CURRENT_TRUTH.md` §J 由
   `backend_state()` 生成，把 `used_backend` / `capture_backend` 分布与
   "已提升到 MAA 却跑了 ADB 的技能"并列。**记下来还不够，要并排比对。**

## 触发条件（再次出现即按本卡处理）

- 新写 / 修改任何启动器、快捷方式、计划任务、CI 步骤里出现 python 路径
- 出现 `MAA_IMPORT_FAILED` / `MAA_CONNECT_FAILED` / `MAA_SCREENCAP_BLACK` 任一字样
- "为什么这么慢 / 为什么没有 MAA 节点生效 / 模板匹配为什么报 cv2 缺失"
- 新增任何需要第三方包的模块，却没有同时更新 `runtime_env.REQUIREMENTS`

## 相关

- `winter_agent_v2/runtime_env.py` — 要求表 + 解释器解析（唯一来源）
- `tools/preflight.py` — 一条命令回答"能不能跑"+"最近实际在用什么"
- `tests/test_runtime_interpreter.py` — 防回归（含"不许继承解释器"的源码断言）
- `knowledge/execution/backend_routing.json` — 逐技能后端选型与证据
- `knowledge/failure_patterns/tooling/TOOLING_MISSELECTION_MAA_UNUSED.md` — 上一张同族卡
