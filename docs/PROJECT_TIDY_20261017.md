# 项目文件与过期内容整理（2026-10-17 执行记录）

> 指令来源：操作者「Winter Agent OS V2｜项目文件与过期内容全面整理指令」。
> 本文件是**执行记录**，不是待办清单：下面每一条都已在同一天做完，并附有可复跑的校验命令。
> 报告正文限 7 项，与指令要求一致。

## 一、正式根目录与入口

| 项 | 值 |
|---|---|
| 正式根 | **`E:\WinterAgent`**（原 `E:\无尽冬日智能体`，旧路径已无任何活跃引用） |
| 路径唯一事实源 | `config/paths.py`；`_DEFAULT_MAIN_REPO` 是全项目唯一一处根字面量 |
| 生产 pin | `E:\WinterAgent\.worktrees\prod\repo`（分支 `codex/production-pin-recovery`）+ `.worktrees\prod\PRODUCTION_PIN.json` |
| 桌面入口 | `Start-Winter-Agent-V2.cmd` / `.ps1`（根用 `%~dp0` / `$ProjectRoot` 派生，无字面量） |
| 计划任务 | `WinterAgentV2Panel` → `E:\WinterAgent\.venv\Scripts\pythonw.exe` + `.worktrees\prod\repo\tools\launch_pinned_production.py` |
| C 盘 junction | `C:\Users\xhw\.codex\worktrees` → `E:\WinterAgent\.worktrees`（指针，不是数据） |

**复核**：`python tools/check_mainline.py` → 三条不变量全 OK；
`cd .worktrees\prod\repo && python tools\launch_pinned_production.py --check-only`
→ `CODE_COMMIT=<sha> WORKTREE_CLEAN=true DATA_ROOT=E:\WinterAgent`。

## 二、删除数量

| 类 | 量 |
|---|---|
| 被 git 跟踪的文件 | **383**（225 临时/过期内容 + 158 被误提交的 `.pytest_tmp_r17` 测试临时目录） |
| 未跟踪的临时产物（主树） | **约 1,000**（481 个 `out*.txt`、236 个 `out_*`、56 个 `.probe*`、48 个 `_wb1002_*.py`、77 个无引用 `tools/*.py`、183 个一次性 `learning` 转储、9 个 `out_*` 截图目录等） |
| 生产 pin 树内未跟踪残留 | **52**（49 个一次性脚本 + `backups/` + `out/` + 2 个 txt） |
| 过期 worktree | **6 个**，并删掉 `E:\无尽冬日智能体_worktrees`（281 MB，含 245 MB seed） |
| 大块目录 | `p2p_agent/` 171 MB（2026-10-07 后无活动）、`codex_clipboard/` 11 MB、`debug/` 3 MB、`learning/_*` 58 MB |

**顺带**：C 盘从 **0 字节**恢复到 **60.5 GB 可用**（`Cursor\snapshots` 9.5 GB 与 `state.vscdb` 16.5 GB 迁到 `E:\HostData\Cursor`，原位留 junction）。

## 三、清理了哪些过期内容

1. `.gitignore` 补 12 条运行时产物规则（`knowledge/perception/{pages,candidates}`、
   `learning/{unknown_requests,tests_batched,recon_mail,fishing_performance_v2_replay,pytest_tmp_*,probe_*}`、
   `knowledge/ui/screenshot_audit`、`dataset/exploration`、`learning/{DEVICE_LEASE,MODE_STATE}.json`、`.worktrees/`）。
