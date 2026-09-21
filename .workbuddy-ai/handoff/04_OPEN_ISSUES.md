# 04 — OPEN ISSUES

`AUTO:open_issues` 块由脚本重算（Top Failure、证据完整性、只失败过的技能、脏文件）。
下面的手写块记录**机器看不出来的**未决问题。

<!-- AUTO:open_issues -->
Machine-detected issues (recomputed every run):

- **FREE_STAMINA_CLAIM_NOT_PROVEN** x236 all-time; recent=153 (last 2d), last seen 2026-09-20T10:18:03.144489+00:00 — CLAIM_FREE_STAMINA(236)
- **SEMANTIC_TARGET_NOT_VERIFIED** x224 all-time; recent=90 (last 2d), last seen 2026-09-20T13:00:04.155708+00:00 — SELECT_RESOURCE(44), DISMISS_MAIL_GENERIC_REWARD(39), DISMISS_INTEL_REWARD(35)
- **ALLIANCE_GIFTS_CLAIM_NOT_PROVEN** x11 all-time; recent=11 (last 2d), last seen 2026-09-19T09:09:43.182090+00:00 — ALLIANCE_GIFTS(11)
- **INFANTRY_CAMP_HIGHLIGHT_NOT_PROVEN** x12 all-time; recent=10 (last 2d), last seen 2026-09-19T12:31:43.758085+00:00 — NAVIGATE_INFANTRY_CAMP(12)
- **SAFE_BACK_NOT_PROVEN** x13 all-time; recent=9 (last 2d), last seen 2026-09-20T10:16:19.235731+00:00 — BACK(13)
- **EXPLORATION_IDLE_DIALOG_NOT_PROVEN** x8 all-time; recent=7 (last 2d), last seen 2026-09-19T11:24:22.269603+00:00 — EXPLORATION_IDLE_CLAIM(8)
- `ALLIANCE_HELP` never succeeded (attempts=1, failure=0)
- `CONFIRM_EXPLORATION_IDLE_CLAIM` never succeeded (attempts=2, failure=2)
- `DISMISS_EXPLORATION_REWARD` never succeeded (attempts=1, failure=1)
- `DISMISS_MAIL_REWARD` never succeeded (attempts=1, failure=1)
- `DISPATCH_BEAST` never succeeded (attempts=1, failure=1)
- `RESEARCH` never succeeded (attempts=1, failure=0)
- `SAFE_STOP` never succeeded (attempts=5, failure=5)
- `SELECT_BEAST_TARGET` never succeeded (attempts=1, failure=1)
- `SELECT_INFANTRY_CAMP` never succeeded (attempts=2, failure=2)
- `WAIT` never succeeded (attempts=1, failure=1)
- 149 uncommitted file(s): ['M .workbuddy-ai/handoff/01_CURRENT_TRUTH.md', ' M .workbuddy-ai/handoff/02_CURRENT_PROGRESS.md', ' M .workbuddy-ai/handoff/03_NEXT_ACTION.md', ' M .workbuddy-ai/handoff/04_OPEN_ISSUES.md', ' M .workbuddy-ai/handoff/05_RECENT_CHANGES.md']
<!-- /AUTO:open_issues -->

---

## 手写：未决问题

### 第 24 轮（2026-09-16 20:2x GMT+8）—— 能力总表 + MAIL 落地

| # | 问题 | 状态 | 备注 |
|---|---|---|---|
| 0at | **478 行 episode 无 `recorded_at`**（旧 schema 的自报成功，共 51 个技能） | ⚠️ **未修（结构问题，需裁决）** | 占语料 35%。`mode=PRODUCTION` 但无 `episode_id` / 截图 / `verifier_ok`。**污染所有历史指标**。总表已加 `evidence_policy` 排除它们；**不要**删历史（§18）。**待裁决**：这 478 行该标 `mode=LEGACY_SELF_REPORTED`（保留但降级），还是只在新统计里忽略？ |
| 0au | Skills 记录声称 `state=VERIFIED` 而**无任何可追溯证据** | ⚠️ **未修** | 例：`MAIL_CLAIM_REWARDS` 记录写 `VERIFIED`，但 24 行证据全是旧 schema。`SkillState` 与证据脱钩 ⇒ **不能只看 `state` 字段判断覆盖**，要跑总表 |
| 0av | `CAP-E01/E04 RESEARCH` 被角色自身状态挡住 | ✅ **非缺陷（已定性）** | 该角色已有进行中研究（6d05:20:54）+ `queue_available=false`，客户端正确拒绝。属 §7 Feature Availability，**不要再当 bug 修** |
| 0aw | MAIL 等技能的 episode **`verifier` 字段为空 `{}`** | ⚠️ **新发现，未修** | `verifier_ok=True` 有，但判定理由（如 `MAIL_BADGE_REDUCTION_PROVEN`）只出现在运行日志里，**没有落进语料** ⇒ 事后无法从语料复核"为什么算通过"。门禁要求 Verifier PASS，理由应随 episode 落盘 |
| 0ax | `CAP-AY05 FREE_ITEM` / `CAP-B09/B10 VIP` 等 T0 免费能力**完全未实现** | ⚠️ **未实现** | PHASE 1 剩余主体；VIP 需先发现入口（`OPEN_VIP` 不在 registry） |

**本轮改动**：新增 `tools/build_capability_catalog.py`（总表生成器）+ `knowledge/game/capability_catalog.json`（522 条）。
**没做**：没有为已实现的功能重建技能；没有按字母顺序推进（按操作者 §5 的价值顺序）。

### 第 23 轮（2026-09-16 19:0x GMT+8）—— CAPABILITY-FIRST 阶段启动

| # | 问题 | 状态 | 备注 |
|---|---|---|---|
| 0ak | **采集链在 R22 之后无法起步**（空闲时客户端不画计数器 ⇒ `idle_marches=None` ⇒ CHECK_MARCH 死循环） | ✅ **已修 + 已真机验证** | `has_free_march_slot`：`used==0 ⇒ 有空位`（下界，非容量猜测）；派兵后计数器出现，`max None->2`。实测 11:19:52–11:20:57 五步全 PASS |
| 0am | ~~派兵后 43 秒行军消失~~ | ✅ **已解：那是假的** | 逐步重放 11:20:47→11:21:42 五帧，**始终 `used=1 max=2 MARCHING`** —— 队伍从未消失。`used 1->0` 是**旧空闲规则**在资源弹窗遮住 HUD 时把"读不到"读成"没有"造成的。**我自己的假说也是被这条缺陷骗到的** |
| 0aq | **遮盖帧被读成空闲**（RESOURCE_DETAIL / 任何盖住 HUD 的覆层） | ✅ **已修 + 已用真机帧验证** | 空闲规则加 `primary.page is Page.MAP` 守卫；RESOURCE_DETAIL 帧现在报 `used=None`（未知），MAP 空闲帧仍报 0。证据 `dataset/truth_audit/march_counter_overlay_20260916/`，测试 `tests/test_march_count_idle.py`（8 项） |
| 0al | **`RECALL_MARCH` 可判定、从未执行** | ⛔ **BLOCKED（理由已查实，不是没做）** | 触发条件是 `idle_marches==0`，即**槽位占满**。但该角色第二次派兵被**游戏自己拒绝**：`page=POPUP`，OCR 全文 `领主大人，您的城镇中现在暂无可出征士兵，请前往训练。` + `训练士兵` 按钮。⇒ **限制这个角色的是"兵力"而不是"槽位"**（槽位读到 `1/2`，永远有空位）⇒ 靠派采集**无法**把 `idle_marches` 压到 0。派兵/召回去凑状态属于禁项 ⇒ 记为 BLOCKED 并换下一个能力 |
| 0ar | **"无兵可出征"弹窗被识别成 `INTEL_BEAST_MISSION`** | ⚠️ **新发现，未修** | 该弹窗内容是"去训练士兵"，却命中了 `popup='INTEL_BEAST_MISSION'` 模板 ⇒ 大脑随后走了 intel 分支（run2 以 `OPEN_INTEL_BEAST_TARGET` 失败收场）。**幸运的是它同时暴露了一条真实线索**：这正是操作者顺序第 3 项 **TRAIN** 的入口（`训练士兵`），可作为落地 TRAIN 的起点 |
| 0as | **召回触发条件用"槽位"表达，而实际瓶颈可能是"兵力"** | ⚠️ **设计缺口，未改** | 操作者第 9–13 节要求 Capacity / Occupancy / Reservation 分开，并允许"更高价值目标需要队列时召回"。当前实现只在**计数器满**时才召回。本角色证明：**槽位未满 ≠ 还有可用队伍**。若要真正实现"按需召回"，触发应基于"新目标还需要一支部队而拿不到" |
| 0an | 27 个技能**未实现**（按操作者顺序：CLAIM_MAIL/OPEN_VIP/TRAIN/RESEARCH/ALLIANCE 多数/ARENA/LABYRINTH/PET/RALLY/BEAR） | ⚠️ **未实现** | 用 `tools/capability_landing_queue.py` 按顺序推进；每个走最小验收四件套 |
| 0ao | 3 个技能**实现了但不可判定**（`ALLIANCE_HELP` / `JOIN_RALLY` / `START_RALLY` 不在 `VERIFIED_ATOMIC`） | ⚠️ **未修** | 运行时拒绝派发它无法评价的步骤（RR-003 同源） |
| 0ap | 覆盖率在 **Goal 层已无 NEVER_TRIED / MISSING** | ✅ 事实更正 | 所以"推 MISSING→LIVE_VERIFIED"只能在 **Skill 粒度**做，别在 Goal 层找活 |

**本轮生产代码改动两处**：① `models.WorldState.has_free_march_slot` + `brain.py` MAP 分支用它起步；
② `ocr.py` 空闲规则限定 `Page.MAP`（覆层不得制造空队列）。
**没做**：没有为让召回可触发去制造状态（禁项），也没有再引入任何容量常量。

### 第 22 轮（2026-09-16 18:4x GMT+8）—— 产品定义落地：身份来源已找到

产品定义见 `docs/PRODUCT_ONE_AGENT_MULTI_ROLE.md`（冻结级，后续会话按它执行）。

| # | 问题 | 状态 | 备注 |
|---|---|---|---|
| 0af | **身份能读了但没人用**：`read_role_identity()` 已实现并双向验证，但运行路径没有调用它 | ⚠️ **未修（下一件该做的事）** | 需要 `IDENTIFY_ROLE` Skill（Precondition/Action/Verifier）+ 运行序言。⚠ 代价：2 个动作（点头像 + Back）。⚠ 面板内有 `设置` 页签，**永不点击面板内控件**。 |
| 0ag | **语料跨两个角色**：09-14 是 70,206,322 战力 / `行军 6/6`，09-16 是 542,443 / `1/2`，同服 `#4298` | ⚠️ **未修** | 在每条 episode 带 `role_id` 之前，容量/无效率统计都只能当参考。**不要**回头改写历史（§18）。 |
| 0ah | **`领主档案` 未登记为 page 模板** | ⚠️ **刻意未做** | 今天它判 `UNKNOWN` ⇒ 会被 `unknown_page` 恢复按 BACK 并成功退出（已实测）。**登记页但不加恢复规则会卡死在面板上** —— 要登记就连 Back 一起做。 |
| 0ai | `ocr.py` 全帧回退用 `re.fullmatch(r"(\d+)\s*/\s*(\d+)")`，**无位数上限** | ⚠️ **未修（相邻，未测量）** | 与刚修的 `read_march_count` 同类；本轮只修有证据的那条。触发面窄（要求 token 在左上 `x<300,y<360`）。 |
| 0aj | `resources_policy` / 角色状态**仍无 role-scoped 落盘** | ⚠️ **未修** | 与 0af 同批做：`learning/roles/<role_id>.json`。**不要**用配置声明当身份（见产品定义 §5.2）。 |

**本轮修掉的**：`read_march_count` 把令牌拼接后再匹配，`'3/'＋'3/6'` 读成 `(3,3)`（客户端说 6）。
已收紧为整 token 优先 + 数字边界；14 例全过（含 `200/200`、`542,443` 必须为 `None`）。

### 第 21 轮（2026-09-16 13:0x GMT+8）—— 角色成长/行军容量动态建模：审计 + 两项 P0

审计全文见 `docs/ROLE_SCOPED_CAPABILITY_AUDIT.md`，方案见 `docs/ROLE_SCOPED_CAPABILITY_PLAN.md`。

| # | 问题 | 状态 | 备注 |
|---|---|---|---|
| 0bu | **页面模型在编造行军容量与占用（比"硬编码 2"更糟）** | ✅ **已修 + 测试钉住** | `vision.py` 四个 beast/hero 状态分支手写 `march_used=1/2/5/6` + 固定 `march_max=6`。**编造占用会喂 `idle_marches`**：其中 `6/6` ⇒ idle=0 ⇒ 大脑据此走向**召回采集队**，而那个数字没人测过；反向（默认 6 而真实容量更低）会凭空多出空闲位、授权派进满队列。**模板只能证明"哪一页在屏幕上、某支队伍什么状态"，不能证明"有几个队列位、用了几个"** ⇒ 未读到就是 `None`（既有的"未证实"语义）→ `CHECK_MARCH` 去读。`calibrated_march_max` 默认改 `None`；OCR 读到计数器时会覆盖真值（`ocr.py:698-706` **同时**替换 used 与 max）。 |
| 0bv | **`reserve_for_stamina=2` 被当成绝对队列位数 ⇒ 把容量 2 的角色彻底锁死** | ✅ **已修 + 真机证据 + 接线检查** | 真机 2026-09-16：该角色 **`march_max = 2`**，派出 1 支后 idle=1 ⇒ `1 <= 2` 恒真 ⇒ **每次** `GATHER_RESOURCE` 都 `SAFE_STOP reserved_march_for_stamina`，04:20–04:30 **三次运行零 episode**。同一常量对写它时的 6 队角色合理 ⇒ **它不是常量，是容量的函数**。改为 `max(0, min(reserve_marches, capacity - 2))`：容量 1→0、2→0、3→1、4→2、**6→2（原始意图完整保留）**。⚠ **正确的不变式是 `reserved_slots < capacity`**（否则 `idle <= reserved` 在任何占用量下都成立 ⇒ 目标**永久**不可达）；我第一次把不变式写错，**是我自己的两条测试互相矛盾当场抓住的**。已同时写进 `check_wiring.py`。⚠ 另删掉 `resource_policy.reserve_marches_for_stamina_spend`（同策略第二份拷贝、**零消费者**）。 |
| 0bw | **角色隔离的前提不成立：无法观测"这是哪个角色"** | ⚠️ **阻断中，故意未动手** | `role_id|role_switch|multi_role|account_id|切换角色|多角色` 全仓库**零命中**；现有标识都不是角色（`device.serial`/MAA `instance_name` = **模拟器实例**，`package_name` = 游戏包，`block_account_or_role_delete` 只是安全拦截）。`WorldState.account_stage` 字段存在但**恒为 `{}`**、零写入方。⇒ **在没有角色身份之前建"按角色隔离的状态"，只能建在一个猜出来的键上，会制造"已经隔离好了"的假象，比不做更糟。** 三条路径与建议（先做"观测到就记住"；把"从客户端读领主名"立为正式任务；**不要**先做配置声明）写在 PLAN 第二节。 |

### 第 20 轮（2026-09-16 12:1x GMT+8）—— 队列空后收掉 SELECT_RESOURCE；采集链首次跑通

| # | 问题 | 状态 | 备注 |
|---|---|---|---|
| 0br | **`SELECT_RESOURCE` 的失败不是几何，是门禁低于它自己的标定语料** | ✅ **已修 + 真机 PASS** | 我上一轮写的「pitch 157 与真机 145–150 不符」**正式撤回**：那个数字来自**缩放截图上目测**。在选中项已知的帧上实测括号推进 **157/158/157 px**、绝对位置与配置**只差 1 px** ⇒ 几何从来没错。真因是门禁 6.0 **低于自己标定语料的最大值 6.49**（正确总体 0.00–6.49 / 错误 10.65–25.09）⇒ 已在拒绝自己标定帧就能产生的读数。改 **8.0**（余量 1.51 / 2.65）。⚠ 那条让 6.0 显得宽松的旧注释（"active ≤1.2 / non-active ≥13.0"）是**从括号处裁剪**测的，不是门禁实际打分的对象 —— 已更正。⚠ 顺带把两个测试期望从 `None` 改为 `BEAST`/`GIANT_BEAST`，理由是**不含被测机制的独立证据链**（偏移扫描给出唯一 offset +399，括号反解出整数索引 0.00 / 1.00）。 |
| 0bs | **客户端在选中之前根本不画括号 ⇒ offset 卡在 None，既点不了也滚不了** | ✅ **已修（真机 PASS）** | 阈值修好后暴露的第二缺陷。真机 `04:09:31` 帧 `stroke pairs: []`（面板已开、生肉/木材/煤矿全可见、一个括号都没有）⇒ `resource_tab_offset=None` ⇒ 既不能点（目标位置未知）**也不能滚**（滚动分支要求 offset 已知）⇒ 对着**已经在屏幕上**的目标失败。修法：**offset 与 identity 是两个独立事实** —— 新增 `_offset_from_tab_contents`（用四张模板的已知相对间距反推，要求 ≥2 格一致且每格以自己模板为唯一最优；错误 offset 无法满足），只在括号失败时惰性调用（约 110 ms）。身份仍如实报 `None`。⚠ **未测**：该情形在真机上的出现频率。 |
| 0bt | **`START_GATHER` 的 37.2% 不是这个技能的属性，是整条链的阻塞被记在了它头上** | ✅ **已解释 + 真机 PASS** | `WB-R19-START-GATHER-MAA-LIVE-AB`。它的历史 94 次 35 成功，**59 次失败全是 `MARCH_PAGE_NOT_OPEN`**（链子从没走到它）。链修好后**首次可达即通过**，且 recog/act/exec **全 MAA**。**通用教训**：高频技能的失败原因高度集中在上游页面时，先查上游。⚠ **A/B 只凑到 1 个 MAA 臂、0 个 fallback 臂**：派出行军后大脑每次都答 `SAFE_STOP reserved_march_for_stamina`（`reserve_for_stamina=2`），其后 3 次运行**一条 episode 都没产生**。要凑样只能等行军回来或 Codex 改策略 —— **召回行军凑样 = 制造状态，禁止**。 |

### 第 19 轮（2026-09-16 10:1x GMT+8）—— Codex 第 2 批队列 3 单

| # | 问题 | 状态 | 备注 |
|---|---|---|---|
| 0bn | **`OPEN_INTEL` 失败 6 连的真因不是阈值，是两个独立轴：HUD 栈位置 + 昼夜主题** | ✅ **已修 + 真机 PASS** | `WB-R19-OPEN-INTEL-MAA-RECOVERY`。该语义指向的是**世界地图 HUD 上的蓝色「≡」按钮**（x_norm 0.925）。右侧按钮列**底部锚定** ⇒ 它的行随当前画了哪些按钮而变：布局 A `y=0.6727`、布局 B `y=0.7453`，**差 93 px**。6 张失败帧上固定 ROI 是**纯空天空**（phash 34–38 vs 阈值 24），控件其实在下方 93 px（phash **2**、ccoeff **0.945**）。**一个 ROI 不可能同时是「它在哪里」和「该去哪找」。** 第二轴是昼夜循环重绘 HUD：单张日间模板在夜间帧只有 0.390–0.448 ⇒ 注册了两张夜间模板。修法：`vision.py` 的 ccoeff 分支支持 per-record `search_band`，并**上报找到的位置**（executor 点 `match.center_norm`；上报注册点会把点击送到按钮上方 93 px）。**阈值 24 一字未动**。真机 `02:04:04Z` `MAP→INTEL` verifier PASS，点击 **(666, 954)** = 找到的行（注册点是 861），MAA 日志同一时刻为 `[x=666] [y=954]`。⚠ **残留**：5 个正样本（距离 26–29）仍被拒 —— **原始距离两群重叠**（正 max 29 / 负 min 28），放宽到 25–28 余量只剩 0–3 px，故按任务要求**不追**。⚠ `>=2/3 独立真机` 未达成：3 次允许运行里只有 1 次真走到 OPEN_INTEL 决策。 |
| 0bo | **账本 `capture_backend` 与 episode 同名字段描述的是两个不同事实** | ⚠️ **已报告，未动手（需 schema 裁决）** | `WB-R19-BACKEND-PROVENANCE-TRUTH`。`runtime.py:346` 写的是**观测**设备（这些帧是谁取的）；`executor_router.py:401` 写的是**执行器**设备。HYBRID 下必然不等 —— 本轮 **34 步**全是 `episode=MAA_MUMU_EXTRAS / ledger=ADB_EXEC_OUT`。**两者都不错，名字错**；单看任一侧都无法判断帧的来源。且账本该键**完全由 `used_backend` 决定**（零额外信息）⇒ **建议直接删键**。**未动手的原因**：改动已落盘 schema，且旧行会保留旧键。 |
| 0bp | **MAA/HYBRID 声明可对 `maafw.log` 追溯，但审计规则本身错过两次** | ✅ **已修 + 测试钉住** | `WB-R19-BACKEND-PROVENANCE-TRUTH`。独立产物 = `learning/maa_logs/maafw.log`（27578 行，**本地时间，需 −8h**）。两个错都是**测量抓出来的**：① 连接窗 3s 太紧 —— 实测 episode 落后动作 **2–13s（median 9.6s）**，20s 才对 ⇒ **先测偏移，别猜容差**。② **MAA 事件必须一对一归属** —— 连续步只隔 ~2.5s，±5s 窗会把**下一步自己的按键**算进上一行（实测 13:35:14.866 的 ADB 行吃掉了 13:35:17.660 的 BACK 键）⇒ 6 个**不存在的「双驱动」嫌疑**。改最近行归属后归零：68 条声明、6 条 `NO_LEDGER_ROW`。⚠ `NO_LEDGER_ROW` 真因 = 那些步**没走路由**（无 MAA adapter 时 `build_router` 原样返回 ADB executor ⇒ 无人写账本），**不是**旧数据（账本起于 09-14T13:11，零条声明早于它）。 |
| 0bq | **战斗中误按返回的风险，已用 run-scoped 上下文消除；但「战斗 vs 普通未知」在本语料中不可分** | ✅ **已修（真机未验）** | `WB-R19-BATTLE-UNKNOWN-RECOVERY`。实测那张战斗帧被判 `Page.UNKNOWN` **confidence 0.0** ⇒ 既有 `unknown_page` 恢复会**直接按 BACK 进战斗**。**先查可分性，结论是没有**：语料里战斗帧只有 1 张，hero 系列帧**全部**解析为已知页 ⇒ 用现有模板分不开（且注册模板不在本单授权范围）⇒ 走 run-scoped：`FIGHT_STARTING_VERIFIERS={"INTEL_HERO_DISPATCHED"}`（**从 registry 读 verifier，不写死技能名**），验证通过后未知帧**只等不按**（有界），仍上报原 `unknown_page`。**负向对照是验收项**：普通未知帧**仍按 BACK**、仍能恢复。⚠ **armed 分支从未在真实战斗中触发过**（任务禁止制造战斗）—— 这是诚实的剩余缺口。⚠ `DISPATCH_INTEL_BEAST`/`DISPATCH_BEAST` **没有 verifier**，所以 Beast 战斗无法武装此保护。 |

### 第 18 轮（2026-09-15 23:0x GMT+8）—— 接入 Codex Commander Queue + 执行 6 个 Work Order

**任务来源变了**：Codex 通过 `.workbuddy-ai/commander/WORK_QUEUE.json` 派活。
接管后**必做** `tools/cq.py plan`（已写进 `START_HERE.md` 第 3.5 步与 `00_MASTER_RULES.md` §23）。
判据 = `status=="READY"` **且** `dependencies` 全有终态；`QUEUED` 与
`WAITING_FOR_NATURAL_STATE` **不是可执行任务**。队列终态：**RUNNABLE 0**。

