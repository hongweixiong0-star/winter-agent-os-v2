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
- **`state_before` 是 runtime 的「信念」，不是像素（2026-09-20，我自己读错过一次）。**
  19 条连续失败的 episode 里 `state_before` 都写着 `page=POPUP, popup=INTEL_REWARD`，
  我据此断定「调度器用别的域的关闭技能去关弹窗」—— **错的**。打开 PNG 看到的是一张**干净的邮件收件箱**
  （标题「邮件」、战争/联盟/系统/报告/收藏、可领取奖励列表），屏幕上一个弹窗都没有；真因是视觉层**误报**（下一条）。
  ⇒ **诊断任何 UI 缺陷，先打开那一帧看**。把「世界状态是错的」读成「动作是错的」，会让人去修一个没坏的东西
  （本轮已有另一个 Job 据此启动）。
- **`POPUP_INTEL_REWARD_TITLE` 的阈值 22 把邮件收件箱吃了进来（2026-09-20，同类型第 6 次）。**
  同一帧重跑生产分类器：`PAGE_MAIL d=0.0`、`TAB_MAIL_SYSTEM_ACTIVE d=0.0`、`BTN_MAIL_TAB_ALLIANCE d=0.0`、
  `BTN_MAIL_CLAIM_ALL d=4.0`、`STATUS_MAIL_TAB_BADGES d=4.0`、`BTN_MAIL_TAB_REPORT d=6.0`，
  而 `POPUP_INTEL_REWARD_TITLE d=20.0 thr=22.0` ⇒ **六个强邮件信号输给一个踩在 91% 阈值上的弹窗信号**，
  帧被判成 `POPUP/INTEL_REWARD`。缺陷行 `vision.py:1144-1147`，它在 `PAGE_MAIL` 分支（`:1630-1639`）**之前**求值，
  负向对照只挡地图页（`BTN_RESOURCE_SEARCH_*`）；阈值在 `vision.py:265`。该模板 ROI（x .30 w .40 y .215）
  **横跨邮件列表行**，行内容逐封邮件变化 ⇒ 又是「裁剪框盖住了会变的内容」。
  **为什么一直没抓到：`tools/probe_reward_popup_gate.py:45` 的 `SIGNALS` 把这个语义排除了** ——
  「零误报」的结论从未覆盖真正在触发的那个分支 ⇒ **探针的信号清单本身要有覆盖断言**，
  否则它证明的只是「我没测的那部分没问题」（同「测试从未走到那个守卫」）。
  代价：`DISMISS_INTEL_REWARD`（09:51–12:04，35 次）与 `DISMISS_MAIL_GENERIC_REWARD`（04:24–04:37，29 次）
  是**同一个 bug 的两个技能名**，约 70 次失败、约 2 小时白跑。
- **占空比信号不能用固定节拍采样（2026-09-20，Soak 自检误报）。**
  `auto_gameplay` 读的是**每轮全新进程**的线程标志（`control_panel.py:2194-2202`：
  `mode=="AUTO" and (runtime_thread_alive or scheduler_loop_alive)`），一轮里只有约 4 s 为真（~10% duty），
  而采样节拍 ~12.5 s ⇒ **拍频锁相**：40 个样本全 False，而同一窗口的证据流里有 **13 条已完成的轮次**。
  ⇒ 采样前先算「信号占空比 × 采样周期」；正解是改用**单调计数**（完成轮数）作为更强证据，
  **不是**放宽判据（旧信号可以在零轮次时为真，计数器不会）。

### 架构：正式 AUTO 的阶段链（2026-09-20 体检）
- **正式 AUTO 的"一轮"不是一次 Goal 选择，而是 `tools/control_panel.py:4644` 起的阶段链**：
  `邮件 → 日常 → 联盟 → 探险 → Intel → 野怪 → 采集`，每个阶段一个 `run_live.py --goal <STAGE>` 子进程。
  ⇒ 面板层选"任务族"，`GoalLibrary`/`RuleBrain` 在 run 内选具体 Goal。**两层不是重复实现。**
- **阶段只在「被认可的成功 stop_reason」上交棒**（`:4713` 起的 `stop_reason == "mail_all_clear"` 等）。
  ⇒ **一个失败阶段永久占位，后面所有阶段（含真正消耗体力的 Intel / 野怪）永远轮不到。**
  2026-09-20 01:00–04:37 就是这样烧掉约 2 小时。**诊断"任务长期饥饿 / 体力不消耗"先看这里**，
  不要先去怀疑调度器或 Goal 定义。
- 旧链 `_run_worker`（`:4726`）**无任何生产调用者**，是不可达的重复实现，与现役链**不混用**；
  唯一引用是 `tests/test_runtime_interpreter.py:183` 断言其源码文本。
- **打野只扫不派**：`SCAN_MAP_FOR_BEAST` 396 成 / `BEAST_HUNT` 0 成；**免费体力领不到**：
  `CLAIM_FREE_STAMINA` 10 成 / 235 败。体力积压是**四道阻断叠加**，不是"忘了消耗"。

### 控制面重载与奖励弹窗（2026-09-20 实测定案）
- **`panel_restart.py:290` 的 `taskkill /PID <panel> /T /F` 会杀掉重启助手自己。** `/T` 跟随**父进程关系**，
  而助手是**面板自己派生的**子进程 ⇒ 它在 tree kill 中自杀，`cmd_start()`（`:391`）**永不执行**，
  面板**停掉后不会回来**。`_ensure_gateway_after_stop` 的 docstring 早已写明这个机制（2026-09-18 实测），
  **只给网关处理了**。两次实测同形（pid 2272 / 19612），其中 19612 是**操作员从桌面入口**启动的
  ⇒ **不是开发宿主限制，是产品缺陷**（我先前那次归因已撤回）。
  `0792cb8` 已**停用**自动重载（改提示人工重启）；**真正的修法是让接替者由不在待关闭进程树内的机制驱动**
  （WMI `Win32_Process.Create` / 计划任务），或"先起新面板→按 pid 不带 `/T` 停旧面板→单独处置其 worker"。
- **在加载了 `0792cb8` 之前启动的面板仍在运行期间，不要提交 `tools/control_panel.py`**，否则它会再次自杀。
- **五个 `DISMISS_*_GENERIC_REWARD` 的动作目标其实是同一个**（`POPUP_GENERIC_REWARD_HEADER`，`skills.py:169-174`）
  ⇒ `brain.py:397` 的 `TRAIN`/`RESEARCH` 白名单**在机械上没有保护任何东西**，它只限制这一个行为何时被允许。
  ⇒ **"关掉一个自称「点击任意位置退出」的弹窗"不是猜测**，别再用"不许猜"当理由把弹窗留在屏幕上。
- **执行器能传坐标**：`Action("SWIPE", "0.50,0.62,0.50,0.30", …)`（`skills.py:426`）在生产跑通 396 次。
  ⇒ "执行器只支持 `TAP_SEMANTIC`、无绝对坐标" **对点击成立，对坐标输入不成立**；缺的只是**一个 tap 到固定点的动作种类**。
- 弹窗类模板**卡在阈值上**是常态，不要只看"是否命中"：`POPUP_GENERIC_REWARD_HEADER` 在本日那张弹窗上
  **恰好 = 16 = 它的门**；`BTN_CLOSE` 在同一帧 **28 ≫ 6**（ROI 落在右上空白处）⇒ `CLOSE_POPUP` 在那里必然失败。
  **量原始距离**（`max_distance=999` + `find`）是唯一能分辨"差一点"与"对着空地"的办法。

### 测试与验证
- **咬合验证必须改「调用点」，不能只改被调的纯函数（2026-09-20，我差点交付 green-but-useless 测试）。**
  给"零进度 deferral 的原因措辞"写测试时，第一版只直接调 `_no_progress_reason()`；
  把**网关里的调用点**改回旧措辞后，**10 个测试全绿**——测试从未覆盖生产路径。
  改成走 `CapabilityGate._no_progress_deferral()`（生产真正用的方法）后，同样改回调用点 ⇒
  **2 failed / 12 passed**，报错原文即缺陷本身。⇒ 「证明测试会咬人」时，
  **要恢复的是生产代码里被替换掉的那一行**；只测 helper 的测试无法发现"生产已经不再调用它"。
- **干净 worktree 才是回归基线；脏工作树不是（2026-09-20）。**
  同一个 `tests/test_live_runtime.py`：干净 HEAD worktree 上 **8 passed**，live tree 上 **2 failed**。
  差异来自**未提交的 `knowledge/goals/*.json`、`knowledge/game/capability_catalog.json`、
  `config/policy_state.json`**（runtime/goal 会读它们），与代码无关。
  ⇒ **工作树脏时，runtime / goal 类测试不能当回归信号**；判定"这是不是我的回归"用
  `git worktree add --detach <tmp> HEAD` 的干净树做 A/B。注意 worktree **不含被 gitignore 的
  `dataset/`**，只适合跑不依赖 dataset 的测试；全量基线必须在干净 live tree 上取。
- **一个 worker 的 diff 不能当已验证的交付（2026-09-20）。** 一个 worker 被 429 打断时留下了
  未提交、未跑过任何测试的 `runtime.py` + `capability_gate.py` 改动。接管后逐个核对：
  调用点收敛性、8 个行为用例、A/B 排回归、补测试并证明其咬合——结论是改动正确，
  **但"diff 看起来对"和"已验证"之间的距离，正是这类事故会吞掉的距离**。

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


---

### 10:05 P0 闭环审计：四处真断点，其中一处是「用失败当修复证据」（336437f…5ba83b3）

**队列有消费者但没有时钟。** `observe_run` 只挂 AUTO 轮次尾部；轮次是分钟级
（空闲时 10 分钟），AUTO 停/暂停时永不执行 ⇒ `NEW` = 「被看到过一次」。
修：`EscalationQueueAdapter.pump()`（与 `observe_run` 共用 `_drain`）+
`control_panel.QueuePump`（面板常驻守护线程，**随窗口而非随 AUTO 启动**，
STOPPED 才停、暂停不停）+ `pump.json` 心跳（线程里跑的东西从进程外看不见）。

**真正严重的那个：`LIVE_VERIFIED` 被授予了「失败本身」。** job 2934e9cd 以
「6 条 verifier_ok + 树有变化」被判 live improvement，而那 6 条的 `goal_progress`
**全是 False**，签名恰恰是 `NO_GOAL_PROGRESS`。新增 `PROOF_IS_GOAL_PROGRESS`：
**证明必须是缺失的那次测量本身**（`require_goal_progress` 只认 `is True`，`None` 是未观测）；
释放路径同一把尺；台账用文字写明为何拒绝。已 `--correct` 撤回为 `TEST_PASS`。
**遗留**：模型战绩里那条 `live_improvement=true` 未回改（写入时判定），live 列偏高。

**超时 job 永久占住唯一并发槽**：`max_concurrent_jobs=1` 且从不取消。
时间盒此前只是提示词里的一句话；现为 `EscalationPolicy.job_timebox_minutes` 单一来源。
**只在 `pending()` 非空时回收**——否则就是按点杀掉认真干活的 agent。

**AUTO 在等 WorkBuddy（用户明令禁止）**：`evaluate` 因 `active_jobs > 0` 最多延后 900 秒。
现：活动 job **只报告不等待**；结算窗口由 `newest_write(ROOT)`（真实写入 mtime）度量，
上界 20 秒且永不为一个 job 等待。

**凭据「存在但是错的」被读成「网关不可用」**：同一时刻 shell 43 字符→401、
用户环境 24 字符→200。`gateway_password()` 回退 `persisted_password()`（HKCU\Environment，
仍是环境变量）；`_request` **只在 401** 用持久化值重试一次并采纳。

**操作铁律（本轮用事故换来的）**
- **绝不用模式匹配进程表来杀进程**：`control_panel|run_live` 会匹配到 WorkBuddy 桌面端、
  它的 node、以及我自己所在的 shell（它们命令行里也有工作区路径与 `control_panel.py`）。
  用 `tools/panel_restart.py`（面板自写 pid；venv `pythonw` 是 stub，真正在跑的是子进程；
  有轮次在跑就拒绝停止；启动后核实存活）。
- **同一文件一轮只发一个 Edit**：并发两个 Edit 会互相覆盖，且**报成功**。
  `observe_run → _drain + pump`、`_auto_development_allowed()` 都曾被静默覆盖，靠测试才发现。
- **长驻 GUI 必须以长驻任务形态启动**：工具调用结束时整棵进程树被回收，
  `DETACHED_PROCESS` 也不行（实测：+19s 写了一次心跳，+25s 就没了，无崩溃无日志）。

**未完成**：设备租约（Single Device / Single UI Owner）、`LIVE_VERIFY_PENDING`、
统一 trace_id 落字段、`无人值守闭环` GUI 状态；P0-D/E/F 未证且不得伪造。


## 10:25 逻辑修正版落地：版本生效顺序 + 设备租约（309f7c6 / dbf4b8c）

用户发来「自主开发闭环逻辑修正版」，覆盖此前相关指令。**最重要的一条是 §6：顺序错了**。
本轮按 §28 从当前断点向后打通。

### 一、§6/§7：**新版本未生效就判 LIVE_VERIFIED**（309f7c6）

原阶梯 `CODE_CHANGED → TEST_PASS → LIVE_VERIFIED → Reload` 把功劳记给了一个**从未加载过
这段代码的进程**。修正后：
- `new_live_episodes(..., after=)`：证明用的 episode 必须**记录在任务结束之后**——每一轮都是
  新进程从磁盘 import，所以任务结束后的第一条 episode 才是第一条「跑着新代码」的。
  仅「树不同」不够，它同样匹配**中间态**（agent 改到一半的树）。
- 新结局 `VERSION_ACTIVATION_PENDING`：树变了 + 接线绿灯 + **还没人跑过它**时返回这个，
  并用文字说明，而不是宣称验证通过。
- 新状态 `LIVE_VERIFY_PENDING`：**既不在 `ACTIVE_STATES` 也不在 `TERMINAL_STATES`**。
  不在 active：没有 agent 在工作，不能占住唯一并发槽（这个亏已经吃过一次）；
  不在 terminal：下一轮还要重新测量它。每轮重测直到有 episode 关闭它。
- **§4 的死锁在源头关掉**：gameplay 不准重入失败路径 + validation 没有别的执行者 ⇒
  证明永远产不出来。闸门现在**放行**「版本等待验证」的那个 Goal（用户原话「允许 A 进行受控
  真机验证」，而本项目唯一的执行者就是 V2 自己的循环），但仍拒绝 job 正在 WORKING 的路径。
  两个方向都有测试。
- **生效边界是网关的 `firstTerminalAt`**，作为 `version_since` 落到记录上供重测复用。
  两种形状必须区分而没区分：该字段是**毫秒整数**，记录的其它时间是 datetime——把 int
  传进 datetime 的位置会让这一级**静默永不触发**。新增 `_from_millis()` 并写明理由。
- §21：`LIVE_VERIFY_PENDING` 在 GUI 显示为「● 等待真机验证」/「等待真机验证」，
  来自 view 里它**自己的列表**（它原本既不在 current 也不在 pending_verify，等于看不见）。

### 二、§8/§9/§19：设备租约 = 单一 UI 拥有者（dbf4b8c）

`winter_agent_v2/device_lease.py`：一把锁，不是生命周期。一个文件、一条记录、一个谓词，
**里面不运行任何东西**。
- `acquire` 拒绝第二个 owner 并**点名**（"GAMEPLAY holds it: GATHER"）。拒绝本身就是功能。
- `request` 只记「请求」，不夺取 —— 这才让「等待安全点」成为真状态而不是推断。
- **`release` 第一版并没有真的归还**：已释放的记录留在文件里且 `released_at` 已设，
  `holder()` 继续返回它 ⇒ §15 会变成纸面归还。被「acquire→release→再 acquire」的测试抓到。
- 过期租约不是持有者（§11 崩溃的验证不得锁住 MuMu），窗口显示 `恢复AUTO`。
- `renew` 保持租约**自己的时长**，不会把 60 秒的租约悄悄升成 15 分钟默认值。
- 审计行带全 §19 要求的字段（trace_id/job_id/capability_id/owner/acquired_at/released_at/
  reason/result），追加写，请求与授权不会对不上先后。
- 运行时守卫放在**一轮循环的第一件事**（截图之前），因为那是唯一「没有输入在飞」的时刻；
  stop reason `device_leased_for_development` 属于**非升级条件**（§2 A：设备归验证所有是
  条件不是能力缺口，升级它等于为「有个开发任务在跑」花掉一个开发任务）。
- GUI 增加「设备所有权（Single UI Owner）」行，四个词从租约文件读，不硬编码。

### 三、并发写入者与我自己的失误

- 在飞的开发任务 **0440cd38** 与我修同一个缺陷（退让派生的签名把**失败类型填进了能力槽**），
  它正在改 `capability_gate.py` / `escalation_queue.py`，并把签名改成位置式 + 锚定失败类型。
  我没有与它争文件，只在相同提交里如实署名（同一文件无法按路径分开）。
