# 本轮总览 —— 免费体力首次真机领取闭环 + 两条「空读数」缺陷

> Winter Agent OS V2 · 2026-09-15 12:2x GMT+8 · 证据等级：**LIVE_CLIENT**
> 所有结论都来自真机运行或语料闸门；未真机复现的部分已在下文逐条标注。

## 一、最重要的结果：`0an` 关闭（免费体力首次真机领取）

`CLAIM_FREE_STAMINA` 在本项目语料里**从未被执行过**（0 条记录），它的验证器也**从未判过一次真实领取**。
本轮补齐：

```
tools/run_live.py --goal INTEL --max-actions 6 --stop-after CLAIM_FREE_STAMINA   ->  exit 0

step 1  04:12:23  OPEN_STAMINA_SOURCES   MAP -> POPUP
        before.stamina {"current": 2, "source": "MAP_HUD"}
        after.stamina  {"current": 2, "max": 200, "source": "STAMINA_PANEL", "free_claim_available": true}
step 2  04:12:26  CLAIM_FREE_STAMINA     POPUP -> POPUP
        before.stamina {"current": 2,   ..., "free_claim_available": true}
        after.stamina  {"current": 152, ..., "free_claim_available": false}
        action {"kind": "TAP_SEMANTIC", "target": "BTN_CLAIM_FREE_STAMINA"}
```

**体力 2 → 152（+150）**，真实点击真实按钮，判定来自面板自身读数，`verifier_ok=true`。
`BTN_CLAIM_FREE_STAMINA` 模板**首次在真正可领取的面板上命中**。

帧对照（肉眼可核，均在 `dataset/truth_audit/free_stamina_claim_20260915/`）：
- `03_..._stamina_2_live.png`：`2/200` + 绿色**领取**
- `04_..._stamina_152_live.png`：`152/200` + 领取被「下次补给 06:47:35」取代

## 二、顺带测出的新事实：补给周期是 7 小时（不是每天一次）

| 时刻 (UTC) | 面板显示 | 推出的补给时刻 |
|---|---|---|
| 03:59:46.7 | 下次补给 `00:00:15` | **04:00:01** |
| 04:12:26 | 下次补给 `06:47:35` | **11:00:01** |

两者**正好差 7 小时** ⇒ 补给时刻 **04:00 / 11:00 / 18:00 / 01:00 UTC**（北京 12:00 / 19:00 / 02:00 / 09:00），
**一天 3–4 次**。且两帧相隔 42 分钟、外推误差仅 **1 秒** ⇒ 倒计时可以直接当**绝对时间**持久化。
这把 `0e` 从「省 2 个动作」升级为「每 7 小时一次 +150」。

## 三、两条同源缺陷：**「读不到」被当成了「不要做」**

真机 04:03:02Z：体力**真的是 0**（上一轮出征花光最后 10 点），而 `HUD_STAMINA_ROI` **一个 token 都读不出来**
⇒ `stamina={}`。同一个错误条件在两层各出现一次：

| 位置 | 条件 | 实际后果 |
|---|---|---|
| `brain.py` MAP 分支 | `stamina.current is not None` 才去开免费体力面板 | **恰好在礼物最值钱的一帧跳过检查**，转去开情报 pin |
| `runtime.py` 目标解析 | 同一条件才解析体力条点击目标 | 即使大脑做了决定也**执行不了** |

### 两个候选修法都被实测否决

- **降阈值**：单独一个 `0` 在任何 padding(0/2/4/6/8) × scale(1/2) 下最高置信度只有 **0.73**，
  且在 `0` 与 `O` 之间跳（同一字形 scale=3 读成 `'O'`）⇒ 读出来的不是"数字"是"猜测"。
- **加 padding**：在 35 帧闸门上**一个值都没变**（可读 11→11，不一致 0 处）⇒ 不是修法。

### 采用的修法：把「要不要去看」「能不能点」与「数字读没读到」解绑

