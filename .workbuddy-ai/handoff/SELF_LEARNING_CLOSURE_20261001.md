# UI-Venus 自学习闭环 — 交付与验收报告（2026-10-01）

> 对应操作者 47 节《Winter Agent OS V2 — UI-Venus 自学习闭环升级总指令》。
> 本文件按 §47 要求的字段逐条给出。**凡是未取证的，一律写「未取证」并给出原因，不写估计值。**

---

## A. 现场标识（§47 基线字段）

| 字段 | 值 |
|---|---|
| `CODE_COMMIT`（生产） | `f4a7b7c`（`desktop_startup.log` 03:01 起可查；当前 `main` 已到 `4eded5a`，差一个纯文档 commit，见 D 节） |
| `PRODUCTION_PIN.expected_commit` | `f4a7b7cad9e1808d849b0f177c488d0dbf670fcd` |
| 生产工作树 | `C:\Users\xhw\.codex\worktrees\winter-prod-pinned\无尽冬日智能体` |
| `WORKTREE_CLEAN` | `true`（数据目录外 0 处改动；两次 safe repin 均为 `RESULT: CLEAN_OUTSIDE_DATA`） |
| `DATA_ROOT` | `E:\无尽冬日智能体` |
| 设备 | MuMu `127.0.0.1:7555`，`720x1280`，前台 `com.gof.china` |
| 模型服务 | `http://127.0.0.1:18080`，`/health` 200，`multimodal_projector_loaded = true` |
| AUTO 状态 | **运行中**（panel pid 8412，worker 活跃） |

## B. 运行时长与稳定性（`AUTO_UPTIME`）

来自 `learning/auto_uptime.jsonl` 的**当日**实测：

```
今日轮次        40 轮
时间跨度        3.00 小时（本地 00:01:12 → 03:01:26）
halt_reason 非空  0 轮      <- AUTO 一次都没有自行停下
unhealthy         0 轮
executed=365  verified=356  failures=9   -> 验证率 97.5%
```

期间经历 **两次 safe repin**（`de38da0 → e7e2b56 → f4a7b7c`），每次 `--stop` 都拒绝在飞 run、
等到轮次边界才停，数据目录从未被 checkout 覆盖。

## C. §4 截图真的进了模型（`SCREENSHOT_INPUT_VERIFIED`）

**`SCREENSHOT_INPUT_VERIFIED = TRUE`** —— 本轮**重新实测**，不是继承上一轮的结论。
`tools/probe_gui_model_multimodal.py` 用同一问题问两次（不给图 / 给图）：

```
不给图： "roughly 10 distinct buttons/icons, the largest readable text being \"Play Now\"."   <- 编的
给  图： "about 20 distinct buttons/icons, and the largest readable text is the resource
          count \"62,795,625\" at the top."                                                   <- 真的
```

`62,795,625` 就是该帧左上角真实的战力数字 —— 图没被读到时不可能答对。
顺带查出一个**真缺陷并修掉**（`4eded5a`）：该探针的默认端点写的是 `:8080`（WorkBuddy 网关）而不是
`:18080`（模型服务），不带参数运行会拿到 403 并报出 `screenshot_input_verified: false` ——
一个由参数默认值制造的**假阴性**「模型瞎了」。默认值现在从 `config/v2.json` 的
`local_planner.endpoint` 读，并有 2 条测试钉住。

## D. 本轮改了什么（6 个 commit，均为显式 `git add` 小 commit）

| commit | 内容 |
|---|---|
| `7596ac9` | `unknown_learning.py`：已验证步台账 + Candidate 编译器；runtime 接线（先复用已学、成功即归档） |
| `6950914` | `skill_repair.py` / `offline_learning.py` / `learning_funnel.py` + 控制台中文学习面板 + CLI |
| `bf1bb8c` | `test_learning_loop_wiring.py`：§42 的「首次问、再次不问」代码路径验收 |
| `e7e2b56` | §28 故障隔离：学习层抛异常不得带崩真实步进（并打印，不静默） |
| `f4a7b7c` | 自闭环：归档即编译 Candidate；控制台每轮刷新漏斗；§21 离线夜间调度 |
| `4eded5a` | 探针默认端点修正（见 C 节）——**未上生产**，纯工具修复 |

新增测试 **63 项**：`test_unknown_learning` 12 / `test_skill_repair` 10 / `test_offline_learning` 16 /
`test_learning_funnel` 11 / `test_learning_loop_wiring` 12 / `test_model_probe_endpoint` 2。

