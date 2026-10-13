# 生产分支被重置：一次会话的代码提交被卷走（2026-10-05 21:3x 发现）

> ## 处置结果（21:5x，操作者裁定："全部恢复到当前分支" + "你接着做完，对方不做了"）
>
> 1. **先解决分叉**：`958fc9b3` 是 `297af0d1` 的祖先 ⇒ **快进**（不重写任何历史）。
>    快进被一个未跟踪文件挡住（`knowledge/events/bear_participation_chain_status.json`）；
>    按规矩**先逐字节比对**（工作树 4895 B vs 提交 4987 B ⇒ **不同**），
>    **备份到 `E:/_bak_bear_status_20261005.json` 后再移开**，快进后 git 恢复了提交里**较新的那份**
>    （`d5f4178f…`），旧快照留在备份里，**没有丢失**。
> 2. **逐个 `git cherry-pick -x`（保留原提交信息，它承载着测量）**，按时间序：
>
>    | 提交 | 结果 |
>    |---|---|
>    | `2c08116f` 冰原巨兽 strip OCR | **空补丁** ⇒ 已在场（对方 `77ec0c43` 把它的 `ocr.py` 改动与该测试一并收了） |
>    | `ad7c9ade` 建筑卡片版式 | 挑回 `2424ba32`，无冲突 |
>    | `b0a77a74` 猛犸目标=印字 | 挑回 `7e1711f7`，自动合并 |
>    | `c873ab0c` 训练守卫 | 挑回 `3f7613f6`，无冲突 |
>    | `766630e3` 面板带移回 | 挑回 `ae8ef9e6`，自动合并（6 文件） |
>    | `fa015b4a` 花费身份门 | 挑回 `22d9ca3d`，无冲突 |
>
>    **`2bc37b32`（路由退役）跳过**：它只有两个产物（数据文件 + 那个测试），**两半都已在场**
>    （数据在数据根未受影响；测试被 `77ec0c43` 吸收）。
>    **`8c6974af` + `b4c4b3b1`（页签能力与其回退）跳过**：净值零。
> 3. **零冲突**，五个标识全部复核在场（`_current_upgrade_sheet_layout` / `BEAST_LABEL_TARGET_SPECIES` /
>    `quick_panel_is_open_on_a_tab_without_the_training_entry` / `SCROLL_QUICK_PANEL_BACK` /
>    `building_upgrade_needs_a_known_identity`）。
> 4. **测试**：五条修复各自的 6 个测试文件 ⇒ **53 passed / 1 failed / 1 skipped**，
>    那一条失败是**既有红**（`test_the_archived_frame_drives_both_halves_of_the_hop`：取证帧已被保留策略删除）。
> 5. **重放后的 A/B**（当前 HEAD vs 基线 `297af0d1`，180 个文件，**按失败测试名**比对）
>    —— 见下面 §「重放后的 A/B」。
>
> **教训（写给下一位）**：`git branch -a --contains` 为空 + 磁盘代码不含修复 = 真的被卷走；
> 但**`git cherry -v` 的 `+/-` 在这里不可靠**（内容可能被别的提交以不同 patch-id 吸收），
> **可靠的判据是"用该提交真正新增的符号去 grep"**。我第一次 grep 用的是**既有的**标识
> （`NO_BUILDING_NAME_TOKEN`、`SELECT_BEAST_TARGET_MAMMOTH`），差点得出"已被覆盖"的假结论。

**一句话**：`codex/production-pin-recovery` 被 `git reset` 到 `6bef9082` 并另起了一条线，
**我这次会话的 7 个代码修复随之离开分支与磁盘**；数据侧改动与两份文件幸存。

## 事实（用 git 证据，不是印象）

```
958fc9b3 HEAD@{0}: reset: moving to 958fc9b
77ec0c43 HEAD@{1}: reset: moving to 77ec0c43
77ec0c43 HEAD@{2}: commit: chore(artifacts): commit the session's tests, observation tools and hand-off
ab0e9302 HEAD@{3}: reset: moving to ab0e9302
69f8ebfc HEAD@{4}: reset: moving to HEAD      ← 我的最后一个提交
69f8ebfc HEAD@{5}: commit: docs: say that the deeper handoffs are untracked, and why   ← 我的
80c9f8bd HEAD@{7}: commit: docs: say which HEAD docs/HANDOFF.md describes              ← 我的
a711f028 HEAD@{9}: commit: docs: hand the current state over in docs/HANDOFF.md         ← 我的
```

