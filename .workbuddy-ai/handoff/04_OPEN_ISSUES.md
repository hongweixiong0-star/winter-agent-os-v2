# 04 — OPEN ISSUES

`AUTO:open_issues` 块由脚本重算（Top Failure、证据完整性、只失败过的技能、脏文件）。
下面的手写块记录**机器看不出来的**未决问题。

<!-- AUTO:open_issues -->
Machine-detected issues (recomputed every run):

- **SEMANTIC_TARGET_NOT_VERIFIED** x112 all-time; recent=45 (last 2d), last seen 2026-09-14T14:08:48.104088+00:00 — SELECT_RESOURCE(40), SEARCH_RESOURCE(32), OPEN_MAIL(13)
- **RESOURCE_NOT_FOUND** x30 all-time; recent=30 (last 2d), last seen 2026-09-14T06:42:03.928936+00:00 — SUBMIT_RESOURCE_SEARCH(30)
- **DISPATCH_NOT_PROVEN** x29 all-time; recent=28 (last 2d), last seen 2026-09-14T05:25:20.306984+00:00 — DISPATCH_MARCH(29)
- **STAMINA_SOURCES_NOT_OPEN** x8 all-time; recent=8 (last 2d), last seen 2026-09-14T23:37:22.332132+00:00 — OPEN_INTEL(8)
- **INTEL_HERO_DISPATCH_NOT_PROVEN** x8 all-time; recent=8 (last 2d), last seen 2026-09-14T12:19:55.812501+00:00 — INTEL_HERO_DISPATCH(8)
- **INTEL_RESCUE_START_NOT_PROVEN** x6 all-time; recent=6 (last 2d), last seen 2026-09-14T17:17:43.915836+00:00 — EXECUTE_INTEL_RESCUE_SURVIVORS(6)
- `ALLIANCE_HELP` never succeeded (attempts=1, failure=0)
- `CONFIRM_EXPLORATION_IDLE_CLAIM` never succeeded (attempts=2, failure=2)
- `DISMISS_MAIL_REWARD` never succeeded (attempts=1, failure=1)
- `DISPATCH_BEAST` never succeeded (attempts=1, failure=1)
- `RESEARCH` never succeeded (attempts=1, failure=0)
- `SAFE_STOP` never succeeded (attempts=4, failure=4)
- `SELECT_BEAST_TARGET` never succeeded (attempts=1, failure=1)
- `WAIT` never succeeded (attempts=1, failure=1)
- 2 uncommitted file(s): ['M .workbuddy-ai/handoff/.checkpoints.jsonl', ' M .workbuddy-ai/handoff/.last_good_commit']
<!-- /AUTO:open_issues -->

---

## 手写：未决问题

### P0（2026-09-15 08:xx GMT+8 新增）

