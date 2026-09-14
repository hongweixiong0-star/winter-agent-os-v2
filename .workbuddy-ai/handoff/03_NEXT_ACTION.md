# 03 — NEXT ACTION

> 本文件必须保持**短小、具体**。目标：新账号不读完整历史也能继续当前任务。
> `AUTO:next_action` 块由 `tools/update_workbuddy_handoff.py` 重写；
> 其余手写内容不会被自动覆盖。

<!-- AUTO:next_action -->
CURRENT PRIORITY: fill the missing skills that block 4 goal(s)
CURRENT TASK: implement `CHECK_ALLIANCE_EVENT` — missing from the registry, blocks 2 goal(s): ['ALLIANCE_TIMED_EVENTS', 'PARTICIPATE_BEAR']

WHY: 4 goal(s) BLOCKED, 8 PARTIAL, mean implementation coverage 0.54. The blocked goals share one small set of never-implemented skills, so one skill purchase can move several goals at once.

CURRENT ROOT CAUSE: SEMANTIC_TARGET_NOT_VERIFIED x104
LAST GOOD COMMIT: db268f9
CURRENT DIRTY FILES: 12
LAST PRODUCTION EPISODE: {"skill": "DISMISS_INTEL_GENERIC_REWARD", "result": "SUCCESS", "recorded_at": "2026-09-14T08:34:26.144051+00:00", "episode_id": "live_intel_full_run8", "before_screenshot": "dataset\\raw\\control_panel\\runtime_auto\\live_intel_full_run8\\live_intel_full_run8_step_001_before_20260914T083415178489.png", "after_screenshot": "dataset\\raw\\control_panel\\runtime_auto\\live_intel_full_run8\\live_intel_full_run8_step_001_after_20260914T083418180357.png"}
TOP FAILURE: {"failure_type": "SEMANTIC_TARGET_NOT_VERIFIED", "count": 104, "top_skills": [["SELECT_RESOURCE", 40], ["SEARCH_RESOURCE", 32], ["OPEN_MAIL", 13]]}

BLOCKED GOALS: ['KEEP_RESEARCH_PRODUCTIVE', 'ALLIANCE_TIMED_EVENTS', 'USE_FREE_ARENA_ATTEMPTS', 'LABYRINTH_DAILY']
MISSING SKILLS BY LEVERAGE: [('CHECK_ALLIANCE_EVENT', 2), ('CLAIM_EVENT_TIER', 2), ('JOIN_RALLY', 2), ('READ_BEAR_TIMER', 2), ('READ_COUNTER', 2), ('READ_TIMER', 2), ('USE_ACTIVITY_ATTEMPT', 2), ('ALLIANCE_HELP', 1), ('ALLIANCE_TECH_CONTRIBUTE', 1), ('OPEN_ARENA', 1)]
NEVER EXECUTED SKILLS (first 12): ['CANCEL_DUPLICATE_TARGET', 'CHECK_MARCH', 'CLAIM_FREE_STAMINA', 'CLAIM_REWARD', 'DISMISS_ALLIANCE_GENERIC_REWARD', 'DISMISS_EXPLORATION_REWARD', 'EXECUTE_INTEL_RESCUE_SURVIVORS', 'JOIN_RALLY', 'NAVIGATE_TO', 'OPEN_ALLIANCE_GIFTS', 'OPEN_INTEL_RESCUE_SURVIVORS_TARGET', 'OPEN_STAMINA_SOURCES']

NEXT EXACT ACTION: Add `CHECK_ALLIANCE_EVENT` to winter_agent_v2/skills.py v2_registry() AND register a post-action verifier in LiveRuntime.VERIFIED_ATOMIC (a skill without a verifier is never dispatched). It unblocks: ALLIANCE_TIMED_EVENTS, PARTICIPATE_BEAR. Requirement side: knowledge/goals/goal_capability_map.json lists it as an alternative for the blocked capability. Then REPLAY -> LIVE -> VERIFY -> EVIDENCE.

ACCEPTANCE: production episode + passing verifier + screenshot evidence, and the named goal(s) move off BLOCKED (live coverage increases).

DO NOT: re-architect, rename goals, or touch anything already live-verified without new failure evidence.
<!-- /AUTO:next_action -->

---

## 手写：当前任务的上下文

本区由人维护。生成器不会碰它。写「为什么是这个任务」以及「坑在哪」。

