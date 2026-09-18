# 项目记忆 — 无尽冬日智能体 / Winter Agent OS V2

## 定位
《无尽冬日》(Whiteout Survival) 国服客户端截图驱动自动化 Agent。MuMu 模拟器 + ADB，720×1280，
包名 `com.gof.china`。V2 完全独立，不 import 任何 legacy Agent/Brain/Scheduler/Vision 代码。

## 铁律（改代码前必读）
- **只有一个** Scheduler、SkillRegistry、WorldState、Executor 边界、Episode 流。
- Vision Template-first；OCR 仅用于 UNKNOWN 或明确缺失的结构化字段，角色 `TEXT_RECOGNITION_ONLY`。
- `RuleBrain` 决定 WHAT，Skill 定义 HOW，Vision 与 Qwen **永不点击**。
- 运行态真相源唯一：`learning/runtime_snapshot.json`；GUI 只读、不写业务状态。
- 真实成功必须有 live 状态变化 + Vision + Verifier 证据；Replay 一律标 `SIMULATION`。
- "代码存在" / "单次成功" ≠ `STABLE`；**当前 STABLE=0 是刻意的**。
- 外部项目（wos / bot / wosbot / autopilot）只能 `REFERENCE_ONLY`，不得复制代码 / 坐标 / 截图 / 图标 / 账号数据。
- 真实支付、账号或角色删除、账号安全变更、系统危险操作**永久阻断**。
- 历史失败 Episode 与截图**不得篡改**。
- 证据链：`external → raw → normalized → candidate → verified → production`。
- 用户偏好：**不虚报**——宁可标 CANDIDATE / UNKNOWN / 0，也不把未验证的写成成功；报告要区分
  LIVE_CLIENT / HISTORY·仅参考 / PRIOR / SIMULATION；不要每步停下来问，自动继续下一最高价值任务；
  **清理文件必须先列清单逐项确认，禁止按前缀/通配符批量删除**（已付出过代价）。
- **角色不是全局的**（2026-09-16 实测）：同一台模拟器上至少出现过两个账号 —— 09-14 帧战力
  70,206,322 / 面板 `行军 6/6`，09-16 帧战力 542,443 / 面板 `1/2`，**同服务器 `#4298`**。
  容量、功能解锁、资源、Goal 状态全部 role-scoped；**禁止**把行军容量或"某功能已解锁"
  当成全局常量，也禁止用配置声明当角色身份。
- **身份只能从客户端读**：`领主档案` 面板（HOME/MAP **点一次左上头像**）给出
  `账号：1171757165` / `[zoe]xhw小号` / `所在王国：4298`。一次 Back 回 MAP。
  ⚠ 该面板底部有 `设置` 页签，而账号/角色删除路径正是 `config.risk` 保护的对象
  ⇒ **只读，永不点击面板内任何控件**。名字**不在** HUD 上（三帧核实），战力/统帅都不是键。
- **数值只来自观测**：容量必须来自计数器 `/` 读数（炉子/世代只能提供 Prior）。解析器必须
  整 token 匹配 —— `'3/' ＋ '3/6'` 曾被拼成一行读成 `3/3`，**客户端说 6、episode 记 3**。
- **当前阶段 = CAPABILITY-FIRST（2026-09-16 起）**：不再扩架构，尽快"会做越来越多的事"。
  单功能 30–60 分钟（复杂最多 90）；**超时无明显真机进展 ⇒ BLOCKED ⇒ 立即换下一个**；
  **已能稳定工作的功能不要再优化**；最小验收 = `Preconditions → Execute → Verifier PASS →
  Production Episode → Evidence`；顺序：GATHER/RECALL → CLAIM·MAIL·VIP·FREE →
  TRAIN·PROMOTE·HEAL → RESEARCH·BUILD → ALLIANCE → HUNT_BEAST → ARENA·EXPLORATION·PET →
  RALLY → BEAR。**Intel 除 P0 回归不再深挖。** 用 `tools/capability_landing_queue.py` 看队列。
  ⚠ 区分「没试过」与「没实现」：`Skill.verifier` 只是声明的名字，真裁判是 `VERIFIED_ATOMIC`。
- **"等待/重试"类技能必须有终止条件**：`CHECK_MARCH` 只是"再看一眼"，当被观测对象不随时间
  变化时它是纯烧动作（实测一轮烧完 8 个动作、零产出）。设计任何重观测前先问：**什么会变？**
- **删掉一个错误假设之后，必须重跑一次端到端**：R22 删掉"假定容量 6"是对的，但它同时删掉了
  采集链**起步条件的唯一数值** —— 而 R21 的成功恰好由那个假设供给，**成功掩盖了这个洞**。

## 工具优先（HARD RULE，2026-09-14）
- **先找工具，再写代码。** 开工前先读 `docs/AVAILABLE_TOOLING.md`，汇报给 TOOL CHECK 五行：
  `AVAILABLE_TOOLS / BEST_EXISTING_TOOL / EXISTING_IMPLEMENTATION / WHY_NOT_USE_EXISTING_TOOL /
  CUSTOM_CODE_NEEDED`。解释不了"成熟工具为何不够"就不许自研底层。
- **MaaFw 5.12.3 已装在项目 venv**。涉及截图 / 控件与页签定位 / 模板 / OCR / ROI / 点击 / 滑动 /
  等待页面 / 等待消失 / 重试 / UI 恢复，**先评估 MAA**。