| # | 问题 | 状态 | 备注 |
|---|---|---|---|
| 0be | **`SEMANTIC_TARGET_NOT_VERIFIED` 的第 4 个子成因 = 「pin 耗尽」的**结果**已被修掉，但 target_metric 的第三款没满足** | ✅ **验收达成；残余如实记录** | `WB-0BA`。四条验收**全过**（无 TAP_SEMANTIC、无 SEMANTIC_TARGET_NOT_VERIFIED、verifier 3/3、理由可解释）。但真机跑出来是 `SELECT_INTEL_PIN`(开卡) → `BACK`(把刚开的卡关掉) → `SAFE_STOP intel_no_untried_pins` ⇒ **每轮 1 次「无效 BACK 往返」**，即 `target_metric` 明写的「0 次无效 BACK 往返」**没满足**。**这不是缺陷而是 tap-first 的固有代价**（任务卡类型只有点开才知道）。`intel_no_untried_pins` 这个理由**字面上是准确的**（该分支要求 `pins > 0`）。真机本轮实测：13:34:54Z 起 4 步、exit 0、3/3 verifier OK。⚠ **若要去掉那次往返**需要按 pin 类型分类（新视觉工作），**按操作者指令不再在 Intel 深挖**。 |
| 0bf | **免费体力路线其实早已闭环，缺的是「两个方向都验」** | ✅ **已闭环（同运行 + 反向）** | `WB-0BB`。单次运行 7 步全 verifier OK：`BACK(INTEL→MAP) → OPEN_STAMINA_SOURCES → CLAIM_FREE_STAMINA(140→290) → BACK → OPEN_INTEL(回到主任务) → SELECT_INTEL_PIN → BACK`。**反向本轮也拿到**：补给未到期（时钟在 14.4h 外）时**不绕道**。⚠ **顺带撤回一处错误推断**：`stamina_supply.py` 的 docstring 曾由两个样本推出「04:00:01 与 11:00:01 相隔 7 小时 ⇒ 一天 3-4 次」；第 4 个样本显示「领取后 **+15.5 小时**才下一次」⇒ **7 小时守恒不成立**。代码本来就只信面板倒计时，所以**行为无需改，是注释在骗人** —— 已改成明确写「机制 UNKNOWN，不要从样本推周期」。 |
| 0bg | **episode 的 backend provenance 曾有两个真缺陷；且「全空的 SAFE_STOP 行」不可能来自 runtime** | ✅ **两个缺陷已修；第三个结论已钉住** | `WB-EXECUTOR-EVIDENCE-AUDIT`。先纠正队列前提：**今日 280 条只有 7 条不完整（97%），积压是历史**（09-12 100%、09-13 100%、09-14 69%空）。今日 9 条缺口拆成**三个互不相同的成因**：① **6 条**失败 TAP_SEMANTIC 报 `capture_backend=""` 而磁盘上有真实 before 帧 —— 该字段 docstring 说是「产生本 episode 帧的通道」，却被 `if execution.executed` 门控 ⇒ **两个不同问题共用了一个空值**。修：改判据为「帧是否存在」。② **2 条**成功 `BACK` 报 `recognition_backend=""`，而同屏 MAA 步骤报 `NONE` —— router 对系统键写 `NONE`，裸 `Executor` 漏传参数 ⇒ **同一动作因走哪条路而记录不同**。修：`PRESS_BACK` 显式声明 `NONE`。③ **1 条**全空 SAFE_STOP 行：**查明它不可能来自 runtime** —— `runtime.py` 在 `_record_episode` **之前**就 `return`。⇒ **语料里存在 runtime 从不产生的行**，对任何用该流算失败率的人都很重要，已用测试钉住。⚠ **未验**：两个修复路径是单测 + REPLAY 级；15:16:47Z 那条 `executed=true`，没有真机触发 `executed=false` 路径。 |
| 0bh | **`check_wiring.py` 的 0aw 扫描**扫错了目录** | ✅ **已扩到 tools/ 与 tests/** | `WB-0AW`。原扫描只走 `winter_agent_v2/`，但**每轮新增代码都在 `tools/` 与 `tests/`**，且**无人值守入口 `run_live.py` / `run_intel_pins.py` 就在 `tools/`** ⇒ 「覆盖率 ≠ 执行」这个坑**又高了一层**。现已扫三目录（198 文件，全 0）。**先测量再动手**：扩展前 162 文件 0 命中 ⇒ 是加信号不是加噪声；并加「扫描必须真的分析传入目录」的负向对照（否则它可能永远报 clean）。 |
| 0bi | **`unexpected_worker_exits` 有两个写入方且规则不一致 —— 修复超出该 Order 的授权文件范围** | ⚠️ **已定位，未修；已上交 RR-001** | `WB-RUNTIME-EXIT-ROOTCAUSE`。`tools/control_panel.py` 里 `_handle_worker_failure`（1234/1239）**只计 `WORKER_CRASH`**（并承诺 traceback 落 `crashes/`），而兜底的 `_handle_runtime_error`（1257）**凡非 fatal 一律计数、完全不看 classification** ⇒ **环境失败在带分类的路径上被排除，在兜底路径上不被排除**。**由此可推**：代码承诺每个被计数的 WORKER_CRASH 都有 traceback，而 **`learning/control_panel/crashes/` 根本不存在、`latest.log` 是 0 字节**，全语料 1284 条**没有任何 crash/fatal 类型** ⇒ **这 15 次几乎不可能来自真实崩溃**，更可能来自那条不看分类的兜底路径。⇒ **历史 15 的正确读法是「成因不明的非致命中断累计」，不是「15 次崩溃」，更不能清零**（清零会丢掉唯一线索）。**修复位置在 `tools/control_panel.py`，不在该 Order 的 `files_allowed_to_modify` 里**（且 `do_not_touch` 明列 watchdog semantics）⇒ **未动手，写成 `REVIEW_REQUESTS.md` 的 RR-001**。已在授权范围内做的事：把结论写进 `tools/update_workbuddy_handoff.py` 的 KNOWN RISKS，**让每个后续会话都看到**。 |
| 0bj | **BLOCKED 巨兽卡恢复：集成层已证，真机状态不可安全复现** | ⛔ **BLOCKED（非「没做」，是队列自己写的 stop_condition）** | `WB-0AZ`。**新增 REPLAY 级测试**驱动**真实 `LiveRuntime`**：第 1 步真的**派发** BACK、**零 tap**、经**真 verifier** 验证；并测得反向行为 —— BACK 没挪动客户端时 `stop_reason=SAFE_BACK_NOT_PROVEN` 且**只按一次**（不乒乓）。**结构可达性也已确认**：`BACK` 在 `VERIFIED_ATOMIC` 里、决策与 goal 无关、`decide()` 中更早的出口只有 `unknown_page`。**但**从当前状态进入 `Page.BEAST + available=false` 需要按 `大师悬赏` 弹窗上的 `前往查看`，而**那是当前大脑明确拒绝的控件**、副作用未测量 ⇒ **不许手工造状态**。⇒ 建议 Codex 改为 `WAITING_FOR_NATURAL_STATE`（该状态今日已自然出现 ≥2 次）。 |
| 0bk | **`SEMANTIC_TARGET_NOT_VERIFIED` 全时 118 次，但它的总量现在被证明是不可分解的噪声源** | ⚠️ **不要再拿总量论证视觉层退化** | 已确认**至少 4 个互不相干的子成因**：`0ax` 红花费（已修）、`0ay` `小队设置` 页（已覆盖）、`0ba`/`0be` pin 耗尽（已修）、以及 `SELECT_RESOURCE`/`SEARCH_RESOURCE` 的历史簇（09-12/09-13，未查）。⚠ **在这个数字被拆干净前，用它的总量做回归判断会把四件事一起算作一件事。** |
| 0bl | **客户端可能停在「不该按任何键」的画面上 —— 而 runtime 的 unknown_page 恢复会按 BACK** | ⚠️ **已记录，未在原地发明导航** | 本轮实测：15:14:46Z 客户端停在**战斗进行中**（技能键、`x2`、暂停键），被判 `Page.UNKNOWN` / confidence 0.0。**判 UNKNOWN 是正确的**（不点任何东西），但 `runtime.py` 的 `unknown_page` 恢复**会按一次 BACK**，而**战斗里按 BACK 的后果未测量** ⇒ 本轮**选择等待**（新工具 `tools/wait_for_known_page.py`，只读、有界），战斗自行结束后才跑任何 run。⚠ 同一时段还实测到客户端停在**英雄招募**（抽卡页，按钮消耗招募券）被判 UNKNOWN —— 同样是「安全但不认识」。⚠ 还有一次 `MAP → MAIL` 在两次探针之间自行变化，时间点与一封 21:30:06 到达的邮件吻合，**归因未证实**。 |
| 0bd | **本机 `pytest tests/` 报 ~27 个「假错误」：`failures=0` 但 `errors=27`** | ✅ **已定位 + 已修（有测量）** | **决定性证据**（本轮全量 junit）：`tests=702, failures=0, errors=27, skipped=7`；stdout `595 passed, 7 skipped, 27 errors, 73 subtests in 1074.40s`；**首个错误是 `SystemExit: 1`**（`tests/test_capture_naming`），随后是 `AssertionError` 级联，**最后的 4 个错误落在我自己的 `tests/test_wiring_static_resolution.py`**。**根因：上一轮的 `pytest.ini` 自相矛盾。** 宿主沙箱在 `rmtree` 超过约 50 个文件时抛 `SystemExit`，而 pytest 有两处 rmtree：① 每个测试的 `tmp_path` 清理 ② **会话级把 `--basetemp` 指向的目录整个删掉**。上一轮同时设了 `tmp_path_retention_policy=none`（不删测试目录）**和** `addopts=--basetemp=tools/_pt_bt` ⇒ 保留策略让 basetemp 长到 **145 个文件**，于是**下一次运行开头那次整目录删除正好撞上守卫**。**修法（已验）**：`pytest.ini` 去掉 retention 覆盖与 `--basetemp`，回到默认（每个测试目录在自己还小的时候就被删掉）；`scratch_pkg` 继续只拷**源码**（去掉 `__pycache__`，36 个文件 < 阈值）。**测量**：此前报错的那 5 个文件一起跑 **31 passed / 0 errors / 0 failures / 3.78s**；**随后全量复测**：`tests=708, failures=0, errors=0, skipped=7, 73 subtests`（此前为 `failures=0, errors=27`）⇒ **27 个假错误归零**。⚠ **不要只看 `failures`** —— 27 个错误是在 `failures=0` 的情况下出现的。一步区分法：单独跑可疑文件，全过 ⇒ 是环境不是回归。⚠ **仍有一个残留的 exit=1**：全部测试跑完、junit 写完之后，pytest 的会话级 GC 去删**此前遗留**的 `garbage-*` 目录（463 个文件），宿主守卫拒绝并返回 1。**它不再污染任何测试结果**（`errors=0`、junit 完整），但会让退出码不是 0。⇒ **一次性清除 `%TEMP%\pytest-of-xhw`（15 个目录 / 1105 个文件）即可归零**；它们是 pytest 临时草稿、可安全删除，本轮未清除因为那属于宿主临时目录、超出本任务授权范围。 |

### P0（本轮新增，2026-09-15 17:5x GMT+8）

| # | 问题 | 状态 | 备注 |
|---|---|---|---|
| 0ax | **出征按钮「花费变红」被记成「视觉找不到控件」—— 同一现象被两轮误诊过** | ✅ **已修（分离度 25×0 / 4×26 + 回放 + 单测 17）** | **症状**：`SEMANTIC_TARGET_NOT_VERIFIED` 全时 116 次（项目第一大失败）。**近期**（≥09-14）只有 12 次，且集中在同一形状：`MARCH` 页上的派兵按钮 —— `BTN_BEAST_DISPATCH` ×4（09-15，全在无人值守 `intel_pins_*` 里）、`BTN_DISPATCH` ×6（09-14）。**根因（定量）**：把全部 29 条记录的 `before` 帧逐张测过 —— **25 次成功全部 pHash 距离 0、强红像素 0；4 次失败全部距离 26、强红像素 452**（阈值 8）。两组**各自内部完全一致**，所以不是动画抖动或阈值临界，是两种确定画面。看裁图：失败帧的 `10` 被画成**红色**（`dataset/probe_output/beast_dispatch_roi_20260915/`）。**这就是 `0av` 那条机制**：客户端把「你付不起」直接画成红色；红色数字叠在模板的白色数字上 ⇒ 模板不命中 ⇒ 解析器返回 `None` ⇒ 执行器记成「控件不存在」。**两次误诊**：上一轮先判「模板过期（距离 36）」，后又因一次成功判「实测它是好的」—— 两次都没解释成功/失败为何是 0 与 26 两个**离散**值。**修法（复用，不重写）**：`ocr.HybridVision.observe` 在 `Page.MARCH` 上用**已有的** `unaffordable_cost_pixels()`（`0av` 为营地面板写的）读 manifest 注册的 ROI，写 `stamina.cost_affordable` + `cost_verdict_source=DISPATCH_COST_COLOUR`；`brain.py` 在 `cost_affordable is False` 时 `SAFE_STOP` `dispatch_unaffordable_for_stamina`。**没有新增任何颜色判别代码**，该 helper 在 29 帧上零错分。证据归档 `dataset/truth_audit/beast_dispatch_cost_colour_20260915/`（4 张失败帧 + 2 张成功帧 + `live_ab_records.json` + README）。⚠ **边界**：真机只验证了**「付得起」**一侧（运行当下体力≫10 ⇒ 白花费 ⇒ 闸门不触发、出征照常，无回归）；**「红色 ⇒ 真停下」只有回放证据**（4 张真实客户端帧 + 单测），**未真机触发过**（要触发得把体力花到 <10）。⚠ 红色变体**故意不入模板**（那只会去点一个客户端已判定付不起的按钮，与 `0av` 冲突）。⚠ `小队设置` 页的绿色「战斗」按钮**不在本闸门范围内**（本 ROI 未在它上面测过），因此闸门刻意放在该分支之后。⚠ 拒绝时选 `SAFE_STOP` 而非绕路取体力：免费体力路线在地图上，从编队页按返回会去哪**未测量**，不发明未验证导航。 |
| 0ay | **那 6 条 `BTN_DISPATCH` 失败是「小队设置」页被当成 MARCH** | ✅ **已由既有分支覆盖；本轮给出解释，非新增缺陷** | 09-14 的 6 条 `BTN_DISPATCH` 失败（`goal=INTEL`）**红像素为 0**，与 `0ax` **不是同一个原因**。裁图后真相：那些帧是 **`小队设置`（英雄编队）页** —— 标题写着「小队设置」，而 ROI 位置上是一个**绿色「战斗」按钮**，所以出征模板命中不了（实测 pHash 距离 32，正常编队页是 2）。这与 `brain.py` 里 `MARCH 且 goal==INTEL 且 not world.beast ⇒ INTEL_HERO_DISPATCH` 那条分支（注释明写是为 `2026-09-14` 的 `SEMANTIC_TARGET_NOT_VERIFIED` 循环而加）**正是同一件事** ⇒ 该缺陷**已被上一轮修掉**，这 6 条是修复前的历史。**本轮价值**：把「6 次 BTN_DISPATCH 失败」这个数字**解释清楚**，避免后续会话去找一个并不存在的模板 bug。证据：`dataset/probe_output/dispatch_roi_btndispatch_20260915/`。⚠ **顺带记录一个已知缺口**：`小队设置` 页自己的战斗按钮若被画成红花费，本轮**不拦**（ROI 未标定），仍可能白点一次。 |
| 0az | **BLOCKED 的巨兽卡会把客户端留在 BEAST 页 ⇒ 之后每次运行都在第 1 步静默退出（无人值守直接停摆）** | ✅ **已修（先测量落点、再落地；单测 9 项）** | **症状**：客户端停在一张 `available=false` 的巨兽/大师悬赏卡上时，`run_live.py --goal INTEL` **在第 1 步就 `SAFE_STOP / beast_not_actionable` 退出**（`brain.py:448`），**既不按返回也不去情报页**。于是 `run_intel_pins.py` 的导航周期连续 3 次撞上限后放弃 ⇒ 该小时**零产出**。**这不是「游离模态挡路」**（那个会显式失败），它是**静默且不自愈**的。**两次独立复现**：① `evidence/intel_pins_20260915_092119.json` 那次运行末尾（memory `2026-09-15.md` 的 17:20 GMT+8 小节已记录，含终态探针 `Page.BEAST / MASTER_BOUNTY / POWER_BELOW_RECOMMENDED`）；② 本轮 `09:56:05Z`，`tools/run_intel_pins.py 3` → `STOP: 3 navigation cycles failed to reach the intel page`，三条 nav 周期**每条都是 `exit_code=2 / steps=1 / elapsed_s=5.4 / stop_reason=beast_not_actionable`**、`dispatches=0 claims=0 productive_steps=[]`（`evidence/intel_pins_20260915_095605.json`）。**修法（先测再改，未凭猜导航）**：新增 `tools/probe_back_from_beast.py`，在真机那张卡上**按一次 BACK**并观察落点 —— 实测落到 **`Page.MAP`**，HUD 恢复可读（体力 110）。据此在 `brain.py` 的 `Page.BEAST` 非可行动分支加「离开本页」：`not self.beast_card_not_actionable_left` 时返回 `BACK` / `beast_card_not_actionable_leaving_the_page`，否则维持原有 `SAFE_STOP`（**一次性守卫**，避免 BACK 没生效时在卡↔地图之间乒乓烧动作，与营地面板 `unaffordable_camp_panel_left` 同一模式）。**这一步是可验证的**：`verify_safe_back` 要求 before 不是 MAP/POPUP、after 不同且已知 —— 正好是实测的 BEAST→MAP，单测里用真 verifier 断言，并带负向对照（同页判 `SAFE_BACK_NOT_PROVEN`）。测试 `tests/test_beast_card_dead_end_recovery.py`（9 项）。⚠ **`MAX_NAV_CYCLES=3` 不要去放宽**（历史上无上限曾空转死循环），出路必须给在 brain 侧。⚠ **真机复验状态（诚实）**：修好后本轮的 pin 循环（`evidence/intel_pins_20260915_100034.json`）**没有触发这条恢复** —— 因为我的测量探针已经把客户端从卡上挪到了 MAP，nav 周期是从 MAP 起手的，所以它只是正常跑（`steps=4`，`stamina_after=110`）。**「站在 BLOCKED 卡上 → 第 1 步 BACK → MAP」这条整链尚未真机跑过**，目前是「落点已测量 + 单测覆盖」。要复验需先把客户端故意停在那种卡上。 |
| 0ba | **`SELECT_INTEL_PIN` 的「没有未试过的 pin 了」被记成视觉失败** | ✅ **已修 + 真机验证（本轮核实并提交）** | 本轮真机 pin 循环（`evidence/intel_pins_20260915_100034.json`）跑出 8 条 episode，其中 **2 条** `SELECT_INTEL_PIN` 失败、`failure_type=SEMANTIC_TARGET_NOT_VERIFIED`、`action.target=INTEL_PIN`、`page=INTEL→None`。**根因（读代码即定）**：`runtime.py` 的 `resolve()` 在 `INTEL_PIN` 分支里，遍历 `intel_pin_centers()` 并跳过本 run 内已点过的 pin；**当每个检测到的 pin 都已在 40px 内被点过时它返回 `None`** —— 代码注释明说这是**刻意拒绝**（"refuses instead of re-tapping one, so the run ends honestly rather than looping on a consumed pin"）。但 `None` 会让执行器统一记成「控件不存在」，而真相是「没有未试过的 pin」。⇒ 与 `0ax` **完全同一类错误**（刻意拒绝被记成视觉缺陷），只是发生在另一个技能上。**行为代价**：同一次运行里可见 `SELECT_INTEL_PIN → BACK → SELECT_INTEL_PIN(FAIL)` 的往返，白烧动作；而 harness 事后自己正确地判定 `no actionable pins left on the intel board`（说明「板子空了」是可知道的）。**下一步（按 `0ax` 的同一套做法）**：让大脑在情报页知道「无可行动 pin」时**不要选 `SELECT_INTEL_PIN`**，改为诚实的停止理由；而不是让解析器返回 `None`。⚠ 注意 `SEMANTIC_TARGET_NOT_VERIFIED` 现在已知**至少 3 个不同子成因**：① 红花费（`0ax`，已修）② `小队设置` 页（`0ay`，已由既有分支覆盖）③ pin 耗尽（本条）。**在这个数字被拆干净之前，不要再用它的总量去论证任何视觉层的退化。** **✅ 已修（2026-09-15 20:3x 核实并提交，commit `ae9f71b`）**：`runtime.py` 改为**每轮从同一帧算一次** `untried_intel_pins`，把 `untried_pins`/`detected_pins` 写进 `world.intel`，解析器只消费这份列表（规划与执行不可能再各算一套）；`brain.py` 在 `untried_pins == 0` 时给出诚实的 `SAFE_STOP / intel_no_untried_pins`，不再选一个解析不出目标的技能；`run_live.py` 接受该停止理由 ⇒ **情报板排空时 exit 0（诚实完成）而不是 2**。真机复核：`run_gather_acceptance` 两次都报 `stop_reason=intel_no_untried_pins`、`GATHER_EXIT=0` —— **不再伪造 `SEMANTIC_TARGET_NOT_VERIFIED`**。测试 `tests/test_intel_pin_exhaustion.py`。 |
| 0bb | **MAA 采集已进入生产路径（`capture_backend = MAA_MUMU_EXTRAS`）** | ✅ **已达成（有生产证据）** | 生产 episode 统计（全语料 1276 条）：`capture_backend=MAA_MUMU_EXTRAS` **349** 条、`recognition_backend=MAA` **31** 条、`action_backend=MAA` **128** 条、`executor_backend=MAA/HYBRID` **74/52** 条。明细：`INTEL_HERO_DISPATCH` n=11 **11/11 SUCCESS**（`recog=MAA`、`action=MAA`、lat_mean 51.3ms）、`OPEN_INTEL` n=52（50 SUCCESS/2 FAIL，`recog=V2`）。真机实测采集 **MAA 12.6–15.6ms vs ADB 404–525ms（26–42×）**。⚠ **`recognition_backend=MAA` 只出现在 `INTEL_HERO_DISPATCH`/`INTEL_HERO_START_MARCH`（战斗按钮）两个技能上**；`OPEN_INTEL`/`SELECT_RESOURCE`/`SEARCH_RESOURCE`/`CLOSE_POPUP` 仍是 LEGACY（V2 识别 + MAA 采集/点击），且 `START_GATHER`/`OPEN_HOME`/`CLOSE_POPUP` **一次都没在 MAA 上跑过**。 |
| 0bc | **采集工作流从未起步的真因：行军计数「没画出来」被当成「读不出来」** | ✅ **已修 + 真机验证（采集链能起来了）** | **先更正我自己上一轮的错误结论**：我曾写「城市视图被判成 MAP、视觉层**根本没有能力区分 HOME 与 MAP**」。**这是错的**。本轮实测：城市帧判 `HOME 0.98`、世界地图帧判 `MAP 0.99`，**分得开**；`PAGE_MAP` 模板确实命中 HOME 帧而 `BTN_OPEN_HOME` 命中 MAP 帧（即**两者命名与语义相反**，是个地雷，见下），但**页面判定本身没有因此出错**。**真因**是：在真实 MAP 帧上 `march_used=None` 而 `march_max=6` ⇒ 大脑选 `CHECK_MARCH` ⇒ 每轮第 1 步以 `MARCH_COUNT_NOT_READ` 结束（live 12:59:36Z）⇒ **`START_GATHER` 至今一次都没执行过**，这就是「MAA 步骤 4 无法测量」的原因。**证据链**：两张真机 MAP 帧对比 —— 一张计数 ROI OCR 出 `6/6`，另一张**该 ROI 一个 token 都没有**且 `marches=[]` ⇒ **没有队伍在外时客户端根本不画计数器**。**判据（由语料决定，不是猜的）**：`(used is None, 无 marches)` 出现 **98** 次；`(used is None, 有 marches)` 出现 **35** 次 ⇒ 只有前者可以读作空闲，后者是「真读不出来」，**必须保持未知**。**修法**：`ocr.py` 在 `march_used is None and not fused_marches` 时置 `0`；**用 `fused_marches`（两层证据合并）做守卫**，任一层看到行军就不猜。**代价是对称性正确的方向**：猜错 ⇒ 派兵被 verifier 拦下，浪费 1 个动作；不猜 ⇒ 整个采集 Goal 永久停摆。**真机验证（16:05Z，GATHER_RESOURCE，从 HOME 起手）**：`OPEN_MAP HOME→MAP OK` → **`SEARCH_RESOURCE MAP→MAP OK`（reason=`idle_march_available`）** → `SELECT_RESOURCE`（现止步于此）；episode 记录 `march_used None→0`、随后 `0->0 max 6`。**这是采集链有史以来走得最远的一次。** ⚠ **顺带发现（未修）**：`PAGE_MAP` 与 `BTN_OPEN_HOME` 两个模板的**命名与命中页正好相反**（前者命中 HOME，后者命中 MAP），当前没有代码因它出错，但**任何将来用 `PAGE_MAP` 做「是否在地图」判断的写法都会是反的**。 |
| 0bm | **采集链走到 `SELECT_RESOURCE` 后停在 `RESOURCE_DYNAMIC` 无法解析** | ⚠️ **新发现，未修（这正是操作者的 MAA 步骤 5）** | 真机 16:06:19Z：`SELECT_RESOURCE` / target=`RESOURCE_DYNAMIC` → `SEMANTIC_TARGET_NOT_VERIFIED`，且 `executed=False`、`latency_ms=None` ⇒ **在目标解析阶段就返回了，根本没点**。**注意这不是新缺陷**：`SELECT_RESOURCE` 历史上有 40 次 `SEMANTIC_TARGET_NOT_VERIFIED`（09-12/09-13），只是**以前根本走不到这一步**（一直被 `0bc` 挡在第 1 步）。**含义**：`0bc` 修好后，这才是采集链**当前真实的前沿**，也正是操作者列的「用 MAA 做 Page/Target Recognition + Action，V2 做 Goal/WorldState/Verifier」的落点。**下一步（未做）**：在真机搜索面板打开的状态下**测量**资源条（是否需滚动、目标 cell 是否离屏、几何是否漂移），再决定修几何还是接 MAA 识别 —— **先测再改，不要凭空给坐标**。⚠ 另注：`SEARCH_RESOURCE` 这一步历史上有 32 次 `SEMANTIC_TARGET_NOT_VERIFIED`，本次**是成功的**，说明它至少在当前布局下可用。 |
| 0bd | **本机全量测试的「假红」：宿主批量删除闸门让 26 个无关测试在 setup 阶段报错** | ⚠️ **根因确认为宿主环境；已给出修复，正在做最终验证** | 现象：`pytest tests -q` 出现 26 个 `E`（**failures = 0**），且**全部落在 setup**。**根因不在项目代码**：宿主 shim `sitecustomize.py → _check_bulk_delete_guard → raise SystemExit(1)` —— 沙箱拒绝任何对 **>50 个文件**目录的 `shutil.rmtree`，而 pytest 清理某个测试的 `tmp_path` 时正会调用它。teardown 被中断后污染 fixture 状态，于是**报错落到"接下来碰巧在跑"的那些文件上**：v3 实测分布 = `test_resource_rotation`(5+1)、`test_stamina_supply_clock`(5)、`test_intel_pin_exhaustion`(4)、`test_wiring_static_resolution`(4)、`test_capture_naming`(3)、`test_runtime_snapshot`(3)、`test_handoff`(1) —— **恰好证明是级联，而不是这些测试本身有问题**。**判定证据**：可疑文件**单独跑是 12 passed / 0 error**。⚠ **走过一次弯路，如实记录**：我先前把根因判成「pytest 清理 `%TEMP%\pytest-of-<user>` 的历史目录」，并给出 `PYTEST_DEBUG_TEMPROOT` 的跑法 —— **实测无效**（v3 设了它，仍是 26 个 E）。真正的触发是**任意单个测试的 `tmp_path` 超过 ~50 个文件**（我自己的 `test_wiring_static_resolution` 就 copytree 了 36 `.py` + 36 `.pyc` = 72 个）。**修法（两处）**：① 新增 `pytest.ini`：`tmp_path_retention_policy = none` + `count = 0` ⇒ pytest **不再删除** tmp 目录，删除动作从源头消失（目录落在已 gitignore 的 `tools/_pt_bt`）；② `test_wiring_static_resolution` 的 copytree 加 `ignore_patterns("__pycache__", "*.pyc")` ——**分析器读的是文本，从来不需要字节码**。⚠ 遇到 `E` 先看是不是这个：**failures = 0 而 errors 全在 setup**，就是它；判定方法是**把可疑文件单独跑一遍**。 |


### P0（上一轮，2026-09-15 16:2x GMT+8）

| # | 问题 | 状态 | 备注 |
|---|---|---|---|
| 0ap | **常驻自动化「在跑」是假的 —— 第 4 次复发（上一轮接管实测确认）** | ⏸️ **曾在跑（有生产证据）；2026-09-15 18:37 操作者主动暂停** | 上一轮的结论是「三处 handoff 都写 `e3485d0c-…`（ACTIVE），接口 `list` 里没有它、按 id `view` 是 not found ⇒ 那段时间没有任何无人值守在跑」。已重建 `43aef0ad-d5bc-4d79-9291-0a4da0b0dc27`（ACTIVE，每小时）。**本轮拿到了「真的跑了」的硬证据**：`evidence/intel_pins_20260915_092119.json`（mtime `09:38:19Z`，`pins_processed=3 dispatches=4 claims=10`）+ `learning/episodes.jsonl` 里 **81 条** `episode_id` 前缀为 `intel_pins_20260915_0921` 的 episode，含 `DISPATCH_INTEL_BEAST`×4、`INTEL_HERO_DISPATCH`×4、`EXECUTE_INTEL_RESCUE_SURVIVORS`×1、`INTEL_CLAIM_REWARDS`×10，**全部 verifier ok**。**这批运行不是本会话手动发起的**（本会话唯一一次 pin 循环是 `09:56:05Z`，产出的是 `intel_pins_20260915_095605.json`，且因下述卡页一条都没产出）⇒ 判据成立：**无人值守真的在执行，且上一轮修的 `0au`/`0e`/`0av` 都真的被自动走到了**（这 81 条里 `cost_affordable` 出现 12 次）。⚠ **仍需每轮重查**：id 每次重建都会变（`0o`→`7c1c18c1`、`0q`→`e3485d0c`→`43aef0ad`，**全部失效过**），**唯一可信判据是当次接口查询 + 当次是否有非手动的 episode 产出**；本文档里的 id 不是存在证明。⚠ **新发现的无人值守断点在下一条 `0az`。** ⏸️ **2026-09-15 18:37 GMT+8：操作者主动要求「取消情报定时循环」，已把该自动化置为 `PAUSED` 并用接口 `list` 复核。** ⚠ **这与 `0ap` 的历史病不是一回事**：那 4 次是「接口说在跑、实际没有任何运行」；**这次是人为主观停用**。⇒ 下一轮**不要**因为它不产出新 episode 就判定自动化故障，也**不要**当它丢失而重建；**先查状态是不是 PAUSED**。若要恢复，`update` 置回 `ACTIVE` 即可（同一个 id，配置与 prompt 都还在）。 |
| 0aw | **脏树里上一轮留下的代码会 `AttributeError` 崩在免费体力唯一的入口上** | ✅ **已修 + 真机验证** | `ocr.HybridVision.observe` 在 `GET_MORE_STAMINA` 分支调用 `self._next_supply_seconds(...)`，而**该方法在任何类上都不存在**（AST 核对：`HybridVision` 只有 `__init__ / _semantic_roi / observe`）。**它语法合法** ⇒ `check_wiring.py`（`problems: 0`）、`pytest`（542 passed）、`import` **全部通过**；只有真机走到那个面板才炸 —— 而那正是 `0au`/`0as`/`0am` 三条修复共同依赖的路径。已实现为模块级 `read_next_supply_seconds()` + 22 项单测 + 真机 A/B/C。**教训**：`check_wiring.py` 是执行级校验但**不是覆盖率校验**；接管脏树时**必须先核对上一轮未提交代码的完整性**，不能只看 `problems: 0`。**补强已完成（本轮 `0aw` hardening）**：`check_wiring.py` 新增两条 AST 检查 —— ① 每个 `self._私有名(` 调用点都能解析到本类/基类/包内定义；② 每个裸 `名(` 都能解析到模块级绑定（含 import / 类名 / 赋值 / 推导式目标 / 形参）。**并且做了负向对照**：把 `0aw` 那条调用**原样重新注入**一份临时包副本，检查器**抓到** `self-call resolves:ocr.HybridVision._next_supply_seconds`；真实树 `0`。测试 `tests/test_wiring_static_resolution.py`（7 项，含正负对照）。**范围是刻意收窄的**：`self._` 只查下划线私有名，否则会把注入式协作者（`sleeper`/`target_resolver`/`adb_resolver`）全报出来，检查器会在一周内被关掉。 |
| 0au | **免费体力检查在无人值守循环里根本不可达** | ✅ **已修 + 真机验证** | 检查住在世界地图分支，而情报 pin 循环整个 run 都在情报页（真机 `04:10:33Z`：从情报弹窗起手的 run 一次都没站到地图上）。已在情报页分支加「礼物可能到期 ⇒ 主动 `OPEN_MAP`」，由 `stamina_panel_checked` 限每 run 一趟；**刻意不标成「已检查」**（面板还没看）。真机 Run C 证明到期路径真的会开面板。⚠ Run B（情报页起手、时钟未到期）**没有**触发 `OPEN_MAP`，所以「情报页 → 地图」这条真机路径本身仍未观测过（单测覆盖决策）。 |
| 0e | **「下次补给」倒计时未持久化 ⇒ 每 cycle 白花 2 个动作** | ✅ **已修 + 真机验证** | 面板自报 `下次补给`，实测 4 个采样点全部落在 **7 小时网格**（`04:00:01Z` / `11:00:01Z`），而循环最多 8 cycle/小时 ⇒ 约 16 动作/小时换一个每天只到 3 次的礼物。已落 `learning/stamina_supply.json`（绝对时刻），`RuleBrain._supply_may_be_due()` 只在到期附近放行。**未知一律当作到期**（错判「没到期」静默丢 150 体力 vs 错判「到期」花 2 个动作，代价不对称；文件缺失/损坏/naive 时间戳一律回到「每 run 查一次」）。真机 Run A 落盘 `11:00:02.444Z`；Run C 独立复现 `11:00:01.758Z`，**到秒一致**。⚠ **仍未真机验证**：「时钟驱动的到期」与「真实 +150 领取」拼在同一次运行里（三次运行礼物都确实未到期）。 |

| # | 问题 | 状态 | 备注 |
|---|---|---|---|
| 0av | **「花费被画成红色」是客户端自己的可负担性判决 —— 这是比体力条 OCR 强得多的信号** | ✅ **已修（真机帧测定 5/5 + 单测 9/15）** | 起因：真机 `2026-09-15T04:11:16Z` `DISPATCH_INTEL_BEAST` 报 `SEMANTIC_TARGET_NOT_VERIFIED`，而出征按钮**明明在屏幕上**。定量：`BTN_BEAST_DISPATCH` 模板（`live_beast_march_selection.png` 自身 ROI 裁出，**父帧 d=0**）画的是**白色**花费 `10`；真机那帧是**红色** `10`。用 ccoeff 在 scale 1.0 上打分 **0.9152**（形状对、只是颜色不同）⇒ 是颜色，不是控件缺失。**顺带发现更大的东西**：客户端把"你付不起"直接画成红色。`tools/probe_cost_colour.py` 实测 3 种按钮 5 帧，**红色只出现在体力 < 花费的帧上，能付的帧红色像素为 0**：出征(体力0/花费10)=452、营地面板(7/10)=220、营地面板(16/10)=0、英雄出征页(10/10)=0、模板源=0。**5/5，且不是阈值判断**（能付的帧是**零**红像素）。**这比体力条 OCR 强得多**：后者营地面板 19/25，且单独的 `0` 根本读不出（见 `0as`）。已落地：`ocr.py::unaffordable_cost_pixels()` + `HybridVision` 在营地面板上写 `stamina.cost_affordable`（source=`BUTTON_COST_COLOUR`）+ `brain.py` 把它当作**最高优先级**的可负担性信号（`cost_affordable is False` ⇒ 路由去取免费体力；`None` 表示"没量到"，**不得阻止**能付的战斗）。测试 `tests/test_cost_colour_verdict.py`。**真机 A/B 已拿到（同一技能、同一按钮、只有可负担性不同）**：`04:11:16Z` 体力 **0** ⇒ 花费**红** ⇒ 模板不命中 ⇒ `DISPATCH_INTEL_BEAST` **FAILURE / SEMANTIC_TARGET_NOT_VERIFIED**；`06:14:56Z` 体力 **176** ⇒ 花费**白** ⇒ 模板命中 ⇒ 同一技能 **SUCCESS**（MARCH→MAP），整轮 10/10 SUCCESS、exit 0。**未做的部分**：红色变体**没有**加进 `BTN_BEAST_DISPATCH` 模板（那只会让我们去点一个必被拒的按钮；现在"找不到"恰好等于"不能点"）；出征页的红花费尚未在 `brain.py` 里显式成文，只体现在模板不命中上。**`cost_affordable` 字段本身没在真机运行中出现过**（两轮都没走到营地面板），只在生产单帧上验证过。 |



| # | 问题 | 状态 | 备注 |
|---|---|---|---|
| 0aq | **免费体力首次真机领取：体力 2 → 152** | ✅ **已闭环** | `tools/run_live.py --goal INTEL --max-actions 6 --stop-after CLAIM_FREE_STAMINA`，`exit 0`：第 1 步 `OPEN_STAMINA_SOURCES`（MAP→POPUP，`MAP_HUD 2` → 面板 `2/200, free_claim_available=true`），第 2 步 `CLAIM_FREE_STAMINA`（`TAP_SEMANTIC BTN_CLAIM_FREE_STAMINA`，`2/200 true` → **`152/200 false`**）。这是 `0an` 的关闭证据，也是 `verify_free_stamina_claimed` 第一次判真实领取。证据：`dataset/truth_audit/free_stamina_claim_20260915/`（4 帧 + 全部步骤记录）。 |
| 0ar | **补给周期实测是 7 小时，不是每天一次**（`0e` 的价值被大幅上调） | ⚠️ 待实现（`0e`） | 领取后 04:12:26Z 面板显示 `下次补给 06:47:35` ⇒ 下次补给 **11:00:01Z**；而 03:59:46.7Z 那张帧显示 `下次补给 00:00:15` ⇒ **04:00:01Z**。两者**正好差 7 小时**。⇒ 补给时刻是 **04:00 / 11:00 / 18:00 / 01:00 UTC**（北京 12:00 / 19:00 / 02:00 / 09:00），**一天 3–4 次**。所以「下次补给」倒计时可以直接当**绝对时间**用（两帧相隔 42 分钟、外推误差 1 秒），`0e` 从「省 2 个动作」升级为「每 7 小时一次 +150」。 |
| 0as | **体力真的为 0 时 `HUD_STAMINA_ROI` 一个 token 都读不出来 ⇒ `stamina={}` ⇒ 免费体力检查被整条跳过** | ✅ **已修（单测 + 语料闸门，未真机复现）** | 真机 `2026-09-15T04:03:02Z`：上一轮出征花光最后 10 点，地图体力条**真的是 0**，而 ROI 读返回**空**。`tools/probe_stamina_zero.py` 实测：单独一个 `0` 在任何 padding(0/2/4/6/8) × scale(1/2) 下最高置信度只有 **0.73**，且在 `0` 与 `O` 之间跳（同一字形 scale=3 读成 `'O'`）⇒ **「把阈值降下来」不是答案**。后果有两条：`RuleBrain` 的 MAP 分支要求 `stamina.current is not None` 才去开面板 ⇒ **恰好在免费礼物最值钱的一帧跳过了检查**（该轮转去开了情报 pin）；`LiveRuntime` 也拒绝解析 `HUD_STAMINA_GAUGE` 点击目标 ⇒ 即使大脑做了决定也执行不了。**修法：把「要不要去看」和「能不能点」都从「数字读没读到」解绑。** 依据：`tools/probe_map_gauge_unreadable.py` 实测 6 张 MAP 帧中 2 张读不出，**2/2 都是干净 HUD、体力条画着并显示 0**（`dataset/probe_output/map_gauge_unreadable/`）；而且 `probe_stamina_zero.py` 的 35 帧闸门显示加 padding **一个值都没变**（11→11 可读，0 处不一致）⇒ 加 padding 不是修法。礼物是否可领由**面板自己的模板**判定，不由体力条判定。测试：`tests/test_stamina_check_without_a_read.py`（10 项）。**未真机复现**（要复现得让体力回到 0）。 |
| 0at | **营地战斗被客户端拒绝会终止整轮** | ✅ **已修（单测，未真机复现）** | `runtime.py` 在**第一次验证失败就 return**（`:676`），于是 `INTEL_HERO_MARCH_REFUSED_FOR_STAMINA`（`0ak` 的诚实拒绝）会**把整轮掐死** —— 而它离免费体力检查只差一步。**反事实**：没有这条路时，`03:51:37Z` 那轮死在第 3 步。**修法**：把「被拒」当成可恢复的路由信号（`runtime.py` 对 `RESOURCE_NOT_FOUND` 早有同样先例），记录客户端自己的判决到 `brain.camp_panel_refused`（**客户端的拒绝是 ground truth，优先于任何 OCR 读数**）后 `continue`，每轮限 1 次；运行时**自己不按任何键**，`POPUP/GET_MORE_STAMINA` 仍由 `RuleBrain` 决定（有免费礼物就领，否则回地图）。测试：`tests/test_camp_fight_refusal_recovery.py`（11 项，含端到端「拒绝之后真的走到免费体力检查」）。**未真机复现**（要同时造出「闸门读不到体力 + 客户端拒绝」，本轮没造出来）。 |
| 0au | **`run_live.py` 从情报页出发时**整轮不会回到地图**，免费体力检查因此根本不跑** | ⚠️ **新发现，未修** | 真机 `2026-09-15T04:10:33Z`：起手是情报 pin 的弹窗 ⇒ `BACK` 回到 **INTEL**（不是 MAP）⇒ 之后全程 `SELECT_INTEL_PIN → OPEN_INTEL_BEAST_TARGET → INTEL_BEAST_START_MARCH → DISPATCH_INTEL_BEAST(FAILURE)`，**一次都没站到地图上**，所以 `0am`/`0as` 修好的免费体力检查**没有被执行**。而 pin 循环（`run_intel_pins.py`）的常态就是停在情报页 ⇒ **免费体力检查在无人值守循环里可能几乎不跑**。⇒ 需要让大脑在「本轮还没检查过免费体力」时**主动去一次地图**（`INTEL → OPEN_MAP`），或按 `0ar` 的补给时刻只在窗口附近去。**这是 `0am`/`0as` 能否真正生效的关键一环。** |


| # | 问题 | 状态 | 备注 |
|---|---|---|---|
| 0am | **`--no-stamina-check` 把「唯一无人值守进程」的免费体力检查永久关掉，而它是为已修的 bug 打的补丁** | ✅ **已移除 + 真机验证** | `tools/run_intel_pins.py:83` 一直在给 `run_live.py` 传 `--no-stamina-check`（`59e94ed`，2026-09-14 19:23 加入），而 `config/v2.json` 的 `stamina_policy` 写着 `claim_free_stamina: true` 且 note 明说「the free 丰盛的招待 gift (+150) **must be claimed**」。**两端直接矛盾，且该旗子的存在理由已经被修掉了**：它的 help 文本说要抑制"repeated failed claim attempts"，而语料里那类失败长这样 —— `failure_type=STAMINA_SOURCES_NOT_OPEN`、`skill=OPEN_INTEL`、`action.target=BTN_OPEN_INTEL_WILD_HUD`、`state_after.page=INTEL`（**动作成功了**），共 9 条。那就是 `0i` 一步一决策 bug 的签名，已修。**而且这旗子连"降噪"都没做到**：09-14T23:37 与 09-15T02:31 仍有同类失败，都在旗子落地之后（那两次调用方没传旗子）。**已删掉该传参**（`run_live.py` 保留旗子作诊断逃生口，help 文本改为如实说明）。真机验证：`run_live.py --goal INTEL --max-actions 3`（不带旗子）第 1 步即 `OPEN_STAMINA_SOURCES / free_stamina_gift_not_yet_checked_this_run`，MAP→`GET_MORE_STAMINA`，verifier OK，3/3 OK，exit 0。**代价已量化**：pin 循环每个 cycle 会多花 ≤2 个动作（该循环最多 8 个 cycle/小时）⇒ 约 16 动作/小时，换到 +150 体力 ≈ 45–60 动作的产出，净正。**真正的优化是 `0e`**。 |
| 0an | **`CLAIM_FREE_STAMINA` 至今从未真机执行过（全语料 0 次）** | ✅ **已闭环 + 真机验证（首次领取）** | 见顶部本轮小节 `0aq`：真机 `2026-09-15T04:12:26Z` 体力 **2 → 152（+150）**，真实 `TAP_SEMANTIC BTN_CLAIM_FREE_STAMINA`，verifier 从面板自身读数判定（`2/200, free_claim_available=true` → `152/200, false`），`exit 0`。模板 `btn_claim_free_stamina__live_stamina_panel.png` **首次在真正可领取的面板上命中**。证据：`dataset/truth_audit/free_stamina_claim_20260915/`。 |
| 0ao | **视觉层会抛异常而不是返回 UNKNOWN（`min() iterable argument is empty`），且根因是我自己往语料目录写裁剪图** | ✅ 已修 | 全语料扫描在 `match("POPUP_HERO_BATTLE_VICTORY")` 处崩掉：`SemanticROIVision.find` 的 `matches` 列表在 `ccoeff` 分支下**可能为空**（`match_ccoeff` 返回 None 时不追加），而 `min([])` 抛 `ValueError`。**有 4 个语义是全 ccoeff 单记录**：`BTN_HERO_CAMP_FIGHT`、`BTN_HERO_FIGHT`、`BTN_INTEL_VIEW_TARGET`、`POPUP_HERO_BATTLE_VICTORY`，都被普通页面分支调用。触发条件：帧分辨率与 ROI 注册分辨率不同（`match_ccoeff` 每个 scale 都被 `th >= window.shape[0]` 跳过）⇒ 任何**部分写入的截图**或**分辨率变化的设备**都可能让整次 observe 崩掉。**暴露它的原因是我把 104 张 302×79 标题裁剪图写进了 `dataset/raw`**（`dataset/raw` 是帧语料，语料闸门假设里面每张 PNG 都是完整真机帧）。已修三处：① `find` 加空列表守卫（"无法评估的模板不是匹配"）；② 裁剪图移到 `dataset/probe_output/`（**移动不是删除**，104/104 保留）并更新 `probe_formation_title.py` 输出目录；③ `.gitignore` 加 `dataset/probe_output/` 并写明原因。测试：`tests/test_vision_never_raises.py`。**教训：语料目录只放完整真机帧；派生素材另开目录。** |
| 0ap | **常驻自动化接口报 ACTIVE，但恢复后约 1 小时无任何运行痕迹** | ⚠️ 已如实记录，未解决 | `automation list` 返回 `e3485d0c-1b51-48a4-880c-c01fe0fdec19`（`FREQ=HOURLY`，ACTIVE），但：最新 episode 是 `2026-09-15T03:04:43`（**我自己**的手动运行），最新 `evidence/intel_pins_*.json` 是 10:27（同样是我的手动运行），且该自动化自己的 `.workbuddy/memory/automations/<id>/memory.md` **不存在**。**这是记忆里已记过两次的同一个坑（接口说在跑、磁盘目录也在、实际没有任何运行）**，现为第 3 次。恢复 ACTIVE 后接口才给出 `nextRunAt`。**结论：在拿到一次真实的自动化运行产物之前，不得声称"有无人值守在跑"。** |

| # | 问题 | 状态 | 备注 |
|---|---|---|---|
| 0aj | **`tests/test_beast_formation_page.py` 把「编造身份」写成了断言（`0p` 同类，第 4 次）** | ✅ 已改写 | 原 `test_the_reviewed_formation_frame_keeps_its_original_identity` 断言 `live_beast_march_selection.png` 的 `beast.level == 9`，注释还写着"the reviewed 麝牛 level-9 branch must keep winning"。**而那张帧是情报出征页**（标题栏 `出征`，其自身模板族是 `BTN_BEAST_DISPATCH`/`PAGE_BEAST_MARCH`）—— level 9 来自另一张野生帧的同形按钮裁图。**同一个测试文件里的另一条**（`test_the_formation_page_asserts_only_the_safety_fact_it_shows`）却要求同页 `"name" not in beast and "level" not in beast` —— 两条在同一页面上互相矛盾，这就是暴露它的方式。**教训（第 4 次重申）**：`0p` / `0ae` 已各记一次；**改判据前先问"这条断言写的是它自称的东西吗"，以及"同一页面/同一契约的其他测试是否与它冲突"。** |
| 0ak | **体力不足时游戏拒绝出征，却被 verifier 记成「战斗已开始」** | ✅ **已修 + 真机验证** | 真机 `2026-09-15T03:03:57Z`：客户端停在英雄之旅营地面板（`探险 💧10`），体力 **9** ⇒ 游戏**拒绝**并弹 `获取更多`。而 `verify_intel_hero_march_open` 的判据是 `before_ok and (after.page is not before.page)`，`GET_MORE_STAMINA` 同样替换了营地面板 ⇒ **必然通过**，`INTEL_HERO_START_MARCH` 被记为成功。**这正是项目最不能接受的一类（把拒绝记成成功）。** 已修：`GET_MORE_STAMINA` 单独判拒绝，并用**不同的 reason** `INTEL_HERO_MARCH_REFUSED_FOR_STAMINA`（与 `INTEL_HERO_MARCH_NOT_OPEN` 区分，按 `0n` 的原则），证据字段加 `refused_for_stamina`。**根因级修法已于同日落地并真机验证**：营地面板现在能读到体力（见 `0ao`），大脑在动手前比较两者，不足就走 `BACK` 去取免费体力 —— 见 `0am`。 |
| 0al | **获取更多面板里有一行「使用自有体力道具」，属操作者策略决策** | ℹ️ 需操作者决策，**未动代码** | 真机帧 `dataset/truth_audit/stamina_check_live_20260915/02_...png` 显示：`领主体力 / 使用后恢复10点领主体力 / [使用] / 库存 1,007` ⇒ 账上持有约 **1,007 × 10 ≈ 10,070** 体力道具，而当时体力只有 **9**。该行**不是付费行**（付费行是 `购买并使用 💎300` / `超值月卡` / `礼包购买` / `英雄集结`），但 `config/v2.json` 的 `stamina_policy.note` 明确写「only `BTN_CLAIM_FREE_STAMINA` is a target」。**在操作者明确表态之前，代码不得去点它** —— 但这条信息本身很重要：一个"体力长期为个位数"的账号，账上却躺着上万的体力道具。 |

### P0（2026-09-15 10:xx GMT+8 新增）

| # | 问题 | 状态 | 备注 |
|---|---|---|---|
| 0z | **联盟首页被读成宝箱页 —— 一个误分类打断了两件事** | ✅ **已修 + 真机 12/12 闭环** | 详情见 `03_NEXT_ACTION.md` 顶部本轮小节。要点：模板层（`PAGE_ALLIANCE_GIFTS` 在首页 d=6 且排在 `PAGE_ALLIANCE` 之前）+ OCR 层（`ocr.py:258` 见 `联盟宝箱` 即写 `section="GIFTS"`，而该文本在首页/宝箱页**都**是精确 token）两层独立成因；`HybridVision` 又把 OCR 盖在模板之上。互锁：`brain.py:206` 要 `section=="HOME"` 才派发，`verify_open_alliance_gifts` 也要 `before.section=="HOME"` ⇒ 看起来像"技能没实现"。闸门 2757 帧：页面身份改变 **0** 帧。 |
| 0aa | **情报巨兽目标被路由到 `BEAST_HUNT`，被 verifier 判成 FAILURE** | ✅ **已修（证据等级：生产 episode 回放 + 单测，非真机运行）** | `brain.py` 原来用 `current_goal == "INTEL"` 判定「这是情报目标」。但页面身份由 `mission_id` 决定，与 goal 无关 ⇒ **任何非 INTEL goal 下**，`Page.BEAST` 上的情报目标都会落到 `BEAST_HUNT`（文档写的是"击败野外普通巨兽"），而它注册的 verifier `verify_beast_march_open` 要求 before 是**地图野怪 `麝牛`/9**。**两次点击完全相同**（都是 `BTN_BEAST_START_MARCH`），所以动作成功、却被记成失败。真机记录：episode `ally_prep_20260915` step 3 / `2026-09-15T02:10:52Z` / `goal_id=HOME` / `BEAST_HUNT` / `BEAST_MARCH_NOT_PROVEN`。**修法**：删掉 goal 闸门，只按 `mission_id ∈ {INTEL_BEAST_10, INTEL_FIREBEAST_10}` 路由到 `INTEL_BEAST_START_MARCH`（其 verifier `verify_intel_beast_march_open` 用 mission→level 表绑定身份）。**未做真机运行确认**：`run_intel_pins.py` 内部固定 `--goal INTEL`，在 INTEL 下旧代码本来就路由正确，所以它无法验证本次改动；要真机确认需先把客户端停在情报巨兽目标页、再用非 INTEL goal 跑。回放证据：`dataset/truth_audit/beast_intel_target_routing_20260915/recorded_episode_20260915T021052Z.json`（同一条真机 before/after 现在通过正确 verifier）。 |
| 0ae | **`tests/test_beast_verifier.py` 曾把本 bug 写死成测试（`0p` 同类，第三次）** | ✅ 已改写 | 原断言 `RuleBrain().decide(live_beast_intel_world_target.png) == "BEAST_HUNT"` —— 而该帧标签明确是 `mission_id=INTEL_BEAST_10 / 大角鹿 / 22`，即**情报**目标。它能通过只是因为 `RuleBrain()` 的 `current_goal=None` 让 goal 闸门恰好为假。已改写为 `INTEL_BEAST_START_MARCH`，并补 5 项真机 episode 回放 + 1 项"地图野怪仍走 `BEAST_HUNT`"的护栏。**教训重申**：`0p` 已记过一次，这是第三次遇到"测试断言的是错行为"；改判据前先看断言写的是不是它自称的东西。 |
| 0af | **`brain.py` 的 `world.beast.get("level") == 22` 是死分支** | ✅ **已修（与 `0w` 同根因，一起修的）** | 原判据 `self.current_goal == "INTEL" or world.beast.get("level") == 22` 读的是 vision **编造**的字段 ⇒ 野怪/情报的选择由像素噪声决定。现改为读 `world.beast.get("target_kind")`（`HybridVision` 从标题栏量测）。**并且修了一个安全性方向**：野生路由要求**正向证据**（标题读出 `目标：`），其余（情报标题 / 读不出 / goal=INTEL）一律走情报路由 —— 因为两个出征按钮是同一个控件（点哪个都落），但 `verify_beast_dispatch` 要求量测到的 `麝牛`，把身份未量测的编队送过去会把**正确动作记成 FAILURE**。 |
| 0ab | **测试依赖的真机留档被 gitignore 静默吞掉（复现性缺口）** | ✅ 已修 | `.gitignore` 用的是**文件模式** `dataset/truth_audit/**/*.png`，于是 4 个**被测试读取**的归档目录一直没进 git：`intel_pin_board_20260915`（`tests/test_intel_pin_board.py`）、`beast_formation_page_20260915`、`alliance_gifts_chain_20260915`、`panel_redesign`。**新克隆跑不了这 4 个测试文件**。已按目录逐条 `!` 放行；`panel_redesign` 有 69 帧 / 34 MB，只放行测试真正读的 4 张（清单需与 `tests/test_panel_redesign.py` 同步）。**教训：新增真机留档目录后，必须用 `git check-ignore` 验一次，别以为"在磁盘上"就等于"在版本库里"。** |
| 0ac | **`run_live.py` 的 body 检测重试会在仓库根目录堆垃圾 PNG** | ℹ️ 已加 ignore，未清 | 根目录出现 `out_now*.png` / `out_after_back*.png` / `out_back3.png` / `out_final_state.png` / `out_intel_open1.png` / `out_intel_dbg/`，来自不稳定点击目标的 body 探测重试。已加 `out_*.png` / `out_intel_dbg/` 到 `.gitignore`。**没有删除**（它们是不稳定点击目标唯一的现场记录，且项目规则要求清理先列清单逐项确认）。根因见下条。 |
| 0ad | **`BTN_OPEN_ALLIANCE_GIFTS` 是不稳定点击目标** | ⚠️ 记录 | 同一首页在不同帧上实测 d=**2 / 4 / 0**（阈值 8）；`PAGE_ALLIANCE_GIFTS` 在宝箱页上 d=0/2/6；`BTN_ALLIANCE_HELP` d=2/4。真机 12/12 之所以全绿，是因为 `run_live.py` 有 body 检测重试兜住了它。**这是 0ac 的根因，也是 0v（出征按钮 d=0→26）的同类**：联盟族/出征族的按钮都是动画控件。**不要因为本轮成功就以为它稳。** |

### P0（2026-09-15 08:xx GMT+8 新增）

| # | 问题 | 状态 | 备注 |
|---|---|---|---|
| 0p | **「空情报板」的负样本是错标 —— 项目至今没有一张真正的空板帧** | ✅ 已纠正前提 | `dataset/truth_audit/intel_beast_target_20260914/03_intel_page_empty_list.png` 实测是**满板 13 个 pin**（体力 305、`下次刷新:07:59:21`）。上一轮据 OCR 只有表头把它命名为 empty，并写了两个断言 `status == "NOT_AVAILABLE"` 的测试 —— **把 bug 写成了测试**。已重命名为 `03_intel_page_full_board.png`（保留不删，`evidence/INDEX.json` 自动重建），测试改写为正确行为。⇒ **`NOT_AVAILABLE` 至今未被任何真机帧证实**，只能由「pin 检测器一个都没看到」到达。**以后不要把"等负样本"当作不改判据的理由**；也不要再用这个文件当负样本。 |
| 0q | **自动化 / 外部状态记录不可信 —— 已第二次复发** | ✅ 已修 + 规则已强化 | 三份 handoff 都写「常驻自动化 id `7c1c18c1-…`（ACTIVE，每小时）」，自动化接口 `list` 返回**空数组** ⇒ 那段时间**没有任何无人值守在跑**。与第九轮 `0o` 同型。已重建 `e3485d0c-1b51-48a4-880c-c01fe0fdec19`（ACTIVE，每小时）并**用 `list` 复核存在**。**坑：`list` 为空时 `.workbuddy/memory/automations/<id>/memory.md` 仍在磁盘上，看目录会误判为"存在"。** |
| 0r | ~~`INTEL_BEAST_START_MARCH` 的 verifier 写死任务等级~~ | ❌ **假设已被证据推翻，条目作废** | 原文猜测「新上线的 `SELECT_INTEL_PIN` 点开了未复核等级 → verifier 拒绝」。实测 `state_before` 正是复核过的 `INTEL_BEAST_10 / 大角鹿 / level 22 / available`，**verifier 判据没错**。真实根因是页面分类，见 0v。**教训：verifier 失败时先核对 `state_before/after` 的原始值，不要从"新上线的东西"倒推原因。** |
| 0v | **出征（部队编成）页被分类成 `ALLIANCE/HOME`** | ✅ **已修 + 真机 A/B 证明** | 出征按钮 `BTN_BEAST_DISPATCH` 是动画控件（真机帧上还叠着 `00:00:29` 倒计时徽标），同一页面两帧实测 d=0 / **d=26**（阈值 8）。它一失手，下一条命中的就是 `PAGE_ALLIANCE` **标题条**（d=8）→ 整页报成联盟首页 → `INTEL_BEAST_MARCH_NOT_PROVEN`。而这一页复核过的两个锚点 `PAGE_BEAST_MARCH` / `STATUS_VICTORY_ASSURED`（均 d=0）**在清单里却没有任何分支引用**（孤儿模板）。已在 `BTN_BEAST_DISPATCH` 之后加「两个锚点同时命中」的分支。闸门：2716 帧里 83 帧命中锚点，**影响面恰好 5 帧**（全是同一张出征页）；89 张联盟类帧零误命中。真机 A/B：补丁前 `ALLIANCE/HOME` → 补丁后 `MARCH {victory_assured: True}`。 |
| 0w | **出征页会被赋予页面上不存在的野兽身份** | ✅ **已修 + 全语料闸门（104/104）** | 见下方「2026-09-15 11:xx 新增」的 `0aj`–`0al` 与本轮小结。要点：`BTN_BEAST_DISPATCH_MUSK_OX_9` / `BTN_BEAST_DISPATCH` / `STATUS_VICTORY_ASSURED_MUSK_OX_9` / `STATUS_VICTORY_ASSURED` 是**同一个控件的两份裁图**（ROI 差 0.002，实测在两张父帧上距离 0/0/4/0），分支顺序决定了身份 ⇒ `beast6_march.png`（北极狼）被报成 `麝牛/9`。**该页其实显示目标**：标题栏 `目标：<名>`（野生）/ 裸 `出征`（情报）。已改为 vision 不编造、`HybridVision` 读标题栏、verifier 绑量测到的名字、brain 按 `target_kind` 路由。 |
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
| 0e | 免费体力：「下次补给」倒计时没有持久化 | ⚠️ **优先级已升高** | 面板显示 `下次补给 04:52:52`。现在 `0am` 已把检查还给无人值守循环，代价被量化：pin 循环每个 cycle 检查一次（`RuleBrain.stamina_panel_checked` 是**运行期**的），最多 8 cycle/小时 ⇒ 约 16 动作/小时，而三次真机运行里礼物**一次都没到期**（`free_claim_available` 全为 False）。**存下该倒计时即可在到期前跳过检查**，把 16 动作/小时降到接近 0。注意安全方向：倒计时读错或存储过期会**跳过**礼物（回到现状），不会误点付费行 —— 但仍应把"存储缺失/过期"当作"必须检查"。 |
| 0g | **体力在 14:19→15:55 之间从 350 掉到 305（-45），无法归因** | ⚠️ 记录，未定位 | episode 流里**没有任何** `DISPATCH_*` 或体力消费记录（最近一次巨兽派兵是 05:00 的采集）。可能是客户端自身或本会话之外的操作。**不得当成我方成功消费**，也不得当成缺陷——先记录，等有新的可归因数据。 |
| 0h | ~~INTEL 巨兽链路的端到端验证被账号状态挡住~~ | ✅ **已解决** | `run6` 四步全 PASS 并真的派出了巨兽（`marches=['MARCHING']`，体力 305→295）。修复前被挡是因为列表恰好空了。 |
| 0k | ~~英雄之旅的「战斗」点击不生效~~ | ✅ **已修（真机打赢）** | **根因是我自己的测量错误**：BTN_HERO_FIGHT 模板裁在英雄头像行（y 1068-1128），真按钮在 y 1160-1242——偏了 **103px**；而「模板自匹配 d=0」是循环论证，掩盖了错误。用绿色色块分割重测 → 点 (527,1201) 一击进入战斗并**胜利**（奖励 24万×2/4.8万/1.2万/700）。教训见 03 坑列表第 12 条。 |
| 0i | **`OPEN_INTEL` 使用错误验证器（episode 里留下 `STAMINA_SOURCES_NOT_OPEN`）** | ✅ **已修，根因与旧记录完全不同** | **旧记录把根因写成"外部编辑器回写过程中被加载"，并加了一个静态映射护栏 —— 那是错的**：`VERIFIED_ATOMIC["OPEN_INTEL"]` 一直是 `verify_open_intel`（`runtime.py:92`），护栏查的正是这张静态表，所以它**永远不可能**发现这个问题。真根因是**运行时对同一帧算了两次决策**：`runtime.py:387` 先算一次（并用它构建后端路由），`Scheduler.tick`（`scheduler.py:40`）又算一次并执行后者。而 `RuleBrain.decide` **不是纯函数** —— `brain.py:362` 会置 `stamina_panel_checked=True` 并返回 `OPEN_STAMINA_SOURCES`，于是第二次调用返回 `OPEN_INTEL`。结果：执行的是 `OPEN_INTEL` 的动作，**验证器却用了第一次决策的** `verify_stamina_sources_open` ⇒ 动作成功（客户端确实到了情报页）却被判 FAILURE，运行以 `stop_reason=STAMINA_SOURCES_NOT_OPEN`（exit 2）中止。**第二重后果**：免费体力面板**从未被打开**，而大脑已经把"本轮已检查"标成 True —— 一个功能"报告完成却从未执行"，与情报 `NOT_AVAILABLE` 静默终止同族。**第三重**：`STAMINA_SOURCES_NOT_OPEN` 被记在 `OPEN_INTEL` 名下（AUTO 表里 `OPEN_INTEL(8)`），污染统计。**修法**：`Scheduler.tick(world, decision=None)` 改为执行传入的决策；`runtime.py` 把自己的决策交给它 ⇒ **一步一决策**。真机 A/B 见下条。 |
| 0ag | **`runtime.py` 违反了自己写下的不变量「one router decision per step」** | ✅ 已修 + 真机 A/B | `runtime.py:545` 的注释原文就是 "One executor boundary, one router decision per step"，但代码在 `Scheduler.tick` 里又算了一次。**真机 A/B（同一 goal、同一动作、同一 `MAP→INTEL` 迁移、体力 0 消耗）**：<br>修复前 `2026-09-15T02:31:11Z`：`1 OPEN_INTEL / BTN_OPEN_INTEL_WILD_HUD / MAP→INTEL / verify False STAMINA_SOURCES_NOT_OPEN / stop=STAMINA_SOURCES_NOT_OPEN (exit 2)`<br>修复后 `2026-09-15T02:34:45Z`：`1 OPEN_INTEL / BTN_OPEN_INTEL_WILD_HUD / MAP→INTEL / verify True OK {"before_map":true,"after_intel":true,"stamina":3} / stop=MAX_ACTIONS_REACHED (exit 0)`，其后 2 步也全 OK。<br>留档 `dataset/truth_audit/one_decision_per_step_20260915/`（4 帧 + `live_ab_records.json`）；`tests/test_one_decision_per_step.py` 用记录里的原始状态**重新调用两个 verifier**，证明"记录下来的 reason/evidence 正是另一个 verifier 的输出"。 |
| 0ah | **后端路由也用第一次（过期的）决策选择** | ⚠️ 记录，未单独验证 | `runtime.py:551` 用 `skill_id=decision.skill` 构建 `build_router`。在旧代码里，如果 `Scheduler.tick` 改判成别的技能，**路由也会按过期技能选后端**。本轮修复把决策统一后这个隐患随之消失，但**没有独立证据**证明它曾经真的选错过后端（`backend_ledger` 里可查）。 |
| 0ai | **免费体力检查是否真的恢复执行** | ✅ **已真机确认（`OPEN_STAMINA_SOURCES` 项目史上首次执行）** | 本轮真机 `--goal INTEL --max-actions 4`（`2026-09-15T03:03:57Z`，4/4 verifier OK，exit 0）step 3：`OPEN_STAMINA_SOURCES / reason free_stamina_gift_not_yet_checked_this_run / TAP_SEMANTIC HUD_STAMINA_GAUGE / MAP → POPUP/GET_MORE_STAMINA / verify OK`。语料佐证：1105 条 episode 里该技能出现 **0** 次。**诚实边界**：只证明了「面板会被打开」；当时 `free_claim_available=false`（`丰盛的招待` 的下次补给还有 56 分钟），所以大脑正确地 `BACK`，**真正的领取动作仍未真机验证过**。留档 `dataset/truth_audit/stamina_check_live_20260915/`。 |
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

### 2026-09-16 新增（本轮）

| # | 问题 | 状态 | 说明 |
|---|---|---|---|
| 16 | `daily.activity` 读数自相矛盾 | ⚠️ 待查（当前不影响决策） | 同一天三次读到 **285 / 80 / 10**（领取前后），而 `ocr.py` 的写法是：先找字面串 `"325"`，取其后的第一个 1–3 位数字当 activity。⇒ **它读到的很可能不是活动点数**。目前大脑不用它做任何决策（决策看 `tab` / `status` / `claimable_count`），所以不是阻塞项；但**不要基于它做判定或写进证据结论**。要修得先测出真正的活动点数 ROI。 |
| 17 | `activity` 阈值被写死为 `"325"` | ⚠️ 设计债 | 见上：里程碑上限随版本/进度变化，写死一个字面串意味着**换账号或改版后 activity 会静默消失**（读到 `None` 而不是报错）。若将来要用 activity 判定，必须改成"读里程碑行的最后一个数字"这类不依赖具体数值的规则。 |
| 18 | 面板"记住上次页签"的规则未知 | ⚠️ 观察中 | 13:46 手工切到 每日任务后，16:33 那次运行面板**开在每日任务**；16:5x 再次打开时**又回到 章节任务**。两种都观测到了，规则未定（可能与内容是否变化/间隔有关）。当前实现不依赖它：`SELECT_DAILY_TAB` 只在读到 `tab=NOT_TASKS` 时才点，读到 `tab=TASKS` 就继续。 |

### 2026-09-17 新增

| # | 问题 | 状态 | 说明 |
|---|---|---|---|
| 19 | **没有"第三方许可"闸门** | ⚠️ 已知缺口 | `scan_public_repo.py` 只查凭据（token/cookie/手机号/邮箱），**不查第三方代码与许可证**。2026-09-17 一次 `git add -A` 把 4 个 AGPL-3.0 Java 源文件扫进公开仓库（已在下个提交移除，历史未重写）。缺口在于：`out_*` 的忽略规则只覆盖 txt/md/xml/json/png，**不覆盖 .toml，也不覆盖整个抓取目录** —— 已补 `out_*.toml` / `out_ext_*/` / `out_ext_java/` / `dataset/external/`，但**这只是补漏，不是闸门**。真要防，需要在 `scan_public_repo.py` 里加一条"外部源码目录/许可头"检查。 |
| 20 | **VIP 入口仍未找到** | ⚠️ 待发现 | 外部假设（Frostguard `(430,48)-(530,85)`）在 V2 客户端**被证伪**：那一点打开的是 `REAL_MONEY_OFFER`（硬阻断正确挡下）。HOME 全屏 OCR（28 个高置信 token）**没有 VIP/特权/贵族/会员 文本**，右缘只有 `常规活动`(634–700,176–203) 与 `超值活动`(623–700,275–297)。下一步：用同一有界探针逐个探这两个面板，或探领主档案面板的页签 —— 找到显示 VIP 等级/到期时间的那个。证据：`dataset/truth_audit/vip_entry_20260917/`。 |

### 2026-09-17 第二轮（训练/建筑）新增

| # | 问题 | 状态 | 说明 |
|---|---|---|---|
| 21 | **建筑身份是被写死的** | 🔴 阻塞 BUILD 落地 | `vision.py` 的 `BTN_BUILD_UPGRADE` 分支返回 `building={"id":"STOREHOUSE","level":26,"target_level":27}` —— 这是 2026-09-08 某个具体建筑的字面值。今天实测 `建筑实力 提升`(605,550) 聚焦的是 **民居1 3级**，开出的是家具面板与 `升级`（费用 157.7万肉 / 当时只有 16.6万 ⇒ 禁用）。一旦把该按钮注册进生产，视觉就会为**任何**被聚焦的建筑编造 STOREHOUSE 那套值，而 `verify_building_upgrade` 正是按 `before.building` 的 id/level 判定的 ⇒ **会验证通过一个根本没发生的事实**。落地 BUILD 前必须先让 id/level/target_level **从画面读**（面板标题 `民居1 3级` + `升级` 上的费用行）。证据：`dataset/truth_audit/power_route_20260917/key/04_building_focused.png`，测试 `TheBuildingPanelIsStillUnrecognisedTests` 把缺口钉住。 |
| 22 | **情报奖励弹窗被误读成每日奖励** | ✅ **已修（2026-09-17）** | 修法已验证：视觉层改为**先**判"这是客户端共用的「获得奖励」弹窗"（横幅或页脚，页脚在 103 帧上命中 102 帧、距离 ≤2）并报**目标中立**的 `GENERIC_REWARD`，由 goal 上下文选解除技能。改动**不碰任何 verifier** —— 五个 `*_reward_dismissed` 早已接受 `GENERIC_REWARD`。真机：`DAILY_CLAIM_REWARDS`（真领到）→ after `popup=GENERIC_REWARD` → `DISMISS_DAILY_GENERIC_REWARD` verifier OK；`MAIL_CLAIM_REWARDS`（真领到）→ after `popup=GENERIC_REWARD`。全语料 3007 帧闸门 **0 假阳性**（`tools/probe_reward_popup_gate.py`）。证据：`dataset/truth_audit/reward_popup_source_20260917/`，测试 `tests/test_reward_popup_source.py`。 | 两次 `--goal INTEL` 都**真拿到价值**（各领到一份奖励；第二次还 `DISPATCH_INTEL_BEAST` 真派出一队、体力 237→227），却都停在同一处：`DISMISS_DAILY_REWARD` verifier `DAILY_REWARD_ADVANCE_NOT_PROVEN`（exit 2）。**根因已量清（不是阈值问题）**：`POPUP_DAILY_REWARD_CURRENT` 的 ROI 是 `x 0.08 y 0.2 w 0.84 h 0.4` = **整个奖励格区域** ⇒ 对**任何来源**的奖励弹窗都命中（两次情报弹窗实测 **d=6 / d=2**），而带来源信息的 `POPUP_GENERIC_REWARD_HEADER` 是 12 / 16；`vision.py` 第 1046 行又把它排在通用表头**之前**且距离更小 ⇒ 报成 `DAILY_REWARD` ⇒ 跑每日的解除技能。⇒ **该裁剪在结构上无法区分来源**。修法方向：来源只能由**目标上下文**决定（大脑已有 brain.py 221–232 的分支），但**改前必须先量"真每日奖励弹窗"**：若它也走通用路径，`goal=None` 时会不会落到 `SAFE_STOP generic_reward_without_goal_context` 把奖励晾着 —— 本轮手边没有一张真每日奖励帧，**答不了**。**禁止靠调阈值修。** 证据：`key/11_intel_reward_popup.png`、`key/13_intel_reward_popup_run2.png`，测试 `TheIntelRewardPopupIsMisreadTests`。 |
| 23 | **TRAIN/RESEARCH 运行结束后客户端停在叶子页** | 🟡 **已实现，真机 episode 待取** | 镜像 `_leave_daily_panel_once` 的做法已落地：命名 goal 站在自己没有用的叶页上 → 一次 BACK（`verify_safe_back` 接受 `TRAINING/RESEARCH → HOME`，两方向都用 `tools/probe_power_route.py --leave` 量过）；"自己的叶页上无事可做" → 先 BACK 再具名停止；**同一轮不再重走路线**；拥有该页的 goal 与无 goal 的扫掠行为不变。单测 12 项 + `check_wiring` 4 条。**真机 episode 尚未取得**：叶页存活时间很短（探针刚放上去，几十秒后运行起跑已读回 HOME）⇒ 见下面 #27。 |
| 24 | `PAGE_TRAINING_*` 分不出兵营种类 | ⚠️ 设计债 | 三个兵营页签（盾兵营/矛兵营/射手营）上 `PAGE_TRAINING_INFANTRY` **都命中**（标题文字的 phash 相似），所以 `world.training.troop_type` 恒为 `INFANTRY`；而 OCR 标题读得很干净（`百战盾兵`/`刚毅矛兵`/`刚毅射手`）。`verify_training_started` 用 troop_type 判定，所以"在矛兵营开始训练"可能被记成"在盾兵营"。修法：troop_type 从 OCR 标题读，别靠模板。 |
| 25 | **点情报「前往查看」打开的是「英雄之旅」而不是巨兽任务** | ✅ **已修（帧级验证完成，真机复跑待设备空闲）** | 根因**不是**工单里列的两个候选，而是视觉层的判别器本身。实测：① `BTN_INTEL_VIEW_TARGET` 在父帧上 **d=0**，OCR 的「前往查看」中心 **(360,934) 与 ROI 中心逐像素重合** ⇒ 落点没偏；② 失败步的 before 帧其实是**「英雄之旅 等级2」**弹窗，模板层却判成 `INTEL_BEAST_MISSION / BEAST / level 10`；③ 机制：`POPUP_INTEL_HERO_JOURNEY_TITLE` 裁自**等级10** 帧，在**等级2** 帧上 **d=16**（阈值 8）**无法命中**，而 `TARGET_INTEL_BEAST_MISSION`（anywhere、gate 54）**在四张对话框上全部 d=28**——毫无判别力却答了话 ⇒ 英雄之旅被判成兽任务，`OPEN_INTEL_BEAST_TARGET` 去找没上过屏的目标（大脑里**本来就有**正确的 `INTEL_HERO_JOURNEY` 分支，从没被走到）。**修法（非调阈值）**：`winter_agent_v2/ocr.py::_read_intel_dialog_title` 改用**标题文字**判定对话框种类，并顺带把 `vision.py` 里**硬编码的 `mission_level=10`** 换成真实读数（实测出现 等级2、等级20）；认不出的标题**什么都不改**。6 帧真机 replay 全对，`tests/test_intel_dialog_typing.py` **19 项**通过。这是「裁剪覆盖会变的内容」**第 8 次**，卡已更新。 |
| 26 | `EXIT_CONFIRM` 只有隐式处理 | 🟡 **已量测 + 已命名（2026-09-17）** | **先前判断被实测修正**：该弹窗（「确认退出游戏吗?」 取消/确定/X）上 `BTN_CLOSE` 的**胜出记录** d=2、ROI 中心 **(635,455)** = 标题栏里的 **X**；而两个按钮同在 y 748..842 一行（`BTN_CANCEL` 中心 (208,793)，同族 duplicate-target 对话框的确认在 (503,787)）⇒ **现有路径点的是 X，不会退出游戏**，比我先前写的安全。但它当时是**隐式**的（靠 `BTN_CLOSE` 哪条记录胜出）⇒ 已加显式分支（`exit_confirm_closed_via_its_close_button`）把语义定住，并用 `tests/test_exit_confirm_safety.py`（5 项）钉住"落点必须在标题带、距按钮行 ≥200px、且 x 在右半屏"。证据帧：`dataset/truth_audit/power_route_20260917/close_hero_journey_20260917_043919_99_after_back.png`。 |
| 27 | **叶页（TRAINING/RESEARCH）存活时间很短** | ⚠️ 观察中 | 探针刚把客户端放到科技研究页（`after#4 page=RESEARCH`），几十秒后 `run_live` 起跑时已读回 `HOME` ⇒ 让"下一轮开局就站在叶页上"这个前提难以稳定复现，也是 #23 真机 episode 至今没取到的原因。需要在同一命令链内紧接一次运行，或先量叶页存活时长。 |
| 28 | **兵营聚焦后先出现教程手指，不是径向菜单** | ⚠️ 训练路线回归信号 | 2026-09-17 04:41Z `--goal TRAIN`：`NAVIGATE_INFANTRY_CAMP` verifier OK（`after=HOME`），但随后 `SELECT_INFANTRY_CAMP` **verifier 失败**（`INFANTRY_CAMP_MENU_NOT_PROVEN`）、客户端 `HOME→MAP`。帧显示：兵营被高亮 + **一只巨大的教程手指**指向它，**径向菜单（详情/升级/加速/训练）尚未绘制**。所以 `TARGET_INFANTRY_CAMP_HIGHLIGHTED` 命中、`BTN_OPEN_TRAINING_FROM_CAMP` 未命中 ⇒ 大脑选 `SELECT_INFANTRY_CAMP` 去点兵营，那一下把客户端带到了地图。昨天同一路线是 4 步收敛的（菜单先出现）⇒ 训练路线有**两个阶段**（手指态 → 菜单态），需要分别建模。 **2026-09-17 17:45 GMT+8 再次复现**（同一次会话先修掉了"路线根本起不来"的缺口，见下）——现在路线走通 4 跳、verifier 全 OK：`OPEN_POWER_OVERVIEW` → `OPEN_POWER_DETAILS` → `NAVIGATE_INFANTRY_CAMP` → `SELECT_INFANTRY_CAMP` 的 `after` 仍是 **MAP**。证据帧：`dataset/raw/control_panel/runtime_training/20260917_train_homefix/` 的 `step_004_before`（兵营绿色高亮 + 教程手指 + 红点）与 `step_004_after_refresh_2`（世界地图，可见 9/21/7/15 级他人城市与 25 级麝牛）。⇒ 前沿已从"第 0 步"推进到"第 4 步"，**下一个动作是给这两阶段分别建模板**（手指态应等/点手指，菜单态才点 `BTN_OPEN_TRAINING_FROM_CAMP`），并且要注意 `TARGET_INFANTRY_CAMP_HIGHLIGHTED` 的 ROI 不能把教程手指一起吃进去。 **18:00 GMT+8 又量到两个新事实**：① 该状态**不是瞬时的**——连续 **9 次** `WAIT_FOR_CAMP_MENU` 全部 `menu_drawn=false`（`dataset/raw/control_panel/runtime_training/20260917_train_stageAB/` 8 步 + `…train_bound/` 2 步），所以"等待"是安全的但**不充分**，必须有东西**打发掉教程手指**；② 该记录本身可疑：`roi_norm w=0.59 h=0.285 (x .185 y .39)` ——**宽达 59% 屏宽**，裁自 2026-09-08，命中中心**不是兵营**，旧的一次点击落在那里才去了地图。修 Stage B 需要把兵营**本身**裁成模板（≥3 个独立真机正样本，负样本取菜单已绘制的帧），不是把 ROI 放宽。已给 Stage A 加限界：2 次等待后 `SAFE_STOP camp_menu_never_drawn`（跑完不再空耗整轮）。 **19:51 GMT+8 找到 Stage B 的真修法**：在城市帧**点建筑本体 (280,640)** 立刻得到 `training={"building":"INFANTRY_CAMP","menu_open":true}` —— 径向菜单**是能打开的**；"菜单从不出现"是因为只等待、没点对地方，而"点下去跳地图"是因为 `TARGET_INFANTRY_CAMP_HIGHLIGHTED` 的 ROI 宽 59% 屏宽、**命中中心落在空地上**（这些游戏里**点城市空地就是打开世界地图**）。⇒ 后续应把该 ROI 重裁到**建筑本体**；Stage A 的限界 WAIT 保留为过渡。证据帧 `dataset/truth_audit/power_route_20260917/build_live2_20260917_115113_01_after_tap_280_640.png`（同帧 OCR 另读出 `12`+`盾兵营` 浮动标签与 `详情/训练/升级` 三个入口）。 **21:55 GMT+8 决定性测量（本条性质变了）**：`TARGET_INFANTRY_CAMP_HIGHLIGHTED` **区分不了两个状态**。两帧都被读成 `navigation=INFANTRY_CAMP_HIGHLIGHTED`，但点击后果相反 —— `dataset/truth_audit/training_camp_highlight_ambiguity_20260917/camp_with_gold_ring__click_opens_menu__20260908.png`（地面金色选中环+教程手指，点击**打开径向菜单**）距离 **d=0**；`camp_with_officer_badge__click_jumps_to_map__20260917.png`（军官头像标记，**无光环无手指**，点击**跳到世界地图**）距离 **d=8** —— **恰好压在生产的 `max_distance=8` 上**（探针类默认 6，所以探针与生产本来就会给出不同判断）。原因：该裁剪 `w=0.59 h=0.285` 框的是**建筑本身**，而建筑在两帧里都在，高亮只是建筑上的一层光效 ⇒ 模板里"恒定背景"占绝大多数，判别力只剩 8 级。⇒ **禁止靠把阈值 8 调到 7 来修**（`04_OPEN_ISSUES` 的 #22 已立过同样的规矩，且那只是把刀锋挪到另一处刀锋）；**真修法是把金色圆环（或手指/军官标记）单独裁成紧模板，并用上面这张反例帧测距离**。因此 `RuleBrain` 在 `TRAIN` goal 上对该状态**不再点击**、改为有界 `WAIT_FOR_CAMP_MENU` —— 这是**安全侧选择而非修复**：等待实测不会让菜单出现，`TRAIN` 在该跳**仍然 BLOCKED**（具名停止 `camp_menu_never_drawn`）。见 `knowledge/failure_patterns/vision/TEMPLATE_CROP_COVERS_THE_VARIABLE.md`（本类缺陷已记录至少第 4 次），测试 `tests/test_training_verifier.py::test_the_camp_highlight_signal_cannot_tell_the_two_states_apart` 把"不可区分"钉成可执行断言。 |
| 29 | **普通野兽目标只认"9 级麝牛"这一张模板** | 🔴 阻塞 BEAST_HUNT（**首次由 WorkBuddy 升级工单给出根因，已逐条核验**） | 2026-09-17 第一条真机升级工单（job `8fd1dfbf`，agent 因权限模式无法执行但**读源码给出了可核验的根因**）。核验结果：`TARGET_BEAST_MUSK_OX_9` 在 `template_manifest.json` 里**只有 1 条**记录（144×128，`roi_norm` x .505 y .155 w .2 h .1，`status: CANDIDATE`，阈值 38，dhash 全域搜索区域 `(0.25,0.10,0.95,0.82)`），而姊妹语义 `TARGET_INTEL_BEAST_MISSION` 有 **10 条**（agent 说 ~12，实测 10）⇒ **是缺泛化，不是阈值问题**。下游全链硬绑这一个实例：`vision.py:1675` 写死 `{"visible_target":"MUSK_OX","level":9}`、`brain.py:829` 要求 `MUSK_OX and level==9`、`verifier.py:699` 两半都要求字面 `MUSK_OX`+`level==9`、`skills.py` 固定 `TARGET_BEAST_MUSK_OX_9`。⇒ 只要视野里不是那张 9 级麝牛卡，`world.beast` 恒为 `{}`，大脑 `SAFE_STOP verified_beast_target_not_visible`，**野兽一只也派不出去**。已有一条真机反证：`SELECT_BEAST_TARGET` → `BEAST_TARGET_SELECTION_NOT_PROVEN` 且 `state_after == state_before`（点了等于没点）。外部先验同向：`external_capability_map.json` 的 `BEAST_HUNT` 记 "beast hunting is driven by a configurable search area rather than a fixed point"（REFERENCE_ONLY，只借思路）。**修法方向**：把"野兽目标"从**一个实例**泛化成"卡片族 + 从卡面 OCR 读名字与等级"（与 #24/#29 同源：身份不该靠单一模板）。 |