- `git branch -a --contains <我的任一提交>` → **全部为空**（只剩 reflog，`git gc` 可回收）。
- 分支现在的历史：`958fc9b3 → 77ec0c43 → ab0e9302 → 1733cbe8 → 6bef9082 → …`，
  即 **reset 到 `6bef9082` 后另起**。我那条 `2c08116f…69f8ebfc` 不在其中。
- `main` 同时前进到 `297af0d1`（`130ad557 fix(bear)`、`7580eb57 feat(bear)`、`0df4f178`、
  `958fc9b3 fix(events)`、`1733cbe8 feat(activity)` …）⇒ **`main` 与分支已分叉**，
  `tools/check_mainline.py` 报 `MAINLINE_BROKEN=1`（`mirror main 297af0d1` 不在分支上）。
- 磁盘代码**不再包含我的修复**（逐个 grep：`building_upgrade_needs_a_known_identity`、
  `SCROLL_QUICK_PANEL_BACK`、`quick_panel_is_open_on_a_tab_without_the_training_entry`
  均已不存在）。

## 已做的保护（只增不改，不影响生产）

```
git branch rescue/20261005-session-5-fixes 69f8ebfc
```

12 个提交（含 7 个代码修复）现在有 ref 引用，**不会被 gc 回收**。
该分支**未推送、未合入、未改动 `main` 或工作树**；要丢弃就 `git branch -D` 即可。

## 清点：哪些活着、哪些被卷走

| 我的工作 | 现状 |
|---|---|
| `2bc37b32` 路由退役（**数据** `knowledge/execution/backend_routing.json`） | **仍在生效**：两个技能 `preferred=ADB` / `recognition_backend=LEGACY` / `recognition` 已删，`not_migrated` 两条俱在 |
| `reuse_note` 写回（数据 `knowledge/external/external_capability_map.json`） | 仍在磁盘 |
| `docs/HANDOFF.md`（七问交接） | **已被对方 `77ec0c43` 提交进分支** ✓ |
| `tests/test_a_blind_node_does_not_shadow_the_frame_itself.py` | 同上，已被吸收 ✓ |
| `2c08116f` 冰原巨兽 strip 的 OCR 读法 | **分支与磁盘都没有**；提交在 rescue 分支 |
| `ad7c9ade` 建筑升级卡片版式 | 同上 |
| `b0a77a74` 巨兽目标 = 帧上印出的词 | 同上 |
| `c873ab0c` 训练入口面板守卫 | 同上 |
| `766630e3` 面板可见带移回上方（5 文件） | 同上 |
| `fa015b4a` 花费身份门（brain + 2 测试） | 同上 |
| `8c6974af` 页签能力 + `b4c4b3b1` 其回退 | 净值 **零**，无需恢复 |

## 为什么不由我自行重放

对方那条线**正在同一片区域工作**，而且方向重叠：

```
1733cbe8 feat(activity): a SCHEDULED_* ticket asks the page its read can actually run on
958fc9b3 fix(events): an activity's own occurrence answers its window, and a lead is not a plan
0df4f178 test(events): pin the plan/identity split, because either half can regress alone
130ad557 fix(bear): correct my own false conclusion -- the client printed no bear on those frames
```

我的 `c873ab0c`（训练分支的派发守卫）与 `766630e3`（面板可见带）**可能**与它们改动同一处 brain 分支。
**在一棵另一个会话正在构建的分支上单方向重放 7 个提交，可能造成冲突、重复或互相矛盾的修复**，
所以这一步属于需要操作者裁定的协调决定，而不是我可以自行判断的技术决定。

## 若要恢复，我的建议顺序（供裁定用）

1. **先看对方那条线是否已经覆盖**：逐个比对 `git show 1733cbe8` / `958fc9b3` 与
   rescue 分支上对应提交改了哪几个文件、哪几段；**只挑对方没覆盖的**。
2. **优先恢复独立、无重叠的两个**：
   - `fa015b4a` 花费身份门（`upgradeable` 单独不足以授权花费；30 个真实状态全部 `id=UNKNOWN`）
   - `2bc37b32` 已在数据侧生效 ⇒ 代码侧**不需要**恢复
3. **冲突风险最高的最后再看**：`c873ab0c` + `766630e3`（都在训练分支/面板），
   因为对方的 activity/event 线就在旁边。
4. 恢复方式用 `git cherry-pick -n`（不自动提交）逐个跑测试，**不用 merge**，避免把整条线拖进来。

## 另一件独立的事

`tools/check_mainline.py` 现在 `MAINLINE_BROKEN=1`（`main` 前进到 `297af0d1`，不在分支上）。
这**不是**本次重置造成的直接后果，而是 `main` 被推进的结果；修它要么把分支 rebase 到 `main`，
要么把 `main` 对齐到分支 —— **两条路都会动到对方的线，同样需要裁定**。