| # | 问题 | 状态 | 备注 |
|---|---|---|---|
| 0p | **「空情报板」的负样本是错标 —— 项目至今没有一张真正的空板帧** | ✅ 已纠正前提 | `dataset/truth_audit/intel_beast_target_20260914/03_intel_page_empty_list.png` 实测是**满板 13 个 pin**（体力 305、`下次刷新:07:59:21`）。上一轮据 OCR 只有表头把它命名为 empty，并写了两个断言 `status == "NOT_AVAILABLE"` 的测试 —— **把 bug 写成了测试**。已重命名为 `03_intel_page_full_board.png`（保留不删，`evidence/INDEX.json` 自动重建），测试改写为正确行为。⇒ **`NOT_AVAILABLE` 至今未被任何真机帧证实**，只能由「pin 检测器一个都没看到」到达。**以后不要把"等负样本"当作不改判据的理由**；也不要再用这个文件当负样本。 |
| 0q | **自动化 / 外部状态记录不可信 —— 已第二次复发** | ✅ 已修 + 规则已强化 | 三份 handoff 都写「常驻自动化 id `7c1c18c1-…`（ACTIVE，每小时）」，自动化接口 `list` 返回**空数组** ⇒ 那段时间**没有任何无人值守在跑**。与第九轮 `0o` 同型。已重建 `e3485d0c-1b51-48a4-880c-c01fe0fdec19`（ACTIVE，每小时）并**用 `list` 复核存在**。**坑：`list` 为空时 `.workbuddy/memory/automations/<id>/memory.md` 仍在磁盘上，看目录会误判为"存在"。** |
| 0r | ~~`INTEL_BEAST_START_MARCH` 的 verifier 写死任务等级~~ | ❌ **假设已被证据推翻，条目作废** | 原文猜测「新上线的 `SELECT_INTEL_PIN` 点开了未复核等级 → verifier 拒绝」。实测 `state_before` 正是复核过的 `INTEL_BEAST_10 / 大角鹿 / level 22 / available`，**verifier 判据没错**。真实根因是页面分类，见 0v。**教训：verifier 失败时先核对 `state_before/after` 的原始值，不要从"新上线的东西"倒推原因。** |
| 0v | **出征（部队编成）页被分类成 `ALLIANCE/HOME`** | ✅ **已修 + 真机 A/B 证明** | 出征按钮 `BTN_BEAST_DISPATCH` 是动画控件（真机帧上还叠着 `00:00:29` 倒计时徽标），同一页面两帧实测 d=0 / **d=26**（阈值 8）。它一失手，下一条命中的就是 `PAGE_ALLIANCE` **标题条**（d=8）→ 整页报成联盟首页 → `INTEL_BEAST_MARCH_NOT_PROVEN`。而这一页复核过的两个锚点 `PAGE_BEAST_MARCH` / `STATUS_VICTORY_ASSURED`（均 d=0）**在清单里却没有任何分支引用**（孤儿模板）。已在 `BTN_BEAST_DISPATCH` 之后加「两个锚点同时命中」的分支。闸门：2716 帧里 83 帧命中锚点，**影响面恰好 5 帧**（全是同一张出征页）；89 张联盟类帧零误命中。真机 A/B：补丁前 `ALLIANCE/HOME` → 补丁后 `MARCH {victory_assured: True}`。 |
| 0w | **出征页会被赋予页面上不存在的野兽身份** | ⚠️ **新，未修** | 真机 episode 内部自相矛盾：目标卡是 `大角鹿 level 22`，出征页 after 却是 `beast={'name':'麝牛','level':9,...}` —— 来自 `BTN_BEAST_DISPATCH_MUSK_OX_9` + `STATUS_VICTORY_ASSURED_MUSK_OX_9` 在出征页上的**假命中**（两个出征按钮同形）。出征页根本不显示野兽名/等级。**修它要连带 `verify_beast_hunt` 与 `verify_stamina_beast_*`（它们依赖麝牛/9 这些字面值）**，所以先记录。新加的分支已刻意不声明这两项。 |
| 0x | **`PAGE_ALLIANCE` 是弱标题条模板，会误命中任何「出征」标题** | ⚠️ 新，记录 | 3 张 `dataset/raw/bear_live_20260909/auto_join_*` / `bear_troop_setup` 帧（真机看是**出征部队比例配置页**：士兵比例 / 全部撤回 / 平均配置 / 储存）当前被判成 `ALLIANCE`。本轮**故意不把它们改成 MARCH**：它们没有「本次出征胜券在握」，而空 `beast` 的 MARCH 会让 `brain.py:395` 对 INTEL 目标派发 `INTEL_HERO_DISPATCH`——那是危险误派。正解是给「出征族页面」一个统一的页面身份 + 各自的子类型，而不是继续靠标题条。 |
| 0y | **「最高失败」按全时段计数排序，会把人引向已经死掉的问题** | ✅ 已修（生成器 + 测试） | 本轮差点上钩：handoff 的 `CURRENT ROOT CAUSE: SEMANTIC_TARGET_NOT_VERIFIED x112`，按天拆开是 **09-12: 36 / 09-13: 37 / 09-14: 8 / 09-15: 0**（另 31 条无日期）；`MARCH_PAGE_NOT_OPEN x59` **全部集中在 09-12 一天**。也就是说 `START_GATHER` 那个「94 次尝试 / 37% 成功率、最差高频技能」的印象**完全是 09-12 的历史包袱**，09-13 之后它零失败。已改：`episode_state()` 为每个 failure_type 记录 `recent`（相对**最新 episode 时间**的 2 天窗口，按完整时间戳比较而不是按日历天）、`last_seen`、`dates`、`undated`；`top_failures` 改为**按 recent 优先**排序；`CURRENT ROOT CAUSE` 行在 recent=0 时直接标 `HISTORICAL, do not treat as the current defect`。`tests/test_handoff.py` 加 4 项护栏（含「recent=0 必须被标 HISTORICAL」）。 |
| 0s | **光晕 pin 的比例下限余量只剩 0.021** | ⚠️ 记录，稳健化解法待做 | 实测跨度 **0.521–0.644**（0.521 出现在满板帧上），闸门现在是 `0.5 <= w/h <= 1.3`。正解是**剥离光晕后量本体高度**，不是继续降阈值。语料核对：22 帧里降下限只多收那一个光晕橙 pin，其余 16 帧零新增。 |
| 0t | **`intel_pin_centers()` 在 MAP 帧上会误报** | ✅ 已按页面门控 | 世界地图右侧 HUD 圆形按钮会被当成 pin（实测 4 个 BLUE）。生产里只在 `page == INTEL` 时调用，满足约束；**任何新的调用点都必须自己加页面门控**。证据：`dataset/truth_audit/intel_pin_board_20260915/03_map_frame_detector_false_positives*.png`。 |
| 0u | **`run_intel_pins.py` 的导航周期语义与停止条件** | ⚠️ 记录 | 它的 `"navigation cycle"` 分支现在**会做真实工作**（本轮 nav_01 产出 1 次派兵 + 2 次领奖 + 1 次救援），但仍按"导航"记账；且连续 3 次导航周期后**无条件停止**，即使其中有产出。 |

