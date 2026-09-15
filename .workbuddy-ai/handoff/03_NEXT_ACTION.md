# 03 — NEXT ACTION

> 本文件必须保持**短小、具体**。目标：新账号不读完整历史也能继续当前任务。
> `AUTO:next_action` 块由 `tools/update_workbuddy_handoff.py` 重写；
> 其余手写内容不会被自动覆盖。

## 手写：本轮（2026-09-15 11:xx GMT+8）—— 出征页身份不再编造 + 免费体力首次真机执行

### 1. 出征页身份编造（`0w` + `0af`）—— 已修，全语料闸门 104/104

**症状**：`dataset/raw/stamina_emergency/beast6_march.png` 是 **`目标：北极狼`** 的出征页，
修复前被报成 **`麝牛 / level 9`**；而 `verify_beast_dispatch` 当时**正是要求这两个值** ⇒
verifier 在编造身份上通过。

**根因（像素级，不是推断）**：四张"身份"模板是**同一个控件的两份裁图**：

| 语义 | 父帧 | roi (y, h) | 在两张父帧上的距离 |
|---|---|---|---|
| `BTN_BEAST_DISPATCH_MUSK_OX_9` | `beast9_round3_march` | (0.912, 0.070) | 0 / 0 |
| `BTN_BEAST_DISPATCH` | `live_beast_march_selection` | (0.914, 0.070) | 0 / 0 |
| `STATUS_VICTORY_ASSURED_MUSK_OX_9` | `beast9_round3_march` | (0.450, 0.045) | 0 / 4 |
| `STATUS_VICTORY_ASSURED` | `live_beast_march_selection` | (0.455, 0.045) | 0 / 0 |

⇒ 身份由**分支顺序**决定。`tools/probe_beast_formation_identity.py` 可复现。

**该页其实显示目标 —— 在标题栏**（vision 从未读过）：
野生 `目标：麝牛 / 北极狼 / 雪豹`（6/6 帧），情报 裸 `出征`（98/98 帧），**104/104 全部可读、零张失败**。

**修法**：`vision.py` 三个 MARCH 分支只断言 `victory_assured`（不再写 name/level）；
`ocr.py::HybridVision` 读标题栏填 `beast["name"]` + `beast["target_kind"]`；
`verifier.py` 的 MARCH 一侧改为绑**量测到的** name；`brain.py` 路由改读 `target_kind`。

**安全性方向（重要）**：野生路由要求**正向证据**，其余（情报标题 / 读不出 / goal=INTEL）
一律走情报路由。因为两个出征按钮是同一控件（点哪个都落），但 `verify_beast_dispatch` 要求量测到的
`麝牛` ⇒ 把身份未量测的编队送过去会把**正确动作记成 FAILURE**。

**留档**：`dataset/truth_audit/beast_formation_identity_20260915/`（7 帧 + 7 张标题裁图 + 语料闸门输出 + README）。

### 2. 免费体力检查首次真机执行（`0ai`）—— 已确认

真机 `run_live.py --goal INTEL --max-actions 4`（`03:03:57Z`，4/4 verifier OK，exit 0）：
step 3 = `OPEN_STAMINA_SOURCES` / `TAP_SEMANTIC HUD_STAMINA_GAUGE` / `MAP → POPUP/GET_MORE_STAMINA` / **OK**。
语料：1105 条 episode 里该技能此前出现 **0** 次。
**边界**：只证明"面板会被打开"；当时 `free_claim_available=false`，所以**领取动作仍未真机验证**。

### 3. 新缺陷：体力不足被记成"战斗已开始"（`0ak`）—— 已修，待真机重跑

同一次运行 step 1 被判 **OK**，after 态却是 `POPUP/GET_MORE_STAMINA`（体力 9 < 标价 10，游戏**拒绝**）。
`verify_intel_hero_march_open` 的判据是"页面变了就算成功" ⇒ 必然通过。
已修：拒绝单独判定 + 独立 reason `INTEL_HERO_MARCH_REFUSED_FOR_STAMINA`。

### 下一动作（按价值排序）

1. **`0ak` 的真机重跑确认**：把客户端停到英雄之旅营地面板（体力 < 10），跑
   `run_live.py --goal INTEL --max-actions 2`，第 1 步应记 `INTEL_HERO_MARCH_REFUSED_FOR_STAMINA`。
2. **主动体力门（`0ak` 的根因级修法）**：大脑在动手前比较 `world.stamina.current`（地图 HUD）
   与 `exploration.stamina_cost_displayed`，不足就 `SAFE_STOP`，而不是先花 2 个动作去撞拒绝。
   本轮那次运行**4 个动作里有 2 个是 `BACK`**，纯粹因为体力不足。
3. **`CLAIM_FREE_STAMINA` 的真机验证**：等 `丰盛的招待` 的下次补给到期（本轮帧显示 `00:56:02`）再跑一次。
4. **`0al`（需操作者决策）**：账上有约 **1,007 × +10** 体力道具而体力只有 9；
   面板里那行「使用」不是付费行，但 `stamina_policy.note` 只允许 `BTN_CLAIM_FREE_STAMINA`。
   **等操作者表态，不要擅自扩权。**
5. 设计受阻的技能（见 AUTO 块 `DESIGN-BLOCKED`）：需要先拿真机帧再设计语义，不要照草稿硬写。

<!-- AUTO:next_action -->
CURRENT PRIORITY: fill the missing skills that block 4 goal(s)
CURRENT TASK: every highest-leverage missing skill is DESIGN-BLOCKED — no draft is implementable from the manifest alone (14 NOT_REGISTERED, 6 NO_VERIFIER); see DESIGN-BLOCKED below

WHY: 4 goal(s) BLOCKED, 8 PARTIAL, mean implementation coverage 0.54. The blocked goals share one small set of never-implemented skills, so one skill purchase can move several goals at once.

CURRENT ROOT CAUSE: SEMANTIC_TARGET_NOT_VERIFIED — 48 in the last 2 day(s), 115 all-time, last seen 2026-09-15T01:06:10.228210+00:00
LAST GOOD COMMIT: 8943141
CURRENT DIRTY FILES: 58
LAST PRODUCTION EPISODE: {"skill": "BACK", "result": "SUCCESS", "recorded_at": "2026-09-15T03:04:43.757203+00:00", "episode_id": "live_runtime", "before_screenshot": "E:\\无尽冬日智能体\\dataset\\raw\\live_runtime\\live_runtime_step_004_before_20260915T030429554449.png", "after_screenshot": "E:\\无尽冬日智能体\\dataset\\raw\\live_runtime\\live_runtime_step_004_after_20260915T030432112556.png"}
TOP FAILURE: {"failure_type": "SEMANTIC_TARGET_NOT_VERIFIED", "count": 115, "recent": 48, "last_seen": "2026-09-15T01:06:10.228210+00:00", "dates": {"2026-09-12": 36, "2026-09-13": 37, "2026-09-14": 8, "2026-09-15": 3}, "undated": 31, "top_skills": [["SELECT_RESOURCE", 40], ["SEARCH_RESOURCE", 32], ["OPEN_MAIL", 13]]}
TOP FAILURE IS RANKED BY RECENT FIRST: read `recent` (last 2 day(s), floor 2026-09-13T03:04:43.757203+00:00) before `count` (all-time). A failure type with recent=0 is history, not a current defect.

