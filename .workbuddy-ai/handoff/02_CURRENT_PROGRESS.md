# 02 — CURRENT PROGRESS

本文件回答「项目现在走到哪一步了」。机器事实由生成器刷新，判断由人维护。

<!-- AUTO:progress -->
Machine progress at 2026-09-14T12:30:35+00:00 (commit da28686):

- goals: 16 — FULLY_LIVE_VERIFIED 1, PARTIAL 8, NEVER_TRIED 0, BLOCKED 4, DEGRADED 3
- mean implementation coverage: 0.54
- mean live coverage: 0.5452
- skills: live_verified 23, stable 19, degraded 9, only_failed 11, never_executed 26
- episodes: 918 (success 614 / failure 299, rate 0.6725)
- evidence integrity: PASS
<!-- /AUTO:progress -->

---

## 手写：阶段性判断

### 已 Live 且应守住（不要动）

| 能力 | 证据 |
|---|---|
| Intel 全链（打开 → 选任务 → 编队 → 派兵 → 领奖 → 关奖励） | 生产 episode 大量成功，`OPEN_INTEL` 94%、`INTEL_BEAST_START_MARCH` 100%、`DISPATCH_INTEL_BEAST` 92% |
| Mail | `OPEN_MAIL` 67%、`MAIL_CLAIM_REWARDS` 54%、`DISMISS_MAIL_GENERIC_REWARD` 86% |
| 训练 | `KEEP_TRAINING_PRODUCTIVE` 是唯一 FULLY_LIVE_VERIFIED 的 Goal |
| 建筑升级 | `BUILDING_UPGRADE` 已注册且有成功记录 |
| 采集入口 | `SEARCH_RESOURCE` / `SUBMIT_RESOURCE_SEARCH` / `START_GATHER` / `DISPATCH_MARCH` 已在真机走通 |
| 资源页签识别 | 真机 22/22 帧正确（2026-09-14 重写后） |

### 部分完成 / 有已知缺陷

| 能力 | 现状 |
|---|---|
| `GATHER_RESOURCE` | 真机已多次完整闭环（MEAT ✓、WOOD ✓），并具备**资源不可用自动切换**；
  **仍未**达到「四资源各 ≥3 次」——COAL / IRON 一次都没尝试（默认偏移下在屏幕外，需滚动） |
| `SELECT_RESOURCE` | 分类器真机 22/22，且能在至少三种滚动偏移下工作；已有新的生产成功样本 |
| `MARCH_PAGE_NOT_OPEN` | 失败原因已拆成 ACTION_MISSED / NOT_RECOGNIZED；本会话真机 0 次 |
| `RESOURCE_NOT_FOUND` | 已定性为**资源可用性**（MEAT 在 level 7 能搜到，WOOD 在 level 1~8 全搜不到）；
  活锁已修复并真机验证 |
| `DISPATCH_NOT_PROVEN` 28 次 | **未定位根因** |
| `MAIL_CLAIM_FEEDBACK_NOT_PROVEN` 10 次 | 未定位 |
| ALLIANCE_ROUTINE | 只有 ANY_OF 部分能力；`ALLIANCE_HELP` 从未成功过 |

### 尚未开始

- 竞技场 / 迷宫 / 限时活动 / Bear / Rally：所需技能未实现（见 `03_NEXT_ACTION.md`）
- 外部项目实际借鉴（`07_EXTERNAL_REUSE.md`）：只有 REFERENCE_ONLY 清单，尚无接入
- Auto Improvement 闭环：未启用
- 72h Soak：**远未达标**（当前最好成绩是单轮 17 秒闭环）

### 数字口径警告

- 成功率是**全历史混算**（736 条跨越多天、多种代码版本）。它只能看趋势，
  **不能**当作「当前版本的成功率」。
- 旧基线 616 条 / 71.8% 与新值不可直接比较：新增尝试集中在最容易失败的采集类技能上。
- `STABLE` 目前刻意保持极少数；`STABLE=0` 曾是刻意设计，现在有了真实样本才允许放开。