### P0（第九轮，2026-09-14 22:xx）

| # | 问题 | 状态 | 备注 |
|---|---|---|---|
| 0o | **handoff 声称的「外部状态」不可信（本次踩到最大的一个）** | ✅ 已修 + 已建规则 | 三处 handoff 都写着「常驻自动化『Winter V2 情报循环（每小时）』已创建（id `1a07567f-…`）」，`list` 里没有它、按 id `view` 返回 **not found** —— **那段时间根本没有任何无人值守在跑**，今天修好的 MAA/节点/verifier/OCR 全都不会被自动执行。已重建 id `7c1c18c1-94ca-4051-a2ca-7a1614cb3979`（ACTIVE，每小时）。**规则：自动化 / 连接器 / MCP / 真机这类"外部状态"，必须用对应接口复核后才能写进 handoff；handoff 里写「已完成」不等于事实**（与宪法 §1「最高事实原则」同一逻辑：文档 < 现实）。 |
| 0m | **英雄之旅卡片的「橙皮」变体不被识别** | ⚠️ 未解，触发条件 UNKNOWN | 同一任务在真机上出现过两种皮肤：`橙皮` → 视觉读 `UNKNOWN/0.00`（大脑回 SAFE_STOP，钉子循环会卡死在该卡片上）；`蓝皮` → 正常识别 `POPUP/INTEL_HERO_JOURNEY/0.99`。两皮的**几何完全一致**（标题框都在 x237-483 / y288-323），OCR 都能读出「英雄之旅等级10」0.999，**只差横幅配色**，因此只认蓝皮的模板匹配不到橙皮。帧：`dataset/truth_audit/hero_journey_card_variants_20260914/`。**禁止猜游戏机制**——橙皮的触发条件没有任何观测支撑，先记为 UNKNOWN。 |
| 0n | **`TEMPLATE_NOT_REGISTERED` 被报成 `SEMANTIC_TARGET_NOT_VERIFIED`** | ⚠️ 可诊断性缺口 | 「模板没注册」与「屏幕上真的没有这个控件」是两个根因，却共用同一个 reason（宪法 §6 明确禁止）。本次为此多花了不少时间：真机一直说「找不到目标」，实际是路由器没把节点模板交给适配器（已修 `c03af7d`）。建议把 `last_outcome.error` 透出到 episode，让两者可区分。 |

### P0（历史遗留，仍然有效）