## E. §11–§14 学习闭环：形状与结构性保证

链路 `UNKNOWN → UI-Venus → SemanticAction → MAA → Verifier → 学习 → Candidate Skill → 晋升 → KNOWN`
已落地。三条保证**不靠自觉，靠结构**：

1. `LearnedStepCandidate` 数据类**没有任何 x/y/bbox 字段** ⇒ §10「模型 bbox 生命周期仅当前帧」
   在类型层面无法被违反；复用时用 `find_printed_words` 在**当前帧**重新定位。
   `tools/check_coordinate_hardcoding.py` 对学习路径报 **0 violation**。
2. Candidate 文件自带 `not_yet = "CANDIDATE only -- not registered, not runnable, and not STABLE"` ⇒
   UI-Venus 无晋升权，§39 在文件层面成立。
3. 「控件已不在画面上」→ 回落到普通路径并**重新问模型**，有专门测试 ⇒ 陈旧记录不是死胡同。

## F. §36/§37/§38 学习效果读数（控制台，真实数字）

`learning/learning_funnel.json`（**由面板在轮末自己刷新**，见 G 节）：

```
今日游戏任务完成率 GAME_TASK_COMPLETION_RATE   = 0.8626   (n=2494)
UNKNOWN_RESOLUTION_RATE                      = 0.0
UNKNOWN_VERIFIER_PASS_RATE                   = 未测量（分母缺：没有已归档的 UNKNOWN 步）
UNKNOWN_REPEAT_MODEL_CALL_RATE               = 0.5   全时段 0.3133
CANDIDATE_TO_STABLE_RATE                     = 未测量（STABLE 是 registry 的词，funnel 不代它发言）
SKILL_REPAIR_SUCCESS_RATE                    = 未测量（尚无 repair 发生）
KNOWN_MODEL_CALLS                            = 26     今日 2
MODEL_CALLS_PER_HOUR                         = 0.167
UNKNOWN_MODEL_CALLS                          = 83     今日 4
OFFLINE_UNKNOWN_CLUSTERS                     = 47
OFFLINE_KNOWLEDGE_CANDIDATES                 = 94
```

漏斗 13 级中 **7 级如实报「未测量 + 原因」**（`GROUNDING_RESULT_NOT_PERSISTED`、
`RISK_REFUSAL_NOT_PERSISTED`、`REPLAY_RUNS_OUTSIDE_THE_RUNTIME`、`REGISTRY_OWNS_THIS` 等），
不报 0 —— 「不知道」和「是零」是两件事。

## G. §21/§22/§23 离线夜间学习：**已自动跑过一次（真机证据）**

```
03:01:14  本轮结束
03:01:26  控制台：离线夜间学习已启动（只读截图建索引，不操作设备）。
03:01:26  knowledge/offline/last_run.json  = {"local_date":"2026-10-01"}
03:01:40  pass 完成
```

产出（`knowledge/offline/unknown_clusters.json`）：

```
frames_in_clusters = 291      47 个视觉状态     最大一组 49 帧
candidate_knowledge = 96      candidates/ 下 50 个文件
sources = FAILURE_EPISODE / UNKNOWN_REQUEST
failure_types = SEMANTIC_TARGET_NOT_VERIFIED / NO_EXECUTION / CONTROL
```

**最大一组 49 帧同属 `SEMANTIC_TARGET_NOT_VERIFIED`** —— 这正是 §22 想要的结论：
一个视觉状态出现了 49 次，分析一次即可，不必 49 次。**0 次模型调用，0 次设备操作。**

## H. §3 快速路径绝不依赖模型（结构性证据）

```
grep advisor|planner|local_gui_model|ui_planner  winter_agent_v2/fishing*.py   ->  0 命中
```

钓鱼实时路径（`fishing_pressure/session/state/vision`）**没有任何一行代码能碰到模型**，
所以 `FISHING_REALTIME_MODEL_CALLS = 0` 是结构性的，不是承诺。
`KNOWN_MODEL_CALLS` 的语义由 funnel 以证据统计（planner 台账中 named page 的行数），本轮 `= 26`。

## I. §6/§29/§30 预算与窗口

```
MAX_MODEL_CONTEXT   = 32768     OUTPUT_RESERVE = 4096
MAX_INPUT_BUDGET    = 28672     IMAGE_TOKENS   = 1024
每屏模型调用上限  max_steps_per_screen = 2      <- 比 §29 的「每屏 2 次」一致
每轮模型调用上限  max_steps_per_run    = 12     <- §29 要求 8~12
```

