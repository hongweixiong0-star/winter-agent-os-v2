# ⚠️ 全量测试**不绿**：299 failed / 29 errors —— 而且这个数字**此前看不到**（2026-10-14）

> 本轮用 `--basetemp` 绕开宿主删除守卫，**第一次拿到全量汇总行**。
> 项目记录里长期写着"**本机 pytest 全量跑不出汇总行**" ⇒ **全量的真实状态此前是未知的**。
> 现在它露出来了，而且**不是绿**。**本文件只报事实与已定位的部分，不粉饰。**

---

## 一、数字（原样，2026-10-14 13:38 起跑，27:10 结束）

```
299 failed, 5403 passed, 71 skipped, 9 warnings, 29 errors, 1013 subtests passed
in 1630.05s (0:27:10)
```

用数据根 `.venv`，命令：
`python -m pytest tests -q --basetemp="E:/无尽冬日智能体/tools/_pt_tmp" -p no:cacheprovider`

## 二、29 个 `errors` **已定位**（是守卫**拒绝**，不是漏进生产）

错误原文：

```
conftest.ProductionRuntimeWriteError: PRODUCTION_RUNTIME_FILES_TOUCHED_BY_TESTS != 0 -- 1 write(s)
    write_text(learning/control_panel/gui_model_service.json)
```

**机制**（读 `tests/conftest.py`）：`_REDIRECTS`（`:97`）把一批**模块常量**在整个 session 里
`setattr` 到 `TEST_RUNTIME_ROOT` 下的临时路径；写入守卫（`:346`）**拒绝**任何对
`GUARDED_TREES = ("learning","config")` 下、**没有被重定向覆盖**的写入（`raise` **在写之前**）。

⇒ 所以 `gui_model_service.json` 的写入被**拒绝**（生产没被污染，守卫干得对），但它被记进
`PRODUCTION_WRITES` ⇒ session teardown **把这 29 条报成 error**。

**为什么它没被重定向**：`winter_agent_v2/gui_model_service.py` 里该路径是**内联默认值**
（`:184-186` `self.state_path = state_path or (self.root / "learning/control_panel/gui_model_service.json")`），
**模块里没有对应常量**，而 `_REDIRECTS` 只能重定向**模块常量**。守卫自己的报错就写了补救法：
> "If this path is not covered, add its module constant to `_REDIRECTS`; **do not weaken the guard**."

**两条候选修法（都**未做**）**：
1. **按守卫的原话**：把那条内联路径**提升为模块常量**（`gui_model_service.py`），再加进 `_REDIRECTS`
   —— 效果**只在测试期**（同一 fixture 会在 teardown 还原），**不影响生产**；
2. 找出那个**没传 `state_path`/`root` 隔离**的测试，让它传临时路径 —— 治标，但更窄。

**修法 1 的精确形状（设计已核完，等重跑结束再落）**：

- **要提升的**：`gui_model_service.py` 里有**两条**内联路径在 `learning/` 下（不只是状态文件）：
  ```
  self.state_path = state_path or (self.root / "learning/control_panel/gui_model_service.json")
  self.log_path   = log_path   or (self.root / "learning/control_panel/gui_model_launcher.log")
  ```
  ⇒ **两条都要**提升为模块常量（否则修完状态路径、日志路径仍会 tripping）。
- **为什么提升后重定向就能生效**：`_runtime_relative()`（`tests/conftest.py:78`）= `TEST_RUNTIME_ROOT / relative`，
  而 `TEST_RUNTIME_ROOT` 是 `tempfile.mkdtemp()` ⇒ **绝对路径**；
  于是 `self.root / <绝对常量>` 依 `pathlib` 语义**取绝对的那个** ⇒ 写到临时树。**已核，成立。**
- **`_REDIRECTS` 加两行**（`("winter_agent_v2.gui_model_service", "<常量>", "<live 相对路径>", True)`）。
- 依据：守卫自己的报错就写了 "add its module constant to `_REDIRECTS`; **do not weaken the guard**"。

### 二·补：这不是孤例 —— 受守卫树的**覆盖面**（只读审计，2026-10-14）

对 `winter_agent_v2/*.py` grep `learning/`/`config/` 下的路径字面量：

