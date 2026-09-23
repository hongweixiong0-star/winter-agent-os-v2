# 11 — GITHUB 搜索与巨熊素材实况（指令 B 交付物）

**性质**：指令 B「必须先交付一份真实的 GitHub 搜索结果」的六字段报告。
**纪律**：本文只写**已经亲手打开过的文件**。没打开的不写，打不开的写「资源不可取得」并写明真实失败原因。
**日期**：2026-09-23。

三态口径（指令 B 第二节要求区分）：

- **已检查源码** = 我读到了实现该行为的实际函数体。
- **仅有功能说明** = 只有 README / 函数名 / 配置项，**没有**函数体可读。
- **资源不可取得** = 目标文件不存在、或存在但内容为空壳、或需要凭据。

---

## 一、GitHub 搜索

**执行方式**：`gh` CLI（`gh api` / `gh search repos`）。**已认证**，账号 `hongweixiong0-star`，
token scopes 含 `repo`。GitHub 接口可用，**不存在"未搜索"的情况**。

关键词与命中数（`gh search repos`，非 README 推断）：

| 关键词 | 命中 | 备注 |
|---|---:|---|
| `whiteout survival` | 205 | 太宽，只用来看总量 |
| `whiteout survival bot` | 50 | 主战场 |
| `WOS automation` | 25 | 主战场 |
| `whiteout survival automation` | 12 | 主战场 |
| `无尽冬日 脚本` | 4 | 中文侧 |
| `bear trap whiteout survival` | 1 | **只有 1 个** |
| `whiteout survival macro` | 0 | 无 |
| `winter survival maa` | 0 | 无 |
| `无尽冬日 巨熊 脚本` | 0 | 无 |
| `无尽冬日 自动集结` | 0 | 无 |
| `无尽冬日 MAA` | 0 | 无 |

**去重后逐一打开根目录检查的仓库：10 个。**

| # | 仓库 | 可访问 | 许可证 | 实际内容 |
|---|---|---|---|---|
| 1 | `Shederator/wosbot` | 是 | **AGPL-3.0** | Java；`modules/` `tools/` `docs/`；Discord/联盟管理向，**已克隆到本地（sparse）** |
| 2 | `AminulIslamSifat/whiteout-survival-bot` | 是 | README 称 MIT，**但仓库内无 LICENSE 文件** ⇒ VERIFY_REQUIRED | Python + OpenCV + PaddleOCR；**已克隆到本地** |
| 3 | `ducker24678/wjdr-helper` | 是 | 无 | 中文；`logic/tasks/bear_attack.py` 有真实实现 |
| 4 | `yun-2000/wos-bluestacks-bot` | 是 | 无 | `tasks/*.yaml` 声明式任务 |
| 5 | `Fiki6640/android_auto_game` | 是 | 无 | ADB + OpenCV 链式任务框架 |
| 6 | `Samge0/wujindongri` | 是 | 无 | **纯固定坐标点击，无模板无识别** ⇒ 价值极低 |
| 7 | `batazor/whiteout-survival-autopilot` | 是 | UNKNOWN | 已登记，未深入 |
| 8 | `austxio/WOS-Bot` | 是 | 无 | 未见巨熊实现 |
| 9 | `camoloqlo/wosbot` | 是 | 无 | 未见巨熊实现 |
| 10 | `aixed/whiteout-survival` | 是 | 无 | 未见巨熊实现 |

**许可证纪律**：`Shederator/wosbot` = AGPL-3.0 ⇒ 只可借鉴**思路与能力分解**，代码不得复制进 V2。
`AminulIslamSifat/whiteout-survival-bot` README 声称 MIT 但**没有 LICENSE 文件**
⇒ 按项目铁律（`07_EXTERNAL_REUSE.md`：未知许可证 = REFERENCE_ONLY）**降级为 REFERENCE_ONLY**。
其余无许可证仓库一律 REFERENCE_ONLY。**没有任何外部代码被复制进 V2。**

