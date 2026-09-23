---
name: controlled-ab-replay
description: "Prove a decision-layer change in Winter Agent OS V2 (priority, ranking, gating, a branch) using recorded production frames and no device: rebuild the world from each frame with the production vision, then toggle exactly one variable between two runs of the same code. Also covers whole-RUN replay -- feeding a recorded run's frames in order into ONE brain instance to attribute a decision chain whose reasons never reached episodes.jsonl. Use when the change is a judgement rather than a pixel, when AUTO holds the device, or when you need cause rather than correlation."
description_zh: "离线受控 A/B 回放：同帧同代码只切一个变量；也覆盖整轮回放（按序喂进同一个 brain 实例，为没有进语料的决策链归因）"
description_en: "Controlled single-variable A/B replay over production frames, and whole-run decision replay"
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

## 3b. 整轮回放：当问题是"**这一串**决策为什么会这样"

单帧 A/B 回答"这条规则改不改变选择"；但本项目更常见的问题是
"**一个运行为什么来回走**"——而 `episodes.jsonl` 当时**不记 `decision.reason`**
（本项目的 `Episode.decision_reason` 2026-09-23 才落地），运行时日志只保留最新一轮，
于是**理由没有幸存证人**，帧是唯一能回放的东西。工具：`tools/replay_run_decisions.py`。

三条纪律，缺一条结论就不能信：

1. **按运行分组、按顺序喂，而且一个 run 只用一个 brain 实例。**
   `RuleBrain` 的计数器（`ordinary_attempts`、`_panel_row_attempts`）和运行时的
   `_replan_attempted` / `_barren_pages` 都是**运行内状态机**；每步新建实例 = 每步重放第一步。
   同理，运行时侧的兜底分支要用 `object.__new__(LiveRuntime)`（照
   `tests/test_capability_gate.py` 的写法）**保留跨步状态**。
2. **回放结果必须与语料逐条对账，并公布一致率**，而不是只报成功的那些。
   本项目：18 个空转运行 36 步里**一致 28 步**，不一致的 8 步是"生产里当时**有**目标的步骤"——
   回放只重建无目标链，限度要写进工具 docstring 和 README。**一致率是这套证据的可信区间。**
3. **A/B 做在同一个工具里**（每个运行跑两遍：带守卫 / 不带守卫），而不是"改代码前跑一次、
   改代码后跑一次"。后者会被"两次运行之间机器上的台账变了"污染，而且无法在同一个归档里证明
   两侧只差一个变量。本项目：**36 步 → 27 步，7 个运行提前诚实停止**。

### 3c. 基线那一腿的两个坑（都踩过）

- **把新增的测试文件挪开再做基线**。新测试引用新符号，无改动时**收集期就报错**，
  pytest 退出码 2，整腿没有任何汇总（本项目连续两次 A/B 因此作废）。
  基线要跑的是**同一批既有文件**，再单独跑新文件。
- **绝不要在测试还在跑的时候 `git stash`**。stash 会改工作树，而套件读工作树
  （本项目有一次 2671 项的全量跑在 18% 处被自己 stash 掉 `runtime.py` 打死；
  另一次是 onnxruntime 在多线程下原生崩溃——环境问题，也要如实写进提交信息，不要冒充通过）。
  做法：`git stash push … && pytest …; git stash pop` 写成**一条命令**，且不与任何后台套件并行。

### 3d. 当 `git stash` 本身就不可用时：运行时打补丁的 pytest 插件

这棵树**长期有第二个写入方**（AUTO 周期 + 另一个开发作业），`.git/index.lock` 大部分时间被别人持有，
`git stash` 会直接失败（本项目 `#109` 第一次 A/B 就这么废掉）。替代做法是把"回退"做在**模块边界**上：

```python
# learning/_ab_screen_key_plugin.py，用 -p 加载
def pytest_configure(config):
    if os.environ.get("AB_SCREEN_KEY") == "page":
        ce.control_key = lambda page, control, screen="": f"{page}|{control}"   # 退化成旧键
        ce.reusable_on_this_screen = lambda e, s: True
    if os.environ.get("AB_CLOSE_BAND") == "off":
        orig = SemanticROIVision.__init__
        def patched(self, *a, **k):
            orig(self, *a, **k)
            self.records = [r for r in self.records if r.get("template_id") != BAND_ID]
        SemanticROIVision.__init__ = patched
```

