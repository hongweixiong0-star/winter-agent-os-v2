# 数据根**不是它自己 HEAD 的检出**：测试少跑 192 条，且有 6 个测试**不在库里**（2026-10-14）

> 从上一轮的巨熊证据（工具不在库）顺下去，扩到"代码侧还有哪些被引用的东西其实不在库"。
> 结论比预期重：**数据根 `E:\无尽冬日智能体` 的 `tests/` 工作树停在 2026-10-08 之前**，
> 而它的 HEAD 是当前的 ⇒ **从数据根跑回归会少跑 192 条测试**；另有 6 个测试文件根本没进库。

---

## 一、怎么发现的

- 读 handoff `THE_BEAR_ASSETS_EXIST_AND_NOBODY_READS_THEM_20261014.md` 引用的
  `tests/test_runtime_capability_discovery_lane.py`（它被写成"钉着这条巷子"）——
  核实发现该文件 **`git cat-file -e HEAD:…` 不存在** ⇒ **未跟踪**。
- 于是把范围放大：**数据根与 pin 树，谁的 `tests/` 与 HEAD 一致？**

## 二、实测：两棵树的测试数不一样

| 树 | 分支 | `tests/` 工作树 | `pytest --collect-only` |
|---|---|---|---|
| **pin 树**（生产 pin） | `codex/production-pin-recovery` | **干净**（`git status` = 0） | **5753** |
| **数据根** | `main` | **19 个 tracked 测试被删、16 个是旧版** | **5561** |

⇒ **差 192 条。** 而且方向明确是"数据根更旧"：

- 全部 35 个差异文件的 diff 都是**删除多于新增**（合计 **4653 删除 / 51 新增**）⇒ 磁盘是旧版；
- 逐字证据：`tests/test_local_planner.py` 磁盘版是旧名
  `test_a_screen_cannot_consume_the_whole_run`，而 HEAD 是操作者 **2026-10-08 指令**更新后的
  `test_a_screen_is_stopped_by_no_progress_not_by_a_step_count`（`max_steps_per_run=5`）。
  ⇒ **数据根的 `tests/` 停在 2026-10-08 之前。**
- 对照组：**`winter_agent_v2/` 在数据根是干净的**（`git status` = 0）⇒ **代码是新的、测试是旧的。**

## 三、为什么一直没被发现

`check_mainline.py` 与 `WORKTREE_CLEAN` **只看 pin 树**（实测 pin 树 `WORKTREE_CLEAN=true`）。
数据根工作树的漂移**对这两把尺子完全不可见** —— 与上一轮那个"只在数据根的工具"**同一个盲区**。

## 四、本轮做的修复（可复现）

数据根的 `tests/` 差异**全是"磁盘更旧"**（含那 51 处新增也经逐行确认为旧版残留），
**没有任何本地新工作可丢** ⇒ 从 HEAD 恢复是安全的：

```
恢复前：5561 tests collected
git checkout -- tests/     # 数据根；index == HEAD
恢复后：5799 tests collected
```

**5799 = 5753（HEAD 的规范集）+ 46（下面 §五 那 6 个未跟踪测试）。**
⇒ 所以 **`66bf7630` 的规范测试数是 5753**。

## 五、残留：**6 个测试文件不在库里**（3 个还是红的）

数据根里仍有 6 个 `?? tests/*.py`（**全部不在 HEAD**）：

| 文件 | 结果 |
|---|---|
| `test_runtime_capability_discovery_lane.py` | 通过 —— **但 handoff 把它当"钉着"的测试引用**（见下） |
| `test_unknown_learning.py` · `test_role_goal_state_store.py` · `test_open_quick_panel_skill.py` | 通过 |
| `test_empty_task_page_recovery.py` | **失败**（1） |
| `test_template_lifecycle_precedence.py` | **失败**（2） |

跑这 6 个：**`3 failed, 43 passed`**。⇒ 它们是**本地草稿/WIP**，**不是库里的测试**。

⚠️ **证据完整性问题**：`tests/test_runtime_capability_discovery_lane.py` 在
`THE_LEARNING_BUDGET_CLAUSE_IS_UNREACHABLE_IN_PRODUCTION_20261014.md` 里被写成
"这条巷子有测试钉着（`tests/test_runtime_capability_discovery_lane.py`）"。
**它确实通过，但它不在库里** ⇒ 该"钉住"**不可从库里重现**（新克隆/pin 树都没有它）。
这与上一轮"回放工具不在库"是**同一族**：**引用的东西不在库**。

## 六、影响与建议（**未做**）

1. **回归计数取决于你在哪棵树跑**：pin 树 5753、数据根（恢复后）5799、
   数据根（恢复前）5561。**引用"N passed"时要说明树与 cwd**，否则数字不可比。
2. 数据根是 `.venv` 所在、也是文档里那条回归命令的 cwd
   （`03_NEXT_ACTION.md:1981`：`"E:/dongri-mumu-bot/.venv/Scripts/python.exe" -m pytest tests -q --basetemp="…tools/_pt_tmp"`）
   ⇒ **文档化的回归正是从数据根跑的** ⇒ 历史"回归通过"很可能是**在少 192 条的旧集上**测的。
   **建议**：要么固定从 pin 树（用数据根的 venv）跑，要么每次先 `git checkout -- tests/` 对齐。