---

## 二、仓库证据（实际检查过的源码 / 资源目录）

### 2.1 `ducker24678/wjdr-helper` —— 唯一含真实巨熊执行流程的仓库

- `logic/tasks/bear_attack.py`（**27427 字节，全文读毕**）
- `logic/tasks/giant_beast_rally.py`（18867 字节）
- `assets/templates/`（**50 个中文命名模板**，清单已读）

其状态机与实现（原文核实）：

```python
class State(Enum):
    CHECK_RALLY_PAGE; NAVIGATE_HOME; FIND_ALLIANCE_TAB
    FIND_SWORDS; FIND_TEAM; WAIT_CLICK_GROUP; CLICK_EXPEDITION; VERIFY_RALLY_PAGE

_DEFAULT_TEAM_COOLDOWN_SECS = 60.0     # 可配 324
_DEFAULT_ENTER_GROUP_BUTTON_Y_VALID_RANGES = [(1448,1496),(997,1007),(508,518)]
_DEFAULT_FIRST_TWO_TEAM_Y_EXTRA_VALID_RANGES = [(462,475),(951,965),(1439,1452)]
_DEFAULT_RALLY_TAB_POINT = (163, 154)
self._rally_template = cfg.get("rally_template", "熊集结页")
self._enter_group_button_x = 770;  self._enter_group_button_y_offset = 134
self._expedition_button_point = (1665, 995)
```

可复用的四条设计（**思路**，非代码）：

1. **`_team_skip_until[team_id] = now + team_cooldown_secs`** —— 每支队伍**独立冷却**。
   对应本项目缺的「加入后隔多久才能再上同一队」。
2. **`enter_btn_y = team_y + 134` 后用 y 白名单校验，不在范围直接 `return` 结束本轮** ——
   作者注释明说「本轮页面位置下坐标已不可信」。与本项目「不得把固定 ROI 历史坐标当新页面实际位置」同源。
3. **`_step_verify_rally_page` 恢复阶梯**：首次 miss → 等 0.5s 重判；第 1、2 次 → `try_go_back`；
   再 miss → 回首页。对应 §十八「集结已出发 / 列表为空」恢复。
4. **`_maybe_scroll_rally_page`**：每 60s 滑一次 `(960,1500)→(960,500)`，进页面时滑 2 次到底。
   解决「集结列表需要滚动才看得到可加入的行」。

模板资源为**中文命名 PNG**，与本项目国服同语言，**语义可直接映射**：
`熊集结页.png`、`加入队伍绿色.png`、`加入队伍灰色.png`、`出征按钮.png`、`集结旗帜.png`、
`联盟战争.png`、`两把剑.png`、`联盟tab.png`、`编队1-4.png`、`编队1备用-3备用.png`、
`返回按钮.png`、`关闭按钮.png`、`重新连接.png`、`世界地图.png`、`城镇大门.png`。

> **未下载其模板文件本体**：该仓库无许可证文件 ⇒ REFERENCE_ONLY，**不得把无许可证的图片复制进候选资产库**。
> 已记录**语义名称与用途**（可复用的是「有哪些控件」这一知识），图片本体不取。

### 2.2 `yun-2000/wos-bluestacks-bot` —— 有真实门控规则

- `tasks/hold_rally.yaml`（4236B）、`tasks/_select_hun_and_deploy.yaml`（1143B）、`docs/architecture.md`
- **`loop_until_text: "1/6"` 于 `region_pct [0.0, 0.13, 0.40, 0.20]`** ——
  等**左侧行军条显示 1/6** 才开下一轮，与本项目 `bear_dispatched.png` 的左侧 `行军 1/6` **完全吻合**。
  这是「何时该开下一车」的实测判据。
- 模板阈值 `0.72`，并注释说明半透明放大镜需降到 `0.55`（阈值不能一刀切）。

