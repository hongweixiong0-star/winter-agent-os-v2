# SEMANTIC_TARGET_NOT_VERIFIED 诊断（2026-10-02 凌晨，WorkBuddy 自主开发第一轮）

> 手写会话文档，不覆盖任何既有 handoff 文件。数据均来自真实 `learning/episodes.jsonl`（129 MB，
> 与生产 worktree 共享同一物理文件）。

## A. 本轮先恢复的真实状态（§四十五）

| 项 | 实测 |
|---|---|
| 生产工作树 | `C:\Users\xhw\.codex\worktrees\prod\repo` |
| 生产分支 / HEAD | `codex/production-pin-recovery` / `d7a86c4` |
| 开发工作树 | `E:\无尽冬日智能体`（`main`），与生产 HEAD 一致 |
| repin 工具 | `tools/repin_production.py --to <commit>`，安全语义 `RESULT: CLEAN_OUTSIDE_DATA` |
| 数据共享 | `learning/episodes.jsonl` 两边同大小（129,042,569 B）同 mtime ⇒ 同一文件 |
| 并行 worktree | 共 7 个（`global-multirole-*`、`main-integration`、`winter-prod-pinned`、`winter-rally-generalize`） |
| AUTO | `AUTO_RUNNING`；`watchdog_restart_count 24`、`unexpected_worker_exits 18` |
| UI-Venus | `127.0.0.1:18080` → `{"status":"ok"}` |
| 控制面重载 | `learning/CONTROL_PLANE_RELOAD_REQUIRED.json` **pending**（见 §D） |

**结论：E: 的代码改动不会自动进生产，必须 commit 到 `main` 后再 `tools/repin_production.py`。**

## B. 当前最高频失败（真实数据）

```text
SEMANTIC_TARGET_NOT_VERIFIED   373 条（episodes 全量）
日分布：09-24:1  09-25:20  09-26:60  09-27:46  09-28:38  09-29:2  09-30:155  10-01:51
```

**09-29 的 2 条 → 09-30 的 155 条是剧烈变化，符合"回归"特征，不是老问题。**

按 skill / reason：

| skill | 条数 | 主要 reason | 主要 goal |
|---|---|---|---|
| `TRY_ORDINARY_CONTROL` | 139（09-30 占 69） | `unclaimed_activity_panel_is_observed_before_any_flow_leaves_it`（64） | `AVOID_STAMINA_WASTE` 93 |
| `SELECT_RESOURCE` | 53（09-30 占 47） | `balanced_resource_not_selected`（47） | `EVENT_MINIMUM_GUARANTEE` 71 |
| `SELECT_BEAST_TARGET_MAMMOTH` | 30 | `verified_visible_mammoth_target`（16） | `CLAIM_EXPLORATION_IDLE` 33 |
| `EXPLORATION_IDLE_CLAIM` | 29 | `idle_income_claimable`（11） | `KEEP_BUILDING_PRODUCTIVE` 34 |
| `OPEN_HOME` | 23（10-01 占 11） | `fishing_entry_requires_city_hud` | — |

⇒ 影响 ≥5 个 Goal、8 个 skill，属**共享根因**（§四十七），不应逐 Goal 打补丁。

## C. 三个已确认的事实缺口（按可操作性排序）

### C1. 失败原因没有落盘（wiring 缺口，§十五）

- 写入点：`executor.py:80`（TAP_SEMANTIC 未解析）与 `executor.py:133`（SWIPE 未解析）。
- `observed_change` **100% 是 `UNKNOWN`**（373/373）——动作根本没执行，不是"执行后没变化"。
- episode 里**没有** `recognition_error` 字段；但有 `recognition_backend`（V2/MAA）。
- 而 `executor_router.last_recognition_error` **已经存在**，含丰富原因：
  `RECOGNITION_BACKEND:<declared>:NODE_NOT_ENTITLED`、`MAA_OCR:NO_TEXT/BAD_BOX/NO_SIZE/BAD_SIZE`、
  `STRUCTURE:NO_ANCHOR/ANCHOR_NOT_FOUND/BAD_BOX`、`LIST_DYNAMIC:NO_ROWS/NO_JOINABLE_ROW/TARGET_FALLBACK_REFUSED`。
