# Winter Agent OS V2 记忆系统架构评审与分层设计

评审时间：2026-09-14 晚 · 评审人：寒野（接管开发专家）
数据来源：对项目目录的全量实测（非记忆），所有数字可复核。

---

## 0. 直接回答：现在这套架构能不能支撑连续作战？

**能支撑 70%，但有两个洞必须在一周内补上，否则会在下一次长中断时出事。**

今天两次接管演练（假设丢失全部聊天上下文、只读项目目录）都成功恢复了真实状态并继续开发——这证明 **handoff 层是可靠的**。但盘点发现：

1. **双记忆根已经分裂**：`.workbuddy-ai/memory/`（32.7 KB，项目约定路径）和 `.workbuddy/memory/`（5.7 KB，WorkBuddy 宿主读写路径）**同一天各有一份日志**，内容部分重叠、部分互不知情。这就是"第二事实源"的开始——再不加规则，一週内必然出现"读错记忆"的事故。
2. **证据库没有索引**：`evidence/` 有 57 个文件，全靠文件名人肉翻。任何"这个结论的证据在哪"的问题都要靠记忆回答，而记忆恰恰是最不可靠的层。
3. 日志无蒸馏规则（06-13 的日志已开始陈旧）——**紧迫性最低**，但规则应该现在写下来。

---

## A. 现状全景（实测数字）

| 层 | 路径 | 现状 | 写手 | 读者 |
|---|---|---|---|---|
| 长期知识 | `.workbuddy-ai/memory/MEMORY.md` | 2.9 KB | 接管专家（人写） | 新会话第一读 |
| 会话流水 | `.workbuddy-ai/memory/2026-09-1{3,4}.md` | 30.5 KB，追加式 | 接管专家 | 复盘 / 蒸馏源 |
| 会话流水② | `.workbuddy/memory/2026-09-14.md` | 5.1 KB ⚠️ 分裂 | 宿主注入的约定路径 | 宿主 + 接管专家 |
| 自动化记忆 | `.workbuddy/memory/automations/<id>/memory.md` | 0.7 KB | 每小时情报自动化 | 该自动化自身 |
| 当前真相 | `.workbuddy-ai/handoff/01+08+09` | 14.9 KB，生成器整写 | `update_workbuddy_handoff.py`（唯一写手） | 每次接管 |
| 操作现场 | `handoff/02/03/04/05/06/10` | 80.7 KB，AUTO 块+手写区 | 生成器（AUTO）+ 专家（手写） | 每次接管 |
| 宪法 | `handoff/00_MASTER_RULES.md` + 根目录 `START_HERE.md` | 15.7 KB | 人写，低频改 | 每次接管第一步 |
| 机器态 | `learning/`（episodes.jsonl 1.4 MB / 904 行、runtime_snapshot、goal_state 等 17 个文件） | 1.49 MB | 运行时进程 | 生成器、审计脚本 |
| 证据库 | `evidence/`（57 文件）+ `dataset/truth_audit/`（回归 fixture） | 数百 MB | 运行与实验脚本 | 验证器、回归测试 |
| 技能台账 | `.workbuddy/skills/SKILL_AUDIT.json` + `skill-install-gate/` | 新建 | 安装门禁 | 安装决策 |

---

## B. 缺口分析（按危险度排序）

### B-1 双记忆根（🔴 最高危，已发生）
`.workbuddy-ai/memory/` 是项目自己长出来的约定；`.workbuddy/memory/` 是 WorkBuddy 宿主在每次会话注入的约定路径。今天两边都写了 `2026-09-14.md`：`-ai` 版 20.6 KB（六轮完整记录），宿主版 5.1 KB（第四轮起的部分记录）。**内容已经开始漂移**。危害：新会话不知道该信哪份；蒸馏时会漏掉一边的事实。

### B-2 证据无索引（🟠 高）
"DISPATCH_NOT_PROVEN 的根因证据在哪"这类问题，答案是"记得在某个 truth_audit 目录里"。57 个证据文件 + 数十个 fixture 没有索引，结论→证据的回溯靠会话记忆。会话一断，回溯成本指数上升。

### B-3 会话流水膨胀（🟡 中）
2026-09-14 一天就写了 20.6 KB 流水。按这个速率，一周后 MEMORY.md 的蒸馏压力会很大，而没有"什么时候蒸馏、怎么蒸馏、原文去哪"的成文规则。episodes.jsonl 904 行/1.4 MB，增长可控但同样没有归档线。

### B-4 手写区漂移（🟡 中）
`03/04/05/10` 的手写区质量很高（今天救过场），但它们的内容会随轮次堆积——05 已经有六轮记录堆在一起，新人需要读 18 KB 才能找到"现在什么最重要"。

### B-5 宿主记忆的写入权（🟢 低，但要知道）
`.workbuddy/memory/` 由宿主注入和读取，**不能删除或拒写**——只能规定"那边写什么"。

---

## C. 四层设计提案（映射到现有文件，零破坏迁移）

