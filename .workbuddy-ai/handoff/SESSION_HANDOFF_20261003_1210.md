# 会话交接：2026-10-03 12:10 (Asia/Shanghai)

交接时 dev HEAD `7795b88c`　生产 pin `72dfeee6`　生产计划任务 `WinterAgentV2Panel` = Running
本会话共 8 个提交（4 个修复 + 4 个文档/测试），全部已入库并部署验证。

---

## 一句话状态

**四个修复已上线、其中第一个在真机上完全确证；当前最高价值待办是一个跑了三天的导航乒乓循环，
已确证根因、未修，因为修它需要先回答一个产品问题。**

---

## 一、已上线且已确证的修复

### 1. `f72b3253` 面板 sweep目标的记账缺口 ——✅ **真机完全确证**

`DISCOVER_QUICK_PANEL_TASKS` 曾是全场被选 1291 次、1138 步全 SUCCESS、**却零记录**的目标。
根因：它在**回答它的那一帧**从 board 上消失（`goal_library.py:926` 只在面板关时构造它），
而 `progress_moved` 对缺行返回 `None`（=未测量，不罚不奖）、`newly_completed_goal_ids`
需要 COMPLETE 行。

修法：补一行诚实的 COMPLETE，形状照抄同模块已有的 `ALLIANCE_DONATION`/`CLEAR_INTEL`。
承重结构是 `COMPLETE ∈ NOT_ACTIONABLE ⇒ priority=-inf ⇒ rank 丢行`（用真 `rank` 断言，
不只断言 `priority`）。

**确证证据（可复算）**：跨**修复前的 77 个部署版本、1005 步**，
`goal_progress` 是 `None` 1003 / `False` 2 ⇒ **True 占比 0.0%**。
修复后 42 步：
```
("read_true","True") -> 16     ("EMPTY","None") -> 26     零反例
completed_goal_ids 命中 16 次（该目标历史上从未有过）
```
（数字随生产继续跑而增长；判据是**修复前 True 恒为 0、修复后 read_true 与 True 一一对应**。）
固化在 `tests/test_the_ledger_shows_the_sweep_fix_changed_something.py`（读生产账本，
将来回归会自己喊出来）。

### 2. `a1c091ed` 在"已完成"的行上点了 43 次

`PET_TREASURE` 行在 before 帧上 37/43 已写着 `已完成`，门却只看 badge + control。
那 6 次 `UNKNOWN` 更能说明问题：**6/6 都在 5–7 秒后被 `BACK` 接住**（打开就回来）⇒
43 次零收益、账本零失败（verifier答的是"点击落地了吗"）。
修法：加 `status`/`source_word` 完成态门，词表直接用 `ocr.QUICK_PANEL_COMPLETED_WORDS`，
`UNKNOWN` **显式不拒**。

### 3. `cc3da6d7` 面板动画中仍被画出，但像素门拒了它

我先怀疑阈值，**量完推翻了自己**（真值 min 0.4519 /伪值 max 0.1451，间隙 3.1×，
阈值 0.30 漏掉 0/200）⇒ 阈值正确，不该动。真机制是**面板动画时贴着屏幕左边缘、右边界收缩**
（稳态 `x=11..359` vs 滑出中 `x=0..85/196`）⇒ 面积判据退化成"变窄"而非"没有"。
修法：**加第二个判别**（`_quick_panel_is_sliding_out`），不是放宽第一个。
放宽型改动双向验证：3 张滑出帧全放行 / **200 张关着帧误放行 0** / 100 张开着帧漏检 0。

### 4. `e86d1b28` 一个月前的雪豹拒绝否决了今天所有雪豹

`BEAST_DISPATCH_NOT_PROVEN` 9 次、0 次被同技能成功接住 ⇒ 真假阴性。
根因是**用错工具**：`lookup_by_name(name)` 不传 level + `not target.refused`，
而知识库里雪豹只有一行，2026-09-06 记于 29 级胜算较低 ⇒ 此后每只都被否决。
**我先试的修法（补 level）是死路** —— `refused_by_evidence` 的物种兜底是**有意的**。
真正的兄弟是同文件的 `verify_intel_beast_dispatch`（只信帧），照抄它。

