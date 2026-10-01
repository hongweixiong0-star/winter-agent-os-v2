# 桌面快捷方式「打不开」——第二次启动静默（2026-10-01 21:0x）

**结论一句话**：快捷方式、`.cmd`、`preflight`、计划任务**全都是好的**。真正的缺陷是
**面板已经在运行时，第二次双击不会产生任何可见结果**——而面板可以带着那把单实例锁
活很久（今天实测：**8.5 小时**）。现在双击要么把面板窗口举到你面前，要么明确告诉你
为什么举不起来。

---

## A. 现场（用户原话：「桌面快捷方式还是打不开」）

修复前，双击的真实行为（21:02 之前，我原样复现过）：

```
信息: 计划任务 "WinterAgentV2Panel" 正在运行。
成功: 尝试运行 "WinterAgentV2Panel"。
=== exit=0 ===
```

命令窗口一闪、报「成功」、**没有窗口**、**日志里一个字都没有**、退出码 **0**。
对操作员来说，「面板已经在跑」和「快捷方式坏了」**完全无法区分**。

---

## B. 根因：两条互相独立的静默路径

### 路径 1（主路径）：计划任务是 `IgnoreNew`

```
MultipleInstancesPolicy = IgnoreNew      ← schtasks /Query /TN ... /XML 实测
LogonType = InteractiveToken | Hidden = (空) | 状态 = 已启用 | 上次结果 = 267009
```

`IgnoreNew` 意味着：**面板一旦在跑，`schtasks /Run` 就什么都不启动**，只回一句
「正在运行」，**退出码仍是 0**。于是 `launch_pinned_production.py` 根本不被调用：

- `desktop_startup.log` **零条**新记录（launcher 在跑面板**之前**就写这行）
- `PRODUCTION_LAUNCH.log` **零条**新记录
- 所以 `control_panel.main()` 里的任何逻辑**都没机会运行**

**这一条推翻了我最初的修复位置。** 我先把修复写在 `main()` 的单实例分支里，端到端
验证**失败了**——窗口仍是最小化。那次失败是必要的：它把「要修的地方」从
`main()` 纠正到了**批处理文件**。

### 路径 2：单实例互斥锁

当面板**不是**由这个任务启动时（09:59:02 实测：任务被触发、launcher 跑了、
`PRODUCTION_LAUNCH.log` 写下 `SystemExit: 0`），新进程会命中
`control_panel._acquire_single_instance()` 的命名互斥锁，而它的失败分支原本是**裸的
`return 0`**：没有窗口、没有日志、没有提示。

### 为什么这次能持续 8.5 小时

```
panel.log:  12:03:42「自动运行已启动」之后 —— 全部静默，连周期性刷新都没有
PRODUCTION_LAUNCH.log: 12:xx 无 SystemExit  → 不是正常退出
System 事件 1074 @ 20:41:43  → 用户发起重启；LastBootUpTime = 20:42:07
```

面板进程从 12:03 起一直活着（整机进入睡眠、进程被冻结），**那把锁一直握着**，
直到 20:41 重启机器才释放。**这 8.5 小时里的每一次双击都被静默拒绝。**

---

## C. 三个反直觉的实测数据（都改变了实现）

### C1. `.NET` 的 `MainWindowHandle` 会说「没有窗口」——而窗口明明在屏幕上

```
Get-Process pythonw | Select MainWindowTitle, HasWindow
  11856  (空)  False          ← .NET 的答案

EnumWindows + IsWindowVisible + GetWindowRect
  pid=11856 hwnd=0x10b7a visible=True iconic=False rect=(156,101,1532,960)
  class='TkTopLevel' title='Winter Agent OS V2 — 无尽冬日 AI 指挥中心'   ← 真实答案
```

Tk 顶层窗口带 owner，`.NET` 的属性因此返回 0。**这个检查最初把我引向了
「进程活着但没有窗口」的错误结论**。用错 API 的检查会断言健康面板不存在——所以
实现用 `EnumWindows`。

### C2. `SMTO_ABORTIFHUNG` 把**最小化**的健康窗口判成「无响应」

