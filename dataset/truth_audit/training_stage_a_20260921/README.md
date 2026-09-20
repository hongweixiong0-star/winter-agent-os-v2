# 训练路线 Stage A：落点在环外，以及项目找了 4 天的那个判别器

`KEEP_TRAINING_PRODUCTIVE` 全史 127 步里 **45 步（35%）花在 `WAIT_FOR_CAMP_MENU`**，
真正到达训练页只有 4 次；从 2026-09-17 到 2026-09-21，每轮浪费 2 步 + 一整轮。

原因是代码注释与 `verify_camp_menu_reobserved` 都写着的：**教学手指压着兵营，点了会跳地图** ——
依据是 **2026-09-17 唯一一次尝试**。本轮把这条理由推翻了，并且顺手找到了项目自己一直在找的判别器。

## 一、Stage A 的几何（46 帧真机，5 个独立时段）

取 `learning/episodes.jsonl` 里所有 `NAVIGATE_INFANTRY_CAMP` / `WAIT_FOR_CAMP_MENU` /
`SELECT_INFANTRY_CAMP` 的前后帧，筛出 `TARGET_INFANTRY_CAMP_HIGHLIGHTED` 命中（d ≤ 6）的 **46 帧**，
跨 2026-09-20 的 14:49 / 15:07 / 15:08 / 16:05–16:07 与 16:38 五个时段：

| 量 | 范围 | 均值 | 说明 |
|---|---|---|---|
| **模板落点** | **(346, 682)** | — | **46/46 帧完全相同**（模板匹配的确定性） |
| 金环中心 | x 305–319, y 577–597 | (313, 585) | sd 4.3 / 4.0 ⇒ 极稳 |
| 环内白色兵营图标 | x 333–352, y 541–552 | (342, 547) | 教学手指的指尖正指着它 |

⇒ **模板落点在环外**：环的 y 范围约 520–645，落点 y=682 **低于环下沿 37 px**，
即落在**建筑之间的空地**上。客户端把空地点击当成**地图操作**。

⇒ 这就是 09-17 那次"跳地图"的真因。**手指从来没有覆盖那个点**（它覆盖的是环，
而环是客户端画的选中标记，本身就是要交互的对象）。

## 二、判别器：环的尺寸（解开项目 09-17 以来的悬案）

`tests/test_training_verifier.py` 里有一条测试叫
`test_the_camp_highlight_signal_cannot_tell_the_two_states_apart`，它的依据是这对人工验证过的帧：

| 帧（`dataset/truth_audit/training_camp_highlight_ambiguity_20260917/`） | 人工点击实测 | 模板距离 | **金环 bbox** |
|---|---|---|---|
| `camp_with_gold_ring__click_opens_menu__20260908.png` | ✅ **开菜单** | 0.0 | **x 215–420, y 527–639 ⇒ 205 × 112** |
| `camp_with_officer_badge__click_jumps_to_map__20260917.png` | ❌ **跳地图** | **8.0**（正好压在门上） | **x 215–222, y 624–639 ⇒ 7 × 15** |

**两帧的模板距离是 0.0 vs 8.0** —— 后者**恰好等于生产闸门**，所以项目当时的结论是
"这个信号几乎区分不了两态"。**它在量错东西。** 跳地图那帧根本没有环，
只有 **7×15 px 的金色碎片**（军官徽章的边缘）；开菜单那帧有 **205×112 的完整环**。

⇒ **环的尺寸把两态分开了两个数量级**，而模板距离分不开。

## 三、落地（`winter_agent_v2/camp_ring.py`）

- `ring_centre_norm(image_path, roi_norm)`：在**匹配到的模板自己的 ROI** 里找金环，
  返回 bbox 中心（帧归一化）。**ROI 是调用方给的**，所以没有任何坐标被写死；
  检测器**不是**全帧找金色（第一版那样做时，它返回了右侧活动栏的金色装饰）。
- **最小尺寸判据** `MIN_WIDTH_NORM=0.12` / `MIN_HEIGHT_NORM=0.05`：小于这个不算选中态 ⇒ 返回 `None`。
  实测：真环 0.28 × 0.088，碎片 0.0097 × 0.012。
- 读不出环时**返回 None，不返回兜底点** —— 于是路线**等待**而不是乱点（安全侧）。

接入：

| 处 | 改动 |
|---|---|
| `vision.py` | stage A 分支除 `navigation` 外，读环并写 `training["camp_tap_norm"]` |
| `runtime.py` | 新增派生解析器 `TRAINING_CAMP_IN_RING`（带 HOME 页守卫，防止陈旧坐标被复用） |
| `skills.py` | `SELECT_INFANTRY_CAMP` 的目标由 `TARGET_INFANTRY_CAMP_HIGHLIGHTED` 改为 `TRAINING_CAMP_IN_RING`（**识别与点击分离**） |
| `brain.py` | stage A **先点一次**（`_camp_selected` 一次性），再走原有的 2 次等待与让位 |
| `verifier` | 不变：`verify_infantry_camp_selected` 要求 `after.training.menu_open is True` |

