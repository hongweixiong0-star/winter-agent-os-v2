# 巨熊：识别资产**在**，但**没人读**（2026-10-14 复核）

> 操作者最高优先级的链。本轮把"资产有没有"与"有没有人消费"分开量了一遍，
> 结论与台账的诊断**方向一致、层次更深**：
> **卡住的不是没有模板，而是（a）OCR 门形状不对，（b）模板语义没有任何消费者。**
> 另外：我这一轮**两次读错自己的检查**，都记在下面。

---

## 一、先更正我自己：那 14 个语义**都有模板**

`dataset/candidate/template_manifest.json`（383 KB，475 条记录，`status: CANDIDATE`）
里，本文件 `CASES` 点名的 **14 个巨熊语义各有一条模板**：

```
BTN_ALLIANCE_WAR 1 · TAB_RALLY_LIST 1 · TARGET_BEAR_TRAP 1 · ROW_TARGET_BEAR_COLUMN 1 ·
STATUS_RALLY_COUNTDOWN 1 · BTN_JOIN_ROW 1 · BTN_AUTO_JOIN 1 · BTN_START_RALLY 1 ·
POPUP_TITLE_START_RALLY 1 · BTN_CONFIRM_START_RALLY 1 · BTN_BEAR_GO 1 ·
STATUS_BEAR_WINDOW 1 · PAGE_TITLE_MARCH 1 · BTN_CONFIRM_MARCH 1
```

**我两次读错**（都记下来，因为都是"先看一条/看错一层就下结论"）：
1. 第一次我按**嵌套字典的键**搜语义名 → 报 `NONE`；实际记录是**扁平的**，语义在 `semantic` **字段**里。
2. 更早我还以为记录有 `templates` 键（`r.get("templates")`）→ 报"0 条有模板"；
   实际每条记录**本身就是一条模板**（`template_path` / `roi_norm` / `parent_screenshot` / `parent_sha256`）。

## 二、那个探针**把自己的数据报成了反的**（已修）

`tools/_bear_replay_verify.py` 修前输出 `clean separation: 0/14`，全部 `NO_TEMPLATE`。
但它同一张表里印的是 **`POS=0`, `NEG=None`** —— 即**正帧命中（距离 0）、负帧完全没命中**，
**这是最好的结果**（它自己的 docstring 就写着负帧"must miss"）。
原因：判据写的是 `if pd is None or nd is None: NO_TEMPLATE` —— **要求负帧的距离是个数字**，
于是把"负帧根本不命中"判成了模板缺失。

**已修**（只改判据与输出，未动任何资产）：
- 负帧 `None`（不命中）**计入分离**（最强的一种）；
- 正帧 `distance == 0` 标注为 **`exact self-match`** —— 因为裁剪**来自那一帧本身**，
  这只证明"裁对了"，**不证明**它能泛化到同一控件的另一次捕获。

**修后实测**：
```
separated: 14/14   (of which exact self-match: 14)
ambiguous: 0   missed its own parent: 0
```
⇒ **14 个模板都裁对了、都拒绝了负帧；但 14 个全都是自匹配 ⇒ 泛化能力未测。**

## 三、本轮的新发现：**3 个巨熊专属语义注册了却没有任何消费者**

对 `winter_agent_v2/` 全量搜索这些语义名：

| 语义 | 生产代码里的引用 |
|---|---|
| `TARGET_BEAR_TRAP` | **0** |
| `STATUS_BEAR_WINDOW` | **0** |
| `BTN_BEAR_GO` | **0** |
| `TAB_RALLY_LIST` | **1**（`vision.py:2455`，已接线） |

⇒ 巨熊**陷阱/窗口**这三个语义**模板存在、裁剪正确、负帧拒绝，但没有任何地方读它们**。
这正是项目自己的话（§三·八 第十五条）："常见真相是**机制已经有，只是没接线** / … / **字段没人消费**"。

**所以"窗口一开认不出"这条链的完整形状是三件事，不是一件**：
1. `ocr.py:1175-1184` 的**文字门**是为"还没开窗"建的（窗口内给的是『集结』+ 到结束倒计时，
   且标签被 OCR 读成 `o将猎陷阱`）—— **形状不对**；
