# Winter Agent OS V2 — 接管轮次总览（2026-09-15）

## 一、这一轮做了什么（两条独立改进，都已落盘 + 真机证据 + checkpoint）

### 1. 修复：出征（部队编成）页被读成联盟首页 → 直接造成真实失败
- **Before**：`INTEL_BEAST_START_MARCH` 在真机报 `INTEL_BEAST_MARCH_NOT_PROVEN`（00:14:13Z）。
- **After**：同一技能 verifier OK；真机端到端 10/10 步全 PASS。
- **根因**：出征按钮 `BTN_BEAST_DISPATCH` 是**动画控件**（真机帧上还叠着 `00:00:29` 倒计时徽标），
  同一页面两帧实测 d=0 / **d=26**（阈值 8）。它一失手，下一条命中的就是 `PAGE_ALLIANCE` **标题条**（d=8），
  整页被报成联盟首页。而这一页**复核过的两个锚点**（`PAGE_BEAST_MARCH`、`STATUS_VICTORY_ASSURED`，均 d=0）
  在清单里存在却**没有任何分支引用**（孤儿模板）。
- **修法**：在按钮分支**之后**加「两个锚点同时命中」的分支 → `Page.MARCH` + `victory_assured`。
  不声明野兽名/等级（出征页不显示它们，声明就是编造）。
- **影响面闸门**：2716 张真机帧中，83 帧命中锚点 → 75 帧本已是 MARCH（不变）、8 帧是 ALLIANCE，
  其中**只有 5 帧两个锚点同时命中**（全是同一张出征页）⇒ **恰好影响 5 帧，零附带损伤**；
  89 张联盟类帧两个锚点零命中。

### 2. 修复：handoff 的「最高失败」按全时段计数排序，把人引向已死的问题
- 差点按 `CURRENT ROOT CAUSE: SEMANTIC_TARGET_NOT_VERIFIED x112` 开工。
  按天拆开是 **09-12: 36 / 09-13: 37 / 09-14: 8 / 09-15: 0**；`MARCH_PAGE_NOT_OPEN x59` 全部在 09-12 一天。
- 于是「`START_GATHER` 是 94 次尝试 / 37% 的最差高频技能」也是**历史包袱**（59 次失败全在 09-12，之后零失败）。
- **改法**：每个 failure_type 增加 `recent`（相对最新 episode 的 2 天窗口，按完整时间戳比较）、
  `last_seen`、`dates`、`undated`；`top_failures` 改为 **recent 优先**；recent=0 直接标注 `HISTORICAL`。
- **结论**：09-15 全天只有 **1 条失败**，就是本轮已修的那条 ⇒ 当前几乎没有「活着的」未解释失败。

## 二、当前真实状态

| 项 | 值 |
|---|---|
| commit / checkpoint | `8943141`（上一 checkpoint `6a2a96c`） |
| episodes | 1043（production 1043） |
| success rate（decided） | 0.7013 |
| skills: stable / live_verified / degraded | **20** / 26 / 10 |
| evidence integrity | PASS |
| 全量测试 | **431 passed, 7 skipped, 7 subtests passed** |
| `check_wiring.py` | problems: 0 |
| 无人值守自动化 | `e3485d0c-…` **ACTIVE**（每小时，已用接口复核存在） |

## 三、下一步最高价值任务（按证据排序）

1. **能力缺口**：4 个 goal `BLOCKED`（`KEEP_RESEARCH_PRODUCTIVE`、`ALLIANCE_TIMED_EVENTS`、
   `USE_FREE_ARENA_ATTEMPTS`、`LABYRINTH_DAILY`）+ 8 个 `PARTIAL`。
   单点杠杆最高的是 `CHECK_ALLIANCE_EVENT`（缺失即卡住 2 个 goal）。
2. **无人值守时长**：72h soak 至今未启动 —— 项目目标就是「数天无人值守」。
3. **登记待修（不阻塞）**：出征页被赋予页面上不存在的野兽身份（`0w`）；
   `PAGE_ALLIANCE` 弱标题条会误命中「出征族」页面（`0x`）；光晕 pin 比例下限余量只剩 0.021（`0s`）。

## 四、诚实声明（不虚报）
- `INTEL_BEAST_START_MARCH` 的真机通过**走的是按钮分支**，证明「链路通」；
  **新分支的真机触发**由同帧 A/B（`intel_board_20260915_003755.png`：补丁前 `ALLIANCE/HOME` →
  补丁后 `MARCH {victory_assured: True}`）证明，两者不是同一件事。
- 项目至今**没有任何经过验证的「空情报板」帧**；`NOT_AVAILABLE` 仍只能由「pin 检测器一个都没看到」到达。
- 截图不进 git（`.gitignore`），「Live Verified」的可追溯性依赖本机磁盘。

## 五、改动清单
- `winter_agent_v2/vision.py`：出征页稳定锚点分支（+30 行注释说明证据与取舍）。
- `tools/update_workbuddy_handoff.py`：失败时效字段 + recent 优先排序 + `failure_rank_line()`。
- `tests/test_beast_formation_page.py`（新，9 项）；`tests/test_handoff.py`（+4 项）。
- `tools/probe_anchor_decision.py`（新）、`tools/probe_frame_semantics.py`（新）、
  `tools/probe_page_anchor.py`（新，**已被前者覆盖，待确认后清理**）。
- 受保护证据：`dataset/truth_audit/beast_formation_page_20260915/`、
  `evidence/page_anchor_decision_20260915.json`。