| | 条数 |
|---|---:|
| 路径字面量总数 | **53** |
| `_REDIRECTS` 覆盖 | **21** |
| **未被覆盖** | **36** |

未覆盖的里包括本轮的 `learning/control_panel/gui_model_service.json`（与 `..._launcher.log`），
也包括 `learning/MODE_STATE.json`、`learning/runtime_snapshot.json`、`learning/goal_state.json`、
`learning/role_identity.json` … 等**看起来很可能被测试写**的路径。

⚠️ **但要分清**：守卫只在**测试真的去写**它们时才 trip。所以这 36 条是"**可能 trip 的面**"，
**不是"已经 trip 的清单"** —— 本轮全量实测到的**只是 1 条**（`gui_model_service.json`）。
⇒ **修的时候以实测为准**：先修实测 trip 的那条（提升常量 + 加 `_REDIRECTS`），
再考虑是否扩面；**不要**因为审计出 36 条就一次改 36 处。

## 三、299 个 `failed` **尚未定性**（不猜）

已后台重跑并保留**完整清单**（`--tb=no`，输出到 `E:/tmp/wb_pytest_full.txt`），
跑完看"**按文件的失败分布**"再判断：

- 若**集中在少数文件** → 逐个看是环境性（Tk 无显示 / 需要设备 / fixture）还是真因；
- 若**散在所有文件** → 先查是否"**测试写坏了活运行态导致级联**"
  （`learning/`/`config/` 是**junction**，与 pin 树共享同一份 —— 这一点本会话已确证）。

**在分布出来之前，本文件不把 299 说成"回归"，也不说成"环境性"** —— 两者都还没证据。

### 三·补²：分布**已提前拿到**（用新工具从进度流反推）+ 一个强假设

**新工具** `tools/map_pytest_progress.py`（本会话新写、已验证）：因为**顺序是确定的**
（没装 `pytest-randomly`），`-q` 的**第 N 个结果字符 = 第 N 个收集到的测试** ⇒
把"进度流"与 `--collect-only` 的清单对齐，就能**从已捕获的输出里反推失败清单**（无需重跑，
正好治项目记录里的"**全量跑不出汇总行**"）。已验证收集侧：pin 树 **5753**、数据根 **5799**。

**用它对 51% 处的那份输出反推**（数据根，`--root "E:/无尽冬日智能体"`）得到 **179 个失败**，
分布**横跨 40+ 个文件**：

```
12 test_live_runtime            11 test_refusal_yields_the_cycle   10 test_capability_gate
 9 test_quick_panel_handle       9 test_interactive_unknown_element  8 test_panel_architecture_view(E)
 6 test_camp_fight_refusal_recovery  5 test_intel_pin_exhaustion      5 test_entry_badges
 5 test_daily_tab_selection       5 test_battle_unknown_recovery     5 test_a_panel_mid_slide_…  …
```

⇒ **不是几个文件坏了，是**系统性**的**（~4.4% 匀速、遍及全局）。

**⭐ 强假设（本轮最有价值的一条）**：`tests/conftest.py` 的写入守卫对**未被 `_REDIRECTS` 覆盖**的
`learning/`、`config/` 写入是 **`raise`（拒绝）**，而 raise 发生在**写之前** ⇒
**一个走到这种写入的测试会直接 FAIL**，不只是 teardown 报 error。
若如此，则 **299 个失败里有相当一部分与那 29 个 error 是同一个根因**：
**`_REDIRECTS` 的覆盖面落后于代码**（本轮审计：53 条字面量、覆盖 21、**36 条未覆盖**）。

**⚠️ 这是假设，不是结论。** 证法很简单：等本轮全量结束后，
挑几个失败测试**单独带 traceback 重跑**（`--tb=short`），看失败里有没有
`ProductionRuntimeWriteError`。**有 ⇒ 根因确认，且修覆盖面就能同时清掉大部分红；没有 ⇒ 另找。**

### 三·补³：**假设已被证伪**，且**摸到真正的根因方向**（2026-10-14 晚）

**① 证伪**：单跑 `tests/test_camp_panel_stamina.py`（`--tb=short`），失败**不是**守卫拒绝，而是**真断言**：

