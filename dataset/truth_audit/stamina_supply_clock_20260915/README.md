# 免费体力补给时钟：读得到、存得住、不再白跑（2026-09-15）

一次真机 A/B 关闭了两个未决问题（`0au` + `0e`），并顺手拆掉一颗运行时炸弹。

## 一句话

`获取更多` 面板自己写着下一次免费礼物何时到（`下次补给 06:47:35`）——
把它读出来存成绝对时刻，就同时解决了「无人值守循环根本走不到地图」和
「每个 cycle 白花 2 个动作去确认一个 7 小时才到一次的东西」。

## 顺带修掉的运行时炸弹（最重要的一条）

脏树里 `ocr.HybridVision.observe` 在 `GET_MORE_STAMINA` 面板分支上调用
`self._next_supply_seconds(...)`，而**这个方法在任何类上都不存在**
（AST 核对：`HybridVision` 只有 `__init__ / _semantic_roi / observe`）。
它是**语法合法的**，所以 `check_wiring.py`、`pytest`、`import` 全部通过，
只有真机走到那个面板时才炸 `AttributeError` —— 而那个面板**正是免费体力唯一的入口**。

⇒ 已实现为模块级函数 `read_next_supply_seconds()`，并补上单测与真机复现。

## 两个未决问题

### `0au` —— 检查根本不可达

免费体力检查住在**世界地图**分支里，而无人值守的情报循环整个 run 都待在情报页。
真机 `04:10:33Z` 实测：从情报 pin 弹窗起手的 run **一次都没站到地图上**，
所以面板永远打不开，`0am`/`0as` 修好的东西等于没生效。

**修法**：情报页分支在「礼物可能到期」时主动 `OPEN_MAP` 去一次，
由 `stamina_panel_checked` 限一遍（每 run 最多一趟往返）。
措辞上刻意**不**把它标成「本轮已检查」——面板还没看，不能先记完成。

### `0e` —— 每个 cycle 白跑两趟

面板是唯一能看到礼物的地方，所以最原始的做法是「每 run 看一次」。
但补给周期实测 **7 小时**（`04:00:01Z` / `11:00:01Z`），而循环最多 8 cycle/小时
⇒ 约 **16 个动作/小时**去确认一个每天只到 3 次的东西。

**修法**：读面板自己的倒计时 → 存成绝对时刻 → 只在到期附近才去。

## 倒计时读数（LIVE_CLIENT，生产 OCR 栈）

| 帧 | 倒计时 | 置信度 | 备注 |
|---|---|---|---|
| `04_panel_after_claim_stamina_152` | `06:47:35` | 0.936 | 领取后，⇒ 下次 `11:00:01Z` |
| `04_stamina_panel_opened_live` | `00:55:33` | 0.952 | |
| `02_stamina_refusal_popup_after` | `00:13:18` | 0.963 | |
| （另一帧 03:59:46.7Z） | `00:00:15` | 0.965 | ⇒ `04:00:01Z` |

相隔 13 分钟的两帧外推同一时刻、误差 1 秒 ⇒ 是真实时钟，不是动画。
**领取按钮在场时完全没有倒计时**，所以「读不到」也是一个事实，不是失败。

解析器的闸门（6/6 符合预期）：

```
03_panel_before_claim_stamina_2_live.png    -> None   （可领取，行内只有「领取」）
04_panel_after_claim_stamina_152_live.png   -> 24455  （06:47:35）
04_stamina_panel_opened_live.png            -> 3333   （00:55:33）
02_panel_with_claim_button_live.png         -> None   （可领取）
03_map_before_free_stamina_check_live.png   -> None   （地图帧）
01_hero_camp_panel_before_live.png          -> None   （营地面板）
```

## Live A/B（同 goal、同客户端、连续两次）

**Run A** `08:14:56Z`，从**世界地图**起手：

```
1 OPEN_STAMINA_SOURCES reason=free_stamina_gift_not_yet_checked_this_run
  action TAP_SEMANTIC HUD_STAMINA_GAUGE   backend ADB
  MAP -> POPUP/GET_MORE_STAMINA
  stamina_after {"current":191,"max":200,"free_claim_available":false,
                 "next_supply_in_seconds":9900}          ← 新字段，真机首次出现
  verifier True OK
2 BACK   reason=stamina_panel_without_a_free_gift   （礼物未到期，正确退出）
3 OPEN_INTEL  MAP -> INTEL
stop=MAX_ACTIONS_REACHED  exit=0  （3/3 verifier OK）
```

