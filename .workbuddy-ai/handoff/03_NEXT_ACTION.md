# 03 — NEXT ACTION

> 本文件必须保持**短小、具体**。目标：新账号不读完整历史也能继续当前任务。
> `AUTO:next_action` 块由 `tools/update_workbuddy_handoff.py` 重写；
> 其余手写内容不会被自动覆盖。

## 手写：本轮（2026-09-17 12:1x–13:0x GMT+8）—— 打开 #22（奖励弹窗来源）；终止页退出落地但**真机 episode 未取到**；工作队列按 CAPABILITY-FIRST 重建

接手时 `HEAD == origin/main == ac694ee8`，工作树 8 项脏（KEEP 3 / UNKNOWN 5）。旧 `WORK_QUEUE.json`
是 09-16 的 R19 版，按指令**不执行其 READY 项**，已归档为
`.workbuddy-ai/commander/WORK_QUEUE_20260916_R19_ARCHIVED.json` 并**重写**为 CAPABILITY-FIRST 队列
（8 单：INTEL 巨兽目标 / EXIT_CONFIRM 安全 / 建筑身份 / 叶页真机证据 / 训练两阶段 / ALLIANCE_HELP / ARENA / 机会型）。

### 一、#22 已修（**真机已验证**）：奖励弹窗的来源不在画面里

**根因不是阈值，是问错了问题。** `POPUP_DAILY_REWARD_CURRENT` 的 ROI 是 `x .08 y .20 w .84 h .40`
= **整个奖励格区域**，它回答"这些图标像不像我裁下来的那批"（**内容**问题），却被排在通用横幅之前。

在 **103 帧有标签的生产帧**上量四个总体（`SemanticWorldVision`，`max_distance=8`）：

| 语义 | DAILY(8) | EXPLOR(12) | GENERIC(65) | INTEL(18) |
|---|---:|---:|---:|---:|
| `BTN_DISMISS_INTEL_REWARD`（页脚） | **8/8** | **12/12** | **65/65** | **17/18** |
| `POPUP_GENERIC_REWARD_HEADER`（横幅） | 5/8 | 8/12 | 64/65 | 1/18 |
| `POPUP_DAILY_REWARD_CURRENT`（奖励格） | 8/8 | 0/12 | 0/65 | 0/18 |

只有**页脚**几乎处处在场（102/103、距离 ≤2）。且**真实每日帧与真实情报帧的页脚区域 phash=4、横幅=4**
⇒ 两帧是**同一个「获得奖励」弹窗**，只是奖励格不同。**来源不在画面里。**

修法：视觉层先判"这是共用的奖励弹窗"（横幅**或**页脚），报**目标中立**的 `GENERIC_REWARD`，
由 goal 上下文选解除技能。**没碰任何 verifier** —— 五个 `*_reward_dismissed` **早已**接受
`GENERIC_REWARD`，这正是 `verifier.py` 第 953–961 行与 `REWARD_POPUPS` 不含 `DAILY_REWARD` 的设计意图。

真机（都可追溯）：
```
04:44:20  DAILY_CLAIM_REWARDS           DAILY -> POPUP  verifier OK  after.popup=GENERIC_REWARD
04:44:29  DISMISS_DAILY_GENERIC_REWARD  POPUP -> DAILY  verifier OK
04:46:31  MAIL_CLAIM_REWARDS            MAIL  -> POPUP  verifier OK  after.popup=GENERIC_REWARD
```
`DISMISS_*_GENERIC_REWARD` **只有 `popup==GENERIC_REWARD` 时可达** ⇒ 这次修复真的生效了。
**闸门**：全语料 3007 帧，命中页脚 186 / 横幅 134，**假阳性 0**。

### 二、#23 叶页退出：**已实现，真机 episode 还没取到**

`TRAINING`/`RESEARCH` 是叶子页，上一轮 TRAIN 停在那里 ⇒ 下一轮一步都走不了就 `goal_page_mismatch`。
修法镜像 `_leave_daily_panel_once`：**命名 goal** 站在自己没有用的叶页上 → 一次 BACK
（`verify_safe_back` 接受 `TRAINING/RESEARCH → HOME`，两方向用探针量过）；自己的叶页上无事可做 →
先 BACK 再具名停止；**同一轮不再重走路线**；**拥有该页的 goal 与无 goal 的扫掠行为不变**
（可训练队列、可开始节点照旧动作 —— 这一条是第一版写宽了、被 `check_wiring` 抓住后收窄的）。

单测 12 项 + `check_wiring` 4 条（problems: 0）。**没有真机 episode**：叶页**存活很短** ——
探针刚放上去（`after#4 page=RESEARCH`），几十秒后运行起跑已读回 `HOME`（问题 #27）。
取证办法：把 goal 轮**接在同一条命令链内**，别隔一次探针。

### 三、⚠ 三件必须知道的事

1. **INTEL 链现在卡在新的一步（#25，当前真实前沿）**：04:38Z 跑了 4 步 verifier 全 OK，
   第 5 步 `OPEN_INTEL_BEAST_TARGET` 点「前往查看」后**打开的是「英雄之旅」弹窗**
   （`after.page=EXPLORATION`、`intel.mission_type=HERO_JOURNEY`），verifier
   `INTEL_BEAST_TARGET_NOT_PROVEN {mission_dialog:true, target:false}`。**不是本轮的改动造成的**，
   是这条链走到这里才第一次被看见。证据帧已归档。
2. **`EXIT_CONFIRM` 在大脑里没有分支（#26，安全缺口）**：实测该弹窗是
   「确认退出游戏吗? / 取消(橙,左) / 确定(蓝,右) / X(右上)」，而 brain 只走通用 `CLOSE_POPUP` 点 `BTN_CLOSE`。
   当次没出事（弹窗自行消失），但**这条路径不该靠运气**。
3. **训练路线出现回归信号（#28）**：兵营聚焦后**先出现教程手指**，径向菜单还没画
   ⇒ `TARGET_INFANTRY_CAMP_HIGHLIGHTED` 命中而 `BTN_OPEN_TRAINING_FROM_CAMP` 未命中
   ⇒ 大脑选 `SELECT_INFANTRY_CAMP` 去点兵营，那一下把客户端带到地图。**训练路线有两个阶段**，需分别建模。

### 四、本轮新增文件

`tools/probe_reward_popup_gate.py`（可复用的奖励弹窗负样本闸门）、
`tests/test_reward_popup_source.py`（10 项）、`tests/test_terminal_page_exit.py`（12 项）、
`dataset/truth_audit/reward_popup_source_20260917/`（README + 4 帧）。
`check_wiring.py` 新增 11 条（奖励弹窗 5 goal + 无上下文 + 5 verifier + 叶页 2 + run_live 2）。



**先读证据**：`dataset/truth_audit/power_route_20260917/README.md` 的「研究（RESEARCH）」一节
（`key/14`、`key/15`、`key/16` 三帧可复核）。

### 1. 真实改进（有真机 episode）

```
1 OPEN_POWER_OVERVIEW    HOME -> POPUP/POWER_OVERVIEW            verifier OK
2 OPEN_POWER_DETAILS     POPUP/POWER_OVERVIEW -> POWER_DETAILS   verifier OK
3 NAVIGATE_RESEARCH_LAB  POPUP/POWER_DETAILS -> HOME(科研所聚焦)   verifier OK
4 OPEN_RESEARCH          HOME(菜单已开) -> RESEARCH               verifier OK
5 SAFE_STOP              research_page_no_startable_node
```
`run_live.py --goal RESEARCH` exit 0。**还是那条「战力路线」**，只是取 `科技实力` 那一行而不是
`部队实力`（`加成总览 → 实力详情 → 科技实力 提升 → 科研所的「研究」按钮`）。

⚠ 与训练**同一模式**：路线**早已记录**（`knowledge/skills/RESEARCH_RESEARCH.md` 第 38 行，
2026-09-04 在 30 级账号上量过）、`skill_factory.GOAL_REQUIREMENTS` 早已点名要
`("OPEN_RESEARCH","RESEARCH")`、verifier 早已绑定。**缺的是真机模板 + 决策。**

### 2. 本轮修的两处（都不靠调阈值）

1. **旧 `BTN_OPEN_RESEARCH` 的 ROI 中心不在控件上**：旧记录 ROI 中心 **(536,840)**，
   而 OCR 实测「研究」按钮六边形是 **435..520 × 855..910，中心 (478,878)** ⇒
   即使匹配成功也会点偏约 **65px**（执行器点的是命中记录的 ROI 中心）。
   新裁剪 = **以按钮为圆心的 340×340**（同时吃掉按钮上的引导手指动画）。
   三次路线正样本 **0/8/8**、所有负样本含它通往的研究页**全部不命中（最近 28）**；
   旧记录在真机帧上 26–36（阈值 12）⇒ 保留无害。
2. **没有任何东西读"科研所菜单已打开"，且 RESEARCH goal 没有导航** ⇒
   只可能以 `research_entry_not_verified` 结束。现已补成四跳。
   ⚠ 城市帧里**不写** `queue_available`（隔壁训练分支硬编码了 `True`，goal library 会读成
   "队列空闲"——那是谎言；本路线只写 `menu_open`）。

### 3. 本轮**没有**声称的（重要）

**不能开始研究。** 科技研究页今天没有可开始的东西、节点/花费读数不存在、
`BTN_START_RESEARCH` **零模板**。所以以 `research_page_no_startable_node` 收尾 ——
**具名的诚实停止**（原代码是从后面所有分支掉下去、以同样停止但无理由结束）。
晋升条件已写在 `RESEARCH_RESEARCH.md`：队列空出 → 看节点的前置/花费屏 →
要求 `queue_available=true → IN_PROGRESS + timer + 期望节点`。

### 4. 下一条该做的（按价值排序）

1. **研究的"开始"那一步**（上面的晋升条件）：需要读节点选中态 + 研究按钮花费。
2. **BUILD 落地的前置**（问题 #21）：建筑身份从画面读（`BTN_BUILD_UPGRADE` 仍写死 STOREHOUSE/26/27）。
   入口已实测：`建筑实力 提升`(605,550) → 民居1 3级。
3. 问题 #22（情报奖励弹窗误读，**已复现两次**）、#23（TRAIN 结束停训练页）、#24（troop_type 恒 INFANTRY）。

## 手写：本轮（2026-09-17 07:2x–08:3x GMT+8）—— 训练路线真机跑通（7 步 → 4 步）；建筑入口找到但**没落地**；情报领到了奖励却在弹窗识别上翻车

**先读证据**：`dataset/truth_audit/power_route_20260917/README.md`（`key/` 是每态一帧，可复核，不需重测）。

### 0. 操作者要求 vs 交付

要求 = 「建筑和训练优先落地，继续，情报记得及时做」。

| 项 | 结果 |
|---|---|
| **训练（TRAIN）** | ✅ **路线 4 跳全部真机 verifier OK**，收敛为 4 步（原 7 步），exit 0 |
| **建筑（BUILD）** | ⚠️ **入口找到但故意没落地** —— 视觉还不认识那个面板，且既有分支把建筑身份写死（问题 #21）。落地会**编造建筑身份**，比不落地更糟 |
| **情报（INTEL）** | ✅⚠ **两次运行都真拿到价值**（各领一份奖励；第二次还真派出一队情报野兽、体力 237→227），但两次都停在同一处弹窗误读（问题 #22，根因已量清：`POPUP_DAILY_REWARD_CURRENT` 裁的是**整个奖励格区域**，对任何来源都命中） |

### 1. 训练路线的真实改进（有真机 episode）

```
1 OPEN_POWER_OVERVIEW    HOME -> POPUP/POWER_OVERVIEW        verifier OK
2 OPEN_POWER_DETAILS     POPUP/POWER_OVERVIEW -> POWER_DETAILS verifier OK
3 NAVIGATE_INFANTRY_CAMP POPUP/POWER_DETAILS -> HOME(camp focused) verifier OK
4 OPEN_INFANTRY_TRAINING HOME(menu_open) -> TRAINING          verifier OK
5 SAFE_STOP              training_queue_busy
```

