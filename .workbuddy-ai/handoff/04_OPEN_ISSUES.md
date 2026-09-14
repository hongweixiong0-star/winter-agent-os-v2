# 04 — OPEN ISSUES

`AUTO:open_issues` 块由脚本重算（Top Failure、证据完整性、只失败过的技能、脏文件）。
下面的手写块记录**机器看不出来的**未决问题。

<!-- AUTO:open_issues -->
Machine-detected issues (recomputed every run):

- **SEMANTIC_TARGET_NOT_VERIFIED** x104 — SELECT_RESOURCE(40), SEARCH_RESOURCE(32), OPEN_MAIL(13)
- **MARCH_PAGE_NOT_OPEN** x59 — START_GATHER(59)
- **RESOURCE_NOT_FOUND** x30 — SUBMIT_RESOURCE_SEARCH(30)
- **DISPATCH_NOT_PROVEN** x29 — DISPATCH_MARCH(29)
- **MAIL_CLAIM_FEEDBACK_NOT_PROVEN** x10 — MAIL_CLAIM_REWARDS(10)
- **POPUP_CLOSE_NOT_PROVEN** x5 — DISMISS_REAL_MONEY_OFFER(4), RECONNECT_SESSION(1)
- `ALLIANCE_HELP` never succeeded (attempts=1, failure=0)
- `CONFIRM_EXPLORATION_IDLE_CLAIM` never succeeded (attempts=2, failure=2)
- `DISMISS_MAIL_REWARD` never succeeded (attempts=1, failure=1)
- `DISPATCH_BEAST` never succeeded (attempts=1, failure=1)
- `RESEARCH` never succeeded (attempts=1, failure=0)
- `SELECT_BEAST_TARGET` never succeeded (attempts=1, failure=1)
- `WAIT` never succeeded (attempts=1, failure=1)
- 12 uncommitted file(s): ['M .workbuddy-ai/handoff/03_NEXT_ACTION.md', ' M .workbuddy-ai/handoff/05_RECENT_CHANGES.md', ' M .workbuddy-ai/handoff/10_LAST_HANDOFF.md', ' M learning/goal_state.json', ' M learning/runtime_snapshot.json']
<!-- /AUTO:open_issues -->

---

## 手写：未决问题

### P0

