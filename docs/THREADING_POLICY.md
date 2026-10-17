# THREADING POLICY — 主线程纪律

> **本文件 §1 的四条规则逐字来自操作者的会话指令，不得改写。**
> 它们的权威是**操作者本人**，不是本文件；这里只做逐字誊录。
> （与 `docs/GAME_KNOWLEDGE.md`、`docs/STORE_POLICY.md` 那种「另有权威原件」的副本不同 ——
> 这四条**目前只存在于会话消息里，本文件是它们唯一落盘的记录**，
> 所以誊录必须逐字，改动必须先取得操作者确认。）
>
> §2 以后是**落地证据**，属本仓库可复核读数（每条带 `文件:行号`），
> 随代码变动会过期 —— 引用前请回原文件确认。
>
> 整理时间：2026-10-05。

---

## 1. 操作者原文（唯一权威）

操作者于 **2026-10-04 08:48 (GMT+8)** 在会话中给出的四条纪律，逐字如下：

```
1. 主线程只做 UI + 调度 + 派发
2. I/O 类任务 → 后台线程或 asyncio
3. CPU 类任务 → 独立进程
4. 大任务 → 独立子进程
```

背景：这四条是对「无尽冬日 AI 指挥中心卡顿严重」的架构性答复。
同一会话里操作者补充了硬件前提：**笔记本 8 核 16 线程**（解释 CPU% 时要用这个基数）。

> ⚠️ 这四条**不在任何仓库文件里** —— 它们只存在于操作者的会话消息中。
> 本文件是它们到目前为止**唯一落盘的规范化记录**。
> 但它们**不是**「用户明确策略」（§69 那一类），所以：
> 修改实现方式不需要再问；**修改这四条本身需要**。

---

## 2. 落地证据（本仓库可复核）

结论先行：**四条都已落地，且不是因为「顺手这么写」，是因为有实测数字逼着改的。**

### 2.1 第 1 条：主线程只做 UI + 调度 + 派发

代码把这个规则**写进了 docstring**，并注明出处的日期。两处：

`tools/control_panel.py:4842-4855`

```python
class ControlPlaneProbe:
    """Answers "is this window running code that is no longer on disk?" off the UI thread.

    Division of labour, the operator's rule of 2026-10-04: the main thread does UI,
    scheduling and dispatch only, and I/O belongs on a background thread.  Reading the tree's
    version is I/O by that rule (``git`` subprocesses, then ``sha256`` over the dirty files),
    and by measurement it is the most expensive thing the refresh cycle did.

    This class only *computes and publishes*.  Acting on the answer -- writing the reload
    marker, deciding a safe point, delegating the restart to the launcher -- stays on the UI
    thread, because it touches the process and Tk.  ``_check_control_plane_reload`` is the
    consumer; ``refresh_once`` is exposed so a test can compute one answer synchronously
    instead of waiting for the thread.
    """
```

`tools/control_panel.py:2857-2870`（同一个模式，更早）

```python
class ClosureCardProbe:
    """Keeps the closure card computed and published, off the UI thread.

    Division of labour, the operator's rule of 2026-10-04: the main thread does UI, scheduling
    and dispatch; I/O belongs on a background thread.  This card is I/O by that rule -- it reads
    ``learning/workbuddy_escalations.jsonl`` (7.5 MB), a 32 MB tail of ``learning/episodes.jsonl``
    and runs ``git log`` through :func:`unattended_closure.heads` -- and by measurement it cost
    **3104 ms cold on the thread that draws the window**, once a minute.
    ...
    This class only *computes and publishes*.  Nothing here touches Tk, the process or the
    device.  ``closure_card`` is the consumer and reads a published snapshot; ``refresh_once``
    is exposed so a test can compute one card synchronously instead of waiting for the thread.
    """
```

**「只计算与发布」是这条纪律在代码里的形状**：探针类不碰 Tk、不碰进程、不碰设备，
只产出一个不可变答案（`ControlPlaneAnswer` 是 `NamedTuple`，发布就是一次引用替换），
由 UI 线程上的消费者去**行动**。

### 2.2 第 2 条：I/O 类任务 → 后台线程或 asyncio

面板当前有 **6 个命名守护线程**，每一个都是「把 I/O 从画窗口的线程上搬走」的结果：