- 分层固定：**V2 = Brain/Goal/Strategy/WorldState/Knowledge/Verifier；MAA = 取帧/识别/UI 动作/等待/重试；
  ADB = 设备层 + fallback；Verifier = 唯一事实裁判**（MAA 返回 SUCCESS ≠ Skill 成功）。
- 两个轴分开决策（真机 20 次实测）：**取帧 MAA 8.92ms vs ADB 324ms（36.3×）→ 已切**；
  识别 MAA 113ms vs 旧 V2 34.5ms（都 20/20 命中、中心差 0.3px）→ **逐语义按证据迁**，不伪造"更优"。
- 提升某 skill 到 MAA **必须同时写入 evidence**（`knowledge/execution/backend_routing.json`）。
- 止损：单个 UI 元素 15 分钟；单个 Skill/Failure/Goal 90 分钟内必须拿到「成功率改善 / Root Cause /
  具体 Blocker / 证明方案错误」之一；单个变体持续失败就标 PARTIAL/DEGRADED 并登记，不阻塞全局。

## 已踩过的坑

### 模板与视觉
- 旧模板只能当 Candidate：须来自独立真机帧、带正负样本、阈值标定、页面上下文。
  **禁止模板自己裁自己再自匹配**（d=0 是循环论证，曾骗过三次真机运行）。
- **提升闸门：正样本 ≥3 张独立真机帧、负样本 ≥3 张**，否则输出 `PROMOTION BLOCKED`。
  曾用 1 张正样本提升 `OPEN_INTEL` 节点，首次真机即回归（找对位置但相关性 0.448 < 0.7，
  按钮是动画的）→ 已回滚 HYBRID。
- **哈希距离的容差不能搬到模板匹配阈值上**。旧语义为动画控件放宽过容差
  （如 `BTN_OPEN_INTEL_WILD_HUD` max_distance 24），迁移时必须重新标定。
- **MaaFw `post_screencap` 返回 BGR，而本项目全部像素路径是 RGB**。实测 2026-09-14
  （MaaFw 5.12.3 + MuMu EmulatorExtras，同一帧同一模板）：MAA 匹配器「原样」0.6879
  （阈值 0.7 → NO_MATCH），R↔B 交换后 **1.0000 命中**；V2 读已保存 PNG 是 `UNKNOWN/0.00`，
  交换后 `POPUP/INTEL_HERO_JOURNEY/0.99`。已修：`to_rgb_frame()` 在 `capture()` 边界只转一次。
  **`docs/AVAILABLE_TOOLING.md` 写的是 "RGB"，与实际相反** —— 框架文档的通道顺序一定要当假设验证；
  「刚好卡在阈值下面」会让带色模板随机通过/失败，并让磁盘上所有证据帧颜色都是错的。
- **MAA 识别节点必须显式注册模板文件**：节点里的 `template` 是语义名（`BTN_HERO_CAMP_FIGHT`），
  而磁盘文件名带 provenance 后缀且位于 `template_dir` 之外
  （`dataset/candidate/hero_camp/btn_hero_camp_fight__live_hero_camp.png`）。路由若不把节点的
  `source_template` 交给适配器，会以 `TEMPLATE_NOT_REGISTERED` 失败却被报成
  `SEMANTIC_TARGET_NOT_VERIFIED`（读作"屏幕上没这个控件"）——**曾使所有带节点的技能在生产上
  全部解析不出目标**。已修（`c03af7d`）。
- **verifier 可能落后于 brain/vision 的页面契约**：2026-09-14 一次性发现三处同源
  （营救开始 / 英雄目标打开 / 英雄 march 打开）。真机页面分类变了而 verifier 还写死旧页面时，
  **已经成功的动作会被记成 FAILURE**，同时毒化成功率与 Recovery 决策。
  核对顺序：先看 `brain.py` 与 vision 层的实际契约，再改 verifier；优先用
  「不可逆的真实状态变化」（体力扣减 / 资源变化 / 队列变化）作证据，而不是单帧模板读数。
- **判定一个控件"坏了"之前，先找到动作真正指向的语义名（2026-09-17，我写错过一次）。**
  `skills.py` 的技能 `action.target` 才是生产要解析的语义；**同一控件常有两个语义名**
  （例：`BTN_OPEN_POWER_OVERVIEW` 宽裁剪含战力数字 ⇒ 只能匹配裁它那个账号；
  `BTN_OPEN_POWER_OVERVIEW_ICON` 只裁图标 ⇒ 两账号都命中。**技能点的是后者，它一直是好的**）。
  我用前者量出 MISS 就写下"入口是值依赖模板、必须重裁"，还写进了提交说明 —— **近乎报告了一个
  早就存在的修复**。⇒ 量任何控件前先 `grep` 它的 `action.target`；**结论写进文档/提交前，
  必须找到引用了该语义名的代码路径**，找不到引用就说明你量的东西没人用。
