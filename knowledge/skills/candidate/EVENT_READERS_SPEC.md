# EVENT_READERS_SPEC.md — EVENT 读取族 5 份读取器规格（草案 v1，r211）

> 依据：r209-r210 实机素材（`dataset/exploration/` + `VALIDATION_PLANS.md` 批 3 节）。
> 目的：把"素材"固化成**读取器规格**（字段/来源/样例/校验/接线落点），作为 vision/OCR 层
> 接线的输入。**本规格不触发生产代码变更**；接线走既有 `vision.py`/OCR 层，禁止第二套读取系统。

## 通用原则

1. **只读**：五读取器全部 OBSERVE 类，零点击；被读取的帧从当前实时帧来（不读缓存）。
2. **动态性**：活动列表与卡片内容**会轮换/重排**（r210 实测：雪原商路从内容区移入页签行）
   ⇒ **任何列表/位置不得跨帧复用**；每次从现帧识别。
3. **置信策略**：数值类（进度/倒计时/档次）必须**两读数递进或与视觉高亮交叉**；单帧不确定记 `UNKNOWN`。

## 1. READ_EVENT_LIST

| 项 | 规格 |
|---|---|
| 字段 | `events[]`（页签行卡名列表）· `active_event`（当前翻开的活动名） |
| 来源元素 | EVENT 页页签行（"常规活动"右侧的卡名）+ 内容区标题 |
| 样例 | 页签：`联盟大作战 / 雪原商路 / 凛风攻城战`（**实测会变**） |
| 校验 | 每次读取现帧；条数 ≥1；`active_event` 须同时出现在内容区标题 |
| 接线落点 | vision.py 页面元素识别（文字层）——同 EVENT 页既有读取模式 |

## 2. READ_EVENT_RULES

| 项 | 规格 |
|---|---|
| 字段 | `tasks[]`（每条：描述文本 + 积分值） |
| 来源元素 | 卡内容区的"任务表"区 |
| 样例 | `护送1次任意品质商旅 10,000点积分` · `拦截1次任意品质商旅 10,000点积分` · `领主装备最高评分提升1点（不包含领主宝石） 22点积分` |
| 校验 | ≥1 条；每条含"积分"与数值；括号注释（"(不包含领主宝石)"）属描述本体，须原样保留 |
| 备注 | 任务表可能滚动 ⇒ 读取"可见条数"并如实记录（不虚构不可见项） |

## 3. READ_EVENT_PROGRESS

| 项 | 规格 |
|---|---|
| 字段 | `my_score`（整数） |
| 来源元素 | `我的积分：<N>` 行 |
| 校验 | OCR 后对 N 做整数解析；与 REWARD_TIERS 的"已达档位"交叉（N 落入的档位与高亮一致） |
| 备注 | `我的积分：0` 为合法读数（0 不是"读失败"） |

## 4. READ_EVENT_REWARD_TIERS

| 项 | 规格 |
|---|---|
| 字段 | `tiers[]`（数值序列）· `claimable_index`（若有领取态标记） |
| 来源元素 | 卡内容区的档次数值序列 |
| 样例 | `100 / 37,500 / 75,000 / 125,000 / 187,500` |
| 校验 | 序列**单调递增**；末档与卡内"大奖励"图标相邻（视觉交叉） |
| 备注 | 领取动作**不在本读取器**（CLAIM_EVENT_TIER 计划另管） |

## 5. READ_EVENT_TIMER

| 项 | 规格 |
|---|---|
| 字段 | `phase_name`（如"侦察阶段"）· `remaining`（HH:MM:SS；游戏内时基） |
| 来源元素 | 卡内容区：阶段名与倒计时（实测同行呈现：`侦察阶段 13:27:18`） |
| 校验 | 两次读数**递进一致**（Δt 与读数差吻合）；phase_name 属已知阶段名集合（新名记 `UNKNOWN` 并入知识） |
| 备注 | **时间不可靠时保留 UNKNOWN**（宪法）；绝不用本读数反推"活动开始时间"以外推 |

---

