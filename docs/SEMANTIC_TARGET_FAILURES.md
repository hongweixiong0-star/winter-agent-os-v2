# SEMANTIC_TARGET_NOT_VERIFIED 归因（PHASE F）

- 来源：`learning\episodes.jsonl`
- 该失败总数：**104**（全部失败 241 次中的 43%）

## 按失效的动作目标拆分

| 次数 | action.target | 典型前置状态 |
| ---: | --- | --- |
| 34 | `RESOURCE_DYNAMIC` | search_open=True,selected=None,level=None ×25 |
| 32 | `BTN_OPEN_RESOURCE_SEARCH` | search_open=False,selected=None,level=None ×32 |
| 13 | `BTN_OPEN_MAIL` | search_open=False,selected=None,level=None ×13 |
| 6 | `RESOURCE_WOOD` | search_open=True,selected=None,level=None ×6 |
| 4 | `BTN_DISMISS_INTEL_REWARD` | search_open=False,selected=None,level=None ×4 |
| 3 | `BTN_OPEN_INTEL_WILD_HUD` | search_open=False,selected=None,level=None ×3 |
| 3 | `BTN_MAIL_TAB_ALLIANCE` | search_open=False,selected=None,level=None ×3 |
| 1 | `BTN_CLOSE` | search_open=False,selected=None,level=None ×1 |
| 1 | `BTN_OPEN_HOME` | search_open=True,selected=WOOD,level=8 ×1 |
| 1 | `BTN_OPEN_EXPLORATION` | search_open=False,selected=None,level=None ×1 |
| 1 | `POPUP_MAIL_REWARD` | search_open=False,selected=None,level=None ×1 |
| 1 | `BTN_EXPLORATION_IDLE_CLAIM` | search_open=False,selected=None,level=None ×1 |

## 阈值裕度实测

### `BTN_OPEN_RESOURCE_SEARCH`

- 当前阈值：12
- 实测分布（51 帧）：min 0 / median 6 / max 12
- 风险：最大值已顶到阈值；ROI 内含地图动态指示箭头，pHash 随动画相位漂移，无裕度。

### `BTN_RESOURCE_SEARCH_SUBMIT`

- 当前阈值：6
- 风险：未单独标定；如需放宽应先按 ROI 实测分布决定，不得直接套用其它语义的阈值。

## 结论

1. `SELECT_RESOURCE` 的 `RESOURCE_DYNAMIC` 分支在「面板已打开但选中态识别为 None」时
   无法确认目标，需真机复现以定位点击坐标与回读几何的偏差。
2. `SEARCH_RESOURCE` 的 `BTN_OPEN_RESOURCE_SEARCH` 阈值裕度为零（实测最大 12 = 阈值 12），
   属于真实鲁棒性风险，而非当前失败主因。
3. 两者都**尚未真机复验**，因此不得标记为已修复。
