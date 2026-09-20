# 「点击任意位置退出」奖励弹窗：落点证据（2026-09-20）

对应 `04_OPEN_ISSUES.md` **#64**。本目录只回答一个问题：
**这张弹窗到底该点哪儿**——以及为什么先前点的地方点了等于没点。

## 一、证据帧

| 文件 | 来源 | 说明 |
|---|---|---|
| `key/01_shared_reward_popup_step_001_before_20260920T124146.png` | `dataset/raw/control_panel/runtime_auto/20260920_204143_843357/…_step_001_before_20260920T124146365715.png` | 患者帧（720x1280）。弹窗：横幅「获得奖励」+ 三格奖励 + 页脚「点击任意位置退出」。**复制到本目录**是为了让测试不依赖会被 retention 清理的运行帧（#46）；放进 `key/` 并按 `.gitignore` 白名单发布，理由同 `march_formation_20260918`。 |

## 二、在这张帧上量的原始距离（`SemanticROIVision`，闸门无关）

用项目自身的 `image_hash.phash/hamming`，ROI 取自 `dataset/candidate/template_manifest.json`：

| 语义 | 原始距离 | 自身闸门 | 判定 | ROI（归一化） | 中心（设备像素） |
|---|---:|---:|---|---|---|
| `POPUP_GENERIC_REWARD_HEADER`（横幅/标题） | 16 | 16 | **恰好卡门** | x .14 y .21 w .72 h .09 | (360, 326) |
| `BTN_DISMISS_INTEL_REWARD`（页脚退出带） | **2** | 8 | PASS | x .36 y .90 w .28 h .07 | **(360, 1197)** |
| `BTN_CLOSE`（= `CLOSE_POPUP` 的目标） | 28 | 8 | **NO MATCH** | x .807 y .079 w .09 h .073 | (613, 148) |
| `POPUP_INTEL_REWARD` | 28 | 8 | NO MATCH | x .085 y .205 w .83 h .41 | — |
| `POPUP_DAILY_REWARD_CURRENT` | 24 | 8 | NO MATCH | x .08 y .20 w .84 h .40 | — |
| `POPUP_EXPLORATION_REWARD` | 28 | 8 | NO MATCH | x .08 y .20 w .84 h .40 | — |

两个可直接读出的结论：

1. **横幅「恰好卡门」**（16 对 16）。按项目已立的判据（#54：跨帧距离应落在阈值空档内，而不是擦边），
   卡门说明**是容差在干活、不是裁剪在干活**。它作为**识别**信号仍可用（`vision.py` 用它 + 页脚报
   `GENERIC_REWARD`），但它**不是可点的表面**——它就是弹窗的标题，点它没有任何效果。
2. **`CLOSE_POPUP` 在这张弹窗上必然失败**（28 ≫ 6，且它的 ROI 在右上空白）。#64 之前给
   `TRAIN`/`RESEARCH` 用 `CLOSE_POPUP` 兜底，等于发一个永远解析不出目标的点击。

## 三、真机 episode 证明"点了等于没点"

`learning/episodes.jsonl`，2026-09-20 那一轮（21:04 本地 / 13:04Z 起）：

```
step 21  DISMISS_INTEL_GENERIC_REWARD  reason=intel_goal_generic_reward_feedback
  execution.action.target = POPUP_GENERIC_REWARD_HEADER     ← 横幅
  execution.tap_point     = [360, 326]                      ← 与上表横幅中心一致
  execution.backend       = ADB                             ← 真的发出去了
  after.page              = UNKNOWN
  verification            = FAILURE  INTEL_REWARD_DISMISS_NOT_PROVEN
stop_reason = INTEL_REWARD_DISMISS_NOT_PROVEN
```

⇒ 目标**解析成功**、点击**真的发射**（所以不是 `SEMANTIC_TARGET_NOT_VERIFIED`），
但**点的是标题**，弹窗没关。这解释了 20:38–20:53 那 5 轮"只做一个动作然后失败"全部是
`DISMISS_*_GENERIC_REWARD:FAILURE`。

同一轮的 deferrals 显示这条失效**不只挡一个目标**，它把四个目标一起拖成 `NO_GOAL_PROGRESS`：

```
CLEAR_INTEL            READ_INTEL_LIST     … | DISMISS_INTEL_GENERIC_REWARD      streak 5
MAIL_ROUTINE           OPEN_MAIL_PAGE      … | DISMISS_MAIL_GENERIC_REWARD       streak 3
DAILY_ACTIVITY_TARGET  READ_DAILY_PROGRESS … | DISMISS_DAILY_GENERIC_REWARD      streak 3
ALLIANCE_ROUTINE       OPEN_ALLIANCE_PAGE  … | DISMISS_ALLIANCE_GENERIC_REWARD   streak 5
```

## 四、修法

1. **改"点哪儿"**：五个 `DISMISS_*_GENERIC_REWARD` 与新增的 goal 中立技能
   `DISMISS_SHARED_REWARD` 全部改点页脚退出带（`SHARED_REWARD_EXIT = BTN_DISMISS_INTEL_REWARD`）。
   执行器对 `TAP_SEMANTIC` 走 `SemanticWorldVision.find(...).center_norm`（`runtime.py:1098`），
   所以落点由技能点名的记录决定 ⇒ 新落点 **(360, 1197)**，正是弹窗自称的退出方式。
2. **改决策兜底**：`brain.py` 里"goal 说不清页面的情况"由 `SAFE_STOP` 改为
   `DISMISS_SHARED_REWARD`。理由：关掉一个**自称**「点击任意位置退出」的弹窗不是猜，
   是它自己声明的退出方式。
3. 守卫同步：`tools/check_wiring.py` 三条 + `tests/test_reward_popup_source.py` +
   `tests/test_generic_reward_covers_the_new_goals.py`。

**未做（不许当已完成）**：本目录不含任何"关掉之后客户端确实回到原页面"的帧——那需要真机复验。
本目录只证明**落点该在哪、以及旧落点为什么无效**。

复现命令：

```bash
"E:/无尽冬日智能体/.venv/Scripts/python.exe" .probe_popup_landing.py
```
