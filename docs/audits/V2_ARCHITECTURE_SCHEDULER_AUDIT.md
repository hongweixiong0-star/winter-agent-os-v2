# Winter Agent OS V2：架构、逻辑与调度深度审计

## 交付版本复核 — 2026-09-22（优先阅读）

**最终基线：0d06b9d4ffd1ab6b05a290c94e63faf879a37d03。** 后文A–E保存09-21初始快照及复现，以便追踪；本节和文末“最终裁决”覆盖其中已过时的现状判断。没有把后台WorkBuddy的修复算作本次审计的改动。

当前main相对已缓存origin/main领先33个提交；09-21实读远端为d7d9a40，本次续审未再次刷新远端，33不是已重新联网确认的远端差值。新增源码重新复制到隔离目录核对，未操作真实设备。新增证据：[09-22复核](E:/WinterAgent/docs/audits/evidence/20260922)。

| 原问题 | 最新结论与证据 |
|---|---|
| A01 Goal归属分裂 | **仍存在，P0**。runtime当前1556–1603重新排board并改_committed_goal，但路线只在current_goal为空时切换；_step_goal 600/626仍优先取新best_goal。最新9次打野失败也记在CLAIM_EXPLORATION_IDLE等非打野Goal下 |
| A02 三营 | **仍存在，P0**。Brain、quick_panel及camp契约未修；当前复现仍三营DISCOVERED/目标营都BACK。新增769条记录中TRAIN_TROOPS仍0 |
| A03 角色 | **仍缺生产轮询与隔离，P1**。新增fairness/control经验也以全局goal/page+control为key，不是多角色实现 |
| A04 通用Verifier失败结束run | **该直接返回分支已修，不再作为当前待实现修复**。410fc31增加有界让位、失败control记忆；复现现在MAIL失败后选择SHIELD_CAMP_TRAINING，yielded包含两者。A01仍可能让错Goal被defer；保持回归验收 |
| A05 验证租约 | **自拒绝已修，所有权风险仍在**。_owns_the_lease现按mode+owner允许验证；自定义合法验证不再零动作租约退出。但不同job均可用DEVELOPMENT_VALIDATION字符串，未核对job/trace/token；GUI的process/validating分离风险未改 |
| A05 过期验证版本 | 0322eaf已增加superseded结算/释放旧验证请求，不能再断言“旧版本永远请求”。新增测试通过；按真实job验证释放并恢复AUTO，不能仅凭祖先版本声称修复已被当前代码保留 |
| A06/A07/A08/A10 | 原核心函数未变：寻敌预算、派兵因果Verifier、VERIFY_GATHERING缺live接线、体力store结构错用仍在 |
| B2 DISCOVERED竞争 | **生产排序已改变**。现在Runtime调用GoalLibrary.rank→goal_utility，包含fairness、资源适配、历史与重复失败项；原“仅按priority”只适用于旧快照/不传world的兼容best接口。新排序已接线，不能继续按旧180/70直接证明长期饥饿 |
| 新增经验复用 | 5c00337/0d06b9d在模板失配时使用历史位置；风险表检查保留，但弹窗身份与坐标复用上下文仍不足，见A11 |
| 新生产打野阻塞 | 新窗口9次DISPATCH_BEAST全BEAST_DISPATCH_NOT_PROVEN，编队OCR名字“巨膜”4次、“泰”5次均无法lookup；Brain却已经允许出征。见A12，这是当前连续打野最直接的新增证据 |

**最新测试口径：** 原19节点在最新隔离快照重跑为 **17失败/2通过（20.02秒）**。增加通过的是“deferred Goal不挤走仍可做的工作”；预留槽位测试继续通过。不是当前全量仅17失败。新增6个模块共 **113通过、7个subtests通过（1.08秒）**，包含utility、验证自有租约、superseded版本、经验复用和失败让位。原99项通过属于旧快照。

新增测试首次在系统Temp副本中有4项失败：经验模块刻意排除Temp来源，导致测试的“项目截图”也被排除。改在正式工作区以外的独立audit-sandbox运行后113全通过，未修改断言或生产代码；这4项不列为产品失败。

**最新生产窗口：** (2026-09-21T13:37:39.825287Z, 2026-09-21T23:16:01.939418Z]，769条新增记录；TRAIN_TROOPS/RECALL_MARCH/VERIFY_GATHERING均0，DISPATCH_BEAST 9失败。窗口跨版本，不能把769条都归属最终HEAD。失败样本保留完整before/after及repo_revision；有些动作后已回MAP并出现MARCHING，故“Verifier失败”也不等于“游戏绝未出征”。

**最新最小修复顺序：** F01统一Goal承诺 → F02/F03三营契约与动作 → F06同时修A12的出征前后身份契约及A07因果证明 → A11约束历史坐标复用 → F04剩余租约隔离 → F07采集回收 → F08角色。F05改为已修代码的回归验收，不重复实现；F09测试隔离仍要做。全程复用现有主链。


审计日期：2026-09-21。性质：独立只读审计。没有修改生产代码、启动/重启 AUTO、连接或操作 MuMu、抢占租约、提交或推送。只新增本报告与其审计证据。既有 Commander Queue 本轮不改写；下述修复清单是审计建议，不是已启动的开发任务。

**结论：问题主要出在模块之间的状态与执行契约。当前最直接的阻塞是执行路线与 Goal 归属分裂，以及三营读数没有接通三营实际操作。已有 Scheduler、Verifier、角色标签，并不代表这三条契约已经成立。无需以整体重构代替修复。**

证据目录：[本轮证据](E:/WinterAgent/docs/audits/evidence/20260921)。文件名在下文直接引用。历史文档只用于寻找入口，不作为完成证明。

## A. 当前真实状态

### A1. 版本、工作区与审计边界