- **verifier 的刷新重试会吃掉"瞬时 UI"的寿命（2026-09-17）。** 兵营聚焦浮层（`详情/立即完成/加速/训练`
  + 引导手指动画 + 呼吸光圈）寿命约 **2 秒**；旧模板 7 帧只中 3 帧 ⇒ verifier 连刷两次、
  烧掉 **21 秒**才通过 ⇒ 下一步观测时浮层已消失 ⇒ **整条路线被迫重走**（7 步，前 3 步重复一次）。
  ⇒ 识别不稳时**先看 verifier 花了多久**，再怀疑推理链；给"点一下→下一步"的链路配模板时，
  必须让**第一次观测就能通过**。
- **点击落点 = 命中记录的 ROI 中心**，而执行器只支持 `TAP_SEMANTIC`（无绝对坐标动作）
  ⇒ 若要点的控件周围有动画，"最稳的那块"和"要点的那个按钮"常常不是同一块；
  **裁剪必须以要点的按钮为圆心，靠扩大范围吃掉动画，而不是挪到最稳处。**
- **门禁必须按"两个总体"定，而不是按"让这个候选通过"定（2026-09-17）。**
  `BTN_OPEN_TRAINING_FROM_CAMP` 旧阈值 17 是给旧裁剪调的（正样本 12–16、负样本 ≥20）；
  新裁剪正样本 0–8，但**普通城市帧是 16 —— 落在 17 之内** ⇒ 会报 `menu_open` 并把点击送进城市。
  收窄到 12。**收紧也有正当情形**：跨号帧靠它自己的旧记录仍命中（d=0），故不丢召回。

### OCR
- **小 ROI 上的数字会被 OCR 拆成重叠碎片；正解是碎片拼接，不是放大裁剪。**
  真机 42×24 体力裁剪实测形态：`295+5`、`29+95`、`16+66+6`、`18+9`。每个碎片都是同一个数字的
  **部分读取**，真值 = **包含全部碎片的最短字符串**（按阅读顺序拼接，重叠取最长公共串）。
  **固定倍率放大是错的**：3× 修好了 `166`/`189`，却把原本正确的 `295` 拆成 `29+95` 读成 29。
- OCR 置信度**逐次波动**（同一帧同一裁剪，某碎片一次 0.812、一次 0.999），
  「单次实测通过」不等于稳定。

### 情报（Intel）— 当前重点
- **`intel_not_available` 这个 stop_reason 不可信。** `winter_agent_v2/ocr.py` 的 INTEL 回落分支
  在 `status` 仍为 `UNKNOWN` 时按 `has_header` 直接判 `NOT_AVAILABLE`，而真机对照证伪：
  截图 `live_intel_full_run6_step_001_before_20260914T082814883105.png` OCR 全量只有
  `情报 / 305 / 下次刷新：07:31:46 / 满级 / 40`（**没有 `前往查看`**），随后它却连做 4 个真实动作
  并真派兵、真领奖（`SELECT_INTEL_BEAST_MISSION` → `OPEN_INTEL_BEAST_TARGET` →
  `INTEL_BEAST_START_MARCH` → `DISPATCH_INTEL_BEAST`，08:30 又 `INTEL_CLAIM_REWARDS`）。
  即**"只有表头"同时对应"有空任务"和"空列表"**。情报地图 pin 是纯图形、无文字，`前往查看`
  只在点开 pin 后出现 → 列表页 OCR 从结构上就拿不到区分两者的证据。模板层一旦漏检（→`UNKNOWN`），
  回落就会把"有任务"错报为 `NOT_AVAILABLE` 并正常退出（exit 0、verifier PASS），
  **静默终止目标且看起来像成功**。
- **`tools/run_intel_loop.py` 对 pin 地图情报板是"错的工具"（2026-09-15 两次真机复现）。**
  两次都是 3 轮 `intel_not_available` / exit 0 / dispatches 0 / claims 0，而**它自己连拍的帧
  全部是满板 8 pin 的情报地图**。同一次自动化紧接着跑 `tools/run_intel_pins.py 8`：
  8/8 `card_opened=true`、`DISPATCH_INTEL_BEAST`×3、`INTEL_HERO_DISPATCH`×2、
  `INTEL_CLAIM_REWARDS`×7（全部 verifier ok），体力 **176 → 107（净 −69）**。
  ⇒ **有 pin 地图时"空板"结论永远错**；**真相源是逐 pin 的 `card_opened/productive`**
  （`evidence/intel_pins_*.json`）。
- 根因链：情报页是 **pin 地图**，任务卡只在**点开 pin 之后**出现；`vision.py` +
  `dataset/candidate/template_manifest.json` 是按"单张任务卡"标定的 → 地图上必漏检 →
  template 层给 `Page.INTEL` 但 status `UNKNOWN` → 落进 `ocr.py` 的 `has_header` 回落 → 假 `NOT_AVAILABLE`。
  而 `winter_agent_v2/intel_pins.py::intel_pin_centers()`（颜色 blob + 白图标校验，已真机可用）
  **只被 `tools/run_intel_pins.py` 调用，没接进生产 vision/OCR 路径**。
  ⇒ 正解：INTEL 可用性判据改成 **pin 计数**（`pins>0 ⇒ AVAILABLE/available_count=N`）；
  `NOT_AVAILABLE` 只允许由"pin 数为 0"或逐 pin 证据支撑，**禁止由表头文字推导**。
