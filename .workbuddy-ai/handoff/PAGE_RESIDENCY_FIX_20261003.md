# 导航乒乓：架构审查与最小修复（2026-10-03）

> 结论先行：**上一位开发者留下的"需要产品判断"这个结论是错的**，因此本轮没有去问用户。
> 乒乓不是"两个目标谁该让路"的问题，是排序层缺少一个事实：**我们为什么会站在这一页**。
> 修它不需要决定谁优先，只需要让"已经在对的页上"这件事值一点钱。

---

## 一、接手时的状态（复算，不采信上一份 handoff 的数字）

| 项 | 值 | 来源 |
|---|---|---|
| dev HEAD | `05e91e61` | `git rev-parse` |
| 生产 pin | `72dfeee6` | 上一份 handoff（本次未改动生产） |
| episodes 总行 | 10064（`recorded_at` 齐全） | `learning/episodes.jsonl` |
| 时间跨度 | 2026-09-30T11:35Z → 2026-10-03T04:13Z | 同上 |
| 架构不变量 | PASS 10 / FAIL 0 / UNMEASURED 4 | `tools/invariant_review.py` |
| 上一轮的三个诊断测试 | 11 passed | 亲自复跑 |

> 教训复用：上一轮写"`f72b3253` 的 EMPTY 那一半"等结论都带快照数字。本轮所有引用都写成
> 可复算形式（窗口 = 最近 400 步，按 `recorded_at` 排序），生产继续跑也不会让结论失效。

---

## 二、现象复算（最近 400 步）

```
页面分布   HOME 168 · MAP 76 · EVENT 54 · POPUP 27 · INTEL 19 · …
skill 分布 OPEN_HOME 51 · OPEN_MAP 50 · OPEN_QUICK_PANEL 45 · BACK 43 · …
页面序列   HOME→MAP→HOME→MAP→…（20 个来回，零个中间动作）
```

**101 步（25%）是纯导航。** 其中：

- **99 步正确落地**（49 次 `OPEN_HOME`→HOME，50 次 `OPEN_MAP`→MAP）
- **58 步（59%）的下一步是反向导航**

| 前一步（谁付的钱） | 落地页 | 下一步选了 | 干了什么 | 次数 |
|---|---|---|---|---|
| `CLEAR_INTEL` `OPEN_MAP` | MAP | `KEEP_BUILDING_PRODUCTIVE` | `OPEN_HOME` | 29 |
| `KEEP_BUILDING_PRODUCTIVE` `OPEN_HOME` | HOME | `CLEAR_INTEL` | `OPEN_MAP` | 29 |
| `KEEP_TRAINING_PRODUCTIVE` `OPEN_HOME` | MAP | `KEEP_TRAINING_PRODUCTIVE` | `OPEN_HOME` | 14 |

每一笔的 `goal_progress` 都是 `False`。

---

## 三、根因：**导航是好的，被撕毁的是承诺**

`runtime.py:8746` 每一步都重新 rank 整块 board（这是 §四/§五 的正确设计）。
问题在于**价格里没有任何一项记录"我们为什么会站在这一页"**：

1. 目标 X 付一次导航到达 P；
2. 下一���，`rank` 只看"谁更值钱"，X 与一个**想离开 P** 的目标 Y 常常同价；
3. tiebreak 是 board 顺序，于是 Y 赢，Y 第一件事就是 `OPEN_其他页`；
4. 回到第 2 步。

**每一次跳转单独看都是正确的**（`skill.ready` 通过、verifier 通过、落地页正确），
所以账本里记不出任何一条 FAIL —— 这正是它跑了三天才被发现的���因。

> 与上一份 handoff 的分歧：那份写"六个目标 total 全是 180.0、distance 全是 1.0，
> fairness 挤在 99.19–99.40 去决定一个差 0.0 的平局"，因此判断"需要产品判断"。
> **fairness 的挤压是症状不是病因**：把 tiebreak 换成任何确定性的东西，它仍然会
> 每步换个赢家，因为真正的信息（"我刚花了钱到这一页"）根本不在价格里。
> 提价、改 fairness 曲线、修 tiebreak —— 三者都在优化一个不承载该信息的排序。

