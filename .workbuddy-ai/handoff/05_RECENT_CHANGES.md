# 05 — RECENT CHANGES

`AUTO:recent_commits` 块由脚本从 git 生成。下面的手写块按会话记录**改了什么、为什么改、
带来什么可测效果**——这部分机器读不出来。

<!-- AUTO:recent_commits -->
Last 12 commits (newest first):

- `3cb413e 2026-09-14T23:51:10+08:00 docs(knowledge): correct two intel facts the live client contradicted`
- `5c4ddd1 2026-09-14T23:13:56+08:00 docs(handoff): the hourly automation did not exist; it is recreated and verified`
- `5c96773 2026-09-14T22:59:53+08:00 fix(runtime): back out of an unreadable screen instead of dying on it`
- `39e246f 2026-09-14T22:49:47+08:00 docs(handoff): refresh after the OCR fragment-stitching fix (full suite green, 408 passed)`
- `48e266f 2026-09-14T22:48:48+08:00 fix(ocr): stitch overlapping digit fragments instead of enlarging the crop`
- `9bfa719 2026-09-14T22:17:57+08:00 chore(knowledge): carry over the uncommitted knowledge files from the previous session`
- `5c902be 2026-09-14T22:17:45+08:00 docs(handoff): ninth round - three false-failure root causes fixed, hero chain green`
- `a218319 2026-09-14T22:15:00+08:00 fix(intel): 探险 from the camp panel opens the squad page, not a beast card`
- `c03af7d 2026-09-14T22:12:48+08:00 fix(executor): register a routing node template, or every MAA node fails`
- `e3f3493 2026-09-14T22:08:34+08:00 fix(intel): the hero-journey camp panel is Page.EXPLORATION, not Page.BEAST`
- `1b7956b 2026-09-14T22:04:40+08:00 fix(executor): MaaFramework screencaps are BGR - convert them to RGB at capture`
- `7c2fae5 2026-09-14T21:55:14+08:00 fix(intel): a real rescue start is proven by the paid stamina, not by one frame-specific status read`

Uncommitted changes: 6
- `M .workbuddy-ai/handoff/04_OPEN_ISSUES.md`
- ` M learning/episodes.jsonl`
- ` M learning/executor_backend.jsonl`
- ` M learning/goal_state.json`
- ` M learning/runtime_snapshot.json`
- `?? evidence/intel_loop_20260914_155030.log`
<!-- /AUTO:recent_commits -->

---

## 手写：2026-09-14 第九轮 — 识别引擎升级（pHash → OpenCV 互相关，按证据 opt-in）

操作者质问「为什么识别这么差」后做的根因分析 + 修复：

**MAA 澄清**：项目**没有用 MAA**（winter_agent_v2 零 MAA 代码；宪法里只是概念位）。
执行后端是自写 ADB 封装（adb shell input tap / exec-out screencap）。

**识别差的五个根因**：① 模板靠人肉测量（战斗按钮偏 103px 事故）；② 模板整族漂移；
③ 页面模型缺失（情报板钉子从未建模）；④ 小字 OCR 碎片化；⑤ 单信号判定。

**引擎升级（核心修复）**：新增 winter_agent_v2/matchers.py — OpenCV
TM_CCOEFF_NORMED 多尺度（0.9/1.0/1.1）互相关，带 ±40px 搜索窗与 0..1 绝对分。
tools/ab_matcher.py 做 A/B：战斗按钮正样本 1.000 / 负样本 0.216、0.142（分离 +0.784）；
胜利横幅 1.000 / 0.159、0.347（分离 +0.653）——**绝对分阈值远比汉明距离可判**。
接入方式：按记录 opt-in（matcher=ccoeff, max_distance=16），已切换 4 个 hero 流程模板；
其余模板行为完全不变（无未验证的全局切换）。帧级 4/4 正负验证通过，39 项测试零回归。

**防呆工具**：tools/verify_template.py — 对任意 semantic 打印 ROI/matcher/provenance，
并在帧上画出红圈+匹配框，强制目视复核。**因为模板匹配自己的裁剪区永远 d=0，
距离 0 不能证明坐标对**（pitfall 11）。

---

## 手写：2026-09-14 第八轮 — 英雄之旅链路真机闭环（操作者纠正后）

