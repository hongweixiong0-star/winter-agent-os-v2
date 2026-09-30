@echo off
rem ---------------------------------------------------------------------------
rem Winter Agent OS V2 -- production desktop entry point.
rem
rem This used to launch the panel from a script that did not run preflight, so a
rem wrong interpreter reached production unnoticed: on 2026-09-17 the panel was
rem running on a generic runtime python without maa/cv2, the worker inherited it
rem ("PYTHON_PATH = Path(sys.executable).with_name("python.exe")"), and every
rem skill promoted to MAA silently fell back to ADB capture -- 324 ms against
rem 8.92 ms, measured live.  The interpreter below is the one
rem tools/preflight.py proves; a preflight failure now stops the launch instead
rem of degrading it.  Override with config/v2.json -> runtime.python_path if the
rem environment moves.
rem ---------------------------------------------------------------------------
cd /d "E:\无尽冬日智能体"

set "WINTER_PYTHON=E:\无尽冬日智能体\.venv\Scripts\python.exe"
set "WINTER_PYTHONW=E:\无尽冬日智能体\.venv\Scripts\pythonw.exe"

if not exist "%WINTER_PYTHONW%" (
    echo [Winter Agent OS V2] 找不到生产解释器：%WINTER_PYTHONW%
    echo 诊断：python tools\preflight.py
    echo 修复：在 config\v2.json 的 runtime.python_path 指定可用解释器。
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
    echo 解释器不可用：面板与它派生的 worker 会继承同一个解释器，进程内无法自愈。
    echo 设备类问题（模拟器未启动 / 游戏未在前台）不阻止开窗 —— 面板会启动它们。
    echo 诊断：python tools\preflight.py
    echo 修复：在 config\v2.json 的 runtime.python_path 指定可用解释器。
    pause
    exit /b 1
)

rem The acceptance soak is measured by the window, so the window has to be able to say which
rem launch path it came from (P0 2026-09-18 §三).  A GUI started by a development tool cannot
rem be kept alive -- that host reaps its children when its call ends, measured on panels
rem 24936/25408 -- so a soak from one is recorded as DEVELOPMENT_ENV_LIMITATION rather than
rem counted as evidence.  This marker is that declaration; it is inherited by the child.
set "WINTER_AGENT_LAUNCH_PATH=desktop"

rem Task Scheduler owns the interactive process so it survives the short-lived
rem desktop launcher.  Its pythonw action runs launch_panel_logged.py, which
rem records startup exceptions in learning\control_panel\desktop_startup.log.
schtasks /Run /TN "WinterAgentV2Panel"
if errorlevel 1 (
    echo [Winter Agent OS V2] Panel launch failed. See learning\control_panel\desktop_startup.log.
    pause
    exit /b 1
)