| 窗口状态 | `SMTO_ABORTIFHUNG` | `SMTO_NORMAL` |
|---|---|---|
| **最小化** | **0（等满 2000 ms 超时）** | **1（219 ms）** |
| 恢复后 | 1（125 ms） | 1（31 ms） |

而**最小化正是操作员双击时最可能的状态**。这个 flag 会让修复**恰好拒绝服务目标场景**。
已改为 `SMTO_NORMAL`，并在 `WINDOW_PROBE_FLAGS` 上写了实测注释 + 一条防回归测试。

### C3. `windows[0]` 不是面板窗口；而且「无响应」对**忙碌但健康**的面板也成立

```
EnumWindows 顺序（实测）: TtkMonitorClass, TkTopLevel, MSCTFIME UI, IME
```
一个 Tk 进程同时拥有 4 个顶层窗口，**主窗口不在第一位**。取 `windows[0]` 会拿到
隐藏的 `TtkMonitorClass`。实现改为**按窗口类过滤**（`TkTopLevel`）。

更进一步：面板在 AUTO 轮次里会**阻塞自己的消息循环**去等 worker，所以存活探测对
「健康但正在跑一轮」的面板也会答「否」（实测：最小化后第一次探测等满超时，
下一次对同一窗口 219 ms 就答上了）。

**因此存活探测从「门槛」降级为「附注」**：无论如何都先把窗口举起来，
探测结果只用来补充说明。否则修复会**恰好在操作员最可能双击时拒绝服务**。

---

## D. 修复

### D1. `tools/panel_window.py`（新文件，唯一实现）

窗口探测与激活的唯一实现（`panel_window.py` 是轻量模块：`ctypes` + `winproc.alive`，
不 import `control_panel`，所以 `.cmd` 可以在加载面板**之前**调用它）。

退出码即接口，`.cmd` 按降序分支：

| 码 | 含义 |
|---|---|
| 0 | 找到在跑的面板并把它的窗口带到前台 |
| 1 | 没有面板在跑 → 调用方应当启动一个 |
| 2 | 有面板进程但窗口无法显示（原因在 stdout） |

另有 `--wait <秒>`：轮询直到窗口出现。**`schtasks` 的退出码 0 同时表示「启动了」和
「被忽略了」，区分不了**——一个始终不出现的窗口可以。

### D2. `Start-Winter-Agent-V2.cmd`：先问、后启、再确认

```
preflight --launch-gate          (原有)
panel_window.py --focus          (新)  0 → 已在运行，已举到前台，exit 0
                                        2 → 报明原因 + pause，exit 1
                                        1 → 落到下面
schtasks /Run                    (原有)
panel_window.py --wait 30        (新)  非 0 → 报明原因 + pause，exit 1
```

编码保持不变：**CP936 无 BOM、纯 CRLF、控制流行零非 ASCII**（中文只在 `rem`/`echo`）。

### D3. `tools/control_panel.py`：覆盖「任务没在跑但锁被占」

`main()` 的单实例失败分支调用 `_report_existing_panel()`（薄封装，委托给
`panel_window.focus_existing_panel`）。**这一半保留，因为 09:59 实测过它会被触发**——
当时面板不是由这个任务启动的。

整条报告路径**包了 try/except**：它跑在「即将 return 0」的出口上，那里抛异常就会
把刚修好的静默第二次点击**还原回去**。

### D4. 没有改 `.ps1`

它是无面板兄弟入口，直接跑 launcher（不走 `schtasks`），所以 D3 的修复自动覆盖它。

---

## E. 验证

| 层 | 读数 |
|---|---|
| 单元 | `test_startup_semantics` **61 项**（52 → 61）；启动/面板/运行时组 **285 项** |
| 变异 | 改回裸 `return 0` → 1 项红；去掉忙碌分支 → 1 项红；改回 `SMTO_ABORTIFHUNG` → 1 项红 |
| **端到端（决定性）** | 最小化面板 → 真实双击 → **`iconic=True → False`**、`rect=(-32000,-32000) → (156,101,1532,960)`、`.cmd` 打印「面板已在运行，已切换到它的窗口。」、**exit 0** |

端到端这一次**抓到过两个真 bug**（C2 的 flag、C3 的选窗），两者都只在真实窗口上
才暴露——这正是「完成 = 真实动作 + 真实状态变化」的意义。

