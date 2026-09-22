# `TRY_ORDINARY_CONTROL` 的失败里，有一半的"理由"是假的（2026-09-23）

## 这是什么

`SEMANTIC_TARGET_NOT_VERIFIED` 是项目里最大的单类失败。近 12 小时 988 步里它占 54 次，其中
**`TRY_ORDINARY_CONTROL` 29 次**——而这个技能是最近才进来的，历史高频里根本没有它，所以本轮从它开始查。

结论：它的 32 次失败里有 **21 次理由写的是假的**。帧上明明画着控件，运行时的**闸门**拒绝了它，
而执行器把"解析器没给落点"一律写成 `SEMANTIC_TARGET_NOT_VERIFIED`（"帧上没有这个控件"）。
本目录记录这次定性与修复的全部依据。

复算命令（不需要真机）：

```
"E:/无尽冬日智能体/.venv/Scripts/python.exe" -u tools/probe_ordinary_control_failures.py   # 帧上有什么
"E:/无尽冬日智能体/.venv/Scripts/python.exe" -u tools/probe_ordinary_control_resolution.py  # 解析器怎么答
```

## 数字

`TRY_ORDINARY_CONTROL` 全量 69 次尝试：38 SUCCESS / 32 FAILURE，失败**全部**是
`SEMANTIC_TARGET_NOT_VERIFIED`。按"这是本 run 的第几次尝试"分组（`episodes.jsonl` 里同 `episode_id` 内排序）：

| | 第 1 次尝试 | 第 2 次及以后 |
|---|---:|---:|
| SUCCESS | 37 | 1 |
| FAILURE | 13 | 18 |

⇒ **重复尝试 19 次里 18 次失败**，而第 1 次尝试 50 次里只 13 次失败。失败帧上：

* `handle_on_frame=True`（该帧的 `state_before.quick_panel.handle` 就在那儿，COLLAPSED）且面板关闭；
* 用**生产解析器**在同一帧上重跑：把"本 run 已用过这个控件"这一个变量设为空 → 返回落点
  `(0.0181, 0.4301)`；设为 `(HOME, QUICK_PANEL_HANDLE)` → 返回 None。
  **同一个帧、同一份代码，只有一个变量不同。**

## 根因

`LiveRuntime._ordinary_control_candidate` 的声明控件层有四个闸门，它们**全都**拒绝一个**帧上画着**的
控件，而且**全都不出声**（只有一个 `return None`）：

| 闸门 | 代码位置（改前） | 它拒绝的理由 |
|---|---|---|
| 本 run 已用过 | `runtime.py:3262` | `(page, semantic)` 已在 `_ordinary_tried` 里（操作者 §七.3：按过的控件不在同一 run 里重复按） |
| 记录不服务这个 goal | `runtime.py:3315` | 记录 `related_goals` 只列了 `KEEP_TRAINING_PRODUCTIVE` / `KEEP_RESEARCH_PRODUCTIVE` |
| 记录不列这个页 | `runtime.py:3312` | 记录 `pages` = HOME / MAP |
| 记录的 risk 不可探索 | `runtime.py:3318` | 非 `EXPLORABLE_RISKS` |

于是 `executor.py:78` 的 `if center is None: return self._result(False, action, "SEMANTIC_TARGET_NOT_VERIFIED")`
把四种不同的根因压成同一句话，`runtime.py` 再原样写进 episode。这正是 `00_MASTER_RULES.md` §6
禁止的："两个根因不同的缺陷不得共用同一个 reason 字符串"。项目里**已有**同一形状的先例
（`brain.py:2025`：买不起的出征被误报成"控件不在那儿"，修法是"按名字拒绝"），本轮照同一形状修。

还有两处连带影响，都指向同一个错：

* `_collect_ui_evidence` 把它当成 **"named and unlocatable"** 归档 —— 一个"读不到"的元素候选。
  元素其实被读到了，只是被拒绝使用；这条假候选进了 `knowledge/perception/candidates/`。
* `escalation_queue.is_ui_unread` 按后缀匹配，`..._NOT_VERIFIED` → **`UNKNOWN_UI`** →
  "客户端显示了 V2 读不懂的东西"，会交给开发 agent 去修。**没有东西读不懂。**
  （同一份文件 §209-232 记着一次真实代价：一个错误归因耗尽了一整个修复预算并把最高优先级的 goal 推迟。）