### 2.3 `AminulIslamSifat/whiteout-survival-bot`（本地已克隆）—— 巨熊是空壳

- `usecases/bear_trap.py` **全文只有 27 行，三个函数体全是 `return`**：

```python
def start_bear_rally():  return
def join_bear_rally():   return
def remove_wrong_formation():  return
```

- **数据驱动核实**：全仓 `grep -rn "bear_trap\|BearTrap\|bear" --include="*.py"` 只命中该文件自身的两个
  `def` 行 —— **没有被任何 `TASKS` 列表引用**（`Main/task_menu.py` 的 TASKS 无此条目）。
  ⇒ 结论：**"仅有功能说明"都算不上，是死代码**。**绝不能把它报告成"外部已有巨熊实现"。**
- `references/` 下 **0 个图片资源**（`find -name '*.png|*.jpg|*.jpeg'` = 0），
  它的"模板匹配"依赖的 `references/icon/` 只有一个 141 字节的 `template_config.json`。
  ⇒ 该仓库**不携带任何可用 UI 模板**。

**但它有真实价值的三件东西**（已检查源码）：

1. **`core/core.py`（921 行，全文读毕）** —— OCR/模板双引擎客户端。
   `tap_on_text` / `tap_on_template` / `tap_on_templates_batch` / `tap_on_closest_text` / `req_text`。
   关键设计：**以文字为锚点定位控件**（`tap_on_closest_text(base_text, target_text)` 用
   「和某个基准文字最近的那个目标文字」定位），且**每次调用都从当前帧重新 OCR 求坐标** ⇒
   天然免疫固定坐标漂移。这正是本项目 `SEMANTIC_TARGET_NOT_VERIFIED` x424 的根因方向。
2. **`core/recalibrate.py`** —— 任意页面的归位引擎：loop 内读 `World.World` / `World.City`，
   命中即认为到家；否则依次尝试 `Global.Back` / `Global.Close` / `FirstPurchase.Close` / `Home.Store.Back`，
   再扫 `tap anywhere to continue` / `Reconnect` 等全屏遮罩文字；都没有则点左上角。
   **带 timeout=30 并有终态断言**（找不到首页就 `raise`）。
3. **`references/TextArea/*.json`（35 个文件）** —— **英文侧的文字锚点 + ROI 百分比**。
   其中两份**直接对应巨熊页面**，是本仓库对本次任务最有价值的部分：
   - `Home.Alliance.War.json`：`Rally` tab、`Solo` tab、`Events` tab、`Auto-join` /
     `Auto-joining` 两个状态文案，**以及它们的 box 百分比**。
   - `Home.Alliance.War.AutoJoin.json`：`Auto-Join` 标题、`Use the Formation`、
     `IncreaseQueueLimit`(`+`)、`QueueLimit`(`6`)、`Only Auto-Join After Exiting Game`、
     `Stop`、`Restart`、`Enable` —— **官方自动加入弹窗的每一个控件与其 ROI**。
   - `World.Deploy.json`：出征页 8 个编队位（`ATK/BR1/BR2/BR3/BR4/GIN/DF1/DF`）、
     `TroopCapacity`、三兵种数量、`MarchTime`、`Deploy`、`Withdraw All`、`Equalize`、`Balance` 及三比例。
   - `World.json`：`World.MarchQueue`（`4/6`）、五条行军剩余时间 —— **行军队列读数的 ROI 定义**。

> **这份英文 ROI 表的价值**：它是**国际版**的百分比坐标，**语言不同**（`Rally` vs `集结`），
> 但**页面结构与控件相对位置同源**。按 §六，应当建立中英文语义映射，
> **而不是**把英文 box 当成本项目 720×1280 的实际点击坐标（§三：绝对坐标不可直接复用）。

### 2.4 `Fiki6640/android_auto_game` —— 有 skip_conditions

