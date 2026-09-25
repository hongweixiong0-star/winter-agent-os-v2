# WorkBuddy → Codex 交接（2026-09-26 凌晨）

> 本轮由 WorkBuddy 在本地工作区直接操作测试小号完成。
> 全部结论均以真机帧为证据；未真机验证的部分已显式标注。

## 1. Git 状态

- **HEAD**：`3905e55 feat(autogen): let the runtime derive the recognition node it is missing`
- **已推送**：是（`origin/main`），Codex 拉取即可获得。本轮两个提交：`1e9b2ef`（巨熊）→ `3905e55`（运行时自主生成）。
- **仍未提交（有意保留）**：
  - `knowledge/ui/semantic_dictionary.json` —— 本轮新增 4 条语义（`BTN_ALLIANCE_SHOP`、
    `BTN_ALLIANCE_TERRITORY`、`TAB_SPECIAL_BUILDINGS`、`TEXT_BEAR_TRAP_COOLDOWN`），但该文件**同时带有本轮之前他人未提交的大量改动**，故未随本轮一并提交，避免与 Codex 未落盘的工作冲突。运行实例读的是工作区文件，4 条语义当前已生效。
  - `winter_agent_v2/runtime.py` —— 工作区仍带 **+745 行你的未提交改动**（活动日历、联盟科技、
    英雄招募、训练批量领取等）。本轮提交只把「autogen 钩子」这 102 行放进索引，
    **你的改动一行都没被提交、也没被丢弃**，工作区文件仍是完整版（6391 行）。
    ⚠️ 请自行提交你的那部分；本轮提交不会与之冲突，但也还没包含它。
  - `knowledge/game/capability_catalog.json` 等未被改动。

## 2. 巨熊（P0）：今天为什么错过，以及现在修到了哪

**根因（已实测确认）**：不是优先级数字问题，而是**生产链上根本没有可用的时间**。

- `learning/timed_event_schedule.json` 的 `roles` 是一个**空数组**。`event_schedule.py` 明确写着
  `reserved_start` 是唯一能产生唤醒的字段——没有预约，就没有任何外部事件来调度 AUTO。
- `knowledge/events/timed_event_readiness.json` 里巨熊的 `start`/`end` 均为 `null`，
  `next_open_condition` 只是一段 2026-09-09 的历史推算，没有任何当前客户端读数。
- **顺带纠正台账里的两处误判**（原为推断，现已被实测推翻）：
  | 旧记录 | 实测结果 |
  |---|---|
  | "PARTICIPATE_BEAR still lacks that RuleBrain route" | `goal_library.route_for('PARTICIPATE_BEAR') == 'ALLIANCE'`，**路由存在** |
  | "no live reservation exists" | `event_schedule.load()` 现在能读到一条真实预约 |

**本轮补上的东西**：从客户端真实读到了陷阱冷却，并据此建立预约。

三次读数单调递减，证明是活倒计时而非静态文字：
```
联盟 → 联盟领地 → 特殊建筑 → 狩猎陷阱   冷却中：1天19:31:51
同一陷阱再来一次                        冷却中：1天19:26:42
野外地图视角看同一陷阱                  冷却中：快19:24:22
```
- **预约**：`reserved_start = 2026-09-27T12:59:58+00:00`（= 北京时间 **09-27 20:59:58**）
- **算法**：观测 UTC 时刻 + 剩余秒数 = 绝对未来时刻，**不含任何时区推断**。
- **工具**：`tools/read_bear_cooldown.py`（可重复运行，会自动走联盟→领地→特殊建筑并重写预约）。
- **状态**：`PREPARED_RESERVED_PENDING_LIVE_EXECUTION`
  —— **预约是真的，参加过一日都没过**。没有活动窗口，所以没有、也不能声称"已成功参加"。

**剩余缺口**（真实开放窗口到来前可补）：
1. 预约语义是"陷阱冷却结束"，并非官方公布的活动开场钟。**到点仍需先验证开放判据**
   （陷阱页显示开放，或联盟集结列表出现"等级1变异巨熊"行），再执行participation。
2. 车头（START_RALLY）**零真机帧**；车身（JOIN_RALLY）流程有测试但无 Window 内实执行。
3. 集结列表滚动未真机执行过。