| # | 问题 | 状态 | 备注 |
|---|---|---|---|
| 0 | **体力不可观测 → 操作者的「体力优先」策略无法生效** | ✅ **已修（真机验证）** | `ocr.py` 的 `HUD_STAMINA_ROI` 现在从地图 HUD 读领主体力。ROI 是**测量**的（`tools/calibrate_hud_stamina.py` 打印 token box）：x 0.046–0.089、y 0.080–0.091。**关键坑**：全屏 OCR 会漏掉这个小组件（同帧全屏 token 里没有，裁成 ROI 后 0.999 读出 `350`），所以必须单独对 ROI 做 OCR。真机读数 领取前 `200` → 领取后 `350`。`AVOID_STAMINA_WASTE` 现已能在地图上被发现。 |
| 0b | **`RECALL_MARCH` 不可调度** | ✅ **已修（真机验证）** | 拆成两个技能（与 `EXPLORATION_IDLE_CLAIM`→`CONFIRM_...` 的既有约定一致）：`SELECT_MARCH_TO_RECALL`（Page.MAP，点队列第 1 行）+ `RECALL_MARCH`（Page.POPUP，点「确定」），都有 verifier 并进了 `VERIFIED_ATOMIC`。**实测纠正**：撤回**不立刻释放槽位**——确认后仍 6/6、该行变「返回中」，回城后才释放（13:53 6/6 → 14:06 5/6）。原声明的 `NORMAL_IDLE_SLOT_INCREASED` 会判掉正确撤回，已改为状态迁移判定。 |
| 0c | 采集优先级过高（已改配置，未改行为） | ✅ 配置已生效 | `march_policy.reserve_for_stamina: 0 → 2`，`resource_policy.gather_priority=LAST_RESORT`。**真机确认这条配置现在真的改变行为**：采集扫描在 idle≤2 时返回 `reserved_march_for_stamina` 并停止，不再吃满队列。⚠ 副作用见 0d。 |
| 0d | **`reserve_for_stamina=2` 使撤回触发条件几乎不出现** | ⚠️ 设计后果，待决策 | 撤回的触发是 `idle_marches == 0`，而 reserve=2 让采集在 idle≤2 就停，所以「采集把队列占满」这一状态不再自然发生；撤回目前是**安全网**（用于非采集行军占满其余槽位时），不是日常路径。若操作者更看重「没事时把 6 条都拿去采集」，可把 reserve 降到 1 或 0 —— 现在撤回真的可用了，这个取舍才成立。**这是操作者决策，不是代码缺陷。** |
| 0e | 免费体力：「下次补给」倒计时没有持久化 | ⚠️ 待优化 | 面板显示 `下次补给 04:52:52`。现在每次运行都会开一次面板确认（白花 2 个动作）。存下该倒计时即可在到期前跳过检查。 |
| 0g | **体力在 14:19→15:55 之间从 350 掉到 305（-45），无法归因** | ⚠️ 记录，未定位 | episode 流里**没有任何** `DISPATCH_*` 或体力消费记录（最近一次巨兽派兵是 05:00 的采集）。可能是客户端自身或本会话之外的操作。**不得当成我方成功消费**，也不得当成缺陷——先记录，等有新的可归因数据。 |
| 0h | ~~INTEL 巨兽链路的端到端验证被账号状态挡住~~ | ✅ **已解决** | `run6` 四步全 PASS 并真的派出了巨兽（`marches=['MARCHING']`，体力 305→295）。修复前被挡是因为列表恰好空了。 |
| 0i | **`OPEN_INTEL` 偶发使用错误验证器**（episode 里留下 `STAMINA_SOURCES_NOT_OPEN`） | ⚠️ 已加护栏，根因是外部编辑器 | 磁盘代码正确、运行却偶发跑错 → 编辑器回写过程中被加载。已在 `run_live.py` 启动前校验 3 个关键映射，被污染时直接 `VERIFIER_MAPPING_CORRUPT` 退出，**不再写入虚假 episode**。彻底解法是不要在外部编辑器里长期打开 `winter_agent_v2/*.py`。 |
| 0j | 情报奖励领取：`INTEL_CLAIM_REWARDS` 判 `INTEL_CLAIM_FEEDBACK_NOT_PROVEN` | ✅ 已修 | 客户端对**所有来源共用同一个「获得奖励」弹窗**，而 `POPUP_EXPLORATION_REWARD` 的分支排在 `POPUP_INTEL_REWARD` 之前 → 同一帧被判成 `EXPLORATION_REWARD`（首帧）/ `GENERIC_REWARD`（刷新帧）。改为：**来源由 before 态证明**（情报页 + claimable>0），弹窗只要属于奖励类即算反馈（与 `verify_daily_claim_feedback` 既有口径一致）。 | 2026-09-14 16:00 起情报列表为空（`下次刷新 07:59:21` 已过但未刷新出任务），所以 `OPEN_INTEL_BEAST_TARGET` 之后无法真机走完。修复本身已用真实帧验证（见 `tests/test_beast_target_card.py`），端到端待列表出现任务后重跑 `run_live.py --goal INTEL`。 |
| 0f | **行军计数会被覆盖层遮挡 → unknown** | ⚠️ **新，下一轮第一动作** | 巨兽目标面板会盖住 HUD 上的 `x/y`，此时 `march_used=None`。这是**诚实返回 unknown**（旧代码会谎报 1/6 = 5 个假空闲槽，已修）。后果：计数未知时 `idle_marches=None`，派兵与撤回都无法决策。证据帧 `dataset/raw/control_panel/probe/state_now.png`。下一步：识别该面板为地图覆盖层并优先关闭，或从行军列表行数推导计数。 |
| 1 | **AUTO 主循环此前完全无法执行语义点击** | ✅ 已修 | `LiveRuntime.resolve` 用 `self.semantic_vision.semantic.find`，而 `run_live.py` 传入的已经是 `SemanticROIVision` → 第一次点击就 `AttributeError`。已改为 `_semantic` 访问器。**这是接手时最重要的发现。** |
| 2 | **`unexpected_worker_exits = 15` 无法归因** | ⚠️ 部分 | 历史值来自丢弃 traceback 的旧代码，**永久无法追溯**。现在已改为写完整崩溃报告到 `learning/control_panel/crashes/`，并把环境失败与真实崩溃分开计数。真实的 72h 结论需要新数据。 |
| 3 | **`DISPATCH_NOT_PROVEN` x28** | ✅ 根因已定位并修复 | 根因：行军队列浮层盖住「搜索资源」按钮 → 模板层对地图返回 `UNKNOWN` → OCR 兜底读到地图活动栏按钮文字「常规活动」→ 判成 `Page.EVENT`（`marches=[]`）→ verifier 失败。已加世界地图常驻锚点（`BTN_OPEN_HOME` 且非 `PAGE_MAP`）并从 OCR 规则删除该按钮标签。**但修复后还没有新的成功闭环证据。** |
| 4 | **Evidence 未进 git** | ⚠️ 设计如此 | 截图 ~1.1 GB，`.gitignore` 排除。这意味着「Live Verified」的可追溯性依赖**本机磁盘**。Retention 已保护被引用的帧，但换机器就丢。见 `06_DECISIONS.md`。 |
| 5 | **项目曾不是 git 仓库，已造成不可恢复损失** | ✅ 已修 | 2026-09-14 已 `git init` 并建立首个 checkpoint `f9ef073`。此前按 `_` 前缀批量删除，永久丢失 15 个 Codex 遗留探索脚本。 |