| 项目 | 核实结果 |
|---|---|
| 正式入口 | Start-Winter-Agent-V2.cmd；固定项目 .venv/Scripts/python.exe / pythonw.exe，执行 preflight 后启动 tools/control_panel.py |
| 初始 HEAD / 分支 | e2afaa3 / main；已包含快捷面板读数提交 |
| 审计期间 HEAD | d56875dbce7105f6b7ed9615a77fe629d57997e6；相对 e2afaa3 只新增一张快捷面板归档截图 |
| 远端 | git ls-remote 实读 main=d7d9a40d12db1e08b55ff8168f6c94e46b815f1e，与本地 origin/main 一致；本地领先25、落后0。没有执行 fetch/push |
| 工作区 | Commander三文件是前轮交付；其余 config、knowledge、learning、memory 多项生产/开发状态仍有修改。审计期间 WorkBuddy 又修改 tools/run_live.py 的版本门禁；不是审计者的修改 |
| 测试快照 | 系统临时目录 winter_readonly_audit_f22fum81；复制当前代码、配置、知识、必要归档图片和状态，不使用工作区作为测试写入目录 |
| 漂移处理 | manifest.json 保留代码 SHA256。导出时除 tools/run_live.py 外，所列关键源码与测试快照一致。run_live 新增 ancestor-version 放行逻辑已额外静态复核，见 V2-A05 |
| 最新取样 runtime | PAUSED，原因为 DEVELOPMENT_VALIDATION 持有 OPEN_TRAINING_PAGE 设备租约；不是已证实的 worker crash。历史 unexpected_worker_exits=15、watchdog_restart_count=21，不清零、不当作本窗口增量 |
| 历史全量测试 | .full_raw.txt 的确写着19 failed / 2106 passed / 7 skipped / 486 subtests passed，耗时1533.43秒；文件本身没有完整版本指纹，不能据此归属当前HEAD |

本报告的生产统计窗口固定到 **2026-09-21T13:37:39.825287Z**，共448条。AUTO与WorkBuddy仍在后台活动，因此后续新增记录不混入这个统计。审计快照与最终工作区不是同一时刻的静止仓库。

### A2. 实际生产链

```text
Start-Winter-Agent-V2.cmd
  → tools/preflight.py
  → tools/control_panel.py::ControlPanel.start [4448]
      → 后台线程 _run_unified_worker [4753]
      → _ensure_device [4790]
      → 子进程 tools/run_live.py --max-actions 24
          → 启动前版本指纹 freeze_process_revision [34]
          → ADBDevice + build_maa_adapter + HybridVision
          → RuleBrain / v2_registry / LiveRuntime
          → LiveRuntime.run [1113]
              → 检查设备租约 → screenshot → Vision.observe
              → _record_goals [688]
                  → observation_store.record/load
                  → GoalLibrary.discover [463]
              → policy + CapabilityGate.blocks → GoalLibrary.best [745]
              → route_for → Brain.current_goal / goal_id
              → RuleBrain.decide
              → Scheduler.tick(world, decision) [scheduler.py:39]
              → ExecutorRouter.execute [337] → MAA / ADB
              → 新截图与观察 → VERIFIED_ATOMIC对应Verifier
              → EpisodeStore / goal_progress / GoalStateStore
              → 下一step，或结束本worker
      → GUI收到complete/failure → 非fatal时安排下一worker
```

这个顺序有两个重要细节：

1. **Goal选择和路线承诺实际由 Runtime + GoalLibrary完成；Scheduler主要负责检查skill readiness及执行一个已经选好的Decision。** Scheduler.select_next存在，但全仓生产调用搜索只找到定义，没有生产调用。不能把它的多observation测试当成多角色AUTO已经接通。
2. Runtime把同一个Decision传给Scheduler.tick，过去“decide两次导致操作/Verifier错配”的问题在当前主链已修。没有发现正式AUTO同时调用两个Scheduler实例执行同一步。GUI仍保留手工任务_run_worker及验证_run_validation_worker入口，但它们都调用run_live；真正需要修的是生命周期/设备所有权，不是再创建调度器。

MAA取帧与动作选择是两个轴。run_live先尝试MAA observation device；ExecutorRouter按backend_routing选动作。当前有ADB动作与MAA取帧组合，不能据此认定MAA没有接入。Runtime里搜索栏swipe和部分恢复press_back直接调用device，绕过Scheduler/Router逐动作账本；device可能是MAA适配器，也可能ADB fallback，**不是所有直接调用都等于裸ADB**。这些恢复动作应补统一可归因证据，而不是重新实现一条执行链。

### A3. 当前证据能证明到哪一步

- 普通打野：窗口内3条DISPATCH_BEAST，均SUCCESS/verifier_ok=true。两条12:16、12:37的记录有体力440→430→420的状态差分；第三条13:26。能证明若干单次出征，不足以证明连续消耗至体力<30。
- 这些出征的goal_id分别出现KEEP_TRAINING_PRODUCTIVE、CLEAR_INTEL，和实际打野动作不一致，见A01。不能用这些字段直接计算各Goal闭环率。
- TRAIN_TROOPS=0，RESEARCH=0；OPEN_INFANTRY_TRAINING=1，WAIT_FOR_CAMP_MENU=21且全部SUCCESS。打开训练页、等待菜单成功不等于启动训练成功。
- 有DISPATCH_MARCH成功，但VERIFY_GATHERING注册后仍未进入LiveRuntime允许执行表。采集状态、召回、返程释放槽位不能由派兵PASS替代。
- 角色编号已写Episode，但生产循环从一个持久化role_identity取一次角色；没有找到切换全部角色并轮询工作的生产链。
- 旧RR-004“仅凭时间给job记功”的说法不能原样沿用：当前escalation_queue已有execution_mode、trace、版本等校验，相关validation_driver隔离测试通过。仍存在版本门禁、验证租约与结算之间未闭合的问题。
- 72h无人值守、三营持续生产、多角色全部可做任务耗尽后才等待：均没有足够证据验收。

### A4. 测试方法和结果

19个历史失败节点在隔离快照逐项重跑：**18失败、1通过，21.96秒**。每个测试前清空隔离observation store再跑：仍**18失败、1通过，22.28秒**，但部分失败形态改变，证明有状态依赖。通过的是预留槽位可供体力Goal使用的测试。

额外跑9个相关测试模块：**99 passed、34 subtests passed，35.71秒**，涵盖让位、设备断连、租约、三营读数、巡检排序、预留槽位、验证结算、worker等待和退出语义。第一次少复制一张fixture导致3失败；补齐同一归档图片后99通过，该次环境缺件不计作产品缺陷。

测试运行拦截对正式工作区的写入、网络连接，以及ADB/MuMu/run_live/control_panel/任务计划启动等子进程。测试代码和OCR只在隔离副本执行。没有重跑全部2106个历史通过项，不能把本轮结果写成“当前全量通过率”。完整19项见附录。

## B. 架构与调度问题清单

分类说明：“确认缺陷”表示代码及离线复现吻合；另标生产记录是否支持。同一问题有离线证据，不等于已经观察到每一种线上后果。

### V2-A01 — P0 / 确认缺陷：执行路线、当前Goal、Episode归属不是同一份承诺

