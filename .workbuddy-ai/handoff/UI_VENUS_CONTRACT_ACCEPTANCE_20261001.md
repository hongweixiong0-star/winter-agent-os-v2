# UI-Venus 输入/输出契约 V1 — 交付与验收报告（2026-10-01 晚）

> 对应操作者 33 节《Winter Agent OS V2 — UI-Venus Input / Output Contract V1》。
> 定性：**模型接口契约**，不是新 Agent 架构 —— 未新增第二 Scheduler / Executor / WorldState /
> Runtime Model。
> **凡是未取证的，一律写「未取证」并给出原因，不写估计值。**
> 本报告的数字由 `tools/ui_venus_contract_acceptance.py` 现场打印，可复跑。

---

## A. 现场标识

| 字段 | 值 |
|---|---|
| `CODE_COMMIT`（开发树 HEAD） | `783a219` |
| `PRODUCTION_PIN.expected_commit` | `783a2195b82a09f9a8dcaeaf203c219c66f85e52` |
| 生产工作树 | `C:\Users\xhw\.codex\worktrees\winter-prod-pinned\无尽冬日智能体` |
| `WORKTREE_CLEAN` | `true`（数据目录外 0 处改动；`RESULT: CLEAN_OUTSIDE_DATA`） |
| `DATA_ROOT` | `E:\无尽冬日智能体`（`learning/` / `config/` / `knowledge/` / `dataset/` 四个 mount 指回此处） |
| 模型服务 | `http://127.0.0.1:18080`，活体 `/props` 可达，`vision = true` |
| 模型 | `UI-Venus-2-9B`，`Q4_K - Medium`，`multimodal_projector_loaded = true` |
| AUTO 状态 | **运行中**，面板 pid 25892，轮次持续（19:53:05Z 一轮结束） |

**本轮三个 commit**：

| commit | 内容 |
|---|---|
| `410c04a` | 契约四模块 + 四套测试（8 文件 / +6249 行） |
| `f1d7ffe` | 上活体路径 + 16 层漏斗统一统计（7 文件 / +444 −39） |
| `783a219` | §33 验收仪器 + 仪器自身的测试（2 文件 / +873 行） |

## B. §31 第 0 门禁：截图真的进了模型（`SCREENSHOT_INPUT_VERIFIED`）

**`SCREENSHOT_INPUT_VERIFIED = TRUE`** —— 来自 `learning/_multimodal_probe.json` 的实测记录，
并由活体 `/props` 二次确认服务此刻仍在。

```
multimodal projector  loaded = True   modalities = {'vision': True, 'video': True, 'audio': False}
image                 1,068,452 bytes（base64 data URL，1,424,626 字符）
latency with image    5,774.7 ms     text only 1,471.9 ms
text-only reply       "...largest readable text being \"Pl..."
with-image reply      "...the largest readable text is the resource count \"62,795,625\""
```

两条回复的差别就是取证本身：**没有像素的那一次读不出屏幕上的数字，编了一个按钮名**；
有像素的那一次读出了真实资源量。门禁不开，本合约的任何结论都无意义，故列在第一节。

## C. §32 六个正式类型（每个四件套齐备）

| § | 类型 | 模块 | schema | serializer | validator | ledger |
|---|---|---|---|---|---|---|
| 4 | `UIVenusContextPacketV1` | `ui_venus_online` | 同名 | `as_wire()` / `render()` | `.validate()` | `OnlineLedger` |
| 7 | `UIVenusSemanticActionV1` | `ui_venus_online` | 同名 | `as_wire()` | `validate_action` | `OnlineLedger` |
| 14 | `UIVenusSkillRepairPacketV1` | `ui_venus_repair` | 同名 | `as_wire()` / `render()` | `.validate()` | `RepairLedger` |
| 15 | `UIVenusRepairCandidateV1` | `ui_venus_repair` | 同名 | `as_wire()` | `validate_repair_candidate` | `RepairLedger` |
| 16 | `OfflineUIVenusLearningPacketV1` | `ui_venus_offline` | 同名 | `as_wire()` / `render()` | `.validate()` | `OfflineLedger` |
| 18 | `OfflineLearningCandidateV1` | `ui_venus_offline` | 同名 | `as_wire()` | `validate_candidate` | `OfflineLedger` |