3. **别把数据根里的 untracked 测试/工具当库里的**：它们不随镜像、不进克隆。

## 七、未做

没提交那 6 个未跟踪测试（**3 个是红的**，属草稿，提交会让套件变红）；
没删它们（可能是开发中的 WIP）；没动 pin 树；没动 `learning/`（50 个删除）与
`dataset/`（95 个修改）等**数据目录**（那是运行态，不擅自恢复）；
没改 `check_mainline.py` 或 `WORKTREE_CLEAN`（它们**按设计**只看 pin 树）。

## 八、跟进（2026-10-14 晚）：`tools/` 也一并复原了

同一把尺子 —— 数据根的**代码目录**会旧，而 `tests/` / `tools/` 是**真实目录（各自两份）**，
`winter_agent_v2/` 本来就与 HEAD 一致。`tools/` 原来有 **5 个 tracked-dirty**：

| 状态 | 文件 | 性质 |
|---|---|---|
| ` D` | `tools/explore_step.py` | 磁盘上被**删** |
| ` M` | `tools/invariant_review.py` | 只差**一个空行**（噪声） |
| ` M` | `launch_gui_model_server.py` · `profile_gui_model_context.py` · `register_daily_tab_template.py` | **净删除** ⇒ 磁盘是旧版 |

已 `git checkout -- tools/`（数据根）⇒ **tracked 部分现在与 HEAD 一致**，`explore_step.py` 已复原，
**79 个 untracked 草稿工具原样保留**（未动）。⇒ 数据根**代码目录**（`winter_agent_v2`/`tests`/`tools`）**全部对上 HEAD**。

⚠️ **仍在盲区的两类**：① 那 **6 个 untracked 测试**（3 个红，属草稿，**未提交也未删**）；
② **四个 junction 目录**（`knowledge`/`learning`/`dataset`/`config`）**不该被"复原"** —— 它们是共享运行态，
见 `THE_FOUR_DATA_DIRS_ARE_JUNCTIONS_NOT_TWO_COPIES_20261014.md`。

### `.gitignore` **不能一键复原**（它双向分叉了，本轮一个字没动）

数据根的 `.gitignore` **506 行**，HEAD 的 **575 行**，numstat `7 ins / 76 del`：

- **磁盘有、HEAD 没有的 7 行** = 一条 **`p2p_agent/src/` 忽略规则**（注释自称 "added 2026-10-07"）——
  即**本地新增、从未提交**（`git show HEAD:.gitignore | grep p2p_agent` ⇒ **无**）。
- **HEAD 有、磁盘没有的 76 行** = 一大块"运行时产物"忽略规则（`dataset/exploration/**`、
  `/dataset/raw/autogen/`、`/dataset/candidate/template_manifest.json` …，即 2026-10-06 收敛那批）。

⇒ **两边都不是对方的超集** ⇒ **`git checkout -- .gitignore` 会丢掉那条本地 p2p 规则**；
而直接提交它又会**未经确认地改变 ignore 行为** —— 因为 `p2p_agent/` 下**当前没有任何文件被跟踪**
（`git ls-files p2p_agent/` 为空），与那条注释"其余（config/adapter/…）照常跟踪"**不符**。
**所以本轮不动它**，只记录；要动，先确认那条 p2p 规则到底要不要。

## 九、那 3 个红测试**不是回归**（2026-10-14 晚，逐条看懂了断言）

数据根那 **6 个 untracked 测试**里红的 3 个，本轮读懂了它们在断言什么：

| 文件 | 断言内容 | 性质 |
|---|---|---|
| `test_template_lifecycle_precedence.py`（2 红） | 同一语义有 `CANDIDATE/VERIFIED/STABLE` 三条记录时，`vision.find` 应**按层优先**（先 STABLE、只在该层无命中才降到下层）。测试把 `_find_in_roi` 打桩，**在下层被搜时直接 `self.fail`** | **未实现特性的规格**（tier precedence；现实现是一次把候选交给 `_find_in_roi`，顺序不同） |
| `test_empty_task_page_recovery.py`（1 红） | MAIL 页"全领完"且无可选 goal 时，`runtime.run(max_actions=1)` 应**回 HOME** | 未完成的行为规格 |

⇒ **三个都是"规格先行、实现未做"，不是当前代码的回归。** 而且它们**未跟踪** ⇒
**pin 树的规范集（5753）里没有它们**；**只有从数据根跑**才会多出这 3 个红。
**这正是 D-J 的又一条理由**：从数据根跑 = 规范集 ＋ 草稿，**红点与总数都不可比**。

**未做**：没提交它们（提交会让套件变红）、没删它们（是 WIP）、**没去实现那条 tier precedence**
（改 `vision.find` 属生产感知链，需要回归 + 真机验证，不在离线可声称的范围内）。