### 2026-09-19 新增（本轮）

| # | 问题 | 状态 | 说明 |
|---|---|---|---|
| 30 | **MAP 帧不再是"只有一个目标"的页，而三个夹具仍这么假设** | 🔴 **已量清，需操作者定策** | 本轮为修"扫掠/面板例行目标从不被选中"扩了发现层（`PANEL_ROUTINES` + `SWEEP_ROUTINES`，7 条、优先级 **180**），副作用是 **MAP 帧现在发现 8–9 个目标**（实测：`AVOID_STAMINA_WASTE` 2235 / 七条 180 / `KEEP_MARCHES_PRODUCTIVE` 70）。`test_capability_gate.py::DeferredGoalSchedulingTests` 里三条测试（`..._replaced_by_a_hop...`、`..._narrated_once_per_reason...`、`..._the_run_still_plays...`）的前提是"MAP 上除了被延迟的目标没有别的可选项"，并传 `allowed_skills=GATHER_ROUTE`：于是运行选中一条 180 的面板目标，其技能不在该集合内 ⇒ `runtime.py:875` 直接 `SKILL_NOT_ENABLED_FOR_LIVE_LOOP` 收尾、**一步都不发**（`steps[0].execution is None`）。**生产不受影响**：`allowed_skills` 只被测试与 `tools/*probe*` 传入，生产走默认 `allowed = VERIFIED_ATOMIC`（已 grep 全仓确认）。但底下藏着一条真陷阱：**选择器不看 `allowed`**，所以任何"按路线限定技能"的运行都可能被塞给它做不了的目标，然后**硬停而不是顺延**（`allowed_skills` 若将来用于路线级运行即触发）。两件事都属**调度策略**（MAP 上"先领免费奖励"还是"先采集行军"、"路线限定"是否应参与选择），按专家提示词的边界不该由本轮在绿色提交里顺手定死 ⇒ 记录待操作者裁决。数字：本次全量 pytest 由 7 red → **3 red / 100 passed**（受影响文件集），`check_wiring problems: 0`。 |

