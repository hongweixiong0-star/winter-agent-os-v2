# 接缝：把循环检测器落到主路径上（LOOP_WATCH_V1，2026-10-04）

## 一、一句话

`LOOP_DETECTOR_INPUT_IS_NOT_THE_FACT_20261004.md` 的下一步是「修复 A：把检测器接到主路径」。
本次把那一步做完了：新增 `winter_agent_v2/loop_watch.py`（接缝本体）、`tests/test_loop_main_path_wiring.py`
（36 项边界测试）、`tools/replay_loop_main_path.py` 增加「每运行一个检测器」的一遍（判据 3 的仪器），
`runtime.py` 四处接线。**三件事都是量出来的，不是声称的**：

- **上线前的安全性**：约 335 个运行里，梯子的实际动作是 **8 次**把 `HERO_RECRUIT_ADVANCED`
  交还调度器 —— 而那个目标在 179 行里进步次数是 **0**；
- **零回归**：同一棵树、同一份数据、同一顺序的 140 文件 A/B，两侧都是
  `176 failed / 1926 passed / 655 subtests passed`，失败清单逐行一致（§10.1）；
- **不拖慢**：接缝最坏情况 0.0191 ms/步 = 中位步长 7953 ms 的 0.00024%（§5.1）。

另外记下了本次**比接缝更值钱**的一个发现（§8.2）：那条本该拦住 `HERO_RECRUIT_ADVANCED` 的
**目标级守卫一直存在**，只是它的账本窗口按「每行 4 KiB」的假设写死，而行已经长到 12.7 KB，
于是它实际只看到 127 行而不是 400 行 —— **守卫一直在，只是看不见那个目标**。未修，见 §8.2.1。

---

## 二、缺陷回顾（三行）

| 门 | 事实 | 本次怎么处理 |
|---|---|---|
| 门 1 | 检测器只在 `SessionEngine` 里跑，主路径 0 引用 | 主路径现在每次完成一步就喂一次（`runtime.py` 一处调用点） |
| 门 2 | 会话里的 `progress` 是 `result` 冒充的 | **不用冒充值**：主路径已经有 `progress_moved` 的三态事实 |
| 门 3 | 主路径有事实，但没有把事实喂给检测器的载体 | 载体就是那个接缝 |

三道门不是三个 bug，是同一句话：**检测器需要的事实，主路径在算，但没人递过去。**

---

## 三、为什么是「投影」而不是「第二个检测器」

`tests/test_loop_detector_boundary.py` 钉了两条：

1. `session_engine` 里 `"state.loop.observe("` **恰好 1 处**；
2. 四个 adapter 不许出现 `LoopDetector|LoopSignature|RECOVERY_LADDER`。

它**没有**禁止 `runtime.py` 用同一个 `LoopDetector`，但模块自己的设计原话是
「第二个 `observe` 调用点就是第二个『什么叫循环』的定义」。所以本次的纪律是：

- **不重新实现任何判据。** 阈值、模式、窗口、梯子顺序，全部来自 `loop_detector`（`loop_watch.py`
  里连 `AAA_REPEATS` 这几个名字都不出现，有测试钉着）。
- **只做两件引擎从 adapter 那里得到的事**：把一步翻译成 `LoopSignature`；把梯子的每一档
  映射到这个路径**已经有**的表面。
- **接缝是新模块，不是 `runtime.py` 里的新分支。** 于是 `session_engine` 的那 1 处原封不动
  （`test_the_engine_observes_a_loop_in_exactly_one_place` 仍然绿）。

---

## 四、投影表：六档 → 四意图

| 梯子档（`RECOVERY_LADDER`） | 主路径的意图 | 落在哪个既有表面 |
|---|---|---|
| `semantic_retry` | `same_step` | **无动作**：循环下一轮本来就会从同一状态重发同一技能；意图与档名都写进 trace |
| `local_reobserve` | `same_step` | **无动作**：主路径每轮只观察一次，而「便宜地再看一眼当前页」就是下一轮本身 |
| `widen_observe` | `widen` | `runtime._observe(..., widen=True)` 的 `elif widen:` 分支（它的 docstring 早就写明自己就是这一档的落点） |
| `feature_reopen` | `go_home`（**跳过**） | 无可用表面 → 向前跳到 `home_recovery`，并把跳过的档名记进 `Watch.skipped` |
| `home_recovery` | `go_home` | `Decision("OPEN_HOME", ...)`，与 `_deferral_replan` 用的是同一个技能、同一个验证器 |
| `defer_goal` | `yield_goal` | `_yield_to_next_goal`（`runtime.py` 里已有的第 7 个调用者） |

