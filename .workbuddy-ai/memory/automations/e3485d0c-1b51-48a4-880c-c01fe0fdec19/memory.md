# 自动化执行记录 — 情报（Intel）无人值守 pin 循环

## 2026-09-15 09:00 GMT+8（第 1 次实跑）
- 工具：`tools/run_intel_pins.py 8`（**未**使用 `run_intel_loop.py`）。
- 设备：MuMu 已在线（127.0.0.1:7555），无需启动流程。
- 执行了 3 次运行（2 次重试，达上限）：
  - #1 起始页=联盟页（上一轮自动化遗留）→ `3 navigation cycles failed`，pins/dispatches/claims 全 0。
  - #2 起始页=世界地图 → `3 navigation cycles failed`，计数全 0，**但 episodes 证明它真的上了板并做了
    3 轮 pin 作业（SELECT_INTEL_PIN×4、INTEL_HERO_START_MARCH×3，verifier 全 ok）**。计数 0 是假象。
  - #3 起始页=情报板 → `pins_processed=1`（ORANGE pin，card_opened=true，productive=false）→
    `STOP: stamina 5 below 10`。
- 情报板探针（真板帧）：`INTEL / AVAILABLE / pins=7 / available_count=7 / stamina=5`，与检测器一致。
- 唯一根因：`BTN_BEAST_DISPATCH` 状态相关模板陈旧——模板是「白 10（可用态）」，
  真机是「红 10（体力不足）」；生产阈值 6，实测 d=26 → `SEMANTIC_TARGET_NOT_VERIFIED`（本轮 3 次）。
  结局本就正确（体力 5 < 消耗 10），但报错原因是错的，会污染成功率统计。
  `PROMOTION BLOCKED`（仅 1 正样本 0 负样本），未改任何阈值。
- 未点任何付费/礼包控件；未改动任何历史 Episode 或截图；无通配符删除。
- 证据：`evidence/intel_unattended_run_20260915_010800.json`；日志 `out_intel_pins_auto*.txt`。

## 下次运行注意
- **起始页面决定成败**：若客户端不在世界地图，先退回地图再跑（上一轮自动化把客户端留在联盟页，
  直接烧掉一整轮）。
- 连按两次返回键会弹「确认退出游戏吗」；关它要点右上角 X（535,375），点「取消」按钮无效。
- 体力 < 10 时循环会立刻正常停止，属合法终态，不要重试。

## 收尾（同一轮，离线）
跑了语料测量 `tools/probe_page_anchor.py BTN_BEAST_DISPATCH`（2795 帧）：阈值 6 只命中 70 帧且全为 d=0；
d=24–28 那一带（28/41/114 帧）肉眼复核后是邮件横幅、邮件按钮、联盟领取、集结加入和空白区域。
⇒ **不可用态按钮（d=26）与这些无关画面不可分，模板/阈值两条路同时作废**；唯一正确修法是
「读按钮上的消耗 vs 当前体力」的显式状态分支。证据 `evidence/corpus_btn_beast_dispatch_20260915.json`。
下次不要再去试放宽 `BTN_BEAST_DISPATCH` 的阈值。

## 2026-09-15 10:20 GMT+8（第 2 次实跑）
- 工具：`tools/run_intel_pins.py 8`（**未**使用 `run_intel_loop.py`）。设备：MuMu 已在线。
- 执行 2 次：
  - #1 `3 navigation cycles failed`（`goal_page_mismatch`，计数全 0）。真机帧显示客户端卡在
    **联盟宝箱模态弹窗**（上一轮 `ALLIANCE_ALLY_GIFT_CLAIM` 遗留）——`run_live.py --goal INTEL`
    的导航**关不掉模态**。手动点右上角 X（683,44）后立刻回到世界地图。
  - #2 成功：`pins_processed=1 / pins_skipped=0 / dispatches=1 / claims=2`，exit 0。
    真实产出 = `DISPATCH_INTEL_BEAST` + `INTEL_HERO_DISPATCH` + `INTEL_CLAIM_REWARDS`×2，verifier 全 ok。
    终态 `STOP: stamina 1 below 10`（合法终态）。体力 21→11→1（两种派兵各 −10）。
- 探针：`INTEL / AVAILABLE / pins=6`，与检测器一致，**无「疑似检测误零」**。
- 顺手修：`tools/probe_intel_board.py::gate_trace` 的 ratio 下限 0.65 → 0.5，与生产
  `intel_pins.py` 对齐（原来会把已检出的橙 pin 报成「仅因 ratio 被拒」= 凭空制造假零）。
- 未点任何付费/礼包控件；未改动历史 Episode/截图；无通配符删除。
- 证据：`evidence/intel_pins_20260915_022310.json`；日志 `out_intel_pins_auto*.txt`、`out_auto_probe*.txt`。

## 下次运行注意（更新）
- **游离模态是当前第一号杀手**：进 nav 前若客户端停在弹窗（联盟宝箱/各类奖励弹窗），
  `run_live.py --goal INTEL` 会连撞 3 轮后放弃，整轮白跑。**先手动/程序化点弹窗右上角 X（683,44）**，
  回到世界地图再跑。已连续两轮（09:00、10:20）栽在同一根因上。
- **不要读 summary 的 `pins_processed` / `dispatches` 当产出**：它们只数部分技能
  （`dispatches` 不含 `INTEL_HERO_DISPATCH`；nav cycle 的真机作业不计入 `pins_processed`）。
  真实产出看 `per_pin[].productive_steps` 与 `learning/episodes.jsonl`。
- 体力 < 10 立刻正常停止，属合法终态，不要重试。
- 连按两次返回键会弹「确认退出游戏吗」；关它要点右上角 X（535,375），点「取消」无效。
