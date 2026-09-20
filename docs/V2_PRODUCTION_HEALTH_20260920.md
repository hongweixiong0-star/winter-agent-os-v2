# V2 生产级体检报告（2026-09-20）

> 范围：**当前正式 GUI AUTO 的运行链路**。不是从零审计，不是重构。
> 所有结论标注证据来源；无法证实的写 `UNKNOWN`，不写推测。
> 本报告生成时 **面板未运行**（见 §1），因此**没有任何一项能被标为"真机验证通过"**。

---

## 1. 真实运行环境（§一，全部实测）

| 项 | 实测结果 | 证据 |
|---|---|---|
| 工作空间 | `E:\无尽冬日智能体` | `os.getcwd()` |
| Git | `HEAD == origin/main == 0cb30cc`；**无未提交 `.py`** | `git rev-parse` / `status --porcelain` |
| 生产解释器 | `E:\无尽冬日智能体\.venv\Scripts\python.exe`；`PROJECT_VENV=E:\无尽冬日智能体\.venv` | `sys.executable` / `runtime_env.PROJECT_VENV` |
| 旧目录依赖 | 候选里无 `E:\dongri-mumu-bot` | 会话内迁移轮已核；本轮 `PROJECT_VENV` 复核 |
| **正式 GUI** | **未运行**。`panel.pid=2272` 已死；`panel.log` 最后一条 `12:37:40` | 进程表 + `OpenProcess` + 文件 mtime |
| **AUTO** | **未运行**。`runtime_snapshot.updated_at=04:37:40Z`，已过期 **57.6 分钟** | `learning/runtime_snapshot.json` |
| Gateway | ✓ pid **25708** 监听 `127.0.0.1:8080` | `netstat -ano` |
| MuMu / ADB | ✓ `127.0.0.1:7555  device` | `MuMuManager` 目录内 `adb.exe devices` |
| MAA | 执行器在位（会话内实测 `MAA_MUMU_EXTRAS`、`capture()` 720×1280 **11.6 ms**，对 ADB 324 ms） | `learning/executor_backend.jsonl` + 迁移轮记录 |
| 设备租约 | ✓ 当前**无持有**；最后一条 `2026-09-19T05:16:32Z` 已 `released_at` | `learning/DEVICE_LEASE.json` |

### 1.1 面板的读数与真实情况**不一致**（这是 §一 要求重点验证的那一条）

`evidence/gui_workbuddy_loop/latest.json` 在 12:24–12:32 那次生产窗口里：`gateway_reachable 40/40`、`port_owner_legal`、`single_gateway`、`no_restart_loop`、`no_black_console` 全部通过——**而 `auto_running` 40/40 全为 False**。同一窗口的生产证据流里却有 **13 个真实完成的 AUTO 轮次**（约 39 秒一轮）。

⇒ **面板显示的"AUTO 未在运行"是错的**；成因是指标读的是**每轮全新进程**的线程标志（一轮里只有约 4 秒为真，~10% 占空比），而采样节拍约 12.5 秒，形成拍频锁相。已在 `45e7cb8` 改为累计计数（**未真机验证**）。

### 1.2 更要紧的：健康 ≠ 有进展

同一个 12:24–12:32 窗口的 13 个轮次**全部失败**，`last_success_time = null`，没有任何真实游戏状态变化——而网关、端口、GUI、队列全部显示"正常"。**这正是"不得把心跳正常等同于游戏任务正常执行"的实例**，而且它当天就真实发生过。

### 1.3 Soak 现状（含一处证据丢失）

当前 `latest.json` 是 **`started_at=05:21:02Z`（本地 13:21:02）、`sample_count=1`** 的窗口，`gui_pid=12320`（该进程已不存在）、`auto_rounds=0`、`queue_pump_heartbeat=null`。