| # | 问题 | 状态 | 说明 |
|---|---|---|---|
| 31 | **红测试的正确口径是 11 条，不是我先前说的 3 条** | ⚠️ **口径已修正** | 我先前只跑了"受影响文件集"就报了 3，**那是错的**。#30 里写的 "3 red / 100 passed" 只适用于那 5 个文件。**全量实际是 `11 failed, 1907 passed, 7 skipped`（1273s）**。已逐条回基线 `1d0c1f2` 复验：**10 条在基线即失败**（capability_gate 3 条 = #30；control_panel 2 条；evidence_integrity 1 条；live_runtime 1 条；march_formation_attribution 2 条；reward_popup_source 1 条），**另 1 条 `test_live_runtime.py::LiveRuntimeTests::test_unknown_page_recovery_resumes_the_run` 在基线与当前代码下"单跑都过、全量跑才红"** ⇒ **依赖执行顺序/全局状态**，不是我的改动引入的，但它意味着**这条测试的结论取决于谁先跑**，本身是个待修的不稳定项。⇒ 我的提交 `c48448d` 里"passes its offline tests"的说法**没有被全量套件支撑**，此处更正。 |
| 32 | **体力读数 `0/200` 无帧可佐证（假完成风险）** | 🟠 **已加防护，根因待查** | 观测存储记 `stamina {current:0, max:200, source:STAMINA_PANEL} checked_at 13:47:50Z`，但：① 全仓该时刻**没有任何帧**，② 该时刻**没有任何 episode**，③ 前两小时**没有任何耗体力动作**（11 次 `OPEN_INTEL`、**0 次**野兽/情报派出），④ 唯一能读的最近一帧（19:42 本地）写的是 **547/200**。⇒ **不能据此判定"体力已降到 30 以下"**，操作者的验收条件**未达成**。更危险的是：`AVOID_STAMINA_WASTE` 在 HUD 关闭时会**读这个存储**，而该 goal 存在的意义就是把数字压下去 ⇒ 一个假的 0 会让 goal **看起来已满足并停止消耗**，正是本项目最禁止的假完成。**成因**：该次运行观测了帧、写了观测、但**没执行任何动作就停下**（`SAFE_STOP`），因此既没 episode 也没存图 —— 于是这个读数**永远无法被审计**。**已修（`f2837e5`）**：`observation_store.record()` 增加 `frame=`，`_record_observations`/`_record_goals` 全程下传，5 个调用点都带上就地已有的帧变量；带守卫测试（去掉任一 `frame=` 即变红）。**仍未修**：那一次为什么读到 `0/200` 仍然未知，且帧已丢，无法事后追查；下次同类读数会自带证据。 |
| 33 | **`.git/index.lock` 反复成为陈旧残留，卡死所有提交** | ⚠️ 观察中（运维） | 本会话两次遇到：0 字节、mtime 分别早 2h45m 与 24min，`tasklist` 确认**无任何 `git.exe` 进程**后删除即恢复。它让 `git commit`/`git add` 直接失败（`Unable to create index.lock`）。当前处置是"先确认无 git 进程、再删"，**但这依赖人判断**；若无人值守时命中，会静默卡住所有同步。建议后续在同步路径里加一条"陈旧锁检测"（有 PID 语义才删），而不是靠操作者记得。 |

