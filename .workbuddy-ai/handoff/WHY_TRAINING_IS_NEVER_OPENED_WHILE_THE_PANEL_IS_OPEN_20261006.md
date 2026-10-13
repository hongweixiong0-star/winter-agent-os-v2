# 为什么"从营地动作条开训练"在面板开着时从来不可能成功

日期：2026-10-06 · 状态：**已测量，待修（守卫缺项）**

## 一句话

`KEEP_TRAINING_PRODUCTIVE` 的营地动作条路线（`OPEN_INFANTRY_TRAINING` → 点 `BTN_OPEN_TRAINING_FROM_CAMP`）
在快捷面板打开时**0 成功 / 57 次**；面板关闭时 **42 成功 / 47 次（89%）**。
判别量**完全分离**，不是"偶尔失败"，是这条路径在那种状态下不可能成功——而 brain 仍然派发它。

## 搜索产物

```
=== 搜索产物 ===
任务/问题：训练目标长期打不开训练页，且代价是每次失败都多付一次 Venus 调用
搜索关键词：
  - 本仓库：OPEN_INFANTRY_TRAINING / BTN_OPEN_TRAINING_FROM_CAMP / train_tap_norm /
    panel_open_but_training_unread / _panel_draws_the_training_section /
    QUICK_PANEL / preconditions / call_context
  - 真机数据：learning/{episodes,decisions,loop_watch,auto_uptime,ui_venus_online,
    local_planner_steps}.jsonl、learning/learning_funnel.json、
    knowledge/perception/candidates/INDEX.json
搜索结果：
  1. 模型调用总量：229 次 / 13 个 request_id；其中 105 次是 REPLAN/DEFER，
     **74 次（70%）只来自两个具名目标**：BTN_OPEN_TRAINING_FROM_CAMP（50）、
     BEAST_SEARCH_TAB（24）。两者都是"阅读器认不出的具名控件"，不是模型弱。
  2. 该技能的步级结局：104 次尝试，42 SUCCESS / 62 FAILURE（59.6%）。
     **按快捷面板开合切开是干净的两半**：
         面板关：47 次，42 成功（89%）
         面板开：57 次，0 成功（0%）
  3. 失败样本的自身叙述：
         decision_reason  = panel_open_but_training_unread_so_the_page_that_answers_it_is_the_step
         recognition_error= UNKNOWN_NAV:PROVIDER_ANSWERED_NOTHING
         state_before.page= HOME
     61 条带该 decision_reason 的行里 56 条 quick_panel.open=True，且 61 条全部 FAILURE。
  4. 派发点：brain.py:2396-2401。它上方的守卫只在
     「面板开 **且** 面板没画出部队训练区」时改走 SCROLL_QUICK_PANEL_BACK / SAFE_STOP；
     一旦面板**画出了**训练区，就落到派发营地动作条那条分支——而此时动作条正被面板盖住。
  5. 解析器 runtime.py:5876 读的是 `(frame.training or {}).get("train_tap_norm")`，
     它要求动作条可读；面板盖住时该字段必然为空 → 解析器返回 None → 记一次 miss →
     记 ONLINE_UNKNOWN_NAVIGATION → 下一轮问 Venus → REPLAN。这正是那 50 次的来源。
假设：
  在**派发的那条分支**上加守卫——派发前先要求本帧自己的读数里存在该控件
  （`world.training.train_tap_norm` 是二元点），否则不派发。
  这是最紧的守卫，因为解析器没有它必然返回 None：
  没有它的一次派发是**可证明的空步**（该分支上方注释的原话：
  "this is a dispatch into a control that provably cannot be resolved"）。
  同文件 brain.py:1756 已有同型先例（用 `world.building.upgrade_tap_norm` 存在性做守卫）。
不确定性：
  a. 面板关闭但仍读不到动作条的 5 次失败（47 次里的 5 次）会被这条守卫一并抑制——
     这是想要的（同样可证明的空步），但目前只有 5 个样本。
  b. 更彻底的修法是让面板开着时改走**面板自己的路线**
     （`OPEN_TASK_FROM_QUICK_PANEL_SHIELD/LANCER/MARKSMAN`，已注册），
     那是"让目标真的做成"而不是"停止空转"。本次不做——先加守卫，
     路线改派需要它自己的证据（哪个营地行对应 KEEP_TRAINING_PRODUCTIVE 尚未测量）。
  c. `world.training` 在**决策时**与**解析时**是否同一帧读数，未逐条核对；
     成功样本 42 条与该假设一致（成功必须由解析器给出点）。
=== 结束 ===
```