- **位置**：runtime.py::run 1219–1264；_step_goal 562/588；_yield_to_next_goal 490–517；capability_gate.py::load 455及_streak_and_last。
- **触发**：路线已经是BEAST_HUNT/TRAIN等；下一张图又发现优先级更高或不同的best_goal。
- **调用路径**：discover→best把_committed_goal更新为新Goal；只有brain.current_goal为None才改路线；Brain继续旧路线；_step_goal却优先返回新的best_goal。SAFE_STOP/执行拒绝又把该best_goal放进_yielded_goals。
- **后果**：执行A、记录B，甚至让B承担A的拒绝。goal_progress、no-progress deferral、开发升级目标与生产统计都可能指向错误任务。不是仅GUI显示问题。
- **证据**：custom_probes.json：executing_route=BEAST_HUNT、committed=AVOID_STAMINA_WASTE，episode_owner却为SHIELD_CAMP_TRAINING。production_excerpt.json：两次DISPATCH_BEAST记到KEEP_TRAINING_PRODUCTIVE；OPEN_INFANTRY_TRAINING记到MAIL_ROUTINE；菜单等待记到DAILY_ACTIVITY_TARGET。
- **影响**：跨Goal导航期间普遍适用；足以把可执行能力错误降级、延迟真正需要修复的能力。
- **最小修复**：Runtime维护同一轮实际已承诺的goal_id/route/目标身份；明确何时释放/切换。归因、Verifier进展、让位都用实际承诺。发现的新Goal只作为候选，不能静默替换记账标签。
- **验收**：旧路线跨HOME/MAP/MARCH不被新巡检Goal改名；A失败只defer A；两个不同Goal的完整生产链各自闭合。历史Episode保持不变，另生成可追溯派生纠正指标。

### V2-A02 — P0 / 确认缺陷：三营Goal存在，但没有接通“选定那个营→启动那个营”

- **位置**：goal_library.py::_append_camp_training_goals 641；brain.py::decide 518、902–1021、1051–1057；ocr.py::read_quick_panel 1345、_with_quick_panel 2785；camp_training.py::merge_camps 260；runtime.py:218。
- **触发一：新快捷面板**：parser输出status/queue_available，GoalLibrary却读observed/busy。merge_camps只复制字典，不做字段归一化。
- **复现一**：快捷面板一营IN_PROGRESS、两营IDLE，进入生产_with_quick_panel→discover后，三个Goal全部DISCOVERED；真实空闲事实没有变成READY。
- **触发二：营地选择**：三Goal映射到TRAIN，但Brain几乎不使用训练goal_id；POWER_DETAILS固定NAVIGATE_INFANTRY_CAMP。站在盾营忙碌页、目标是矛营/射手营时，也返回BACK，而不是切到目标营。
- **复现二**：custom_probes.json中三个训练goal_id在同一盾营忙碌页产生相同BACK。注册表没有三营切换skill；独立CampReading模型和读数测试通过，不能弥补动作链缺失。
- **入口后果**：当前power路线还能落入INFANTRY_CAMP_HIGHLIGHTED→两次WAIT→guided-step SAFE_STOP。新快捷面板只提供了诊断，没有提供经过验证的新入口。quick_panel打开时直接OPEN_POWER_OVERVIEW是否能命中也缺生产证明。
- **生产证据**：窗口TRAIN_TROOPS=0，21次菜单等待PASS；已有训练页证据说明盾营曾忙碌，不证明Agent开启了训练。不能把“看到训练中”记成“本轮训练成功”。
- **最小修复**：统一CampReading契约，按既有单WorldState存三营；把目标camp作为TRAIN路线参数贯穿导航、页签选择、动作和Verifier。复用入口，补最小语义切营能力，不另建训练Manager。
- **验收**：盾忙/矛闲/射手未知时依次检查剩余营；三种Goal打开正确营，空闲→训练中+倒计时，Verifier同时验证目标营身份；busy营不关闭其他营Goal；跨页保留带新鲜度的同角色读数。

### V2-A03 — P1 / 确认缺失：角色标签不等于多角色调度和状态隔离

- **位置**：run_live.py角色读取（快照236–245，当前新增代码后下移）；runtime.py:348、592–617、655；observation_store.py:35–36、87、167；capability_gate.py:455；goal_library.py::discover 463。
- **触发**：当前角色无可执行工作、用户换角色，或不同角色共享同一learning文件。
- **调用路径**：TruthAudit读取持久role_identity→Runtime固定role_id→全局observation_state/goal_state/stamina_supply/resource_rotation；CapabilityGate按goal_id汇总历史，不按role过滤。
- **证据**：record接口没有role参数；load只返回domain→Observation。隔离写入175体力后，无第二角色存储命名空间可切换；注册表role/account切换skill为空；Scheduler.select_next无人调用。WorldState本身也没有携带每帧的已确认角色身份。
- **后果**：不能实现“本角色无工作→其他角色→全都无工作再等”。手动换角后仍可能复用前角色fresh体力、冷却和deferral。已确认结构不隔离；本轮未操作两角色，**跨角色错误执行尚未真机证实**。
- **最小修复**：既有状态文件按已观测role key隔离；切换时失效瞬时状态并重新读HUD；在现有控制循环接入有界角色轮询。无已验证切换能力时先明确单角色限制，不能假装全部角色完成。
- **验收**：A无工作/B有工作继续B；A失败不defer B；A=2队/B=6队切换不继承；所有角色等待后条件恢复可重入；繁忙角色也不能无限独占。角色身份未知时不得借用别的角色缓存。

### V2-A04 — P1 / 确认缺陷：非致命Verifier失败仍直接结束本worker，和SAFE_STOP让位不一致

- **位置**：runtime.py:1418、1586的让位分支；1814–1820附近通用verification失败返回；control_panel.py::_complete/完成回调 5222–5249。
- **触发**：输入实际发出，但目标页/状态未被Verifier确认；不属于资源搜索、体力拒绝、BACK等专门恢复分支。
- **复现**：custom_probes2.json：MAIL与盾营两个READY，模拟OPEN_MAIL动作发出但仍HOME，max_actions=6；只执行1步就OPEN_MAIL_NOT_PROVEN退出，yielded为空，盾营没有机会。
- **实际后果边界**：这结束的是**本轮worker**，不是必然永久关闭GUI AUTO。continuous=true且非fatal时GUI通常30秒后重启；语义目标拒绝和预算用尽可立即重启；no_idle/reserved可延迟10分钟。新worker可能再次选同一失败任务。
- **生产支持**：窗口存在共享奖励关闭、探索领取、BACK等验证/执行失败；此处不把每次失败都断言为整个AUTO停止。
- **最小修复**：统一“Goal受阻”“环境不可用”“全局fatal”的退出契约；失败后新观察确认安全页面，再让该Goal退出本轮，其他可到达Goal继续。若阻塞弹层无法安全离开，应保留环境/页面阻塞，不承诺其他任务一定可执行。
- **验收**：有另一READY时非fatal失败可让位；无法离开的弹层有界恢复；设备断连不当成Goal失败；同一失败签名跨worker预算不无限退款。