- 该目录下**只有 `latest.json` 一个文件，没有任何归档** ⇒ 12:24 那个 **40 样本生产窗口的原始证据已被覆盖**，只剩本报告与会话记录里的数字。
- 代码里 `gateway_soak.py` 的模块注释写着"GUI 重启会开一个新的 soak，**旧文件留作历史**"——**与文件系统不符**（路径是固定的 `latest.json`）。这是"断言与事实相反"类缺陷，已派工单。
- **矛盾点（未解释）**：13:21 有面板进程 12320 启动了 soak 并写入证据，但 `panel.log` 在 13:21 **没有任何记录**（mtime 停在 12:37:40）。已定位的唯一构造点是 `tools/control_panel.py:2269`，测试用例全部显式传 `tmp_path` 证据路径（已核对 `tests/test_gateway_soak.py`），**所以这不是测试污染生产证据**。原因 `UNKNOWN`。

---

## 2. 正式生产调用链（§二）

### 2.1 唯一在跑的链

```
GUI「开始自动运行」
  → ControlPanel（唯一窗口；probe 守护线程 + AUTO worker 线程）
  → _run_unified_worker()                    tools/control_panel.py:4644
      · 先过生产环境闸门 runtime_env_blocker() → 不合格即 RuntimeError（:4647-4649）
  → 阶段链：每个阶段一个 run_live.py 子进程
      run_live.py --max-actions 24 --capture-dir runtime_auto/<stamp>   :4655
  → LiveRuntime
      → HybridVision(SemanticWorldVision, OCR)   → WorldState
      → GoalLibrary / RuleBrain                  → 本 run 内选 Goal 与 Skill
      → v2_registry（VERIFIED_ATOMIC 78 项）
      → Executor（MAA 主 / ADB 备）              → 游戏
      → Verifier → learning/episodes.jsonl
  → capability gate / escalation queue → WorkBuddy 开发队列
```

### 2.2 节点接入状态

| 节点 | 状态 | 依据 |
|---|---|---|
| GUI 唯一窗口 / probe 线程 | 已接入 | 进程与日志 |
| 生产环境闸门（解释器） | **已接入且会话内真机验证过** | 迁移轮：面板日志"运行环境预检通过"、活 worker 为 venv 解释器、MAA 原生 11.6 ms |
| 阶段链（面板层 Goal 选择） | 已接入 | `:4655` 起 |
| GoalLibrary / RuleBrain | 已接入，**未见真机验证** | run 内决策；本轮无活面板 |
| WorldState / Vision + OCR | 已接入，**部分被证伪** | 邮件帧误报（§4.2），已修未复验 |
| Observation Store | 已接入 | `observation_state.json` 有记录；同时**被写入过错误状态**（误报帧写入 `intel.claim_feedback`） |
| Skill Registry（`v2_registry`） | 已接入 | `VERIFIED_ATOMIC` 78 项 |
| Verifier | 已接入 | episodes 带 verification |
| Episode 证据流 | 已接入 | `episodes.jsonl` 2515 条 |
| Escalation → WorkBuddy 队列 | 已接入 | 台账 2807 条；当前有 Job 在跑 |
| **`_run_worker`（旧链）** | **仅存在代码、未接入** | 定义于 `:4726`，**全仓无生产调用者**；唯一引用是 `tests/test_runtime_interpreter.py:183` 断言其源码文本 |

**关于"旧链与当前 AUTO 是否混用"**：不混用。旧链是**不可达的重复实现**，但仍在仓库里并有一条测试维持它的形状——属于"失效但未清除"，不是并行执行。

### 2.3 链上**最严重的结构性问题**

阶段推进只认**成功态**，不认失败：

```
tools/control_panel.py:4713（并在 4730/4739/4830 等处重复）
if is_mail and first_payload.get("stop_reason") == "mail_all_clear" and ...
```

一个阶段只要不产出被认可的成功 `stop_reason`，**链就永远停在它上面**，后续阶段（Intel、野怪——真正消耗体力的两个）**永远轮不到**。2026-09-20 01:00–04:37 就是这样烧掉约 2 小时的：`DISMISS_INTEL_REWARD` 连败 30 次、`DISMISS_MAIL_GENERIC_REWARD` 连败 29 次，链始终在第一阶段。

---

## 3. 逐任务能力矩阵（§三，派生自生产证据流 2026-09-12 → 09-20）

