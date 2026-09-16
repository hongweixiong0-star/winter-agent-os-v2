# ROLE-SCOPED CAPABILITY AUDIT（2026-09-16）

对「角色成长 / 行军容量 / 功能解锁动态建模」总指令第 25 节的 9 问现场审计。
**方法**：全部结论来自代码检索与真机证据，不来自记忆。

结论一句话：**项目目前没有角色概念；行军容量在读得到时是真值、读不到时是编造的；
reserve 是固定常量且本轮已实测它把整条采集链堵死。**

---

## 1. 是否硬编码 `march_slots = 2`？

**没有硬编码 2，但存在更严重的同类问题：硬编码 6，并且连占用量一起编造。**

| 位置 | 内容 | 性质 |
|---|---|---|
| `vision.py:902` | `calibrated_march_max: int = 6` | 构造默认值 |
| `vision.py:1195` | `march_used=1, march_max=6`（`BTN_BEAST_START_MARCH`） | **编造占用量** |
| `vision.py:1204` | `march_used=2, march_max=6`（`STATUS_BEAST_RETURNING`） | **编造占用量** |
| `vision.py:1213` | `march_used=6, march_max=6`（`STATUS_BEAST_MARCH_OUTBOUND_MUSK_OX_9`） | **编造占用量** |
| `vision.py:1222` | `march_used=5, march_max=6`（`STATUS_INTEL_BEAST_MARCHING`） | **编造占用量** |

`models.py:71` 的字段本身是 `march_max: int | None = None`（正确，允许未知），
`ocr.py:700,705` 也**真的**从 HUD 读 `used/max`（真值可得）。

⇒ 问题不是"没有真值来源"，而是**真值读不到时用编造值兜底**。
这与总指令第 8 节「证据不足则 `confidence = LOW`，不要强猜」直接冲突。
**危险方向**：编造 `march_used=2/march_max=6` 会让 `idle_marches` 算出 4，
调度器据此认为有 4 支空闲队伍 —— 而真机可能只有 2 支。

### 1b. 修复时暴露的第二层问题：那个编造值**被 verifier 依赖**了

删掉编造值后有 2 个测试失败，其中一个揭示了比"硬编码"更深的问题：

`verifier.py:648` 的 `verify_beast_dispatch` 要求

```python
queue_visible = after.march_used is not None and after.march_used >= 1
```

而 `after` 帧走的正是 `STATUS_BEAST_MARCH_OUTBOUND_MUSK_OX_9` 分支 ——
**那个数字的唯一来源就是我刚删掉的编造值**。也就是说：

> **这个 verifier 的"证据"从来不是测量出来的，而是页面模型编出来的。**

**没有削弱 verifier**，而是把"编造"换成"有依据的下界"：
模板确实证明了"有一支麝牛队伍在途中" ⇒ **至少一个队列位在用** ⇒ `march_used=1` 成立；
而**容量 `march_max` 仍然完全未知**。这个区分是关键的：

- **高估容量** ⇒ 凭空多出空闲位 ⇒ 授权派进满队列（危险方向）；
- **低估占用**（且容量未知）⇒ `idle_marches` 仍是 `None` ⇒ 去 `CHECK_MARCH` 读真值（安全方向）。

即：**上界必须来自观测，下界可以由证据推得。** 这条判据已写进 `vision.py` 的注释与测试。

## 2. 是否硬编码 `reserved_march = 2`？

**是。** `config/v2.json:30` `"reserve_for_stamina": 2`，
由 `brain.py:364` 与 `brain.py:600` 消费为 `SAFE_STOP reserved_march_for_stamina`。

**本轮已实测它的后果**（2026-09-16T04:20–04:30Z）：
当日角色 `march_max = 2`，采集派出 1 支后 `marches=["MARCHING"]`，
大脑随即对**每一次** `GATHER_RESOURCE` 都答 `SAFE_STOP reserved_march_for_stamina`
⇒ 3 次运行**一条 episode 都没产生**。正是总指令第 10 节描述的
「角色只有 2 队时 reserve=2 ⇒ available=0 ⇒ Gather/Intel/Beast 全部被 SAFE_STOP」。

## 3. 是否把 march capacity 作为全局状态？

**是全局的，但不是"共享常量"意义上的全局，而是"没有归属"意义上的全局。**
`march_max` 只存在于**单帧** `WorldState`（`models.py:71`），
既不按角色保存，也不跨帧保留（`runtime.py:442,841` 只是透传）。
容量读不到时，下一次观测回到 `None`，**上一次观测到的真值被丢弃**。

## 4. `ROLE_SWITCH` 是否刷新 march capacity？

**不适用 —— 项目里没有任何角色/账号概念。**
对 `role_id|role_switch|multi_role|account_id|切换角色|多角色|角色切换`
在 `winter_agent_v2/ tools/ docs/ knowledge/ config/ tests/` 全量检索：
**零命中**。因此既没有 ROLE_SWITCH，也没有"不能继承上一角色状态"的风险 —— 因为连"上一角色"都不存在。

## 5. `GoalLibrary` 是否假设所有角色拥有同样功能？

**没有硬假设，但只做了"观测门控"，缺"阶段先验"，且 `available_skills` 会列出本角色不存在的技能。**