2. **模板这条路没人走** —— `TARGET_BEAR_TRAP` / `STATUS_BEAR_WINDOW` / `BTN_BEAR_GO` 零消费者；
3. **泛化未测** —— 现有 14 条全是自匹配，**换一帧就不知道还认不认**。

## 四、能说 / 不能说

- **能说**：巨熊的识别**素材齐、裁得对、负帧拒绝**（14/14）；三个专属语义**没接线**；
  台账要求的"新帧"仍然合理 —— 但**理由比台账写的更窄**：不是"没有一帧能证明"，
  而是"**没有一帧是另一次捕获**"（现有帧都是模板的来源帧）。
- **不能说**：这三个语义**没接线**是缺陷还是**刻意**（没有读到说明）。
  下一手应当先查"为什么注册了却不接"（是被更早的决定搁置，还是漏了），**再谈接线**。
  **本轮没有接线**：接哪条消费者是设计决定，且要先回答上面这个问题。

## 五、本轮改了什么（仅此一处）

`tools/_bear_replay_verify.py` 的判据与输出（含 docstring 里"这份回放能/不能得出什么"）。
它**没有被任何测试或文档引用**（全仓库搜索：0 处），所以改动风险低。
**没有**改模板、**没有**改 `ocr.py`、**没有**改清单、**没有**动设备。

## 六、⚠️ **更正第二节**（同日补测）：坏的是**被忽略的那份副本**，项目自己的工具一直是好的

第二节我写"那个探针把自己的数据报成了反的"。补测发现**盘上有两个同名用途的文件**：

| 文件 | git 状态 | 输出词汇 | 实测 |
|---|---|---|---|
| `tools/verify_bear_templates_replay.py` | **UNTRACKED**（5,519 B，**无任何提交历史**；见 §十更正） | `discriminating / ambiguous / not_registered` | **`discriminating: 14/14   ambiguous:0   not_registered:0`**（2026-10-14 重跑复核） |
| `tools/_bear_replay_verify.py` | **IGNORED**（4,374 B，`.gitignore:442` 的 `/tools/_*.py`） | `OK / NO_TEMPLATE` | 修前 `0/14 NO_TEMPLATE` |

⇒ **`0/14 NO_TEMPLATE` 只出现在被忽略的那份副本里**；另一份**一直打印
`14/14 discriminating`**，与 `11_GITHUB_BEAR_SEARCH.md:270-286` 记录的当年运行**逐行一致**
（但**它并不在库里** —— 我上一轮把它写成 `TRACKED` 是**错的**，更正见 §十）。
⇒ 所以我上一轮那句"探针把自己的数据报成了反的"**只对那份副本成立**，
而我**修的是副本，不是项目的工具** —— 后者从来没有这个缺陷。**这是本轮我的更正。**

（那份被忽略的副本已按上一轮改好，本地有效；但它不进库也不进镜像，
所以**别把它当成项目的回放工具**。）

## 七、顺带从 `11_GITHUB_BEAR_SEARCH.md` 读到的三件事（都影响判断）

1. **注册是写进 `template_manifest.json` 的** —— 而该清单**就是 `SemanticROIVision` 的加载源**
   （即 V2 现有识别链本身），doc 原话"**没有新建第二套识别器**"。
   ⇒ 所以"注册了"是真的；缺的不是素材，是**有人去问**。
2. **`TARGET_BEAR_TRAP` 的旧框曾经是错的**：doc 记着旧框 `(200,570,470,700)`
   "**命中巨熊插画本体，不是标题文字**"，并点明"它匹配的是**物种美术**，而**普通巨兽面板也会画巨兽**，
   这正是指令禁止的『**把普通集结误认成巨熊集结**』的**模板级成因**"。⇒ 后来已改正框。
3. **`distance` 是 pHASH 汉明距离**，正样本全为 0 = **同帧精确匹配**
   ⇒ 第二节那条"exact self-match 不等于泛化"的保留意见**对项目自己那份工具同样适用**：
   `14/14 discriminating` 证明的是"能把自己那帧与负帧分开"，**不是**"换一帧还认得"。

## 八、于是本文件的主结论不变，且更精确

