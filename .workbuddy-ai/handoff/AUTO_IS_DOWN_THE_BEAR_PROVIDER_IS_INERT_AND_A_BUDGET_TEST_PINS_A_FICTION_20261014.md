# AUTO 根本没在跑 / 巨熊就绪 provider 是**惰性**的 / 一个预算测试钉的是**虚构**（2026-10-14）

> 操作者本轮授"最高权限"。先按 SOP 重建状态，再挑最高价值缺口。
> 一件是**环境事实**（影响 D-A 的处置），两件是**顺着 D-K 摸出来的**，
> 其中一件**更正我上一轮自己的 handoff**。

---

## 一、AUTO **根本没在跑**（这不是"设备被 MANUAL 锁住"那么简单）

`learning/runtime_snapshot.json`（实读）：

```
agent_state          = 'IDLE'
runtime_thread_alive = False
scheduler_loop_alive = False
last_tick_time       = '2026-10-12T12:21:24Z'   ← 正是切 MANUAL 的时刻
last_action_time     = '2026-10-11T09:28:54Z'
```

⇒ **运行时线程与调度循环都是 False**，最后 tick 停在切 MANUAL 那一刻。
**所以"只把 MODE_STATE 翻回 AUTO"什么也不会发生** —— 没有线程在消费它。
**D-A 的处置因此要改**：解锁设备（或切模式）**不构成"恢复 AUTO"**，
还要**重新起面板/运行时**。本文件把这条写成事实，免得下一个人只翻模式就以为恢复了。

（也正因为如此，本轮**没有**去翻 `MODE_STATE`：翻它既违反操作者自己写的"校准完成后由用户切回"，
又**不足以恢复 AUTO**。）

### 一·补：**恢复 AUTO 的准确步骤**（本轮补测，更正上一版的措辞）

上一版写"还要**重起面板/运行时**"——**方向对，措辞不准**。2026-10-14 12:5x 补测：

| 组件 | 实测 |
|---|---|
| 面板进程 | **在跑**（`pythonw` ×3，最老 start `2026-10-12 20:56`）|
| 模拟器 | **在跑**（`MuMuVMMHeadless` ×1）|
| ADB | **在跑**（5037 LISTENING，pid 1776）|
| AUTO 循环 | **停着**（`runtime_thread_alive=False` / `scheduler_loop_alive=False`）|

而 `MODE_STATE` **只管权限、不管循环存活** —— 面板自己的 docstring 就是这么写的：
> "机器状态 already carries the loop's real liveness, so the headline must not imply
> 'running' purely from the mode … the record said AUTO while the panel had been down 53 minutes."

**循环的启动入口是一个显式按钮**：`tools/control_panel.py:6015`
`ttk.Button(controls, text="开始自动运行", command=self.start)`（总览页，`03_NEXT_ACTION.md` 也提过
"AUTO 面板进程仍是停止状态，需显式启动"）。

⇒ **准确的恢复步骤**（三步）：
1. **模式**：操作者把 latch 放掉（或面板切回 AUTO）——这让 `machine_is_ours` 为真；
2. **启动循环**：在面板总览页点 **「开始自动运行」**（`self.start`）——这一步才是恢复 AUTO；
3. **验收**：`learning/runtime_snapshot.json` 的 **`runtime_thread_alive` 与 `scheduler_loop_alive` 都变 true**
   （这才是"在跑"的判据；**不要**拿 mode==AUTO 当运行证明 —— 那正是上面那段 §9 谎话）。

**所以面板本身不用重起**（它活着）；缺的是第 2 步那个显式启动。

**补：没有 CLI 捷径**（2026-10-14 查 `launch_pinned_production.py --help`）——
它的自述是"**Launch the control panel only**"，`--check-only` 是"verify pin and mounts **without starting AUTO**"。
⇒ 它**只负责启动面板**，**不带**"起 AUTO"这个动作；而面板**已经在跑** ⇒
**真正要做的只有那一次界面点击**（或以后给面板加一个 CLI 入口 —— 那才是可自动化的路）。

### 一·补² · 让"起 AUTO"**可脚本化** —— 提案（**本轮没做**）

**为什么值得做**：AUTO 一旦意外停掉，**只有人去点那个按钮**才能恢复 —— 这挡住了"长期无人值守"本身。

