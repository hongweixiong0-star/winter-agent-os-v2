# 技能生成闭环（WorkBuddy ⇄ WinterAgent）

> 2026-10-18 首版。目标是让"运行 → 发现问题 → 生成/修正技能 → 实机验证 → 固化"这条线
> 有真实的承载物，而不是一份方案。

## 一、闭环的九步与它们的实现位置

| # | 步骤 | 谁做 | 实现 |
|---|---|---|---|
| 1 | WinterAgent 记录未知问题 | 运行时 | `learning/unknown_requests/*.json`（含帧路径、OCR 文本与框、goal、page_label）；`learning/episodes.jsonl`（append-only） |
| 2 | WorkBuddy 自动读取 | 本工具链 | `tools/skill_loop.py brief` → `winter_agent_v2/skill_loop.py` |
| 3 | AI 分析 | WorkBuddy（外部） | 读 brief；不在运行时内，不装模型 |
| 4 | 生成/修正技能 | WorkBuddy | `skills.py` 的 `Skill(...)` + `runtime.LiveRuntime.VERIFIED_ATOMIC` 绑定 + `brain.py` 的 `popup` 分支 |
| 5 | 测试 | WorkBuddy | `tests/test_skill_loop.py`、注册表一致性、弹窗/运行时回归 |
| 6 | WinterAgent 加载 | 运行时 | `p0_registry()` / `v2_registry()` —— 技能是代码，加载即注册 |
| 7 | MAA 实机执行 | 运行时 | `tools/skill_loop_run.py`（`Executor` + `build_maa_adapter` + `DeviceLease`） |
| 8 | Verifier 判定 + Episode | 运行时 | 同一工具：`LiveRuntime.VERIFIED_ATOMIC[skill]` → `learning/episodes.jsonl` |
| 9 | 再读反馈 / 固化 | WorkBuddy | `skill_loop.promotion_verdict()`：≥3 次已验证成功且最近无失败 |

## 二、增量读取（第 2 步的关键）

`episodes.jsonl` 是 128 MB 的 append-only 账本，整文件扫一遍不是可接受的"每次分析"成本。

- **账本**：按**字节偏移**读，只消费以换行结尾的完整行；写了一半的行留到下一次。
- **未知请求**：按 `request_id` 去重，文件不可变，天然增量。
- **游标**：`learning/skill_loop/cursor.json`。读不到 = 从此刻开始（第一遍是基线）。
- **简报**：`learning/skill_loop/briefs/brief_<stamp>.json`，把"读了哪些行"固化下来，
  一周后还能复查这次判断的依据。

简报回答分析需要的五个问题（都带实测行，不是推断）：

1. 哪些页面未覆盖 → `unknowns`（帧、OCR、goal）
2. 是否缺技能 → `popup_skill_coverage` / `popups_without_named_skill` /
   `popups_generic_fallback_only`
3. 哪个现有技能在失败 → `episodes.failures` 按 `(skill, failure_type)` 聚合
4. 失败是识别/前置/动作/验证哪一环 → 行里的 `failure_type` + `verifier_ok`
5. 能否复用 → `registry_skills` 与每个 popup 的映射

> `knowledge/ui/popup_skill_map.json` 是"popup → 技能"的**数据**版本，从 `brain.py` 的
> 分支提取。首版简报用"技能名包含 popup 名"猜覆盖，把 8 个其实有分支的 popup 报成未覆盖；
> 名字匹配对 `EXIT_CONFIRM → CLOSE_POPUP` 永远不会成立。

## 二·补、失败 → 修复队列（第 3→4 步的另一半）

生成新技能只处理"没有技能"的情况；"技能卡住了"是另一半，入口是：

```bash
python tools/skill_loop.py repairs            # 默认阈值 3、最多 10 条
python tools/skill_loop.py repairs --threshold 5 --limit 5
```

判定规则不在这里重写，用的是 `skill_repair.should_escalate` 的两条：

- **只算最后一段连续失败**：上个月连败五次、之后通过二十次的技能不算坏。
- **只认可被截图解释的失败**（`REPAIRABLE_FAILURES`）：`QUEUE_FULL` 是游戏状态答案，
  给模型看十张图也看不出队列满。

产物 `learning/skill_loop/repair_queue.json`：技能、连续失败次数、失败类型、goal、
首末失败时间、最近三帧。按卡住程度排序。

**排除 `NON_SKILL_LEDGER_VALUES`**：`SAFE_STOP` / `PRINTED_TAP` / `OBSERVE_ONLY` 是账本值
不是技能，第一版没排除，队列里出现了"修复 SAFE_STOP 技能"。

