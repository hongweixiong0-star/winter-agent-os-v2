# GAME KNOWLEDGE — 用户明确策略 + 已确认的游戏知识

> **本文件是汇总副本，不是事实源。**
>
> - **实体事实**（某个东西是什么、有多少、叫什么）的权威来源是 `knowledge/game/*.json`。
>   指针表见 `knowledge/game/_index.json`，其原文规则：
>   > 「`knowledge/game/*.json` 是实体事实的权威来源（canonical）。domain 目录
>   > （combat / resources / alliance / heroes / events / strategy）只放决策口径与机制卡。
>   > 两者冲突时以 `knowledge/game/*.json` 为准，并回头修正机制卡。」
> - **用户明确策略**的权威来源是**操作者自己名字下的那份文件**，
>   通常是 `operator_policy` 块（`OPERATOR_POLICY_CONFIRMED`）或
>   `.workbuddy-ai/commander/WORKBUDDY_AUTONOMOUS_DEVELOPMENT_FINAL.md` 的对应节。
> - 本文件**不新增任何规则**，**不得**被当成第二套事实源或优先级体系
>   （依据 `knowledge/research/RESEARCH_CHARTER.json` 的 `single_source_of_truth_rule`
>   与 `.workbuddy-ai/handoff/00_MASTER_RULES.md` §18b 记忆写入路由）。
>
> 整理时间：2026-10-05。凡下面出现具体数字的地方，都标了它来自哪个文件；要引用请回原文件确认。

---

## 第一部分 · 用户明确策略（不得自行更改）

总指令 §69 逐字规定，以下这些**需要用户明确确认才能改变**：

> 真钱策略 / 资源消费政策 / 不可逆账号行为 / Fishing ONLY NORMAL BAIT / 其他用户明确固定策略
>
> 这些之外：开发、调试、代码修复、生产接线、低风险真机验证、Skill修复、Verifier补齐、
> Scheduler修复、Learning修复 —— **自主进行**。

也就是说：`GAME_KNOWLEDGE.md` 的第一部分是「只读」的，开发侧不能顺手动它。

### 1.1 零氪原则（F2P_CONSERVATIVE）

| 项 | 内容 |
|---|---|
| 策略名 | `F2P_CONSERVATIVE` |
| 权威 | `knowledge/strategy/goal_library_v1.json`（`"policy": "F2P_CONSERVATIVE"`，status `REVIEWED`，`source: USER_PROVIDED_GOAL_LIBRARY_2026-09-09`） |
| 一句话 | **钻石是稀缺、不可再生的；时间是可再生的。任何「花钻石换时间 / 换分数」的自动化都不值得做。** |
| 机制卡 | `knowledge/resources/mechanism_cards.json` → `DIAMOND_POLICY`（status `CONFIRMED`）：<br>「**自动化默认禁止消耗钻石**。F2P_CONSERVATIVE 策略下，任何「花钻石换时间」的自动化都不值得做——它把可再生的等待时间换成了不可再生的稀缺资源。真机若出现钻石购买弹窗，属于 REAL_MONEY_PAYMENT 硬边界，只按一次系统返回并交给 verifier 判定。」 |
| 判定准则 | `knowledge/strategy/worth_it_rubric.json` → 「钻石默认不消耗」：`how_far = 不消耗`；`not_worth_when = 任何「花钻石换时间/换分数」的自动化` |

配套的硬边界（`goal_library_v1.json` → `invariants`）：

```
LIVE_CLIENT_IS_FINAL_UI_FACT      UI 事实以真机客户端为准
GOAL_DECIDES_WHAT_SKILL_DECIDES_HOW  Goal 决定做什么，Skill 决定怎么做
ONE_SCHEDULER_ONLY                只有一个 Scheduler
CLICK_IS_NOT_COMPLETION           点了不等于成了
BLOCKED_GOAL_MUST_NOT_BLOCK_AGENT 一个目标被阻塞不得阻塞整个 agent
REAL_MONEY_FORBIDDEN              禁止真钱
RED_DOT_IS_DISCOVERY_NOT_AUTHORIZATION 红点是「发现」，不是「授权」
ELIGIBLE_CANDIDATE_MUST_ENTER_REAL_ATTEMPT_POOL
CANDIDATE_READY_5_CYCLES_FORCES_ONE_EXPLORATION_ATTEMPT
```

### 1.2 商店购买规则（三家）

**完整规则、实测状态、UI 路径见 [`docs/STORE_POLICY.md`](STORE_POLICY.md)。**
这里只放不可自行更改的那一层「裁决表」，且**权威仍是对应的 `operator_policy`**：

