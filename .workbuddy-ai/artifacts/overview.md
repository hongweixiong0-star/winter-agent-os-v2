# 本轮总览 —— 免费体力首次真机领取 + 「费用画成红色」是客户端自己的判决

> Winter Agent OS V2 · 2026-09-15 14:0x GMT+8 · 证据等级：**LIVE_CLIENT**
> 未真机复现的部分逐条标注，不虚报。

## 一、`0an` 关闭：免费体力首次真机领取

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
证据：`dataset/truth_audit/free_stamina_claim_20260915/`。

## 二、补给周期实测 7 小时

`03:59:46.7Z` 显示 `下次补给 00:00:15` ⇒ **04:00:01Z**；`04:12:26Z` 领取后显示 `06:47:35` ⇒ **11:00:01Z**。
**正好差 7 小时** ⇒ 04:00 / 11:00 / 18:00 / 01:00 UTC（北京 12/19/02/09 点），**一天 3–4 次**。

## 三、两条「空读数」缺陷：**「读不到」被当成了「不要做」**

真机 04:03:02Z 体力**真的是 0**，`HUD_STAMINA_ROI` **一个 token 都读不出** ⇒ `stamina={}`，
于是：大脑 MAP 分支跳过免费体力检查（恰好在礼物最值钱的一帧）；运行时也拒绝解析体力条点击目标。

- **降阈值被否决**：单独的 `0` 在任何 padding×scale 下最高置信度 **0.73**，且在 `0`/`O` 间跳。
- **加 padding 被否决**：35 帧闸门上**一个值都没变**。
- **采用**：把「要不要去看」「能不能点」与「数字读没读到」解绑。依据：6 张 MAP 帧中 2 张读不出，
  **2/2 都是干净 HUD、体力条画着并显示 0**；礼物可领与否由**面板自己的模板**判定。

另修 `0at`：营地战斗被客户端拒绝不再掐死整轮（改为可恢复路由，先例 `RESOURCE_NOT_FOUND`）。

## 四、`0av`：**客户端把「你付不起」直接画成红色**

追一条 `DISPATCH_INTEL_BEAST / SEMANTIC_TARGET_NOT_VERIFIED`（出征按钮明明在屏幕上）追出来的。

- 定量：模板画的是**白**色花费 `10`（且从父帧同一 ROI 裁出，**父帧 d=0**），真机那帧是**红**色 `10`；
  ccoeff **带 SEARCH_MARGIN** scale 1.0 打分 **0.9152** ⇒ 形状对、只是颜色。
- **颜色本身就是判决**（`tools/probe_cost_colour.py`，3 种按钮 5 帧）：

  | 帧 | 体力 | 花费 | 红像素 |
  |---|---|---|---|
  | 出征（真机 04:11Z） | 0 | 10 | **452** |
  | 营地面板 | 7 | 10 | **220** |
  | 营地面板 | 16 | 10 | 0 |
  | 英雄出征页（已出征） | 10 | 10 | 0 |
  | 出征模板源 | 可付 | 10 | 0 |

  **5/5，且不是阈值判断**（能付的帧是**零**红像素）。
- **真机 A/B**：`04:11:16Z` 体力 0 ⇒ 花费红 ⇒ 模板不命中 ⇒ **FAILURE**；
  `06:14:56Z` 体力 176 ⇒ 花费白 ⇒ 模板命中 ⇒ 同一技能 **SUCCESS**，整轮 10/10、exit 0。
- 已落地：`unaffordable_cost_pixels()` + `HybridVision` 在营地面板写 `stamina.cost_affordable`
  + `brain.py` 把它当**最高优先级**信号（`False` ⇒ 去取免费体力；`None` 不得阻止能付的战斗）。
- **有意没做**：没把红色变体加进 `BTN_BEAST_DISPATCH` 模板 —— 那只会让我们去点一个必被拒的按钮。

## 五、验证

| 项 | 结果 |
|---|---|
| 全量测试（冻结树，`0av` 前，`eb23534`） | **533 passed, 7 skipped, 54 subtests**，exit 0 |
| 加宽定向集（18 文件，`0av` 后） | **158 passed, 2 skipped, 33 subtests** |
| 全量测试（本轮末，冻结树） | 见 `out_full_final3.txt` |
| `tools/check_wiring.py` | `problems: 0` |
| `tools/verify_handoff.py` | `ALL HANDOFF INVARIANTS PASS` |
| 真机运行 | 6 轮：exit 0（首次领取 +150）/ exit 0（5/5）/ exit 0（10/10，含真实出征成功）/ exit 2（诚实拒绝）等 |

新增：`tests/test_camp_fight_refusal_recovery.py`(11) · `tests/test_stamina_check_without_a_read.py`(10)
· `tests/test_cost_colour_verdict.py`(9) · `tools/probe_stamina_zero.py` · `tools/probe_map_gauge_unreadable.py`
· `tools/probe_cost_colour.py` · 证据 `dataset/truth_audit/free_stamina_claim_20260915/`

## 六、未完成 / 风险（不虚报）

1. **`0as`/`0at`/`0av` 的 `cost_affordable` 字段都没在真机运行中出现过**（两轮都没走到营地面板）；
   `0av` 只有生产单帧 + 真机 A/B 佐证。
2. **`0au`（最高价值）：pin 循环里免费体力检查可能根本不跑** —— 从情报页出发的 `run_live.py`
   全程不回地图（`BACK` 从情报 pin 弹窗回到 INTEL 而非 MAP），所以以上修复在无人值守循环里可能不生效。
3. **`0e`/`0ar`**：持久化「下次补给」绝对时间（现已测到 7 小时周期），让检查只在窗口附近付出动作成本。
4. **`0al` 需操作者决策**：账上 1,007 个「恢复 10 点」道具（≈10,070 体力）而体力长期个位数。**未动代码。**
5. **`0ap`**：自动化接口报 ACTIVE 但无运行痕迹（第 3 次）。**未拿到真实产物前不得声称有无人值守在跑。**
6. **72 小时 Soak 仍未开始。**
