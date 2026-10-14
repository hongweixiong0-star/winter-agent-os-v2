# 修掉 29 个 error（写入守卫的覆盖面）＋ 一个副产品发现：**守卫在 pin 树里是瞎的**（2026-10-14）

> 承接 `THE_FULL_SUITE_IS_RED_AND_WHY_20261014.md` §二/§五第 1 步：**先把 29 个 error 修掉**。
> 修法与验证都做完了；过程中撞到一条**比 29 个 error 更要紧**的结构事实。

---

## 一、修法（3 个文件，小改；**只在测试期生效**）

| 文件 | 改动 |
|---|---|
| `winter_agent_v2/gui_model_service.py` | 把 `learning/control_panel/` 下那**两条内联路径**提升为模块常量 `DEFAULT_STATE_RELATIVE` / `DEFAULT_LOG_RELATIVE`，`__init__` 改用它们。**生产行为不变**（`root / rel` 与原来逐字相同）。 |
| `tests/conftest.py` | `_REDIRECTS` **加两行**，把这两个常量指向临时树。`seed=False`（**这条是承重的**，见下）。 |
| `tests/test_gui_model_service.py` | `test_a_missing_record_is_not_an_error` 显式传 `state_path=tmp_path/"never_written.json"`（与它下面的兄弟测试写法一致）。 |

**为什么 `seed=False` 是承重的**：重定向的目标是**绝对路径**，而 `GuiModelService` 把默认值
**接到调用方的 `root` 上**（`root / DEFAULT_STATE_RELATIVE`）；`root / <绝对>` 依 pathlib 语义**就是那个绝对路径**
⇒ **重定向会盖过调用方的 root**。于是若**播种**（把活文件拷进去），
一个"要自己的空 root"的测试就会读到**活的 16 条记录** ——
`test_a_missing_record_is_not_an_error` 恰好抓到了这一点（我第一次就是 `seed=True`，被这条测试挡下）。

## 二、验证（**必须在数据根做**，理由见 §三）

把三个文件临时拷进数据根跑（**守卫在数据根是生效的**）：

```
258 passed, 3 subtests passed in 40.94s      ← 0 failed / 0 errors
```

覆盖：`test_startup_semantics`（原 1 error）· `test_panel_architecture_view`（原 8 errors）·
`test_gui_model_service` · `test_local_gui_model_decoupling` · `test_local_planner`。
⇒ **这 29 个 error 的那一族被清掉了，且无回归。**（剩余约 10 个 error 是**另一种**成因：
`test_semantic_dictionary_upgrade` 要 `dataset/raw/...` 的一帧、而那帧不在——见 §四。）

## 三、⚠️ 副产品：**写入守卫在 pin 树里等于关闭**（比 29 个 error 重要）

`tests/conftest.py` 的 `classify_production_write()` 是这么判的：

```python
relative = Path(text).resolve().relative_to(ROOT).as_posix()
if relative.split("/", 1)[0] not in GUARDED_TREES:  # ("learning", "config")
    return None
```

**`Path(text).resolve()` 会跟随 junction。** 而 pin 树里 `learning/`、`config/` **正是指向数据根的 junction**
（本会话已在 `THE_FOUR_DATA_DIRS_ARE_JUNCTIONS_NOT_TWO_COPIES_20261014.md` 记过）⇒
`resolve()` 把路径解析到**数据根**，而 `ROOT` 是 **pin 树** ⇒ `relative_to(ROOT)` 抛 `ValueError` ⇒ **返回 `None`（不拦）**。

**干净对照实验**（不是推断）：
- pin 树 + **我的改动**：`test_suite_isolation.py` → **3 failed**
- pin 树 + **`git stash` 掉我的改动**（逐字回到 HEAD）：→ **仍然 3 failed**
⇒ **与我的改动无关**，是**树**造成的。
- 数据根 + **同样跑这个文件**：→ **18 passed**（守卫在那里生效）
- 现场读数：`classify_production_write(pin_ROOT/"learning/goal_state.json")` → **`None`**
  （同一个调用在数据根会返回该路径）。

**⇒ 结论**：
1. **只从 pin 树跑测试时，"测试不许写活运行态"这条 P0 保护是失效的** —— 而 pin 树的 `learning/`/`config/`
   **就是**活运行态（junction，与数据根同一份）⇒ **从 pin 树跑全量有真实风险**。
2. 这也解释了 `test_suite_isolation.py` 那 3 个失败在**全量（数据根）**里也出现：
   在数据根它是**顺序依赖**；在 pin 树它是**结构性**。**两种成因，同一个文件。**

## 四、能说 / 不能说

- **能说**：① 29-error 那一族**已修且已在数据根验证为 0**；② `seed=False` 的**理由**（重定向是绝对路径）；
  ③ **守卫在 pin 树里返回 `None`**（有现场读数 + stash 对照）。
- **不能说**：**剩余那约 10 个 error**（缺 `dataset/raw/...` 帧）能不能修——**要看那帧是否本机还在**；
  以及 pin 树里"守卫失效"是否还有**别的**后果（本轮只测了 `test_suite_isolation` 这一处）。

## 五、未做

**没提交 pin 树里那条"守卫看不见 junction"的修复**（改 `classify_production_write` 属**改守卫语义**，
应是操作者的决定，故只记录）；没改 `dataset/raw/` 的任何东西；没动那 10 个缺帧 error。