落盘：`learning/stamina_supply.json` = `next_supply_at: 2026-09-15T11:00:02.444704+00:00`

**Run B** `08:16Z`，从**情报页**起手 —— 这是 `0e` 的节省证据：

```
1 SELECT_INTEL_PIN            INTEL -> POPUP     verifier OK
2 OPEN_INTEL_BEAST_TARGET     POPUP -> BEAST     verifier OK
3 INTEL_BEAST_START_MARCH     BEAST -> MARCH     verifier OK
stop=MAX_ACTIONS_REACHED  exit=0  （3/3 OK）
```

**没有回地图**，直接做了 3 步真实情报工作。修复前，只要 `stamina_panel_checked`
还是 False，这里就会多出 `OPEN_MAP` + `OPEN_STAMINA_SOURCES` + `BACK` 三步白工。

> 注：Run B 的第 1 步不是 `OPEN_MAP`，因为 Run A 已把时钟存下且未到期。
> 这条正是要证明的行为。

**Run C** `08:17:4xZ`（把落盘时钟人为置到 2 小时前，逼出「到期」路径）——
证明到期路径**真的会去开面板**：

```
1 DISPATCH_INTEL_BEAST     MARCH -> MAP   verifier OK   （顺手真实派出一次巨兽，体力 191→181）
2 OPEN_STAMINA_SOURCES     MAP -> POPUP/GET_MORE_STAMINA   verifier OK   ← 到期路径确实触发
  stamina_after {"current":181,"max":200,"free_claim_available":false,
                 "next_supply_in_seconds":9710}
3 BACK   reason=stamina_panel_without_a_free_gift   （礼物确实未到期，正确退出）
4 OPEN_INTEL               MAP -> INTEL
stop=MAX_ACTIONS_REACHED  exit=0  （4/4 verifier OK）
```

**顺带独立复现了 7 小时周期**：`9710s` @ `08:18:13Z` ⇒ `11:00:01.758Z`，
与 Run A 的 `11:00:02.444Z`（以及更早那次 `04:00:01Z + 7h = 11:00:01Z`）**到秒一致**。
⇒ 三组独立读数互相印证，倒计时可安全当绝对时刻用。

⚠ **Run C 之后必须还原真实时钟值**（已还原为 `11:00:02.444704Z`）：
把 `learning/stamina_supply.json` 留在过去会让每个 run 都白跑一趟面板。

## 「未知」的方向（安全取舍）

未知 **一律当作到期**。两个方向的代价不对称：

- 错判「没到期」⇒ 每 7 小时**静默丢掉 150 体力**；
- 错判「到期」⇒ 白花 **2 个动作**。

存储文件缺失 / 损坏 / 时区不可比（naive 时间戳）⇒ 一律回到历史的「每 run 查一次」。

## 文件

| 文件 | 内容 |
|---|---|
| `live_ab_records.json` | 两次真机运行的完整步骤记录（含 before/after/verifier） |
| `stamina_supply.json` | Run A 落盘的绝对补给时刻 |

复现：

```
cd "E:/无尽冬日智能体" && "E:/dongri-mumu-bot/.venv/Scripts/python.exe" -u \
  tools/run_live.py --goal INTEL --max-actions 3
```

测试：`tests/test_stamina_supply_clock.py`（22 项）。全量 **542 passed, 7 skipped**
（上一轮 422）；`tools/check_wiring.py` = `problems: 0`。

## 仍未验证的部分（不许读成更多）

- **真机「领到 +150」这一环**：本轮三次运行礼物都**确实未到期**
  （`free_claim_available=false`，`next_supply_in_seconds` 分别 9900 / 9710 / 未读）。
  所以「时钟说到期 → 开面板 → 真的领到 +150」这条链，真机只走到**开面板**为止。
  `CLAIM_FREE_STAMINA` 本身的 verifier 判真实领取已由 `0aq` 单独闭环
  （`dataset/truth_audit/free_stamina_claim_20260915/`，体力 2→152），
  但**「时钟驱动的到期」尚未与一次真实领取拼在同一次运行里**。
  下一次真实到期（`11:00:02Z`）后的 run 即可补上这一环。
- 补给时刻的**长期稳定性**仍待观察：目前 4 个采样点全部落在
  `04:00:01Z / 11:00:01Z` 的 7 小时网格上，但样本跨度不到一天，
  客户端是否有维护偏移/版本变更尚未知。
