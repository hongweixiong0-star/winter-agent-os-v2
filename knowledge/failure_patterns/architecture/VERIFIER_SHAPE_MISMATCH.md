# VERIFIER_SHAPE_MISMATCH

- **分类**：`ARCHITECTURE_CONTRACT`（根因大类：`ENVIRONMENT_BLOCK` 之外的第二类——**写了但插不上插座的契约**）
- **记录日期**：2026-09-17
- **记录者**：winter-agent-v2-dev（寒野）
- **可复现**：`python tools/verifier_binding_audit.py --unbound-verifiers`

## 事实

运行时的 verifier 契约只接受一种形状：

```python
Verifier = Callable[[WorldState, WorldState], VerificationResult]
verification = self.VERIFIED_ATOMIC[decision.skill](before, after)   # runtime.py:721 / 736
```

也就是说 **verifier 拿不到"这一步到底作用在哪个对象上"**（哪个建筑 / 哪个研究节点 /
哪个兵种 / 哪个占领目标），也拿不到中间帧。而 `VERIFIED_ATOMIC` 是一个普通 dict，
**绑一个签名不符的函数不会报任何错**——它只是永远不被调用，而技能永远不被派发。
"绑不上"在注册表里与"没写过"**完全无法区分**。

测量（`tools/verifier_binding_audit.py`）：

| 形状 | 数量 | 例子 | 缺什么 |
|---|---:|---|---|
| **PARAMETER** | 10 | `verify_building_upgrade(before, after, building_id)`<br>`verify_research_started(before, after, research_id)`<br>`verify_training_started(before, after, troop_type)`<br>`verify_rally_joined(before, after, target)` | 运行时**不把决策的身份传进 verifier** |
| **FRAME** | 7 | `verify_alliance_gifts_claim(before, reward, after)`<br>`verify_daily_claim(before, reward, after)`<br>`verify_mail_claim(before, reward, after)` | 需要**中间那一帧**（点下去后的反馈横幅）；步骤循环只抓 before/after |
| **STATE** | 4 | `verify_alliance_help_auto_active(state)`<br>`verify_research_queue(state)` | 单参"只观察"断言，运行时也没有这个形状 |

**18 个 verifier 完全无法被任何技能触达**（10 PARAMETER + 7 FRAME + 4 STATE，
扣除 3 个已通过适配器接上的，见下）。

### 已经存在的绕过：3 个 lambda 适配器（**不是 bug，但要逐个判断**）

```python
"BUILDING_UPGRADE": lambda before, after: verify_building_upgrade(before, after, str(before.building.get("id", ""))),
"RESEARCH":        lambda before, after: verify_research_started(before, after, str(before.research.get("node", ""))),
"TRAIN_TROOPS":    lambda before, after: verify_training_started(before, after, str(before.training.get("troop_type", ""))),
```

它们**是可派发的**（适配器本身是两参）。注入值取自 **before 帧**，于是：

- `verify_training_started` / `verify_research_started` 用注入值比对 **after** 状态
  （`after.training["troop_type"] == troop_type`、`after.research["node"] == research_id`）
  ⇒ **仍然是真交叉校验**，没有失效。
- `verify_building_upgrade` 的 `target_ok = before.building["id"] == building_id` **这一项恒真**，
  但同一条里 `after.building["queue_building"] == building_id` 仍在做真校验
  ⇒ 判据**被削弱一项，未失效**。

⚠ 所以"看到自指就喊伪造"是**过度判断**（本项目刚犯过一次）。正确做法是
**逐个把注入表达式打出来**，再对照 verifier 体判断那一项是否还在做功。
`--unbound-verifiers` 已经把注入表达式逐条打印。

### 它挡住的 Capability

**不是** BUILD / TRAIN（它们已由适配器接上，见下）。真正被挡住的是：