**操作者指出「你就是没点击战斗按钮」——完全正确。** 用叠加图复核发现：BTN_HERO_FIGHT
模板裁在英雄头像行（偏 103px），自匹配 d=0 掩盖了错误；此前所有「点击无效」的诊断
（含「出战队伍已满」的误读——那是点英雄槽位的换人拒绝）都建立在错误前提上。

修正后一击生效：**战斗 → 胜利 + 获得奖励**（24万×2/4.8万/1.2万/700），
证据 dataset/truth_audit/hero_fight_final_20260914/。新增 POPUP_HERO_BATTLE_VICTORY
模板（d=0，负向对照通过：小队页/地图均不误报）与大脑 BACK 关闭分支。

完整链路：钉→卡→前往查看→营地探险→小队设置→战斗→胜利→BACK→情报板。
教训写入 03 坑列表第 12 条（模板自匹配是循环论证）。

---

## 手写：2026-09-14 第七轮 — Skill/MCP 工具链审计 + 英雄之旅推进到小队页

**Skill 审计**（操作者指令）：安装 skills-security-check（云鼎）并用它实测审计
winter-os-takeover（Benign 95）；创建项目级 skill-install-gate 门禁 +
SKILL_AUDIT.json 台账；playwright-cli 与 agent-browser 重复→前者保留不主用；
拒绝 github MCP（无远程仓库）。台账见 .workbuddy/skills/SKILL_AUDIT.json。

**MCP 审计**：用户层 mcp.json 为空=零自装；宿主 4 个 MCP 处置完毕
（mail/genie-baas 外发面禁用、weixinpay 永久禁用、sheetagent 按需）；
专家零 MCP 强制依赖。docs/MCP_AUDIT_2026_09_14.md。

**记忆架构**（操作者指令）：docs/MEMORY_ARCHITECTURE_2026_09_14.md；
P0 双记忆根合并（M1 零丢失合并/M2 指针/M3 宪法 18b）+ P1 evidence/INDEX.json
（305 条）已落地。

**英雄之旅真机推进**：路线打通到小队设置页（钉→卡→前往查看→探险→小队页，
全链视觉/技能/验证器就位），但「战斗」点击不生效（见 04 0k）。体力花费 157→157
（本轮无新消耗）。修复过程中附带发现并修复 vision.py 的 return 缩进破坏
（UnboundLocalError: marches）。

---

## 手写：2026-09-14 第六轮 — 情报循环 + 体力读取碎片修复 + 常驻自动化

（第六轮补齐，2026-09-14 16:50-17:00）

操作者指令：**循环进行，把情报任务做完再做其他任务**。

### 情报循环结果（真机）

- 新增 `tools/run_intel_loop.py`：反复调用真实 `run_live.py --goal INTEL`，
  统计 dispatches / claims / 体力变化，停止条件全部诚实（体力耗尽 / 连续静默 / 轮数上限）。
- **本轮实测**：3 轮全部 `intel_not_available`（exit 0）→ **情报列表已排空**：
  第五轮 run6 已派出最后一个巨兽任务（体力 305→295）、run7 已领取、run8 已关闭弹窗。
- 真机读取刷新倒计时 **`下次刷新：06:56:37`** → 下批任务约 **23:51**（本地）出现。
  列表为空不是缺陷，是账号真实状态。

### 顺手修掉的真缺陷：HUD 体力读数丢位

- 真机暴露：HUD 把体力 **295 读成 29**（同一分钟情报页明明显示 295）。
- 根因（精确复现）：ROI 内 OCR 把 `295` 拆成 **3 个重叠碎片** `'29'`(0.991)+`'9'`(0.999)+`'5'`(1.0)，
  旧 `parse_stamina_number` 取第一个 → 29。这个错误数字会污染所有体力决策。
- 修复：`parse_stamina_number` 改为**几何合并**——按 x 左→右扫描，跳过左边缘落进
  已覆盖跨度的碎片（同一数字的重复读取），只追加向右扩展的 token。
- 回归：新 fixture `map_hud_with_stamina_295__roi_fragments.png` + 2 个新测试
  （合成碎片单元测试 + 真机帧端到端）；历史 200 帧不回归、遮挡帧仍诚实返回 None。17 项测试通过。

### 常驻自动化（落实「循环进行」）

- 曾创建 **「Winter V2 情报循环（每小时）」**（当时记录的 id `1a07567f-2868-4414-9010-2b411ae3a85d`）：
  每小时自动跑一轮 `run_intel_loop.py 6`，列表为空时几十秒退出，
  新任务出现即自动打巨兽/领奖励，含付费控件硬边界与失败如实上报。