依据（全部实测）：
- `tools/probe_map_gauge_unreadable.py`：6 张 MAP 帧中 2 张读不出，**2/2 都是干净 HUD、体力条画着并显示 0**。
- 礼物是否可领由**面板自己的模板**判定，不由体力条判定 ⇒ 「要不要去看」不需要数字。
- 点击目标是体力条自己的中心，且 `page is MAP` 已排除弹窗/加载页 ⇒ 「能不能点」也不需要数字。

## 四、`0at`：营地战斗被客户端拒绝会掐死整轮

`runtime.py` 在**第一次验证失败就 `return`**，所以 `INTEL_HERO_MARCH_REFUSED_FOR_STAMINA`
（上一轮的诚实拒绝修复）会终结整轮 —— 而它离免费体力检查只差一步。

**反事实**：没有这条路时，`03:51:37Z` 那轮死在第 3 步，永远到不了第 4–5 步。

**修法**：把「被拒」当成可恢复的路由信号（先例：`RESOURCE_NOT_FOUND` 的两个分支），
把**客户端自己的判决**记到 `brain.camp_panel_refused` 后 `continue`，每轮限 1 次；
运行时**不自己按键**，`POPUP/GET_MORE_STAMINA` 仍归 `RuleBrain` 决定。

## 五、验证

| 项 | 结果 |
|---|---|
| 定向测试集（15 个文件，含 2 个新文件） | **142 passed, 2 skipped, 27 subtests** |
| 全量测试（冻结树） | 见 `04_OPEN_ISSUES.md` 本轮小节 / 下方补记 |
| `tools/check_wiring.py` | `problems: 0` |
| 真机运行 | 4 轮：`exit 0`（10 步含真实出征）/ `exit 0`（8 步）/ `exit 2`（诚实拒绝）/ **`exit 0`（首次领取 +150）** |

新增测试文件：
- `tests/test_stamina_check_without_a_read.py` —— 空读数不得跳过检查（10 项）
- `tests/test_camp_fight_refusal_recovery.py` —— 被拒可恢复，含端到端「拒绝之后真的走到免费体力检查」（11 项）

新增只读探针：
- `tools/probe_stamina_zero.py` —— 量化 `0` 在各 padding×scale 下的可读性 + 35 帧一致性闸门
- `tools/probe_map_gauge_unreadable.py` —— 统计 MAP 帧中读不出的比例并导出待目视裁剪

## 六、未完成 / 风险（不虚报）

1. **`0as` 与 `0at` 都只有单测，未真机复现。** `0as` 需体力回到 0；`0at` 需「闸门读不到体力 +
   客户端拒绝」同时出现 —— 本轮起点不对（没站到地图上、体力不是 0），没造出来。
2. **`0au`（新发现，最高价值）：pin 循环里免费体力检查可能根本不跑。**
   从情报页出发的 `run_live.py` 全程不回地图（`BACK` 从情报 pin 弹窗回到 INTEL 而不是 MAP），
   所以上面所有修复在无人值守循环里可能永远不生效。
3. **`0al` 需操作者决策**：账上 1,007 个「恢复 10 点」道具（≈10,070 体力）而体力长期个位数；
   `config/v2.json` 只授权 `BTN_CLAIM_FREE_STAMINA`。**未动代码。**
4. **`0ap`**：自动化接口报 ACTIVE，但恢复后约 1 小时零运行痕迹（第 3 次）。
   **在拿到一次真实运行产物前，不得声称有无人值守在跑。**
5. **72 小时 Soak 仍未开始。**

## 七、下一步（按价值排序）

1. **`0au`** —— 让免费体力检查在无人值守循环里真的跑起来（1–4 生效的前提）。
2. **`0e`/`0ar`** —— 持久化「下次补给」绝对时间，让检查只在窗口附近付出动作成本。
3. 真机复现 `0as` / `0at`（先确认起点状态）。
4. `0al` 等操作者决策；`0ap` 等一次真实自动化运行产物；72h Soak。