- `BEAST_HUNT`（`verify_beast_hunt` 5 参）、`DAILY_HERO_RECRUIT`（6 参）、
  `RALLY_JOIN` / `RALLY_CREATE`（`target`）、`GATHER_CYCLE`（`expected_resource`）、
  `MAIL_TAB`（`expected_tab`，注意参数**在最前面**，不能按位置分类）
- FRAME 家族对应的奖励领取链（`verify_mail_claim` / `verify_daily_claim` / `verify_intel_claim` …）
  它们各自的技能**已经用另写的两帧版本**绕过（这正是这个家族被逐个手改 4 次的原因）

## 根因

1. **契约是一行 `Callable[...]`，没有任何东西检查它。** 没有校验器、没有导入期检查、
   没有 CI 断言 ⇒ 静默失败的两个条件同时成立。
2. **同一个家族被逐个绕过 4 次**（`ALLIANCE_GIFTS`、`CHECK_MARCH`、奖励弹窗来源、训练/研究路线），
   每次都是"再写一个两帧版本"，从未回头问"为什么还有 18 个写好的 verifier 没人能用"。
3. **没有机器可读的"拼图清单"**：只有人眼逐个读代码才能发现"只差一块"。

## Lesson（写入永久行为）

1. **绑定缺口必须能被机器枚举**：`tools/verifier_binding_audit.py`。它按"缺哪一块"分类 90 个技能，
   单独列出 18 个不可达 verifier 及形状、3 个适配器及其注入表达式，并给出
   **A 组：拼图齐了但从未真机成功**（当前 15 个）。**开新 Capability 前先跑它。**
2. **`PARAMETER` / `FRAME` / `STATE` 不是同一件事，不许合并修**：
   - `PARAMETER` ⇒ 运行时需把**决策的身份**传下去（操作者 P0-2 的原话：
     "BUILD 禁止反推建筑身份"）。
   - `FRAME` ⇒ 需要一次**中间取帧**（可选、按技能开启，对现有 74 个两帧绑定零影响）。
   - `STATE` ⇒ 需要"只观察"的原子形状（`CHECK_MARCH` 已有先例）。
3. **弱化判据必须有记录**。适配器注入 before 帧值是可接受的工程折中，
   但**必须在卡上写明哪一项因此不再做功**，不能让它看起来像一个满判据的 verifier。
4. **真机历史只统计带 `recorded_at` 的行**。本次差点写错：旧脚本显示
   `ALLIANCE_TECH_CONTRIBUTE` "4 次成功"，而那 4 行**没有 `recorded_at` / `episode_id` /
   `verifier_ok`**，是导入行。`tools/reuse_check.py` 早就守这条口径，新工具必须复用。

## 本轮被测量推翻的三个假设（如实记录）

1. "三元 verifier = 需要中间帧" → 错：多数第三参是**技能参数**。
2. "18 个都绑不上" → 错：3 个已用 lambda 适配器接上，可派发。
3. "自指注入 = 伪造证据" → 错：训练/研究是**真交叉校验**，只有建筑的 `id == id` 一项失效。

**教训：先枚举，再下结论。三次里有三次第一直觉不完整。**

## 触发条件

- 某个技能"代码看起来齐全"却永远 `BLOCKED` / `CANDIDATE` / 从不被派发
- 打算新写一个 verifier（**先确认要写哪种形状**，不要默认两帧）
- 打算"再加一个两帧版本绕过"某个 verifier
- 讨论 BUILD / RESEARCH / TRAIN / RALLY / BEAST 落地

## 相关

- `tools/verifier_binding_audit.py` — 本卡的度量工具（只读，可复现）
- `winter_agent_v2/runtime.py:43,151-153,721,736` — 契约、适配器与调用点
- `winter_agent_v2/verifier.py` — 18 个不可达 verifier 所在
- `.workbuddy-ai/handoff/00_MASTER_RULES.md` §2 架构冻结 / §6 Verifier First
- `knowledge/failure_patterns/tooling/TOOLING_INTERPRETER_DRIFT.md` — 同族"静默降级"卡