- `config.yaml`、`crop_template.py`、`README.md`
- `打巨兽` 链带 `skip_conditions`：`队列检测 value < 1`、`体力检测 current < 25`。
  对应 §十二「队列准备」与 `operations_policy.stamina_threshold: 30`。

### 2.5 `Samge0/wujindongri` —— 明确无价值

`auto_hunting.py` / `main.py` 全文 **纯固定坐标 `tap_screen(x,y)`，无模板、无 OCR、无识别**。
⇒ 按指令「不得编造源码功能」，如实记为**无可复用实现**。

---

## 三、巨熊流程（哪些仓库确实含有发起或加入集结的实现）

| 仓库 | 发起集结 | 加入集结 | 判定依据 | 三态 |
|---|---|---|---|---|
| `ducker24678/wjdr-helper` | **有** | **有** | `bear_attack.py` 27427B，`CLICK_EXPEDITION` 点 `(1665,995)` 出征 + 每队 cooldown | **已检查源码** |
| `yun-2000/wos-bluestacks-bot` | 部分 | **有** | `hold_rally.yaml` 的 `loop_until_text: "1/6"` 门控 | **已检查源码** |
| `AminulIslamSifat/whiteout-survival-bot` | **无** | **无** | `bear_trap.py` 三函数全 `return`，且未被任何 TASKS 引用 | **空壳，不是实现** |
| `Fiki6640/android_auto_game` | 未见 | 部分 | `打巨兽` 链含队列/体力 skip_conditions | 仅有链定义 |
| `Samge0/wujindongri` | 无 | 无 | 纯坐标点击 | **已检查源码** |

**结论**：**只有 2 个仓库含有真实的"加入集结"执行流程**，其中 1 个（`ducker24678`）同时含发起。
**没有任何仓库有可直接复用的巨熊 UI 模板文件**（唯一有模板库的 `ducker24678` 无许可证）。

---

## 四、模板资源（实际获取了哪些 UI / 按钮 / 页面图片）

**从 GitHub 实际下载的模板文件：0 个。**

理由（逐条可核查，不是"没搜"）：

| 候选来源 | 模板情况 | 为什么不下载 |
|---|---|---|
| `ducker24678/wjdr-helper` | `assets/templates/` 50 个中文 PNG | **无许可证** ⇒ 按项目铁律 REFERENCE_ONLY，不复制媒体文件 |
| `yun-2000/wos-bluestacks-bot` | 有 `*.jpg` 按钮图 | **无许可证** ⇒ 同上 |
| `AminulIslamSifat/whiteout-survival-bot` | **0 个图片** | 无文件可下载 |
| `Shederator/wosbot` | AGPL-3.0 | 传染性许可证 ⇒ 不复制媒体文件 |

> 这不是倒退。指令 B 第三节写的是「对于**可合法获取和复用**的资源，下载实际文件」，
> 而第四节要求「检查许可证及相关素材的使用条件」。**无许可证的他人截图不可合法复用**，
> 拿进来反而是引入来源不明的资产 —— 与 §五「来源未知的字段如实标记 UNKNOWN」相冲突。

**本次真正落地的模板来自本项目自己的真机帧**（`LIVE_CLIENT`，来源可核查、无许可证风险）：

**14 个巨熊语义，`dataset/candidate/bear_rally/`，manifest 418 → 432。**