### 2026-09-19 深夜新增（真机一轮的实测）

| # | 问题 | 状态 | 说明 |
|---|---|---|---|
| 34 | **HUD 体力表 OCR 丢位，报出"假低体力"** | 🔴 **阻塞 P0（有帧为证）** | 真机单轮实测：帧 `dataset/raw/live_runtime/stamina_verify/stamina_verify_step_004_after_20260919T143454154158.png` 顶部 HUD 实际写 **527**，而 `world.stamina.current` 报 **52**；同轮 step 3 报 502。三步连续读同一块表给出 502/52/52，`source=MAP_HUD`，而动作是 **SWIPE**（不可能消耗体力）、前后 `marches` 由 1 变 0 ⇒ **不是真消耗，是读数错**。这就是此前 `0/200`（#32）那类"假低体力"的来源。**危险**：`AVOID_STAMINA_WASTE` 正是读这个数决定是否还要消耗 ⇒ 假低值会让 goal 看起来已满足、停止消耗，即假完成。**修法方向**：多帧一致性 + 数字位校验（长度/形状）而不是单帧 OCR；`MAP_HUD` 与 `STAMINA_PANEL` 交叉验证。 |
| 35 | **体力路线拆分在真机未生效** | 🟠 已量清 | 提交 `c48448d` 把 AVOID_STAMINA_WASTE 在打野受阻时改走 `SPEND_STAMINA`（情报），**但该轮实际走的是 `BEAST_HUNT`**：覆盖条件要求 `SPEND_STAMINA_ON_BEAST` 处于 `{BLOCKED,COOLDOWN,DEFERRED,DEVELOPMENT_PENDING}`，而本轮它不在其中 ⇒ 保留打野路线 ⇒ 3 次 `SCAN_MAP_FOR_BEAST` 全部扫空。同时免费体力**照领**（382→502），因为 `current_goal != "SPEND_STAMINA"`，守卫不触发。⇒ 结果：**体力 382→502/527，本轮消耗 0**。需要重新审视"受阻判定"的依据（gate 状态已不是 BLOCKED，但打野事实上找不到目标 —— 即 gate 状态与真实可行性脱节）。 |
| 36 | **`control_panel.py:_run_worker`(4676) 是无调用者的死链** | ⚠️ 假接入类 | 整条 mail→daily→alliance→exploration→intel→beast→gather 链**没有任何生产调用者**，仅 `tests/test_runtime_interpreter.py:183` 断言其文本；AUTO 实际跑 `_run_unified_worker`。属于操作者"防假接入"检查第 2 条命中项。 |

| # | 问题 | 状态 | 说明 |
|---|---|---|---|
| 37 | **HUD 体力 OCR 丢位 —— 已修主因，残留 1 帧** | 🟡 **主因已修（`29400e9`）** | 见 #34 的实测。**根因不是裁剪**：放大核对后 `7` 结束于帧 x≈63，旧 ROI 右边界 x=70 ⇒ 数字完整，是 **RapidOCR 检测框小号数字提前结束**（原始 token 只有一片 `('52',1.0,box→26.25)`，而对照帧有 `('50')+('02')` 两片，拼接无从下手）。修法：`HUD_STAMINA_ROI.w_norm` **0.058→0.075**（四帧实测：0.058 两帧读 52，0.075 两帧读回 527，且原本正确的 382 帧不受影响）。证据帧存 `dataset/truth_audit/stamina_hud_roi_20260919/`。**残留**：`hud_still_read_as_502.png` 末位仍 7→2；测试故意钉住该错值以便日后清理。**待做**：给 HUD 读数加"位长/形状"或 `STAMINA_PANEL` 交叉校验，让单帧错读不再能静默通过。 |

| # | 问题 | 状态 | 说明 |
|---|---|---|---|
| 38 | **HUD 体力丢位的纵深守卫** | 🟢 **已接入（本轮）** | 见 #37。 纯函数（规则＝新值是旧值前导数字且更短；**上升永不中招**）， 在 **5 个  调用点前置**执行、作用于脑与 verifier 真读的 world，命中时保留上次好读数并写 ； 由观测存储播种 ⇒ 跨 run 生效。**明确不拦** 527→502（末位错读，差 25，单帧不可区分，硬拦会误伤）。测试 8 条，撤任一守卫点即红。 |

| # | 问题 | 状态 | 说明 |
|---|---|---|---|
| 39 | **HUD 体力读数修复：真机已验证** | ✅ **已真机验证** | 复跑一轮（修订号 `c415cce4eadd`，确认跑的就是新代码）：5 步全部 `527 (MAP_HUD)`，before/after 一致，无 `dropped_digit_suspected` 标记 ⇒ 加宽 ROI 在真实帧上生效，丢位不再出现；守卫**未触发**（无丢位就不该动）—— 行为正确。**P0 仍未达成**：该轮 stop_reason=`verified_beast_target_not_visible`，5 次扫图、**消耗 0**。⇒ 瓶颈已从视觉层转到路线层：`AVOID_STAMINA_WASTE` 依旧走 `BEAST_HUNT`（#35 闸门状态 vs 真实可行性脱节），地图上有 7 级/24 级野兽却匹配不到（#29 单模板）。 |

| 40 | **野兽识别：23 帧零命中，而数据表早已有那一行** | 🔴 **阻塞体力消耗（已实测）** | 只读探针 `out_beast_measure.py` 对今晚两轮真机共 **23 帧**测量：`vision.py` 的 `TARGET_BEAST_MUSK_OX_9`、`TARGET_BEAST_MAMMOTH_5`、`BTN_BEAST_CARD_ATTACK` **全部零命中**（`find()` 返回 None，连距离都没有），而帧上确实画着带等级徽标的野兽。**关键**：`knowledge/game/beasts.json` 已有 `GREAT_HORNED_DEER_22` 大角鹿 22 级 `status=VERIFIED, action=ATTACK`（另有 `BEAST_GENERIC` 野兽 `CONFIRMED, action=ATTACK`），而 `beast_targets.py` 的设计是**决策看表、识别看模板；无模板的物种没有 `visible_target`，永远到不了这张表** ⇒ **缺口在识别层，不在决策层**。这也解释了 #35：闸门说打野可用（表里有可用行），打野却扫不到目标（没有任何模板命中）—— 两者都没错，只是不在说同一件事。**不是调阈值能修**（#29 同规）。**修法**：为该物种裁模板（≥3 个独立真机正样本 + 反例测阈值），再按既有模式在 `vision.py` 给出 `visible_target` 与名称/等级读数；`beast_targets.py` 与 `beasts.json` 无需改。 |

| 41 | **野兽模板的 ROI 指着空地 —— 比 #40 更基本** | 🔴 **阻塞体力消耗（已实测，含图）** | 把 `TARGET_BEAST_MUSK_OX_9` 的 ROI（`x .505 y .155 w .2 h .1` ⇒ 720x1280 帧上 **(364,198)-(508,326)**）画到今晚真机帧上：**框内是纯雪地／湖岸，没有任何野兽**；而同一帧**确实有**一只带 `7` 级徽标与名字标签的大型野兽，位置约 **x≈119..310、y≈663..877**，**完全在 ROI 之外**（证据图 `out_beast_roi_on_frame.png`，已入库）。⇒ 23 帧零命中的解释是**模板在图上没有野兽的区域里搜索**，而不是「少一个物种模板」。且形态也不同：模板像是按某张 9 级麝牛卡裁的，而本图上野兽是**地图大型立绘 + 等级徽标 + 小名字标签**。⇒ 要修的是**「野兽在地图上如何被识别」这个定义**（ROI 重新量 + 以徽标／标签为锚 + ≥3 真机正样本 + 反例），不是补一行数据。#40 的「该物种无模板」只是它的一个后果，两者不是并列问题。 |

| 42 | **野兽身份可以语义读取 —— 识别应改为"搜名字"而不是"比立绘"** | 🟠 **方向已实测确定** | 对今晚 23 帧、在地图带（x 0.05–0.50，y 0.45–0.80）跑 OCR：**野兽名字被读出**，`霜鳞避役`@0.89 (0.269,0.655)、`猛犸象`@0.88 (0.189,0.645)，且旁边有 1.00 置信度的徽标数字 （`20`@(0.175,0.701)、`25`、`28`、`27` 等）⇒ **名字与等级同帧可读**；标签**随平移移动**，故不能固定 ROI，要在地图带内**搜索**。两个决定性事实：① **`猛犸象` 真的在地图上**，而 `TARGET_BEAST_MAMMOTH_5` 存在却 0 命中 ⇒ 再证模板指错（#41）；② **`beasts.json` 里没有 `霜鳞避役`**（表内为 大角鹿22/麝牛9/猛犸象5/北极狼6/雪豹29/野兽）⇒ **地图上的物种不在表里**，将来模板修好了决策层仍认不出。**修法**：地图带 OCR **物种名** → 与 `beasts.json` 物种名做白名单匹配 → 等级取紧邻徽标数字 → `visible_target` 由名字决定。**比逐物种裁大立绘模板稳得多**（位置鲁棒、物种无关），新物种只需补一行**从客户端读到的名字**（不编造）。同时需把 `霜鳞避役` 登记为新行（等级/费用逐项实测后再填）。 |

| 43 | **野兽语义读取：辅助函数已入库（未接线）** | 🟢 **识别可用，接线未做** | `ocr.py` 新增纯函数 `named_beast_label(tokens, known_names)` 与 `level_beside_label(tokens)`，以及实测搜索带 `BEAST_LABEL_BAND`（x .05 y .45 w .45 h .35）。**白名单是安全属性**：同带内还有 联盟畜牧场／联盟木材场／铁厂／未驻防／开，不过滤就会把锯木厂叫成野兽；等级取**唯一**裸数字，出现两个候选取 None（不猜，猜错会照未知等级派行军）。真机帧测试 5 条全过：`猛犸象`@0.88 读回；`霜鳞避役`@0.89 **读得出但返回 None（未登记）**；无反例误报。**未接线**：`world.beast` 仍只由那两张大立绘模板产生，因此本次不改变 Agent 行为。**待做**：① 将该读接入 `vision.py` 的 `world.beast`（严格增量：模板已命中时不覆盖）；② 登记 `霜鳞避役` 一行（等级与体力消耗实测后再填）；③ 真机验证 `world.beast` 非空且体力开始下降。 |

| 44 | **登记 `霜鳞避役`（仅实测字段）并证明白名单链路可用** | 🟢 **已登记并验证读通** | `beasts.json` 新增 `FROST_SCALED_RUNNER_20` / 霜鳞避役 / level 20：**只填实测两项**（名字 0.89、徽标 20 读 1.00），其余推荐战力／体力消耗／entry／action／verification **一律 UNKNOWN**、`status=UNVERIFIED`（这些正是决定派不派行军的字段，不得猜）。**证明**：登记前同一帧返回 `None`，登记后返回 `霜鳞避役`；测试子项 6→8 全过，且"名字不在白名单必须拒绝"改为对**临时移除该名字的白名单**断言，与表内容无关仍成立。**仍未接线**：`world.beast` 只由模板产生。**下一层障碍已查明**：`visible_target` 用物种 token （`MUSK_OX`/`MAMMOTH`），硬编码于 `brain.py:1042`、`verifier.py:749/761` ⇒ 新物种被派发还需 ① 一个 species token ② 接受该物种的 verifier（无 verifier 的技能永不被调度）。属多环节改动，另立一步。 |

| 45 | **物种 token 已补，拒绝派发已显式化** | 🟢 **已补齐并经真实 loader 验证** | `beasts.json` 的 `FROST_SCALED_RUNNER_20` 增补 `species=FROST_SCALED_RUNNER`（`_species_from_record` 显式字段优先于 id 解析；路线说的是物种 token）与 `dispatchable=false`（显式值自己说了算，不走"绿色胜算 + VERIFIED"的推断 —— 该物种除名字/等级外未验证，拒绝应被**声明**而非被推断出来，这也是防止将来接标签读数时误花体力的闸门）。**用真实 loader 验证**：`load()` 现返回该行 `species=FROST_SCALED_RUNNER level=20 status=UNVERIFIED route=FROST_SCALED_RUNNER_20`；`is_dispatchable(...)` → **False**。22 条测试通过。**剩余缺口仅两件**：① 接受该物种的 **verifier**（无 verifier 的技能永不被调度）；② 将标签读数接入 `world.beast`（严格增量）。 |

| 46 | **`world.beast` 接线尝试失败并回退；`observe` 被我弄坏两次** | 🔴 **未完成（已回退）** | 目标：把 #43 的标签读数接进 `world.beast`（严格增量、模板优先）。**错法一**：把辅助方法插在 `visible_musk_ox = match(...)` 之前，而该行在 `SemanticWorldVision.observe` **方法体内** ⇒ 4 空格缩进的 `def` **就地截断了 `observe`**，MAP 分支整段变成新函数体、`observe` 返回 None；**`py_compile` 仍通过**（结果仍是合法 Python），只被 `test_beast_card_route.py` 两条行为测试抓到。**错法二**：改模块级函数后那两条仍红，而我**未先量基线就继续改**，随即停止并回退 `vision.py` 到 HEAD。**教训**：`py_compile` 不证明结构完好；插入前必须确认插入点作用域，改后必须跑行为测试。**并发发现**：连跑多文件时 `test_live_runtime.py` 新增 5 条 `FileNotFoundError`（此前 2 条）—— 运行中的面板有 retention 会删掉运行截图，而测试读这些帧 ⇒ **失败集合随跑法与时机变化**，这解释了 #31 的"单跑过、全量红"。**测试不得依赖可被清理的运行帧**，需换成证据帧。**未完成项仍是两件**：接受该物种的 verifier、以及这次没接成的 `world.beast` 接线。 |

**更正（2026-09-19 23:27）**：本条说"`observe` 被我弄坏两次"——**第二次没有成立**。回退后补测：`test_beast_card_route.py` **单独 13 passed**；与 `test_beast_label_recognition.py` 同跑 **18 passed**（`vision.py` 全程与 HEAD 逐字节相同）。⇒ 第一次是真错（4 空格 `def` 插进方法体会就地截断 `observe`，结构上确定）；**第二次那两条红属"顺序/组合相关"失败**，被我误读为"仍然坏"，**因此回退了一个尚未被证明有问题的版本**。**教训**：归因前必须先把受影响测试**单独跑一遍**排除顺序相关。**未完成项不变**：接受该物种的 verifier、`world.beast` 接线。

| 47 | **让位机制真机生效；新阻塞＝情报"无未试引脚"** | 🟠 **半通（真机已验证让位）** | 真机一轮（修订 `0b814fca+8b5040da`，dirty＝含本次未提交改动）：步1–5 `SCAN_MAP_FOR_BEAST`（体力恒 527）→ **步6 `OPEN_INTEL`**（让位按设计生效，不再是扫完即 SAFE_STOP）→ 步7 `SELECT_INTEL_PIN` → 步8 `BACK`；stop_reason=**`intel_no_untried_pins`**，**体力仍 527、消耗 0**。**新阻塞**：观测存储记 `intel {status: AVAILABLE, pins: 5, available_count: 1}`，但大脑判"无未试引脚" ⇒ 两者不一致；与本日早先记录（被"战力不足"拒绝的引脚未记入已试集合）同源。**待做**：查清"可用引脚"与"未试引脚"的口径差异（大概率是拒绝原因未落账），再决定是记录拒绝还是换其它已验证耗体力任务（如探索 ⚡10）。 |

| 48 | **情报阻塞＝环境条件（战力不足），非能力缺口** | 🟢 **已定性（逐步真机读数）** | 真机逐步 reason：步6 `OPEN_INTEL`（`spend_goal_switches_to_intel_no_beast_in_view`，让位名字确认生效）→ 步7 卡面 `{BLOCKED, MASTER_BOUNTY, level 20}` → 步8 `BACK`（**`intel_master_bounty_power_blocked`**）→ 步9 `intel_no_untried_pins`（`detected_pins: 1, untried_pins: 0`）。⇒ 情报板**只有 1 个引脚**（存储 `pins: 5` 为旧读数），且**因战力不足被正确放弃** ⇒ 按 §六.22 属**环境/账号条件，DEFER/SWITCH，不开发**。**另确认耗体力链路已注册**：英雄之旅 `OPEN_INTEL_HERO_JOURNEY_TARGET`/`INTEL_HERO_START_MARCH`(探险⚡10)/`INTEL_HERO_DISPATCH` 均已绑 verifier；`START_RALLY`/`JOIN_RALLY` 亦然。**结论**：三条耗体力路径中，**只有打野是真能力缺口**（模板搜空地，23 帧 0 命中）⇒ P0 下一步应修它，而不是放宽战力判定。 |

| 49 | **卡死解除（真机证实）＋让位可靠；新阻塞＝`OPEN_INTEL` 验证失败** | 🟠 **半通** | 修订 `580e89a6+9694423f` 真机：步1 `BACK` reason=**`beast_goal_leaves_a_panel_it_does_not_own`** （**INTEL→MAP**，卡死解除；该卡死系我上一轮让位改动引入的回归，**单测全绿、靠真机才发现**）；步2–6 五次扫图（体力恒 527）；步7 **`OPEN_INTEL`**（reason=`spend_goal_switches_to_intel_no_beast_in_view`，让位第二次独立触发）。**新阻塞**：`stop_reason=SEMANTIC_TARGET_NOT_VERIFIED`（exit 2）—— `OPEN_INTEL` 的 verifier 未通过，**体力仍 527、消耗 0**。**可疑成因（待测）**：步2–6 连续 5 次地图 SWIPE 平移很远，随后点情报入口时语义目标不可解析/点击未生效。**下一轮先量该帧**，不改判定。 |

| 50 | **`OPEN_INTEL` 因语义目标 `BTN_OPEN_INTEL_WILD_HUD` 未解析而失败** | 🟠 **根因已定位，距离未测** | run JSON 实测：`execution={{executed:false, target:"BTN_OPEN_INTEL_WILD_HUD", error:"SEMANTIC_TARGET_NOT_VERIFIED", backend:"MAA"}}` ⇒ 动作**根本没执行**。该帧（`beast_label2_step_007_before_...png`）上**情报入口图标可见**（左侧蓝色图标），且地图被 5 次 SWIPE 平移得很远、大片黑区。模板清单 402 条中 `BTN_OPEN_INTEL_WILD_HUD` **出现 3 次**（`semantic` 字段）⇒ **不是缺模板，是该帧匹配不上**。**未完成**：尚未量出这 3 条模板在该帧上的**实际距离**（`find()` 只给匹配/不匹配），故无法判断是"差一点（阈值/ROI）"还是"差很远（画面状态）"。**下一步先测距离再决定**，不得先动阈值（#29 规矩）。**附带实测**：该帧两只动物只有等级徽标（28/17）**没有名字** ⇒ 标签识别在这类帧上不触发（正确，但说明名字并非每帧都有）。 |

| 51 | **情报入口 ROI 在该帧上对着空地 —— 不是阈值问题** | 🔴 **已量出，修法已定方向** | `SemanticROIVision(max_distance=999)` 并抬 per-semantic 阈值后测**原始距离 = 34**（阈值 **24**），3 条模板（`wild_fresh_before`/`night_1`/`night_2`，均 `CANDIDATE`）；`roi_norm` x **0.865** y 0.635 w 0.12 h 0.075 ⇒ 帧上 (623,813)-(709,909)。**决定性证据是裁图**：该 ROI 从失败帧裁出放大 6 倍后**是一整块近乎纯黑面板，没有任何图标**（`out_intel_roi.png`）⇒ **不是"阈值紧 10 点"，是锚点在这帧上根本不对着按钮**。按 #29 规矩**禁止把 24 调到 35**（那只会让"对着空地"变成"命中空地"）。**正确方向**：在当前客户端上**重新定位情报入口真实位置并重裁模板**。**旁证**：该帧右侧图标列在 y≈0.815/0.859（≡ 与邮件），ROI 却指 y 0.635（黑区）；左侧蓝图标列在 x≈0.055 ⇒ 入口真实位置与 0.865 不符。 |

| 52 | **情报入口模板把背景裁进去了 —— 同一按钮，背景变则失配** | 🔴 **已定死，修法明确** | 同阈值抬到 999 测两帧原始距离：**成功帧（23:33）13**（<24）、**失败帧（23:50）34**（>24），**最佳中心完全相同 (0.925,0.745)**。并排放大 5 倍（`out_intel_button_compare.png`）：**同一图标、同一位置，唯一差别是背景** —— 成功帧是浅蓝底、失败帧是深黑底（该轮在地图上连滑 5 次，HUD 背后地图变黑）。⇒ `BTN_OPEN_INTEL_WILD_HUD` 的裁剪**把背景吃进去了**。**这是本项目已知缺陷类「裁剪覆盖了会变的内容」的第 5 次**（#24/#25/#28/#29 同类）。**修法**：裁到按钮恒定核心（蓝底白圈方块）、排除背景；当前 ROI w 0.12 h 0.075 ⇒ 86x96 px，图标本体只占一小部分。**禁止**放宽阈值 24→35。 |

