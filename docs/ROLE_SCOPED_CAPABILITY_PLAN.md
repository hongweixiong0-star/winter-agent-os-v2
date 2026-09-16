# ROLE-SCOPED CAPABILITY — 本轮改动与剩余实施方案（2026-09-16）

对应总指令第 25 节审计的后续。审计结论见 `docs/ROLE_SCOPED_CAPABILITY_AUDIT.md`。
本文件记录**本轮已修的两项 P0**（含证据）与**剩余项的实施方案**，以及一处必须先解决的阻断性前提。

---

## 一、本轮已修（两项 P0，均有真机证据）

### P0-1 页面模型不再编造行军容量与占用

**改前**：`vision.py` 在四个 beast/hero 状态分支里手写 `march_used=1/2/5/6` 与固定 `march_max=6`，
且页面模型默认容量也是 6。

**为什么危险**：编造占用会喂给 `idle_marches`。其中
`STATUS_BEAST_MARCH_OUTBOUND_MUSK_OX_9` 报 `6/6` ⇒ `idle_marches=0` ⇒
大脑据此走向**召回采集队**——一个基于"没人测量过的数字"的决定。
反向（默认 6 而真实容量更低）会凭空多出空闲位，授权一次派进满队列的派兵。

**改后**：模板能证明"哪一页在屏幕上、某支队伍是什么状态"，
不能证明"有几个队列位、用了几个"。计数未读到就是 `None`，
经 `WorldState.idle_marches` 变成"未证实"，由 `CHECK_MARCH` 去读。
`calibrated_march_max` 默认改为 `None`（OCR 能读到计数器时会覆盖成真值，
见 `ocr.py:698-706` —— 它同时替换 `used` 与 `max`）。

### P0-2 预留量改成容量的函数

**改前**：`config.march_policy.reserve_for_stamina = 2` 被当作**绝对队列位数**使用
（`world.idle_marches <= self.reserve_marches`）。

**真机证据（2026-09-16）**：该角色 `march_max = 2`。派出一支采集队后
`marches=["MARCHING"]`、`idle_marches = 1`，于是 `1 <= 2` 恒真 ⇒
**每一次** `GATHER_RESOURCE` 都答 `SAFE_STOP reserved_march_for_stamina`，
04:20–04:30 三次运行**一条 episode 都没产生**。
同样的常量对写它时那个 6 队列位的角色是合理的 —— 这正是"它不是常量而是容量的函数"。

**改后**：`RuleBrain.reserved_slots(world) = max(0, min(reserve_marches, capacity - 2))`

| 容量 | 有效预留 | 含义 |
|---:|---:|---|
| 1 | 0 | 单队列位永不预留 |
| 2 | 0 | 采集 1 + 空闲 1 已是全部兵力；实时任务改由**按需召回**服务 |
| 3 | 1 | |
| 4 | 2 | |
| 6 | 2 | **写它时的原始意图完整保留**（采集最多占 4/6） |

**不变式（已写成测试 + 接线检查）**：`reserved_slots < capacity`。
否则 `idle <= reserved` 在任何占用量下都成立，目标**永久不可达**而不仅仅是暂时被挡。

**顺带**：`resource_policy.reserve_marches_for_stamina_spend` 是同一策略的**第二份拷贝且零消费者**，
已删除并留说明（留一个看起来权威但没人读的键，比删掉更危险）。

---

## 二、阻断性前提：**当前无法观测"这是哪个角色"** ⚠

总指令第 6 / 24 / 27 节要求角色隔离与 `ROLE_SWITCH` 后刷新。
**前提不成立**：全仓库检索 `role_id|role_switch|multi_role|account_id|切换角色|多角色|角色切换`
在 `winter_agent_v2/ tools/ docs/ knowledge/ config/ tests/` **零命中**。

现有可用标识都不是角色：