⚠ **这条链路的决策与 verifier 2026-09-17 之前就全部存在**（`brain.py` 243–246 / 446–456、
`VERIFIED_ATOMIC` 已绑 5 个 verifier、`run_live --goal` 已收 `TRAIN`）。
**唯一断点是模板全裁自 2026-09-08 的另一个账号**（战力 5,708万 vs 今天的 82.6万、
不同头像、**城市镜头更远**）⇒ `world.training` 永为空 ⇒ 那些分支一条都不可达。
所以本轮**没有改大脑、没有改 verifier**，只换了模板 + 收了一处门禁。

⚠ **一处必须知道的自纠**：本轮第一版结论"战力入口是值依赖模板、必须重裁"是**错的**，
且已随首个提交写进 message。真相：`skills.py` 点的是 `BTN_OPEN_POWER_OVERVIEW_ICON`
（**只裁图标的既有记录**），它**今天就能命中 d=4**（09-08 账号 d=10，门禁 12）——
**"避开会变的数字"这件事早就有人做过了，只是换了名字**。我为 `BTN_OPEN_POWER_OVERVIEW`
加的那条记录**没有动作引用**，已删除并改由测试钉住事实。
真正的断点是四跳里的三个：`POPUP_POWER_OVERVIEW` / `BTN_OPEN_POWER_DETAILS` /
`POPUP_POWER_DETAILS` / `BTN_POWER_TROOP_IMPROVE`，加上兵营菜单门禁。
⇒ **教训：判定控件"坏了"之前，先找到动作真正指向的语义名。**

另一个缺陷（**真实的**，属"同一控件多种外观"）：
**兵营聚焦浮层带引导手指动画 + 呼吸光圈**：旧裁剪一次运行 7 帧只中 3 帧，
害 verifier **连刷 21 秒**（07:41:18→29→39）才通过，而浮层寿命约 2 秒 ⇒
下一步观测时已消失 ⇒ **整条路线重走一遍**。新裁剪为**以训练按钮为圆心的 300×300**
（点击落点 = 该记录 ROI 中心，执行器只有 `TAP_SEMANTIC`，没有绝对坐标动作），
一次运行 7 帧全 0–8 ⇒ verifier 第一次观测即通过 ⇒ **收敛 4 步**。

**门禁 17 → 12**（两个总体，全语料 3522 帧，`tools/probe_camp_menu_gate.py`）：
≤8 有 17 帧、≤12 有 22 帧（**抽查 OCR 全是兵营菜单帧**）、≤17 有 36 帧
—— 但 **plain HOME 帧是 16**（落进 17 里！）⇒ 保留 17 会让普通城市帧报 `menu_open`
并把训练点击送进城市。09-08 的菜单帧（新裁剪 d=18）靠**它自己的旧记录 d=0** 仍命中，故不丢召回。

### 2. 下一条该做的（按价值排序）

1. **BUILD 落地的前置**（问题 #21）：让建筑 id/level/target_level **从画面读**，
   再注册 `升级` 按钮 + verifier。今天的入口已实测：`建筑实力 提升`(605,550) → 民居1 3级。
   ⚠ 顺手会发现：该面板 `page=UNKNOWN`，`building={}`，而既有 `BTN_BUILD_UPGRADE` 分支
   **写死 STOREHOUSE/26/27** ⇒ 必须先修它，否则一注册就会**验证通过没发生的事**。
2. **每日活跃宝箱领取**（上一轮定位：只差一个"可领宝箱"帧的启用/禁用模板对）。
3. **`ALLIANCE_GIFTS` / `ALLY_GIFT_CLAIM`**（后者 11 次真机成功，可复跑刷价值）。
4. **`RECALL_MARCH`**：只差 `idle_marches==0 ∧ GATHERING 在外` 这个自然状态。
5. **问题 #22**（情报弹窗误读）、**#23**（TRAIN 结束停训练页）、**#24**（troop_type 恒为 INFANTRY）。

### 3. 环境/协作提醒（本轮新增）

- **客户端落点要留意**：`--goal TRAIN` 以 `training_queue_busy` 收尾会把客户端**留在训练页**，
  下一次换 goal 会立刻 `goal_page_mismatch`（本轮亲历）。跑下一个 goal 前先确认页；见问题 #23。
- 本机 pytest 全量仍拿不到汇总行 ⇒ 用 `-o tmp_path_retention_policy=all`
  或 `PYTEST_PLUGINS=winter_failwatch`。
- repo 仍可能有第二个写入方：改完立刻 `git log --oneline -3` 复核。
- 新探针 `tools/probe_power_route.py` 可复用：`--tap x,y` 逐跳推进、每跳留帧 + 全量 OCR token、
  `--allow-page` 显式声明"我认得这个页"、`--leave` 收尾 BACK 一次。**它只点你给的坐标。**

## 手写：上一轮（2026-09-16 23:0x–00:5x GMT+8）—— 专家包 v1.1.0 增量升级；任务面板页签切换落地

### 0. 本轮两个交付物

