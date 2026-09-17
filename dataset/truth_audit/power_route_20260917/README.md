# power_route_20260917 — 战力路线：训练与建筑共同卡住的那一段

## 为什么这些帧存在

2026-09-17 操作者要求「建筑和训练优先落地，情报记得及时做」。

两者**卡在同一处**，而且**不是推理问题**：

- `brain.py` 早已接好整条链（第 243–246 行、446–456 行）；
- `LiveRuntime.VERIFIED_ATOMIC` 早已绑好每一跳的 verifier；
- `run_live.py --goal` 早已接受 `TRAIN`。

**唯一断点是模板。** 今天真机 HOME 帧上实测，路线需要的语义**全部 MISS**：

```
BTN_OPEN_POWER_OVERVIEW            MISS
TARGET_INFANTRY_CAMP_HIGHLIGHTED   MISS
BTN_OPEN_TRAINING_FROM_CAMP        MISS
PAGE_TRAINING_INFANTRY             MISS
BTN_START_TRAINING                 MISS
```

原因：这些模板全部裁自 **2026-09-08 的另一个账号**（战力 57,083,909 对今天的
826,444、不同头像、**城市镜头拉得更远**，能看到今天客户端根本不显示的楼）。
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

## 顺手修掉的两个缺陷（都属于「同一控件有多种外观」这一类）

### 1. 战力入口是**值依赖模板**

旧 `BTN_OPEN_POWER_OVERVIEW` 的裁剪 `x 97..302` **把战力数字裁了进去**，
所以它只能匹配裁它时那个账号。实测：

| 裁剪 | 今天(826,444) ↔ 09-08(57,083,909) | 非城市帧 |
|---|---:|---:|
| 旧宽裁剪（含数字） | **28** | — |
| **只裁拳头图标（采用）** | **2**（dhash 0） | **30** |

一个图标记录同时覆盖两个账号 —— 见 `test_the_power_entry_is_the_same_control_on_both_accounts`。

### 2. 兵营聚焦浮层是**动画**，而旧裁剪只命中一次运行里的 3/7 帧

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

### B. 情报：领到了奖励，却在**弹窗识别**上失败（独立缺陷）

`--goal INTEL` 实跑：

```
1 OPEN_MAP            HOME -> MAP                     verifier OK
2 OPEN_INTEL          MAP -> INTEL (claimable=1)      verifier OK
3 INTEL_CLAIM_REWARDS INTEL -> POPUP                  verifier OK ← 真的领到一份奖励
4 DISMISS_DAILY_REWARD -> INTEL                       verifier FALSE
      DAILY_REWARD_ADVANCE_NOT_PROVEN   (exit 2)
```

情报奖励反馈用的是客户端的**通用「获得奖励」弹窗**（五格奖励 + 点击任意位置退出，
见 `key/11_intel_reward_popup.png`）。该帧上**唯一**命中的是
`POPUP_GENERIC_REWARD_HEADER`(d=12)，而 daily/intel 的奖励标题模板都不命中；
但 `vision.py` 第 1046 行的 `POPUP_DAILY_REWARD_CURRENT` 排在前面对它假阳性，
于是页面被报成 `DAILY_REWARD`、跑了**每日**的解除技能，其 verifier 期待"进入每日页"
而实际回到了情报页 ⇒ 失败。

大脑里**已经有**正确的 goal 上下文分支（`GENERIC_REWARD` + `current_goal=="INTEL"`
→ `DISMISS_INTEL_GENERIC_REWARD`，brain.py 221–232 行），所以修法在视觉的判定顺序
或那条 daily 记录上，**需要先量出两个总体**（真每日奖励 vs 通用奖励）。
测试 `TheIntelRewardPopupIsMisreadTests` 把这个测量钉住。

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
