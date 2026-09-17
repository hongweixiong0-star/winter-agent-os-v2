# START HERE — Winter Agent OS V2

**你是接管这个项目的新账号。你没有前一个账号的聊天上下文，这是设计如此。**

项目目录本身就是事实源。按下面 5 步走，不要跳步。

---

## 第 0 步：认清环境（5 分钟，别跳过）

### 0a. 先读工具清单 —— `docs/AVAILABLE_TOOLING.md`

**不读这个文件就开始写代码，是本项目最贵的错误。**
MaaFramework 5.12.3 早已安装并可正常驱动 MuMu（截图 8.9 ms vs ADB 324 ms），
但开发长期用裸 adb + 自研模板重新实现它已经解决的问题，代价是一个战斗按钮
调了 2 小时。任何涉及**截图 / 按钮定位 / 页签定位 / 模板 / OCR / ROI / 点击 /
滑动 / 等待页面 / 等待按钮消失 / 重试 / UI 恢复**的任务，先看那份清单。

硬规则：如果 15–30 分钟还在手写上述某一项，停下来做 TOOL CHECK。

### 0b. 运行环境的两个坑（不知道会浪费大量时间）

1. **Bash 工具在这台机器上没有 coreutils**：`ls` / `cat` / `head` / `tail` / `sleep` /
   `wc` / `date` 全部 `command not found`，只有 shell 内建命令可用。
2. **PowerShell 工具的 stdout 不回传**（返回 exit code 0 但没有任何输出）。

所以：**所有命令都用 Python 执行**，输出重定向到文件后再用 Read 读取。

```bash
# 唯一可用的通用执行方式
cd "E:/无尽冬日智能体" && "E:/dongri-mumu-bot/.venv/Scripts/python.exe" -u tools/<script>.py > out.txt 2>&1
# 然后 Read out.txt
```

Python 环境：
- **项目 venv（含 PIL / rapidocr，跑项目脚本必须用它）**：
  `E:\dongri-mumu-bot\.venv\Scripts\python.exe`
- 托管 Python 3.13（**没有 PIL**）：`C:\Users\xhw\.workbuddy\binaries\python\versions\3.13.12\python.exe`

真机（MuMu 默认**不启动**）：
```bash
"D:/Program Files/Netease/MuMu Player 12/nx_main/MuMuManager.exe" control -v 0 launch -pkg com.gof.china
"D:/Program Files/Netease/MuMu Player 12/nx_main/adb.exe" connect 127.0.0.1:7555
```
启动后真机为 720×1280，前台包 `com.gof.china`。

---

## 第 1 步：读宪法

读 **`.workbuddy-ai/handoff/00_MASTER_RULES.md`**。
它包含 V2 架构冻结、Single Scheduler/WorldState/Registry、Goal≠Skill、Semantic First、
Verifier First、安全红线、开发方式等**长期硬规则**。改动架构前必须读过。

---

## 第 2 步：重建当前事实

```bash
"E:/dongri-mumu-bot/.venv/Scripts/python.exe" tools/update_workbuddy_handoff.py
```

这一步会读 git / registry / capability mapping / episodes.jsonl / runtime snapshot /
latest log / evidence integrity / commercial parity，并重写：

- `01_CURRENT_TRUTH.md`（完整重生成）
- `08_LIVE_METRICS.json`、`09_RUNTIME_STATE.json`（完整重生成）
- `03_NEXT_ACTION.md`、`04_OPEN_ISSUES.md`、`05_RECENT_CHANGES.md`、
  `02_CURRENT_PROGRESS.md`、`10_LAST_HANDOFF.md` 里 **`<!-- AUTO:... -->` 之间的块**

手写内容不会被覆盖。

---

## 第 3 步：读这四份

| 文件 | 回答什么问题 |
|---|---|
| `01_CURRENT_TRUTH.md` | 现在的真实数字：commit / episodes / 成功率 / 技能生命周期 / Goal 覆盖 / 证据完整性 |
| `03_NEXT_ACTION.md` | 当前最高价值任务、为什么、根因、下一个精确动作、验收标准 |
| `04_OPEN_ISSUES.md` | P0/P1 未决问题与环境坑 |
| `10_LAST_HANDOFF.md` | 上一个账号停在哪里、什么已验证、什么没有、不要重复什么 |

补充阅读（按需）：
`02_CURRENT_PROGRESS.md`（阶段判断）、`05_RECENT_CHANGES.md`（改了什么/为什么）、
`06_DECISIONS.md`（**非显然决定的理由，防止你好心改回去**）、
`07_EXTERNAL_REUSE.md`（外部项目台账）。

---

## 第 3.5 步：检查 Codex Commander Queue（**接管后必做**）

