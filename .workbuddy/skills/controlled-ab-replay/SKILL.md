---
name: controlled-ab-replay
description: "Prove a decision-layer change in Winter Agent OS V2 (priority, ranking, gating, a branch) using recorded production frames and no device: rebuild the world from each frame with the production vision, then toggle exactly one variable between two runs of the same code. Use when the change is a judgement rather than a pixel, when AUTO holds the device, or when you need cause rather than correlation."
description_zh: "离线受控 A/B 回放：同帧同代码只切一个变量，用生产帧证明决策层改动"
description_en: "Controlled single-variable A/B replay over production frames for decision-layer changes"
agent_created: true
---

# 受控 A/B 回放（决策层改动的证据）

## 为什么有这条技能

真机定向验证（`live-directed-verification`）解决"这个坐标/这个控件在设备上到底怎样"，
但它回答不了**决策层**的问题："这条规则真的改变了选择吗？"——而设备往往正被 AUTO 占着
（本项目 2026-09-23 的一轮就是如此：`runtime_snapshot` 每秒都在更新，抢租约等于打断一轮有效运行）。

同时，最贵的一类错误恰好在这一层：**加一个从不改变任何选择的项**（看起来在工作）
或**改动看起来生效、实际是别的原因生效**（相关性冒充因果）。回放能同时挡住这两类：
没有它，"板序变了"只能证明发生了什么；有了它，才能证明**是这一个变量**让它发生的。

## 三步

### 1. 先把"这个改动能不能影响选择"量出来，再动手

新增一个优先级项之前，先量**信号本身**，否则很容易写出死代码或恒亮项。

- 信号存在吗、会变化吗：`tools/measure_panel_row_badges.py`（面板行的角标：区分度、恒亮、读不出）
- 它是否总是亮着（恒亮的角标不是信号，是常量）：`tools/measure_mail_dot_blind_window.py`
- 想加"唤醒某条 Goal"这种会**重复开页**的规则之前，先量这个窗口多久出现一次——本项目量出来
  "读完邮件说无事之后 15 分钟 TTL 内红点再现"在语料里**一次都没出现**，于是**不做**。
  **没有证据的规则不要加**，把测量结论写进 issue。

### 2. 挑帧：口径写清楚，别用"看起来合适"的帧

- 帧来自 `learning/episodes.jsonl` 里**自己记录了 page/状态**的 before 帧；记录只用来**挑帧**，
  世界一律**用生产视觉从图片重读**（`SemanticWorldVision` + RapidOCR，见 `tools/cq_nav_tap_probe.py`
  的 `build()`），不采信记录里的读数——否则回放只是在复述旧结论。
- **边界**：`episodes.jsonl` 由**正在跑的运行时追加**，读到半行是常态（本轮实测 6734 → 6754 行、
  偶发一行 `JSONDecodeError`）。工具必须统计并**报告**跳过的行数，不能静默跳过。
- **分组要按图片，不要按记录**。本项目实测：2 帧"记录说没有红点"，用今天的代码重读**读到了红点**——
  旧记录写在读取器修复（#98 角标窗口从按钮左三分之一移到右三分之一）**之前**。
  按记录分组会把这类帧错放进对照组。

### 3. A/B：同帧、同代码、只切一个变量

```python
world = vision.observe(frame)                 # 生产视觉，从图片重读
goals = library.discover(world)               # 同一个发现函数
after  = library.rank(goals, world)                              # 变量在
before = library.rank(goals, replace(world, red_dots={}))        # 变量关掉
```

- 两个方向**共用** goals / 观测 / 公平台账 / 路由事实 —— 只让目标变量不同。
- 用 `dataclasses.replace(world, <那个字段>=空)` 制造 before 侧：它等价于"改动前的行为"，
  因为改动前没有一层读它。
- **必须有负向对照组**：图上没有该信号的帧，两侧必须**一模一样**（变化数 = 0）。
  没有对照组，"板序变了"可能来自别处误触发——这是这套证据唯一可能对自己有利的错误。
- 归档到 `dataset/truth_audit/<主题>_<日期>/`：`replay.json`（每帧的 before/after 板序 + 每一项的
  分数与来源）+ `README.md`（口径、结果表、**刻意没做的事**、复算命令）。
  帧不进 git（`.gitignore`），README 里写路径即可复现。

## 判据（本项目已付过代价的）

- **一个新项必须有界，而且界要算出来**：`RED_DOT_BONUS = 60` 的依据是板上真实间隙
  （未读探访 180 + 60 = 240 **<** 一次可领取 250），不是"看起来合适"。测试里把这条界钉成断言
  （`TheBoundTest`），否则下一个人调阈值时没人知道为什么是 60。
- **信号要先被证明会变化**：恒亮角标（每日/联盟 26/26）、疑似图案（英雄 `SUSPECT_ARTWORK`）、
  从未读到 PRESENT 的行，一律**不参与排序**；读取器给出 UNKNOWN 的行也不参与
  （"没读出来"不是"没有"）。
- **绑定必须落在真实词汇上**：本项目真实缺陷——面板「科技研究」行的红点绑到 `"RESEARCH"`，
  那是 `run_live.py --goal` 的**路由域**而不是 Goal id，于是这一行（面板里最常亮、唯一有区分度的行）
  的信号**永远匹配不到任何 Goal**。新增绑定要**对着下游的词汇表断言**（测试，
  不是靠眼睛看），并且**没绑定的要显式丢弃**（丢弃 + 登记），不能猜一个最近的名字。
- **确认改动的日志字段**：项要进 `as_row()` / `why()`，让决策日志写出"是哪个入口在指"，
  否则事后只能看到一个 +60。
- **负向对照为 0 才算通过**；对照组非 0 时先找误触发，不要解释成"可能是别的原因"。

## 反面清单

- ✗ 因为设备忙着就跳过证据，把 pytest PASS 当完成。
- ✗ 用自选帧（"这几帧看着对"）而不写挑帧口径。
- ✗ 只跑处理组，没有负向对照组。
- ✗ 采信记录里的读数（记录可能是**旧读取器**写的）。
- ✗ 为了让 A/B 好看而改两次变量（例如顺手把观测也换掉）。
- ✗ 量出"这个规则几乎不会触发"之后仍然把规则加进去——那既不改善真实运行，又增加一条要维护的分支。
