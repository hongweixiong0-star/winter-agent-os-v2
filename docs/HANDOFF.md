# 交接：当前状态

> 本文由当前会话在 2026-10-05 20:2x（GMT+8）写下，目的只有一个：**让下一位接手的人不必重新推导。**
> 每条结论后面都跟着它是怎么被测出来的；**凡未测到的，本文都写成"未测"而不是"应该没问题"。**

---

## 1. 当前 git HEAD

**先说清本文与 HEAD 的关系，否则它一提交就自相矛盾**：本文描述的是**它被引入时**的那棵树 ——
`fa015b4a`。引入本文的那次提交是 `a711f02 docs: hand the current state over in docs/HANDOFF.md`，
在它之后；此后每多一次提交，HEAD 都会继续前移，**而本文描述的状态不随之改变**。
所以读 §1/§2 时请把下面两行当成**"截至 `a711f02` 时的状态"**，而不是"此刻的 HEAD"；
要此刻的，用 `git log --oneline -1` 和 `tools/check_mainline.py`。

```
fa015b4a87ab85c30b30e9f90090e9c06ec8f4b5
fa015b4a  fix(building): the upgrade may not be authorized by `upgradeable` alone
```

分支 `codex/production-pin-recovery`。本次会话共交付 9 个提交（最新在上）：

| 提交 | 一句话 |
|---|---|
| `fa015b4a` | 花费不再仅凭 `upgradeable` 授权（身份门） |
| `766630e3` | 面板可见带移回上方（对偶滚动能力） |
| `b4c4b3b1` | **回退** 页签切换能力（前提被测量证伪） |
| `8c6974af` | （已回退）页签切换能力 |
| `c873ab0c` | 面板盖住动作栏时拒绝派发训练入口 |
| `2bc37b32` | 退役两个"位置盲"的 MAA 识别节点 |
| `b0a77a74` | 巨兽目标 = 帧上印出的那个词，不是精灵图 |
| `ad7c9ade` | 选中建筑的升级卡片用的是"实验室"那套版式 |
| `2c08116f` | 冰原巨兽页签上的 OCR 读法 |

## 2. 生产 pin

| 项 | 值 |
|---|---|
| manifest `expected_commit` | `fa015b4a87ab85c30b30e9f90090e9c06ec8f4b5` |
| pin 工作树 HEAD | `fa015b4a`（与上一致） |
| `tools/repin_production.py` | `RESULT: CLEAN_OUTSIDE_DATA` |
| `tools/check_mainline.py` | `RESULT: MAINLINE_OK`（pin HEAD == expected == 在分支上；mirror `main 6bef9082` 在分支上） |
| `tools/gui_wiring_verify.py` | `wired and matching 19/19`，`mismatched 0` |
| pin 工作树非数据脏项 | 无（只有 `?? evidence/gui_workbuddy_loop/`，长期存在、已被自检白名单） |

**两棵树的关系**：`E:\无尽冬日智能体` 是仓库的 `main` worktree（数据根，210 ahead of origin），
pin 是 `E:\无尽冬日智能体_worktrees\winter-prod-pinned\无尽冬日智能体`（分支 `codex/production-pin-recovery`）。
`config/ knowledge/ learning/ dataset/` 在 pin 里是**指向数据根的 junction**，所以 pin 的
`git status` 会列出上千条数据脏项 —— **那是数据根的常态，pin 的自检把它们排除在外**（`CLEAN_OUTSIDE_DATA` 就是这个意思）。
`docs/` 在 pin 里是**独立真实目录**（不是 junction），因此本文进的是 pin 分支。

## 3. 正在做的事（进行到哪一步）

**主题：把"训练目标看不见自己的面板区段"这条线修完。** 已走完的路径：

1. 测出因果：61 条面板开着的训练失败里 **59 条**在同一次运行更早步骤有过
   `OPEN_QUICK_PANEL` → `SCROLL_QUICK_PANEL_TASKS` ⇒ **扫掠把面板滚下去了，而训练段在列表顶部**。
2. 中间走过一次弯路并**已回退**：先做了"切换面板页签"，被账本自己的**共现结构**证伪
   （3205 帧里城市段与野外行大量共现；一帧里 部队训练/科技研究/联盟捐献/专家/英雄招募
   **堆在同一条可滚动列表**上）⇒ 面板是**一条连续列表**，"哪段可见"是**滚动位置**的函数，不是页签。
3. 按正确的因果落地：读取器在**同一处构造**下多返回**首尾互换**的手势、解析器镜像分支、
   一个技能、一个**判方向**的验证器、大脑里**有界** hop（上限 3）后回落原拒绝对。
4. **已交付**（`766630e3`），且**首次生产尝试即成功**：带在设备上真的下移 0.143、
   上方确有新行露出。

