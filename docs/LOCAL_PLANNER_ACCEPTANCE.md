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


---

## 6. 补遗（同日，修完两处后复验）

### 6.1 两处由"跑"发现的缺陷

**（a）`run()` 里抛 `NameError` —— 注入参数其实没接上。**
第一版把 `advisor=None` 加进了 `__init__`，却在 `run()` 里写 `self._advisor = advisor or ...`。
`self._advisor` 是在 **`run()`** 里创建的（run-scoped，因为 advisor 带 `max_steps_per_run`），
`run()` 里没有那个参数名 → **每一次运行都 `NameError`**。
`tools/check_wiring.py` 看不到（它从不调用 `run`），
`tests/test_refusal_yields_the_cycle.py` 看到了：13 个失败。
现在的形状：`__init__` 只存 `self._advisor_factory`，`run()` 里
`factory = self._advisor_factory` → `callable` 则调用（每次运行拿到新的、预算干净的 advisor），
否则用实例，都没有则用原来的答案文件 reader。`tools/run_live.py` 因此传的是**工厂**。
修完：同一组测试 13 失败 → **2 失败**，且这 2 个用 HEAD 版 `skills.py` 复现确认是**既有**的
（失败信息里直接点名 `LEAVE_FOREIGN_LAYER`，来自工作树里既有的未提交改动）。

**（b）`COMPLETE` 被误用成 `DEFER`。**
真机上 client 停在 INTEL 页而 goal 是 DAILY_ROUTINE、页面上没有相关控件时，模型答 `COMPLETE`。
安全上没出事（`COMPLETE` 只落一条 `COMPLETE_CLAIM / verified=false`，不点任何东西），
但**分类错了**。prompt 的 §5 因此写清：`COMPLETE` 只在"目标自己的结果就在屏上"时用，
"这屏不属于这个 goal"要答 `DEFER`。复验（离线 MAP + 真机 INTEL 各一次）**两次都答 DEFER**。

### 6.2 §10 场景 D 的实测证据

```
page : INTEL  goal : DAILY_ROUTINE  elements : 4
plan : {"decision":"DEFER","reason":"The current screen is the Intel page, which does not contain
        controls for daily routine tasks; the scheduler needs to switch to the correct page."}
结果为：没有任何点击，没有虚构按钮，占用槽位不消耗。
```

### 6.3 回归范围（本轮实测）

| 测试文件 | 结果 |
| --- | --- |
| `test_local_planner.py` / `test_qwen_decoupling.py` | 全绿 |
| `test_unknown_ai_channel.py` | 42 passed |
| `test_refusal_yields_the_cycle.py` | 2 失败，**均为既有** |
| `test_control_panel.py` | 2 失败，**均为既有** |
| `test_unknown_advisor.py` / `test_gateway_service.py` | 全绿 |
| `tools/check_wiring.py` | `problems: 8`，与开工前完全相同 |
---

## 7. 元素身份、图标+标签控件，与判据的真实标定（2026-09-25 第二轮）

### 7.1 做了什么

`ui_collection` 新增元素身份（宪法 B §25.1）与图标+标签控件：

| 身份 | 含义 | 可作为 CLICK 目标 |
| --- | --- | --- |
| `TEXT_LABEL` | 客户端印的字（城镇名、资源数、说明） | **否** |
| `ICON` | 无字图形 | — |
| `INTERACTIVE_CONTROL` | 自带文字的画出来的控件（领取按钮） | 是 |
| `COMPOSITE_CONTROL` | 图标 + 其下方标签，**一个语义 ID、一个真实可点区域** | 是 |

