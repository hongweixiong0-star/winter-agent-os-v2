# 自主操作过度限制 —— 代码位置审计与放宽记录

> 基线与口径：审计针对 **commit `39eba75`**（2026-09-21）的代码，方法是在包内逐个定位"拦截点"，
> 而不是按文件目录浏览。每条给出 `file:line` 与**原文守卫表达式**。
> 凡"我改了这一处"的，下面标明新行为与它被什么钉住。

---

## 一、七条限制的确切位置

### R1 —— 未注册 Skill 完全不允许尝试普通页面操作

| 位置 | 守卫 | 说明 |
|---|---|---|
| `winter_agent_v2/runtime.py:1486` | `if decision.skill not in allowed or decision.skill not in self.VERIFIED_ATOMIC:` → `return finish("SKILL_NOT_ENABLED_FOR_LIVE_LOOP")` | **主执行门禁**。`allowed` 由 `runtime.py:1152` `allowed = allowed_skills or set(self.VERIFIED_ATOMIC)` 生成 |
| `winter_agent_v2/runtime.py:122` | `VERIFIED_ATOMIC: dict[str, Verifier] = {` | 白名单本体；`runtime.py:1673/1690` 还用它取 verifier |
| `winter_agent_v2/scheduler.py:68-70` | `skill = self.registry.get(decision.skill)` / `if skill is None or not skill.ready(world): return TickResult(Decision("SAFE_STOP", "skill_not_ready", ...))` | 第二道：注册表成员 + 页面匹配 |
| `winter_agent_v2/capability_gate.py:52,60` | `DEFERRING_STATES = frozenset({DEVELOPMENT_PENDING, DEFERRED, COOLDOWN, BLOCKED})` | 能力级同类限制（`RUNNABLE` / `LIVE_VERIFIED` 是唯二可调度态） |

⚠ **澄清一条常见误判**：执行路径**不看** `skill.state`。`skills.py:92` 的 `ready()` 只排除
`BLOCKED`，`semantic_gate.can_promote_stable` 只管 STABLE 晋升。所以"未 VERIFIED 就不许动"
实际上等价于"**不在 `VERIFIED_ATOMIC` 里就不许动**"。

### R2 —— 模板未 VERIFIED 禁止点击有视觉依据的普通按钮

| 位置 | 守卫 | 说明 |
|---|---|---|
| `winter_agent_v2/executor.py:76-78` | `center = self.target_resolver(action.target)` / `if center is None: return self._result(False, action, "SEMANTIC_TARGET_NOT_VERIFIED")` | **硬门禁：不点击** |
| `winter_agent_v2/runtime.py:1133-1141` | `match = self._semantic.find(frame_path, semantic) ...` / `return None` | 模板查不到即 None |
| `winter_agent_v2/vision.py:1109-1112` | `candidates = [row for row in self.records if row["semantic"] == semantic]` / `if not candidates: return None` | 语义**必须先登记** |
| `winter_agent_v2/maa_executor.py:605` | `reason = f"TEMPLATE_NOT_REGISTERED:{name}"` | MAA 侧同类拒绝 |

⚠ **另一条误判**：模板清单的 `status` 字段**运行时不看**（实测 `records[*].status` 全为
`CANDIDATE` 或空，`vision.py:1109-1170` 的 `find()` 完全不过滤 status）。真正的门是
"**没有模板记录**"，不是"模板没 VERIFIED"。

### R3 —— 结果不可预知就 SAFE_STOP

| 位置 | 守卫 |
|---|---|
| `winter_agent_v2/brain.py:353` | `return Decision("SAFE_STOP", reason, 1.0, transition)`（`_leave_or_stop`） |
| `winter_agent_v2/brain.py:434` | `return Decision("SAFE_STOP", "unknown_page", 1.0, "no_action")` |
| `winter_agent_v2/brain.py:1676` | `return Decision("SAFE_STOP", "no_ready_skill", 1.0, "no_action")` |
| `winter_agent_v2/recovery.py:66-67` | `if count >= self.max_retries: return RecoveryDecision(RecoveryAction.SWITCH_TASK, True, count, "RETRY_EXHAUSTED")`（`recovery.py:41-43` 把 `max_retries` 硬限 0..2） |
| `winter_agent_v2/runtime.py:1868-1871`（旧） | `if not verification.ok: ... return finish(verification.reason)` |

### R4 —— 未预定义完整执行链无法进入新活动