## 顺带记录的两个「字段有生产者、无消费者」

本次排查中又撞到两次同一模式（本会话第三次与第四次），都不是本次要修的，但要留痕：

1. `Skill.preconditions`（`skills.py:63`）——被 `capability_miner` / `unknown_learning` /
   `knowledge_preload` / `skill_factory` 四处写入，**调度/大脑侧零读取**。
   若它有消费者，`OPEN_INFANTRY_TRAINING` 的"动作条可读"本该写在声明里。
2. `call_context`（`learning_funnel.py:428/433`）——**从未被写进 `local_planner_steps.jsonl`**
   （314 行全是 `(missing)`），于是 `!= "ONLINE_UNKNOWN"` 恒为真，
   `UNKNOWN_REPEAT_MODEL_CALL_RATE` 变成"模型调用落在已命名页上的占比"。
   而调用点 `runtime.py:6747` 自己的注释写着「**This is a missing control on a known page,
   not a missing page identity**」——与 `learning_funnel.py:426` 那句
   「调用点只守卫未命名屏，所以任何落在具名页上的行都是不该发生的调用」**直接矛盾**。
   ⇒ 该指标不是"浪费"的证据；上一份交接文档（`THE_LEARNING_FUNNEL_PRODUCES_NOTHING_20261006.md`）
   把它读成"77.6% 是重复问同一件事"是**误读**，我上一轮据此设的验收标准也**挂错了**。
   漏斗"什么都没产出"的结论不受影响——它靠的是 `UNKNOWN_RESOLUTION_RATE=0.0` 与
   `grounding_valid=0` 这两个独立证据。

---

## 实施记录与两处更正（2026-10-06，同轮）

### 采用的修法：把"代理判据"换成"解析器自己的输入"

原判据是"面板有没有画出**部队训练区**"——它是"那个控件够不够得着"的**代理**，而它量错了东西：
面板是**盖在**动作条上的，所以"区画出来了"完全不能推出"下面的控件读得到"。
现判据改为本帧自己的读数 `world.training.train_tap_norm` 是否为二元点——
**这正是解析器 `runtime.py:5876` 要的东西**，所以它只可能拒绝**本来就点不动**的步。

另一个派发点（`brain.py:1714`，"an opened camp bar is the page this goal came for"，42 次成功的那条）
要求的正是 `world.training.get("menu_open")`——两处现在问的是同一件事。

### 更正一：我犯了一次"假阴性"，并据此下了错误断言

排查中我用 `grep -rn "test_unanswered_training_opens_the_training_page" .` 去找那个被引用的测试，
**零命中**，于是断定"引用指向一个已删除的文件"，并把这句话写进了 `brain.py` 的注释和测试文档里。
**错了。** 文件一直在（`tests/test_unanswered_training_opens_the_training_page.py`，6298 字节，
git 跟踪，提交 `e52bec7d`）。零命中的原因是：**我在用文件名的字符串去搜文件的内容**，
而它当然不会在自己的正文里写自己的文件名。`ls` 一秒就能证伪。

⇒ 教训：**"某文件是否存在"要用列目录/git 回答，不能用内容 grep 回答。**
一次零命中的内容搜索，对"存在性"这个问题**没有证明力**。
（这三处错误断言已从代码与测试注释中撤回并改成事实描述。）

### 更正二：那个"矛盾"其实是 fixture 少写了一个前置

`test_unanswered_training_opens_the_training_page` 的 fixture `_home_panel()` **既没写 `camps`
也没写 `training`**——是个合成帧。而解析器**必须**有 `train_tap_norm` 才能给出坐标，
所以那 57 次历史成功**必然**都带这个读数。**我的新守卫不会拦住它们**，
只会拦住那 56 次本来就点不动的。

⇒ 处理：给该 fixture 补上动作条读数（`BAR_POINT`），并在注释里说明为什么补。
**该测试的意图（"没被回答的训练问题要走到训练页，而不是被拒"）完整保留**，
两个文件从互相矛盾变成互相一致。两个文件合起来 **20 passed**。
