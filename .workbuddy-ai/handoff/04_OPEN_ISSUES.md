# 04 — OPEN ISSUES

`AUTO:open_issues` 块由脚本重算（Top Failure、证据完整性、只失败过的技能、脏文件）。
下面的手写块记录**机器看不出来的**未决问题。

<!-- AUTO:open_issues -->
Machine-detected issues (recomputed every run):

- **SEMANTIC_TARGET_NOT_VERIFIED** x104 — SELECT_RESOURCE(40), SEARCH_RESOURCE(32), OPEN_MAIL(13)
- **MARCH_PAGE_NOT_OPEN** x59 — START_GATHER(59)
- **DISPATCH_NOT_PROVEN** x28 — DISPATCH_MARCH(28)
- **RESOURCE_NOT_FOUND** x12 — SUBMIT_RESOURCE_SEARCH(12)
- **MAIL_CLAIM_FEEDBACK_NOT_PROVEN** x10 — MAIL_CLAIM_REWARDS(10)
- **POPUP_CLOSE_NOT_PROVEN** x5 — DISMISS_REAL_MONEY_OFFER(4), RECONNECT_SESSION(1)
- `ALLIANCE_HELP` never succeeded (attempts=1, failure=0)
- `CONFIRM_EXPLORATION_IDLE_CLAIM` never succeeded (attempts=2, failure=2)
- `DISMISS_MAIL_REWARD` never succeeded (attempts=1, failure=1)
- `DISPATCH_BEAST` never succeeded (attempts=1, failure=1)
- `RESEARCH` never succeeded (attempts=1, failure=0)
- `SELECT_BEAST_TARGET` never succeeded (attempts=1, failure=1)
- `WAIT` never succeeded (attempts=1, failure=1)
- 2 uncommitted file(s): ['?? tools/coldstart.txt', '?? tools/simulate_new_account.py']
<!-- /AUTO:open_issues -->

---

## 手写：未决问题

### P0

| # | 问题 | 状态 | 备注 |
|---|---|---|---|
| 1 | **AUTO 主循环此前完全无法执行语义点击** | ✅ 已修 | `LiveRuntime.resolve` 用 `self.semantic_vision.semantic.find`，而 `run_live.py` 传入的已经是 `SemanticROIVision` → 第一次点击就 `AttributeError`。已改为 `_semantic` 访问器。**这是本轮最重要发现。** |
| 2 | **`unexpected_worker_exits = 15` 无法归因** | ⚠️ 部分 | 历史值来自丢弃 traceback 的旧代码，**永久无法追溯**。现在已改为写完整崩溃报告到 `learning/control_panel/crashes/`，并把环境失败与真实崩溃分开计数。真实的 72h 结论需要新数据。 |
| 3 | **`DISPATCH_NOT_PROVEN` x28** | ❌ 未定位 | 全部来自 `DISPATCH_MARCH`。需要拿真实前后帧看 `marches` / `march_used` 的读取是否漏了某种状态。 |
| 4 | **Evidence 未进 git** | ⚠️ 设计如此 | 截图 ~1.1 GB，`.gitignore` 排除。这意味着「Live Verified」的可追溯性依赖**本机磁盘**。Retention 已保护被引用的帧，但换机器就丢。见 `06_DECISIONS.md`。 |
| 5 | **项目曾不是 git 仓库，已造成不可恢复损失** | ✅ 已修 | 2026-09-14 已 `git init` 并建立首个 checkpoint `f9ef073`。此前按 `_` 前缀批量删除，永久丢失 15 个 Codex 遗留探索脚本。 |

### P1

| # | 问题 | 状态 | 备注 |
|---|---|---|---|
| 6 | ~~等级滑条范围 1~27~~ → **实为 1..8** | ✅ 已澄清 | 真机实测：连续点「+」得到 1→4→8 并停在 8。上一轮记录的「1~27」是**误解**（27 是野兽等级上限，不是筛选器）。`resource_level_max = 8` 与线性标定**正确**，`resource_level()` 读数与真机一致。 |
| 7 | ~~`resource_level_max` 仍为 8~~ | ✅ 已澄清 | 与上条同源，无需修改。 |
| 12 | **`RESOURCE_NOT_FOUND` 是资源可用性，不是 bug** | ✅ 已修 | 真机对照实验：MEAT 在 level 7 直接搜到资源点；WOOD 在 level 1~8 **全部**搜不到。所以不是等级问题、也不是 WOOD 识别问题，而是「该资源当前在范围内没有可采节点」。原代码只在派兵成功时推进轮换 → **活锁**（永远重复搜同一个空查询）。已修：`unavailable()` 冷却 + 同一次运行内切换资源。 |
| 13 | 采集验收（四资源各 ≥3 次）**仍未达成** | ⚠️ 进行中 | 已建立可重复的验收 harness `tools/run_gather_acceptance.py`，逐次记录每步 verifier 与整车是否闭环。 |
| 8 | 「大型锯木厂」等野兽类页签未跟踪 | ⚠️ 已知 | 真机确认页签顺序为 `冰原巨兽 / 大型锯木厂 / 生肉 / 木材 / 煤矿 / 铁矿`（野兽在最左）。只识别 4 种可采集资源。 |
| 9 | 被选中页签被屏幕边缘裁切时拒绝识别 | ⚠️ 设计如此 | 安全返回 `None` 而不是猜。COAL/IRON 在默认滚动偏移下就是这种情况，应由滚动逻辑先滚进屏内。 |
| 10 | `RELAX_RESOURCE_LEVEL` 从未执行 | ⚠️ | 已注册但 episode 流里 0 次。它只在 `level > 1` 且搜索为空时触发；实测 WOOD 失败时 level 已是 1，所以正确的补救动作是**换资源**，不是降等级。 |
| 11 | `capability_skill_map.json` 与 `goal_capability_map.json` 名字容易混 | ⚠️ | 前者是**输出报告**，后者是**手写输入映射**。已在两个文件的 docstring/why 字段里写明。 |

### 环境类（会反复干扰开发，先记住）

- Bash 工具无 coreutils：`ls/cat/head/tail/sleep/wc/date` 全部 `command not found`。
- PowerShell 工具 stdout 不回传（返回 exit code 0 但无输出）。
- 托管 Python 3.13 无 `PIL`；必须用 `E:\dongri-mumu-bot\.venv\Scripts\python.exe`。
- 项目自带 `tests` 全量约 7 分钟（含 OCR 初始化），不要频繁全量跑。