**首跑实测（2026-10-18）**：2 条——`OPEN_BEAST_SEARCH_TAB` 连续 28 次、
`SCROLL_QUICK_PANEL_BACK` 5 次。前者看帧后**没有改**：那帧选中的 tab 是「冰原巨兽」，
技能要的是「野兽」，验证器证据 `resource_selected_tab == "BEAST"` 是对的（两者不可混，
见 `verifier.py` 的 docstring）；这是定位/目标错误，盲改验证器会制造假通过。

## 二·补二、反馈与固化（第 8→9 步）

```bash
python tools/skill_loop.py promotions
```

`outcomes.jsonl` 是**闭环自己的账**（它生成/执行过什么、判定如何），与 `episodes.jsonl`
（运行时的一步）分开：episode 不该长出只有分析半边读的字段。

- `skill_loop.read_outcomes()`：尾部读，坏行跳过；`brief` 会带最近 20 条，这样下一轮
  分析不会把已经试过的技能再提一遍。
- `skill_loop.pending_promotions()`：只看**本闭环碰过的技能**，逐个问
  `promotion_verdict`，分成 `ready`（够条件固化）与 `waiting`（附拒绝原因：
  `NO_PRODUCTION_ROWS` / `NOT_ENOUGH_VERIFIED_PASSES` / `RECENT_FAILURE`）。

固化的动作仍然是**改代码里的 `SkillState`**，不是运行时写文件：技能状态是代码的一部分，
一个能自己把自己提升为 VERIFIED 的技能库，等于没有状态。`promotions` 只回答"该不该提"，
提出动作由人（或本闭环的代码提交）完成。

**生成那一刻也要留痕**。`skill_loop_run` 只在实机跑过之后写 outcome，所以"我生成过什么"
一度只存在于提交信息里。现在用 `tools/skill_loop.py record --verdict GENERATED` 回填，
两个首批技能各有一条，evidence 里写明依据的行数、修正类型、以及**实机未跑的原因**。
`promotions` 随后的回答是诚实的：两条都是 `NO_PRODUCTION_ROWS`——**没跑过就是没跑过**。

**一个容易误判的边界**：`docs/SKILL_COVERAGE.md` / `goal_skill_graph.json` 按
goal→capability 组织，而这两个 popup 技能是"任何 goal 都可能撞上的兜底"，不属于任何
capability，所以重生成这些文档时它们**不会出现**。这是口径，不是遗漏——它们由
`brain.py` 的 popup 分支在 goal 路由之前选中，而不是由某个 goal 的能力表选中。

## 三·补、第二个案例：修一个"动作根本没发出"的失败

`PURCHASE_POPUP` 在账本里只有 3 行，但**三行全失败**：

```
skill=CLOSE_POPUP  failure=SEMANTIC_TARGET_NOT_VERIFIED  after_screenshot=""  (×3)
```

空的 `after_screenshot` 是关键：不是"点了没关掉"，是**没点**。brain 走的是
`blocking_popup → CLOSE_POPUP → BTN_CLOSE`，而真实帧是 ¥328 礼包页，`BTN_CLOSE` 在那上面
解析不到。修正不是换模板，是换动作：

- `DISMISS_PURCHASE_POPUP`：`Page.POPUP` / `PRESS_BACK` / `LOW` / `POPUP_CLOSED` /
  recovery `CLOSE_POPUP`
- brain 在 `blocking_popup` 兜底之前点名该 popup，模板查找不再花在购买面上

**为什么 Back 更安全**：购买面上"没有坐标"本身就是安全属性——没有哪个点会落到「购买」。
这比"更准的 X 模板"可靠，因为后者永远有瞄错的可能。

## 三·补二、两个案例的差别（这是判据）

| 案例 | 原状态 | 修正的性质 |
|---|---|---|
| `GET_MORE_STAMINA` | 通用 BACK 已能关掉（21 次成功），但没有验证器 | 补验证，不改动作 |
| `PURCHASE_POPUP` | 通用 CLOSE_POPUP 三次都没发出动作 | 改动作，从"要定位"变成"不需要定位" |

闭环的价值不在"生成了几个技能"，而在于**能分清这两种情况**：前者的正确动作是补证据，
后者才是改实现。把前者当后者改，会把一个能用的技能改坏。

## 三、首个真实案例：`GET_MORE_STAMINA`

**来源（不是构造的）**：`episodes.jsonl` 中 53 行 `state_before.popup == GET_MORE_STAMINA`。
其中 21 次由**通用 `BACK`** 关闭成功，1 次 `SAFE_BACK_NOT_PROVEN`。