| 类别 | episodes | 成功 | 失败 | 最近成功 | 可调度技能 | 判定 |
|---|---:|---:|---:|---|---:|---|
| 邮件 | 69 | 32 | 37 | 16.0 h 前 | 7 | 能进页面；dismiss 环节失败（3/38） |
| 日常奖励 | 41 | 34 | 7 | 16.0 h 前 | 5 | 基本可用 |
| 联盟 | 44 | 33 | 11 | 5.0 h 前 | 5 | 基本可用（`ALLIANCE_GIFTS` 0/11） |
| 探险 | 14 | 6 | 8 | 17.2 h 前 | 5 | 能进页面；`EXPLORATION_IDLE_CLAIM` 0/7 |
| 情报 | 537 | 445 | 92 | 13.1 h 前 | 17 | 最成熟；`DISMISS_INTEL_REWARD` 8/33 是同一误报 |
| 打野/巨兽 | 402 | 396 | 6 | 12.8 h 前 | 6 | **扫描 396 次全成，`BEAST_HUNT` 0 成 1 败** |
| 采集 | 464 | 296 | 168 | 16.5 h 前 | 5 | 可用但失败率高（`SELECT_RESOURCE` 60/46） |
| 训练 | 5 | 3 | 2 | 3.1 h 前 | 2 | 只在探索路径里被点到 |
| 科研 | 14 | 14 | **0** | 16.1 h 前 | 3 | 只验证了"能进页面" |
| 建筑 | 98 | 85 | 13 | 3.1 h 前 | 6 | `NAVIGATE_INFANTRY_CAMP` 6/10 |
| **竞技场** | **0** | — | — | **从未尝试** | **0** | 无实现 |
| **巨熊 / Rally** | **0** | — | — | **从未尝试** | **0** | 无实现 |
| **当前活动** | **0** | — | — | **从未尝试** | **0** | 无实现 |
| 地图/导航 | 399 | 366 | 33 | 0.5 h 前 | 4 | 可用 |

**体力相关（单列，因为它是 P0）**

| 技能 | 成功 | 失败 |
|---|---:|---:|
| `SCAN_MAP_FOR_BEAST` | 396 | 5 |
| `CLEAR_MAP_FOR_BEAST` / `BEAST_HUNT` | 0 | 1 |
| `CLAIM_FREE_STAMINA` | 10 | **235** |
| `OPEN_STAMINA_SOURCES` | 28 | 0 |

**七问逐类回答的汇总**（逐条溯源见上表与 §4）：

1. **今天知道要检查它吗？** 邮件/日常/联盟/探险/训练/Intel/野怪/采集：知道（在 `config/control_panel_state.json` 的 `task_enabled` 里且有阶段）。竞技场/巨熊/活动：**不知道**（无 Goal、无阶段、无可调度技能）。
2. **能真实进入页面吗？** 上表有成功记录的都算"能"；`OPEN_INTEL` 91 次、`OPEN_MAIL` 15 次、`OPEN_ALLIANCE` 9 次等。
3. **能可靠识别状态吗？** 邮件页**不能**（§4.2 误报，已修未复验）。
4. **有任务时能完成吗？** 情报与采集有闭环证据；**打野完全不能**（扫描 396 次、派兵 0 次）。
5. **能用真实状态变化证明吗？** 有 verifier + episode；但**本会话之前没有任何一项被"真机状态变化 + Verifier PASS"在最近 24 小时内证明**（最近一次真实成功是 04:06:52Z 的 `CLOSE_POPUP`）。
6. **不会做时是否生成能力缺口？** 会，且量很大（台账 2807 条、`escalation_created` 38 条）。但见 §4.6。
7. **没任务时是否正确等待/切换？** 阶段内有 `reserved_march_for_stamina` 这类良性结束（在 `run_live.py` 的 `accepted_stops` 里）；**但阶段之间没有预算**，所以"等待"会退化成"无限重试同一失败阶段"（§2.3）。

**区分**：竞技场/巨熊/活动 = **尚未实现**；`EXPLORATION_IDLE_CLAIM` 0/7 = **缺少执行能力**；`CLAIM_FREE_STAMINA` 235 败 = **真正的程序缺陷（待定位）**；`no_idle_march` 等 = **自然条件不满足**。

---