| 位置 | 守卫 | 说明 |
|---|---|---|
| `winter_agent_v2/capability_gate.py:559-565` | `blocked = [item for item in (entry(capability) for capability in composition.capabilities) if item]` / `if not blocked: return None` / `if composition.composition == "ANY_OF" and len(blocked) < len(composition.capabilities): return None` | **`SEQUENCE` goal 任一必需环节不可用即整条 goal 被 defer —— 第 1 步都进不去** |
| `winter_agent_v2/goal_library.py:816-861` | `GoalComposition`（读 `knowledge/goals/goal_capability_map.json` 的 16 个 goal） | 组合语义的来源 |
| `winter_agent_v2/goal_library.py:62-86,97-113` | `GOAL_ROUTES` / `route_for()` → `return GOAL_ROUTES.get(value)`（无路由返回 `None`）；消费点 `runtime.py:1296-1314` | 没有路由的 goal 被调度但"什么都不做" |

`skill_factory.GOAL_REQUIREMENTS`（`skill_factory.py:24`）**只用于覆盖率/审计**，不是执行门禁。

### R5 —— 单步未达目标就终止整个 Goal

| 位置 | 守卫 |
|---|---|
| `winter_agent_v2/runtime.py:1868-1871`（旧） | `if not verification.ok:` → `return finish(...)` —— **单步验证失败即终止整轮** |
| `winter_agent_v2/capability_gate.py:579-602` | `_no_progress_deferral`：`if streak < self.no_progress_threshold: return None` 否则 `state=DEFERRED`（阈值 `capability_gate.py:84` `NO_PROGRESS_STREAK = 3`） |
| `winter_agent_v2/runtime.py:520-548` | `_yield_to_next_goal`：`self._yielded_goals.add(goal.goal_id)` / `self.brain.current_goal = None` |
| `winter_agent_v2/goal_library.py:152-157` | `if self.status in {COMPLETE, BLOCKED, UNKNOWN}: return float("-inf")` —— 这些态不可调度 |

🐛 **顺手发现的死字段**：`goal_library.py:139` `retry_after: str | None = None` —— 全仓库
**无任何读取点**。"带重试时间的重排"目前**没有实现**（只有 streak 计数 + `until`）。

### R6 —— 页面无法识别时只等待

**该描述在当前代码中不成立。** 实测行为：

- `winter_agent_v2/brain.py:433-434` 未知页面返回 **`SAFE_STOP`**（不是 `WAIT` 占位技能）。
- `winter_agent_v2/runtime.py:1375-1416` 拿到 `unknown_page` 后**确实会恢复**：
  `self.device.press_back()`，且受 `self._unknown_page_backs < self.max_unknown_page_backs` 约束。
- `WAIT` 只用于 `Page.MAINTENANCE` / `Page.LOADING`（`brain.py:438-441`）。
- 唯一的纯等待分支是战斗动画（`runtime.py:1390-1400`）与维护/加载（`runtime.py:1315-1329`）。

⇒ 这一条**不需要改**；要改的是它的上游（未知页面占多大比例、恢复是否有效），不是"只等待"。

### R7 —— 失败后不允许尝试其他候选

| 位置 | 守卫 |
|---|---|
| `winter_agent_v2/runtime.py:1868-1871`（旧） | 首次验证失败即 `return finish(...)` |
| `winter_agent_v2/runtime.py:1786-1861` | 仅有的三个 `continue` 例外（`SUBMIT_RESOURCE_SEARCH` 换资源 / `INTEL_HERO_START_MARCH` 体力拒绝 / `LEAVING_SKILLS` 二次退出），**全部有界且同技能，不换候选** |
| `winter_agent_v2/scheduler.py:102-112` | `if candidates: _, index, decision = max(candidates, key=...)` —— 每 tick 只选一个 |
| `winter_agent_v2/candidate_policy.py:23-26` | `eligible()` 要求 `skill.state is CANDIDATE and skill.id in verifier_skills and skill.id in recovery_skills and risk in allowed_risks and semantic_contract_complete` |

⚠ `attempt_controller.py` 全文只有一个 `attempt_priority()` 打分函数，**不是**重试/候选控制器，
不要把它当成门禁去找。

---

## 二、本轮实际放宽的三处（都有定向测试）