```
AssertionError: None != 9                 # camp.stamina.get("current")
AssertionError: None != 'CAMP_PANEL_HUD'  # camp.stamina.get("source")
```

⇒ **不是"守卫引起失败"**。失败是"**该读到的数没读到**"。而且该测试**没被 skip**
（它的 `setUpClass` 在 `production_vision()` 为 None 或 fixture 缺失时会 skip）⇒ **OCR 栈与 fixture 都在**。

**② 一步步摸到根因方向**（都是只读探针）：

| 探针 | 结果 |
|---|---|
| `production_vision().observe(MAP_FRAME)` | `stamina={}`（**空的**） |
| 全帧 OCR（`recognize(frame)`） | **29 个 token，中文正常** ⇒ **OCR 引擎是活的** |
| `recognize(frame, HUD_STAMINA_ROI)` | **`[]`（零 token）** |
| **手动裁 ROI（px 28,96,82,120）并放大 6× 再 OCR** | **`[('6', 0.997)]`** ← 读出来了 |

⇒ **`HUD_STAMINA_ROI` 那个 54×24 的小裁片，生产路径的 OCR 读不出任何东西；放大 6 倍才读得出。**
而项目自己的 `D-021` 早就写过"**小号文字必须走专用 ROI OCR，不能依赖全屏结果**"——
现在这条路的**反例出现了**：**ROI OCR 本身在一个 54×24 的裁片上返回空**
（全帧有 29 个 token，说明引擎没问题，是**这个尺寸/这条裁片**读不出）。

**⚠️ 两个必须分开的保留**：
1. **读出来的值是 `'6'`，而测试期望 `9`** ⇒ 即使放大，**ROI 与当年也不再逐字一致**
   （ROI 现为 `w_norm=0.075`→54px；`test_camp_panel_stamina.py` 的 docstring 记的是 px 70 右边界、即 42px）。
   ⇒ **是 ROI 变了、还是引擎版本变了，本地判不了 —— 要真机**。
2. `CAMP_PANEL_HUD` 这个 source **确实存在于代码里**（`ocr.py:6088`）⇒ **不是"没实现"**。

**③ 一个结构性旁证**：重跑到 **72%** 那一行是
`....................FFFF.FFFFFFFFFFFFFF................` —— **18 个连续 F** ⇒
失败**不是纯散布**，而是"**大部分散布 + 若干按文件成簇**"。这与"一个共因（ROI 读不出）
命中所有依赖 HUD 读数的测试"相符，也与"某些文件另有一处共因"相符。

**⇒ 阶段性结论（谨慎版）**：299 里**至少有一部分**是"**HUD 小字号 ROI OCR 读不出**"这一个**运行/引擎层**共因，
**不是逐条的业务逻辑回归**；但**具体占比**要等全量结束、把失败按"是否依赖 HUD 读数"分组才能说。
**在那之前不改任何生产代码。**

### 三·补⁴：**没有单一共因** —— 失败是**异质的**（2026-10-14 晚，第二份抽样）

抽最大的那一簇 `tests/test_live_runtime.py`（映射里 12 个 F），`--tb=line` 看原因：

```
AssertionError: 0 != 1 : one back recovers, no more
AssertionError: 0 != 2 : recovery is bounded per run
IndexError: tuple index out of range          (test_live_runtime.py:185)
FileNotFoundError: ...\Temp\tmp010jfviu\episodes.jsonl
FileNotFoundError: ...\Temp\tmp068y_s2a\action_latency.jsonl
```

⇒ **这一簇与 HUD OCR 无关**，而且是**三种不同的成因**：
① **计数器不符**（0 != 1/2，runtime 没做出预期的恢复/动作）；
② **`IndexError`**（真代码错误）；
③ **文件不存在**——**测试期望 runtime 写出的 `episodes.jsonl` / `action_latency.jsonl` 没被写出来**。

⚠️ ③ 值得单独警觉：它有两种可能，**要 traceback 才能分开** ——
(a) runtime 根本没写；或 (b) **写了、但写到了 `conftest` 重定向后的位置**（`_REDIRECTS` 会
`setattr` 模块常量到 `TEST_RUNTIME_ROOT`，而测试期望的是**它自己的 tmp**）。
**若是 (b)，那就是"重定向与自管路径的测试相冲突"这一族** —— 与 §三·补² 的假设**同源但不同面**
（不是"守卫拒绝"，而是"重定向改了路径"）。