| 商店 | 权威文件 | BUY | SKIP | 免费刷新 | 钻石刷新 |
|---|---|---|---|---|---|
| 游荡商人 | `knowledge/skills/VISIT_WANDERING_MERCHANT.json` | 资源换资源；**钻石换统帅经验** | 其它钻石报价 | 3 / 天 | 禁止 |
| 神秘商店 | `knowledge/skills/VISIT_MYSTERY_SHOP.json` | 名称含 `英雄组件自选箱` **且** 折扣 = 50% | 其它一切 | 1 / 天（有艾格尼丝 5 / 天） | 禁止 |
| 联盟商店 | `knowledge/skills/VISIT_ALLIANCE_SHOP.json` | 名称含 `统帅经验` | 其它一切 | 无（自刷新） | 禁止 |

三家共同：规则未覆盖 → `STOP_AND_ASK`；一律不点付费刷新；
卡片本身不印物品名，名字只能从卡片自己的 `确定购买` 弹窗里读。

> ⚠️ 只有一条 BUY 分支被真机证实过：游荡商人「钻石换统帅经验」（两次，钱包精确变动）。
> 另外三条 BUY **裁决触发过、花钱路径从未走完**。见 `STORE_POLICY.md` §4.2。

### 1.3 钓鱼：只用普通饵

**权威**：`WORKBUDDY_AUTONOMOUS_DEVELOPMENT_FINAL.md` §40「Fishing固定策略」，逐字如下：

```
Fishing Tournament：ONLY NORMAL BAIT

禁止：special bait / special mode / treasure mode / tickets / gems / real money

Realtime Fishing：UI-Venus = 0/frame，OCR = 0/frame，Global Scheduler = 0/frame

保持实时控制本地化。
```

要点：

- **普通饵是唯一允许的**。特殊饵、特殊模式、寻宝模式、门票、钻石、真钱全部禁止。
- **实时钓鱼期间算力本地化**：这 0/frame 的三条不是「尽量少」，是「不许占用」——
  实时控制必须留在本地闭环里。
- 这条在 §69 里被点名，属于**不能自行更改**的那一类。

### 1.4 其它明确策略（指针）

| 策略 | 权威位置 |
|---|---|
| 免费领取永远值得做（领到无可领为止） | `worth_it_rubric.json` → worth_it_rules |
| 每日次数类动作做到上限即止（`NOT_AVAILABLE` 是正常终态，应 Skip 而非 Retry） | 同上 |
| 队列空转优先于单次收益最优（宁可降级采集也不要空转） | 同上 |
| 体力消耗需先判断胜算（只打客户端显示「胜券在握」的目标；体力未知时 `OBSERVE_NO_SPEND`） | 同上 |
| 集结值得「不带英雄也加入」（英雄兜底顺序 杰西→书允→杰赛尔→NO_HERO） | 同上；`knowledge/game/bear.json` |
| 普通加速允许自主使用，但不为「让队列好看」而加速 | `knowledge/resources/mechanism_cards.json` → `SPEEDUP_USAGE` |
| 活动只做保底、不追榜 | `knowledge/events/mechanism_cards.json` |

---

## 第二部分 · 已确认的游戏知识

### 2.1 证据权威层级（`RESEARCH_CHARTER.json` → `authority_tiers.order`）

判断一条游戏事实可不可信，先看它在哪一层。**上层的证据可以推翻下层的记录。**

```
LIVE_CLIENT            ← 真机客户端读数（最高）
OFFICIAL               ← 官方说明 / 帮助中心
MULTI_SOURCE_CONFIRMED ← 多来源互相印证
WOS_FORGE / COMMUNITY_DB
MATURE_OPEN_SOURCE_WOS_BOT
PLAYER_GUIDE / VIDEO
LEGACY                 ← 本项目早期文本（可能已过期）
UNKNOWN
```

两条纪律：

1. **`LIVE_CLIENT > 一切`**，而且**真机会推翻旧的项目文本**（下面情报那节就是活例）。
2. **`UNKNOWN` 不等于「没有」**。识别不到就是 UNKNOWN，不得当成「空 / 没有 / 可点」。

### 2.2 角色

| 项 | 值 |
|---|---|
| 主角色 | `1063040265`，`[ioi]零氪纯盾流`（零氪纯盾流；大熔炉 30 级） |
| 第二角色 | `1061663148`，`[DIW]xhw`（战力约 8243.4 万） |
| 王国 | 4298 |
| 权威 | `knowledge/roles/role_inventory.json`；`knowledge/skills/ROLE_SWITCH_RESEARCH.md` |