## 4. 长期无进展专项（§四，逐项给出调用位置与证据）

### 4.1 高优先级 Goal 连续失败、其他任务无法执行 —— **已定位并已修（未真机验证）**

- 位置：`winter_agent_v2/runtime.py:1161-1174`（失败路径不写 `goal_progress`，默认 `None`）+ `winter_agent_v2/capability_gate.py:312-317`（全 `None` 即中断计数）⇒ 阈值 3 的 `NO_GOAL_PROGRESS` deferral(`:510-536`) **永不触发**。
- 证据：30 次 + 29 次连续 episode，`goal_progress=null`、`executor_backend=""`、`after_screenshot=""`。
- 影响：一个学不会的 Goal 可以占据**全部**轮次，其它任务永远饥饿。约 2 小时。
- 处置：`0cb30cc`。

### 4.2 当前页面与 Goal / Skill 不一致 —— **已定位并已修（未独立复核）**

- 位置：`winter_agent_v2/vision.py:1144-1147`（旧行）。邮件收件箱被读成 `POPUP/INTEL_REWARD`：同一帧上 `PAGE_MAIL d=0.0`、`TAB_MAIL_SYSTEM_ACTIVE d=0.0` 等 6 个强邮件信号，输给 `POPUP_INTEL_REWARD_TITLE d=20.0 thr=22.0`。
- 证据：`dataset/raw/control_panel/runtime_auto/20260920_123335_422288/..._step_001_before_...png`（我本人打开确认为邮件收件箱）；会话内复跑分类器复现。
- 影响：邮件链永远拿不到 `mail_all_clear` ⇒ 后续阶段全断（与 §2.3 叠加）。
- 处置：`9ee62cc`（改为不再使用该内容裁剪，并在 `tools/probe_reward_popup_gate.py` 补上此前**被排除**的信号，覆盖被测分支）。

### 4.3 页面已打开、但 Verifier 误判失败 —— `UNKNOWN`

本轮未取得该形态的证据。已知 `verify_mail_reward_dismissed` 要求 after 为 `Page.MAIL`；在 §4.2 的误报下它**不会被调用**（目标解析不出、不发点击）。**未证实，不作为结论。**

### 4.4 同一奖励 / 弹窗 / 扫描被无限重复 —— **两个实例，均已定位**

1. 邮件弹窗 dismiss 连败（§4.2）。
2. **`SCAN_MAP_FOR_BEAST` 成功 396 次，`BEAST_HUNT` 成功 0 次**：机器整天扫地图找野怪，从不派兵。这是"体力零消耗"的直接机制。

### 4.5 体力大量积压、始终无法真正消耗 —— **已定位（多重阻断）**

- 观测到的体力值（527）**来自 2026-09-19T15:50，已过期**（观察存储按域 TTL，过期不复用）。
- 在邮件页面上，`GoalLibrary.discover` 的 board 里**根本没有体力类 Goal**（6 项都是面板/清扫流程）。
- 链到不了 MAP（§2.3），而体力只在 MAP 读得到。
- 即使到了 MAP：`SCAN_MAP_FOR_BEAST` 只扫不派（§4.4）。
- `CLAIM_FREE_STAMINA` 10 成 / **235 败**。
⇒ **不是"忘了消耗"，是四道阻断叠加**。P0 仍未达成。

### 4.6 开发任务完成后没有回到原任务验证 —— **倾向成立，但证据不足，标 UNKNOWN**

`learning/workbuddy_escalations.jsonl` 2807 条里，**没有任何一条带 `production_reuse_episode_id` 字段**。（该字段属于闭环对账机制，可能在别的存储里；本轮**没有**定位到它的写入方，因此不能断言"从不回验"。）会前一轮的 trace 该字段为空、判定为 `INCOMPLETE`，是倾向成立的旁证。**需要一个针对性核查，已列工单。**

### 4.7 角色身份 UNKNOWN 时任务状态写入错误角色 —— `UNKNOWN`（本轮无证据）

### 4.8 正式 AUTO 使用旧代码 / 错误解释器 / 未验证的新能力

