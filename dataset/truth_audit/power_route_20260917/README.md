# power_route_20260917 — 战力路线：训练与建筑共同卡住的那一段

## 为什么这些帧存在

2026-09-17 操作者要求「建筑和训练优先落地，情报记得及时做」。

两者**卡在同一处**，而且**不是推理问题**：

- `brain.py` 早已接好整条链（第 243–246 行、446–456 行）；
- `LiveRuntime.VERIFIED_ATOMIC` 早已绑好每一跳的 verifier；
- `run_live.py --goal` 早已接受 `TRAIN`。

**唯一断点是模板。** 今天真机 HOME 帧上实测，路线需要的语义**多数 MISS**：

```
POPUP_POWER_OVERVIEW               MISS   ← 真正的断点
BTN_OPEN_POWER_DETAILS             MISS   ← 真正的断点
POPUP_POWER_DETAILS                MISS   ← 真正的断点
BTN_POWER_TROOP_IMPROVE            MISS   ← 真正的断点
BTN_OPEN_TRAINING_FROM_CAMP        3/7 帧 MISS（门禁过宽，见下）
PAGE_TRAINING_INFANTRY             MISS
BTN_START_TRAINING                 MISS
BTN_OPEN_POWER_OVERVIEW_ICON       d=4（**本来就通**，见"更正"一节）
```

原因：这些模板（除最后一条）裁自 **2026-09-08 的另一个账号**
（战力 57,083,909 对今天的 826,444、不同头像、**城市镜头拉得更远**，
能看到今天客户端根本不显示的楼）。
`world.training` 因此永远为空，上面那些分支**一条都不可达**。

## 这一轮实测走通的链路

`tools/probe_power_route.py` 在真机上逐跳走（每跳的坐标都从前一帧量出来，
命令行显式传入，绝不盲点），`tools/register_power_route_templates.py` 把帧变成记录：

```
HOME --[点战力图标 (115,72)]--> POPUP / POWER_OVERVIEW  （加成总览）
     --[点 实力详情 (360,660)]--> POPUP / POWER_DETAILS  （实力详情）
     --[点 部队实力 提升 (605,653)]--> HOME，盾兵营(12级) 被聚焦，浮出 详情/立即完成/加速/训练
     --[点 训练 (526,874)]--> TRAINING（训练中 216位百战盾兵）
```

`key/` 里是这条路线的每一态（`01`→`06`），加上按门禁分组的帧与两个反向证据。

**真机 episode（`run_live.py --goal TRAIN`，exit 0，共 5 步）**：

```
1 OPEN_POWER_OVERVIEW    HOME -> POPUP/POWER_OVERVIEW       verifier OK
2 OPEN_POWER_DETAILS     POPUP/POWER_OVERVIEW -> POWER_DETAILS verifier OK
3 NAVIGATE_INFANTRY_CAMP POPUP/POWER_DETAILS -> HOME(menu_open) verifier OK
4 OPEN_INFANTRY_TRAINING HOME(menu_open) -> TRAINING         verifier OK
5 SAFE_STOP              training_queue_busy
```

## 顺手修掉的缺陷，以及一处**被我自己写错的因果**

### 0. ⚠ 更正：第一跳（战力入口）**从来没坏**

第一次量这条路线时我用的是 `BTN_OPEN_POWER_OVERVIEW`，它 MISS ⇒ 我写下"入口是值依赖模板、
必须重裁"。**这个结论是错的**：`skills.py` 点的是**另一个语义**
`BTN_OPEN_POWER_OVERVIEW_ICON`，它**早就存在**、而且**今天就能命中**：

| 语义 | 今天城市帧 | 09-08 另一账号 | 门禁 |
|---|---:|---:|---:|
| `BTN_OPEN_POWER_OVERVIEW`（宽裁剪，含战力数字；**没有任何动作点它**） | 28 | — | 8 |
| `BTN_OPEN_POWER_OVERVIEW_ICON`（55×40 只裁图标；**技能实际点它**） | **4** | **10** | 12 |

⇒ **"只裁图标、避开会变的数字"这件事早就有人做过了**，只是换了名字。
本轮为 `BTN_OPEN_POWER_OVERVIEW` 加的那条记录因此是**死重**（没有动作引用该语义），
**已删除**；改为由 `test_the_power_entry_resolves_on_both_accounts` 把这个事实钉住。
⇒ **教训：判定一个控件"坏了"之前，先找到动作真正指向的那个语义名。**

