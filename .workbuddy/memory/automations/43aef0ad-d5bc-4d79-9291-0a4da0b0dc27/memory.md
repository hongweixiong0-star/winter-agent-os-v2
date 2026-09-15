# 自动化执行记录 — 情报（Intel）无人值守 pin 循环

## 2026-09-15 17:20 GMT+8（本 id 第 1 次实跑）
- 工具：`tools/run_intel_pins.py 6`（**未**使用 `run_intel_loop.py`，后者对 pin 地图是错工具）。
- 设备：MuMu 已在线（`127.0.0.1:7555`），**无需启动流程**。前置探针确认客户端就在情报页
  （`Page.INTEL` 0.99 / `CLAIMABLE` / 体力 194 / 无游离模态）——上两轮栽的"模态挡路"本轮不存在。
- 结果：`pins_processed=3 / pins_skipped=0`，exit 0，耗时 17 分钟。
  真实产出（全部 verifier ok）：`DISPATCH_INTEL_BEAST`×4、`INTEL_HERO_DISPATCH`×4、
  `EXECUTE_INTEL_RESCUE_SURVIVORS`×1、`INTEL_CLAIM_REWARDS`×10。共 81 个 episode，仅 3 个 FAILURE。
- 体力：情报页表头 **194 → 105（净 −89）**；按技能计应 −92（4×10 + 4×10 + 1×12），
  差 3 是表头 OCR 的 ±1 抖动（读到过 185 / 166 / 125）。
  中途出现的 `14` / `13` 是 **HUD 在浮层下漏掉中间位的已知误读**（真值 144 / 134，
  可由 154 −10 −10 −10 = 124 复核），**不可用于记账**。
- 停止原因：`STOP: 3 navigation cycles failed to reach the intel page`（到上限）。
  根因：最后一个 pin 点开是 **BLOCKED 的大师悬赏（20 号，推荐战力 189M）**，客户端被留在
  `BEAST` 页；`run_live.py --goal INTEL` 面对 INTEL-blocked 的 BEAST 页直接判 `beast_not_actionable`
  并在 **1 步 / 3.5s 内退出**（既不点返回也不去情报页）→ 连烧 3 个 nav cycle → STOP。
  结束时探针复核：`Page.BEAST / intel BLOCKED / MASTER_BOUNTY / POWER_BELOW_RECOMMENDED`。
- 未归因的失败（3 条，已登记未解决）：
  - `OPEN_INTEL_BEAST_TARGET` ×2 FAILURE `INTEL_BEAST_TARGET_NOT_PROVEN`（09:28:23 那次
    state_after 是 MAP/AVAILABLE，**原因不明**；09:37:55 那次已归因为大师悬赏阻断）。
  - `DISMISS_DAILY_REWARD` ×1 FAILURE `DAILY_REWARD_ADVANCE_NOT_PROVEN`（09:23:24）——
    情报领奖后的弹窗关闭未被证明。它把 pin_00 cycle 的 exit_code 顶成 2，但**未阻断产出**。
- 硬边界：81 个 episode 里**没有任何**付费/礼包/月卡/集结「前往」类技能（token 扫描为空）。
  未改动历史 Episode 或截图；无通配符删除。
- 证据：`evidence/intel_pins_20260915_092119.json`；日志 `out_intel_pins_auto.txt`；
  终态帧 `dataset/raw/control_panel/probe/live_page_20260915_093902.png`。

## 下次运行注意
- **新的头号杀手：BLOCKED 大师悬赏 pin 会把客户端留在 BEAST 页，而 INTEL nav 出不来。**
  它比"游离模态"更隐蔽——`run_live` 不报错，只是 1 步内正常退出（`beast_not_actionable`），
  于是 nav cycle 空转 3 次就 STOP。**修法方向：run_live 的 INTEL 目标在 BEAST 页见到
  `intel.status == BLOCKED` 时应先 BACK 回地图再继续，而不是直接判不可行动。**
  在修好之前，`run_intel_pins.py` 每轮都会在一个 BLOCKED pin 上折损剩余预算。
- **不要读 summary 的 `pins_processed` / `dispatches` 当产出**：nav cycle 里的真机作业
  （本轮 6 次派兵里有 2 次、10 次领奖里有 5 次）不计入 `pins_processed`。
  真实产出看 `per_pin[].productive_steps` 与 `learning/episodes.jsonl`。
- 跑之前先 `tools/probe_live_page.py` 探一次：起始页是情报页就直接跑；是弹窗先关（右上角 X）；
  是 BEAST/BLOCKED 先回地图。
- 体力 < 10 时循环会立刻正常停止，属合法终态，不要重试。
