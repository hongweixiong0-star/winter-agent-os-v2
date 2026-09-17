[CmdletBinding()]
param(
    [ValidateSet("gather", "observe")]
    [string]$Mode = "gather"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ConfigPath = Join-Path $ProjectRoot "config\v2.json"
$RuntimePath = Join-Path $ProjectRoot "tools\run_live.py"
# The interpreter must be the one that owns MAA / OpenCV / RapidOCR.  This used
# to point at a generic Codex runtime python that ships numpy and PIL only, so
# the whole launcher ran with "MAA_IMPORT_FAILED:ModuleNotFoundError" (and no
# cv2 at all: winter_agent_v2.matchers imports it at module scope).  Preflight
# below refuses to start rather than let that degrade silently.
$PythonPath = "E:\dongri-mumu-bot\.venv\Scripts\python.exe"
$MuMuPath = "D:\Program Files\Netease\MuMu Player 12\nx_main\MuMuNxMain.exe"
$MuMuManagerPath = "D:\Program Files\Netease\MuMu Player 12\nx_main\MuMuManager.exe"
$LogRoot = Join-Path $ProjectRoot "learning\launcher"
$CaptureRoot = Join-Path $ProjectRoot "dataset\raw\desktop_runtime"

New-Item -ItemType Directory -Force -Path $LogRoot, $CaptureRoot | Out-Null
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogPath = Join-Path $LogRoot "launcher_$Timestamp.log"
Start-Transcript -Path $LogPath | Out-Null

try {
    Write-Host "Winter Agent OS V2" -ForegroundColor Cyan
    Write-Host "正在检查模拟器、游戏与智能体运行环境..."

    if (-not (Test-Path -LiteralPath $ConfigPath)) {
        throw "缺少配置文件：$ConfigPath"
    }
    if (-not (Test-Path -LiteralPath $PythonPath)) {
        throw "缺少 Python 运行环境：$PythonPath"
    }

    # Prove the interpreter before trusting anything it reports afterwards.
    & $PythonPath (Join-Path $ProjectRoot "tools\preflight.py")
    if ($LASTEXITCODE -ne 0) {
        throw "运行环境预检未通过（缺少 MAA / OpenCV / RapidOCR 之一）。已阻止启动：拒绝静默降级到 ADB。"
    }

    $Config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
    $AdbPath = [string]$Config.device.adb_path
    $Serial = [string]$Config.device.serial
    $PackageName = [string]$Config.device.package_name

    if (-not (Test-Path -LiteralPath $AdbPath)) {
        throw "找不到 ADB：$AdbPath"
    }

    & $AdbPath start-server | Out-Null
    & $AdbPath connect $Serial | Out-Null
    $Connected = (& $AdbPath devices) -match "^$([regex]::Escape($Serial))\s+device$"
    if (-not $Connected) {
        if (-not (Test-Path -LiteralPath $MuMuManagerPath) -and -not (Test-Path -LiteralPath $MuMuPath)) {
            throw "模拟器未连接，且找不到 MuMu 启动程序：$MuMuPath"
        }
        Write-Host "MuMu 安卓实例尚未连接，正在启动实例 0..." -ForegroundColor Yellow
        if (Test-Path -LiteralPath $MuMuManagerPath) {
            & $MuMuManagerPath control -v 0 launch -pkg $PackageName | Out-Null
        }
        else {
            Start-Process -FilePath $MuMuPath
        }
        for ($Attempt = 1; $Attempt -le 60; $Attempt++) {
            Start-Sleep -Seconds 2
            & $AdbPath connect $Serial | Out-Null
            $Connected = (& $AdbPath devices) -match "^$([regex]::Escape($Serial))\s+device$"
            if ($Connected) { break }
        }
    }
    if (-not $Connected) {
        throw "等待 MuMu 连接超时。"
    }

    Write-Host "设备已连接，正在打开《无尽冬日》..." -ForegroundColor Green
    & $AdbPath -s $Serial shell monkey -p $PackageName -c android.intent.category.LAUNCHER 1 | Out-Null
    Start-Sleep -Seconds 5

    if ($Mode -eq "observe") {
        $ObservePath = Join-Path $CaptureRoot "observe_$Timestamp.png"
        & $AdbPath -s $Serial shell screencap -p /sdcard/winter_agent_observe.png | Out-Null
        & $AdbPath -s $Serial pull /sdcard/winter_agent_observe.png $ObservePath | Out-Null
        Write-Host "观察截图已保存：$ObservePath" -ForegroundColor Green
    }
    else {
        $RunCapturePath = Join-Path $CaptureRoot $Timestamp
        Write-Host "正在启动 V2 采集主循环..." -ForegroundColor Cyan
        & $PythonPath $RuntimePath --max-actions 12 --goal GATHER_RESOURCE --capture-dir $RunCapturePath
        if ($LASTEXITCODE -ne 0) {
            throw "智能体本轮未通过 Verifier，退出码：$LASTEXITCODE"
        }
        Write-Host "本轮智能体执行完成。" -ForegroundColor Green
    }
}
catch {
    Write-Host "启动失败：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host "日志：$LogPath"
    Read-Host "按回车关闭"
    exit 1
}
finally {
    Stop-Transcript | Out-Null
}

Write-Host "日志：$LogPath"
Read-Host "按回车关闭"