- 下批情报（~23:51）出现后会被自动消化，无需人工。
- ⚠️ **第九轮更正（重要）**：上述 id **在自动化接口里查不到（not found）**，
  即该自动化**实际并不存在**，那段时间并没有任何无人值守在运行。
  第九轮已重建 **`7c1c18c1-94ca-4051-a2ca-7a1614cb3979`**（ACTIVE，每小时）。
  **教训**：handoff 记录的"已完成"不等于事实——自动化这类外部状态必须用接口复核。

### 状态

- 门禁：情报/召回/体力子集 17 passed；全量基线 381 passed（上一轮）。
- 情报任务 = **做完**（列表排空，等待刷新，自动化接管）。

---

## 手写：2026-09-14 第四轮 — 修复体力出口链路断裂（情报巨兽）

上一轮如实记录的最高价值任务：`OPEN_INTEL_BEAST_TARGET` 失败（`INTEL_BEAST_TARGET_NOT_PROVEN`）。
本轮定位并修掉了**两层**根因——都不是当初猜的「点击坐标漂移」。

### 根因 1：巨兽目标卡模板整体过期（新客户端布局）

真机帧里的 `推荐实力5,107,044`、`等级22大角鹿`、`出征 10` 与代码里 `INTEL_BEAST_10`
的标定**完全一致**，说明内容没变、位置变了。实测匹配距离：

| 模板 | 实测距离 | 阈值 |
|---|---:|---:|
| `BTN_BEAST_START_MARCH` | **30** | 8 |
| `DIALOG_BEAST_TARGET` | 14 | 8 |
| `BTN_BEAST_DISPATCH` | **36** | 8 |

点击坐标其实是**对的**：`BTN_INTEL_VIEW_TARGET` 距离 6，中心 (0.5, 0.73) 正好落在 OCR 读到的
`前往查看` 框 (px 292,914–428,955) 上。问题在于点完之后客户端把结果画在**世界地图**上
（目标卡），而模板层认不出卡 → 判成 `Page.MAP` → 要求 `Page.BEAST` 的 verifier 永远不可能通过。

`BTN_BEAST_START_MARCH` 是**双载荷**语义：既是页面证据，又是 `INTEL_BEAST_START_MARCH`
（出征按钮）的点击目标。按测量值新增记录（`tools/register_beast_target_templates.py`），
旧记录保留作 provenance（`find()` 取最佳匹配）。修复后该帧判为 `Page.BEAST`，
verifier 复算 **OK**，负向对照（普通地图帧）仍为 MAP。

### 根因 2：情报列表「空」这个状态在视觉层根本没有分支

`OPEN_INTEL_BEAST_TARGET` 修好后，链路不再卡在巨兽卡上，却暴露出下一步：情报页显示
`intel.status = UNKNOWN` → 大脑只能 `SAFE_STOP intel_state_unknown`（exit 2，看起来像失败）。
实测两帧的**可区分证据**：

- 有任务卡：OCR 出现 `前往查看`（px 292,914）
- 空列表：只有 `情报` / `体力` / `下次刷新：07:59:21` 头行

**关键取舍**：不能用「模板没匹配」推断空列表——本轮刚被模板过期坑过一次，
那样会把「模板失效」误报成「没有任务」并静默结束目标。所以只在 OCR 找到**正向证据**时
才判定，判不出来就保持 `UNKNOWN`。

结果：`intel_state_unknown`（exit 2）→ **`intel_not_available` + `list_read=True`（exit 0）**。
「账号当前没有情报任务」从「看起来故障」变成「诚实地说无事可做」。

### 未完成（如实记录）

- **巨兽链路没有真机端到端跑通**：修好之后情报列表恰好空了（`下次刷新 07:59:21` 已过但未刷新），
  没有任务可点。端到端待列表出现任务后重跑。
- 体力 350→305 的下降**无法归因**（episode 流无对应记录），已记入 `04_OPEN_ISSUES.md` 0g。

---

## 手写：2026-09-14 第三轮 — 体力可观测 + 撤回可调度（操作者策略落地）

操作者策略：**体力满了就去花（情报/巨兽），奖励及时领，采集只在队列没有更好用途时做；
队列需要时可以随时撤回（包括为了验证实验）。**

