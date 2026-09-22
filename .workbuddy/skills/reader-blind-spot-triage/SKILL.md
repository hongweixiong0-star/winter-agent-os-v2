---
name: reader-blind-spot-triage
description: "Diagnose a Winter Agent V2 case where an episode recorded a failure (or empty state) on a screen whose own frame visibly shows the client HAD drawn what the route wanted. Walks the gate template, the y-band and the layout variants the constants were measured on, and reports which one rejected it. Use whenever training/panel/camp steps log FAILURE or training={} while the after-frame looks correct."
description_zh: "读取器盲区排查：episode 记失败但帧上明明画着时的定位流程（Winter Agent V2）"
description_en: "Triaging a reader that reports a missing screen on a frame that shows it"
agent_created: true
---

# 读取器盲区排查（episode 记失败，但帧上明明画着）

## 为什么有这条技能

2026-09-23 一夜里同一个模式出现四次，每次都要从零绕一圈才知道是读取器的问题而不是客户端的问题
（`16:42:30` / `18:54:27` / `18:43:51` 三次 FAILURE、以及 `17:54:28`）：

- `PANEL_ROW_TASK_BAR_NOT_PROVEN` / `INFANTRY_CAMP_HIGHLIGHT_NOT_PROVEN` 这些失败名**听起来像客户端没做到**，
  但帧上是做到了的；
- 而一旦误判成"客户端没做到"，就会去做**路由改动**——那是改错地方。

**规律**：这个项目里"读取器比客户端更常出错"。任何"到达判据不满足"的失败，先怀疑读取器。

## 流程（按顺序，不要跳）

1. **先看图**。把该 episode 的 `after_screenshot` 直接打开（必要时裁切放大），
   确认客户端**到底**画了什么。不要用"时间接近的另一条记录"代替看图。
   （帧的归属用 `tools/frame_owner.py`，见 `frame-evidence-joins` 技能。）
2. **用当前读取器重读那一帧**：
   ```python
   from winter_agent_v2.ocr import HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend
   vis.observe(Path(frame))   # 打印 page / training / quick_panel
   ```
   - 若现在读得出 ⇒ 缺陷**已修**，那条 episode 是历史，不要据此改代码；
   - 若现在仍读不出 ⇒ 活缺陷，继续。
3. **找出是哪一层拒的**，逐层问，**不要跳层**：
   - **门模板**：这类读取都有一个便宜的模板门（如 `CAMP_ACTION_BAR_GATE`）。
     直接量原始相关分：`cv2.matchTemplate(frame, gate_img, TM_CCOEFF_NORMED)` 取最大值，
     与阈值比较（本项目 `distance = round((1-score)*64)`，默认 `max_distance = 6`）。
     **0.65 左右的常数几乎总是"模板不在这一帧上"，不是"匹配得差"。**
   - **OCR 词表 + y 带**：把 OCR token 逐条按 band 打印出来（文本、中心归一坐标、置信度、
     是否落在 band 内、是否在词表内）。**词读到了但被 band 拒掉**是最隐蔽的一种。
   - **名称/前置校验**：如 `camp` 必须非空（词表 → 营地名）。
4. **问"这些常量是在哪种布局/渲染上量的"**——这是最常见的根因。
   用一个控件在**每种已知渲染**上的实际坐标/图标去打分，做交叉表：
   ```
   crop 自 A 布局的图标 -> A 1.000 | B 0.969 | C 0.651
   crop 自 B 布局的图标 -> A 0.969 | B 1.000 | C 0.585
   ```
   跨布局 ≥0.95 的控件才能当门；只会命中一种的，必须**每种布局各一条记录**
   （`find()` 对同一 semantic 有多条记录时任一条命中即算命中）。
5. **改最小的一处，并让工具自己证明**：本项目每个注册工具都有 `--check`
   （must-match / must-not-match 两组）。先跑它，要求 **miss = 0 且假阳性 = 0**，再提交。
   顺手检查**`--check` 的清单本身对不对**：拿"帧自己记录的状态"分类，
   而不是按技能名或日期——本项目已出现"同一技能早上结束在 A 渲染、晚上结束在 B 渲染"，
   于是清单把判对的帧报成 miss。
6. **可读词表绝不顺带扩**：词表就是"词 → 可点的点"。花钱控件（`立即完成`、`加速`、带钻石数的）
   即使与可读词同排同带，也**不得**入表，要在代码里写明原因。

## 反面清单（本项目已付过代价）

- ❌ 用"有某个视觉特征"当**到达/身份判据**：金环（#92）会自己闪、白气泡（#95 补充）是通用提示框
  且内容随对象变。**特征存在 ≠ 对象是它**；判据要落在**对象自己的文字或图标**上。
- ❌ 只在一种渲染上量一个常量（band / 模板 / 阈值）就当通用。
- ❌ 从别的页面的同名控件照搬固定坐标；坐标必须来自当帧（把手、行按钮、环心、气泡都是按帧定位的）。
- ❌ 把"读了/生成了 Goal"当作"执行成功"。

## 交付时要写清的三件事

1. 缺陷是**读取器**还是**客户端**（附"当前读取器重读"的结果）；
2. 常量原来量在哪种渲染上、漏了哪种（附逐词/逐像素表）；
3. 修完的 `--check` 结果（miss 数、假阳性数），以及**仍未在真机观察到的部分**。