`ui_planner.take_guard()` 是**硬拒绝**并落台账（`PLANNER_RUN_BUDGET_SPENT` /
`PLANNER_SCREEN_BUDGET_SPENT`），不是提示。

## J. §42/§43/§44 真实验收：**状态 = 部分取证**

| 验收项 | 状态 | 依据 |
|---|---|---|
| `FIRST_ENCOUNTER_MODEL_USED = TRUE` | **代码路径层已证 / 真机未取证** | 测试：无已学记录时 advisor 被问 1 次 |
| `SECOND_ENCOUNTER_MODEL_USED = FALSE` | **代码路径层已证 / 真机未取证** | 同上：有已验证步时 advisor 被问 0 次，且点位由当前帧重新定位 |
| `SECOND_ENCOUNTER_VERIFIER_PASS = TRUE` | **未取证** | 需要真机走到 UNKNOWN 屏并跑完 Verifier |
| Skill Repair 真实验收（§43） | **未取证** | 需要某技能真的连续失败 3 次触发 |
| 离线学习验收（§44） | **已取证** | G 节 |

**为什么真机未取证（诚实原因）**：本轮生产重启（02:49:54）后
`learning/local_planner_steps.jsonl` 与 `learning/local_gui_model_calls.jsonl`
**新增 0 行** —— AUTO 还没有走到任何需要咨询模型的 UNKNOWN 屏，所以链路后半段没有输入。
`learning/unknown_verified_steps.jsonl`、`knowledge/skills/candidates/`、
`learning/skill_repair_requests/` 因此都**尚不存在**，这是**正确**的空状态，不是失败。

**我没有做的事（以及为什么）**：没有为了凑出 `SECOND_ENCOUNTER_VERIFIER_PASS = TRUE`
而伪造 Verifier 通过 —— §25「COMPLETE 永远不能模型自证」、§43「不得人为破坏生产代码制造假成功」。
这个数只能等真实遭遇取得。

## K. §45 Git 纪律

只用了显式 `git add <路径>` 与 6 个小 commit；**未使用** `reset --hard` / `clean -fd` /
`checkout .` / `restore .` / `git add .` / 盲目 `stash pop`。

## L. `CURRENT_TOP_5_REAL_BLOCKERS`

1. **真机 UNKNOWN 遭遇未发生**（最高优先）：AUTO 已在跑、模型在线、学习闭环已接线，但 3 小时内
   没有一个屏进入 UNKNOWN 通道，链路后半段（归档 → 编译 → 复用）在真机上仍是空的。
   这是当前唯一挡住 §42 真机验收的阻塞。
2. **角色切换占用了大量轮次**：今日 40 轮中多轮以 `ROLE_SWITCHED_TO:<id>` 结束，
   `SKILL_REPAIR` / `UNKNOWN` 的机会被角色仲裁挤掉。多角色仲裁本身是既有设计，
   但它显著降低了「撞上 UNKNOWN」的概率。
3. **`SEMANTIC_TARGET_NOT_VERIFIED` 仍是第一失败类型**：同时也是 49 帧那一组聚类的类型，
   说明它是一个**稳定的、可复现的单一视觉状态**，是最值得优先解的一个 —— 而且现在已经有
   离线聚类把它单独挑出来了。
4. **漏斗有 7 级测量不到**：`grounding_valid` / `risk_allowed` / `verifier_progress` 等
   在**拒绝点没有落盘**，所以「模型指了没指到」和「模型没被问」在台账上不可区分。
   要修就得在拒绝点写一行 —— 本轮没有做。
5. **夜班历史遗留**：账号「强制下线」阻塞已消失（帧已确认在 HOME/CITY），但
   `RECONNECT_SESSION` 仍是 CANDIDATE 且缺模板；另外面板上的
   `repair budget exhausted (2/2)` 是**调度器自己的 recovery 预算**，
   与新的 `skill_repair` 同名不同物，日志上容易误读。

## M. §18/§19/§20 未完成项（如实列出）

Page Tree / Navigation Graph / UI Semantic Dictionary 的 Candidate 化，目前只有
`offline_learning.suggest_candidate_knowledge()` 产出的 `UnknownVisualStateCandidate` /
`FailurePatternCandidate` 雏形（96 条），**没有**分别落到三者的 Candidate 存储；
§31 Knowledge Retrieval Top-K 未做。这两项是本轮明确未覆盖的指令项。