---

## 四、被否决的两个修法（及为什么）

| 修法 | 否决理由 |
|---|---|
| 给训练/建筑链提价 | 会把它们抬到"能在当前页干活"的目标之上——同训练链那次的结论。且它抬高的是**某一类目标**，不是"已付过导航成本"这个事实。 |
| 改 `fairness_bonus` 曲线 | 既有测试 `test_goal_utility.py:174` 钉住单调性 + 渐近上限；且公平性本身没错，错在它被用来决定平局。 |
| 用 `Skill.required_page` 当"归属页" | **实测反了**：`OPEN_HOME` 声明 `MAP`、`OPEN_MAP` 声明 `HOME`（因为它是你在**对面**按的那个键）。直接用会让每个目标为"它想离开的那一页"加分。见下。 |

---

## 五、实现：`page_residency` —— 一个有界的"已在此页"项

复用既有结构，不新增 Scheduler、不新增状态文件、不新增第二份真值。

```
PAGE_RESIDENCY_BONUS = 40.0      # 界于 claim 间隙 70 与 repeat-failure 60 之间
RESIDENCY_PAGE_SHARE  = 0.5      # 页面必须是该目标"通常在"的页
RESIDENCY_PAGE_MIN_STEPS = 5     # 且至少做过 5 步 —— 一次幸运不算家
NAVIGATION_SKILL_IDS = {OPEN_HOME, OPEN_MAP}   # 纯换页技能永不算居民
```

**归属页从生产账本实测**，不从常量表声明：读 `skill` × `state_before.page`，
剔除换页技能，再要求"占该目标步骤 ≥50% 且 ≥5 步"。最近 2000 步的实测分布：

```
DISCOVER_QUICK_PANEL_TASKS  HOME 231/231 = 100%   → 家是 HOME
MAIL_ROUTINE                MAIL  32/42  =  76%   → 家是 MAIL
KEEP_BUILDING_PRODUCTIVE    HOME  45/98  =  46%   → 家是 HOME
CLEAR_INTEL                 MAP   53/242 =  22%   → 无家（POPUP 30% INTEL 28%）
AVOID_STAMINA_WASTE         MAP  104/337 =  31%   → 无家（EVENT 42%）
```

**这解释了乒乓为什么隐形**：`CLEAR_INTEL` 与 `KEEP_BUILDING_PRODUCTIVE` 从任一页看都同样合理，
所以谁都能赢，也谁都不肯留在原地。

---

## 六、验证（三层，全部可复算）

### 1. 判据分离

```
page=HOME   OPEN_QUICK_PANEL=40   OPEN_INTEL=0   SELECT_INTEL_PIN=0
page=MAP    OPEN_QUICK_PANEL=0    OPEN_INTEL=40  SELECT_INTEL_PIN=0
page=INTEL  OPEN_QUICK_PANEL=0    OPEN_INTEL=0   SELECT_INTEL_PIN=40
UNKNOWN/LOADING/MAINTENANCE=0 · page=None=0 · world=None=0 · 无此目标=0
```
字符串 page 与 `Page` 枚举两种形态结果一致（`Page.HOME` 与 `'HOME'` 同为 40）。

### 2. 真实账本 A/B（`tools/page_residency_ab.py`）

同一进程、同一块 board、同一份真实价格带（`CLEAR_INTEL` base 155.7，其余 180.0），
只切换 `PAGE_RESIDENCY_BONUS` 与 0：