### V2-A05 — P1 / 确认缺陷与风险：开发验证的版本、租约、进程生命周期没有闭合

- **位置**：run_live.py构造LiveRuntime时无条件传DeviceLease；runtime.py::run 1169–1179；device_lease.py::acquire 220–255；control_panel.py::start 4448、_maybe_validate 4613、_run_validation_worker 4701。
- **确定复现**：取得DEVELOPMENT_VALIDATION租约，启动同job/trace且execution_mode=DEVELOPMENT_VALIDATION的LiveRuntime，返回device_leased_for_development，steps=0。guard只允许OWNER_GAMEPLAY，没有识别“这是我的验证租约”。
- **其他确定逻辑**：两个不同job以同一个OWNER_DEVELOPMENT_VALIDATION字符串acquire，第二个得到第一个的租约并报告already held；不是按job/trace/process验证所有者。文件read-check-write没有进程互斥，release不验证调用者所有权。
- **GUI风险**：start只看process/starting，不看validating；验证worker把process保存在局部变量，普通AUTO的self.process守卫看不到它。可能启动第二worker或提前_ensure_device。**未实际制造双worker争抢**，列为可达并发风险。
- **生产日志**：validation.log反复出现旧expected=91e3475与新actual不等，退出4；runtime有验证租约让位。本次读取能证明版本门禁失败，不能证明该次已经走到租约自拒绝。
- **审计期间新改动**：WorkBuddy未提交的run_live.py允许expected为actual祖先时继续，日志明确“validation_settlement credits none”。这缓解启动拒绝，却仍不能通过旧expected版本结算，且未改租约自拒绝。祖先关系也不能证明dirty tree没有覆盖/回退那个修复。
- **最小修复**：校准任务明确绑定实际待验证的版本及新验证尝试身份，保留原job溯源；实际载入版本与结算使用同一契约。租约用不可混淆token+job/trace/process；GUI把校准与AUTO都纳入同一worker拥有权；只在原子动作安全点交接。
- **验收**：同job合法校准能执行≥1步；其他job、AUTO被拒；原子交接无双输入；释放/超时后AUTO恢复；新版本验证能结算而不冒领旧job改善；先解决本项再宣称自动开发闭环无人值守。

### V2-A06 — P1 / 确认缺口：一次野兽搜索成功后，下一轮搜索预算没有按成功出征重置

- **位置**：brain.py:1336/1369的目标点击重置、1414–1507的搜索/扫描预算；runtime.py成功尾段只有DISPATCH_MARCH资源轮换，没有DISPATCH_BEAST后的寻敌生命周期。
- **触发**：已用客户端搜索并出征成功；下一张MAP无可见可点击目标，但体力与普通行军空位仍足够。
- **复现**：custom_probes2.json，beast_search_used=true、体力100、1/3队，连续决策为SCAN_MAP_FOR_BEAST×5→SAFE_STOP verified_beast_target_not_visible；不重新走客户端搜索。AUTO的AVOID_STAMINA_WASTE可能改去Intel，不是持续普通打野的证明。
- **边界**：新目标标签出现时，现有代码可以重置预算；因此不是“任何情况下都不能第二次出征”。三个生产PASS也分属不同run，不能反证此失败条件。
- **最小修复**：在真实DISPATCH_BEAST Verifier通过后完成该寻敌attempt；为下一只目标重建有界搜索预算，保留拒绝同一集结卡的防循环记忆。不能在每次观察时无条件退款。
- **验收**：同一个AUTO工作周期连续两次客户端搜索→普通攻击→出征；每次有体力/队列变化；体力30继续检查实际10体力攻击；不足时按客户端拒绝让位；集结卡不进入solo链。

### V2-A07 — P1 / 确认Verifier漏洞，尚未证实线上误判：已有行军可替新出征作证

- **位置**：verifier.py::verify_beast_dispatch 906–925。
- **触发**：before是胜券在握编队页，已有一队在外；动作后回MAP，原有队伍还在行军。
- **复现**：before/after march_used均1、体力均100，after有旧MARCHING队伍；Verifier仍ok=true。它只检查after至少一队及已知可打目标，不检查新派出的队伍、容量增量或花费。
- **影响**：失败/取消后回地图可能被记成新派兵成功。实际3次成功中的两次另有体力下降支持，**本轮没有将它们改判为失败**。
- **最小修复**：把新派兵归因到本次目标/队伍，用可靠前后计数、同目标队伍标识和体力差分组合证明；识别不到则明确未证实，不能只看“MAP上有任意军队”。
- **验收**：旧行军+无新花费/新队伍负控必须FAIL；真实新派兵PASS；多队异步归来不能依赖单一计数差而误判。

### V2-A08 — P1 / 确认接线缺失：已注册VERIFY_GATHERING仍不能从真实loop执行

- **位置**：skills.py:194注册VERIFIED；brain.py:1027产生Decision；runtime.py::VERIFIED_ATOMIC及1440前后门禁。
- **触发**：RESOURCE_DETAIL、资源不可用/未明确、已观测GATHERING，Brain要求VERIFY_GATHERING。
- **证据**：custom_probes2.json列出16个registered_not_live_enabled，其中VERIFY_GATHERING是现有Brain可直接产生的技能，不只是未来占位符。
- **后果**：该分支让位或SKILL_NOT_ENABLED_FOR_LIVE_LOOP；采集闭环不能以此技能完成。其他15项包括Rally和占位技能，不能一律开放。
- **最小修复**：定义有因果、同角色同队伍的采集验证，或把它并入已验证的派兵后续观测；先有Verifier再接允许表。
- **验收**：派出对应资源队伍→真正采集中→召回→返程→空闲，各阶段证据独立；禁止把OBSERVE执行成功作为采集成功。

### V2-A09 — P2 / 确认测试隔离问题：FakeDevice不阻止Runtime写真实默认状态

