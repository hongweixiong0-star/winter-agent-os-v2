# 90 个被挡的候选**逐字复现**；池里**冻结的变成两个**；`BEAR_AUTO_JOIN` 却不在可派发集里（2026-10-14）

> 复核决策包 **D-H**（"90 个候选无试跑路径"，此前标"未复核"）。
> 先查它有没有像别的那样**已被推翻**——结果是：**没被推翻，逐字复现**；
> 但顺着它摸到两件新事，其中一件与头号任务（巨熊）有关。

---

## 一、它与出处的关系：**没有被推翻，复现一致**

出处是 `knowledge/ui/screenshot_audit/V2_FINAL_ACCEPTANCE_REPORT.md` 的 **§12.5**
（标题即"the mechanism works for 12, and **90 have no trial path**"）。
该节的"18 entries, **all cycles 0**"这句**已在 2026-10-11 就地更正过**（原文保留 + 更正块）——
所以 D-H 引的那句话**本身带更正**，不是一条没人碰过的旧结论。

**本轮用同一条只读脚本（`_scripts/measure_candidate_trials_20261010.py`）重跑**，逐字一致：

```
CANDIDATE skills                  : 102
eligible for a trial              : 12
semantic_contract_incomplete      : 78
no_bound_verifier                 : 10
risk_not_allowed:MEDIUM_COMBAT    : 2
```

⇒ **90 = 78 + 10 + 2**，就是记了两周的那个"90"。**数没动。**
⇒ 因此 D-H 的**处置也不变**：要让那 78 个能试，得**逐条撰写 `semantic_contract`**，
而报告已判"按相似度映射 = 猜测"（项目禁止）⇒ **仍是决策，不是执行**。

## 二、顺路问的**巨熊**问题（两件，性质不同）

那 78 个里**含 `OPEN_BEAR_RALLY_LIST`** —— 它是巨熊链的核心
（`goal_library.py:1640` 把它列为 `PARTICIPATE_BEAR` 的技能之一；`:1691` 是 `DISCOVER_BEAR_RALLY_LIST`
的**唯一**技能；`session_adapters.BEAR_SKILLS` 也有它）。于是查了一句：**候选闸门会不会因此挡死巨熊链？**

**答案：不会。** 三个核心巨熊技能**都在 `LiveRuntime.VERIFIED_ATOMIC`（141）里**：

| 技能 | state | in VERIFIED_ATOMIC |
|---|---|---|
| `OPEN_BEAR_RALLY_LIST` | CANDIDATE | **True** |
| `START_RALLY` | CANDIDATE | **True** |
| `JOIN_RALLY` | CANDIDATE | **True** |

⇒ 它们**状态是 CANDIDATE、却已进可派发集** ⇒ **候选池挡不住它们**，走的是生产派发路径。
这与 `THE_BEAR_CHAIN_IS_BUILT_AND_HAS_NEVER_RUN_20261014.md` 的"链路齐"**一致**（多一条佐证）。

**但另一件**：`BEAR_AUTO_JOIN`（`skills.py:494`）**不在 `VERIFIED_ATOMIC`**，**也不在 `BEAR_SKILLS`**：

| 技能 | state | in VERIFIED_ATOMIC |
|---|---|---|
| `BEAR_AUTO_JOIN` | CANDIDATE | **False** |

而它**不是空气**：`executor_router.py:679-695` 有它的**生产状态守卫**（"Before any production tap of
`BTN_BEAR_AUTO_JOIN` the switch [must be] OFF"），`settle_policy.py:58/64` 两处点了它，
巨熊 playbook 也把 "**AUTO_JOIN state**" 列进前置复核。
⇒ **⚠ 这条我只报事实、不判定**：`BEAR_AUTO_JOIN` 目前**两条路都派不发**
（既不在 `VERIFIED_ATOMIC`，也不在 `BEAR_SKILLS`），而链的前置复核里却要"看 AUTO_JOIN 状态"。
**是否构成缺口，取决于链是否必须切这个开关**（手工加入可绕开）——**本轮未定论**。

## 三、池里**冻结的变成两个**（§12.5 只点了 RESEARCH）

`learning/candidate_attempt_pool.json`（mtime **2026-10-12 20:21**）：

```
threshold: 5
RESEARCH         : 566
OPEN_QUICK_PANEL : 12
其余 16 条        : 0
```

- `RESEARCH: 566` —— §12.5 的更正块已记；
- **`OPEN_QUICK_PANEL: 12` —— 新的**（§12.5 当时只有 RESEARCH 非零）；
- 两者**都在"12 个 eligible"名单里**（本轮实测 `in_pool=True`）⇒ **合格、却仍被跳过**。
- 其余 16 条为 0 是**被试过的痕迹**（`attempted()` 选中即清零），不是"没试过"。

⇒ §12.5 自己点名的那个机制缺口——**"a blocked candidate is invisible"**——
**今天仍然活着**，且**不止一个**。

## 四、能说 / 不能说

- **能说**：① D-H 的 90 = 78+10+2 **逐字复现**（2026-10-14）；② 三个核心巨熊技能**在 `VERIFIED_ATOMIC`**
  ⇒ 候选闸门**不挡巨熊链**；③ `BEAR_AUTO_JOIN` **两条路都派不发**（name-level 事实）；
  ④ 池里**两个**合格候选被冻结（566 / 12）。
- **不能说**：`BEAR_AUTO_JOIN` 不派发**是不是缺陷**（取决于链是否必须切它，**未定论**）；
  那 566/12 是"真被饿"还是"加成被压过"（§12.5 已标**不下定论**，本轮也没定）。

## 五、未做

**没改任何代码**（没把 `BEAR_AUTO_JOIN` 加进 `VERIFIED_ATOMIC`，也没动候选闸门）；
没给 78 个候选写 `semantic_contract`（**项目禁止按相似度推断**）；没动池账本、没动设备。