零氪角色名字本身就写着策略：**零氪**。这解释了为什么 §1.1 的钻石政策在这个账号上是硬约束
而不是「偏好」。

### 2.3 情报 / 灯塔（INTEL）

**权威**：`knowledge/game/intel.json`（gate `REVIEWED`，9,343 B）

| 项 | 值 |
|---|---|
| 名称 | 情报（别名 灯塔 / Intel / Intel Missions） |
| 入口 | `MAP/LIGHTHOUSE_HUD` → 页面 `INTEL` |
| 任务类型 | `beast hunt` / `survivor rescue` / `hero journey` / `master bounty` |
| 领取 | 完成的任务一键领取 |
| 不可用语义 | `NOT_AVAILABLE`（不是失败） |
| 真机读数 | `searchlight_level 20`、`latest_stamina 161`、普通野兽 10/10/10（尝试/成功/领取） |

**状态枚举（`state_enum`）**：

```
AVAILABLE · IN_PROGRESS · COMPLETED · CLAIMABLE · NOT_AVAILABLE · EXPIRED · UNKNOWN · BLOCKED
```

> 记录里写明：「State values remain distinct; **BLOCKED is never reported as FAILED or DONE**.」

**四种任务的真机事实**：

| 记录 | 任务 | 体力 | 备注 |
|---|---|---|---|
| `INTEL_FIREBEAST_10` | 狩猎炽红巨兽 | 10 | 推荐战力 1,467,020；走 verifier 门控的野兽编队/派遣链 |
| `INTEL_RESCUE_SURVIVORS_10` | 营救幸存者 | 12 | 立即营救动作；真机证据含 in-progress → claimable → 奖励 → 清除 |
| `INTEL_HERO_JOURNEY_10` | 英雄之旅 | 10 | **不要走普通野兽情报的路线** —— 营地面板把它分类为 EXPLORATION，不是 BEAST。实测 boss 战力 6,654,991 对推荐 95.7 万，打得过 |
| `INTEL_MASTER_BOUNTY_20` | 大师悬赏：20号 | 10 | 推荐战力 189,295,920 对角色约 5,608 万 —— **status: BLOCKED**，未派遣 |

**⚠️ 颜色不是「可领」信号** —— 这是本项目被真机推翻过、必须记住的一条：

> 早期项目文本声称 `ORANGE = 已完成 / 可领`。2026-09-14 真机**两次**反驳：
> 一个橙色 pin（211,664）开出 `大师悬赏：20号`（`INTEL_MASTER_BOUNTY`，status **BLOCKED**，
> 是个可操作目标而不是奖励）；另一个橙色 pin（215,611）开出英雄之旅卡片。
> **每种颜色编码什么，是 UNKNOWN —— 不要猜，不要从颜色判；从大脑读到的卡片判。**
> pin 本身是了解任务身份的唯一途径（板子在点击前不透露类型）。

补充两条：

- **颜色覆盖曾被更正（2026-09-20，open issue #68）**：早期列的表面上是 BLUE/PURPLE/ORANGE，
  但那只是 `intel_pins.py` 当时只 mask 了这三种 —— 记录描述的是**检测器**，不是**板子**。
  实测板上还有 GREEN（(541,399)、(210,614)）与 GREY/银（(104,593)、(344,765)）水滴针，
  同样的针体、同样的白色针头图标、同样的橙色底环，只有针体颜色不同。**检测器返回 4，实际有 9 个标记。**
  要避的假阳性是页面标题 `情报` 本身（灰色掩膜，blob 166×171，fill 0.32）。
- **同一任务的横幅颜色会跨帧变化**：同一个英雄之旅卡片在 13:56 读成 `UNKNOWN`、
  14:00 读成 `INTEL_HERO_JOURNEY`。所以按一种横幅颜色裁出来的模板匹配不到另一种。

**⚠️「本轮打完」≠「今天做完了」** —— `intel.json` → `round_state` 整块都在讲这件事：

> 观测 2026-09-20T14:48:53Z，状态 `ROUND_CLEARED_AWAITING_REFRESH`：
> 「本轮的板子已经打不动了 —— 不是「今天的情报做完了」。agent 必须在下一次刷新后重新检查，
> **不得**把这个状态读成 `CLEAR_INTEL=COMPLETE` 并永久收工。」

机制来源也要记住：

- `untried_pins=1` 的含义是「本轮还没点过」，**不是「打得过」**；
  那个 pin 点过之后仍留在板上（pin 在任务被消耗后不消失），所以会被反复算作「还有情报」，
  但开出的是 BLOCKED 任务 —— 这正是本轮 `goal_progress` 恒为 false 的机制来源。