| 标识 | 实际指代 | 能否区分角色 |
|---|---|---|
| `config.device.serial` = `127.0.0.1:7555` | **模拟器实例** | ✗ 同一模拟器可登不同角色 |
| `config.device.package_name` = `com.gof.china` | 游戏包 | ✗ 所有角色相同 |
| MAA 日志 `instance_name = ginstance...` | 模拟器实例名 | ✗ 同上 |
| `config.risk.block_account_or_role_delete` | 安全**拦截**规则 | ✗ 不是身份 |
| `WorldState.account_stage` | 字段存在但**恒为 `{}`** | ✗ 从未写入 |

⇒ **在没有角色身份之前，任何"按角色隔离的状态"都只能建在一个猜出来的键上**，
那会制造一种"已经隔离好了"的假象，比不做更糟。因此本轮**没有**动持久化结构。

**三条可选路径（需操作者/Codex 选一）**：

1. **从客户端读角色名**（唯一真正自动化的路径）。HOME/个人资料页会显示领主名，
   需要新增一个语义模板 + OCR 读取。工作量：一次模板登记 + 一次 OCR ROI 标定 + 负样本。
   这条同时解锁第 23 节"角色成长后自动发现"。
2. **配置声明 + 操作者切换**（最小可行）。`config` 加 `role.id`，
   切换角色时由操作者改配置；系统据此给状态文件加命名空间。
   代价：不是自动的，且配置写错会静默串档。
3. **不做隔离，先只做"观测到就记住"**。把观测到的容量等事实写进
   `account_stage`（不落盘、不跨角色），至少让单角色内的重复观测不再丢失。

**建议**：先做 (3)（零风险、立刻有用），同时把 (1) 立为一个正式任务。
在 (1) 完成前，(2) 不要做——它会让"角色隔离"看起来已完成。

---

## 三、剩余项实施方案（按依赖顺序）

### 3.1 `account_stage` 接线（低风险，建议下一个做）

**只写观测事实，不写推断**：

```json
{
  "observed_march_capacity": 2,
  "march_capacity_confidence": "OBSERVED",
  "march_capacity_last_observed": "2026-09-16T04:15:47Z",
  "observed_march_used": 1,
  "furnace_level": null,
  "furnace_level_source": "NOT_READ",
  "last_observed": "2026-09-16T04:15:47Z"
}
```

- `observed_march_capacity` 来源：`march_max` 被 OCR 真正读到时的值
  （`ocr.py:698-706` 已经产出它）。
- `furnace_level` **保持 `null`** 直到有人真读它。绝不用"容量 = 2 ⇒ 大概是 X 级炉子"反推 ——
  那是第 8 节禁止的硬推。
- 置信度用现有词汇（第 3 节的五级，见 3.4 的映射表），不新造枚举。

### 3.2 `knowledge/game/feature_unlocks.json`（低风险，纯知识）

按第 4 节的字段建表，**每条必须带 `source` 与 `confidence`**，并且：

```json
{
  "feature_id": "ARENA",
  "likely_unlock_conditions": ["furnace_level >= ?"],
  "furnace_requirement": null,
  "generation_dependency": null,
  "source": "...",
  "confidence": "LOW",
  "observed_roles": [],
  "live_verified_roles": [],
  "last_reviewed": "2026-09-16"
}
```

⚠ **必须写清 `furnace_requirement` 为 `null` 的含义是"未知"，不是"无要求"。**
第 18 节禁止 `Furnace 30 → Arena` 这类等级表直接驱动生产；
本表只用于"**该去看一眼什么**"，绝不用于"**可以跳过什么**"。

现有 `knowledge/game/` 已有 `buildings.json` / `fire_crystal.json` / `pets.json` /
`chief_gear.json` / `alliance.json`，且**都带 `gate: DISCOVERED|REVIEWED`** —— 新表沿用同一约定。

### 3.3 未知新入口 → `FEATURE_UNLOCK_CANDIDATE`（中风险，需谨慎）

**现状**（审计第 8 问）：未知页 ⇒ `brain.py:100` 答 `SAFE_STOP unknown_page`
⇒ runtime **按 BACK**（≤2 次）⇒ 仍未知则 `DEGRADED` + **结束整个 run**。

**要做的是把"终止"变成"记账 + 有界探查"**，但必须守住两条：