**诊断**：不是"没有技能"，而是"有路由、没有验证"——通用 `BACK` 没有 verifier 绑定，
账本无法区分"关掉了"和"按了没反应"。

**修正**（三处，缺一不可）：

- `skills.py`：新增 `DISMISS_GET_MORE_STAMINA`（`Page.POPUP` / `PRESS_BACK` / `LOW` /
  `verifier="POPUP_CLOSED"` / `recovery=("CLOSE_POPUP",)`）。`PRESS_BACK` 是刻意的：
  面板的购买行不可成为目标。
- `runtime.py`：`DISMISS_GET_MORE_STAMINA → verify_popup_closed`（形状盲：前是弹窗、后不是）。
- `brain.py`：`GET_MORE_STAMINA` 的两条 `Decision("BACK", ...)` 改为返回该技能。
  **先领免费体力的分支原样保留**（`free_claim_available` → `CLAIM_FREE_STAMINA`），
  改的只是"关闭"那一步。

**离线复算（真实生产帧，非实机）**：episode `20261017_012523_158076` step_007
（原技能 `BACK`，`verifier_ok=true`）

```
before: POPUP  popup=GET_MORE_STAMINA   skill.ready(before)=True
after : MAP    popup=None
verify_popup_closed -> True (OK)
```

**全量复算 22 组帧对**（`materials/experiments/retired_20261018/acceptance_20261018/skill_loop/offline_recompute_GET_MORE_STAMINA.json`）：
账本里 `popup=GET_MORE_STAMINA` 且 `skill=BACK`、前后帧都在盘上的 22 组——

```
precondition ready   22 / 22
verify_popup_closed  21 / 22 OK
1 failure            20261008_213639_061389 step_004
                     before POPUP/GET_MORE_STAMINA -> after POPUP/GET_MORE_STAMINA
```

那 1 组不是复算的误差：账本里 step_004 本来就记着
`BACK / FAILURE / SAFE_BACK_NOT_PROVEN / popup_closed=False`，step_005 重试才成功。
**新验证器与旧记录在这 22 组上逐组一致**，并且它会把 step_004 判为失败而不是"按了就完事"。
这正是"补验证"想要的效果：同一个 Back，失败的那次不再被记成通过。

这证明技能契约与验证器在真实帧上成立；**它不证明一次真实点击**——那是下一步。

## 四、实机执行为什么必须由用户触发

`tools/skill_loop_run.py` 已实现完整执行链（截图 → `vision.observe` → `skill.ready` →
`Executor(MAA)` → 截图 → verifier → episode → outcome），但它拒绝在两件事成立时运行：

1. **模式是 AUTO**。`learning/mode_state.json` 记录：`AUTO`，发起方 `USER`，
   `user_latch=true`，回切条件"用户指令（§4 触发 2：WorkBuddy 不得自主切回 Manual）"。
   当前 AUTO **未运行**（面板进程已不在），但模式闸门仍生效——这是规则，不是故障。
2. **设备上有另一套自动化**。2026-10-18 22:26 实机抓帧：前台是
   `com.xm.wujindongri`（"XM-冬日助手 v1.173"，带 `:web/:shell/:remote/:sc/:vd` 子进程，
   以 root 运行），`com.gof.china` 在后台。两套自动化抢同一块屏幕，此时发任何点击都是
   不可归因的。

所以实机的正确触发方式是：**用户**切 Manual、关掉第三方助手、确认游戏在前台，然后

```bash
E:\WinterAgent\.venv\Scripts\python.exe tools\skill_loop_run.py \
  --skill DISMISS_GET_MORE_STAMINA --purpose "close the stamina offer without buying"
```

成功一次后，`promotion_verdict` 需要 3 次已验证成功且最近无失败才会说 `promote: true`；
在那之前技能保持 `CANDIDATE`——"代码存在"不等于"已验证"。

## 五、边界（不会做）

- 不在运行时内装模型：分析发生在 WorkBuddy，运行时只读写文件。
- 不绕过 MAA 点击：`skill_loop_run` 的 `Executor` 是项目唯一执行链。
- Replay 不计入 promoted：`skill_loop.SIMULATION_MODES` 排除 `SIMULATION/REPLAY/DRY_RUN`。
- 不自动扩权：`skill_loop_run` 只执行**已注册且已绑定验证器**的技能，二者缺一即拒绝。
- 高风险动作仍在 `SafetyPolicy` 与 `HIGH_RISK_WORDS` 之下，技能不参与风险判断的改写。
