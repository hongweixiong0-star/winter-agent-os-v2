# 奖励弹窗来源识别 + 终止页退出（2026-09-17）

本轮两件事：修掉 `04_OPEN_ISSUES.md` #22（情报奖励弹窗被判成每日奖励，导致**已经成功的领取**被记成失败），
以及让"上一轮停在训练/研究页 ⇒ 下一轮立刻 `goal_page_mismatch`"这一失效模式不再发生（#23）。

## 一、根因：#22 不是阈值问题，是**问错了问题**

`POPUP_DAILY_REWARD_CURRENT` 的 ROI 是 `x 0.08 y 0.20 w 0.84 h 0.40` —— **整个奖励格区域**。
它回答的是"这些奖励图标像不像我当初裁下来的那批"，也就是**内容**问题，而不是"这个弹窗由谁产生"。
它排在通用横幅之前，于是**任何**奖励弹窗只要格子长得像，就被判成 `DAILY_REWARD`。

在 103 帧有标签的生产帧上量四个总体（`SemanticWorldVision`，`max_distance=8`）：

| 语义 | DAILY(8) | EXPLORATION(12) | GENERIC(65) | INTEL(18) |
|---|---:|---:|---:|---:|
| `BTN_DISMISS_INTEL_REWARD`（页脚） | **8/8** | **12/12** | **65/65** | **17/18** |
| `POPUP_GENERIC_REWARD_HEADER`（横幅） | 5/8 | 8/12 | 64/65 | 1/18 |
| `POPUP_INTEL_REWARD_TITLE`（阈值 22） | 6/8 | 10/12 | 58/65 | 17/18 |
| `POPUP_DAILY_REWARD_CURRENT`（奖励格） | 8/8 | 0/12 | 0/65 | 0/18 |
| `POPUP_EXPLORATION_REWARD` | 7/8 | 12/12 | 1/65 | 0/18 |

只有**页脚**几乎处处在场（102/103，距离 ≤2）。而且 `key/01`（真实每日奖励）与 `key/03`（真实情报奖励）
的**页脚区域 phash = 4、横幅 = 4** —— 两帧是**同一个「获得奖励」弹窗**，只是奖励格子不同。

结论：**来源不在画面里。** 客户端对多种来源共用一个弹窗，所以唯一诚实的做法是报**目标中立的标签**，
让大脑按 goal 上下文选解除技能。这正是 `verifier.py` 第 953–961 行早已写下的设计
（"the source is therefore proven by the *before* state … any reward popup counts as the feedback"），
也是 `REWARD_POPUPS` 里**故意不含 `DAILY_REWARD`** 的原因。视觉层当时违背了这个设计。

同时核对：**五个 `*_reward_dismissed` verifier 全部早已接受 `GENERIC_REWARD`** 作为弹窗前置态，
所以这次改动不需要碰任何 verifier。

## 二、真机结果

### 修好后的两次真实领取（两个不同来源，都可追溯）

```
04:44:11  OPEN_DAILY                 HOME -> DAILY              verifier OK
04:44:20  DAILY_CLAIM_REWARDS        DAILY -> POPUP             verifier OK   ← 真领到
             after.popup = GENERIC_REWARD
04:44:29  DISMISS_DAILY_GENERIC_REWARD  POPUP -> DAILY          verifier OK   ← 目标上下文解除
04:46:21  OPEN_MAIL                  HOME -> MAIL               verifier OK
04:46:31  MAIL_CLAIM_REWARDS         MAIL -> POPUP              verifier OK   ← 真领到
             after.popup = GENERIC_REWARD
```

两处都走了 `DISMISS_*_GENERIC_REWARD` —— 这是**只有 `popup == "GENERIC_REWARD"` 才可达**的分支。
修好前，同一个弹窗会被判成 `DAILY_REWARD` ⇒ 大脑选 `DISMISS_DAILY_REWARD` ⇒ 其 verifier 要求
"之后回到 DAILY 页"，而实际上回到了源页 ⇒ **一次成功的解除被记成 FAILURE**（#22 的原貌）。

### 负样本闸门：全语料 0 假阳性

`tools/probe_reward_popup_gate.py`，3007 帧：

```
BTN_DISMISS_INTEL_REWARD         matched   186 frames
POPUP_GENERIC_REWARD_HEADER      matched   134 frames
any signal                         186 frames
observed as GENERIC_REWARD         186 frames
FALSE POSITIVES                      0 frames
```

页脚这条判据在**非奖励帧上从未命中**，所以把每一个奖励弹窗标成 `GENERIC_REWARD` 不会把普通页面误判成弹窗。

## 三、终止页退出（#23）：实现 + 单测验证，**真机 episode 尚未取得**

训练页与科技研究页是**叶子页**：goal 走到它们，没有任何分支把客户端移开。上一轮 TRAIN 就停在训练页，
于是紧接着的 DAILY/INTEL 轮**一步都走不了**就 `goal_page_mismatch`（本轮实测复现）。

修法不新增任何体系组件：**一次 BACK**（`verify_safe_back` 接受 `TRAINING/RESEARCH → HOME`，
两个方向都用 `tools/probe_power_route.py --leave` 量过），复用 `_leave_daily_panel_once` 的**一次性旗标**先例：

* 命名 goal 站在自己没有用的叶页上 → BACK（`*_page_not_actionable_leaving_the_page`）
* 该 goal 自己的叶页上确实无事可做（队列忙 / 无可开始节点）→ 先 BACK，再以具名原因停止
* **同一轮不再重走路线**（否则 HOME → 路线 → 页 → BACK → HOME 死循环）
* **拥有该页的 goal 与无 goal 的扫掠不受影响**（可训练的队列、可开始的研究节点照旧动作）

单测 `tests/test_terminal_page_exit.py`（12 项）逐条钉住上述行为；`check_wiring.py` 新增 4 条。

**尚未取得的证据**：真机 episode。原因是叶页**存活时间很短** —— 探针刚把客户端放到科技研究页
（`after#4 page=RESEARCH`），几十秒后 `run_live` 起跑时已读回 `HOME`，所以"下一轮开局就站在叶页上"
这个前提在真机上很难被我这次的操作序列稳定复现。下一步做法：把叶页**立即**接一个 goal 轮
（同一命令链内，不隔探针），或先给叶页做一次存活时长量测。

## 四、帧清单（`key/`，已白名单进公开仓库）

| 文件 | 说明 |
|---|---|
| `01_daily_reward_popup_163338.png` | **真实每日奖励弹窗**（`DAILY_CLAIM_REWARDS` 的 after 帧，16:33:38Z） |
| `02_intel_reward_popup_run1.png` | 真实情报奖励弹窗（09-16 23:53Z 那次失败的 after 帧） |
| `03_intel_reward_popup_run2.png` | 真实情报奖励弹窗（09-17 00:26Z 那次失败的 after 帧） |
| `04_intel_hero_journey_instead_of_beast.png` | **另一个缺陷**：点情报"前往查看"后打开的是「英雄之旅」而不是巨兽任务（#25） |

三张弹窗帧是这次量测的总体来源：它们是**同一个弹窗**被判成两种来源的直接证据。
