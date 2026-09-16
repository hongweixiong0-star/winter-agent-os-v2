# External Source Mining — 2026-09-17

> 机器可读版本：`knowledge/external/external_capability_map.json`（**31 条能力**、逐条带
> `source_files` / `navigation` / `recognition` / `action` / `verification` / `recovery` /
> `license` / `reuse_level` / `v2_equivalent` / `current_gap`）。
> 本轮时间盒：约 75 分钟（目标 90，上限 120）。**时间盒内到点停止浏览仓库**，转回能力开发。

---

## 1. 哪些仓库实际读过源码

两个 P0 仓库**早就在本地**（`dataset/external/repositories/`，gitignored），只是工作树是空的。
本轮把它们物化后**直接读源码**，没有再走 README：

| 仓库 | 提交 | 语言/规模 | 读法 | 许可证（实测） |
|---|---|---|---|---|
| `Shederator/wosbot`（Frostguard） | `50dd188`（2026-09-06） | Java 620 文件，模块化（api/automation/desktop/tasks/vision） | partial clone（`blob:none`）按需取 + `gh api` 补齐；**6 个文件全文读**、188 个文件落盘、1336 条路径建索引 | **AGPL-3.0-only**（API + README + LICENSE 三处一致） |
| `AminulIslamSifat/whiteout-survival-bot` | `1d09932`（2026-09-02） | Python 42 文件 + 本地 OCR/模板 HTTP 服务 | 本地 `git checkout`；**`core/core.py`、`core/fsm.py`、`coord_utils.py`、`Main/main.py`、`usecases/vip.py` 全文读**，16 个 usecase + 73 张 ROI 表落盘 | **UNVERIFIED** ⚠ |
| `batazor/autopilot-page` | — | 文档站（MIT） | 仅确认许可证 | MIT（真源码在 GitLab，本轮**不可达**，未审计） |
| `zenpaiang/wos-database` | — | — | 仅查许可证 | **无许可证**（API 404） |
| `HuNiu-rgp/wosbot` | — | — | 快速判断：产品页 + 闭源下载 | **无许可证** ⇒ `NOT_USEFUL`（代码层面） |

⚠ **两个必须点名的许可证发现**：

1. **`AminulIslamSifat/whiteout-survival-bot` 的 MIT 只存在于 README**。GitHub license API 返回 **404**，
   完整递归树里**没有 LICENSE/COPYING 文件**，`pyproject.toml` 也没有 `license` 字段。
   ⇒ 按指令判为 **UNVERIFIED / REFERENCE_ONLY，禁止复制代码**。**README 徽章不是许可证。**
2. `Shederator/wosbot` 确认为 **AGPL-3.0-only** ⇒ 不复制源码/资源；其**像素常数与流程顺序**属于
   对游戏 UI 的测量事实，可作为**待验证假设**带回。

### 本轮最重要的单一发现

Frostguard 的 README 明确写：**Resolution `720 × 1280` portrait，emulator 推荐 MuMu Player** ——
**与 V2 的客户端完全一致（720×1280 / MuMu）**。
⇒ 它的**绝对像素 ROI 与 V2 可直接比对**，例如
`DAILY_MISSION_DAILY_TAB_BUTTON` 的搜索区 `(300,1050)-(720,1200)`，与 V2 本轮刚测出的每日任务页签
（x 481–704、y 1091–1173）**吻合到 ~10px**。这是一条**独立验证**，也是一座可直接用的坐标矿。

对照之下，Python 那套是 **1080×2456**（宽高比 0.44 vs V2 的 0.5625）⇒ **y 轴百分比不可迁移**，
x 轴与**流程顺序**可以。

---

## 2. 读到哪些具体实现（摘要，全表见 JSON）

### Frostguard（AGPL-3.0，`ADAPT_PATTERN`）

- **`DailyMissionRoutine.java`** —— 与 V2 当前工作最贴近的一个文件：
  - 切页签：先找 `DAILY_MISSION_SCREEN_TITLE`（区域 `(180,70)-(540,170)`），已在每日页就跳过；
    否则在 `(300,1050)-(720,1200)` 找页签按钮 → 点击 → **再验一次标题**才继续领奖。
    ⇒ **独立印证了 V2 本轮 `SELECT_DAILY_TAB` 的设计**（切完必须验，不能假设）。
  - **启用/禁用变体判别**：找到领取按钮后，再找 `..._CLAIM_BUTTON_DISABLED`，
    若两者**同点（曼哈顿距离 ≤20px）**则判定为"不可领"。**这正是 V2 反复踩的那类坑**
    （灰掉的领取按钮、红色报错成本）——V2 自己的页签修复用的就是同一招。
  - **无进展即停**：点击后在同点仍找到按钮（连续两次）⇒ 停并报告"没有视觉进展"。
  - 先试一键领取，失败则逐个领（上限 20）。
  - 调度：`GameTimeUtils.dailyResetTime()` 锚点 + **重置前 2 分钟的最后检查** + 自动模式 30 分钟安全重排。
