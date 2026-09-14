# 05 — RECENT CHANGES

`AUTO:recent_commits` 块由脚本从 git 生成。下面的手写块按会话记录**改了什么、为什么改、
带来什么可测效果**——这部分机器读不出来。

<!-- AUTO:recent_commits -->
Last 12 commits (newest first):

- `446d909 2026-09-14T13:41:40+08:00 feat(policy): stamina spending beats gathering; gathering is LAST_RESORT`
- `f35df92 2026-09-14T13:32:27+08:00 docs(handoff): record the map-anchor fix, the corrected tally and the march-slot constraint`
- `7a3380d 2026-09-14T13:32:06+08:00 fix(vision): world map was classified as EVENT, breaking DISPATCH_MARCH`
- `8c59182 2026-09-14T13:13:18+08:00 docs(handoff): final truth refresh at the new last-good commit`
- `6189c67 2026-09-14T13:13:05+08:00 test(handoff): assert START_HERE leads to real commands and no orphan files`
- `65b2955 2026-09-14T13:12:09+08:00 docs(handoff): regenerate truth and record the new last-good commit`
- `68e3540 2026-09-14T13:11:55+08:00 fix(gather): break the unavailable-resource livelock + acceptance harness`
- `0f006ab 2026-09-14T12:36:41+08:00 docs(handoff): regenerate truth at the new baseline`
- `d3f974a 2026-09-14T12:36:28+08:00 chore: ignore the transient commit-message helper file`
- `7512a33 2026-09-14T12:36:15+08:00 feat(handoff): cross-account handoff mechanism + git baseline`
- `f9ef073 2026-09-14T12:29:31+08:00 chore: initial checkpoint of Winter Agent OS V2`

Uncommitted changes: 8
- `M .workbuddy-ai/handoff/.last_good_commit`
- ` M .workbuddy-ai/handoff/03_NEXT_ACTION.md`
- ` M .workbuddy-ai/handoff/04_OPEN_ISSUES.md`
- ` M .workbuddy-ai/memory/2026-09-14.md`
- ` M tools/_h.txt`
- `?? dataset/truth_audit/march_queue_20260914_134158/`
- `?? evidence/gather_march_queue_probe.log`
- `?? tools/probe_march_queue_recall.py`
<!-- /AUTO:recent_commits -->

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