**当前停在哪一步**：上一条的**目标级效果**还没看到 —— `SCROLL_QUICK_PANEL_BACK` 仅 2 SUCCESS / 1 FAILURE，
且那两次成功之后的目标轮转走了（该族本就稀疏，约 20 次/天）。**机制已在设备上成立，目标级收益待累积。**

## 4. 下一步计划

**顺序不能颠倒**，这是本轮学到的东西：

1. **`OPEN_BUILDING_UPGRADE` 残留 30 条**（`page_after=BUILDING, upgrade_dialog_visible=None`）。
   模板层认了页面、也看到升级控件（`upgradeable=True`），而文本分类器只在模板说 `UNKNOWN` 时才跑
   （`ocr.py:5552`），所以那条标志永不被置。**修法**：让"页面由哪一层命名"都走同一条升级卡片证据
   （帧内版式 + 文本），使 `upgrade_dialog_visible` 不再依赖分类器是否运行。
   **为什么现在才做**：修它会让该步成功、路由继续走到**花费**——而那正是 `fa015b4a` 刚关上的门。
   **门先、导航证明后。**
2. **`SELECT_BEAST_TARGET_MAMMOTH`（45 行 / 45 全失败）** —— 见 §7 的纠正。
   现在的签名是**"点了、卡片没开"**（`before_visible: True, after_card: False`），
   与修复前"目标找不到"是**两种病**。第一条测量：那 8 张失败帧里，点击落点相对
   `after` 帧上卡片**存在与否**的关系（点到了什么）。
3. **重排家族**（用 `_family_fingerprint_scan.py`，数据根），再选下一个 —— 今天已修 5 个家族，
   排序会明显变化。

## 5. 未完成的改动

**代码侧：没有。** pin 工作树内本次会话的全部改动都已提交并 repin（§1、§2）。

