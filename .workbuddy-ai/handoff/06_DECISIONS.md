# 06 — DECISIONS

已做出的、**非显然**的技术决定。目的是回答「为什么不是另一种做法」，
防止新账号好心地把它们改回去。倒序：最新在上。

格式：`决定 / 理由 / 备选被否决的原因 / 影响范围`

---

## D-018：采集降为 LAST_RESORT，体力消耗优先

- **决定**：`config/v2.json` → `march_policy.reserve_for_stamina: 0 → 2`，
  新增 `resource_policy{gather_priority: LAST_RESORT, stamina_first: true,
  claim_rewards_promptly: true}`。策略写进 `tests/test_operator_policy.py` 而不是只写注释。
- **理由**：操作者明确指令——体力满时应去花体力（情报 / 巨兽），奖励及时领，
  **采集性价比很低，只有队列没有其他用途时才采**。而原来的
  `reserve_for_stamina: 0` 让采集吃掉全部 6 条队列，体力任务永远排不上。
  `march_policy` 里原本已写「recall_on_demand」——**但配置注释不产生行为**，
  这正是要把它变成可测断言的原因。
- **被否决**：只改 `reason` 文字（等于没改）；直接禁止采集（队列绝大多数时间空闲，
  会浪费产出）。
- **诚实的边界**：这两个数字**只阻止采集吃满队列**，并不能让 Agent 主动去花体力。
  真正的前提是「体力可观测」与「撤回可调度」，两者都还没做（见 `04_OPEN_ISSUES.md` 的 0 与 0b）。
  本测试包含两条**阻塞记录断言**：一旦有人实现它们，测试会失败并提醒更新 handoff。
- **影响**：`config/v2.json`、`tests/test_operator_policy.py`。

## D-017：聚合统计同样适用「无证据不算验证」

- **决定**：闭环计数只认可携带 `episode_id` 且截图真实存在的 episode。
- **理由**：第一次统计得出 `WOOD 27 / MEAT 3 / COAL 1 / IRON 1 = 32`，
  其中 **27 条**是旧代码写的行——没有时间戳、没有 `episode_id`、没有截图，
  而且当时的 `resource_target` 是 vision 里**硬编码的 "WOOD"**。
  把它们算进去等于凭默认值编造结果。加上证据门槛后真实值是
  **MEAT 2 / WOOD 2 / COAL 0 / IRON 1 = 5**。
- **被否决**：保留宽松统计并在文里加注（数字会被引用，注释不会）。
- **影响**：`tools/build_gather_closure_tally.py`、`evidence/gather_closure_tally.json`。

## D-016：世界地图需要一个「常驻锚点」，OCR 兜底不能靠按钮文字

- **决定**：
  1. `SemanticWorldVision.observe` 用 `BTN_OPEN_HOME` 匹配 **且** `PAGE_MAP` 不匹配
     作为世界地图的常驻证据；
  2. 从 `OCRPageClassifier.RULES` 中删掉「常规活动」。
- **理由**：`DISPATCH_MARCH` 28 次的 `DISPATCH_NOT_PROVEN` 根因被真机帧证实：
  行军队列浮层打开时会盖住「搜索资源」按钮，且 `STATUS_*` 行模板不匹配该布局 →
  模板层对一张**地图**返回 `UNKNOWN` → OCR 兜底读到地图右侧活动栏的按钮文字
  「常规活动」（置信 0.998）→ 返回 `Page.EVENT` 且 `marches=[]`。
  verifier 要的是「地图 + 有行军在跑」，结果拿到一个被替换掉的错误页面。
- **原则**：**一句话如果玩家不在那个页面时也能看到，它就不能用来判定页面。**
  这条写进了 `OCRPageClassifier` 的 docstring。
- **被否决**：放宽 `verify_wood_dispatch_from_march`（真正错的是观测，不是判定）。
- **影响**：`vision.py`（地图锚点）、`ocr.py`（规则集）、
  `tests/test_map_page_anchor.py`、fixture `dataset/truth_audit/map_overlay_20260914/`。

## D-015：占位技能不得赢得「第一个可执行技能」兜底

- **决定**：`brain.py` 的兜底 `registry.ready(world)[0]` 排除 `WAIT`；
  并且 `Page.MARCH` 必须有显式分支。
- **理由**：注册表按插入顺序返回，第一个 `required_page=None` 的技能是 `WAIT`
  （语义是「等环境自行解决」）。真机复现：采集链走到编队页后选 `WAIT`，
  整个运行以 `ENVIRONMENTAL_WAIT_NOT_PROVEN` 结束。
- **被否决**：给 `WAIT` 更宽松的 verifier（会让真正的环境等待也失去保护）。
- **影响**：新增任何 `required_page=None` 的占位技能时，必须确认它不会抢占兜底。

