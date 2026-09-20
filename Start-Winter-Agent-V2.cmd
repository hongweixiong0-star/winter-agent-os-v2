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

"%WINTER_PYTHON%" "tools\preflight.py"
if errorlevel 1 (
    echo.
    echo [Winter Agent OS V2] 运行环境预检未通过，已阻止启动。
    echo 不在缺少 MAA / OpenCV / RapidOCR 的解释器上静默降级运行。
    pause
    exit /b 1
)

rem The acceptance soak is measured by the window, so the window has to be able to say which
rem launch path it came from (P0 2026-09-18 §三).  A GUI started by a development tool cannot
rem be kept alive -- that host reaps its children when its call ends, measured on panels
rem 24936/25408 -- so a soak from one is recorded as DEVELOPMENT_ENV_LIMITATION rather than
rem counted as evidence.  This marker is that declaration; it is inherited by the child.
set "WINTER_AGENT_LAUNCH_PATH=desktop"

start "Winter Agent OS V2" "%WINTER_PYTHONW%" "E:\无尽冬日智能体\tools\control_panel.py"