**未提交但有意保留的**（都在**数据根** `E:\无尽冬日智能体\`，与约 180 个同类研究脚本并列；
这是本项目的既有做法，`_*.py` 是研究用探针、`tools/` 才是长期工具）：

| 文件 | 它是什么 |
|---|---|
| `_ab_quick_panel_row_routing.py` | 退役两个 MAA 节点所需的 A/B（**账本即可算，无需截图**） |
| `_retire_quick_panel_nodes.py` | 上一项的改法脚本（带前置断言） |
| `_finish_quick_panel_retirement.py` | 按先例删除 `recognition` 字典的收尾脚本 |
| `_probe_panel_tab_vs_scroll.py` | **证伪页签模型**的那条测量 |
| `_family_fingerprint_scan.py` | 家族排序（`(goal, skill, signature)` 计数） |

**本次会话写的交接文档**（数据根 `.workbuddy-ai/handoff/`，供人读，不作为代码交付）：
这些文件**未跟踪**，与该目录下既有的 18 个同类文件一致 —— 所以 `git log -- <它们>` 会是空的，
这是本项目的既有做法而不是本次的遗漏。**要提交的交接只有本文这一份**，它在 pin 分支上。
数据根是仓库的 `main` worktree，而按项目铁律 **`main` 是只读镜像、提交只能落在生产工作树的主线上**，
所以那些笔记留在工作树里。

```
A_BLIND_NODE_SHADOWED_THE_FRAME_20261005.md     退役两个 MAA 节点
THE_PANEL_COVERS_THE_BARRACKS_BAR_20261005.md   训练入口守卫（含页签假设被证伪的 OUTCOME 块）
THE_PANEL_TAB_SWITCH_20261005.md                页签能力（顶部 OUTCOME 说明它已被回退）
THE_SWEEP_LEFT_THE_PANEL_SCROLLED_20261005.md   可见带移回上方
THE_SPEND_NEEDED_AN_IDENTITY_20261005.md        花费的身份门
```

**有意不做的**（都写在各自交接文档里，不是遗漏）：
- 反向 hop（把面板切回野外）——没有目标需要。
- `QUICK_PANEL_TAB_WILDERNESS` 未配技能（**可达**但未接）。
- 给 `upgradeable` 带依据（`upgradeability_basis` 已存在、未带进 `WorldState`）——
  更好的修法，但需要模板层自己表态"它的命中值多少"，本轮没有足够证据定这件事。

## 6. 当前阻塞点

**没有硬阻塞**（pin 干净、验证全绿、生产在跑）。以下是**诚实的软阻塞**，每一条都会让下一位读者少走弯路：

1. **`repo_revision` 是子进程启动那一刻的 git HEAD，不是磁盘上的代码。**
   `run_live.py` 从 HEAD 取进程版本戳、却从**工作树磁盘**导入模块 ⇒ **未提交的就地编辑会产出
   "盖章为不含该行为的提交"的 episode**（本轮实测：一条 `SELECT_QUICK_PANEL_CITY_TAB`
   盖着 `c873ab0c`，而该提交里根本没有那个技能）。
   ⇒ **归因要用代码级论证**（"哪个读取器才可能产出这一行"），**不要只靠版本戳**。
2. **账本会被重写。** 同一天同一查询两次得到 108 与 107 行 ⇒ **现在测不到 ≠ 当时没发生**。
   "存活数据里不存在某形状"只能写成**不置可否**，不能写成"它不成立"。
3. **"只差一个标志就能过"的验证器，不一定是识别问题。** 本轮的顺序是：先查**那个动作被什么授权**、
   那个字段**有几个写入者、依据强度是否相同** —— 由此撞到一条从未发生、只被"顺序的偶然"挡住的**花费路径**。
4. **两处已知的"主张 vs 测量"缺口**：
   - 可见带的对偶手势**方向**是"段在带上方"的**主张**，不是测量。若某帧段在带**下方**，swipe 会走错
     （验证器会拒、上限 3 次会停，但那是**成本**不是已处理）。
   - 只有 **2 行可见**的帧建不出手势（带宽 <3 行 / <0.12），那一步**派发不出去** —— 诚实，但目标得不到服务。
5. **SAFE_STOP 的措辞仍写着 `tab`**（`quick_panel_is_open_on_a_tab_without_the_training_entry_…`），
   而测量说这一切**与页签无关**。设备确认后应改名。

## 7. 最近一次验证结果

**测试与 A/B**

| 项 | 结果 |
|---|---|
| 最后一次改动的定向回归 | 17 个文件（提到 `BUILDING_UPGRADE`/`upgradeable`/`Page.BUILDING` 的），**按失败测试名**比对：两臂各 **16** 条失败、**对称差为空** ⇒ **0 新红** |
| 为什么按名字比对 | 该改动**动了测试文件**，收集顺序与条数变化 ⇒ **位置比对失效**（这是上一轮踩的坑） |
| 基线臂的做法 | **连测试一起回退**（`git checkout` 源码 + 两个测试文件），使比较是"改动前 vs 改动后"而非混合状态 |
| 恢复校验 | `brain.py` 恢复后 `sha256 5f02a85e…`、门存在 |
| 变异验证（本轮两处） | 均在**副本**上做、**先跑未变异对照**（15/15 绿）；各变异**恰好 1 条**红 |
| `gui_wiring_verify` | 19/19 wired and matching |
| `check_mainline` | `MAINLINE_OK` |

**方法学（本轮新增，已进技能）**

- 判"一块界面是**一条列表**还是**几组**" → 用**共现结构**（可见区段集合 × 可见行键集合），
  **不要靠看一帧**；两组的键大量共现 ⇒ 一条列表。
- **同一个条件，在不同"主张"下真假不同**：判据必须与主张同层。
  "城市段从无到有"用来证明"页签切换了"是**假**、用来证明"可见带移回上方了"是**真**。
- A/B 里出现 `>`（只在改动臂红）时，**先读那条测试的 docstring 有没有"某次测量"**：
  若它钉着既定行为，**错的是修复**，应取**两种证据都接受的最窄改动**，而不是改测试。

**生产观测（截至 20:2x，GMT+8）**

| 家族 / 技能 | 修复后 | 判读 |
|---|---|---|
| `SELECT_GIANT_BEAST_TAB` | 175 行：146 失败全部在修复前；**修复后 29 行全 SUCCESS**（末行 12:19:16） | **确实修好了** |
| `OPEN_TASK_FROM_QUICK_PANEL_*`（退役节点的两个家族） | 09:00 起 **13 SUCCESS / 4 FAILURE** | 生效（此前面板开着的帧 0/60） |
| `OPEN_INFANTRY_TRAINING` | 09:30 起 **2 SUCCESS / 0 FAILURE** | 守卫 + 带移动生效 |
| `SCROLL_QUICK_PANEL_BACK` | **2 SUCCESS / 1 FAILURE**；首次尝试 `10:48:38` 即 SUCCESS，evidence 里 `moved_down`（+0.143 等）与 `revealed_above` **同时命中** | 机制在设备上成立；**目标级收益待累积** |
| `BUILDING_UPGRADE`（花费） | **0 行**（历史全量也是 0） | 现在由身份门**结构性**保证（此前只被"顺序的偶然"挡住） |
| `building_upgrade_needs_a_known_identity` | **尚无 tick** | 门就位后尚未遇到那种状态；**未测**，不是"不需要" |
| `SELECT_BEAST_TARGET_MAMMOTH` | 45 行 / **45 全失败** | ⚠️ **纠正**：早先"该家族已 0 行"只在当时窗口内成立。修复后它带着**新签名**回来了 —— `BEAST_TARGET_SELECTION_NOT_PROVEN`，`before_visible: True, after_card: False`，即**标签找到了、点击后卡片没开**。与修复前"目标找不到"是两种病 |
| `SELECT_BEAST_TARGET_LABELLED` | 57 行 / 38 失败 / 19 成功，末行 07:33（修复前） | 修复后**休眠**，未测 |