```
without_term   on HOME  -> CLEAR_INTEL
without_term   on MAP   -> CLEAR_INTEL          ← 修复前：两页都选它，于是它每步都被要求离开
with_term      on HOME  -> KEEP_BUILDING_PRODUCTIVE
with_term      on MAP   -> AVOID_STAMINA_WASTE   ← 修复后：各守其页

[PASS] HOME's winner is a goal that lives on HOME
[PASS] MAP's winner is a goal that lives on MAP
[PASS] the two pages no longer pick each other's goals
```

### 3. 反例与饥饿（`tools/page_residency_invariants.py`）

```
[PASS] residency(40) < 领奖间隙 70        → 常驻目标无法长期霸占可领奖目标
[PASS] residency(40) < repeat-failure(60) → 在对页但没进展，仍输给在错页却在干活的
[PASS] fairness(100) > residency(40)      → 被饿死的目标仍能翻身（STARVATION_FREE）
[PASS] 同一块 board 开关两次，目标集合完全相同 → 只重排，绝不排除
[PASS] 在不属于自己的页上，可领奖目标仍然第一   → 250 + 0 > 180 + 40
```

### 4. 回归

- `tests/test_goal_utility.py` 等 **54 passed**
- 新增 `tests/test_the_page_residency_term_reads_the_ledger.py` **7 passed**（读生产账本）
- `tools/invariant_review.py` **PASS 10 / FAIL 0 / UNMEASURED 4**（与修复前一致，无退化）
- 全量 `pytest tests` 收集阶段有 **3 个预存在错误**（缺截图文件 / 缺两个函数），
  涉及文件我全部未改（`git diff --name-only HEAD` 逐个核对为 `False`），
  排除后全量待记录

### 5. 执行级校验（不靠字符串匹配）

```
AST OK · import OK
runtime total=220.0  residency=40.0  as_row 含 page_residency 键
why: page-residency +40.0 (already standing on its page)
```

---

## 七、本轮被自己的验证抓住的三次错误（都写在这里，因为它们比修复更值钱）

1. **第一版用 `Skill.required_page` 当归属页** → A/B 判据 FAIL（HOME 与 MAP 仍都选
   `CLEAR_INTEL`，修复等于没做）。真因：`required_page` 是"技能被允许触发的来源页"，
   对两个换页技能正好读反。若只看"表建出来了、值是 40"，会当场收工。
2. **`page` 读 `.value` 导致整项静默失效** → 账本里 `state_before.page` 是字符串
   `'HOME'`，不是枚举。第一版对每一帧都返回 0。若只测枚举，这条会一路进生产。
3. **测试夹具把 `reward_value=250` 当成 `priority`** → 断言"领奖目标仍第一"失败，
   看起来像代码 bug。真因是 250 是 `reward_value` 字段，真实 `priority` 也是 250 但
   含义不同；填对之后断言通过。**这次是我自己的测试因错误的原因失败**，改夹具而非改断言。

另有一条断言自己写错（用 `"required_page" not in source` 检查源码，而该词正当出现在
解释"为什么不能用它"的注释里）——改为只扫非注释行。

---

## 八、状态与下一步

- 本轮**只改了 `winter_agent_v2/goal_utility.py`**，新增 1 个测试 + 2 个工具。
- **未提交、未部署**。生产 pin 仍是 `72dfeee6`，AUTO 仍在跑。
- 提交前必须：`git ls-files --error-unmatch` 确认备份，并按项目铁律用
  内存 blob 构造提交（工作树会在数秒内被生产 checkout 还原）。
- **真机验证判据**（部署后按 `recorded_at` 取新窗口）：
  1. 最近 200 步里 `OPEN_HOME`/`OPEN_MAP` 的占比，从 25% 下降；
  2. 导航步的"下一步是反向导航"比例，从 59% 下降；
  3. 至少出现一次 `KEEP_TRAINING_PRODUCTIVE` 或 `KEEP_BUILDING_PRODUCTIVE` 的
     `goal_progress=True` —— 它此前 503 次被选、354 次零进展。
  判据 3 是唯一能证明"训练链终于拿到第二步"的那一条，前两条只是症状。