1. **专家包 v1.1.0**：新增 4 个技能 `github-project-sync` / `github-advisor-bridge` /
   `remote-project-review` / `commit-evidence-linking`，开工加 GIT STATE CHECK、
   加 Issue #2 上报格式、加禁止项 16/17（Git 与"外部同意≠验证"）。
   目录：`C:\Users\xhw\.workbuddy\plugins\marketplaces\my-experts\plugins\winter-agent-v2-dev`；
   `validate_expert.py` / `register_expert.py` 均已通过。
   ⚠ 技能由**宿主插件缓存**加载（`plugins\cache\my-experts\winter-agent-v2-dev\1.0.0\`）：
   若下个会话看不到新技能，确认插件是否已重新同步 —— **不要手改 cache 目录**。
2. **`SELECT_DAILY_TAB` LIVE_VERIFIED**（提交 `cb716da` 已 push）。

### 1. 本轮真实改进（有真机 episode）

| 步骤 | 技能 | 页面 | verifier | 关键读数 |
|---|---|---|---|---|
| 1 | `SELECT_DAILY_TAB` | DAILY→DAILY | **OK** | before `tab=NOT_TASKS` → after `tab=TASKS, task_id=ALLIANCE_CONTRIBUTE_5, activity=10` |
| 2 | `BACK` | DAILY→HOME | OK | 面板退出（上一轮加的守卫） |
| 3 | `SAFE_STOP` | — | — | `daily_panel_already_read_not_actionable` |

⚠ 16:33 那次运行的 `REAL_MONEY_OFFER` 是**被硬阻断正确挡下**的，不是缺陷；
那次还**真的领到一份每日奖励**（`DAILY_CLAIM_REWARDS` verifier OK：`claimable_before` +
`reward_visible`）—— 该技能**第一条可追溯真机 episode**（此前所有行来自无
`recorded_at`/截图/verifier 的旧写入器）。

### 2. 根因（一句话）与修法

`OCRPageClassifier` 用**页签栏上的字面串 `每日任务`** 判 `Page.DAILY`，
而 `OPEN_DAILY` 打开面板时停在**第一页签 章节任务**；整个 daily 技能族是在
**每日任务页签**上标定的。代价可测量：当天活动 285、三个宝箱（80/160/270）全部达标，
机器一个都看不见。

修法：把"哪个页签在显示"当**画出来的状态**读（未选中=深蓝胶囊+白字，选中=浅色胶囊+深字），
两条记录都取自**归档真机前后帧**（中间只有一次点击）。**全语料 3503 帧**：
`BTN_DAILY_TAB_TASKS` 命中 **4**、`TAB_DAILY_TASKS_SELECTED` 命中 **5**，
**全部是当天运行的面板帧，树里没有别的帧命中**。

⚠ **同类坑第三次出现（本轮现场抓到）**：第一版裁剪把整个胶囊（x 481..704）都裁进去，
**含右下角红色可领角标**（中心 ≈(688,1158) r≈9）⇒ 那次运行 13 帧里只命中 3 帧，
恰好是**没有角标**的 3 帧。这正是把 `BTN_OPEN_DAILY` 冻死 8 天的缺陷。
裁剪改为止于 x=670，**一条记录覆盖有/无角标两态**（5 帧全 d=0）。
⇒ **注册任何点击/判定模板前先问一句：这个控件会不会画角标？**

### 3. 下一条该做的

1. **每日活跃宝箱的"领取"这一步还没有技能**：三个宝箱今天已达标（285 ≥ 270）
   但**已被领取**（箱盖是开的）。链路现在是
   `OPEN_DAILY` → `SELECT_DAILY_TAB`（新）→ 读 `daily` → 领；
   而旧标定的 `BTN_DAILY_CLAIM_ALL` 在 y≈0.777，与今天的面板版式不符 ⇒ 需重新注册 + verifier。
2. `CAP-B03/B05`（`CLAIM_REWARD` 进 `VERIFIED_ATOMIC`，受 RR-003 边界约束，需 Codex 裁决）。
3. `CAP-B09/B10`（VIP，需先发现入口）、`FREE_ITEM` / `FREE_SHOP_ITEM`。
4. `ALLIANCE_GIFTS` / `ALLY_GIFT_CLAIM`（后者上一轮真机 11 次成功，**可复跑刷价值**）。
5. `RECALL_MARCH`：只差 `idle_marches==0 ∧ GATHERING 在外` 这个自然状态。

### 4. 环境/协作提醒（本轮新增）

- **GitHub 已进日常工作流**：`tools/git_sync.py status|push`、`tools/scan_public_repo.py`（推前闸门）、
  `docs/GITHUB_SYNC_RULES.md`（规则全文）。开工先 `git_sync.py status`，
  一个可验证工作单元完成即 push；**禁止强推 / 重写 main / 盲 reset**。
- 本机 pytest 全量仍拿不到汇总行（宿主批量删除守卫）⇒ 用 `-o tmp_path_retention_policy=all`，
  或 `PYTEST_PLUGINS=winter_failwatch`（失败发生时即时落盘）。
- repo 仍可能有第二个写入方：改完立刻 `git log --oneline -3` 复核。

## 手写：上一轮（2026-09-16 21:0x–22:1x GMT+8）—— 让每日任务入口真正能用；面板不再把人困住

**先读本轮的证据目录**（都是可复核的帧 + README，不需重测）：
`dataset/truth_audit/daily_entry_template_20260916/` 与 `dataset/truth_audit/daily_tasks_tab_20260916/`。

### 1. 本轮真实改进（两条，都有真机 episode）

按能力总表 `--rank` 的顺序，`CAP-B01 CLAIM_DAILY_MISSION` 本该是最便宜的一项
（"动作已实现、页面可达、只缺可采信 episode"）。**它不是** —— 卡在入口上，本轮把入口修通了。

| 步骤 | 技能 | 页面 | verifier | 说明 |
|---|---|---|---|---|
| 1 | `OPEN_DAILY` | HOME→DAILY | OK `{"before_home":true,"after_daily":true}` | 2026-09-16T13:44:13Z / 13:51:43Z |
| 2 | `BACK` | DAILY→HOME | OK `{"page_returned":true}` | 13:52:03Z |
| 3 | `SAFE_STOP` | — | — | `daily_panel_already_read_not_actionable` |

episode 均可追溯：`episode_id=live_runtime` + `step_id` + `verifier_ok=true` + 前后截图在磁盘上。
`learning/episodes.jsonl` 里 13:10:49 那条 **`OPEN_DAILY FAILURE / SEMANTIC_TARGET_NOT_VERIFIED`
就是修复前的那一帧**，别当成新缺陷。

### 2. 根因一：`BTN_OPEN_DAILY` 的模板早就失效了（不是页面问题）

`OPEN_DAILY` 此前**从没有过可采信 episode**（`--rank` 里的 5 次成功全是 478 行旧 schema）。
真因：`BTN_OPEN_DAILY` 只有一条 2026-09-08 的记录，**在今天的真机帧上距离 18、门禁 8**，
而同一帧上城市其它按钮都命中（探险 d=0、联盟 d=8、邮件 d=8–20 走它自己的 24）。
⇒ 帧没问题，模板过期：角标不见了 + 背后的城市换了一个。

**修法不是抬门禁**（抬高会让一个召回 2.2% 的点击目标留在生产里），而是**换一个排除角标的裁剪**：
`(12,1026,50,1084)` 图标圆的左 2/3，**一条记录同时覆盖"可领"与"已领"两种状态**。
在**整棵语料 3480 帧**上量（`tools/probe_daily_entry_gate.py`，代理总体 = 同屏那个稳定按钮）：

| 候选 | 召回(HUD n=1104) | 代理外命中 | 2026-09-08 帧 |
|---|---:|---:|---:|
| 旧记录 | 24 (2.2%) | 0 | d=2 |
| 整圆含角标 | 41 (3.7%) | 0 | **d=16 ✗** |
| 圆下半带 | 587 (53.2%) | 0 | d=2 |
| **圆左 2/3** | **1054 (95.5%)** | **1** | **d=6 ✓** |

⚠ 那唯一一条"代理外命中"`legacy_resource_search.png` **目视是城市帧**（另一个账号、底部导航变淡）
⇒ 它是代理看不见的**真阳性**，不是假阳性。**代理外命中必须逐帧分类**，不能看数字小就放过。
⚠ "HUD 帧"不是"城市帧"：城市与世界地图**共用**同一列左键与底部导航，那个卷轴图标**两张页都在**。

### 3. 根因二：入口修好之后，那个面板变成新的死胡同（已修）

客户端第一次真的站到面板上时：`daily={"status":"AVAILABLE","claimable_count":0}` ⇒
大脑 `SAFE_STOP daily_no_claimable_rewards`，**停在面板里**（与 `Page.BEAST` 同一类：
没人把客户端挪走，之后每次运行、**任意 goal**，都会几秒内结束）。

修法（`brain._leave_daily_panel_once` + 一次性旗标 `daily_panel_not_actionable_left`）：
- 面板里无东西可领 ⇒ **一次 BACK**（真机实测 DAILY→HOME，`verify_safe_back` 接受该迁移）；
- 旗标防止"BACK 没真的离开"被反复重试；
- **DAILY goal 在 HOME 上不再重开已经读过、判过空的面板**（`daily_panel_already_read_not_actionable`）
  —— 这是 beast card 那套不需要的一半，因为面板有入口技能而 BEAST 页没有。
- `tools/run_live.py` 的 `accepted_stops` 同步加了新 reason（同类：verifier 全过、客户端被留在可用页面）。
测试：`tests/test_daily_panel_dead_end_recovery.py`（12 项）+ `check_wiring.py` 三条新检查。

### 4. ⚠ 结论：`CAP-B01` 今天**不是可做的**（Feature Availability，不是缺陷）

用一次有界探针（`tools/probe_daily_tasks_tab.py`，只点一下、只点量过的坐标）量到：面板是**分页**的
（章节任务 / 成长任务 / 每日任务，页签行 y≈1117–1154），**默认落在 章节任务**；
切到 每日任务 后 `activity=285`，四条任务 **16/20、25/40、0/10、0/10**，
三个活跃宝箱（80/160/270）**是开的** ⇒ **任何页签今天都没有可领的东西**。
⇒ 与 RESEARCH 的 `QUEUE_BUSY` 同类：**客户端正确地没事可做**。**不要当 bug 修、不要为凑证据造状态。**

### 5. 下一条该做的（按顺序，都已定位）

1. **`SELECT_DAILY_TAB`（新技能，推荐先做）**：注册表里**没有任何切页签的能力**，
   而整条 daily 系列技能是在 每日任务 页签上标定的。今天缺它的后果是**具体的漏领**：
   三个活跃宝箱在 285 点活动下已达标，机器却看不见（它读的是 章节任务 页的内容）。
   ⚠ 设计要点：切页签的 verifier 不能用任务名（每天在变），要用**选中态**——
   选中/未选中的样子**两张帧都在** `daily_tasks_tab_20260916/` 里（01 = 章节选中、02 = 每日选中）。
   还要给 `vision.py` 一个可读的 `daily.tab`，否则大脑看不见"现在是哪一页"。
   ⚠ 顺带记下：`DAILY_HERO_RECRUIT` 在 goal=DAILY 下**本来就不可达**（goal 块先于页面块返回），
   且它没有 verifier ⇒ 不可派发。**别把它当成新引入的回归。**
2. `CAP-B03/B05`（`CLAIM_REWARD` 进 `VERIFIED_ATOMIC`）、`CAP-B09/B10`（VIP，需先发现入口）。
3. `CAP-AY05 FREE_ITEM` / `CAP-B20 FREE_SHOP_ITEM`（免费商店项）。
4. `ALLIANCE_GIFTS` / `ALLIANCE_ALLY_GIFT_CLAIM`（后者上一轮真机 11 次成功，**可复跑刷价值**）。
5. `RECALL_MARCH`：实现齐、verifier 齐，**只差 `idle_marches==0 ∧ GATHERING 在外`** 这个自然状态。

### 6. 本轮踩到/确认的环境事实（会让下一轮白花时间）

- **本机 pytest 全量跑不出汇总行**：宿主批量删除守卫在会话末尾拦下 pytest 自己清理
  `%TEMP%\pytest-of-xhw\garbage-*`（本轮 707/868 个文件），`SystemExit` 把终端汇总吞掉
  ⇒ 只剩进度点。**本轮的做法**：`tools/winter_failwatch.py`（`PYTEST_PLUGINS=winter_failwatch
  PYTHONPATH=tools`）在每条失败发生时就把 nodeid + longrepr 写文件，汇总丢了也不丢信息。
  ⚠ `%TEMP%\pytest-of-xhw` 属**宿主保护目录**，本轮**未清理**（个人目录不擅自递归删）；
  项目自己的 `pytest.ini` 注释说它"可安全清除"，需要操作者点头。
- **本 repo 有第二个写入方**：本轮进行中，另一个会话（同一 `Winter Agent OS V2` 身份）
  把我的工作树**分三个 commit 提交了**（`91667d2` gitignore / `4f51875` 本轮的代码+证据+工具 /
  `cc8ba87` 我的测试改动），还写了 `a42726a`（GitHub 远端 + 连接器 403 + GCM 陷阱）。
  ⇒ **改完立刻 `git log` 复核**，不要默认"未提交的改动还在"；也**不要**在别人刚写完的路径上凭空新建提交。
- **episode 的"验证"字段是 `verifier_ok`，不是 `verifier`**（后者不在 schema 里）。
  上一轮留的"episode verifier 为空 {}"疑问**到此关闭**：`verifier_ok=true` + 前后截图 + 步级
  `verification`（在 run 结果 JSON 里）已足够可审计。

## 手写：上一轮（2026-09-16 20:2x GMT+8）—— 建能力总表；落地 MAIL 领取

### 0. 阶段的第一件事：跑这两条

```
"E:\dongri-mumu-bot\.venv\Scripts\python.exe" -u tools/build_capability_catalog.py --rank
"E:\dongri-mumu-bot\.venv\Scripts\python.exe" -u tools/capability_landing_queue.py
```

第一条建/刷新 `knowledge/game/capability_catalog.json`（操作者 §4 的 522 条能力，
按 `CAP-<类><序号>` 编号），并按**操作者 §5 的阶段顺序**打印工作清单（`DO` = 待做）。
第二条打印技能粒度的落地状态（未实现 / 不可判定 / 可判定未执行）。
**两者都不是第二个 Skill Registry** —— 真执行表永远只有 `v2_registry()`。

### 1. ⚠️ 先看这条：语料里有 478 行"自报成功"，不可采信

`learning/episodes.jsonl` 共 1351 行，其中 **478 行没有 `recorded_at`**（也没有 `episode_id` /
截图 / `verifier_ok`），字段只有 8 个：`skill, state_before, state_after, action, result, mode,
duration, failure_type`，全部写着 `mode=PRODUCTION`。样本里 `MAIL_CLAIM_REWARDS` 的"验证"是一个
**自述字符串**（`"reward feedback AND all tab badges clear"`），不是裁判的判定。

⇒ **这是另一代写入器的输出（旧 schema），按 `live-verification` 门禁不得支撑 LIVE_VERIFIED。**
⇒ **所有历史指标都被它污染**（最重的：`OPEN_INTEL=53 OPEN_MAIL=46 MAIL_CLAIM_REWARDS=24
SEARCH_RESOURCE=23 OPEN_HOME=23 OPEN_MAP=23 START_GATHER=20 DISPATCH_MARCH=20`）。
总表已把这条写进 `evidence_policy` 并只统计带 `recorded_at` 的行。
**不要**按这些行宣称能力已上线；**也不要**删历史（§18 禁止篡改）。

### 2. ✅ 本轮落地一个真实能力：MAIL 领取（PHASE 1 / T0 / 免费）

验收四件套全齐（真机 2026-09-16T12:21:37–12:22:44，`--goal MAIL`，`stop_reason: mail_all_clear`）：

| 步骤 | 技能 | 页面 | verifier |
|---|---|---|---|
| 1 | `OPEN_MAIL` | HOME→MAIL | OK |
| 2 | `MAIL_CLAIM_REWARDS` | MAIL→MAIL | **`MAIL_BADGE_REDUCTION_PROVEN`**（角标 8→5） |
| 3 | `SELECT_MAIL_ALLIANCE_TAB` | MAIL→MAIL | OK |
| 4 | `MAIL_CLAIM_REWARDS` | MAIL→POPUP | OK |
| 5 | `DISMISS_MAIL_GENERIC_REWARD` | POPUP→MAIL | OK（角标 → **0**） |

10 张截图在磁盘上、`episode_id=live_runtime` + `step_id` 齐备、`mode=PRODUCTION`。
**总表覆盖：LIVE_VERIFIED 26 → 29**（`CAP-B06 CLAIM_MAIL` / `CAP-B07 MAIL_READ` /
`CAP-B08 MAIL_COLLECT_ALL`），CANDIDATE 42 → 39。

### 3. 下一条该做的（PHASE 1 里最便宜的）

按总表 `--rank` 的输出顺序，T0 优先：

1. **`CAP-B01 CLAIM_DAILY_MISSION`**（`DAILY_CLAIM_REWARDS` 已存在，0 条可追溯证据）
   —— 与 MAIL 同一形态：**动作已实现、页面已可达、只缺一条可采信 episode**。这是最便宜的下一项。
2. `CAP-B03/B05 CLAIM_EVENT_MILESTONE / CLAIM_ALL`（`CLAIM_REWARD` 未进 `VERIFIED_ATOMIC`）
3. `CAP-B09/B10 VIP 日领 / VIP 免费宝箱`（**完全未实现**，需先发现 VIP 入口）
4. `CAP-AY05 FREE_ITEM` / `CAP-B20 FREE_SHOP_ITEM`（免费商店项）
5. `CAP-S06/S07 ALLIANCE_GIFT / CHEST`（`ALLIANCE_GIFTS` 已存在，同样缺可追溯证据）

⚠ **`CAP-E01/E04 RESEARCH` 现在不可落地**：真机显示该角色已有一个进行中的研究
（`branch=GROWTH node=WARD_EXPANSION_VII status=IN_PROGRESS timer=6d05:20:54`），
`queue_available=false` ⇒ 客户端正确地拒绝（`QUEUE_BUSY`）。这是 §7 的 Feature Availability
问题，**不是缺陷** —— 不要再当 bug 修。

### 4. 门禁提醒（本轮踩到）

- 项目脚本/测试**必须**用项目 venv `E:\dongri-mumu-bot\.venv\Scripts\python.exe`；
  受托管的 3.13 **没有 PIL**，用错会得到 `ModuleNotFoundError: No module named 'PIL'`。
- PowerShell 里 `python -c "...%d..."` 会被安全策略拦（`%VAR%` 被当成 cmd 变量）⇒ 用 `str.format`。

## 手写：上一轮（2026-09-16 19:0x GMT+8）—— 进入 CAPABILITY-FIRST 阶段

**阶段定义（操作者，最高优先）**：不再扩架构，尽快让 Agent「会做越来越多的事」。
现有 V2 顶层架构冻结；Role/Progression 够用即停；**优先把 MISSING / NEVER_TRIED 推进到
LIVE_VERIFIED**；MAA 优先、复用外部成熟项目；单功能 30–60 分钟（复杂最多 90）；
超时无真机进展 ⇒ BLOCKED 立即换下一个；**已稳定的功能不要继续过度优化**；
最小验收 = `Preconditions → Execute → Verifier PASS → Production Episode → Evidence`。

**操作者给的落地顺序**：GATHER / RECALL → CLAIM·MAIL·VIP·FREE → TRAIN·PROMOTE·HEAL →
RESEARCH·BUILD → ALLIANCE(HELP/GIFT/TECH) → HUNT_BEAST → ARENA·EXPLORATION·LABYRINTH·PET →
JOIN/START_RALLY → BEAR → 其他已解锁。**Intel 已有大量成功证据，除 P0 回归不再深挖。**

### 0. 先跑这一条，它把整阶段的队列算出来

```
"E:\dongri-mumu-bot\.venv\Scripts\python.exe" -u tools/capability_landing_queue.py
```

按操作者的顺序逐项打印 `reg / judge / tried / state / episodes`，并分出三类：
- **未实现**（不在 registry）27 个：`CLAIM_MAIL OPEN_VIP CLAIM_VIP OPEN_DAILY…`（含 TRAIN/RESEARCH/
  ALLIANCE 大部分/ARENA/LABYRINTH/PET/RALLY/BEAR 全部）
- **实现了但不可判定**（不在 `VERIFIED_ATOMIC`，运行时会拒绝派发）3 个：`ALLIANCE_HELP JOIN_RALLY START_RALLY`
- **可判定且从未执行**：`RECALL_MARCH`（见第 2 条）

⚠ 注意 `Skill.verifier` 只是**声明的名字**，真正的裁判是 `LiveRuntime.VERIFIED_ATOMIC`；两者不一致
就是 RR-003。**别把 `never_tried` 当成"没实现"**（覆盖率审计技能的警告）。

### 1. 本轮修掉一个 P0 回归：采集链曾**无法起步**（已真机恢复）

R22 删掉"假定容量 6"是对的，但它同时删掉了起步条件的**唯一数值**：

- 客户端**只在有队伍在外时才画行军计数器**。空闲时 `MARCH_COUNT_ROI` 一个 token 都没有
  ⇒ `march_used=0` 但 `march_max` 读不到 ⇒ `idle_marches=None`
  ⇒ 大脑答 `CHECK_MARCH`，而 `CHECK_MARCH` 只是"再看一眼" —— **不会改变任何东西**。
- **实测**：2026-09-16 11:09–11:16 三次运行各烧完 8 个动作在 CHECK_MARCH 上，**零次派兵**。
  （R21 那次能跑通，是因为当时 `march_max` 由被硬编码的 6 供给。**成功掩盖了这个洞。**）

**修法**（`models.WorldState.has_free_march_slot` + `brain` MAP 分支）：起步不需要容量，
只需要"有空位"这个更弱、并且**两种状态下都可判定**的事实 —— `used == 0 ⇒ 至少一个空位`。
这是**下界，不是容量猜测**，而且**自我修正**：派兵本身让计数器出现，下一帧就读到真容量
（实测 11:20:57 `DISPATCH_MARCH` `max None->2`）。`CHECK_MARCH` 现在只保留在"确实有队伍在外、
容量却仍读不到"这一种**重观测可能有用**的状态。

### 2. 下一个能力：`RECALL_MARCH`（操作者顺序第 2 项，已可判定、从未执行）

**实现是齐的**（不要再造）：`SELECT_MARCH_TO_RECALL`（TAP `MARCH_ROW_1`，标定中心 0.28/0.2234）
→ 弹窗（`POPUP_TITLE_RECALL` 已注册，`vision.py` 已返回 `popup="MARCH_RECALL"`）
→ `RECALL_MARCH`（TAP `BTN_CONFIRM_RECALL`，ROI 中心 px 512,788 与实测"确定"吻合）；
两个 verifier 都完整且有真机依据（**召回由 `GATHERING→RETURNING` 证明，不是靠空位增加**）；
单测/回放已覆盖 12 项。**唯一缺的是触发条件**：

```
brain._recallable 要求  page==MAP ∧ 搜索面板关闭 ∧ idle_marches == 0 ∧ GATHERING 在外
```

⇒ 需要**两个队列位同时被占用**（该角色容量 2）跑一次运行。本轮试过：11:20:57 第一次派兵成功，
但 43 秒后 `used 1->0`（客户端现在 HOME、无行军）—— **太快，不可能是采集完成，根因未定，不得猜测**。
**下一步**：派兵后**立刻**再跑（不要等），或先查清"派兵后 43 秒消失"的真因（候选：
那次 `START_GATHER` 落到了 POPUP 上、或有弹窗遮住 HUD 导致计数器消失被读成空闲）。

### 3. 顺手确认的两件事

- `docs/CAPABILITY_COVERAGE.md` 已重跑：`rate 0.7424 → 0.7474`；**Goal 层 `never_tried=0`、
  `missing=0`** ⇒ 这一阶段只能在 **Skill 粒度**推进（用第 0 条那个工具）。
- `read_march_count` / `read_role_identity` / `has_free_march_slot` 三者都在"**不猜**"这一侧：
  读不到就是 `None`，由调用方决定是等待还是用下界。

## 手写：上一轮（2026-09-16 18:4x GMT+8）—— 产品定义落地：**身份来源已找到**（一次点击）

**先读**：`docs/PRODUCT_ONE_AGENT_MULTI_ROLE.md`（操作者的产品定义 + 落地现状 + 硬边界）。

### 1. 本轮最重要的一句话

**"登录的是哪个角色"以前无法观测，现在可以了**：从 HOME/MAP **点一次左上头像**
打开 `领主档案` 面板，OCR 直接读出 `[zoe]xhw小号` / `账号：1171757165` / `所在王国：4298`。
一次 Back 回 MAP（实测 0.99）。证据：`dataset/truth_audit/role_identity_20260916/`。

**但还没人用它。** 已落地的是**观测能力**：`models.RoleIdentity`、
`HybridVision.read_role_identity()`、`tools/role_identity_probe.py`、
`tools/cq_role_identity_verify.py`、`tests/test_role_identity.py`（20 项，4 个负向帧）。

### 2. 下一步就是把它接进运行（这是当前最高杠杆项）

1. **`IDENTIFY_ROLE` 正式 Skill 化**（照 §15 的 Precondition / Action / Verifier 三件套）。
   Precondition：页 ∈ {HOME, MAP} 且身份未知或过期。Action：点头像。Verifier：`read_role_identity()`
   返回非 None **且** 回到 HOME/MAP。⚠ 代价必须记录：这一步要 2 个动作（点 + Back）。
2. **role state 按 `role_id` 分文件落盘**（`learning/roles/<role_id>.json`），
   承载 AccountStage / MarchCapacity / FeatureAvailability。**不要**建第二套引擎（§26）。
3. **每条 episode 带 `role_id`**，否则历史指标永远是无归属的（见第 3 条）。
4. **不要把 `领主档案` 登记成 page 模板却不加恢复规则**：今天它判 `UNKNOWN` ⇒ 会被
   `unknown_page` 恢复按 BACK 并成功退出；一旦登记成已知页而大脑没有对应分支，就会卡在面板上。
   要登记就连恢复（Back）一起做。

### 3. ⚠ 语料已经跨了两个角色（本轮证实）

| | 2026-09-14 13:41 | 2026-09-16 18:37 |
|---|---|---|
| 战力 | **70,206,322** | **542,443** |
| 统帅 | 统帅9 | 统帅2 |
| 行军 | **行军 6/6** | **行军 1/2** |

同服务器 `#4298`。⇒ `learning/episodes.jsonl` 里**混了两个账号**，容量差 3 倍。
任何"某技能的容量/无效率"统计，在带 `role_id` 之前都只能当作参考。