**真正的断点是四跳里的三个**（今天帧全部 MISS）：`POPUP_POWER_OVERVIEW`、
`BTN_OPEN_POWER_DETAILS`、`POPUP_POWER_DETAILS`、`BTN_POWER_TROOP_IMPROVE`，
加上兵营菜单的门禁。第一跳本来就是通的。

### 1. 兵营聚焦浮层是**动画**，而旧裁剪只命中一次运行里的 3/7 帧

聚焦后盾兵营周围浮出 `详情 / 立即完成(1,039钻) / 加速 / 训练`，
其中**训练按钮上有引导手指动画 + 呼吸光圈**。旧裁剪的距离在一次运行里
从 `d=4` 跳到 `16`（另 3 帧直接 MISS）⇒ `NAVIGATE_INFANTRY_CAMP` 的 verifier
**连刷两次、烧掉约 21 秒**（07:41:18 → 07:41:29 → 07:41:39）才通过，
而浮层寿命只有约 2 秒 ⇒ 下一步观测时它已经消失 ⇒ **整条路线被迫重走一遍**
（第一次运行 7 步，其中步骤 1–3 重复了一次）。

新裁剪是以训练按钮为圆心的 300×300 区块（因为**点击落点就是该记录 ROI 的中心**，
而执行器只支持 `TAP_SEMANTIC`，没有绝对坐标动作）。一次运行 7 帧全部 0–8。
verifier 因此**第一次观测就通过**，路线收敛为 **4 步**。

`tools/probe_camp_menu_gate.py` 在**全部 3522 帧**语料上量了两个总体：

| 阈值 | 命中帧 | 说明 |
|---:|---:|---|
| ≤8 | 17 | 今天的运行帧 + 09-09 导航会话帧 |
| ≤12 | 22 | 同上 + 09-08 导航会话帧（**抽查 OCR：每帧都有 盾兵营/详情/训练**） |
| ≤17 | 36 | 同上，但 **plain HOME 帧也进来了（d=16）** |

⇒ 门禁从 17 **收紧到 12**（这是"两个总体之间的分界"，不是为了让某个候选通过）。
09-08 的兵营菜单帧（新裁剪 d=18）**靠它自己的旧记录 d=0 仍然命中**，所以不丢召回。

## 三个必须知道的事实

### A. 建筑（BUILD）入口找到了，但**今天没落地**

`建筑实力 提升`(605,550) 会把 **民居1（3级）** 聚焦，并开出它的家具面板与
`升级` 按钮（费用 **157.7万** 肉，而账号当时只有 **16.6万** ⇒ 按钮为禁用态）。
帧见 `key/04_building_focused.png`。

**但这条没有落地，因为视觉还不认识这个面板**（`page=UNKNOWN`、`building={}`），
而 `vision.py` 里既有的 `BTN_BUILD_UPGRADE` 分支**把建筑身份写死**成
`{"id": "STOREHOUSE", "level": 26, "target_level": 27}` —— 一旦注册就该按钮，
它会为**任何**被聚焦的建筑**编造**这套值，而 `verify_building_upgrade` 正是按
`before.building` 的 id/level 判定的。所以落地 BUILD 前必须先让建筑身份**从画面读**。
已立为未决问题。测试 `TheBuildingPanelIsStillUnrecognisedTests` 把这个缺口钉住。

### B. 情报：**两次运行都真的拿到了价值**，却都倒在同一处弹窗识别上

**第一次** `--goal INTEL`：

```
1 OPEN_MAP            HOME -> MAP                     verifier OK
2 OPEN_INTEL          MAP -> INTEL (claimable=1)      verifier OK
3 INTEL_CLAIM_REWARDS INTEL -> POPUP                  verifier OK ← 真的领到一份奖励
4 DISMISS_DAILY_REWARD -> INTEL                       verifier FALSE
      DAILY_REWARD_ADVANCE_NOT_PROVEN   (exit 2)
```

**第二次**（补跑，离开第一页情报后）：