| 语义 | 来源帧 | 尺寸 | 用途 |
|---|---|---|---|
| `BTN_ALLIANCE_WAR` | `alliance_main_now.png` | 270×80 | 联盟战争入口（badge 21） |
| `TAB_RALLY_LIST` | `join_list_now.png` | 170×74 | 集结 tab（巨熊列表只在此 tab 下） |
| `TARGET_BEAR_TRAP` | `bear_trap_detail.png` | 254×54 | **`等级1变异巨熊` 标题行** |
| `ROW_TARGET_BEAR_COLUMN` | `join_list_now.png` | 130×184 | 一行的 `目标` 列 |
| `STATUS_RALLY_COUNTDOWN` | `join_list_now.png` | 180×36 | 行头 `集结中` + MM:SS |
| `BTN_JOIN_ROW` | `bear_rally_panel.png` | 62×74 | **绿色 `+`（车身加入口）** |
| `BTN_AUTO_JOIN` | `bear_rally_panel.png` | 328×80 | `自动加入` 页脚 |
| `BTN_START_RALLY` | `bear_trap_detail.png` | 196×58 | **橙色 `集结`（车头发起口）** |
| `POPUP_TITLE_START_RALLY` | `bear_rally_next.png` | 244×48 | `发起集结` 弹窗标题 |
| `BTN_CONFIRM_START_RALLY` | `bear_rally_next.png` | 352×76 | `发起集结` 确认 |
| `BTN_BEAR_GO` | `special_buildings.png` | 128×52 | 狩猎陷阱 `前往` |
| `STATUS_BEAR_WINDOW` | `special_buildings.png` | 262×42 | `剩余时间 00:15:39` |
| `PAGE_TITLE_MARCH` | `bear_troop_setup.png` | 90×40 | `出征` 页标题 |
| `BTN_CONFIRM_MARCH` | `bear_troop_setup.png` | 188×54 | `出征` 确认 |

**首轮注册的 3 个坐标是错的，已用像素网格法修正并逐张复核**：

| 语义 | 旧 box | **错在哪（review 图确认）** | 新 box |
|---|---|---|---|
| `BTN_JOIN_ROW` | (508,300,580,368) | **落在第 4 个英雄头像上，未命中绿色 +** | (600,356,662,430) |
| `BTN_START_RALLY` | (358,842,516,906) | **框在奖励图标条上方，未命中橙色集结** | (368,982,564,1040) |
| `TARGET_BEAR_TRAP` | (200,570,470,700) | **命中巨熊插画本体，不是标题文字** | (232,796,486,850) |

后两个的性质：`BTN_START_RALLY` 点下去不会发起集结；`TARGET_BEAR_TRAP` 更危险 ——
它匹配的是**物种美术**，而**普通巨兽面板也会画巨兽**，这正是指令禁止的
「把普通集结误认成巨熊集结」的模板级成因。另修正 `STATUS_BEAR_WINDOW`
（旧框命中行标题而非倒计时）、`BTN_BEAR_GO`、`PAGE_TITLE_MARCH`。

---

## 五、本地比对（哪些已有、哪些本次新增）

**已有、本次保留原版不动**（§三：本地已有且可靠的保留原版）：
`dataset/candidate/templates/` 280 个模板中与巨熊间接相关的
`page_alliance__live_alliance_home_2__0.png`、`march_count_1_of_6__*`、
`btn_dispatch__live_march_selection__1.png`、`status_marching__*`、`status_returning__*`、
`btn_troop_plus_first__*`、`btn_remove_all__*` —— **未覆盖、未重截、未改 box**。

**本地缺失、本次新增（14 条，全部 `LIVE_CLIENT`）**：见上表。
`dataset/candidate/templates/` 280 个模板中**此前零个 bear/rally 模板** —— 这是本次补上的最大空缺。

**已下载但无法兼容现有识别器**：无（本次未下载外部图片）。

**外部知识已吸收但未落为模板**（避免来源不明资产）：
`ducker24678` 的每队 cooldown / y 白名单校验 / 恢复阶梯 / 列表滚动；
`yun-2000` 的 `1/6` 行军条门控；`Fiki6640` 的队列与体力 skip_conditions；
`AminulIslamSifat` 的 OCR 文字锚点定位与 `recalibrate` 归位引擎；
`Shederator` 的 `MailClaimPassPolicy` 有界收敛策略（`STOP_NO_PROGRESS`）。

---

## 六、接入结果（新增素材是否进入现有 Vision / MAA 识别链）

**已进入识别链，且已用离线回放证明。**