### 【最新，覆盖下面的旧判断】2026-09-14 操作者策略变更：体力优先，采集降为最低

操作者明确指令：

> 体力满了 → 撤回采集去做情报任务和打巨兽等性价比高的体力消耗 → 把体力用掉 →
> 各种奖励及时领取。**采集性价比很低，只有队列没有其他用途时才去采集。**

据此 `config/v2.json` 已改为：

- `march_policy.reserve_for_stamina: 0 → 2`（原来采集会吃掉全部 6 条队列）
- 新增 `resource_policy`：`gather_priority=LAST_RESORT`、`stamina_first=true`、
  `claim_rewards_promptly=true`

**### ✅ 情报任务状态（第六轮更新，2026-09-14 17:00）：**已做完，自动化接管**

- 情报列表已排空（真机 3 轮 `intel_not_available`，exit 0）；最后一个巨兽已派出（体力 295）。
- 下批任务 **~23:51**（真机倒计时 `下次刷新：06:56:37`）。
- **常驻自动化**「Winter V2 情报循环（每小时）」已创建（每小时跑
  `tools/run_intel_loop.py 6`）：新任务自动打、奖励自动领，无需人工。
- 顺手修复 `parse_stamina_number` 丢位（295 被读成 29，OCR 碎片 `'29'+'9'+'5'`），
  已几何合并 + fixture 回归（见 05 第六轮）。
- **情报做完后，按排序公式下一项是 `SEMANTIC_TARGET_NOT_VERIFIED` x104 家族**
  （SELECT_RESOURCE 40 / SEARCH_RESOURCE 32 / OPEN_MAIL 13，见 01_CURRENT_TRUTH）。

**两个卡点已于 2026-09-14 解决，并留下真机证据**（旧描述见文末历史区）。

##### ① 体力已可在地图上观测（整条策略的前提）

- `ocr.py` 新增 `HUD_STAMINA_ROI`，读地图 HUD 上的领主体力数值。ROI 是**测量**出来的
  （`tools/calibrate_hud_stamina.py` 直接打印 OCR token box，不靠目测）：
  x 0.046–0.089、y 0.080–0.091（720×1280），中心 (49,110)。
- **必须单独对这一小块做 OCR**：实测全屏 OCR 会漏掉这个小组件——同一帧的全屏 token 里
  根本没有它，而裁剪成 ROI 后以 **0.999** 置信度读出 `350`。原因写进代码注释了。
- 真机读数：领取前 `200`，领取后 `350`（地图显示当前值，不封顶）。
- 结果：`AVOID_STAMINA_WASTE` 现在能在地图上被发现，`stamina_first` 才有意义。

##### ② 撤回已可调度：4 个新技能，全部带 verifier

| 技能 | 动作 | verifier |
|---|---|---|
| `OPEN_STAMINA_SOURCES` | 点地图体力条 → 打开「获取更多」面板 | `STAMINA_SOURCES_OPEN` |
| `CLAIM_FREE_STAMINA` | 点面板里**免费的**「领取」 | `FREE_STAMINA_CLAIMED` |
| `SELECT_MARCH_TO_RECALL` | 点行军队列第 1 行 → 打开召回确认框 | `MARCH_RECALL_DIALOG_OPEN` |
| `RECALL_MARCH` | 点确认框的「确定」 | `MARCH_RECALLED` |

**实测纠正了一个错误假设**：撤回**不会立刻释放槽位**——确认后队列仍是 6/6，该行变成
「返回中」，槽位在部队回城后才释放（实测 13:53 = 6/6 → 14:06 = 5/6）。技能原本声明的
`NORMAL_IDLE_SLOT_INCREASED` 会**判掉一次正确的撤回**，已改为状态迁移判定。

**免费体力在哪**：面板里只有一行免费（「丰盛的招待」+ 裸露的 `领取`，旁边没有任何价格），
其余都带价（`购买并使用 💎300`、超值月卡、礼包购买、英雄集结「前往」）。付费控件已登记为
**负向对照模板**，并有测试断言没有任何技能把它当目标。

##### NEW: 下一轮第一动作（按顺序）

1. **行军计数会被覆盖层遮挡**：巨兽目标面板会盖住 HUD 上的 `x/y` 计数，此时
   `march_used=None`。这是**诚实返回 unknown**（旧代码在这种帧上会谎报 1/6，等于 5 个假空闲槽）。
   后果：计数未知 → `idle_marches=None` → 派兵和撤回都无法决策。
   证据帧 `dataset/raw/control_panel/probe/state_now.png`。
   下一步：把该面板识别为地图覆盖层并优先关闭，或改从行军列表行数推导计数。
