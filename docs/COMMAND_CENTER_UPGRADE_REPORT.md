# AI 指挥中心升级报告

## 页面

一级页面已收敛为：总览、目标、策略、活动、能力、学习、系统。

- 总览：Runtime 状态、实时 Evidence、当前 Goal/Skill/原因/前置条件/Verifier/下一步/风险/置信度。
- 目标：读取 `learning/goal_state.json`，展示真实 GoalState；信息不足时明确显示“未知 / 待识别”。
- 策略：只配置 Goal Category、Reward Policy 与 Resource Policy。
- 活动：区分 `LIVE_CLIENT`、`HISTORY · 仅参考`、`PRIOR`。
- 能力：以 Universal Skill 为主视图，显示语义目标、参数、Verifier、Recovery、风险、延迟、生命周期、实机成功和稳健性警告。
- 学习：合并 Knowledge Quality 与按 Goal 影响排序的问题。
- 系统：Runtime Watchdog、日志、Vision Debug、Replay 与 Evidence 入口。

## Runtime 修复

`learning/runtime_snapshot.json` 是运行状态的唯一真相源。Runtime 原子写入，GUI 每 1.5 秒只读。

GUI 已停止在刷新动作中调用 OCR/Qwen，也不再选择固定 Goal、拼接邮件/训练/Intel 等任务链。控制台只启动现有 `run_live.py`，唯一 Scheduler 决定 Goal 与 Universal Skill。

普通 Goal/Skill 失败不会终止 AUTO。无空闲行军属于正常 `IDLE` 等待；启动校准属于 `RECOVERING`；只有硬 Fatal 进入 `FATAL_STOPPED`。

## 当前真实指标

- Skill Registry：75
- 有真实成功 Episode 的 Skill：45
- VERIFIED 生命周期：44
- STABLE：0（严格遵守 Semantic Robustness Gate，不因代码存在或单次成功晋升）
- P0/P1 Goal Coverage：0/6 完整 VERIFIED
- 全部 Goal Coverage：2/15 完整自动验证
- 历史 Production Episode：478；成功 409；失败 69
- 回归测试：本轮相关测试 60 项通过

## 30 分钟真机验收

证据文件：`evidence/runtime_soak_30m.json`。

结果：连续采样 30 分钟、180 个样本；运行态矛盾 0、意外 worker 退出 0、watchdog 重启 0。该结果证明 Runtime 状态一致性，不冒充任务 Skill 成功率。

## 真机故障闭环

真机发现世界地图的资源搜索层上方出现“进攻方胜利”结果浮层。旧 Vision 把底层 MAP 当成可操作页面，导致 `SEARCH_RESOURCE`/`SELECT_RESOURCE` 对遮挡页面点击并返回 `SEMANTIC_TARGET_NOT_VERIFIED`。

本轮新增 `BATTLE_VICTORY_BANNER` 语义状态和 `DISMISS_BATTLE_VICTORY` Candidate。它使用浮层结构识别、系统返回动作及“POPUP → 非 POPUP”状态 Verifier，不依赖玩家编号、奖励、固定文字或瞬时关闭图标。两张不同时间真实画面 Replay 均识别成功，普通地图负样本未误报。浮层在实机验证开始前自然消失，因此当前状态仍为 CANDIDATE，不虚报 LIVE_VERIFIED。

同时修复资源详情页丢失全局行军容量的问题：OCR 会在 `RESOURCE_DETAIL` 重读 HUD 的 `used/max`，队列已满或只剩体力预留槽时禁止进入采集编队。这是对外部 WOS 项目“每个目标动作前重读物理行军槽”模式的 V2 原生适配。

后续真机采集还暴露了动作后的 ¥30 促销弹窗。派遣本身已经成功，但旧 Runtime 因无法识别插入层而把动作记为失败。现已新增 `REAL_MONEY_OFFER` 硬阻止状态：购买面永久不可执行，只允许系统返回关闭；关闭后继续用原 `DISPATCH_MARCH` Verifier 检查 MAP、MARCHING 和行军队列。相同真机 Before/Popup/After 证据离线复验通过，见 `evidence/live_dispatch_payment_offer_recovery_20260913.json`。历史失败 Episode 保留，不篡改。

修复后再次由 AI 指挥中心自动执行真实采集：`RESOURCE_DETAIL (2/6) → START_GATHER PASS → MARCH → DISPATCH_MARCH PASS → MAP (3/6, MARCHING)`。这是一轮真实状态闭环，不是 Mock；截图位于 `dataset/raw/control_panel/runtime_auto/20260913_071824_614962/`。随后控制台继续自动调度，未发生 worker 意外退出或 watchdog 重启。

四资源均衡策略已接入同一个参数化 `SELECT_RESOURCE`，没有拆成四套 Skill。策略在库存不可可靠读取时持久记录 MEAT/WOOD/COAL/IRON 的派遣次数并选择最少者；当前客户端四种选择状态均已采集为 Live Candidate。首轮非木材真机闭环已经完成：`MEAT 资源详情 (4/6) → START_GATHER PASS → DISPATCH_MARCH PASS → MAP (5/6, MARCHING)`，证据位于 `dataset/raw/live_four_resource_meat_dispatch_20260913/`。持久状态下一目标为 WOOD。

按用户最新策略，固定行军预留已取消：`reserve_for_stamina=0`。普通采集可使用全部队列；实时活动、Intel、巨兽、野怪或真机验证需要槽位时，目标策略选择最低价值采集队列并调用已有 `RECALL_MARCH` Universal Skill，验证 `GATHERING → RETURNING → idle slot increased` 后再执行高优先级任务。

无人值守恢复同时新增并真机验证：`SESSION_DISCONNECTED → RECONNECT_SESSION → MAP`，以及 `BATTLEFIELD_REVIVAL → 安全返回 → MAP`。真实货币促销采用皮肤无关的价格语义硬阻止；UNKNOWN 不再被 Verifier 当作弹窗关闭成功。