三个设计决定，逐条给理由：

### 4.1 为什么前两档塌成 `same_step`，而不是硬造一个动作

- 「重试同一步」在主路径上**就是现状**：同样的状态喂给同一个 `RuleBrain`，答案大概率一样。
- 「便宜地再看一眼」在主路径上**也是现状**：每轮一次观察，不看第二眼。
- 硬造一个「强制重发上一步的决定」是**新的行为**：它会让运行时发出一个 brain 不会选的点击。
  一档 remedy 的收益是「早点发现循环」，而它的代价是「多一次可能错的点击」——这个交换在本档
  上不划算，而且它并不是必需：第三档 `widen` 才是第一档真正有区别的补救。
- 它**不是静默的空操作**：意图与档名都进 trace（`loop_watch_rung` / `loop_watch_intent`）。
  引擎的原话是「一个静默无事的 remedy 与没有 remedy 无法区分」——这里不是静默。

### 4.2 为什么不可用的一档是「向前跳」，而不是像引擎那样直接结束

引擎的 `_apply_loop_rung` 对 `feature_reopen` 返回 `False`，调用方就结束会话。那是因为**引擎
没有 adapter 就没有任何更后面的档**……但它其实有（`home_recovery`、`defer_goal` 都不需要
adapter）。`DEVICE_RUNGS` 的注释写明引擎「可以跳过宿主演不出来的档」。所以主路径选了更完整的那条：

- 向前跳到**能执行的第一档**；跳过的档记进 `Watch.skipped`，于是 trace 说的是「这里梯子少了
  一档」，而不是假装梯子有六档。
- 如果哪天梯子长到一档**都**执行不了，`resolve` 会 `raise`，不会返回「继续」。

两条路都写下来了，因为这是一个**决定**，不是一个默认值。

### 4.3 为什么检测器是「每运行一个」，以及为什么先量再上

`run()` 顶部建一个 `LoopWatch`，`finish` 时丢掉。理由有两条，第二条更重要：

1. 一个模块级/跨运行的检测器会把上一轮的账带进下一轮（`LoopDetector` 自身把计数器放在实例上
   就是这个理由）；
2. **梯子数字会完全不同。** 整窗一个实例：`LOOP_DEFERRED = 92/172`。每运行一个实例：85 次
   `defer_goal` 检测，但**实际动作只有 8 次** —— 因为 `_yield_to_next_goal` 对一个已经交还过的
   目标返回 `False`。一个「报了几次」的数字不能当「做了什么」用。

---

## 五、上线前的安全性测量（先量，再上）

`tools/replay_loop_main_path.py` 的 C 遍（每运行一个检测器，真目标，账本事实）。一次调用原文：

```
window   : last 60 MB of learning/episodes.jsonl
rows     : 4047                     runs 335  detectors 335
rungs    : semantic_retry 28  local_reobserve 25  widen_observe 21
           feature_reopen 9（不可用）  home_recovery 9      defer_goal 85
意图      : same_step 53  widen 21  go_home 18  yield_goal 85

被交还的目标 : ['HERO_RECRUIT_ADVANCED']   在 8 个运行里
             HERO_RECRUIT_ADVANCED 触发 130 次 / 179 行
             AVOID_STAMINA_WASTE   触发 46 次 / 673 行 / 从未到 defer_goal
```

⚠ **这些整数是「形状」，不是常量。** 仪器读的是生产**正在追加**的文件，而「按字节取尾」在
增长的文件上是一个**滑动**窗口：同一条命令一分钟后对同样的 `rows 4047` 打印的是
`detections 176`，再下一次是 177。不会动的是形状，而论证靠的是形状：

```
约 335 个运行 → 约 175 次检测 → 其中 85 次 defer_goal 塌成 **8 次真实交还**
                                （`_yield_to_next_goal` 对同一运行内已交还过的目标答 False）
                                8 次**全部**是 HERO_RECRUIT_ADVANCED
```

三条结论：