- 正确处理方式**已经是对的，不要改成「永久完成」**：`capability_gate` 把 `CLEAR_INTEL`
  判成 `DEFERRED`（`NO_GOAL_PROGRESS`，源 `READ_INTEL_LIST`），DEFERRED 走
  `no_progress_probe_minutes=30` 的探测窗，窗口一过自动放行重新观察。
  **「等待刷新」是自动的，唯一要防的是把它写死成 COMPLETE。**

### 2.4 日常任务与活跃度

**权威**：`knowledge/game/daily.json`（gate `REVIEWED`，12,148 B）；
读取 Skill：`knowledge/skills/READ_DAILY_PROGRESS.json`

**活跃度里程碑**（实测 `claimed_milestones`）：

```
40 · 80 · 120 · 160 · 215 · 270 · 325
```

出处：`knowledge/skills/READ_DAILY_PROGRESS.json` 的 `measured` 字段，
标签源 `tests/replay/labels.json`（`claimed_milestones [40,80,120,160,215,270]`，`next_milestone 325`）。
同一条里还有一条**读数字的教训**：模板层曾在真机帧上把活跃度读成 70，
而**帧上明明写着 270**；OCR 层读到 270，merge 让 270 胜出。
→ **HUD/面板上的数字不能只信模板层**，这正是机制卡「读 HUD 小数字必须单独裁剪 ROI」的实例。

**已实测的任务（真机 VERIFIED）**：

| 任务 | 进度 → | 活跃度 | 其它奖励 | 备注 |
|---|---|---|---|---|
| 完成1次英雄招募 | 0/1 → 1/1 CLAIMABLE | **+10** | 煤 800、铁 200 | `cost: FREE_RECRUIT`；重复版为「完成3次英雄招募」 |
| 每日任务一键领取 | claimable 3 → 0 | **+65** | 生肉 28,000、煤 800、铁 200 | 打开了 40 里程碑 |
| 完成联盟捐献5次 | 3/5 → 5/5 CLAIMABLE | **+5** | 木材 4,000 | linked_skill `ALLIANCE_TECH_CONTRIBUTE` |

**每日任务清单现场观察**（`DAILY_TASK_CATALOG_LIVE_20260928`，2026-09-28，活跃度 185，
刷新倒计时 14:06:07）里看到的行：完成联盟捐献5次 / 完成3次英雄招募 / 处理5次情报线索 /
在仓库领取3次补给 / 研究1次科技 / 击败冰原巨兽2次 / 进行1次竞技场挑战 /
成功分享1次传说英雄·满级宠物·执政官 / 进行1次探险挑战 / 每日登录 / 联盟互助20次 /
训练30个盾兵·矛兵·射手 / 采集250,000生肉·木材 / 采集4次。

**日常的重复任务清单**（`DAILY_ROUTINE`）：
`INTEL · ALLIANCE_HELP · ALLIANCE_TECH · MAIL · VIP · TRAINING · GATHER_RESOURCE · HERO_RECRUIT`。

> **重要限制**：「只有被单独真机验证过的任务变体才可执行。付费任务留在常规选择之外。」
> （原文：`Only individually live-verified task variants are executable. Paid tasks remain outside normal selection.`）

**已实测的免费领取**：

| 记录 | 内容 |
|---|---|
| `DAILY_TRAVEL_SUPPLY_FREE_REFILL_LIVE_1063040265` | 游历补给免费领取：每次 **10** 个；文案「每日 8:00 和 16:00，可手动领取 10 个游历补给」；实测 63 → 73（delta 10）；同时可见一个**付费**报价（钻石 1000，`4/4`）—— **未操作**，且该事实不得拷贝到别的角色 |
| `GROWTH_INFERMARY_LEVEL_23_LIVE_1063040265` | 主线「将军医所升到23级」22/23 → IN_PROGRESS，剩余 17:43:04；期间租了 2 天第二建造队列（**1000 钻石**）—— 明确标注 `role_scope: CURRENT_TEST_ALT_ONLY`，**不得**在没有当次政策的情况下复用到另一个角色 |

### 2.5 联盟

**权威**：`knowledge/game/alliance.json`；机制卡 `knowledge/alliance/mechanism_cards.json`

真机数值：**

- **联盟币 2000 / 2000**
- **科技捐献 10,000 生肉**；**基数 120，暴击 ×2 = 240**，实测 delta 序列 `[240,120,240,120,240]`
- 「**捐到每日次数上限即止**」——超出上限的部分既不给活跃度也不给贡献，属于纯浪费

