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

## 三、这条路怎么被选中的（代码已闭合）与**为什么不能被归因**（本轮的第二件事）

`runtime._stamina_route`（`runtime.py:1722-1744`）：

```python
intel = data.get('intel_state') or {}                      # ← 读的是 goal.evidence，不是 state_before
runnable_intel = (not intel_blocked and intel.get('status')=='AVAILABLE'
                  and intel.get('untried_pins', intel.get('pins', 1)) != 0)
sink = choose_stamina_goal(current, 'AVAILABLE' if runnable_intel else 'NOT_AVAILABLE', ...)
```

而 `operations_policy.choose_stamina_goal`（`:58-79`）的顺序是：
`stamina<30 → NONE` ｜ `intel AVAILABLE → **INTEL**` ｜ 无空闲行军 → WAIT ｜
**`giant_beast_ready → GIANT_BEAST`** ｜ `beast_ready → BEAST_HUNT` ｜ 否则 STAMINA_BLOCKED。
⇒ **GIANT_BEAST 是"情报跑不了之后的兜底"**，不是首选。

**时间上确实吻合**（`state_before.intel.status` 的出现次数）：

| 日期 | `AVAILABLE` | `BLOCKED` | 极地会话 |
|---|---:|---:|---:|
| 10-08 | 553 | 11 | 19 |
| 10-10 | 1007 | **344** | **119** |
| 10-11 | 315 | **111** | 55 |

**但这一条我无法用数据坐实，原因是记账缺口，不是一个猜测**：

1. 决策真正读的字段是 **`best_goal.evidence['intel_state']`**，而 episode 只存 `state_before/state_after`——
   我上面那张表用的是 `state_before.intel.status`，**两者不是同一个字段**。⇒ 那张表只能算**旁证**。
2. `_stamina_route` 把结论写进 `data.update(stamina_sink=…, stamina_sink_reason=…)`（`runtime.py:1739`），
   而 **`stamina_sink_reason` 在整个 episode 流里出现 0 次** —— 它只活在会话 data 里，从不落盘。
3. 于是"这一次为什么选 GIANT_BEAST 而不是 INTEL"这个**每个读账本的人都会问的第一个问题**，
   在账本里**没有答案**。

⇒ 这是与 `verifier_evidence` 为空、`recognition_error` 缺失**同一类**的记账缺口，只是深了一层：
**上一轮修的是"verifier 不说原因"，这一层是"路由器不说原因"**。

## 四、据此能说的、和不能说的

- **能说**：verifier 是对的；失败是**结果半**（找不到目标），不是路由半（tab 一直是对的）。
  `WB-1002-11` 在 2026-10-02 两帧上得到的结论（"地图平移到空白处，verifier 说的是真话"）
  在**全量数据上成立**，而且这次是全量。
- **不能说（且原因已定位到记账缺口，不是我偷懒）**：**会话占比为什么涨，账本回答不了** ——
  决策读的 `evidence['intel_state']` 与 `stamina_sink_reason` **都不落盘**（见第三节）。
  因此"是哪一次提交改了它"这个问题**在补上这笔账之前无法用数据裁定**；窗口是
  10-08 23:19 → 10-10 01:58（32 小时停机期间），**未裁**。
  另：`operations_policy.py` 在 10-07~10-11 **没有任何提交**，`BLOCKED` 的识别也没有
  （`git log -S MASTER_BOUNTY / BATTLE_FAILED` 皆空）⇒ 不是这两处改的。
- **§10 分类未定**：若"当前没有冰原巨兽可找"，它属 `EXPECTED_NO_ACTION`（正常，换 Goal），
  而不是 `CAPABILITY_GAP`。判定它需要先知道**冰原巨兽现在是否存在** —— **这一步要真机**。

## 五、本轮改的代码（提交 `d3b41ce6`）

`SUBMIT_GIANT_BEAST_SEARCH` 的验证曾是一行 lambda：`ok` 用
`before.resource_selected_tab=='GIANT_BEAST' and (title_text or has_rally)`，而**原因串**只看
`after.beast_search_result` 的真假 ⇒ 两个根因共用一个名字（§3 明禁），且 164/164 条 `verifier_evidence` 为空。

现提成命名 verifier `verifier.verify_giant_beast_search`：原因串与 `ok` 用**同一组事实**，
`GIANT_BEAST_TAB_NOT_SELECTED`（新，路由半）/ `GIANT_BEAST_SEARCH_NOT_PROVEN`（保留原义，结果半），
三条路径都带 evidence，**`ok` 行为不变**。

**并且写明它有多大**（免得被读大）：**证据半**在 164/164 上真的发生了；**误标半是潜在的**
（全部 206 次尝试 tab 都对 ⇒ 历史上 0 次）。所以这次改动**不给当前数据新增任何原因**，
它的价值是：让下一次 tab 真的选错时能被记成路由失败，以及让这条搜索的结局从此可读。

## 六、这件事**本轮已经做了**（更正本文件上一版的"未做"）

上一版这里写的是"没做，因为要动 schema、需单独审阅"。**本轮把它做了**（提交 `37d26b79`）。
理由：`WB-1002-11` 就是对**同一个 dataclass** 单独加了一个字段（`recognition_error`），
所以这在**项目自己的先例之内**；我原先的谨慎过了头。

做法，以及那个差点写错的陷阱：

- `learning.Episode` 加 `stamina_sink` / `stamina_sink_reason`（默认 `""`，纯增字段；
  存储走 `asdict`，因此不需要改 writer）。
- `runtime._stamina_route_reason(evidence)` 从**被选中的那个 goal** 的 evidence 读回。
  **故意不写在 `_stamina_route` 方法里**：它有 **3 个调用点**，其中两个
  （`runtime.py:1263`、`:2753`）在**遍历整个 goal 板** —— 写在方法内会盖上"循环里最后一个
  goal"的值。那会往账本里写**错值**，比不写更糟。已在 `_sync_brain_goal` 按 goal 清一次、
  在每步边界（与另外两个 recorder 并列）清一次。
- 测试 `tests/test_the_stamina_route_records_its_own_choice.py`（**6 项**，含这个循环陷阱）。

**证据等级：`UNIT_TEST_PASS`** —— 最低一级。字段的**真实取值只能在下次真机运行里看到**，
而设备锁在 MANUAL。**这次提交让问题可被回答，不等于回答了它。**

A/B：`tests/test_learning_loop_wiring.py` 的两处红是**既有的**，不是这次改的 ——
把我的 `learning.py`+`runtime.py` 改动 stash 掉重跑，复现**完全相同**的
`ProductionRuntimeWriteError`（`learning/ui_venus_online.jsonl` 未被 `_REDIRECTS` 覆盖），
且恢复后 diff 统计一致。

## 七、未做

没有改会话的行为、没有动 pin、没有重开任何既有簇、没有改 `AVOID_STAMINA_WASTE` 的调度。