- **代价是 8 次交还 / 约 335 个运行 = 2.4%**，而且全部落在历史上**从未进步过**的目标上。
- **会进步的目标只吃到便宜的档**：`AVOID_STAMINA_WASTE` 触发 46 次，档位停在 `widen` 一线，
  一次都没到结束档。原因是它偶尔真的进步，`_rung_index` 被清零。
- 所以「会不会误伤好目标」这个问题，答案是**量出来的，不是辩出来的**。

⚠ 这一遍**不执行任何一档**，所以它测的是「会做什么」，不是「做完会怎样」。第二半要上线后看。

### 5.1 判据 4（主路径不得变慢）的直接测量

`--tail-mb` 那种前后对照要等上线后才有数据，但**接缝本身的开销可以现在就量死**，而且应该
用「最坏情况」量：让同一个动作连续无进步，于是每一步都真的取到 intent（2 万步里 19998 步取到），
这是梯子被打满的上界，不是平均。

```
raw LoopDetector.observe         0.0104 ms/call
LoopWatch 完整往返（observe+take）0.0191 ms/step   ← 最坏情况
LoopWatch.summary（每运行一次）   0.0016 ms/call

基线：total_step_ms p50 = 7953 ms ；episode_write_ms p50 = 78 ms
```

**0.0191 ms / 7953 ms = 0.00024%。** 判据 4 以约 40 万倍余量满足，且这是上界。
另外 `loop_watch_ms` 是**单独计时**的，不并入 `episode_write_ms`，所以上线后基线口径不变。

### 5.2 首次接触的真实记录（不是预期，是已发生）

worker 每个周期都重新导入包（`panel_restart.py` 的 docstring 原话：「the worker imports the
package fresh each cycle, so AUTO does not need it」），所以 `runtime.py` 一落到生产树，
**下一个 worker 就已经在跑 Fix A**，不必等面板重启。第一轮的真实产物：

```
[loop] MAX_ACTIONS_REACHED: detected 1 (AAA=1), ladder top (none), acted {}, skipped []
```

读法：24 步里只出现 1 次 `AAA` 检测，**没有升到任何一档、没有执行任何意图、没有跳过任何档**。
同时 `learning/control_panel/latest.log` 与 `panel.log` 里 `LOOP_WATCH_*` 警告 **0 条**、
`Traceback` **0 条** —— 也就是 `broken == 0`，接缝一次都没有拒绝过观察。

⚠ 这一轮 `acted {}` **不是「接缝没生效」**。那一轮运行的进行中目标是
`DISCOVER_QUICK_PANEL_TASKS`，而它在账本里 580 步有 **353 次 `True` 进步**（三态里真有进步的少数
目标之一）—— 进步会清零梯子，所以「检测到一次、什么都没做」正是设计要的行为。若拿它当
「接缝无效」的证据，就是把「没触发」与「不该触发」混为一谈。

---

## 六、预登记判据的对照

| 判据（原文） | 现在用什么量 | 状态 |
|---|---|---|
| 1. 回放里「规则 A」的那一列不再是 0 | 重读后：A=0 是**设计使然**（A 就是 `result` 冒充 `progress`，而接缝**不采用**这条规则）。接缝采用 B。仪器：`tools/replay_loop_main_path.py` | **判据本身需要重写**，见下 |
| 2. 回放里必须报告 `LOOP_FALSE_POSITIVE` | 仪器报 0；但 §8.4 已证明这个 0 是**定义使然**（`_settle` 只在同动作后来进步时才 +1）。独立探针 106/66 才是真数字 | 需要新指标 |
| 3. `LOOP_LADDER_TOP` 是否长期停在 `defer_goal` | C 遍给了静态值；**上线后看 `runtime` 状态里的 `loop_ladder_top` 与 `[loop]` 行** | 上线后 |
| 4. 主路径不得变慢 | 基线（改动前，`learning/action_latency.jsonl`，n=7307）：`episode_write_ms` p50 78 / p90 750 / p99 1235；`total_step_ms` p50 7953 / p90 14984；`reobserve_ms` p50 5594（**步长由观察主导**）。新增的 `loop_watch_ms` 单独计时，不并入 `episode_write_ms` | **已满足（上界）**：最坏情况 0.0191 ms/步 = 中位步长的 0.00024%，见 §5.1。上线后仍要看 `loop_watch_ms` 真实值 |
| 5. `HERO_RECRUIT_ADVANCED` 的连续 False 串显著变短 | 上线后统计该目标的连续 False 长度 | 上线后 |