| 53 | **修法已由实测证明：紧裁到按钮本体，距离 30 → 12** | 🟢 **修法+坐标已定，注册未做** | 用项目自身 `image_hash.phash/hamming` 比两帧同区：**现 ROI 尺寸 86x96 @ (623,813) → d=30（FAIL）**；**按钮本体 69x68 @ (629,922) → d=12（PASS，<24）** ⇒ 背景是主因，紧裁即修法（非调阈值）。按钮位置是在**失败帧**上量的（该帧背景全黑，蓝板是画面唯一蓝色）：`(629,922)-(698,990)` ⇒ 归一化 {'x_norm': 0.8736, 'y_norm': 0.7203, 'w_norm': 0.0958, 'h_norm': 0.0531}；而现 ROI y=0.635 **比按钮本体高 -0.0853**（这解释了我先前裁出"纯黑面板"——我的框比按钮高了一截）。**留档**：`dataset/truth_audit/intel_button_plate_20260919/` 存两帧紧裁为候选正样本（不从运行帧取，因 retention 会清理）。**未做**：注册进 manifest（需按既有流程 + ≥3 独立正样本 + 反例）、真机复验。 |

| 54 | **紧裁模板 42 帧分离度实测：命中 d≤6、缺席 d≈36，阈值 24 落在空档** | 🟢 **修法已验证，注册未做** | 把按钮本体框 `(629,922)-(698,990)` 用于 **42 张 720x1280 真机帧**（跨 4 个运行目录），与正样本比 phash 距离：**d ≤ 6 → 34 帧**（按钮在场，命中）；**d ≈ 36 → 8 帧**（**全是非地图帧**，正确缺席）。⇒ 阈值 24 正好落在 6 与 36 之间的空档，**分离干净、不会误报**（不只是"擦边过"）。**正样本已补至 4 个**（存在 `dataset/truth_audit/intel_button_plate_20260919/`），满足"≥3 独立真机正样本"。**未做**：写入 `template_manifest.json`（按既有注册流程）、真机复验。 **关联**：该缺陷属「裁剪覆盖了会变的内容」类第 5 次（#52），此处给出该类的一个**可复用判据**：**跨帧同区距离应当落在阈值空档内，而不是擦边**。 |

| 55 | **情报入口模板已修并注册（验证通过）；真机复验被 `STARTUP_VERSION_CHANGED` 与训练路线失败挡住** | 🟢 **模板已修 + 🔴 **新发现** | 新建 `tools/cq_intel_entry_register_plate.py`（仿既有注册工具），**增量**注册紧裁模板 `69x68 @ (629,922)`、`roi_norm {0.8736,0.7203,0.0958,0.0531}`；manifest 402→403。生产匹配器验证：失败帧 **NO MATCH→MATCH d=6**；原本成功的帧 d=13→d=0；**3 张非地图帧仍 NO MATCH**（无假阳性）。**阈值 24 未动**（6 与 36 之间有空档，无需动）。**真机复验两次均未到体力链路**：① **`STARTUP_VERSION_CHANGED`**（R1 `+f435a0c1` ≠ R2 `+3f6d7c5d`）—— 启动窗口内工作树被改，**最可能是运行中的泵在写状态文件**（该文件在版本指纹集合内）；围栏行为正确，但**面板持续写状态时 AUTO 轮次会被随机拒绝**，需量频率；② 重试后运行选了训练路线（`OPEN_POWER_OVERVIEW` → `POWER_OVERVIEW_NOT_PROVEN`），**没走到体力链路**。**体力 527→527，消耗 0，低于30=FAIL**。 |

| 56 | **体力目标"未被选中"的真因：该轮根本没发现它** | 🟠 **已查明（含链条）** | 用生产侧同一套视觉构造在那一轮真机帧上跑运行时选择链（只读）：`page=HOME`、`stamina=None`，`discover()` 产出 **7 个目标但没有 `AVOID_STAMINA_WASTE`**（其余各 180）⇒ **丢在第一步 discover**。链条：① 起始帧是 **HOME**，该页无体力表 ⇒ 帧里无体力；② 该目标只在能读到体力的页面上产出（设计如此）；③ 观测存储也补不上 —— stamina 域**现已整个消失**，且其 **TTL 仅 10 分钟**，昨晚 14:45Z 的读数即便还在也已过期；④ ⇒ 本轮不可发现，180 的训练目标胜出；⑤ 训练路线在 HOME 上第一步即 `POWER_OVERVIEW_NOT_PROVEN` 收尾，**整轮在观测地图之前结束** ⇒ 体力目标始终没机会出现。**不是策略/闸门问题**（`deferrals` 空亦相符）。**含义**：要让体力目标存在，本轮必须先**走到 MAP** 读一次 HUD；而当前训练路线在 HOME 上会失败收尾，把这一轮挡在到达地图之前。**下一步**：查训练路线在 HOME 的第一步为何失败（或让目标在被选前先读一次 HUD）。 |

| 57 | **训练第一步落点打在建筑上（军医所），间接挡死体力链路** | 🔴 **已定位（含帧）** | 真机 after 帧（`plate_fix2_step_001_after_...png`）显示点开后打开的是**「军医所」升级面板**，不是实力面板 ⇒ `OPEN_POWER_OVERVIEW` 的语义目标**落点偏、打在建筑上**，`verify_power_overview_open` 正确拒绝（`POWER_OVERVIEW_NOT_PROVEN`）。**属今晚已查清的同一缺陷类**（野兽模板搜空地 #41 / 情报入口把背景裁进去 #52）。**它为何卡住 P0**：该轮选训练目标 → 第一步失败 → **verifier 失败即结束整轮** → **整轮在观测地图之前死掉** → 而地图是体力目标唯一可能出现之处（#56）。**修法**：先量 `OPEN_POWER_OVERVIEW` 真实落点与 HOME 上实力入口的实际位置，按 #52 的判据（跨帧距离落在阈值空档内）；**不得**放宽 verifier 让它通过。 |

**更正（2026-09-20 08:10）**：本条原写"落点偏、打在建筑上"——**测量推翻**：`BTN_OPEN_POWER_OVERVIEW_ICON` 只有 1 条记录（CANDIDATE），在**该轮 HOME 帧**上解析 **distance=10、中心 (0.1625,0.0565)**，正是左上角实力数值（帧上可见 `1,596,488`）⇒ **落点正确**。且 `after_refresh_2`（约 24s 后）**两张面板都不在**，是普通 HOME ⇒ `after` 里那张「军医所」是**瞬时面板**，而**实力面板始终没打开**。**真实结论**：落点正确但期望面板未打开、并出现一张无关瞬时面板；**成因未查明**。**教训**：我凭"同类缺陷"的直觉归因，**没有先量落点** —— 归因前先量这条纪律今晚又被我自己违反一次。

| 58 | **点击落点没有落进证据 —— 使"点击为何无效"事后不可查** | 🔴 **证据缺口（已定位）** | 读 verifier 得"实力面板"的定义：`verify_power_overview_open` 要求 `after.page is POPUP and after.popup == "POWER_OVERVIEW"`；而该轮 after 帧被判 **HOME**（`evidence: {home_before: true, overview_after: false}`）⇒ 客户端确实没打开。**但"为什么没打开"在证据里查不到**：execution 记的是 `{"kind":"TAP_SEMANTIC","target":"BTN_OPEN_POWER_OVERVIEW_ICON","payload":{}}`，**`payload` 为空、解析出的落点从不落盘**；step 字段仅 `[after, before, decision, execution, index, verification]`。⇒ 对"一切结论都要能从 artifacts 证明"的系统，这是**证据完整性缺口**：一次点击没生效，事后**无法判断落点**，只能离线用**静态帧**重算（未必等于运行时那帧）。**这就是该项今天无法收口的原因**——不是没查，是证据里没有那一项。**修法**：把 `resolve()` 的实际落点写进 execution payload（或 step 单列字段），使"点哪儿了/偏多少"可从事后帧直接回答。 |

| 58b | **点击落点已落进 Episode（#58 已修）** | 🟢 **已修（`6b0a6dd`）** | `ExecutionResult` 新增 `tap_point`（**设备像素**，非归一化 —— 归一化会丢掉帧尺寸这一事实）；`executor.py` 保留交给设备的像素、`executor_router.py` 重建结果时转发；运行以 `asdict(result)` 输出 ⇒ **无需额外接线即进 Episode JSON**。测试 5 条（自建假设备记录实际 tap）。**该测试抓到了本次改动自身的一个真错**：第一版把参数加进 `_result` 签名却**未转发给 `ExecutionResult(...)`** ⇒ 设备被正确点击而记录恒为 None（**只靠看代码看不出来**）。**下一步**：下一次真机点击失败将自带落点，届时可直接回答"实力面板为何没打开"（#57）。 |

| 59 | **点击落点字段真机验证通过** | ✅ **已验证（重机）** | 修订 `a880194204+3f6d7c5d`：步1 `OPEN_ALLIANCE` **tap=[540,1229]**（页面 **HOME→ALLIANCE** ✅）、步2 `OPEN_ALLIANCE_GIFTS` **tap=[529,678]**、步3 `SAFE_STOP alliance_state_unknown`。⇒ **每次点击都带设备像素坐标，"点哪儿了"可从事后 Episode 直接回答**。本轮所选为联盟路线（`KEEP_TRAINING_PRODUCTIVE` 被让位给开发任务 `02986fdd`），取得一次真实页面变化；**与体力无关，体力 527→527、消耗 0、低于30=FAIL**。**遗留**：步3 的 `alliance_state_unknown` 说明联盟页读不出状态，是联盟路线的下一个待查点（非 P0 阻塞）。 |

| 60 | **客户端卡在联盟页、`BACK` 推不动 —— 当前首要阻塞** | 🔴 **已定位（含 reason）** | 修订 `1be0748b+f272d5e0`：步1 `BACK`（`tap=None`，正确：BACK 无落点）`page ALLIANCE→ALLIANCE`、reason=`mail_goal_leaves_a_panel_it_does_not_own`，`stop_reason=SAFE_BACK_NOT_PROVEN` ⇒ 上一轮把客户端留在联盟页，本轮发一次 BACK 但**客户端没动**。**与昨晚 INTEL 同形**（一轮留页、下一轮出不去），但这次**连 BACK 都推不动** ⇒ 该页退出方式**不是系统返回键**（或被该页吞掉）。**为何首要**：客户端回不到 MAP ⇒ 读不到体力表 ⇒ 体力目标无法被发现（#56）⇒ **P0 整链被挡在最前**。**下一步**：看该轮 after 帧，量清联盟页真实退出方式（独立关闭控件 / 需按两次），**不得**放宽 `verify_safe_back` 让失败通过。 |

| 61 | **V2 已解除对旧目录 `E:\dongri-mumu-bot` 的依赖** | ✅ **已验证（真机）** | 新环境 `E:\无尽冬日智能体\.venv`（**复制**自旧 venv：959MB/61 包，MaaFw/MaaAgentBinary/opencv/onnxruntime 齐全；基底解释器在旧目录之外，副本自立；新 venv 内部无旧路径）。四处生产引用 + 20 个开发工具 + 4 份文档 + 工具注册表已改指；`START_HERE.md` 保留一条「旧目录已退役」的警告（`verify_handoff` 的陷阱令牌需要）。**真机验证**：`resolve()` → `missing=()`；preflight **PASS**；面板日志 `运行环境预检通过` → `自动运行已启动`；**活 worker 命令行已是 `E:\无尽冬日智能体\.venv\Scripts\python.exe`**；**MAA 原生执行** `capture_backend=MAA_MUMU_EXTRAS`、`capture()` 11.6 ms；网关 OK。**同时修掉挡住 AUTO 启动的真 bug**：面板按 OEM 解码 `preflight --json` 的裸 UTF-8 ⇒ 中文根路径乱码吃掉闭引号 ⇒ `Invalid \escape` ⇒ 拒绝启动 AUTO；已改为 ASCII 转义 JSON。**仅剩两处非运行时引用**：① `knowledge/provenance/research_research_sources.json` 指向旧目录里一个源文件（`LOCAL_REFERENCE_ONLY` 的溯源记录，删后该指针悬空）；② `capability_bootstrap.py:1086` 的 `legacy:` 资产**名**（只做名字匹配，不读该目录）。**未删除旧目录任何内容。** |

| 62 | **Soak「启动失败」＝窗口来自开发解释器（机制正确）；另修两个真缺陷** | ✅ **已定性 + 已修** | `_drive_soak` 是**进程内**构造 `GatewaySoak`，`gateway_soak.py` **不创建任何子进程** ⇒ **Soak 不选解释器**；截图那句来自 `launch_context()`（`control_panel.py:1390`），打印的是**窗口自己的** `sys.executable`。三向实测：venv 启动→`production`（Soak 启动）；带 `WINTER_AGENT_LAUNCH_PATH=desktop`→`production`；其它解释器→**截图那句** ⇒ 拒绝正确，**隔离检查必须保留**。今天 `panel.log` 有 4 次 `验收 Soak 已启动`（09:54–09:59，venv 窗口）。**真缺陷 A**：`escalation_queue._wiring_problems()` 用 `sys.executable` 派生 `check_wiring`，而它由面板泵驱动 ⇒ 开发解释器会判断产品接线；**已改走 `runtime_env`**（解析不到返 `None`）。**诚实**：本次**未改变结论**（该工具不依赖第三方包）⇒ 修的是隐患，不是症状。**真缺陷 B**：`control_panel.py:4023` `view` 未绑定（两个兄弟刷新都有 `view = escalation_view()`，此处丢了），NameError 被宽 `except` 吞掉 ⇒ **一致性卡片每次刷新都失败且沉默**；无 traceback，靠**静态分析**定位，**已补**，并加 `tests/test_panel_names_are_bound.py`（移除该行即 2 条变红）。**观察（未定性）**：`CONTROL_PLANE_RELOAD_REQUIRED.json` **只写不删**（对照 `runtime_reload` 有 `clear()`），重载判定虽为 git 派生，陈旧标记是否复触发**未证明**。 |

| 63 | **测试基线重建：此前"已知 9 项失败"清单的**成员**是错的（数量巧合相同，反而掩盖了错误）** | 🟢 **已重建（2026-09-20）** | **方法**：**不要**单次跑全量 `pytest tests/ -q` —— 本机会在 `[100%]` 处被宿主的批量删除护栏截断（`[safe-delete][SAFE_DELETE_BULK_CONFIRM_REQUIRED] {"count":742,"threshold":50,...}`），**不打印 summary**，于是"没有 FAILED 行"会被读成全绿（本轮我本人踩了一次，差点报成"全绿"）。必须用 `python tools/run_tests_batched.py --batches 8 --timeout 900`（按文件切批 + 每批 fresh basetemp；无 summary 的批记 `INCONCLUSIVE`，不重掷骰子）。**结果**（8 批全部有 summary，`no verdict: none`）：`1973 passed, 9 failed, 7 skipped, 0 error`，VERDICT: INCOMPLETE。**真实 9 项**：① `test_camp_panel_stamina.py::CampPanelStaminaIsReadTests::test_the_camp_panel_reads_the_same_number_as_the_map` ② 同文件 `::test_the_read_names_the_page_it_came_from` ③ `test_evidence_integrity.py::test_every_image_literal_in_the_suite_resolves_to_a_file` ④ `test_live_runtime.py::LiveRuntimeTests::test_verified_action_repeats_then_safe_stops` ⑤⑥⑦ `test_capability_gate.py::DeferredGoalSchedulingTests::{test_a_deferred_goal_does_not_displace_work_that_is_still_selectable, test_a_deferred_goal_is_replaced_by_a_hop_to_where_goals_are_observable, test_the_run_still_plays_when_the_blocked_goal_is_all_there_is}` ⑧⑨ `test_march_formation_attribution.py::MarchFormationAttributionTests::{test_a_run_that_never_selected_a_goal_keeps_the_placeholder, test_the_step_that_opens_the_formation_page_carries_the_goal_that_owns_it}`。**与旧清单的差（两个方向都错）**：旧清单里 `test_capability_gate.py` 6 项现在只红 3 项，`test_queue_pump.py::VersionActivationTest` 与 `test_beast_targets.py::TableTest::test_todays_table_allows_exactly_the_live_verified_musk_ox` 现在**通过**；而 `test_camp_panel_stamina.py`×2、`test_march_formation_attribution.py`×2、`test_live_runtime.py`×1 **不在旧清单里却红着**。⇒ **"这是既存失败、与本次改动无关"不得引用任何静态清单**；判定必须用干净 `git worktree add --detach <tmp> HEAD` 在 HEAD 上 A/B（注意 worktree **不含被 gitignore 的 `dataset/`**，只适合跑不依赖 dataset 的测试）。**另一条稳定性限制**：`test_live_runtime.py` 与 `test_camp_panel_stamina.py` 会读 `knowledge/**` 与 `config/policy_state.json` ⇒ **失败集合随工作树数据变化**（同一份脏数据下我先后看到 1 项和 2 项失败）⇒ 静态清单对它们天然不稳定。 |

| 64 | **「点击任意位置退出」的奖励弹窗把 AUTO 挡死；修法已被操作者同意，待实施** | 🔴 **已定死，等实施** | **现场**：`runtime_snapshot` 停在 `current_goal=AUTO_DISCOVERY`、`current_skill=SAFE_STOP`、`page=POPUP`、`stop_reason=generic_reward_without_goal_context`；帧 `dataset/raw/control_panel/runtime_auto/20260920_204143_843357/…_step_001_before_20260920T124146365715.png`（「获得奖励」+ 页脚「点击任意位置退出」）。每出现一次就结束一轮 ⇒ 情报/体力做到一半就停。**实测（`max_distance=999` + `find`）**：`POPUP_GENERIC_REWARD_HEADER` **16 / 门 16**（恰好卡门）；`BTN_CLOSE`（= `CLOSE_POPUP` 的目标）**28 / 门 6**（ROI 在右上空白）⇒ **`CLOSE_POPUP` 在这张弹窗上必然失败**；`BTN_DISMISS_INTEL_REWARD` **2**（roi x0.36 w0.28 **y0.90** h0.07 = 页脚那条）。**两个结构事实**：① **五个 `DISMISS_*_GENERIC_REWARD` 的动作目标完全相同**（`skills.py:169-174` 都点 `POPUP_GENERIC_REWARD_HEADER`）⇒ `brain.py:397` 的 `TRAIN`/`RESEARCH` 白名单**在机械上没有保护任何东西**，只是限制这**一个**行为何时被允许；② **执行器能传坐标**（`skills.py:426` 的 `Action("SWIPE","0.50,0.62,0.50,0.30",…)` 已在生产跑通 396 次）⇒ 项目笔记"执行器只支持 `TAP_SEMANTIC`、无绝对坐标"**对点击成立、对坐标输入不成立**。**操作者已同意的三步修法**：① 新增一个 **goal 中立**的弹窗关闭技能，目标与那五个一致（或在新建语义后指向页脚退出带 y≈0.90，避开奖励图标）；② 把 `brain.py:412` 的 `SAFE_STOP` 兜底指到它（**仍不猜域名技能**）；③ 同步更新两处守卫并写清理由——`check_wiring` 的 `OK brain: reward popup without goal context stops rather than guessing` 与 `tests/test_reward_popup_source.py::…::test_without_goal_context_it_stops_rather_than_guessing`（**理由：关掉一个自称"点任意位置退出"的弹窗不是猜，是它自己声明的退出方式**）。⚠ **三步必须一起做完再提交**：只做①②会把 `check_wiring` 留红。⚠ 新增技能必须绑 verifier 并进 `VERIFIED_ATOMIC`，否则永不被调度。 |

**#64 补充（2026-09-20 20:58，真机）——问题比"拒绝关闭"更深一层：关闭动作**试了、但无效**。**
最近 20 分钟 6 轮里有 **5 轮是"只做一个动作然后失败"**，全部是奖励弹窗：
`20:38:24` `OPEN_DAILY→DAILY_CLAIM_REWARDS→DISMISS_DAILY_GENERIC_REWARD:FAILURE`；
`20:39:15` / `20:52:01` / `20:52:38` / `20:53:45` 各 `n=1`，分别是 `DISMISS_DAILY_GENERIC_REWARD:FAILURE` 与
`DISMISS_MAIL_GENERIC_REWARD:FAILURE` ×3；直到 `20:54:34` 才由 `BACK→OPEN_MAP→OPEN_HOME→OPEN_MAP→SEARCH_RESOURCE→SELECT_RESOURCE` 脱身
（末步 `SUBMIT_RESOURCE_SEARCH:FAILURE`）。
⇒ **当 goal 有上下文（MAIL/DAILY）时，那五个域技能确实被选中并点击了，但 verifier 判失败** ——
与实测一致：`POPUP_GENERIC_REWARD_HEADER` **恰好 = 16 = 它的门**，所以能解析、能发射点击
（因此是 verifier FAILURE 而不是 `SEMANTIC_TARGET_NOT_VERIFIED`），但那块 ROI 是**弹窗横幅/标题**，
**点它并不能退出这个"点任意位置退出"的弹窗**。
⇒ 结论修正/加强：**修法不能只改决策兜底，必须同时改"点哪儿"**（页脚退出带 y≈0.90，或等价的一次中性点击）。
只改 `brain.py:412` 的兜底 = 让一个已经证明无效的点击多发生几次。

**#64 续办入口（2026-09-20 21:02，交接给下一个会话）**

**现状**：面板在跑（操作员从桌面重启的），AUTO 在跑；**它现在被奖励弹窗反复打断**
（最近 20 分钟 6 轮中 5 轮是"单个动作失败"，全是 `DISMISS_*_GENERIC_REWARD:FAILURE`）。
`CLEAR_INTEL` 已 `DEFERRED`(streak 4)，体力 Goal 未完成。

**下一步按这个顺序做**：
1. **先改"点哪儿"**，再改决策兜底（顺序反了会白做一次真机）：给那张「获得奖励/点击任意位置退出」
   的弹窗一个**真正有效**的落点——页脚退出带 `y≈0.90`（已实测 `BTN_DISMISS_INTEL_REWARD` 在
   `20260920_204143_843357/…_step_001_before_…png` 上以 **d=2** 命中该带；其 `roi_norm` 为
   `x .36 y .90 w .28 h .07`）。**不要**继续用 `POPUP_GENERIC_REWARD_HEADER`（横幅，点了无效）；
   **不要**用 `CLOSE_POPUP`/`BTN_CLOSE`（该帧 **d=28 ≫ 门 6**，ROI 在右上空白）。
2. 新增**goal 中立**的关闭技能并**绑 verifier 且进 `VERIFIED_ATOMIC`**（否则永不被调度），
   再把 `brain.py:412` 的 `SAFE_STOP` 兜底指到它。
3. 同步改两处守卫（**必须与 1、2 一起提交**，否则 `check_wiring` 会红）：
   `check_wiring` 的 `OK brain: reward popup without goal context stops rather than guessing`
   与 `tests/test_reward_popup_source.py::…::test_without_goal_context_it_stops_rather_than_guessing`。
   理由：关掉一个自称"点任意位置退出"的弹窗**不是猜**，是它自己声明的退出方式。
4. 在**本机**验证落点的方法（不需要占设备）：取该帧路径，
   `SemanticWorldVision(template_manifest.json, max_distance=999)` 然后 `semantic.find(frame, name)`，
   读**原始距离**再和 `semantic_max_distance` 的门比 —— 这是分辨"差一点"和"对着空地"的唯一办法
   （#51/#52 的方法；今天它已经纠正过我两次）。
5. **情报剩余数 / 体力读数仍未取到**（回答验收表 §一 必须补）：
   在**客户端停在情报页**时抓一帧、在**停在 MAP**时抓一帧 HUD，然后用 `Read` 直接看图读数。
   **不得**用 `OPEN_INTEL` 次数、`SCAN_MAP_FOR_BEAST` 次数、Skill PASS 次数或进程重启次数替代；
   **不得**用观察存储里的旧读数（当前那个 `8` 取自 `%TEMP%` 临时帧、4 小时前，已污染）。
   抓帧的现成来源：`dataset/raw/control_panel/runtime_auto/<最新轮次>/*_step_*_before_*.png`。
6. 仍未验证、不要当成已完成：`337bdc4` 的失败让位（尚无 `yield` 行）、普通野怪出征（0 次）、
   所有角色/巡视/事件驱动的下一轮（工作周期机制尚不存在）。

### #64 实施结果与**归因更正**（2026-09-20 21:25，真机）

**已实施**（commit `e8efa2d`）：

1. 五个 `DISMISS_*_GENERIC_REWARD` 与新增的 **goal 中立**技能 `DISMISS_SHARED_REWARD`
   一律改点**页脚退出带** `BTN_DISMISS_INTEL_REWARD`（`roi_norm` x .36 y .90 w .28 h .07，
   落点 **(360,1197)**）。执行器对 `TAP_SEMANTIC` 走 `SemanticWorldVision.find(...).center_norm`
   （`runtime.py:1098`），所以**技能点名哪条记录，落点就是哪儿**。
2. `brain.py` 里"goal 说不清页面"的兜底由 `SAFE_STOP` 改为该技能，绑 `verify_popup_closed` 并已进
   `VERIFIED_ATOMIC`（没有条目 = 永不被调度）。理由是弹窗自己声明「点击任意位置退出」。
   `TRAIN`/`RESEARCH` 原先走的 `CLOSE_POPUP` 也一并换掉——它的目标 `BTN_CLOSE` 在这张弹窗上
   实测 **28 / 门 6**（ROI 在右上空白），本来就是打不中的桥。
3. 两处守卫同提交改完：`tools/check_wiring.py` 三条新检查 + 两个测试文件，`problems: 0`。

**真机已试**（当前轮 `20260920_211101_334048`，跑的就是新代码；该轮 21:11:01 启动，
源码 21:07:42 已落盘，每轮都是新子进程 ⇒ 天然带上工作树）：

```
13:13:12  DISMISS_INTEL_GENERIC_REWARD  target BTN_DISMISS_INTEL_REWARD  SUCCESS  after=INTEL 0.98
13:14:34  DISMISS_INTEL_GENERIC_REWARD  target BTN_DISMISS_INTEL_REWARD  SUCCESS  after=INTEL 0.98
13:16:04  DISMISS_INTEL_GENERIC_REWARD  target BTN_DISMISS_INTEL_REWARD  SUCCESS  after=INTEL 0.98
```

**⚠ 但 #64 原文与补充的归因是错的，此处更正。** 两处都写"`POPUP_GENERIC_REWARD_HEADER`（横幅）
点了无效 / 点它并不能退出"。**第一手帧推翻它**：13:10:26 那一步的 after 帧
（`dataset/truth_audit/reward_popup_exit_20260920/key/03_second_dialog_searchlight_upgrade_20260920T131016.png`）
上，**「获得奖励」已经没有了**，屏幕上是**第二个**弹窗「探照灯升级」。横幅**不是**死按钮。

**真正的主因**（`dataset/truth_audit/reward_popup_exit_20260920/README.md` 第二节）：
`vision.py` 认这张弹窗用的是 **`match(横幅) or match(页脚)`**，而五个解除技能的**动作目标只有横幅**。
两个信号的稳定度差一个量级——六张真机弹窗帧上：

