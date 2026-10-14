# 台账引用的那个"阶段目标"其实已被规则**挂起**：`TARGET_LEARNING_SHARE >= 0.50` 是 `[B]`（2026-10-14）

> 上一轮我复核了台账 `the_budget_that_has_no_run_boundary`，它把
> **`TARGET_LEARNING_SHARE >= 0.50`** 称作 "**CAPABILITY_EXPANSION 阶段真实的天花板**"。
> 本轮顺着这条引用再问一句"**这个目标本身是什么状态**"——结果它不是"生效的目标"，
> 而是**一条被规则显式挂起、且被点名"补出度量前不得引用"的条款**。
> ⇒ 该台账那句话**被高估了两次**：上一轮证明了读它的键到不了；本轮证明**这个目标本身不生效**。

---

## 一、台账是怎么引用它的

`learning/escalation_queue.jsonl` 记录 `the_budget_that_has_no_run_boundary`（2026-10-10）：
把"每进程一次"说成 "CAPABILITY_EXPANSION 阶段（`TARGET_LEARNING_SHARE >= 0.50`）真实的
天花板"，状态 `NOT_FIXED_NEEDS_OPERATOR_DECISION`。

⇒ 它把 `TARGET_LEARNING_SHARE >= 0.50` 当成了一个**正在生效的阶段目标**来引用。

## 二、规则里这个目标的真实状态

| 出处 | 原文 | 状态 |
|---|---|---|
| `.workbuddy-ai/rules/PRINCIPLES.md:48-50` | **§10 Learning Budget — 至少 50%** `[B]`：学习投入不低于一半。**判定缺失**：`learning_share` 等符号全仓 0 命中，**补出度量前不得引用**（见 `README.md §7`）。 | **`[B]` 挂起**（不是废止） |
| `.workbuddy-ai/rules/PRINCIPLES.md:46-47` | **§9 当前阶段：CAPABILITY_EXPANSION** `[废止]` …其优先原则**已由 §58 完整表达**。 | **废止 → §58** |
| `.workbuddy-ai/rules/PRINCIPLES.md:221` | **§58 不要沉迷 95%→97%** `[A]`：优先 0→1；除非该 95% 缺陷属 P0/P1 且大量影响生产。 | **现行优先原则** |
| `.workbuddy-ai/rules/README.md:150-158` | 一张表列"名字在实现目录命中 0 却被旧规则当作决策依据"，其中就有 **`Learning Budget ≥50% 的份额`**；并给出**替代判据**：`NEVER_TRIED_GOALS`、`PRODUCTION_TRIED_GOALS` …。 | **点名 + 替代** |

⇒ 所以 `TARGET_LEARNING_SHARE >= 0.50` **不是**一个"当前阶段目标"。
它是一条 `[B]` 条款，规则原话是 **"补出度量前不得引用"**；
而"当前阶段"这个提法（§9）**已废止**，优先原则换成了 **§58（优先 0→1）**。

## 三、更细一层：度量**规格在、消费者无**

`WORK_QUEUE.json` 里其实**写着一份完整的度量规格**：

```json
"target_learning_share": 0.5,
"learning_measurement": {
  "selection_window": 20,
  "effective_work_window_minutes": 30,
  "unknown_when_unmeasured": true,
  "exclude_no_progress_repeated_observation": true,
  "hard_deadline_and_real_high_loss_override": true
}
```

commander 文档也点名了它**应该**产出的输出：
`PRODUCTIVE_SELECTIONS / DISCOVERY_SELECTIONS / LEARNING_SELECTIONS / RECOVERY_SELECTIONS /
LEARNING_SHARE / HIGH_VALUE_UNKNOWN_SHARE`，以及面板字段 `CURRENT_LEARNING_SHARE`。

**但全仓实测**（`--include=*.py --include=*.json`，排除两份规则文档本身）：

| 符号 | 代码/配置命中 |
|---|---:|
| `learning_measurement` | **0** |
| `LEARNING_SELECTIONS` | **0** |
| `PRODUCTIVE_SELECTIONS` | **0** |
| `DISCOVERY_SELECTIONS` | **0** |
| `RECOVERY_SELECTIONS` | **0** |
| `HIGH_VALUE_UNKNOWN_SHARE` | **0** |
| `CURRENT_LEARNING_SHARE` | **0** |

⇒ 规格**写在配置里**，但**没有任何代码读它/产出它** ⇒ `CURRENT_LEARNING_SHARE` **算不出来**。

## 四、结论（这才是本轮该留下的）

1. **这不是"待操作者决策"** —— 规则**已经**给了处置（§10 `[B]` + 替代判据）。
   把它当开放式问题去问操作者，是**重复提问**。
2. 因此，**任何"学习份额没到 50% / 学习占比下降，所以该选 X"的理由都不成立**
   （`README §7` 的原话：在补出度量之前，这类理由不得成立）。
   要判"学习是否占了该占的"，请用**替代判据**：`NEVER_TRIED_GOALS` / `PRODUCTION_TRIED_GOALS`。
3. 与上一轮的 `THE_LEARNING_BUDGET_CLAUSE_IS_UNREACHABLE_IN_PRODUCTION_20261014.md` 合起来，
   `the_budget_that_has_no_run_boundary` **两处都被高估**：
   - 上一轮：**读那条预算的键在生产里到不了**（载入器丢 `__run__`）；
   - 本轮：**它引的那个目标本身是 `[B]` 挂起条款**。
   ⇒ 那条台账记录不构成"学习被卡住"的证据。

## 五、未做

没改 `PRINCIPLES.md` / `README.md` / `WORK_QUEUE.json` / commander 文档；
没实现 `learning_measurement`；没退役那条台账记录（退役需要操作者的词，见
`OPERATOR_DECISION_PACKAGE_20261014.md` 的 **D-B**）；没动设备。