### 让策略真正生效的四件事

1. **体力在地图上可观测**（`winter_agent_v2/ocr.py`）
   - `HUD_STAMINA_ROI` = x 0.040–0.098、y 0.0755–0.0945，来自**测量**而非目测。
   - **必须单独对 ROI 做 OCR**：实测全屏 OCR 会漏掉这个小数字（同一帧全屏 token 里没有，
     裁成 ROI 后 0.999 读出 `350`）。全屏结果只作兜底。
   - 真机读数 `200` → 领取后 `350`；`AVOID_STAMINA_WASTE` 因此可被发现。
2. **免费体力领取**（`OPEN_STAMINA_SOURCES` + `CLAIM_FREE_STAMINA`）
   - 真机：面板 `200/200` + `领取` → 一次点击 → `350/200` + `领取` 变 `下次补给 04:52:52`。
   - 面板里只有一行免费；付费行（`购买并使用 💎300` / 月卡 / 礼包 / 英雄集结）已登记为
     **负向对照模板**，并有测试断言没有任何技能把它当目标。
3. **撤回两步拆分**（`SELECT_MARCH_TO_RECALL` + `RECALL_MARCH`）
   - 与既有 `EXPLORATION_IDLE_CLAIM` → `CONFIRM_...` 约定一致。
   - **实测纠正**：撤回不立刻释放槽位（确认后仍 6/6，该行变「返回中」；13:53 6/6 → 14:06 5/6）。
     原 verifier `NORMAL_IDLE_SLOT_INCREASED` 会判掉正确撤回，已改为状态迁移。
   - 只有本循环自己打开的召回框才会被确认；来路不明的召回框走 `CLOSE_POPUP`。
4. **行军计数改为 ROI 读取 + 不再编造**
   - `MARCH_COUNT_ROI` 单独读 `x/y`（全屏也会漏掉它）。
   - `vision.py` 删除 `calibrated_baseline_used` 这个「捕获时恰好有 1 条行军」的隐式假设：
     实测 6 条采集行军的帧上它会报 **1/6**，也就是 5 个假空闲槽。现在读不到就返回 `None`。
   - 连带修正了 4 个依赖该基线的测试（改用生产栈 `tests/live_stack.py`）。

### 真机证据

- 免费体力：`dataset/truth_audit/free_stamina_20260914_140601/`（领取前后两帧 + 面板复核图）。
- 撤回：`dataset/truth_audit/march_recall_20260914_135242/`（地图 → 召回框 → 确认后 `返回中`）。
- 体力 HUD：`dataset/truth_audit/hud_stamina_20260914/`（含「被对话框遮住 → unknown」负向对照）。
- 真实 loop 派发：`live_stamina_intel_run1` 日志里 `GET_MORE_STAMINA` 面板被判为
  「没有免费礼包」→ `BACK`，verifier PASS（说明面板解析与安全路径都通）。

---

## 手写：2026-09-14 接管第一轮

### 修复（按影响排序）

1. **`LiveRuntime._semantic` 访问器**（`winter_agent_v2/runtime.py`）
   - 症状：`run_live.py` 下一次运行 13 秒即 `AttributeError`，episode 一条都没写。
   - 根因：前一个账号把 `self.semantic_vision.find` 改成 `self.semantic_vision.semantic.find`，
     但 `run_live.py` 传入的已是 `SemanticROIVision`（另一种接线）。
   - 效果：**AUTO 主循环从「完全不能动」变成可执行**。

2. **资源页签识别重写**（`winter_agent_v2/vision.py`）
   - 从「4 个写死的 x 中心 + pHash」改为「页面门控 → 白色角标锚点 → 相对布局 → 格内模板」。
   - 实测页签带：7 格，pitch 157px，格宽 145px，角标两竖线间距恒 144–145px。
   - 效果：真机 22/22 帧正确；选中态距离 ≤1.2、非选中态 ≥13.0；
     顺带消灭了「HOME 画面误报 `RESOURCE_COAL_SELECTED`」。
   - 新增 `selected_tab_left / resource_cell_center_norm / resource_tab_swipe_for / resource_tab_offset`。