| 线程名 | 定义处 | 负责的 I/O |
|---|---|---|
| `panel-episode-warm` | `tools/control_panel.py:2370` | episode 预热 |
| `closure-card-probe` | `tools/control_panel.py:2895` | 读 `workbuddy_escalations.jsonl`(7.5 MB) + `episodes.jsonl` 32 MB 尾部 + `git log` |
| `panel-probes` | `tools/control_panel.py:3951` | 面板探针；含 `_poll_truth`（`:4041`）与它在 `:3968` 的调用点 |
| `queue-pump` | `tools/control_panel.py:4536` | 队列泵 |
| `control-plane-probe` | `tools/control_panel.py:4871` | `git rev-parse` + 版本相关脏文件的 sha256 |
| `unified-auto-worker` | `tools/control_panel.py:7828` | AUTO 主循环 |

全部以 `daemon=True` 启动（`ControlPlaneProbe.stop` 的 docstring：
「Daemon, so a missed call cannot keep the process up.」）。

**UI 线程留给自己什么**：`root.after(...)` 的节奏 ——
`:5044-5046` 的 `100/250/1000 ms`、`:6980` 与 `:9124` 的 `1500/1200 ms`、
`:7560` 的时钟 `1000 ms`。也就是说 UI 线程只负责**画**和**排下一次什么时候画**。

**为什么必须搬走（实测数字，注释里留着）**：

`tools/control_panel.py:4818-4830`

```python
#: How often the control-plane staleness question is recomputed.
#:
#: Measured 2026-10-04 on the pinned production tree: one answer costs
#: ``canonical_revision`` 1.03 s (a ``git rev-parse`` plus a content hash of every
#: version-relevant dirty path) and ``changed_paths_since`` a second ``git`` process on top.
#: The refresh cycle that consumed it ran every 1.5 s (``root.after(1500, ...)``) *on the UI
#: thread*, so two thirds of every cycle was spent in ``git`` and hashing -- the operator's
#: 卡顿, and the largest single block in a py-spy profile of the live window.
#:
#: Thirty seconds is far tighter than the event it detects: the notice is "a commit touched a
#: file this window imports", and the operator's next action is a restart at a safe point.
#: Nobody commits a control-plane fix and expects the banner within the same second.
CONTROL_PLANE_INTERVAL = 30.0
```

**这条注释是整份纪律的实证**：搬走之后，同一个问题从「每 1.5 s、占满三分之二个周期」
改成「每 30 s、在后台线程」，而 30 s 依然远紧于它要检测的事件（一次提交动了本窗口 import 的文件）。
它同时记录了一件重要的事：**降低频率不是妥协，是因为检测目标本身没那么急。**

`ClosureCardProbe` 的 docstring 里还留着搬走前后的对照表：

```
closure_card cold              3104 ms   ->  ~700 ms
  of which closure.build x 195 2602 ms   ->  ~13 ms (one chain, not 195)
  tail_jsonl(32 MB)             396 ms   ->   396 ms (unchanged, now off-thread)
  EscalationLedger.events()     168 ms   ->   168 ms
  current_development_trace     111 ms   ->   111 ms
```

注意 `tail_jsonl(32 MB) 396 ms → 396 ms (unchanged, now off-thread)` 这一行：
**数字没变，变的只是它不再发生在画窗口的线程上。** 这正是第 2 条要达到的效果。

`ClosureCardProbe` 的 docstring 里另留了一句判据，值得单独记住：

> 之前那版缓存**知道答案还是新的，却仍然在 UI 线程上重算它** ——
> 「a 3 s freeze is not something a TTL can excuse」。

### 2.3 第 3 条：CPU 类任务 → 独立进程

进程级隔离的落点：

| 设施 | 位置 | 说明 |
|---|---|---|
| `NO_WINDOW_FLAGS` | `tools/control_panel.py:403` | `getattr(subprocess, "CREATE_NO_WINDOW", 0)` —— 子进程不弹黑窗 |
| `_background_popen(command, **kwargs)` | `tools/control_panel.py:478-482` | 统一走 `subprocess.Popen(..., **winproc.hidden_kwargs())` |
| `self.process: subprocess.Popen \| None` | `tools/control_panel.py:4923` | 面板持有的子进程句柄 |
| 夜间离线学习 | `tools/control_panel.py:9012` | `winproc.spawn_detached([sys.executable, ROOT/"tools"/"learning_report.py", "--offline", "--root", ROOT], ...)` |

