@echo off
rem ---------------------------------------------------------------------------
rem Winter Agent OS V2 -- production desktop entry point.
rem
rem ENCODING -- read this before editing this file.
rem cmd.exe reads a batch file in the *system OEM codepage* (CP936 on this
rem machine), not in UTF-8.  So keep this file CP936-encoded, and keep every
rem line that decides *control flow* free of non-ASCII.  A UTF-8 file does not
rem fail loudly here: the Chinese bytes of the project path are re-decoded as
rem CP936, which shifts byte alignment and swallows the ASCII byte that follows
rem each Chinese run.  Measured 2026-10-01 09:43 -- as UTF-8 this file lost the
rem closing quote of the project path, the backslash before `.venv`, and the `%`
rem that opened the interpreter variable, so the launcher reported the
rem interpreter missing and the operator's double-click never reached the gate
rem below.  tests/test_startup_semantics.py::LauncherEncodingTest pins this.
rem
rem The root is `%~dp0` (where this file is), not a literal path.  A literal would
rem put the project's Chinese path into executable lines -- the lines the codepage
rem can corrupt -- and duplication is what drifts.  `%~dp0` is expanded by cmd
rem from the command line in UTF-16, so it is correct no matter how this file is
rem encoded.
rem
rem This used to launch the panel from a script that did not run preflight, so a
rem wrong interpreter reached production unnoticed: on 2026-09-17 the panel was
rem running on a generic runtime python without maa/cv2, the worker inherited it,
rem and every skill promoted to MAA silently fell back to ADB capture -- 324 ms
rem against 8.92 ms, measured live.  The interpreter below is the one
rem tools/preflight.py proves; a preflight failure stops the launch instead of
rem degrading it.  Override with config/v2.json -> runtime.python_path.
rem ---------------------------------------------------------------------------

set "WINTER_ROOT=%~dp0"
cd /d "%WINTER_ROOT%"

set "WINTER_PYTHON=%WINTER_ROOT%.venv\Scripts\python.exe"
set "WINTER_PYTHONW=%WINTER_ROOT%.venv\Scripts\pythonw.exe"
set "WINTER_FOCUS_LOG=%WINTER_ROOT%learning\control_panel\desktop_focus.log"

if not exist "%WINTER_PYTHONW%" (
    echo [Winter Agent OS V2] 找不到生产解释器： %WINTER_PYTHONW%
    echo 诊断： python tools\preflight.py
    echo 修复： 在 config\v2.json 的 runtime.python_path 指定可用解释器。
    pause
    exit /b 1
)

rem --launch-gate, not the default: preflight answers two questions and one exit code
rem cannot carry both.  This launcher is the gate for *opening the window*, so it asks
rem the window's question -- can this interpreter run production -- and refuses on that.
rem The device is deliberately not part of it.  A stopped emulator or a game that is not
rem in the foreground is repaired by control_panel._ensure_device, which launches MuMu and
rem foregrounds the client and is itself wrapped in a bounded retry loop; gating the
rem window on it means the window cannot open in the one situation where the window is
rem the fix.  Measured 2026-10-01 07:26: the emulator was up, on the Android launcher,
rem with com.gof.china not running -- preflight called that a core blocker, this script
rem refused to launch on it, and AUTO was never started, so _ensure_device was never
rem reached.  A wrong interpreter is different in kind: the panel and the worker it
rem spawns both inherit it, so nothing inside the process can change it, and on
rem 2026-09-17 exactly that ran a whole session with MAA_IMPORT_FAILED and every
rem promoted skill quietly on ADB at 324 ms against MAA's 8.92 ms.
"%WINTER_PYTHON%" "tools\preflight.py" --launch-gate
if errorlevel 1 (
    echo.
    echo [Winter Agent OS V2] 运行环境预检未通过，已阻止启动。
    echo 解释器不可用： 面板与它派生的 worker 会继承同一个解释器，进程内无法自愈。
    echo 设备类问题（模拟器未启动 / 游戏未在前台）不阻止开窗 —— 面板会启动它们。
    echo 诊断： python tools\preflight.py
    echo 修复： 在 config\v2.json 的 runtime.python_path 指定可用解释器。
    pause
    exit /b 1
)

rem The acceptance soak is measured by the window, so the window has to be able to say which
rem launch path it came from (P0 2026-09-18 §三).  A GUI started by a development tool cannot
rem be kept alive -- that host reaps its children when its call ends, measured on panels
rem 24936/25408 -- so a soak from one is recorded as DEVELOPMENT_ENV_LIMITATION rather than
rem counted as evidence.  This marker is that declaration; it is inherited by the child.
set "WINTER_AGENT_LAUNCH_PATH=desktop"

rem ---------------------------------------------------------------------------
rem A second double-click has to produce something visible.
rem
rem The scheduled task is registered with MultipleInstancesPolicy=IgnoreNew, so once
rem a panel is running `schtasks /Run` starts *nothing*: it answers 正在运行 and still
rem exits 0.  "The panel is already up" and "the shortcut is broken" therefore look
rem identical to the operator.  Measured 2026-10-01: the panel was alive but wrote
rem nothing from 12:03:42 until the machine rebooted at 20:41, and every double-click
rem in those 8.5 hours opened nothing at all.  So ask tools\panel_window.py first --
rem if a panel is running, raise its window; if none is, fall through and start one.
rem ---------------------------------------------------------------------------
"%WINTER_PYTHON%" "tools\panel_window.py" --focus >> "%WINTER_FOCUS_LOG%" 2>&1
if errorlevel 2 goto :panel_unavailable
if errorlevel 1 goto :start_panel
echo [Winter Agent OS V2] 面板已在运行，已切换到它的窗口。
exit /b 0

:panel_unavailable
echo.
echo [Winter Agent OS V2] 已经有一个面板进程在运行，但它的窗口无法显示。
echo 原因见： learning\control_panel\desktop_focus.log
echo 请在任务管理器中结束该面板进程后重新双击；如果它已经卡住，重启计算机最干净。
pause
exit /b 1

:start_panel
rem Task Scheduler owns the interactive process so it survives the short-lived
rem desktop launcher.  Its pythonw action runs launch_pinned_production.py, which
rem records startup exceptions in learning\control_panel\desktop_startup.log.
schtasks /Run /TN "WinterAgentV2Panel"
if errorlevel 1 (
    echo [Winter Agent OS V2] Panel launch failed. See learning\control_panel\desktop_startup.log.
    pause
    exit /b 1
)

rem schtasks exits 0 both when it started the task and when it ignored the request
rem because another instance was still registered -- it cannot tell us which.  A
rem window that never appears can, and that is the difference between "nothing
rem happened" and a sentence the operator can act on.
"%WINTER_PYTHON%" "tools\panel_window.py" --wait 30 >> "%WINTER_FOCUS_LOG%" 2>&1
if errorlevel 1 (
    echo.
    echo [Winter Agent OS V2] 计划任务已被触发，但 30 秒内没有面板窗口出现。
    echo 原因见： learning\control_panel\desktop_focus.log
    echo 常见原因：任务仍停留在「正在运行」（进程已死但任务实例未结束）。
    echo 处理：在任务管理器中结束残留的 pythonw.exe，或重启计算机后重试。
    pause
    exit /b 1
)
