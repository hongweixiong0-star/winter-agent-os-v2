# 日历目标"自我抹除"：根因、最小修复与验收（2026-10-03 第二轮）

> 上一轮修掉 `HOME↔MAP` 乒乓（`58dccc8b`）后，重新评估发现的下一个缺口。
> 提交 `79cb572c`，已部署到生产。

---

## 一句话

`DISCOVER_EVENT_CALENDAR` **在它唯一能干活的 EVENT 页上 100% 不在 board 上**（209/209 次决策缺席）。
它被选中 → 导航到 EVENT → 打开日历 → **目标自己消失了** → 被另一个目标 `BACK` 赶回 HOME → 重复。
**打开日历这个动作本身，就是让它从调度板上消失的动作。**

---

## 一、现象

修复 `58dccc8b` 后页面序列：

```
HOME → EVENT → HOME → EVENT → HOME → MAP → BEAST → MARCH → MAP → …
```

页面转移 top：`HOME→EVENT` 19 次、`EVENT→HOME` 19 次（完全对称）。
`HOME→MAP` 乒乓已消失（那是上一轮修的），**但新的 `HOME↔EVENT` 长成了第二个乒乓**。

逐步形状（生产账本原文）：

```
HOME   OPEN_EVENT_CALENDAR_FROM_HOME  DISCOVER_EVENT_CALENDAR  SUCCESS  gp=True
EVENT  OPEN_EVENT_CALENDAR_TAB        DISCOVER_EVENT_CALENDAR  SUCCESS  gp=False
EVENT  BACK                           AVOID_STAMINA_WASTE      SUCCESS  gp=False
HOME   OPEN_EVENT_CALENDAR_FROM_HOME  DISCOVER_EVENT_CALENDAR  SUCCESS  gp=True   ← 又来
```

**在 EVENT 上待几步后被赶走：`第2步 7次 / 第3步 6次`（13/13，全部发生在头两步）。**

---

## 二、根因：不是价格，是"自我抹除"

`DISCOVER_EVENT_CALENDAR` 的出场率按页统计（`learning/decisions.jsonl`）：

| 页 | 出现在 board 上的次数 |
|---|---|
| MAP | 129/485（27%） |
| HOME | 79/1003（8%） |
| **EVENT** | **0/209（0%）** |
| MARCH / POPUP / MAIL / ALLIANCE / … | 全部 0 |

而它 100% 的工作发生在 EVENT 页。

**它在 EVENT 页上唯一的入口是 `goal_library.py:1937`**，条件是当前帧带 `regular_events_hub`：

```python
hub = events.get("regular_events_hub")
if world.page is Page.EVENT and isinstance(hub, Mapping) and hub.get("recognized") is True:
    ...  # 这里是 EVENT 页上唯一能产出该目标的地方
```

而 `OPEN_EVENT_CALENDAR_TAB` 的**副作用恰好是把 `regular_events_hub` 换成 `CALENDAR_GRID`**
（真机帧里 `events` 的键从 `regular_events_hub` 变成 `calendar`）。
⇒ **它打开日历的那一刻，就把自己从 board 上删掉了。**

### EVENT 帧的二分（实测 19/19）

新版本 38 个 EVENT 帧，恰好一半一半：

| 帧类型 | 帧数 | board 上有该目标 | 执行的技能 | gp |
|---|---|---|---|---|
| 带 `regular_events_hub` | 19 | 有 | `OPEN_EVENT_CALENDAR_TAB` | False ×19 |
| 无 hub（带 `calendar`） | 19 | **无** | `BACK`×13 / `TRY_ORDINARY_CONTROL`×6 | False ×19 |

19 个无 hub 帧全部读出 `entries=5`、`details_observed=5`
⇒ 走 `goal_library.py:1907` 的 `status=COMPLETE, skills=()` 分支
⇒ COMPLETE ∈ `NOT_ACTIONABLE` ⇒ `priority=-inf` ⇒ `goal_utility.rank` 丢行。

**承重结构与上一轮 `DISCOVER_QUICK_PANEL_TASKS` 的缺陷完全同形。**

---

## 三、为什么加价救不了（我先查了这一点）

`page_residency` 已经给日历目标 **+40**（实测它的习惯页就是 `EVENT`，占 51%），
所以**加价已经生效但仍被赶走**。这证明病根不在排序层——
**一个把自己删掉的目标，给它多少分都没用。**

这个判断很重要：它避免了"再调一点权重"这种治标做法。

---

## 四、最小修复