这个修复里**两次被既有测试抓到**：① 我把 `target is not None` 一起丢了 ⇒"帧上没名字"不再拒绝
（绿字条答的是"打得过吗"不是"这是我们要打的那只吗"）；
② `test_beast_formation_identity.py` 有一条断言**与引入它的提交 `82cdf49b` 自相矛盾**
（那次提交的主题就是"验证器由客户端判定绑定，不由物种列表绑定"，却把 `not target.refused` 留在原地）
⇒ 改测试而非删断言，换到真正承载意图的用例。

---

## 二、当前最高价值待办：导航乒乓循环（已确证根因，**未修**）

> **本节所有数字是 12:10 的快照，生产一直在跑 ⇒ 接手后请重跑一遍再引用。**
> 重跑命令见第六节；本文档里每条结论都写成了可复算的形式，不是只能信我的说法。

### 现象

`72dfeee6` 上 37 步里 **7 个完整三步循环**：
```
OPEN_QUICK_PANEL (HOME→HOME) → OPEN_MAP (HOME→MAP) → OPEN_HOME (MAP→HOME) → 重复
```
同一形状的另外两种（`CLEAR_INTEL↔KEEP_BUILDING_PRODUCTIVE`）在 `e86d1b2` 上出现过 12 轮。
**从 `d9103948`（10-01）起每个部署版本都有 ⇒ 已跑三天。**

### 根因（用真实 `discover` + 真实 `rank` 重跑账本里的 `state_before` 得到）

HOME 与 MAP 两帧上，**六个目标的 `total` 全是 180.0、`distance` 全是 1.0** ⇒
`rank` 的 tiebreak 是 board 顺序（`scored.sort(key=(total, index))`），而 board 顺序随页面差一位。

**让它成为振荡器而非抖动的是 fairness 项**：`fairness_bonus` 在 `FAIRNESS_OVERDUE_MINUTES=30`
后按 `100 * overdue/(1+overdue)` 渐近 100，这批饥饿目标全挤在 **99.19–99.40**（跨度 0.21）
去决定一个差 0.0 的平局；选中谁谁的 `last_selected_at` 归零，下一步必然轮到另一个。

### 新证据（本次交接新增，最关键）

`KEEP_TRAINING_PRODUCTIVE` **被选了 503/438 次，`no_progress_streak` 354/264**，
每一步都发出 `OPEN_HOME`、每一步都 `gp=False`。所以：

**不是"选不到训练"，是"训练永远拿不到第二步"** —— 它每被选中一次，就换一个目标把它抢走。

### 为什么没修

要修就得先回答**"哪个目标该让路"**，那是产品判断不是工程判断。
已排除的方向：
- **提价**——会把它们抬到"能在当前页干活"的目标之上（同训练链那次的结论）；
- **改 fairness 曲线**——既有测试 `test_goal_utility.py:174` 钉住单调性 + 渐近上限。

诊断已固化在 `tests/test_two_goals_that_need_each_others_page_ping_pong.py`（7 项测量断言）。

---

## 三、必须知道的两个环境陷阱（本会话各踩一次）

### 1. ⚠️ 生产正在用的共享数据文件上"试写一下"= 高危

我调用 `goal_utility.save({...}, None)` 验证能否落盘，`None` 走默认路径，
**那是生产文件**（`os.path.samefile(pin) == True`，junction 共享）⇒ **覆盖了它**。
`git checkout` 无效——**该文件从未被 git 跟踪**。

**规则**：`learning/`、`config/`、`knowledge/`、`dataset/` 是生产活的输入，
dev 与 pin 工作树 junction 共享 ⇒ **任何写这些路径的动作都是在改生产状态**。
验证"能不能写"要写临时文件；动之前先 `git ls-files --error-unmatch <path>` 确认有备份。

**已造成的实际影响**（比初次报告的小，但非零）：见下面第 4 条。

### 2. ⚠️ 多角色下 `goal_fairness.json` 有三份，只有一份在用

```
learning/goal_fairness.json                  ← 顶层：run 开头被读一次（runtime.py:8535），之后被换掉
learning/roles/1061663148/goal_fairness.json  ← 生产实际在用（49 条，正在写）
learning/roles/1063040265/goal_fairness.json  ← 同上（48 条）
```
路径在 `_activate_role_persistent_state`（`runtime.py:1644`）被重绑。

**我据此误报过一次"账本停写 10 小时"，实际是读错了文件。**
已用三个提交逐字改掉代码注释与测试 docstring 里的错误理由
（`2f2e5018`、`7795b88c`）—— **错误理由留在注释里会让下一个人相信它**。