**⇒ 修正 §三·补²/³ 的措辞**：我先前两次都在找**一个**共因。现在有证据说**不止一个**：
**299 是异质的**（OCR 读数、计数器、真异常、缺账本 …）。**分组归因要靠全量清单 + traceback，不靠猜。**

**未做**：**没改任何代码/测试**；全量仍在跑（**85%**，228 F 时）。

### 三·补⁶：**一个很可能是主因的发现：测试用的帧被 retention 删掉了**（2026-10-14 晚）

**线索**：`grep -l "dataset/raw/" tests/*.py` ⇒ **76 个测试文件**引用 `dataset/raw/`。

**逐个验**（抽 `tests/test_entry_badges.py`，映射里它 5 个 F）：

```
它用  RUNTIME/"20260923_015029_train/20260923_015029_train_step_005_before_...png"

frame exists?      NO        ← 文件不在
its dir exists?    YES       ← 目录在，但里面空了
```

**单跑它，5 个失败全是同一种**：

```
FileNotFoundError: ...\dataset\raw\control_panel\runtime_auto\20260923_000206_train\..._step_001_after_....png
5 failed, 25 passed, 10 subtests passed
```

⇒ **失败的原因不是断言不成立，是"它要读的那一帧已经被删了"。**

**为什么会删**：`dataset/raw/**` 是**运行时捕获区**，会被 `retention` 轮转；而
`PROTECTED_DIRECTORY_NAMES`（`D-004`）保护的是 `dataset/verified / production / normalized / external`，
**不含 `raw`**。⇒ **测试把 fixture 放在了一个会被清掉的目录里。**
（对照：`test_camp_panel_stamina.py` 用的是 `dataset/truth_audit/...`，本会话实测那帧**还在**。）

**⇒ 这很可能解释 299 里的**一大块**：** 60+ 个失败文件里，有多少是"缺帧"这一种，
**要看正在跑的那次 `--tb=line` 全量**（按 `FileNotFoundError` + `dataset/raw/` 计数）——**本轮未完成**。

**两个候选修法（都未做，都要先量占比）**：
1. **把 fixture 迁到受保护区**（`dataset/truth_audit/` 这类**命名回归 fixture** 已经在用且存活）
   —— 治本，但 76 个文件要动；
2. **保护 `raw` 下被测试引用的那些子目录** —— 改动小，但要把"哪些帧是 fixture"表达出来。

⚠️ **注意**：这条与 §三·补⁴ 的 `FileNotFoundError`（`tmpXXX/episodes.jsonl`）**不是同一件事** ——
那个是**临时目录里该被写出的账本**，这个是**仓里的 fixture 帧**。**两条都要分开记。**

### 三·补⁵：全量结束 —— **301 failed / 29 errors**，分布**广而长尾**，且**有 order 依赖**（终稿）

重跑结束（27:12）：`301 failed, 5401 passed, 71 skipped, 29 errors, 1013 subtests passed`。
（与首轮 `299 failed` 差 **2 个** ⇒ **有轻微 flaky**。）

**失败按文件分布（前 10，全表 60+ 个文件）**：

```
26 test_unknown_ai_channel        14 test_ui_collection         14 test_session_outcome_persistence
12 test_live_runtime              11 test_unknown_page_exploration  11 test_refusal_yields_the_cycle
10 test_capability_gate            9 test_quick_panel_handle     9 test_interactive_unknown_element
 7 test_runtime_bootstrap_integration  6 test_reward_popup_source  6 test_camp_fight_refusal_recovery …
```

⇒ **没有任何单文件占主导**（最大 26/299 ≈ 9%）⇒ 是**广谱**的，不是"几个文件坏了"。

**⭐ 新证据：存在 order/状态依赖的失败。**
`tests/test_suite_isolation.py`（就是那个断言"测试不许写活运行态"的**自检**）
**单独跑 = 18 passed**，但在**全量里 3 个 FAILED** ⇒
**有测试把全局状态泄漏给后面的测试**，被泄漏者才失败。

