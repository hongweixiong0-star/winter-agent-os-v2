---
name: frame-evidence-joins
description: "Resolve a Winter Agent V2 screenshot to the episode record that owns it before quoting any recorded field, and build frame sets for a measurement so the result cannot be an artefact of the joining. Use whenever an analysis crosses learning/episodes.jsonl with dataset/raw frames."
description_zh: "帧↔记录的正确配对与测量帧集的构造流程（Winter Agent V2）"
description_en: "Joining screenshots to episode records without inventing a pairing"
agent_created: true
---

# 帧 ↔ 记录的正确配对

## 为什么有这条技能

2026-09-23 一晚之内，因为按 episode 的 `recorded_at` 去取帧，产生了**三次错误结论**，
每一次都写进了提交信息或未决清单，然后被迫撤回：

| 轮次 | 错误结论 | 真相 |
|---|---|---|
| 一 | "按绿勾之后客户端把营房高亮出来" | 环由客户端自己周期画，与 tap 无关 |
| 二 | "`17:51:16 / 17:51:35` 是同一机位的一对" | 取到的是各自前一步的文件；左边那帧其实是世界地图 |
| 三 | "读取层把地图帧读成 HOME 且环命中"（issue #93） | 该帧**自己那条**记录写着 `page=MAP`，环也没命中 |

病根相同：**一个帧由一步写出、只被那一步的记录引用**，而"时间接近的另一条记录"是另一回事。

## 流程

1. **查归属**（先做这一步，再做任何别的）：

   ```bash
   python tools/frame_owner.py <帧名的一部分> [--ring]
   ```

   它打印引用该帧的 episode（时间 / before|after / skill / `page` / `panel_open` / `result`）。
   `--ring` 再报该帧的金环读数。
   返回 **orphan** 时，**不得**为该帧引用任何 `page` 等记录字段——最多只能说"我亲眼在帧上看到什么"。

2. **配对规则**：`before_screenshot` ↔ `state_before`，`after_screenshot` ↔ `state_after`；
   同一 episode 的两侧不可互换，也不可跨 episode 借用。

3. **构造测量帧集**（用于统计，而不是用于举例）时，按 **帧路径**去重，然后排序；
   同一时刻可能有多帧，若只按时间排序，**并列的先后是任意的**，会把真实的一段"有环"切成
   伪交替（本次实测：真实 22 段 vs 误报 62 段）。

4. **口径要写进结论**。任何计数都要说明：用了哪个字段筛（`page` / `panel_open`）、
   用了哪个模板确认"目标真的在画面上"（例：兵营模板 ≥ 0.5 才可能看见环），否则读数为 0
   可能只是"根本没看"。

5. **举例用的帧必须逐像素看**（裁剪/放大），不要用"另一条记录说它是 X"来代替看图；
   看图与查记录是两件事，两者都可以写，但要分别标明来源。

## 反面清单

- ✗ 用一个时间戳把帧和记录连起来（`for r in rows: if r[recorded_at][11:19] == want:`）。
- ✗ 把 `--ring` 之类的模板读数当"记录里写的"（模板读数必须重新量，记录里的字段才是当时读过的）。
- ✗ 在统计里混入"记录说 page=HOME 但画面其实是别处"的帧而不设画面可见性门槛。
- ✗ 发布后才发现配错：更正比一开始查归属贵得多，`tools/frame_owner.py` 一步就够。
