# 控制台只显示它真的量过的数字（2026-10-04）

操作者一次报了三个问题，它们是**同一个缺陷的三张脸**：每个位置都在显示一个看起来像
"量过的数"，其实不是。

| # | 报的现象 | 真正的原因 |
|---|---|---|
| 1 | 活动低保停留在 2026-09-09（595 小时） | **从来没有任何写入端**；该文件是一次人工真机记录 |
| 2 | 今日目标置信度全部 99% | 每行都渲染**整帧**的识别置信度；目标自己**没有** confidence 字段 |
| 3 | 目标卡"待执行"，阻塞原因大量为空 | 面板读 `blocked_reason`，而**这个键不是 `GoalState` 的字段**，没人写过它 |

三个都不是"算错了"，而是**数据链路缺失**：真实值存在，或根本不存在，而界面两种情况都
显示成一个看似量过的数。

---

## 一、问题 1：活动状态（`learning/event_goal_state.json`）

### 1.1 更新链路：不是断了，是**从来没有**

```
$ git log --oneline --all -- learning/event_goal_state.json
3fee534d fix(state): stop Git controlling runtime-mutable production state
f9ef073c chore: initial checkpoint of Winter Agent OS V2
```

- 全树搜索：`winter_agent_v2/` 与 `tools/` 里**没有任何写入端**。唯一读者是
  `winter_agent_v2/state_truth.py`（`EVENT_STATE`）。
- 文件内容自证是人工记录：`"source": "LIVE_CLIENT"`，
  `"resource_spent": "体力：本次显示10；实际扣除待回到 Intel 复核"` —— 中文手记。
- 它的 `plan` 字段是一句人写的策略（"优先完成 Intel 野怪…"），不是程序输出。

**结论**：`f9ef073c`（初始检查点）里它就已经是这个样子，是 2026-09-09 一次真机观察的
留档。**没有写入端可以"修链"，只能给它一个让它自己失效的 TTL。**

### 1.2 加 TTL：两条独立的过期规则，先到者生效

`state_truth.legacy_event_row` 原本已有一条（记录**自己的倒计时**：说剩 28 795 秒的记录，
过了更久就描述一个已结束的活动）。补上第二条，也是记录没带倒计时时唯一可用的一条：

```python
EVENT_CURRENT_SECONDS = 6 * 3600.0   # 同时是 TTL
past_ttl = age is not None and age > EVENT_CURRENT_SECONDS
expired  = bool(window_closed or past_ttl or age is None)
```

**裁决随行携带**：行里新增 `expired` 与 `ttl_seconds`，任何读者都**不必重新推导**规则——
"两个读者各自算一遍"正是它们开始互相矛盾的方式。

### 1.3 顺带修掉的一处同族缺陷（运行状态表）

`TruthAudit.event_state()` 有**第二份**新鲜度判断，读的是
`updated_at` / `recorded_at`，而记录写的是 `verified_at`：

```python
stamp = str(payload.get("updated_at") or payload.get("recorded_at") or "")
status, age = self._stamp(EVENT_STATE, stamp)
```

→ `stamp` 为空 → `_age("")` 返回 `None` → `_grade(age=None)` 返回 **`PERSISTED`**，
读起来是"已保存，正常"。实测（2026-10-04）运行状态表显示：

```
修前  event_state  status=PERSISTED   age=None
修后  event_state  status=STALE       age=2155654.3 (599 h)
                    observed_at=2026-09-09T16:00:00+08:00
```

现在复用 `legacy_event_row` **同一条规则**，不再有第二份。

### 1.4 界面：从"前缀"改成"待重新观测"

2026-09-18 的做法是给旧数字加前缀 `历史参考（不参与当前 Planner）：`。
操作者 2026-10-04 明确否掉了它：**"而不是继续展示 25 天前的模板"** —— 前缀不是藏身处，
那些数字仍然是页面上**仅有**的数字，而且已经 25 天。现在过期的行：

```
name                 '当前活动尚未实时确认'
current/phase/tier/target/missing/plan/estimated_cost/
estimated_completion/resource/verified/rewards   '待重新观测'
source               'learning/event_goal_state.json（记录时来源 LIVE_CLIENT）'
last_verified        '2026-09-09T16:00:00+08:00（599 小时前，已过期）'
status               '⚠ 待重新观测 —— 记录的活动窗口早已结束：…已过去 599 小时'
```

