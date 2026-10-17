# UNKNOWN 全量排查报告（2026-09-24）

## 范围与核验口径

- 审计基线 HEAD：`e3d00ad51849bc3521f5539d5daa1a8485e870e8`；工作树存在大量既有 dirty/untracked 内容，本轮没有批量暂存或提交，也没有覆盖 `vision.py`、`runtime.py`、`brain.py` 的既有修改。
- 20 个 `knowledge/perception/pages/unknown*/` 候选目录去重为 **15 个独立页面簇**。8 个 `learning/unknown_requests/*.json` 请求均能关联到这些页面簇，不重复计为新根因。另有 1 条当前 Goal UNKNOWN 与 1 条角色身份 STALE，单列统计；因此独立未知/过期状态合计 **17 项**（15 页面簇 + 2 当前状态）。
- UNKNOWN dispatcher：**8 条请求、1 条已有答案、7 条无答案、0 个在途作业**。未答请求是留存记录，不占运行调度槽，也未开启 WorkBuddy 自动调用。
- 当前视觉运行时对两个历史请求帧（城市温度 HUD、欢迎回来离线收益弹窗）的离线语义重放仍返回 `UNKNOWN`。对其他页面不以旧报告或模板分支存在来推定已修复；只有有明确证据才标记 RESOLVED。
- 本轮没有设备输入。游戏设备及面板进程仍在运行；曾出现磁盘版本与运行进程版本不一致，但面板随后在 18:04:38 自动进入新一轮，不需要人工重启。

## 统计

| 项目 | 数量 | 说明 |
|---|---:|---|
| 初始页面候选目录 | 20 | 原始候选全部保留 |
| 去重后页面 UNKNOWN | 15 | 5 组重复候选合并；每组仍关联全部来源目录 |
| 页面状态 RESOLVED | 0 | 没有页面分类问题获得足够真实验证 |
| 页面状态 AWAITING_LIVE | 10 | 缺少该页面再次出现时的实时验证 |
| 页面状态 NEEDS_EVIDENCE | 5 | 当前截图重放仍未知、原图缺失或根因不明 |
| 当前 Goal UNKNOWN / 角色 STALE | 2 | `CLAIM_EXPLORATION_IDLE` 无可用 Skill；角色身份自 9 月 16 日未刷新 |
| 页面状态 BLOCKED_ENVIRONMENT / DEFERRED | 0 | 设备当前可运行；没有人为推迟项目 |
| 单独恢复动作 RESOLVED | 1 | 燃霜矿区帧上的“奖励”普通控件：Episode 记录 verifier 通过且观测值变化；不等于页面识别修好 |
| 旧 UNKNOWN 请求 / 在途作业 | 8 / 0 | 7 条未答旧记录已终态，无作业需要等待结算 |

17 项独立未知/过期状态中，10 个 AWAITING_LIVE、7 个 NEEDS_EVIDENCE；关联的普通控件恢复子问题另计，1 个 RESOLVED。视觉页面 15 簇本身仍有 0 个 RESOLVED。完整的逐问题证据、任务/角色、首次/最近时间、来源 revision、影响、可复用 Skill 和下一项动作在 [UNKNOWN_TRIAGE_2026-09-24.json](../../docs/audits/UNKNOWN_TRIAGE_2026-09-24.json)。原始截图、请求、Episode 与 WorkBuddy 历史没有改写。

## 已处理与仍存在的问题

### 代码修复

退役 UNKNOWN 通道此前仍每 8 个 pump tick 创建 dispatcher、检查网关，并反复把 7 条历史问题报告成“等待”。`tools/control_panel.py` 现改为：`workbuddy_channel.enabled=false` 时仍允许结算已有作业；一旦确认没有在途作业，即停止后续轮询，并把未答请求显示为历史留档。没有删除请求、dispatch ledger、旧作业结算能力，也没有调用或启用 WorkBuddy。

**验证：** 两个新增的退役通道测试通过（空队列只结算一次；旧作业仍在途时持续结算到结束）；`tests/test_unknown_ai_channel.py` 42 项通过。`tests/test_control_panel.py` 总体为 47 passed、2 failed；失败项是既有 dirty `brain.py`/测试中的外来页面离开状态不一致（`LEAVE_FOREIGN_LAYER` 与测试预期 `SAFE_STOP`），不是本次 UNKNOWN 改动。该 dirty 内容未擅自更改。完整套件因此不能报告为全绿。

