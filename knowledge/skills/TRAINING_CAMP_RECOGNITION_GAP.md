# 训练链第一步的真实死因（2026-09-22，一帧定案）

> 结论：`KEEP_TRAINING_PRODUCTIVE` 卡住的不是导航、不是策略、不是缺 skill ——
> 是**识别**：已注册的模板对"盾兵营已选中"的**第二种视觉形态**全部不匹配，
> 于是 `training = {}`，于是 verifier 判 `INFANTRY_CAMP_HIGHLIGHT_NOT_PROVEN`。

## 一、真机现场

2026-09-21T16:24:02，AUTO（设备租约刚归还后）执行：

```
skill          NAVIGATE_INFANTRY_CAMP
goal_id        KEEP_TRAINING_PRODUCTIVE
control        BTN_POWER_TROOP_IMPROVE        (TAP_SEMANTIC)
before page    POPUP      (实力详情 弹窗)
after  page    HOME
observed_change PAGE_CHANGED
verifier_ok    False
failure_type   INFANTRY_CAMP_HIGHLIGHT_NOT_PROVEN
expected       infantry_camp_highlighted
```

证据帧：

```
dataset/raw/control_panel/runtime_auto/20260922_001615_642151/
  20260922_001615_642151_step_011_before_20260921T162300135942.png   ← 实力详情弹窗
  20260922_001615_642151_step_011_after_refresh_2_20260921T162341609773.png  ← 见下
```

## 二、那帧画面上有什么（人眼可读，无需识别）

after 帧是**主城**，且**盾兵营已被选中**：

- 建筑上挂着「盾兵营」文字标签与等级 `16`
- 建筑四周是一圈**明亮的放射状光环**（白/蓝，明显区别于未选中建筑的静态外观）
- 底部出现了选中建筑才有的三格操作：**「详情」「升级」「训练」**
- 其中「训练」上面还盖着**游戏自己的手指指示图标**（客户端在提示点这里）
- HUD：`19:57 / 32/32 / 46.0万 / 13,179 / 战力 1,865,759 / -12.7℃ / 统帅4`

**也就是说：动作成功了，画面对了，是识别没跟上。**

## 三、实测：现有识别输出什么

`tools/probe_training_death_frame.py`（本轮新增，只读）对同一帧跑生产识别：

```
SemanticWorldVision.observe
  page        Page.HOME          ← 对
  popup       None
  training    {}                 ← 空。这是死因
  confidence  0.98
```

逐模板（模板在 manifest 里都存在，但**这一帧一个都不匹配**）：

| 模板 | manifest | 本帧 |
|---|---|---|
| `TARGET_INFANTRY_CAMP_HIGHLIGHTED` | recorded ×1 | **(no hit)** |
| `BTN_TRAINING_MENU_LABEL` | recorded ×1 | **(no hit)** |
| `BTN_OPEN_TRAINING_FROM_CAMP` | recorded ×3 | **(no hit)** |
| `BTN_OPEN_TRAINING` | recorded ×1 | **(no hit)** |
| `BTN_UPGRADE` | recorded ×1 | **(no hit)** |
| `BTN_POWER_TROOP_IMPROVE` | recorded ×2 | (no hit) |
| `TARGET_MARKSMAN_CAMP_HIGHLIGHTED` / `TARGET_LANCER_CAMP_HIGHLIGHTED` | **NOT IN MANIFEST** | — |
| `BTN_TRAIN_TROOPS` / `BTN_DETAIL` / `BTN_POWER_OVERVIEW` | **NOT IN MANIFEST** | — |

verifier 的判据（`verifier.py:407`）：

```python
arrived = (after.training.get("navigation") == "INFANTRY_CAMP_HIGHLIGHTED"
           or after.training.get("menu_open") is True)
```

`training` 为空 ⇒ 两个条件都不成立 ⇒ `INFANTRY_CAMP_HIGHLIGHT_NOT_PROVEN`。

## 四、为什么模板不匹配：客户端至少有**两种**选中形态

`winter_agent_v2/camp_ring.py` 记录了上一轮的测量（46 帧，跨 5 个 session，2026-09-20）：

```
                 x            y
gold ring      306 - 319    578 - 594
white camp icon 333 - 352   541 - 552
template tap   346          682      (46/46 帧完全相同)
```

那 46 帧是**金环**形态，`TARGET_INFANTRY_CAMP_HIGHLIGHTED` 就是按它注册的
（"d ≤ 2 on all 46 stage A frames"）。

而 16:24 这帧是**白/蓝放射光环 + 底部三按钮 + 手指**，**没有金环**。

⇒ 两者是同一语义（盾兵营被选中）的**两种渲染**，模板只覆盖了第一种。
这也解释了 `camp_ring.py` 里"模板点击点固定在 (346,682)、比环心低 103px"那条测量 ——
它是在**金环帧**上量的，而线上大量走到的是这一形态。

## 五、影响（真实、可指）

- `KEEP_TRAINING_PRODUCTIVE` 在 `goal_fairness.json` 里累计 `offered=41 / selected=9`，
  `no_progress_streak=3`，`last_block_reason = "3 consecutive production episodes passed
  their verifier and advanced no part of this goal"`，`last_skill=OPEN_HOME`。
  它的失败签名 `OPEN_TRAINING_PAGE|NO_GOAL_PROGRESS|OPEN_HOME`。
- 该目标随后被 `NO_GOAL_PROGRESS` **DEFERRED**（`runtime_snapshot.deferred_goals`）。
- 操作者 §十一 第 1 条（"进入兵营训练页面后，能够主动点击训练并完成实际启动"）**因此未通过**。
- 更早的一次同类现场：`AVOID_STAMINA_WASTE` 名下也出现过连续 `WAIT_FOR_CAMP_MENU`
  （见 `tools/probe_goal_attribution_match.py` 的统计：`WAIT_FOR_CAMP_MENU` 的
  goal 分布为 KEEP_TRAINING_PRODUCTIVE 55 / TRAIN 21 / DAILY_ACTIVITY_TARGET 15 / CLEAR_INTEL 14），
  即这一状态在多个目标名下都反复到达、反复读不出。

## 六、修法（下一步，尚未实施）

**不能凭一帧注册模板。** 需要同一形态的**多帧**（项目自己的标准是"reviewed template"，
`camp_ring.py` 那轮用了 46 帧）：

1. 在真机上重复到达该形态（`KEEP_TRAINING_PRODUCTIVE` 被选中即会走到），
   收集 ≥3 帧、最好 ≥10 帧。
2. 用 `tools/register_power_route_templates.py` 的既有机制注册第二个语义，
   例如 `TARGET_INFANTRY_CAMP_SELECTED_TRAINING_READY`，ROI 取底部三按钮带
   （「详情/升级/训练」）——**那三个按钮是这一形态独有的、比光环更稳的判据**：
   光环是渐变+半透明，模板距离对它敏感；三个按钮是实心圆角矩形，位置固定。
3. `vision.py` 的对应分支补一条：命中该语义时同样给出
   `training={"navigation": "INFANTRY_CAMP_HIGHLIGHTED", "queue_available": True}`，
   并让 `BTN_TRAIN_TROOPS` 有模板可点，链条才能走到真正的 `TRAIN_TROOPS`。
4. 配 verifier 与 brain 路由（§六 第 8 条：不新增 skill 而不配 verifier）。

⚠ 本文件只记录**现状与根因**，不声称已修。
