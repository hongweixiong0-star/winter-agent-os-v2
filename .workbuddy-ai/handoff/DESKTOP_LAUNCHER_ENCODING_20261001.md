# 桌面入口「双击启动」失败 —— 批处理文件编码

- 日期：2026-10-01（09:42–10:05）
- 触发：操作员「双击启动还是报错」
- 提交：`d758c1e`（pin `d910394` → `d758c1e`，`CLEAN_OUTSIDE_DATA`）
- 定性：**不是**闸门语义问题（上午那个已修且在跑），而是**批处理文件的字节编码**问题。
  同一个文件上的第二个、彼此独立的缺陷。

---

## A. 一句话结论

桌面快捷方式指向 `E:\无尽冬日智能体\Start-Winter-Agent-V2.cmd`，而该文件是 **UTF-8**、
`cmd.exe` 却一律按**系统 OEM 代码页（本机 936）**解码整份文件。中文路径的 UTF-8 字节被按
CP936 错位配对后，会**吞掉紧随其后的那个 ASCII 字节** —— 于是 `cd /d "…"` 的收尾引号、
路径里的 `\`、以及 `%WINTER_PYTHONW%` 前的 `%` 全被吞掉，脚本在**闸门之前**就退出。

**它从 2026-09-20（`7c5bca6`）起就是坏的，共 11 天**；之所以没人追，是因为面板有**第二条
入口**（计划任务直接跑 `launch_pinned_production.py`），那条一直在工作。

---

## B. 现象与最小复现

操作员看到的原文（用 `< /dev/null` 重现，按 CP936 解码）：

```
文件名、目录名或卷标语法不正确。
[Winter Agent OS V2] 找不到生产解释器：%WINTER_PYTHONW
诊断：python tools\preflight.py
修复：在 config\v2.json 的 runtime.python_path 指定可用解释器。
请按任意键继续. . .
```

即第 15 行 `cd /d` 就失败了，第 20 行的 `if not exist` 随后判定解释器不存在。
**注意这句话本身是误导的**：解释器一直在，是脚本读不懂自己的路径。

最小复现（同一段内容、只改编码）：

| 编码 | `cd /d "E:\无尽冬日智能体"` | `set` 出的路径 | `if exist` |
|---|---|---|---|
| UTF-8 | `文件名、目录名或卷标语法不正确。`（errorlevel=1） | `E:\鏃犲敖鍐棩鏅鸿兘浣揬.venv\...`（`\` 被吞） | **MISSING** |
| CP936 | 正常（errorlevel=0） | `E:\无尽冬日智能体\.venv\...` | EXISTS |

同一个探针在 PowerShell 上复现（PowerShell 5.1 对**无 BOM** 的脚本用同一个 ANSI 代码页）：

| `.ps1` 编码 | 解析出的路径 | `Test-Path` |
|---|---|---|
| UTF-8 无 BOM | `E:\鏃犲敖鍐棩鏅鸿兘浣揬.venv\...` | **False** |
| UTF-8 带 BOM | 正确 | True |
| CP936 | 正确 | True |

---

## C. 机制：不是"乱码"，是**错位吞字节**

`cmd.exe` 不支持 BOM、也不嗅探编码，逐字节按 OEM 代码页解码。CP936 的首字节范围是
`0x81–0xFE`、尾字节是 `0x40–0x7E` 与 `0x80–0xFE`。中文 UTF-8 是 3 字节一组，按 CP936 两两配对后
**总余出一个字节**，它会去吃掉后面的 ASCII 字节。所以在真实文件里同时发生三件事：

1. `cd /d "E:\无尽冬日智能体"` —— 末字 `体` = `E4 BD 93`，剩下 `93` 与收尾 `"`(`22`) 配成一个
   CJK 字符 ⇒ **引号被吞** ⇒ 字符串未闭合 ⇒ 报的是"语法不正确"而**不是**"找不到路径"
   （这就是为什么错误信息看起来不像路径问题）。