```
1 SELECT_INTEL_PIN        INTEL -> POPUP(野兽任务卡)   verifier OK
2 OPEN_INTEL_BEAST_TARGET POPUP -> BEAST              verifier OK
3 INTEL_BEAST_START_MARCH BEAST -> MARCH              verifier OK
4 DISPATCH_INTEL_BEAST    MARCH -> MAP                verifier OK ← 真派出一队（体力 237→227）
5 OPEN_INTEL              MAP -> INTEL                verifier OK
6 INTEL_CLAIM_REWARDS     INTEL -> POPUP              verifier OK ← 又领到一份（未试 pin 6→5）
7 DISMISS_DAILY_REWARD    -> INTEL                    verifier FALSE
      DAILY_REWARD_ADVANCE_NOT_PROVEN   (exit 2)
```

⇒ **6 步真机动作、2 份奖励、1 次真派兵**；只有解除那一步判错。**缺陷已复现两次。**

**根因（已量，不是"阈值没调好"）**：情报奖励反馈用的是客户端的**通用「获得奖励」弹窗**。
`POPUP_DAILY_REWARD_CURRENT` 这条记录的 ROI 是 `x 0.08 y 0.2 w 0.84 h 0.4` ——
**整个奖励格区域**，它对**任何**来源的奖励弹窗都命中：

| 帧 | `POPUP_DAILY_REWARD_CURRENT` | `POPUP_GENERIC_REWARD_HEADER` | 奖励标题模板 |
|---|---:|---:|---|
| `key/11_intel_reward_popup.png`（第一次） | **6** | 12 | 都不命中 |
| `key/13_intel_reward_popup_run2.png`（第二次） | **2** | 16 | 都不命中 |

而 `vision.py` 第 1046 行把它**排在通用表头之前** ⇒ 距离更小 ⇒ 页面被报成 `DAILY_REWARD`
⇒ 大脑跑了**每日**的解除技能，其 verifier 期待"进入每日页"而实际回到情报页 ⇒ 失败。

⇒ **这条裁剪在结构上无法区分来源**（它不是"太松"，而是"问错了问题"）。
修法方向：**来源只能由目标上下文决定，不能由奖励格决定** ——
大脑里**已经**有这条分支（brain.py 221–232：`GENERIC_REWARD` + `current_goal=="INTEL"`
→ `DISMISS_INTEL_GENERIC_REWARD`）。但**改之前必须先量"真每日奖励弹窗"那一侧**：
若它也走通用路径，则 `goal=None` 时会不会落到 `SAFE_STOP generic_reward_without_goal_context`
而把奖励晾着 —— 这是本轮的证据**不足以**回答的问题（手边没有一张真每日奖励弹窗帧）。
⇒ 记入问题 #22，**不靠调阈值修**。

### C. TRAIN 运行结束后客户端**停在训练页**

下一次运行若换 goal，会撞 `goal_page_mismatch` → SAFE_STOP 立刻结束
（本轮就发生过一次：`--goal INTEL` 第一次跑停在步骤 1）。
与上一轮每日面板的"死胡同"同类，但这次是**运行结束时**没把客户端放回 HOME。
已立为未决问题。

## 帧清单（`key/`，已白名单进公开仓库）

| 文件 | 是什么 |
|---|---|
| `01_home_plain.png` | 普通城市帧：`training={}`，也是兵营门禁的**反向**证据（d=16） |
| `02_power_overview_panel.png` | 加成总览面板（`实力详情` 按钮在此帧） |
| `03_power_details_panel.png` | 实力详情面板（部队实力 `提升` 在此帧） |
| `04_building_focused.png` | 民居1 家具面板 + `升级`（BUILD 入口，未落地） |
| `05_camp_focused.png` | 盾兵营被聚焦，浮出四按钮 |
| `06_training_page.png` | 训练页（`训练中 216位百战盾兵`） |
| `07/08/09/10_camp_focus_*.png` | 一次运行里对同一浮层的四次观测（d=4/8/0/4）——门禁的**正向**总体 |
| `11_intel_reward_popup.png` | 通用「获得奖励」弹窗（情报奖励，被误读为 DAILY_REWARD） |
| `12_old_account_home_20260908.png` | 09-08 另一账号的 HUD（战力 5,708万）——值无关性的证据 |

本目录另有约 19 帧探针原始输出（每态重复、返回前后帧等，约 17 MB），
**按规则 8 留本地**、被 `.gitignore` 忽略；它们仍在磁盘上可查。

⚠ 探针 JSON（`probe_*.json`）里记的帧路径是**移动进 `key/` 之前**的原始路径，
`key/` 下那 12 帧已不在原处；JSON 保留的是**探针自限条件的记录**（它点了哪、允许从什么页出发），
这一点与帧放在哪里无关。