**巨熊的 14 个语义：注册了、被项目自己的工具判为 14/14 discriminating；
但其中 3 个（`TARGET_BEAR_TRAP` / `STATUS_BEAR_WINDOW` / `BTN_BEAR_GO`）在
`winter_agent_v2/` 里零消费者。** 而**回放工具看不见这件事** ——
它比对的是"模板 ↔ 帧"，不是"模板 ↔ 消费者"。这正是 §三·八 第十五条的"**字段没人消费**"。

## 九、对"准时参战"的净影响

把阻塞点从"**没有模板**"更正为"**有模板、被回放判为可区分、但三个专属语义没人读**"，
外加另两件：**`ocr.py` 文字门形状不对**、**泛化未测**（要一帧新捕获）。
第三项要**设备**；前两项是**代码侧**。
但按第五节的结论：**"为什么注册了却不接"要先查清**（本轮只查到 2026-09-2x 的注册与回放记录，
**没有读到"刻意不接"的决定** ⇒ 暂时只能记为**未接线，原因未证**）。

## 十、⚠️ **同日第二次更正：那份"一直好的"回放工具，其实不在库里**

§六 我把 `tools/verify_bear_templates_replay.py` 写成 **`TRACKED`**。**2026-10-14 复核推翻了它**：

| 检查 | 结果 |
|---|---|
| `git ls-files tools/ \| grep -i bear` | 15 条，**不含** `verify_bear_templates_replay.py` / `register_bear_rally_templates.py` / `audit_bear_capability_inventory.py` |
| `git log --all -- tools/verify_bear_templates_replay.py` | **空** ⇒ **从未在任一分支提交过** |
| data-root `git status --porcelain tools/` | 该文件是 **`??`（untracked，且未被 ignore）** |
| pin 树（生产 pin） | 该文件 **不存在**（`ls` 报 No such file） |

⇒ 真实状态：**`verify_bear_templates_replay.py` 是被 untracked 的本地文件，只活在数据根
`E:\无尽冬日智能体` 里；它不在 pin 树、不在镜像、不在 git。** 而 §六 的"项目自己那份（tracked）"
**是错的** —— 两份副本**都不在库里**（一份 ignored，一份仅 untracked）。

**为什么之前没被发现**：`verify_pin()` 只检查 **pin 树**；数据根的 untracked 文件**不影响
`WORKTREE_CLEAN`**（实测 pin 树 `WORKTREE_CLEAN=true`），所以这个"只在数据根"的状态**一路静默**。

### 这对证据意味着什么

1. **`14/14 discriminating` 不可从库里重现**：新克隆 / pin 树里**没有这个工具**。
   本轮用项目 `.venv` 重跑，数字**复现**（`bear pack registered: 14/14`、
   `discriminating: 14/14   ambiguous:0   not_registered:0`）—— 但那复现的是**我这台机器的本地文件**。
2. **这份工具可能丢**：它只存在于数据根工作目录，没有版本控制。
3. ⚠️ **不要**据 §六 把"14/14"当成"库里有据"的证据引用。

### 顺带更正一个我自己的假说

我曾猜 `knowledge/game/bear_ui_coverage.json` 把 `BTN_BEAR_GO` / `STATUS_BEAR_WINDOW` 标
`HAVE_AND_WIRED` 是**假的覆盖声明**。**读它的 `status_vocabulary` 后否掉了**：
该文件自己定义 `HAVE_AND_WIRED = "有素材且已接入识别链（manifest 里有记录，且离线回放能解析）"` ——
是**素材侧**的定义，**不是**"生产消费它"。⇒ 该文件**没有**做假的覆盖声明，措辞是诚实的。

### 于是"为什么注册了却不接"的答案

**仍未证。** 本轮新增的只是**排除**两条路：不是被 `bear_ui_coverage.json` 的假声明掩盖，
也不是"没有回放工具所以没接"。三语义在 `winter_agent_v2/` 里**零消费者**这条事实依旧成立，
且引用它们的地方**全在 `tools/`（且多为 untracked）**。

### 未做

没 `git add` 任何工具（是否把 untracked 的巨熊工具入库是**决定**：它们硬编码
`ROOT=E:\无尽冬日智能体`，且依赖被 `.gitignore` 排除的 `dataset/raw/**` 帧 ⇒ 入库**只能恢复逻辑、
不能恢复可重放性**）；没改 `template_manifest.json`、没改 `bear_ui_coverage.json`、
没动 `winter_agent_v2/`、没动设备。
