# 本轮交付概要 — 2026-09-15 11:xx GMT+8

## 一句话

修好**四个真实缺陷**（两个由真机确认、两个由像素级证伪 + 单测回放），
并让一个**项目史上从未执行过的功能**第一次在真机上跑起来。
本轮最重的一条不是"多修了什么"，而是**发现 verifier 曾在编造的身份上通过**。

| # | 缺陷 | 证据等级 | 收益 |
|---|---|---|---|
| 1 | 联盟首页被读成「宝箱页」 | **真机 12/12 verifier OK** | 84 个未领宝箱进入可领取路径（`OPEN_ALLIANCE_GIFTS` 首次执行） |
| 2 | 情报巨兽目标被路由到 `BEAST_HUNT` | 生产 episode 回放 + 单测 | 消除一个假 FAILURE，两个技能成功率不再被污染 |
| 3 | **运行时对同一帧算了两次决策** | **真机 A/B** | 消除假 FAILURE + 运行中止；揭露一个"报告完成却从未执行"的功能 |
| 4 | **出征页编造野兽身份** | 像素级证伪 + 全语料闸门 104/104 + 单测 | **verifier 不再在编造身份上通过**；身份改为从标题栏量测 |
| 5 | **体力不足被记成"战斗已开始"** | 真机帧 + 单测回放 | 消除一条"把拒绝记成成功"的虚报路径 |

---

## 一、`OPEN_STAMINA_SOURCES` 项目史上第一次执行（真机）

语料事实：1105 条 episode 里该技能出现 **0** 次；MAP 帧体力读数可读率只有 **71/336**；
而配置里 `claim_free_stamina: true`，备注写着"operator 要求必须领"。

真机 `run_live.py --goal INTEL --max-actions 4`（`2026-09-15T03:03:57Z`，
**4/4 verifier OK**，exit 0）：

```
step 3  OPEN_STAMINA_SOURCES  reason free_stamina_gift_not_yet_checked_this_run
        action TAP_SEMANTIC HUD_STAMINA_GAUGE
        before MAP  ->  after POPUP / GET_MORE_STAMINA
        verify True OK  {"before_page": "MAP", "after_popup": "GET_MORE_STAMINA"}
```

**诚实边界**：只证明了「面板会被打开」。当时 `free_claim_available=false`
（`丰盛的招待 +150` 的下次补给还有 56 分钟），所以大脑正确地做了 `BACK` ——
**真正的领取动作仍未在真机上验证过。**

---

## 二、出征页身份编造：四张"身份"模板其实是同一个控件的两份裁图

| 语义 | 父帧 | roi (y, h) | 在两张父帧上的距离 |
|---|---|---|---|
| `BTN_BEAST_DISPATCH_MUSK_OX_9` | `beast9_round3_march` | (0.912, 0.070) | 0 / 0 |
| `BTN_BEAST_DISPATCH` | `live_beast_march_selection` | (0.914, 0.070) | 0 / 0 |
| `STATUS_VICTORY_ASSURED_MUSK_OX_9` | `beast9_round3_march` | (0.450, 0.045) | 0 / 4 |
| `STATUS_VICTORY_ASSURED` | `live_beast_march_selection` | (0.455, 0.045) | 0 / 0 |

ROI 只差 0.002（在感知哈希分辨率之下）⇒ 四张模板互相替代，身份**由分支顺序决定**。
后果可测：`beast6_march.png` 是 `目标：北极狼`，被报成 **`麝牛 / level 9`** ——
而 `verify_beast_dispatch` 当时**正是要求这两个值** ⇒ **verifier 在编造身份上通过**。

**该页其实显示目标，在标题栏**（vision 从未读过）。全语料 104 张出征页：
98 张裸 `出征`（情报）、6 张 `目标：<名>`（麝牛×4 / 雪豹 / 北极狼），**104/104 全可读、零失败**。

修法：`vision.py` 不再编造 → `ocr.py::HybridVision` 读标题栏 → `verifier.py` 绑量测到的名字
→ `brain.py` 按 `target_kind` 路由。**野生路由要求正向证据**，其余走情报路由：
两个出征按钮是同一控件（点哪个都落），但把身份未量测的编队送给 `verify_beast_dispatch`
会把**正确动作记成 FAILURE** —— 这是刻意的不对称。

---

## 三、体力不足被记成"战斗已开始"（本轮真机发现）

真机 `03:03:57Z` step 1 判 **OK**，after 态却是 `POPUP/GET_MORE_STAMINA`
（体力 **9** < 标价 **10**，游戏**拒绝**了出征，战斗根本没开始）。
`verify_intel_hero_march_open` 的判据是"页面变了就算成功" ⇒ 拒绝**必然通过**。
已修：拒绝单独判定 + 独立 reason `INTEL_HERO_MARCH_REFUSED_FOR_STAMINA`
（按 `0n` 的原则，不同根因不共用 reason）。

---

## 四、需要操作者决策（未动代码）

`获取更多` 面板里有一行 `领主体力 / 使用后恢复10点 / [使用] / 库存 1,007`：
账上约 **1,007 × 10 ≈ 10,070** 体力道具，而当时体力只有 **9**。
该行**不是付费行**（付费行是 `购买并使用 💎300` / `超值月卡` / `礼包购买` / `英雄集结`），
但 `stamina_policy.note` 明确写着"only `BTN_CLAIM_FREE_STAMINA` is a target"。
⇒ 登记 `0al`，**等操作者表态，代码不得擅自扩权**。

---

## 五、验证与留档

| 项目 | 结果 |
|---|---|
| 全量测试 | **476 passed, 7 skipped, 0 failed**（exit 0，939s） |
| 目标测试（野兽族） | **73 passed, 1 skipped, 34 subtests**（exit 0） |
| `tools/check_wiring.py` | `problems: 0` |

**新增只读探针**：`tools/probe_beast_formation_identity.py`、`tools/probe_formation_title.py`、
`tools/probe_live_page.py`

**新增证据归档**
- `dataset/truth_audit/beast_formation_identity_20260915/`（7 帧 + 7 张标题裁图 + 语料闸门 + README）
- `dataset/truth_audit/stamina_check_live_20260915/`（4 帧 + 完整运行记录 + README）
- `dataset/truth_audit/one_decision_per_step_20260915/`、`beast_intel_target_routing_20260915/`、
  `alliance_gifts_chain_20260915/`

**新增/改写测试**：`test_beast_formation_identity.py`、`test_one_decision_per_step.py`、
`test_alliance_gifts_chain.py`（新）；`test_beast_verifier.py`、`test_beast_formation_page.py`、
`test_stamina_beast_runtime.py`、`test_intel_verifier.py`（改）

---

## 六、下一动作（按价值排序）

1. **`0ak` 真机重跑确认**：客户端停在英雄之旅营地面板（体力 < 10），
   `run_live.py --goal INTEL --max-actions 2`，第 1 步应记 `INTEL_HERO_MARCH_REFUSED_FOR_STAMINA`。
2. **主动体力门（`0ak` 根因级修法）**：动手前比较 `stamina.current` 与 `stamina_cost_displayed`，
   不足就 `SAFE_STOP`。本轮那次运行 **4 个动作里有 2 个是 `BACK`**，纯粹因为体力不足。
3. **`CLAIM_FREE_STAMINA` 真机验证**：等 `丰盛的招待` 补给到期（本轮帧显示 `00:56:02`）。
4. **`0al` 等操作者决策**。
5. 设计受阻的技能（AUTO 块 `DESIGN-BLOCKED`）：**先拿真机帧再设计语义**，不要照草稿硬写。
6. **72h Soak 仍未开始。**