- **我又犯了一次同类错误**：把 `first_terminal_at`（毫秒整数）当成 datetime 传进 `settled_at`，
  导致新加的生效判定**静默不触发**；测试只暴露成「DONE 而不是 LIVE_VERIFY_PENDING」。
  另外一次 Edit 用错了 old_string，把 `reconcile` 的头部缩进改坏（立刻发现并复原）。
  **教训固化：跨模块传时间字段前先确认是 ms 还是 datetime；一个文件一轮只发一个 Edit。**

### 四、未完成（明确点名）

**取租约的一方还没写**：锁、让路、上报都是真实且有测试的，但**没有任何东西替
`LIVE_VERIFY_PENDING` 记录去申请租约**。这是同一条 trace 上的下一环，也是目前没有 live lease
可展示的原因。此外仍未做：统一 `trace_id` 落字段、`无人值守闭环` GUI 状态、
§2 的失败分类落成代码（环境失败 → DEFER 不升级，目前靠 `NON_ESCALATABLE_STOP_REASONS` 兜住一部分）。


---

---

### 10:2x 一条失败类型被当成 capability 派了单（job 0440cd38 带回的修复）

**症状**：台账里出现 `NO_GOAL_PROGRESS|NO_GOAL_PROGRESS|` —— 一个**失败类型**被当成 capability，
真的派出了一个开发 job（就是本轮的 0440cd38）。同一条墙在 00:45 已经以
`SPEND_STAMINA_ON_BEAST|NO_GOAL_PROGRESS|SCAN_MAP_FOR_BEAST` 登记过 ⇒ 去重键被绕过。

**根因**：`capability_gate._no_progress_deferral` 拼签名时把空字段过滤掉了（`if part`），
于是 `"|NO_GOAL_PROGRESS|SCAN_MAP_FOR_BEAST"` 塌成两段，`escalation_queue` 再按下标取值
⇒ `parts[0]` 正好是失败类型。而 capability 为什么会是空：`AVOID_STAMINA_WASTE` 这条停滞路线
**只跑 `SCAN_MAP_FOR_BEAST`**（导航步，`capability_for_skill` 解成它自己），
与 composition 的三个 capability 不相交。

**修**：`_route_capability` 增加第二跳 —— 用 goal **自己声明的** skills 过
`capability_skill_map.json`（`BEAST_HUNT → SPEND_STAMINA_ON_BEAST`，与 00:45 那条正确签名一致）；
签名恒为三段 `capability|failure_type|skill`，空就是空；`candidates_from_run` 改为
**按失败类型锚定**解析（不再丢空字段），且 capability 为空时**不建单** —— 编造名字正是这次的错误。

**教训（可复用）**：**「位置即语义」的字符串，禁止先过滤空字段再按下标解析。**
被丢弃的空位会把后面的字段整体左移，于是「没有值」变成「有一个错的值」。

**真机证据**（`dataset/truth_audit/no_goal_progress_20260918/`，`report.json` + `key/` 4 帧）：
真机 `run_live.py --goal BEAST_HUNT` 打出
`[schedule] deferred AVOID_STAMINA_WASTE -> DEFERRED on SPEND_STAMINA_ON_BEAST`；
3 条 `SCAN_MAP_FOR_BEAST` episode `verifier_ok=True / goal_progress=False`，体力恒为 457。

**发现但本轮没改（明确记下）**：episode 的 goal 归属取自 `best_goal`（当前可选中的最高优先级 goal），
而不是**这条路线真正服务的 goal**（`runtime.py:912`）。所以目标 goal 已被 defer 时，
野兽路线的 episode 会记到 `KEEP_MARCHES_PRODUCTIVE` 名下并写 `goal_progress=False` ——
一个它根本推进不了的 goal 因此在攒假的「无进展」streak，迟早被错误地 defer。
改它会动到全项目覆盖率与所有 streak 数字，本轮只报告不擅动。

## Capability Bootstrap / Preload：第二条能力增长路径（2026-09-18 操作者定规 + 实现）

**操作者定规**：不要等 V2 撞到每一个不会的功能才开发 —— 持续扫描现有 capability_catalog，
把 MISSING / NEVER_TRIED / DEFINED 但无实现 / 有 External Prior 但未实现 / 有 Legacy·内部资产但未接入
自动变成 Bootstrap 候选，提前备课。于是形成两条增长路径：
**PRELOAD BEFORE ENCOUNTER**（预载）+ **LEARN FROM REAL FAILURE**（既有的失败驱动）。

**两条硬边界（写进代码，不靠自觉）**

1. **Bootstrap 完成 ≠ LIVE_VERIFIED。** 上限是 `READY_FOR_LIVE_VERIFY`
   （`BOOTSTRAP_MAX_LIFECYCLE` / `FORBIDDEN_LIFECYCLES` / `lifecycle_allowed()`，被 check_wiring 钉住）。
   真机验证仍走统一 Development Validation：CANDIDATE → LIVE_VERIFY_PENDING → 设备租约 →
   新版本生效 → V2 统一 Executor（MAA first）→ 真机 → Verifier + Evidence → LIVE_VERIFIED → 正式能力池。
2. **不建第二套 Registry / 第二套开发系统。** 它是**投影 + 简报生成器**：
   读 `knowledge/game/capability_catalog.json`（扫描输入）、`skill_factory.PRIORS` /
   `dataset/candidate/*.json`（既有候选家）、`capability_gate.capability_states`（在飞状态）、
   `knowledge/external/external_capability_map.json`。**只写一件事**：经
   `EscalationQueueAdapter.preload()` 往**同一个台账**追加一条 `origin="bootstrap"` 的记录，
   由同一个 `decide()` 限流、同一个 bridge 派发。`PRELOAD` 是**来源**，不是第二条流水线。

**结构**：`winter_agent_v2/capability_bootstrap.py`（扫描 / 分类 / 排序 / 七字段简报 / 闸门 / 两份 ladder）

- 五个分类：`MISSING` / `NEVER_TRIED` / `DEFINED_NO_IMPLEMENTATION` /
  `EXTERNAL_PRIOR_UNIMPLEMENTED` / `LEGACY_ASSET_UNWIRED`
- 知识来源阶梯（顺序即优先级）：`V2_EVIDENCE → LEGACY_ASSET → EXTERNAL_MAP →
  OPEN_SOURCE_UNINDEXED → GAME_DB_WIKI → SELF_EXPLORATION`（最后才是自行探索）
- 开发优先级阶梯（tier 间距 60 分 > 所有加分之和，所以并列只影响**同一档内**的顺序）：
  `REAL_GAP(100) > UNLOCKED_MISSING(70) > HIGH_FREQ_FREE_VALUE(50) > OTHER_UNLOCKED(30) > FUTURE_LOCKED(10)`
- "已解锁"**只按证据**判定：同一 category 里有 `EXISTING` 行或 `live_attempts>0` 才算观察到；
  否则诚实写 UNKNOWN → 落到 FUTURE_LOCKED。**不放宽成"Wiki 说开放了就开放了"。**
- 闸门（`preload_gate`，纯函数，五个具名拒绝，顺序有意义）：
  `NOT_ARMED_MAIN_LOOP_P0` → `REAL_GAP_WAITING` → `AGENT_SLOT_BUSY` → `DEVICE_LEASED` →
  `REALTIME_ACTIVITY` → `NOTHING_TO_DO`
- **自动启用**：读主闭环自己的阶梯 `dataset/truth_audit/p0_loop_20260918/P0_LOOP_STATUS.json`，
  六个 stage 全部 `PASS` 才 `MAIN_LOOP_P0_PASS`。`config/bootstrap_arm.json` 是**显式**人工开关，
  记录 `armed_by`/`reason`，永不静默。当前实测未启用（P0-A/E=PARTIAL，P0-D/F=NOT PROVEN）——
  这是操作者要的顺序，不是故障。
- 工具：`tools/bootstrap_scan.py --status | --top N [--briefs] | --capability CODE | --write | --preload-once`
- 面板：`QueuePump.PRELOAD_EVERY = 20`（30 秒 × 20 = **10 分钟**，比消费者稀一个数量级），
  `_preload_tick()` 写在 `learning/control_panel/pump.json` 的 `preload_note` 里 ——
  **"机制在休息，原因是 X" 必须是可查状态，不能是"什么都没发生"**。

**两条可复用教训（本轮真踩到）**

1. **"设计完整"本身就是候选** —— 所以「七字段齐 + verifier 绑定 + 语义已注册」的能力
   一定已经在 `dataset/candidate/` 里有草稿 ⇒ 它会走 `_in_flight` 的 `CANDIDATE` 分支被拒。
   想让 READY_FOR_LIVE_VERIFY 可达，Recovery 必须来自**外部卡片**而不是本地草稿。
   这不是绕路：一个已经写完的设计**就是**流水线里的候选，重发简报属于制造工作。
2. **"信袋里的词"不是"有资产"** —— 用整套 corpus 做 token 包含判定（`{READ,BUILDING,LEVEL}`
   散落在不同文件名里）几乎永远命中，`LEGACY_ASSET_UNWIRED` 会退化成噪声（实测 116 → 收紧到 20 行）。
   正确判据是**所有 token 必须出现在同一个文件名里**（`_contained`，按最稀 token 开桶查）。
   同理，相近技能的草稿（`CLAIM_REWARD` ↔ `CLAIM_FREE_REWARD`）只能当**假设**：
   它可以把字段填上，但 `exact=False` 时永远不许把 plan 抬到 DRAFT / READY。

**测试**：`tests/test_capability_bootstrap.py`（60 项）+ `tools/check_wiring.py` 9 条 `preload:` 断言。

## 主路线变更：Knowledge Preload → Capability Preload → Live Calibration → LIVE_VERIFIED（2026-09-18）

**操作者定稿**：能力扩展的**主路线**不再是「跑起来撞到不会 → 从零开发」。改为
**能提前知道的先知道、能提前准备的先准备，真机只负责校准和证明，
运行时 Gap 降级为补漏与自愈**（应对未知内容 / UI 变化 / 游戏更新 / 预装错误 / 重复真机失败）。
四条永久原则：`PRELOAD BEFORE ENCOUNTER / CALIBRATE ON REAL DEVICE / LEARN FROM REAL FAILURE /
VERIFY BEFORE TRUST`。

### 一、知识必须落盘（`winter_agent_v2/knowledge_preload.py` + `knowledge/preload/`）

**「说明书只需要认真读一次」如果只靠提示词就是空话**，所以知识是文件：
`knowledge/preload/<CAPABILITY>.json`，含操作者点名的全部字段
（preconditions / navigation / page_semantics / recognition / actions / success_state /
failure_states / verifier_prior / recovery_prior / resource_rules / risk /
client_specific_notes / live_calibration_status）+ **每个字段**的来源与信任级别。

- 信任阶梯 `PRIOR < UNVERIFIED < OBSERVED < CONFIRMED`（`CONFLICT` 是未决问题，不是低分）；
  **记录的强度 = 它最弱那个字段**（`weakest_field_trust()`）。
- 九级获取顺序（`ACQUISITION_ORDER`）：1-5 级在本机（V2 已验证资产 / 内部 Knowledge /
  Episode 证据 / Legacy 资产 / Failure Pattern），**本地够用就禁止联网**（§四）；
  不够才按**缺失字段**生成**具体问题**（"入口在哪里 / 页面如何识别 / 操作顺序 /
  成功状态 / 恢复方式 / 资源规则"）做定向研究，而不是把整个游戏重查一遍。
- **去重靠问题**（`needs_research`）：同一 `能力 + 问题 + 版本`已有够高置信度答案就不得重查；
  只有新版本 / UI 变化 / 真机冲突 / 重复失败 / 关键字段缺失才重查。
- **真机只校准差异**：`prior_vs_live_diff` 对比先验与真机，`calibrate()` 只覆盖不一致的字段，
  旧先验写进 notes（`PRIOR_VS_LIVE_DIFF`）；**禁止因为一次失败推翻全部先验**。
- **`confirm_from_live()` 是唯一升到 CONFIRMED 的入口**，只由 reconciler 在真机 episode +
  verifier PASS 时调用。离线测试 / Replay / agent 自述都到不了这里。

### 二、常驻循环（`KnowledgeBootstrapController`，同一模块）

`SCAN → SELECT → LOCAL KNOWLEDGE CHECK → TARGETED RESEARCH（仅在缺知识时）
→ NORMALIZE → PRELOAD → TEST → QUEUE LIVE CALIBRATION → UPDATE KNOWLEDGE → SELECT NEXT`

- **宿主是面板的队列泵**（唯一长驻进程），`QueuePump.PRELOAD_EVERY = 20`（10 分钟一轮）；
  进度写 `learning/knowledge_bootstrap/STATE.json`，`pump.json` 记 `preload_note`。
- **看门狗**：`QueuePump.alive()/revive()` + 面板巡检，线程死了自动重启 ——
  直接回答操作者那句「禁止出现：代码支持自动预装，但实际 Controller 根本没运行」。
- **完成 Hook**（§十五）：任何 bootstrap job 结束（LIVE_VERIFIED / BLOCKED /
  KNOWLEDGE_BLOCKED / FAILED / BUDGET_EXHAUSTED）都在 `reconcile` 里回调，
  更新知识 → 更新视图 → **点名下一个能力**，不停下等指令；记录在台账 `knowledge_updated` 行。
- **知识阻塞不阻断循环**（§七）：某能力研究已派出且缺口仍在 → 记 `KNOWLEDGE_BLOCKED` 并
  **跳到下一个**（真机跑 `--cycle` 实测：`skipped 1`，从 TROOP_SELECT 移到 ECONOMY_RESEARCH）。
- **P0-P5 阶梯**：P0 真实 Gap（由运行时产生，Bootstrap 遇 P0 让路）> P1 已解锁 MISSING/NEVER_TRIED
  > P2 高频免费 > P3 其它已解锁 > P4 预计即将解锁 > P5 未来。
  **P4 不按目录顺序猜**（曾把 category A 全降级成"尚未解锁"）：只有「family 未观测但某个
  goal 已经点名要它」才算 P4，其余才是 P5。

### 三、合流（§12，避免两个 Job 改同一个能力）

真机在跑时撞上一个**正在预载**的能力：**不建第二个 Job** ——
`EscalationQueueAdapter._merge_into_preload()` 把 episode / screenshot / failure_signature /
worldstate 追加到已有记录（台账 `evidence_appended` + `priority_raised`），并把优先级提到 P0。
冲突/优先级靠**能力名**匹配（不是去重键），否则同一个能力会有两个不同签名的 Job。

### 四、KPI 换了口径（§十一）

不再以"写了多少 Skill / 多少 Job / 多少单测"论成败。核心是五个覆盖率，
**最重要是「当前已解锁能力」的 LIVE_VERIFIED 覆盖率**，且**分母必须写在数字旁边**
（`coverage()` 的 `definitions` 字段）。实测（2026-09-18 11:24）：已解锁 194 项中
LIVE_VERIFIED 32（16.5%）、Candidate 54.6%、已观测 36.1%；全表 522 项 LIVE_VERIFIED 6.1%。
`knowledge.external_share` 是"外部来源占比"，**它应当随运行时间下降**——否则说明知识没有沉淀。

**未完成（明确点名）**：① 真正的**定向外部研究执行者**还没有——控制器会把带问题的工作单
发进队列，但没人在联网后把答案写回 `knowledge/preload/`（完成 Hook 只做对账与状态迁移）；
② 取租约的一方仍未写（P0-D/F 仍卡在这里）；③ 面板仍是旧进程，
`_preload_tick` 要在下次安全边界重启后才在真机 GUI 里跑。

## P0-D 的那一环：谁替 `LIVE_VERIFY_PENDING` 去要设备（2026-09-18 补齐）

**症状**：`LIVE_VERIFY_PENDING` 状态有了、租约协议有了、运行时让路守卫也有了，
**但没有任何东西去申请设备** —— 操作者那条链
（新版本 → 真机 episode → verifier → LIVE_VERIFIED）**没有人迈出第一步**。

**修**（两条，缺一不可）：

1. **要设备的一方**：`EscalationQueueAdapter.service_validation_lease()`（在 `_drain` 里调用，
   所以 AUTO hook 与面板时钟两条入口都会服务它）。
   取**最老**的 `LIVE_VERIFY_PENDING` 记录 → `DeviceLease.request(capability_id, job_id,
   trace_id=记录 key)`。`request()` 是"请求 + 空闲则直接取得"，所以它是**申请**而不是抢：
   游戏端持有就让路（运行时在原子边界自会 yield），拒绝也如实写 `validation_lease_requested`
   （`acquired=false` + 原因）。台账事件：`validation_lease_requested` / `_released` / `_deferred`。
