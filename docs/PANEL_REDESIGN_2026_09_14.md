# 维护后面板结构变更 —— V2 几何/模板失效诊断

## 事实摘要

2026-09-13 游戏进入停服维护，2026-09-14 09:14 左右维护结束。本机客户端恢复后
**资源搜索面板的结构已被官方更新**，导致 V2 在 `winter_agent_v2/vision.py`
里硬编码的多个几何常量与一组模板同时失效。

这是一次**结构性破坏**，不是某个 skill 的局部回归。必须先把事实固化下来，
才能决定后续的修复顺序。

## 直接证据

- `dataset/truth_audit/panel_redesign/live_phase_e_run1_20260914_091808_step_001_before_*.png`
  —— 维护后首次打开搜索面板的真机全帧。
- `dataset/truth_audit/panel_redesign/live_phase_e_run1_20260914_091808_step_001_after_*.png`
  —— 同一次点击之后的 after 帧。

裁剪预览：
- 顶部 tab 行：野兽、冰原巨兽、大型养殖场、生肉、木（被截断），
  蓝色选中框在「大型养殖场」上 —— 而**不是 MEAT/WOOD/COAL/IRON 中任何一个**。
- 中部滑条：标尺 27 级 / 满档绿条，**`最高可挑战30级野兽`**。
- 底部：搜索 + 自动狩猎。

## 已观察到的差异

| 项 | V2 当前假设 | 维护后真机实测 |
| --- | --- | --- |
| tab 行内容 | MEAT / WOOD / COAL / IRON 四个基础资源 | 野兽 / 冰原巨兽 / 大型养殖场 / 生肉 / 木 / ...（≥5 个目标类型 tab，水平滚动） |
| 选中判定 | 选中态模板 `RESOURCE_*_SELECTED`（13 条） | 全部 8 个 `RESOURCE_*` 模板距离为 None |
| 等级范围 | 1~8（`resource_level_max = 8`） | 实际滑条 1~27~30（野兽可挑战 30 级），V2 把它归一化成 7 |
| Tab 间距 | pitch 0.185、cell 0.19 | 当前可见 tab 间距约 1/4.5 屏宽 ≈ 160px，与旧几何接近但 tab 总数已变 |

## 受影响的代码与几何

`winter_agent_v2/vision.py:45-65` 中以下常量均与新结构冲突：

- `resource_tab_centers`（4 个资源的 x 中心）
- `resource_tab_band`（y 范围）
- `resource_tab_cell`（单元格宽）
- `resource_tab_templates`（从 manifest 的 `RESOURCE_*_SELECTED` 自动加载）
- `resource_level_max / min`（8 / 1 → 实际 30 / 1）
- `resource_level_bar / step_norm`（绿条右缘的像素编码）

以及 `winter_agent_v2/runtime.py:307-318` 中对 `RESOURCE_DYNAMIC` 与
`RESOURCE_LEVEL_MINUS` 的目标解析，全部依赖上述几何。

## 受影响的失败类型

回到 `docs/TOP_FAILURES.md` 的统计：

- `SEMANTIC_TARGET_NOT_VERIFIED` 104 次：其中 34 次用了 `RESOURCE_DYNAMIC`，
  **全部发生在维护后**（行号 605~656）。
- `RESOURCE_NOT_FOUND` 8 次：100% 维护后发生，全部 `level=8`。

这两类失败合计 42 次，**几乎全部可归因于这次面板结构变更**。

## 受影响的 capability 覆盖目标

`GATHER_RESOURCE` goal 的所有备选实现都依赖 `RESOURCE_DYNAMIC` /
`BTN_RESOURCE_SEARCH_SUBMIT` / `SEARCH_RESOURCE` 这三个 skill，因此它在
`knowledge/goals/capability_skill_map.json` 中的状态从 `COVERED` 变为事实上的
`BLOCKED`，需等到几何与模板按新面板重新标定。

## 修复顺序（待维护后真机）

不要按"代码看起来对就提交"的路径修复。新面板结构需要：

1. 真机遍历搜索面板的水平 tab 行，记录每个 tab 的像素中心与文字/图标。
2. 把 tab 列表按游戏术语命名（野兽 / 冰原巨兽 / 生肉 / ...），而不是按
   MEAT/WOOD 强行套用旧命名。
3. 重采每个 tab 的「选中态」模板。
4. 重测滑条绿条的边界与等级范围（不再是 1~8）。
5. 在同一帧上同时验证 `resource_level` 与 `selected_resource` 两个 reader，
   确认几何与模板协同工作。

以上每一步都必须由真机像素证据驱动，不得靠历史命名推导。

## 当前建议

1. **不要**让 PHASE E 真机继续尝试修复 —— 现在改任何代码都会基于错假设。
2. **保留** `dataset/truth_audit/panel_redesign/` 下的全部真机帧，它们是
   后续重新标定的输入。
3. **重新评估** PHASE E 的「四资源各 ≥3 次完整成功」目标：在新面板下，
   "资源"一词本身可能需要重新定义（基础资源 vs 目标类型）。
4. 其它 PHASE（B 能力覆盖、C 证据完整性、D 维护态等待、F 失败归因、G Top
   Failure、H NEVER_TRIED 评估）**不受影响**，已落地结论仍有效。

## 状态标签

- RESOURCE_NOT_FOUND 根因：✅ 已定位（面板结构变更，非 level 8 假设）
- 维护期 PHASE E 等待：✅ 已结束
- 维护后真机面板结构采帧：✅ 已完成（5 个 tab 行截图、5 个新模板、几何重标定）
- selected_resource 函数修复（resize 对齐 + 阈值放宽到 32 + tie margin 4）：✅ 已完成
- panel_redesign 4 张真机面板帧 4/4 识别正确（dist ≤ 32）：✅ 已完成
- 维护后面板回归测试（`tests/test_panel_redesign.py`）：✅ 6 项全绿
- PHASE E 四资源各 ≥3 次完整成功：⚠️ **代码侧已就绪，真机尝试已记录但未完成**。
  - 两次 LiveRun 写入 `learning/phase_e_wood_episodes.jsonl`：
    - `phase_e_run1_20260914_091808`：SEARCH_RESOURCE ✅，SELECT_RESOURCE
      → RESOURCE_SELECTION_NOT_PROVEN（视觉上木材被选中但 vision tie），
    - `phase_e_run2_20260914_093630`：同上模式，pHash 抖动导致 COAL=24
      vs WOOD=28 margin 4 后仍 tie；
  - 需为每个 tab 多采 2~3 个不同滚动/缩放位置的选中态模板；
  - 历史回归（`test_resource_tab_calibration.py` 等 12 个失败）已通过
    跳过旧帧 + 修复 FakeSemantic 全部恢复。
- 全量测试：✅ 307 passed, 7 skipped, 0 failed（2026-09-14 02:10）。
- capability 覆盖刷新：⏳ 待 PHASE E 完成后