- **位置**：runtime.py::_record_goals 688→_record_observations 655；observation_store.py::STATE_PATH 36、record 167；多项test_live_runtime/test_capability_gate/test_march_formation_attribution。
- **触发**：测试在正式仓库运行，用临时EpisodeStore/FakeDevice，却没有替换全局observation store。
- **证据**：默认record不检查production mode或注入root，必写模块ROOT/learning/observation_state.json；两轮19项测试仅隔离store初始值不同，失败形态就变化（归属断言、重复BACK与StopIteration）。本轮这些写入只发生在临时副本。
- **影响**：模拟体力/任务完成状态可能改变下一次AUTO发现；测试之间顺序依赖。没有证据证明本轮测试连接真机，不能从这个问题推导“所有测试都危险”。
- **最小修复**：把观察存储/状态root依赖显式注入；测试默认临时目录，并加禁止生产路径写入/设备连接的全局防线。独立测试数据补足新的有界重观察契约。
- **验收**：单测、随机顺序和合并执行结果一致；生产knowledge/learning逐文件hash不变；模拟状态绝不进入AUTO读数。

### V2-A10 — P2 / 确认接口错用：跨轮体力防掉位读不到上一条已保存体力

- **位置**：runtime.py::_stored_stamina_value 607–617；observation_store.py::load 87–115。
- **触发**：新worker初始化_last_stamina_read。
- **原因**：load返回domain→Observation，调用者却继续取.get("domains")和.get("reading")，始终得到None。
- **证据**：custom_probes.json实际存175，runtime_result=null。常规Goal发现走as_observation_input仍能读缓存，故不是“所有体力缓存失效”。
- **修复/验收**：读取Observation.reading并同时检查角色和TTL；跨run的527→52掉位保护生效；真实数值下降不能被无条件覆盖。

### B2. 有条件风险与已修历史问题

1. **DISCOVERED竞争**：当前SWEEP_NEVER_VALUE=180，未读巡检压过READY采集70，甚至空闲兵营90；best没有状态分层，同分按插入次序。custom_probes确认初始必选训练巡检。这个策略本身旨在巡检轮换，不应简单改成READY永远优先。问题是读数/身份不收口、SAFE_STOP无Episode且_yielded_goals每worker清空时，巡检可不断重新获得180。现有no-progress按run统计与TTL重探机制确实存在；不能仅凭排序声称已证明无限饥饿。修A01/A02后再以跨周期预算和进展验收公平性。
2. **未映射Goal**：discover可产生KEEP_BUILDING_PRODUCTIVE、PARTICIPATE_BEAR、动态CLAIM_FREE_*，route_for返回None。BUILDING页可能靠Brain通用分支正常升级，所以“无route=所有页面都失败”不成立；HOME发现却不能导航、活动skill未启用是可达缺口。当前样本不证明Bear实际可用，不应贸然开放Rally。补生产可发现Goal的路由/可执行能力矩阵。
3. **OCR回归**：19项中的两项camp stamina失败已用真实归档图复现：primary/hybrid均EXPLORATION，cost=10；HUD ROI tokens=[]，current/source缺失。颜色仍读cost_affordable=false。这是当前OCR读数不足，不是那个分支根本没执行；底层空tokens原因（裁剪、模型或fixture差异）尚未完全定位。未知时保留安全拒绝，不能强填9。
4. **GUI阻塞与重启**：communicate在后台worker线程中且有timeout，已不是无限communicate卡Tk的旧问题；相关测试通过。_start_control_plane_reload现在只提示手动重启，没有执行旧taskkill自杀流程。这消除了该自动关闭路径，同时意味着控制面更新仍未实现无人值守热接续。未实际启动计划任务验证宿主回收，不能宣称桌面启动已通过72h。
5. **租约永久残留**：holder对released/expired返回None，有TTL；不能说会永久锁死。进程所有者与原子交接不足仍见A05。
6. **日志/内存**：retention保护生产Episode引用图片，JSON/JSONL不裁剪；Episode约11MB、MAA日志约8.8MB（采样时）。长期数据量会增长，部分消费者整文件读取；GUI完成回调同步_enforce_retention可能随量增长变慢。未测得内存泄漏或磁盘耗尽，列P2容量风险，先做保留/归档预算，禁止删已验证证据。
7. **成功写入顺序**：runtime在Verifier前记录真实after观察和Goal board，这是“观察到状态”，不等于宣称动作成功。实际Episode的成功通常在Verifier后写入；_record_episode函数本身允许verification=None时SUCCESS，但本轮未找到生产成功路径绕过VERIFIED_ATOMIC的证据。不能凭这个函数签名断言当前所有成功都无验证。

## C. 调度行为复现

下表“通过”只指列出的离线条件；不代表真机长期验收。复现脚本、JUnit和生产摘录均在证据目录。场景2/8的跨角色端到端链不存在，明确记录为“不支持”，不伪造角色切换测试。

| 场景 | 实际调用路径与输入 | 实际结果 / 证据 |
|---|---|---|
| 1 单Goal SAFE_STOP，另有工作 | test_refusal_yields_the_cycle、test_march_reservation_handover → LiveRuntime.run→_yield_to_next_goal→重选 | 相关隔离测试通过，单Goal拒绝可让位；A01说明归属错配仍会让错Goal让位。另行模拟Verifier失败则1步结束，见custom_probes2 |
| 2 A角色无工作，B有工作 | 生产只向GoalLibrary传单个WorldState；run_live固定一份持久role_id；无ROLE_SWITCH skill，select_next无调用 | **不支持**。静态生产链与role_switch_skills=[]一致；没有可调用的生产轮询去访问B。共享store的175读数可被下一角色消费者读到 |
| 3 READY与DISCOVERED竞争 | 空MAP，0/3队，discover→best | 7个未读巡检各180压过READY采集70，首先选KEEP_TRAINING_PRODUCTIVE。custom_probes.json；sweep相关测试通过，说明这是当前真实策略，不是注释猜测 |
| 4 体力30且只剩预留队列 | MAP 2/3、stamina30、reserve2→RuleBrain | GATHER_RESOURCE→SAFE_STOP reserved_march_for_stamina；BEAST_HUNT→SEARCH_RESOURCE。预留不会禁止体力路线，历史对应失败项现在PASS |
| 5 盾营忙，矛闲/射手未知 | 规范CampReading→discover→目标TRAIN Brain；另用quick_panel原始字段复现 | 正规读数层能区分三营，相关测试通过；但三个goal_id都给出BACK，不能切目标营。quick_panel则三营全DISCOVERED。A02 |
| 6 搜索卡只有集结 | BEAST attack_card=true、solo_attack=false、has_rally=true→Brain | BACK beast_card_is_a_rally_not_a_solo_attack，拒绝普通攻击；custom_probes。当前修复KEEP；未知card不能自动当已读可攻击 |
| 7 页面返回失败、仍有任务 | 既有foreign-layer/让位测试；OPEN_MAIL输入发出但仍HOME，另有READY盾营 | 有序BACK→LEAVE_FOREIGN_LAYER有界尝试真实存在；普通Verifier失败仍在max_actions6中1步返回OPEN_MAIL_NOT_PROVEN。不能保证在阻塞弹层上执行其他Goal |
| 8 全角色无工作，条件恢复 | 同角色mail observation=CLAIMED，当前fresh与2小时后过期→discover | COMPLETE→DISCOVERED，TTL重新发现通过（ttl_probe.json）；CapabilityGate也有probe_lapsed。跨角色“全都无工作”判据未实现，不能端到端通过 |
| 9 worker中途断连后恢复 | test_device_loss_is_not_a_goal_refusal→_device_lost；GUI _ensure_device在下一worker前重连 | 模拟断连被标RECOVERING并终止本run，普通异常继续抛出；设备相关隔离测试通过。真实断开/恢复按本次只读边界未执行；GUI下一轮重连属于已接线、未本轮真机验收 |
| 10 GUI/校准和AUTO争设备 | 既有lease不同owner拒绝测试＋自定义同job validation run＋同owner不同job acquire | 基础租约测试通过；自己的合法validation仍steps0自拒绝；不同job用同owner字符串被接受。start缺validating守卫属于并发风险，未启动双进程制造争抢 |