**判据 1 必须重写，这是一处诚实交代。** 原文写「修复后规则 A 的那一列必须不再是 0」，它是按
「把检测器的输入修对」写的；但 §八的补测证明了三道门里**只有第三道是全部故事** —— 修的方向不是
把 A 那条规则修好，而是**让主路径喂 B 的那条规则**。A 仍然是 0，而且**永远该是 0**：`result` 是
「这一步落地了没」，不是「这个目标动了没」。所以正确的验收是「生产路径采用 B，且 B 的触发全部
可解释」，本次 C 遍正是这个。

---

## 七、边界测试（36 项，全绿）

| 断言 | 为什么必须有 |
|---|---|
| 投影覆盖梯子每一档（`unmapped_rungs() == ()`） | 第七档不能被 `.get(rung, ...)` 默默降级成「再发一次同一步」 |
| 拿一条真的多出来的档驱动，检查有牙 | 否则上一条是空的 |
| 不在梯子里的档名 `raise` | 同上 |
| 每一档都映射到闭集里的某个意图 | 加一个「结束」意图必须同时改这里，于是会被下面那条看见 |
| 投影表里没有「结束」类意图 | 「不得停止整个 AUTO」作为表格的性质，不只是源码的性质 |
| 唯一不可用的档是需要 adapter 的那一档 | `feature_reopen` = adapter 的 `recover` |
| 不可用档被跳过，且**报出被跳过** | trace 不许假装梯子有六档 |
| 只有被跳过的那一档报 skipped | 其余五档必须干净 |
| 只用标准库 + `loop_detector` | 与 `loop_detector` 同一条纪律 |
| **在新解释器里 import 它**，只加载了 `loop_detector` | 「第二 Scheduler/Executor/WorldState」的最强形式：import 图 |
| 不定义被禁的层 | 同上 |
| 模块级无可变状态 | 同上 |
| 不重述任何阈值 | 重述一次就是第二套判据 |
| 源码够不到任何「结束」 | `sys.exit`/`os._exit`/`AgentState`/`finish` 全无（**AST 扫描**，见 §八） |
| 上一条有牙 | 拿一段真的会 `sys.exit` 的源码驱动它 |
| `runtime` 里 `observe_step(` / `take(` 各恰好 1 处 | 「一个循环只有一个定义」 |
| `LoopWatch()` 只出现 1 次 | 防止跨运行共享 |
| 验证器通过但目标没动 = 循环 | **本次的核心回归** |
| 用引擎那条兜底规则（`progress_from_outcome("SUCCESS") is True`）时**不触发** | 说明为什么这不是一行改动 |
| `progress is None` 永不触发 | `None` 是「观测不到」，不是「没进步」 |
| 进步会清零梯子 | 否则间歇卡住的目标会因为一小时前卡过而被交还 |
| 梯子每重复一次升一档并饱和 | 上界 3 + 6，与预算无关 |
| `widen` 档可达（它的落点 docstring 早就点名了它） | 让「注意力」那条表面真的有调用者 |
| 一次只交出一个 claim；交给别的目标就丢掉 | 与 `_settle` 同一条staleness 规则 |
| 只有**执行过**的意图才计数 | 交出去和做到位是两件事 |
| 观测被拒时计数、不抛、只打印一次 | 诊断不能停游戏，但静默坏掉的诊断更糟 |
| 页名字的拼法与引擎和账本一致 | `Page` 是 `(str, Enum)`，`str(Page.HOME)` 是 `"Page.HOME"` |

---

## 八、同一个毛病出现了三次：仪器的「窗口」不是它声称的那个

本次最值钱的收获不是接缝本身，而是**同一类缺陷在一份代码里被找到三次**。三次的形状完全一样：
一个**检查或读数**，它读的不是它声称读的东西，而且**它一直是绿的**。

### 8.1 读原文的检查，读的是文档（属于别的文件，未改）

`tests/test_loop_detector_boundary.py` 的 `imported_roots()` 是**逐行切文本**的：

```python
elif stripped.startswith("from "):
    roots.add(stripped[len("from "):].split(" import ")[0].strip().split(".")[0])
```