## 3. 本轮已发现 / 已学习 / 已接线 / 已执行

**已发现（真实帧）**
- 页面：联盟领地、联盟领地·特殊建筑、**联盟商店（全新，V2 原有 184 条迁移记录里没有任何通往它的路径）**、明月的盛典活动页。
- 活动：**明月的盛典** 已开放，倒计时 `1天22:16:26`，积分档 `60/100`，奖励档 360/100/1000，**剩余 50 个灯笼可放飞**。
- 联盟积分 63,372；下次刷新 22:22:37。

**已学习（存入 V2）**
- `learning/l1_experiences.jsonl` 新建，4 条 L1 经验：打开联盟商店、读取巨熊冷却、**放飞灯笼**、
  **从联盟页连续返回会触发退出游戏对话框的导航陷阱**。
- `knowledge/ui/semantic_dictionary.json` +4 条语义。
- `knowledge/ui/page_transitions.json` +3 条迁移（184 → 187）。
- `knowledge/perception/candidates/alliance_btn_shop__1ba620d5/`（element/context/metadata），INDEX 68 → 69。

**已接线（进入数据仓库，未改动生产 Python）**
- 巨熊预约进入 `learning/timed_event_schedule.json` → `event_schedule.load()` 可读 →
  `seconds_until_next_transition()` 返回 154601s 的受限轮询间隔；T-30 起按阶梯加优先级
  （T30 +40 → T15 +200 → T5/T1 +2000 → OPEN +4000）。
  **本轮未修改任何 `winter_agent_v2/` 下的生产代码。**

**已执行（MAA 真实发送并被游戏确认）**
- ✅ **放飞灯笼 ×1**：点击后弹出奖励 +14；关闭后再看，**剩余 50 → 49**，是一次真实消耗。
- ✅ 打开联盟商店（首页无卸载）。
- ✅ 读取巨熊冷却三次。
- ⚠️ **失败/教训**：从联盟商店连续 `PRESS_BACK` 三次会触发"确认退出游戏吗？"对话框；
  已点"取消"保护住游戏。**离队联盟页应走底部导航（城镇/野外），不要用连续 BACK。**

## 4. 当前运行环境

- **角色**：`role_id=1171757165`（xhw小号，kingdom 4298，联盟 tag zoe）——测试小号，用户确认。
- **设备租约**：已释放，`state = V2控制中`，无持有者，**设备空闲**。
- **AUTO 运行状态**：**未运行**（当前无任何 python/pythonw 进程）。

> ⚠️ 给 Codex 的重要提醒（本会话实测，连续三次复现）：
> **本环境（开发工具）启动的 GUI 会在调用结束时被进程回收**，包括用 `Start-Process`、
> `cmd //c start`、以及项目自带的 `tools/_launch_panel_detached.py`（DETACHED_PROCESS）都一样。
> 要让 AUTO 真正连续运行，必须由操作者**在桌面双击 `Start-Winter-Agent-V2.cmd`**，
> 不能由 AI 代启动后宣称"AUTO 已恢复"。本轮已把preflight 修到 PASS
> （设备 127.0.0.1:7555 在线、720x1280、前台 com.gof.china），双击即可成功启动。

## 5. 其他限时活动

| 活动 | 时间信息来源 | 状态 |
|---|---|---|
| BEAR_HUNT 巨熊 | 真机读取陷阱冷却（本轮） | 预约 09-27 20:59:58 +08，待真机执行 |
| 壶纳千祥 / 此前记为 DISCOVERED_EVENT_B010DFFED8 | 日历观测 09-25 | **本轮实锤为"明月的盛典"**，已开放，倒计时 `1天22:16:26` |
| ARMAMENT_COMPETITION 军备竞赛 | 仅 09-05 单次观测 | 仍 `REGISTERED_AWAITING_LIVE_WINDOW`，start/end null |
| KINGDOM_OF_POWER 强国之争 | 仅 09-09 单次观测 | 同上 |
| 玉魄流光礼包 | 主城右栏倒计时 21:47:01 | 仅观测，未接线 |

## 5b. 运行时自主生成（本轮第二个提交，`3905e55`）