## D. 最小修复清单（交给WorkBuddy的审计建议）

不要求重新研究全项目。每项先读取本报告对应复现；15分钟定位无进展做TOOL CHECK；普通30–60分钟、复杂90分钟。时间盒到期应写具体blocker。以下是有依赖顺序的建议，**本轮未替换机器执行队列，也未启动开发**。

| 顺序 / ID | 文件与修复原因 | 最小验收 | 依赖 / 时间盒 |
|---|---|---|---|
| 1 AUDIT-F01 | runtime.run/_step_goal/_yield_to_next_goal：统一实际Goal承诺（A01） | 跨页归属不漂移；失败只defer实际owner；生产两Goal各一条一致链 | 无 / 90m |
| 2 AUDIT-F02 | ocr.read_quick_panel、camp_training、goal_library：字段归一化与同角色三营读数保持（A02） | 一忙一闲一未知→COMPLETE/READY/DISCOVERED；缺失不覆盖可信读数；新鲜度生效 | F01 / 60m |
| 3 AUDIT-F03 | brain TRAIN分支、skills、语义导航、verifier：目标camp贯穿，复用已验证入口，补最小切营 | 盾忙仍能进入矛/射手；各一条idle→IN_PROGRESS计时证据；不再点金环空等 | F02 / 90m |
| 4 AUDIT-F04 | run_live、device_lease、GUI validation生命周期：版本尝试身份与独占设备统一（A05） | 合法验证至少1步；其他进程不能争用；验证结算成功或诚实失败后归还AUTO；不能靠祖先关系强行记功 | 无；先与在途job交接 / 90m |
| 5 AUDIT-F05 | runtime通用Verifier失败出口＋跨worker重试预算（A04） | 失败A安全恢复后执行B；不可恢复页面与设备故障独立分类；不反复重开同一预算 | F01 / 60m |
| 6 AUDIT-F06 | brain打野attempt生命周期、verify_beast_dispatch（A06/A07） | 同周期两次出征；无新队伍旧行军负控FAIL；实际体力/队伍更新；rally拒绝KEEP | F01 / 90m |
| 7 AUDIT-F07 | VERIFY_GATHERING接线与已有召回Verifier（A08） | 同role同队伍Gather→GATHERING→RECALL→RETURNING→IDLE；不等自然采集数小时 | F01/F04 / 90m |
| 8 AUDIT-F08 | observation_store/Runtime/CapabilityGate按role隔离，随后现有主循环角色轮询（A03） | A无工作继续B；角色切换刷新HUD；无跨角色冷却/体力/容量继承。切换能力未验证则明确BLOCKED | 先隔离60m；轮询另90m，禁止一单大重构 |
| 9 AUDIT-F09 | 19项失败分组修复：store注入、旧搜索/恢复断言、真实OCR空tokens、fixture分析、开发脚本隐藏进程 | 定向测试+随机顺序通过；真实状态hash不变；不能把正确旧负控直接删掉 | 无；可在被阻塞时做 / 60m |
| 10 AUDIT-F10 | 完成前项后用现有AUTO进行有界验收，最终再安排72h | ≥2小时，三营、至少两次普通打野、采集回收、跨Goal恢复、角色轮询各有可归因证据；真实新增退出0；后台活着/WAIT不算进展 | 先60–90m阶段验收；长跑单独预算 |

优先级理由：先修“执行的是谁、失败的是谁”，否则后续任何成功率、自动升级任务与公平性数据都不可信；随后补三营真实操作。F04是自动开发/验证闭环的独立阻塞，可与无设备离线修复错开执行。不建议另造Scheduler、Registry、WorldState或Manager。

## E. 最终结论

1. **主链是否重复调度、无人认领或状态冲突？** 没有发现正式AUTO同时调用两套Scheduler执行同一步；但Goal选择在Runtime，动作路线留在Brain，两份状态已经真实错配。部分discoverable Goal缺route，部分注册技能被live表拒绝；应按可到达条件处理，不能全量开放占位技能。
2. **能否持续做完所有可执行任务？** 不能验收。巡检优先级180可以压过真实空闲任务，三营读数与动作接线不完整，且路由错配污染no-progress判断。已有TTL/让位机制不是缺失，但不足以保证公平、持续产出。
3. **单Goal受阻会否结束AUTO？** SAFE_STOP多数已有让位；普通Verifier失败仍结束当前worker。GUI往往重启下一轮，所以不是必然永久停机；重复选择与等待仍会显著阻塞当前可做任务。
4. **多角色是否完整？** 不完整。只有持久身份与Episode标签，未接生产轮询，多个业务状态未role-scoped。不能声称已经实现“全部角色无工作才等待”。
5. **普通打野和三营缺什么？** 打野缺成功后重新寻敌的有界生命周期及严格新派兵证明；三营缺统一状态契约、按目标营导航/切页签、每营真实启动训练与Verifier闭环。
6. **GUI/worker/MAA能否长期无人值守？** 已有正确解释器、MAA取帧、后台worker有界等待、环境错误分类和基本租约，均应复用。仍有校准版本/租约自拒绝、并发所有权风险、控制面更新需人工重启；当前无72h生产证据。不能把历史15退出直接算成本轮新增，也不能把它清零宣称通过。
7. **最少修哪些才能验收一键AUTO？** 先F01–F07形成可信单角色核心闭环；用户要求多角色时F08也是验收前置，不能留作“以后优化”；F09确保回归不污染生产，随后F10以真实产出验收。无需整体重构。