- 解释器：**正确**（§1）。
- **旧代码：确有一例**。`panel.log` 12:37:40 记录面板加载的是 `6e8ba75`，而 HEAD 已是 `55d7746`，于是自行做了控制面重载——**重载后窗口没有恢复**（§5.1）。也就是说存在"运行中的 AUTO 用的是几十分钟前的代码"的窗口，且有实例。

---

## 5. 稳定性与测试可信度（§五）

### 5.1 启动 / 重启 / 异常恢复

- 面板**不能**在"检测到控制面代码变化"后可靠恢复：12:37:40 它按安全点重启窗口，之后 `panel.pid` 仍指向死 pid 2272，无人接手。根因：重启被委托给 `tools/panel_restart.py --restart`（`control_panel.py:4496`），而那次窗口是**从开发宿主拉起**的，重启助手跑在宿主进程围栏内，删除 `panel.pid` 的动作撞上宿主的安全删除护栏（`panel_reload.log` 的 `[safe-delete][SAFE_DELETE_BULK_CONFIRM_REQUIRED]`）。
- 判定：这是 `DEVELOPMENT_ENV_LIMITATION`，**§九 禁止在产品里为"造它的工具"生长绕行代码**，因此不在产品内修；正确做法是由操作员从桌面入口启动。
- **未验证**：官方入口 `Start-Winter-Agent-V2.cmd` 在操作员手里能否持续运行（本次从未以"非开发宿主父进程"的方式启动过）⇒ 这是 §一 里唯一一项**我没有也不能自行验证**的。

### 5.2 生产 / 开发隔离

- ✓ 解释器已隔离（`sys.executable` 为 venv）；隔离检查**未被放宽**：`control_panel.py:4647` 起 `runtime_env_blocker()` 不合格即 `RuntimeError`；`escalation_queue.py:3660-3673` 已改为走 `runtime_env.resolve()`，解析不到返回 `None` 而不是用错工具回答。

### 5.3 设备租约与跨进程竞争

- ✓ 无泄漏：最后一条租约 `released_at` 有值；释放走 `finally`。
- 竞争面：目前只有一个 Gateway、一个面板（且未运行），无双写者。

### 5.4 资源增长

- 截图/证据在 `dataset/raw/**` 持续增长；`evidence/`、`learning/` 亦持续追加。**本轮未测得增速与上限**（标 UNKNOWN）。

### 5.5 测试与证据可信度（问题清单）

1. **已知失败清单是错的。** 文档说"已知 9 项失败"，我用干净 `git worktree` 在 HEAD 上 A/B 证明**至少 11 项**（多出 `test_control_panel.py` 两项 + `test_reward_popup_source.py` 一项，且这三项**在 main 上本来就是红的**）。⇒ 任何"这是既存失败、与本次无关"的说法**不得引用那张表**，必须重derive。
2. **工作树脏时 runtime/goal 类测试不是回归信号。** `tests/test_live_runtime.py` 在干净 worktree **8 passed**，在 live tree **2 failed**；差异来自未提交的 `knowledge/goals/*.json`、`knowledge/game/capability_catalog.json`、`config/policy_state.json`（运行时会读）。
3. **咬合验证方法学**：我今天差点交付一个 green-but-useless 测试——只直接调 helper，于是把**生产调用点**改回旧行为后 **10 个测试全绿**。正解是恢复**生产代码里被替换掉的那一行**（改为走真实路径后同样操作 ⇒ 2 failed / 12 passed）。
4. **证据保留是单槽的**：`evidence/gui_workbuddy_loop/latest.json` 无归档，已被覆盖（§1.3）。
5. **仓库内遗留 1010 个未跟踪的测试临时文件（20.1 MB）**：`tools/_pt_bt`、`tools/_pt_v2`、`tools/_pt_tmp`、`tools/_pt_iso2`、`tools/_pt_codex_full_0bb`、`learning/pytest_tmp_nav` 等，**每个都含一份 `winter_agent_v2/**` 副本**。后果：`grep` 结果里约九成是噪声（本轮实测），"工作树是否干净"这个判断被持续干扰。
6. 全量基线：本轮已在后台启动 `pytest tests/ -q`，结果写入 `out_suite_baseline.txt`（见 §8 工单 T7）。