## 修法（只改"怎么记"，不改"点哪里"）

1. `_ordinary_declined`：每次解析开始时清空（与 `_ordinary_last` 同一纪律），四个闸门各自
   **按名字**记下自己拒绝了哪个控件，并打一行日志（改前只有一个 `return None`）。
2. `_failure_type_from(execution)`：执行器说 `SEMANTIC_TARGET_NOT_VERIFIED` 时，若这一步
   **确实什么都没解析出来**（`_ordinary_last is None`）而运行时有具名拒绝，就用那个名字。
3. 候选收集器：具名拒绝**不再**按 "unlocated" 归档。
4. 名字不再落在 UI 后缀里 ⇒ 不再被当成 `UNKNOWN_UI`。

名字与语义（`LiveRuntime.ORDINARY_CONTROL_DECLINES`）：
`ORDINARY_CONTROL_ALREADY_USED_THIS_RUN` / `_NOT_ON_THIS_PAGE` / `_NOT_FOR_THIS_GOAL` /
`_RISK_NOT_EXPLORABLE` / `_ALREADY_OPEN`。

## 结果（同一批真实帧，改前/改后）

| | 改前 | 改后 |
|---|---:|---:|
| 失败数 | 32 | 32（**点击行为完全没变**） |
| 理由为假的失败 | **21** | **0** |
| `ORDINARY_CONTROL_ALREADY_USED_THIS_RUN` | — | 11 |
| `ORDINARY_CONTROL_NOT_FOR_THIS_GOAL` | — | 10 |
| 仍是 `SEMANTIC_TARGET_NOT_VERIFIED` | 32 | 11 |
| ↳ 这 11 条的帧上有没有把手 | — | **全部 `handle=False`**（page=UNKNOWN 或 TRAINING）⇒ 这句话在它们身上是**真的** |

⇒ 理由的真假分布从"21 假 / 11 真"变成"0 假 / 11 真"，且**没有多按一次**。
`resolution.json` 逐帧记录：`failure_type_recorded_by_the_executor` vs `failure_type_now`、
`point_as_first_attempt` vs `point_after_the_handle_was_used`、以及每个闸门的名字。
（`report.json` 是同一批帧上"读到了什么"的那一半：把手在不在、白名单词有哪些。截图本体按 `.gitignore`
不进 git，逐帧路径记在 JSON 里，按路径可复现。）

## 依此发现的下一件事（**未修，需真机**）

10 条 `ORDINARY_CONTROL_NOT_FOR_THIS_GOAL` 说明：客户端在 HOME 上画着把手，而当轮 goal 是
`MAIL_ROUTINE` / `ALLIANCE_ROUTINE` / `AVOID_STAMINA_WASTE` / `AUTO_DISCOVERY` 时，解析器
**拒绝**打开它。但 `brain.PANEL_ROWS_FOR_ROUTE` 明确给 `ALLIANCE` / `DAILY` 两条路由也分配了
面板行（`ALLIANCE_DONATION` / `MY_REWARDS`），而 `QUICK_PANEL_ROW_GOALS` 一共认 7 行 ⇒
`related_goals` 这张表**比面板实际被使用的范围窄**。这是**知识缺口**，不是代码缺口：
那张表是操作者自己列的（"training and research productivity"）。扩宽它 = 在设备上多做 10 次面板打开，
属于行为改动，必须真机验收 ⇒ 登记进 issue，本轮不动。

## 本轮**没有**验证的

* **真机**：AUTO 本轮全程在跑，改动只在离线上验证（帧 + 生产解析器 + 播放）。多按/少按一次都不会发生
  （改动不触碰 tap 决策），但"新名字真的落进 episode"要等下一轮真机跑出 `TRY_ORDINARY_CONTROL` 才算
  Live 证据。
* 三个结构性名字（`NOT_ON_THIS_PAGE` / `RISK_NOT_EXPLORABLE` / `ALREADY_OPEN`）在语料里**没有实例**，
  只有单测覆盖；它们存在是因为那三个闸门确实会拒绝帧上画着的控件。