`loop_detector.py` 的 docstring 里恰好没有一行以 `from ` 开头，所以它现在是绿的。但
`loop_watch.py` 的 `resolve` docstring 里有一句「… walks forward\nfrom the named rung to the
first one…」，那一段**顺着行首**往下读就是一行 `from …`，于是同一个函数把它读成了一个名叫
`the named rung to the first one this path can carry out` 的模块。

⇒ 结论：**一个读原文的检查，读的是文档，不是代码。** 一句话就能让「只依赖标准库」这条断言变成
假的（或变成永远绿的）。本文件的测试因此全部改成 AST 投影（`imported_roots` / `code_names` /
`used_attributes` / `called_names` / `module_level` / `mutable_module_state`），并且**用一段真的
会 `sys.exit` 的源码验证扫描本身有牙**。

那条弱点**没有去改**（不属于本次范围），但记在这里：它是一处「检查会被文档骗过」的实例。

### 8.2 ★ `EPISODE_TAIL = 400` 实际只有 127 行：那条目标级守卫看不见它要拦的目标

**这是本次最重要的发现，比接缝本身更重要，但它不是本次修的。** 起因是接缝上线后我发现
`HERO_RECRUIT_ADVANCED` 在那 172 行零进步里**根本没被延期过**，于是去复现生产自己的门：

```python
CapabilityGate.load(ROOT)      # run_live.py 就是这么调的
```

结果：`streaks` 里只有 **12** 个目标，**`HERO_RECRUIT_ADVANCED` 连记录都不存在**。
追下去是窗口：

```python
EPISODE_TAIL = 400                     # capability_gate.py:88
# 「4 KiB per row is a generous upper bound for an episode」
handle.seek(max(0, size - limit * 4096))     # 400 × 4096 ≈ 1.6 MB
rows[-limit:]
```

这个 400 是**行数**意图，但实现按 **400 × 4096 字节**回退。实测账本单行：

```
last 400 rows:  min 5953   p50 12661   p90 16429   max 19605 bytes
```

于是 `1.6 MB ÷ 12.7 KB ≈ 127 行` —— **实际拿到 127 行，不是 400 行**。两个独立数字吻合：
行长大 3.1 倍 ⇒ 窗口小 3.15 倍。**不是推测，是同一个数的两种读法。**

代价用生产代码自己的 `episodes=` 参数直接量出来了（同一本账，只换窗口）：

| | 实际窗口（127 行） | 意图窗口（400 行） |
|---|---|---|
| 可见运行数 | **7** | **31** |
| 有 streak 记录的目标 | 12 | 25 |
| 达到延期阈值（3） | 2：`KEEP_BUILDING_PRODUCTIVE 4`、`CLEAR_INTEL 3` | 7：再 +\ `KEEP_TRAINING_PRODUCTIVE 8`、`SCROLL_QUICK_PANEL_TASKS 6`、`SCHEDULED_BEAR_HUNT 5`、`SCHEDULED_STATE_VS_STATE 3`、**`HERO_RECRUIT_ADVANCED 3`** |

结论，也是本次最该记住的一句：

> **那条目标级守卫一直存在，只是它的窗口小了 3.15 倍，所以它看不见那个目标。**
> 「171 步零进步为什么没人拦」的答案不是「没有守卫」，而是「守卫的窗口按 4 KiB 假设写死了，
> 而行长大到 12.7 KB 之后，这个假设一直没人再量过」。

三条附带事实：

- `_episode_tail` **只有一个调用者**（`CapabilityGate.load`），所以影响面被限制在门内。
  但门本身是 `streaks` / `attempted` / `reached` / `compositions` 四个东西的输入，窗口一缩，
  这四个一起缩。
- 这不是我一个人踩的坑：`tools/control_panel.py` 有它自己的 `EPISODE_TAIL_BYTES = 512_000`
  配 `limit=30`，那个是**显式的字节上限 + 行数上限**，两个都写明了，而且 `limit` 先绑住
  （512 KB ÷ 12.7 KB ≈ 40 行 ≥ 30），所以它不是同一个毛病。**区别就在于它把「按字节」这件事
  写在了名字里。**
- 修它的方向很明确（按行回读、或把字节预算改成从实测行长推导、或直接提高倍数），
  **但本次没修**，理由见 §8.2.1 —— 这是一个会**把目标从棋盘上撤走**的行为变更。