### P1

| # | 问题 | 状态 | 备注 |
|---|---|---|---|
| 6 | ~~等级滑条范围 1~27~~ → **实为 1..8** | ✅ 已澄清 | 真机实测：连续点「+」得到 1→4→8 并停在 8。上一轮记录的「1~27」是**误解**（27 是野兽等级上限，不是筛选器）。`resource_level_max = 8` 与线性标定**正确**，`resource_level()` 读数与真机一致。 |
| 7 | ~~`resource_level_max` 仍为 8~~ | ✅ 已澄清 | 与上条同源，无需修改。 |
| 12 | **`RESOURCE_NOT_FOUND` 是资源可用性，不是 bug** | ✅ 已修 | 真机对照实验：MEAT 在 level 7 直接搜到资源点；WOOD 在 level 1~8 **全部**搜不到。所以不是等级问题、也不是 WOOD 识别问题，而是「该资源当前在范围内没有可采节点」。原代码只在派兵成功时推进轮换 → **活锁**（永远重复搜同一个空查询）。已修：`unavailable()` 冷却 + 同一次运行内切换资源。 |
| 13 | 采集验收（四资源各 ≥3 次）**受行军槽位硬约束** | ⚠️ 阻塞中 | 可追溯已验证闭环 **MEAT 2 / WOOD 2 / COAL 0 / IRON 1 = 5**（27 条旧记录无证据已排除）。账号只有 **6 条行军队列**，每次闭环占用一条数小时；当前 `6/6` 全忙 → `no_idle_march`。**必须跨多个行军返回周期**，harness 已加早停。 |
| 14 | 32 条 `DISPATCH_MARCH` 成功记录里 27 条无证据 | ⚠️ 历史数据 | 旧代码写下的行：无 `recorded_at` / `episode_id` / 截图，且 `resource_target` 是 vision 里硬编码的 "WOOD"。**不得**用于任何 Live Verified 声明。历史数据不可篡改（规则 44），只能在读取端加证据门槛。 |
| 15 | `Page.MARCH` 分支硬编码 `resource_target="WOOD"` | ⚠️ 待清理 | `vision.py` 的 `BTN_DISPATCH` 分支返回固定 "WOOD"。运行时会在 MAP/RESOURCE_DETAIL/MARCH 页覆盖为计划资源，所以当前不影响判定；但这是「看起来像读取的假设」，容易再次污染统计。 |
| 8 | 「大型锯木厂」等野兽类页签未跟踪 | ⚠️ 已知 | 真机确认页签顺序为 `冰原巨兽 / 大型锯木厂 / 生肉 / 木材 / 煤矿 / 铁矿`（野兽在最左）。只识别 4 种可采集资源。 |
| 9 | 被选中页签被屏幕边缘裁切时拒绝识别 | ⚠️ 设计如此 | 安全返回 `None` 而不是猜。COAL/IRON 在默认滚动偏移下就是这种情况，应由滚动逻辑先滚进屏内。 |
| 10 | `RELAX_RESOURCE_LEVEL` 从未执行 | ⚠️ | 已注册但 episode 流里 0 次。它只在 `level > 1` 且搜索为空时触发；实测 WOOD 失败时 level 已是 1，所以正确的补救动作是**换资源**，不是降等级。 |
| 11 | `capability_skill_map.json` 与 `goal_capability_map.json` 名字容易混 | ⚠️ | 前者是**输出报告**，后者是**手写输入映射**。已在两个文件的 docstring/why 字段里写明。 |

### 环境类（会反复干扰开发，先记住）

- Bash 工具无 coreutils：`ls/cat/head/tail/sleep/wc/date` 全部 `command not found`。
- PowerShell 工具 stdout 不回传（返回 exit code 0 但无输出）。
- 托管 Python 3.13 无 `PIL`；必须用 `E:\dongri-mumu-bot\.venv\Scripts\python.exe`。
- 项目自带 `tests` 全量约 7 分钟（含 OCR 初始化），不要频繁全量跑。
