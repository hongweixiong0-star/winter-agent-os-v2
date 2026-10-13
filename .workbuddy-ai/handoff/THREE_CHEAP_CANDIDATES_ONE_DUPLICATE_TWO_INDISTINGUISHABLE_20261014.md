# 三个"最便宜的候选"里：一个是重名，两个分不开（2026-10-14）

> 起因：按 `CAPABILITY_EXPANSION` 的主路线挑预载目标。扫描出来的最便宜的是四个**只缺
> `Preconditions` 一个字段、风险 T0** 的"每日免费收益"能力
> （`CLAIM_VIP_DAILY` · `VIP_FREE_CHEST` · `CLAIM_ONLINE_REWARD` · `CLAIM_IDLE_REWARD`）。
> 逐个查本地阶梯之后，**结论是这三个都不该现在预载**，理由分两类 —— 都不是"资料难找"。

---

## 一、`CLAIM_IDLE_REWARD`（CAP-B15）是**重名**：能力已存在且已 LIVE_VERIFIED

| 证据 | 内容 |
|---|---|
| `knowledge/skills/EXPLORATION_IDLE_CLAIM.json` | `status: VERIFIED`、conf 0.99；page `EXPLORATION`、state `CLAIMABLE`；识别面 `BTN_EXPLORATION_IDLE_CLAIM` / `POPUP_EXPLORATION_REWARD` / `STATUS_EXPLORATION_IDLE_CLAIMED`；判据"reward feedback visible + claim control becomes disabled" |
| `knowledge/game/exploration.json` | `gate: VERIFIED`，带**真机结果** `{idle_hours 9, steel 29000, hero_exp 80000, gear_items 3}`，`last_verified: 2026-09-05` |
| `knowledge/goals/capability_skill_map.json:690-695` | 该能力**已经**被记成 `"implemented_by": "EXPLORATION_IDLE_CLAIM"` / `"live_verified_by": "EXPLORATION_IDLE_CLAIM"` |
| 全仓库引用 | `CLAIM_IDLE_REWARD` **只出现在 `capability_catalog.json` 自己**（`code` 与 `description`），没有任何实现引用 |

⇒ 它是**总表里的一个游离 token**，不是能力缺口。目录行 `existing_skill` 空白是 **token join 没配上**，
不是"没有实现"。**按它预载 = 给一个已存在的能力造第二条记录**（违反 §十四"不允许重复真值"、
§八"不重复开发"）。

**处置**：**不预载**。（也**没有**手改那份生成的总表 —— 它是 `tools/build_capability_catalog.py`
生成的，2026-09-13/14 实测重建会产生 26k 行纯格式 diff，已回退过。）

## 二、`CLAIM_VIP_DAILY` 与 `VIP_FREE_CHEST`：**分不开，且先验明确说它没有验证**

这两个候选**共用同一条外部先验**（`VIP_FREE_CLAIM`，wosbot，`ADAPT_PATTERN`）、
**同一个未知字段**（`Preconditions`）、**同一个风险档**（T0）。在现有证据下**无法区分它们是两件事还是同一件事的两个 token**
—— 这正是第一节 CAP-B15 的形状。

⇒ **在能区分之前，把两条都预载会让同一件事被记两次。** 先别预载。

而那条先验自己的原文（`external_capability_map.json`）也已经把话说死了：

```
action      : tapInside(DAILY_CHEST_REWARDS (540,813)-(624,835), attempts=3, 300ms) then tapInside(VIP_POINT_REWARDS …)
verification: NONE for the claims — the taps are blind fixed-coordinate, repeated 3x.
              Only the menu opening is verified (template).
```

两条**must-not-import**：

1. **坐标**：`(430,48)-(530,85)` / `(540,813)-(624,835)` 是**别人的固定像素**。
   生产宪法**第二条**禁止任何形式的坐标硬编码（含"藏在配置文件里"），**第三条**要求坐标只由当前 UI 识别产生。
   ⇒ 这条先验里的 `navigation`/`action` **一个坐标都不能进 V2**，只能用它的**页级事实**
   （入口在 HOME、面板由 VIP 模板确认）。
2. **它的 verification 是空的**：原文承认那几下点击是**盲点固定坐标、重复 3 次**。
   ⇒ **不能**把这条先验当作"claim 已可验证"的依据。

另注：`knowledge/game/vip.json` 只有一行有效信息 ——
`purchase_policy: BLOCK`（"外部 bot 的自动购买行为不允许进入 V2"）。**免费领取可以，购买不允许。**

## 三、`CLAIM_ONLINE_REWARD`：与 `CLAIM_OFFLINE_REWARDS` **不是同一个东西**

token 命中的是 `CLAIM_OFFLINE_REWARDS` / `BTN_CLAIM_OFFLINE_REWARDS` ——
**online ≠ offline**，是两条不同的奖励。本 skill 的反模式清单明确禁止
"用 token 信袋匹配判定已有资产"（要求所有 token 出现在**同一个**文件名里）。
⇒ **不能**据此判它是重名，**也不能**据此判它已被覆盖。**本轮没有把它放进取或舍的任一边**，
只登记"需要一条独立证据才能定"。

## 四、本轮**没有**做的事（以及为什么不是偷懒）

- **没有预载任何一个**：第 1 个是重名；第 2、3 个是**在能区分之前预载就会造成重复计数**。
- **没有**把外部先验的坐标写进任何知识文件。
- **没有**手改 `capability_catalog.json`（生成物）。
- **没有**顺手把 `CLAIM_ONLINE_REWARD` 判成重名（token 命中不等于同一件事）。

## 五、这条留给下一个人的一句话

**"只缺一个字段"不等于"可以便宜地补上"。** 这四个候选真正的问题是
**总表 token 与项目自己的规范能力映射（`capability_skill_map.json`）没有对齐**，
而那是**目录侧**的问题 —— 补它的正确位置是那份映射或生成器，**不是**给每个 token 造一条预载记录。
