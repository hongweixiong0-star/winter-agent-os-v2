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

### 为什么"重试"没有救回来 —— 上一轮说反了方向

上一轮我写"`frame_changed=False` 所以重试被跳过"。**方向说反了。**
`runtime.py:9696` 的条件确实是 `if not frame_changed and settle_retry_wait > 0.0`，
但用**同一批 before/after 帧**直接跑 `FrameChangeProbe` 实测：

```
TRAIN_TROOPS 失败步（5 次）
  03:03:26  changed=True  fraction=0.1963
  14:55:50  changed=True  fraction=0.1935
  15:54:51  changed=True  fraction=0.1113
  07:13:04  changed=True  fraction=0.2450
  07:16:55  changed=True  fraction=0.1999
```

阈值是 `fraction >= 0.06`，实测 0.11–0.25 ⇒ **5/5 都被判为"画面已变"**
⇒ **重试分支根本没进去**。

**真正的链条：**

```
TRAIN_TROOPS 点下按钮
  → 训练启动，队列徽标刷新 ⇒ 画面变了 11–25%
  → FrameChangeProbe 因此回答 changed=True
  → 代码据此判定"不需要再等" ⇒ 只等 first_wait
  → 但"徽标刷新"与"状态字段可读"是两件事，后者更慢
  → 观察时 status 仍是 AVAILABLE、无 timer ⇒ 记 TRAINING_START_NOT_PROVEN
```

**settle 预算（`TRAIN_TROOPS` 已在 `settle_policy._NETWORK` 集合内）：**

```
SettlePolicy('NETWORK_ACTION', first_wait_s=0.2, retry_wait_s=0.5)
名义总计 0.7 秒
```

而状态真正可读需要 **4–10 秒**（下一步的实测值）。**差 6–14 倍。**

⇒ **"画面变了"被当成了"状态可读了"**。这两个信号在训练启动这一刻**恰好不同步**：
徽标先变，状态字段后到。

⚠ 账本**没有持久化** `latency` 里的 `settle_*_ms`（读出来全是 0/null），
所以 0.2/0.5 秒来自 `settle_policy.choose('TRAIN_TROOPS')` 的代码值，
0.11–0.25 来自**对账本现存帧的直接测量**。两者都不是推断。

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

## 四、第十三轮：两问都答完了

### 问一：Probe 的 ROI 覆盖得到队列徽标吗？—— 覆盖到，而且它就是变化源

`FrameChangeProbe._thumbnail` = `resize((72,128))[13:109, 4:68]`
⇒ 覆盖 **y_norm 0.102 – 0.852**。

在 07:16:55 那对 before/after 上逐行测变化占比，峰值**精确落在徽标所在行**：

```
thumb_row 83   y_norm=0.648  变化占比=0.56
thumb_row 84   y_norm=0.656  变化占比=0.89   ← 峰值
thumb_row 85   y_norm=0.664  变化占比=0.91   ← 峰值
thumb_row 86   y_norm=0.672  变化占比=0.33
全图变化率 0.1391   vs   Probe ROI 变化率 0.1999
```

**整行 90% 都变了，那正是计时器/队列徽标刷新的位置。**

⇒ **`changed=True` 是完全正确的判断** —— 徽标真的变了。
上一轮我怀疑"ROI 覆盖不到所以测错了"，**这个怀疑是错的**。

**真正的不对称因此更清楚了：**
**徽标（图像）已经刷新，而 `status` / `timer`（结构化字段）还没刷新。**
这两个信号在训练启动这一刻**不同步**，而代码拿前一个当后者的判据。

### 问二：那两次"真的没启动"是什么？

**仍然开着。** 10-01 14:55:50 与 10-03 07:16:55 两步之后
`status` 仍是 `AVAILABLE`、`timer` 为 `null` ⇒ 训练**没有启动**。
`BTN_START_TRAINING` 的模板在手/动画下失配是一个可能，
但**没有量过就不写成结论**。

**这是与上面完全独立的第二个缺陷。** 修好读取时序只会让 3 次成功被记上，
**不会**让那 2 次开始。混在一起会两边都修不好。

---

## 五、现在的状态与下一轮的起点

**两问的答案把修法方向完全确定了：**

| | 做法 | 后果 |
|---|---|---|
| ❌ | 放松 `verify_training_started` 的五个条件 | 把"启动了别的兵种"也记成成功 |
| ❌ | 改 `FrameChangeProbe` 的 ROI 或阈值 | 它**判断正确**，改了会引入误判 |
| ✅ | **让"状态字段可读"成为独立的等待条件**，而不是用画面变化代理它 | 条件不变，成功照记、失败照失败 |

⚠ 具体形态仍未定：是把 `frame_changed` 从"是否重试"的判据里拿掉、
还是给 `TRAIN_TROOPS` 单独加一个"等状态字段刷新"的轮询，
取决于下一轮读完 `runtime.py:9665-9710` 的完整控制流后才能定。
**两者都会让"画面不变但状态已变"的情况误判，所以不能随手改。**

---

## 六、本轮状态

- **零代码改动。** 生产 pin `291ede58`，AUTO 正常运行。
- 分支 `workbuddy/page-residency-20261003` = `7b7c7c4e`。
- 上一轮的 `TRAINING_CHAIN_ZERO_PROGRESS_20261003.md` 已被纠正横幅标注。