- **闸门已解除，修复已上线（2026-09-15 08:xx GMT+8）。** 上轮卡在「负样本未确立」，真相是
  **那个"负样本"是错标的正样本**：`dataset/truth_audit/intel_beast_target_20260914/
  03_intel_page_empty_list.png` 实测是**满板 13 个 pin**（体力 305、`下次刷新:07:59:21`），
  而且上轮还写了一个断言 `status == "NOT_AVAILABLE"` 的测试 —— **把 bug 写成了测试**。
  已重命名为 `03_intel_page_full_board.png`（保留不删），两个测试改写为正确行为。
  ⇒ **本项目至今没有任何经过验证的「空情报板」帧**。修复后同一张真机帧：
  `NOT_AVAILABLE/available_count=0` → `AVAILABLE/pins=5`；`SELECT_INTEL_PIN` 真机 4 次执行 4 次
  SUCCESS（含 `EXECUTE_INTEL_RESCUE_SURVIVORS` 链路）。
  **教训：所谓"负样本"必须先肉眼复核，不能靠 OCR 文字推断。**
- **pin 计数的假零已修：长宽比下限 0.65 → 0.5。** 根因是橙 pin 的**光晕把 blob 向下拉长**
  （本体 ~90px，blob 到 137–167px）→ 比例跌破下限；实测跨度 **0.521–0.644**（0.521 出现在满板帧上）。
  现闸门 `h>=60 and w>=40 and 0.5 <= w/h <= 1.3 and fill>=0.30`。语料核对（22 帧）：降下限后
  **每块板只多收那一个光晕橙 pin，其余 16 帧零新增**。
  ⇒ **`run_intel_pins.py` 打出的 "no actionable pins left" 不是"板空"的证据**，
  先分清是"检测为 0"还是"点开后被判无动作"。**0.5 的余量已经很小**，更稳健的解法是
  **剥离光晕后量本体高度**（而不是继续降阈值）。
  另外：`intel_pin_centers()` 在 **MAP 帧上会误报**（右侧 HUD 圆形按钮被当成 pin，4 个 BLUE）
  → 它**必须按页面门控**，生产里只在 `page == INTEL` 时调用。
  证据：`dataset/truth_audit/intel_pin_board_20260915/`（含 MAP 误报对照帧）。
- **体力读数的可信面**：只采信**情报页表头**读数（`run_intel_pins.intel_stamina()` 的
  0.78/0.015/0.16/0.04 ROI）。同一轮里 nav cycle 报出的 16 / 36 是地图 HUD 体力条在浮层下的
  已知误读，**不要用于记账**。逐 pin 会话里最稳的序列是 episodes 中 `OPEN_INTEL` 的
  `intel.stamina`（表头 OCR，conf 0.999）。
- **大师悬赏（INTEL_MASTER_BOUNTY）是长期阻断项**：2026-09-15 点开「大师悬赏：20号」，
  vision 读 `status=BLOCKED`（推荐战力 189M，账上远不够），卡上只有 `前往查看` 无领取按钮，
  brain 正确走 `BACK`（`reason=intel_master_bounty_power_blocked`，verifier ok，未花体力）。
  这类 pin 会长期占着地图，**别把它当成"任务失败"反复重试**；战力达标前它不可动作。
- **BLOCKED 大师悬赏 pin 会毒化整轮 nav（2026-09-15 17:20 实跑）。** 点开它之后客户端被留在
  `BEAST` 页；`run_live.py --goal INTEL` 面对 INTEL-blocked 的 BEAST 页直接判 `beast_not_actionable`
  并在 **1 步 / 3.5s 内退出**——既不点返回也不去情报页，**不报错、只是"正常"退出**。
  于是 `run_intel_pins.py` 的 nav cycle 空转 3 次撞上限 `STOP`，剩余 pin 预算作废。
  这与「游离模态挡路」不同：模态会让 nav run 显式失败，这个只会静默空转。
  正解方向：INTEL 目标在 BEAST 页见到 `intel.status == BLOCKED` 时先 BACK 回地图再继续。
  ✅ **已修（2026-09-15 18:0x，id `0az`）**：修法与你写下的方向一致 —— 先**测量**落点
  （`tools/probe_back_from_beast.py` 在真机那张卡上按一次 BACK ⇒ 落到 `MAP`，体力恢复可读 110），
  再在 `brain.py` 的 `Page.BEAST` 非可行动分支加 `BACK` 出路（`beast_card_not_actionable_leaving_the_page`），
  并用一次性守卫 `beast_card_not_actionable_left` 防止 BACK 没生效时卡↔图乒乓；
  `verify_safe_back` 正好接受该转移。条件比 `intel.status == BLOCKED` **更宽也更稳**：
  触发条件是「这张卡在屏幕上但没有任何可行动作」（`available` 假值），不依赖情报字段。
  ⚠ 修好后**整链尚未真机跑过**（当时客户端已被测量探针挪到 MAP），目前是「落点已测量 + 单测 9 项」。
- **`DISMISS_DAILY_REWARD` 的 `DAILY_REWARD_ADVANCE_NOT_PROVEN` 是未归因失败**（2026-09-15 09:23:24）：
  情报领奖后的弹窗关闭未被 verifier 证明，会把该 cycle 的 exit_code 顶成 2，但不阻断产出。