#### 8.2.1 为什么「一行就能改」却没有改

把窗口从 127 行放宽到 400 行，上表右侧那 5 个目标**会新越过阈值**，其中
`KEEP_BUILDING_PRODUCTIVE` 从 4 涨到 **20**。延期闸门是「不许再选这个目标」，
所以放宽窗口的后果是**同时把更多目标从棋盘上撤走**；而本项目历史上已经吃过一次反面的亏
（`capability_gate` 的注释里记着：ANY_OF 的三条通路只返回一条，结果整个目标被藏起来，
「kept the goal off the board entirely」）。

于是判断是：**这是一个和修复 B 同类、需要自己一份 A/B 的行为变更，不是一个可以顺手带上的
一行修改。** 和 Fix A 混在同一个提交里，上线后的测量就再也分不清是哪一个起的作用 ——
而「提交粒度必须等于部署粒度」正是本项目已经写下来的教训。

另外它和 Fix A 的关系要说清楚，否则看起来像两套重复机制：

| 层 | 位置 | 粒度 | 判据 | 状态 |
|---|---|---|---|---|
| 运行内逐步 | `runtime.py` `no_progress_streak` | 步 | 连续计数 | 存在，修复 B 的目标 |
| 运行内检测 | **本次 `loop_watch`** | 步（按动作重复升档） | 六档梯子 | 本次新增 |
| 运行间 | `capability_gate` `NO_PROGRESS_STREAK=3` | **episode** | 连续 3 个 episode 无进步 + 30 分钟探测 | 存在，但**窗口缩水**，见 8.2 |

三者不重复：层的粒度不同。而 8.2 说明**运行间那一层目前是瞎的**，所以本次新增的运行内那一层
不只是「更快」，它现在是唯一真正在看这件事的。

### 8.3 重放仪器的 `--tail-mb` 也不是可复现窗口

同一条命令 `tools/replay_loop_main_path.py --tail-mb 60`，一分钟内三次调用：

```
rows 4047  runs 335  detections 176
rows 4047  runs 335  detections 177
```

`rows` 一样而 `detections` 不同，因为生产**正在往这个文件里追加**：4047 是「最后 4047 行」，
而那 4047 行本身在滑动。所以：
**数字要连同窗口一起引用，并且只能对「形状」作稳定断言**（§五 已经改成这么写了）。
`--tail-mb` 该有一个按运行数的兄弟参数；本次没加，因为改仪器会作废刚刚验过的那批证据，
而收益只在我的文档里。记在这里。

---

## 九、没做的 / 下一步

**下一步第一件事：§8.2 的窗口（`capability_gate.EPISODE_TAIL`）。** 它现在是已知缺陷里
性价比最高的一个 —— 一行级别的改动，影响的却是一条**已经存在、而且本该拦住
`HERO_RECRUIT_ADVANCED`** 的守卫。但它必须自带一份 A/B：要量「新越过阈值的 5 个目标里，
哪些真的该被撤走、哪些会因此少做事」。验收判据应该是「被延期的目标里，事后证明该延期」，
不是「被延期的目标变多了」。

- **修复 B 没做**：`no_progress_streak` 仍是「连续计数」而不是「率」。周期性循环是它的对手。
  证据已在：`DISCOVER_QUICK_PANEL_TASKS` 829 选 / streak 0、`DISCOVER_EVENT_CALENDAR` 797/0、
  `CLAIM_EXPLORATION_IDLE` 326/0、`DAILY_ACTIVITY_TARGET` 130/0，而 `CLEAR_INTEL` 1263/1142、
  `KEEP_TRAINING_PRODUCTIVE` 564/329。每角色账本在 `learning/roles/<role_id>/goal_fairness.json`；
  **顶层 `learning/goal_fairness.json` 是旧的，不要信**。
- **上线后要看的**（判据 3/5）：从 `learning/runtime_snapshot.json` 与 `[loop]` 行读
  `loop_ladder_top` / `loop_detected` / `loop_acted` —— 它会不会长期停在 `defer_goal`（饱和 vs 恢复）；
  `loop_watch_ms` 的真实分布；以及 `HERO_RECRUIT_ADVANCED` 的连续 False 串是否变短
  （注意：§8.2 之前这一条**不能**只归功于 Fix A，因为窗口那一层同时在影响它）。
  **⚠️ 这一句在上线后被证伪了：`learning/runtime_snapshot.json` 里当时根本没有 `loop_*` 键。
  见 §十一 —— 判据 3/5 当时**无法测量**，读 `learning/loop_watch.jsonl` 才是它真正的地方。**
