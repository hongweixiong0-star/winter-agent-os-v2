# 本地 Qwen 结构化 UI 动作 — 验收记录（2026-09-25）

四个验收级别是**分别取得的**，不能互相代替。本文件记录每一级当前的**真实**证据，以及仍然
没有取得的那一级卡在哪里。

| 级别 | 含义 | 当前状态 |
| --- | --- | --- |
| `STRUCTURED_OUTPUT_PASS` | 模型真实输出符合结构化协议 | **已取得** |
| `MAA_EXECUTION_PASS` | MAA 在真机上定位并执行了对应动作 | **已取得** |
| `GOAL_VERIFIED` | 实际任务目标已完成（项目自己的 verifier 确认） | **未取得** |
| `SKILL_REUSABLE` | 成功流程已通过验证并可复用 | **未取得**（依赖上一级） |

---

## 1. STRUCTURED_OUTPUT_PASS — 已取得

```
$ .venv/Scripts/python.exe tools/probe_local_planner.py --trials 2
model    : qwen3635bagent-q3:latest
endpoint : http://127.0.0.1:11434
trial 1: ok=True latency=40429ms reply=299c
  PLAN : decision=EXECUTE action=CLICK_ELEMENT element=E1 text='领取'
trial 2: ok=True latency=3278ms  reply=299c
  PLAN : decision=EXECUTE action=CLICK_ELEMENT element=E1 text='领取'
STRUCTURED_OUTPUT_PASS: 2/2
```

要点：

- 真实模型（本机 Ollama，35.5B MoE，`num_ctx=8192`，`format=json`，`think=false` 被接受）；
- 首次 40 s（模型装载），预热后 3.3 s；
- goal=DAILY_ROUTINE 的屏幕上同时摆了 `领取` 与 `钻石`，模型选了 `领取` —— prompt 的
  §7 消耗禁令生效，没有去碰钻石；
- 回复里没有任何坐标；`ui_planner.FORBIDDEN_KEYS` 会递归拒绝带几何信息的回复（有单测钉住）。

## 2. MAA_EXECUTION_PASS — 已取得（真机）

```
$ .venv/Scripts/python.exe tools/probe_planner_live.py --goal DAILY_ROUTINE --execute
device     : connected=True resolution=(720, 1280) foreground=com.gof.china
frame      : dataset/truth_audit/local_planner_live/before_frame.png (capture=MAA_MUMU_EXTRAS)
page       : MAP confidence=0.99
elements   : 40 region(s) / 40 text(s) on this frame
plan       : {"decision":"EXECUTE","action_type":"CLICK_ELEMENT",
              "target_element_id":"E9","target_text":"登录好礼"}
[advisor] map__control__4cf644d7: the answer's anchor '登录好礼' is on this frame
          -> {'x_norm':0.7222,'y_norm':0.1383,'w_norm':0.0972,'h_norm':0.0203}
resolved   : 'AI_ADVICE[登录好礼]' at 0.7708,0.1484 basis=AI_ADVICE/ANCHORED_TO_TEXT
executed   : executed=True backend=MAA error=None tap=(555, 190) latency=51.34ms
verifier   : verify_ordinary_control_tried ok=True
page       : MAP -> MAP
```

**这条链是真的**：真实帧 → 本项目自己的 OCR 得到 40 个元素 → 本地模型选出 `E9 登录好礼`
（DAILY_ROUTINE 下的正确语义：登录好礼是免费日常入口）→ 本项目已有的 `grounded_region`
在**同一帧**上把该元素自己的 OCR 框解成坐标（0.7708, 0.1484）→ MAA 实际点击 (555, 190)，
51 ms → 项目自己的 verifier `verify_ordinary_control_tried` 返回 ok。

坐标**没有**经过模型：模型只见 `id / text / area`，见
`ui_planner.build_packet` 与 `tests/test_local_planner.py::test_the_packet_shows_no_coordinates_at_all`。

