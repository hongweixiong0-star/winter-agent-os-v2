# 04 — OPEN ISSUES

`AUTO:open_issues` 块由脚本重算（Top Failure、证据完整性、只失败过的技能、脏文件）。
下面的手写块记录**机器看不出来的**未决问题。

<!-- AUTO:open_issues -->
Machine-detected issues (recomputed every run):

- **SEMANTIC_TARGET_NOT_VERIFIED** x115 all-time; recent=48 (last 2d), last seen 2026-09-15T01:06:10.228210+00:00 — SELECT_RESOURCE(40), SEARCH_RESOURCE(32), OPEN_MAIL(13)
- **RESOURCE_NOT_FOUND** x30 all-time; recent=30 (last 2d), last seen 2026-09-14T06:42:03.928936+00:00 — SUBMIT_RESOURCE_SEARCH(30)
- **DISPATCH_NOT_PROVEN** x29 all-time; recent=28 (last 2d), last seen 2026-09-14T05:25:20.306984+00:00 — DISPATCH_MARCH(29)
- **STAMINA_SOURCES_NOT_OPEN** x9 all-time; recent=9 (last 2d), last seen 2026-09-15T02:31:47.501403+00:00 — OPEN_INTEL(9)
- **INTEL_HERO_DISPATCH_NOT_PROVEN** x8 all-time; recent=8 (last 2d), last seen 2026-09-14T12:19:55.812501+00:00 — INTEL_HERO_DISPATCH(8)
- **INTEL_RESCUE_START_NOT_PROVEN** x6 all-time; recent=6 (last 2d), last seen 2026-09-14T17:17:43.915836+00:00 — EXECUTE_INTEL_RESCUE_SURVIVORS(6)
- `ALLIANCE_HELP` never succeeded (attempts=1, failure=0)
- `CONFIRM_EXPLORATION_IDLE_CLAIM` never succeeded (attempts=2, failure=2)
- `DISMISS_EXPLORATION_REWARD` never succeeded (attempts=1, failure=1)
- `DISMISS_MAIL_REWARD` never succeeded (attempts=1, failure=1)
- `DISPATCH_BEAST` never succeeded (attempts=1, failure=1)
- `RESEARCH` never succeeded (attempts=1, failure=0)
- `SAFE_STOP` never succeeded (attempts=4, failure=4)
- `SELECT_BEAST_TARGET` never succeeded (attempts=1, failure=1)
- `WAIT` never succeeded (attempts=1, failure=1)
- 13 uncommitted file(s): ['M .workbuddy-ai/handoff/.last_good_commit', ' M .workbuddy-ai/handoff/01_CURRENT_TRUTH.md', ' M .workbuddy-ai/handoff/02_CURRENT_PROGRESS.md', ' M .workbuddy-ai/handoff/03_NEXT_ACTION.md', ' M .workbuddy-ai/handoff/04_OPEN_ISSUES.md']
<!-- /AUTO:open_issues -->

---

## 手写：未决问题

### P0（2026-09-15 12:1x GMT+8 新增）—— 免费体力闭环 + 两条「空读数」缺陷

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