| 语义 | 原始距离（样本） | 自身门 |
|---|---|---|
| 横幅 `POPUP_GENERIC_REWARD_HEADER` | 14 / 16 / 16 / 18 / 20 / 26 | 16 |
| 页脚 `BTN_DISMISS_INTEL_REWARD` | 0 / 2 / 2 / 2 / 2 | 8 |

⇒ 失效链条是纯粹的接线错误：

> 页脚命中 ⇒ 弹窗被认出来 ⇒ 大脑选中解除技能 ⇒ 执行器去解析**横幅** ⇒ 横幅在门外 ⇒
> `SEMANTIC_TARGET_NOT_VERIFIED` ⇒ **一次点击都没发出去**。

`learning/episodes.jsonl` 全史，按**动作目标**分组（`DISMISS_*_GENERIC_REWARD` 全部）：

| 目标 | SUCCESS | FAILURE | 失败中 `SEMANTIC_TARGET_NOT_VERIFIED` |
|---|---:|---:|---:|
| `POPUP_GENERIC_REWARD_HEADER`（旧） | 68 | 51 | **45**（39 MAIL + 4 INTEL + 2 DAILY） |
| `BTN_DISMISS_INTEL_REWARD`（新） | **7** | **0** | 0 |

⇒ 旧目标 51 次失败里 **45 次是"点都没点出去"**，不是"点了没用"。**修法方向对，理由换了**：
不是"横幅是死按钮"，而是**瞄准的信号必须与识别用的信号一致**，且要挑那个有余量的。

⚠ **这不是受控对比**：新目标只有 7 次且集中在最近几分钟；旧目标也成功过 68 次。
⇒ 只能当**方向性证据**，不能当"已修好 #64"的证明。

### 2026-09-20 21:25 新发现（同一批帧）

| # | 问题 | 状态 | 说明 |
|---|---|---|---|
| 65 | **关掉一个奖励弹窗会露出第二个弹窗，而它识别不出 ⇒ 整轮结束** | 🔴 **未修（有帧）** | 13:09:48 `INTEL_CLAIM_REWARDS` → 「获得奖励」；13:09:49 点横幅（`tap [360,326]`）→ 13:10:16 after 帧上是**「探照灯升级」**（页脚写「点击任意位置**继续**」，与「退出」不是同一段字）。该帧 **横幅 26 / 页脚 22**，双双在门外 ⇒ `observe` 报 `UNKNOWN`（conf 0.0）⇒ `verify_intel_reward_dismissed` 要的 `after.page==INTEL` 落空 ⇒ 整轮 `INTEL_REWARD_DISMISS_NOT_PROVEN`。**这才是 13:10:26 失败的真因。** 修法方向：给它**自己的身份**（新增识别记录），**不得**放宽现有两个信号的容差。 |
| 66 | **横幅即使解析成功也不保证关得掉** | 🟠 **观察中（样本 1）** | 12:52:01 那一步：before 帧横幅 **16 = 门**（解析成功、点击真的发出），**+8s 后弹窗仍在**（`key/04_banner_was_tapped_popup_still_there_20260920T125159.png`，页脚「点击任意位置退出」清晰可见）。⇒ 换到页脚不只是换更稳的落点，也是换到弹窗**自己声明的退出面**。 |
| 67 | **在非弹窗页面上跑弹窗技能** | 🟠 **观察中** | `runtime_auto/20260920_120744_012719/…_step_001_before_…` 那一步选中了解除技能，但该帧是**邮件收件箱**（横幅 24 / 页脚 36，两个信号都在门外）。⇒ `observe` 本不该报 `POPUP/GENERIC_REWARD`，选中解除本身可疑。与 #24/#25/#28/#29 的"裁剪覆盖了会变的内容"是**不同**一类（这次是"技能在该页面上本不该被选中"）。未查。 |

**#64 仍未做（不许当成已完成）**：① 原始第 5 条的两个读数（**情报剩余数 / 体力**）仍未取到 ——
本轮 episode 里 `intel {status: AVAILABLE, available_count: 2, detected_pins: 2, untried_pins: 2,
stamina: 585}`（13:04）与 `{status: CLAIMABLE, claimable_count: 1, untried_pins: 1, stamina: 565}`（13:09）
是**运行读数**，按第 5 条的口径**不算**（要停在页面上抓帧后用 `Read` 直接看图）；
② `337bdc4` 的失败让位仍无 `yield` 行；③ 普通野怪出征 0 次。

### #64 第 5 条：两个读数已取到（2026-09-20 21:22，真机帧）

按第 5 条的口径（**停在页面上抓帧 → 用 `Read` 直接看图**，不用运行读数、不用观察存储的旧值）：

**体力**（客户端停在 MAP，帧 `dataset/truth_audit/reward_popup_exit_20260920/readings/map_hud_20260920T132136.png`，帧上时间戳 09-20 21:21:36）：

> 左上角体力表读数 **491**。与同帧 episode 的 `stamina {current: 491, source: MAP_HUD}` 一致。

**情报**（客户端停在情报页，帧 `readings/intel_page_20260920T131907.png`）：

> 页头 **情报**；**下次刷新 02:40:54**；右上角 **513**（运行时把它读作 `intel.stamina`）；
> 左下角等级徽标 **7**，条上 **5/90**；右下角 **02:40:55 后开启**；
> 板上可见 pin 标记 **9 个**（灰狼 1、绿狼 2、绿帐篷 1、蓝帐篷 1、紫交叉剑 1、灰交叉剑 1、紫狼 1 含橙色底光）。

⇒ 体力的路径是通的：本轮 513 → 501 → 491，**确实在消耗**（`EXECUTE_INTEL_RESCUE_SURVIVORS` 12 点、
`INTEL_HERO_DISPATCH` 10 点）。**但 P0 的"体力降到 30 以下"远未达成**，`AVOID_STAMINA_WASTE` 仍未完成。

| # | 问题 | 状态 | 说明 |
|---|---|---|---|
| 68 | **情报 pin 计数只认紫/蓝/橙 —— 灰与绿的 pin 一律不计** | 🔴 **新发现（有帧）** | 项目自身的 `intel_pin_centers`（`vision` 层 `available_count` / `pins` / `untried_pins` 的唯一来源）只用三组 HSV 掩码：`purple 250-330`、`blue 195-250`、`orange 10-55`。在 `readings/intel_page_20260920T131907.png` 上它返回 **4**（blue 1 / purple 2 / orange 1），而板上按图数得出 **9** 个 pin 标记，**差的 5 个全是灰色或绿色**（灰狼、绿狼×2、绿帐篷、灰交叉剑）。⇒ 只要那 5 个也是可打的情报任务，Agent 眼中的"剩余情报"就**只有实际的一半**，`intel_no_untried_pins` / `pins>0` 这类判定会在还有任务时判"没得打"。**未查清的是**：那些灰/绿 pin 是不是真任务（可能表示已试/已领）。**下一步**：点一个灰或绿的 pin，看是否开出任务卡；不要靠猜颜色。**不得**用放宽 `min_area` 之类的方式"修"这个方法。 |

**群体计数（补，65 张真机 before 帧）**：最近 5 个 AUTO 轮次里，
页脚「点击任意位置**退出**」（共用奖励弹窗）命中 **7** 帧，「点击任意位置**继续**」（#65 的探照灯升级）命中 **1** 帧；
同一窗口 episode 里新目标解除动作 **7 次全过（7/7）** ⇒ **这 5 轮里每一张奖励弹窗都被新落点解析、点击并通过验证**，
且与群体计数对得上。⇒ #64 的"落点"这一半可以算**真机验证通过**；
"关掉之后底下露出什么"那一半是 #65，仍开着。#65 目前只有 1 个实例（跨两轮），不够注册模板的 3 个正样本门槛。

**全量套件结论（2026-09-20 21:48，`tools/run_tests_batched.py --batches 8 --timeout 900`）**：
`batches 8 | 1977 passed, 9 failed, 7 skipped, 0 error`，`no verdict: none`；
`VERDICT: INCOMPLETE` 是运行器的字面意思（batches 1/4/7 有红），**不是"没有结论"**。
**红的 9 条与 #63 重建的基线逐条相同**（camp_panel_stamina ×2、evidence_integrity ×1、
live_runtime ×1、capability_gate ×3、march_formation_attribution ×2）⇒ **本次改动没有引入新失败**；
通过数 1973 → **1977**（+4 = 新加/改写的测试）。两处口径说明：① batch1 跑的时候本轮的测试文件
还在改，故其结论不足以代表最终内容；最终内容单独跑过 `24 passed / 27 subtests`。
② 运行期间面板 AUTO 在跑，`test_live_runtime.py` / `test_camp_panel_stamina.py` 会读
`knowledge/**` 与 `config/policy_state.json`，#63 已记它们的失败集合随工作树数据变化。

### #68 已修（2026-09-20，真机语料 435 帧）

**诊断**：`intel_pin_centers` 的三组掩码（purple/blue/orange）是**检测器能看见的东西**，不是**板面画的东西**。
在 `readings/intel_page_20260920T131907.png` 上逐块裁图核对：漏掉的 5 个标记与已计数的**是同一类物体**
（水滴本体 + 白色头部图标 + 橙色底环），只有本体颜色不同 —— **2 个绿、2 个灰**
（第 5 个 (508,410) 距 (541,399) 仅 35 px，被检测器自己的 45 px 邻域规则并成同一个 pin）。

**修法（`winter_agent_v2/intel_pins.py`）**：

1. 新增 **GREEN** 掩码（`hue 70-170 / sat≥90 / val≥90`）。语料上 **153 帧**新增 pin，
   2026-09-20 的 **40/40 帧**全有；新增 blob 几何 w 51–67 / h 73–77，与已知 pin 一致，**无标题类假阳性**。
2. 新增 **中性（灰/银）掩码**（无色调，只按 sat≤60 与 val 60–215 门）。
3. 新增**宽度上界 `max_width=130`**：真 pin 实测 w 51–107，页标题「情报」w 165–166（60 帧里 53 帧误报，全部是它）。
4. 新增**中性类专属位置下界 `BOARD_TOP=200`**：语料里真实 pin 的 tap 点**最小 y=261**（PURPLE 354,261），
   而中性假阳性是页标题（y 73–85）与左上 HUD（y 38–57，**23/435 帧**）。
   **下界只作用于中性类**——加到所有颜色会冒着把上移板面的真彩色 pin 顶掉的风险，那正是本 issue 要防的漏计。

**四条判据的实测淘汰过程**（写下来免得重做）：饱和度上界 50/40/30/25 都留标题（或换成中性地形）、
20 连真 pin 一起去掉；橙色底环丢掉两个真灰 pin 中的一个（灰斑的垂直范围伸过自己的环）。
⇒ **只有宽度与位置能分离**。

**全语料复验（435 帧情报帧，新旧并跑）**：

| | 旧 | 新 |
|---|---:|---:|
| 读成 **0 个 pin** 的帧（⇒ `goal_library` 判 `CLEAR_INTEL=COMPLETE`） | **1** | **0** |
| 板外（y<200 或 x>690）录取 = 假阳性 | 0 | **0** |
| 找回的绿/灰 pin 次数 | — | **397 绿 + 247 灰** |

**测试**：`tests/test_intel_pin_board.py` 新增 `ColourCoverageTests`（3 条，用**已发布**的证据帧，
不依赖本机语料，也不 skip）。单帧代价 0.27s → **0.6s**（中性掩码的连通域更大），仍在步骤预算内。

**仍开着**：`intel_board_corpus/` 那 435 帧只在**本机**（388 MB，未发布）⇒ 群体数字可由同三个探针在任意情报帧重算，
但**换台机器要重算群体就得自己再收帧**。另：`readings/` 与 `key/` 已白名单，语料没有。

| # | 问题 | 状态 | 说明 |
|---|---|---|---|
| 69 | **操作者的体力顺序在代码里写了两遍，其中一遍没有任何调用者** | 🟠 **已定性，未修** | `knowledge/strategy/operations_priority.json` 的 `rules.stamina.order = [INTEL, GIANT_BEAST, BEAST_HUNT]`（threshold 30）在代码里被实现**两次**：① `operations_policy.choose_stamina_goal()` —— **grep 全仓无生产调用者**，只有 `tests/test_operations_policy.py`；② `runtime.py:876` 的内联 route 映射（`AVOID_STAMINA_WASTE → BEAST_HUNT`，gate 报 `SPEND_STAMINA_ON_BEAST ∈ {BLOCKED,COOLDOWN,DEFERRED,DEVELOPMENT_PENDING}` 时改走 `SPEND_STAMINA`）。**生效的是 ②**；`scheduler.py:90` 的 `operational_priority` 给三个耗体力 goal 加权也是真接线的。⇒ **不构成第二套调度**（① 从不执行），但**改一处不会改另一处**，属真接入缺口。同文件里 `choose_troop_rotation` / `choose_shield` / `choose_healing` / `reward_candidates` 同样无调用者。 |
| 70 | **体力路线的实测成本表与性价比结论** | 🟢 **已落盘** | 见 `knowledge/strategy/stamina_routes.json`（`knowledge/game/_index.json` 已登记）。要点：**采集实测 0 体力（54/54）**；情报三路 10/10/12；**世界地图打野显示 10、实际 7 —— 是所有路里最便宜的**；每次成功的体力 = 消耗 ÷ 真机成功率 ⇒ 打野 **11.3**（88.9%/54 次）< 英雄之旅 **14.7**（68%/25 次）< 营救幸存者 **22.5**（53.3%/15 次）。**但冰原巨兽未实现（`START_RALLY`/`JOIN_RALLY` 未进 `VERIFIED_ATOMIC`，永不调度），打野被识别层卡死（#41/#46）** ⇒ 「做完情报再用剩余体力去打野」今天**落不了地**，先修打野识别才是唯一路径。**未算奖励量级**，所以"性价比"目前只按体力算，别当已证。 |

**#68 闭环：真机已经发生过一次「假空板」（同一会话回查发现）**。`learning/episodes.jsonl` 里：

```
2026-09-20T14:03:18Z  OPEN_INTEL  SUCCESS
  after.intel = {"status": "NOT_AVAILABLE", "available_count": 0, "list_read": true}
```

`NOT_AVAILABLE` ⇒ `goal_library` 判 `CLEAR_INTEL = COMPLETE`。该帧（已归档
`key/06_live_frame_read_as_zero_pins_20260920T140309.png`，已白名单发布）上
**旧判据 0 个 pin / 新判据 5 个 pin（4 绿 + 1 灰）** —— 满板被读成空板，5 个任务全是旧掩码看不见的颜色。
⇒ 这不是"少算几个"，是**差一步就把情报路线判成完成**。守卫：
`tests/test_intel_pin_board.py::ColourCoverageTests::test_the_live_frame_that_read_as_empty_is_not_empty`。
**仍未做**：这一帧是修好之后**回查**出来的，不是修好之后**真机复跑**验证的；
下一轮 AUTO 走到情报页时会用新检测器读数，届时 `intel.pins` 应显著大于历史同板读数。

### 2026-09-20 通用 UI 语义盘点（操作者要求的一次性许可）

**做法**：不新建第二套视觉/调度/执行。先把三份既有事实交叉盘点（`dataset/candidate/template_manifest.json`
403 条模板 / 230 个语义、`winter_agent_v2/skills.py` 95 个技能、`LiveRuntime.VERIFIED_ATOMIC` 79 条绑定），
再用**真机截图语料**给"通用语义"找证据，最后只补被量出来的缺口。

**语料**：`dataset/truth_audit/ui_semantics_corpus/` —— 244 帧，**页面标签由生产自己打的**
（`learning/episodes.jsonl` 的 `state_before/state_after.page`，conf≥0.9），14 个页面各 20 帧。
工具：`tools/ui_semantic_evidence.py`（全帧 OCR，产物 `knowledge/ui/semantic_evidence.json`）。

**盘点数字**：

| 项 | 数量 |
|---|---:|
| 模板清单语义 / 记录 | 230 / 403 |
| 技能 / 已绑 verifier | 95 / 79 |
| 被技能点名的语义 | 71（59 有模板，12 走派生解析器） |
| 模板没被任何技能使用（识别专用：页面身份/状态标记） | 171 |
| **一个视觉语义被 ≥2 个技能共用** | **3** |
| 语义词典候选 | 96 |
| ├ 有视觉/模板证据 | **57** |
| └ **纯候选，无任何视觉证据** | **39** |
| 候选在 244 帧真机语料上被 OCR 确认可见 | **45** |
| **客户端确实显示、但词典没命名的跨页字符串（≥2 页）** | **133** |

**"一按钮多含义"的既有三例**（正是操作者要的复用形态，靠 goal/页面上下文区分，不靠新系统）：

| 视觉语义 | 被哪些技能共用 |
|---|---|
| `BTN_DISMISS_INTEL_REWARD`（页脚「点击任意位置退出」） | **7 个**：`DISMISS_INTEL_REWARD` + 五个域解除 + `DISMISS_SHARED_REWARD` |
| `BTN_INTEL_VIEW_TARGET`（情报卡「前往查看」） | 3 个：救援 / 英雄之旅 / 野兽任务 |
| `BTN_BEAST_START_MARCH`（「出征」） | 2 个：`BEAST_HUNT`（世界地图打野）与 `INTEL_BEAST_START_MARCH`（情报任务） |

**客户端盲区里最有语义价值的**（词典没命名，但真机反复出现）：
底部导航 `商店`/`背包`/`超值活动`/`登录好礼`/`漫游剧场`（4–6 页）、`奖励`（4 页）、
`前往`（4 页）、`未驻防`（5 页）、计数器 `2/6`（3 页）、`仅搜索资源为满的资源点`（2 页）。

**⚠ 一条"不要做"的结论（有数字）**：`前往` 出现在 4 个页面上，但它指向哪儿由**所属任务卡**决定。
把它做成一个通用可点语义会直接违反"不要仅凭模糊文字/相似背景执行点击"——项目现在就是**按页+对象作用域**
处理的（`BTN_INTEL_VIEW_TARGET` 等各自绑定）。**不要**把 `前往` 合并成一个通用按钮。

| # | 问题 | 状态 | 说明 |
|---|---|---|---|
| 71 | **`RESEARCH` 可被调度，但它的按钮不在它要求的那一页上** | 🔴 **新发现（有帧）** | 新守卫（`tools/check_wiring.py`）把"可调度技能点名了视觉层解析不出来的目标"钉成了精确集合，全仓只有一条：`RESEARCH -> BTN_START_RESEARCH`。**原因不是缺裁剪**：科技研究路线落到的是**科技树**（`dataset/truth_audit/ui_semantics_corpus/RESEARCH__01__live_runtime_step_001_after_*.png`：发展/经济/战斗 三个页签 + 带 `1/3` 徽标的节点，**整页没有「研究」按钮**）。该按钮**只在选中某个科技之后才出现**，而路线里**没有"选节点"这一步**。⇒ 补的不是模板，是**缺一个环节**。真机旁证：`RESEARCH` 全史只跑过 1 次，且被 `QUEUE_BUSY` 挡在门口（环境条件），所以这个缺口**今天还没暴露**，队列一空就会暴露。**未修**（不在操作者本次要求的前四个验证目标内）。 |

**#68 真机复验完成**：修复 22:20 落盘 → 22:41:39 那一轮走到情报页，生产记录
`{"status": "AVAILABLE", "available_count": 3, "pins": 3}`；同一帧
（`key/07_live_after_fix_pins3_20260920T144139.png`）**旧判据 0 / 新判据 3**（2 绿 + 1 灰），
**生产记录的 3 与新判据一致** ⇒ 跑的就是新检测器。修好前（14:03:18Z）满板读成 0，修好后读成 3。
⇒ 这一条从「回查」升级为「真机复跑验证」。

**未完成的一条（有意停手）**：`pages_by_template`（每个语义在多少个页面上被**模板**命中）这一列仍是 UNKNOWN。
`.probe_semantic_reuse.py` 跑 230 语义 × 244 帧要 ~1 小时（`phash` 是纯 Python，瓶颈在它），
而**操作者明确要求本次开发不得阻塞正式 AUTO**，同一个盒子上跑一小时 CPU 重活与实机循环争资源 ⇒ **主动停掉**。
台账里这一列已经**按名字留着**而不是合并进 OCR 那一列，说明它是"没测"不是"没这回事"。
要补它：把语料缩到每页 10 帧、或只扫被技能点名的 71 个语义（约 2.5 倍加速），在一个 AUTO 空闲的时段跑。

## P0 2026-09-20（操作者）：情报已清完 → 转入剩余体力消耗

### 阻塞点的真实结构（都不是"路线没写"）

用项目自己的 API 读当前判定（不是读日志猜）：

```
CapabilityGate.load('.').blocks(...)
  CLEAR_INTEL         -> DEFERRED / READ_INTEL_LIST   "3 consecutive episodes passed their verifier
                                                        and advanced no part of this goal"
  AVOID_STAMINA_WASTE -> DEVELOPMENT_PENDING / SPEND_STAMINA_ON_BEAST   job=17f1c743
```

**阻塞 1（P0 真凶）**：作业 `17f1c743`（`SPEND_STAMINA_ON_BEAST|NO_GOAL_PROGRESS|SELECT_INTEL_PIN`，
14:39:05Z 提交）挂着 `WORKING`，但 `detail = {"summary": "Idle background coding session with no task"}`
——**15 分钟里什么都没做**，而它：
- 把 `SPEND_STAMINA_ON_BEAST` 钉在 `DEVELOPMENT_PENDING` ⇒ `AVOID_STAMINA_WASTE` **永不入调度**；
- 占住唯一并发槽 ⇒ 面板日志里**另外 5 个升级全部 `CONCURRENCY_WAIT`**。

实测它的进度钟：`b.status('17f1c743').progress_at` ⇒ **已冻结 34.6 分钟**（阈值 20）。
⇒ 项目自带的规则（`escalation_queue._cancel_over_timebox`：超 45 分钟 **且** 进度钟冻结）会在
**15:24:05Z** 自动取消它并释放槽位，**不需要手工改状态**。⏳ 待观察确认。

**阻塞 2**：情报这一轮的真相比"已清完"更精确 —— 板上还剩 **1 个 pin**，而它开出的是
`BLOCKED / MASTER_BOUNTY / level 20`（`INTEL_MASTER_BOUNTY_20`，recommended_power 189,295,920
对本角色 ~1.6M）。`untried_pins: 1` 的含义是"本轮还没点过"，**不是"打得过"**；pin 在任务被消耗后
**不会消失**，所以它会被反复算作"还有情报"，而 `goal_progress` 恒为 false。
⇒ 已写入 `knowledge/game/intel.json` 的 `round_state`（`ROUND_CLEARED_AWAITING_REFRESH`，
含下次刷新 ~2026-09-21 00:00 GMT+8）。**有界性已实测**：该推迟走 `no_progress_probe_minutes=30`
的探测窗，模拟时间前进 5 分钟即返回可调度 ⇒ **不是永久标完成**，无需改代码。

**阻塞 3（本次修掉的）**：`SCAN_MAP_FOR_BEAST` 是一个没有收敛条件的视野平移（全史 420 次，
`goal_progress` 恒 false），而真正能到目标的两种手段**都是逐物种的**：两个精灵模板
（麝牛9 / 猛犸象5）。项目自己的失败模式文件 `BOUNDED_SCAN_THAT_NEVER_CONVERGES.md` 早已写明
规则 3：「客户端已经提供的导航（搜索/前往）优先于自家手势摸索」，并记着"野兽搜索这条 hop 没有接线"。

### 患者帧（`dataset/truth_audit/beast_labelled_selection_20260920/`）

`stamina_verify2_step_001_before_20260919T144336706139.png` 上，**客户端在地图上的野兽旁边
印着名字**：`named_beast_label → 霜鳞避役`（conf 0.89）、`level_beside_label → 20`（conf 1.00）、
`lookup_by_name → FROST_SCALED_RUNNER_20` 命中 —— **然后 `is_dispatchable → False`**
（该行 `dispatchable: false` / `UNVERIFIED`，上一版作者刻意留的硬闸，理由是"未测量的物种不能花体力"）。

⇒ **识别链从头到尾没问题，卡的是一道手写的逐物种预批准开关。** 这正是操作者说的
"不要只针对某个物种，要通用，只要打得过就可以打"。

### 实施（commit 见下）

1. `beast_targets.py`：判定从**逐物种预批准**换成**客户端自己的判定**，同一个模块回答两个问题——
   `may_evaluate`（能不能点，开卡不花体力，身份够了就行）与
   `is_dispatchable`（能不能花体力：要帧上有客户端印的 `本次出征胜券在握`，或该行本就预批准）。
   **实测拒绝**（雪豹29 的红判定 + `BLOCKED_BEFORE_DISPATCH`）成为唯一无需帧即可拒绝的东西，
   ⇒ 比改前**更严**（连点都不点）。
2. `ocr.beast_from_its_label`：改为在**可评估**时发布身份，并带上**实测落点** `tap_norm`
   （名字标签框中心映射回整帧；该帧 = (193,838) = (0.2687,0.6551)，标签画在兽体上）。
   没有帧尺寸时**不给坐标**，而不是编一个。
3. `skills.py` + `runtime.py`：新增 `SELECT_BEAST_TARGET_LABELLED`（`TAP_SEMANTIC: BEAST_ON_MAP`，
   动态解析，带页面守卫防陈旧坐标），绑 `verify_beast_card_opened` 并进 `VERIFIED_ATOMIC`；
   技能→能力映射登记进 `knowledge/goals/capability_skill_map.json`。
4. `verifier.py`：新增 `verify_beast_card_opened`（证明**目标**卡开了，而非动作发生）；
   `verify_beast_dispatch` 的 `target.dispatchable` 改为 `not target.refused`（客户端绿条仍是硬要求）。
5. `brain.py`：BEAST_HUNT 在盲扫**之前**接上该跳，并重置平移预算。
6. 守卫：`check_wiring` 新增 8 条（注册/绑定/路由/预算/三条安全线/musk-ox 不回归/执行器解析）。
   ⚠ 第一次跑时报出 3 条 MISS —— 其中一条是**我自己加的 #71 检查**把新动态目标认了出来
   （已把 `BEAST_ON_MAP` 加进派生解析器清单），另两条是真缺口（能力映射、拼写）。
   ⇒ `problems: 0`。

### ⚠ 尚未验证（不许当已完成）

- 上面全部是**离线在真机帧上**跑出来的。**真机出征 0 次**：链路的后半段
  （点标签 → 开卡 → 攻击 → 阵型页 → 出征 → verifier）**必须等 AUTO 下一轮走到地图页**，
  且要等 `SPEND_STAMINA_ON_BEAST` 的门禁被释放之后才可能发生。
- "点 nameplate 能开卡"这一条**本目录没有帧**，只有真机会说话。
- 因此本 issue 的状态是 **CANDIDATE，不是 LIVE_VERIFIED**。

**⚠ 重大更正（2026-09-20T16:10:04Z 真机 1 次尝试，rev `82cdf49`）**：`霜鳞避役` 的卡面是
**`等级7 霜鳞避役` · 推荐实力 683,100,000 · `[集结]` 25** ⇒ **它是集结目标（冰原巨兽一类），不是普通野兽**。
那次尝试的读数：

```
before  MAP  beast={label_text:霜鳞避役, level:20, source:BEAST_LABEL, tap_norm:[0.5181,0.7778]}
action  TAP_SEMANTIC BEAST_ON_MAP
after   MAP  beast={label_text:等级7霜鳞避役, tap_norm:[0.5021,0.3946]}     ← 卡面已开
result  FAILURE / BEAST_TARGET_SELECTION_NOT_PROVEN
```