闭合了「缺失节点只能等人手写」这个长期缺口：**运行中发现找不到控件 → 自己派生节点 → 写回路由表 →
下一次解析同一个语义就能找到**。已提交范围 9 个文件 / +1833 行。

| 文件 | 作用 |
|---|---|
| `winter_agent_v2/pipeline_autogen.py` | 派生本体：capture（走既有设备路径）/ locate_text（既有 OCRService）/ 裁剪模板 / wire（经 `RoutingTable.save()`） |
| `winter_agent_v2/executor_router.py` | `maa_resolver` 按 `kind` 分派：OCR 走 `adapter.ocr()`，模板走 `find()`；**并修掉 `save()` 会删除 `not_migrated` 与缩短 `policy.note` 的严重 bug** |
| `winter_agent_v2/runtime.py` | `_maybe_autogen_node()` 钩子，挂在「首次记录 unresolved 控件」处 |
| `knowledge/execution/backend_routing.json` | 5 个新节点，全部 `promoted: false` / **P3**（不是 P0） |
| `tools/pipeline_coverage.py` | A/B/C/D 覆盖清单 |
| `tools/autogen_harvest.py` | 两阶段采帧生成，**验证通过才写入** |
| `tools/autogen_closed_loop.py` | 闭环证明脚本 |
| `tests/test_pipeline_autogen_hook.py` + `tests/test_executor_router.py` | 27 项，全通过 |

**实测覆盖现状（跑 `tools/pipeline_coverage.py` 可得）**：137 个技能里只有 **4 个**有真 MAA 识别节点；
16 个 goal 里 **0 个**达到 A 类。这是「批量补全」的真实起点，不是估算。

**踩过的坑（别再踩）**
- 模板必须用**裁剪到屏幕后的同一 ROI** 去切，否则 MAA 报 `templ size is too large`。
- PIL `crop` 参数是 `(l,t,r,b)`，不是 `(x,y,w,h)`。
- 底部导航真实 y = **1250**（不是 1240）；访问子页前要先返回，否则停在子页里采到错帧。
- `OCRToken` 是 dataclass 不是 dict；`validate()` 要显式传帧，传 `None` 会让 MAA 重抓当前帧导致 0/0。
- 生成的节点**必须**标 `promoted: false`：它是采集验证，不是语料 A/B 测量，标 P0 就是虚报。

**测试口径**：`tests/test_live_runtime.py` 有 4 项失败，但**在 HEAD（不含本轮改动）上同样是这 4 项失败**，
属基线既有，本轮既没有引入也没有修好——不做相反宣称。全量基线：47 失败 / 3096 通过。

## 6. 下一项可直接执行的开发任务

1. **优先**：让操作者桌面启动 AUTO，跑一轮普通 AUTO，确认 Wolf loneliness 把 Session 得到的知识用起来。
2. **巨熊收口**：execute（09-27 21:00 前）把 `PARTICIPATE_BEAR` 的执行链在**预设的沙盒演练**中跑通
   ——难点是真机没有集结列表可言；建议先用历史帧 `dataset/raw/bear_live_20260909/` 做离线回放验证
   `read_rally_list` + JOIN 决策，并把"到点后先验证开放判据"这一步写成硬门禁。
3. **放飞灯笼接 AUTO**：本轮证明了能跑，下一步把 `BTN_FLY_LANTERN` 注册为 Skill 并接入
   `EVENT_MINIMUM_GUARANTEE` 路由（现已有该路由），让 AUTO 自动消耗灯笼。
4. **补红点真机样本**：联盟商店红点已有第 1 份证据；按 `entry_badges` 口径还需 ≥3 个独立正样本 + 反例才能注册。
5. **批量补全 Pipeline（接着本轮做）**：跑 `tools/pipeline_coverage.py` 拿到 B/C 类清单，
   用 `tools/autogen_harvest.py --visit page:x,y --back-before N --apply` 逐页采帧生成；
   生成后必须补正负帧验证，验证不过的不要 wire。
6. **（Codex 先做）提交你自己在 `winter_agent_v2/runtime.py` 的 745 行未提交工作**——
   本轮已刻意绕过它，但它现在只存在于工作区，任何 `git checkout` 都会毁掉它。
