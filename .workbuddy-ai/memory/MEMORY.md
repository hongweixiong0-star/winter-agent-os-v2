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
- **小 ROI 上的数字会被 OCR 拆成重叠碎片；正解是碎片拼接，不是放大裁剪。**
  真机 42×24 体力裁剪实测形态：`295+5`、`29+95`、`16+66+6`、`18+9`。
  每个碎片都是同一个数字的**部分读取**，所以真值 = **包含全部碎片的最短字符串**
  （按阅读顺序拼接，重叠取最长公共串）。**固定倍率放大是错的**：3× 虽然修好了
  `166`/`189`，却把原本正确的 `295` 拆成 `29+95` 读成 29（全量测试抓到）。
  另一个坑：OCR 置信度**逐次波动**（同一帧同一裁剪，某碎片一次 0.812、一次 0.999），
  「单次实测通过」不等于稳定。
- **MaaFw `post_screencap` 返回 BGR，而本项目全部像素路径是 RGB**（V2 模板裁自 ADB PNG 并经
  PIL 读取；OCR 同理）。实测 2026-09-14（MaaFw 5.12.3 + MuMu EmulatorExtras，同一帧同一模板）：
  MAA 匹配器「原样」0.6879（阈值 0.7 → NO_MATCH），R↔B 交换后 **1.0000 命中**；
  V2 视觉读已保存的 PNG 是 `UNKNOWN/0.00`，交换后 `POPUP/INTEL_HERO_JOURNEY/0.99`。
  已修：`to_rgb_frame()` 在 `capture()` 边界只转一次。**`docs/AVAILABLE_TOOLING.md` 写的是
  "RGB"，与实际相反** —— 框架文档的通道顺序一定要当假设验证；「刚好卡在阈值下面」会让带色
  模板随机通过/失败，并让磁盘上所有证据帧颜色都是错的。
- **MAA 识别节点必须显式注册模板文件**：节点里的 `template` 是语义名（`BTN_HERO_CAMP_FIGHT`），
  而磁盘文件名带 provenance 后缀且位于 `template_dir` 之外
  （`dataset/candidate/hero_camp/btn_hero_camp_fight__live_hero_camp.png`）。路由若不把节点的
  `source_template` 交给适配器，会以 `TEMPLATE_NOT_REGISTERED` 失败，却被报成
  `SEMANTIC_TARGET_NOT_VERIFIED`（读作"屏幕上没这个控件"）——**曾使所有带节点的技能在生产上
  全部解析不出目标**。已修（`c03af7d`）。
- **verifier 可能落后于 brain/vision 的页面契约**：2026-09-14 一次性发现三处同源
  （营救开始 / 英雄目标打开 / 英雄 march 打开）。真机页面分类变了而 verifier 还写死旧页面时，
  **已经成功的动作会被记成 FAILURE**，同时毒化成功率与 Recovery 决策。
  核对顺序：先看 `brain.py` 与 vision 层的实际契约，再改 verifier；并且优先用
  「不可逆的真实状态变化」（体力扣减 / 资源变化 / 队列变化）作为证据，而不是单帧模板读数。
- **`intel_not_available` 这个 stop_reason 目前不可信（2026-09-15 真机对照推翻其判据）。**
  `winter_agent_v2/ocr.py` 的 INTEL 回落分支声称两个状态"仅靠 OCR 即可分开"：
  「有任务卡 → `击败野兽等级10 … 前往查看`；列表为空 → 只剩 `情报 / 体力 / 下次刷新` 表头」，
  并在 `status` 仍为 `UNKNOWN` 时按 `has_header` 直接判 `NOT_AVAILABLE`。
  **真机对照证伪**：截图 `live_intel_full_run6_step_001_before_20260914T082814883105.png`
  （08:28 UTC）OCR 全量只有 `情报 / 305 / 下次刷新：07:31:46 / 满级 / 40`——
  **没有 `前往查看`**，而它随后连做 4 个真实动作并真派兵、真领奖
  （`SELECT_INTEL_BEAST_MISSION` → `OPEN_INTEL_BEAST_TARGET` → `INTEL_BEAST_START_MARCH`
  → `DISPATCH_INTEL_BEAST`，08:30 又 `INTEL_CLAIM_REWARDS`）。
  即**"只有表头"同时对应"有空任务"和"空列表"**，`has_header ⇒ NOT_AVAILABLE` 是假阳性判据。
  情报地图上的 pin 是纯图形、无文字，`前往查看` 只在点开 pin 后才出现——所以列表页 OCR
  从结构上就拿不到区分两者的证据。该帧之所以判成 `AVAILABLE` 是因为**模板层**先命中了
  野兽卡，OCR 回落根本没被调用；一旦模板层漏检（→`UNKNOWN`），回落就会把"有任务"错报为
  `NOT_AVAILABLE` 并正常退出（exit 0、verifier PASS），**静默终止目标且看起来像成功**。
  修法方向：`NOT_AVAILABLE` 只能由**逐 pin 点开**（`tools/run_intel_pins.py` 的
  `card_opened/productive` 证据）或"pin 数为 0"来支撑，不能由表头文字推导。
  按项目提升闸门，此结论目前只有 **1 张正样本帧**，修模板/判据前需补齐 ≥3 正 ≥3 负，属
  `PROMOTION BLOCKED`；但**"别信 `intel_not_available`"这条可以直接用**。