`tools/register_bear_rally_templates.py` 写入
`dataset/candidate/template_manifest.json`（418 → **432**），
该 manifest 就是 `SemanticROIVision` 的加载源，也就是 V2 现有识别链本身 ——
**没有新建第二套识别器**（§二）。

`tools/verify_bear_templates_replay.py` 的离线回放（正样本 = 该 crop 的来源帧；
负样本 = 另一张**不含该控件**的真机帧）：

```
registered semantics: 255
bear pack registered: 14/14

SEMANTIC                     POS   NEG  MAX  VERDICT
BTN_ALLIANCE_WAR               0  None    6  OK
TAB_RALLY_LIST                 0  None    6  OK
TARGET_BEAR_TRAP               0  None    6  OK
ROW_TARGET_BEAR_COLUMN         0  None    6  OK
STATUS_RALLY_COUNTDOWN         0  None    6  OK
BTN_JOIN_ROW                   0  None    6  OK
BTN_AUTO_JOIN                  0  None    6  OK
BTN_START_RALLY                0  None    6  OK
POPUP_TITLE_START_RALLY        0  None    6  OK
BTN_CONFIRM_START_RALLY        0  None    6  OK
BTN_BEAR_GO                    0  None    6  OK
STATUS_BEAR_WINDOW             0  None    6  OK
PAGE_TITLE_MARCH               0  None    6  OK
BTN_CONFIRM_MARCH              0  None    6  OK
--------------------------------------------------------------
discriminating: 14/14   ambiguous:0   not_registered:0
```

`distance` 是 pHASH Hamming 距离（越小越好），正样本全为 0（同帧精确匹配），
负样本全为 `None`（无记录命中）。**特别核对了两个"同活动近邻页"的假阳性风险**：

```
BTN_JOIN_ROW    vs join_list_now.png          -> 0     (另一支可按的集结仍应命中，符合预期)
BTN_JOIN_ROW    vs join_list_after_detail.png -> None   (已灰的 + 不命中)
BTN_AUTO_JOIN   vs bear_rally_next.png        -> None
BTN_START_RALLY vs bear_rally_panel.png       -> None
TARGET_BEAR_TRAP vs special_buildings.png     -> None   ← 关键：巨熊标题不在联盟领地页命中
```

**尚未接入的部分（诚实登记）**：
模板进了识别链，但 `JOIN_RALLY` / `START_RALLY` 仍**不能派发** —— 见下节。

---

## 七、尚未解决

按重要性排序，每条写明**为什么现在没解决**：

1. **`JOIN_RALLY` / `START_RALLY` 不在 `LiveRuntime.VERIFIED_ATOMIC`。**
   `runtime.py` 第 4584 行：`if decision.skill not in allowed or decision.skill not in self.VERIFIED_ATOMIC:`
   → `finish("SKILL_NOT_ENABLED_FOR_LIVE_LOOP")`。类注释：「Only skills with an explicit
   post-action verifier may execute.」**模板齐了也不会被派发**，这是当前第一硬阻塞。
2. **`Executor.execute` 不支持这两个技能的 action kind。**
   `executor.py` 只处理 `TAP_SEMANTIC / PRESS_BACK / SWIPE / OBSERVE`，
   其余 `action.kind` 落到 `DEVICE_ADAPTER_NOT_CONNECTED`，是第二断点。
3. **verifier 签名不匹配。** `verify_rally_joined/created(before, after, target)` 是三参数，
   `runtime.py` 第 4839 行以 `self.VERIFIED_ATOMIC[decision.skill](before, after)` 两参数调用
   ⇒ 必须用 `lambda b, a: verify_rally_joined(b, a, "BEAR")` 绑定。
4. **五个词在 registry 里根本不存在**：`CHECK_ALLIANCE_EVENT` / `READ_BEAR_TIMER` /
   `SELECT_TARGET` / `SELECT_TROOP_PRESET` / `CONFIRM_MARCH`。
   `skill_factory.py` 第 30 行的 `PARTICIPATE_BEAR` 元组引用了它们，`goal_library` 也在用 ⇒ 空壳引用。