- `build_element_table()`：**一帧只建一次表**，规划器从这个表选 `id`，执行器从**同一个表**解析 `id` —— "模型与执行器同帧同表"是代码性质而不是希望。
- 表内**复合控件排在最前**，所以按标签文字 ground 的答案会落到**控件的区域**而不是标签框。这就是 `SEMANTIC_TARGET_IS_A_LABEL_NOT_A_CONTROL` 的修复点。
- `ui_planner.parse_plan` 新增拒绝：命名 `executable=false` 的元素 → `PLAN_TARGET_IS_NOT_A_CONTROL`（§2 的硬要求）。
- 注册表 `knowledge/ui/icon_label_controls.json` 只存**身份 + 关系 + 裁片**，不存点击坐标；点击位置永远来自当前帧匹配（宪法 A §24.2/§24.4，§24.3 允许有界搜索区）。

### 7.2 两条判据的实测：一条被否定，一条通过

**（a）几何判据 —— 被自己的标定否定。**
`dataset/truth_audit/icon_label_controls/samples.json`：从生产帧挖出 **136 个正样本**（登录好礼/常规活动/超值活动/明月的盛典）与 **1832 个负样本**（同帧的其他印字）。

```
$ python tools/calibrate_icon_label_gate.py
positives: 50/136 accepted = 36.76%   (want high)
negatives: 722/1832 accepted = 39.41% (want low)
```

**正负样本完全不可分。** 更早的两版判据同样被否定并留下了原因：饱和度判据在自己的正样本上失败（`登录好礼` 是蓝白日历，`sat_delta≈-0.01`，而红色礼盒 +0.31）；边缘强度判据在正样本上低于旁边的地形（`edge_ratio` 最小 0.16，负样本最大 1.71）。**结论：像素几何不是这个问题的可解判据，因此它没有被接入生产**（`allow_measured_block` 默认 false）。

**（b）注册裁片 + 匹配器 —— 通过。**
这正是本项目文档里一贯的做法（"how is a textless icon located: a registered crop plus a matcher, never a pixel heuristic"）。

```
$ python tools/validate_icon_template.py --label 登录好礼
RECALL  : matched 36/37 = 97.3%
score   : min/median/max = 0.955/0.992/1.000      (阈值 0.7)
specificity: 整帧搜索的最高匹配落在 x=0.731 y=0.097 —— 就是图标本身
```

裁片 `knowledge/ui/icon_templates/登录好礼.png`（56×55）从真实帧 `20260924_101003_761338` 提取，**经过目视确认**（整个日历按钮：蓝色头部含挂环 + 米色主体含棕色 7）。

### 7.3 真机结果

```
page      : HOME (conf 0.98)
anchor '登录好礼' is on this frame -> {'y_norm': 0.0969, 'h_norm': 0.043}   <- 图标框
（修复前同一步:                         {'y_norm': 0.1383, 'h_norm': 0.0203}  = 标签框）
tap       : (554, 152)   ← 修复前 (555, 190)，高了 38 px，落在图标上
executed  : executed=True backend=MAA latency=51.56ms
verifier  : verify_ordinary_control_tried ok=True
page      : HOME -> HOME          <- 仍未变化
```

- `STRUCTURED_OUTPUT_PASS` ✅  `MAA_EXECUTION_PASS` ✅（MAA 真的发了点击）
- `GOAL_VERIFIED` ❌  `SKILL_REUSABLE` ❌

**第一个真实断点已经换了**：不再是"点标签"，而是**解析到执行之间画面变了**。后帧显示 HUD 活动列**会移动**——同一时刻日历图标在前帧 x≈0.73、在后帧 x≈0.64，且镜头被拉近。也就是说：在一帧上测出的位置，到点击落地时可能已经过期，或命中了相邻的另一个入口。

下一步（具体动作）：
1. 解析与执行之间不得插入另一次取帧/等待；`TAP_SEMANTIC` 应在**同一帧**上完成匹配与点击（现在的探针里 settle 1.5 s + 独立截图，间隔正是问题所在）。
2. 或者点击前**再匹配一次**并比对：若匹配位置相对解析时偏移超过阈值，则放弃本次点击并按 `REPLAN` 处理，而不是点击过期位置。
3. HUD 动画需要在多帧上量出位移幅度，再决定阈值（现在只有一帧的证据）。
---