Codex 用机器可读队列给 WorkBuddy 派活，**不要手工复制指令**：

```bash
"C:/Users/xhw/.workbuddy/binaries/python/versions/3.13.12/python.exe" tools/cq.py init
"C:/Users/xhw/.workbuddy/binaries/python/versions/3.13.12/python.exe" tools/cq.py plan
```

- `WORK_QUEUE.json`（Codex 写）→ `cq.py plan` 解析出 **READY 且依赖已满足** 的可执行集，
  按 `priority` → 声明顺序排好；`QUEUED` / `WAITING_FOR_NATURAL_STATE` **不要碰**。
- 每个 Work Order 走固定十步：
  `READ EVIDENCE → TOOL CHECK → IMPLEMENT → TARGETED TEST → REPLAY → LIVE → VERIFY → BEFORE/AFTER → REPORT → NEXT`
- 结果写 `.workbuddy-ai/commander/results/<task_id>.json`，状态由 `cq.py` 统一维护：
  `cq.py start <id>` → `cq.py finish <id> --result <file> [--require-live]`。
- **timebox 内做不到就承认**：`cq.py block <id> --result <file>`（含 `root_cause_found` /
  `attempts` / `changes_made` / `evidence` / `blocker` / `recommended_codex_review`），
  **然后立刻做下一项 READY 任务**，不要死磕、不要停下来问。
- 需要高级代码分析（改冻结架构、证据与代码无法裁决、同一任务到 timebox 仍无法分类）→
  追加到 `.workbuddy-ai/commander/REVIEW_REQUESTS.md`，等 Codex 下一次可用。

**队列是任务来源，不是免死金牌**：本文件其余所有铁律（架构冻结、真机证据、付费红线、
不伪造完成）在队列任务内**同样生效**。

---

## 第 3.7 步：看一眼同步状态（仓库是 PUBLIC）

```bash
"C:/Users/xhw/.workbuddy/binaries/python/versions/3.13.12/python.exe" tools/git_sync.py status
```

`https://github.com/hongweixiong0-star/winter-agent-os-v2` 是这个项目的**公开镜像**，
"本地是否领先远端"属于当前事实的一部分：跑上面那条就知道
（`local_head` / `remote_head` / `unpushed_commits` / `git_dirty` / `last_push_at`）。
同样的字段也写进了 `01_CURRENT_TRUTH.md §A2` 与 `08_LIVE_METRICS.json.git_sync`。

- **该推的时候推**：一个可验证工作单元（Work Order 完成 / LIVE_VERIFIED / 重要修复并验证 /
  P0 根因修复 / handoff 关键状态变化 / 会话结束）⇒ `tools/git_sync.py push`。
  **不要**每改一行就推；**也不要**把明显 broken 的状态推 `main`。
- **推送前先过敏感信息闸门**（`push` 会自动跑；单独跑见 `tools/scan_public_repo.py`）。
- **绝不** `push --force` / 重写 `main` / `reset --hard`。
- 完整规则与坑：**`docs/GITHUB_SYNC_RULES.md`**（含本机 pytest 汇总丢失、repo 双写入方等）。

---

## 第 4 步：亲自核对（不要只信 Handoff）

```bash
git log --oneline -12          # 版本历史
git status --porcelain         # 脏文件
python tools/truth_audit.py    # 重算 episode / registry / 证据完整性
```

要核对的东西：

- **git**：HEAD 与 `10_LAST_HANDOFF.md` 是否一致？有没有未提交改动？
- **episodes**：`learning/episodes.jsonl` 最后几条是什么？`recorded_at` 是不是新的？
- **evidence**：被引用的截图真的在磁盘上吗？（`01_CURRENT_TRUTH.md` 的 Evidence integrity 段）
- **runtime**：`learning/runtime_snapshot.json` 的 `updated_at` 有多新？
  `unexpected_worker_exits` / `stop_reason` 是什么？
- **latest logs**：`learning/control_panel/latest.log` 的最后 `stop_reason`；
  `learning/control_panel/crashes/` 有没有新的崩溃报告？

### 运行环境预检（2026-09-17 增补，接管必做）

```bash
"E:/dongri-mumu-bot/.venv/Scripts/python.exe" tools/preflight.py
```

一条命令回答两件事：**当前解释器能不能跑生产**（`numpy` / `PIL` / `cv2` / `maa` /
`rapidocr_onnxruntime`），以及**台账里最近实际在用什么后端**
（`learning/executor_backend.jsonl` 的 `used_backend` / `capture_backend`）。
判定 FAIL ⇒ **不要相信之后任何一轮的数字**。