⇒ **一半成、一半败**：① 标签读数在真机上有效（conf 0.875，落点与整帧 OCR 位置一致）；
② **点击真的发出且卡面真的开了**（这是这一跳的 LIVE 证据）；③ **但目标类别错了** ——
开出来的是 rally 卡，普通打野链（要 `BTN_BEAST_CARD_ATTACK`）消费不了它，
所以**验证器那个 ERROR 是判对了**。

**新增未修缺口**：

| # | 问题 | 状态 | 说明 |
|---|---|---|---|
| 72 | **地图上"站着且印名字"的兽可能是集结目标，名字无法区分类别** | 🔴 **未修（有帧）** | 需要按**卡面自己画的控件**（`攻击` vs `集结`）分类，或改走操作者指的那条路：**搜索面板的 `野兽` 页签按等级搜**（`dataset/raw/beast_search_exploration/beast5_found.png` 人肉验证过；项目失败模式文件 `BOUNDED_SCAN_THAT_NEVER_CONVERGES.md` 规则 3 也写了"客户端自带的导航优先"）。两条都不该无真机校准就凭猜实现。**同时**：`START_RALLY`/`JOIN_RALLY` 仍无 `VERIFIED_ATOMIC` 条目 ⇒ 即使认出来是集结目标也无处派发。 |

## 2026-09-21 导航与快捷入口全面发现（操作者一次性许可）

**做法**：不建第二套导航。先派生（`tools/ui_navigation_matrix.py` → `knowledge/ui/navigation_matrix.json`），
再在真机帧上量缺口。**产物是投影，不是手写表**：96 技能 / 80 可调度 / 40 个导航类入口 / 38 可调度 /
230 个有模板的语义 / **171 个有模板但没有任何技能点名的语义**。

**操作者清单逐条核对（脚本可复跑）**：

| 功能 | 可调度入口 | 有模板语义 | 有模板无技能 |
|---|---:|---:|---:|
| 城镇/野外快捷面板 | 4 | 7 | 3 |
| 兵营/盾兵-矛兵-射手 | 3 | 20 | **17** |
| 科技研究 | 2 | 11 | 9 |
| **联盟捐献** | **0** | 13 | 12 |
| 情报/灯塔 | 18 | 31 | 23 |
| 地图搜索栏 | 4 | 6 | 4 |
| **巨兽/自动加入** | **0** | **0** | **0** |
| 采集点/资源详情 | 1 | 9 | 7 |
| 回城/返回 | 2 | 7 | 5 |
| 邮件 | 6 | 13 | 7 |
| 活动/限时提醒 | 4 | 23 | 18 |
| 体力HUD | 2 | 3 | 2 |

### ⚠ 三个重要更正 / 新发现（都有真机帧）

| # | 问题 | 状态 | 说明 |
|---|---|---|---|
| 73 | **"城镇快捷面板"被认错了**：路线用的 `OPEN_POWER_OVERVIEW → BTN_OPEN_POWER_DETAILS → 提升` 实际打开的是 **`加成总览`**（`部队/建筑/科技/领主装备/英雄实力` + 战绩，各带数值）再进 **`实力详情`**（五行进度条 + `提升` 按钮）。**这是属性统计链**，不等于操作者描述的"显示进度/倒计时/可用次数、带城镇-野外标签的快捷功能面板" | 🔴 **未找到（有帧）** | 帧：`runtime_auto/20260921_001508_805754/…_step_003_before`（加成总览）、`…_step_004_before`（实力详情）。⇒ 操作者那个面板**项目里零记录**，需要真机发现。**注意**：这不影响现有两条路线的可用性（它们确实能到兵营/研究所），只是"快捷面板"这个名字指向的东西不同。 |
| 74 | **训练路线被一个教学手指卡了 3.25 天，而"手指是遮挡"这个理由被证伪** | 🟠 **已定性，未修** | `KEEP_TRAINING_PRODUCTIVE` 共 127 步，其中 `WAIT_FOR_CAMP_MENU` **45 步（35%）**、`OPEN_POWER_OVERVIEW`+`OPEN_POWER_DETAILS` 33 步，而**真正到训练页只有 4 次**。代码注释与 `verify_camp_menu_reobserved` 都写"手指压着兵营、点了会跳地图"（依据是 **2026-09-17 唯一一次尝试**）。**但证伪**：`dataset/raw/control_panel/runtime_auto/20260920_093256_036374/…_step_005_before` 显示**手指在且菜单正常开着**（`16 盾兵营` + 径向菜单 `详情/立即完成/加速/训练`，手指此时指向 `训练`）⇒ **手指是引导，不是遮挡**。真正的差别是**状态不同**：stage A＝金环亮、菜单未画（`TARGET_INFANTRY_CAMP_HIGHLIGHTED` d=2 命中）；菜单态＝`BUILDING_INFANTRY_CAMP` d=8 命中。两者落点都在 (340,690)。⇒ 待真机判定的问题只有一个：**stage A 该点哪里**（环中心已试过→跳地图；手指尖下的兵营图标在 ≈(350,545)，比模板中心**高 137 px**，从未试过）。**不猜**，故本轮不改落点。 |
| 75 | **快捷面板的内容完全没读进 WorldState** | 🔴 **未修（已量）** | 在 `POWER_DETAILS` 帧上 `observe` 返回 `training={}`、`research={}` ⇒ 操作者 §四 要的"先用快捷面板读可靠状态再决定是否进详情页"**今天做不到**，因为面板内容根本没被读。面板上确有可读数字（`528,255/801,036`、`良好/普通/平庸`）与 `提升` 控件。 |
| 76 | **同一个面板被两个目标复用（正面证据）** | 🟢 **已确认真机** | `16:05:11 NAVIGATE_INFANTRY_CAMP`（训练目标用 `部队实力→提升`）与 `16:15:55 NAVIGATE_RESEARCH_LAB`（科研目标用 `科技实力→提升`）**走的是同一条面板链**，两条都 SUCCESS。⇒ 复用已经在发生，不需要新建入口。 |
| 77 | **底部导航六个入口全部真机可见，但只有 3 个有模板、2 个有技能** | 🟠 **已定性** | 帧：`runtime_auto/20260921_000413_168533/…_step_004_after`（`探险/英雄/背包/商店/联盟/野外`）。`OPEN_EXPLORATION`/`OPEN_ALLIANCE`/`OPEN_MAP` 可用；**背包/商店/英雄无入口技能**（用户列为"应有"，未验证）。 |
| 78 | **右侧活动/邮件快捷入口真机可见且密集** | 🟠 **仅记录** | 同帧右侧有 `生存者试炼 / 常规活动 / 明月的盛典 / 超值活动 / 漫游剧场 / 首充 / 玉镶礼包 / 7日签到` 八个入口 + 右下 `邮件/设置`。项目只覆盖 `OPEN_MAIL` 与 `OPEN_DAILY`；其余**零语义**。用户列的"限时任务主界面提醒入口"同理：帧上有 `通关探险第80关 (0/1)` 任务卡，**零语义**。 |
| 79 | **`巨兽/自动加入` 完全未记录** | 🔴 **未修** | 用户列出的"巨兽搜索栏存在自动加入按钮"在 manifest 与词典里**命中 0**（`GIANT_BEAST|RALLY|AUTO_JOIN|JOIN_` 全无）。`knowledge/ui/pages.json` 有 `GIANT_BEAST` 页但没有任何模板/技能。 |

## 2026-09-21 训练 Stage A（#74 结案，并解开 09-17 以来的悬案）

### #74 已修：不是手指遮挡，是落点在环外的空地上

`KEEP_TRAINING_PRODUCTIVE` 全史 127 步里 **45 步（35%）在 `WAIT_FOR_CAMP_MENU`**，
真正到训练页 4 次。代码给的"不点"理由是**教学手指压着兵营、点了跳地图**（依据 09-17 唯一一次尝试）。

**46 帧真机 stage A 语料（5 个独立时段）实测**：

| 量 | 范围 | 说明 |
|---|---|---|
| **模板落点** | **(346, 682)** | **46/46 帧完全相同** |
| 金环中心 | x 305–319, y 577–597（sd 4.3/4.0） | 极稳 |
| 环内白色兵营图标 | x 333–352, y 541–552 | **教学手指的指尖正指着它** |

⇒ 环的 y 范围约 520–645，**落点 y=682 低于环下沿 37 px** ⇒ 落在**建筑之间的空地** ⇒ 客户端当**地图点击**。
⇒ **手指从未覆盖那个点**（它覆盖的是环，而环本身就是要交互的选中标记）。

### ⭐ 判别器：环的尺寸（项目找了 4 天的东西）

`tests/test_training_verifier.py::test_the_camp_highlight_signal_cannot_tell_the_two_states_apart`
的依据是这对人工验证帧：

| 帧 | 人工点击 | 模板距离 | **金环 bbox** |
|---|---|---|---|
| `camp_with_gold_ring__click_opens_menu__20260908` | ✅ 开菜单 | 0.0 | **205 × 112** |
| `camp_with_officer_badge__click_jumps_to_map__20260917` | ❌ 跳地图 | **8.0（正好压在门上）** | **7 × 15**（徽章边缘碎片） |

⇒ 旧结论"信号区分不了两态"**量错了东西**：它量的是**模板距离**（分不开），
而**环的尺寸**把两态分开**两个数量级**。09-17 那帧**根本没有环**。

### 落地

`winter_agent_v2/camp_ring.py`（新）：在**匹配到的模板自己的 ROI** 内检测金环
（ROI 由调用方给 ⇒ **无写死坐标**；第一版全帧找金色时返回了右侧活动栏的金色装饰，故必须加窗）；
**最小尺寸判据**（真环 0.28×0.088 vs 碎片 0.0097×0.012）；读不出 ⇒ **None，不兜底** ⇒ 路线等待。

接入：`vision.py` 写 `training["camp_tap_norm"]` → `runtime.py` 派生解析器 `TRAINING_CAMP_IN_RING`
（带 HOME 页守卫防陈旧坐标）→ `skills.py` 把 `SELECT_INFANTRY_CAMP` 的目标改为它（**识别与点击分离**）
→ `brain.py` stage A **先点一次**（一次性标志）再走原有 2 次等待与让位。verifier 不变
（`verify_infantry_camp_selected` 要求 `menu_open`）。

**离线验证**：46 帧 **46/46** 零退化；**开菜单帧给出落点 (317,583)**、
**跳地图帧被拒（None）**；决策序列 `SELECT_INFANTRY_CAMP → WAIT → WAIT → SAFE_STOP` 有界；
无 `camp_tap_norm` 时**不点**。守卫新增 6 条，`problems: 0`；训练相关 28 条测试全过。

### ⚠ 未验证

**点环心是否真开菜单，真机未验证。** 现有：① 点环外空地实测跳地图（09-17）；
② 09-08 的人工记录**不能当对照** —— 该帧几何与 09-17 **相同**（tap 到环心 102 vs 103 px），
它"成功"很可能是按顺序推断而非实测。真正差别是**环存在与否**。⇒ 状态 **CANDIDATE**。

| # | 问题 | 状态 | 说明 |
|---|---|---|---|
| 80 | **`ALLIANCE`/`ALLIANCE_ROUTINE` 之外，联盟页的状态读不出** | 🟠 **已定性** | 历史分布：`section=GIFTS status=CLAIMABLE` 57 次、**`section=HOME status=UNKNOWN` 56 次**、`GIFTS/UNKNOWN` 14、`TECHNOLOGY status=None` 6。brain 的 GIFTS 分支要求 `status=="CLAIMABLE"`、TECHNOLOGY 要求 `=="AVAILABLE"` ⇒ **字段缺失时全部失效**。而联盟首页真机上明明画着 **`联盟科技` 带 25 角标、`联盟互助` 带 6 角标、`联盟商店` 红点**（帧 `runtime_auto/20260921_002526_807831/…_step_003_before`）。⇒ 需要把首页角标读进 `world.alliance`。**未修**（本轮先修了它导致的整轮停机，见下）。 |
| 81 | **`ALLIANCE_TECH_CONTRIBUTE` / `ALLIANCE_HELP` 无 verifier ⇒ 永不调度** | 🔴 **未修** | 两者都是 `SkillState.CANDIDATE` 且不在 `VERIFIED_ATOMIC`。模板**存在且能匹配**（`BTN_ALLIANCE_TECH` d=0 @ (533,936)、`BTN_ALLIANCE_HELP` d=2 @ (189,1071)）。⇒ 补 verifier 即可（各自证明"捐献计数增加"/"帮助计数减少"），但需要真机读数支撑。 |

**全量套件结论（2026-09-21 01:16，`tools/run_tests_batched.py --batches 8 --timeout 900`）**：
`batches 8 | 2023 passed, 8 failed, 7 skipped, 0 error`，`no verdict: none`；
`VERDICT: INCOMPLETE -- failed: ['batch2','batch5','batch8']` 是运行器的字面意思（不是每批都绿），
**不是"没有结论"**。

**8 条红的逐条都在 #63 基线集合内**：`camp_panel_stamina` ×2、`capability_gate` ×3、
`evidence_integrity` ×1、`march_formation_attribution` ×2。
基线是 9 条（另含 `live_runtime` ×1），本轮少的那条是 **#31 已记录的顺序相关不稳定项**。
⇒ **本轮（联盟页让位 `ecb0014` + 训练 Stage A `6dbc609`）没有引入任何新失败**；
通过数 **1977 → 2023（+46）**，失败数 **9 → 8**。

两点口径说明（与 #63 相同）：① 运行期间面板 AUTO 在跑，`test_live_runtime.py` /
`test_camp_panel_stamina.py` 会读 `knowledge/**` 与 `config/policy_state.json`，
它们的失败集合随工作树数据变化；② `test_march_formation_attribution.py` 的两条也是既有基线。

**补：#74 的诊断有三次真机失败支撑（不是推理）**。回查发现 `SELECT_INFANTRY_CAMP` **全史只触发 2 次**
（都在修复前、都用旧目标）：

| 真机尝试 | 当时落点 | 结果 | 新检测器同帧给的点 |
|---|---|---|---|
| 2026-09-17T04:42:03Z | (346,682) | `FAILURE / INFANTRY_CAMP_MENU_NOT_PROVEN` | (309,586)（103 px 外，环内） |
| 2026-09-17T09:46:29Z | (346,682) | 同上 | (314,584)（103 px 外，环内） |
| 2026-09-17（跳地图） | (346,682) | 跳到 MAP | 无环 ⇒ 拒绝 |

⇒ 三次落点**完全相同** ⇒ 模板的系统性偏移；**环外无效**有了三次独立印证。
**但环内是否有效仍未验证**；09:46:29 那帧**有完整环** ⇒ 新代码会点 (314,584) ⇒ 这是下一轮可验证的场景。
另：verifier 三次都正确报 `INFANTRY_CAMP_MENU_NOT_PROVEN` ⇒ **验证器层可信，没有误报成功**。

### ⚠ 训练 Stage A 真机验证**失败**（2026-09-20T18:43:51Z）——已回退点击

修复上线后真机跑了 1 次该跳：`repo_rev 2f616406`（含修复）、`TAP_SEMANTIC: TRAINING_CAMP_IN_RING`、
`before.training.camp_tap_norm=[0.441,0.4551]`=**(317,583) 环中心**、`action_backend=ADB`（**点击真的发出**）、
结果 **`FAILURE / INFANTRY_CAMP_MENU_NOT_PROVEN`**、`after.page=HOME`、**`after.training={}`**。
after 帧（`key/09_*`）显示：**菜单没出现，金色高亮环消失**（点击被当成"点空"）。

**⇒ stage A 四次真机点击、四次失败**：三次环外 (346,682)（两次菜单没开、一次跳地图）+ **一次环内 (317,583)**。
**"瞄得更准"不是答案** ⇒ `brain.py` **撤回该点击、回到等待**，保留 `camp_ring.py` 与 `camp_tap_norm`
（环的测量可靠：46/46 帧、sd 4px）。守卫改为钉住"撤回"，测试相应更新；`problems: 0`，29 条训练测试全过。

**环内的真相（`key/10_*` 标注图）**：环内有 **5 个亮色块**，我点的 (317,583) 紧邻其中最小的一个（60px）；
而**教学手指的指尖指向环右侧那个带 `2` 角标的图标**（测得 **(379,592)**，98px、12×15）。
⇒ 那块**可以被测出来**，但"5 选 1"**没有客观唯一判据**，故**未据此再改落点**。

| # | 问题 | 状态 | 说明 |
|---|---|---|---|
| 82 | **stage A 那个"金色椭圆 + 教学手指 + `2` 角标"到底是什么状态？** | 🔴 **未决（有帧）** | **假设（非结论）**：它不是"兵营被选中"的**圆形**选中框，而是**椭圆**（rx=102, ry=56）画在一个**大型多部件建筑**上、带 `2` 角标、且有教学手指指着角标 ⇒ 更像**引导式步骤**。**若成立**，`verify_infantry_camp_highlighted` 接受这一帧就是**假到达**，训练路线前半段一直在报**从未获得的成功**。**可判定的下一步**（不需盲点坐标）：① 在 stage A 帧上 OCR 环内/附近建筑名，与 `knowledge/game/buildings.json`（13 条，含 `INFANTRY_CAMP` 但**无位置/外观字段**）比对；② 查有无**教程/引导态**证据（项目目前**零 tutorial 语义**）；③ 若确为引导态 ⇒ 记为**前置条件未满足**（`DEFER`），停止找点击点。 |

## 2026-09-21 P0（操作者）：预留行军导致体力任务无法执行、AUTO 提前等待

### 一、那句话的真实来源与生产位置

GUI 显示的「已为体力任务预留1支行军」是 `reserved_march_for_stamina` 的中文，
产生处**只有两处**，都在 `winter_agent_v2/brain.py`：

| 位置 | 页面 | 条件 |
|---|---|---|
| `brain.py:857` | `RESOURCE_DETAIL` | `current_goal in {None,"GATHER_RESOURCE"}` 且 `idle_marches <= reserved_slots(world)` |
| `brain.py:1214` | `MAP` | 同上 |

现场那一帧（`dataset/truth_audit/march_reservation_20260921/key/01_*`）**是 MAP** ⇒ 命中的是 **1214**。
`reserved_slots` = `max(0, min(reserve_marches, capacity-2))`；`config/v2.json` 的
`march_policy.reserve_for_stamina=2`、容量 3 ⇒ 有效预留 **1**。

### 二、预留队列是否真正空闲：**是**

患者帧用生产链读：`marches=[GATHERING, RETURNING]`、`march_used=2`、`march_max=3`
⇒ `idle_marches=1` ⇒ `idle(1) <= reserved(1)` ⇒ 停。**预留机制本身正确**（挡住采集占用最后一格）。

### 三、根因：**不是预留挡住体力任务，而是"拒绝"被写成了"结束整轮"**

同帧用**生产 reserve=2** 跑 `RuleBrain.decide`：

```
goal=None / GATHER_RESOURCE  ->  SAFE_STOP  reserved_march_for_stamina
goal=BEAST_HUNT              ->  SCAN_MAP_FOR_BEAST       ← 体力路线本来就能用这一格
```

⇒ **预留从未挡住 `AVOID_STAMINA_WASTE`**（`BEAST_HUNT` 只在 `idle_marches <= 0` 时拒绝）。
真正的问题是 `runtime.py` 对 `SAFE_STOP` 的处理：记 `DEGRADED` 并 `return finish(reason)`
⇒ **一轮只做 1 件事就结束**，且没有动作把客户端挪出地图 ⇒ **下一轮开局还在同一屏**。

**为什么当时是采集目标在跑**：`KEEP_MARCHES_PRODUCTIVE` **不在这份文件的 goal→route 映射里**
（`runtime.py:880` 的 8 条：CLEAR_INTEL / AVOID_STAMINA_WASTE / KEEP_TRAINING_PRODUCTIVE /
KEEP_RESEARCH_PRODUCTIVE / MAIL_ROUTINE / DAILY_ACTIVITY_TARGET / ALLIANCE_ROUTINE /
CLAIM_EXPLORATION_IDLE），所以 `current_goal=None`，而两个预留分支的条件正好是
`{None, "GATHER_RESOURCE"}` ⇒ 采集分支先回答。同时 `AVOID_STAMINA_WASTE` 被开发作业
`2d5c3dd5`（`SPEND_STAMINA_ON_BEAST = DEVELOPMENT_PENDING`）挡住；它是该帧上优先级最高的
可调度目标（**825**），门禁 **03:26:03Z** 一放行（`RUNNABLE`）立刻被选中并开始跑。

**该帧上打野的真实阻塞**：地图上那只兽只有 `22` 徽标、**没有名字**（`key/03_*`），
生产链 `beast={}`、整帧 OCR 也找不到已注册兽名 ⇒ **"没有可识别目标"**，与预留无关。

### 四、修法与验证

`runtime.py` 的 `SAFE_STOP` 分支内，**只针对该理由**改用项目已有的
`_yield_to_next_goal`（与"技能不可执行"同一条 Rule A 路径）⇒ 循环 `continue`、重新取帧、重选目标。
**不是改状态名**；范围精确限定（守卫会因"扩到所有 SAFE_STOP"变红）；保留两道既有边界
（`index < max_actions`、同一 goal 一轮只让位一次）。

`tests/test_march_reservation_handover.py` 7 条：**本树 7 passed / 未修 HEAD 3 failed + 4 passed**
（红的三条正是缺陷：`stop_reason` 就是该理由、让位后没有发出任何真实步骤、零次让位叙事；
另外 4 条两侧都过 ⇒ 钉的是不变行为）。守卫 +5，`problems: 0`。

**当前这批相关测试的 3 条红（`test_capability_gate.py::DeferredGoalSchedulingTests`）已在
未改动的 HEAD 上复现** ⇒ 是 #63 基线，不是本次引入。

### 五、仍未做

| # | 问题 | 状态 | 说明 |
|---|---|---|---|
| 83 | **`KEEP_MARCHES_PRODUCTIVE` 不在 goal→route 映射里** | 🟠 **已定性，未补** | 补它**不是无副作用的**：`current_goal is not None` 在 `brain.py:274 / 534 / 1055` 会新激活三条分支（终端页让位、`goal_page_mismatch`、联盟页让位）⇒ 等于同时打开三条未测路径，必须单独测。**本轮不补**，记此处。⚠ 注意：**补它也不会改变本次停机** —— 两个预留分支对 `None` 与 `"GATHER_RESOURCE"` 行为相同。 |
| 84 | **角色身份没有任何生产路径重读** | 🟠 **真实缺口** | `learning/role_identity.json` 最后观测 **2026-09-16T10:44:08Z**（已过 **112.8h**），`verification=VISION_READ_REPLAY`（**回放**）。生产只把它当**标记**（`[role] 1171757165 (PERSISTED)`）打在 episode 上，**不参与调度门控**、不会把队列/体力写进别的角色 ⇒ **展示层过期**，不是队列问题的伪装。但 `record_role` 只被操作者工具 `tools/state_truth_audit.py --record-role` 调用，**AUTO 从不重读** ⇒ 需要一条生产重读路径（或在无人值守里定期走一次领主档案）。 |
| 33 | **陈旧 `.git/index.lock`（第 3 次）** | ⚠️ **再次命中** | 本次 0 字节、mtime 早 3h30m、`tasklist` 无 `git.exe` ⇒ 按既有规程删除后恢复。**已三次**，建议尽快在同步路径加"陈旧锁检测"（#33 原有建议），不要靠人记得。 |

### 六、真机验证：**被 AUTO 停摆挡住**（本轮未能完成，据实报告）

**AUTO 在 `11:43:24`（本地）那一轮之后再没有起过新轮**：

| 证据 | 值 |
|---|---|
| 最后一轮目录 | `dataset/raw/control_panel/runtime_auto/20260921_114324_887590`，9 帧，**最后一帧 `03:44:57Z`** |
| 最后一条 episode | `03:44:56Z  OPEN_ALLIANCE_GIFTS  KEEP_MARCHES_PRODUCTIVE  rev=8a8429c77b55` |
| `runtime_snapshot` | `agent_state=DEGRADED`、`current_skill=SAFE_STOP`、`page=ALLIANCE`、**`stop_reason=alliance_state_unknown`**，`runtime_thread_alive=false`，`updated_at=03:45:04Z` |
| 面板进程 | **仍然活着**：`pump.json` `last_tick=11:56:51`、`passes=548`、`gateway.json checked_at=11:57:05` |
| `panel.log` | 最后一行 `11:43:24 自动运行已启动`，**之后 13 分钟没有任何输出** |
| `operator_intent` | `RUNNING`（11:43:24 置位） |

⇒ **面板活着、AUTO 意图是 RUNNING，但轮转循环不再起轮**。

**这不是本次改动造成的，而且与它无关**：
① 那个卡住的轮次跑的是 **`8a8429c7`（修复前）**；
② `winter_agent_v2/runtime.py` **不在** `CONTROL_PLANE_PATHS` 名单里
（名单 = `tools/control_panel.py`、`workbuddy_bridge.py`、`gateway_service.py`、`escalation_queue.py`、
`device_lease.py`、`version_identity.py`、`state_truth.py`）⇒ **本次提交不需要控制面重载**。

**处置**：**未自行重启面板**。重启 GUI 进程属于控制面动作，操作者本次明确要求"不得为了本次修复触发
未经验证的控制面自动重载"，且本会话开头就是操作者手工重启的。⇒ **需要操作者再重启一次**。

| # | 问题 | 状态 | 说明 |
|---|---|---|---|
| 85 | **无 goal 的轮次站在联盟页会以 `alliance_state_unknown` 结束整轮** | 🔴 **真的又发生了（有帧与快照）** | 昨天 `ecb0014` 把联盟页的停机改成"**有命名 goal 时**让位一次再停"，并**刻意保留**无 goal 时直接停（依据是 `tests/test_multitask_scheduler.py` 钉的"没有 goal 时是调度器在探测"）。本次实测：`11:43:24` 那轮在 `page=ALLIANCE` 上以 `current_skill=SAFE_STOP / alliance_state_unknown` 结束，**快照的 goal 标签是 `KEEP_TRAINING_PRODUCTIVE`**，但 brain 侧当时 `current_goal=None`（标签取的是 `_committed_goal`）⇒ 走的是**被刻意保留的那条**。⇒ 后果与昨天判断的一致：**一个没人能操作的页面结束了整轮，而没有任何动作把客户端挪出去** —— 只是这次"没人能操作"的原因不是"别的 goal 站错了页"，而是**当轮没有任何 goal 可调度**。**未修**：改它就要推翻 `test_multitask_scheduler.py` 钉住的那条性质，需要单独判断"无 goal 时 Back 是否会被误当成有活干"。 |
| 33 更正 | **`tasklist` 在本环境不可用，"确认无 git 进程"这一步实际没做成** | ⚠️ **证据更正** | 本次删陈旧锁前的"无 `git.exe` 进程"结论，实际来自 `tasklist` **返回 0 行**——而该命令在本环境**对任何查询都返回 0 行**（`tasklist //FO CSV \| wc -l` = 0），所以它**不能证明任何事**。⇒ 当时删除的依据只有：**0 字节、mtime 早 3h30m、`git add` 报 `index.lock exists` 且无 git 输出**。结论仍合理，但**过程证据要按实际写**。**建议**：把"陈旧锁检测"做成代码（比年龄 + 0 字节），不要依赖进程检查 —— 本环境的进程检查不可用。 |