### 外部状态
- **automation / connector / MCP / 真机这类"外部状态"，写进 handoff 之前必须用对应接口查一次。**
  已复发两次：三份 handoff 都写着「常驻自动化 id `7c1c18c1-…`（ACTIVE，每小时）」，
  而自动化接口 `list` 返回**空数组**（磁盘上只剩 `.workbuddy/memory/automations/<id>/memory.md`）
  ⇒ **两次记录都不可信，两次都等于"没有任何无人值守在跑"**。已重建
  `e3485d0c-1b51-48a4-880c-c01fe0fdec19`（ACTIVE，每小时）并用 `list` 复核存在。
  另一个坑：`list` 为空时磁盘上的 `memory.md` 还在，**看目录会误判为"存在"**。
- **反向的坑：把"人为停用"误判成"又丢了"（2026-09-15 18:37）。**
  `43aef0ad-d5bc-4d79-9291-0a4da0b0dc27`「Winter V2 情报循环（每小时）」曾被生产证据证明**真的在跑**
  （`evidence/intel_pins_20260915_092119.json`：`dispatches=4 claims=10` + 81 条 episode），
  随后**操作者主动要求取消**，已置 `PAUSED` 并复核。
  ⇒ 判断自动化时**必须分三种状态**：① `ACTIVE` 且在产出 → 正常；② `ACTIVE` 但无产出 → `0ap` 那个病；
  ③ `PAUSED` → **人为停用，不是故障**。看不到新 episode 时**先查 status**，
  不要一律当故障去重建（重建会覆盖操作者的意图）。恢复只需把 status 置回 `ACTIVE`，id 与 prompt 都还在。

## 环境
- **入口**：先读 `START_HERE.md`（根目录），它会指向 `.workbuddy-ai/handoff/`。
- 跨账号接力：`python tools/update_workbuddy_handoff.py` 从真实项目重算 handoff；
  `tools/verify_handoff.py` 校验其结构不变量。项目已有 git 仓库（2026-09-14 建立），
  checkpoint 用 `python tools/update_workbuddy_handoff.py --checkpoint -m "..."`。
- **跑项目脚本/测试必须用项目 venv**：`E:\dongri-mumu-bot\.venv\Scripts\python.exe`
  （含 PIL / rapidocr）。托管 Python 3.13 **没有 PIL**，系统 Python 3.12 也不完整。
- 命令执行：Bash 工具**当前可用** `ls / head / wc / echo`（2026-09-15 实测）；
  历史上曾无 coreutils，且 **PowerShell stdout 不回传**。稳妥做法仍是
  `"...python.exe" -c "..." > out.txt 2>&1` 再用 Read 读文件。
- MuMu 默认**不启动**。启动：`MuMuManager.exe control -v 0 launch -pkg com.gof.china`
  → `adb connect 127.0.0.1:7555`。真机 720×1280，前台包 `com.gof.china`。
- 启动入口：`Start-Winter-Agent-V2.cmd` / 桌面 `Winter Agent OS V2.lnk`。
- **GitHub 远端已接（2026-09-16）**：`origin = https://github.com/hongweixiong0-star/winter-agent-os-v2.git`
  （**public**，含完整 88 次提交历史）。checkpoint 之后加一步 `git push origin main` 即同步。
  推送身份用 **`gh` CLI**（`C:\Program Files\GitHub CLI\gh`，已登录 `hongweixiong0-star`，
  scopes `gist / read:org / repo`；`gh auth setup-git` 已把凭据接进 git）。
  ⚠ **不要再走 `git credential fill` 取 token**：GCM(`credential.helper=helper-selector`) 那条路径
  会因凭据失效弹 GUI 窗口并把**非交互调用挂死**（实测两次，各 2 分钟仍无输出，必须靠
  `timeout N` 兜底）；而且它返回的 `gho_` token 属于旧会话，不可信。
  ⚠ **WorkBuddy 的 GitHub 连接器不能建仓库**：`create_repository` 返回
  `403 Resource not accessible by integration`（App 权限不含 Administration）。
  建仓库只有两条路：`gh repo create <name> --public --source=. --remote=origin --push`，
  或操作者在网页手动建。「连不上 git」的判据是 `git remote -v` **为空**，不是 `gh auth status`。
- **与 ChatGPT 的长期桥梁 = 公开 Issue #2 `CHATGPT-ADVISOR`**（2026-09-16 建）
  `https://github.com/hongweixiong0-star/winter-agent-os-v2/issues/2`
  用途：只上报**高价值阻塞 / 架构决策 / 工具选型 / 反复失败的真机问题**，
  不发流水账。每条必须带 `current commit` + `task_id` + 证据摘要 + 已尝试的修法 + **明确的问题**。
  **禁止**贴密钥 / token / cookie / 凭据 / 账号隐私 / 大段原始日志。
  发帖：`gh issue comment 2 --repo hongweixiong0-star/winter-agent-os-v2 --body-file <file>`。
  ⚠ 这是 **public** 仓库，发帖前按上面红线自查一遍。
- **`SAFE_STOP` 是「让调度器跳过这条观测」的信号，不是"没事干"的兜底**（2026-09-17 学到。
  `Scheduler.select_next` 把**每一条 `skill != "SAFE_STOP"`** 的决策都放进候选并按优先级排序）。
  ⇒ **任何"恢复/清理"类动作（BACK、关闭弹窗）都会把一条死端提升成一个任务**，从而挤掉真正有活干的观测。
  实测：给"忙碌的研究队列"加了一次 BACK 之后，`test_multitask_scheduler` 立刻从选 index 3（每日）
  变成选 index 0（那条 BACK）。**规矩：恢复动作只对"命名 goal"发出；goal-less 的自动扫掠必须保持 SAFE_STOP。**
  （`brain._leave_or_stop` 就是这条规矩的落点。）