为什么有这一步：2026-09-17 发现桌面启动器 pin 的解释器里**没有 MAA**，而
`control_panel.py` 用 `sys.executable` 派生 worker，于是整条 AUTO 链静默退回 ADB
（取帧 324 ms，对 MAA EmulatorExtras 的 8.92 ms），唯一痕迹是 worker stdout 里一行
`MAA_IMPORT_FAILED`，而它只写进 `latest.log`。**记下来 ≠ 发现得了。**
详见 `knowledge/failure_patterns/tooling/TOOLING_INTERPRETER_DRIFT.md` 与
`01_CURRENT_TRUTH.md` **§J 后端轴**。

### 冲突裁决（不可颠倒）

1. Handoff 文档与**代码**冲突 → **代码优先**
2. 代码与 **Production Evidence** 冲突 → **Production Evidence 优先**

证据优先级总表：
```
LIVE CLIENT > PRODUCTION EVIDENCE > VERIFIER RESULT > CURRENT CODE
> REPLAY > TEST > DOCUMENT > PRIOR KNOWLEDGE
```

---

## 第 5 步：继续开发

1. 承接 `03_NEXT_ACTION.md` 里的**当前最高价值任务**。若你认为它不是最高价值，
   先用真实数据说明理由，再换。
2. **任何 Capability 开工前先跑 2 分钟 Reuse Check** —— 见 `docs/ADDING_A_LIVE_ROUTE.md` §0。
   先查本地五件事（skill / brain route / verifier / 契约 / legacy evidence）；
   **本地已有明确路径 ⇒ 用本地，不查外部**。只有命中"从未实现 / UI 或玩法未知 / 导航不知道 /
   连续失败 / 15~30 分钟仍无可靠实现"才升级到
   `knowledge/external/external_capability_map.json`，并按里面记的 `source_files` 直接读源码。
   **两条禁令：已经有成熟本地实现还跑去 GitHub 重新研究；外部已有成熟实现却自己摸 UI 两小时。**
   外部实现**只是 prior**：`External → Adapt → Current Client Probe → Live Verify`。
3. **禁止重新设计架构。** 见 `00_MASTER_RULES.md` §2。
4. **禁止重复已经 Live Verified 的工作。** 见 `02_CURRENT_PROGRESS.md` 的「已 Live 且应守住」表。
5. 进入循环：

```
RUN → FAILURE → FIX → REPLAY → LIVE → VERIFY → EVIDENCE → NEXT
```

6. 只有真实客户端 + 真实动作 + 真实状态变化 + Verifier PASS + 可追溯 Evidence
   才能把能力标为 `LIVE_VERIFIED` / `STABLE`。
7. **不要每完成一步就停下来问用户。** 自动继续下一最高价值任务
   （唯一例外：真实支付、账号安全、不可恢复破坏）。
8. 会话准备结束时（或完成一个重要节点后）：

```bash
python tools/update_workbuddy_handoff.py
```

在这几个时机刷新 handoff（不要每改一行就重写）：
新的 Live Verified / Goal Coverage 变化 / Stable·Degraded 变化 / 重大 Failure 修复 /
重大 Runtime Failure / 外部模式真正接入 / 重要 checkpoint / 会话准备结束。

9. 若本轮改动「逻辑完整 + 测试通过 + 值得保留」，建 checkpoint：

```bash
"E:/dongri-mumu-bot/.venv/Scripts/python.exe" -m pytest tests -q
python tools/update_workbuddy_handoff.py --checkpoint -m "type(scope): summary"
```

仍在实验中 → **保持 dirty tree**，并在 `10_LAST_HANDOFF.md` 手写块说明脏文件的意义。
**不许假装已完成。**

---

## 目录职责

```
.workbuddy-ai/memory/     长期项目知识、设计决定、历史经验（人写）
.workbuddy-ai/handoff/    当前开发现场、当前进度、下一操作（机器生成 + 人写补充）
```

关键路径速查：

| 用途 | 路径 |
|---|---|
| 运行态唯一真相源 | `learning/runtime_snapshot.json` |
| 生产证据流 | `learning/episodes.jsonl` |
| Worker 崩溃报告 | `learning/control_panel/crashes/` |
| 最近一次运行日志 | `learning/control_panel/latest.log` |
| 能力映射（**手写输入**） | `knowledge/goals/goal_capability_map.json` |
| 覆盖率报告（**生成输出**） | `knowledge/goals/capability_skill_map.json` |
| 商业脚本对标 | `knowledge/coverage/commercial_bot_parity.json` |
| 真机证据归档 | `evidence/`、`dataset/truth_audit/` |
| 本项目唯一入口 | `START_HERE.md`（本文件） |

---

**一句话总纲：让真实客户端更可靠、更快、覆盖更多 Goal、恢复更强、人工干预更少。
做不到，这次开发价值接近 0。**