2. 109 条**已剪除且不可恢复**的证据帧登记到 `knowledge/provenance/pruned_evidence_20261017.json`
   （按技能分组：OPEN_MAP 59 / OPEN_QUICK_PANEL 43 / 其余 7），并给 `tests/test_evidence_integrity.py`
   加路径归一化（`\` 与 `/`、junction 拼写差异）与 1%/3 条的登记上限——登记是账，不是免死金牌。
3. 自相矛盾的识别节点：`knowledge/execution/backend_routing.json` 里
   `OPEN_EVENT_CALENDAR_FROM_HOME`（`preferred: ADB` + `recognition_backend: LEGACY`）带着一个
   `recognition` 节点。移掉节点，并在 `winter_agent_v2/pipeline_autogen.py` 加规则
   `LEGACY_DECLARATION_TAKES_NO_NODE`，让生成器**拒绝**再写回来。
4. `winter_agent_v2/capability_bootstrap.py` 里退役的假资产名 `legacy:<旧树>`（资产清单里一条不存在的路径）。
5. `knowledge/execution/backend_routing.json.bak_20260915_maab`：一个月前的手工备份，无引用。
6. `.pytest_tmp_r17/`（158 个被跟踪的测试临时文件，2026-10-08 的日志里记过它污染 grep）。
7. **冲突指令就地改正**（不在旧表述旁展开新说明）：
   - `config/v2.json` 里"当前本地模型是 UI-Venus-2-9B"的尾句与同文件 2026-10-08 指令（Qwen3.6-35B-A3B）冲突 → 改为"以 `llm.model` 为准"。
   - `.workbuddy-ai/rules/OPERATIONAL.md` §26.2/§26.4/§26.5：worktree 拓扑（7 个 → 1 个、`.worktrees` 已不是装入点）、
     复跑命令（`cd <worktree>\无尽冬日智能体` → `cd E:\WinterAgent\.worktrees\prod\repo`）、
     计划任务偏差（已修，不再列为遗留）。
   - `.workbuddy-ai/memory/MEMORY.md`：在 2026-10-04 的四条事实后加 2026-10-17 现况。
8. **历史测量文档不改数字**：`docs/V2_PRODUCTION_HEALTH_20260920.md`、`docs/WORKSPACE_HYGIENE_20261016.md`
   只加一行 2026-10-17 路径注记（改了就是伪造测量）；后者原本的"待授权"清单标注为**已执行**，防止被当成待办重做。
9. 清掉全部 `__pycache__` / `.pytest_cache`（1,060 个条目）：迁移保留了 mtime，字节码被判有效但
   `co_filename` 仍固化了旧绝对路径，导致每条报错都指向已退役的路径。

## 四、保留的核心文档

| 对象 | 规模 | 为什么留 |
|---|---|---|
| `START_HERE.md` | 1 | 唯一根入口说明 |
| `docs/` | 68 篇 | 设计/诊断/体检记录；两篇 dated 快照只加注记 |
| `.workbuddy-ai/rules/` | 5 篇（OPERATIONAL / FINAL_FULL / PRINCIPLES / PERSISTENT_DEVELOPMENT / README） | 现行硬规则 |
| `.workbuddy-ai/handoff/` | 96 篇 | 带日期的决策与事故记录（含 5 篇现行状态：01/03/04/09/10） |
| `knowledge/` | 197 MB | 版本化知识：事件注册表、语义字典、技能定义、模板 |
| `tests/` | 5,577 个用例 | 守卫网络本身 |
| `.workbuddy/memory/*`、`.workbuddy-ai/memory/*` | — | 历史流水与蒸馏教训（事实源 `.workbuddy-ai/memory/MEMORY.md`） |

## 五、无法安全删除的对象及原因

1. **`dataset/` 43 GB**：证据语料与训练素材，`retention.py` 有自己的引用保护（`referenced_evidence`）；
   手工删会同时破坏 109 条登记之外的证据引用，超出"整理"范围。
2. **`learning/` 605 MB**：在线运行时状态与台账（`episodes.jsonl` 10,223 行）。它是生产的记忆，
   不是缓存；删掉等于让 AUTO 失忆。
3. **`.workbuddy-ai/handoff/` 96 篇 / `.workbuddy/memory/*`**：带日期的历史记录。删了就无法回答
   "当时为什么这么改"，且与「证据不得改写」冲突。
4. **`knowledge/ui/screenshot_audit/*.jsonl`**：历史审计转储（已被 `.gitignore` 覆盖，不再进版本库），
   但仍是审计证据，留在磁盘上按需清理，不在本轮删除。
5. **`tools/` 里 24 处盘符字面量（20 个开发脚本）**：生产代码一个都不 import 它们；迁移属独立批次，
   且必须用 `MAIN_REPO`（不是 `parents[1]`）以免审计脚本改读别处。
6. **`tools/check_wiring.py` 的 navigation matrix 过期投影**（committed 153 技能 / fresh 156）：
   重跑生成器会把可调度面从 141 扩到 144，等于把 3 个未核对的技能推入可调度集合——
   与「不把未验证的技能提升为生产」冲突，留给操作者决定。
7. **两个旧名空壳目录**：`E:\无尽冬日智能体` 与 `E:\无尽冬日智能体_worktrees` 现在都含 **0 个文件、0 字节**
   （子项已逐个搬走，只剩 `winter-prod-pinned\无尽冬日智能体` 两层空壳）。删除报
   `Device or resource busy`——有 GUI 进程（编辑器/资源管理器）仍持有该路径的句柄，
   按「不杀正在运行的进程」不做强制手段。**持句柄的进程退出后**一条命令即可收尾：
   `Remove-Item -LiteralPath 'E:\无尽冬日智能体','E:\无尽冬日智能体_worktrees' -Recurse -Force`。
   它们不含任何数据，不影响"单一根目录"的可用性。

## 六、测试与运行时检查结果

| 检查 | 结果 |
|---|---|
| `pytest -q`（全量） | **5577 passed, 268 skipped, 984 subtests passed, 0 failed**（21 分 09 秒） |
| `tools/check_mainline.py` | **MAINLINE_OK**（HEAD == expected_commit；在主线；main 是主线祖先） |
| `tools/launch_pinned_production.py --check-only` | `CODE_COMMIT=... WORKTREE_CLEAN=true DATA_ROOT=E:\WinterAgent` |
| `tools/verify_handoff.py` | **ALL HANDOFF INVARIANTS PASS** |
| `tools/check_wiring.py` | 4 条 problems，全部为整理前既有（含上节第 6 项） |
| 计划任务 `WinterAgentV2Panel` | 动作已改到新路径（`Set-ScheduledTask` 落盘并回读确认） |

## 七、两个"看起来像代码回退、其实是状态缺失"的坑（已修，供以后复用）

1. `learning/timed_event_schedule.json` 是 **gitignored 运行时状态**，但 `tests/conftest.py` 的
   `_REDIRECTS` 用它**从生产现场播种**到测试沙箱。文件被删后 `calendar_scan_due()` 对空状态答 True，
   调度板以 1000 分推 `DISCOVER_EVENT_CALENDAR`（走 `OPEN_HOME`）压过 `OPEN_STAMINA_SOURCES`。
2. 同一机制还有两处：`observation_state.json` 让 `AVOID_STAMINA_WASTE` 用**上一轮的体力读数**上板
   （→ `START_RALLY`），`goal_fairness.json` 让**同轮其它测试**写进去的 `repeat-failure`/`page-residency`
   决定谁胜出。

⇒ 修法统一为"测试自己声明起点"：`tests/test_stamina_check_without_a_read.py` 用
`mock.patch.object` 把四个 store 指到本用例的临时文件（日历快照写成"今天已读过"、观察存储为空、
公平账为空、control_experience 为空），目标板于是只由当前帧与目录价决定，不再受生产状态或测试顺序影响。