留**来源**是刻意的：来源不是数值断言，"这是哪一次读数"正是过期行仍能诚实回答的唯一问题。

---

## 二、问题 2：置信度

`tools/control_panel.py` 的目标行：

```python
f"{float(snapshot.get('confidence',0)):.0%}"     # ← 每行都是它
```

`snapshot["confidence"]` 是 `world.confidence`，即**整帧页面识别**的置信度，一个数。而
`GoalState` 的字段里**没有** confidence（14 个 dataclass 字段，见 §四），
`GoalStateStore._serialize` 也不写 —— 实测 `goal_state.json` 里 33 个目标**全是
`confidence: null`**。所以那是**一个不属于本行问题的数**被复制了 33 遍。

修法（按操作者"接不上就写未计算"）：

```python
@staticmethod
def _goal_confidence_cell(goal: dict) -> str:
    value = goal.get("confidence")
    if value is None: return "未计算"
    try:    return f"{float(value):.0%}"
    except (TypeError, ValueError): return "未计算"
```

整帧置信度**没有消失**，它仍在表头说明行里，且被明确标注：

> 识别页面：TRAINING · 整帧识别置信度：99%（这是页面识别，不是每个目标的置信度）· 时间：…

---

## 三、问题 3：待执行目标的真实阻塞原因

### 3.1 为什么"很多是空的"

`blocked_reason` **不是 `GoalState` 的字段**（14 个字段：goal_id/status/completion/
remaining_seconds/reward_value/daily_loss/event_synergy/development_value/resource_cost/risk/
available_skills/retry_after/evidence/distance）。`GoalStateStore._serialize` 用 `asdict`
写盘，也不会写出它。面板读一个从未被写过的键 ⇒ 33 行全是 `—`。
（`goal_state.json` 的 JSON 有 15 个键，第 15 个 `priority` 是 property，由 `_serialize`
在 `asdict` 之后另加。）

### 3.2 但原因**本来就存在**

用生产自己的构造调用实跑（`CapabilityGate.load(ROOT)` + `gate.blocked(goals)`）：

```
CLEAR_INTEL            -> DEFERRED on READ_INTEL_LIST: 3 consecutive production episodes
                          passed their verifier and advanced no part of this goal
MAIL_ROUTINE           -> BLOCKED on READ_MAIL_TABS: repair budget exhausted (2/2) after CODE_CHANGED
DAILY_ACTIVITY_TARGET  -> BLOCKED on READ_DAILY_PROGRESS: repair budget exhausted (2/2) after CODE_CHANGED
SCROLL_QUICK_PANEL_TASKS -> DEFERRED: 3 episodes, no progress
```

⇒ **原因存在，缺的只是链路。** 所以这是数据链路修复，不是新机制。

### 3.3 两类"没在跑"，两个来源

| 类别 | 来源 | 落点 |
|---|---|---|
| 过期历史 / 无进展 **延期** | `CapabilityGate` 的决定 | `goal_state.json["blockers"]`（运行时写入） |
| **队列忙**（兵营在训练、科研排 15 天） | 帧自己的读数，库已判 `BLOCKED` | 目标自己的 `evidence.reason` / `condition` / `retry_after` |

实跑 gate 得到的四类真实原因：

```
KEEP_BUILDING_PRODUCTIVE (READY)  START_BUILD：repair budget exhausted (2/2) after CODE_CHANGED · [BLOCKED] · 至 2026-09-30T…
DAILY_ACTIVITY_TARGET    (DISCOVERED) READ_DAILY_PROGRESS：repair budget exhausted (2/2) … · [BLOCKED] · 至 2026-09-23T…
SHIELD_CAMP_TRAINING     (BLOCKED) 该兵营正在训练中（队列未空） · 剩余 11:17:36
KEEP_RESEARCH_PRODUCTIVE (BLOCKED) 队列忙，已有工作在进行 · 剩余 15天21:03:41
```

**注意第一条**：`KEEP_BUILDING_PRODUCTIVE` 的状态是 `READY`（"待执行"），而 gate 在延期它
—— 这正是操作者看到的"卡在待执行却不知道原因"，现在那一格直接写出原因。

### 3.4 写在哪里（为什么不是面板自己算）

在 `runtime.py` 已经建好 gate 的那一刻写进 `goal_state.json`，**紧挨它解释的那些目标**：

```python
# runtime.py ~2422
self.goal_store.write(world, goals, role_id=role_id, blockers=self._goal_blockers(goals))
```