## 8. 更正：HUD 没有移动（2026-09-25 第三轮实测）

上一轮 §7.3 我写了"HUD 活动列会移动，所以位置会过期"。**这个结论是错的**，本轮用同一对前后帧实测否定：

```
before_frame.png: label_x=0.7236 label_y=0.1391
                  icon   = {'x':0.7306,'y':0.0969,'w':0.0778,'h':0.043} score 0.9923
after_frame.png : label_x=0.7236 label_y=0.1391
                  icon   = {'x':0.7306,'y':0.0969,'w':0.0778,'h':0.043} score 0.9921
```

**四次小数完全一致，匹配分也一致。** 上一轮的"x≈0.73 → x≈0.64"来自**另一次不同时刻的截图**（镜头已被拉近的 `navigate_1.png`），被我误当成同一操作的后帧——正是"不能仅凭前后两张截图的位置差异下结论"这条纪律的反面教材。

### 8.1 那么点击到底落在哪里

图标匹配框 = x 0.7306–0.8084 → **526–582 px**，y 0.0969–0.1399 → **124–179 px**。
实际点击 **(554, 152)** —— 正好落在图标框内（框心 554,152）。

**所以坐标是对的，且不是过期的。** 修复后的定位没有问题；"点标签"的缺陷确实被修掉了。点击之后页面没变，原因在别处。

### 8.2 仍然未确定的真实原因（有边界，不猜）

候选（**均未经证实，按 §二 记为 UNKNOWN**）：

1. **点击没有真正到达游戏**：MAA 返回 `executed=True` 只说明输入通道发送成功，不代表客户端收到。
2. **`登录好礼` 入口的可点区域不是这个图标本体**（可能存在更大的透明按钮区域，或需要点红点/徽标）。
3. **存在前置条件**（当日已领取 / 活动未刷新 / 需要特定等级）。
4. **Verifier 与页面模型是假阴性**：`登录好礼` 打开的面板可能没有对应的页面条目，`HOME → HOME` 是**读不出来**而不是没打开。

下一轮必须先用一张"点击后即时帧"与"稳定后帧"对比是不是**完全没发生任何像素变化**（若是，则是 1 或 2；若有变化，则是 4）。本轮没有拿到同操作 ID 的完整帧序列，因此**不下结论**。

### 8.3 本轮新增（已提交）

- `tools/probe_live_operation.py`：单次操作、唯一 op_id、每帧带 UTC 与毫秒时间戳。
  记录链：drift 序列（**完全无输入**下测图标是否自己动）→ plan 帧 → **点击前重新取帧并重新匹配** → MAA 点击（含发送时刻）→ after_0（即时）→ after_1（稳定后）→ 页面状态与 Verifier。
  并且**先申请设备租约再定位与点击**，结束即释放，不长时间占设备。
- 挡停逻辑（§三.3）：点击前重新取帧后，若图标消失 → `RELOCATE_FAILED`；若页面已变 → `PAGE_CHANGED_BEFORE_TAP`；两者都停止点击，不点旧坐标。
- §三.4 已实现：重新定位的结果若与规划时不同但可靠，**使用当前区域执行**，不判为失败。

### 8.4 尚未接入生产

"点击前实时定位"目前在探针里，**尚未接入 `Executor`/`Runtime` 的生产解析路径**（`_resolve_semantic_target` 仍用步骤帧）。
**但本轮证据表明过期坐标不是失败原因**，因此这个接线不会修复当前问题——先查清 §8.2，再决定要不要改生产链（宪法：无证据不改已验证链路）。

### 8.5 当前四级状态（未变）

`STRUCTURED_OUTPUT_PASS` ✅ / `MAA_EXECUTION_PASS` ✅ / `GOAL_VERIFIED` ❌ / `SKILL_REUSABLE` ❌
**无候选 Skill 被保存**（§五：未验证的流程不得写成可用经验）。