- **模板裁剪若覆盖"内容会变"的区域，识别的是内容、不是身份/来源** —— 这个坑已出现四次：
  `BTN_OPEN_DAILY` 的**角标**、训练按钮上的**引导手指动画**、奖励弹窗的**奖励格**、
  以及把**战力数字**裁进战力图标。**判据：问"这个控件的哪一部分会随状态变化"，把它排除掉。**
- **探针的匹配配置可能 ≠ 生产配置**：`SemanticWorldVision(max_distance=8)` 内部构造的
  `SemanticROIVision` 用的是 **8**，而独立 `SemanticROIVision(...)` 默认 **6**。
  用独立探针量读数会**偏严**，本轮差点据此误判"模板坏了"。量之前先确认用的是**生产那条路径**，
  或直接读 `w.semantic`。

## 操作者定规：任何 Capability 开工前先跑 **2 分钟 Reuse Check**（2026-09-17）

**两条禁令（原文）**：
> 禁止已经有成熟本地实现还跑去 GitHub 重新研究。
> 禁止外部已有成熟实现却自己摸 UI 两小时。

**顺序**：
1. **先查本地 V2 五件事**（≤2 分钟，**默认不查外部**）：
   `skill`（`v2_registry()` 的 id/action.target/state）·
   `brain route`（`grep` 目标名于 brain.py）·
   `verifier`（`LiveRuntime.VERIFIED_ATOMIC`）·
   `契约`（`skill_factory.GOAL_REQUIREMENTS` + `knowledge/skills/<X>_RESEARCH.md`）·
   `legacy evidence / knowledge`（`knowledge/`、`episodes.jsonl`、`dataset/truth_audit/`、`evidence/INDEX.json`）。
2. **本地已有明确路径 ⇒ 直接用本地，不查外部。**
3. **命中任一条才升级外部**：`MISSING` / 从未实现 / UI 未知 / 玩法未知 / 导航不知道 /
   连续失败 / **15~30 分钟仍未找到可靠实现**。
4. 升级顺序：**先查** `knowledge/external/external_capability_map.json` →
   有映射就**直接读它记的 GitHub `source_files`** → 没有映射才用 GitHub 搜索成熟 WOS 项目，
   并把结果**回写索引**（否则下次重查）。
5. 外部实现**只是 prior，不是结论**：`External → Adapt → Current Client Probe → Live Verify`。
   坐标/颜色/阈值**每一处都要在本客户端重量**；`DIRECT_REUSE_ALLOWED` 之外不复制源码与资源；
   README 里写的许可证不算证据（看 LICENSE + license API，缺席即 `UNVERIFIED`）。

**为什么写进宪法级记忆**：2026-09-17 一天内把训练与研究两个 BLOCKED 目标打成 LIVE，
**两次都在最后一步之前以为"要从零摸索 UI"，实际机制早已存在**（路由/verifier/契约/实测路线全在本地）。
反面案例同期也真实发生过：拿外部 Frostguard 的 VIP 入口坐标直接上真机，
结果打开的是**付费礼包**（硬阻断挡下）——外部坐标**是假设，必须先在当前客户端量**。

**全文**：`docs/ADDING_A_LIVE_ROUTE.md` §0；接管流程 `START_HERE.md` 第 5 步第 2 条。

## 展示层规则（GUI = 派生层，2026-09-17）

**GUI 不拥有状态。** `tools/control_panel.py` 只从既有事实源派生显示：
`capability_catalog.json` / Skill Registry / `episodes.jsonl` / `executor_backend.jsonl` /
`runtime_snapshot.json` / `escalation_queue` 的 fold / WorkBuddy jobs API。
**禁止为 GUI 新增 Manager/Registry/Scheduler 或第二套状态系统**；数字对不上就改那个文件。
唯一例外是**一个后台轮询线程**（HTTP 不能在 Tk 回调里等，会冻结窗口）。

**四层与状态栏**：`V2大脑 / MAA / MuMu / 游戏 / 页面 / AUTO / WorkBuddy / 时间`。
**Qwen、Vision 不得作为一级状态出现**（前者是可选离线提供者，后者是 MAA 的职责）。
**模型名只能作为 WorkBuddy 任务的二级信息显示**（从升级台账读回），面板内不得出现任何模型字面量
（`tests/test_control_panel.py::test_the_panel_names_no_model` 用 AST 强制）。

**状态词汇（硬规定）**：`未读取 ≠ 未知`。没人读过 ⇒ `未读取`；读过没读出 ⇒ `未知（识别中/原因未分类）`。
其余真实语义：`待刷新`（只有无 `recorded_at` 的导入声明）· `不可用`（T4/真钱）· `未解锁` ·
`已识别` · `可执行` · `执行中` · `等待`（普通天气停机：空邮件/队列忙/目标不可见）· `Blocked` ·
`Live Tried` · `Live Verified` · `Stable`。**禁止再用"未知 / 待识别"当占位符。**