- **`VipRoutine.java`** —— VIP 入口是**固定盒子 `(430,48)-(530,85)`**，用模板确认面板；
  每日宝箱 `(540,813)-(624,835)`、点数奖励 `(602,263)-(650,293)`，
  **3 次盲点、无验证**（V2 的 verifier 标准比它强，不要学这一步）；
  VIP 到期时间用 OCR 读（`charWhitelist("0123456789d")`，3 次×200ms）并**持久化到 profile**，
  下次执行时间取"游戏重置"与"到期时刻"的较早者。**月卡购买路径存在但默认关闭。**
- **`ArenaRoutine.java`（1639 行，最富的一个文件）** —— 竞技场对手列表是**重复行布局**：
  基准 y 376（首轮 380）、**行距 128**、最多 5 个对手；每行的挑战按钮 x=624（±38）、
  名字/区服/战力/星星都是**相对坐标**；战力比较**不用模板而用颜色**
  （绿 `rgb(105,230,50)`、`MIN_COLORED_PIXELS=10`、绿/红优势比 1.5、扫描步长 2）；
  名称/区服/战力用了 **4 种容错正则**（`[ABC]` / 残缺 `[ABC` / 无括号 / 尾部括号），
  战力正则 `([0-9]+[.,][0-9]+)([KMBkmb])` **兼顾逗号小数点与 K/M/B 后缀**；
  免费刷新 3 次、钻石刷新 5 次但**默认关闭**、额外次数价格 `{100,200,400,600,800}`；
  `AVOID_PROFILE_ALLIANCE`（**不打自己联盟的人**）；`DEFAULT_ACTIVATION_TIME="23:55" UTC`。
- 其他：`ShopNavigator`（商店页签模型 + **横向滑动标定类** + OCR 复读页签确认，最多 10 次滑动）、
  `BearTrap*`（把巨熊做成**schedule + 抢占规则 + 视觉保护**三层）、
  `PolarTerror*`（战斗与**体力策略分离**）、`Gather*Policy`（队列/英雄/轮换/抢占四种策略）、
  `FurnaceUpgradeInjectionRule`（**把高优先级任务注入运行中的计划**）、
  `PetSkills*`（先读冷却再动作 + 帧证据测试）、`IntelDeploymentPreflight`（**先查再做，不白跑导航**）。

### whiteout-survival-bot（UNVERIFIED，`REFERENCE_ONLY`）

- **`core/fsm.py`** —— **显式页面图** `{节点: {邻居: {action, target}}}` + `detect_state()`（按标题识别）+
  **BFS 最短路** + 每一步失败就**重新识别并重试整条路线**；识别不出来就 `recalibrate()` 并回到已知节点。
  ⇒ 这是 V2 "goal_page_mismatch → SAFE_STOP → 客户端被搁浅" 的**结构性答案**（本轮最强结构借鉴）。
- **`core/core.py`** —— 视觉是**独立本地 HTTP 服务**（paddleocr+opencv），每个请求
  **同一 payload 重放**直到服务恢复或超时（35s，退避 0.35→2.5s），并要求 `success=true`。
  文本点击链：先精确匹配 → 再 fuzzy（rapidfuzz）→ **重试时把 ROI 每次扩 5px**；
  `align=[0,-16.26]` = **在找到的文字上方 16.26% 屏高处点**。
  还有 `tap_on_closest_text`（找 base 文本，再点**它下方最近**的目标文本，可设最大距离）——
  正是"这一行的 前往/领取 按钮"这类需求的成熟解法。
- **百分比 ROI 体系** —— 73 张 `references/TextArea/*.json`（`{text, box % , score}`）+
  `references/icon/<系统>/*.png` 模板名自带语义 + `template_config.json` 给每个模板**自己的阈值与盒子** +
  **设备专属标定覆盖**（`references/<device_id>/*.json` 覆盖默认值）；`tap_on_template` 在等待模式下
  **阈值随时间衰减**（每 0.4s −0.05，下限 0.6）。
- **`Main/main.py`** —— 多账号/多角色：按 `priority` 排序；切角色后**重新读身份并断言**账号一致，
  不一致直接 `RuntimeError`；`completion_log.txt` + **3 小时跳过窗**（同一角色 3 小时内不重复跑）；
  OCR 噪声过滤（非字母数字占比 >0.6 判垃圾、标题 fuzzy <60 判失败、`pick_best_text(expected=...)`）。

---

## 3. 哪些最值得借鉴（Top 10 已按价值排序进 JSON）