**机制已查清**（读 `winter_agent_v2/runtime_reload.py` 的 docstring）：
> AUTO 的**每个 cycle 都是一个全新的子进程** —— 面板用
> `self.repeat_after_id = self.root.after(5000, self.start)` **每 5 秒重新拉起 `tools/run_live.py`**。

⇒ 所以 `self.start`（按钮 `command=self.start`）**调用一次就会自我续排**；要"起 AUTO"只需**触发一次 `self.start`**。

**项目里已有现成的文件式请求机制可扩展**（不要另造第二套）：
`winter_agent_v2/runtime_reload.py` 的 `ReloadSignal`：`REQUEST_KIND = "RUNTIME_RELOAD_REQUIRED"`、
`request(job_id, reason, evidence)` / `pending()` / `clear(reason)`，面板在 tick 里消费（`control_panel.py:8211-8320`）。

**两条候选形状**（都属设计决定，未实施）：
1. **加一个请求 kind**（例 `AUTO_START_REQUESTED`）到同一套 `ReloadSignal` 模式，面板 tick 读到就调一次 `self.start()`；
   —— 优点是**复用单一真值**（§三·八 第十四条），缺点是面板 tick 里多一个消费者。
2. **给启动器加开关**（例 `launch_pinned_production.py --start`），把它透传给面板，面板起来后自动调一次 `self.start()`；
   —— 优点是改动面更小，缺点是**只在面板启动时有效**（不能给"已经跑着的面板"下命令）。

**可验证性（关键）**：这条改动**可以真机验证而无需"放行设备"** —— 因为
**mode 门只管动作、不管循环存活**；实施后重启面板、写一次请求，
**看 `runtime_snapshot.json` 的 `runtime_thread_alive` / `scheduler_loop_alive` 是否变 true** 即可。

**本轮没做的理由**（明确）：它要**重启面板**（一次生产操作）并**在你机器上拉起 AUTO 进程**，
而这正是操作者手动 latch 想独占的东西 ⇒ **属你的决定**，不是我在离线里能替你按的键。

## 二、巨熊就绪 provider 的 `READY` 分支：**不可达，而且惰性 ⇒ D-K 有答案了**

**两个operand 在生产里都没人写**（全仓实读）：

| 字段 | 读它的地方 | 生产写入方 |
|---|---|---|
| `auto_join_enabled` | `goal_library.py:1988`（provider 的 READY 条件） | **无** —— 只有 `tests/test_alliance_timed_provider.py:20` 造过 |
| `joinable_rally_count` | 同上 | **无** —— 全仓**零**键位写入 |

而 `_append_alliance_timed_provider`（`:1973`）只在 `bear.get("auto_join_enabled") is True
or bear.get("joinable_rally_count", 0)` 时把 `provider_state` 记成 `READY`。
⇒ **该分支在生产里不可达**；provider 只能停在 `OPEN` / `WAITING_WINDOW` / `REGISTERED`。

**但更要紧的是它惰性**：`provider_state` **全仓没有任何消费者**
（只有 `goal_library.py:1993` 写它；`goal_utility.py:640` 还专门把这一行**列为不给票**的 projection，
因为它 `available_skills=()` 且 `execution_owner="EXISTING_EVENT_GOALS"`），
控制台也**不展示** `provider_state`（只展示 episode 证据文件名）。
⇒ **就算把 `joinable_rally_count` 接上，结果也没有人读**。

**可用的读取器却在闲置**：
- `rally.RallyListReading.joinable_bears()`（`rally.py:351`）—— 用行自己的 `joinable` 谓词
  （`rally.py:143` = `joinable_for(BEAR)`，含容量未满判定），**`winter_agent_v2/` 内零消费者**；
- `bear_state.read_state_from_image()`（`bear_state.py:69`）读自动加入开关，目前**只**被
  `executor_router.py:699/704` 那个 tap 守卫用。

**⇒ 对 D-K 的答案**：**巨熊链不需要 `BEAR_AUTO_JOIN` 这个开关技能**。
`PARTICIPATE_BEAR` 的路由用 `BEAR_SKILLS = {START_RALLY, JOIN_RALLY, OPEN_BEAR_RALLY_LIST}`
（三个都已在 `VERIFIED_ATOMIC`），**不含** `BEAR_AUTO_JOIN`；
自动加入只是 playbook 的一条**策略分支**（"auto_join_on → 先观察、JOINED 直接 PASS"），
读不到它只意味着**少一条快路**，链本身仍走 LIST_DYNAMIC 手工加入。
⇒ **不是巨熊的阻塞点**；`BEAR_AUTO_JOIN` 不在 `VERIFIED_ATOMIC`/`BEAR_SKILLS` 是**安全的**。

