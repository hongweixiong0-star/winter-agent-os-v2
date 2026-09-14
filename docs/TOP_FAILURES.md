# Top Failures（由真实 Episode 流重算）

- 来源：`learning\episodes.jsonl`
- Episode 总数：732
- 结果分布：486 SUCCESS / 241 FAILURE
- 失败总数：241

## 失败类型排行

| 次数 | 失败类型 | 已修复 |
| ---: | --- | :---: |
| 104 | `SEMANTIC_TARGET_NOT_VERIFIED` | 否 |
| 59 | `MARCH_PAGE_NOT_OPEN` | 否 |
| 28 | `DISPATCH_NOT_PROVEN` | 否 |
| 10 | `MAIL_CLAIM_FEEDBACK_NOT_PROVEN` | 否 |
| 8 | `RESOURCE_NOT_FOUND` | 是 |
| 5 | `POPUP_CLOSE_NOT_PROVEN` | 是 |
| 3 | `EXPLORATION_REWARD_FEEDBACK_NOT_PROVEN` | 否 |
| 2 | `INTEL_MISSION_SELECTION_NOT_PROVEN` | 否 |
| 2 | `MAIL_TAB_SELECTION_NOT_PROVEN` | 否 |
| 2 | `OPEN_HOME_NOT_PROVEN` | 否 |
| 2 | `INFANTRY_CAMP_HIGHLIGHT_NOT_PROVEN` | 否 |
| 2 | `OPEN_MAIL_NOT_PROVEN` | 否 |
| 1 | `RESET_DURING_ACTION` | 否 |
| 1 | `VISION_VARIANCE` | 否 |
| 1 | `BEAST_TARGET_SELECTION_NOT_PROVEN` | 否 |
| 1 | `BEAST_DISPATCH_NOT_PROVEN` | 否 |
| 1 | `INTEL_CLAIM_FEEDBACK_NOT_PROVEN` | 否 |
| 1 | `INTEL_BEAST_DISPATCH_NOT_PROVEN` | 否 |
| 1 | `INTEL_REWARD_DISMISS_NOT_PROVEN` | 否 |
| 1 | `EXPLORATION_IDLE_DIALOG_NOT_PROVEN` | 否 |
| 1 | `ALLY_GIFT_REWARD_FEEDBACK_NOT_PROVEN` | 否 |
| 1 | `DAILY_REWARD_ADVANCE_NOT_PROVEN` | 否 |
| 1 | `RESOURCE_SEARCH_NOT_OPEN` | 否 |
| 1 | `SAFE_BACK_NOT_PROVEN` | 否 |
| 1 | `RESOURCE_SELECTION_NOT_PROVEN` | 否 |
| 1 | `OPEN_MAP_NOT_PROVEN` | 否 |

## 按 Goal 归因的阻塞点

- **GATHER_RESOURCE**（174）：SEMANTIC_TARGET_NOT_VERIFIED ×73、MARCH_PAGE_NOT_OPEN ×59、DISPATCH_NOT_PROVEN ×28、RESOURCE_NOT_FOUND ×8、OPEN_HOME_NOT_PROVEN ×2、VISION_VARIANCE ×1、RESOURCE_SEARCH_NOT_OPEN ×1、RESOURCE_SELECTION_NOT_PROVEN ×1、OPEN_MAP_NOT_PROVEN ×1
- **UNATTRIBUTED**（44）：SEMANTIC_TARGET_NOT_VERIFIED ×13、MAIL_CLAIM_FEEDBACK_NOT_PROVEN ×10、POPUP_CLOSE_NOT_PROVEN ×5、EXPLORATION_REWARD_FEEDBACK_NOT_PROVEN ×3、INTEL_MISSION_SELECTION_NOT_PROVEN ×2、MAIL_TAB_SELECTION_NOT_PROVEN ×2、INFANTRY_CAMP_HIGHLIGHT_NOT_PROVEN ×2、RESET_DURING_ACTION ×1、INTEL_CLAIM_FEEDBACK_NOT_PROVEN ×1、INTEL_REWARD_DISMISS_NOT_PROVEN ×1、EXPLORATION_IDLE_DIALOG_NOT_PROVEN ×1、ALLY_GIFT_REWARD_FEEDBACK_NOT_PROVEN ×1、DAILY_REWARD_ADVANCE_NOT_PROVEN ×1、SAFE_BACK_NOT_PROVEN ×1
- **MAIL**（15）：SEMANTIC_TARGET_NOT_VERIFIED ×13、OPEN_MAIL_NOT_PROVEN ×2
- **INTEL**（4）：SEMANTIC_TARGET_NOT_VERIFIED ×3、INTEL_BEAST_DISPATCH_NOT_PROVEN ×1
- **BEAST_HUNT**（2）：BEAST_TARGET_SELECTION_NOT_PROVEN ×1、BEAST_DISPATCH_NOT_PROVEN ×1
- **EXPLORATION**（1）：SEMANTIC_TARGET_NOT_VERIFIED ×1
- **DAILY_TASKS**（1）：SEMANTIC_TARGET_NOT_VERIFIED ×1

## 外部变更（维护后面板重构）

2026-09-13 的停服维护结束后，资源搜索面板被官方改版：

- tab 行不再是 MEAT/WOOD/COAL/IRONA 四个基础资源，而是「野兽 / 冰原巨兽 / 大型养殖场 / 生肉 / 木 ...」等目标类型 tab，
- 等级滑条范围由 1~8 改为 1~27（野兽最高 30 级），
- 所有 `RESOURCE_TAB_*` 与 `RESOURCE_*_SELECTED` 模板在新面板上距离为 None。

后果：`GATHER_RESOURCE` 的 capability 状态从 COVERED 变为事实上的 BLOCKED，
PHASE E 的「四资源各 ≥3 次完整成功」目标需要在重采几何后重新定义。详见 `docs/PANEL_REDESIGN_2026_09_14.md`。

**2026-09-14 进展**（维护期结束即真机采帧）：

- `tests/test_panel_redesign.py` 6 项回归测试全绿，
- `selected_resource` 在 4 张 panel_redesign 真机帧上 4/4 正确识别（dist=0），
- 真机像素实测的几何已固化进 vision（band=0.672/0.789、4 中心、max_distance=32、tie margin 4），
- 余下问题：`selected_resource` 在跨滚动位置的帧上仍因 pHash 抖动 tie，需为每个 tab 多采 2~3 个样本。

## 已定位根因（真机复验前不标 STABLE）

### `RESOURCE_NOT_FOUND`

- 修复：等级过滤改为从滑条实读，并在搜索落空时降级重搜
- 证据：8/8 失败样本均为 level=8 固定过滤；RELAX_RESOURCE_LEVEL 已注册到 VERIFIED_ATOMIC
- 状态：**尚未真机复验**
- ⚠️ **已被维护后面板变更覆盖**，详见 `docs/PANEL_REDESIGN_2026_09_14.md`

### `POPUP_CLOSE_NOT_PROVEN`

- 修复：维护/加载页新增 WAIT 分支，弹窗不再被反复 BACK
- 证据：维护公告模板 + verify_environmental_wait 已接线；unexpected_worker_exits 根因确认
- 状态：**尚未真机复验**

## 数据质量

- `result` 出现过的非规范取值：['blocked', 'failure', 'in_progress', 'success']
- result 字段历史上同时存在大写与小写变体，统计前已归一化。
