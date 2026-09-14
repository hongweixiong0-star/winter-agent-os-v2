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

## 工具优先（HARD RULE，2026-09-14）
- **先找工具，再写代码。** 任何任务开工前先读 `docs/AVAILABLE_TOOLING.md`，并在汇报里给出
  TOOL CHECK 五行：`AVAILABLE_TOOLS / BEST_EXISTING_TOOL / EXISTING_IMPLEMENTATION /
  WHY_NOT_USE_EXISTING_TOOL / CUSTOM_CODE_NEEDED`。解释不了"成熟工具为何不够"就不许自研底层。
- **MaaFw 5.12.3 早已装在项目 venv 里并可用**，却长期没被用过。涉及截图 / 按钮与页签定位 /
  模板 / OCR / ROI / 点击 / 滑动 / 等待页面 / 等待消失 / 重试 / UI 恢复，**先评估 MAA**。
- 分层固定：**V2 = Brain/Goal/Strategy/WorldState/Knowledge/Verifier；MAA = 取帧/识别/UI 动作/等待/重试；
  ADB = 设备层 + fallback；Verifier = 唯一事实裁判**（MAA 返回 SUCCESS ≠ Skill 成功）。
- 两个轴分开决策（真机 20 次实测）：**取帧 MAA 8.92ms vs ADB 324ms（36.3×）→ 已切；
  识别 MAA 113ms vs 旧 V2 34.5ms（都 20/20 命中、中心差 0.3px）→ 逐语义按证据迁**，不伪造"更优"。
- 提升某 skill 到 MAA **必须同时写入 evidence**（`knowledge/execution/backend_routing.json`）。
- 止损：单个 UI 元素 15 分钟；单个 Skill/Failure/Goal 90 分钟内必须拿到「成功率改善 / Root Cause /
  具体 Blocker / 证明方案错误」之一；单个变体持续失败就标 PARTIAL/DEGRADED 并登记，不阻塞全局。
- 旧模板只能当 Candidate：必须来自独立真机帧、带正负样本、阈值标定、页面上下文。
  **禁止模板自己裁自己再自匹配**（d=0 是循环论证，曾骗过三次真机运行）。
- **识别节点的提升闸门：正样本 ≥3 张独立真机帧、负样本 ≥3 张**。少于这个就输出
  `PROMOTION BLOCKED`。曾用 1 张正样本提升 `OPEN_INTEL` 的节点，第一次真机就回归
  （找对位置但相关性 0.448 < 阈值 0.7，因为按钮是动画的），已回滚为 HYBRID。
- **哈希距离的容差不能搬到模板匹配阈值上**。旧语义为动画控件放宽过容差（如
  `BTN_OPEN_INTEL_WILD_HUD` max_distance 24），迁移时必须重新标定，不能沿用默认 0.7。



## 环境
- **入口**：先读 `START_HERE.md`（根目录）。它会指向 `.workbuddy-ai/handoff/`。
- 跨账号接力：`python tools/update_workbuddy_handoff.py` 从真实项目重算 handoff；
  `tools/verify_handoff.py` 校验其结构不变量。
- **项目已有 git 仓库**（2026-09-14 建立），checkpoint 用
  `python tools/update_workbuddy_handoff.py --checkpoint -m "..."`。
- **Bash 工具没有 coreutils**：`ls/cat/head/tail/sleep/wc/date` 全部不可用；
  **PowerShell 工具 stdout 不回传**。所有命令用
  `"E:/dongri-mumu-bot/.venv/Scripts/python.exe" -c "..." > out.txt 2>&1` 再用 Read 读。
- 跑项目脚本/测试必须用项目 venv：`E:\dongri-mumu-bot\.venv\Scripts\python.exe`
  （含 PIL / rapidocr）。托管 Python 3.13 **没有 PIL**，系统 Python 3.12 也不完整。
- OCR 运行时装在 `E:\dongri-mumu-bot\.venv`，通过 module_path 引用，不 import 其项目代码。
- MuMu 默认**不启动**。启动：
  `MuMuManager.exe control -v 0 launch -pkg com.gof.china` → `adb connect 127.0.0.1:7555`。
  真机 720×1280，前台包 `com.gof.china`。
- 启动入口：`Start-Winter-Agent-V2.cmd` / 桌面上 `Winter Agent OS V2.lnk`。

## 稳定偏好（用户）
- 要求“不虚报”：宁可标 CANDIDATE / UNKNOWN / 0，也不把未验证的东西写成成功。
- 报告要区分 LIVE_CLIENT / HISTORY·仅参考 / PRIOR / SIMULATION。
- 不要每完成一步就停下来问；自动继续下一最高价值任务。
- 清理文件必须先列清单逐项确认，禁止按前缀/通配符批量删除（已付出过代价）。