2. **「下次补给」倒计时没有持久化**：面板上写着 `下次补给 04:52:52`，存下来就能在到期前
   跳过检查；现在每次运行都要开一次面板确认，白花 2 个动作。
3. `DISPATCH_NOT_PROVEN` x28 根因仍未定位。

#### 已经可以直接做的（不需要上面两项）

- **情报任务**：INTEL 全链已在 `VERIFIED_ATOMIC`（`OPEN_INTEL` 94% 真实成功率）。
  `run_live.py --goal INTEL` 现在就能跑。
- **打巨兽**：`SELECT_BEAST_TARGET` / `BEAST_HUNT` / `DISPATCH_BEAST` 都可调度。
  `run_live.py --goal BEAST_HUNT`。
- **奖励领取**：MAIL / DAILY / INTEL / EXPLORATION / ALLIANCE 的 claim 技能大多可调度。

> 注意：`march_policy.reserve_for_stamina: 2` 之后，当地图上空闲行军 ≤2 时，
> 大脑会返回 `SAFE_STOP reserved_march_for_stamina`——这是**正确行为**，
> 不是缺陷。它保证槽位留给体力任务。

---

### 旧判断（仍然有效，但优先级低于上面）

**为什么「补齐缺失技能」是长期最高价值**

2026-09-14 用新的能力模型核实后的结论：

- `NEVER_TRIED` 的 Goal = **0 个**。旧文档怀疑的 5 个（Arena / Labyrinth / Event /
  AllianceTimed / Bear）**不是「没试过」，而是「没有实现」**——它们要求的技能
  在注册表里根本不存在，只在 `knowledge/skills/candidate/*.json` 里有设计稿。
- 因此继续在采集链路上打磨收益递减；真正卡住 4 个 BLOCKED Goal 的，是同一小批缺失技能。
- 反过来，采集链路**必须**先守住：它是当前唯一每天真实运行的产出。

所以并行两条线：
1. **守住** 已 Live 的链路（Intel / Mail / Train / 采集），不要回归；
2. **补齐** 缺失技能，把 BLOCKED Goal 变成 PARTIAL → FULLY_LIVE_VERIFIED。

### 缺失技能清单（按 blocked_goals 排序，来自 capability_skill_map.json）

- `CHECK_ALLIANCE_EVENT`  → 卡 PARTICIPATE_BEAR + ALLIANCE_TIMED_EVENTS
- `READ_BEAR_TIMER`       → 卡 PARTICIPATE_BEAR + ALLIANCE_TIMED_EVENTS
- `CLAIM_EVENT_TIER`      → 卡 EVENT_MINIMUM_GUARANTEE + ALLIANCE_TIMED_EVENTS
- `JOIN_RALLY` / `START_RALLY` → 卡 PARTICIPATE_BEAR + AVOID_STAMINA_WASTE
- `OPEN_ARENA` `READ_FREE_ATTEMPTS` `SELECT_ARENA_OPPONENT` `START_ARENA`
  `VERIFY_ARENA_RESULT` → 卡 USE_FREE_ARENA_ATTEMPTS
- `OPEN_LABYRINTH` `READ_LABYRINTH_ATTEMPTS` `START_LABYRINTH`
  `VERIFY_LABYRINTH_RESULT` → 卡 LABYRINTH_DAILY
- `OPEN_EVENT` `READ_EVENT_PROGRESS` `READ_EVENT_TIMER` → 卡 EVENT_MINIMUM_GUARANTEE
- `OPEN_RESEARCH` → 卡 KEEP_RESEARCH_PRODUCTIVE（`RESEARCH` 本身已注册但为 BLOCKED）

### 坑（必须知道）

0. **这个项目的文件被两个地方同时编辑，外部编辑器会把旧缓冲区刷回磁盘，悄悄吃掉刚写入的改动。**
   本轮就中过招：`models.py` 的 `stamina` 字段、`brain.py` 的两条弹窗分支、`runtime.py` 的
   `resolve` 分支、`tests/test_ocr.py` 的辅助类都曾被无声还原。**症状极具迷惑性**：
   `grep` 能找到某处出现，但运行时报 `TypeError`/`NameError`，或某个分支干脆不生效。
   对策（必须照做）：
   - 改完代码立刻跑 `"E:/dongri-mumu-bot/.venv/Scripts/python.exe" tools/check_wiring.py`
     —— 它做的是**执行级**校验（导入对象、对真实 WorldState 真的调用 `RuleBrain.decide`），
     而不是字符串匹配。`problems: 0` 才算通过。
   - 校验通过后**立刻 `git commit`**，用 git 作为可恢复基线。
   - 跑测试前再跑一次校验；测试期间不要编辑被测试的文件。