### 4. 顺手修掉的一个真缺陷

`read_march_count` 把 ROI 的多个 token 拼成一行再匹配 ⇒ `'3/' ＋ '3/6'` 读成 `(3,3)`，
**客户端说 6、episode 记 3**，而这正是派兵依赖的数字。已收紧为"整 token 优先、
碎片不得改写、歧义返回 None"，并加了数字边界（`200/200` 不再被读成 `0/20`）。

### 5. 上一轮（13:0x）的角色能力审计仍然有效

`docs/ROLE_SCOPED_CAPABILITY_AUDIT.md` 的 9 问答案不变；本轮只是把其中"无法观测身份"
从**阻断性前提**变成了**已解决的前提**。

### 6. 再做任何"取新可观测事实"之前，先读 `docs/ADDING_A_LIVE_OBSERVATION.md`

那是本轮踩出来的固定流程（先目视确认事实画在哪 → 穷尽已有帧 → 有界探针 → 几何量 ROI →
双证据门 → 归档到 truth_audit + .gitignore 白名单 → 双向测试 → 改阈值前先建两个总体）。
产品定义第 19 节（自动发现新解锁功能）会反复需要它。里面也记着几条**实际发生过的反模式**。

## 手写：上一轮（2026-09-16 13:0x GMT+8）—— 角色成长/容量动态建模：审计 + 两项 P0

**先读两份文档，不要只看本条**：`docs/ROLE_SCOPED_CAPABILITY_AUDIT.md`（9 问逐条答案，全带证据）
与 `docs/ROLE_SCOPED_CAPABILITY_PLAN.md`（剩余项方案 + 阻断性前提）。

### 0. 先做这一步（**接管后第一件事**，不变）

```bash
"C:/Users/xhw/.workbuddy/binaries/python/versions/3.13.12/python.exe" tools/cq.py plan
```

### 1. 本轮修了什么（两项，都有真机证据）

1. **页面模型不再编造行军容量与占用**（`vision.py`）。四个 beast/hero 分支原本手写
   `march_used=1/2/5/6` + 固定 `march_max=6`。**编造占用会喂 `idle_marches`**，
   其中 `6/6` ⇒ idle=0 ⇒ 大脑据此去**召回采集队**，而那个数字没人测过。
   ⇒ 模板证明不了"有几个队列位"，未读到就是 `None` → `CHECK_MARCH` 去读。
2. **`reserve_for_stamina` 不再是绝对位数**（`brain.RuleBrain.reserved_slots`）。
   真机该角色 `march_max=2`，固定 reserve=2 使 `idle <= reserve` 恒真
   ⇒ 04:20–04:30 **三次 `GATHER_RESOURCE` 零 episode**。
   现在 `有效预留 = min(reserve_marches, capacity - 2)`：2 队→0、6 队→2（原始意图保留）。
   ⚠ **不变式是 `reserved_slots < capacity`**，已写进 `check_wiring.py`。

### 2. ⚠ 下一件最重要的事：角色身份（否则第 6/24/27 节无法落地）

**当前无法观测"这是哪个角色"**：`role_id` 等关键词全仓库零命中；
`device.serial` / MAA `instance_name` 是**模拟器实例**（同一模拟器可登不同角色），
`package_name` 是游戏包。`WorldState.account_stage` 存在但恒为 `{}`。

**建议顺序**（详见 PLAN 第二节）：
1. **先做"观测到就记住"**（单角色内，`account_stage` 写实测容量，零风险）；
2. **同时把"从客户端读领主名"立为正式任务**（新增一个语义模板 + 一次 OCR ROI 标定 + 负样本）
   —— 这是唯一能真正自动化的路径，且它同时解锁第 23 节"成长后自动发现"；
3. **不要**先做"配置声明 role.id"：它会让角色隔离**看起来**已完成，而实际靠人工维护、易静默串档。

### 3. 其余待办（按价值）

1. **第 16 节的 12 次四资源 E2E 现在才真正可行**（容量 2 的角色原本被固定 reserve 锁死）。
   按 MEAT/WOOD/COAL/IRON 各 ≥3 次立项。
2. **召回的价值比较不存在**（第 13 节）：现在只有"没空闲位就召回"，
   没有 `NewGoalPriority vs CurrentGatherValue`。机制部分（RECALLABLE / 有 idle 用 idle /
   真实 verifier `MARCH_RECALLED`）已齐备。
3. **未知新入口 → `FEATURE_UNLOCK_CANDIDATE`**（第 19 节）：现状是
   `SAFE_STOP unknown_page` → 按 BACK ≤2 次 → `DEGRADED` + **结束 run**。
   改造要守住"**不把阻塞变成游荡**"（有界、只截图不点击、失败仍如实上报原 reason）。
