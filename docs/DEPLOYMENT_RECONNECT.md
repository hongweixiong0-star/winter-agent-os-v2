# 实机部署修复记录

2026-09-07：在线设备已从配置中的 `127.0.0.1:16384` 变为 `emulator-5554`，控制台因此等待连接超时。

已部署：保留已配置且在线的设备；配置设备离线时只接受唯一在线设备；多设备拒绝猜测。控制台把选定设备显式传给各个任务子进程。游戏已经在前台时跳过重复启动。

设备实测：`emulator-5554`，720×1280，前台 `com.gof.china`。控制台重新启动后恢复主城截图与识别。

当前主城邮件入口与旧模板不匹配，已增加来自当前客户端的局部候选模板（总数 317）。真实主城→邮件操作执行成功，`verify_open_mail` PASS；截图位于 `dataset/raw/live_deployment_reconnect_mail/`，Episode 自动保存于 `learning/episodes.jsonl`。

专项测试：设备与控制台 27 项通过。此结果不代表所有游戏任务可无人值守。普通野怪主动搜索、长期耐久运行仍需完成；只检查页面不能计作消耗体力成功。

追加：实机报告通知执行“一键已读并领取”后红点 1→0，没有奖励弹窗。保留严格领奖验证器，另加读通知/领奖分流验证，读通知明确记录 `reward_verified=false`。29 项设备、控制台、邮件通知测试通过；实机再次读取邮件得到 `mail_all_clear`，零点击结束。证据在 `dataset/raw/live_deployment_mail_claim/` 与 `dataset/raw/live_deployment_mail_clear/`。已从控制台重新启动自动任务链。

追加（2026-09-07 探险收益）：当前客户端真实流程为 `EXPLORATION/CLAIMABLE → EXPLORATION_IDLE_DIALOG → EXPLORATION_REWARD → EXPLORATION/CLAIMED`。绿色领取按钮已在实机领取后变为灰色；证据位于 `dataset/raw/live_deploy_exploration_claim_v3/`、`v4/`、`v5/`。控制台已接入“探险”，任务链调整为邮件 → 探险 → Intel，并完成探险 → 主城 → 世界地图 → Intel 的实机交接验证（`dataset/raw/live_deploy_exploration_panel_entry_v2/`、`live_deploy_exploration_to_intel_v3/`）。完整测试 174/174 通过。该能力保持 `VERIFIED`，下一次自然累计收益需由单次不中断运行完整通过后才可晋升 `STABLE`。

追加（2026-09-08 奖励闭环）：识别并领取“欢迎回来”离线收益，修复其导致整夜 `UNKNOWN` 停止的问题。每日任务入口已接入控制台，实机一键领取 3 项任务奖励并领取 40 活跃度宝箱，活动度 0→70；控制台只领取已完成奖励，不自动执行尚未单独验证的“前往”任务。邮件 66 个红点按报告、联盟、系统分类清理至 0。奖励页改用严格的通用“获得奖励”标题，再结合当前 Goal 归属；阈值以正样本 ≤10、联盟负样本 ≥24 校准为 16。探险动画按钮采用“探险页 + 绿色状态”双重验证后的归一化目标，实机完成领取并回到灰色已领取状态。模板总数 338；证据位于 `dataset/raw/live_20260908_*`、`live_deploy_mail_generic_reward_v2/`、`v3/`、`live_deploy_exploration_dynamic_target_v1/`、`v2/`。

追加（2026-09-08 联盟赠礼）：从当前联盟首页识别赠礼入口与 `99+` 红点，进入盟友赠礼页后连续执行 3 次领取。每次均由赠礼进度增长以及可领取按钮减少/已领取条目增加共同验证：`137372→137402`、`137402→137432`、`137432→137513`，最终可领取数 `3→0`，全部 Verifier PASS。购买生成赠礼的“前往”入口未触碰。控制台现已正式接入“联盟赠礼”，串联顺序为邮件 → 日常 → 联盟赠礼 → 探险 → Intel → 野怪 → 采集；无赠礼时以 `alliance_action_not_needed` 正常结束并继续后续任务。当前模板总数 340，实机证据位于 `dataset/raw/live_20260908_alliance_current.png`、`live_20260908_alliance_gifts_current.png` 与 `live_deploy_alliance_gifts_v2/`。这只证明联盟赠礼闭环，联盟帮助和联盟科技尚未作为同一控制台任务自动执行。

追加（2026-09-08 下一批）：修复当前邮件活动标签无法识别导致的清扫中断；联盟邮件 24 个红点清零，随后新到的联盟/系统/战争邮件按分类处理，最终战争邮件 `3→0`，Verifier 以红点总数下降确认通知处理，同时明确 `reward_verified=false`，没有把普通已读冒充成奖励。新增当前客户端“邮件已清空”模板，操作前红点页负样本不匹配，模板总数 342。研究所经“战力→实力详情→科技提升”定位，实机识别研究队列 `IN_PROGRESS` 并以 `research_queue_busy` 安全跳过，未点击加速。盾兵营经部队提升入口定位为空闲，真实启动 806 名王牌盾兵训练，状态 `AVAILABLE→IN_PROGRESS`、计时器 `10:03:10`，`verify_training_started` PASS；未使用钻石或加速。证据位于 `dataset/raw/live_20260908_next_batch_*`、`live_20260908_mail_*`、`live_20260908_research_*` 与 `live_20260908_training_start_current/`。训练原子动作已经接入 LiveRuntime，但主城到兵营的三段导航尚未固化，因此控制台入口仍保持待接入，避免伪自动化。

追加（2026-09-09 训练控制台接入）：将当前客户端“战力总览→实力详情→部队提升→盾兵营菜单→训练页”固化为单一 Brain 下的五步导航链，每步均有独立 Verifier。实机完整不中断运行 `live_20260909_training_navigation_full_v2/` 依次通过 `OPEN_POWER_OVERVIEW`、`OPEN_POWER_DETAILS`、`NAVIGATE_INFANTRY_CAMP`、`OPEN_INFANTRY_TRAINING`，最终识别盾兵训练队列 `IN_PROGRESS`、剩余 `03:26:11` 并以 `training_queue_busy` 安全结束，没有重复训练或点击加速。为动态战力数值、昼夜图标和手势动画使用局部阈值，并以普通主城负样本校准；模板总数 352。训练现已正式接入 AI 指挥中心，默认启用，位于联盟赠礼之后、探险之前。