---

## 6. 已经修复的项目

**通过真机验证的：0 项。** 面板未运行，本轮没有任何一项获得"真实客户端 + 真实动作 + 真实状态变化 + Verifier PASS + 可追溯 Evidence"。下表全部是**离线或 A/B 验证**。

| 提交 | 内容 | 验证强度 |
|---|---|---|
| `45e7cb8` | Soak 的 `auto_gameplay` 由"瞬时线程标志"改为累计轮次计数 | 单元 + 咬合证明；**未真机** |
| `6f8e8b6` | 两项 `test_control_panel.py` 陈旧断言修正（更严，非放宽） | 干净 worktree A/B 证明既存；47 passed |
| `9ee62cc` | 邮件收件箱不再被读成奖励弹窗 | **已独立复核（§6.1，见下）**；作者测量 + 咬合证明；**未真机** |
| `7b712d8` | 第三项陈旧断言修正（先证明行为有据可依再改） | 实测四种 goal 决策 + 咬合证明 |
| `0cb30cc` | 学不会的 Goal 现在会喂给已存在的停滞 deferral，且理由不再说假话 | 8 个行为用例 + A/B 非回归 + 咬合证明；**未真机** |

---

## 6.1 `9ee62cc` 的独立复核结果（2026-09-20，**由本轮执行者独立完成**）

`9ee62cc` 动的是核心识别层，因此在把它当成可信之前，必须由**另一个执行者**重建前后分类器自行测量，
而不是采信作者的说明。结果如下。

**仪器**（第三次换代才有判决，前两代都不可用，如实记下）：
- 全 `observe()` 差分：实测 **1.3 s/帧 ⇒ 6747 帧需 2.5 h 以上**，成本不可接受。
- 六距离谓词扫描：快，但**量的是我重建的谓词，不是真标签**，并且**它给出了一个错误的警报**（见下）。
- **最终（漏斗 + 真标签）**：先按"被删掉的信号命中 ≤22、存活的整弹窗模板未命中 ≤6、两条负向对照都不命中"
  把语料收窄到候选帧，再在候选帧上跑**修复前/后两个真分类器**取真标签。

**结果**（语料 6747 帧，与作者同一总体）：

| 指标 | 值 |
|---|---|
| 候选帧 | 267 |
| **标签发生变化的帧** | **80** |
| 其中**带弹窗外壳**（= 真弹窗丢了标签，即回归） | **0** |
| 变化且不带外壳、**在邮件页** | **70** |
| 变化且不带外壳、不在邮件页 | 10 |

变化明细：`70 → MAIL`、`5 → UNKNOWN`、`3 → INTEL`、`1 → HOME`、`1 → MAP`。

**独立核对（不采信作者）**：那 70 帧变成 `MAIL` 是对的——**我自己测出**它们 `PAGE_MAIL ≤ 6`。
另外 10 帧只是"不再被错标成 `INTEL_REWARD`"；它们的新标签我**没有**做地面真值核对。

**重叠问题只核对了邮件侧**：我测到邮件页的 title 原始距离 **n=304, min=20, p50=30, max=40**（下限恰好 20）
⇒ 任何想排除邮件页的门必须 ≤19；真弹窗一侧（0..26、其中 85/217 ≥19）是**作者的测量，我没有独立重测**。
所以"没有阈值可分"这个**组合**结论成立，但**我的仪器只覆盖了邮件侧**，这一点不能含糊。

**我自己制造并纠正的一次错误警报**：六距离仪器曾报 `chrome=42`，看起来像 42 张真弹窗丢了标签。
**那是我错了** —— 我重建的谓词忽略了 `vision.py:1136` 的外壳分支**在它之前**执行，带外壳的帧早已返回
`GENERIC_REWARD`、**根本到不了**被删掉的那个谓词。换成真标签仪器后，同一问题给出 **0**。
⇒ 教训：**"我自己算出来的中间量"同样不是事实**；中间量必须用真路径校准。

**结论**：在 6747 帧上**未发现回归**，`9ee62cc` 可以保留并等待真机验证；**它仍然不是 `LIVE_VERIFIED`**。
候选清单已落盘 `learning/verify_vision_candidates.json`（267 条，可复查）。