4. `knowledge/game/feature_unlocks.json`（第 4 节）：纯知识表，沿用 `knowledge/game/` 既有的
   `gate: DISCOVERED|REVIEWED` 约定。⚠ `furnace_requirement: null` 的含义是**未知**，不是"无要求"。
5. **技能生命周期 vs 功能可用性是两个轴**，`capability_coverage.py` 现在混在一起（审计第 7 问）。

### 4. 🔧 编辑工具陷阱（本轮新增两条，都会**静默**损坏文件）

- **`old_string` 截断到行中间 ⇒ 只替换前缀，行尾变残片。** 本轮实际发生：`vision.py` 留下
  `)r": 5107044, "stamina_cost_displayed": 10},` —— **而工具报告"成功"**。
- **`old_string` 少一个结尾换行 ⇒ 两行被合并**（语法合法所以不报错，但难读）。
- **对策：每次 Edit 后立刻 `ast.parse` 整个文件 + 读回改动区域**，不要只看"编辑成功"。

---

## 手写：上一轮（2026-09-16 12:1x GMT+8）—— 队列空后收掉最高杠杆项：**采集链首次跑通**

### 0. 先做这一步（**接管后第一件事**，不变）

```bash
"C:/Users/xhw/.workbuddy/binaries/python/versions/3.13.12/python.exe" tools/cq.py plan
```

### 1. 本轮最重要的一件事：采集链端到端跑通

`2026-09-16T04:15Z`，`--goal GATHER_RESOURCE`，**四步全部 verifier PASS**：

```
SELECT_RESOURCE         MAP->MAP              sel None->COAL
SUBMIT_RESOURCE_SEARCH  MAP->RESOURCE_DETAIL  resource_available=True
START_GATHER            RESOURCE_DETAIL->MARCH  recog/act/exec 全 = MAA
DISPATCH_MARCH          MARCH->MAP
```

**并且要理解 `START_GATHER` 的历史 35/94 (37.2%) 是什么**：它 **59 次失败全是 `MARCH_PAGE_NOT_OPEN`**
⇒ 那 37.2% **不是这个技能的属性**，是**整条链的阻塞被记在了队列里下一个技能头上**。
**这是一条通用教训**：当一个高频技能的失败原因高度集中在上游页面时，先查上游，别先查它。

### 2. 两个真缺陷（都不是几何 —— 几何从来没错）

**① 门禁阈值低于它自己标定语料的最大值。** 两个总体：正确 `0.00..6.49`、错误 `10.65..25.09`，而配置是 **6.0**
⇒ 它在拒绝自己标定帧就能产生的读数（6.45 / 6.49）。已改为 **8.0**。
⚠ 那条让 6.0 显得宽松的旧注释（"active ≤1.2 / non-active ≥13.0"）是**从括号处裁剪**测出来的，已更正。

**② 客户端在选中之前根本不画括号。** 面板刚打开时 `stroke pairs: []` ⇒ `resource_tab_offset=None`
⇒ 既不能点（目标位置未知）**也不能滚**（滚动分支要求 offset 已知）⇒ 对着**已经在屏幕上**的目标失败。
修法：**offset 与 identity 是两个独立事实**（`_offset_from_tab_contents`，用模板相对间距反推，只在括号失败时惰性调用）。

### 3. 一个可复用的手法：**偏移扫描**

**不问锚点，直接滑条带，看哪个 offset 让可靠标签的模板各自落回自己的格子。** 它本轮裁决了三个问题：
确认 pitch 没错；确认两个待改期望值的身份**正确**（整数索引 0.00 / 1.00）；在无括号帧定出 offset=89。
**改期望值之前，先用一条不含被测机制的证据链复核。**

### 4. 下一步（按价值排序）

1. **`WB-R19-START-GATHER-MAA-LIVE-AB` 的 A/B 只凑到 1 个 MAA 臂**。不是缺陷：派出行军后大脑每次都答
   `SAFE_STOP reserved_march_for_stamina`（`reserve_for_stamina=2`），其后 3 次运行**一条 episode 都没产生**。
   要凑样只能**等行军回来**或 Codex 改策略 —— **召回行军凑样 = 制造状态，禁止**。
2. **`WB-R19-LOW-RISK-GOAL-ATTEMPT` 仍未做**（`NO_SAFE_CANDIDATE`，见 RR-003：6 个技能在
   `VERIFIED_ATOMIC` 内但**没有 verifier**）。给 `READ_INTEL_LIST` 或 `SELECT_INFANTRY_CAMP` 补 verifier 即可解锁。
3. **RR-002 / RR-003 仍待 Codex 裁决**（见 `REVIEW_REQUESTS.md`）。
4. 采集已能派兵 —— 值得接着量的是**行军回来之后的闭环**（召回 / 收获 / 再采集），本轮未碰。

### 5. 环境坑（本轮新增，会让下一轮白花时间）

- **Shell 会退化**：本轮 `timeout` 被解析成 **Windows 的 TIMEOUT.EXE**（不是 GNU timeout），
  `dirname`/`cat`/`head` 全部 `command not found`（shim 的 PATH 装配失败）。
  ⇒ 出现这种症状就**改用 PowerShell 工具**。另：`Out-File -Encoding append` 不是合法参数（要用 `-Append`）。
- **同一文件的多处 Edit 必须逐个做**：同一条消息里发两次 Edit，可能只生效一次、另一次**静默丢失**。改完**务必 grep 复核**。
- **PowerShell 的 `Out-File` 要等命令结束才落盘**，所以后台运行时输出文件会是空的 —— 别据此判断"卡住了"。

---

## 手写：上一轮（2026-09-16 10:1x GMT+8）—— Codex 第 2 批队列 7 单

### 0. 先做这一步（**接管后第一件事**，不变）

```bash
"C:/Users/xhw/.workbuddy/binaries/python/versions/3.13.12/python.exe" tools/cq.py plan
```

### 1. 本轮队列终态（`EXECUTION_STATE.json` 为准）

| Order | 终态 | 一句话 |
|---|---|---|
| `WB-R19-RUNTIME-EXIT-SEMANTICS` | DONE | RR-001 已修：两条写入路径改调**同一个**判据函数 |
| `WB-R19-OPEN-INTEL-MAA-RECOVERY` | DONE | 真机 `MAP→INTEL` verifier PASS；点击落在**找到的行** (666,954) |
| `WB-R19-BACKEND-PROVENANCE-TRUTH` | DONE | 68 条声明对 `maafw.log` 可追溯；发现 `capture_backend` 同名两义 |
| `WB-R19-BATTLE-UNKNOWN-RECOVERY` | DONE | 派发战斗后的未知帧**不再按 BACK**，改为有界等待 |
| `WB-R19-SELECT-RESOURCE-ANCHOR` | **BLOCKED** | 条带几何需重标定（标定集已存在，见下） |
| `WB-R19-START-GATHER-MAA-LIVE-AB` | **BLOCKED_BY_LIVE_STATE** | 依赖上一条；跑也只会再停在 SELECT_RESOURCE |
| `WB-R19-LOW-RISK-GOAL-ATTEMPT` | PENDING / READY | 本轮未做，可接手 |

### 2. 最重要的一件事：`SELECT_RESOURCE` 条带几何重标定

**它是整条采集链的唯一阻塞项**（`SEARCH_RESOURCE` 已 OK，之后永远停在 `SELECT_RESOURCE`）。
`0bc`（行军计数）修好后链子第一次真正起步，暴露出这是新前沿。

- **现状**：`vision.py` 的标定 pitch = 157 px，真机实测 ~145–150 px，漂移约 1/3 格。
- **不要**再假设"模板覆盖是瓶颈"（那是上一单被推翻的假设）。
- **有现成标定集**：`dataset/truth_audit/resource_cells_20260914_120027/`（MEAT/WOOD/COAL/IRON 逐项选中帧）。
- **先测再改**：在真机搜索面板打开时量资源条（是否需滚动、cell 是否离屏），再决定修几何还是接 MAA 识别。

### 3. 两条给 Codex 的一句话改动（都需 schema 裁决，本轮只报告未动手）

1. **账本 `capture_backend` 删键**：它完全由 `used_backend` 决定（零额外信息），却与 episode 的同名字段描述**不同事实**（观测通道 vs 执行器通道），34 步上必然不等。删掉即消除歧义。
2. **给 `DISPATCH_INTEL_BEAST` / `DISPATCH_BEAST` 补显式 verifier**：它们**目前没有 verifier**，所以 Beast 战斗无法武装本轮的防误按保护，且其 episode 天生没有可审计的验证结果。

### 5. P2 `WB-R19-LOW-RISK-GOAL-ATTEMPT` 的候选已筛完（工具：`tools/cq_low_risk_candidates.py`）

对 **20 个从未执行**的技能做三重过滤（本单自己的条件）：
1. 必须在 `LiveRuntime.VERIFIED_ATOMIC` 里（否则真机循环直接拒执行）；
2. `risk ∈ {NONE, LOW}` 且**同时有** `verifier` 与 `recovery`；
3. 不在本单禁区（Arena/Labyrinth/Rally/支付/账号）。

**结果：只剩 1 个 —— `RECALL_MARCH`**（verifier `MARCH_RECALLED`、recovery `REFRESH_MARCH_STATE`、risk LOW）。

其余全部被硬条件淘汰，且淘汰原因是**可查的**：
- `NAVIGATE_TO` / `RECOVER_HOME` / `READ_TIMER` / `READ_COUNTER` / `CLAIM_REWARD` / `SEND_MARCH` —— **有 verifier 有 recovery，但不在 `VERIFIED_ATOMIC`**（真机不可执行）；
- `READ_INTEL_LIST` / `SELECT_INFANTRY_CAMP` / `SELECT_INTEL_RESCUE_SURVIVORS` / `CANCEL_DUPLICATE_TARGET` / `DISMISS_ALLIANCE_GENERIC_REWARD` / `RELAX_RESOURCE_LEVEL` —— 在 atomic 里，但**根本没有 verifier**；
- `JOIN_RALLY` / `START_RALLY` —— risk `MEDIUM_COMBAT`，且 Rally 是禁区。

**但 `RECALL_MARCH` 现在也做不了**：它需要**自然存在的进行中行军**，而当前客户端 `march_used=0`。
⇒ 本单大概率应记 `NO_SAFE_CANDIDATE`（或 `WAITING_FOR_NATURAL_STATE`），**不要**为了凑任务去派一支队伍再召回 ——
那正是本单 `do_not_touch` 和 §「禁止为验证主动消耗资源」所禁止的。

**顺带得到的一条更值得修的结论**：`DISPATCH_BEAST` / `DISPATCH_INTEL_BEAST` **已被执行过**，但它们**没有 verifier**
⇒ 它们的 episode 天生缺少可审计的验证结果（与本轮 `WB-R19-BACKEND-PROVENANCE-TRUTH` 的发现同源）。

### 6. 两个本轮踩到的坑（会让下一轮白花时间）

- **同一文件的多处 Edit 必须逐个做**：同一条消息里发两次 Edit，可能只生效一次、另一次**静默丢失**（本轮丢了 3 处，症状是"报告成功但 grep 不到"）。改完**务必 grep 复核**。
- **`%TEMP%\pytest-of-xhw` 会拖慢全量测试**：本机全量从 ~5 分钟退到 ~16 分钟，与本轮多次中断的 pytest 进程留下的残骸有关。

---

## 手写：上一轮（2026-09-15 23:2x GMT+8）—— 接入 Codex Commander Queue；队列已跑空

### 0. 先做这一步（**接管后第一件事**）

```bash
"C:/Users/xhw/.workbuddy/binaries/python/versions/3.13.12/python.exe" tools/cq.py plan
```

任务来源现在是 `.workbuddy-ai/commander/WORK_QUEUE.json`（Codex 写），
**不是**文档里的待办列表。判据 = `status=="READY"` **且** `dependencies` 全有终态。
`QUEUED` / `WAITING_FOR_NATURAL_STATE` **不是可执行任务**（后者禁止为凑任务消耗资源）。