修复已由新控制面板进程实际运行：PID 4264 于 18:03:55 启动；18:11:15 的 pump 显示 `unknown_ticks=8`、`7 个历史 UNKNOWN 留档；0 个旧作业待结算`。轮询完成一次无在途作业结算后保持在 8 tick，没有继续每 8 tick 重查。自动通道仍关闭，提交数为 0。本轮没有手工重启持有设备的进程。

### 页面 UNKNOWN 的真实分类

- 8 个旧请求跨越城市 HUD、回城收益弹窗、过场、战斗层、实力详情、情报奖励、活动页面和故事对话等画面；同标题候选只有在截图/页面语义相同的情况下才合并。
- 旧生产 Episode 证明部分任务后来继续执行（例如欢迎回来弹窗之后邮件/日常/地图动作通过；Intel 战斗界面之后有战斗结算和返回地图；燃霜矿区 UNKNOWN 后地图、资源搜索和采集链继续成功）。这说明 AUTO 能从部分未知页恢复继续推进，但不能证明这些页面已被正确识别。
- “探照灯升级”奖励弹窗有一次关闭 Verifier 失败，也有不同后续回合的 Intel 奖励关闭成功；由于不是同一帧/同一来源，不能互相抵销。
- 原请求 `unknown_i__control__b860b24a` 的截图已丢失；另一个相似故事候选帧不能替代原图。保留 NEEDS_EVIDENCE。
- Skill Registry 核验到 114 项：47 VERIFIED、65 CANDIDATE、2 BLOCKED。`RESEARCH` 有 `verify_research_started` 运行时验证函数但 Skill 被标 BLOCKED 且缺少自描述 verifier/recovery contract；`ALLIANCE_HELP` 被 BLOCKED，现有 `verify_alliance_help_auto_active` 只证明自动帮助状态，不能证明逐项帮助动作。两项都没有在本轮解除，因为缺少完整可验证操作契约；它们是现有受控缺口，不是新底层执行原语。Qwen 规划与 MAA/现有 Skill 保持现有单链。

### AUTO 与执行稳定性

最新 `learning/runtime_snapshot.json`（10:11:13Z）：`runtime_thread_alive=true`、`scheduler_loop_alive=true`、`agent_state=GOAL_RUNNING`；当前在 MAP 页面执行 `AVOID_STAMINA_WASTE / SEARCH_RESOURCE`，Verifier PASS、最近成功时间 10:11:03Z、`stop_reason=null`。AUTO 正在推进。上一轮曾以 `every_page_this_run_was_fruitless` 安全结束，面板持续意图仍为 RUNNING，之后已开始新一轮。

累计 `unexpected_worker_exits=15`、`watchdog_restart_count=21`。保留的 8 份 crash JSON 都将退出归类为环境问题（MuMu 连接歧义/连接等待超时），时间为 2026-09-20 至 2026-09-21；所查近期 Episode 没有 crash/fatal 类型，最近 6 小时没有新增 worker crash 报告。计数是历史累计值，不能据此推断当前仍在崩溃，也不能重置来掩盖历史。是否达到 72 小时无人值守稳定标准仍需后续在线窗口证据。

## 仍未解决项的阻塞条件

- 10 个 AWAITING_LIVE 页面簇：相应活动、战斗、奖励、确认页当前不一定可见；待真实页面再次出现后按状态变化与 Verifier 验证。
- 5 个 NEEDS_EVIDENCE 页面簇：两张历史帧经当前语义重放仍为 UNKNOWN；一个过场帧需完整离线重放；一个原请求截图丢失；一个强度详情页的复验关联证据不足。无需猜测坐标或重复点击。
- 退役通道轮询修复：需观察活动面板加载新源码后的心跳，确认已停止反复报告 7 条历史 pending；本轮未重启活动设备所有者。
- Worker exit 稳定性：需要安全 reload 后的新鲜生产观察窗口；历史统计不可改写。

## AUTO 状态结论

**AUTO 当前正常进入新一轮运行，最新一次调度步骤通过 Verifier。** 15 个页面 UNKNOWN 尚无一个达到 RESOLVED；另有当前 Goal UNKNOWN 和角色身份 STALE。无新增 WorkBuddy 派发；本轮没有更改游戏状态。