3. **`Page.MARCH` 采集分支**（`winter_agent_v2/brain.py`）
   - 症状：`START_GATHER` 验证通过后，第 3 步选 `WAIT`，以 `ENVIRONMENTAL_WAIT_NOT_PROVEN` 结束。
   - 根因：`Page.MARCH` 只有野战分支；采集页落到 `registry.ready()[0]` 兜底，
     而注册表里第一个 `required_page=None` 的技能是占位技能 `WAIT`。
   - 效果：真机 `SUBMIT → START_GATHER → DISPATCH_MARCH` 全链验证通过，退出码 0。

4. **`SWIPE` 能力**（`device.py` / `executor.py`）
   - 页签带会滚动，没有 swipe 就无法选中屏外的 WOOD/COAL/IRON。

5. **失败原因拆分**（`verifier.py`）
   - `verify_march_page_open` 拆为 `MARCH_PAGE_ACTION_MISSED`（点击未生效）
     与 `MARCH_PAGE_NOT_RECOGNIZED`（页面识别失败）。
   - `verify_resource_selected` 不再把「读不到等级」当作选中失败——等级是**独立观测**，
     把它并进选择判定会让一个脆弱读取拖垮整条链路。

6. **证据与保留根治**（`retention.py` / `learning.py` / `runtime.py`）
   - 保护名单补上 `verified / production / normalized / external`——这两个长期保留区
     **此前完全不在保护名单内**，可以被剪掉。
   - 新增 `referenced_evidence()`：被 episode 引用的帧永不被剪除。
   - Episode 增加 `episode_id / goal_id / step_id / before_screenshot / after_screenshot / verifier_ok`。

7. **Worker 崩溃可归因**（`tools/control_panel.py`）
   - `except Exception` → `except BaseException`，写完整 traceback + 运行时快照 + 线程清单到
     `learning/control_panel/crashes/`。
   - 失败分类 `ENVIRONMENT`（不计入 `unexpected_worker_exits`）vs `WORKER_CRASH`（计入）。

8. **覆盖率模型重建**（`capability_coverage.py` + `knowledge/goals/goal_capability_map.json`）
   - 从「Goal 需求字符串直接匹配注册表字符串」改为
     `Goal → Canonical Capability → Registered Skill → Production Evidence`。
   - 输出 design / implementation / live / stable 四层覆盖 + 5 类状态。
   - 效果：纠正了 5 个 Goal 的错误分类（不是 NEVER_TRIED，而是 BLOCKED）。

### 事故

- 清理 `tools/_*.py` 时**按前缀批量删除**，误删 15 个 Codex 遗留探索脚本；
  当时项目不是 git 仓库 → **不可恢复**。已建 git 仓库作为补救。

### 遗留

- `DISPATCH_NOT_PROVEN` x28 未定位。
- 「四资源各 ≥3 次闭环」验收未达成（当前 MEAT 1 次、WOOD 1 次；COAL/IRON 尚未尝试）。

---

## 手写：2026-09-14 第三轮（验收 harness + 资源可用性活锁）

### 1. 建立可重复的验收 harness

`tools/run_gather_acceptance.py`：逐次运行真实有界 live loop，记录
**每一步的技能与 verifier 结果**、stop_reason、以及**整车是否闭环**
（「3 次成功」不能被某个子步骤的侥幸成功满足）。
输出 `evidence/gather_acceptance_<stamp>.json` + 每轮一个截图目录。

### 2. 发现并修复「资源不可用活锁」

真机对照实验（`tools/probe_resource_availability.py`）：

| 资源 | 等级 | 结果 |
|---|---|---|
| MEAT | 7 | ✅ 直接搜到资源点 |
| WOOD | 1~8 全部 | ❌ `RESOURCE_NOT_FOUND` |

结论：**不是等级问题，也不是 WOOD 识别问题**，而是「该资源当前在范围内没有可采节点」。

原代码的轮换只在 `DISPATCH_MARCH` 成功时才推进（`completed()`），
所以不可用的资源会被**永远选中**——活锁，不是慢路径。

修复：
- `ResourceRotationStore` 新增 `unavailable()` 冷却（默认 30 分钟）与
  `target()` 排除冷却中的资源；全部冷却时回退到全集而不是死锁。
- `LiveRuntime` 在 `SUBMIT_RESOURCE_SEARCH` 返回 `RESOURCE_NOT_FOUND` 且
  等级已在最小值时，标记该资源不可用并**在同一次运行内切换**（`max_resource_switches`）。