**接线序（下批候选）**：以 1（LIST）为最易（纯文字行）；3/4 次之（数字解析）；5 依赖阶段名集合；
2 视滚动需求最后。接线提交前跑 `tools/invariant_review.py` 与相关测试（不新开闸门）。

---

# 接线评估（r212）：与 `READ_EVENT_CALENDAR` 的关系及最小接线序

## 现状核对（读源码所得，非推测）

- **V2 已有**：`READ_EVENT_CALENDAR`（skills.py:312，**已注册 CANDIDATE**；`Action("OBSERVE","EVENT_CALENDAR")`
  ；verifier=`EVENT_CALENDAR_READ` **已绑** runtime.py:545）——它读的是**日历总览面**：
  `events["calendar"] = {recognized, visible_dates_raw[≥2], entries[]}`（verifier.py:1995 判据）。
- **5 份 READ_EVENT_*** 读的是**活动卡面**（规则/进度/档/时间）——**与 calendar 不同面，互补不重复**。
- `skill_factory.py:60-64` 已存 5 份的 **prior 模板**（供生成/对照；未注册为 skill）。

## 最小接线评估（结论）

1. **不新增页面类型、不新增 OBSERVE 框架**：读面挂在既有 `world.events` 字典下扩展
   （建议键：`events["card"] = {event_id?, my_score, tiers[], phase, remaining, tasks[]}`），
   与 `events["calendar"]` 同级——**同一真值容器，符合"禁止第二套"**。
2. **接入点**：EVENT 页既有识别分支处**顺带读卡面**（OBSERVE 零点击；与 calendar 读取同源帧）。
3. **Verifier**：仿 `verify_event_calendar_read` 写一个 `EVENT_CARD_READ`（判据：page=EVENT +
   至少 `my_score` 或 `remaining` 其一成立 + 字段互不矛盾）——**注册前先有此绑定**。
4. **建议序**（对应本文件的 1-5）：
   - **Step 1**：卡面四字段读取函数（纯函数，输入帧输出 dict）——**先做**（可单测，零生产影响）
   - **Step 2**：接 `world.events["card"]` + `EVENT_CARD_READ` verifier（**接线提交**）
   - **Step 3**：按规格第 2 条（RULES 滚动）在 Step 1 函数内补可见条数
   - **Step 4**：注册 `READ_EVENT_*` 家族（**或**并入 calendar 家族的读面表述——**以 Step 2 实测为准**）
5. **风险与边界**：全部 OBSERVE（零点击零消耗）；唯一"动作"类（前往侦察/领取）**不在本族**。

## 影响审查（§三·八 九问简答）

还能被发现吗✓（goal 不变）· 能进 Scheduler 吗✓（不碰 chooser）· 不做时能学吗✓（本族即学习入口）·
失败会重试吗✓（COOLDOWN 既有）· Verifier 可达吗✓（Step 2 前置）· 一个失败挡其他吗✗（OBSERVE 级）·
**是否形成永久不可达**✗（不新增过滤）。**结论：可安全推进，Step 1 为下一步起点。**

---

# Step 2 探路记录（r214）：接入点的现状核对

- **发现**：`vision.py` 中**没有"常规活动"页（卡组/卡面）的专属识别分支**——
  该页当前落进 `Page.EVENT` 家族（与"超值活动 hub"共用页类型；r136 的历史注释还记录过
  OCR fallback 把 **世界地图** 误读成 EVENT 的教训，见 vision.py:2582）。
- **含义**：Step 2（把卡面挂进 `world.events`）之前需要一个**页面归属决策**：
  - **方案 A（最小）**：不新增页面类型；在**已识别为 `Page.EVENT` 且帧含卡面特征**（如页签行/`我的积分`文本）时
    顺带调用 `event_card_reader.read_event_card`——**零新页面、零新分支**；
  - 方案 B（较大）：给"常规活动"页新增识别分支——**有误判风险（前车之鉴），不优先**。
- **推荐**：**方案 A**；其判据（"帧含 `我的积分：` 或页签行特征"）本身可用今天素材单测。
- **Step 2 实施清单（下批）**：①写"卡面帧判据"纯函数+测试；②在 EVENT 分支尾随挂读（一次小 diff）；
  ③写 `EVENT_CARD_READ` verifier；④跑 `invariant_review` + 回归；⑤提交。