---

## F. 未做与遗留（诚实标注）

1. **`--wait` 分支未端到端验证。** 它只在「`--focus` 返回 1（没有面板）」时才走到，
   而那需要先杀掉正在跑的面板——**我没有杀**（会中断进行中的 episode）。它的逻辑
   由单元测试覆盖（超时理由、陈旧 pid 不算已启动），但**没有真机证据**。
2. **无法确定你双击的确切时刻**（在 12:03–20:41 的面板存活期内，还是重启之后）。
   两条已知的静默路径**都已修复**，所以不需要这个答案才能收工——但如实记录。
3. **进程会带着单实例锁长时间存活**（今天 8.5 小时，跨越整机睡眠）。本轮**不修**：
   它要么是「整机睡眠」，要么是「面板周期性阻塞消息循环」（C3），后者是一个独立的
   工作单元（面板等 worker 时阻塞主线程），不该塞进这次修复。
4. 运行中的面板（**PID 11856**）仍是**旧进程代码**。本轮的修复对**下一次双击**生效
   （`--focus` 走数据根的 `tools/panel_window.py`），所以**不需要重启面板**。
5. 新增日志：`learning/control_panel/desktop_focus.log`（记录每次双击的判定原因）。

---

## G. 一句话教训

**「第二次双击」是一个必须被设计的状态，不是可以被忽略的边界。**
把「已经在运行」折叠成 `return 0`（或折叠成 `schtasks` 的一句「成功」），
就等于让操作员唯一能按的那个按钮在最常见的情况下**失效且无提示**——
而且失效时长等于「进程能活多久」，今天那个答案是 8.5 小时。

**另外**：`.NET` 的 `MainWindowHandle`、`SMTO_ABORTIFHUNG`、`EnumWindows` 的第一项,
这三个看起来最顺手的 API **在这台机器上各有一次会把健康面板判成不存在**。
三次都被**真机读数**抓住，一次都没有被单元测试抓住。

---

## H. 落地状态（2026-10-01 21:1x）

**已提交**（本地 `main`，尚未推到 `origin/main`）：

| sha | 内容 |
|---|---|
| `44c04a8` | 第一版，**位置是错的**：机制放在 `control_panel.main()` 的单实例分支（+153/-1），并且**漏提交** `.cmd` 与 `panel_window.py` |
| `1e5c24a` | **本轮的正式版本**：答案移到 `.cmd` 的 `schtasks` 之前；新增 `tools/panel_window.py`；`main()` 改薄委托（141 行 → 35 行）；含本报告 |
| `198fc38` | 记忆同步（`MEMORY.md` + 两份当日日志） |

**pin 已更新**：`tools/repin_production.py --to 1e5c24a` → `RESULT: CLEAN_OUTSIDE_DATA`。
`control_panel.py` 不在 `VERSION_RELEVANT_FILES` 里，但 `Start-Winter-Agent-V2.cmd` 与
`tools/panel_window.py` 必须在这一版上。**不要** repin 到 `198fc38`——那只是记忆。

**推送未完成，原因不是失败，是守卫主动拦截**：

```
active agent      : 9d7dd6eb
REFUSING: a WorkBuddy escalation job is editing this tree right now.
```

`9d7dd6eb` 是**面板运行时真实发起的自我修复 job**
（key `TAP_FOCUSED_TRAINING_CAMP_SHIELD|SEMANTIC_TARGET_NOT_VERIFIED`），`state=WORKING`，
心跳持续刷新（13:09:31 → 13:12:30 UTC）。

**没有用 `--allow-active-agent` 绕过**：该开关的前提是「tree coherent / `check_wiring`
problems: 0」，而本项目当前有 **15 项既有积压**（F 节），条件不满足；且这个守卫是为
2026-09-17「升级 job 的半成品被扫进无关提交、`main` 短暂不一致」那次真实事故加的。
**正确做法是等 job 结束再推**：

```
./.venv/Scripts/python.exe tools/scan_public_repo.py   # 已跑：0 forbidden / 0 secret / 0 pii / 0 gap
./.venv/Scripts/python.exe tools/git_sync.py push
```

收尾时 `git status -sb` 为 `## main...origin/main [ahead 3]`。
