# 首次真机领取免费体力（free_stamina_claim_20260915）

`CLAIM_FREE_STAMINA` 在本项目语料里**从未被执行过**（`learning/episodes.jsonl` 0 条记录），
它的验证器 `verify_free_stamina_claimed` 也从未判过一次真实领取。本轮补齐了这条证据。

## 事实（LIVE_CLIENT）

跑法：`tools/run_live.py --goal INTEL --max-actions 6 --stop-after CLAIM_FREE_STAMINA --serial 127.0.0.1:7555`

| 步骤 | 时刻 (UTC) | 技能 | 前 → 后 | 体力读数 |
|---|---|---|---|---|
| 1 | 04:12:23 | `OPEN_STAMINA_SOURCES` | MAP → POPUP | 前 `MAP_HUD 2` → 后 `STAMINA_PANEL 2/200, free_claim_available=true` |
| 2 | 04:12:26 | `CLAIM_FREE_STAMINA` | POPUP → POPUP | 前 `2/200, true` → 后 **`152/200`, false** |

- 动作是真实的：`{"kind": "TAP_SEMANTIC", "target": "BTN_CLAIM_FREE_STAMINA"}`。
- 状态变化是真实的、不可逆的：**体力 2 → 152（+150）**，与 `config/v2.json` 里
  「丰盛的招待 +150 必须领取」完全一致。
- 判定来自面板自己的读数（`verify_free_stamina_claimed`），`verifier_ok=true`，`exit 0`。
- `BTN_CLAIM_FREE_STAMINA` 模板（`dataset/candidate/stamina_sources/
  btn_claim_free_stamina__live_stamina_panel.png`）**首次在真正可领取的面板上命中**：
  03 帧的绿色「领取」按钮就是该模板，04 帧它被「下次补给」倒计时取代。

帧对照（肉眼可核）：
- `03_panel_before_claim_stamina_2_live.png`：`2/200` + 绿色**领取**
- `04_panel_after_claim_stamina_152_live.png`：`152/200` + 领取 → **下次补给 06:47:35**

## 顺带测出的补给周期（重要修正）

领取后 04:12:26Z 面板显示 `下次补给 06:47:35` ⇒ 下次补给 **11:00:01Z**。
上一轮独立测到的补给时刻是 **04:00:01Z**（另一张帧 `下次补给 00:00:15` @ 03:59:46.7Z）。

⇒ **补给间隔正好 7 小时**（04:00 / 11:00 / 18:00 / 01:00 UTC，即北京 12:00 / 19:00 / 02:00 / 09:00），
**不是每天一次**。所以「下次补给」倒计时可以直接当绝对时间用，而且免费体力一天有 3–4 次机会。
这一条把 `04_OPEN_ISSUES.md` 里 `0e` 的价值从「省 2 个动作」提到「每 7 小时一次 +150」。

## 同一批次的其它证据

`live_run_records.json` 还含本轮 4 次真机运行的全部步骤记录（20 条），其中包含：

- `live_free_gift_claim_20260915`（03:59Z）：免费体力检查被跑到，但面板在补给前 **15 秒**被读到
  （`下次补给 00:00:15`，没有领取按钮），于是 `BACK`，整轮错过 +150。
- `live_free_gift_claim_20260915b`（04:03Z）：体力真的是 **0**，而 `HUD_STAMINA_ROI` 对单独的
  `0` **一个 token 都读不出来**，导致 `stamina={}`，于是免费体力检查被整条跳过。
- `live_zero_stamina_claim_20260915`（04:10Z）：从情报页出发，全程没站到地图上，检查同样没跑。

## 尚未真机确认的部分

- 「体力为 0 时仍然打开免费体力检查」这一改动**已单测但未真机复现**（要复现得让体力回到 0）。
- 「营地战斗被客户端拒绝后可恢复」这一改动**已单测但未真机复现**（本轮没能造出「闸门读不到体力
  + 客户端拒绝」的组合）。