- **`session_host.py:380` 不要顺手改**：`goal_progress = (outcome == SUCCESS)` 改成 `None` 会
  **降低** streak 爬升，是一次有真实副作用的行为变更，必须和 B 一起评估。
- **判据 3 仍未满足**：训练/建造链的 `goal_progress=True` 至今一次没出现过。前作 §三 的三个问题
  （HOME 上哪个控件是训练入口？为什么它在价格上输？它有没有验证器？）需要一张真机帧。
- 8 个未合并的旁支、`stash@{0}`、50 个 tracked-but-absent 的 `learning/_*.txt`、2 个既有
  `check_wiring` 红：与上次交接相同，未动。
- **开发仓里有两个未被跟踪的测试草稿**（`tests/test_one_shot_validation_probe.py`、
  `tests/test_travel_and_underground_pages.py`），它们让 `pytest tests/` 在**收集阶段**就中断，
  必须先加 `--continue-on-collection-errors` 才能跑全量。要么补上缺失的符号，要么删掉。

---

## 十、交付物行号清单

| 文件 | 位置 | 内容 |
|---|---|---|
| `winter_agent_v2/loop_watch.py` | 新增 | 接缝：`LoopWatch` / `Watch` / `RUNG_INTENTS` / `UNAVAILABLE_ON_MAIN_PATH` / `resolve` / `unmapped_rungs` |
| `winter_agent_v2/runtime.py` | 导入块 | `from .loop_watch import (INTENT_GO_HOME, INTENT_WIDEN, INTENT_YIELD_GOAL, LoopWatch)` |
| | `run()` 初始化 | `self._loop_watch = LoopWatch()`（每运行一个） |
| | 每轮开头（观察前） | `watch_goal` / `watch = self._loop_watch.take(...)` / `_observe(..., widen=watch.intent == INTENT_WIDEN)` |
| | 决策点之后 | `go_home` / `yield_goal` 两条分支（都能被 `best_goal` 与检测时的目标是否同一个关掉） |
| | 记录前 | `observe_step(...)`，喂 `progress`；`latency["loop_watch_ms"]` |
| | 延迟轨迹 | `**loop_fields`：`loop_watch_rung` / `loop_watch_intent` / `loop_rung` / `loop_pattern` / `loop_repeats` |
| | `finish` → `_publish_loop_watch` | 每运行一行：`loop_detected` / `loop_ladder_top` / `loop_acted` / `loop_skipped_rungs` / `loop_broken` + 一条 `[loop]` 打印 |
| `tests/test_loop_main_path_wiring.py` | 新增 | 36 项 |
| `tools/replay_loop_main_path.py` | 新增 C 遍 | 每运行一个检测器 + `loop_watch.resolve` 的意图列 |

### 10.1 本次跑过、可以复现的命令

```bash
# 边界断言：36 项新 + 16 项既有
pytest tests/test_loop_main_path_wiring.py tests/test_loop_detector_boundary.py -q
#   -> 52 passed, 74 subtests passed

# 爆破半径 A/B（同一棵树、同一份数据、同一顺序，只换 runtime.py）
#   基线  = git show HEAD:winter_agent_v2/runtime.py     (5a5bbdfa)
#   带修复 = 工作树
#   两侧各 140 文件：
#   -> 176 failed, 1926 passed, 11 skipped, 12 errors, 655 subtests passed
#      基线 422.45s / 带修复 416.45s
#   186 行失败清单逐行对比：唯一差异是一行 pytest 的警告捕获残渣
#   => 176 个失败与 12 个错误全部既有，Fix A 零回归

# 判据 4 上界（最坏情况，梯子打满）
#   raw LoopDetector.observe 0.0104 ms/call
#   LoopWatch 完整往返      0.0191 ms/step     基线 total_step_ms p50 = 7953 ms
#   LoopWatch.summary       0.0016 ms/call

# 窗口缺陷（§8.2）：同一本账，只换窗口
CapabilityGate.load('.')                    -> 12 goals, 2 over threshold
CapabilityGate.load('.', episodes=last400)   -> 25 goals, 7 over threshold
```