## D-014：资源不可用要切换资源，不是继续等

- **决定**：`SUBMIT_RESOURCE_SEARCH` 返回 `RESOURCE_NOT_FOUND` 且等级已在最小值时，
  标记该资源不可用（冷却 30 分钟）并在**同一次运行内**换资源；
  `ResourceRotationStore` 的状态文件完全防御式读取。
- **理由**：真机对照实验证明 `RESOURCE_NOT_FOUND` 是资源可用性
  （MEAT level 7 秒过 / WOOD level 1~8 全失败），而轮换只在派兵成功时推进，
  于是不可用资源被**永远选中**——活锁，不是慢路径。整个 Goal 无法前进。
- **被否决**：
  - 继续降等级（等级已经是 1，没有更低）。
  - 直接把 `RESOURCE_NOT_FOUND` 当普通失败结束运行（浪费整轮预算，且 Goal 永远卡住）。
  - 永久排除该资源（节点稍后会重新出现，应该重试）。
- **影响**：`resource_rotation.py`、`operations_policy.choose_resource_balanced(exclude=)`、
  `runtime.LiveRuntime.max_resource_switches`、`tests/test_resource_rotation.py`。

## D-013：截图证据不进 git

- **决定**：`.gitignore` 排除 `dataset/raw/**` 与 `dataset/truth_audit/**` 的 PNG
  （约 1.1 GB），只保留 `dataset/candidate/**` 模板与命名的回归 fixture 目录。
- **理由**：checkpoint 必须快且可读。1.1 GB PNG 会让每次 commit 失去意义，也无法 clone。
  截图是机器本地产物，retention 已在磁盘上保护被引用的帧，handoff 记录绝对路径。
- **被否决**：全部提交（体积不可接受）；全部不提交（会丢掉 `dataset/candidate` 的模板，
  而模板是 live-verified vision 的输入）。
- **影响**：Live Verified 的可追溯性依赖**本机磁盘**，换机器需要重新采集。
  **注意**：排除图片必须用**文件 pattern**（`dataset/truth_audit/**/*.png`），
  绝不能用目录 pattern 排除父目录——git 无法再 include 其子文件，会静默丢掉 fixture。

## D-012：FAILURE 与 DEGRADED 的判定收紧

- **决定**：Goal 级 `DEGRADED` 只在「所有能力都已 live 证明，但至少一个低于可靠成功率」时才给。
- **理由**：最初写成「任一次能力有 ≥2 失败且成功率 <0.8 就 DEGRADED」，
  结果 16 个 Goal 里 7 个变 DEGRADED、`NEVER_TRIED` 被吞成 0 —— 而这恰恰是
  用户明确要求的开发优先级输入。
- **影响**：`capability_coverage.py` 的状态判定顺序。
  改这一处之前先问：`NEVER_TRIED` 的数字还有意义吗？

## D-011：Episode 直接携带截图路径

- **决定**：`Episode` 增加 `before_screenshot` / `after_screenshot`（绝对路径），
  并给 `retention` 提供 `referenced_evidence()`。
- **理由**：需求要求「任何被引用证据不存在 → FAIL」。没有引用就没有可校验的东西；
  同时引用是保留策略知道「哪些帧不能删」的唯一依据。
- **被否决**：只把路径写进 `docs`（文档会说谎，且不会被校验）。
- **影响**：`learning.py` / `runtime.py` / `retention.py` / `tests/test_evidence_integrity.py`。

## D-010：能力映射层，而不是继续修字符串

- **决定**：新增 `knowledge/goals/goal_capability_map.json` 作为**手写输入映射**，
  覆盖率改为在其上计算；`knowledge/goals/capability_skill_map.json` 保留为**输出报告**。
- **理由**：需求侧的 `SELECT_INTEL` / `EXECUTE_INTEL` 与注册表的
  `SELECT_INTEL_BEAST_MISSION` / `DISPATCH_INTEL_BEAST` 是两套词汇。
  直接匹配会让已实现的算缺失、没实现的算满足。
- **被否决**：把注册表改名去迁就需求字符串（会破坏已有 episode 证据的可追溯性）。
- **影响**：文件名相近容易混——前者 input，后者 output，两个文件里都写了说明。

## D-009：`verify_resource_selected` 不再要求读得到等级

- **决定**：等级被降级为 evidence，不再作为「选中成功」的必要条件。
- **理由**：这个 verifier 要证明的状态变化是「锚定的页签变成了请求的资源」。
  等级是另一个观测（且滑条范围已从 1~8 变 1~27，尚未重标定）。
  把它并进选择判定，等于让一个脆弱读取拖垮整条链路。
- **被否决**：保留 `resource_level is not None`（会继续制造假失败）。
- **影响**：判定变窄但更准；等级读数仍在 evidence 里，另有独立 verifier 时再校验。