**当前队列终态：RUNNABLE 0。** 8 个 Order 已全部收敛：
`WB-0BA`/`WB-0BB`/`WB-0AW`/`WB-EXECUTOR-EVIDENCE-AUDIT`/`WB-RUNTIME-EXIT-ROOTCAUSE` = DONE；
`WB-0AZ` = BLOCKED；`WB-0AX` = WAITING_FOR_NATURAL_STATE；`WB-GOAL-LOW-RISK-COVERAGE` = QUEUED（Codex 压着）。
⇒ **下一轮不要自己发明任务**：等 Codex 更新 `WORK_QUEUE.json`，或按下面第 2 条做。

### 1. 队列留了三件明确交接

1. **RR-001（`0bi`，最该先看）**：`unexpected_worker_exits` 有两个写入方且规则不一致
   —— 带分类的路径只计 `WORKER_CRASH`，兜底路径**凡非 fatal 全计**。
   `crashes/` 不存在、`latest.log` 0 字节 ⇒ **历史 15 不是「15 次崩溃」**。
   修复位置在 `tools/control_panel.py`，**超出该 Order 的授权文件范围** ⇒ 未动手，见 `REVIEW_REQUESTS.md`。
   ⚠ 72h 验收要求 `unexpected_worker_exits = 0`，而**一个把环境失败也算崩溃的计数器永远到不了 0**。
2. **`0bj` / `WB-0AZ`**：建议 Codex 改成 `WAITING_FOR_NATURAL_STATE`
   （BLOCKED 卡今日已自然出现 ≥2 次），或先裁决「按 `大师悬赏` 弹窗的 `前往查看` 是否可接受」。
3. **队列自己的前提要重算**：`WB-EXECUTOR-EVIDENCE-AUDIT` 的 before_metric
   （「大量空 backend 字段」）描述的是**历史语料**，当前写路径当时已经 **97%** 完整。
   ⇒ 以后把指标**限定在近期 episode** 上，Order 会更准。

### 2. 如果你在本轮没有队列可跑，按价值做这三件（都已定位、都在授权内）

1. **`0be` 的残余**：pin 耗尽每轮多一次「无效 BACK 往返」（1 动作）。
   要去掉需要按 pin 类型分类 ⇒ 新视觉工作。**先算性价比**，别默认去做。
2. **`0bg` 的真机确认**：两个 provenance 修复目前只有单测 + REPLAY；
   下一次审计要**确认不再出现那两种形状**，而不是假设已生效。
3. **`0bl` 的观察项**：客户端可能停在**战斗中**且被判 UNKNOWN；runtime 的 unknown_page 恢复**会按 BACK**，
   而**战斗里按 BACK 的后果未测量**。若再遇到，**等待而不是按**（`tools/wait_for_known_page.py`）。

### 3. 两个本机环境事实（本轮新增，别重新踩）

- **`pytest tests/` 的 27 个「假错误」已修（`0bd`）**：根因是上一轮的 `pytest.ini`
  **自相矛盾**（`tmp_path_retention_policy=none` + `--basetemp=tools/_pt_bt`）。
  **看 `errors`，不要只看 `failures=0`**。一步区分法：单独跑可疑文件。
  遗留：`%TEMP%\pytest-of-xhw` 下 15 个目录 / 1105 个文件（含被中断的 `garbage-*` 残骸），
  **可安全清除**，清一次即断掉自持循环（本轮未清，超出授权范围）。
- **客户端会被游戏自身改变**：本轮实测 `MAP → MAIL` 在两次探针之间自行变化，
  时间点与一封 21:30:06 到达的邮件吻合。⇒ **run 必须重新 observe，不能假设上次的页面还在**。

---

## 手写：本轮（2026-09-15 20:4x GMT+8）—— 操作者纠偏：Intel 冻结，全面转向 MAA 生产接入

**操作者指令**：Intel 成果 KEEP，但**禁止继续把主要时间投入 Intel**；`0ba` 最多 30 分钟收尾后
**立即切回 MAA P0**；顺序 = MAA Capture → MaaExecutorAdapter → 战斗按钮 MAA →
OPEN_MARCH_PAGE A/B → SELECT_RESOURCE MAA → Live A/B → `unexpected_worker_exits` → 重算 Top Failure。

### 0. 先做的一件事：把上一会话**未提交的 2 小时工作**锁进 git（commit `ae9f71b`）

接管时工作树是脏的，里面已经躺着 `0ba` **和** MAA 采集生产化两件事，**全部未提交**
（`winter_agent_v2/runtime.py`、`brain.py`、`tools/run_live.py`、新增
`tests/test_intel_pin_exhaustion.py`，以及 `learning/episodes.jsonl` 里 9 条新 episode）。
本项目已有「外部编辑器把未提交改动回滚」的前科 ⇒ **先校验、再立刻提交**：
`check_wiring.py` = `problems: 0`、相关测试 74 passed（含 65 项定向）。

### 1. 用生产证据核实 MAA 的真实状态（不要只看文档）

| 判据 | 实测 | 结论 |
|---|---|---|
| `capture_backend = MAA_MUMU_EXTRAS` | **349** 条 episode | ✅ 步骤 1 已达成 |
| `recognition_backend = MAA` | **31** 条（`INTEL_HERO_DISPATCH`/`START_MARCH`） | ✅ 步骤 3（战斗按钮）已达成 |
| `action_backend = MAA` | **128** 条 | ✅ |
| `executor_backend = MAA / HYBRID` | **74 / 52** 条 | ✅ |
| 真机采集时延 | MAA **12.6–15.6ms** vs ADB **404–525ms**（26–42×） | ✅ |

⇒ **操作者计划的步骤 1–3 其实早已完成**（上一会话做的），只是没提交。
`MaaExecutorAdapter` 也已存在且能力齐全（`recognize/find/ocr/wait_page/click/swipe/run_task/save_annotated`）。
**真正还没做的**：`START_GATHER`（步骤 4）、`SELECT_RESOURCE`（步骤 5）**一次都没在 MAA 上跑过**。

### 2. `0ba` 收尾 + 一个把「步骤 4 无法测量」解释掉的发现（commit `f9aa8be`）

想跑步骤 4 的 A/B 时，**三次 `GATHER_RESOURCE` 闭环全部在第 1 步就死**：
`stop_reason=SKILL_NOT_ENABLED_FOR_LIVE_LOOP`。根因：城市视图被判定为 `MAP`、
不画可读的行军计数 ⇒ 大脑选 `CHECK_MARCH` ⇒ 而该技能 `verifier=None`、不在
`VERIFIED_ATOMIC` ⇒ 运行时拒绝执行。**这就是 `START_GATHER` 从未在 MAA 上跑过的原因。**

已修的一半：补 `verify_march_count_readable` + 登记进 `VERIFIED_ATOMIC`。
真机 before/after：`execution=null / stop=SKILL_NOT_ENABLED_FOR_LIVE_LOOP`
→ `executed=true / verifier=MARCH_COUNT_NOT_READ`（技能真的会执行了，理由也诚实了）。

⚠ **没修的一半**：计数在城市视图上就是不画（`march_used` 跨帧持续 None，非单帧遮挡），
所以**采集仍然起不来**。城市 vs 世界地图的判定是**独立的页面分类调查**（新开 `0bc`），
且**很可能是 `MARCH_PAGE_NOT_OPEN` 家族的真根因**。

### 3. 顺手修好「全量测试在本机会假红」（新开 `0bd`）

`pytest tests -q` 会出现约 26 个 **setup 阶段**的 `E`。根因**不在项目代码**：
堆栈进入宿主 shim `sitecustomize.py → _check_bulk_delete_guard → SystemExit(1)`，
即 pytest 清理 `%TEMP%\pytest-of-<user>\garbage-*`（实测 463 文件）时触发宿主批量删除闸门，
中断后污染 fixture teardown 并级联出 25 个 `AssertionError`。
**判定证据**：可疑文件**单独跑 12 passed / 0 error**。
**可复现跑法**：`PYTEST_DEBUG_TEMPROOT=<项目内>` **加上** `--basetemp=<项目内>`（光有后者不够）。

### 4. 下一步（按操作者给定顺序）

1. **`0bc`：判定「城市 vs 世界地图」** —— 这是解锁步骤 4/5 的前置。城市视图有底部导航
   （探险/英雄/背包/商店/联盟/城镇）与 `城镇` 按钮，可作为正向信号。**先测量再改**。
2. **步骤 4：`OPEN_MARCH_PAGE`（`START_GATHER`）OLD vs NEW MAA 真机 A/B**
   —— 记录 attempts / success / failure / success_rate / latency。
   OLD 基线已记录：`docs/EXECUTOR_REALITY_AUDIT.md` = **94 次、37%**
   （`START_GATHER` 是注册表里最差的高频技能）。⚠ `tools/maa_live_case.py action-ab`
   **目前写死只支持 `OPEN_HOME`**（`verifier = {"OPEN_HOME": verify_open_home}[skill]`），
   要跑 `START_GATHER` 需先把它改成从 `LiveRuntime.VERIFIED_ATOMIC` 取 verifier。
3. **步骤 5：`SELECT_RESOURCE` MAA 识别**。⚠ 上一会话**有意**保留 LEGACY 并写明理由：
   它走 `RESOURCE_DYNAMIC`（白色方括号锚点 + 157px 步距、滚动条偏移随会话变化），
   属几何/布局问题而非固定模板问题；要迁识别需先有**搜索面板的 MAA 页面模型（每页 ≥2 信号）**。
   ⇒ 这一步不是「加个 template」能完成的。
4. `unexpected_worker_exits = 15` —— 操作者列为 P0，MAA 第一轮后立即查真实 traceback。
5. 最后再重算 Top Failure。

---

## 手写：上一轮（2026-09-15 17:5x GMT+8）—— 解开 pHash「0 / 26」之谜（`0ax`）+ 拆掉无人值守的静默死结（`0az`）

**一句话**：第一大失败 `SEMANTIC_TARGET_NOT_VERIFIED` 的近因不是「控件找不到」，
而是**客户端把「你付不起」画成了红字**；同时无人值守被一张 BLOCKED 巨兽卡静默卡死。

### 1. `0ax` —— 出征花费变红 ⇒ 被误记成视觉失败（已修）

**只测一件事就破案了**：把 29 条记录的 `before` 帧逐张量 pHash 距离与红像素。

| 组 | n | pHash 距离 | 强红像素 |
|---|---:|---:|---:|
| 成功 | 25 | **0**（25/25 全等） | **0** |
| 失败 | 4 | **26**（4/4 全等） | **452** |

阈值 8。两组各自内部**完全一致** ⇒ 不是抖动、不是临界，是两种确定画面：
失败帧的 `10` 是**红色**的（`0av` 已确立：红 = 客户端判定付不起）。
红色数字叠在模板的白色数字上 ⇒ 模板不命中 ⇒ 解析器返 `None` ⇒ 报「控件不存在」。

**两次误诊的教训**：上一轮先判「模板过期（距离 36）」，后又因一次成功判「实测它是好的」——
**两次都没解释成功/失败为何恰好是 0 与 26 两个离散值**。先问那个问题，答案就在屏幕上。

修法**复用** `0av` 的 `unaffordable_cost_pixels()`（29 帧零错分），新增零行颜色代码；
`brain.py` 在 `cost_affordable is False` 时 `SAFE_STOP dispatch_unaffordable_for_stamina`。

### 2. `0ay` —— 6 条 `BTN_DISPATCH` 失败是 `小队设置` 页（已解释，非未解）

红像素为 0，与上条不同因。那些帧是 `小队设置` 页（ROI 上是绿色「战斗」按钮，距离 32 vs 2），
已被既有的「MARCH + INTEL + 无 beast ⇒ INTEL_HERO_DISPATCH」分支覆盖 ⇒ **修复前历史**。

### 3. `0az` —— BLOCKED 巨兽卡把无人值守静默卡死（已修）

`Page.BEAST` + `available=false` ⇒ 原代码 `SAFE_STOP beast_not_actionable`，
**没人把客户端挪走，下一次运行撞同一页再停**。两次独立复现（`dispatches=0`，
nav 三条都是 `steps=1 / elapsed_s=5.4`）。