BLOCKED GOALS: ['KEEP_RESEARCH_PRODUCTIVE', 'ALLIANCE_TIMED_EVENTS', 'USE_FREE_ARENA_ATTEMPTS', 'LABYRINTH_DAILY']
MISSING SKILLS BY LEVERAGE: [('CHECK_ALLIANCE_EVENT', 2), ('CLAIM_EVENT_TIER', 2), ('JOIN_RALLY', 2), ('READ_BEAR_TIMER', 2), ('READ_COUNTER', 2), ('READ_TIMER', 2), ('USE_ACTIVITY_ATTEMPT', 2), ('ALLIANCE_HELP', 1), ('ALLIANCE_TECH_CONTRIBUTE', 1), ('OPEN_ARENA', 1)]
DESIGN-BLOCKED (not implementable from the draft alone; each needs a live frame of its page first): CHECK_ALLIANCE_EVENT [NOT_REGISTERED] — requires semantic(s) `ALLIANCE_EVENT_ENTRY` that do not exist in dataset/candidate/template_manifest.json; the page has never been observed live, so this needs new vision design first; CLAIM_EVENT_TIER [NOT_REGISTERED] — requires semantic(s) `EVENT_TIER_CLAIMABLE` that do not exist in dataset/candidate/template_manifest.json; the page has never been observed live, so this needs new vision design first; JOIN_RALLY [NO_VERIFIER] — has no design draft at all (absent from winter_agent_v2/skill_factory.PRIORS), so its required semantics and success condition are undefined; READ_BEAR_TIMER [NOT_REGISTERED] — requires semantic(s) `BEAR_TIMER` that do not exist in dataset/candidate/template_manifest.json; the page has never been observed live, so this needs new vision design first; READ_COUNTER [NO_VERIFIER] — has no design draft at all (absent from winter_agent_v2/skill_factory.PRIORS), so its required semantics and success condition are undefined; READ_TIMER [NO_VERIFIER] — has no design draft at all (absent from winter_agent_v2/skill_factory.PRIORS), so its required semantics and success condition are undefined ... and 14 more
NEVER EXECUTED SKILLS (first 12): ['CANCEL_DUPLICATE_TARGET', 'CHECK_MARCH', 'CLAIM_FREE_STAMINA', 'CLAIM_REWARD', 'DISMISS_ALLIANCE_GENERIC_REWARD', 'JOIN_RALLY', 'NAVIGATE_TO', 'READ_COUNTER', 'READ_INTEL_LIST', 'READ_TIMER', 'RECALL_MARCH', 'RECOVER_HOME']

NEXT EXACT ACTION: Do not implement a design-blocked skill from its draft. The cheapest real progress is to obtain a live frame of the page the skill needs (a read-only discovery probe), design the missing semantic from that evidence, then implement. Failing that, take the highest-value *live-evidenced* defect from 04_OPEN_ISSUES — those are already proven by production episodes.

ACCEPTANCE: production episode + passing verifier + screenshot evidence, and the named goal(s) move off BLOCKED (live coverage increases).

DO NOT: re-architect, rename goals, or touch anything already live-verified without new failure evidence.
<!-- /AUTO:next_action -->

---

## 手写：当前任务的上下文

### 【最新 2026-09-15 10:3x GMT+8】运行时对同一帧算了两次决策 —— 已修 + 真机 A/B

**这是本轮价值最高的一条**，而且它**推翻了旧记录对 `0i` 的归因**。

**怎么发现的**：本来只是想做一次真机确认，结果第一次运行就撞上了 ——
`--goal INTEL` 在地图页第 1 步判 FAILURE 并 exit 2。动作明明成功了：

```
1 OPEN_INTEL  action TAP_SEMANTIC BTN_OPEN_INTEL_WILD_HUD
  before MAP  ->  after INTEL            ← 动作完全成功
  verify ok=false reason=STAMINA_SOURCES_NOT_OPEN
         evidence {"before_page": "MAP", "after_popup": null}
  recorded skill OPEN_INTEL
  stop_reason STAMINA_SOURCES_NOT_OPEN   exit 2
```

`STAMINA_SOURCES_NOT_OPEN` 是 `verify_stamina_sources_open` 的 reason，那串 evidence 也是它的
evidence ⇒ **一个"这一步根本没执行的技能"的验证器，判了这一步**。

**真根因（旧记录写的是"外部编辑器回写"，那是错的）**：运行时**对同一帧算了两次决策**。
```
runtime.py:387   decision = self.brain.decide(before, registry)   ← 第 1 次（并用它建后端路由）
Scheduler.tick   decision = self.brain.decide(world, registry)    ← 第 2 次，执行的是这一次
runtime.py:595   VERIFIED_ATOMIC[decision.skill](before, after)   ← 验证器绑第 1 次
runtime.py:612   episode 记 tick.decision                        ← 记录写第 2 次
```
而 **`RuleBrain.decide` 不是纯函数**：`brain.py:362` 置 `stamina_panel_checked=True`
并返回 `OPEN_STAMINA_SOURCES`。所以第 2 次调用返回 `OPEN_INTEL`。
`runtime.py:545` 的注释原文就写着 **"one router decision per step"** —— **代码违反了自己写下的不变量**。

**三重后果**：
1. **假 FAILURE + 运行中止**（上面那条，exit 2）；
2. **免费体力面板从未被打开**，而大脑已把"本轮已检查"标为 True ——
   **一个功能"报告完成却从未执行"**，与情报 `NOT_AVAILABLE` 静默终止同族；
3. `STAMINA_SOURCES_NOT_OPEN` 被记在 `OPEN_INTEL` 名下（AUTO 表 `OPEN_INTEL(8)`），污染统计。
   顺带解释了为什么 `0i` 的"静态映射护栏"永远查不到它：映射本来就是对的。

**修法（一步一决策）**：`Scheduler.tick(world, decision=None)` 改为执行**传入的**决策；
`runtime.py` 把自己的决策交给它。不传时行为不变（单测覆盖）。

