# TROOP_SELECT — 出征页的编队预设行

Status: `CANDIDATE`（知识完整 + 识别已实现并有定向测试；**未真机尝试**）。
上限 `READY_FOR_LIVE_VERIFY` —— 只有一次带 verifier PASS 的 production episode 才能改这个字。

能力：`CAP-G09 TROOP_SELECT`　技能：`SELECT_TROOP_PRESET`　目标：`PARTICIPATE_BEAR`
优先级：P1 已解锁的 MISSING / NEVER_TRIED（bootstrap 扫描器第 1 名，score 749）

## 为什么做 / 做到什么程度

出征前选哪套编队预设。它挡着 `PARTICIPATE_BEAR`（巨熊车头要用「熊*」/「开车」预设）与
`AVOID_STAMINA_WASTE`、`ALLIANCE_TIMED_EVENTS`。**做到「点中目标预设块，并且能证明它被选中」为止**；
按「出征」那一跳属于 `CONFIRM_MARCH`，不在本能力内。

## 实测（全部读自本项目自己的真机归档帧，2026-09-21，720×1280 国服）

复现命令与产物：

```bash
"E:/无尽冬日智能体/.venv/Scripts/python.exe" -u tools/probe_troop_preset_rule.py   # 全语料闸门
"E:/无尽冬日智能体/.venv/Scripts/python.exe" -u tools/probe_troop_preset_rows.py   # 逐行颜色
"E:/无尽冬日智能体/.venv/Scripts/python.exe" -u tools/probe_troop_preset_diff.py   # 两帧差异
```

| 事实 | 读数 |
|---|---|
| 页面门控 | 条带上方 y=88..96 均色 = (13,129,198)；B∈[192,198]、G∈[129,133]、R≤35 |
| 唯一近似的干扰页 | 联盟科技页，其条带 B=227 —— **只靠「蓝通道」这一项就能分开**，对称容差会放它进来 |
| 全语料闸门 | 454 帧 720×1280，26 帧读出本页，收紧后假阳性 0 |
| 找块 | y=104..144 内偏离条带色 ≥3 采样点的列连续段；本账号 9 段 = 8 个预设 + 最右保存钮（x621..685） |
| 本账号预设命名 | 打野 / 书咏 / 杰西 / 杰赛尔 / 尼莫 / 熊6 / 熊7 / 开车 |
| 选中态 | 块左右边框列（内缩 6px，y=112..136）金色 (245,188,61)；未选中亮蓝 (87,190,255) |
| 真值复现 | `bear_preset6.png` 第 6 段 (x405..463) gold=81 / blue=0，其余 8 段 gold=0 |

**为什么块必须当帧找、不能写死八个坐标**：块数由玩家定义；同语料另一些出征帧里块宽
58..59 变 67..68、首块中心 62 变 67。

**这一行不是巨熊专属**：26 帧覆盖采集 / 异兽 / 情报 / 巨熊四条来源，是全局「出征」页控件。

## 未证明的部分（别当成已完成）

1. **「点击 → 金边移动」尚未被证明。** 归档里只有 1 帧出现金边，且它与无金边的帧**不是同一次
   点击的前后帧**：战力读数 55,813,315 vs 96,098,265，兵力读数也不同，属两次不同捕获。
   `tools/probe_troop_preset_diff.py` 量出条带外差异 37640 个采样块 vs 条带内 504。
   ⇒ 这正是**真机校准要回答的唯一问题**。
2. 选择动作**是否产生资源扣减**未测（26 帧中该动作前后没有资源确认弹窗，仅此而已）。
3. `TARGET_PRESET_ABSENT`（账号没有策略要的那个预设）从未观测到。

## 已落在代码里的部分

`winter_agent_v2/vision.py`

- `read_troop_preset_strip(path) -> TroopPresetStrip | None`
  —— 页面不对返回 `None`；页面对但没有预设被选返回 `selected_index=None`（这是两个不同的答案）。
- `TroopPresetStrip.center_norm(index)` —— 目标块的点击中心，块号越界返回 `None`。

`tests/test_troop_preset_strip.py` —— 12 项：合成帧的正/负例（含「联盟科技条带不得被读成本页」
这一条把唯一的假阳性钉住）、真机帧、`center_norm` 边界、不可变值对象，以及全语料闸门。

## 还差什么才算 READY_FOR_LIVE_VERIFY

bootstrap 简报当前给出的三个阻塞项（`bootstrap_scan.py --capability CAP-G09`）：

```
DESIGN_COMPLETE -> NOT_PROVEN（缺字段 ['Recovery']；未注册语义 ['TROOP_PRESET']；verifier 未绑定）
```

1. **缺字段 'Recovery'** —— 已解决，但**不在扫描器看的地方**。
   扫描器的 Recovery 只从 `dataset/candidate/<code>.json` 的 `recovery` 键取
   （`capability_bootstrap._facets`）。**实测把这个草稿放进去反而更差**：
   `_match_draft` 会按目录里的 `code` 命中草稿，于是 `prior = PRIORS.get('TROOP_SELECT')` 查空，
   Navigation / Action / Verifier 从「已有来源」退化成 UNKNOWN，能力还被标成 `IN_FLIGHT`
   死锁（既不再预载、也不在注册表里）。**已回滚**，理由记在这里，避免下一个人再试一次。
   真正该修的是扫描器的草稿查找键（应同时认 `existing_skill`）—— 属于扫描器的独立缺陷。
2. **未注册语义 `TROOP_PRESET`** —— 它是**派生目标**（由几何算出，不是模板），
   而扫描器的 `registered_semantics` 只认 `dataset/candidate/template_manifest.json` 里的模板记录。
   **派生目标因此永远显示为「未注册」**，这是扫描器的第二个盲点。
   既有的同类（`RESOURCE_DYNAMIC` / `BEAST_SEARCH_TAB` …）都不在模板清单里，
   它们靠 `tools/check_wiring.py` 的 `_derived_targets` 白名单通过。
3. **verifier 未绑定** —— 需要先有 `skills.py` 条目、`LiveRuntime.VERIFIED_ATOMIC` 绑定、
   以及 `WorldState` 上承载 `selected_index` 的字段；verifier 形如
   `troop_policy_applied = before.selected_index != 目标 且 after.selected_index == 目标`。

接线四件（`docs/ADDING_A_LIVE_ROUTE.md` §4）：解析器分支（`LiveRuntime._resolve_semantic_target`
的 `TROOP_PRESET` 分支，需要一个 `troop_preset` 参数从 brain 传下来）、两条 verifier 绑定、
vision 读「选中索引」这个导航事实、brain 的 goal 路由。

## 真机校准请求（尚未排队）

- **设备要证明什么**：点一次**非**选中的预设块之后，金边移动到该块，且 before/after 两帧可追溯。
- **台架**：`run_live.py --goal PARTICIPATE_BEAR`（走到编队页为止；**不按「出征」**，不产生支出）。
- **最低证据**：一次 before/after 帧对 + `troop_policy_applied` PASS + 一个带 `recorded_at` 的 episode。
- **为什么没排队**：预载派单被主闭环闸门拒绝 ——
  `GATE_REFUSED: NOT_ARMED_MAIN_LOOP_P0`（P0-D、P0-F 未过）。这是操作者要求的顺序：
  主闭环未证完之前，预载不占设备、不占开发槽。

## 不要重复

- 不要写死预设块坐标（块数由玩家定义）。
- 不要用对称的颜色容差做页面门控（会放进联盟科技页）。
- 不要把 `bear_preset6.png` 与 `bear_troop_setup.png` 当成同一次点击的前后帧 —— 它们不是。