1. **不能把阻塞变成游荡**。新入口探查必须**有界**（次数上限 + 每步都记录），
   且失败时仍如实上报原 `unknown_page`，不得把根因藏起来。
2. **不能自动化未验证的界面**。探查只允许"截图 + 记录 + 退出"，
   **不点击**（沿用 `pages.json` 的 `unknown_action=NO_CLICK` 约定）。

建议流程：未知页 → 截图存档到 `dataset/unknown_pos/` →
记录 `account_stage` 快照 → 查 `feature_unlocks.json` 的 prior →
生成 `FEATURE_UNLOCK_CANDIDATE` 记录（**不是 Goal**）→ 退出当轮。
人类/后续会话据此登记模板，再走正常的 `CANDIDATE → VERIFIED` 晋升。

### 3.4 能力五级 → **复用**既有枚举（第 26 节：不新建）

第 3 节的五级与既有枚举的映射（**不新增平行枚举**）：

| 总指令 | 既有 | 位置 |
|---|---|---|
| POTENTIAL_AVAILABLE | `SkillState.DISCOVERED` | `models.py:41` |
| OBSERVED_AVAILABLE | `SkillState.CANDIDATE` | `models.py:42` |
| LIVE_VERIFIED | `SkillState.VERIFIED` / `STABLE` | `models.py:43-44` |
| LOCKED | `SkillState.BLOCKED` | `models.py:45` |
| UNKNOWN | 缺席（不在任何注册表里） | — |

`knowledge/goals/goal_capability_map.json` 已有 `LIVE_VERIFIED` 的**定义**
（"production episode + success + verifier pass + traceable evidence"），与第 3 节一致，直接复用。

⚠ **要区分两个轴**（审计第 7 问发现的混淆）：
- **技能生命周期**（`SkillState`，全局，与角色无关）；
- **功能在该角色上的可用性**（POTENTIAL/OBSERVED/LOCKED，**按角色**）。
`capability_coverage.py` 现在把两者混在一起标注，接线时需要分开。

### 3.5 召回（第 11–16 节）

**已经实现的部分**（无需改动，仅需登记）：
- `GATHERING` 是 RECALLABLE 而非 LOCKED：`brain._recallable()` 已如此判断。
- 有 idle 用 idle、无 idle 才召回：`brain.py` 的 MAP 分支已如此
  （`idle <= 0` 才走 `SELECT_MARCH_TO_RECALL`）。
- 召回要真实验证：`SELECT_MARCH_TO_RECALL`（verifier `MARCH_RECALL_DIALOG_OPEN`）与
  `RECALL_MARCH`（verifier `MARCH_RECALLED`）都已在 `VERIFIED_ATOMIC` 里。

**缺的部分**：第 13 节的**价值比较**（`NewGoalPriority` vs `CurrentGatherValue`）
目前不存在 —— 现在的规则只是"没有空闲位就召回"，没有比较价值。
第 12 节列的允许场景（真机重复验证 / Deadline / Intel / Beast / Event / Bear / Rally）
也没有作为判断输入。

**第 16 节的 12 次四资源 E2E，在本轮 P0-2 之后才真正可行**：
容量 2 的角色原本被固定 reserve 锁死；现在有效预留为 0，
可以"采集→验证→召回→验证空闲"循环（第 14 节明确允许开发期主动召回）。
建议按 MEAT/WOOD/COAL/IRON 各 ≥3 次立项执行。

---

## 四、本轮未做的（明确记录，不假装完成）

| 项 | 状态 | 原因 |
|---|---|---|
| 角色隔离 / `ROLE_SWITCH` | **未做** | 阻断性前提：无可观测角色身份（见第二节） |
| `account_stage` 落盘 | **未做** | 同上：落盘必然需要角色维度 |
| `feature_unlocks.json` | **未做** | 方案已定（3.2），本轮时间用于两项 P0 与审计 |
| 未知新入口 → 候选 | **未做** | 方案已定（3.3），且需先定"不游荡"的边界 |
| 召回价值比较 | **未做** | 方案已定（3.5） |
| 12 次四资源 E2E | **未做** | 本轮刚解锁可行性 |