2. **驱动它的一方**：面板 `_maybe_validate()` + `_run_validation_worker(goal, key)` ——
   当租约已被 `DEVELOPMENT_VALIDATION` 持有、且 **AUTO 没有在跑一轮** 时，
   用**同一个统一执行器** `run_live.py --goal <记录自己的 goal> --max-actions 12`
   （`VALIDATION_MAX_ACTIONS=12`，校准是"考试"不是"挂机"），
   `finally` 里**无条件释放**（PASS / FAIL / 崩溃都归还）。

**关键安全性质（必须保住）**：**没人能驱动时绝不申请**。
判据是**面板心跳**（`learning/control_panel/pump.json` 的新鲜度，>90 秒即视为无消费者）——
因为一旦取得租约，V2 就会在下一个原子边界让路，
**"让了路却没人开"比"多等一轮"糟得多**。实测：心跳新鲜 → 取得设备（trace=记录 key）；
心跳过期 → 不申请，写 `validation_lease_deferred`。
另外 `release_validation_lease(expect_key=...)` 拒绝释放**别人记录**的租约（否则谁先结束谁误还设备）。

**测试**：`tests/test_knowledge_preload.py::ValidationLease` 6 项 +
`tools/check_wiring.py` 4 条 `lease:` 断言。

**仍然未完成**：真正的**定向外部研究执行者**（工作单能派出，没人把答案写回
`knowledge/preload/`）；面板仍是旧进程（要重启才加载新的 `_maybe_validate`）。

## READ ONCE 的另一半：研究答案必须落盘（2026-09-18 12:20）

上面那条「未完成」已经补上：`knowledge_preload.ingest()` + `knowledge/preload/inbox/`。
**只派研究不回写 = 每个循环重问同一个问题、知识库永不增长**（操作者原话：READ ONCE）。
- 答案文件形状：`{capability, answers:[{field,value,source,source_type,source_confidence,observed_date}]}`。
- 三条**在代码里强制**的规则（不是文档承诺）：① 字段名不认识 → **按名字拒绝**
  （闸门读的是精确字段名，改名会让答案与闸门**悄悄脱钩**）；② `source_type` 不认识 → 拒绝
  （给一个不知道的等级赋信任，就是先验变成事实的路径）；③ 答案**永远不能写 CONFIRMED** ——
  `trust_for_source()` 是**天花板不是阶梯**：外部 rung 封顶 `PRIOR`，仓内 `UNVERIFIED`，
  真机看到 `OBSERVED`；**`CONFIRMED` 不在任何 rung 的返回值里**，只有
  reconciler 拿着「真机 episode + verifier PASS」才能调 `confirm_from_live()`。
- 消费掉的答案移到 `inbox/done/`，坏文件移到 `inbox/rejected/`——**不删研究**。
- 命令：`tools/bootstrap_scan.py --inbox` / `--ingest`。

**三个真实缺陷（这轮才浮出来，都已修）**：
1. **一条 CONFIRMED 字段把整条记录读成 CONFIRMED** → `select()` 会**永久**拒绝预载它。
   改 `KnowledgeRecord.headline_status()`：记录只和它**最弱的已知字段**一样强；
   **有洞的记录永远不能 CONFIRMED**。否则「回答了一个问题」会让这个能力永久下架
   —— 回答者反而成了取消调度者。
2. **`needs_research()` 把「问题已记录」当成「问题已回答」**：字段还空着却回
   `already answered at UNVERIFIED`，于是**最需要研究的能力恰好被永久拒绝研究**
   （TROOP_SELECT 实测 `research_attempts=0`、`recovery_prior` 缺、却被拒绝去找）。
   现在 **有缺失字段 ⇒ 必须研究**。
3. **`validation_lease_consumer()` 读墙上时钟而非本轮时钟** → 答案不可复现；
   所有钉时间戳的测试都是**定时炸弹**（写完后 90 秒开始永久红，5 个租约测试就是这么挂的）。
   现在收 `now=` 参数。

**控制器状态机（§15）**：`machine_state()` 按优先级折叠出
`RUNNING / LEARNING / PRELOADING / WAITING_LIVE_VERIFY / LIVE_CALIBRATING / BLOCKED / IDLE_NO_WORK`，
对外还报 `waiting_live_verify_count / queue_depth / current_job / last_ingest / last_success`。
**顺序就是价值**：等设备 ≠ 等资料 ≠ 没活干，面板要能分辨。
面板「能力学习 / 预装」行**读控制器自己写的 STATE.json**，不自己再算一遍。

**寒野 Expert 已升到 V2.1**（原地升，未新增第二个专家）：`winter-agent-v2-dev` v2.1.0，
新增永久 SOP、`READ ONCE / STORE ONCE / REUSE MANY TIMES`、「寒野不是什么」边界、
`HOW TO LEARN（专家）vs WHAT WAS LEARNED（Knowledge）`、连续自主验收纪律。
**玩法不进提示词**，操作细节进 `capability-preload`（§11 回写 / §12 连续验收 / §13 重启恢复）。

## Truth Source 审计：显示状态必须有来源（2026-09-18 13:00）

**操作者报的实例**：GUI `current_role=xhw`，真机不是 xhw。
根因不是缓存 —— 是 `tools/control_panel.py` 里的**字符串字面量** `text="xhw"`，
旁边还有 `text="● 在线"`（无条件宣称在线）。**常量无法与测量区分**，
所以它能漂多远就漂多远。结论：这是「显示状态可以没有来源」的系统性质，不是一格子的 bug。

**`winter_agent_v2/state_truth.py`（投影，不是第二套 WorldState）**：
只读既有工件，对 17 个关键状态回答五问（value/source/observed_at/evidence/role·episode·version/过期），
按阶梯定级：

```
LIVE_OBSERVED > FRESH_RUNTIME > PERSISTED > REQUESTED ＞ ASSUMED（字面量或默认值）
```

- 缓存允许**帮助恢复**，禁止**冒充当前**；`display` 永不裸输出值。
- 两源不一致 → `STATE_CONFLICT`，**两条读数都记**，不静默选一个。
- 不可能的数（`march_used > march_max`）**是冲突，不是读数**。
- 空 ≠ 没有：没读到必须显示「未知」，不得显示 0 或「正常」。

**第一次跑就抓到**：`march_capacity = 21/3`（占用>容量）、
`current_goal` 快照 `AVOID_STAMINA_WASTE` vs episode `BEAST_HUNT`、`resources`/`queues` 空被读成「没有」。
角色真实是 **`xhw小号`**（账号 1171757165、zoe、王国 4298、54.2万），
**其余状态全部没有按角色限定**（语料本来就是两个账号混的）。

**角色链闭环**：`HybridVision.read_role_identity`（归档帧验证过；最新真机帧 6/6 无假阳性）
→ `learning/role_identity.json`（`record_role` **拒绝无帧的身份**；
**回放按帧时间戳记，不按当前时钟**）→ 审计 → 窗口。
缺的是**写入方**：`tools/state_truth_audit.py --record-role <frame.png>`。
**读得出来却没人写，窗口只能印字面量** —— 与知识回写同一类缺口。

**防复发不变量**：测试与 `check_wiring` 直接读面板**源码**，
状态格又变回字面量就红；**先剥注释**（注释引用被删字面量是文档，不是缺陷——
第一版两边都被自己的注释绊倒过）。

**未做到（排名第一的未决项）**：① 没有一次**新鲜**真机角色读取（要点左上头像；
设备由 AUTO 与另一位 beast 探针开发者占用，按 Single UI Owner 不抢）；
② **角色切换后的 State 隔离尚不存在** —— 没有任何状态带 role 命名空间。

### 教训：签名键不是身份，能力才是（`a950936`）

**§九「一个能力不许两个 Job」原来只由键相等保证，而键是不稳定的。**
`capability_for_skill()` 按文件顺序返回第一个匹配，而 `capability_skill_map.json`
里 **89 个技能有 22 个同时命名两个能力** —— 所以「给某个较早条目补一个 alternative」
就会**静默重键**该技能的全部未来升级。实测：`SCAN_MAP_FOR_BEAST` 被加进
`SPEND_STAMINA_ON_BEAST` 的 alternatives 后，从解析成自己变成解析成该能力，
而真实台账里该能力已有一个 WORKING job（`d8ea0e44`）；键相等把这判成**新问题**。

- 闸门放在 `decide()`：同能力在**另一个键**下处于 ACTIVE / LIVE_VERIFY_PENDING →
  `DEDUP_SKIP` 并**点名**持有它的 job。这是 drain / pump / preload 唯一共同路径。
- `_merge_into_active_job`：合并对象 = **任何**拥有该能力的活动 job（原来只认 bootstrap 来源），
  记 `from_key`/`into_key`；`priority_raised` 仍只给 bootstrap。
- 反模式：**测试钉住「某技能不在映射里」这个偶然**，还声称在测 episode 流的闸门。
  要钉解析就明确钉解析；要测闸门就**经由解析器取键**。

### 一个设备一个主人，也要一个时钟一个窗口（`4a55c1b`）

**同一分钟内量到两个面板**：`pump.json` 16:34:52 由 pid 26428 写、16:35:19 起了控制台、
16:36:22 由 pid 16508 写。两个 `QueuePump`、两个会自启的 AUTO。
`panel.pid` 是**后写者赢的单槽**，没有所有权记录 —— Single UI Owner 只管了设备，**窗口层没有对应物**。

- `panel_clock_owner()` 从**唯一已有心跳**（pump.json）读 `(pid, age)`。
  **不新建账本文件**：pump 每 tick 写自己的 pid，新鲜的文件**就是**所有权证据。
- pid 缺失 / 时间戳不可解析 → `(0, inf)`：不让调用方对**自己没有的主人**报「刚刚」。
- 输的窗口**照常打开**（操作者要看得到），但**不起泵**，于是不写心跳，
  不会被任何读 pump.json 的东西（含队列的租约消费者）误认成主人。
  三个闸门查它：`_auto_development_allowed` / `_maybe_validate` / `_maybe_autostart`。
- **教训（又一次由我提供）**：我上一轮报「新 GUI 上线 pid 26428」，而 26428 **早已不存在**，
  三方一致指向 16508。**结论对在代码、错在进程号** —— 报告里引用 pid 前必须现场核实，
  不能沿用一次读到的值。

### 五处「窗口声称得比它知道的多」（`79b2dce`，全部格式正确、只有断言是错的）

操作者 GUI 工单第一轮。**共同形状**：窗口渲染正常、数值正常，**只有「这是当前值」这句是假的**。

- **不是当前值就拒绝当当前值印**：`TruthValue.headline` / `last_known`。
  `role` 46 小时前的读取 → headline `UNKNOWN` + `Last Known: xhw小号（账号 …）`。
- **活动的当前性由记录自己的倒计时决定**：`events()` 是**列表**（active/claimable/upcoming/history），
  每行带 status/source/observed_at/age/confidence/window/progress/claimable/role/evidence
  与显式 `planner_usable`。实测那条记着 28795 秒、已过 781965 秒 ⇒ **活动早结束**，
  无论它的 `source` 写着什么。没有当前行 → 「当前活动尚未实时确认」。
  **反模式**：把 `learning/event_goal_state.json` 直接当当前活动显示（面板原来就这么干）。
  ⚠ **实时发现还没写**：模型与闸门有了，没人把截图变成 live 行，所以当前活动会一直「尚未确认」。
- **Job 状态不是网关健康**：`gateway_health()` 独立状态，读面板**落盘**的探针；
  顶部那格只评网关。加熔断：连续失败 30/60/120/300 秒退避，成功清零，**unknown 不动阶梯**。
- **上一代 flag 不能当证据**：AUTO 是每轮一个 `run_live.py` 子进程，
  `runtime_thread_alive` / `scheduler_loop_alive` 是**面板自己写 False** 的，
  永远不可能为真。`auto_state()` 按**产出**（新 episode）+ 面板心跳 + 操作者意图评。
- **`expired()` 不看 `released_at` ⇒ 已正常归还 3 秒的租约被判成孤儿**
  （窗口原文：“lease expired … without being released (its process is gone or hung)”）。
  已归还 ≠ 过期：`describe()` 必须说归还与结果。
- **闸门不能因意外对象而崩**：`self._other_instance` 让既有测试的命名空间桩抛 AttributeError。
  改模块级 `observes_only(panel)`（getattr，安全答案＝假设我是主人）。

### 后台进程只有一个启动口（`fb629a9`）—— 黑窗与「异常」的真因

**黑窗根因不是 ADB**（它每个调用点都传了 flags）。真凶：① `state_truth._head()` **每次刷新**
跑 `git rev-parse` 且**完全没有 creationflags**；② `panel_restart` 的 `tasklist`/shell 探针没有 flags，
而面板**启动路径**会调它。③ **无控制台的父进程**启动控制台子进程时 Windows 会**新分配**控制台
（`preflight.py` 的 `adb connect` 就是这样闪的）。

- `winter_agent_v2/winproc.py` = **唯一启动后台进程的地方**。
  `CREATE_NO_WINDOW` **＋** `STARTF_USESHOWWINDOW`/`SW_HIDE`（后半对才有控制台的父进程有效）；
  `shell=False`；输出 PIPE/DEVNULL **绝不继承**；`spawn_detached`（独立进程组＋日志＋PID）；
  `kill_tree`/`alive`/`port_owner`。`V2_SHOW_BACKGROUND_CONSOLES=1` 才看控制台。
- **编码必须固定**：本环境给 Python 设了 UTF-8 默认，控制台工具却按 OEM 输出 ——
  `netstat -ano` 抛 `UnicodeDecodeError: 0xbb`，**诊断恰好在出问题时失败**。
  统一 `encoding` + `errors="replace"`。
- **守卫**：`check_wiring` AST 扫包与 `tools/`；不带 flags 的 `subprocess.*`/`os.system` 直接红。
  一次性人工工具走**带理由的白名单**（23 个，逐名）。
- **网关「异常」是推的，服务真的下线**：8080 拒绝连接、无监听者、无 owner pid；
  **全项目没有任何代码启动它**，所以「probe 失败就再启一个」这条链在代码里不存在。
  **不要给 GUI 加启动器**（面板偷偷拉起 agent host 后果更大）；加**测量**（`port_owner`）与
  诚实状态格：原因/连续失败/下次探测/最后成功/**Job last known**/AUTO 真实状态。
  **反模式**：顶部 `workbuddy` 格读**任务台账** ⇒ 网关超时时它显示「正常」。
- **仪器先证伪再使用**：`tools/console_window_watch.py` 第一版把操作者自己的终端报成缺陷；
  正对照用 150ms 采样**什么都没抓到**，改 10ms 才抓到 `PseudoConsoleWindow`
  —— 那次窗口只亮 **10~20ms**。**没有正对照的「0 次」什么都证明不了。**
- **改完必须跑一下工具本身**：`panel_restart.py` 接 winproc 后 `--status` 直接
  `ModuleNotFoundError`（从 `tools/` 运行的脚本顶层没插 ROOT）。



## 2026-09-18 — 网关（WorkBuddy Gateway）生命周期铁律

事实源：`winter_agent_v2/gateway_service.py` + `tools/live_gateway_acceptance.py` 的真实轨迹。

- **网关由系统自己启动**。全项目曾没有任何地方启动 `codebuddy --serve`，开发环因此整条停摆
  （实测 pump.json errors 17 / WinError 10061）。现由面板探针线程每轮驱动
  `GatewayService.ensure()`；GUI 启动 = 系统启动。禁止要求操作员手动跑 `codebuddy --serve`。
- **CLI 位置**：`%WORKBUDDY_APP_PATH%` 的 `app.asar` 换成 `app.asar.unpacked`，再拼
  `cli/bin/codebuddy`，用 `%CODEBUDDY_NODE_BIN%` 的 node 跑。`which codebuddy` 不存在。
- **启动命令固定为** `--serve --port 8080 --session-id winter-agent-v2`。不传 `--model`
  （会覆盖每个 escalation 自己的模型选择），永不使用 `--auth none`。
- **口令只在环境变量**（`CODEBUDDY_GATEWAY_PASSWORD`）。CLI 会把生效口令打到 stdout，
  所以**网关日志绝不能落在仓库树内**：现在写 `%LOCALAPPDATA%\WinterAgentV2\gateway.log`
  （`WINTER_AGENT_GATEWAY_LOG_DIR` 可覆盖）。曾计划写 `learning/control_panel/gateway.log`，
  那距 `git add` 提交一个活口令只差一步。
- **进程存活判定不能用进程名**。`winproc.alive()` 曾只认 "python"，而网关是 `node.exe`：
  持有 8080 且 health 200 的进程被判为死，这正是产生第二个网关的输入。用
  `winproc.pid_exists()`（名字无关）判断后台服务；`alive()` 只用于面板自身解释器。
- **只允许一个网关**：未知进程占 8080 → `PORT_CONFLICT`，只报告不强杀；自己启动的 pid 在
  90s 启动宽限期内未监听 → 等待而不是再起一个；连续失败 3 次才算状态改变（退避 30/60/120/300，
  一次超时不重启）；用户 STOP 优先于看门狗（不启动、也不杀健康的网关）。