**六个 schema 字符串与指令给的类型名逐字相同**（有测试守，防止"意思差不多"）。

## D. §30 独立性

```
online  : learning/ui_venus_online.jsonl
repair  : learning/ui_venus_repair.jsonl
offline : learning/ui_venus_offline.jsonl
三条不同文件 = True
```

共用层只有 **LocalGUIModel 客户端、Knowledge 置信度语义、Verifier 真值语义、Skill Lifecycle
字段名、Risk Gate 判定、16 层漏斗层名** —— 即指令要求的共享清单，各模式的 schema / validator /
ledger **互不复用**。

## E. §33 五条判据

### E1–E4：四条 `false`，**结构性成立**

| 判据 | 值 | 成立方式（是"没有那条代码路径"，不是"我们没这么写"） |
|---|---|---|
| `MODEL_DIRECT_DEVICE_CONTROL` | **false** | `ast` 解析契约四模块的 import 图，findings = **0**。契约不许 import `executor`/`runtime`/`scheduler`/`verifier`/`skills`/`ocr`/`subprocess`/`socket`/`os`/`ctypes`/`threading`… 实际 import 只有 `dataclasses/datetime/hashlib/json/pathlib/re/typing` + 契约内部模块 + `unknown_advisor`（取 `SPEND_WORDS` 词表）。`pathlib` 是允许的，因为账本路径由**调用方传入**；被禁的是进程 / 设备 / 套接字 / 原生调用这类"能自己动起来"的能力 |
| `OLD_FRAME_DIRECT_GROUNDING` | **false** | 旧帧区域被拒，返回 `GROUNDING_STALE_FRAME`；`VisualHistory.grounding_allowed` 是恒 `False` 的字段。§22 历史截图最多 1 张且 `grounding_allowed = false` |
| `MODEL_COMPLETE_SELF_VERIFICATION` | **false** | `decision: COMPLETE` 只能转成 `MODEL_COMPLETE_CLAIM`；契约里没有任何一处能调到 Verifier |
| `OFFLINE_DIRECT_PRODUCTION_WRITE` | **false** | 离线模式**没有几何通道**：`find_any_geometry` 命中一切几何键（含塞进开放的 `payload` 块），写入路径只有它自己的 candidate ledger |

附三条同源保证，均为**恒 False 的函数或 property，不存在 setter**：

```
real_money_allowed        = False   （§25，永久）
may_overwrite_stable()    = False   （§15，唯一路径 candidate patch → replay → shadow → live → PromotionGate）
phash_is_sufficient(True) = False   （视觉相似只缩小搜索范围，从不授权旧动作）
```

### E5：`KNOWN_MODEL_CALLS = 0` —— **本轮未取证，且不声称成立**

这一条是**运行**属性，不是代码属性，所以必须给窗口和日期：

```
窗口            1d，since 2026-09-29T19:55:36Z（now 2026-09-30T19:55:36Z）
KNOWN_MODEL_CALLS   全史 26   窗口内 2
UNKNOWN_MODEL_CALLS 全史 84   窗口内 5
最后一次模型咨询    2026-09-30T19:31:42Z  page_key = UNKNOWN::对战  decision = OBSERVE
```

- 26 条 named-page 调用集中在 `09-24 (7) / 09-25 (9) / 09-26 (6) / 09-27 (2)`，**均为旧 pin 时期的运行**；
  窗口内那 2 条是 `2026-09-30T15:22:22Z`，**同样在 repin（19:46:12Z）之前**。
- repin 之后模型**一次都没被咨询过**，因此没有"新 pin 上的窗口"可测。
- 按 §26 的口径，窗口内无调用时读数应为 `unmeasured` 而非 `0` ——验收仪器正是这么打印的，
  并同时给出全史值，避免把"上一窗口的旧账"读成"本轮 0"。

**结论：`KNOWN_MODEL_CALLS = 0` 未取证。** 需要在 pin 之后的活体运行里真正走到模型咨询路径
才能取得。**不写估计值。**