## 四、验证结果（离线）

| | 结果 |
|---|---|
| 46 帧 stage A 语料 | **46/46** 读出环，落点 (305–319, 577–597)，**零退化** |
| `camp_with_gold_ring__click_opens_menu` | 给出落点 **(0.4410, 0.4555)** = (317, 583) |
| `camp_with_officer_badge__click_jumps_to_map` | **拒绝（None）** ⇒ 路线等待而不是重复 09-17 的错误 |
| 决策序列（stage A 帧） | `SELECT_INFANTRY_CAMP` → `WAIT` → `WAIT` → `SAFE_STOP`（有界） |
| 无 `camp_tap_norm` 时 | 直接 `WAIT`，**不点** |
| 守卫 | `check_wiring` 新增 6 条，`problems: 0` |

## 五、⚠ 未验证（不许当已完成）

- **点环心是否真的开菜单，真机未验证过。** 现在有的是：① 落在环外的空地实测跳地图（09-17）；
  ② 落在环内有 09-08 的人工记录，但那帧的几何与 09-17 **相同**（tap 到环心 102 px vs 103 px）
  —— ⇒ **09-08 不能当作"环内有效"的对照**，它的"成功"很可能是按顺序推断而非实测。
  真正的差别是**环存在与否**，不是落点在环内还是环外。
- 因此这一步是 **CANDIDATE**。下一轮 AUTO 走到训练路线时应当看到：
  ① `SELECT_INFANTRY_CAMP` 真机首次触发；② 它的 verifier 是否 `OK`（即菜单是否真开）；
  ③ 若 verifier 失败，`camp_ring` 的最小尺寸判据需要按真机结果重校。

## 六、文件

| 文件 | 内容 |
|---|---|
| `key/01_stage_a_ring_and_finger_20260921T163802.png` | stage A 真机帧（环 + 手指 + 无菜单） |
| `key/02_where_the_template_tap_lands_20260921T163802.png` | 同帧标出模板落点的十字与圆圈 |
| `key/03_stage_a_second_session_20260920T160508.png` | 另一个独立时段的 stage A |
| `key/04_the_20260917_tap_landed_on_the_map.png` | **09-17 那次点击的结果：世界地图** |
| `key/05_finger_present_and_menu_open_20260920T013343.png` | **手指在、菜单也开着** ⇒ 手指是引导不是遮挡 |

复现：

```bash
"E:/无尽冬日智能体/.venv/Scripts/python.exe" .probe_training_stage_a.py <frame>
"E:/无尽冬日智能体/.venv/Scripts/python.exe" .probe_ring_and_icon.py
```

## 七、三次真机失败的独立印证（补，2026-09-21 01:20）

修完之后回查 `learning/episodes.jsonl`，发现 `SELECT_INFANTRY_CAMP` **全史只触发过 2 次**
（我修复之前，用的是旧目标 `TARGET_INFANTRY_CAMP_HIGHLIGHTED`），
**两次都失败**，加上"跳地图"那次，共**三次真机失败**：

| 真机尝试 | 落点（当时实际点的） | 结果 | **新检测器在同帧给的点** |
|---|---|---|---|
| 2026-09-17T04:42:03Z | **(346, 682)** | `FAILURE / INFANTRY_CAMP_MENU_NOT_PROVEN` | **(309, 586)**（103 px 外，环内） |
| 2026-09-17T09:46:29Z | **(346, 682)** | `FAILURE / INFANTRY_CAMP_MENU_NOT_PROVEN` | **(314, 584)**（103 px 外，环内） |
| 2026-09-17（`step_004_after_refresh_2`） | **(346, 682)** | **跳到世界地图** | 无环 ⇒ **拒绝** |

⇒ **"点 (346,682) 无效"现在有三次独立真机失败支撑**，不是推理；而三次的落点**完全相同**，
说明这是模板的**系统性**偏移，不是偶然。

⚠ **仍然只证明了一半**：三次都只说明**环外无效**。**环内是否有效，真机仍未验证过**。
其中 09:46:29 那帧**有完整环** ⇒ 新代码会点 (314,584) ⇒ **那正是下一轮可以验证的场景**。

`SELECT_INFANTRY_CAMP` 的 verifier 三次都正确报 `INFANTRY_CAMP_MENU_NOT_PROVEN`
（要求 `after.training.menu_open is True`）⇒ **验证器这一层是可信的**，它没有误报成功。