### 2.6 资源与货币

**权威**：`knowledge/game/resources.json`

资源实体：`MEAT`（生肉）· `WOOD`（木材）· `COAL`（煤矿）· `IRON`（铁矿）· `STEEL`（钢）·
`GEMS`（钻石）· `FIRE_CRYSTAL`（火晶）· `SPEEDUP`（加速）· `HERO_SHARD`（英雄碎片）。

- **四种基础资源**（生肉/木材/煤矿/铁矿）有城内生产 + 世界采集双来源，HUD 常驻显示。
- **采集等级**：等级越高单趟收益越高，但可选目标越少。实测 22 次失败里 19 次发生在 level 7–8，
  说明高等级筛选经常返回**空**。
  → **`RESOURCE_NOT_FOUND` 是「换条件」信号**，不是「降级以外的失败」。空队列的损失远大于
  「只采到低等级」的损失，所以**宁可降级采集也不要空转**。
- **加速**（`SPEEDUP_USAGE`）：普通加速允许自主使用；但不值得为了「让队列好看」而加速低价值任务 ——
  优先加速**卡住后续 P0 Goal 的那一环**，而不是剩余时间最长的那一环。**加速是手段不是目的。**
- **社区 20:20:4:1 比例不是通用生产规则，未被采纳**（`knowledge/strategy/resource_priority.json`）。

### 2.7 行军 / 战斗 / 巨熊（指针）

| 主题 | 权威文件 |
|---|---|
| 行军状态枚举 | `knowledge/game/marches.json` —— `IDLE · MARCHING · GATHERING · RETURNING · UNKNOWN` |
| 普通野兽 | `knowledge/game/beasts.json`（真机体力显示 10，实际 7） |
| 冰原巨兽 | `knowledge/game/giant_beasts.json`（confidence 0.62，**未验证**） |
| 巨熊行动 | `knowledge/game/bear.json`（车头/车身策略、加入规则、英雄兜底） |
| 兵种 | `knowledge/game/troops.json`（盾/矛/射；真机 `camp_level 30` / `tier 10` 晋升门槛） |
| 建筑 / 科研 | `knowledge/game/buildings.json` / `knowledge/game/research.json` |
| 英雄名册 | `knowledge/game/heroes.json`（⚠️ **非全集，仅 5 条**） |

### 2.8 页面与交互模型

| 主题 | 权威文件 | 要点 |
|---|---|---|
| 页面枚举 | `knowledge/ui/pages.json` | 23 个页面 + `state_policy`：**`unknown → NO_CLICK`**；识别顺序 `TEMPLATE → OCR → DETECTOR → QWEN` |
| 语义词典 | `knowledge/ui/semantic_dictionary.json` | 26 KB，最大的 UI 事实库 |
| 语义台账（派生） | `knowledge/ui/generic_semantics.json` | 230 个模板语义 + 39 个无视觉证据的候选；缺的字段一律 UNKNOWN |
| 导航矩阵（派生） | `knowledge/ui/navigation_matrix.json` | 96 个技能的「源页面→动作→目标→可调度性→verifier→视觉证据」 |

**`unknown → NO_CLICK`** 是必须遵守的硬规则：识别不到状态时**不许点**。

### 2.9 两个必须分清的东西

| 别搞混 | 分辨依据 |
|---|---|
| `英雄经验` ≠ `统帅经验` | 两个药瓶**只差一个字**；联盟商店的 BUY 只认 `统帅经验`，`英雄经验` 绝不能算 |
| 「点了」≠「成了」 | `CLICK_IS_NOT_COMPLETION`；购买是**两次**点击，只有钱包数字能证明钱真的动了 |
| 「本轮打完」≠「做完了」 | 见 §2.3 情报 `round_state` |
| 「检测器返回空」≠「板子是空的」 | 检测器静默丢掉真 pin，会让满板读成空板，然后 Goal 自称完成（已出现三次） |
| 「红点亮」≠「授权了」 | `RED_DOT_IS_DISCOVERY_NOT_AUTHORIZATION` |

---

## 附：本文件的维护约定

1. **只在原文件变更后同步过来**，不要在本文件里独立编辑事实。
2. 新增一条游戏知识时，先在 `knowledge/game/*.json`（实体）或对应机制卡（口径）里落下来，
   再来这里加指针。**顺序不能反。**
3. 任何标 `UNKNOWN` 的字段都不要在本文件里「补全」成看起来确定的说法。
4. 本文件不承载任何裁决逻辑；裁决在技能文件与 `knowledge/strategy/*.json` 里。