**附带发现（同一缺陷的第二个视角）**：漏斗里
`venus_proposed / unknown_observed = 8.875` —— 模型提案数**远多于**已归档的 UNKNOWN。
两个数字说的是同一件事：**planner 在"已知命名页"上也被调用了**，而既有守卫的意图是"只在
未命名屏调用"。这是**先于本轮存在**的缺陷，本合约不改变该守卫，故不予掩盖。

## F. 三条链路（进程内驱动，给出指令自己的拒绝码）

```
ONLINE   放行  一个点在本帧确实存在的控件 → code="" stage=""
         拒绝  模型点了一个本帧不存在的元素 'E99'
               → PLAN_TARGET_NOT_ON_THIS_FRAME   stage=ELEMENT_EXISTENCE
REPAIR   已知技能成熟度 = STABLE
         拒绝  提案直接改写 STABLE → REPAIR_WOULD_TOUCH_PRODUCTION
OFFLINE  证据包内 episode = ['ep_001']
         拒绝  提案里 decision=EXECUTE → OFFLINE_DECISION_EXECUTE_FORBIDDEN
```

三条链路的拒绝点都落在**契约自己的拒绝码**上，不是"抛了个异常"。线上代码路径上，
ONLINE 闸门只在 `decision == EXECUTE` 的计划上生效（`OBSERVE` / `DEFER` 在闸门之前就返回），
每次判定写**恰好一行**到 `learning/ui_venus_online.jsonl`（放行或拒绝都写，拒绝才是信息量大的一半）。

## G. §26 十六层漏斗（当前读数）

```
层数 16（末层 stable_promoted）
有产出的层 3 / 16：unknown_observed, venus_called, venus_proposed
其余 13 层均为"未测量"，各带原因（NO_CONTRACT_ACTIONS_RECORDED_YET /
NO_ADVISED_STEP_SETTLED_YET / REPLAY_RUNS_OUTSIDE_THE_RUNTIME /
REGISTRY_OWNS_THIS …），不写成 0
契约账本读数：
  CONTRACT_ONLINE_ROWS 0 | ADMITTED 0 | REFUSED 0 | REFUSAL_FAMILIES {}
  CONTRACT_REPAIR_ROWS 0 | CONTRACT_OFFLINE_ROWS 0
```

**三条契约账本文件目前 `ABSENT`（从未被创建）。** 这不是"闸门坏了"，是**样本缺失**：
闸门只在模型被咨询且计划为 `EXECUTE` 时才写行，而 repin 之后模型根本没被咨询过（见 E5）。
判据不是推断，是 `learning/local_planner_steps.jsonl` 的 mtime 停在 `19:31:42Z`。

## H. 本轮修掉的三个真实缺陷（测试在真实生产者上抓出来的）

三个都是**"签名对、样例对、真实对象进不来"**的静默失效：

1. **`packet_from_request` 读错字段名。** `RepairRequest` 用 `old_semantic` /
   `verifier_expectation`，适配器读 `semantic_target` / `expected_result`
   ⇒ **每一个包都会被自己的 `validate()` 拒**，且不抛异常。修复后新增测试断言**真实
   `RepairRequest`** 能通过 `validate()`。
2. **`candidate_from_proposal` 路由误诊。** `ENTRY_MOVED` 属于 `ROUTE_DIAGNOSES`，但带
   `new_semantic_target` 时会产出 `SEMANTIC_TARGET`，被 `REPAIR_CHANGE_TYPE_UNKNOWN` 拒
   ⇒ 路径类诊断必须优先折叠成 `ROUTE`。
3. **`candidate_from_cluster` 读错真实生产者。** `offline_learning.UnknownCluster` 用
   `members`，其 `representative` 是**对象**而非路径，`Path(obj)` 会抛
   ⇒ 适配器读四种拼法并统一命名（显式 id 优先，回落 path stem）。