`goal_library.py` 的 COMPLETE 分支补一个 `served_by`，形状照抄同文件已有的
`DISCOVER_QUICK_PANEL_TASKS`（同一缺陷、同一修法，已在上一轮真机确证）：

```python
"served_by": (None if status is GoalStatus.READY
              else "every_visible_entry_already_observed"),
```

**行本身一直是对的**（COMPLETE、零价格、零技能——不能定价，否则 AUTO 会重开刚读过的面板）。
缺的只是"一种能说出『问过了、答完了』的方式"。

> 注意 `calendar_scan_due` 的 docstring 记载（2026-10-02 实测）：只要还有"广告了但没人打开"的活动，
> 扫描就永远 due。所以**本修复不会消除导航本身**，改变的是"已完成的扫描现在会留下记录"。
> 这是本修复的边界，不能过度声称。

---

## 五、验证

### 真实帧重放（`tools/calendar_completion_record_replay.py`）

```
[PASS] 带 hub 的帧仍产出可执行的 DISCOVER_EVENT_CALENDAR（OPEN_EVENT_CALENDAR_TAB 等）
[PASS] 无 hub 的帧现在产出一行（此前一行都没有）    400/402
[PASS] 完成的扫描是 COMPLETE、未完成的仍可执行 —— 这个划分才让这行诚实
       203 COMPLETE（无技能） / 197 仍可执行
[PASS] COMPLETE 行说明为何停止可执行（served_by），且未完成的行不冒充  203/203
[PASS] 完成的扫描不带技能，AUTO 不会重开刚读过的面板                0 行带技能
[PASS] 每个带日历网格的无 hub 帧都产出一行（这才是缺陷本身）        395/395
```

那 2 帧产不出的已逐帧查明并按名排除：2026-10-02 旧版本（`f80093be`/`f3e5d8d5`）的
`SUPER_ACTIVITY` 与钓鱼锦标赛页 —— **是真活动页，不是日历网格，本就不该产出日历目标**。

### 回归 A/B

`-k "calendar or event"` 修复前后指纹**完全相同**：235 字符、4 个 F、
失败测试名逐条一致（`test_runtime_bootstrap_integration.py` 4 项）⇒ **零回归**。

新测试 3 项 + 上一轮 7 项 = **10 passed**。

---

## 六、真机验收（`79cb572c`，样本尚小）

| 指标 | `58dccc8b` | `79cb572c` |
|---|---|---|
| 步数 | 202 | 13 |
| `HOME→EVENT` 转移 | 19 | **0** |
| `EVENT→HOME` 转移 | 19 | **0** |

**样本只有 13 步，不足以定论。** 下一轮接手第一件事：

```bash
cd /e/无尽冬日智能体
.venv/Scripts/python.exe -u -c "
import json,collections
rows=[json.loads(l) for l in open('learning/episodes.jsonl',encoding='utf-8') if l.strip()]
rows=[r for r in rows if r.get('recorded_at')]
rows.sort(key=lambda r:r['recorded_at'])
n=[r for r in rows if str(r.get('repo_revision','')).startswith('79cb572c')]
def pg(r):
    s=r.get('state_before'); return s.get('page') if isinstance(s,dict) else None
p=collections.Counter()
for i in range(len(n)-1):
    a,b=pg(n[i]),pg(n[i+1])
    if a and b and a!=b: p[(a,b)]+=1
print('steps',len(n),'HOME->EVENT',p.get(('HOME','EVENT'),0),'EVENT->HOME',p.get(('EVENT','HOME'),0))
"
```

判据：`HOME→EVENT` 与 `EVENT→HOME` 在**≥150 步**窗口内都保持 0 或极低。
若仍出现，说明 `calendar_scan_due` 的 `advertised_but_unread_activities`
（已知、刻意、见其 docstring）是主因，**那属于另一个缺口**，不要与本修复混为一谈。

---

## 七、本轮再次被自己的验证抓住

1. **第一版追加了第二个同名 GoalState 行** ⇒ 会污染 board。
   读回 1903-1910 才发现 `status` 早已分流、原 COMPLETE 行本来就会被追加。
   **改成在原行的 evidence 上补字段，而不是新增行。**
2. **重放判据写成"全部 COMPLETE"** ⇒ FAIL（203/402）。
   真相是 192 帧 READY（确有待看详情，是正确行为）。
   **这个断言等于在断言缺陷本身**——真 bug 会诱导写出错误判据。
3. **判据范围错了**（要求所有无 hub 帧都出行）⇒ 那 2 帧是旧版本的真活动页。
   改为只对"带日历网格"的帧断言，其余按名排除并写明理由。