2. `set "WINTER_PYTHONW=E:\无尽冬日智能体\.venv\..."` —— `体` 与 `\`(`5C`) 配对 ⇒ **反斜杠被吞**
   ⇒ 路径变成 `…浣揬.venv\…` ⇒ `if not exist` 判定"找不到生产解释器"。
3. `echo …找不到生产解释器：%WINTER_PYTHONW%` —— 全角冒号 `：` = `EF BC 9A`，剩 `9A` 吃掉 `%`
   ⇒ 变量不展开 ⇒ 打印出**字面量变量名** `%WINTER_PYTHONW%`。

三处症状都是同一个机制。**反向结论很重要：这类失败不会自己喊出来** —— 它输出的是"看起来很
合理的错误"，而错误内容恰好指错了地方。

---

## D. 精确引入日期：`7c5bca6`（2026-09-20 10:02）

不是"一直如此"，也不是我上午改坏的。逐提交取证：

| 提交 | 日期 | `WINTER_PYTHONW` 指向 | 守卫能否通过 |
|---|---|---|---|
| `f9ef073` | 2026-09-14 | 无守卫（只有 `cd /d` 与 `start <绝对路径>`） | 不适用；`cd` 失败被忽略，`start` 用绝对路径，所以"能用" |
| `f49566b` | 2026-09-17 | `E:\dongri-mumu-bot\.venv\Scripts\pythonw.exe`（**纯 ASCII**） | **能** |
| **`7c5bca6`** | **2026-09-20** | `E:\无尽冬日智能体\.venv\Scripts\pythonw.exe`（**中文路径**） | **不能 ⇒ 每次双击死在闸门之前** |
| `0eca611` | 2026-09-30 | 同上（数据根恢复） | 不能 |
| `783a219` | 2026-10-01 | 同上 | 不能 |

`f49566b` 的 commit 信息是"the production entry ran on an interpreter that had no MAA" —— 它加的
守卫本身是对的，只是当时路径还是 ASCII。`7c5bca6`（"V2 runs on its own venv"）把解释器挪进项目
自己的中文目录，**把一个正确的守卫变成了每次都失败**。

**旁证（同一天的历史记录）**：`2026-09-27.md` 已经写着"若再双击失败：cmd 里跑
Start-Winter-Agent-V2.cmd 看报错，**或直接 schtasks /Run**"。也就是说当时已经改用替代路径绕过，
只是没人把"双击失败"当成一个待修的缺陷。

---

## E. 为什么 11 天没人发现：两条入口互相掩盖

面板有两条入口，行为不同：

1. **桌面快捷方式** → `Start-Winter-Agent-V2.cmd`（闸门 + `schtasks /Run`）—— **坏的**。
2. **计划任务 `WinterAgentV2Panel`** → 直接 `pythonw launch_pinned_production.py` —— **好的**。

于是每一轮"把面板拉起来"的动作只要走 ②，系统看起来完全正常：`desktop_startup.log` 有记录、
`panel.log` 在滚、`auto_uptime.jsonl` 在长。而 ① 死了 11 天没有任何人收到信号：
`schtasks` 的上次结果只会显示 `1`，不会说是谁把它跑成 1 的。

对照上午那个缺陷：上午是**两个文件对同一个退出码有两种理解**（`.cmd` 与 `preflight.py` 静默不一致）；
这次是**两个入口对同一件事有两种可达性**（`.cmd` 死了、计划任务活着）。共同点仍然是：
**没有任何测试看得见"操作员实际按的那个东西"**。

---

## F. 修复：两条互相独立的防线

单靠"记住编码规则"是不够的 —— 默认写文件的工具（包括我这轮的 `Edit`）都会写成 UTF-8 无 BOM，
这正是它复发的方式。所以同时做两件事：

**① 编码迁就读者**

- `Start-Winter-Agent-V2.cmd` → **CP936**，无 BOM（`cmd.exe` 不支持 BOM）。
- `Start-Winter-Agent-V2.ps1` → **UTF-8 带 BOM**（5.1 认 BOM；不带就被当 ANSI）。

**② 让控制流不依赖编码（这才是结构性修复）**

- `.cmd` 里**所有决定控制流的行都是纯 ASCII**：根目录改成 `set "WINTER_ROOT=%~dp0"`。
  `%~dp0` 由 cmd 从**命令行**以 UTF-16 展开，项目的中文路径**根本不进入文件的字节**。
  中文只允许留在 `rem` 与 `echo` 里。
- `.ps1` 的 `$PythonPath` 改成 `Join-Path $ProjectRoot ".venv\Scripts\python.exe"`，同理。

这样即使将来有人把文件重新存成 UTF-8，**后果降级为"消息变乱码"，而不再"启动不了"**。

顺带修正：`.cmd` 失败文案里"找不到生产解释器"现在会**正确展开**真实尝试路径（因为 `%` 不再被吞），
并且明确写出设备类问题不阻止开窗。

---

## G. 验证（分层，全部真实读数）

**① 最小复现 A/B**：同一内容 UTF-8 vs CP936，见 §B 表 —— 机制确认。

**② 真跑操作员的那条路径**（不是代理物）：

```
09:45:45  cmd /c Start-Winter-Agent-V2.cmd   → exit 0
           VERDICT: PASS - the window may open
           成功: 尝试运行 "WinterAgentV2Panel"。