## D-008：`MARCH_PAGE_NOT_OPEN` 必须拆成两个原因

- **决定**：拆为 `MARCH_PAGE_ACTION_MISSED`（资源点页面仍在，控件还在 → 点击未生效，
  属于重试/延迟问题）与 `MARCH_PAGE_NOT_RECOGNIZED`（页面已变但 Vision 命名失败 →
  模板问题）。
- **理由**：两者根因与修法完全不同，共用一个计数器等于无法行动。
- **影响**：`verifier.py`；历史 59 次仍是旧口径，不可与新数据直接比。

## D-007：资源页签用「锚点 + 相对布局」，不写死坐标

- **决定**：`selected_resource` 先找白色角标的**一对竖线**（间距 130–175px），
  再按 pitch 推出其它格；坐标由 `resource_cell_center_norm()` 现场计算，
  屏外则由 `resource_tab_swipe_for()` 先滚动。
- **理由**：客户端会把当前选中页签重新居中，整条带的滚动偏移在会话之间会变
  （实测到 0 与 +400px 两种）。写死中心只对一种偏移成立。
- **证据**：旧实现下 `SELECT_RESOURCE` 44 次只成功 3 次（6.8%）；
  新实现在 22 个真机帧上 22/22 正确。
- **被否决**：再加几组固定坐标（偏移是连续的，永远补不全）。
- **影响**：`vision.py`；`runtime.py` 的 `RESOURCE_DYNAMIC` 解析与滚动逻辑。

## D-006：`Page.MARCH` 必须有显式分支

- **决定**：采集编队页显式返回 `DISPATCH_MARCH`；兜底 `first_ready_p0_skill` 排除 `WAIT`。
- **理由**：兜底按注册表插入顺序取第一个 `required_page=None` 的技能，
  而那个是占位技能 `WAIT`（「等环境状态自行解决」）。环境状态在上方已全部显式处理，
  让 `WAIT` 在这里胜出会静默卡死在任意页面上。
- **影响**：`brain.py`。

## D-005：Worker 用 `except BaseException` 且必须留 traceback

- **决定**：捕获一切（含 `KeyboardInterrupt`/`SystemExit`），写崩溃报告后再通知 GUI；
  失败分类决定是否计入 `unexpected_worker_exits`。
- **理由**：「worker 悄无声息地消失」比崩溃本身更难查。历史 15 次退出因为只留了
  `str(exc)` 而永久无法归因。
- **被否决**：清零计数器（需求明确禁止）；无脑加 retry（掩盖根因）。
- **影响**：`tools/control_panel.py`；`learning/control_panel/crashes/`。

## D-004：长期保留区必须显式列入保护名单

- **决定**：`dataset/verified` / `dataset/production` / `dataset/normalized` /
  `dataset/external` 加入 `PROTECTED_DIRECTORY_NAMES`，并新增 `referenced_evidence()`。
- **理由**：这两个「长期保留区」此前**完全不在**保护名单里，会被正常轮转删掉——
  即唯一能证明「曾经真机跑过」的帧。
- **影响**：`retention.py`；`tests/test_retention.py`。

## D-003：`LiveRuntime._semantic` 访问器（不要直接 `.semantic`）

- **决定**：用 `getattr(vision, "semantic", vision)` 统一取语义 ROI 视觉对象。
- **理由**：`run_live.py` 传 `SemanticWorldVision.semantic`（ROI 对象本身），
  其它调用方传 world vision。前一个账号把访问方式改成 `self.semantic_vision.semantic`，
  恰好让 `run_live.py` 这条路 100% 崩溃。
- **影响**：`runtime.py`。改这里前先确认两种接线都还能跑。

## D-002：`git init` 并建立 checkpoint 机制

- **决定**：项目纳入 git；`last_good_commit` 记录在
  `.workbuddy-ai/handoff/.last_good_commit`，由 `--checkpoint` / `--mark-good` 维护。
- **理由**：此前无版本控制，已造成一次不可恢复的删除事故。
- **规矩**：只有「逻辑完整 + 测试通过 + 值得保留」才建 checkpoint；
  仍在实验中就保持 dirty tree，并**必须在 handoff 里写清脏文件的意义**。
  不许假装已完成。

## D-001：Handoff 是加速器，不是唯一事实源

- **决定**：所有关键事实都能仅靠 git / episodes / evidence / runtime snapshot / logs /
  registry / goal state 重建；生成器负责重算。
- **理由**：必须支持「上一个账号突然断线」——它可能没机会写 `10_LAST_HANDOFF`。
- **影响**：`tools/update_workbuddy_handoff.py` 的存在意义；
  任何只存在于 Markdown 里的「事实」都视为不可信。