| # | 问题 | 状态 | 备注 |
|---|---|---|---|
| 0 | **体力不可观测 → 操作者的「体力优先」策略无法生效** | ✅ **已修（真机验证）** | `ocr.py` 的 `HUD_STAMINA_ROI` 现在从地图 HUD 读领主体力。ROI 是**测量**的（`tools/calibrate_hud_stamina.py` 打印 token box）：x 0.046–0.089、y 0.080–0.091。**关键坑**：全屏 OCR 会漏掉这个小组件（同帧全屏 token 里没有，裁成 ROI 后 0.999 读出 `350`），所以必须单独对 ROI 做 OCR。真机读数 领取前 `200` → 领取后 `350`。`AVOID_STAMINA_WASTE` 现已能在地图上被发现。 |
| 0b | **`RECALL_MARCH` 不可调度** | ✅ **已修（真机验证）** | 拆成两个技能（与 `EXPLORATION_IDLE_CLAIM`→`CONFIRM_...` 的既有约定一致）：`SELECT_MARCH_TO_RECALL`（Page.MAP，点队列第 1 行）+ `RECALL_MARCH`（Page.POPUP，点「确定」），都有 verifier 并进了 `VERIFIED_ATOMIC`。**实测纠正**：撤回**不立刻释放槽位**——确认后仍 6/6、该行变「返回中」，回城后才释放（13:53 6/6 → 14:06 5/6）。原声明的 `NORMAL_IDLE_SLOT_INCREASED` 会判掉正确撤回，已改为状态迁移判定。 |
| 0c | 采集优先级过高（已改配置，未改行为） | ✅ 配置已生效 | `march_policy.reserve_for_stamina: 0 → 2`，`resource_policy.gather_priority=LAST_RESORT`。**真机确认这条配置现在真的改变行为**：采集扫描在 idle≤2 时返回 `reserved_march_for_stamina` 并停止，不再吃满队列。⚠ 副作用见 0d。 |
| 0d | **`reserve_for_stamina=2` 使撤回触发条件几乎不出现** | ⚠️ 设计后果，待决策 | 撤回的触发是 `idle_marches == 0`，而 reserve=2 让采集在 idle≤2 就停，所以「采集把队列占满」这一状态不再自然发生；撤回目前是**安全网**（用于非采集行军占满其余槽位时），不是日常路径。若操作者更看重「没事时把 6 条都拿去采集」，可把 reserve 降到 1 或 0 —— 现在撤回真的可用了，这个取舍才成立。**这是操作者决策，不是代码缺陷。** |
| 0e | 免费体力：「下次补给」倒计时没有持久化 | ⚠️ 待优化 | 面板显示 `下次补给 04:52:52`。现在每次运行都会开一次面板确认（白花 2 个动作）。存下该倒计时即可在到期前跳过检查。 |
| 0g | **体力在 14:19→15:55 之间从 350 掉到 305（-45），无法归因** | ⚠️ 记录，未定位 | episode 流里**没有任何** `DISPATCH_*` 或体力消费记录（最近一次巨兽派兵是 05:00 的采集）。可能是客户端自身或本会话之外的操作。**不得当成我方成功消费**，也不得当成缺陷——先记录，等有新的可归因数据。 |
| 0h | ~~INTEL 巨兽链路的端到端验证被账号状态挡住~~ | ✅ **已解决** | `run6` 四步全 PASS 并真的派出了巨兽（`marches=['MARCHING']`，体力 305→295）。修复前被挡是因为列表恰好空了。 |
| 0k | ~~英雄之旅的「战斗」点击不生效~~ | ✅ **已修（真机打赢）** | **根因是我自己的测量错误**：BTN_HERO_FIGHT 模板裁在英雄头像行（y 1068-1128），真按钮在 y 1160-1242——偏了 **103px**；而「模板自匹配 d=0」是循环论证，掩盖了错误。用绿色色块分割重测 → 点 (527,1201) 一击进入战斗并**胜利**（奖励 24万×2/4.8万/1.2万/700）。教训见 03 坑列表第 12 条。 |
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
| 16 | **`SAFE_STOP` 的「正确空转」被记成 FAILURE** | ✅ **已核实为过期条目（第九轮末）** | 复核发现：`SAFE_STOP` **不在** `skills.py` 注册表里，也没有 `verify_safe_stop`；现存 4 条 SAFE_STOP/`NO_EXECUTION` **全部在 13:25Z 之前**（09:29 / 11:20×3），即 MAA 相关那几个 commit 之前的旧代码所写。**当前代码不再写这种 episode** —— 本会话的 live6 运行里第 6 步就是 SAFE_STOP，episode 流里没有对应失败行。**不要再"修"这个不存在的问题。** |
| 17 | **verifier 落后于真机页面分类（一类缺陷，非孤立）** | ⚠️ 本轮修了 3 处 | 本日三处同源：`verify_intel_rescue_started`（依赖单帧 `IN_PROGRESS` 读数）、`verify_intel_hero_target_open`、`verify_intel_hero_march_open`（都写死 `Page.BEAST`，而真机与 `brain.py` 早已按 `Page.EXPLORATION` 工作）。**建议**：把「verifier 与 brain/vision 的页面契约」做一次一致性审计，而不是等它一条条在真机上暴露。 |
| 18 | **统计口径：`RESOURCE_NOT_FOUND` 大量来自验收 harness，不是生产缺陷** | ℹ️ 澄清，勿误判 | 第九轮曾据"当日 22 条"判断采集链在浪费动作，**复核后该结论是错的**：30 条里 27 条来自 `accept_*`（`run_gather_acceptance.py` **故意**去填满队列以触发 `no_idle_march`/撤回），8 条是 09-13 无 `episode_id` 的历史行；**当日生产运行 0 条**。**教训：按 failure_type 统计时必须先按 `episode_id` 区分「生产」与「harness/实验」，否则会把测试自身的探索行为当成产品缺陷。** |
| 19 | **情报页「下次刷新」倒计时读数不可靠，不能用来排期** | ⚠️ 记录，未修 | 连续 3 次采样（间隔 45s）中 **2 次 `refresh=None`**（模板/OCR 没读到），第 3 次读到 `00:02:45`。且跨时间点的读数与真实流逝时间**不一致**：23:47 读 `00:12:41`、23:55 读 `00:11:10`（8 分钟只走了 1.5 分钟）。**结论：不要用这个倒计时推算"下批任务时间"**（handoff 曾据它写"下批 ~23:51"，实际刷新点并不吻合）。可靠的判据只有 `intel.status`（`AVAILABLE` / `NOT_AVAILABLE`）——**循环按"板子是否空了"判断即可，不要去算时间**。若要修，应先查清该读数是模板命中间歇丢失，还是客户端本身会重置倒计时。 |

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
