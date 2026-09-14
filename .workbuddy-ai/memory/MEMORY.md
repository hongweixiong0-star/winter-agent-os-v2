# 项目记忆 — 无尽冬日智能体 / Winter Agent OS V2

## 定位
《无尽冬日》(Whiteout Survival) 国服客户端的截图驱动自动化 Agent。MuMu 模拟器 + ADB，分辨率 720×1280，
包名 `com.gof.china`。V2 完全独立，不 import 任何 legacy Agent/Brain/Scheduler/Vision 代码。

## 项目约定（修改代码前必读）
- **只有一个** Scheduler、SkillRegistry、WorldState、Executor 边界、Episode 流。新增功能不得再造第二个。
- Vision 是 Template-first；OCR 仅用于 UNKNOWN 或明确缺失的结构化字段，角色是 `TEXT_RECOGNITION_ONLY`。
- `RuleBrain` 决定 WHAT，Skill 定义 HOW，Vision 和 Qwen 永不点击。
- 运行态真相源唯一：`learning/runtime_snapshot.json`。GUI 只读、不写业务状态。
- 任何真实成功都必须有 live 状态变化 + Vision + Verifier 证据。Replay 一律标 `SIMULATION`。
- 禁止把 “代码存在” 或 “单次成功” 当作 `STABLE`；当前 STABLE=0 是刻意的。
- 外部项目（wos/bot/wosbot/autopilot）只能 `REFERENCE_ONLY`，不得复制代码/坐标/截图/图标/账号数据。
- 真实支付、账号/角色删除、账号安全变更、系统危险操作永久阻断。
- 历史失败 Episode 不得篡改。
- 证据链：`external → raw → normalized → candidate → verified → production`。

## 环境
- 跑测试用系统 Python 3.12：`C:/Users/xhw/AppData/Local/Programs/Python/Python312/python.exe -m pytest tests -q`
  （托管 Python 3.13 未装 pytest/PIL，会直接报 No module named pytest）
- 项目**没有 git 仓库**，改动不可回滚，动手前先备份。
- OCR 运行时装在 `E:\dongri-mumu-bot\.venv`，通过 module_path 引用，不 import 其项目代码。
- 启动入口：`Start-Winter-Agent-V2.cmd` / 桌面上 `Winter Agent OS V2.lnk`。

## 稳定偏好（用户）
- 要求“不虚报”：宁可标 CANDIDATE / UNKNOWN / 0，也不把未验证的东西写成成功。
- 报告要区分 LIVE_CLIENT / HISTORY·仅参考 / PRIOR / SIMULATION。