`_gate()` 每个周期本来就会被构建并缓存（`_rank` 的第 1112 行无条件调用），所以这里**不增加
任何解析**。反过来，让面板自己算会在每次刷新时读 episode 尾巴，并给面板一个**可以和审计
不一致的第二意见**。序列化直接用 `Deferral.as_row()`（它自己的 docstring 就写着
"for the runtime snapshot and the escalation hook"），不手拼字段。

### 3.5 空格子不再是 `—`

`—` 读起来是"未知"。一个可执行但没被选中的目标**不是未知**：没有东西拦它，它没跑是因为
调度选了别的。两种陈述不同，后者才是诚实的：

```
READY / DISCOVERED 且无阻塞  ->  '就绪 · 未被阻塞（未选中＝调度顺序，不是被拦）'
```

并且**只对状态确实是 `BLOCKED` 的目标**才去读 `evidence.condition`：READY 目标上的
`condition`（如 `fresh_fishing_read`）是**已满足的前置条件**，把它渲染成阻塞就是凭空造墙。

---

## 四、验收

在**生产 pin 树内**（不是开发树）跑：

```bash
pytest tests/test_the_console_only_shows_numbers_it_measured.py \
       tests/test_state_truth.py tests/test_control_panel.py \
       tests/test_event_goal.py tests/test_daily_task_goal_wiring.py \
       tests/test_every_goal_has_a_route.py tests/test_global_scheduler_dashboard.py \
       tests/test_global_scheduler_state.py tests/test_loop_main_path_wiring.py \
       tests/test_a_ledger_that_stopped_being_written_says_so.py \
       -q -p no:randomly
#   -> 281 passed, 50 subtests passed

python tools/check_wiring.py      # -> problems: 2（既有那两条，无新增）
```

**给新测试验牙**（回退 4 个生产文件、保留新测试）：

```bash
git checkout -- tools/control_panel.py winter_agent_v2/state_truth.py \
                winter_agent_v2/goal_library.py winter_agent_v2/runtime.py
pytest tests/test_the_console_only_shows_numbers_it_measured.py -q
#   -> 21 failed, 1 passed
```

唯一通过的是 `test_the_goal_model_is_unchanged` —— 它是一条**守卫**（"数据模型没有动"），
本来就应该在两侧都通过。其余 21 条在新代码下全绿、在旧代码下全红。

### 4.1 一条既有检查编码了旧要求，已更新为更强的断言

`tools/check_wiring.py` 原本要求面板源码里存在字面量 `历史参考（不参与当前 Planner）`。
操作者已经**明确退休**了那个做法，所以这条检查断言的正是被否掉的行为。改为断言：

```
row.get("expired") in _panel_source   and   待重新观测 in _panel_source
```

**这不是放宽**：旧断言只要求有一个前缀字符串；新断言要求面板读**行自己的裁决**，并且
**完全不渲染过期记录的数值**。检查里写明了这次改动的理由，因为"检查跟着实现走"正是
检查变得没有意义的方式。

---

## 五、没做 / 发现但未动

- **`event_goal_is_current`（`control_panel.py:1297`）是死代码**：全树没有生产调用点，
  只有 `tests/test_control_panel.py` 导入它。它读 `updated_at`（同样是字段名错配），
  是**第二份、且互相矛盾**的新鲜度规则。删它会动到那个测试的导入，超出本轮范围，
  仅记录。**下一批该处理**：要么让它复用 `legacy_event_row`，要么删掉。
- **延期期限已过却仍在拦**：`DAILY_ACTIVITY_TARGET` 的 gate 理由是
  `repair budget exhausted (2/2) … until 2026-09-23`，而 `until` 已过去 10 天仍 `allows=False`。
  `_probe_lapsed` 的锚点是"该目标最近一个 episode 的时间"（`last or fallback_anchor`），
  所以一个**持续产生 episode 的目标，其阻塞永远不会 lapse**。这会影响调度行为，
  必须自带 A/B，本轮**只显示、不改**。
- **`capability_gate.EPISODE_TAIL`**（400 行用字节表达，实测只有 127 行）：与上一批相同，
  仍待自带 A/B。
- **开发树里的既有杂物**（非本轮产生，未提交）：`winter_agent_v2/formation_policy.py`
  （未跟踪、无人 import，2026-09-28 遗留）、`winter_agent_v2/runtime_env.py`、
  `winter_agent_v2/workbuddy_bridge.py`。