本报告没有承诺这些修复完成后的成功率；完成标准是指定状态转移、生产可追溯证据和有界恢复，而不是模块数量、注册数或pytest数量。

## 附录：19个历史失败节点逐项复核

以下表格由保存的JUnit节点生成，名称与输出逐项对应。所有项目均非本次审计引入：本次没有修改生产代码或原测试。由于历史.full_raw.txt没有版本指纹，除可由明确提交定位的变更外，不能准确宣称是哪一历史轮次引入；“历史也失败”不构成忽略理由。

| 序号 / 完整节点 | 09-21隔离 | 09-22最新 | 归因、生产影响及修复要求 |
|---|---|---|---|
| 1. `tests/test_beast_card_runtime_recovery.py::TheLoopItselfRecoversTests::test_a_back_that_changed_nothing_is_not_repeated` | FAIL | FAIL | 旧断言要求一次BACK后立刻结束；当前有二阶段离层和Goal让位，初始状态又改变归属。应验有界恢复与无误点，不恢复旧全局停止。 |
| 2. `tests/test_camp_panel_stamina.py::CampPanelStaminaIsReadTests::test_the_camp_panel_reads_the_same_number_as_the_map` | FAIL | FAIL | 真实归档图的HUD ROI OCR tokens为空；current缺失。颜色仍判断不可支付。当前识别缺口；需修ROI/模型证据，不填常量。 |
| 3. `tests/test_camp_panel_stamina.py::CampPanelStaminaIsReadTests::test_the_read_names_the_page_it_came_from` | FAIL | FAIL | 同上一项：没有数值就没有CAMP_PANEL_HUD来源；同一根因，不另算一个生产缺陷。 |
| 4. `tests/test_capability_gate.py::DeferredGoalSchedulingTests::test_a_deferred_goal_does_not_displace_work_that_is_still_selectable` | FAIL | PASS | 旧快照FakeVision在重观察耗尽；最新有界让位改动后通过。保留这个有效负控。 |
| 5. `tests/test_capability_gate.py::DeferredGoalSchedulingTests::test_an_allowed_goal_is_untouched_by_the_gate` | FAIL | FAIL | 测试硬断言旧SCAN_MAP_FOR_BEAST；当前先SEARCH_RESOURCE是已验证新路线。改验同Goal、合法搜索与结果，不能回退搜索。 |
| 6. `tests/test_capability_gate.py::DeferredGoalSchedulingTests::test_the_run_still_plays_when_the_blocked_goal_is_all_there_is` | FAIL | FAIL | 有限FakeVision脚本没覆盖实际导航/Verifier重观察，StopIteration；补完整状态序列及预算。不能直接增加任意重复帧掩盖停滞。 |
| 7. `tests/test_capability_gate.py::EpisodeMeasurementTests::test_a_goal_that_moved_is_recorded_as_progress` | FAIL | FAIL | 只允许SCAN_MAP_FOR_BEAST，当前搜索Decision被allowlist拒绝，未产生Episode文件；测试入口契约过时，进展度量仍须验证。 |
| 8. `tests/test_capability_gate.py::EpisodeMeasurementTests::test_a_verifier_pass_without_goal_progress_is_recorded_as_such` | FAIL | FAIL | 同上；应选实际可执行动作并验证Verifier PASS但Goal未进展这一负控。 |
| 9. `tests/test_control_panel.py::ControlPanelTests::test_intel_goal_never_inherits_gather_actions` | FAIL | FAIL | 断言离开异页一次后SAFE_STOP；当前第二步LEAVE_FOREIGN_LAYER。保持不得执行采集的负控，允许有界导航。 |
| 10. `tests/test_control_panel.py::ControlPanelTests::test_mail_goal_never_inherits_gather_actions` | FAIL | FAIL | 同上，MAIL路线不应继承采集，但可执行第二阶段离层。 |
| 11. `tests/test_evidence_integrity.py::test_every_image_literal_in_the_suite_resolves_to_a_file` | FAIL | FAIL | AST图片字面量分析混合真实归档、子目录拼接片段及临时a/b/shot/x/y图片；逐个解析表达式与fixture来源。不能直接全跳过路径检查。 |
| 12. `tests/test_live_runtime.py::LiveRuntimeTests::test_verified_action_repeats_then_safe_stops` | FAIL | FAIL | 旧FakeVision序列耗尽；新版让位/发现更多Goal改变调用次数。另有全局observation状态串扰；须注入store和显式脚本。 |
| 13. `tests/test_march_formation_attribution.py::MarchFormationAttributionTests::test_a_run_that_never_selected_a_goal_keeps_the_placeholder` | FAIL | FAIL | 测试假设没有Goal，但新巡检会发现Goal；状态不同可表现归属错误或无Episode。不能仅把期望改为任意Goal，A01仍为真实缺陷。 |
| 14. `tests/test_march_formation_attribution.py::MarchFormationAttributionTests::test_the_step_that_opens_the_formation_page_carries_the_goal_that_owns_it` | FAIL | FAIL | 旧allowlist/输入状态使新发现路线未执行目标动作，Episode文件不存在；同时A01的跨页归属需专门固定负控。 |
| 15. `tests/test_march_reservation_handover.py::TheReservationRefusesTheSlotTests::test_the_stamina_goal_could_have_used_that_very_slot` | PASS | PASS | 最新返回SEARCH_RESOURCE而非旧扫描，预留并未挡体力；现通过，KEEP。 |
| 16. `tests/test_panel_routine_discovery.py::ConsecutiveSweepsMustHopBetweenPanels::test_the_hop_happens_once_so_a_back_that_did_not_move_cannot_loop` | FAIL | FAIL | 旧一步离层断言与当前BACK→LEAVE_FOREIGN_LAYER两阶段不符；更新成有界且不重点击失败控件。 |
| 17. `tests/test_route_goal_requires_home.py::UnrelatedPageStillStopsTest::test_research_on_an_unrelated_page_leaves_it_once_then_stops_named` | FAIL | FAIL | RESEARCH同上；须证明异页恢复后不会误执行别的业务。 |
| 18. `tests/test_route_goal_requires_home.py::UnrelatedPageStillStopsTest::test_train_on_an_unrelated_page_leaves_it_once_then_stops_named` | FAIL | FAIL | TRAIN同上；不能以此掩盖三营目标未路由。 |
| 19. `tests/test_winproc.py::TheGuardKeepsItFixed::test_the_tree_has_no_unhidden_background_process` | FAIL | FAIL | 两个开发工具存在未隐藏subprocess：tools/_launch_panel_detached.py:42、tools/_trace_panel_startup.py:42。当前桌面主入口不调用它们，P2维护性；用既有winproc。 |