1. **Arena 全套**（行距 128 / 基准 y 376 / 战力颜色规则 / 免费优先刷新）——V2 完全没有，且分辨率一致。
2. **启用/禁用变体判别**（同点不同外观 ⇒ 不可领）——V2 反复踩的坑，已有同一招的先例。
3. **导航图 + BFS + 重识别自愈**——V2 搁浅问题的结构答案（属架构话题，先评审）。
4. **VIP 入口盒子 `(430,48)-(530,85)`**——V2 一直找不到的入口，有了可验证假设。
5. **无进展即停**（同点复查）——把 V2 的一次性守卫升级成可测量规则。
6. **滑动标定类**（横向页签条）——V2 资源条带同类问题当时是临时解法。
7. **按游戏重置自排程 + 重置前 2 分钟最后检查 + 安全重排**——边界时刻漏领就是净损失。
8. **切换后身份断言 + OCR 噪声过滤**——V2 读了角色身份但从不复验。
9. **动作前 preflight**（先查体力/队列/板上状态，再花导航周期）——省的是 V2 现在真花的成本。
10. **时间窗任务 + 抢占规则**（巨熊 / 手动集结）——V2 现在做不到"到点就插队"。

---

## 4. 哪些不能直接复制

| 对象 | 判定 | 依据 |
|---|---|---|
| Frostguard 源码 / 512 张 LFS 图标 | **LICENSE_BLOCKED** | AGPL-3.0-only；复制即传染 |
| whiteout-survival-bot 源码 / 62 张图标 | **REFERENCE_ONLY** | 无 LICENSE 文件、API 404，README 徽章不算许可 |
| wos-database / HuNiu-rgp 的任何资源 | **REFERENCE_ONLY** | 无许可证 |
| autopilot（GitLab）架构 | **REFERENCE_ONLY** | 本轮不可达，未验证；且指令明确禁止把 worker/priority/TTL/queue 搬进来 |
| **坐标常数 / 流程顺序 / 游戏机制事实** | **ADAPT_PATTERN** | 这是对 UI 的测量，不是代码表达；且必须先在 V2 真机复测才能进生产 |

**本轮没有复制任何外部代码或资源。** 落盘的东西只有：本报告 + JSON 索引 + 我自己的审计脚本输出。

---

## 5. 当前 V2 哪些 Capability 可以因此快速实现

| V2 能力 | 可直接借的东西 | 还缺什么 |
|---|---|---|
| **每日活跃宝箱领取**（CAP-B01 剩下的那一步） | 启用/禁用按钮对 + 无进展复查 + 一键/逐个回退 | 只需**一个真机帧**拿到启用与禁用两种外观 |
| **VIP**（CAP-B09/B10） | 入口盒子 + 面板模板 + 领奖顺序（宝箱→click to continue→claim→tap to exit） | 一次入口探针 |
| **FREE_SHOP_ITEM**（CAP-B20） | 商店页签模型 + 滑动标定 + OCR 确认页签 | 一次商店面板观察 |
| **ARENA** | 行布局 + 战力颜色规则 + 免费优先刷新 + 避开本盟 | 一次竞技场真机帧 |
| **ALLIANCE_HELP**（RR-003：有技能无 verifier） | `AutoJoin` 表暗示**客户端可能存在"自动帮助"开关** | 确认该开关存在 ⇒ 一次性设置而非每次请求 |
| 导航自愈 / 时间窗任务 | 导航图 + 抢占模型 | **属架构话题**：需 Codex 裁决（不新增 Scheduler） |

---

## 6. 下一项立即落地的能力

**`CAP-B01` 每日活跃宝箱的"领取"这一步**（V2 唯一"今天真的漏了价值"的缺口：
三个宝箱在活动 285 ≥ 270 时已达标，机器看不见也点不到）。

落地顺序（不新增架构，全部走既有主链）：
1. 真机取一帧**可领**宝箱行的帧 ⇒ 注册 `BTN_DAILY_CHEST_CLAIM`（可领态）
   与 `BTN_DAILY_CHEST_CLAIM_DISABLED`（禁用态）两条模板，用**同点判别**（外部做法）分出"不可领"；
2. 新增 `CLAIM_DAILY_CHEST` skill（Page.DAILY，TAP_SEMANTIC 可领态）+
   verifier 读**活动点变化或宝箱外观变化**（不用任务名，任务名每天都在变）；
3. 复用本轮已验证的 `SELECT_DAILY_TAB` 作为前置；
4. REPLAY → 真机 → VERIFY → EVIDENCE → commit → push。

若宝箱今天已全部领完（今天的观测就是如此），则改为落地
**VIP 入口探针**（借 Frostguard 的 `(430,48)-(530,85)` 作为假设，先在 V2 客户端上复测）。

---

## 附：本轮新增/改动的文件

- `knowledge/external/external_capability_map.json`（新增，机器可读索引）
- `docs/EXTERNAL_SOURCE_MINING_20260917.md`（本文件）
- 本地（**不进 git**，`dataset/external/` 已被忽略）：两个外部仓库的工作树已物化，
  供以后**按需回查源码**，不必重新全仓库审计。