---

## 7. 待修复工单（按实际影响排序）

| # | 级别 | 问题 | 证据位置 | 下一步 |
|---|---|---|---|---|
| T1 | **P0** | 正式 GUI/AUTO **当前未运行**，且开发宿主启动的窗口活不过控制面重载 | §1、§5.1 | 由操作员从 `Start-Winter-Agent-V2.cmd` 启动；这是唯一未被验证的一环 |
| T2 | **P0** | Soak 条件 7 可被**全失败窗口**判 PASS（计数器计所有退出码） | `run_live.py:351`；空转轮次 exit 2 | 已给出精确规格：只把 exit 0 计为 gameplay 证据 |
| T3 | **P1** | 链的阶段推进只认成功态 ⇒ 失败阶段永久占位，Intel/野怪永远轮不到 | `control_panel.py:4713` 等 | 给阶段加**有界失败预算**（§六.4 允许 Skip/Next），不能放宽验收条件 |
| T4 | **P1** | 打野只扫不派：`SCAN_MAP_FOR_BEAST` 396 成 / `BEAST_HUNT` 0 成 | 证据流 | 从 `BEAST_HUNT` 的 `goal_progress`/失败签名定位 |
| T5 | **P1** | `CLAIM_FREE_STAMINA` 235 败 | 证据流 | 取失败 episode 的帧与 verifier 判定 |
| T6 | **P1** | 开发任务完成后"回到原任务验证"未见证据 | `workbuddy_escalations.jsonl` 无该字段 | 定位 `production_reuse_episode_id` 的写入方 |
| T7 | P2 | 测试基线不实：已知失败清单少 3 项 | §5.5.1 | 后台全量跑完 → 以输出重建清单，写入 `04_OPEN_ISSUES.md` |
| T8 | P2 | 1010 个测试临时文件（20.1 MB）留在仓库内 | §5.5.5 | 列清单后**逐项**确认删除；不得通配符批量删 |
| T9 | P2 | Soak 证据单槽无归档，且注释断言"旧文件留作历史"与事实相反 | §1.3 | 让注释与文件系统一致（最小改法）或补归档 |
| T10 | P2 | 竞技场 / 巨熊 / 当前活动：0 实现、0 尝试 | §3 | 属能力缺口，按 Capability Preload 路线推进，不是 bug |
| T11 | P3 | 旧链 `_run_worker` 死代码仍在，且有测试维持其形状 | `control_panel.py:4726` | 确认无保留价值后清理（需单独授权） |

---

## 8. 尚未完成 / 下一项自动执行任务

**未完成（如实列出）**

1. `9ee62cc` 的**独立复核**没有做——负责它的 worker 被配额 429 打断两次（额度 **2026-09-21 12:29:50 GMT+8** 恢复）。它的爆炸半径声明目前**只是作者自己的测量**。
2. `T2` 的返工**未开始写**。
3. `T7` 全量基线**仍在跑**。
4. `§4.3` / `§4.6` / `§4.7` 三项为 `UNKNOWN`，需要针对性核查才能定性。
5. §一 中"官方入口能否持续运行"**无法由我验证**（需要操作员动手一次）。

**下一项自动执行任务（配额恢复后按序）**

1. `T2`：Soak 只把成功轮当 gameplay 证据 + 理由串说出停滞（规格已写好）。
2. `9ee62cc` 独立复核：重建前/后分类器，全语料 `(page, popup)` diff。
3. `T3`：阶段失败预算，这是解除"任务长期饥饿"的正解。
4. `T4` / `T5`：从真实失败 episode 的帧与 verifier 定位打野与免费体力两个高频失败。
5. `T7` / `T8`：重建测试基线、清理仓库内测试残留。

**一句话**：本轮真正的收获不是五个提交，而是把"V2 不消耗体力"从一句抱怨拆成了**四道可定位的阻断**（链不交棒 → 扫了不派 → 体力读数过期 → 免费体力领不到），并修掉了其中两根已经无法自愈的死锁。但**它们一个都还没有在真机上被证明**——因为机器现在什么都没在跑。