好处不止"绕开锁"：**不动磁盘、不动 git、不动清单**——清单在这个项目里是**运行中的进程会读**的文件，
"临时把记录删掉再跑"是会污染真机行为的。两腿因此跑的是同一棵树、同一份清单、同一个运行器。

**同一运行器是硬要求，不是讲究**：本项目同一个文件集在 pytest 与 unittest 下失败数不同
（`test_live_runtime.py` 读 `knowledge/**`，AUTO 在改），拿 pytest 的一腿去比 unittest 的一腿，
比的是**运行器**不是改动。两次都在同一运行器下跑，再 `diff` 失败清单。

**判据**：基线多出的失败，应该**正好是**本轮新增的测试（它们无修时按设计失败）；
若基线比本树**多**出别的名字 ⇒ 有回归，先查那些名字。

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
- **"界"的检查**：看到"某某每轮只能一次"的界，先问它保护的是**一个动作**还是**一对动作**。
  本项目真实缺陷：`_replan_attempted` 的注释自称防两页乒乓，实测只给双向环的**一侧**上界，
  环还在（18/75 个运行纯粹在 `OPEN_MAP` ↔ `OPEN_HOME` 之间来回）。
  **给环的一半加上界，环没有消失**；缺的往往不是第二个界，是**记忆**（哪一页已经看过且什么都没有）。
- **存的记忆要按"它最小为真的范围"设键**。本项目真实缺陷（`#109`）：台账用
  `(page, semantic)` 存坐标，而 `POPUP` 是**页面大类**——语料里它底下有 **22 种**叠层、
  2717/2717 条读数都带着是哪一种，于是**退出确认弹窗上学到的 X 坐标被 8 轮以上花在加成总览上**
  （点进面板自己的数字列），且**没有任何地方报错**（查询命中、照用）。全量 13883 条读数里
  **25%** 的屏身份被丢弃。**先问：项目里是否已有正确概念、只是有第二处没跟上？**
  （这里 `state_signature` 早就写明了"更窄会跨屏复用含义不同的控件"，而只有 L1 层在用。）
- **"看起来像某个模板给了它"不等于它给的**。本项目 `#109` 的第一步就是这种巧合：落点 `[635,456]`
  正好等于某模板记录的 roi 中心，于是像是模板给的；而**用生产的 `find()` 在同一帧上跑**返回 `None`
  ⇒ 落点其实来自再往下的"记忆台账"层。**让真代码回答，不要停在像不像。**
- **给出"找到的点"和"实际点的点"必须一致**：解析点 `(0.9236,0.1301)×(720,1280)=(665.0,166.5)`、
  执行台账 `tap_point [665,167]`、帧上目视量到的 X —— 三者同一位置，这条链才算闭合。
- **状态机式的桩要真的会变**：给整轮测试造设备/视觉桩时，让"视觉读到的页面"由**桩自己收到的点击**
  推出来（本项目 `test_no_repeated_look_around._TwoPageClient`）。忽略点击的桩会让运行因为
  **真实客户端给不出的理由**绕圈，于是测试在测一个不存在的世界。
- **新名字要同时登记到所有读这份词汇表的地方**：本项目一个停机理由要进
  `runtime_snapshot.NON_FATAL_STOPS`、面板的 `REASON_ZH`、`RUNTIME_WAITING_STOPS`、
  `summarize_runtime_result` 的 `successful_stops` —— 少一处，一个每步都验证通过的运行
  在面板上显示 ● 异常。**加理由前先 grep 这个字符串在别处的用法。**

## 反面清单

- ✗ 因为设备忙着就跳过证据，把 pytest PASS 当完成。
- ✗ 用自选帧（"这几帧看着对"）而不写挑帧口径。
- ✗ 只跑处理组，没有负向对照组。
- ✗ 采信记录里的读数（记录可能是**旧读取器**写的）。
- ✗ 为了让 A/B 好看而改两次变量（例如顺手把观测也换掉）。
- ✗ 量出"这个规则几乎不会触发"之后仍然把规则加进去——那既不改善真实运行，又增加一条要维护的分支。
