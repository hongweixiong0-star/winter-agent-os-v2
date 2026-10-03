# 训练链的真正根因：动作成功、状态后到，被记成失败（2026-10-03 第十三轮）

> 上一轮我说"启动了错误的兵种"。**那是错的，本文件纠正它。**
> 营、兵种、目标三者全对，训练也真的启动了 —— 问题在**验证的时序**。

---

## 一句话

`TRAIN_TROOPS` 点了 `BTN_START_TRAINING`，训练**确实启动了**，
但验证器在"点完立刻读"的那一瞬读到 `status=AVAILABLE`、无计时器、队列仍空闲
⇒ 记为 `TRAINING_START_NOT_PROVEN` ⇒ **`goal_progress` 永为 False**。
**5 次失败里有 3 次，下一步就看到了 `IN_PROGRESS` + 计时器。**

---

## 一、上一轮的错误，纠正

我写"它启动的是 INFANTRY，而目标是 SHIELD_CAMP_TRAINING（盾兵）"，
并据此说"按钮位置取自当前打开的营"。

**实测那一帧（07:13:04）：**

```
troop_type        "INFANTRY"
camp_open_label   "盾兵营"
goal              SHIELD_CAMP_TRAINING
CAMP_GOAL_FOR     {'SHIELD_CAMP': 'SHIELD_CAMP_TRAINING', ...}
TROOP_TO_CAMP     {'INFANTRY': 'SHIELD_CAMP', 'SHIELD': 'SHIELD_CAMP', ...}
```

`INFANTRY` **就是**盾兵（`LABEL_TO_TROOP['盾兵营'] = 'INFANTRY'`）。
三者完全自洽，`brain.py:2304` 的门（`goal_camp != open_camp` 才切页签）
**正确地没有切页签**。

全 TRAINING 页 86 步的交叉验证：

```
troop_type 与 camp_open_label 一致 63 帧，不一致 0 帧
（MARKSMAN/射手营 25、LANCER/矛兵营 21、INFANTRY/盾兵营 17）
```

⇒ **观测侧没有矛盾，切换页签的逻辑也没有错。** 我上一轮把
`INFANTRY` 读成"别的兵种"，是**没查 `TROOP_TO_CAMP` 就下的结论**。

---

## 二、真正的根因：验证早了一瞬

5 次 `TRAINING_START_NOT_PROVEN` 的 `verifier_evidence` **五次完全一致**：

```
was_available: True
type_ok:       True     ← 兵种对
status_ok:     False    ← 那一刻读到的 status 不是 IN_PROGRESS
timer_ok:      False    ← 也没读到计时器
queue_busy:    False    ← 队列仍显示空闲
```

**`type_ok=True` 说明 `after` 帧的兵种是对的**，也就是说 `after` 采到了正确的页面 ——
只是**状态还没刷新**。

而每次失败之后的下一步：

| 失败时刻 | 下一步 | 训练状态 |
|---|---|---|
| 10-01 03:03:26 | 03:03:32 | **IN_PROGRESS / timer 11:25:07** ✓ |
| 10-01 14:55:50 | 14:55:54 | AVAILABLE / timer null（未启动） |
| 10-02 15:54:51 | 15:55:01 | **IN_PROGRESS / timer 11:25:07** ✓ |
| 10-03 07:13:04 | 07:13:13 | **IN_PROGRESS / timer 11:25:08** ✓ |
| 10-03 07:16:55 | 07:16:59 | AVAILABLE / timer null（未启动） |

**5 次里 3 次训练真的成功了**，只是没被记到。间隔都是 **4–10 秒** ——
状态在下一步就绪，而验证已经在更早的那一瞬判完了。

### 为什么重试没有救回来

`runtime.py:9696` 一带有这套机制：

```python
self.sleeper(settle_first_wait)
...
if not frame_changed and settle_retry_wait > 0.0:
    self.sleeper(settle_retry_wait)
    retry_path = self._capture_path(index, "after", suffix="settle_retry")
```

**它靠 `frame_changed` 决定要不要重试。** 而训练启动时**页面不变**（还在 TRAINING，
只是队列图标刷新）⇒ `frame_changed=False` ⇒ 会重试，但
`settle_limit` 把总等待截到 `settle_seconds`（默认 1.5s）以内
⇒ **远小于实测需要的 4–10 秒** ⇒ 重试读到的仍是旧状态。

**判据用错了信号**：训练启动不改变画面构成，只改变队列徽标；
"画面没变"不等于"什么都没发生"。

---

## 三、这不是"放松验证器"

`verify_training_started` 要求
`was_available` + `troop_type` 相等 + `IN_PROGRESS` + 有计时器 + 队列忙 ——
**这 5 条一条都不能少**。本轮的问题**不是条件太严，是读取时机太早**。

区别很关键：
- **放松条件** = 把"启动了别的兵种"也记成成功 ⇒ 把真缺陷记成成功；
- **等久一点再读** = 承认状态是异步刷新的 ⇒ 条件不变，成功照记、失败照失败。

第二种是对的。

---

## 四、边界：还有两件事没查

1. **为什么每次都是"下一步"才看到 `IN_PROGRESS`，而不是同一步的 settle 重试？**
   需要量 `settle_first_wait` / `settle_retry_wait` / `settle_limit` 的实际值，
   以及 `FrameChangeProbe` 在训练页上到底看到了什么。
2. **14:55:50 与 07:16:55 那两次是真的没启动**（下一步仍 `AVAILABLE`）
   ⇒ 训练本身有**间歇性失败**，那是另一个问题（`BTN_START_TRAINING` 模板在手或动画下失配）。
   **不要把这两个问题混成一个。**

**这两条没量之前不写代码。** 本会话已有四次"改了三处方向都错"的记录，
本轮已经纠正了一次自己的错误结论，不急在这一步。

---

## 五、本轮状态

- **零代码改动。** 生产 pin `291ede58`，AUTO 正常运行。
- 分支 `workbuddy/page-residency-20261003` = `fa853d77`。
- 上一轮的 `TRAINING_CHAIN_ZERO_PROGRESS_20261003.md` 里"启动了错误兵种"一节
  **已被本文件纠正**。
