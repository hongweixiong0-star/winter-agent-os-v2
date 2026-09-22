# `OPEN_HOME` 的第八个发出点：兜底跳转不关搜索面板 ⇒ 六分钟里连续 8 次失败（2026-09-23）

## 这是什么

上一轮（`c522bc9`）给**七个** `OPEN_HOME` 发出点补上了"先关资源搜索面板"的守卫。本目录记录的是：守卫落地
**40 分钟后，同一类失败又成串出现 8 次**——因为发出这个动作的地方有**八处**，第八处在运行时里，
不在 `brain.decide` 里，所以七处大脑守卫**一处都管不到它**。

复算命令（不需要真机）：

```
"E:/无尽冬日智能体/.venv/Scripts/python.exe" -u tools/probe_open_home_fallback.py --frames 1
```

## 生产里发生了什么（`learning/episodes.jsonl`）

`21:22:12Z` 一次 `SEARCH_RESOURCE` 成功打开搜索面板（`resource_search_open: False -> True`）之后：

| 时刻 (UTC) | episode（=一次运行） | 步 | 动作 | 结果 |
|---|---|---|---|---|
| 21:22:27 | `20260923_052106_388842` | step 3 | `OPEN_HOME` | FAILURE `SEMANTIC_TARGET_NOT_VERIFIED` |
| 21:23:17 | `20260923_052253_240829` | step **1** | `OPEN_HOME` | FAILURE |
| 21:24:04 | `20260923_052338_889685` | step **1** | `OPEN_HOME` | FAILURE |
| 21:24:50 | `20260923_052423_781688` | step **1** | `OPEN_HOME` | FAILURE |
| 21:25:34 | `20260923_052508_661097` | step **1** | `OPEN_HOME` | FAILURE |
| 21:26:20 | `20260923_052554_016557` | step **1** | `OPEN_HOME` | FAILURE |
| 21:27:13 | `20260923_052644_347466` | step **1** | `OPEN_HOME` | FAILURE |
| 21:27:57 | `20260923_052732_081600` | step **1** | `OPEN_HOME` | FAILURE |

每一次的 `state_before.resource_search_open` 都是 **True**，而 `OPEN_HOME` 的控件（城镇门）正是被这块面板
盖住的那个角（#101）。

**七次是"一步长"的运行**：开局 → 决定回城 → 失败 → 结束 → 面板 30 秒后重启下一轮 → 同一张地图、同一块
面板 ⇒ 六分钟死循环，直到 `21:28:53` 一次**无关的** `SCAN_MAP_FOR_BEAST` 平移地图才把面板关掉。

## 根因：发出点有八个，守卫只在七个上

`brain.py` 里 `OPEN_HOME` 只有 7 处，**全部**绑在具名 goal 上（MAIL / EXPLORATION / DAILY / ALLIANCE /
RESEARCH / TRAIN / HOME），每处都有守卫。但爆发串的运行里 `best_goal` 是 **None**（所有 goal 都被
defer 掉），此时决定由运行时自己做：

```python
# runtime.py:651  _deferral_replan —— 运行时唯一的 Decision 发出点
if best_goal is not None or not deferrals or self._replan_attempted or world.page is not Page.MAP:
    return None
home = self.registry.get("OPEN_HOME")
if home is None or not home.ready(world):
    return None
return Decision("OPEN_HOME", f"deferred_{...}_left_nothing_to_do_here", ...)
```

它的触发条件恰好就是"这张地图上无事可做"，而"无事可做"最常见的成因就是上一轮把搜索面板留在了地图上。
⇒ **它在最需要守卫的地方没有守卫。**

离线复现（同一帧、生产视觉 + 生产大脑）：把 `current_goal` 设成 `AUTO_DISCOVERY` / `""` 时，`brain.decide`
回答 `SELECT_RESOURCE`，**不会**回答 `OPEN_HOME` ⇒ 这条 `OPEN_HOME` 不可能来自大脑。现场日志
（`learning/control_panel/latest.log`）里每一步都带 `decision.reason`，但它只保留最近一轮，爆发串的理由
已经滚掉了——这也是一条独立缺口：**episode 流里没有 `decision.reason`**，"这一步是哪个分支决定的"事后无法回答。

## 修法

`_deferral_replan` 里加与大脑七处**同样形状**的三行：面板在场时先发 `BACK`，
`reason=close_resource_search_before_the_deferral_hop`、`expected_result=resource_search_closed`、满足子仍是既有的
`resource_search_closed`（`BACK` 技能与 `verify_safe_back` 都是现成的）。

**刻意不设 `_replan_attempted`**：关面板是跳转的**前提**，不是跳转本身；那个标志保护的边界（一轮最多回城
一次、有活干时绝不回城）原样不变，同一轮的下一步会带着已关掉的面板重新进入这个函数。

测试：`tests/test_capability_gate.py::DeferredGoalSchedulingTests` 两个新用例——一个是本规则本身，
一个是它的**三条边界**（没有 defer 不动、有可选 goal 不动、不在 MAP 不动）。直接测函数而不是跑一轮：
"这一轮有没有可选 goal"取决于机器上的公平台账（该文件里已有两个用例正是这个 moving set 的受害者），
而这条规则与"哪个 goal 赢了"无关。

## 证据与边界

- `report.json`：该帧上用生产视觉重建的世界、注册表在该帧判为 ready 的技能全表、以及各种 `current_goal`
  下大脑的回答（用来证否"这条 OPEN_HOME 来自大脑"）。
- 未做/未验：**真机**未跑（AUTO 全程在跑，本轮改动是纯决策层，不会多按也不会少按）；爆发串本身的
  `decision.reason` 已无法回溯（日志滚动），所以"当时确实是 `_deferral_replan` 发的"是由
  **条件排他**得出的（大脑不可能发 + 该分支的触发条件与现场完全吻合），不是由当轮日志直接读出的。
  这正是上面那条"episode 缺 `decision.reason`"缺口值钱的地方。
