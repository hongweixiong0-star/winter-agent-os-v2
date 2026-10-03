# 缺口定位到单点：`read_event_detail` 的判据不看"页面身份"（2026-10-03 第六轮）

> 上一轮说"要改判据，但不能靠加关键词"。本轮把改法**定死了**，
> 并且用真机帧证明：**项目里已经有正确的身份判据，只是没接到这条路上。**
> **本轮零代码改动**（连续第四轮）。

---

## 一句话

`ocr.py` 早在 1050-1066 行就实现了"当前是哪个活动页面"的正确判据
（**已注册别名 + 标题尺度**），并据此选出 `峡谷会战`（h_ratio 0.0367）；
但 `read_event_detail` 的 `explicit_calendar_detail` 三个分支**全在检查时间标签**，
所以 `runtime.py:2072` 传进来的那 20 个 token 里没有它要的东西，**判据恒为假**。

---

## 一、纠正上一轮的一个事实错误

上一轮我写「`峡谷会战` 在横条上、不在网格里」，并暗示它不在横条带内。**后半句是错的**。

用 OCR 拿到的**当帧 token 几何**（不是肉眼）：

| 文字 | y_px | y_norm | 在横条带 0.06–0.20 内？ |
|---|---|---|---|
| `常规活动` | 41.0 | 0.032 | 否（是页面标题） |
| **`最强王国`** | 171.0 | **0.134** | **是** |
| **`峡谷会战`** | 235.5 | **0.184** | **是** |
| `教学` | 356.5 | 0.279 | 否 |

**两个活动都在横条带内**（带 = y 76–257px）。上一轮那句话是错的，此处更正。

---

## 二、纠正上一轮的另一个说法："选中态"不可用作判据

上一轮我说"横条上峡谷会战是选中态（白底高亮）"。**那是肉眼印象，测不出来**：

```
最强王国  区块亮度 mean=141.3  最亮20%均值=253.2
峡谷会战  区块亮度 mean=116.3  最亮20%均值=252.9
```

**两者差 0.3**（阈值噪声级别）。用横条列亮度找"高亮段"也只找到右侧图标区
（x_norm 0.66 / 0.82），与活动标签无关。

⇒ **"选中态"不能作为身份判据，任何依赖它的改法都是猜。**

---

## 三、真正的答案：项目里已经有正确判据

`ocr.py:1050-1066`（在 `read_event_calendar` 之前）：

```python
# The canonical event registry owns exact title aliases. A discovered alias is page identity
# only when the frame draws it at heading scale; small event tabs are navigation, not the
# active event. The real event hub can draw 联盟总动员 as a tab while its open content is 军备竞演.
event_title_tokens = []
for token in eligible:
    label = token.text.strip()
    if not event_goal.event_id_for_label(label):
        continue
    ...
    if frame_size and frame_size[1] > 0:
        is_title = is_title or height / float(frame_size[1]) >= 0.03
    if is_title:
        event_title_tokens.append(token)
```

**用真机帧复现这一判据**：

```
最强王国  event_id=STATE_VS_STATE  box_h=26.0  h_ratio=0.0203  标题尺度=False   ← 小页签=导航
峡谷会战  event_id=CANYON_CLASH    box_h=47.0  h_ratio=0.0367  标题尺度=True    ← 大标题=当前页
```

**它天然就把两个活动区分开了**，而且理由已经写在注释里
（小页签是导航，不是当前活动）。

**页面身份判据不需要发明 —— 它已经存在、已在真机上验证。**

---

## 四、缺口的确切位置（实测，不是推断）

`event_calendar.read_event_detail` 的三个分支：

```python
explicit_calendar_detail = (
    "活动详情" in all_text
    or (date_range is not None and any(m in all_text for m in (
        "活动时间", "开始时间", "结束时间", "报名时间", "战斗时间", "开放时间")))
    or (date_range is not None and "前往" in all_text
        and any(_candidate_title(text) for _, text in rows))
)
if not calendar_score_panel and not explicit_calendar_detail:
    return {"kind": "EVENT_DETAIL", "recognized": False, ...}
```

**全部在检查文本形状，没有一个分支问"这是哪个活动的页面"。**

实测对照（同一帧，只改 `event_label`）：

