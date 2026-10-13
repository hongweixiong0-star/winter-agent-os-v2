# 学习闭环其实学到过并复用了 24 次——而控制台记 0

日期：2026-10-06 · 状态：**三条已坐实，一条未解**

## 一句话

`THE_LEARNING_FUNNEL_PRODUCES_NOTHING_20261006.md` 的结论**过强**：
机器**确实**学到过一个可复用步骤，并在真机上**不带模型**复用了 **24 次**（最近一次 2026-10-06T02:08:14Z，
就是查看前 8 分钟）。真正坏掉的是**上报**（漏斗记 0）和**在线提案的准入**（723/723 全被拒）。

## 搜索产物

```
=== 搜索产物 ===
任务/问题：在线学习闭环是否真的什么都没产出
搜索关键词：
  - 本仓库：LEARNED_STEPS_PATH / VerifiedStepLedger / learned_steps_for /
    CANDIDATE_STEP_REUSED / SECOND_ENCOUNTER / CANDIDATE_STEP_CREATED /
    CONTRACT_ONLINE_* / call_context / _learned_ledger_rows /
    _learned_reuse_point / _note_learned_step / model_used / reused_from_trace_id
  - 真机数据：learning/{ui_venus_online,learning_funnel,episodes,decisions}.json(l)、
    learning/control_panel/{panel.log,crashes/}、knowledge/perception/candidates/INDEX.json
搜索结果：
  1. **在线契约准入是零**：`CONTRACT_ONLINE_ROWS=723`、`ADMITTED=0`、`REFUSED=723`
     （家族 `OTHER 665 / TARGET 58`）。`VENUS_PROPOSED` 全史 105 条决策里
     **REPLAN 91 / DEFER 12 / OBSERVE 2，EXECUTE 一次都没有**。
     ⇒ 模型从未驱动过任何一步，`grounding_valid=0` 与 `UNKNOWN_RESOLUTION_RATE=0.0` 由此而来。
  2. **但复用路径是真的在跑**：`CANDIDATE_STEP_REUSED` × 24，全部
     `CLAIM_EXPLORATION_IDLE|UNKNOWN|ORDINARY_CONTROL[领取]|`、全部 `model_used=False`。
     时间线：10-04 一条 → 10-05 十三条 → 10-06 01:51 起每 ~2.7 分钟一条至 02:08:14。
  3. **控制台记 0 的原因找到了**：`learning_funnel.py:275` 计数条件是
     `row.get("model_used") is False and row.get("reused_from_trace_id")`，
     而真机那 24 条的 `reused_from_trace_id` **全是空串**。
     写入者 `_learning_event`（runtime.py:3404）取的是 `context.get("reused_from_trace_id")`，
     而 `_learned_reuse_point`（runtime.py:7396）填的是被复用台账行的 `row.get("trace_id")`
     —— 即**台账行自己没有 trace_id**。
  4. 顺带更正：`UNKNOWN_REPEAT_MODEL_CALL_RATE` 不是"重复问同一屏"。
     `call_context` 字段**从未被写进 `local_planner_steps.jsonl`**（314 行全 missing），
     于是 `learning_funnel.py:428/433` 的过滤条件恒真。该指标实际量的是
     "模型调用落在已命名页上的占比"，而调用点 `runtime.py:6747` 自己的注释写着
     「**This is a missing control on a known page, not a missing page identity**」——
     两者直接矛盾。⇒ 该指标不能作为"浪费"的证据。
假设：
  (a) 上报缺陷可直接修：让计数不再依赖一个生产环境恒为空的字段（或修写入者）。
  (b) 准入为零是更根本的问题：模型从未产出过可采纳的提案，应查 723 条的原始拒绝码。
不确定性：
  **台账文件 `learning/unknown_verified_steps.jsonl` 现在不存在**，
  `VerifiedStepLedger(<runtime 解析出的路径>).rows()` 返回 0 行，
  而 24 次复用要求它当时非空。**这个矛盾未解**。已排除的嫌疑人：
    - 保留策略：`_enforce_retention` 只剪 `CAPTURE_ROOT` 的截图，不碰 learning/；
    - repin：`repin_production.py:99-101` 的 pathspec **显式排除**
      config/knowledge/learning/dataset；
    - 测试：四个引用该路径的测试文件全部用 `tmp_path`，且 `tests/conftest.py` 未重定向该常量；
    - main 工作树常量不同：不是，两处都是 `learning/unknown_verified_steps.jsonl`。
  剩余可能（未验）：某个只在真机路径上跑的写入/清理者；或复用事件另有发射点（但 grep
  只命中 runtime.py:7407/7408 一处）。
=== 结束 ===
```

## 为什么这比"修训练守卫"更值得做

