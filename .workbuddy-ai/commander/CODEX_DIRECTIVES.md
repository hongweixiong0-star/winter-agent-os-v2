# WorkBuddy 持续自主开发 — 当前执行契约

更新时间：2026-10-02T10:18:26+08:00。最高用户指令全文：[WORKBUDDY_AUTONOMOUS_DEVELOPMENT_FINAL.md](WORKBUDDY_AUTONOMOUS_DEVELOPMENT_FINAL.md)，73节，逐字节保存；SHA256见同名meta.json。先读全文，再读本说明与 WORK_QUEUE.json。

## 所有权与入口

WorkBuddy已经在 results/WB-1002-01-HANDOFF-FACTS.json 记录独占claim，07:32任务DONE；后续060d75b/e49879f/77d5b4b已有开发/发布记录。当前claim归WorkBuddy。Codex本次仅交付治理文档和队列，未回收源码、设备或发布权，不push/repin/reload。后续Codex heartbeat只读。当前是否正在开发，必须另看fresh执行证据。

每次修改仍确认无并发源码/发布者、文件归属与设备租约。cq.py start不检查ownership；task01被BLOCKED也会被cq当依赖终态，所以仅plan可执行或DONE字段不能替代真实claim。已有效claim无需逐项再问用户。

## 持续工作循环

Fresh事实 → 最高价值根因 → Architecture Review → 最小实现 → targeted checks → 由WorkBuddy安全发布/加载 → 普通AUTO → Verifier/学习 → 重新选下一项。

八个旧任务保留为历史证据与seed backlog；本次新增模型服务可用性缺口。只保留事实/claim前置，不强制日历→训练→科研→巨兽→建筑顺序，不要求完成八单后停。每轮重新比较P0活性、共享断链、高价值UNKNOWN/NEVER_TRIED、真实deadline与高损失。cq.py plan给出可选集和静态建议，不能决定下一项。WorkBuddy可向同一WORK_QUEUE追加唯一ID的新根因单，记录why/scope/evidence/timebox/acceptance/retry；保留原单与结果，不创建第二开发队列。原files_scope是种子提示；共享根因涉及其它既有文件时先声明实际范围与所有权。

## 核心实施裁决

- FINAL中的设计字段/阈值按第0节视为建议；用户目标、安全、唯一架构、AUTO活性与真实证据优先。先追Goal→Scheduler→Capability→Route/Bootstrap→MAA→Verifier→Progress/Learning→Retry/Re-entry，避免UNKNOWN黑洞。
- CAPABILITY_EXPANSION默认保障约50%有效学习机会；测最近20次有效选择及30min有效工作。缺测量记NEEDS_EVIDENCE，不改计数、重复低价值观察或制造UNKNOWN凑比例。硬deadline/真实高损失临时优先，之后恢复学习机会。
- 失败有界退避，到期/相关新证据可重入。所有合法工作暂cooldown/等待真实条件时允许有界WAIT并保留下次唤醒；不能永远移除UNKNOWN，也不能每帧重撞。解除cooldown的Progress须关联当前Goal/能力。
- FINAL的L0–L5是Goal覆盖成熟度；只有证据支持L5才COVERAGE_COMPLETE。不得混用既有Pipeline/Skill分级。cq DONE、服务ready、导航PASS、模型proposal、MAA点击、单步Progress、Goal成功、Candidate复用、Stable晋升分开记录。
- Candidate用语义/模板/OCR锚/关系及真实Verifier证据；不存历史绝对坐标或一次性bbox。FIRST/SECOND两个真实encounter的trace通过parent_trace/同能力身份关联，不要求共用同一个trace_id；PROGRESS不能虚称PASS。Candidate失败恢复后继续其它Goal。
- 保护既有STABLE的修复/替换晋升要求，与普通Candidate在当前帧/Policy下可执行相分离；不恢复全局历史成功/Shadow准入禁令。

## 不变量与固定策略

唯一Global Scheduler、Executor、WorldState、Goal Library、Skill Registry、现有Session Engine；唯一UI-Venus-2-9B Q4_K_M/32768；MAA执行、Verifier判成功。Known/L1/Semantic Retry/实时环模型0；Fishing realtime OCR/模型/Scheduler per-frame均0。

WorkBuddy/Codex仅开发，runtime通道enabled=false/auto_submit_jobs=false保持退役。00_MASTER_RULES历史§10b/§10c runtime gateway及§23固定队列/Codex专属写入被最新用户FINAL覆盖；其它架构、安全、证据约束保留。

真钱永久禁止；Fishing仅普通鱼饵，特殊模式/宝藏/票券/钻石均禁止；资源消费及不可逆动作遵当前授权/Policy。模型不选Global Goal、不切号、不直接点设备、不宣告完成或晋升。操作需现有独占租约与当前帧grounding；模型每屏默认≤2次，有界预算，结果未知先观察。

显式暂存小提交，保留无关dirty/untracked及mutable数据；禁止reset --hard/clean -fd/checkout ./restore ./blind stash pop/git add .或force push。不要为测试数字长停AUTO。

## 事实、结果与下一项

本次HEAD/origin=77d5b4b09bbe21193cfe467d6363dc66726b3ce6；生产PIN=951abbdd039c4955f2cd99fd442ae2aea56ffae3。当前facts见WORK_QUEUE.current_verified_facts，旧base_facts及原单是历史捕获，不作为当前状态。10:12模型health拒绝连接，Known AUTO仍存活；先fresh核查是否已恢复，再比较最高价值下一项。

结果继续用现有cq.py/EXECUTION_STATE/results/BLOCKED_QUEUE/REVIEW_REQUESTS，真实游戏证据优先；环境等待保留具体条件及retry。开发单BLOCKED后，相关条件变化可追加关联原结果的新尝试ID，保留原终态；Runtime Goal仍经现有Scheduler/cooldown到期重入。能自主裁决的实现冲突记录并继续其它工作，不机械等Codex。仅用户固定策略、真钱/不可逆风险或真正需要产品选择时询问用户。

完整旧Commander说明/Review/队列/START_HERE已保存在仓库外：C:/Users/xhw/.codex/backups/winter-workbuddy-continuous-20261002T101218，manifest含路径、字节数和SHA256。本交付没有改WorkBuddy执行态、历史Episode或实际生产代码，也不证明新调度/学习规则已实现。