`goal_library.py:67-133` 实际是**观测驱动**的（这一点方向正确）：
`CLEAR_INTEL` 要求 `intel.status != "UNKNOWN"`、`PARTICIPATE_BEAR` 要求
`events["bear"]` 存在、`CLAIM_FREE_*` 要求 `rewards["verified_claimable"]` 存在
⇒ 功能不存在时一般不生成目标，**不会反复失败**。总指令第 5 节的
「没有 Arena 就不要一直生成 USE_FREE_ARENA_ATTEMPTS」**目前成立**（因为没有 Arena 目标）。

三个真实缺口：
1. **无阶段先验**：不能预先知道"这个角色可能已经解锁了什么"，因此**不会主动去看**。功能解锁了也没人去找。
2. **`available_skills` 不校验本角色能力**：`goal_library.py:113` 给熊事件列出
   `("START_RALLY", "JOIN_RALLY")` —— 若该角色无 Rally，目标仍会挂出这些技能。
3. **目标状态无角色归属**：`GoalStateStore` 写单一文件，多角色会互相覆盖。

## 6. 是否已存在 `AccountStage` / `ProgressionState`？

**字段已存在但完全未接线；没有 ProgressionState。**

- `models.py:90` `account_stage: dict[str, Any] = field(default_factory=dict)`
  —— 真机状态转储里恒为 `{}`，**全仓库仅此一处提及**，无任何写入方。
- 无 `ProgressionState`、无 `FeatureUnlock`、无 `CapabilityState` 实体。

⇒ 按总指令第 26 节，**这就是应当扩展的现成结构**，不需要新建管理器。

## 7. 是否能记录 `furnace_level / generation / feature availability`？

**不能。** 三者都没有任何记录点。

- `furnace_level`：`knowledge/game/buildings.json` 有 `FURNACE` 条目且
  `level: null`、`prerequisites: "dynamic_by_level..."` —— 知识层知道它存在，运行时从不读取。
- `generation` / `server_progress`：无字段。
- `feature availability`：`knowledge/goals/goal_capability_map.json` 有
  `LIVE_VERIFIED` 的**定义**（"production episode + success + verifier pass + traceable evidence"），
  但它标注的是**能力覆盖**，不是**角色解锁状态**。二者被混在 `capability_coverage.py` 里。

## 8. `UNKNOWN` 新入口是否可能被错误当失败？

**是，而且是"直接终止运行"级别的失败，不是降级。**

`brain.py:100` 对未知页面返回 `Decision("SAFE_STOP", "unknown_page", 1.0, "no_action")`；
`runtime.py` 随后**按系统 BACK**（每轮最多 2 次，`max_unknown_page_backs=2`），
若仍未知则 `AgentState.DEGRADED` + **结束整个 run**。

⇒ 角色新解锁的功能所带来的**新界面 = 一次会让 run 结束的事件**，
而不是一次"发现候选功能"的事件。总指令第 19 节要的
`FEATURE_UNLOCK_CANDIDATE` 路径**不存在**。
（本轮新增的 `FIGHT_STARTING_VERIFIERS` 只是把"战斗中"从这条路径里摘出去，范围很窄。）

## 9. 是否能识别角色成长后新功能？

**不能。** 三个必要条件全部缺失：

1. 无 `AccountStage` ⇒ 不知道角色处于哪个阶段，无法判断"现在该出现什么"。
2. 无 `knowledge/game/feature_unlocks.json` ⇒ 没有先验清单可比对。
3. 未知页面走的是 BACK+终止路径（第 8 问）⇒ 就算新入口出现了，系统也只当它是"看不懂的画面"。

---

## 修法分层（按总指令第 26 节：只扩展现有结构）

| 优先级 | 项 | 做法 | 风险 |
|---|---|---|---|
| P0 | 删掉 `vision.py` 四处编造的 `march_used/march_max` | 读不到就报 `None`，让 `idle_marches` 返回 `None`（既有的"未证实"语义） | 低。会暴露更多 `CHECK_MARCH`，但那是**真话** |
| P0 | Reserve 动态化 | `reserved_slots = f(capacity, occupancy, goals, stamina)`，容量未知时不预留 | 中。需要负向对照测试 |
| P1 | `account_stage` 接线 | 用**已观测**事实写入：`furnace_level`(可读则读)、`observed_march_capacity`(+置信度)、`last_observed` | 低 |
| P1 | 角色归属 | 给持久化状态加 `role_id` 维度；`ROLE_SWITCH` → 重观测 | 中 |
| P2 | `knowledge/game/feature_unlocks.json` | 只作 **Prior**，标注 `confidence` 与 `observed_roles` | 低 |
| P2 | 未知新入口 → `FEATURE_UNLOCK_CANDIDATE` | 未知页面先记候选并安全探查，而不是直接 BACK+终止 | 中 |

## 与总指令的对应关系

- 第 8 节（从客户端观测）⇒ 本审计第 1 问：**已有真值来源，兜底值是错的**。
- 第 10 节（reserve 禁止固定）⇒ 本审计第 2 问：**固定 2 已实测堵死采集链**。
- 第 24 节（角色隔离）⇒ 本审计第 3/4/6 问：**连角色维度都不存在**。
- 第 19 节（成长后自动发现）⇒ 本审计第 8/9 问：**未知入口是终止事件，不是发现事件**。