```
event_label=None    -> recognized=False   event_id=None
event_label='峡谷会战' -> recognized=False   event_id=None
```

**给标签也不够**——因为 `event_label` 只在**判据已通过之后**才用于取名。
判据本身不看身份，所以身份信息根本进不来。

这也解释了 `runtime.py:2072` 为什么传 `None`：
`ocr.py:1098` 那条路（`read_state`）先算出 `event_detail_label` 再传进去，
而 `runtime.py` 这条路是独立的一次调用，**没有把 `event_title_tokens` 传过来**。
两处调用同一函数、一处有身份一处没有——**这是断线的位置。**

---

## 五、改法（现在可以定了，且不违反任何既有约束）

**不是加关键词，是补一个分支：当帧的 `event_title_tokens` 判出标题尺度 ≥ 0.03 的
已注册活动别名时，这个 `EVENT_DETAIL` 就是那个活动的详情页。**

它满足全部约束：

| 约束 | 为什么满足 |
|---|---|
| 生产宪法第 2 条（禁坐标硬编码） | 用当帧 token 的**高度比例**，不用任何存下来的坐标 |
| "预览不能变成战斗时钟" | 该分支**只确定身份**（这是谁），不产出 `start`/`end`；时间窗仍由既有的显式标签分支负责 |
| 单一真值（不造第二套身份） | **复用** `ocr.py` 已有的 `event_title_tokens` 判据，不新写一套别名/尺度规则 |
| 不猜 | 判据在真机上已实测：0.0367 vs 0.0203，间隙 1.8× |

**接线点**（两处，二选一或都做）：
- `runtime.py:2072` 把 `event_title_tokens` 推出的标签传进去（与 `ocr.py:1098` 对齐）；
- 或在 `read_event_detail` 内部自行调用已有的 `event_goal.event_id_for_label` + 尺度判据。

**后者更好**：一处改动、不依赖调用方记得传参，且两个调用点同时受益。

---

## 六、反向验证已做（blocker 已解除）

上一节说"第 1 条是 blocker，不过它就改"。本轮把它做掉了。

**样本**：从生产账本里筛出**真实网格页帧**（`page==EVENT` 且 `events.calendar` 有值
且 `regular_events_hub` 缺失，且截图文件仍在磁盘），共 235 张，取最近 6 张。

**测量**（用项目自己的 `ocr.OCRService(RapidOCRBackend())`，
判据 = `event_id_for_label(label)` 有值且 `box_h/frame_h >= 0.03`）：

```
step_016_before_20261003T0609…   命中标题尺度=无
step_004_before_20261003T0614…   命中标题尺度=无
step_008_before_20261003T0614…   命中标题尺度=无
step_012_before_20261003T0615…   命中标题尺度=无
step_016_before_20261003T0615…   命中标题尺度=无
step_004_before_20261003T0618…   命中标题尺度=无

网格页误判为详情页的帧数: 0 / 6
```

**两侧都实测了，判据可用**：

| 页面类型 | 帧数 | 标题尺度命中 | 判据 |
|---|---|---|---|
| 活动详情页（`峡谷会战`） | 1 | **1/1**（h_ratio 0.0367） | 命中 ✓ |
| 日历网格页 | 6 | **0/6** | 全部不命中 ✓ |

间隙：`峡谷会战` 标签高 47px vs `最强王国` 26px（1.8×），
且 47/1280 = 0.0367 **高於** 0.03 阈值、26/1280 = 0.0203 **低於**——
**不是擦边**，两侧都有余量。

⚠ **样本量诚实说明**：详情页只有 1 个样本（`STATE_VS_STATE` 的详情页没抓到），
所以"其它活动详情页也满足"**仍未验证**（上一节第 2 条）。
**改完部署后必须在真机上确认第二个活动详情页也能被识别**，否则可能只修好了一个活动。

---

## 七、状态

- 零代码改动。dev 分支 `workbuddy/page-residency-20261003` = `a403e829`。
- 生产 pin `79cb572c`，AUTO 正常，`worker_exits` 19 未增长。
- **HEAD 又退了一次**（第三次，已确认成因：8 worktree 共享 `main`）。
  **不再追 HEAD** —— 分支 ref 才是本会话的真相，每轮用
  `git rev-parse refs/heads/<branch>` 复核。