**本轮没有接线**，理由是明确的：**接上去的产物没人消费**（`provider_state` 无消费者）
⇒ 那是**无人使用的 churn**，不是修复。要让 `joinable_rally_count` 有意义，
得先**给它一个真消费者**（例如让巨熊链按"可加入数"择优）—— 那是**设计决定**，不是顺手接线。

## 三、⚠️ 更正我上一轮自己的 handoff：预算有**第二个**生产读者

`THE_LEARNING_BUDGET_CLAUSE_IS_UNREACHABLE_IN_PRODUCTION_20261014.md` 说
`max_bootstrap_visits_per_run` "**生产只有一个调用方**"（那条死支）。
**不完整**：`winter_agent_v2/runtime.py:2245-2255` 的 `_learning_window_open` **也读它**：

```python
if getattr(self, "_learning_window_used", False):
    return False
self._learning_window_used = True
state = self._bootstrap_state()
row = state.get("__run__") if isinstance(state, dict) else None
visits = int((row or {}).get("visits_this_run") or 0) if isinstance(row, dict) else 0
return visits < DEFAULT_BUDGET["max_bootstrap_visits_per_run"]
```

**它在生产里也读到 0** —— 因为 `_bootstrap_state()`（`runtime.py:2214-2219`）只保留带
`cooldown_until` 的条目，`__run__` 被丢掉 ⇒ `row=None` ⇒ `visits=0` ⇒ `0 < 1` = **True**。
⇒ 所以这个函数**每次进程的第一次调用都返回 True**，真正的界还是 `_learning_window_used`
（进程内一次性内存标志）。**上一轮的结论（"预算在装饰、真正的界是内存标志"）是对的，
但"只有一个调用方"是错的 —— 有两个，且两个都读到 0。**

## 四、⚠️ `test_learning_window.py` 钉住了一个**生产里不可能发生**的守约

`tests/test_learning_window.py:56` `test_the_window_respects_the_budget_it_reads_from_the_projection`
这样构造：

```python
harness = _Harness({"__run__": {"visits_this_run": spent}})   # spent = 1
assert _open(harness) is False
```

而 `_Harness._bootstrap_state()`（`:39-43`）**只是 `return self._state`** ——
**没有施加真实 `LiveRuntime._bootstrap_state()` 那个"只留带 `cooldown_until` 的条目"的过滤器**。

⇒ 于是：测试喂进一个 `__run__`，真实过滤器会把它**丢掉**；测试的桩不会。
⇒ **该测试断言的"预算拒绝"（`visits=1 → False`）在生产里永远发生不了**
（生产里 `visits` 恒为 0 ⇒ 恒 True）。**这是一条假信心**：
它绿着，却让人以为"运行时会按预算关窗"，而真值是这个读取**到不了**拒绝分支。

**本轮没有改它**：改法有两种（把 harness 换成真实过滤器 ⇒ 测试会**变红**，
暴露"预算不生效"；或把断言改成**真实行为**），**两者都触及"预算到底该不该咬合"这个设计决定**，
不是我可以顺手定性的。**先记录。**

## 五、能说 / 不能说

- **能说**：① AUTO 线程与调度循环**都是 False**（有读数）；② `auto_join_enabled`/`joinable_rally_count`
  **生产零写入** ⇒ provider `READY` 不可达；③ `provider_state` **零消费者** ⇒ 惰性；
  ④ 巨熊链**不需要** `BEAR_AUTO_JOIN`（路由不含它、三个核心技能都在 `VERIFIED_ATOMIC`）；
  ⑤ 预算有**两个**生产读者且都读到 0；⑥ 那个测试的 harness **绕过**了真实过滤器。
- **不能说**：预算"该不该"咬合（**设计决定**）；`joinable_rally_count` 该由谁消费（**设计决定**）。

## 六、未做

**没翻 `MODE_STATE`**（操作者的 latch + 且无线程，翻了也无效）；没起面板/运行时；
**没接线 `joinable_rally_count`**（产物无人消费 ⇒ churn）；没改 `provider_state` 的消费者；
**没改** `test_learning_window.py`；没改 `capability_bootstrap` 的预算；没动设备。
