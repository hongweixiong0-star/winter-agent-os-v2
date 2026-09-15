# 情报循环自动化 — 执行记录

## 2026-09-15 00:01 (GMT+8) / 2026-09-14T16:01Z — 首次运行

**前置**：MuMu 已连接（已 connected，未走 launch 分支）；前台 `com.gof.china`，720×1280。

**执行**：`tools/run_intel_loop.py 6`（项目 venv）。3 轮后脚本自行停止。
**结果**：全部 `intel_not_available`，exit 0；dispatches 0 / claims 0；体力板读数 162 未变。
**判定**：按任务规则属正常终态，本次结束，未重试。

**重要副产**：本次顺带用生产视觉 + OCR 全量文本做了一次对照验证，证伪了
`intel_not_available` 的判据——"只有表头 ⇒ 空列表"不成立，一个有真实可派任务的历史帧
OCR 文本结构与本次**完全相同**（都没有 `前往查看`）。结论：**该 stop_reason 不可作为
"情报板已空"的证据**，会静默掩盖"有任务但模板层漏检"。详见
`.workbuddy-ai/memory/MEMORY.md`；当日流水见 `.workbuddy/memory/2026-09-15.md`。
未改代码（无人值守 + 项目提升闸门要求 ≥3 正 ≥3 负样本）。

**下一轮注意**：
- 要确认情报板真空，用 `tools/run_intel_pins.py` 的逐 pin `card_opened/productive` 证据。
- 下一次情报刷新约 2026-09-15 07:59 (GMT+8) / 23:59 UTC。
- `runtime_snapshot.json`：`agent_state=DEGRADED`、`unexpected_worker_exits=15`、
  `watchdog_restart_count=13`（既有计数，未清零）。

## 2026-09-15 01:10 (GMT+8) / 2026-09-14T17:10Z — 第 2 次运行

**前置**：MuMu 已 connected（未走 launch 分支）；前台 `com.gof.china`，720×1280。

**⚠️ 任务书前提被推翻**：`run_intel_loop.py 6` 又是 3 轮 `intel_not_available` / exit 0 /
steps 1 / dispatches 0 / claims 0（13.5 min，含 2×120s sleep）。
但**本次连拍的 3 张 frame 全是满板 8 pin 的情报地图**（体力 175、`下次刷新:06:49:22`）——
即该 stop_reason **又一次假阴性**，"报它就=板已排空"**不成立**（与 00:01 那次同源）。
任务书自带前提"列表**确**为空"未满足，故未按终态收尾。

**改走对的工具，拿到真实产出**：`tools/run_intel_pins.py 8`（13m23s，EXIT=0）
→ 8/8 pin `card_opened=true`；**派兵 3**（`DISPATCH_INTEL_BEAST`）+
**英雄之旅 2**（`INTEL_HERO_DISPATCH`）+ **领取 7**（`INTEL_CLAIM_REWARDS`，全部 verifier ok）；
**体力 176 → 107（净 −69）**；非产出 3 pin（pin_00 营救 `INTEL_RESCUE_START_NOT_PROVEN`、
pin_02 无动作、pin_04 `INTEL_BEAST_MARCH_NOT_PROVEN`，均 exit2 如实记录）。
证据：`evidence/intel_pins_20260914_171640.json`。收尾帧干净（情报页、体力 107、余 5 pin、无弹窗）。

**根因**：情报页是 **pin 地图**，任务卡只在点开 pin 后出现；模板按"单卡"标定 → 地图必漏检
→ `ocr.py` 的 `has_header ⇒ NOT_AVAILABLE` 回落把"有任务"错报成"无任务"并 exit 0。
`winter_agent_v2/intel_pins.py::intel_pin_centers()` 没接进生产 vision 路径。
未改代码（无人值守 + 负样本未确立，仍 PROMOTION BLOCKED）。

**下一轮（重要）**：
1. **不要再以 `run_intel_loop.py` 作为情报任务的主入口**——pin 地图上它注定空转。
   直接跑 `tools/run_intel_pins.py <budget>`；本轮预算 8 用满即停，余 5 pin。
2. 记账只采信**情报页表头**体力读数；nav cycle 的 16 / 36 是 HUD 浮层误读，不入账。
3. 自动化任务书里"`intel_not_available` = 正常终态"这句需要改掉（建议改为"逐 pin 无
   `card_opened/productive` 才算排空"）。
4. 刷新计时：收尾帧 `下次刷新 06:29:44` ⇒ 约 2026-09-15 08:00 (GMT+8)。
5. `runtime_snapshot.json` 计数未动：`unexpected_worker_exits=15`、`watchdog_restart_count=13`。

## 2026-09-15 06:33 (GMT+8) / 2026-09-14T22:33Z — 第 3 次运行（首次有真实产出）

**前置**：已 connected（未走 launch）；前台 `com.gof.china`，720×1280。起始板 6 pin、体力 **168**。

**① `run_intel_loop.py 6`（任务书指定的入口）第 3 次空转**：3 轮 `intel_not_available` /
exit 0 / dispatches 0 / claims 0，4m32s —— 同一时刻连拍帧是满板 6 pin，**又是假阴性**。

**② 改跑 `tools/run_intel_pins.py 8`（对 pin 地图唯一对的入口）**：EXIT=0，6m31s，
pins 4/4 `card_opened=true`，4 条 per_pin + 1 nav cycle：
**派兵 3**（`DISPATCH_INTEL_BEAST`×2 + `INTEL_HERO_DISPATCH`×1）、**营救 1**（`EXECUTE_INTEL_RESCUE_SURVIVORS`）、
**领取 4**（`INTEL_CLAIM_REWARDS`，全部 verifier ok）；**体力 169→157→147→138→128，净 −41**；
1 条失败如实记录（pin_00 橙·帐篷 `INTEL_BEAST_TARGET_NOT_PROVEN` exit2）。
证据：`evidence/intel_pins_20260914_223903.json`。

**③ 新发现（值得下一轮用）**：`intel_pin_centers()` 的长宽比闸门 `w/h>=0.65` 漏掉**带光晕的橙 pin**
（实测 `ratio 0.64`，光晕把 blob 拉长到 h=136）⇒ 收尾时检测器报 0 pin 而板上还有 1 个。
即 **"no actionable pins left" 也不等于板空**。已手工点开该 pin 验证：是「大师悬赏：20号」，
`status=BLOCKED`（推荐战力 189M），brain 走 BACK，**未花体力、无奖励可领** ⇒
本次是**有证据的终态**（点开→BLOCKED→BACK），不是靠表头文字推的。收尾帧干净（情报页、体力 128、
`下次刷新 01:13:03`、无弹窗）；snapshot 计数未清零（15 / 13）。

**下一轮（重要）**：
1. 任务书里"`intel_not_available` = 正常终态"**必须改掉**；入口直接写
   `tools/run_intel_pins.py <budget>`，终态判定改成"逐 pin 点开均无动作且 pin 检测为 0（需人工复核）"。
2. 修 `intel_pin_centers()` 的 `0.65` 下限（→ ~0.5，或剥离光晕）；本轮+昨天已有 ≥3 正样本，
   仍缺"真空板"负样本，补齐前按项目闸门不改代码。
3. 大师悬赏 20 号（189M 战力）会长期占位，**不要当失败反复重试**。
4. 持久化事实已写入 `.workbuddy-ai/memory/MEMORY.md` 与 `.workbuddy/memory/2026-09-15.md`。