上一轮我修的训练派发守卫，事后核对时间线发现它的 50 次失败**最后一次是 10-05 17:31，
即改动前约 17 小时就已经停了**——那次修复的价值是防御性的（外加修好一个先存的红测试），
不是"消灭了正在流的浪费"。而本文这三条是**此刻仍在发生**的：
复用每 2.7 分钟一次、准入 100% 被拒、控制台对已发生的事报 0。

## 对既有文档的更正

`THE_LEARNING_FUNNEL_PRODUCES_NOTHING_20261006.md` 标题与结论应改为
"**学习闭环在上报与准入两处断开**"，而不是"什么都没产出"：
它引用的 `UNKNOWN_REPEAT_MODEL_CALL_RATE=0.7761`（"77.6% 是重复问同一件事"）是**误读**（见上第 4 条），
而它真正的证据 `UNKNOWN_RESOLUTION_RATE=0.0` 与 `grounding_valid=0` 依然成立。

---

## 追加更正（同轮）：我上面第 1 条说错了

我在本文件里写「在线提案 **723/723 全被拒**」，**这是错的**，必须撤回。

### 真相：`CONTRACT_ONLINE_*` 是三个幽灵指标

`learning_funnel.py:457-458`：
```python
online_admitted = [row for row in online_rows if row.get("admitted")]
online_refused  = [row for row in online_rows if not row.get("admitted")]
```
分母是 `ONLINE_LEDGER = learning/ui_venus_online.jsonl` 的**全部行**（737 行）。
而该文件里**没有任何一行带 `admitted` 字段**（实测：带 `admitted`/`verdict` 的行 = 0）。

⇒ `not row.get("admitted")` 对**阶段行**（`UNKNOWN_OBSERVED` / `VENUS_CALLED` / …）恒为真，
于是 723 行被算成"拒绝"。`ADMITTED=0` 的含义不是"模型全被拒"，
而是"**这份台账里没有一行是契约裁定行**"。家族 `OTHER 665 / TARGET 58`
也是从阶段行的 `error` 字段反推出来的，不是契约的家族。

**为什么契约行不存在**：写入者是 `OnlineLedger.record_action / record_refusal`
（`ui_venus_online.py:1003/1019`，会写 `admitted` 与 `verdict`），
唯一调用点在 `ui_planner.py:1369/1372`，且该处还会写跟踪阶段
`CONTRACT_ALLOWED` / `CONTRACT_REJECTED`——**这两个 stage 在 737 行里一条都没有**。
即：契约校验这一步在真机上从未留下任何记录。
⇒ 这是本次会话第 **五** 次撞上同一个模式：**有消费者、没有生产者。**

### 真正的拒绝信号是 `VENUS_PROPOSAL_REJECTED` × 58，而且高度集中

```
   50  PLAN_TARGET_IS_NOT_A_CONTROL: E16 is TEXT_LABEL
    2  PLAN_TARGET_IS_NOT_A_CONTROL: E21 is TEXT_LABEL
    1  PLAN_TARGET_NOT_ON_THIS_SCREEN: 'E11 (1倍钓鱼)'
    5  其余 E7/E10/E13/E22/E24 is TEXT_LABEL
```
50 条全部来自同一个 `request_id = unknown__control__57d12023`（`UNKNOWN::城墙`），
这正是第二多重复屏（70 次 Venus 调用、66 次调用失败）。

### 断点的完整陈述（替代第 1 条）

105 条模型回复的归宿：
- **58 条指定了目标，但指定的是"打印文字"**，被计划校验器按 §2 规则拒绝
  （`ui_planner.py:713` `element.get("executable") is False`；
  而 `executable` 的判据在 `ui_collection.py:2229`：**打印文字只有在"本帧同时测到同名控件"
  时才可执行**）。拒绝是**正确的**——§2 原话「不存在可靠交互区域时，该元素不得作为可执行
  CLICK 目标提供给 Qwen」。
- **47 条根本没有指定目标**（REPLAN 91 减去被拒的份额，实际落到 47：REPLAN/DEFER/OBSERVE）。
- ⇒ **没有任何一条指定了一个可执行的控件。这就是 `EXECUTE` 从未出现的全部原因。**

**它是"模型在指一个名字，而不是一个控件"，不是管道坏了。** 修的方向有两个，都还没做：
1. 若该屏幕上**一个可执行元素都没有**（很可能：`UNKNOWN::城墙` 没有测到任何控件），
   那么这一轮**根本不该花那次模型调用**——同"训练守卫"那一类前置条件的形状；
2. 若屏幕上确有控件而模型仍指文字，就是提示词/置信的问题。
   两者需要先量出"这些帧里 executable 元素有几个"，而现有台账**不记录这个数**
   （`VENUS_CALLED` 有 `element_count`，但没有 executable 计数）。