---

## 十一、上线后的更正：判据 3/5 当时是**不可测**的（2026-10-04，同日晚）

§六 与 §九 都把判据 3/5 的读法写成「从 `learning/runtime_snapshot.json` 读 `loop_ladder_top`」。
Fix A 上线（`08886209`）之后发现**这句读不出来**，而失败方式是无声的：

```
learning/runtime_snapshot.json   mtime 2026-10-04 13:44:34   （晚于 Fix A 上线）
                                 total keys: 35
                                 loop_* keys: NONE
```

mtime 晚于上线 ⇒ 运行中的面板**确实**在调 `_publish_loop_watch`、**确实**在打 `[loop]` 行；
同一个文件里却一个 `loop_*` 键都没有。原因不在调用方：

```python
# runtime_snapshot.py  RuntimeSnapshotStore.update
data.update(changes)
RuntimeSnapshot(**{k: v for k, v in data.items()
                   if k in RuntimeSnapshot.__dataclass_fields__})   # ← 未声明的键在此静默出局
```

`RuntimeSnapshot` 当时 35 个字段，**没有任何一个是 `loop_*`**。
「发布到运行时状态」这一半是**静默空操作**，而外部观察到的现象是健康的
（`[loop]` 行照常打印）。这是同一毛病在本项目的**第三次**：
`deferred_goals`（2026-09-18）、`fairness_written_at`/`fairness_write_skipped`（2026-10-03）。

**同时暴露的第二个问题：`[loop]` 行本身也不是可用的账。**
`learning/control_panel/latest.log` 每轮被 `write_text` 重写，worker 的 stdout 从不进追加的
`panel.log`（实测：`[utility] chose` 在 `latest.log` 出现 2 次、在 `panel.log` **0** 次）。
第一条真实 `[loop]` 行在一个重启内就从磁盘上消失，只剩引用。

**本次修法（三条一起，缺一条就还会复发）**

1. `RuntimeSnapshot` 声明 9 个 `loop_*` 字段（35 → 44）。
2. `LiveRuntime._append_loop_ledger()` 每次运行追加一行到 `learning/loop_watch.jsonl`，
   **空运行也写**（一个只记"有意思的运行"的账无法回答"多频繁"，而判据 3/5 都是趋势问题）。
   行含运行边界：`episode_id` / `recorded_at` / `role_id` / `step_goal`。
3. 通用守卫 `tests/test_a_ledger_that_stopped_being_written_says_so.py`：
   扫描 `winter_agent_v2/`、`tools/` 下**每个** `self._runtime(**changes)` 与
   `runtime_store.update(...)`，任何未声明键都要报出来。
   —— **点名今天的字段治不了明天的。**

**判据 3/5 现在的正确读法**

```bash
# 每运行一行的持久账（追加，不会被重写）
tail -n 20 learning/loop_watch.jsonl
# 运行状态里的当前值（现在真的有了）
python -c "import json;d=json.load(open(r'learning/runtime_snapshot.json',encoding='utf-8'));print({k:v for k,v in d.items() if k.startswith('loop_')})"
```

**验收（在 pin 树内）**

```bash
pytest tests/test_a_ledger_that_stopped_being_written_says_so.py \
       tests/test_runtime_snapshot.py tests/test_loop_main_path_wiring.py \
       tests/test_loop_detector_boundary.py tests/test_live_runtime.py \
       tests/test_auto_uptime_ledger.py tests/test_worker_exit_semantics.py \
       tests/test_auto_subprocess_recovery.py tests/test_loop_production_wiring.py -q -p no:randomly
#   -> 130 passed, 86 subtests passed

python tools/check_wiring.py        # -> problems: 2（仍是既有那两条，无新增）

# 通用守卫的牙（只回退两个生产文件、保留新测试）
git checkout -- winter_agent_v2/runtime.py winter_agent_v2/runtime_snapshot.py
pytest tests/test_a_ledger_that_stopped_being_written_says_so.py -q
#   -> 7 failed, 6 passed   失败原文：these writes are accepted by ``update``
#                            and then dropped without an error
```

**部署说明**：`winter_agent_v2/runtime_snapshot.py` **不在** `CONTROL_PLANE_PATHS`，
且 worker 每轮重导入包 ⇒ **本次不需要重启面板**。