```
L1 长期记忆（月级，人写，不常变）
   .workbuddy-ai/memory/MEMORY.md
   架构决定 / 环境铁律 / 操作者偏好 / 蒸馏后的教训主题

L2 当前真相（每次接管重算，机器唯一写手）
   .workbuddy-ai/handoff/01_CURRENT_TRUTH.md
   .workbuddy-ai/handoff/08_LIVE_METRICS.json
   .workbuddy-ai/handoff/09_RUNTIME_STATE.json
   .workbuddy-ai/handoff/06_DECISIONS.md（决定日志，追加）

L3 操作工作记忆（每轮更新）
   .workbuddy-ai/handoff/03_NEXT_ACTION / 04_OPEN_ISSUES
   .workbuddy-ai/handoff/05_RECENT_CHANGES（只保留最近 5 轮）
   .workbuddy-ai/handoff/10_LAST_HANDOFF（最新一轮停止点）
   会话流水：.workbuddy-ai/memory/YYYY-MM-DD.md（追加式）

L4 证据库（追加式 + 索引）
   evidence/ + dataset/truth_audit/ + dataset/candidate/（带 provenance）
   evidence/INDEX.json（新增：每条证据一行——路径/产出轮次/支撑的结论）

L0 机器态（进程写手，人只读）
   learning/*（episodes、runtime_snapshot、rotation、candidate pool）
```

**宿主路径的处理**：`.workbuddy/memory/` 由宿主管理，保留其 daily 日志作为"当日流水镜像"，但规则写入 00_MASTER_RULES：**长期知识与蒸馏结论只写 `.workbuddy-ai/memory/MEMORY.md`；宿主路径的日志视为缓存，不作为事实源。** `MEMORY.md` 在宿主路径只放一行指针。

### 迁移计划（零删除）

| 步骤 | 动作 | 风险 |
|---|---|---|
| M1 | 把 `.workbuddy/memory/2026-09-14.md` 中 `-ai` 版没有的段落合并进 `-ai` 版（人工比对，两边都保留原文） | 低——纯追加 |
| M2 | 在 `.workbuddy/memory/MEMORY.md` 写入指针（"事实源在 .workbuddy-ai/memory/MEMORY.md"） | 无 |
| M3 | 00_MASTER_RULES 增补"记忆写入路由"一节 | 无 |
| M4 | `update_workbuddy_handoff.py` 增加 evidence/INDEX.json 生成（第 4 步的产出） | 无——生成器已有全部钩子 |

---

## D. 每层的 trade-off（诚实版）

**L1 长期记忆**：优点是检索快、上下文占用小（3 KB 级）；代价是**人工维护**——写多了没人读，写少了丢教训。蒸馏规则必须成文（见 E），否则它会烂掉。**不放进任何自动生成**：机器生成的"长期知识"等于把 episodes 复读一遍，没有蒸馏价值。

**L2 当前真相**：优点是零手写、零漂移、带时间戳与 commit（今天 5 步接管全靠它）；**代价是生成器只能数到脚本知道的东西**——"为什么这是最高价值任务"这类判断永远需要手写区补充。这是设计使然，不是缺陷。

**L3 操作工作记忆**：优点是"新会话 5 分钟上手"；代价是**膨胀**——05 已经 18.7 KB。规则：只保留最近 5 轮，更早的结论沉淀进 06（决定）或 MEMORY.md（教训），原文不删但不占当前位置。

**L4 证据库**：优点是"每个结论可回溯"（本项目的诚实性基石）；代价是**体积**（截图数百 MB，git 外置）与**登记纪律**——索引的完整性取决于每次实验是否写了 provenance。今天的 fixture 都带 provenance.json，习惯已经成型，只差索引。

**L0 机器态**：唯一真源是进程；人绝不手编。episodes.jsonl 将来 >5000 行时按月归档，**当前 904 行，不动**。

---

## E. 打扫规则（成文，避免"以后再说"）

1. **每日日志**：追加式。超过 30 天的日志 → 按主题蒸馏进 MEMORY.md → 原文移入 `.workbuddy-ai/memory/archive/`（移动，不删除）。
2. **handoff/05**：每次新轮次把最旧一轮压成三行进 06 的对应决定条目，保持 ≤5 轮。
3. **episodes.jsonl**：>5000 行时按月切分到 `learning/archive/episodes-YYYYMM.jsonl`，主文件只留近两月。
4. **evidence/**：只进不删；INDEX.json 由生成器重算，损坏可随时重建。
5. **蒸馏触发**：每月 1 日由每小时情报自动化顺带检查一次日志年龄（它已经在跑，加一行检查即可），发现 >30 天日志时在 03_NEXT_ACTION 顶部提醒，由当值会话执行蒸馏。

---

## F. 落地顺序

| 优先级 | 事项 | 工作量 | 效果 |
|---|---|---|---|
| **P0（现在）** | M1+M2+M3：双记忆根合并规则 + 指针 + 宪法增补 | ~20 分钟 | 消灭第二事实源，这是唯一"会出事故"的洞 |
| **P1（本周）** | M4：evidence/INDEX.json 进生成器 | ~30 分钟 | 结论→证据回溯从"翻目录"变成"查索引" |
| **P2（可等）** | 05 轮次压缩规则生效；月度蒸馏检查进自动化 | 各 ~15 分钟 | 防未来膨胀 |

---

## G. 结论

**handoff 层（L2+L3）今天已被两次接管实战验证，保持不动；它的"生成+手写分区"设计是这个项目最值钱的架构决定之一。**

必须改的只有一件事：**双记忆根**。它不是设计问题，是历史意外（宿主路径与项目路径各自生长），但事实源的分裂是所有记忆系统最经典的死法。合并成本 20 分钟，收益是"任何会话读到的长期知识只有一份"。

其余（证据索引、轮次压缩、月度蒸馏）都是防未来劣化的保险，按 P1/P2 排队即可，不影响当下的连续作战能力。
