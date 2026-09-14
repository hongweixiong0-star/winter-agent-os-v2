# 05 — RECENT CHANGES

`AUTO:recent_commits` 块由脚本从 git 生成。下面的手写块按会话记录**改了什么、为什么改、
带来什么可测效果**——这部分机器读不出来。

<!-- AUTO:recent_commits -->
Last 12 commits (newest first):

- `68e3540 2026-09-14T13:11:55+08:00 fix(gather): break the unavailable-resource livelock + acceptance harness`
- `0f006ab 2026-09-14T12:36:41+08:00 docs(handoff): regenerate truth at the new baseline`
- `d3f974a 2026-09-14T12:36:28+08:00 chore: ignore the transient commit-message helper file`
- `7512a33 2026-09-14T12:36:15+08:00 feat(handoff): cross-account handoff mechanism + git baseline`
- `f9ef073 2026-09-14T12:29:31+08:00 chore: initial checkpoint of Winter Agent OS V2`

Uncommitted changes: 2
- `M .workbuddy-ai/handoff/.last_good_commit`
- `?? tools/_h.txt`
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
