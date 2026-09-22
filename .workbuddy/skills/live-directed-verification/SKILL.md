---
name: live-directed-verification
description: "Run a directed verification on the real device for Winter Agent OS V2: hold the device lease, locate every coordinate on the frame you are about to tap, prove the tap landed, and decide when the honest answer is to NOT tap. Use when a fix or a locator has to be confirmed on the device rather than argued offline."
description_zh: "真机定向验证流程：持租约、坐标取自当帧、证明落点，以及何时应当拒绝点击"
description_en: "Directed device verification with frame-derived coordinates and a refusal path"
agent_created: true
---

# 真机定向验证（持租约、坐标取自当帧、可以拒绝点击）

## 为什么有这条技能

本项目多次把"离线看起来对"当成"已经验证"：`arrow_norm` 的落点修好后只在生产帧上复读过，而它决定 tap 坐标；
反过来也有把"没点中"当成"客户端没做到"的时候。真机验证解决的是那些**只有设备能回答**的问题，
而它有两条硬约束：**不能与 AUTO 并发**（同一台 MuMu 会被两个执行者同时操作），
以及**不得照搬任何坐标**（同名控件在不同页面/不同滚动位置的坐标不同）。

## 车辆

用 `tools/live_panel_arrow_check.py`（会话 2026-09-23 建立）。它复用 `tools/cq_nav_tap_probe.py` 的
`build()` 与 `take_the_lease()`，因此设备构造与租约纪律不会各写一份。已支持：

| 参数 | 作用 |
|---|---|
| （默认） | 开快捷面板 → 点第一行「有落点箭头」的行 → 读结果 |
| `--scroll N` | 点行之前先滑动面板列表 N 次（下面的行需要滚动才可见） |
| `--row KEY` | 指定行（`SHIELD_CAMP`/`RESEARCH`/`MY_REWARDS`/`ALLIANCE_DONATION`/`HERO_RECRUIT`） |
| `--on body` | 点该行的**行体**（标签中心，取自本帧 OCR token），而不是它的箭头 |
| `--measure-callout` | **只测量不点**客户端画出的气泡，并把"为什么本轮不点"写进记录 |

结果写 `dataset/truth_audit/live_panel_arrow_<日期>/`（帧 + JSON），该目录**不被清理**（`dataset/raw` 会被磁盘保护清理）。

## 步骤

1. **等窗口**：查 `learning/control_panel/panel.log` 尾与 `learning/device_lease.json`。
   面板每轮之间留固定间隔（本轮实测 10 分钟），那段就是设备空闲窗口；能跑完一轮再从从容开始。
2. **只读预检**：`tools/cq_nav_tap_probe.py --page`（同样持租约）先看客户端在哪一页、面板是否已开、
   红点台账。**先知道自己在哪一页，再决定点哪里**——同一串固定坐标在 HOME 是开面板、在地图是下令行军。
3. **跑定向验证**：坐标全部来自**当帧读数**（把手 `find_quick_panel_handle`、行落点 `rows[].arrow_norm`、
   行体取自本帧 OCR token）。点之后**必须再观察**：页面前后对比 + `verifier_evidence` 式的证据字段。
4. **判读**：把"这一下有没有落到控件上"与"客户端因此发生了什么"分开说。
   落点对而客户端没反应 ⇒ 那个控件不是你以为的功能；落点不对 ⇒ 是读数的缺陷（见 #98）。
5. **拒绝点击是可以接受的答案**：当定位器在**点击前**就有反例（例如面板打开时窗内最大白块是**把手**），
   就把模式改成"只测量"，把反例数字写进文档头与 issue，等有了独立依据再点。
   **凭一个自选阈值点下去，比不点更糟**——它会产出一个看起来有效的错误结论。

## 判据（本项目已付过代价的）

- **坐标来源**：只接受当帧定位。会话中"从测试桩里抄来的把手点 (13,550)"点开的是**军师卡牌页**，
  于是那次三跳实验从第一步起就在量错屏。
- **UNKNOWN ≠ 在别处**：读取器判不出页面的帧**不能**当作"在别的页面"去导航；等一帧再看，仍 UNKNOWN 就停。
- **复位用客户端自己的控件**：地图上用 `BTN_OPEN_HOME`、弹窗上用 `BTN_CLOSE`（取**当帧匹配到的**那条记录的 ROI，
  同一语义可能有 4 条记录），**不要**盲目 BACK——地图上按 BACK 打开的是退出确认，等于自己制造失败状态。
- **一次一跳**、每跳后重新观察；有界（本轮 3-4 跳）。
- **受控对比**才谈因果：前后两帧必须是同一相机、之间只有那一个动作。本轮由此确认"点已完成行体 → 客户端画出气泡"
  （点击前 0 白块、面板打开时最大白块是把手 270px、点击后 891px、四分钟后同位置 733px）。
- 验证完把**证据帧按留存惯例拷进 `dataset/truth_audit/` 并 `-f` 入库**（`.gitignore` 忽略该目录的 png，
  但测试与结论依赖它们，不能静默缺失）。

## 反面清单

- ✗ 拿另一页面/另一次会话的坐标来点。
- ✗ 把"面板关了"当成"动作成功"（面板消失是它自己的结果，见 #92 的验证器收紧）。
- ✗ 用自选阈值把定位器"收窄"到能点——阈值必须来自**两侧都有实测**的间隙（本轮：非气泡 270px vs 气泡 519-891px）。
- ✗ 与 AUTO 并发，或长期占住租约（AUTO 的下一轮会被拒）。跑完立即释放（车辆在 `finally` 里释放）。
- ✗ 把"读到红点 / 生成 Goal / 页面打开"当成"任务完成"。
