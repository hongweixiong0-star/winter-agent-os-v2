# 建筑升级面板证明到不了"模板层成功"的那条路（2026-10-06）

**一句话**：`OPEN_BUILDING_UPGRADE` 的验证器读 `upgrade_dialog_visible`，而这个键以前
**只有 OCR 分类器**会写，且只写在"模板层认不出页面"的分支里。模板层一旦认成 `BUILDING`
（生产上绝大多数情况），那个分支就被跳过 → 键根本不存在 → 面板明明开着也记
`BUILDING_UPGRADE_PANEL_NOT_PROVEN`。

## 证据（都是量出来的，不是推的）

- `learning/episodes.jsonl` 里该失败类型 **104 条**（10-03 ~ 10-05，最后一次 15:52:05 仍在发生）。
- 每一条的 `verifier_evidence` 都是
  `{"page_before":"HOME","page_after":"BUILDING","upgrade_dialog_visible":null}`。
- 每一条的 `state_after.building` **完全没有这个键**
  （只有 `upgradeable/id/name/level/target_level/identity_confidence/identity_source`）。
- 把最后那条失败帧的 OCR 重跑一遍分类器：`upgrade_dialog_visible = True`，
  且 OCR 读得到 `城墙 | 升级效果 | 城墙耐久度 | 25000+5000 | 需要条件 | 大熔炉等级29`。
  → 所以这是**接线缺口**，不是识别缺口。

## 缺口在哪

- 验证器：`runtime.py:548-555`（`"OPEN_BUILDING_UPGRADE": lambda b, a: ...`）。
- 只写键的地方：`ocr.py:5585-5630` 的分类器分支，**它直接 `return`**，而它整体位于
  "模板层没能命名页面"的那条路。`ocr.py:5631` 才是 `if primary.known:`。
- 已知页路径里读建筑身份的是 `_read_building_identity`（`ocr.py:5369`），
  它返回的 dict 里没有这个键。

**这是本模块自己记过三次的同一个教训，换了一页又犯**：
"下层通过 ≠ 生产入口会走到它"（`ocr.py` 里 `_read_training_camp_tabs`、训练分支、
以及 `observe` 包装 `_observe_inner` 的注释都在讲这件事）。

## 修法

在 `_read_building_identity` 的 `is_dialog` 分支里补上该键，紧挨着已有的
`RESEARCH_CENTER` 分支（那个分支为同样的理由做同样的事）。
**只作佐证**：页面已经是模板层给的 `BUILDING`，所以这一步永远不会改判页面。
**方向是更安全**：`brain.py:1878` 是"面板可见但升级未获授权 → SAFE_STOP"的守卫，
键变成 True 只会让它更容易触发。

## 回归测试

`tests/test_the_upgrade_sheet_proof_reaches_the_known_page_path.py` —— **走
`_read_building_identity` 而不是 `OCRPageClassifier.classify`**。
直接调分类器的测试在这条缺陷存在的全部时间里都会通过，那正是本模块记录过的错误形状。

证据帧放在 `dataset/truth_audit/building_upgrade_sheet_20261005/`（`dataset/raw/` 会被回收清理）。
该 PNG **不入 git**（`.gitignore:39` 排除新增的 `dataset/truth_audit/**/*.png`，这条规则是刻意的），
所以帧不在时测试 **skip** —— 但 skip 不等于"修复未验证"，验证是在真实帧上做的。

## 顺带发现（未处理，先记下来）

`tests/test_building_upgrade_entry_target.py` 有 **1 条先存的失败**：它断言
`dataset/raw/control_panel/runtime_auto/20261002_135045_182262/..._step_004_before_*.png`，
而该文件**已被回收清理**（目录还在，文件没了），它在 `FRAME.exists()` 守卫处就 `self.fail`，
早于任何被改代码。**25 个测试文件**引用 `dataset/raw/control_panel/runtime_auto` 下的帧 ——
"测试断言的数据会被保留策略删掉"是个真问题，需要决定：把被断言的帧钉进 `truth_audit`，
还是让这类测试统一 skip。

## 我一开始判断错的地方（留档以免重犯）

最先怀疑的是 `DISCOVER_EVENT_CALENDAR`（最近 200 条里占 68 条，34%）。**那个怀疑是错的**：
它在最近的序列里只成对出现（`FROM_HOME` → `TAB` 两跳），并且**确实收敛** ——
`learning/timed_event_schedule.json` 里 `1063040265` 的 `CALENDAR_GRID` 在 15:50:18 被写入了。
34% 是跨整个窗口的占比，不是"无限打转"。真正仍在持续的是建筑这条失败。
教训：**占比高 ≠ 没收敛**；判定"打转"要看最近序列 + 是否写回了状态。

## 还有一个坑（本轮踩到）

我在**数据根**（`main` 镜像，落后主线 474 提交）里 `grep` 代码，得到的答案是**过期的** ——
`SCROLL_QUICK_PANEL_BACK` 在数据根查不到，因为它在主线上。
**读代码必须 `cd` 到 pin**（`E:/无尽冬日智能体_worktrees/winter-prod-pinned/无尽冬日智能体`）。
`learning/` 是 junction 所以**数据**两边一致，只有**代码**会不同 —— 这个组合最容易骗人。