**真机 A/B（同 goal、同动作、同 `MAP→INTEL` 迁移、体力 0 消耗）**
| | 修复前 `02:31:11Z` | 修复后 `02:34:45Z` |
|---|---|---|
| skill / action | `OPEN_INTEL` / `BTN_OPEN_INTEL_WILD_HUD` | 同 |
| before → after | `MAP → INTEL` | 同 |
| verification | **False** `STAMINA_SOURCES_NOT_OPEN` | **True** `OK {"before_map":true,"after_intel":true,"stamina":3}` |
| stop_reason / exit | `STAMINA_SOURCES_NOT_OPEN` / **2** | `MAX_ACTIONS_REACHED` / **0**（3/3 OK） |

留档 `dataset/truth_audit/one_decision_per_step_20260915/`（4 帧 + `live_ab_records.json`）；
`tests/test_one_decision_per_step.py` 用记录里的**原始状态重新调用两个 verifier**，
证明"记录下来的 reason/evidence 正是另一个 verifier 的输出"——不是字符串比对，是重放。

**诚实边界**：本轮那次 A/B **没有**触发免费体力检查（当时地图 HUD 体力读数为空，
而闸门要求它非空）⇒ **不要声称"免费体力检查已恢复"**，待下次地图帧体力可读时确认（登记为 `0ai`）。

**下一最高价值任务**：见下一节的 `0af` + `0w`（MARCH 页被 vision 编造野兽身份）。
另外 `0ai` 是一个**零成本顺带确认**：下次地图帧体力可读时，第 1 步应当是
`OPEN_STAMINA_SOURCES`（reason `free_stamina_gift_not_yet_checked_this_run`）。

### 【2026-09-15 10:5x GMT+8】情报巨兽目标被路由到 `BEAST_HUNT` —— 已修（证据=生产回放，非真机）

**一句话**：`Page.BEAST` 被两个不同目标共用，而路由判据用的是 goal 而不是页面身份。

**真机记录（这是本轮唯一的事实来源，未做新真机运行）**
episode `ally_prep_20260915` step 3，`2026-09-15T02:10:52Z`，`goal_id=HOME`：
```
state_before  BEAST  beast={"mission_id":"INTEL_BEAST_10","name":"大角鹿","level":22,"available":true}
action        TAP_SEMANTIC BTN_BEAST_START_MARCH
state_after   MARCH  beast={"name":"麝牛","level":9,"victory_assured":true}
result        FAILURE  failure_type=BEAST_MARCH_NOT_PROVEN
```

**根因**：`brain.py` 用 `current_goal == "INTEL"` 判定"这是情报目标"。
但情报身份由 `mission_id` 决定，**与 goal 无关** ⇒ 任何非 INTEL goal 下，
情报目标都落到 `BEAST_HUNT`（技能文档写的是"击败野外普通巨兽"），
而它注册的 verifier `verify_beast_march_open` 要求 before 是**地图野怪 `麝牛`/9`**。
**两次点击完全相同**（都是 `BTN_BEAST_START_MARCH`）⇒ 动作成功、却被记成失败。

**修法（1 行，且不改变任何物理点击）**：删掉 goal 闸门，只按
`mission_id ∈ {INTEL_BEAST_10, INTEL_FIREBEAST_10}` 路由到 `INTEL_BEAST_START_MARCH`
（其 verifier `verify_intel_beast_march_open` 用 mission→level 表绑定身份，是既有正确实现）。
各 goal 自己的页面闸门在上方先执行，所以 goal 语义不受影响。

**证据等级（不许读成 LIVE_VERIFIED）**：生产 episode 回放 + 单测。
`dataset/truth_audit/beast_intel_target_routing_20260915/recorded_episode_20260915T021052Z.json`
保存了同一条真机 before/after，**同一对状态现在通过正确的 verifier**（改前判 FAILURE）。
**没有做真机运行确认**，原因：`run_intel_pins.py` 内部固定 `--goal INTEL`，
而 INTEL 下旧代码本来就路由正确 ⇒ 它**无法**验证本次改动。
要真机确认，需先把客户端停在情报巨兽目标页、再用非 INTEL goal 跑（见下方"下一动作"）。

**同时发现（第三次 `0p` 同类）**：`tests/test_beast_verifier.py` 原来断言
`RuleBrain().decide(live_beast_intel_world_target.png) == "BEAST_HUNT"` —— 而该帧标签明确是
`mission_id=INTEL_BEAST_10 / 大角鹿 / 22`，即**情报**目标。它能通过只是因为
`RuleBrain()` 的 `current_goal=None` 让 goal 闸门恰好为假。**它把 bug 写死成了测试。** 已改写。

**下一最高价值任务（`0af` + `0w`，同一根因，要一起修）**：**MARCH 页被 vision 编造了野兽身份。**
`vision.py:784` 只要 `BTN_BEAST_DISPATCH_MUSK_OX_9` + `STATUS_VICTORY_ASSURED_MUSK_OX_9` 命中，
就写死 `beast={"name":"麝牛","level":9,"victory_assured":True}` —— 不管这一仗其实是情报的
`大角鹿/22`。后果有两层：
1. `brain.py:405` 靠 `world.beast.get("level") == 22` 区分情报/野怪派发 ⇒ **死分支**，
   非 INTEL goal 下的情报出征会被判给 `DISPATCH_BEAST`（点 `BTN_BEAST_DISPATCH_MUSK_OX_9`）
   而不是 `DISPATCH_INTEL_BEAST`（点 `BTN_BEAST_DISPATCH`）。
2. 出征（部队编成）页根本不显示野兽名/等级 ⇒ 任何名字/等级都是编造，违反「不得声明页面上不存在的信息」。

**正解**：MARCH 页只声明它真正显示的东西（`victory_assured` / 体力消耗），
并把 mission 身份从 BEAST 页**传递**到 MARCH 页，而不是让 MARCH 页自己猜。
⚠ 动它之前先核清 `verify_beast_march_open` / `verify_beast_dispatch` / `verify_beast_hunt` /
`verify_stamina_beast_*` 的依赖面 —— 它们都依赖这些字面值。
**低成本真机确认顺带做**：下一次情报 pin 运行把客户端留在巨兽目标页时，直接跑
`tools/run_live.py --goal HOME --max-actions 2`，第 1 步应当是 `INTEL_BEAST_START_MARCH` 且 verifier OK。

**顺带（`0ab` 已修，但要记住教训）**：新增真机留档目录后必须 `git check-ignore` 验一次。
本轮发现 4 个**被测试读取**的归档目录（含 69 帧 / 34 MB 的 `panel_redesign`）一直被
`dataset/truth_audit/**/*.png` 这条文件模式静默吞掉，新克隆跑不了对应测试。

### 【2026-09-15 10:2x GMT+8】联盟首页被读成「宝箱页」—— 两层缺陷，已修 + 真机 12/12 闭环

**本轮真实改进（Before → After）**
`OPEN_ALLIANCE_GIFTS` —— **项目史上从未被执行过**（在 handoff 的 NEVER EXECUTED 名单里）
→ 真机 1/1 verifier OK，并连锁带出 11 次 `ALLIANCE_ALLY_GIFT_CLAIM` 全部 OK。
而在此之前，进入联盟页的唯一结局是 `SAFE_STOP alliance_state_unknown`。

**为什么值得做**：真机联盟首页上「联盟宝箱」磁贴挂着 **84** 个未领宝箱（`badge_count`），
而机器**看不见**它们 —— 这不是"少做一个功能"，是"一个正在漏收益的链路"。

**一个误分类同时打断了两件事**（所以之前没人能修好它）：
1. `brain.py:206` 只有在 `section == "HOME"` 时才派发 `OPEN_ALLIANCE_GIFTS` → 永远不成立；
2. `verify_open_alliance_gifts`（`verifier.py:244`）也要求 `before.section == "HOME"` →
   **即使强行派发也永远判不过**。两层互锁，看起来像"技能没实现"。

**两个独立原因，单独任一个都不足以解释**
- **模板层**：`PAGE_ALLIANCE_GIFTS` 在首页上 d=6（阈值 8），且它的分支排在 `PAGE_ALLIANCE`
  之前 ⇒ 首页根本走不到 HOME 分支。
- **OCR 层（真根因）**：`ocr.py:258` 只要看到精确文本 `联盟宝箱` 就写 `section="GIFTS"`。
  但 `联盟宝箱` **本身就是首页的入口磁贴** —— 实测它在 **5 张首页帧和 3 张宝箱页帧上都是
  精确 token**，也就是它**什么都区分不了**。而 `HybridVision` 又把 OCR 的 `alliance` 字典
  **盖在**模板结果之上 ⇒ 就算模板层答对了 HOME，也会被 OCR 覆写回 GIFTS。
  ⇒ 实测隔离证据：`SemanticWorldVision.observe(首页)` → `HOME`，同一帧过完整 `HybridVision` → `GIFTS`。

**修法（两处严格加法 + 一个缺失的 verifier）**
- `vision.py`：在两条弱标题条**之前**加成对锚点分支
  `if match("PAGE_ALLIANCE") and (match("BTN_OPEN_ALLIANCE_GIFTS") or match("BTN_ALLIANCE_HELP"))`
  → `HOME`。`PAGE_ALLIANCE` 单独用不可信（见 04 的 0x），必须配一个入口磁贴。
- `ocr.py`：模板层已经决定 `section` 时，OCR **不得覆写** `section`（其余字段照旧合并）。
- `verifier.py` + `runtime.py`：补上 `ALLIANCE_GIFTS` 的 verifier 并注册 ——
  **没有 verifier 的技能永远不会被派发**。

**闸门（2757 张真机帧）**：`PAGE_ALLIANCE` 单独命中 79 帧，**全部是 MARCH**（已知弱标题条）；
成对锚点命中 **16 帧，全部当前已是 `ALLIANCE` 且 `visible_claim_buttons == 0`**（真首页）。
⇒ **2757 帧里页面身份改变 0 帧**，只在 16 张首页上把 `section` 从错的 GIFTS 改成 HOME。

**Live Evidence（`tools/run_live.py --goal ALLIANCE --max-actions 12`，exit 0）**
`stop_reason=MAX_ACTIONS_REACHED`，**12/12 verifier OK**：
```
1 OPEN_ALLIANCE_GIFTS  reason=alliance_gifts_badge_visible  ver=True OK
  before ALLIANCE {"section":"HOME","tab":"VICTORY_LOOT","status":"UNKNOWN"}
  after  ALLIANCE {"section":"GIFTS","tab":"ALLY_GIFT","status":"CLAIMABLE","visible_claim_buttons":4,"badge_count":84}
  evid   {"alliance_home_before": true, "gifts_after": true}
