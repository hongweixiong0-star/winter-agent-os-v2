# 学习漏斗在 grounding 之前就断了：UNKNOWN 解决率 0.0（2026-10-06）

> 只读生产观察（AUTO 运行期间，§2 禁改代码）。**本轮没有改任何东西。**
> 这是本会话找到的最大一条 —— 它命中的是项目自己声明的当前阶段（§9 CAPABILITY_EXPANSION）。

## 一句话

**生产侧在跑，学习侧根本不产出。** `learning/learning_funnel.json`：

```
GAME_TASK_COMPLETION_RATE      0.8816    ← 生产侧 88%
KNOWN_MODEL_CALLS              0         ← §24 成立：已知路径不调模型
UNKNOWN_RESOLUTION_RATE        0.0       ← 一个未知都没解决
UNKNOWN_REPEAT_MODEL_CALL_RATE 0.7761    ← 77.6% 是重复问同一件事
```

漏斗（当前窗口）：

```
unknown_observed        68
venus_called            68
venus_proposed          60
grounding_valid          0   ┐
grounding_rejected       0   │ 注意：这两个同时为 0
risk_gate_allowed        0   │
maa_executed             0   │  count=0 且**没有** unmeasured_reason
verifier_success         0   │  → 是"测了，是零"，不是"没测"
candidate_step_created   0   │
candidate_skill_created  0   ┘
candidate_replay_pass    None  reason=REGISTRY_OWNS_THIS   ← 只有这几级是"没测"
```

**所以漏斗不是"卡在某一级"，是 `VENUS_PROPOSED` 之后没有任何下游阶段。**

## 为什么：§48 的尝试预算没有生效

`learning/ui_venus_online.jsonl`（713 行，01:31 仍在写）：

```
stage 分布：
  UNKNOWN_OBSERVED        228
  VENUS_CALLED            228
  VENUS_PROPOSED          103
  VENUS_CALL_FAILED        66    ← 29% 的模型调用直接失败
  VENUS_PROPOSAL_REJECTED  58
  SECOND_ENCOUNTER         15
  （没有 GROUNDING_* / MAA_* / VERIFIER_* 任何一行）
```

**而 228 次调用只对应 13 个 `request_id`：**

| request_id | 调用次数 |
|---|---|
| `home__control__36e65c39` | **84** |
| `unknown__control__57d12023` | **70** |
| `map__control__4cf644d7` | 30 |
| `event__control__b3c5c916` | 20 |
| `unknown__control__78694f1b` | 15 |

**合计 228 次 / 13 个问题 = 平均 17.5 次/问题；超过 2 次的 request 占调用数 219/228 = 96%。**

### 这直接违反 `PRINCIPLES §48`

> **§48 同一 UNKNOWN 不能无限烧模型**
> 同一 Screen：默认最多约 **2 次** Venus 尝试。
> 超过后：Recovery → Cooldown → Next Goal
> **禁止：Venus → Replan → Venus → Replan 无限循环。**

账本里 `decision` 分布：**`REPLAN` 90 次 vs `DEFER` 11 次 vs `OBSERVE` 2 次**。
**重规划是退避的 8 倍** —— 正是 §48 点名禁止的那个循环的形状。
`UNKNOWN_REPEAT_MODEL_CALL_RATE = 0.7761` 就是这条规则的度量，而它的值是 0.78。

### 最严重的那个还叠加了调用失败

| request_id | 失败/被拒次数 |
|---|---|
| `unknown__control__57d12023` | **66** |
| `home__control__36e65c39` | 27 |
| `event__control__b3c5c916` | 19 |

`unknown__control__57d12023` 被调用 70 次，其中 **66 次是 `VENUS_CALL_FAILED`** ——
即模型调用**本身**失败。所以这个未知被反复重试，而每次重试都失败，
它既没有产出提案，也没有触发退避。

## 为什么这条比"面板争用"重要

| | 面板争用（已修） | 本条 |
|---|---|---|
| 浪费的是 | 30% 的动作 | **学习管线的 100%** |
| 影响 | 生产效率 | **§9 当前阶段的全部意义** |
| 规则 | —（设计缺口） | **§48 明文写着的上限，被违反 9 倍** |

`§9` 说当前阶段是 `CAPABILITY_EXPANSION`、`§58` 说 0→1 优先于 95%→97% ——
而 `UNKNOWN_RESOLUTION_RATE = 0.0` 意味着**0→1 这件事一件都没发生**。
面板争用省下来的是动作；这一条省下来的是**整个学习循环**。

## 我还没搞清的（**不猜，列出来**）

§48 的 ~2 次预算显然在**某处**实现了（`unknown_advisor.REQUEST_COOLDOWN_SECONDS = 3600`
这类常量存在），但它**没有约束住这条路径**。可能是：

1. **计数器的"同一屏幕"身份与调用方的 `request_id` 不是同一个东西**
   （`request_id` 形如 `page__kind__hash`，若 hash 来自 frame，则会随帧变化 —— 但那与"84 次同一个 id"矛盾，
   所以更可能是计数器根本没被查）；
2. **`DEFER` 路径存在但输给了重规划**（90 vs 11 的比例支持这个方向）；
3. **`VENUS_CALL_FAILED` 走的不是"尝试"计数**（失败算不算一次尝试？如果不算，就会无限重试）。

**这三条导出完全不同的修法，必须先量再改** —— 本轮到此为止。
下一步该找的是：谁在 §48 的预算里扣数、以及 `VENUS_CALL_FAILED` 是否计入。

## 与前面几条的关系

- 面板争用（`4026fcd0`）已修并验证：那是**生产侧的效率**。
- 建筑花钱 0 行、`TRY_ORDINARY_CONTROL` 比值 5.82：**经查不是缺陷**
  （项目把 `SEMANTIC_TARGET_NOT_VERIFIED` 归类为 `stop_category=CAPABILITY_GAP`、`healthy=True`，
  `healthy=false` 只占 0.4%）—— 那是"遇到未知屏幕"的正常记录。
- **但那些能力缺口**（`SEMANTIC_TARGET_NOT_VERIFIED` 169 次、`ROLE_IDENTITY_UNCONFIRMED` 155 次）
  **本应被学习管线吃掉变成能力，而本文说明它们吃不掉** —— 这才是那条链的真正断点。
