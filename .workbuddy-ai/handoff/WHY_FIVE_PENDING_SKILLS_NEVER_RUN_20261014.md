# 五条待投递记录点名的技能为什么一次都没跑过（2026-10-14）

> 队列审计新加的 `SKILL_NEVER_DISPATCHED` 说："这条跳没人派"。本文把它拆开 ——
> 五种原因**没有一种**是"缺一帧真机"，所以**处方各不相同**。

---

## 一、先看事实

全流 10436 条 episode 里，下列技能 **episode 数 = 0**：

| 技能 | 在 `skills.py` 注册？ | 在导航矩阵？ | 有 runtime verifier 绑定？ |
|---|---|---|---|
| `SELECT_QUICK_PANEL_CITY_TAB` | **不是技能**（见下） | **不在**（153 行里没有） | **无** |
| `NAVIGATE_RESEARCH_LAB` | 是 | 是（sched=True） | 是（`verify_research_lab_focused`） |
| `OPEN_POWER_OVERVIEW` | 是 | 是（sched=True） | 是（`verify_power_overview_open`） |
| `READ_EVENT_CALENDAR` | 是 | 是（sched=True, nav=False） | 是（`verify_event_calendar_read`） |
| `SELECT_INTEL_FIREBEAST_MISSION` | 是 | 是（sched=True） | 是（`verify_intel_mission_selected`） |

**注意**：矩阵里 12 个 `schedulable=False` 的全是通用助手（`READ_TIMER` / `SEND_MARCH` /
`CLAIM_REWARD` …），**这 5 个一个都不在里面** ⇒ 用"不可调度"解释不了。

## 二、五种原因（每种都落到 file:line）

### 1. `SELECT_QUICK_PANEL_CITY_TAB` —— **它根本不是技能**
`winter_agent_v2/skills.py:109` 早就写着：

```
#:   ``SELECT_QUICK_PANEL_CITY_TAB``     in no source file at all (one row, 2026-10-05, unresolved)
```

并且它被列在 `:119-123` 那个"**这些名字不是技能**"的集合里
（和 `PRINTED_TAP` / `OBSERVE_ONLY` / `SAFE_STOP` 并列）。
⇒ 那条 escalation 记录引用的是一个**幽灵名字**，**永远不可能被满足**。

### 2. `NAVIGATE_RESEARCH_LAB` —— 门从未成立
`brain.py:1108`：

```python
if world.page is Page.POPUP and world.popup == "POWER_DETAILS" and self.current_goal == "RESEARCH":
    return Decision("NAVIGATE_RESEARCH_LAB", "research_goal_technology_power_route", ...)
```

需要**同时**满足：停在 `POWER_DETAILS` 弹窗 **且** 当前目标是 `RESEARCH`。
10436 条 episode 里没有一次。

### 3. `OPEN_POWER_OVERVIEW` —— 它是**兜底**，而兜底没轮到
`brain.py:1973` / `:2451` 两处，理由串是
`panel_did_not_serve_this_goal_so_the_power_route_is_the_fallback`。
⇒ 只有当**快捷面板没有服务这个目标**时才会走它；这条兜底从未被触发。

### 4. `SELECT_INTEL_FIREBEAST_MISSION` —— 前提条件没出现过
`brain.py:2664`：`if world.intel.get("mission_type") == "FIREBEAST":`
⇒ 情报板从未报过 `FIREBEAST` 这个任务类型（旁边 `== "BEAST"` 的那条
`SELECT_INTEL_BEAST_MISSION` 是跑的）。

### 5. `READ_EVENT_CALENDAR` —— 项目**故意**不提供它
`goal_library.py:322`：

```python
#: offering it would turn "no action" into "an action certain to fail".
_ACTIVITY_OBSERVATION_SKILLS: tuple[str, ...] = ("READ_EVENT_CALENDAR",)
```

⇒ 上面那行注释就是理由：**提供它会把"没事可做"变成"一次注定失败的动作"**。
也就是说，**这条记录在要求一个被故意关掉的能力** —— 照它字面去"修"，会把项目
一个刻意的决定推翻。**这条记录按原文不可执行**，要动它得先改那个决定。

## 三、结论与处方

| 原因 | 记录 | 正确处方 |
|---|---|---|
| 幽灵名字 | `SELECT_QUICK_PANEL_CITY_TAB` | **退役**（它引用一个不存在的技能） |
| 门从未成立（×2） | `NAVIGATE_RESEARCH_LAB`、`SELECT_INTEL_FIREBEAST_MISSION` | 先问**那个前提为什么从不成立**（要真机/要读帧），**不是**"给这条跳补一帧" |
| 兜底没轮到 | `OPEN_POWER_OVERVIEW` | 先量**兜底条件是否可达** |
| 被刻意关闭 | `READ_EVENT_CALENDAR` | **先由操作者重新裁定那个决定**，否则不动 |

⇒ 五条**没有一条**是 `RECOGNITION_CLAIM_NEEDS_A_FRAME` 那个处方能解的。

## 四、顺带发现的一个覆盖缺口（未修）

`tools/check_wiring.py` 报 `problems: 3`，**其中没有这一族**。它检查的是
"注册 ↔ 矩阵"（`every registered skill appears in the matrix exactly once`，正在通过），
**不检查"大脑能决定、但从未决定过"**。于是 4 个 *有绑定、有矩阵行、大脑里真有 return 分支*
的技能可以**一次都不跑**而检查全绿。

**本轮没有加这条检查**：要把它写好，得先定义"从未跑过"的窗口与阈值（多长算"从未"、
样本多少才够），那是一个设计决定，不是一个顺手能加的断言。**登记，不动手。**

## 五、未做

没退役任何记录（架构上仍无合法退役通道）、没改队列、没改 `check_wiring`、
没有为这 5 条中的任何一条写代码。