5. **`TARGET_BEAR_TRAP` 与普通巨兽的区分只到模板级。**
   模板证明「巨熊标题不在联盟领地页命中」，但**尚未用普通巨兽 detail 面板做负样本**
   —— 手上没有一张普通巨兽面板帧。这是本条的关键缺口，**不可声称已解决**。
6. **车头侧最缺模板的页面**：`发起集结` 的**编队/英雄选择**页、
   集结**已满**状态的 `+`、**加入成功**的行内态、**行军结果 / 战斗报告**页。
   现有 `hero_picker_fast.png` / `joined_with_jesse.png` / `bear_dispatched.png` 尚未裁剪注册。
7. **`自动加入` 弹窗的 `使用编队` / `加入队列最大数量` 未建控件。**
   `auto_join_final.png` 显示了它们，但未裁模板、未建技能参数。
8. **英文 ROI 表未映射进本项目。** `Home.Alliance.War.AutoJoin.json` 的 8 个控件 ROI
   与 `World.Deploy.json` 的 8 个编队位 —— 仍未做中英文语义映射（§六），
   且**不可**直接当 720×1280 点击坐标。

---

## 八、本次的可核查产出

| 产出 | 路径 |
|---|---|
| 巨熊模板注册脚本 | `tools/register_bear_rally_templates.py` |
| 巨熊模板（14 个 PNG） | `dataset/candidate/bear_rally/*.png` |
| 人工复核图（7 张，红框标注） | `dataset/candidate/bear_rally/_review_*_boxes.png` |
| 像素网格校验图 | `dataset/raw/bear_live_20260909/_grid/grid_*.png` |
| 离线回放验证脚本 | `tools/verify_bear_templates_replay.py` |
| manifest 条目 | `dataset/candidate/template_manifest.json`（418 → 432） |

**没有交付的东西也写明**：没有下载任何外部图片（无许可证）；
没有把任何外部代码复制进 V2；没有新增第二套识别器 / 调度器 / 执行器。

---

## 九、许可证核对（2026-09-24 补充，任务书 §九）

任务书 §九 要求「先核对那 5 个包含巨熊内容的仓库分别有什么许可证或使用条件」。
用 GitHub API 直接查（`gh api repos/<full>`），**不靠 README 声明**：

| 仓库 | GitHub API 报告的许可证 | 可复用？ |
|---|---|---|
| `ducker24678/wjdr-helper` | **NONE**（无 LICENSE 文件） | **否** — 无许可证 = 保留全部权利 |
| `yun-2000/wos-bluestacks-bot` | **NONE** | **否** |
| `AminulIslamSifat/whiteout-survival-bot` | **NONE**（README 声称 MIT，但仓库内无 LICENSE 文件） | **否** |
| `Fiki6640/android_auto_game` | **NONE** | **否** |
| `Shederator/wosbot` | **AGPL-3.0** | 仅思路 — copyleft，代码/素材不得进 V2 |

**结论**：含巨熊内容的 5 个仓库里，**4 个完全没有许可证**，第 5 个是 AGPL-3.0。
⇒ **没有任何一个的源码或图片可以合法复制进 V2。**

这一条此前是基于「仓库内没有 LICENSE 文件」的推断；现在由 GitHub 的许可证 API 直接确认，
包括 `AminulIslamSifat` 那个**README 写 MIT 而 API 报 NONE** 的情况 —— README 声明不是证据。

因此「外部 UI 模板下载与入库」**继续保持未完成**，且不再是待办：**没有可合法复用的资源**。
按任务书 §九 末句，改以**本项目自己的真机截图**完成关键参战能力 ——
这正是 21 个巨熊模板的来源（`LIVE_CLIENT`，无许可证风险）。
