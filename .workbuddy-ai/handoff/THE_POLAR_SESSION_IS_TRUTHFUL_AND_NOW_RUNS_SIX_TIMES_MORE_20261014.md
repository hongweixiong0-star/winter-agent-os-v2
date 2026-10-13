# 头号失败 `GIANT_BEAST_SEARCH_NOT_PROVEN`：verifier 说的是真话 —— 这条路跑得多了，而大多找不到目标（2026-10-14）

> **206 次尝试 = 206 个会话各一次，每一次的 `before.resource_selected_tab` 都是 `GIANT_BEAST`。**
> 164 次失败全部收在 `Page.MAP` 且 `resource_search_open=True`（面板开着、没有目标卡）。
> ⇒ 不是识别缺陷、不是路由缺陷，是**客户端没找到冰原巨兽**。
> 它之所以成为"头号失败"，是因为 `AVOID_STAMINA_WASTE` 打开这条会话的次数在 10-10 之后涨了 6–8 倍，
> 而成功率从 68% 掉到 7%。

---

## 一、这条路怎么被驱动的（读代码，不猜）

```
AVOID_STAMINA_WASTE 的 evidence 声明 stamina_sink ∈ {INTEL, GIANT_BEAST}   runtime.py:1284
  → runtime 把 sink 放进会话 data                                        runtime.py:1739
  → _stamina_polar = bool(data.get('stamina_sink'))                     session_adapters.py:704
  → POLAR_TERROR 会话规格 (stamina_sink=True, step_budget=14)             session_adapters.py:115/:117
  → 会话选 SELECT_GIANT_BEAST_TAB
  → _polar_step 发一次 SUBMIT_GIANT_BEAST_SEARCH（_polar_search_sent 守卫）session_adapters.py:882-885
  → 之后只 OBSERVE_ONLY
```

⇒ **每个会话恰好一次**。实测完全一致：206 次尝试落在 **206 个 run** 上，**1.00 次/run**，无一例外。

## 二、实测（`learning/episodes.jsonl`，10436 条）

| 日期 | `SELECT_GIANT_BEAST_TAB` | `SUBMIT_GIANT_BEAST_SEARCH` | 成功 |
|---|---:|---:|---:|
| 10-05 | 4 | 4 | 0.0% |
| 10-06 | 3 | 3 | 33.3% |
| 10-07 | 6 | 6 | 66.7% |
| 10-08 | 17 | 19 | **68.4%** |
| 10-10 | **108** | **119** | **16.8%** |
| 10-11 | 54 | 55 | **7.3%** |

而**同一天里 `AVOID_STAMINA_WASTE` 自己的 episode 数并没有涨**（10-08: 1195 → 10-10: 948 → 10-11: 402）
⇒ 变的是**目标内部选中这条会话的比例**（1.4% → ~12%），不是这个目标的调度量。

⚠️ 口径：这也说明**先按 episode 归一化是不够的** —— 10-10 的绝对量上涨里，有一部分正是"会话占比"变了。

## 三、据此能说的、和不能说的

- **能说**：verifier 是对的；失败是**结果半**（找不到目标），不是路由半（tab 一直是对的）。
  `WB-1002-11` 在 2026-10-02 两帧上得到的结论（"地图平移到空白处，verifier 说的是真话"）
  在**全量数据上成立**，而且这次是全量。
- **不能说**：是哪一次提交改了会话开启比例。窗口是 **10-08 23:19 → 10-10 01:58**（32 小时停机期间），
  候选 `1733cbe8 feat(activity): a SCHEDULED_* ticket asks the page its read can actually run on`、
  `b4704288 feat(bear): a window that has not opened names when to come back`、
  `6dfa1da5 fix(board+gate): …`，**未裁定**。
- **§10 分类未定**：若"当前没有冰原巨兽可找"，它属 `EXPECTED_NO_ACTION`（正常，换 Goal），
  而不是 `CAPABILITY_GAP`。判定它需要先知道**冰原巨兽现在是否存在** —— **这一步要真机**。

## 四、本轮改的代码（提交 `d3b41ce6`）

`SUBMIT_GIANT_BEAST_SEARCH` 的验证曾是一行 lambda：`ok` 用
`before.resource_selected_tab=='GIANT_BEAST' and (title_text or has_rally)`，而**原因串**只看
`after.beast_search_result` 的真假 ⇒ 两个根因共用一个名字（§3 明禁），且 164/164 条 `verifier_evidence` 为空。

现提成命名 verifier `verifier.verify_giant_beast_search`：原因串与 `ok` 用**同一组事实**，
`GIANT_BEAST_TAB_NOT_SELECTED`（新，路由半）/ `GIANT_BEAST_SEARCH_NOT_PROVEN`（保留原义，结果半），
三条路径都带 evidence，**`ok` 行为不变**。

**并且写明它有多大**（免得被读大）：**证据半**在 164/164 上真的发生了；**误标半是潜在的**
（全部 206 次尝试 tab 都对 ⇒ 历史上 0 次）。所以这次改动**不给当前数据新增任何原因**，
它的价值是：让下一次 tab 真的选错时能被记成路由失败，以及让这条搜索的结局从此可读。

## 五、未做

没有改会话的行为、没有动 pin、没有重开任何既有簇、没有改 `AVOID_STAMINA_WASTE` 的调度。
