# 下一个最高价值缺口：训练链从未在 HOME 上训练过（2026-10-03 确证）

> 上一轮修掉了导航乒乓（`58dccc8b`）。修完之后重新评估整个项目，
> 暴露出一个**更深、且先前被乒乓掩盖**的缺口。本文件是它的完整证据，
> 下一轮接手可直接施工，不需要重新诊断。

---

## 一句话

`KEEP_TRAINING_PRODUCTIVE` 被选中 508 次，其中 **416 次只是导航到 HOME**，
然后**从来没有在 HOME 上执行过一次训练动作**。三天以来它在 HOME 上只走过 2 步。

---

## 一、证据（全部来自 `learning/episodes.jsonl`，按 `recorded_at` 排序）

### 1. 它被选中的 508 步在做什么

```
expected_result 分布：
  home_opened              416   ← 只是"把 HOME 打开"
  resource_search_closed    28
  underlying_page_restored  22
  ordinary_control_observed 18
  selected_goal_entry_reachable 15
  live_page_restored         3

decision_reason 分布：
  training_goal_requires_home                     388
  close_resource_search_for_training_goal         28
  train_goal_leaves_a_panel_it_does_not_own       28
  train_goal_generic_reward_dismissed             22
  selected_goal_leaves_unrelated_event_session    15
  unclaimed_activity_panel_is_observed_...         8
```

**`training_goal_requires_home` 388 次 + `home_opened` 416 次**：
这条链的全部行为就是"我现在不在 HOME，请导航过去"。

### 2. 剔掉导航步后，它真正干活的 18 步在哪

```
page=POPUP   CLAIM_FREE_STAMINA / BACK / DISMISS_SHARED_REWARD
page=MAP     BACK  ×6
page=EVENT   BACK  ×4 / TRY_ORDINARY_CONTROL ×1(FAILURE)
page=UNKNOWN TRY_ORDINARY_CONTROL ×1(FAILURE)
page=MAIL    BACK
page=HOME    OPEN_QUICK_PANEL  ← 唯一一次像样的
```

**在 HOME 上执行过的总步数：2**（其中 1 步是 `OPEN_QUICK_PANEL`）。
`goal_progress=True` 的次数：**0**。

### 3. 它不是"没有归属页"，是"归属页上没有动作"

最近 2000 步、剔除 `OPEN_HOME`/`OPEN_MAP` 后：

```
KEEP_TRAINING_PRODUCTIVE  tot=18   HOME=1 (6%)   [UNKNOWN:5 POPUP:4 ALLIANCE:2 BUILDING:2 HERO:1]
KEEP_BUILDING_PRODUCTIVE  tot=100  HOME=43(43%)  [EVENT:44 HOME:43 UNKNOWN:8 ...]
CLEAR_INTEL               tot=242  HOME=0 (0%)   [POPUP:73 INTEL:68 MAP:53 ...]
DISCOVER_QUICK_PANEL_TASKS tot=207 HOME=207(100%)
```

这解释了为什么 `page_residency` 对它**正确地返回 0**：
它确实没有"习惯页"——因为它从没在任何页上做过训练。
**这是如实测量，不是阈值过严。** 我特意核对了这一点，因为
"阈值收得太紧"是一个听起来同样合理、但会导向错误修法的解释。

---

## 二、为什么先前没被发现

三条证据链互相掩护：

1. **verifier 从不报错** —— 导航动作的 `expected_result=home_opened` 确实达成了，
   `result=SUCCESS`；乒乓的每一步也都 `SUCCESS`；
2. **`goal_progress=False` 不罚分** —— `progress_moved` 对缺行返回 `None`（未测量），
   而 `no_progress_streak` 要累积 3 次才饱和；
3. **它一直在被选中** —— 508 次，看起来很"活跃"，
   掩盖了"每次都只走到门口"。

所以它在 `capability_skill_map` / 覆盖矩阵里大概呈现为
"READY 且被频繁调度"，而实际上 **L3 STEP_VERIFIED 都不该有**。

---

## 三、待回答的问题（下一轮必须先答，再写代码）

1. **HOME 上的训练入口是哪个控件？** 候选：`OPEN_INFANTRY_TRAINING`
   （registry 里 `required_page=HOME`，历史上在 HOME 上跑过 17 次）、
   还是 `OPEN_TASK_FROM_QUICK_PANEL_BUILDING` 那种"先开面板再点任务"的形状。
   **必须看真机帧回答**，不能从代码推断。
2. **为什么 `available_skills` 里有它却没被选中？**
   决策日志显示 `KEEP_TRAINING_PRODUCTIVE` 在 HOME 那一帧
   `base=180 / total=120 / repeat_failure=-60`，输给 `DISCOVER_EVENT_CALENDAR`。
   即：**它带着 -60 的连败惩罚在参与排序**，而这个惩罚是乒乓期间
   388 次无谓导航积累出来的。乒乓修好后这个 streak 会自然衰减 —— 需要复看确认。
3. **训练有没有 Verifier？** 若 `OPEN_INFANTRY_TRAINING` 没有绑定
   "训练队列真的进了 IN_PROGRESS"的判据，那么即使点对了也无法记 `GOAL_PROGRESS`，
   缺口会从"到不了"变成"到了但证明不了"。**这是 §七 里
   "MAA click succeeded ≠ Goal 成功"的老问题，必须提前查。**

---

## 四、为什么本轮不继续修

本轮已经交付并真机验证了一个修复（乒乓：导航步 17.8%→5.0%、
反向导航 37%→0%、`goal_progress=True` 16.8%→25.0%）。
继续动训练链需要**先看真机帧确认训练入口**——那是另一个完整的
"观察 → 定位 → 最小修复 → 真机验证"循环，
而当前 A/B 回归判定尚未完成、dev 工作树还停在修复前版本（铁律要求先换回）。

**顺序不能颠倒**：先让工作树回到已验证的状态，再开下一条链。

---

## 五、复算命令

```bash
cd /e/无尽冬日智能体
.venv/Scripts/python.exe -u -c "
import json,collections
rows=[json.loads(l) for l in open('learning/episodes.jsonl',encoding='utf-8') if l.strip()]
rows=[r for r in rows if r.get('recorded_at')]
rows.sort(key=lambda r:r['recorded_at'])
kt=[r for r in rows if r.get('goal_id')=='KEEP_TRAINING_PRODUCTIVE']
print('被选',len(kt),'步')
print(collections.Counter(str(r.get('expected_result')) for r in kt).most_common(5))
work=[r for r in kt if r.get('skill') not in ('OPEN_HOME','OPEN_MAP')]
home=[r for r in work if isinstance(r.get('state_before'),dict) and r['state_before'].get('page')=='HOME']
print('非导航步',len(work),'其中在HOME上',len(home),'gp_true',sum(1 for r in kt if r.get('goal_progress') is True))
"
```