夜间那条是最清楚的「CPU 活搬家」例子：**离线学习（只读截图建索引，不操作设备）
被扔到一个 detached 子进程里跑**，面板只留一句「离线夜间学习已启动」。

### 2.4 第 4 条：大任务 → 独立子进程

`winproc.spawn_detached(...)` 是这条的落点。它同时带着一条**血泪约束**，
记录在 `tools/control_panel.py:7960-7975`：

```
# ``panel_restart.py --restart`` is ``cmd_stop()`` then ``cmd_start()``, and ``cmd_stop``
# ends in ``taskkill /PID <panel> /T /F`` (panel_restart.py:290).  ``/T`` follows
# *parentage*, and this helper is spawned BY the panel ..., so the helper is inside the
# tree it is killing: it kills itself before ``cmd_start`` is ever reached.
# ... "taskkill /PID <panel> /T follows parentage, and DETACHED_PROCESS does not change
# parentage", measured 2026-09-18
```

**教训**：`DETACHED_PROCESS` **不改变父子关系**。所以「把大任务扔进子进程」时，
如果那个子进程还负责重启父进程，它会把**自己**先杀掉 —— 这是 2026-09-20 连续两次
（pid 2272 与 pid 19612）重启失败的真实原因，日志停在 "stopping panel tree at pid 19612"。

---

## 3. 四条对应的正确形状（照这个写新代码）

| 你在做什么 | 往哪放 |
|---|---|
| 画界面、排下一次重绘、响应点击 | **UI 线程**（`root.after` 之外不要做别的） |
| 读文件、读 git、读网络、跑 OCR、读设备帧 | **后台守护线程**（参照 `ClosureCardProbe`：只计算与发布，行动留给 UI 线程） |
| 批量计算、离线索引、重编码 | **独立进程**（`_background_popen` / `spawn_detached`） |
| 会跑很久、且不该跟着面板一起死的大任务 | **独立 detached 子进程** |
| 一个探针算出的答案 | **不可变对象 + 一次引用替换**；不要在 UI 线程上`join()` 它 |

**判据（来自 `ClosureCardProbe`）**：如果一段代码会让窗口**冻结到能被操作者肉眼看见**
（实测阈值出现在 3104 ms），那它不管缓存多新都不该留在 UI 线程上。

**反例（来自 `CONTROL_PLANE_INTERVAL` 注释）**：不要用「把频率调低」来掩盖主线程上的重活 ——
当时的问题不是问得太勤，是每次问都花 1.03 s 且发生在错误的线程上。

---

## 4. 尚未转换的部分（诚实清单）

以下是**已知仍在 UI 线程上、或尚未按这四条整理**的地方。列在这里是为了不让本文件看起来像
「全都做完了」：

1. **`_poll_truth` 的消费者路径**：探针在 `panel-probes` 线程上算，
   但 `TruthAudit` 的导入与实例化在 `_poll_truth`（`:4041`）内发生 ——
   **新起一个审计实例的成本是否落在 UI 线程，尚未逐条核过**。
2. **`sys.executable` 相关的第三处**（`:2819`）只用于解析解释器路径，未涉及耗时工作 ——
3. **未做全仓盘点**：本文件只核了 `tools/control_panel.py`。
   `winter_agent_v2/` 下是否还有在主线程上做重 I/O 的地方，**没有验证过**。

**下一轮的检查方式**（可复跑）：对面板跑一次 py-spy，
看还有哪些耗时块落在 `MainThread` 上；对照本文件 §2.2 的表逐条判定是否已搬走。

---

## 5. 维护约定

1. 本文件 **§1 的五行不许改** —— 要改先取得操作者明确确认。
2. §2 的 `文件:行号` 会随代码漂移。**改面板线程结构时，顺手更新这里的行号**；
   若某条证据消失了，就把对应的行删掉，**不要留一个已经不成立的「证据」**。
3. 新增守护线程时，把它加进 §2.2 的表。
4. 不要在本文件里写「已完成」而没有 `文件:行号` 支撑的结论。