- **网关重启不得创造 Job**：重启后从 `learning/workbuddy_escalations.jsonl` 折叠而非重提。
  验收已证明台账行数在整轮启动/杀/恢复过程中不变。

## 奖励弹窗的落点：正确结论（2026-09-20 更正，勿再引用旧说法）

- **`#64` 里"横幅 `POPUP_GENERIC_REWARD_HEADER` 点了无效"是错的**。帧证：`key/03_*`（13:10:26 的 after）
  显示点完横幅后「获得奖励」**已经关掉**，露出的是**第二个**弹窗「探照灯升级」。横幅**不是**死按钮。
- **真主因是"识别与瞄准用了不同信号"**：`vision.py` 判这张弹窗用 `match(横幅) or match(页脚)`，
  而五个 `DISMISS_*_GENERIC_REWARD` 的动作目标**只有横幅**。横幅在六张真机弹窗帧上是
  **14 / 16 / 18 / 20 / 26（门 16）—— 骑着容差跑**；页脚是 **0~2（门 8）**。
  ⇒ 页脚认出弹窗 ⇒ 选中解除 ⇒ 解析横幅失败 ⇒ `SEMANTIC_TARGET_NOT_VERIFIED` **一次点击都没发出**。
  全史旧目标 51 次失败里 **45 次**属于这一类（39 MAIL + 4 INTEL + 2 DAILY）。
- 已改成点页脚（`SHARED_REWARD_EXIT`），并新增 goal 中立技能 `DISMISS_SHARED_REWARD`
  （绑 `verify_popup_closed`、进 `VERIFIED_ATOMIC`）。真机：同一 5 轮 65 张 before 帧里
  奖励弹窗 **7 张**，新目标解除 **7 次全过（7/7）**，两个数对得上。
- **仍未修**：#65「关掉一个奖励弹窗会露出第二个识别不出的弹窗（探照灯升级，横幅 26 / 页脚 22），
  导致 after=UNKNOWN、per-domain verifier 落空、整轮结束」——这是 13:10:26 失败的真因；
  #66 横幅解析成功也不保证关得掉；#67 在非弹窗页面上跑弹窗技能；
  #68 `intel_pin_centers` 只认紫/蓝/橙，情报帧上返回 4 而板上有 9（灰/绿 pin 全漏）。
- **通用教训**：凡"某控件无效 / 点了没用"的说法，**必须先看那一次的 after 帧**再引用；
  handoff 里的因果句与它的测量数字要分开对待——数字可信，因果常错。
  另：`.probe_*` 探针要在**同一批帧**上同时给出"原始距离"和"生产判定"，
  否则分辨不出"差一点"和"对着空地"（#51/#52 的方法，本日再次靠它纠错）。

## 视觉检测器改判据的规矩（2026-09-20，第 3 次撞同一类坑后固化）

**症状类**：「某个界面上确实画着的东西，检测器就是看不见」，而且**静默**——不报错、不抛异常，
只是少算。已发生三次：`POPUP_DAILY_REWARD_CURRENT` 问错问题（#22）、
橙色 pin 的宽高比 0.65 门槛把它丢掉（2026-09-15）、**掩码只认紫/蓝/橙而板面还画绿与灰（#68）**。
后果都一样：**满板读成空板 ⇒ `goal_library` 判 `CLEAR_INTEL=COMPLETE` ⇒ 假完成**。
⇒ **凡是"数不到"，先假设是判据问题，不要先假设"界面上没有"。**

**改判据前必须做的四件事**（`intel_pins.py` 的 docstring 与
`dataset/truth_audit/reward_popup_exit_20260920/README.md` 第七节各有一份）：

1. **语料从 episode 日志里取**，不靠翻目录：`state_before/after.page == X` 的 `before/after_screenshot`
   就是天然标注的 X 页帧（本次拿到 435 帧）。
2. **新旧判据在同一次运行里 A/B**，不要跟记忆里的数字比。
3. **两个半场都要量**：找回了多少**真**目标（真阳），以及**新录取的假阳**分别在哪儿。
   本次若只量前半场，就会漏掉"中性掩码其实是**页标题检测器**"（60 帧里 53 帧误报）。
4. **把被淘汰的判据连同数字写下来**，否则下一轮会重做：饱和度上界 50/40/30/25 都留标题、
   20 连真 pin 一起去掉；橙色底环丢一个真灰 pin。⇒ 只有**宽度**与**位置**能分离。

**一条取舍纪律**：假阳与假阴**不等价**——假阴 = 假完成（本项目最禁止）；
假阳 = 数字永远不为 0、目标永远做不完（镜像失败）。所以**分离判据要挑不伤真阳的那一侧**：
本次位置下界 `BOARD_TOP=200` **只作用于中性类**（误报只出在它身上），
而不加到所有颜色——后者会冒着把"上移板面"的真彩色 pin 顶掉的风险，那正是要防的漏计。

**别用"界面上应该没有"当证据**：`dataset/truth_audit/intel_beast_target_20260914/03_intel_page_empty_list.png`
曾被当成"空板"写进断言，实际是 13 个 pin 的满板（已改名 `03_intel_page_full_board.png`）。
**本项目至今没有一张经验证的空情报板。**

## "说得出名字的东西，检测器却看不见"——第 4 次，且这次是三层叠加（2026-09-20）

**症状**：真机画面里明明有某物（这次是地图上标着名字的野兽），路线却报"看不见"并去做无用功
（这里是无收敛条件的平移 `SCAN_MAP_FOR_BEAST`，全史 420 次、`goal_progress` 恒 false）。

**这次的教训是**：**同一个读取上可能叠着好几层独立的拒绝，修一层不会让它通。**
必须先量出"卡在哪一层"，而不是修最显眼的那层：
- 第 1 层 身份**门槛**：`beast_targets.is_dispatchable` 要逐物种预批准（`dispatchable:false`/UNVERIFIED）⇒ 全通却拒发。
- 第 2 层 **地理**：`BEAST_LABEL_BAND = x .05-.50, y .45-.80` 只覆盖左半屏中部 —— 40 帧里唯一 2 帧读到的兽名**都在带外**。
- 第 3 层 **键**：身份按 `(物种, 等级)` 精确配对，兽的徽标是 19 而表里只有 20 ⇒ 名字读准也返回 None。
- 第 4 层 **字符**：OCR 把 `霜鳞避役` 读成 `霜解避役`（0.78 < 0.80 门槛）且互不为子串 ⇒ 两道闸同时拒。

**方法（可复用）**：
1. **先量"有没有"，再量"为什么被拒"**：对一批**真机帧**做整帧 OCR / 全掩码扫描，
   得到"这个信息在画面上出现了几次、出现在哪"。本次这一步直接推翻了"板上没有"的假设。
2. **每一层都要有它自己的反例**：门槛层的反例是"已实测被拒"的目标（雪豹29）必须**更严**；
   地理层的反例是"带外放宽后不能把建筑名/联盟旗读成野兽"（靠**兽名白名单**兜底，
   而不是靠裁剪区域——裁剪只是搜索范围，不是安全边界）。
3. **模糊匹配必须有唯一性条件**：允许"恰一字之差"，但**两个候选时答 None**；
   而且给它自己的置信下限（误读会拉低引擎自评分，用精确匹配的下限会把这条路径废掉）。
4. **匹配只做一次，把命中 token 传下去**：等级徽标要"在它旁边"、落点要用它的框中心、
   置信度要用它自己的。本次第一版在三处各自重找，结果模糊命中时三处全部静默失败
   （报 `label_confidence: 0.0`、丢 `tap_norm`）。
5. **"某帧是空的"是断言，不是事实**：本次 `NEGATIVES` 里两帧被当作"没有野兽"，
   放宽后都读出了兽名；裁出来看兽体和名牌都在。⇒ **任何"这里没有 X"的清单，都要先裁图看过**。

**一条判定纪律**：触发这一整轮工作的是一个**僵尸开发作业**（`WORKING` 但
`detail="Idle background coding session with no task"`，进度钟冻结 34.6 min）把能力钉在
`DEVELOPMENT_PENDING`，导致目标**永不入调度**、另外 5 个升级 `CONCURRENCY_WAIT`。
⇒ **"目标没被选中"要先查 `CapabilityGate.load('.').blocks(goal)`**，不要先怀疑路线；
而**释放**要用项目自带的规则（45 分钟超时 + 进度钟冻结 → 自动 cancel），**不要手改状态**。

## "认出了名字"≠"找对了类别"（2026-09-20，真机 1 次尝试的更正）

**经过**：为了让 `AVOID_STAMINA_WASTE` 能花掉剩余体力，给地图上"客户端印了名字的兽"接了
一跳（读名字 → 点它 → 开卡 → 读客户端自己的胜算 → 出征）。修完识别（四处缺陷）后，
**真机跑过 1 次**：`霜鳞避役` 标签读对（0.875）、点击发出、**卡面真的开了**。

**但打开的卡面是**：`等级7 霜鳞避役` · 推荐实力 **683,100,000** · **`[集结]` 25**。
⇒ 那是**集结目标（冰原巨兽一类）**，不是普通野兽（普通野兽卡面是 `攻击` + 10 体力）。
⇒ 验证器判 `BEAST_TARGET_SELECTION_NOT_PROVEN` **是判对了**，不是 bug ——
它拒绝了把 rally 目标当成普通打野目标。

**两条纪律**：
1. **接入之前先确认类别，不要只确认身份。** 地图上"站着并印着名字"的东西可能是三条不同路线上的目标
   （情报 / 普通打野 / 集结），而**名字区分不了它们**。类别的证据在**卡面自己画的控件**上
   （`攻击` vs `集结`）与代价上（体力 vs 肉）。
2. **一次真机尝试可以同时是"成功"和"失败"**，必须按环节分开报：
   读到名字 ✅ / 点击发出 ✅ / 卡面打开 ✅ / **目标类别 ❌**。
   把这种结果报成"真机通过"或"真机失败"都是在丢信息。

**顺带**：`START_RALLY`/`JOIN_RALLY` 至今**没有 `VERIFIED_ATOMIC` 条目 ⇒ 永不被调度**，
所以即使认出来是集结目标也无处派发；而操作者的路书里"冰原巨兽集结"是三条路里的第二条。

## "信号区分不了两态"要先问：它量的是哪个量（2026-09-21）

**经过**：训练路线 stage A（兵营被高亮、径向菜单未画）从 2026-09-17 起只等待、不点击，
理由写在代码与测试里：**同一语义 `INFANTRY_CAMP_HIGHLIGHTED` 对应两种点击结果**
（开菜单 / 跳地图），而**模板距离 0.0 vs 8.0、8.0 正好等于生产闸门** ⇒ 结论是"信号区分不了"。

**实测推翻了这个"区分不了"**：开菜单那帧有 **205×112 的金色选中环**，
跳地图那帧只有 **7×15 的金色碎片**（军官徽章的边缘，**根本不是环**）。
⇒ 相差**两个数量级**。**旧结论对"模板距离"成立，对"环的尺寸"不成立。**

**可复用规则**：
1. **"分不开"通常不是现象的性质，而是所选度量的性质。** 遇到"这两个状态看起来一样"，
   先问「我在量什么」，再挑一个**与该状态因果相关**的量重测（这里是客户端画的**选中标记**本身，
   而不是"整片建筑群像不像"）。
2. **文件（或旧结论）里的"无法区分"是断言，不是事实** —— 必须自己量一遍，并**同时给出两侧的数值**
   （本次 205×112 vs 7×15），否则无法判断"分不开"是真的还是量错了。
3. **别把"按顺序的人工帧"当对照实验**：`click_opens_menu__20260908` 那帧几何与失败帧**相同**
   （tap 到环心 102 vs 103 px），它的"成功"很可能是从有序帧推断的，**不是实测**。
   ⇒ 只有**真机执行**过的那一侧才算对照。
4. 落地时，**判据要挑"拒绝"比"放行"更安全的一侧**：读不出环 ⇒ 返回 None ⇒ 路线**等待**，
   而不是退回模板中心（那正是原 bug）。

## `SAFE_STOP` 的真实语义：停机整轮，不是"跳过这个观察"（2026-09-21）

brain 的注释写着 "`SAFE_STOP` is how the brain tells the scheduler 'skip this observation'"
（`_leave_or_stop` 的 docstring），**但 runtime 的实现是**：记 `DEGRADED` 并 `return finish(reason)`
**结束整轮**，且只有 `reason == "unknown_page"` 有窄恢复。
⇒ 含义是「**本轮到此为止，下轮别选这个 goal**」（跨轮次），不是「同一轮内换下一个观察」。

**后果与纪律**：
- **"一个页面没人能操作"绝不能结束整轮** —— 它会让**所有其他 goal 一起停摆**，
  而且因为没有动作把客户端挪走，**下一轮开局还在同一屏**（真机实测：一轮只有 1 步，
  `section=HOME` 历史 56 次）。
- 正解是项目已有的 `_leave_foreign_page_once`（有界一次、绑 `verify_safe_back`）。
- **但范围要收窄到"命名 goal"**：`goal is None` 是**调度器在探测**，那里 Back 会被当成"有活干"
  并挤掉真正有工作的观察（`test_multitask_scheduler.py` 钉的正是这个）。
- **改这类行为前先读被打破的测试的注释**：本次我第一版改错了，而注释里已经写着
  DAILY 面板拿到**同一个 Back** 的理由（"stranded the client for every following run"）
  以及 "**Alliance is untouched**" ⇒ 任务不是发明新行为，是**把遗留页面对齐到已跑通的形状**。

## "落点在范围内" ≠ "客户端会响应"（2026-09-21，真机一次否掉）

**经过**：训练 stage A 我做了完整测量 —— 46 帧真机语料证明模板落点 (346,682) **恒定落在金环外 103 px 的
空地**上（环心 (313,585)，sd 4px），三次真机点击都在环外且全败（两次菜单没开、一次跳地图）。
于是改为**点环心**，并把这条推理写进提交与文档，**当作已解决问题**。

**真机 1 次就否掉了**：`action_backend=ADB`（点击真的发出）、落点 **(317,583) 在环内**、
结果仍是 `INFANTRY_CAMP_MENU_NOT_PROVEN`，`after.training={}` —— **菜单没开，高亮环消失**
（= 客户端把点击当成"点空"）。

**⇒ 纪律（写进流程）**：
1. **改落点前先问"那个位置本来就有可交互目标吗"**，而不是只问"落点是否在范围内"。
   范围内可能有**多个**候选（本次环内 5 个亮色块：264/98/60/60/44 px），而**我点的紧邻最小的那个**。
2. **几何一致 ≠ 语义正确。** 46/46 帧的稳定测量只证明"模板中心与环的相对位置稳定"，
   **不证明"环中心可点"**。测量的**精度**不能替代对**目标语义**的理解。
3. **当候选不唯一时，不要用代码挑一个再赌一次**。本次"5 选 1"没有客观唯一判据
   （宽高比、(面积)、手指指向三者不一致），所以**没有发第 5 次盲点实验** —— 这是正确的停手。
4. **一次真机失败就足以否掉一个纯推理的修法**；而**撤回**要连"为什么曾经认为它对"一起写进注释，
   否则下一个人会重新推一遍同样的逻辑。

**配套事实**：撤回后仍**保留**测量资产（`camp_ring.py`、`training["camp_tap_norm"]`）——
**测量是对的，指向的目标不明**。删掉测量会丢掉将来任何尝试都需要的输入。

## 体力消耗的真实路径（2026-09-21 实测）

真机时间线（`learning/episodes.jsonl`，每步 -10）：体力 **367 → 265（-102）**，
消耗者主要是 **`DISPATCH_INTEL_BEAST`**（情报板上的野兽任务）+ 少量 `EXECUTE_INTEL_RESCUE_SURVIVORS`（-12）。
**不是**"世界地图普通打野"。

⇒ 两条推论：
1. **"情报清完后继续消耗体力"依赖情报板有野兽任务**；板子打完就断供（实测 17:29 后停在 265 达 6 小时）。
2. 真正的续航路径必须是**不依赖情报的世界地图打野**，而它被 **#72（地图上带名字的兽可能是集结目标）**卡住 ⇒ 修 #72 才是续航的前提。

## 「拒绝」不是「结束」：一个任务让出共享资源，不能停掉其他所有任务（2026-09-21）

**经过**：GUI 报「已为体力任务预留1支行军」（`reserved_march_for_stamina`），AUTO **一轮只做 1 件事就停**。
表面像是"预留挡住了体力任务"。**实测推翻了它**：同帧同配置下
`goal=BEAST_HUNT` 给的是 `SCAN_MAP_FOR_BEAST`（体力路线**本来就能用那一格**，它只在 `idle_marches<=0` 时拒绝）。
⇒ **预留没有挡住体力任务；是 `runtime.py` 把 `SAFE_STOP` 处理成 `return finish(reason)` = 结束整轮。**

