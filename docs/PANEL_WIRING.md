# 控制面板接线表（GUI = 视图 + 控制面，不是状态源）

操作者要求：**看得到 + 接得上 + 数据是真的 + 按钮真的能控制 + 状态变化能同步 + 异常能正确显示**，
并禁止一切展示型假接线。这份表逐项列出**每个显示值的真实来源**、**它是怎么被读的**、
**来源沉默时显示什么**，以及**它被哪条验证证明过**。

自动验证：`python tools/verify_panel_wiring.py`（独立重算生产源的值，与 GUI 派生函数逐项比对，
不读源码、不看注释）。2026-09-17 实测 **16/16 PASS**。

---

## 一、顶部状态栏

| 单元格 | 真实来源 | 读取方式 | 来源沉默时 | 证明 |
|---|---|---|---|---|
| **V2大脑** | `learning/runtime_snapshot.json` 的 `agent_state`（由 worker 写） | 面板每 1.5s 读文件 | `● 等待` | 集成测试读回单元格 |
| **MAA** | ① 生产解释器**子进程探测**（真跑一次 `import maa`）② `learning/executor_backend.jsonl` 的 `preferred/used/fallback_used/attempts[].error` | `runtime_env.resolve_for_project()` + 读台账末 200 行 | `● 未初始化`（台账一行都没有） | `verify_panel_wiring.py` 独立重算 = 一致 |
| **MuMu** | 真实 `ADBDevice.status()`（`adb shell wm size` + `dumpsys window`） | 独立 daemon 线程，每 10s 一次，**只读** | `未探测`（还没探过） / `● 未连接（原因）`（探过且失败） | 见下方 §三 的断线实测 |
| **游戏** | 同上，比对真实前台包名与 `config.device.package_name` | 同上 | `未读取` | 同上 |
| **页面** | `runtime_snapshot.page`（Vision→WorldState 的真实产物） | 每 1.5s 读文件 | 运行中→`未知（识别中）`；空闲→`未读取` | 集成测试断言无 `未知 / 待识别` |
| **AUTO** | **面板自身的控制状态**：`self.process.poll()` / `starting` / `paused` / `stop_requested` / `repeat_after_id` | 纯函数 `auto_cell()`，**不读任何状态文件** | 无 worker 且无排程 → `● 已停止` | 有测试用 AST 断言该函数不出现 `snapshot/agent_state/runtime_store` |
| **WorkBuddy** | `workbuddy_escalations.jsonl` 的 fold + `workbuddy_bridge.is_available()` | 文件 fold（每 1.5s）+ daemon 线程每 5s 探一次网关 | 网关不可用→`● 不可用（原因）`；无 job→`● 待命` | 见下方 §四 |
| **时间** | `datetime.now()` | 每 1s | — | — |

**MAA 为什么有 5 个取值而不是 4 个。** 操作者列的是 `正常 / ADB降级 / MAA不可用 / 未初始化`。
实测（2026-09-17）：近 200 步里 **`preferred_backend=MAA` 的 30 步全部真的走了 MAA、零降级**，
但**最后一次 MAA 执行是 64 分钟前**，而循环一直在跑 ADB-only 技能。
只看偏好会显示"正常"；只看降级会显示"正常"；两者都在说过去。
所以单元格是 `● 正常 · 1.3 小时前无 MAA 执行` —— 探测说明**能力完好**，
新鲜度说明**证据很旧**，两个事实都给出来，一个都不编。

## 二、当前决策（右侧）

| 字段 | 真实来源 | 沉默时 |
|---|---|---|
| 执行后端 | `executor_backend.jsonl` **最后一行**的 `used_backend` + `capture_backend` + `latency_ms` | `未读取` |
| 当前 Goal / Skill | `runtime_snapshot.current_goal / current_skill` | `未读取` |
| 当前状态 | `runtime_snapshot.stop_reason` 经普通天气停机表 | `等待` / `未读取` / `未知（原因未分类）` |
| 为什么执行 / Preconditions / Verifier / 下一步 | `runtime_snapshot` 对应字段 | `未读取` |
| Preconditions | `runtime_snapshot.preconditions`（列表拼接） | `未读取` |

**执行后端不许由 `preferred_backend` 推断。** 两种 ADB 必须分开：
`preferred=ADB` 是**技能未迁移**（按设计），`preferred=MAA 且 used=ADB` 或 `fallback_used=true`
才是**真降级**。`verify_panel_wiring.py` 各有一条断言。

## 三、设备断线（操作者 §9 第 1–2 项）

| 场景 | 做法 | 结果 |
|---|---|---|
| MuMu 连接 → GUI 正确 | 真实 `ADBDevice.status()` 独立读一次，与单元格比对 | ✅ `● 已连接 127.0.0.1:7555 720x1280`，`游戏=运行中` |
| MuMu 断开 → GUI 同步变更 | **未拔真机**（操作者的 AUTO worker 正在用这台客户端）。改在 ADB 边界做等价负例：`ADBDevice` 指向 `127.0.0.1:59999`（无人监听）→ 真实 ADB 失败 | ✅ `● 未连接（ADBDevice.status() raised RuntimeError: adb device ... not found）` |