2..12 ALLIANCE_ALLY_GIFT_CLAIM  ver=True OK ×11
  badge 84 → 73；gift_progress 58250 → 62480（target 150000）
```
留档：`dataset/truth_audit/alliance_gifts_chain_20260915/`（5 帧，含 1 张出征页负对照）。

**诚实边界（不要读成更多）**
- `ALLIANCE_GIFTS`（我补 verifier 的那个技能）**至今仍是休眠代码**：`brain.py:301` 只在
  `tab != "ALLY_GIFT"` 时才选它，而真机宝箱页默认就停在 `ALLY_GIFT` ⇒ 走的是
  `ALLIANCE_ALLY_GIFT_CLAIM`。**它有单测、已注册，但没有真机证据**，不许标 LIVE_VERIFIED。
- 本轮**没有**改动 `tab` 的判据（`ocr.py:285` 用 `购买含有盟友赠礼` 判别）——它在本轮没暴露问题。

**上一轮 handoff 的 `NEXT EXACT ACTION` 按字面做不了**（必须记下来，否则下个账号会再撞一次）：
它要求实现 `CHECK_ALLIANCE_EVENT`，但该技能自己的设计稿依赖的语义 `ALLIANCE_EVENT_ENTRY`
**在 `dataset/candidate/template_manifest.json` 里根本不存在**（385 条查过；联盟类只有
home / help / tech / gifts 四组），而这一页**从未被真机观测过** ⇒ 那等于要凭空设计 3 处新视觉。
`ALLIANCE_TIMED_EVENTS` 的另外两个能力（`ALLIANCE_EVENT_TIMER` / `EVENT_TIER_CLAIMABLE`）
同样没有观测支撑。**本轮改为先做有真机证据的缺陷**，这是"Live Improvement > Report"的取舍。

**下一最高价值任务（`0af` + `0w`，同一根因，要一起修）**：**MARCH 页被 vision 编造了野兽身份。**
`vision.py:784` 只要 `BTN_BEAST_DISPATCH_MUSK_OX_9` + `STATUS_VICTORY_ASSURED_MUSK_OX_9` 命中，
就写死 `beast={"name":"麝牛","level":9,"victory_assured":True}` —— 不管这一仗其实是情报的
`大角鹿/22`。后果有两层：
1. `brain.py:405` 靠 `world.beast.get("level") == 22` 区分情报/野怪派发 ⇒ **死分支**，
   非 INTEL goal 下的情报出征会被判给 `DISPATCH_BEAST`（点 `BTN_BEAST_DISPATCH_MUSK_OX_9`）
   而不是 `DISPATCH_INTEL_BEAST`（点 `BTN_BEAST_DISPATCH`）。
2. 出征（部队编成）页根本不显示野兽名/等级 ⇒ 任何名字/等级都是编造，违反「不得声明页面上不存在的信息」。

**正解**：MARCH 页只声明它真正显示的东西（`victory_assured` / 体力消耗），
并把 mission 身份从 BEAST 页**传递**到 MARCH 页，而不是让 MARCH 页自己猜。
⚠ 动它之前先核清 `verify_beast_march_open` / `verify_beast_dispatch` / `verify_beast_hunt` /
`verify_stamina_beast_*` 的依赖面 —— 它们都依赖这些字面值。

**顺带（`0ab` 已修，但要记住教训）**：新增真机留档目录后必须 `git check-ignore` 验一次。
本轮发现 4 个**被测试读取**的归档目录（含 69 帧 / 34 MB 的 `panel_redesign`）一直被
`dataset/truth_audit/**/*.png` 这条文件模式静默吞掉，新克隆跑不了对应测试。

### 【2026-09-15 08:45 GMT+8】出征（部队编成）页被读成联盟首页 —— 已修 + 真机 A/B 证明

**本轮真实改进（Before → After）**
`INTEL_BEAST_START_MARCH` 在真机上：`INTEL_BEAST_MARCH_NOT_PROVEN`（00:14:13Z）
→ 同一技能 verifier OK。

**上一轮 handoff 的猜测是错的**（原文写「verifier 写死了任务等级，新 pin 打开了别的等级」）。
`state_before` 正是复核过的 `INTEL_BEAST_10 / 大角鹿 / level 22 / available`。
真根因：**出征页被分类成 `ALLIANCE/HOME`**。

同一个页面的两帧实测（全部证据）：

| 语义 | 帧 A（同轮 SUCCESS） | 帧 B（失败帧） |
|---|---|---|
| `BTN_BEAST_DISPATCH` | d=0 命中 | **d=26 不命中**（阈值 8） |
| `PAGE_BEAST_MARCH` | d=0 命中 | d=0 命中 |
| `STATUS_VICTORY_ASSURED` | d=0 命中 | d=0 命中 |
| `PAGE_ALLIANCE` | d=8 命中 | d=8 命中 |

出征按钮是**动画控件**（真机帧上还叠着 `00:00:29` 倒计时徽标），hash 漂移越过阈值 8；
它一失手，下一个命中的就是 `PAGE_ALLIANCE` 那条**标题条**模板 → 整页报成联盟首页。
而这一页真正复核过的两个锚点（`PAGE_BEAST_MARCH`、`STATUS_VICTORY_ASSURED`，都裁自
`dataset/raw/live_beast_march_selection.png`）在清单里存在却**没有任何分支引用**（孤儿模板）。

**修法**：在 `BTN_BEAST_DISPATCH` 之后、`PAGE_ALLIANCE` 之前加
`if match("PAGE_BEAST_MARCH") and match("STATUS_VICTORY_ASSURED")` → `Page.MARCH`
+ `beast={"victory_assured": True}`。放在按钮之后 ⇒ 已 live-verified 的路径逐字节不变；
不声明野兽名/等级 ⇒ 不编造页面上不存在的信息。

**闸门（2716 张真机帧）**：83 帧命中锚点，其中 75 帧当前已是 `MARCH`（不变）、8 帧是 `ALLIANCE`；
8 帧里只有 5 帧两个锚点同时命中（全部是同一张出征页）⇒ **影响面恰好 5 帧**。
另核：89 张联盟类帧两个锚点零命中。

**Live Evidence**
1. 真机帧 A/B（同帧）：`dataset/raw/control_panel/probe/intel_board_20260915_003755.png`
   补丁前 `ALLIANCE {'section':'HOME'}` → 补丁后 `MARCH {'victory_assured': True}`。
2. 真机端到端 `tools/run_live.py --goal INTEL`（00:39:14Z，2m09s，exit 0）：
   **10/10 步 verifier OK，`stop_reason=MAX_ACTIONS_REACHED`**，含 `DISPATCH_INTEL_BEAST` OK
   （`marches=['MARCHING']`）。⚠ 该轮 `INTEL_BEAST_START_MARCH` 走的是按钮分支，
   证明的是「链路通」，不是「新分支被真机触发」——后者由第 1 条证明。

**下一最高价值任务**：见 04_OPEN_ISSUES 的 0w（出征页被赋予页面上不存在的野兽身份，
会污染 episode 与统计）与 0r（已作废）之外，优先项仍是
`START_GATHER` 的 MAA 端到端（94 次真机尝试 / 37% 成功率，是最高频最差项）。


本区由人维护。生成器不会碰它。写「为什么是这个任务」以及「坑在哪」。

### 【最新 2026-09-15 08:xx GMT+8】情报可用性假阴性已修 + 真机验证 + 自动化重建 —— 读这一节

**本轮真实改进（Before → After，同一张真机帧）**

```
Before  {"status": "NOT_AVAILABLE", "available_count": 0, "list_read": true}
After   {"status": "AVAILABLE",     "available_count": 5, "pins": 5, "list_read": true}
```

根因链（真机复现 07:36）：`run_live.py --goal INTEL` 打开情报页 → 生产视觉报 NOT_AVAILABLE
→ `goal_library.py:71` 把它映射成 `CLEAR_INTEL = COMPLETE` → **AUTO 静默停止，exit 0 像成功**。
同一帧肉眼可见 **5 个任务 pin**（2 紫 / 2 蓝 / 1 橙），其中橙 pin 还被比例闸门漏掉。

改动（增量，无新架构）：`intel_pins.py` 比例下限 0.65→0.5；`ocr.py` 情报页 UNKNOWN 时
**先数 pin，`pins>0 ⇒ AVAILABLE`**，无 pin 才落回原表头规则；新增 `SELECT_INTEL_PIN`
（`skills.py` + `runtime.py` 的 `INTEL_PIN` 解析与去重 + `verifier.py::verify_intel_pin_opened`
+ `brain.py` 分支，排在 `READ_INTEL_LIST` 之前）。

**Live Evidence**：`tools/run_intel_pins.py 8`（6m22s，exit 0，`evidence/intel_pins_20260915_000822.json`）
- `SELECT_INTEL_PIN` **4 次执行 / 4 次 SUCCESS**（verifier PASS）⇒ LIVE_VERIFIED（attempts=4）。
- 连带真实产出：`DISPATCH_INTEL_BEAST` ×3、`EXECUTE_INTEL_RESCUE_SURVIVORS` ×1、`INTEL_CLAIM_REWARDS` ×4；
  体力 39 → 26 → 16。**救援任务在上一版是永远看不到的**（模板层不认那个 pin）。
- 全量测试 `422 passed, 7 skipped`；`check_wiring.py` = `problems: 0`；checkpoint `c2908ad`。

**⚠ 本轮推翻的一个前提：项目唯一的"空情报板"参考帧是错标。**
`dataset/truth_audit/intel_beast_target_20260914/03_intel_page_empty_list.png`
实测是**满板 13 个 pin**（体力 305、`下次刷新:07:59:21`），上一轮还写了断言 `NOT_AVAILABLE` 的测试
（把 bug 写成了测试）。已重命名为 `03_intel_page_full_board.png`（保留不删），两个测试改写。
⇒ **本项目至今没有任何经过验证的「空情报板」帧**；`NOT_AVAILABLE` 只能由「pin 检测器一个都没看到」到达。
以后**别再用它当负样本**，也**别再把"等负样本"当作不改判据的理由**。

**⚠ P0 复发：自动化接口 `list` 返回空。** handoff 三次声称的 id `7c1c18c1-…` 查不到
（磁盘上 `memory.md` 还在，看目录会误判为存在）⇒ 当时**没有任何无人值守在跑**。
已重建 **`e3485d0c-1b51-48a4-880c-c01fe0fdec19`**（ACTIVE，每小时，cwds=`E:\无尽冬日智能体`），
payload 换成真机有效的 `tools/run_intel_pins.py`，并**用 `list` 复核存在**。

**下一轮按此顺序（按失败影响 × 频率 × 可修性排序）**

1. **`INTEL_BEAST_START_MARCH` 的 verifier 写死了任务等级**（`INTEL_BEAST_10`→22、`INTEL_FIREBEAST_10`→20）。
   `SELECT_INTEL_PIN` 现在会点开**未复核**的 pin，于是可能打开其他等级的巨兽任务 →
   本轮 00:14:13 出现 `INTEL_BEAST_MARCH_NOT_PROVEN`（同轮前两次同技能 SUCCESS）。
   这是本轮**唯一新增失败**，且直接限制了刚拿到的能力。先查那一帧实际等级，再决定放宽 verifier
   还是按 `mission_id` 分派。证据：`dataset/raw/control_panel/runtime_auto/intel_pins_20260915_000822_nav_01/`。
2. **光晕 pin 的稳健化**：比例下限 0.5 的余量只剩 0.021（实测跨度 0.521–0.644）。
   正解是**剥离光晕后量本体高度**，不是继续降阈值。
3. **`START_GATHER`（=OPEN_MARCH_PAGE）的 MAA 端到端**：94 次真机 37% 成功，
   是注册表里最差的高频 skill；识别节点已测通（3/3 正、0/5 负）但**从未真机端到端**。
4. **`run_intel_pins.py` 的导航周期语义**：它现在**会做真实工作**却仍记成 `"navigation cycle"`，
   且连续 3 次导航周期后无条件停止（本轮 nav_01 有产出，之后 2 次失败即停）。
5. 72h Soak 仍未开始。

---

### 【上一轮 2026-09-14 21:1x】MAA 已进入生产执行路径 —— 下一轮做什么

先读 `docs/AVAILABLE_TOOLING.md`（工具清单）与 `docs/EXECUTOR_REALITY_AUDIT.md`
（每个 skill 现在真实走哪条后端）。**这是本轮最重要的两个新增文件。**

已落地：`MaaExecutorAdapter` + `ExecutorRouter`；取帧默认走 MAA（真机 20 次交替实测
**8.92 ms vs ADB 324.12 ms，36.3×**）；8 个 P0 skill 的 `preferred_backend=MAA`
（其中 5 个带 MAA 识别节点，1 个 HYBRID，2 个仅设备轴）；episode 记录真实调用链
`capture_backend / recognition_backend / action_backend / executor_backend`。

**下一轮按此顺序：**

1. **`START_GATHER`（=OPEN_MARCH_PAGE，`BTN_GATHER`）**：审计显示 94 次真机尝试
   只有 **37% 成功**，是注册表里最差的高频 skill。识别节点已测通
   （3/3 阳性、0/5 阴性、82.6 ms），**还没做过真机端到端**。
   动作：`run_live.py --goal GATHER_RESOURCE`，看 `MARCH_PAGE_NOT_OPEN` 是否下降，
   并把 episode 里的 `executor_backend` 从 UNRECORDED 变成 MAA/HYBRID。
2. **`INTEL_HERO_DISPATCH`（战斗按钮）**：识别 9/9、中心误差 0.5 px，但真机 8 次
   全部 `INTEL_HERO_DISPATCH_NOT_PROVEN`（都是今天修坐标之前的记录）。
   **需要情报板上有英雄之旅钉子**才能真机复验；没有就记 `BLOCKED_NO_INTEL_TARGET`，
   不要伪造尝试次数。
3. **`PAGE_MAP` 候选重测**：现用 `page_map__live_back_safe_home__0` 只 1/4 命中，
   说明它只匹配自己那一帧、不泛化。要按战斗按钮那套办法（绿色色块分割）在**当前
   客户端**重新裁一次，再进 MAA。不要直接塞旧模板。
4. **`CLOSE_POPUP` 的识别仍是 LEGACY**（无正样本语料：母帧已被 retention 轮转掉）。
   它是 HYBRID，可用；等有弹窗真机帧再补节点。
5. **72h Soak 仍未开始。** 现在取帧快了 36 倍、每步开销大降，是开始 Soak 的好时机。

**新的硬规则（已写入 `00_MASTER_RULES.md` §2b）：先 TOOL CHECK，再写代码。**
单个 UI 元素 15 分钟止损；单个 Skill/Failure/Goal 90 分钟止损。

### 【最新，覆盖下面的旧判断】2026-09-14 操作者策略变更：体力优先，采集降为最低

操作者明确指令：

> 体力满了 → 撤回采集去做情报任务和打巨兽等性价比高的体力消耗 → 把体力用掉 →
> 各种奖励及时领取。**采集性价比很低，只有队列没有其他用途时才去采集。**

据此 `config/v2.json` 已改为：

- `march_policy.reserve_for_stamina: 0 → 2`（原来采集会吃掉全部 6 条队列）
- 新增 `resource_policy`：`gather_priority=LAST_RESORT`、`stamina_first=true`、
  `claim_rewards_promptly=true`

**### ✅ 情报任务状态（第六轮更新，2026-09-14 17:00）：**已做完，自动化接管**

- 情报列表已排空（真机 3 轮 `intel_not_available`，exit 0）；最后一个巨兽已派出（体力 295）。
- 下批任务 **~23:51**（真机倒计时 `下次刷新：06:56:37`）。
- **常驻自动化**「Winter V2 情报循环（每小时）」：每小时跑 `tools/run_intel_loop.py 6`，
  新任务自动打、奖励自动领，无需人工。
  ⚠️ **第九轮更正**：旧 handoff 记的那个自动化 id **查不到（not found）**，等于那段时间
  **没有任何无人值守在运行**。第九轮已重建，当前 id
  **`7c1c18c1-94ca-4051-a2ca-7a1614cb3979`**（ACTIVE，每小时）。
  **判断自动化是否存在只能用自动化接口查询，不要只信本文档。**
- 顺手修复 `parse_stamina_number` 丢位（295 被读成 29，OCR 碎片 `'29'+'9'+'5'`），
  已几何合并 + fixture 回归（见 05 第六轮）。**第九轮又回到这一处并改进了算法**：
  现在的规则是「真值 = 包含全部碎片的最短字符串」，并移除了第九轮中途试错的「放大裁剪」方案
  （它修好 166/189 却把 295 拆坏）。
- **情报做完后，按排序公式下一项是 `SEMANTIC_TARGET_NOT_VERIFIED` x104 家族**
  （SELECT_RESOURCE 40 / SEARCH_RESOURCE 32 / OPEN_MAIL 13，见 01_CURRENT_TRUTH）。

**两个卡点已于 2026-09-14 解决，并留下真机证据**（旧描述见文末历史区）。

##### ① 体力已可在地图上观测（整条策略的前提）

- `ocr.py` 新增 `HUD_STAMINA_ROI`，读地图 HUD 上的领主体力数值。ROI 是**测量**出来的
  （`tools/calibrate_hud_stamina.py` 直接打印 OCR token box，不靠目测）：
  x 0.046–0.089、y 0.080–0.091（720×1280），中心 (49,110)。
- **必须单独对这一小块做 OCR**：实测全屏 OCR 会漏掉这个小组件——同一帧的全屏 token 里
  根本没有它，而裁剪成 ROI 后以 **0.999** 置信度读出 `350`。原因写进代码注释了。
- 真机读数：领取前 `200`，领取后 `350`（地图显示当前值，不封顶）。
- 结果：`AVOID_STAMINA_WASTE` 现在能在地图上被发现，`stamina_first` 才有意义。

##### ② 撤回已可调度：4 个新技能，全部带 verifier

| 技能 | 动作 | verifier |
|---|---|---|
| `OPEN_STAMINA_SOURCES` | 点地图体力条 → 打开「获取更多」面板 | `STAMINA_SOURCES_OPEN` |
| `CLAIM_FREE_STAMINA` | 点面板里**免费的**「领取」 | `FREE_STAMINA_CLAIMED` |
| `SELECT_MARCH_TO_RECALL` | 点行军队列第 1 行 → 打开召回确认框 | `MARCH_RECALL_DIALOG_OPEN` |
| `RECALL_MARCH` | 点确认框的「确定」 | `MARCH_RECALLED` |

**实测纠正了一个错误假设**：撤回**不会立刻释放槽位**——确认后队列仍是 6/6，该行变成
「返回中」，槽位在部队回城后才释放（实测 13:53 = 6/6 → 14:06 = 5/6）。技能原本声明的
`NORMAL_IDLE_SLOT_INCREASED` 会**判掉一次正确的撤回**，已改为状态迁移判定。

**免费体力在哪**：面板里只有一行免费（「丰盛的招待」+ 裸露的 `领取`，旁边没有任何价格），
其余都带价（`购买并使用 💎300`、超值月卡、礼包购买、英雄集结「前往」）。付费控件已登记为
**负向对照模板**，并有测试断言没有任何技能把它当目标。

##### NEW: 下一轮第一动作（按顺序）

1. **行军计数会被覆盖层遮挡**：巨兽目标面板会盖住 HUD 上的 `x/y` 计数，此时
   `march_used=None`。这是**诚实返回 unknown**（旧代码在这种帧上会谎报 1/6，等于 5 个假空闲槽）。
   后果：计数未知 → `idle_marches=None` → 派兵和撤回都无法决策。
   证据帧 `dataset/raw/control_panel/probe/state_now.png`。
   下一步：把该面板识别为地图覆盖层并优先关闭，或改从行军列表行数推导计数。
2. **「下次补给」倒计时没有持久化**：面板上写着 `下次补给 04:52:52`，存下来就能在到期前
   跳过检查；现在每次运行都要开一次面板确认，白花 2 个动作。
3. `DISPATCH_NOT_PROVEN` x28 根因仍未定位。

#### 已经可以直接做的（不需要上面两项）

- **情报任务**：INTEL 全链已在 `VERIFIED_ATOMIC`（`OPEN_INTEL` 94% 真实成功率）。
  `run_live.py --goal INTEL` 现在就能跑。
- **打巨兽**：`SELECT_BEAST_TARGET` / `BEAST_HUNT` / `DISPATCH_BEAST` 都可调度。
  `run_live.py --goal BEAST_HUNT`。
- **奖励领取**：MAIL / DAILY / INTEL / EXPLORATION / ALLIANCE 的 claim 技能大多可调度。

> 注意：`march_policy.reserve_for_stamina: 2` 之后，当地图上空闲行军 ≤2 时，
> 大脑会返回 `SAFE_STOP reserved_march_for_stamina`——这是**正确行为**，
> 不是缺陷。它保证槽位留给体力任务。

---

### 旧判断（仍然有效，但优先级低于上面）

**为什么「补齐缺失技能」是长期最高价值**

2026-09-14 用新的能力模型核实后的结论：

- `NEVER_TRIED` 的 Goal = **0 个**。旧文档怀疑的 5 个（Arena / Labyrinth / Event /
  AllianceTimed / Bear）**不是「没试过」，而是「没有实现」**——它们要求的技能
  在注册表里根本不存在，只在 `knowledge/skills/candidate/*.json` 里有设计稿。
- 因此继续在采集链路上打磨收益递减；真正卡住 4 个 BLOCKED Goal 的，是同一小批缺失技能。
- 反过来，采集链路**必须**先守住：它是当前唯一每天真实运行的产出。

所以并行两条线：
1. **守住** 已 Live 的链路（Intel / Mail / Train / 采集），不要回归；
2. **补齐** 缺失技能，把 BLOCKED Goal 变成 PARTIAL → FULLY_LIVE_VERIFIED。

### 缺失技能清单（按 blocked_goals 排序，来自 capability_skill_map.json）

- `CHECK_ALLIANCE_EVENT`  → 卡 PARTICIPATE_BEAR + ALLIANCE_TIMED_EVENTS
- `READ_BEAR_TIMER`       → 卡 PARTICIPATE_BEAR + ALLIANCE_TIMED_EVENTS
- `CLAIM_EVENT_TIER`      → 卡 EVENT_MINIMUM_GUARANTEE + ALLIANCE_TIMED_EVENTS
- `JOIN_RALLY` / `START_RALLY` → 卡 PARTICIPATE_BEAR + AVOID_STAMINA_WASTE
- `OPEN_ARENA` `READ_FREE_ATTEMPTS` `SELECT_ARENA_OPPONENT` `START_ARENA`
  `VERIFY_ARENA_RESULT` → 卡 USE_FREE_ARENA_ATTEMPTS
- `OPEN_LABYRINTH` `READ_LABYRINTH_ATTEMPTS` `START_LABYRINTH`
  `VERIFY_LABYRINTH_RESULT` → 卡 LABYRINTH_DAILY
- `OPEN_EVENT` `READ_EVENT_PROGRESS` `READ_EVENT_TIMER` → 卡 EVENT_MINIMUM_GUARANTEE
- `OPEN_RESEARCH` → 卡 KEEP_RESEARCH_PRODUCTIVE（`RESEARCH` 本身已注册但为 BLOCKED）

### 坑（必须知道）

0. **这个项目的文件被两个地方同时编辑，外部编辑器会把旧缓冲区刷回磁盘，悄悄吃掉刚写入的改动。**
   本轮就中过招：`models.py` 的 `stamina` 字段、`brain.py` 的两条弹窗分支、`runtime.py` 的
   `resolve` 分支、`tests/test_ocr.py` 的辅助类都曾被无声还原。**症状极具迷惑性**：
   `grep` 能找到某处出现，但运行时报 `TypeError`/`NameError`，或某个分支干脆不生效。
   对策（必须照做）：
   - 改完代码立刻跑 `"E:/dongri-mumu-bot/.venv/Scripts/python.exe" tools/check_wiring.py`
     —— 它做的是**执行级**校验（导入对象、对真实 WorldState 真的调用 `RuleBrain.decide`），
     而不是字符串匹配。`problems: 0` 才算通过。
   - 校验通过后**立刻 `git commit`**，用 git 作为可恢复基线。
   - 跑测试前再跑一次校验；测试期间不要编辑被测试的文件。

1. **跑真机验证前先清 `__pycache__`。** 编辑器回写时可能带上较旧的 mtime，
   使 Python 认为旧的 `.pyc` 仍然有效 → **运行的是已回滚的字节码**（本轮表现为
   `OPEN_INTEL` 用了 `verify_stamina_sources_open`、免费体力检查不触发，而磁盘上的代码是对的）。
   固定流程：清 `__pycache__` → `tools/check_wiring.py` 显示 `problems: 0` → 立刻跑真机。
2. **不要用「模板没匹配」推断页面语义。** 模板会整体过期（本轮 `BTN_BEAST_START_MARCH`
   距离 30、`BTN_BEAST_DISPATCH` 距离 36，而点击坐标其实是对的）。
   要判定「空 / 无任务 / 不可用」这类语义，必须有**独立的正向证据**
   （例：情报空列表用 OCR 的 `下次刷新` 头行 + 无 `前往查看`）。

3. **跑全量测试要加 `--basetemp`**：默认临时目录在 `%TEMP%\pytest-of-*`，
   跑完清理时会被工作区的**批量删除安全钩子**拦下（69 个文件 > 阈值 50），
   进程被中断、拿不到汇总行（测试其实已经跑完）。用：
   `"E:/dongri-mumu-bot/.venv/Scripts/python.exe" -m pytest tests -q --basetemp="E:/无尽冬日智能体/tools/_pt_tmp"`

4. **不要写死坐标。** 资源页签带会滚动，客户端会把当前选中页签重新居中。
   已经实测到多种滚动偏移（0、+400px，以及 MEAT 落在 0.4993 的第三种）。
   必须走 `SemanticROIVision.selected_resource` 的白色角标锚点 + 相对布局。
5. **`run_live.py` 与 `control_panel.py` 传入的 vision 对象不是同一种。**
   用 `LiveRuntime._semantic` 访问器，不要直接 `self.semantic_vision.semantic`。
6. **新增 Skill 必须同时提供 verifier**，否则 `LiveRuntime.VERIFIED_ATOMIC` 不含它，
   就永远不会被 live loop 调度（`capability_coverage` 会把它算成「未实现」）。
7. **不要用通配符批量删文件。** 项目目录曾经不是 git 仓库；现在已经有了，
   但删除前仍必须逐项确认。
8. Bash 工具在本机**没有 coreutils**（`ls/cat/head/sleep/wc/date` 都不可用），
   PowerShell 工具**stdout 不回传**。所有命令都用
   `"E:/dongri-mumu-bot/.venv/Scripts/python.exe" -c "..."` 配合重定向 + Read 读取。
9. **等级筛选器范围是 1..8，不是 1..27。** 真机实测 1→4→8 后停在 8。
   `RESOURCE_NOT_FOUND` 不是等级问题，是「该资源当前范围内没有可采节点」。
   正确补救是**换资源**（`ResourceRotationStore.unavailable()`），不是降等级。
10. **升级/等待类操作要看清页面语义**：采集编队页的正确动作是
   `DISPATCH_MARCH`，不是 `WAIT`（`WAIT` 只用于维护/加载画面）。
11. **模板自匹配是循环论证：d=0 不能证明坐标对。** 从错误位置裁出的模板再拿去匹配同一帧，
    永远返回 d=0。必须用**独立信号**验证：颜色分割 / 把点击点画在帧上目视复核 / 负向对照帧。
    本日事故：`BTN_HERO_FIGHT` 裁高了 **103px**（落在英雄头像行），三次真机运行、7 点位扫描、
    90 秒观察全部被误导，最终靠画点击点叠加图才暴露；修正坐标后一击即胜。
    **注册任何点击类模板后，必须画框复核一次。**
12. **带反引号/引号的内容绝不要经 `bash -c` 写文件**（Python 源码字符串里的反引号会被
    shell 当命令替换吃掉，静默丢内容）。一律用 Write/Edit 工具写。

### 真机环境（当前实测）

- MuMu 默认不启动。启动：
  `"D:/Program Files/Netease/MuMu Player 12/nx_main/MuMuManager.exe" control -v 0 launch -pkg com.gof.china`
  然后 `adb connect 127.0.0.1:7555`。
- 真机可用时：720×1280，前台包 `com.gof.china`。
- 跑项目脚本必须用项目 venv：`E:\dongri-mumu-bot\.venv\Scripts\python.exe`（含 PIL / rapidocr）。
  托管 Python 3.13 **没有 PIL**。
- 脚本里**不要用 `date`/`head`/`tail`** 之类外部命令（不存在）。
- 验收扫描：`tools/run_gather_acceptance.py --runs N`，每轮约 1–2 分钟。
