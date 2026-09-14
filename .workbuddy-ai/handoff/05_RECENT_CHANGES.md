# 05 — RECENT CHANGES

`AUTO:recent_commits` 块由脚本从 git 生成。下面的手写块按会话记录**改了什么、为什么改、
带来什么可测效果**——这部分机器读不出来。

<!-- AUTO:recent_commits -->
Last 12 commits (newest first):

- `f9ef073 2026-09-14T12:29:31+08:00 chore: initial checkpoint of Winter Agent OS V2`

Uncommitted changes: 8
- `M .gitignore`
- ` M .workbuddy-ai/memory/2026-09-14.md`
- ` M dataset/external/repositories/whiteout-survival-bot`
- ` M dataset/external/repositories/wosbot-sparse`
- `?? .workbuddy-ai/handoff/`
- `?? START_HERE.md`
- `?? tools/handoff_run.txt`
- `?? tools/update_workbuddy_handoff.py`
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
- 「四资源各 ≥3 次闭环」验收未达成（本轮只有 1 条完整链路）。