**后端轴必须区分两种 ADB**：`preferred_backend=ADB`（技能未迁移，**按设计**）vs
`preferred=MAA 但 used=ADB` 或 `fallback_used=true`（**真降级**）。混为一谈会凭空造事故，
反过来漏报就是静默退化。MAA 单元格的口径：解释器缺 `maa` ⇒ `降级ADB`；缺其它必需模块 ⇒ `异常`。

**KPI 必须标注来源文件**，否则是没人会信的数字。

### 三条展示层实测（重复踩过就照这个办）
1. **Tk 会静默裁掉超出高度的 tab 内容**（1360×820 实测可用内容高 **638px**）。
   高页面必须走 `_scroll_area()`（canvas + inner frame），并**在真实映射窗口里量 `scrollregion`** 验证。
2. **大日志不要每 tick 全文解析**：`episodes.jsonl` 3.3MB ⇒ 单次全文 **34ms**。
   用 mtime 键控的**一次 pass**（per-skill 计数 + 时长 + 结果 + 失败直方图同遍），热态 ≈1ms。
3. **冒烟测试不得跑面板事件循环**：`__init__` 的 `root.after(1800, self.start)` 没保存 id、
   **无法取消**，且 `start()` 不看 `continuous` ⇒ 走过 1.8s 会真的拉起 worker。
   只 `update_idletasks`，测完即 `destroy`，并临时替换 `_enforce_retention` 以免剪掉证据。

### 运行期生效四条（2026-09-17 实测，重复踩过就照这个办）

1. **长驻进程的启动方式**：从「工具调用」里起的子进程，会在**该调用结束时被整棵回收** ——
   `DETACHED_PROCESS | CREATE_BREAKAWAY_FROM_JOB` 也照死（探针先写 `alive` 再消失），
   PowerShell `Start-Process` 同理。长驻 GUI/AUTO 只能以**长驻任务**形态起，或由操作者双击
   `Start-Winter-Agent-V2.cmd`。**不要**把「fire-and-forget 子进程」当成守护进程。
2. **「代码已生效」的判据是进程，不是文件**：长驻面板吃不到修复，必须重启。
   验证方式是看**它自己的进程命令行**（解释器 + cwd + 脚本），不是看磁盘上的文件。
   注意 venv 下 `python.exe` 会重定向到基础解释器（两级进程），**那是正常的**，不是解释器漂移。
3. **MAA 的生产判据是 episode 的 `capture_backend`**（`MAA_MUMU_EXTRAS`），不是「能 import maa」，
   也不是面板单元格。`executor_backend=ADB` 与它并不矛盾：技能不在 `backend_routing.json` 里就走历史
   ADB 路径，MAA 在此是**观测/设备层**（`run_live.py` 换掉 `observation_device`）。
   账本同名 `capture_backend` 含义不同（`REVIEW_REQUESTS.md` 已登记），引用时要说清是哪个来源。
4. **网关凭据必须与「正在运行的网关」一致**：会话环境里的 `CODEBUDDY_GATEWAY_PASSWORD` 可能是
   网关首次启动的随机值 ⇒ 面板 `reconcile` 恒 401、队列的 in-flight job 永远推不动。
   症状是面板显示 `不可用 / AUTH_REJECTED`，而网关本身是好的。凭据只进环境变量（用户级），**不进仓库**。

### 启动语义与两处静默失效（2026-09-18 实测）

**启动 GUI = 自动运行 + 自动开发**：`_maybe_autostart`（只在 `main` 里调用一次）按
**操作者意图 → 真实 preflight → AUTO** 顺序决定。preflight 分 **core**（解释器 + MuMu 设备）
与 **aux**（WorkBuddy Gateway）：core 失败**拒启**并按 60s 周期重试，gateway 失败**只标不可用**
（「网关异常不得阻止游戏 AUTO」已固化为 `CORE_SECTIONS` / `AUX_SECTIONS` 两个常量）。

- **操作者意图必须落盘**：`config/control_panel_state.json` 的 `operator_intent`
  （RUNNING/PAUSED/STOPPED）跨 GUI 重启保持，只有显式「开始」清除；状态文件必须**合并式写入**，
  否则任务选择与意图会互相擦除。
- **关窗要杀进程树**：面板持有的是 **venv stub**，真身是它的子进程（`taskkill /T`）——
  只 `terminate()` stub 会留下**孤儿 AUTO worker**继续点游戏。

**两类「看起来在工作、其实什么都没做」的失效（都会静默）**：

1. **无命名目标 + 叶子页 = 死端**：AUTO 不传 `--goal`，目标发现**只读当前页**；
   `_leave_or_stop` 在 `current_goal is None` 时**故意不离开**（免得挤掉真有活的观测）
   ⇒ 停在 RESEARCH/TRAINING 且队列忙时**每轮零动作**。修：运行时在
   「discovery 为空」时退一步离页（`RuleBrain.leave_terminal_page`）。
2. **解析要求「整行是 JSON」= 恒失败**：MuMu 连接行**紧贴**结果 JSON 同一行、无换行
   ⇒ `parse_runtime_result` 每轮返回 `{}`，所有 `stop_reason` 决策链/摘要/升级载荷
   沦为死代码，界面只说「暂无结构化结果」。**遇到「暂无结构化结果」先怀疑解析，别怀疑大脑。**

---

### 调度不变量：会的自己做，不会的交给开发，学会以后自动交还（2026-09-18 实测）