- `choose_resource_balanced()` 新增 `exclude` 参数。
- 顺手修掉一个真实健壮性缺陷：状态文件里非数字的 `dispatched` 值会让
  `int()` 抛异常，把文件损坏升级成整个工作流失败。现在是完全防御式读取。

### 3. 顺带澄清两个此前的错误判断

- **等级筛选器范围是 1..8，不是 1..27。** 真机连续点「+」得到 1→4→8 后停在 8。
  上一轮记录的「1~27」是误解（27 是野兽等级上限）。`resource_level_max = 8`
  与线性标定**本来就是对的**，`resource_level()` 读数与真机一致。
- 资源页签带又出现第三种滚动偏移（MEAT 落在 0.4993），锚点+相对布局
  **自动适应**——这是写死坐标做不到的。

### 4. 真机验收结果（本轮 3 次运行）

| 运行 | 计划资源 | 结果 |
|---|---|---|
| 1 | WOOD | ✅ 整车闭环（4 步全 verifier OK） |
| 2 | MEAT | ✅ 整车闭环（5 步全 verifier OK） |
| 3 | WOOD | 第 3 步 `RESOURCE_NOT_FOUND` → **自动切换资源** → 第 4–6 步全部 OK，闭环达成 |

第 3 轮正是活锁修复的**真机验证**：此前这种情况会直接结束运行。

---

## 手写：2026-09-14 第四轮（DISPATCH_NOT_PROVEN x28 根因定位并修复）

### 1. 定位到根因（有真机帧 + OCR token 证据）

跑 COAL 验收时全部步骤都通过，只有最后一步失败：

```
5 DISPATCH_MARCH  verifier=False DISPATCH_NOT_PROVEN | MARCH -> EVENT
```

看 `after` 帧：**那是世界地图**，行军队列显示 `6/6`、5 条「采集中」——**派兵其实成功了**。
逐层诊断（`tools/diagnose_map_event_misclassification.py`）得到完整因果链：

1. 行军队列浮层打开时盖住了「搜索资源」按钮，且 `STATUS_*` 行模板不匹配该布局
   → 模板层对这张地图返回 `page=UNKNOWN`；
2. `HybridVision` 回落到 OCR 分类器；
3. OCR 读到地图右侧活动栏的**按钮文字**「常规活动」（置信 0.998）
   → 判定 `Page.EVENT`，且 `marches=[]`、`march_used=None`；
4. `verify_wood_dispatch_from_march` 需要「地图 + 有行军在跑」→ 失败。

**这就是 28 次 `DISPATCH_NOT_PROVEN` 的来源。**

### 2. 两处修复

- **世界地图常驻锚点**：`BTN_OPEN_HOME` 匹配 **且** `PAGE_MAP` 不匹配 → 地图
  （主城显示的是「地图」按钮，两者互斥）。修复后同一帧：
  `page=MAP marches=['GATHERING'] march_used=6` —— 正是 verifier 需要的证据。
- **OCR 规则集删掉「常规活动」**：它是按钮标签，不是页面标题。
  新原则写进 docstring：**玩家不在那个页面时也能看到的文字，不能用来判定页面。**
  「最强王国」（活动页自身的标题）保留。

### 3. 验收数字被大幅下修（诚实性修复）

第一次统计出 `WOOD 27 / MEAT 3 / COAL 1 / IRON 1 = 32`。
但 32 条里有 **27 条是旧代码写的行**：没有 `recorded_at`、没有 `episode_id`、
没有截图，且当时的 `resource_target` 是 vision 里**硬编码的 "WOOD"**。

加上证据门槛（必须有 `episode_id` 且截图存在）后的真实值：

| 资源 | 可追溯已验证闭环 |
|---|---:|
| MEAT | 2 |
| WOOD | 2 |
| COAL | 0 |
| IRON | 1 |
| **合计** | **5** |

排除 27 条无证据记录。**「无证据不算验证」同样适用于聚合统计。**

### 4. 发现的硬约束：验收受行军槽位限制

账号只有 **6 条行军队列**，每次闭环占用一条数小时。当前 `6/6` 全部采集中、空闲 0，
运行时正确地以 `no_idle_march` 停止（修复地图锚点后 `march_used` 才被正确读成 6，
此前误读 1/6 才敢继续派兵）。

**结论：「每资源 ≥3 次、合计 ≥12 次」不可能在单次会话内完成**，
必须跨多个行军返回周期。harness 已加入 `no_idle_march` 早停，避免空跑浪费预算。