**通用规则：追"写到哪/从哪读"要追到赋值点，不是追到常量定义。**
一个字段两处赋值时，只看常量会得到一个**看起来完全合理**的错误答案。
动作固定：`grep -n "<字段名>" 那个模块` 看全部出现处。

**顶层那份的实际影响**：我覆盖了它，**角色账本 49/48 条完好**；
但顶层那份仍会被 `8535` 在 run 开头读一次 ⇒ 影响了"角色未确认前的那几步"的排序。

---

## 四、本会话其它可复用教训（已写入 `.workbuddy-ai/memory/MEMORY.md`）

| 教训 | 一句话 |
|---|---|
| git SHA 不是时间戳 | `"fa86a51a" > "f72b3253"` 为 True，但前者跑在 09-30。分组统计必须用 `recorded_at` |
| UTC 字段 vs 本地时钟 | `03:19Z` 对 `11:20` 差 8 小时。判"多久没动"必须用同一带时区对象做差 |
| `comm` 的共有数为 0 | 不是零回归，是有一侧没产出。**共有数是那个哨兵** |
| pytest 汇总行永远不打印 | 沙箱拦临时目录清理（`SystemExit` 在汇总行之前）⇒ 用 `-p no:randomly` 的**进度字符指纹**做 A/B |
| 改长注释块会吃掉缩进 | 必须 `ast.parse` + 实际 `import` + 跑测试**三件都做**（本轮连续三次语法错误） |
| 派生的属性不是构造参数 | `BeastTarget.refused` 由 `load()` 派生 ⇒ 我当参数传，测试因错误的原因通过 |

---

## 五、下一步建议（按价值）

1. **导航乒乓循环** —— 根因已备好，需要的是产品判断：训练链与intel 链在 HOME/MAP 之间
   谁该优先？一旦定了，`rank` 的 tiebreak 或 brain 的导航承诺都能改。
2. **`MY_REWARDS` 同一个病但没改** —— 门是 `control == "DONE"` 而 `DONE` 本身就是完成标记。
   **没改的理由**：历史 0 步 ⇒ 没有实测浪费 ⇒ 现在改是无证据的产品变更。测试里钉住了这个事实。
3. **`f72b3253` 的 `EMPTY` 那一半** —— 面板 39 步里 23 步读不出，`gp=None`。
   我上一轮量过分离度（阈值正确），真机制是动画中右边界收缩，已修；
   但**当前窗口仍有 `EMPTY`**，值得再量一次是不是同一形态。

---

## 六、操作速查（本会话验证过）

### 接手第一件事：先自己复算，别信本文档的数字

```bash
cd /e/无尽冬日智能体
.venv/Scripts/python.exe -m pytest \
  tests/test_the_ledger_shows_the_sweep_fix_changed_something.py \
  tests/test_a_ledger_that_stopped_being_written_says_so.py \
  tests/test_two_goals_that_need_each_others_page_ping_pong.py -q -p no:randomly
```
这三个文件**读生产账本**，跑一遍就能确认：修复效果仍在、循环形状未变、
ledger 的两个字段存在。**它们是本会话结论的可执行副本。**

### 日常操作

```bash
# 提交（工作树会在数秒内还原已跟踪文件 ⇒ 用内存 blob 构造提交）
B=$(git hash-object -w <file>)            # 或 cat HEAD:file extra | git hash-object -w --stdin
TREE=$(git rev-parse HEAD^{tree})
export GIT_INDEX_FILE="C:/Users/xhw/AppData/Local/Temp/idx"; rm -f "$GIT_INDEX_FILE"
git read-tree "$TREE"
git update-index --add --cacheinfo 100644,$B,<path>
NEW=$(git write-tree); unset GIT_INDEX_FILE
C=$(git commit-tree "$NEW" -p HEAD -F <msgfile>); git update-ref HEAD "$C"

# 部署（--to 必须给显式 SHA，--to HEAD 会在 checkout 前解析拿到旧 SHA）
.venv/Scripts/python.exe tools/repin_production.py --to $(git rev-parse HEAD)
# → 必须看到 RESULT: CLEAN_OUTSIDE_DATA
# → PowerShell: Stop/Start-ScheduledTask -TaskName 'WinterAgentV2Panel'

# 验证生效（只认 repo_revision，且按 recorded_at 判新旧）
```

**注意**：`/tmp` 在 Git Bash 与 Python 里不是同一处 ⇒ 跨进程传文件用
`C:/Users/xhw/AppData/Local/Temp/`。