**可复用规则**：
1. **看到一个"因 X 而停"的理由时，先分清三件事**：① **拒绝**（本任务不该拿这个资源，正确）；
   ② **结束**（本轮到此为止，错）；③ **归因**（谁在运行、谁被挡）。本次三者混在一句话里，
   而正确的一半（拒绝）和错误的一半（结束）在**不同文件**里。
2. **"某目标被某条件挡住"要用两个 goal 分别跑一次决策来判定**，不要从一个理由字符串推断归属。
   本次一行对比就定了性（`BEAST_HUNT` 不被拒 ⇒ 预留的靶子不是它）。
3. **共享资源的让出必须走"让位重选"而不是"停机"**：项目已有 `_yield_to_next_goal`（Rule A），
   本次复用它，**不是改状态名**，也不是新造调度。
4. **让位要有两道边界**，否则从"停机"变成"自旋"：`index < max_actions`（没有下一次迭代时仍停）
   与"同一 goal 一轮只让位一次"。**并且守卫要钉住"范围精确限定在该理由"** ——
   否则下一个人把它扩到所有 `SAFE_STOP`，就会在下一轮必然给出同样答案的状态上白花一次迭代。
5. **缺路由的 goal 会静默借用别人的分支**：`KEEP_MARCHES_PRODUCTIVE` 不在 goal→route 映射里
   ⇒ `current_goal=None` ⇒ 而预留分支的条件正好写成 `{None,"GATHER_RESOURCE"}`
   ⇒ **采集分支替它回答了**。⇒ 判断"哪个 goal 在做这件事"时，**不要只看 goal 名字，要看 route 映射里有没有它**。
   ⚠ 但**不要顺手补上**：`current_goal is not None` 会让**别的**分支一起激活
   （本次 `brain.py` 274/534/1055 三条）。**补一个名字 = 同时打开三条未测路径**，必须单独测。
6. **"测量精度"不能替代"目标语义"**（与 2026-09-21 训练 Stage A 同一条）：46 帧一致只证明几何稳定。
   本次患者帧上那只兽**只有等级徽标、没有名字** ⇒ 诚实结论是"没有可识别目标"，不是"预留"或"识别坏了"。

## 没有上限的等待就是生命周期缺陷（2026-09-21）

**经过**：AUTO 在 `11:43:24` 那轮之后停了 13 分钟，`panel.log` 无输出、最后 episode 不动，
而 `operator_intent=RUNNING`、面板的 escalation pump 每 30 秒照跳 —— **窗口活着，工作周期结束了**，
只能人工重启。根因：`tools/control_panel.py` **16 处 `Popen.communicate()` 没有超时**，
而 `_kill_worker_tree` 自己的注释写明：**在 Windows 上面板持有的是 venv 转发 stub，
真正驱动设备的孙进程才是持管道的那一个** ⇒ 孙进程不退出 ⇒ **EOF 永不到来**。

**可复用规则**：
1. **等一个子进程返回，必须有上限**，并且在到点时**杀进程树**（不是只 terminate 面板持有那个 stub）
   且**把"我放弃等待"写进日志** —— 否则事后读日志的人会把"面板放弃了"读成"这轮正常结束"。
2. **"进程还活着"不等于"在工作"**：判断 AUTO 是否在推进，要看**产物时间戳**
   （最后一帧 / 最后 episode / `panel.log` mtime），**不要**看进程列表或某个心跳文件。
   ⚠ 本环境的 `tasklist` **对任何查询都返回 0 行**，**不能**用来判断进程有无（我先前据此下过错误结论）。
3. **改控制面前先查 `CONTROL_PLANE_PATHS`**：改动是否要求窗口自替换，是"这次要不要重启"的依据，
   而不是凭感觉。（`winter_agent_v2/runtime.py` 不在名单里 ⇒ 改它不需要重启窗口。）

## 页面的模板层死掉时，它填的字段可能是常量（2026-09-21）

**经过**：`KEEP_TRAINING_PRODUCTIVE` 永远做不了事，根因在它上游：训练页的模板
（`PAGE_TRAINING_*`、`TRAINING_QUEUE_TIMER`）**在真机帧上一个都不匹配**（全是旧截图手裁的
`CANDIDATE`），而 `TAB_TRAINING_LANCER` 与 `_MARKSMAN` **同图**（都从未选中的格子裁 ⇒ 分不开）。
于是 `world.training` 恒空。更糟的是：那个分支里还写着 `"tier": 10, "batch_count": 806` ——
**旧截图的常量被写成"从当前帧读出来的"**。

**可复用规则**：
1. **"识别不了"与"字段是假的"常常同时存在**：模板失配后，那个分支没人验证过，里面的常数就留在那里
   冒充读数。**修识别时顺手审一遍该分支填的每个字段**。
