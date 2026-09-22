# 红点作为优先级信号：受控 A/B 回放（2026-09-23）

## 这是什么证据

操作者第二份指令 §二② 要求把红点当作**优先级信号**。本目录记的是这条改动唯一能给出因果的
那种证据：**同一帧、同一份代码，只切红点这一个变量**。

- `before` 侧 = 把该世界的 `red_dots` 清空 —— 这就是改动前的行为，因为改动前没有任何一层
  读 `red_dots` 来排序（`grep` 全包只有 `brain.py:809` 一处消费它，且那处只做"邮件无角标就
  不进邮件页"）。
- `after` 侧 = 保留该帧读到的红点。
- 两侧共用同一个 `GoalLibrary().discover()`、同一个 `rank()`、同样的观测与公平台账（都为空），
  只有 `red_dots` 不同。

复算命令（不需要真机、不需要设备租约）：

```
"E:/无尽冬日智能体/.venv/Scripts/python.exe" -u tools/replay_red_dot_priority.py --frames 6 --negatives 6
```

选帧口径：`learning/episodes.jsonl` 里**自己记录 `page=HOME`** 的 before 帧，按记录里的红点
台账去挑（有红点的当处理组，没有的当对照组）；世界本身由**生产视觉**（`SemanticWorldVision`
+ RapidOCR）从图片重读，不采信记录里的读数。

## 结果

```
frames                                  12
frames_with_a_rankable_dot               8
dotted_frames_where_the_order_changed    8     ← 处理组 8/8
negative_control_frames                  4
negative_control_frames_where...         0     ← 对照组 0/4（必须为 0）
records_that_understated_the_dot         2
```

处理组 8/8 全部换了板首：

| 帧 | 板上读到的红点 | 板首 before → after | 项值 |
|---|---|---|---|
| `..._step_002_before_...T185245` | `BTN_OPEN_MAIL` | `KEEP_TRAINING_PRODUCTIVE` → **`MAIL_ROUTINE`** | 180 (+60) = 240 |
| `..._step_002_before_...T190302` | 面板行 `RESEARCH` | `CLEAR_INTEL` → **`KEEP_RESEARCH_PRODUCTIVE`** | 180 (+60) = 240 |
| `..._step_018_before_...T193104` | 面板行 `RESEARCH` + `SHIELD_CAMP` | `CLEAR_INTEL` → **`KEEP_RESEARCH_PRODUCTIVE`** | 240 / 营房 80 (+60) = 140 |
| （其余 5 帧同上表形态） | | | |

对照组 4/4 一动不动，说明**板序的变化来自红点本身**，不是这个项在别处误触发。

## 边界（这一项刻意做不到的事）

- 处理组 8 帧的板首都是 **180 → 240**：仍然**低于**一次「可领取」(250)。红点只把"客户端正在指
  的那个东西"提到普通日常与其它未读探访之前，**不越过任何真正付钱的目标**（情报 800、巨兽
  1000、体力 2450）——操作者 §二②「红点本身不自动最高优先」落到数字上就是这个 60。
  这个界是**算出来的**：`goal_utility.RED_DOT_BONUS = 60`，见 `tests/test_red_dot_priority.py`
  的 `TheBoundTest`。
- 只有**被量到会消失**的角标才算信号（`entry_badges.dot_varies`）。每日/联盟是 26/26 常在的
  计数角标、英雄是 `SUSPECT_ARTWORK`、面板的矛兵/射手行与联盟捐献/英雄招募/我的奖励行在 12 帧
  里从未读到过 PRESENT 或全为 UNKNOWN ⇒ 它们**不参与排序**，不是"暂时没用"而是"还没有被证明
  是信号"。测量见 `knowledge/ui/entry_badges.json` 的 `dot_variability` 段。
- **没有做**「把红点叫醒的 Goal」：`tools/measure_mail_dot_blind_window.py` 量过这件事——
  1085 个 HOME before-帧里只有 40 帧带邮件行读数（红点层 2026-09-22 才落地），其中 5 PRESENT /
  35 ABSENT，而"读完邮件（说无事）之后 15 分钟 TTL 内红点又出现"这种情况在语料里**一次都没有
  出现过**（唯一一次发生在读数后 1841 分钟）。没有证据支持为此增加一条会重复开页的规则 ⇒ 不做，
  留作开放式风险写进 `04_OPEN_ISSUES.md`。

## 顺带证实的两件事

1. **一个真实的绑定缺陷（已修）**：面板「科技研究」行的红点绑定写的是 `"RESEARCH"` —— 那是
   `run_live.py --goal` 接受的**路由域**，不是 Goal id（`GOAL_ROUTES` 里
   `KEEP_RESEARCH_PRODUCTIVE -> RESEARCH`）。而这一行是面板里最常亮、也是唯一真正有区分度的行
   （12 帧里 9 帧 PRESENT；9 帧里它亮而别的行不亮），所以面板红点信号的大半原本**根本落不到任何
   Goal 上**。生产记录里那些行的 `goal` 字段就是 `"RESEARCH"`。
2. **#98 的修复在数据里可见**：2 个"记录说没有红点"的帧，用今天的代码重读**读到了红点**——旧记录
   是在角标窗口还位于「按钮左三分之一」时写的，修复把它移到了右三分之一（红点实测在 412-420）。
   所以本目录的对照组是**按图片**分组的，不是按记录；`summary` 里的
   `records_that_understated_the_dot = 2` 就是这两帧。

## 证据清单

- `replay.json` —— 上面全部数字的机器可读版本（含每帧的 `board_before` / `board_after` /
  `red_dot_terms` / 记录自身字段）。
- 帧文件本身在 `dataset/raw/control_panel/runtime_auto/`（截图不进 git，见 `.gitignore`）；
  本目录记录的是路径，按路径可复现。
- 判定这一项的后端与价格带：`winter_agent_v2/goal_utility.py`（`RED_DOT_BONUS`）、
  `winter_agent_v2/entry_badges.py`（`dot_varies` / `dots_pointing_at`）、
  `tests/test_red_dot_priority.py`（23 项）。