**引入版本判定：** 本轮审计零生产/原测试改动，故上述失败都不是本次审计引入。历史全量报告未保存版本指纹，不能给19项编造首次引入commit。测试断言与当前代码演进不兼容、真实OCR缺口、状态串扰、开发脚本规范问题分别处理；不能用“旧失败”统一豁免。

## 最新增量问题（2026-09-22）

### V2-A11 — P1：历史控件坐标缺少当前弹窗身份校验

- **位置与调用链：** `winter_agent_v2/runtime.py::_resolve_semantic_target`（1310–1323）→ 模板未命中 → `_remembered_control_center`（1325–1383）→ `control_experience` 中 Page+semantic 历史记录。
- **触发条件：** 当前页面同为 POPUP、语义同为 BTN_CLOSE，历史位置曾成功且被标为 LOW risk，但当前弹窗种类或布局已经变化。
- **证据：** `evidence/20260922/popup_reuse_probe.py` 和对应 JSON。隔离完整解析器探针向历史库提供成功点 `(0.7, 0.62)`；GENERIC_REWARD 与 EXIT_CONFIRM 都返回同一点，当前模板未命中。没有调用设备点击。这证明解析器缺少上下文门禁，**不证明生产已发生误点击**。
- **影响：** 语义动作低风险不能保证旧坐标在另一弹窗上仍指向低风险按钮。当前 key 没有弹窗身份、布局或当前锚点；`has_measured_frame` 排除 Temp 来源也不能证明坐标仍适用于当前画面。
- **最小修复：** 保留历史经验作为候选搜索区域，要求当前弹窗身份及布局/锚点匹配后再产生动作坐标；敏感或身份不明弹窗拒绝直接回放。复用现有 resolver 与风险门禁，不增加第二套执行器。
- **WorkBuddy 验收：** 不同弹窗不能直接复用同一点；同弹窗布局平移须重新定位；同布局有效经验仍可在当前证据支持下复用；保留风险门禁负例。无需为修复而真实点击退出确认。

### V2-A12 — P0：打野出征准入与事后验证的目标身份契约不一致

- **位置与调用链：** `winter_agent_v2/brain.py`（1620–1645）以 victory_assured + WILDERNESS 允许 DISPATCH_BEAST → 实际出征 → `winter_agent_v2/verifier.py::verify_beast_dispatch`（906–925）额外要求目标名称可被 `lookup_by_name` 识别且不是拒绝目标。
- **触发条件：** 编队页仍满足可胜和野外目标，但 OCR 名称失真、未保留此前已识别的普通野兽身份；动作前允许执行，动作后必然无法满足该身份条件。
- **生产证据：** 最终固定窗口769条新增 Episode 中，9次 DISPATCH_BEAST 全部为 `BEAST_DISPATCH_NOT_PROVEN`。before 名称“巨膜”4次、“泰”5次，均 lookup 失败；完整样本及各自 repo_revision、before/after、截图路径保存在 `evidence/20260922/beast_dispatch_failures.json`。不是把跨版本窗口全部归给最终 HEAD。
- **实际后果：** 部分 after 已回 MAP 且出现 MARCHING，因此不能把验证失败解释为游戏从未出征。系统可能已占队列/消耗体力，却把流程记录为失败，难以连续可靠执行；部分又因 A01 归到 CLAIM_EXPLORATION_IDLE 等 Goal，污染后续调度。
- **最小修复：** 从已验证的普通目标卡保留目标身份进入编队上下文，统一出征前准入与事后验证的身份条件。未知身份应在消耗前处理；事后结合可信目标、新增行军与成本变化证明结果。不要将两个错误 OCR 名称加入白名单，也不要把所有未知目标转 Intel 来绕过验证。
- **WorkBuddy 验收：** 重放9例，逐例定位身份在哪一层丢失；保留集结拒绝；A07“已有旧行军且无新变化”负例必须失败。随后独占设备验证连续2次普通打野，每次目标身份、所属 Goal、新行军和成本证据一致。只有点击或回到地图不算成功。

## 最终裁决（2026-09-22交付版）

1. **生产主链没有发现两个独立执行调度器同时调度。存在已证实的 Goal 所有权冲突。** Runtime 选中的新 Goal、Brain 正在执行的旧路线和 Episode 记录可以分裂（A01）。首要修复是统一执行承诺及归属，不是增设 Scheduler。
2. **尚不能证明持续完成所有可执行任务。** 新 utility 排序已经接入，旧的单纯 priority 饥饿推论不再适用；但三营目标不能正确落到对应兵营、打野后不能稳定重新搜索，以及错误 Goal 被记失败仍可阻塞实际工作。
3. **单次普通 Verifier 失败直接结束 run 的旧分支已经修复。** 当前有界重试和让位离线通过；仍需正确的 Goal 归属，否则可能让位错误对象。run 的有界退出不等于整个 AUTO 永久停机，两者不能混写。
4. **多角色生产轮询与状态隔离不完整。** 当前 role 标签不能替代按角色的观察、能力和任务状态；“所有角色无工作后重新唤醒”尚无完整生产证据。
5. **普通打野缺目标身份贯穿、出征因果验证和成功后重新搜索；三营缺观察字段契约与按目标营执行。** A12 是最新9次生产失败的直接契约缺口，A06/A07也要一并用正负例验收。
6. **长期无人值守尚不可验收。** 自有验证租约和 superseded 请求已修，不能重复派单；同 owner 不同 job 的租约隔离、GUI/验证并发控制仍不足。历史 worker 退出累计数不是最新根因证据，未在本次只读审计中触发断连、抢占或重启来“验证”。
7. **最小修复顺序：** A01 → A02观察与动作两段 → A12+A07+A06打野闭环 → A11历史坐标上下文 → A05剩余所有权问题 → A08采集验证/回收 → A03角色隔离与轮询；测试状态隔离和失败清单同步处理。复用正文D的文件/函数/验收清单，F05仅保留回归验收，不再重复开发已修分支。

**交付边界：** 当前19个历史失败节点复核为17失败、2通过；新增相关测试113通过，未重跑当前全量测试。10个场景分别记录了离线结果、历史证据及无法验证的边界，不以静态缺口冒充多角色/断连/并发真机实验。此次只写审计报告与独立证据，没有修改生产代码、Commander接口或生产状态，也没有启动、重启、操作或抢占真实设备。后台进程仍可能继续推进，后续修复以本报告固定版本和时间窗为基线做增量复核。