用户把它定为**永久不变量**，适用于所有 Goal。实现方式＝四块最小接线，**不新增第二套
Scheduler / Registry / WorldState / 触发系统**，也不提高 repair budget 掩盖失败。

**核心分离：`Action Progress` ≠ `Goal Progress`。**
`GoalState.distance`（每个 Goal 自己「还差多少」）在 `goal_library` 一处定义，
每条 episode 记 `goal_progress`。`None` ＝ 该 Goal 在这两帧上不可观测，**不是**停滞。
反面教材（实测）：58 条 `SCAN_MAP_FOR_BEAST` 全部 `verifier_ok=True`、体力 457 二十分钟
不动——「滑动落地了」被当成「Goal 在推进」。

**`winter_agent_v2/capability_gate.py` 是投影，不存任何东西。**
输入＝既有升级台账（能力态：`DEVELOPMENT_PENDING` / `COOLDOWN` / `BLOCKED` /
`LIVE_VERIFIED`）＋ episode 流（同一 Goal 连续**多少轮**没有推进）。
规则顺序：① 正在被开发的同一失败路径（经 `capability_skill_map.json` 把该 Goal 真正用过的
skill 映射回能力）；② 组合语义——`SEQUENCE` 任一不可用即退让，`ANY_OF` 必须**全部**不可用；
③ 连续无进展（按**轮次**计，不按 episode 计；一轮里多步算一次尝试，且**没有尝试过该 Goal
的轮次不清零**——否则退让会与重选交替出现）。

**重新进入条件（禁止 30 秒软循环，也禁止永久饿死）**：`DEVELOPMENT_PENDING` 持有到任务
结论变化；`COOLDOWN` 到队列自己的期限；预算耗尽每 3 小时探一次；停滞路每 30 分钟探一次；
reload 待办时全部持有。探针窗口**以最后一次真实尝试为基准**；从未尝试过的路径不失效。

**退让必须外泄**，否则队列不知道它发生过（退让的 Goal 不产生失败步骤）：运行时把它写进
snapshot、打印出来、并作为候选交给**既有**升级管线，复用 `REPEATED_LIVE_FAILURE`
条件与既有节流（去重 / 并发上限 / 单签名预算 / 冷却）。

**归因（RR-004）**：只有「跑着**与派单时不同的树**」的 verifier 通过 episode 才算证明
某个开发任务学会了能力。episode 现在带 `repo_revision`（每轮一个进程，读一次），
对账行带 capability / failure_signature / job_id / before_version / after_version /
live_verify_episode / reload_id。**并发成功与历史成功都不算学会。**

**静默缺陷清单（都吃过一次）**：`RuntimeSnapshotStore.update` 会**静默丢弃未声明字段**；
`new_live_episodes` 会把 job 还在 WORKING 时跑的旧代码 episode 算成学习证据；
不透明 id（job_id）不能当时间排序用。

---

### 「已创建」不等于「会到达」：升级队列必须有消费者（2026-09-18 P0 实测）

**症状**：`DISPATCH_GATHER_MARCH / UNKNOWN_UI` 记录创建后 54 分钟仍是 `NEW`，Job ID 未提交，
网关正常。队列 `NEW=2`。

**根因**：那条记录**只有一行台账**（`escalation_created`），行内写着
`dispatch=CONCURRENCY_WAIT … already used by a7ce58f0`——当时正确，之后**再没有任何东西重新看过它**，
因为候选只从「产生它的那一轮」派生。⇒ **`NEW` ＝「被看到过一次」，不是「会到达 bridge」。**

**永久规则**：
1. **记录必须有消费者**：每轮把 `NEW`（已创建未派单）与 `QUEUED`（已决定、网关不可达）按**最旧优先**
   重新交给**同一个节流**（去重/并发上限/单签名预算/冷却）。消费者不得越过当初拦住它的规则。
2. **消费者要判断，不只是派单**：能力在记录创建后**已被真机证明**（verifier 通过的 episode、
   带 `recorded_at` 与截图）⇒ 记录直接结算为 `DONE / LIVE_VERIFIED / released_by=self_proven`，
   写明 episode 与 revision；`live_improvement=false`、`repair_used=false`（**没有 job 就不许领功、不许花预算**）。
   否则一个真的 backlog 与一个幽灵 backlog 无法区分。
3. **`STOPPED` 也是终态**：网关把 "stopped" 映射为终态，而 fold 只认 `DONE/FAILED`
   ⇒ 被停掉的 job 永远停在 `WORKING` 并占住唯一并发槽，**同一类停滞的另一个入口**。
4. **只写不 fold 的字段等于没写**（`task_type` 栽过一次，`dispatch_reason` 又栽一次）。
5. **GUI 每个状态一个词**：`NEW=待提交`、`QUEUED=排队`、`SUBMITTED=已提交`、`WORKING=开发中`。
   把「已创建未派单」显示成「排队」是在宣称有 job 在等——**没发出去的东西不许说成排队中**。
6. **先测量再派单**：用户的前提「消费链没运行」对了一半——链确实缺（已修），但那两条记录
   **不是真实缺口**（`DISPATCH_MARCH` 创建后真机通过 4 次）。派开发任务去做已经能做的事＝**制造工作**。
   任何「缺失能力」在派单前都要用 `new_live_episodes(...)` 问一次「创建之后它到底成功过没有」。