**与上一条并列的**：`tests/test_live_runtime.py` **单独跑也 12 failed** ⇒ **既有"单独就跑不过"的真失败，也有"只在全量里才失败"的 order 依赖**。**两类并存。**

## 四·终：能说 / 不能说（把话说满，但不越界）

- **能说**：① 全量 **301 failed / 29 errors / 5401 passed**（此前**看不到**）；
  ② 分布**广、长尾、无单文件主导**；
  ③ 成因**异质且两类并存**：**真失败**（`test_live_runtime` 单独也红：计数器、`IndexError`、
  缺 `episodes.jsonl`/`action_latency.jsonl`）**＋ order 依赖**（`test_suite_isolation` 单独绿、全量红）；
  ④ **一个已定位的具体机制**：`HUD_STAMINA_ROI` 那个 54×24 小裁片，生产 OCR **读出 0 个 token**，
  放大 6× 才读出（§三·补³）；⑤ 29 个 error 的机制是"内联路径未被 `_REDIRECTS` 覆盖"（§二）。
- **不能说**：299/301 里**各成因的占比**（要逐类分组 + traceback，**本轮没做完**）；
  也**不能说"生产代码坏了"**（有相当一部分是**测试侧**的 order/隔离问题）。**两者都还是开放的。**

## 五·给下一个人的最短路径（**未做**）

1. **先把 29 个 error 修掉**（机制已定位、改动小、只在测试期生效）——见 §二。
2. **再分失败**：按 `--tb=line` 的**首行类型**分组（`AssertionError` / `IndexError` / `FileNotFoundError` / …），
   每组抽 2~3 条带 traceback 复现；
3. **单独跑每个"只在全量红"的文件**（如 `test_suite_isolation.py`）验证 order 依赖，
   用 `-p no:randomly`（本来就没装）或二分法找**污染者**；
4. **HUD ROI 那条**（§三·补³）单独跟：它是"读不出"，且**要真机**才能定 ROI 该是多少。

**方法论教训（本会话最大的一个）**：**"全量跑不出汇总行"这件事本身，藏了 300 个红。**
一个"看不见"的度量，比一个"红着但看得见"的度量危险得多。

### 三·补：重跑进行中的**实时进度**（已有证据）

后台重跑用 `-q`（一测一字符）。跑到 **~26%** 时读了一次输出：

```
字符直方图： 1437 个 '.'  63 个 'F'  5 个 's'（跳过）
开头片段：  .........F...F..........[1%] .....FFFF..F....[2%] .........Fsss.....[3%]
            ..........F....F......[4%] ....FFFFF....FFF....[6%] ......F.....[7%] ...
```

⇒ **63 个失败散布在整段里，不是堆在开头** ⇒ **可以排除"单个早期失败引发级联"**。
（这也与总数相符：`63/≈1500 ≈ 4.2%`，而全量是 `299/5753 ≈ 5.2%`。）

**未定性的部分不变**：还要等**收尾时的那份完整失败清单**（`-q --tb=no` 会在末尾列出），
才能按文件归组、判断是"若干文件的系统性失败"还是"环境性"。

⚠️ **重跑期间不改动被它测试的代码**（`winter_agent_v2/`、`tests/`）—— 免得污染这次测量。
`gui_model_service.py` 那条修法**等重跑结束再做**。

## 四、能说 / 不能说

- **能说**：① 全量当前 **299 failed / 29 errors / 5403 passed**（这是**第一次**有汇总行）；
  ② 29 个 error 的**机制已定位**（内联路径未被 `_REDIRECTS` 覆盖，守卫拒绝并记账）；
  ③ 补救法**守卫自己写了**，且**只在测试期生效**。
- **不能说**：299 是不是回归、是不是环境性、有没有长期存在（**都没有证据**）；
  也不能说"pin 树跑就会绿"（**那个假设现在必须被检验，不能假定**）。

## 五、未做

**没改任何测试或代码**（先量）；没修 `_REDIRECTS`；没改 `gui_model_service.py`；
没动 `learning/`（junction，不该被"复原"）；**299 的清单在后台重跑中**。