> **这一步抓到过一个真实的假接线**：探测失败时探针把 `status` 存成 `None`，
> 单元格于是显示 **`未探测`** —— 把"设备不在"说成"还没读"。
> 已修：探针状态区分 `ok=None`（没探过）与 `ok=False`（探过且失败），
> 并由 `test_a_failed_probe_is_a_disconnection_not_a_missing_reading` 钉住。

## 四、WorkBuddy（§9 第 7–10 项）

| 场景 | 做法 | 结果 |
|---|---|---|
| 网关在线 | 用**运行中网关真正接受的**口令探 `GET /api/v1/health` | ✅ `网关正常 · 检查于 22:54:44` |
| 网关停止 | 真杀进程（PID 28564），端口释放后重读 | ✅ `网关不可用 · 网关不可达（未启动或端口不同）`，WorkBuddy 卡片 → `● 不可用` |
| 网关恢复 | 重启网关后重读 | ✅ 回到 `网关正常 · 检查于 22:55:55` |
| 真实 Job 运行 | 让**生产队列适配器**提交台账里**真实存在的待办缺口**（`SCAN_MAP_FOR_BEAST\|BEAST_SCAN_NOT_PROVEN`，由无人值守循环真实记录） | 提交前 `● 排队` → 提交后 **`● 开发中（859e3787）`**，Job=`859e3787`，模型=`deepseek-v4.1-flash`，状态=`SUBMITTED` |
| Job 完成 → 真实结果 | 读已完成 job 的 fold | ✅ `job=f465a6c9 model=glm-5.3-flash state=COOLDOWN outcome=TEST_PASS live_improvement=否 duration=1.3 小时` |

**没有为了 GUI 造过任何 job。** 那次提交用的是生产适配器（AUTO hook 同一个函数）
针对生产 episode 里真实存在的失败签名；缺的只是一个**持有可用网关口令的进程**
（面板自己的环境里是过期口令，所以 AUTO 只能建单）。

网关判定带**时效**：超过 3 个轮询周期（15s）就改说 `网关状态待测（最近检查 …）`，
不让一分钟前的"正常"冒充当前状态。

## 五、Capability KPI 与能力表（§9 第 11 项）

| KPI | 真实来源 | 实测值 |
|---|---|---|
| 已读取特性 | `capability_catalog.json`（角色可用性/解锁状态已读，或真机尝试>0） | 35 |
| 已实现 | `implementation_status == EXISTING` | 70 |
| Live Tried | `live_attempts > 0` | 34 |
| Live Verified | `lifecycle == LIVE_VERIFIED` | 32 |
| Stable | **Skill Registry 的 `SkillState.STABLE`** | **0**（VERIFIED 46 / CANDIDATE 44 / BLOCKED 2） |
| 从未尝试 | `lifecycle == MISSING` 且 0 次真机 | 452 |
| Blocked | 带 `blocked_reason` | 3 |
| WorkBuddy Queue | 升级台账 fold 的活跃数 / 累计数 | 1 活跃 / 3 累计 |

**每张卡都标注来源文件。** 数值**没有一个是写死的**：`overview_kpis()` 每次现算，
并且有一条测试把 `capability_catalog` 副本里的 `LIVE_VERIFIED` 全改成 `MISSING` 后
断言 KPI 从 32 变 0（**在副本上做，不碰生产目录**）。

## 六、按钮（§6）

| 按钮 | 真实动作 | 证明 |
|---|---|---|
| 开始自动运行 | `start()`：先跑解释器预检（不合格就**拒绝启动**并写明原因）→ 读重载标记（有则延后）→ 用解析出的生产解释器起 `tools/run_live.py` 子进程 | 面板日志记录解释器路径；`AUTO` 单元格从 `● 启动中 → ● 运行中` |
| 暂停 | `pause()`：终止当前 worker 并**不再自动排下一轮** | AUTO 单元格 → `● 已暂停` |
| 停止 | `stop()`：置 `stop_requested` 并终止进程 | AUTO 单元格 → `● 已停止` |
| 刷新状态 | `refresh()`：重读全部真实源并重画 | 集成测试断言刷新后每格非空 |

按钮路径的**状态转移**由 `AutoCellTest` 覆盖（6 个用例）；
**现场读数**由 `verify_panel_wiring.py` 从进程表实际询问"有没有 `run_live.py` 在跑"并与单元格比对。

未做：**点击"开始/停止"的现场实测** —— 那会真的启停操作者正在跑的 AUTO 循环。
按"没有真实接线的元素宁可不显示"的原则，这里如实标注为未执行，而不是假装。

## 七、GUI 明确不做的事

- 不重新实现 Planner / Scheduler / Capability 判断 / MAA 状态判断 / Verifier / WorkBuddy 调度 / Runtime 状态机。
- 不维护第二份状态：所有值现读现算，`_refresh_runtime_snapshot` 每 1.5s 从源重建。
- 不新增 Manager / Registry / Scheduler。全部新增运行时只有一个 daemon 线程
  （`PanelProbes`：读设备 + 探网关）—— 因为 HTTP 与 `adb shell` 放进 Tk 回调会冻结窗口。
- 数据不足时显示 `未读取 / 未探测 / 待刷新 / 未解锁 / 不可用`，
  只有**真正读了没读出来**才显示 `未知`。

## 八、跑一次

```bash
E:/dongri-mumu-bot/.venv/Scripts/python.exe tools/verify_panel_wiring.py
```