2. **先问 OCR 能不能读**，再考虑重切模板：同一批帧上 `OCRPageClassifier` 直接读出了
   `troop_type`/`status`/`batch_count`/**真实倒计时**，而客户端**本来就把这些字画在屏上**。
   ⇒ **模板失效 ≠ 数据不可得**；`HybridVision` 已有"模板定页面、OCR 补字段"的成熟形状，
   只需把闸门换成"模板层无话可说（UNKNOWN）时才咨询"。
3. **两个半场都要量**：既要证明"该认的认出来了"（8/8），也要证明"不该认的没被认成"
   （14 张非训练帧 **0/14** 误判），并给出代价（只在 1.5% 的 `UNKNOWN` 帧触发，0.59s）。
4. **三个同类对象读得出，不等于模型分得开**：三个兵营页签名 OCR 全读得出（1.00/0.99/1.00），
   但目标模型只有**一个** `status`，`IN_PROGRESS` 就把整个目标标 COMPLETE ⇒
   **一个忙，另外两个永远不会被看**。⇒ 修"识别"之后要接着问"**数据模型有没有那个维度**"。

## 「拒绝」只关于那一个 goal（2026-09-21，第三次撞同形）

**经过**：`SAFE_STOP` 是大脑在说"**这个 goal** 在这屏上没事可做"，而 runtime 一律
`DEGRADED` + `return finish(reason)` ⇒ **一个任务正确拒绝，结束了本轮其他所有任务**。真机两次同形：
`reserved_march_for_stamina`（预留机制**正常工作**，同帧 `goal=BEAST_HUNT` 本来就能跑）
与 `alliance_state_unknown`（联盟页上明明有可操作角标）。

**可复用规则**：
1. **一个"停"要么关于一个 goal，要么关于整轮 —— 不要用同一个出口。** 判断归属时问：
   "这条理由是不是也在说**别的** goal 不能做？" 若是，它必须让位，不能结束。
2. **最危险的形式是"点名一个理由的例外表"**：上一轮只把 `reserved_march_for_stamina` 接进
   让位机制，看起来是精确修复，实际是**给同一个缺陷留了藏身处** —— 另外六个理由走同一行代码，
   继续停轮。⇒ **修这一类问题时，把判据换成项目自己的分类函数**（这里是 `is_fatal_stop`，
   runtime 用来在 DEGRADED / FATAL_STOPPED 之间选的那个），而不是再加一个名字。
3. **让位必须自带收敛**：这里沿用了既有两条边界（剩余迭代 > 0、同一 goal 一轮只让位一次）。
   没有它们，修法会把"停"变成"自旋"。
4. **让位需要"有人可让"**：`best_goal is None`（调度器探测态）时让位返回 False，仍会停。
   这不是本修法的漏洞，而是**下一层**的缺口（#89），要单独判断。

## ⚠ 从开发工具启动的 GUI 进程会被回收（2026-09-21，实测）

**经过**：AUTO 卡住，我按正式方式（`taskkill` 旧面板 → preflight PASS → **项目 venv 的 pythonw**）
重启面板。面板**确实起来了并写了** `运行环境预检通过：...\.venv\Scripts\python.exe` 与
`自动运行已启动`，**约 2 分钟后进程消失，`panel.log` 停在那一行且无退出记录**。

⇒ **宿主在调用结束时回收其子进程**（`Start-Winter-Agent-V2.cmd` 的头注释早就写了这条，
并提到"measured on panels 24936/25408"）。`Start-Process` 与 `cmd /c start` **都救不了** ——
新进程仍在同一作业对象里。

**纪律**：
- **"启动 GUI 让它继续跑"这件事，只能由操作者做**（桌面双击）。失败要**诚实说"我做不到"**，
  不要报成"已恢复运行"。
- **不要伪造 `WINTER_AGENT_LAUNCH_PATH=desktop`**：那是"从桌面启动"的声明，面板用它判定
  soak 是否算数。从开发工具启动却带上它 ⇒ **等于伪造验收证据**。（我这次带了，已在 issue 写明。）
- **判断"进程还在不在"要用可用手段**：本环境 `tasklist` 在 Git Bash 里**返回 0 行、不可用**，
  改用 `Get-CimInstance Win32_Process`（PowerShell 工具，stdout 不回传则写文件再读）。
  ⚠ 我曾据 `tasklist` 的 0 行下过"无 git 进程"的结论，那是错的。
- **判断 AUTO 是否在推进，看产物时间戳**（最后 episode / 最后一帧 / `panel.log` mtime），
  **不要**看心跳文件（`pump.json` 是独立泵，面板卡死时它照跳，正是"看着还活着"的原因）。

### 判别法：怎么**确证**是"被回收"而不是"启动失败"（2026-09-21 复现，工具已留在仓库）

两种死法在面板日志里长得**一模一样**（都停在某一行、无退出记录），所以必须用实验分开：

1. **分离启动**：`tools/_launch_panel_detached.py`（`DETACHED_PROCESS` + `desktop` 标记，
   记录 PID/解释器/revision 到 `learning/control_panel/launch_record.json`）。
2. **挂载启动**：`tools/_trace_panel_startup.py`——**同一解释器、同一入口**，但挂在当前调用下，
   stderr 重定向到 `learning/control_panel/startup_trace.log`，观测 60 秒。

**判读**：
- 挂载能活满观测窗 + trace 文件 **0 字节** ⇒ 启动**干净**，死因是**回收**（不是 bug）。
- 挂载也立刻死 + trace 有 traceback ⇒ 真的是启动失败，去读 trace。

**已复现的结论**：分离启动约 3 秒后消失，挂载启动 60 秒**全程存活、零报错** ⇒ **回收确证**。
⇒ **soak / 真机验收只能由操作者双击 `Start-Winter-Agent-V2.cmd` 完成**；
我这个环境**无法**维持面板存活，**不得**把"我启动的面板"计作验收证据。

### ⚠ 不得伪造的另一样东西：`--goal` 的两个词表（2026-09-21）

台账 `goal` 字段存**goal id**，`run_live --goal` 只收 **route 域**。直接透传 ⇒ **argparse 就死**
（`invalid choice: 'KEEP_TRAINING_PRODUCTIVE'`），但**租约已拿到** ⇒ 每 30 秒抢一次设备、
每次 1 秒失败，表现为 AUTO 反复 `device leased for development` 而日志说"EXIT_2 停止原因未知"。
映射现**唯一**在 `goal_library.GOAL_ROUTES`；`route_for()` **幂等**（台账里已有 `BEAST_HUNT`
这类域值，必须原样通过）；无路由 **抛错** 不得硬塞；`ROUTE_DOMAINS` 是 `run_live` argparse 与
映射表**共用**的真相源，有测试钉住二者不得漂移。

### ⚠ 死代码判别法：**单测过 ≠ 生产路径过**（2026-09-21，一天内撞两次）

`ocr.py` 的训练页 OCR 回退分支写成 `if primary.known:` 里嵌 `if primary.page is Page.UNKNOWN:`
——**互斥，永不执行**；而 `test_training_page_by_ocr` 直接调 `OCRPageClassifier.classify`，
**比生产入口低一层**，于是全绿。⇒ 同类问题**必须**：
- 分支移到 `observe()` 等**生产入口**可达处；
- 测试**断言行为**（经生产入口读真实帧），**不要**只断言源码里有某行字符串
  （`assertIn` 源码那条测试**正是**让死代码活了一整轮的共犯）。

### ⚠ "它选了我以为更差的那个" —— 先读定价注释与测试名（2026-09-21）

我见 MAP 帧上有空闲行军位，`best()` 却选了**从未读取的 sweep 票据**而不是 `KEEP_MARCHES_PRODUCTIVE`，
判定是 bug 并把 `best()` 改成"READY 优先于 DISCOVERED"。**错**，两个测试立刻打回。

真实设计：`SWEEP_BASE_VALUE` 80–130 / `SWEEP_NEVER_VALUE` 180，**故意**高于采集的 70，
且**上限仍在真实 claim(250) 之下**；年龄项是**渐近线**（任意两个不同 history 永不相等）。
⇒ **这个排序就是轮换机制**：它保证"从未读过的页面"不被永远在排队的采集饿死。
（引入它的那轮正是因为**封顶后全部并列** ⇒ `best()` 永远取第一个 ⇒ 12 连 CLOSE_POPUP。）

**纪律**：
- 优先级"看起来不合预期"时，**先读那套定价的注释和测试名**，再判断是不是 bug。
- **真正的冲突**（某 goal 占着另一个 goal 等着的资源）属于 **yield / Rule A** 的职责，
  要在**看得见冲突的地方**处理，**不要**为它全局重排 `best()`。

### ⚠ 知识预载层的两个盲点 + 一条不可再犯的负结果（2026-09-21）

做 `CAP-G09 TROOP_SELECT` 时量出来的，代码未改，**下次碰预载前先读这一段**：

1. **派生目标永远显示"未注册"**。扫描器的 `registered_semantics` 只由
   `dataset/candidate/template_manifest.json` 的模板记录派生，而 `TROOP_PRESET` 这类
   「由几何当帧算出、不是模板」的目标（同族：`RESOURCE_DYNAMIC` / `BEAST_SEARCH_TAB` /
   `MARS_ROW_1` …）不在模板清单里 ⇒ **这类能力的 `Targeted Test` 永远 `NOT_PROVEN`**，
   而且简报会说"需要一帧真机页面才能设计"，**误导方向**。它们的实际放行靠
   `tools/check_wiring.py` 的 `_derived_targets` 白名单。
2. **草稿查找键错了**：`capability_bootstrap._match_draft` 依次试
   `existing_skill`、`code`，命中 `dataset/candidate/<code>.json` 就返回该草稿；
   但随后 `prior = PRIORS.get(draft_skill or existing)` —— 用**目录 code** 去查
   **技能名**的 prior 表，于是查空。结果：Navigation / Action / Verifier 从"已有来源"
   退化成 `UNKNOWN`，且 `_in_flight` 见到"该 skill 已有草稿 ⇒ CANDIDATE"把能力
   标成在飞（既不再预载、也不在注册表里 ⇒ **死锁**）。
3. **负结果，别重试**：因此**不要**为了让扫描器"少报一个缺字段"而往
   `dataset/candidate/` 塞设计稿。**实测更差**（上一条）。设计稿的正确落点是
   `knowledge/preload/<CAPABILITY>.json`（扫描器**不读**它，所以不会互相干扰）
   + `knowledge/skills/<X>_RESEARCH.md`（实测路线，SkillFactory 不覆盖 .md）。

配套教训：预载记录的 `notes` 每轮被 `+=` 追加一次，
`TROOP_SELECT.json` 曾累积约 560 份同一句话；已在 `knowledge_preload.py` 的
`as_json` / `from_json` 两侧用 `_unique()` 去重（读侧负责让已污染的文件自愈）。

### ⚠ 调度器：改动目标盘之前先读 `best()` 的注释（2026-09-21）

`goal_library.best()` 的 docstring 记录了一次**实测失败**：曾经按状态分层
（DISCOVERED 排在 READY 之后），**静默关掉了扫掠轮换**，`CLEAR_INTEL` 在任何有空闲行军槽的
帧上都变得不可达。目标盘上的价格是**承重**的：

```
SWEEP_BASE_VALUE 80 (+ 年龄奖励最多 100)   ← 未读页面的清扫票，故意高于采集
KEEP_MARCHES_PRODUCTIVE 70                  ← 采集
TRAINING_CAMP_VALUE 90
真实领取 250 / 情报奖励 500 / 体力目标 2450
```

规则：
1. **不要重新定价，只做有界可加叠加**。新增的 `goal_utility.py` 把每个正项上限压在
   「70 → 250」这个间距**之内**，并用 `test_no_combination_can_re_tier_the_board` 钉死。
2. **同一个迟滞量只能计一次**。`_sweep_value` 已经用 `overdue_ratio` 给清扫票加龄，
   所以公平项**绝不能**再读 `overdue_ratio`（读了就是双重计价、重排轮换）。
   公平项只读"距上次被选中多久"，那是**另一个量**。
3. **不要再造一道资格门**。资格属于 `capability_gate`（有自己的 `probe_minutes`）；
   在别处再加窗口只会**延长**封锁 ⇒ 违反 §六"Utility AI 不得把 V2 变得更加保守"。
   `retry_after` 是死字段，但正确用法是**报告**"下次何时再看一眼"，不是拦截。
4. **真机数据一直躺在盘上没人用**：`knowledge/strategy/stamina_routes.json` 有实测
   `live_success_rate` / `cost_per_success`，长期**只被索引、从未被读取**。
   改造调度前先 grep 一遍 `knowledge/strategy/`，很可能要的东西已经量过了。
5. **只用 `cost_per_success`，不用界面显示值** —— 卡上写得很清楚：显示 10、实测扣 7。





### ⚠ 版本指纹：跨进程断言只能用 commit，不能用含 digest 的 token（2026-09-22）

`RepoRevision.token` 是 `head`（干净树）或 `head + digest`（脏树），
digest = 未提交内容的 sha256。这个形状**只适合同进程内**回答"树变了吗"
（`differs_from`），**不适合跨进程**回答"设备加载了哪一版"。

实测证据：`learning/episodes.jsonl` 里同一个 commit `39eba75a2...` 出现在**两个不同 digest**
下（`e304be3180e1b369` / `e324f8791464cd4b`）—— 因为一轮运行**自己就会写版本相关文件**。
所以 `episode.repo_revision == after_version` 这种严格比较，等于要求两个进程对
"一棵仍在被写的树的**内容**"达成一致 ⇒ **在长跑里永不成立**。

代价（这是本条的份量所在）：账本全史 `validation_lease_requested` **111 次**、
`version_active` **0 次**、`live_verified` **0 次** —— 整条
`VERSION_ACTIVATION_PENDING → VERSION_ACTIVE → LIVE_VERIFY_PENDING → LIVE_VERIFIED`
阶梯**从未运行过一次**，而它在无限索取设备，AUTO 一小时零步。

规则：
1. 跨进程版本断言用 `commit_of(token)`（取 `+` 前的 commit），两侧同一形状。
   "未提交内容也算版本"的立场**属于同进程比较**，不属于"设备加载了哪一版"。
2. **`after_version` 写入端用 `after.head`、读取端比 `repo_revision`（带 digest）——
   这种"两个不同形状的量"是静默失败**：比较恒为 False，没有异常、没有日志。

### ⚠ 选择器的准入必须与结清器的准入一致（2026-09-22）

死循环的机制：`validation_lease_target()` 只问 `state == LIVE_VERIFY_PENDING`，
而 `settle_validations()` 还要 `outcome == VERSION_ACTIVE`。当一个记录的 `after_version`
已被历史超越（`91e3475` vs 树 `d5b46c4`，差 57 个提交）：
选择器每轮选中它 → 索取设备 → AUDO 让路（0 步）→ 无法结清 → 再选它。
**14:37→16:09 循环 30+ 次。**

规则：**凡是"索取资源"的选择器，必须只选那些"用该资源能真正推进"的对象**；
并且必须有**出口**把不可能完成的对象**终结**（否则 `unfinished_trace` 会再挡住同能力的新开发）。
注意 `validation_command` **只跑工作树、从不 checkout 版本** —— 所以"索要过去的 commit"
结构上不可能被满足，不是"慢"。

### ⚠ 判断一条机制有没有跑过，看事件计数，不看它是否存在（2026-09-22）

代码齐全、有 docstring、有测试、状态机自洽 —— 但 `version_active` 在全史是 0 次。
`requested 111 / completed 0` 这个比率一眼就能看出来，而逐行读代码看不出来。

### ⚠ `git status` 在热路径上要 `--no-optional-locks`（2026-09-22）

`.git/index.lock` 停留 40 分钟、无 git 进程，`git add` 全挂而 `git log`/`status` 正常。
`repo_revision` 每轮 run / 每次 drain 都被调用，unflag 的 `git status` 可能为刷新 stat cache
去抢 index 锁 ⇒ 进程被 kill（它有 `timeout`）就可能留下锁。

**但不要断言锁的归属**：实测（`tools/probe_git_index_lock.py`）无锁时两种形式都不留锁，
**有 stale 锁时两种形式都仍能成功读**、都不动别人的锁，只有 `git add` 被挡（rc=128）
⇒ **可观测行为无法区分**。删掉的是"被杀可能留锁"的窗口，不是已证明的肇事者。
（第一版测试断言"读完后无锁"，**过不了自己的反例**，已重写 —— 教训：行为测试必须能被反例检验。）

### 方法：用 `git worktree` 在历史提交上做干净的 A/B（2026-09-22）

`git worktree add --detach <tmp> <sha>` → 在那里用主 venv 跑测试 → `git worktree remove --force`。
不污染当前树、不需要 stash、能一次拿到逐项结果。判定"失败是不是我引入的"就靠它：
同类测试失败数 **410fc31 = 14 → d5b46c4 = 9 → 0322eaf = 9**，一目了然。

### 方法：归因类怀疑先量再改（2026-09-22）

看到"体力目标的 episode 里跑训练 skill"就断定归因错 —— 量完 4456 条后发现
**每个 goal 名下就是它自己那条链**，交叉的只是 `WAIT_FOR_CAMP_MENU`
（无输入重观察，任何 goal 站在 HOME 都可能走到，§六 明确允许）。
**不改**。差点为了一个想象出来的问题去动承重的接线。

### 训练链的真实死因是识别，不是策略（2026-09-22）

`NAVIGATE_INFANTRY_CAMP` 判 `INFANTRY_CAMP_HIGHLIGHT_NOT_PROVEN`，但那帧人眼就是
"盾兵营已选中"（标签 + 放射光环 + 客户端自己的「详情/升级/训练」+ 手指）。
生产 vision 给出 `training = {}`，**所有已注册模板全不匹配**。
`camp_ring.py` 的模板来自 **46 帧金环**；这帧**没有金环**，是同一状态的**另一种渲染**。
⇒ 同一语义有多种渲染，模板只覆盖一种，是这类"动作对了但 verifier 说没到"的典型原因。
详见 `knowledge/skills/TRAINING_CAMP_RECOGNITION_GAP.md`。


### ⚠ 经验台账必须先可证伪，才能拿去决策（2026-09-22）

`learning/control_experience.json` 实测：**35 条里 11 条来源帧在系统临时目录**。
铁证：**6 个完全不同的控件记录完全相同的坐标 `(0.8403, 0.50)`**
（`HOME|PAGE_MAP`、`MAP|BTN_OPEN_HOME`、`EXPLORATION|BTN_HERO_CAMP_FIGHT`、
`POPUP|BTN_CLAIM_FREE_STAMINA`、`ALLIANCE|BTN_CLOSE`、`ALLIANCE|BTN_ALLY_GIFT_CLAIM`）
—— 客户端不会把 6 个控件画在同一点。根因：**`STATE_PATH` 是模块级常量**，
测试/探针不重定向就写真实台账，而它们 stub 的 `target_resolver` 返回常量。

规则：
1. **任何"运行期证据文件"都必须能回答"这条是哪个进程、在哪一帧上量的"**。
   现在的判据是 `measured_on_a_real_frame()`：来源帧不在系统 temp 下。
2. **读写两侧都要过滤**。只修写侧，已被污染的文件会继续把脏行喂给读者；
   只修读侧，下一次运行又会写脏。读侧过滤 = 自愈。
3. **不要因为"字段存在"就相信它**。`position_norm` 看起来是坐标，实际可能是测试常量。
   验证方式：把它画回一张**真实帧**上看（`tools/probe_experience_point_on_frame.py`）。
   实测 `(0.9236, 0.9539)` = `(665,1221)` 在 HOME 上是「野外」、在 MAP 上是「城镇」
   —— **同一物理按钮两个名字**，所以那条"同坐标"是**正确**的。**先验证再下结论。**
4. **模块级路径常量是"测试污染生产"的标准入口**。新写状态文件时优先做成参数，
   或至少在读写两侧都加 provenance 判据。

### ⚠ 训练链的真相：`TRAIN_TROOPS` 不是必经之路（2026-09-22）

真机 3 次（`dataset/raw/control_panel/runtime_auto/20260921_095242_635577/…step_005_after_…png`）：
```
OPEN_INFANTRY_TRAINING  action = TAP_SEMANTIC BTN_OPEN_TRAINING_FROM_CAMP  ver=True
   training_after = {status: IN_PROGRESS, queue_available: False, troop_type: INFANTRY,
                     batch_count: 250, timer: 00:25:15}
```
画面对得上：标题「英勇盾兵」、「训练中 00:25:15」、「正在训练250位英勇盾兵」。
⇒ **点「从兵营打开训练」那一下就直接把训练开起来了**（`batch_count=250` 是默认值），
**不经过 `TRAIN_TROOPS`**。所以 `TRAIN_TROOPS` 0 次**不等于训练没发生**。

`TRAIN_TROOPS` 0 次的两个真实原因：
1. 队列已占用（`status=IN_PROGRESS` ⇒ brain 正确不生成）
2. `BTN_START_TRAINING` **没有模板**
注意它的 skill 状态是 **`VERIFIED`**，不是"未验证" ⇒ "未验证所以不许点"对这一步**不适用**。

**真正的缺口**：训练页**底部就是「盾兵营 / 矛兵营 / 射手营」三个页签**，但**没有任何 skill 指向它们**
⇒ 只训练盾兵营。可复用 `ocr._label_tap_norm(name_token, frame_size)`（由文字标签算可点坐标）
+ `read_resource_tab_labels` 的形状。

### ⚠ 用 `MAP_HUD` 的 `current` 证明体力消耗（2026-09-22）

普通打野 3 次全通过，体力 **430 → 420 → 410（每次 -10）**：
```
DISPATCH_BEAST  marches []->['MARCHING']  march_used None->1
   stamina 来自 MAP_HUD（roi x_norm 0.04 / y_norm 0.0755, gauge_pixels 510/569/556）
   action = TAP_SEMANTIC BTN_BEAST_DISPATCH_MUSK_OX_9
```
⇒ `state_after.stamina.current` 是**可引用的体力证据**。而 `resources` 字典**一直是空的**，
不要用它证明资源消耗。

⚠ **`EXECUTE_BEAST_ATTACK` 全仓零命中** —— 那个技能名**不存在**；普通打野出征的名字是 **`DISPATCH_BEAST`**。

### ⚠ 两个"前提不成立"的负结果，别去修（2026-09-22）

1. **`capability_gate.py:559-565` 的 SEQUENCE 一票否决**：用当前台账实测
   （`tools/probe_gate_sequence_veto.py`），9 个可调度 goal 里**只有 1 个被否决**
   （`ALLIANCE_ROUTINE`，因为有**正在运行的开发 job** ⇒ 阻挡**正确**）。
   `KEEP_TRAINING_PRODUCTIVE` 的组合是 **`VARIANT`** 且**什么都不否决**；
   **"未学会"的能力根本不在台账里**（`no state recorded`）⇒ 不触发 defer。
   逻辑上它对 SEQUENCE 确实过宽（应看"前沿"），但**当前未触发** ⇒ 记为潜伏故障，**不改**。
2. **"Brain 在 Skill 不完整时不敢动作"**：近 52 步 PRODUCTION 里"未生成动作" = **0**。
   7 次失败 = 3 次目标无模板 + 4 次点了但状态没到。
   ⇒ 机器在点，缺的是"具名控件没有模板时该点哪里"。

**教训**：operator 的怀疑值得当**假设**去量，量完若前提不成立，**如实报告并不改**。

### 方法：判断"某能力是否接入生产"要看调用方，不看模块存在（2026-09-22）

`control_experience` 有 `load`/`classify_change`/`save` 三个调用点，另有
`candidates()` / `known_outcomes()` 两个专为读取写的辅助 —— **零生产调用者**。
⇒ "台账已建立"与"台账在影响决策"是两件事；前者有文件和测试，后者要看**谁读了它**。


### ⚠ A/B 判定"失败是不是我引入的"：三条铁律（2026-09-22）

1. **用显式父提交 sha**：`git show 0322eaf:<file>`。
   当本轮改动**已经提交**时，`git show HEAD:<file>` 就是**你的代码**，用它做"旧代码"
   等于拿自己和自己比。我犯过这个错，还因此得出"修好了 5 项"的假结论。
2. **每组跑之前还原状态**。本项目多个测试读**环境学习状态**
   （`learning/control_experience.json`、`learning/goal_fairness.json`、`decisions.jsonl`），
   所以"第二跑"承接"第一跑"的残留。快照这三个文件，每臂前还原。
3. **帧类测试不能用 `git worktree`**。未纳入版本管理的 `dataset/` 证据帧不在工作树里 ⇒
   工作树报 171 项失败，全是环境缺失。只能"原树内还原代码 + 固定状态"。
   （不读证据的测试，worktree 仍然好用。）

判据形态：`410fc31=14 → d5b46c4=9 → 0322eaf=9`，现在再加 `5c00337/0d06b9d = 21 == 父提交 21（逐项相同）`。

### ⚠ 这个套件的红/绿由 `learning/` 的内容决定，不由代码决定（2026-09-22）

`tests/test_live_runtime.py` 单独跑 1 项失败；前面先跑 6 个其它测试文件后 5–6 项失败。
机制：**每个先跑的测试模块都在写生产 `learning/` 文件**，而运行期要读好几个；
`goal_fairness.json` 的 `no_progress_streak` 罚分**改变价格序** ⇒ 胜利的 goal 变
⇒ brain 问的 skill 变 ⇒ 测试断言的正是 skill。

结论与纪律：
- **不要用"逐文件 patch 路径"去修它**。实测：只隔离控制台账 → 仍是 5 项（改由公平账本主导）；
  两个都隔离 → 仍有 3 项随环境翻转。**耦合面比能点名的文件更宽。**
- 我因此**撤回**了已写好的模块级隔离补丁：它把切片从 21 变成 16，而 16 是状态的巧合。
  **让数字好看比留着已知耦合更危险。**
- 正确修法：**一处"学习目录"间接层**（进程内解析一次、测试可覆盖），而不是每个文件打补丁。
- `tests/test_live_runtime.py` 那几个测试本该像**同文件第一个测试**那样显式钉住路线
  （`brain=RuleBrain(current_goal="INTEL")`），它们依赖"哪个 goal 赢"却从不声明。

### ⚠ 复用记忆位置必须尊重风险标签（2026-09-22）

`_remembered_control_center` 是"模板失效时用历史测量位置"，它是比实时模板匹配**更弱**的依据
⇒ 它是**最不该**绕过风险表的地方。现在：`entry.risk` 非空且不在 `EXPLORABLE_RISKS` 中 ⇒ 拒绝。
今天无人写该字段（零成本），但字段在 schema 里且会往返；**"无人写"不是"可以不管"的理由**。


### ⚠ 客户端会把同一语义画成两种样子；模板只认识其中一种（2026-09-22）

这是第三次遇到同一模式，现在可以当规律用：
`TARGET_INFANTRY_CAMP_HIGHLIGHTED`（金环，46 帧）**认不出**当前的
"场景压暗 + 建筑名 + 底部 详情/升级/训练 动作条"渲染 ⇒ 一个**已经到达**的路线被判"没到"，
连错 12 次、goal 被 DEFER。

规律：**同一语义有多种渲染时，模板会静默只覆盖一种**；症状永远是"动作对了，verifier 说没到"。
处理顺序：①先对比通过帧与失败帧，确认是不是**两种画法**（而不是两种状态）；
②优先用**客户端自己画的文字**做读数（`训练` conf 0.986-0.997，跨 7 小时漂移 4px）；
③文字读数的成本要用**模板当门**（见下条），不能每帧都 OCR。

### ⚠ "模板层已解析的页面不做 OCR" 是承重契约（2026-09-22）

`tests/test_ocr.py::test_hybrid_is_template_first` 钉的就是它。我第一版在**每个 HOME 帧**上读动作条
⇒ backend calls 0→1 ⇒ 测试红。**它是对的，不要改测试，要加门。**

而且"廉价的像素门"这次**实测不成立**：带区"最小通道 ≥185 的像素比例"，
动作条帧 0.037-0.363 与普通 HOME 帧 0.003-0.944 **完全重叠**。**先量再写**，别信直觉。
可用的门是模板（项目自己的机制）：取**不透明的图标**当模板，
不要取**半透明的按钮本体**（对它的哈希会跟着背景的城市跑）。

### ⚠ `git show HEAD:<file>` 当"旧代码"用，在本轮已提交时是错的（2026-09-22）

我犯过：拿 `HEAD` 的文件和 HEAD 的代码比，得出"修好了 5 项"的假结论。
**A/B 必须写显式父提交 sha**（`git show 0d06b9d:winter_agent_v2/runtime.py`）。
另见同日"套件的绿取决于 learning/ 内容"那条：每臂前必须还原状态，否则第二跑承接第一跑的残留。

### ⚠ 状态机里"没有值"必须和"值不匹配"分开处理（2026-09-22）

`validation_lease_target` 的守卫写成 `if not record.after_version or commit_of(...) == head`
⇒ 把"**没有版本**"当成"没有约束"放行 ⇒ 一条 job 被时间盒取消、从没记下版本的记录，
**每 40 秒索取一次设备**，而激活阶段又因为"要有版本"跳过它 ⇒ 永远结不清、永远占设备。

**规则：凡是"索取资源"的选择器，`None`/空值必须显式判断** ——
"没有值"通常是"这条记录没有可做的工作"，不是"随便放行"。
（这与上一条 `after_version` 形状不一致的教训是同一个根：**空值与不等值被混为一谈**。）


### ⚠ 判断"某道门禁是不是真的墙"，看它有没有触发过（2026-09-22）

操作者点名 `runtime.py` 的 `VERIFIED_ATOMIC` 资格检查是"动作没交给 MAA"的原因。
**实测：它从未触发过一次。** 2485 步 PRODUCTION 里 `SKILL_NOT_ENABLED_FOR_LIVE_LOOP` 0 次；
83 个注册技能、64 个真的发出动作，没有一个在表外。

真正的墙是**它的下一跳**：`executor.py` 的 `SEMANTIC_TARGET_NOT_VERIFIED`（150 次）。
根因不是"门禁太严"，而是**解析器只有两条把名字变成像素的路**（模板 / 本机记忆坐标），
两者都没有的控件就永远到不了 —— 而客户端明明把它画在屏上。

**规则：报告"某门禁阻碍执行"之前，先数它触发过几次。** 计数为零的门禁是**潜伏**的，
改它是零收益，而且会掩盖真正的断点。（同上一轮 SEQUENCE 那条：逻辑上过宽，但当前未触发。）

### ⚠ OCR 匹配默认必须精确；包含匹配会点错控件（2026-09-22）

MAP 打开野兽搜索面板时，导航栏被盖住，`城镇` 已不在屏幕上。**包含匹配**却在
`我的城镇` 里"找到"了它 —— (0.5062, 0.4945)，那是**地图中间的任务中心**，不是底部导航格。
若按那个点去点，机器会以为自己找到了"城镇"按钮，实际点到别的东西上。

**规则：按文本定位控件时，默认只认与目标完全相同的 token。**
包含匹配要显式开启，并在注释里写明为什么。好处是双向的：HOME 帧的聊天行
`系统消息：…退出了联盟` 含 `联盟`，精确匹配正好选中底部导航格 `联盟`（conf 1.000）。

### ⚠ 客户端印的指令要照做，不要再加"意图"闸（2026-09-22）

奖励弹窗底部印着 `点击任意位置退出`（两帧相隔 3 天，同在 (0.5000, 0.9227)，conf 0.9977）。
我第一版给它加了闸："只有名字含 CLOSE/DISMISS/LEAVE 的语义才允许用它"——
结果 `POPUP_GENERIC_REWARD_HEADER`（名字里没有关闭字样，却被当关闭用，历史第一大失败 **38 次**）
被自己挡住。**客户端的话就是意图**：它说这一屏点哪都能退出，那这一屏就没有第二个含义。
唯一要守的是**词表对页面的声明**（`BTN_ATTACK` 声明 BEAST/MAP ⇒ 弹窗满足不了它），
而那是数据。

### ⚠ "我 grep 不到读者" ≠ "没有读者"（2026-09-22）

我把 `_remembered_reuse` 当死字段删了（全仓只有 append + 一个去重判断）。
`tests/test_remembered_control.py` 立刻失败："the reuse must be visible, not silent"。
**测试是对的**：那是"这次运行里复用发生在哪里"的可答性。
**删字段之前必须跑相邻测试**；测试红时先假设测试对，再假设自己错。

### ⚠ 入口脚本是每轮新进程时，"生产没加载新代码"会自己解决（2026-09-22）

`panel.log` 显示面板每轮：`运行环境预检通过` → `自动运行已启动` → `30 秒后进入下一轮`，
**每轮都是新子进程**。所以提交后**不需要强推重启**，下一轮自动加载；
`latest.log` 的 `[code]` 行是"那一轮启动时刻"的版本，判断"生产加载了什么"必须按此读，
不能用"我刚提交了所以生产就有了"。面板自己的 `RUNTIME_RELOAD_REQUIRED` 是**面板进程**
的事，走它既有的安全点机制。


### ⚠ "下层单测全绿" ≠ 生产入口能到达那段代码（2026-09-22，一天内踩两次）

1. 把页签折叠写进 `observe` 的通用链 —— **训练分支在那之前就 return 了**，
   训练帧永远走不到，产出全空；而所有直接调 `OCRPageClassifier.classify` 的单测照旧全绿。
2. 更早一版插进 `OCRPageClassifier.classify` —— 它收 `OCRResult`、**没有 image_path** ⇒ `NameError`。

**规则：新增"读某一页"的分支时，必须确认那一帧在生产 `observe` 里走哪条路、在哪里 return。**
判断方法：`HybridVision.observe` 里 `if primary.page is Page.UNKNOWN:` 分类分支**会 return**，
后面 `if primary.known:` 的链只服务"模板层已认识"的帧。

### ⚠ 同一语义被客户端画在多个位置时，"在屏上"不能回答"点哪个"（2026-09-22）

训练页**同时画出三个页签文字**（盾兵营/矛兵营/射手营），所以：
模板、记忆坐标、甚至"文字在屏上"都无法决定点哪个 —— 只有"我在哪一页"能，
而那是**页面标题**（`camp_open_label`）。
⇒ 用**派生目标**（按当前页推出该点哪一个），不要用三条按营的硬编码路线。

### ⚠ 加派生目标后要登记 `check_wiring._derived_targets`（2026-09-22）

不登记会被判 `unresolvable scheduler target`。**那是检查在对**，不是噪音：
`RESOURCE_DYNAMIC` / `BEAST_ON_MAP` / `TRAINING_CAMP_IN_RING` 都在同一张表里。

### ⚠ 技能瞄着一个"该页根本没有"的控件，是最难看出来的失败（2026-09-22）

`LEAVE_FOREIGN_LAYER` 点 `BTN_CLOSE`，而联盟页没有 X —— 症状表现为
**另有其名的失败**（`SAFE_BACK_NOT_PROVEN`：BACK 没把页面挪走，20 次），
真正的死因要到解析器那一层才看得见。
排查顺序：**先数失败类型 → 再看那一步的目标名 → 最后确认该控件在这一页是否存在**（用真机帧量）。

### ⚠ "代码已提交" ≠ "AUTO 已加载"；判断生产是否吃到改动要看三件事（2026-09-22）

本轮为此绕了很大一圈，结论固化如下。

- **每轮是新子进程**（`tools/control_panel.py` 明确写着"Each cycle is a fresh subprocess that
  imports vision/brain/skills from disk"），所以**落盘即生效——但只对"改动之后启动的那一轮"**。
  判断某一步是否跑的是新代码，先看那一步所属 run 目录名（= 轮启动时刻）与文件 mtime 的先后。
- **`[code] revision <sha>+<hash>` 不能当"已加载"的证据**：它是进程 import 时算的，
  而 `<hash>` 会把**未跟踪的临时文件**也算进去（在仓库根建/删一个 `_probe.py` 就会变），
  所以它一直在动，拿它和"现在的树"比对必然不等。
- **有 `reload_deferral` 机制**：开发工具刚写完代码时，面板会**延后启动整轮**（"延后启动：…"），
  期间不产生任何真机动作 —— 不要把它误读成"能力没触发"。
- 可信的落地证据按强度排序：**生产 episode 出现该 skill/该 reason** > 生产状态文件（INDEX/台账）
  出现新条目 > 面板日志出现新的 reason 字符串 > 什么都只看日志推断。

### ⚠ 测试绝不能写进生产知识目录：`_ui_store()`/`_page_store()` 会按需创建生产目录（2026-09-22）

`LiveRuntime._page_store()` 在 `_ui_pages` 没设时会**当场创建 `knowledge/perception/pages/`**。
第一版测试驱动采集 hook 时没说写到哪 ⇒ 测试把自己的帧写成了"AUTO 学到的知识"，
凭 `source_episode=run3`（测试自己编的 episode 名）才认出来。
⇒ 测试装配 runtime 时必须显式传临时目录下的 store；诊断生产知识时要核对
`source_episode`/`entry_trigger` 是否可能是测试产物。

### ⚠ 记录索引会"复活"证据已删的记录，并且会阻止重新采集（2026-09-22）

实测：`knowledge/perception/pages/INDEX.json` 在其 `<id>/` 目录被删后仍被某轮反复重写
（每 ~25s 一次），且**后续每次遇到该屏都折进这条没有图的记录**，永远不再重新截图。
两处都要挡：`_load()` 丢掉 `page_image_path` 已不存在的记录；`stage` 前若图不在就重新 stage。

### ⚠ 同一文件不要在一条消息里发两个 Edit（2026-09-22）

两个 Edit 对同一文件并发执行时都基于同一份原始快照，**后写者覆盖前写者**，而两次都返回"成功"。
本轮 `ControlExperience` 的 dataclass 字段就这样丢了一次：`as_json` 里有 `level`、dataclass 里没有
⇒ `from_json` 抛 `TypeError`，而 `load()` 当时没有兜底 ⇒ 读台账会打到运行时路径上。
⇒ 规则：同一文件的多处修改，**串行发**（或写一个补丁脚本一次跑完）。
⇒ 另一条：**改存储结构后立刻做一次 save→load 往返自测**，这比读代码可靠得多。
（`load()` 现在对读不出的记录跳过而不是抛出。）

### ⚠ 指向生产文件的模块常量会被测试改写（2026-09-22）

`control_experience.STATE_PATH`、`ui_collection.CANDIDATE_ROOT`/`TEMPLATE_MANIFEST`、
`page_knowledge.PAGE_ROOT`/`TRANSITIONS_PATH` 都是**模块常量且指向生产文件**，
而 19 个测试文件会驱动完整 `LiveRuntime`（跑完一轮就 `save()`）。
实测：一次测试套件运行把 `learning/control_experience.json` 从 **52 条压到 4 条**。
⇒ `tests/conftest.py` 已在**会话级**把这五个常量重定向到临时目录（跑完还原）；
  测试若要自己的路径仍可显式传入。新增这类常量时必须同时加进 conftest。
⇒ 该台账的 `save()` 也已改为**与磁盘取并集**（按 key，尝试次数多者胜、同时新者打破平局）：
  条目按设计从不删除，任何进程都不该能抹掉别人证明过的东西。

### ⚠ 同一状态被两个写者写时，词表必须先统一（2026-09-22）

`unknown_dispatch` 的**在飞上限在第一次真机运行时就失效了**：`dispatch` 写的是提交返回的网关词
（`working`），`reconcile` 写的是桥的裁决词（`RUNNING`），而 `open` 只认第一种拼写 ⇒
**一次结算之后所有在跑的 job 都被当成已结束**，第二个 job 被并发提交（我当场看到两个同时 working）。
⇒ 规则：一个字段由两个地方写，就先定**唯一词表**（这里统一用网关词），另一种信息另存字段
（`verdict`）而不是挤进同一列；并且**两种历史拼写都要能读**（账本只追加，不重写历史行）。
⇒ 附带测得的环境事实：**网关并发执行 job**。账本里长期只有一个 job 在 `working`，看起来像串行，
我据此写过"串行"的注释 —— 错；实测两个 job 同时 `working`/`alive`，那一个 job 是**队列策略**的结果。

### ⚠ 过滤器可能正好滤掉你要收尾的那个东西（2026-09-22）

`reconcile`（结算 job）此前走 `in_flight()`，而 `in_flight()` 的语义是"**还没有答案的**在跑 job" ⇒
答案在 job 结束前落盘的那种（最常见的成功路径）**永远不会被结算**，于是 job 永久留在账本里，
而模型路由最需要的"成功样本"一条也拿不到。⇒ 拆成两个名字：
`open_jobs()`（结算用：只看"在跑"）/ `in_flight()`（占位用：看"在跑且无答案"）。
**判据：一个过滤条件如果同时服务两个目的，它迟早会服务错一个。**

### ⚠ 模板匹配在平坦画面上病态 —— 模板与命中窗口都必须有对比度（2026-09-22）

实测：候选库里那条 `ORDINARY_CONTROL[退出]` 的裁图灰度 **std 只有 2.22**（它本来就是从一张模糊过场帧裁出来的），
在**另一张模糊帧**上拿到 `score 0.9943` —— TM_CCOEFF_NORMED 在近均匀patch上无意义。
⇒ `ui_collection.template_regions` 加了**双闸门**（模板自身 `std` 与命中窗口 `std` 都 ≥ 8）。
真实 UI 裁图实测 39.5–62.1，离阈值极远。修完：模糊帧区域数 1 → **0**，
并且燃霜矿区帧上那个 0.7+ 的模板命中**也是**同一类假匹配（同样消失）。

### ⚠ `match_ccoeff(image, template, roi)` 的 template 必须是**裁图文件**（2026-09-22）

我曾把"经验条目"的**整张源帧**当模板传进去 ⇒ 等于在一个 40px 搜索窗口里找一张 720x1280 的截图，
**永远不可能命中**，于是那个"依据来源"静默无效（不会报错、只会永远返回空）。
⇒ 改为一律按 digest 落一份裁图缓存（`_crop_cache`）。**"不会报错但永远为空"的来源最危险。**

### ⛔ 不要再写"通用像素级无文字元素检测器"（2026-09-22，已写过一次并被数据否决）

9% 窗口的连通域 blob 法在真机帧上把 **289 个网格点中的 138 个**判成"元素"（火山美术与 UI 图标同样有纹理）；
想用来分开的闸门实测**分布重叠**（环带平坦度：真图标 22.8–84.0 vs 美术 26.6–85.6；
大组件轮廓被窗口边界裁切 ⇒ 紧致度一律 0.0），12–50% 窗口的"平面度"同样重叠（0.11–0.65 vs 0.14–0.39）。
⇒ 结论：本项目**能测文字、能匹配裁图，不能把无文字控件与美术分开**。
无文字控件只能靠 ① 已注册裁图 ② 锚定到本帧真实文字框（有界偏移）。
引擎侧正路是 MAA 自带的 `ColorMatch` / `FeatureMatch`（`JRecognitionType` 里确实有），未接线。

### ✅ 无人值守作答通道的正确形态（2026-09-22）

UNKNOWN 问题通道此前**没有消费者**：runtime 会写问题、会读答案，但把问题变成工作的代码**不存在**，
答案只能由人运行 `--list/--show/--answer` 产生 —— 那**不是**自动 AI 推理。
正确形态（本轮已落地）：**文件驱动的状态目录 + 挂在面板既有 30 秒时钟上的派发器**，
经**现有** `WorkBuddyBridge` 提交背景 agent job（提示词指向请求文件与真实截图，
要求用项目自己的工具落盘以复用同一套校验），有界/幂等/可审计；
`runtime.py` 与 `brain.py` **不得**出现该模块（有测试静态判失败）—— 这条保证 AUTO 永不等待。

### ✅ "注意力优化"必须先量一次观测的代价（2026-09-22）

生产 `SemanticWorldVision.observe` 实测：**不论 Goal 是什么，每帧固定问 106 个语义**，
真实帧耗时 2.8–9.7s；其中 `TARGET_INTEL_BEAST_MISSION` 一个就 3.6–3.8s（在整条地图带上
以 8px 步长滑 16×16 感知哈希 ≈6200 个位置）。
⇒ 在写任何"注意力"代码之前先测出这个数字，否则会去优化错的东西。
⇒ 结论：**代价集中在少数几个"在地图带上滑窗"的语义上**，而它们与 Goal 的相关性是可判定的。

### ⚠ 缓存绝不能把"我没看"当成"答案是没找到"（2026-09-22）

本轮最隐蔽的 bug：`find` 缓存答案，于是**被有意跳过的扫描**返回的 `None` 被写进缓存，
第二次观测直接命中它 ⇒ 加宽那一遍 0.00s 就"完成"了，**什么都没加宽**。
⇒ 规则：任何"因策略/注意力而跳过"的查询，结果**不得**写入缓存；只有真正做过的查找才缓存。
⇒ 这个 bug 读代码看不出来，是**耗时数字本身（0.00s）**把它暴露出来的 —— 异常快的路径要和异常慢的一样可疑。

### ⚠ `PIL.Image.crop` 会强制解码整张图（2026-09-22）

`Image.open` 是惰性的，但一旦 `crop`（或 `np.asarray`）就解码整帧 PNG。
旧代码每次 `find` 都 `crop` 一次 ⇒ **一张 720×1280 的图在一次观测里被解码约 100 次**。
⇒ 帧级缓存（保留最近 2 帧）即把 9.55s → 7.34s。**这类浪费在代码审阅时完全看不见。**

### ⚠ 观测链的顺序是语义决定，不是性能决定（2026-09-22）

把便宜的页面定义分支（HOME 等）提到地图扫描之前，能让快捷面板帧快 3.7s 且判定不变；
但**真实的情报野兽图上也有主城按钮** ⇒ 谁先谁后决定了这帧被读成 INTEL 还是 HOME，
而项目自己在 `vision.py` 里写明"必须在 map 分支之前"。⇒ **不要为了速度重排判定链**；
速度要从"不重复做同一件工作"和"按 Goal 免除确实无关的昂贵查找"里拿，并保留扩大范围的路。

### ⚠ 本机环境的删除守卫会吞掉 pytest 的汇总行（2026-09-22）

全量/批量 pytest 跑到 100% 后，`[safe-delete][SAFE_DELETE_BULK_CONFIRM_REQUIRED]` 会拦住
pytest 自己的临时目录清理，**汇总行（"N passed, M failed"）与 `-rf` 失败清单都不会打印**。
⇒ 不能以"没有汇总行"判断运行失败；要看**进度行是否到 100%** + `grep -c FAILED` + 进度点里有没有 `F`。

### ⚠ 叠层（overlay）自己的控件，只在它打开时才画出来（2026-09-22）

快捷面板的把手**只在面板收起时画在屏幕左边缘**（展开时改画在面板右边缘）。此前读取器的每个锚点
（三个区头 / 任务行 / 把手估算点）都是**展开态面板自己画的** ⇒ **最需要把手的那个状态恰好测不到它**。
⇒ 规则：任何"叠层的开关控件"，必须在**它要打开的那个状态**里可定位；锚点不得只依赖被叠层的那个东西。
⇒ 无字控件的定位只能靠：① 已注册裁图 + 匹配器 ② 对**当前帧**实测的形状（本文把手=三角形+基边+
填充色+描边竖条）③ 锚定到本帧真实文字框（有界偏移）。**绝不能存坐标**。

### ⚠ "没找到"必须连同"我找的是哪个范围"一起记（2026-09-22）

上一轮把展开态把手判成"未确认"，原因只是**找错了 x 带**：在 x 0.20–0.40 找白三角，那是面板
**文字**的右边缘，而面板的右边缘在 x≈0.67。同一个错误在项目里已经出现过多次
（"低层通过 ≠ 生产入口会走到"）。
⇒ 规则：写下任何否定结论时，**同时写下搜索范围/门槛/帧**，否则后人无法判断结论错在事实还是错在范围。

### ⚠ 全屏关键词否决会连坐无字控件（2026-09-22）

`ORDINARY_CONTROL_REFUSED_WORDS` 是**整帧**检查，而**城帧的活动入口自带 `首充`/`玉魄流光礼包`**
⇒ 整条普通控件链在把手所在的唯一页面上是死的（实测）。
⇒ 规则：风险否决要按**被按的那个东西的身份**判（动作名 + 它自己的词 + 它自己声明的风险），
页面上的消费词只能否决**由词命名的**控件；无字控件的风险由词典记录声明（LOW 才放行）。
（指令原话：「页面上出现'钻石''加速''购买'等文字，不代表这个页面上的返回、关闭或普通查看动作全部禁止」）

### ⚠ 新的事实名要同时进"变化词表"，否则被静默降级（2026-09-22）

验证器命名了 `QUICK_PANEL_OPENED`，但 `control_experience.record_outcome` 只接受
`CHANGE_KINDS` 里的名字 ⇒ 台账把它记成 **UNKNOWN** ⇒ 这一步刚挣到的 L1 **不可复用**
（`l1_reusable` 拒绝 UNKNOWN 的 last_result）。
⇒ 规则：新增任何"可被验证的效果名"时，**同一次改动**里把它加进 `CHANGE_KINDS`，并跑一遍
`save→load` 与"该步是否能复用"的自测。

### ⚠ `git stash push -- <paths>` / `git add` 的两个操作陷阱（2026-09-22）

- 对**已暂存**的路径做 `stash push` 再 `pop`，文件会回到**未暂存**状态：随后 `git commit` 报
  "no changes added to commit"，看起来像白干了（其实只是要重新 `add`）。
- 一次 `git add` 里混入一个被 `.gitignore` 覆盖的路径时，**整条命令失败**（且部分路径可能已暂存），
  于是提交又被跳过。本项目 `dataset/raw/**/*.png|jpg` 一律忽略 ⇒ 真实帧证据**不入库**（惯例），
  但依赖它的测试只能在本机跑。

### ⚠ 本机 shell 会破坏 heredoc 里的中文与 `\xNN` 转义（2026-09-22，再次）

`cat > x.py <<'PY'` 里出现中文或 `b"\x89PNG..."` 时，编码/转义被改写（曾把字节串截断成语法错的
"The following paths..." 这类奇怪报错）。⇒ 一律用 **Write 工具**写补丁脚本或测试文件，再执行；
不要用 heredoc 传中文/转义。这条已经踩过不止一次。

### ⚠ "到达页面"≠"能做事"：还要问"这一页归这个 Goal 吗"（2026-09-22）

真机故障（射手营训练页，蓝色训练按钮亮着，282/03:28:53 都在，V2 直接 BACK 回主城）的**第一个断点**
不在训练判定里，而在更早的通用闸门：

```python
if world.page in (Page.TRAINING, Page.RESEARCH) and not self._owns_terminal_page(world):
    return self._leave_terminal_page_once(world)     # BACK
