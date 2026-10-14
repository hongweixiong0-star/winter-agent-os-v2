# 学习预算：那条"每轮一次"的检查**在生产里到不了**；而台账据此得出的"学习天花板"是**虚的**（2026-10-14）

> 台账 `the_budget_that_has_no_run_boundary`（2026-10-10）把一个东西列为**阶段级天花板**：
> "『每进程一次』等于整个学习计划的上限是一次观察。**这是 CAPABILITY_EXPANSION 阶段
> （`TARGET_LEARNING_SHARE >= 0.50`）真实的天花板**"，状态 `NOT_FIXED_NEEDS_OPERATOR_DECISION`。
> **复核之后：那个结论不成立** —— 不是因为它被修好了，而是因为**读它的那个键在生产里根本到不了**。

---

## 一、链路上的两处（各自都读到了）

**写侧** `runtime.py:2379-2384`：
```python
state = self._bootstrap_state()            # ← 注意：写的是这个"过滤后的"字典
row = state.setdefault(key, {})
row["attempts_this_run"] = int(row.get("attempts_this_run") or 0) + 1
row["cooldown_until"] = (now + 300s).isoformat()
state.setdefault("__run__", {})["visits_this_run"] = 1
```
**磁盘上确实存着**：`learning/capability_bootstrap/runtime_discovery.json` 的键是
`['1061663148|SCHEDULED_BEAR_HUNT', '1061663148|SCHEDULED_STATE_VS_STATE', '__run__']`，
`__run__ = {'visits_this_run': 1}`。**写成功了。**

**读侧（生产唯一调用方）** `runtime.py:2273` → `cooldowns = self._bootstrap_state()`
→ `runtime.py:2347-2351` `project_runtime_discovery(..., cooldowns=cooldowns, ...)`

而 `_bootstrap_state()`（`runtime.py:2214-2219`）**只保留带 `cooldown_until` 的条目**：
```python
self._bootstrap_cooldowns = {
    key: {"cooldown_until": value.get("cooldown_until")}
    for key, value in payload.items()
    if isinstance(value, dict) and value.get("cooldown_until")
}
```
⇒ **`__run__` 没有 `cooldown_until` ⇒ 被丢掉。**

于是 `capability_bootstrap.py:192-198`：
```python
run = ledger.get("__run__", {}) or {}                      # → {} （总是）
... or _discovery_count(run.get("visits_this_run")) >= budget["max_bootstrap_visits_per_run"]
```
`_discovery_count(None)` = `max(0, int(None or 0))` = **0**，而预算是 **1** ⇒ `0 >= 1` **为假**
⇒ **这一项永远不会让 `exhausted` 成立。**

（另外两个调用方是 `tests/` 与 `tools/full_auto_coverage_audit.py`；**生产只有一个**，
且它传的就是过滤后的字典。）

## 二、所以台账那两句都要更正

| 台账说 | 实际 |
|---|---|
| "两个计数器都没有可用的运行边界…『每进程一次』等于学习计划的上限是一次观察" | **计数器不是边界** —— 它在**被检查之前就被丢掉了**。真正的界是 `self._learning_window_used`（**进程内一次性内存标志**，`runtime.py:2245-2247`），而 worker **每个循环都是新进程** ⇒ 大约是**每循环一次**，**不是天花板** |
| `status: NOT_FIXED_NEEDS_OPERATOR_DECISION` | 需要决策的是**另一件事**（见第四节），不是"要不要放开预算" |

**而每个目标自己的界**（`attempts_this_run` + `cooldown_until`）**是有效的** —— 因为它们**带 `cooldown_until`**，
会穿过那个过滤器。

## 三、顺带查实的一个真值漂移（小，但会导致误判）

`DEFAULT_BUDGET["max_bootstrap_visits_per_run"] = 1`（`capability_bootstrap.py:102`）**被声明了、
在生产里却从不生效** —— 读它的调用方总是丢掉那个键。**这是一个"声明存在、行为不存在"的预算。**

## 四、⚠️ **看起来该做的那个修法是错的**

自然的修法是"让载入器保留 `__run__`，这样预算就绑上了"。**不要那样做**：
`visits_this_run` 被**永久写成 1**、全仓库**没有任何复位点** ⇒ 一旦它真被读到，
`1 >= 1` 会**恒真** ⇒ **学习窗口会被永久关掉** ——
而 `runtime.py:2232-2233` 的 docstring 记的正是这个后果：

> "…the element table was never built … **The learning window was closed permanently and nothing
> said so.**"

⇒ **把它"修好"等于把那个已经修掉的停机重新装回去。** 本轮**不动**。

## 五、真正该决定的是什么（**未做**）

两选一，都是设计决定，且这条巷子有测试钉着（`tests/test_runtime_capability_discovery_lane.py`）：

1. **删掉那条死支**（`capability_bootstrap.py:198` 的 `visits_this_run` 项）——
   让 `DEFAULT_BUDGET` 不再声明一个不生效的预算（**只是诚实化，不改行为**）；
2. 或者**给 `visits_this_run` 一个真正的运行边界**（谁在什么时刻把它清零），让它名副其实 ——
   但那要先定义"一次 run"是什么（worker 每循环换进程，所以"进程"不是"run"）。

**本轮没有做**：它改的是 `runtime` 的载入过滤 / 预算语义，且第 1 条虽小仍需过测试与复核；
按"先量再改"，本轮先把它量清。

## 六、未做

没改 `runtime.py`、没改 `capability_bootstrap.py`、没改预算、没动磁盘上的
`runtime_discovery.json`、没动设备。
