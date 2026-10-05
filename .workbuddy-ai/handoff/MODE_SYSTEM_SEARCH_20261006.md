# 搜索产物 — 双模式运行规范（Auto / Manual）落地

> §8 硬门要求：开发新功能，进入实现前必须先有搜索产物。本文件即该产物。
> 任务来源：操作者 2026-10-06 给出的《Winter Agent OS V2 — 双模式运行规范》§14 落地步骤 3–7。

```
=== 搜索产物 ===
任务/问题：把一个"机器归属"双模式（Auto=系统跑 / Manual=WorkBuddy 开发）做成
        持久化、可原子切换、崩溃可恢复的机制，并保证不会出现"半 Auto 半 Manual"。

搜索关键词：
  - single-writer exclusive lock durable state machine atomic mode switch crash recovery pattern
  - game automation bot human takeover pause resume exclusive device ownership ADB single input owner

搜索结果：
  1. 【首选模式】"优先用原子状态写入，而不是另建锁服务"——
     positioniseverything.net/everything-i-know-about-distributed-locks：
     "The first case to avoid is when the operation can be expressed as an atomic write in the
      system that owns the data... Adding Redis, ZooKeeper, or etcd as a separate lock service can
      create a split-brain between 'who has the lock' and 'what the database accepted.'
      Prefer ownership over coordination... Start with atomic state changes, ownership boundaries,
      idempotent operations, and durable workflows; add a distributed lock only when those tools
      are not enough."
  2. 【要有所有权令牌，且释放必须是"条件释放"】同一来源：
     "A lock has a TTL... which means a holder can lose its lock mid-work by running past the TTL.
      If release were unconditional, that holder would then delete a lock someone else had already
      acquired, and two workers would run at once."
     lemmego.org/docs/cache/locks：On Redis the release is a single Lua compare-and-delete
     "for the same reason: reading the owner and then deleting are two operations, and the lock can
     change hands between them."；并给出 owner token / Extend()（续租）与
     "A false return means the lock is already gone, which tells the caller to stop rather than
     carry on believing it is protected."
  3. 【切换=原子状态转换，用 CAS】blog.csdn.net/wangonik_l/article/details/156949870：
     无锁状态机的 TryStart() 用 Interlocked.CompareExchange(ref _state, Running, Idle) ——
     "原子转换: Idle → Running（仅当状态为 Idle 时成功）"。
  4. 【用"记录+状态"而不是"临时锁"，因为前者有审计轨迹且抗崩溃】
     positioniseverything.net 同一篇：
     "'Only one deployment per environment' may fit better as a deployment record with states like
      pending, running, succeeded, and failed. These designs leave an audit trail and survive
      process crashes better than an ephemeral lock key."
  5. 【同领域（游戏挂机）已有 managed/manual 两模式，但语义不同】
     cbot.bot-cave.org/ready-to-go/managed-or-manual-mode：
     "Managed Mode: ... the bot will do EVERYTHING for you. However you can still pause/resume
      single instances or even all instances at once."
     "Manual Mode: If you press the Play button for any instance you will be in manual mode."
     —— 它的 manual 是"由用户手动挑实例启动"，**不是**"机器所有权交给开发方"。
     diepes/rust-android-adb-automation：ADB 自动化 GUI，"Pause/resume automation anytime"。
  6. 【单输入所有者是同类系统的共识约束】skillsmp.com device-takeover（52 stars）：
     同一台设备通过 ADB 收 tap/swipe；本仓库既有代码也写着
     "Single Device / Single UI Owner"（winter_agent_v2/device_lease.py）。

假设（基于搜索，我认为应该怎么做）：
  A. **模式状态做成一份"记录"，不做成第二个锁。** 落点 `learning/MODE_STATE.json`，字段含
     mode / owner / reason / started_at / expected_duration / completion_criteria / history。
     这正是搜索结论 1 与 4 的直接推论：有审计轨迹、抗崩溃、不产生第二套真值。
  B. **切换 = 对持久化状态做一次 CAS。** 读当前状态 → 校验期望的前置状态 → 用
     tmp 文件 + `os.replace` 一次落盘（同目录 rename 在 Windows 上原子）。
     崩溃只会看到旧状态或新状态，看不到中间态 —— 这就是 §7"不允许半 Auto 半 Manual"的机器保证。
  C. **在既有 device lease 之上分层，不另建所有权机制。** `device_lease.py` 已经提供
     "一个设备一个所有者 / 在安全点交出 / 带理由与 TTL"，模式层只负责
     "谁有权持有租约"（Auto→系统，Manual→WorkBuddy）。这是 ONE-* 不变量的要求。
  D. **释放/回切必须条件化并校验发起方**（搜索结论 2）：Manual→Auto 的收尾若由
     "已失去所有权"的进程执行，必须失败而不是把新所有者的状态删掉。
  E. **预计时长是决策点，不是回切点**：到点后必须二选一（暂停回切 / 申请延长），
     延长要写进历史。搜索里没有现成模板，这部分是自研设计（见下"不确定性"）。
  F. **控制台字段直接从这份记录派生**，不另存一份，避免第二个真值源。

不确定性（哪些还没搞清）：
  1. **没搜到任何先例实现"自主切换 + 预计时长决策点 + 强制收尾"这个组合。**
     CBot 的 managed/manual 没有自主切换，也没有决策点；分布式锁那些材料只解决
     "谁能写"，不解决"到点该不该继续"。所以 §4 触发 3 / §5 是**自研**，没有模板可抄，
     需要真机验证后才敢说它对。
  2. **"机时分配"（§6 机制 1 的 30 秒空闲让出、机制 2 的每小时 5 分钟窗口）目前无实现可依。**
     现有 AUTO 循环是连续的 tick，没有"空闲 30 秒"的现成判据。
     本轮**不实现 §6**，先做模式本身（§1–§5、§7、§9、§13），
     因为 §6 的三条机制在 Manual 模式下全部作废，且用户强制切 Manual 时也作废。
  3. **§13"Manual 超过预计时长 10 倍要高亮警告"没有可信的时长来源**——
     现有 `auto_uptime.jsonl` 记的是 AUTO 运行时长，不是 Manual 时长。
     本轮先由模式记录自己累计 `manual_seconds`。
  4. **§8 搜索的"硬门"如何自动化判据不明。** 本轮先把它写成文档 + 手工执行；
     要变成机器判据需要定义"什么算新功能"，这个我没搜到权威定义。
=== 结束 ===
```

## 本轮实现范围（明确的不做清单）

**做**：§1 模式与持久化、§4 三种触发（用户强制 ×2 + 自主）、§5 决策点、§7 原子性与收尾、
§9 控制台字段（数据层）、§13 异常恢复。落点 `winter_agent_v2/mode_state.py` + 测试。

**不做（并说明为什么）**：§6 机时分配（依赖一个不存在的"空闲判据"，且在 Manual 下整体作废）；
§8 硬门的机器化（缺"新功能"的可判定定义）；§9 的面板渲染（先出数据层，UI 另开一次）。