```
`_owns_terminal_page` 只认 `current_goal == "TRAIN"`，而 Goal 层早已把训练拆成三个**兵营 Goal** ⇒
兵营 Goal 在结构上永远不拥有训练页。
⇒ 规则：**叶子页的"归属"必须问 Goal 层自己**（`goal_library.route_for(goal_id)`），
不要在 brain 里再写一份 Goal 名单——那份名单迟早和 Goal 层漂移。
⇒ 并且：**多实例页面（三个兵营）必须在动作前比对"页面上开的是哪个"与"这个 Goal 要哪个"**，
否则会去训练别人的兵营。

### ⚠ 页面上每一条数字/时间，先问"这是谁画的"（2026-09-22）

训练页的「训练」按钮是两行：`训练` + **这批的预计耗时**（实测 03:28:53，y 0.888）。
旧读取器把页面上**任意** `\d{1,2}:\d{2}:\d{2}` 当队列倒计时 ⇒ 永远判"训练中" ⇒
`queue_available=False` ⇒ 大脑没有可发动作 ⇒ 离开页面。
同一段还有一行**无条件**的 `training.update({"status":"IN_PROGRESS","queue_available":False})`
——在没读任何一个 token 之前就下结论。
⇒ 规则：读取器不得在证据之前写入结论；每个数字/时间都要能说出**它是哪一行的**（位置判据），
与第十一段"动态值移出控件身份"是同一条教训的第二次出现。

### ⚠ 记录在案的语义可能根本没有识别器（2026-09-22）

`POPUP_EXPLORATION_IDLE_DIALOG` 在模板清单里**有声明的记录、但 templates=0** ⇒ 唯一识别路径永远
不可能命中；而 OCR 把弹窗的标题/按钮读得 1.00/0.99。
⇒ 规则：新增"某个语义/弹窗由模板识别"时，**同时确认模板真的存在**；否则就补一条按帧上文字的识别规则
（本项目已有 `REAL_MONEY_OFFER` / `NEW_TROOP_UNLOCK` 两条同类先例，加规则的位置就在它们旁边）。
⇒ 排查口诀：**"验证器报未证明"时，先分辨是"没做对"还是"没看见"**——本例是点击真的生效了
（弹窗被打开），只是读数不认。

### ⚠ 要在真机上跑"定向轮"，必须先向项目申请设备租约（2026-09-22）

**一台设备一个执行者**。面板的 AUTO 与任何定向轮都是独立的 run_live 进程，
系统层面没有任何互斥——但项目**已有**互斥协议：`runtime.py` 里 AUTO 会
**向租约持有者让位**（`DeviceLease.holder()` 非 GAMEPLAY 且不是本进程 ⇒ 在原子边界停下整轮）。

⇒ 定向轮的正确姿势：先 `DeviceLease(root).request(capability_id=..., reason=...)`
（它记录申请，**只在设备空闲时才真正取得**），跑完 `release(result=...)`。
一旦持有，即使面板提前起轮，AUTO 自己会让位。
⇒ 第十三段那次 23 秒重叠的教训：**守卫在，申请缺席** ——
不是"没有机制"，而是定向轮没走这个机制。
⇒ 另注：`learning/DEVICE_LEASE.json` 里 `owner=DEVELOPMENT_VALIDATION` 是**已释放**的记录
（`released_at` 有值 ⇒ `holder()` 为 None），所以它既不泄漏、也不构成任何阻拦；
它保护的是 bootstrap 路径，不是 run_live 之间。

### ⚠ 判"面板是否在空档"只能看面板自己的日志，且要区分 30 秒与 10 分钟（2026-09-22）

面板每轮结束会等两种时长：**30 秒**（还有活可干）与 **10 分钟**（行军已满）。
**30 秒不是空档**——一轮定向要几分钟，插进去必然重叠。
判据：最后一条"进入下一轮"必须含"10 分钟后"，且该行**之后**没有"自动运行已启动"，
且 `learning/runtime_snapshot.json` 的 mtime 距今 >120 秒，且剩余时间 ≥300 秒。
⇒ 反面教材：第十二段的脚本只在日志尾部找"本轮结束"四个字，而那行**早已留在尾部**，
于是它认为有空档、实际面板新一轮已在跑。

### ⚠ 本机排查脚本的两个环境限制（2026-09-22）

1. **`wmic` 已从这台 Windows 移除** —— 依赖它数进程会静默得到空结果（曾被误读为"零个进程"）。
2. **不要在 bash/python 里 spawn 那个 Windows 命令行宿主** —— 沙箱直接拒绝
   （提示：Invoking PowerShell from Bash bypasses PowerShell security checks; use the PowerShell tool instead）。
   第一版定向轮因此**永远认为设备被占用、9 分 34 秒一步没动**。
   ⇒ 需要"谁在占用设备"时，优先用项目自己写的状态文件（快照 mtime、租约、面板日志），
   而不是问操作系统。需要真查进程时用工具层，不要在脚本里 spawn。

## 铁律：帧 ↔ 记录必须按**路径**配对，不得按时间戳

连续三轮（2026-09-23）都因为按 episode 的 `recorded_at` 去取帧而发布过错误结论：

- 把"按绿勾之后出现金环"当成 tap 的后果（实为客户端自画）；
- 称 `17:51:16 / 17:51:35` 是"同一机位的一对"（实际取到的是前一步的文件）；
- 据"地图帧被读成 HOME 且环命中"开出的 issue #93（该帧的**自己那条**记录写着 `page=MAP`，环也没命中）。

**规则**：
1. 一个帧由**一步**写出，只被那条记录的 `before_screenshot` 或 `after_screenshot` 引用；
   与之匹配的是同一侧的 `state_before` / `state_after`；
2. 引用一个帧的部分结论前，先用 `python tools/frame_owner.py <帧名的一部分>` 查它的归属；
   返回"orphan"（无记录引用）时，**不得**为该帧引用任何 `page` 等记录字段；
3. 需要判断帧的内容时，直接看帧（裁剪/放大），不要拿"时间接近的另一条记录"代替。

## 决策层改动的证据：受控 A/B 回放（2026-09-23）

背景：红点此前只被**读取**（`WorldState.red_dots`），没有任何一层用它排序 —— "读到了"和"用上了"
是两件事，而后者才是功能。证明方式不是"板序变了"，而是**同一帧、同一份代码、只切一个变量**：

```
world  = vision.observe(frame)                                  # 生产视觉从图片重读
after  = rank(discover(world), world)                           # 变量在
before = rank(discover(world), replace(world, red_dots={}))     # 这就是改动前的行为
```

三条硬规矩（本项目这一轮量出来的）：

1. **必须有负向对照组**：图上没有该信号的帧，两侧必须完全一致（本轮 0/4，才敢说处理组 8/8
   是红点造成的，而不是这个项在别处误触发）。
2. **按图片分组，不按记录分组**：有 2 帧"记录说没有红点"，用今天的代码重读**读到了红点** ——
   旧记录写于读取器修复（#98：面板行角标窗口从按钮左三分之一移到右三分之一）**之前**。
   ⇒ 记录里的读数可能是**旧读取器**写的；回放要以图片为准，记录只用来挑帧。
3. **新增的优先级项必须有界，且界要算出来**：`goal_utility.RED_DOT_BONUS = 60` 来自板上真实间隙
   （未读探访 180 + 60 = 240 **<** 一次可领取 250）⇒ 红点越不过任何付钱的目标。凭"看起来合适"
   定的阈值会在下一个人手里漂走，所以测试里把这条界钉成断言。

配套：`.workbuddy/skills/controlled-ab-replay`（完整流程与反面清单）、
`tools/replay_red_dot_priority.py`、证据归档 `dataset/truth_audit/red_dot_priority_20260923/`。

**同类教训：绑定必须对着下游的词汇表断言。** 面板「科技研究」行的红点绑的是 `"RESEARCH"` ——
那是 `run_live.py --goal` 的**路由域**，不是 Goal id（`GOAL_ROUTES` 里
`KEEP_RESEARCH_PRODUCTIVE -> RESEARCH`），于是这一行（面板里最常亮、唯一真正有区分度的行）的
信号永远匹配不到任何 Goal，而**没有任何东西会报错**。消费方读不到就静默为零，所以要靠测试断言 +
显式丢弃不能绑定的项。

## 失败理由必须由"知道原因的那一层"产生（2026-09-23，issue #103）

`SEMANTIC_TARGET_NOT_VERIFIED`（"帧上没有这个控件"）是项目里最大的单类失败，而它的 21/32 实例
**是假的**：`_ordinary_control_candidate` 的声明控件层有四个闸门都会拒绝一个**帧上画着**的控件
（本 run 已用过 / 记录不服务这个 goal / 记录不列这个页 / risk 不可探索），四个都只 `return None`；
`executor.py` 看到解析器没给落点，就一律写成"帧上没有这个控件"。

三步可复用的做法：

1. **先分组，再解释**：把同一技能的失败按"本 run 第几次尝试"分组（第 1 次 50 次里 13 失败，
   第 2 次及以后 19 次里 18 失败）⇒ 一眼看出重复尝试才是主因，而不是"模板坏了"。
2. **只切一个变量的复现**：用**生产解析器**在**同一帧**上重跑，把"本 run 已用过的控件集合"
   设空 vs 设上那个控件 ⇒ 同一帧同一代码，落点从有到无，因果闭合。
3. **修"怎么记"，不修"点哪里"**：具名拒绝（`ORDINARY_CONTROL_DECLINES`）+ 一个
   `_failure_type_from()` 把执行器的通用句替换成具名的真话。**点击行为零变化**，
   所以不需要真机就能把"理由为假 21 → 0"钉住；真机只用来确认新名字确实落进了 episode。

**连带要一起看的两个地方**（否则修了一半）：候选收集器会把具名拒绝当成 "unlocated" 入库
（写一条假候选进 `knowledge/perception/candidates/`）；`escalation_queue` 按后缀把
`..._NOT_VERIFIED` 分类成 `UNKNOWN_UI`，于是会请开发 agent 去修一个**没有东西读不懂**的问题
——该文件自己记着一次因错误归因而耗尽整个修复预算的代价。

## 给某个 skill 加守卫时，按 skill id 搜**整个包**（2026-09-23，issue #101 第二轮）

`OPEN_HOME` 有**八个**发出点。上一轮给 `brain.py` 的七处补上了"先关资源搜索面板"，40 分钟后同类失败
又成串出现 8 次——**七次是"一步长"的运行**，六分钟死循环：决定回城 → 失败 → 结束 → 面板 30 秒后重启到
同一张地图，直到一次无关的 `SCAN_MAP_FOR_BEAST` 平移才把面板关掉。

第八处在**运行时**：`LiveRuntime._deferral_replan`（`runtime.py:651`，运行时唯一的 Decision 发出点），
只在 `best_goal is None`（所有 goal 都被 defer）时触发。它的触发条件正是"这张地图上无事可做"，而"无事可做"
最常见的成因就是上一轮把面板留在地图上 ⇒ **最需要守卫的地方没有守卫**。

三条可复用：

1. `grep -n '"<SKILL_ID>"' winter_agent_v2/*.py` 找**所有**发出者；大脑 ≠ 决策的唯一来源。
   本项目的运行时也发 Decision（兜底跳转），而它不在 `brain.decide` 的任何守卫覆盖范围内。
2. **证否"是谁发的"**可以用条件排他：同一帧上把每个可能的 `current_goal` 都问一遍（生产视觉 + 生产大脑），
   若没有任何一处能发出那个 skill，而某处运行时的分支条件与现场完全吻合，那就是它。
3. 之所以只能排除法，是因为 **episode 流里没有 `decision.reason`**（它只写进 worker stdout，随
   `latest.log` 的滚动消失）⇒ 已给 `Episode` 加 `decision_reason`。**证据字段缺一个，事后就要多绕一圈。**