---

# Step 2-② 探路实测（r216）：回放确认接入点

**方法**：以 `SemanticWorldVision(dataset/candidate/template_manifest.json)` 对
`dataset/exploration/20261016T023240/before.png`（凛风攻城战卡帧）回放 `observe()`。

**结果**：`page=Page.EVENT | confidence=0.99`；`events={"hub":"SUPER_ACTIVITY","panel":"SUPER_ACTIVITY","day_claim_visible":false}`
——**"常规活动"卡帧走的就是 `PAGE_SUPER_ACTIVITY` 分支（vision.py:2382）**（该分支的锚是
返回箭头+右缘"超值活动"标题，两页共有）。

**⇒ 接入点确认**：在 2382 分支 `return WorldState(...)` 前挂尾随逻辑——
`if looks_like_event_card(frame_text): events["card"] = read_event_card(frame_text)`。

**下一小步（Step 2-② 剩余）**：确认 **frame_text 的获取通道**（vision 内既有 OCR 文本读出——
`self.semantic`/ocr 层现有 API），随后写最小 diff + `EVENT_CARD_READ` verifier。

---

# Step 2-② 定稿（r217）：接线设计裁决 → 选项 d

**通道核对结果**：
- 全帧文本的现有通道 = **`OCRService.recognize(image_path, roi=None)` → `OCRResult.text`**
  （ocr.py:302-355：roi=None 即 FULL；截图哈希缓存；**独立服务**）。
- **vision.py 内没有 OCRService**（vision 用 semantic 模板匹配，不做全帧 OCR）。
  ⇒ **"在 2382 分支挂读"需要给 vision 注入 OCRService**（构造签名变化→波及全部调用方）——**不再是"小 diff"**。

**裁决：选项 d（读面不进 vision）**：
1. **零改动 `vision.py`**——页面判定保持原样；
2. 卡面读取以**独立 OBSERVE 步**存在：`EVENT 帧 + OCRService(roi=None) → read_event_card() → events["card"]`；
3. **挂点**：runtime 的 EVENT 帧后处理（或在读取器正式注册时由 Scheduler 以 OBSERVE 技能调度）——
   **两者都先不接线**；本批只交付"读取器 + 判据 + 文档"三件套（已交付）。
4. **理由**：最大兼容（不碰 vision 与其调用方签名）；与"读=OBSERVE"语义一致；
   若未来证明"vision 内挂"更好，**届时再评估**（不现在赌）。

**Step 2 状态**：①判据 ✓ · ②探路 ✓（接入点事实已明）· **接线实现明确推迟**（等 runtime 侧改动批次——
那将是首次触及 runtime 的提交，需完整 §三·八 审查 + 回归）。

---

# Step 2 端到端回放（r219）：链路实证

```
输入帧：dataset/exploration/20261016T023240/before.png（凛风攻城战卡·实机帧）
链路：OCRService(RapidOCR).recognize(frame).text → looks_like_event_card → read_event_card

输出：
  gate : True
  card : {'phase': '侦察阶段', 'remaining': '13:27:18'}
  （该卡无「我的积分」/档次——读取器如实**只输出两项**，不为凑字段编造）
```

**⇒ Step 2 全链闭环**：判据 ✓ · 挂读（runtime 同构 4 行）✓ · 三重验证（79 测试/invariant 11-0-4/§17 世界）✓ ·
**端到端（真 OCR→真读取）✓**。下一步（另批次）：`EVENT_CARD_READ` verifier 函数（绑定待 OBSERVE 技能化时）。

**泛化验证（r232）**：以「米娅的许愿小屋」实机帧（`dataset/exploration/20261016T032008/`）回放——
`looks_like_event_card=False`、`read_event_card={}`——**正确拒绝**。该页信号（`1天12:39:50`/`0/20`/`选择心愿奖励`）
不含四信号任何一项（无"我的积分"、无"点积分"、无"XX阶段"前缀、无单调梯度）⇒ **读取器专于"积分任务制卡"、
不越界**——这是需要的边界；米娅页若将来要读，按同法立新读取器（不扩本族语义）。