| # | 位置 | 旧行为 | 新行为 |
|---|---|---|---|
| 1 | `runtime.py` 验证失败分支（旧 `1868-1871`） | 单步验证失败 → 整轮结束 | 通过既有 `_yield_to_next_goal` 把**失败的那个 goal 本轮让出**，下一轮选**不同**任务，受 `max_verification_retries = 2` 约束 |
| 2 | `runtime.py` 执行器前（新增） | —— | 本轮已失败过的控件**不再在同一位置点第二次**（§七.3），先让位、无人可让则以 verifier 自己的原因结束 |
| 3 | `runtime.py` 新增护栏位置 | —— | 护栏必须在**执行器之前**：放在 verifier 之后会拦住第三次，而规则说的第二次已经发出（实测：一个失败控件、两次相同点击） |

配套新增（§四/§五/§六 的载体）：

- `winter_agent_v2/control_experience.py` —— 按 `(page, semantic)` 记账的控件级经验台账，
  **不存裸坐标**：位置连同它被读出的那一帧一起存。含 8 种变化分类（`classify_change`）
  与风险白名单（`explorable_risk`，真实货币/不可逆永远为假）。
- `learning.py` `Episode` 新增 `control` / `expected_result` / `observed_change`
  —— 期望与实际问题终于落在同一行上（此前期望只活在 `Decision` 里）。
- `runtime._record_episode` 折账，`finish()` 一次落盘 `learning/control_experience.json`。

**没有放宽的**：真实货币与账号安全（`is_fatal_stop` 决定的边界不变）、
动作预算耗尽、重复失败预算。

## 三、仍待接线（下一单元）

1. **`EXPLORE_CONTROL` 通路**：目前经验只由**已有 skill 的动作**填充，尚无"主动去点一个
   未注册控件"的通路。设计已定：目标由**当帧 OCR 读出的文字 token 自身方框**给出
   （同 `BEAST_SEARCH_TAB` 的做法），因此不需要在 `Decision` 上加参数，也不需要写死坐标。
   同时需要把 R1 的门禁改为"`VERIFIED_ATOMIC` 成员 **或** 有当前帧依据的有界探索技能"。
2. **R2 的门**：`executor.py:76-78` 仍要求 `target_resolver` 给出中心点。上面那条通路
   复用它即可，但要新增 `_derived_targets` 成员并同步 `tools/check_wiring.py:686`。
3. **R4 的组合表**：`SEQUENCE` 一票否决仍是"进不去新活动"的主因。放宽方向是让
   `SEQUENCE` 在**前若干跳可执行**时也允许起步，而不是等全部环节可用。
4. **`retry_after` 死字段**：要么实现（按时间重排），要么删除，目前是误导。

---

## 四、基线测试状态（A/B 判定，供下一个接手人省一次排查）

改动后跑定向回归，`tests/test_capability_gate.py` 有 **5 项失败**。为判断是否本次引入，
把 `winter_agent_v2/runtime.py` 与 `learning.py` 临时还原到 `HEAD` 再跑同一组：

```
HEAD 版本      5 failed, 38 passed   ← 同样的 5 项
本次改动版本    5 failed, 82 passed   ← 同样的 5 项 + 新增测试全过
```

⇒ **这 5 项是既有失败，与本次放宽无关**，不要记到本轮头上：

- `DeferredGoalSchedulingTests::test_a_deferred_goal_does_not_displace_work_that_is_still_selectable`
- `DeferredGoalSchedulingTests::test_an_allowed_goal_is_untouched_by_the_gate`
- `DeferredGoalSchedulingTests::test_the_run_still_plays_when_the_blocked_goal_is_all_there_is`
- `EpisodeMeasurementTests::test_a_goal_that_moved_is_recorded_as_progress`
- `EpisodeMeasurementTests::test_a_verifier_pass_without_goal_progress_is_recorded_as_such`

两个症状：`StopIteration`（`FakeVision.observe` 的帧列表跑干）与
`FileNotFoundError: episodes.jsonl`（整轮没记 episode）。
该文件的 `_run` 里已有一段注释在修同类**环境依赖**（它把 `observation_store.STATE_PATH`
指向空文件，因为"机器上真实的 intel AVAILABLE 读数会让 CLEAR_INTEL 值 500 并盖过 hop"）——
说明这组测试本来就在和运行中 AUTO 写下的 `knowledge/ learning/` 抢事实源。
**本轮没有去修它们**（不属于本次要求，且要先判断期望值该改成什么）。

`tools/check_wiring.py` 仍是 `problems: 9`，与改动前**逐条相同**（goal 路由 / 导航矩阵漂移 /
隐藏窗口等），本次改动**未新增**任何接线条目。