09:45:47  desktop_startup.log 新增一条 CODE_COMMIT=d9103948… WORKTREE_CLEAN=true
09:46:13  panel.pid = 22556（新面板进程）
09:46:56  预检·核心：Runtime OK · MuMu OK (127.0.0.1:7555 [720,1280] 前台 com.gof.china)
09:46:56  自动运行已启动
09:49:36  ⚠ 本轮结束：已切换到角色 1061663148
01:50:24Z auto_uptime: ROLE_SWITCHED_TO:1061663148 healthy=True exec=5 ver=4
```

`%~dp0` / `cd /d` / `set` / `if exist` 全部正常 —— preflight 能被跑起来本身就是这条链通的证据。

**③ PowerShell 侧不跑端到端**（跑 `.ps1` 会起第二个 `run_live` 与面板抢设备租约），
改用真实文件解析验证：`Parser::ParseFile` → **0 解析错误**，四个路径赋值全是 `Join-Path`/`Split-Path`，
解析结果 `E:\无尽冬日智能体\.venv\Scripts\python.exe`、`Test-Path` = True。

**④ 反回归 + 变异验证**：`LauncherEncodingTest` 6 项。把两个文件的编码改回坏版本 →
**6 项中 5 项变红**（第 6 项断言"规则写进了文件自身"，按构造在改编码后仍为绿）；恢复后两文件 md5 逐字节一致。

**⑤ git 往返安全性**：`core.autocrlf=true`，所以仓库 blob 是 LF、工作树是 CRLF —— 但
`git show HEAD:Start-Winter-Agent-V2.cmd` **仍能按 CP936 解码**、`.ps1` blob 仍带 BOM。
**pin 树的检出文件与开发树逐字节一致**（`md5 d177d351e6cc` / `6ea7e41fde8d`，两份相同），
所以 repin 不会再把坏文件带回来。

**⑥ 重复双击的行为**（我特意查了，因为它会直接影响操作员）：
任务已在运行时 `schtasks /Run` 返回 **errorlevel 0** 并打印「信息: 计划任务 … 正在运行」+
「成功: 尝试运行」，`上次结果=267009 (0x41301)`。所以**不会出现假失败**，`if errorlevel 1` 分支
不会被误触发，无需为"面板已在运行"增加特判。

**测试计数**：`test_startup_semantics` 39（33 → 39），启动/面板/运行时组合 **272 passed**。

---

## H. 未做与遗留（诚实标注）

1. `out/index_verify_daily_20260928/Start-Winter-Agent-V2.{cmd,ps1}` 是**导出目录里的历史副本**，
   同样是 UTF-8 中文路径、同样坏。它们是快照产物不是活体入口，**本轮未动**；
   若要清理请另起一个工作单元。
2. `.workbuddy-ai/handoff/01_CURRENT_TRUTH.md` 与 `02_CURRENT_PROGRESS.md` 在工作树里处于
   **未提交的修改中状态**（324 行 / 16 行差异），**不是本轮所写**，我没有把它们并进本轮的提交。
3. `tools/check_wiring.py` 的 15 项 problems 仍是本日之前的积压（上午已逐条归因），本轮未动。
4. 本轮**没有**动第二 Scheduler / Executor / WorldState / Runtime Model —— 只改了入口脚本的字节
   与路径推导方式。

---

## I. 一句话教训

**"乱码"只是表象，真正的伤害是错位吞字节 —— 而它输出的错误信息会把你指向错误的地方。**
入口脚本的编码不是洁癖，是它能否被它的读者读懂；而"读者是谁"必须写进测试，
因为脚本不被任何模块 import，纯函数测试永远看不见它。