- **它的唯一读取方是 `tools/device_*.py` 四个手工诊断脚本**（`device_autojoin_boundary`、
  `device_dispatch_l4`、`device_l4_session`、`device_l4_session_v2`），生产写入路径
  （`runtime.py:3274 _failure_type_from`）完全不读它。

⇒ 项目在代码注释里反复用"Measured 2026-09-30 …"手工回答"为什么 miss"，正因为生产数据里没有。
这正是 §五十九"必须能回答为什么没做"的反面案例。

### C2. 失败名与实际语义不符（误导分类）

`SEMANTIC_TARGET_NOT_VERIFIED` 读起来是"点击后未通过验证"，实际是"**当前帧没能定位到该语义目标**"。
后果：它会被当成 `UNKNOWN_UI`（"客户端显示了 V2 读不懂的东西"），而真相往往是"目标可见、
是这次解析没命中"。`_failure_type_from` 的 docstring 已就同类问题（`ORDINARY_CONTROL_ALREADY_USED_THIS_RUN`）
做过一次纠正，**这一类还没有**。

### C3. 决策层与解析层的语义一致性

09-30 集中出现的 reason 文字都在描述"目标确实可见/可领取"
（`unclaimed_activity_panel_is_observed_...`、`balanced_resource_not_selected`、
`verified_visible_mammoth_target`、`idle_income_claimable`）——
即 **brain 判定目标存在并发出 `TAP_SEMANTIC`，executor 却在同一帧解析不到**。

已排除项（不要重复劳动）：
- `ORDINARY_CONTROL` **有**解析分支（`runtime.py:2090 / 2967 / 5009`）；
- 名字不匹配的变体**已修过**（`runtime.py:3790-3800`：解析器登记 `ORDINARY_CONTROL[领取]`
  而查找用 `ORDINARY_CONTROL`，已改为带方括号）；
- OCR 节点走模板路径的误报**已修**（`executor_router.py` 的 `dispatch_hint == "OCR"` 分支）。

## D. 控制面待重载（有意的设计，不是缺陷）

`learning/CONTROL_PLANE_RELOAD_REQUIRED.json`（`requested_at 2026-10-01T16:50:08Z`）为 pending：
本进程加载的控制面已被磁盘版本取代（涉及 `tools/control_panel.py`、`winter_agent_v2/escalation_queue.py`）。

**`_start_control_plane_reload` 的自动重启是刻意停用的**，原因写在代码里且有实测：
`panel_restart.py --restart` = `cmd_stop()` + `cmd_start()`，而 `cmd_stop` 结尾是
`taskkill /PID <panel> /T /F`；`/T` 跟随父子关系，助手由面板自己 spawn ⇒ **助手在杀树时先杀掉自己**，
`cmd_start()` 永远到不了（2026-09-20 两次实测，`panel_reload.log` 在 "stopping panel tree at pid …" 后中断）。

⇒ 当前策略 = 提示待重载 + 等人工在安全点重启。**这属于已知缺口，不是本轮新发现的 Bug。**
若要做，正确方向是"由**树外**进程驱动替换"（例如计划任务 / WMI 创建进程），而不是恢复旧委托。

## E. 下一轮的最小工作（已排好序）

1. **让失败可归因（最小、低风险、共享收益）**：在失败 episode 上落 `recognition_error`，
   取自 router 已有的 `last_recognition_error`（必要时补上 runtime 侧解析失败的分支名）。
   纯新增字段、不改判定；目标：373 条立刻可分类。
2. **离线复现 09-30 的激增**（不碰生产）：取 `TRY_ORDINARY_CONTROL` 那 64 条之一的
   `before_screenshot`（例：`20261002_004824_327843_step_007_before_*.png`），
   在同一帧上跑 `_resolve_semantic_target("ORDINARY_CONTROL", …)`，定位是哪个守卫返回 `None`。
3. 依 1、2 的结论修根因（决策层语义 或 解析守卫），最小修改 + targeted test，
   再 `commit → repin → 真机验证`。

## F. 本轮禁止事项（重申）

- 未改动任何生产代码；未 repin；未触碰 Git 历史（工作树有 1299+ dirty 文件）。
- 未在 AUTO 运行时抢占设备、未重启面板、未消费控制面重载标记。
- 未新增第二份真值：诊断结论写在本文件，数据一律引用 `episodes.jsonl` 与代码位置。