## 3. GOAL_VERIFIED — 未取得，第一个真实断点在这里

`page: MAP -> MAP`：点击落地了，**游戏状态没有变化**。

根因已用同一帧的证据确证，且**不是规划器的问题**：

```
grounding_regions: 40
  GROUND '登录好礼' {'x_norm': 0.7222, 'y_norm': 0.1383, 'w_norm': 0.0972, 'h_norm': 0.0203}
interactive_controls: 8      # 没有一个匹配 登录/探险/常规活动
```

`登录好礼` 是图标**下方的文字标签**（y 0.1383–0.1586 ≈ 177–203 px），可点的图标在它上方
（约 y 95–140 px）。点击落在 y=190，即标签本身，因此没有触发按钮。
`ui_collection.interactive_controls` 也覆盖不到这类 HUD 活动图标（整帧只有 8 个，均不匹配）。

**这是一次 UI 元素定位问题，不是模型问题、不是 MAA 问题、不是执行链问题。**
模型在 40 个元素里选对了语义；是"被识别的元素"（文字）不是"可点的控件"。

### 精确的失败分类

```
FAILURE_TYPE : SEMANTIC_TARGET_IS_A_LABEL_NOT_A_CONTROL
PAGE         : MAP
ELEMENT      : '登录好礼' (icon + label; the label box was used as the target)
ACTION       : CLICK_ELEMENT -> TAP_SEMANTIC -> MAA tap (555,190)
RESULT       : executed=true, verifier ok, page unchanged (MAP -> MAP)
```

### 下一步（给下一个会话的具体动作，不是泛泛的"改进定位"）

宪法 §25 已经把这类问题定义清楚了：**UI 元素的识别范围取决于当前任务**，且状态必须由元素
**及其关系**得出。要修的是元素表本身，而不是在点击处补一个偏移：

1. 触发条件：`grounding_regions` 给出的文本框，其**上方**在有限距离内存在高对比度图标块。
   这是"图标 + 标签"控件，盒子应由两者合成。
2. 落点：`ui_collection.interactive_controls` 已经实现了"从自己的盒子与措辞判断是否像可交互
   控件"这一逻辑，但当前只覆盖 8 个；应先把 HUD 活动图标这一类补进去，而不是在 `_advised_control`
   里写偏移。
3. 证据要求：`dataset/truth_audit/local_planner_live/before_frame.png` 是一张真实的失败帧，
   必须以它作为 Positive 样本、以上下相邻的纯标签（如地图上的城镇名）作为 Negative 样本，
   记录命中/误报，再决定是否接入。
4. **禁止**：点击处 + 固定偏移、把标签框按比例放大、按历史坐标兜底 —— 宪法 A §二 的四条硬禁止。

修好之后再跑同一条命令；`GOAL_VERIFIED` 需要 page 或该目标的状态真的变化，并由项目自己的
verifier 判定，而不是由本探针宣布。

## 4. SKILL_REUSABLE — 未取得

依赖第 3 级。沉淀路径已就位（`ui_collection.UiCandidateStore.stage` →
`dataset/candidate/template_manifest.json`，以及 skill lifecycle 的
`DEFINED → CANDIDATE → LIVE_TRIED → LIVE_VERIFIED`），但**不把未经验证的模型推测存成 Skill**：
只要 `GOAL_VERIFIED` 还没取得，就不写 Candidate。

## 5. 复现命令

```bash
PY=.venv/Scripts/python.exe
$PY tools/probe_local_planner.py --trials 2              # 1 级
$PY tools/probe_planner_live.py --goal DAILY_ROUTINE     # 1 级 + 当前帧定位
$PY tools/probe_planner_live.py --goal DAILY_ROUTINE --execute   # + MAA 执行 + verifier
```

每次规划步骤都会落盘：`learning/local_planner_steps.jsonl`（decision / action / element /
reason，含全部拒绝原因），模型调用与延迟落 `learning/local_qwen_calls.jsonl`。