**严格先测再改**：新写 `tools/probe_back_from_beast.py`，真机按**一次** BACK
⇒ 实测落到 `Page.MAP`（体力恢复可读 110）。据此加 `BACK` 出路 + 一次性守卫
（防卡↔图乒乓）；`verify_safe_back` 正好接受该转移。

### 4. `0ap` 反转 —— 自动化确实在跑

`evidence/intel_pins_20260915_092119.json`（`dispatches=4 claims=10`）+ **81 条**
`intel_pins_20260915_0921` episode（全部 verifier ok），**非本会话手动发起**
⇒ 无人值守在跑，上一轮修的 `0au`/`0e`/`0av` 真的被自动走到。

### 5. 下一步（按价值排序）

1. **`0ba`（新）—— 把第 3 个子成因也拆干净**。`SELECT_INTEL_PIN` 在「每个检测到的 pin
   都已在 40px 内点过」时**刻意返回 `None`**（`runtime.resolve()` 的注释明写是为了不在已消费的
   pin 上循环），但执行器把它记成 `SEMANTIC_TARGET_NOT_VERIFIED` —— 与 `0ax` **同一类错误**。
   真机证据：`evidence/intel_pins_20260915_100034.json` 里 2 条 `page=INTEL→None` 的失败，
   同一次运行还有 `SELECT_INTEL_PIN → BACK → SELECT_INTEL_PIN(FAIL)` 的白烧往返。
   **修法照抄 `0ax` 的做法**：让大脑在情报页知道「无可行动 pin」时不要选 `SELECT_INTEL_PIN`，
   给出诚实的停止理由；不要让解析器返回 `None`。
2. **`0az` 的真机复验**：把客户端故意停在 BLOCKED 卡上，再跑
   `run_live.py --goal INTEL --max-actions 4`，期望**第 1 步是 `BACK` → MAP**。
   本轮只拿到了 BACK 落点的测量（BEAST→MAP，体力 110），**修复后的整链尚未真机跑过**。
3. **`0ax` 的红色臂真机验证**。真机目前只验了「付得起」一侧。
   最省的做法是等某次自动化跑到体力低位又正好停在编队页时**从 episode 里取证**，
   **不要**为了造这个状态去花体力。
4. **`0aw` 的同族排查**：`check_wiring.py` 现在每次都会跑两条 AST 检查；
   若它报 miss，先看是不是又一处脏树残留。
5. **72h Soak 仍未开始** —— 随着 `0az` 这类静默死结被清除，它才真正有意义。
6. `0al`（账号上 ~1007 个 +10 体力道具）仍需**操作者决策**，本轮未动代码。

---

## 手写：上一轮（2026-09-15 16:2x GMT+8）—— 免费体力补给时钟（`0au` + `0e` 双双关闭）+ 拆掉一颗运行时炸弹

**一句话**：面板自己写着下次礼物何时到 —— 读出来存成绝对时刻，同时解决了
「无人值守循环根本走不到地图」和「每 cycle 白花 2 个动作」。**并且发现上一轮留在脏树里的
代码会 AttributeError 崩在免费体力唯一的入口上。**

### 0. 先修炸弹（新增 P0，`0aw`）

脏树里 `ocr.HybridVision.observe` 在 `GET_MORE_STAMINA` 面板分支调用
`self._next_supply_seconds(...)` —— **该方法在任何类上都不存在**
（AST 核对：`HybridVision` 只有 `__init__ / _semantic_roi / observe`）。
它**语法合法** ⇒ `check_wiring.py`（problems: 0）、`pytest`、`import` **全部通过**；
只有真机走到那个面板才炸 —— 而那个面板**正是免费体力唯一的入口**，
且它是 `0au`/`0as`/`0am` 三条修复共同依赖的路径。

⇒ **教训（第 N 次同族）**：`check_wiring.py` 是**执行级**校验但**不是覆盖率校验**；
「方法被调用」不等于「方法存在且被走到」。脏树停在一个会崩的状态时，
下一轮接管必须**先核对上一轮未提交代码的完整性**，不能只看 `problems: 0`。

### 1. `0au` —— 检查根本不可达（已修 + 真机验证）

免费体力检查住在**世界地图**分支，而无人值守的情报循环整个 run 都在情报页。
真机 `04:10:33Z` 实测：从情报 pin 弹窗起手的 run **一次都没站到地图上**。

**修法**：情报页分支在「礼物可能到期」时主动 `OPEN_MAP` 去一次，
由既有的 `stamina_panel_checked` 限一遍（每 run 最多一趟往返）。
措辞刻意**不**标成「本轮已检查」—— 面板还没看，不能先记完成。

### 2. `0e` —— 每个 cycle 白跑两趟（已修 + 真机验证）

补给周期实测 **7 小时**（`04:00:01Z` / `11:00:01Z`），而循环最多 8 cycle/小时
⇒ 约 **16 动作/小时**去确认一个每天只到 3 次的东西。

**修法**：读面板倒计时 → 存 `learning/stamina_supply.json` → 只在到期附近才去。
**未知一律当作到期**（错判「没到期」静默丢 150 体力；错判「到期」只花 2 个动作，代价不对称）。

### 3. Live A/B/C（`dataset/truth_audit/stamina_supply_clock_20260915/`）

| run | 起点 | 结果 |
|---|---|---|
| A `08:14:56Z` | 世界地图 | `1 OPEN_STAMINA_SOURCES` → POPUP，**`next_supply_in_seconds=9900`**（新字段真机首次出现），落盘 `11:00:02.444Z`；**3/3 verifier OK，exit 0** |
| B `08:16Z` | **情报页** | **没有回地图**，直接 `SELECT_INTEL_PIN → OPEN_INTEL_BEAST_TARGET → INTEL_BEAST_START_MARCH`，3/3 OK ← **这就是 `0e` 的节省证据** |
| C `08:17:4xZ` | 时钟人为置到过去 | `2 OPEN_STAMINA_SOURCES` **真的从地图打开了面板** ← 到期路径证实；面板自报 `9710s ⇒ 11:00:01.758Z`，**与 A 到秒一致** |

`2716/2757` 帧级别的语料闸门本轮没做（改动只在两个分支的**前置条件**上，
不改变任何页面判定），改为用 22 项单测 + 三次真机 A/B/C 钉住。

**诚实边界（不许读成更多）**：三次运行礼物**都确实未到期**
⇒ 「时钟说到期 → 领到 +150」这条链真机**只走到开面板**。
`CLAIM_FREE_STAMINA` 本身的 verifier 已由 `0aq` 单独闭环（体力 2→152），
但**两者尚未拼在同一次运行里**。等真实到期（`11:00:02Z` 之后）补这一环。

### 下一步（按价值排序）

1. **`0aw` 的补强**：把「新增/修改的方法是否真的存在」纳入校验。
   本轮是**人工 AST 核对**发现的；`check_wiring.py` 只验既有关键路径。
   最小做法：给它加一条「对改动过的模块，所有 `self._xxx(` 调用点都能解析到定义」。
2. **`0ax` —— 到期驱动的一次真实领取**（`11:00:02Z` 之后跑
   `run_live.py --goal INTEL --max-actions 4`，期望 `OPEN_STAMINA_SOURCES` →
   `CLAIM_FREE_STAMINA` 且体力 +150）。这是把 1+2 闭环的最后一步。
3. **`0au` 的情报页→地图真机路径**：Run B 因时钟未到期未触发，单测已覆盖决策，真机待补。
4. **`0ap` —— 自动化"说在跑、实际没跑"，本轮实测为第 4 次（已重建 + 已复核）**：
   三处 handoff 都写 `e3485d0c-…`（ACTIVE），接口 `list` 里**没有它**、按 id `view` 是
   **not found** ⇒ 上一轮所有修复**都没有被自动执行**。已重建
   **`43aef0ad-d5bc-4d79-9291-0a4da0b0dc27`**（ACTIVE，每小时）并用 `list` 复核。
   ⚠ id 每次重建都会变（`0o`/`0q`/本轮共失效 3 次）⇒ **每轮接管必须重查一次**，
   不得引用文档里的 id 当存在证明。**根因仍未定位。**
5. **`0al`** —— 需操作者决策，未动代码（账上 ~1,007 个 +10 体力道具）。
6. **72 小时 Soak** —— 仍未开始。

## 手写：本轮（2026-09-15 14:0x GMT+8）—— 客户端把「你付不起」直接画成红色（`0av`）

**一句话**：追一条 `DISPATCH_INTEL_BEAST / SEMANTIC_TARGET_NOT_VERIFIED`，追出了**比体力条 OCR 强得多**的可负担性信号。

- 真机 04:11:16Z 出征按钮**在屏幕上**却报"找不到"。定量：模板画的是**白**色花费 `10`
  （且它就是从父帧同一 ROI 裁出的，**父帧 d=0**），真机那帧是**红**色 `10`；
  ccoeff scale 1.0 打分 **0.9152** ⇒ 形状对、只是颜色变了。
- **但颜色本身就是判决**：客户端把"付不起"画成红色。`tools/probe_cost_colour.py` 实测 3 种按钮 5 帧，
  **红色只出现在体力 < 花费的帧上，能付的帧红色像素为 0**（出征 0/10→452；营地面板 7/10→220；
  营地面板 16/10→0；英雄出征页 10/10→0；模板源→0）。**5/5，且不是阈值判断**。
- 已落地：`unaffordable_cost_pixels()` + `HybridVision` 在营地面板写 `stamina.cost_affordable`
  + `brain.py` 把它当**最高优先级**信号（`False` ⇒ 去取免费体力；`None` 表示没量到，**不得阻止**能付的战斗）。
  测试 9 项；加宽定向集 **158 passed, 2 skipped, 33 subtests**。
- **没做**：没把红色变体加进 `BTN_BEAST_DISPATCH` 模板 —— 那只会让我们去点一个必被拒的按钮。
- **没真机复现**：本轮两轮真机（5/5、未命中营地面板）都没走到营地面板，`cost_affordable`
  在**生产单帧**上已验证（真机帧 + 生产视觉栈），但**没在真机运行中**出现过。

## 手写：本轮（2026-09-15 12:2x GMT+8）—— 免费体力首次真机领取闭环 + 两条「空读数」缺陷

**一句话**：`0an` 关掉了（首次真机领到 +150），但顺手挖出两条同源缺陷 —— **「读不到」被当成了「不要做」**。

### 1. 免费体力首次真机领取（`0an` → `0aq`）—— 已闭环

`tools/run_live.py --goal INTEL --max-actions 6 --stop-after CLAIM_FREE_STAMINA`，`exit 0`：

| 步骤 | 技能 | 前 → 后 | 体力 |
|---|---|---|---|
| 1 | `OPEN_STAMINA_SOURCES` | MAP → POPUP | `MAP_HUD 2` → 面板 `2/200, free_claim_available=true` |
| 2 | `CLAIM_FREE_STAMINA` | POPUP → POPUP | `2/200 true` → **`152/200 false`** |

动作是真实的 `TAP_SEMANTIC BTN_CLAIM_FREE_STAMINA`；`verify_free_stamina_claimed` **第一次判真实领取**。
证据：`dataset/truth_audit/free_stamina_claim_20260915/`（含 README 与全部步骤记录）。

### 2. 补给周期实测 7 小时（`0ar`）—— `0e` 的价值上调

领取后 04:12:26Z 显示 `下次补给 06:47:35` ⇒ 下次 **11:00:01Z**；03:59:46.7Z 那张显示 `00:00:15` ⇒ **04:00:01Z**。
**正好差 7 小时** ⇒ 补给时刻 **04:00 / 11:00 / 18:00 / 01:00 UTC**（北京 12:00 / 19:00 / 02:00 / 09:00），
**一天 3–4 次，不是每天一次**。倒计时可当绝对时间用（两帧相隔 42 分钟、外推误差 1 秒）。

### 3. 体力为 0 时读不出 ⇒ 免费体力检查被整条跳过（`0as`）—— 已修（单测）