**另修一处缺口**：离线的几何扫描原本复用在线扫描器，而在线的扫描器**故意豁免**
`candidate_bbox_norm`（那是它的 `UNTRUSTED_CURRENT_FRAME_PROPOSAL` 通道）。离线没有这条通道，
复用会把豁免一起带过去，模型可把坐标框塞进开放的 `payload` 被当作候选知识存下。
故离线另立 `GEOMETRY_KEYS_FORBIDDEN_OFFLINE` + `find_any_geometry`，parse 与 validate 两处都扫。
**教训：豁免清单属于"通道"，不属于"键"。**

## I. 未取证 / 未做的事（必须随结论一起说）

| 项 | 状态 | 原因 |
|---|---|---|
| `KNOWN_MODEL_CALLS = 0` | **未取证** | 需要 pin 之后的活体运行走到模型咨询路径；当前无该窗口（E5） |
| `SECOND_ENCOUNTER_VERIFIER_PASS` | **未取证** | 代码路径层由 `tests/test_learning_loop_wiring.py` 证明；真机需 AUTO 真的再次走到同一 UNKNOWN 屏 |
| `CONTRACT_*` 计数 > 0 | **未取证** | 同上，三条契约账本尚未被写过 |
| §28 `UnknownStateIdentity` 在 runtime 复用点的实际调用 | **未取证** | 类型与函数已就位并有测试，但生产复用点未走到 |
| 一次真实的 Skill Repair 升级被模型作答 | **未取证** | repair 通道只**提问**，答案是异步的；本轮没有真实升级事件 |

## J. 遗留（与本轮无关但会影响下一个接手者）

1. **`learning/auto_uptime.jsonl` 的 `repo_revision` 字段一直为空** —— 运行台账记不下它跑的是
   哪个 commit。本轮判断"生产是否已切到新 pin"不得不靠 `auto_uptime` 的**时间戳 + 进程模型 +
   import 图**三条间接证据拼出来。这是个真实的可追溯性缺口。
2. **`winter_agent_v2/formation_policy.py` 仍未跟踪（untracked）** —— 已核实 `git grep` 无任何
   已提交的 `.py` import 它，本轮的三个 commit 也不依赖它。
3. **`tests/test_learning_funnel.py` 的旧基线已过期**：他人在未提交改动里把 17 文件基线从
   `52 failed` 推到 `60 failed`，引用旧数字会得到假的"新增回归"。

## K. 复跑方式

```bash
# 从 pin 树跑（正确观察点；learning/ 是指向 DATA_ROOT 的符号链接，读的是同一批账本）
cd "C:/Users/xhw/.codex/worktrees/winter-prod-pinned/无尽冬日智能体"
E:/无尽冬日智能体/.venv/Scripts/python.exe tools/ui_venus_contract_acceptance.py
E:/无尽冬日智能体/.venv/Scripts/python.exe tools/ui_venus_contract_acceptance.py --json
E:/无尽冬日智能体/.venv/Scripts/python.exe tools/ui_venus_contract_acceptance.py --window-days 7

# 契约与学习闭环
E:/无尽冬日智能体/.venv/Scripts/python.exe -m pytest \
  tests/test_ui_venus_contract.py tests/test_ui_venus_online.py tests/test_ui_venus_repair.py \
  tests/test_ui_venus_offline.py tests/test_ui_venus_contract_acceptance.py \
  tests/test_learning_funnel.py tests/test_local_planner.py tests/test_unknown_learning.py \
  tests/test_skill_repair.py tests/test_offline_learning.py tests/test_learning_loop_wiring.py -q
# -> 387 passed
```

---

## 一句话结论

契约的**结构性部分已经落地并被证明**：六个类型、三套独立 schema/validator/ledger、三条链路
各自给出指令自己的拒绝码、四条 `false` 由"没有那条代码路径"保证、契约四模块 import 图 0
findings（387 项测试通过，坐标准入 `0 violation(s) / ADMITTED`，生产 pin 已对齐 `783a219`）。
**而"越跑越少"的那部分还没有样本**：`KNOWN_MODEL_CALLS = 0` 与 `CONTRACT_* > 0` 都取决于
pin 之后是否有真实运行走到 UNKNOWN 屏 —— 目前恰好一次都没走到，故未取证，不写估计值。