1. **跑真机验证前先清 `__pycache__`。** 编辑器回写时可能带上较旧的 mtime，
   使 Python 认为旧的 `.pyc` 仍然有效 → **运行的是已回滚的字节码**（本轮表现为
   `OPEN_INTEL` 用了 `verify_stamina_sources_open`、免费体力检查不触发，而磁盘上的代码是对的）。
   固定流程：清 `__pycache__` → `tools/check_wiring.py` 显示 `problems: 0` → 立刻跑真机。
2. **不要用「模板没匹配」推断页面语义。** 模板会整体过期（本轮 `BTN_BEAST_START_MARCH`
   距离 30、`BTN_BEAST_DISPATCH` 距离 36，而点击坐标其实是对的）。
   要判定「空 / 无任务 / 不可用」这类语义，必须有**独立的正向证据**
   （例：情报空列表用 OCR 的 `下次刷新` 头行 + 无 `前往查看`）。

3. **跑全量测试要加 `--basetemp`**：默认临时目录在 `%TEMP%\pytest-of-*`，
   跑完清理时会被工作区的**批量删除安全钩子**拦下（69 个文件 > 阈值 50），
   进程被中断、拿不到汇总行（测试其实已经跑完）。用：
   `"E:/dongri-mumu-bot/.venv/Scripts/python.exe" -m pytest tests -q --basetemp="E:/无尽冬日智能体/tools/_pt_tmp"`

4. **不要写死坐标。** 资源页签带会滚动，客户端会把当前选中页签重新居中。
   已经实测到多种滚动偏移（0、+400px，以及 MEAT 落在 0.4993 的第三种）。
   必须走 `SemanticROIVision.selected_resource` 的白色角标锚点 + 相对布局。
5. **`run_live.py` 与 `control_panel.py` 传入的 vision 对象不是同一种。**
   用 `LiveRuntime._semantic` 访问器，不要直接 `self.semantic_vision.semantic`。
6. **新增 Skill 必须同时提供 verifier**，否则 `LiveRuntime.VERIFIED_ATOMIC` 不含它，
   就永远不会被 live loop 调度（`capability_coverage` 会把它算成「未实现」）。
7. **不要用通配符批量删文件。** 项目目录曾经不是 git 仓库；现在已经有了，
   但删除前仍必须逐项确认。
8. Bash 工具在本机**没有 coreutils**（`ls/cat/head/sleep/wc/date` 都不可用），
   PowerShell 工具**stdout 不回传**。所有命令都用
   `"E:/dongri-mumu-bot/.venv/Scripts/python.exe" -c "..."` 配合重定向 + Read 读取。
9. **等级筛选器范围是 1..8，不是 1..27。** 真机实测 1→4→8 后停在 8。
   `RESOURCE_NOT_FOUND` 不是等级问题，是「该资源当前范围内没有可采节点」。
   正确补救是**换资源**（`ResourceRotationStore.unavailable()`），不是降等级。
10. **升级/等待类操作要看清页面语义**：采集编队页的正确动作是
   `DISPATCH_MARCH`，不是 `WAIT`（`WAIT` 只用于维护/加载画面）。

### 真机环境（当前实测）

- MuMu 默认不启动。启动：
  `"D:/Program Files/Netease/MuMu Player 12/nx_main/MuMuManager.exe" control -v 0 launch -pkg com.gof.china`
  然后 `adb connect 127.0.0.1:7555`。
- 真机可用时：720×1280，前台包 `com.gof.china`。
- 跑项目脚本必须用项目 venv：`E:\dongri-mumu-bot\.venv\Scripts\python.exe`（含 PIL / rapidocr）。
  托管 Python 3.13 **没有 PIL**。
- 脚本里**不要用 `date`/`head`/`tail`** 之类外部命令（不存在）。
- 验收扫描：`tools/run_gather_acceptance.py --runs N`，每轮约 1–2 分钟。