真机 04:03:02Z：体力真的是 **0**，ROI **读不出任何 token** ⇒ `stamina={}`。后果两条：大脑的 MAP 分支
要求「有数字」才去开面板 ⇒ **恰好在礼物最值钱的一帧跳过检查**；运行时也拒绝解析体力条点击目标。
`tools/probe_stamina_zero.py`：单独一个 `0` 在任何 padding×scale 下最高置信度 **0.73**，且在 `0`/`O` 间跳
⇒ **降阈值不是答案**；加 padding 在 35 帧闸门上**一个值都没变** ⇒ 也不是答案。
`tools/probe_map_gauge_unreadable.py`：6 张 MAP 帧 2 张读不出，**2/2 都是干净 HUD、体力条画着并显示 0**。
**修法**：把「要不要去看」与「能不能点」都从「数字读没读到」解绑（礼物可领与否由**面板自己的模板**判定）。

### 4. 营地战斗被拒会掐死整轮（`0at`）—— 已修（单测）

`runtime.py` 第一次验证失败就 `return` ⇒ `INTEL_HERO_MARCH_REFUSED_FOR_STAMINA` 会终结整轮，
而它离免费体力检查只差一步。**改成可恢复路由**（先例：`RESOURCE_NOT_FOUND`）：把客户端自己的拒绝
记到 `brain.camp_panel_refused`（**客户端判决优先于任何 OCR 读数**）后 `continue`，每轮限 1 次；
运行时**不自己按键**，弹窗仍归 `RuleBrain`。

### 下一步（按价值排序）

1. **`0au` —— 让免费体力检查在无人值守循环里真的跑起来（最高价值，因为它是 1–4 生效的前提）。**
   pin 循环常态停在情报页，`run_live.py` 从情报页出发**全程不回地图** ⇒ 检查根本不执行。
   做法：本轮未检查过免费体力时，大脑主动 `INTEL → OPEN_MAP` 一次；或按 `0ar` 的 7 小时补给时刻
   只在窗口附近去（配合 `0e` 持久化「下次补给」绝对时间）。
2. **`0e`/`0ar` —— 持久化「下次补给」绝对时间**，让检查只在窗口附近付出动作成本。
3. **真机复现 `0as` 与 `0at`**（两者都只有单测）：`0as` 需体力回到 0；`0at` 需「闸门读不到体力 + 客户端拒绝」同时出现。
4. **`0al` —— 需操作者决策，未动代码**：账上 1,007 个「恢复 10 点」道具（≈10,070 体力）而体力长期个位数。
5. **`0ap` —— 拿到一次真实的自动化运行产物之前，不得声称"有无人值守在跑"（第 3 次）。**
6. **72 小时 Soak** —— 仍未开始。



### 1. 营地面板现在报出体力（`0ao` 的一部分）—— 已修 + 真机验证

英雄之旅营地面板是**地图浮层**，世界地图 HUD 完整保留 ⇒ 体力条位置与 `Page.MAP` **完全相同**。
但 `HybridVision` 只对 `Page.MAP`/`RESOURCE_DETAIL` 做体力富化，营地面板被判成 `EXPLORATION`
⇒ **读数被量到了又丢掉**（`stamina={}`）。

定向语料闸门（`tools/probe_camp_panel_stamina.py`，25 张"大脑真的看到营地面板"的生产帧）：
`HUD_STAMINA_ROI` 在 **19/25** 上读出数字（157/165/165/165/18/18/186/155/155/145/36/36/157/157/11/11/2/2/9），
6 张读不出是 **OCR 失败而非 ROI 错**（数字紧邻小红点，被读成 `A`/`m`，conf≈0.7）。
**地图分支的全帧回落对这 6 张一张都救不回（实测 0/6）** ⇒ 不接回落，少一次全帧 OCR。
真机：`before.stamina={'current': 16, 'source': 'CAMP_PANEL_HUD', ...}`（补丁前是 `{}`）。

### 2. 体力不足时先量后付（`0ak` 根因级修法）—— 已修 + 真机验证

大脑在营地面板上比较 `world.stamina.current` 与 `exploration.stamina_cost_displayed`：

- 不足 **且** 本轮还没查过免费礼物 ⇒ `BACK`（`camp_fight_unaffordable_go_get_free_stamina`）→ 落 MAP → 免费体力检查
- 不足 **且** 礼物已查过 / 未授权 ⇒ `SAFE_STOP`
- 够 / 读不出 ⇒ 照常 `INTEL_HERO_START_MARCH`

真机（体力 7，cost 10）第 3 步 = `BACK / camp_fight_unaffordable_go_get_free_stamina`，
`EXPLORATION → MAP`，第 4 步即 `OPEN_STAMINA_SOURCES`，6/6 verifier OK，exit 0。
**反事实**：没有闸门时第 3 步会 `INTEL_HERO_START_MARCH` → 被拒 → 记 `INTEL_HERO_MARCH_REFUSED_FOR_STAMINA`
→ `runtime.py` 在**第一次验证失败就 return** ⇒ 整轮死在第 3 步，永远到不了第 4–5 步。

**踩到的坑（写下来）**：闸门第一版复用了 `stamina_panel_checked` 做循环守卫 —— 而 MAP 分支的免费体力检查
**正是**以 `not stamina_panel_checked` 为闸 ⇒ 等于把自己要去做的那一步关掉。改用独立标志
`unaffordable_camp_panel_left`，并补了一条**端到端**测试（`test_the_route_really_reaches_the_free_stamina_check`）
专门钉住这个耦合。**"设一个标志"之前先问：还有谁在读它？**

### 3. 免费体力检查还给无人值守循环（`0am`）—— 已修 + 真机验证

`tools/run_intel_pins.py` 一直在传 `--no-stamina-check`，而 `config/v2.json` 明说免费礼物
**must be claimed**。该旗子的理由（`STAMINA_SOURCES_NOT_OPEN` 噪声）已查明是 `0i` 的签名：
`skill=OPEN_INTEL` + `action=BTN_OPEN_INTEL_WILD_HUD` + `after=INTEL`（**动作成功了**）却记成 FAILURE，共 9 条。
已删传参。真机（不带旗子）：第 1 步 = `OPEN_STAMINA_SOURCES`，3/3 OK，exit 0。

**留档**：`dataset/truth_audit/camp_panel_stamina_gate_20260915/`（5 帧 + 两次运行全量 step 记录 + README）。

### 4. 视觉层不再抛异常（`0ao`）

`SemanticROIVision.find` 的 `matches` 在 `ccoeff` 分支下可能为空 ⇒ `min([])` 抛 `ValueError`。
4 个语义是全 ccoeff 单记录（含 `BTN_HERO_CAMP_FIGHT`、`BTN_HERO_FIGHT`）。已加空列表守卫。
暴露它的是我自己把 104 张 302×79 标题裁剪图写进了 `dataset/raw` ⇒ 已移到 `dataset/probe_output/`（移动，未删除）。

### 下一个账号的最优动作（按价值排序）

1. **`0an`：盯 `CLAIM_FREE_STAMINA` 的真机首执**。免费礼物到期后跑
   `run_live.py --goal INTEL --max-actions 4`，若 `free_claim_available=true` 就应出现
   `CLAIM_FREE_STAMINA`（全语料 0 次）。**它的 verifier 从未判过真实领取**，这是唯一还没真机验证的
   关键动作；若判错，循环每个 cycle 都会产出一条失败。
2. **`0e`：持久化「下次补给」倒计时**（优先级已升高）。现在每个 cycle 白花 ≤2 个动作（最多 8 cycle/小时
   ≈ 16 动作/小时），而三次真机运行礼物一次都没到期。存下倒计时即可把这项降到接近 0。
3. **`0al`（需操作者决策，勿擅自扩权）**：面板里有 `领主体力 / 使用后恢复10点 / [使用] / 库存 1,007`
   ≈ 上万体力道具，而体力常年在个位数。该行不是付费行，但 `stamina_policy.note` 只允许 `BTN_CLAIM_FREE_STAMINA`。
4. **`0ap`：自动化"说在跑、实际没跑"第 3 次**。在拿到一次真实的自动化运行产物前，不得声称有无人值守在跑。
5. **72h Soak** —— 仍未开始。

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
CURRENT PRIORITY: fill the missing skills that block 3 goal(s)
CURRENT TASK: every highest-leverage missing skill is DESIGN-BLOCKED — no draft is implementable from the manifest alone (14 NOT_REGISTERED, 6 NO_VERIFIER); see DESIGN-BLOCKED below

WHY: 3 goal(s) BLOCKED, 9 PARTIAL, mean implementation coverage 0.5713. The blocked goals share one small set of never-implemented skills, so one skill purchase can move several goals at once.

CURRENT ROOT CAUSE: FREE_STAMINA_CLAIM_NOT_PROVEN — 153 in the last 2 day(s), 236 all-time, last seen 2026-09-20T10:18:03.144489+00:00
LAST GOOD COMMIT: e4fd245
CURRENT DIRTY FILES: 149
LAST PRODUCTION EPISODE: {"skill": "DISMISS_INTEL_GENERIC_REWARD", "result": "FAILURE", "recorded_at": "2026-09-20T13:00:04.155708+00:00", "episode_id": "20260920_205419_420369", "before_screenshot": "E:\\无尽冬日智能体\\dataset\\raw\\control_panel\\runtime_auto\\20260920_205419_420369\\20260920_205419_420369_step_014_before_20260920T130002712730.png", "after_screenshot": ""}
TOP FAILURE: {"failure_type": "FREE_STAMINA_CLAIM_NOT_PROVEN", "count": 236, "recent": 153, "last_seen": "2026-09-20T10:18:03.144489+00:00", "dates": {"2026-09-18": 221, "2026-09-19": 14, "2026-09-20": 1}, "undated": 0, "top_skills": [["CLAIM_FREE_STAMINA", 236]]}
TOP FAILURE IS RANKED BY RECENT FIRST: read `recent` (last 2 day(s), floor 2026-09-18T13:00:04.155708+00:00) before `count` (all-time). A failure type with recent=0 is history, not a current defect.

BLOCKED GOALS: ['ALLIANCE_TIMED_EVENTS', 'USE_FREE_ARENA_ATTEMPTS', 'LABYRINTH_DAILY']
MISSING SKILLS BY LEVERAGE: [('CHECK_ALLIANCE_EVENT', 2), ('CLAIM_EVENT_TIER', 2), ('JOIN_RALLY', 2), ('READ_BEAR_TIMER', 2), ('READ_COUNTER', 2), ('READ_TIMER', 2), ('USE_ACTIVITY_ATTEMPT', 2), ('ALLIANCE_HELP', 1), ('ALLIANCE_TECH_CONTRIBUTE', 1), ('OPEN_ARENA', 1)]
DESIGN-BLOCKED (not implementable from the draft alone; each needs a live frame of its page first): CHECK_ALLIANCE_EVENT [NOT_REGISTERED] — requires semantic(s) `ALLIANCE_EVENT_ENTRY` that do not exist in dataset/candidate/template_manifest.json; the page has never been observed live, so this needs new vision design first; CLAIM_EVENT_TIER [NOT_REGISTERED] — requires semantic(s) `EVENT_TIER_CLAIMABLE` that do not exist in dataset/candidate/template_manifest.json; the page has never been observed live, so this needs new vision design first; JOIN_RALLY [NO_VERIFIER] — has no design draft at all (absent from winter_agent_v2/skill_factory.PRIORS), so its required semantics and success condition are undefined; READ_BEAR_TIMER [NOT_REGISTERED] — requires semantic(s) `BEAR_TIMER` that do not exist in dataset/candidate/template_manifest.json; the page has never been observed live, so this needs new vision design first; READ_COUNTER [NO_VERIFIER] — has no design draft at all (absent from winter_agent_v2/skill_factory.PRIORS), so its required semantics and success condition are undefined; READ_TIMER [NO_VERIFIER] — has no design draft at all (absent from winter_agent_v2/skill_factory.PRIORS), so its required semantics and success condition are undefined ... and 14 more
NEVER EXECUTED SKILLS (first 12): ['ATTACK_BEAST_CARD', 'CANCEL_DUPLICATE_TARGET', 'CLAIM_REWARD', 'JOIN_RALLY', 'NAVIGATE_TO', 'READ_COUNTER', 'READ_INTEL_LIST', 'READ_TIMER', 'RECOVER_HOME', 'REINFORCE_TARGET', 'RELAX_RESOURCE_LEVEL', 'SELECT_BEAST_TARGET_MAMMOTH']

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