- **`run_intel_loop.py` 对 pin 地图情报板是"错的工具"（2026-09-15 01:10 实跑复现 + 产出对照）。**
  第 2 次真机运行同样 3 轮 `intel_not_available` / exit 0 / dispatches 0 / claims 0，
  而**它自己连拍的 3 张 frame 全部是满板 8 pin 的情报地图**（体力 175、`下次刷新:06:49:22`）。
  同一次自动化紧接着跑 `tools/run_intel_pins.py 8`：8/8 `card_opened=true`、
  `DISPATCH_INTEL_BEAST`×3、`INTEL_HERO_DISPATCH`×2、`INTEL_CLAIM_REWARDS`×7（全部 verifier ok）、
  体力 **176 → 107（净 −69）**。⇒ **有 pin 地图时"空板"结论永远错**；
  **真相源是逐 pin 的 `card_opened/productive`（`evidence/intel_pins_*.json`）**。
- 根因链（本次补齐）：情报页是 **pin 地图**，任务卡只在**点开 pin 之后**出现；
  `vision.py` + `dataset/candidate/template_manifest.json` 是按"单张任务卡"标定的 → 地图上必漏检
  → template 层给 `Page.INTEL` 但 status `UNKNOWN` → 落进 `ocr.py` 的 `has_header` 回落 → 假 `NOT_AVAILABLE`。
  而 `winter_agent_v2/intel_pins.py::intel_pin_centers()`（颜色 blob + 白图标校验，已真机可用）
  **只被 `tools/run_intel_pins.py` 调用，没接进生产 vision/OCR 路径**。
  ⇒ 正解：INTEL 可用性判据改成 **pin 计数**（`pins>0 ⇒ AVAILABLE/available_count=N`）；
  `NOT_AVAILABLE` 只允许由"pin 数为 0"或逐 pin 证据支撑，**禁止由表头文字推导**。
- **闸门已解除，修复已上线（2026-09-15 08:xx GMT+8）。** 上一轮卡在「负样本未确立」，
  但真相是：**那个"负样本"是错标的正样本**。项目里唯一被当成"空情报板"的帧
  `dataset/truth_audit/intel_beast_target_20260914/03_intel_page_empty_list.png`
  实测是**满板 13 个 pin**（体力 305、`下次刷新:07:59:21`），而且上一轮还写了一个
  断言 `status == "NOT_AVAILABLE"` 的测试 —— **把 bug 写成了测试**。
  已重命名为 `03_intel_page_full_board.png`（保留不删），两个测试改写为正确行为。
  ⇒ **本项目至今没有任何经过验证的「空情报板」帧**；`NOT_AVAILABLE` 只能由
  「pin 检测器一个都没看到」到达。**教训：所谓"负样本"必须先肉眼复核，不能靠 OCR 文字推断。**
  修复后同一张真机帧：`NOT_AVAILABLE/available_count=0` → `AVAILABLE/pins=5`；
  `SELECT_INTEL_PIN` 真机 4 次执行 4 次 SUCCESS（含 `EXECUTE_INTEL_RESCUE_SURVIVORS` 链路）。
- **自动化 / 外部状态必须用接口复核，且这条已经复发第二次（2026-09-15 接手时）。**
  三份 handoff 都写着「常驻自动化 id `7c1c18c1-…`（ACTIVE，每小时）」，
  而自动化接口 `list` 返回**空数组**（磁盘上只剩 `.workbuddy/memory/automations/<id>/memory.md`）。
  与第九轮 `0o` 完全同型 ⇒ **两次记录都不可信，两次都等于"没有任何无人值守在跑"**。
  已重建 `e3485d0c-1b51-48a4-880c-c01fe0fdec19`（ACTIVE，每小时），并用 `list` 复核存在。
  **规则：automation / connector / MCP / 真机这类"外部状态"，写进 handoff 之前必须用对应接口查一次。**
  另一个坑：`list` 为空时磁盘上的 `memory.md` 还在，**看目录会误判为"存在"**。
- **体力读数的可信面**：只采信**情报页表头**读数（`run_intel_pins.intel_stamina()` 的 0.78/0.015/0.16/0.04 ROI）。
  同一轮里 nav cycle 报出的 16 / 36 是地图 HUD 体力条在浮层下的已知误读，**不要用于记账**。
  逐 pin 会话里最稳的序列是 episodes 中 `OPEN_INTEL` 的 `intel.stamina`（表头 OCR，conf 0.999）。
- **pin 计数的假零已修（2026-09-15）：长宽比下限 0.65 → 0.5。**
  根因是橙 pin 的**光晕把 blob 向下拉长**（本体 ~90px，blob 到 137–167px）→ 比例跌破下限。
  实测跨度 **0.521–0.644**（0.521 出现在满板帧上），闸门现在是
  `h>=60 and w>=40 and 0.5 <= w/h <= 1.3 and fill>=0.30`。
  语料核对（22 帧）：降下限后**每块板只多收那一个光晕橙 pin，其余 16 帧零新增**。
  ⇒ **`run_intel_pins.py` 打出的 "no actionable pins left" 不是"板空"的证据**，
  先分清是"检测为 0"还是"点开后被判无动作"。**0.5 的余量已经很小**，
  更稳健的解法是**剥离光晕后量本体高度**（而不是继续降阈值）。
  另外：`intel_pin_centers()` 在 **MAP 帧上会误报**（右侧 HUD 圆形按钮被当成 pin，4 个 BLUE），
  所以它**必须按页面门控**——生产里只在 `page == INTEL` 时调用。
  证据：`dataset/truth_audit/intel_pin_board_20260915/`（含 MAP 误报对照帧）。
- **大师悬赏（INTEL_MASTER_BOUNTY）是长期阻断项**：2026-09-15 点开「大师悬赏：20号」，
  vision 读 `status=BLOCKED`（推荐战力 189M，账上远不够），卡上只有 `前往查看` 无领取按钮，
  brain 正确走 `BACK`（`reason=intel_master_bounty_power_blocked`，verifier ok，未花体力）。
  这类 pin 会长期占着地图，**别把它当成"任务失败"反复重试**；战力达标前它不可动作。



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
