# 操作者的 72h 验收标准**在构造上不可能满足**：它要求一个只增不减的计数器等于 0（2026-10-14）

> `unexpected_worker_exits = 0` 是操作者写进规则文件的**近期验收**。而这个计数器
> **累计、从不归零**（只有 `previous + 1`），现在读到 **59**。
> ⇒ 在这台机器上，`= 0` **再也不可能成立** —— 无论系统变得多好。
> 这与"看门狗块用 `> 0` 判据"是**同一个算术错误**，而那个已经在面板里被更正过（有先例）。

---

## 一、标准在哪（两处，都是操作者的口吻）

| 位置 | 原文 |
|---|---|
| `.workbuddy-ai/rules/OPERATIONAL.md:14` | "近期验收：连续 **72 小时**无人值守，`unexpected_worker_exits = 0`；通过后进入 5–7 天 Soak。" |
| `docs/PROGRESS_2026_09_14.md:81` | "**72h Soak 验收**：`unexpected_worker_exits = 0` 持续 ≥72 小时" |

## 二、计数器为什么到不了 0

- 它**只增不减**：`tools/control_panel.py:9191` 与 `:9237` 都是
  `unexpected_worker_exits=previous.unexpected_worker_exits + (1 if counts_as_exit else 0)`。
- **全仓库没有任何重置路径**（只有 dataclass 默认值 `0` 与那两处 `+ 1`）。
- 而且历史值是**有意保留**的：`.workbuddy-ai/commander/REVIEW_REQUESTS.md:72`
  写着"历史 `unexpected_worker_exits=15` **保留不变**"。
- 现在读到 **59**（`learning/runtime_snapshot.json`）。

⇒ **历史上死过一次 worker 的机器，`= 0` 永远不再成立。**

## 三、已经修过两层，但**没修标准本身**

| 层 | 状态 |
|---|---|
| **计数规则**（RR-001 / `WB-R19-RUNTIME-EXIT-SEMANTICS`，2026-09-16） | ✅ **已修**：原来有两个写入方、规则不一致（兜底路径"凡非 fatal 全计"）；现在两者都调 `counts_as_unexpected_worker_exit()`，也有测试钉住（`tests/test_worker_exit_semantics.py:126/130`）。⇒ **"环境失败也算崩溃"这条已经不成立** |
| **面板阈值**（`tools/control_panel.py:5723-5735`） | ✅ **已修**：§六 写的字面 `> 0` 被改成"**相对本窗口首见值的增长**"，docstring 原文："the literal was implemented first and **measurement killed it on this very machine**… `> 0` therefore measures the machine's *history* rather than the present" |
| **验收标准**（`OPERATIONAL.md:14`） | ❌ **没修** —— 它仍然写着绝对 `= 0` |

⇒ 所以 `03_NEXT_ACTION.md:966` 那条告警**不是过时的**，只是它给的理由只覆盖了第一层
（"把环境失败也算崩溃"），而**第二层理由仍然成立**：累计不归零。

## 四、⚠️ 我自己中途差点判错（记下来）

我一度推断 `03_NEXT_ACTION.md:966` 是**过时的**（"验收其实只看连续轮次"）—— 依据是
`learning/auto_uptime_acceptance.json` 的 `acceptance_required: 3` / `acceptance_met: true`
（连续继续轮次）**和** `tools/unattended_closure.py` 里搜不到这个计数器。

**那个推断错了**：验收有**两条**路径。轮次那条（`measure_auto_uptime.py`）是一条，
而 `OPERATIONAL.md` / `PROGRESS_2026_09_14.md` 里的 **72h + 计数器 = 0** 是另一条，
且它是**操作者写下的**那条。**只看其中一条就宣布另一条过时，是我这一轮的错。**

## 五、建议（**属操作者的标准，本轮没改**）

按 `control_panel.py` 已经用过的**同一把尺子**改：

- 把 `OPERATIONAL.md` 的 `unexpected_worker_exits = 0` 改成
  **"相对某个基线只增"** —— 即"记下一个基线（时间戳 / 当时的计数），验收窗口内**不增长**"；
  这与面板那条的做法完全一致，也保住 §六/§一 的**本意**（"一次意外退出就是信号"），
  只是把**算术**改成与字段实际含义相符。
- 或者：明文规定"验收前重置/记录基线"这一步，把它写进流程而不是留给读者推断。

**本轮没有改**：它改的是**操作者的验收标准**，属他们的决定（与第167轮"加 outcome 词"同一类）。

## 六、这条为什么值得写下来

操作者把 **72h / `= 0`** 列为近期验收门槛。按现状，**这道门永远不会开** ——
不是因为这系统不可靠，而是因为**一个累计计数器被拿来和 0 比**。
下一个读到 `unexpected_worker_exits: 59` 的人，需要一个明确的说法，而不是自己去猜它是不是"59 次崩溃"。

## 七、未做

没改 `OPERATIONAL.md`、没改 `PROGRESS_2026_09_14.md`、没加重置路径、没动 `runtime_snapshot`。
