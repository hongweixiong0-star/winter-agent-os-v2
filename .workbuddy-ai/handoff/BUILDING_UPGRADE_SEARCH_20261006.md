# 搜索产物 — KEEP_BUILDING_PRODUCTIVE 为何 0→1 卡住（2026-10-06）

> 按 `docs/DEVELOPMENT_FLOW.md` §一/§五 的硬门格式产出。**本文件的核心价值是：
> 一次搜索 + 一次代码核对，证伪了我自己最初的假设，并指出真正的拦路点。**

```
=== 搜索产物 ===
任务/问题：KEEP_BUILDING_PRODUCTIVE 是 START_BUILD 0 attempts / stable 0%，
        要搞清建筑升级为什么一次都没真正发生。

搜索关键词：
  - 无尽冬日 建筑升级 需要条件 大熔炉等级 城墙 升级效果 消耗资源

搜索结果（来源：无尽冬日百科 wjdrgl.centurygames.cn/?p=6855 城墙条目）：
  该页给出城墙逐级表：等级 / 前提条件 / 建造花费 / 施工时间 / 建筑实力。
  Lv.8  前提 大熔炉 Lv.27  花费 37M 37M 7.4M 1.8M  时间 3d 00:55:00  实力 217.320
  Lv.9  前提 大熔炉 Lv.29  花费 61M 61M 12M  3M     时间 4d 00:26:00  实力 267.920

  与真机帧 OCR 逐项对照（dataset/truth_audit/building_upgrade_sheet_20261005）：
    前提条件  百科「大熔炉 Lv.29」     真机「需要条件 大熔炉等级29」       一致
    施工时间  百科「4d 00:26:00」      真机「原始时间：4天00:26:00」       完全一致
    建筑实力  百科 Lv.8=217.320       真机「实力 217,320+50,600」         一致
              Lv.9=267.920            267920-217320 = 50,600            算术吻合
  结论：真机帧就是**城墙升 9 级**的面板，且百科与客户端同版本。

假设（基于搜索，我认为应该怎么做）：
  升级面板标题「城墙」读得出、`BUILDING_IDS` 里没有它 → `id` 停在 UNKNOWN →
  「身份未知 → 授权门拒绝 → START_BUILD 0 attempts」。所以要补表：把城墙加进 BUILDING_IDS。

不确定性：
  1. 授权门到底要求 id 还是 name？（若只要 name，补表就不是必要条件）
  2. 「城墙不在表里」是有意的还是遗漏？
  3. 就算身份解决，花费/前置条件是否还需要单独读取？
=== 结束 ===
```

## 核对代码后的结论：**假设 1 与 2 都错了**

### ① 授权门**已经接受"name 就够"**（`brain.py:2470-2483`）

```python
_identity_known = bool(str(_building.get("name") or "").strip()) or _named_id not in {
    "", "UNKNOWN", "NONE",
}
if not _identity_known:
    return Decision("SAFE_STOP", "building_upgrade_needs_a_known_identity", ...)
return Decision("BUILDING_UPGRADE", "building_prerequisites_satisfied", ...)
```

真机 episode 的 before 状态是 `{"id": "UNKNOWN", "name": "城墙", "level": 8, "target_level": 9}`
（`identity_confidence: 0.9983`，`identity_source: FLOATING_LABEL_OCR+QUEST_BANNER`）——
`name = "城墙"` 非空 → **`_identity_known = True`** → **门是通过的**。
`brain.py:2465-2469` 的注释就写着这是刻意的："`name` alone is enough: a floating label read
（`26 仓库`）names the building even when the catalogue lookup did not."

### ② 「城墙不在表里」是**刻意的设计**，不是遗漏

`ocr.py:1831-1835` 原文：

> The title is deliberately *not* part of this test: the layout proves the sheet, and which
> building it belongs to stays a separate exact-table lookup (`building_identity.BUILDING_IDS`)
> that **returns UNKNOWN rather than a guess for an unlisted name such as 城墙**. This proves
> navigation only -- it never sets `upgradeable` and never authorizes spending.

**所以补表会推翻一个刻意的决定，而且它不是拦路点。我没有改。**
（若将来确实要补，表里的既有条目分两类："Live: …" 与 "Operator-supplied, NOT yet observed"；
城墙属于前者——我有真机帧 + 百科同版本的算术吻合，所以补它是**有据**而非猜测。
但那是一个独立决定，不该混在"排查 0 attempts"里做。）

### ③ 真正的拦路点，前一版代码自己记着（`brain.py:2460-2463`）

> It has never actually spent: ``BUILDING_UPGRADE`` has **0 rows in the ledger**, because that
> state only arises from a *failed* ``OPEN_BUILDING_UPGRADE`` **and the session ends before the
> brain is asked again**. That is an accident of ordering, not a guard, and it is exactly the
> kind of accident this project does not leave standing.

—— 该状态**只从失败的 `OPEN_BUILDING_UPGRADE` 产生**，而会话在"再问一次"之前就结束了。
**这是顺序问题，不是守卫。**

## 与上一轮修复的关系（这条最要紧）

2026-10-06 我修掉了 `OPEN_BUILDING_UPGRADE` 的接线缺口（提交 `b883d1fe`）：
`upgrade_dialog_visible` 现在能到达"模板层成功"的那条路，检测器在该帧上返回 `True`。
**也就是说：那个"只能从失败中产生的状态"，其触发条件已经被改变了。**

**因此下一步不是改代码，是验证**：跑一段真实 AUTO，看账本里是否出现
`BUILDING_UPGRADE_PANEL_OPENED`（导航被确认）以及 `BUILDING_UPGRADE` 是否终于产生第一行。

## 真机观察（§三 观察）

用 `tools/explore_step.py --observe` 两次（证据在 `learning/exploration_log.jsonl`）：

- `20261005T165434` — 读到城市 HUD：`城墙`、`将城墙升到9级`、`(8/9)`、`探险/英雄/背包/商店/联盟/野外`
- `20261005T165909` — 仍是 HOME，任务条 `将城墙升到9级（8/9）`

**升级面板当前没有开着**：它只是城市视图上的任务条，不是面板。
要观察面板必须点一下（导航，不花钱——`_current_upgrade_sheet_layout` 的注释明确"
never authorizes spending"），但**点"升级"会花 61M/61M/12M/3M 并占用 4 天队列**，
所以本轮**没有**去点，只做了只读观察。

## 不确定性（仍未搞清）

1. `OPEN_BUILDING_UPGRADE` 现在成功之后，流程走到哪里？**需要真实 AUTO 一段才能看到。**
2. 即使 `BUILDING_UPGRADE` 被提出，`queue_building` 是否读得到？
   `verify_building_upgrade` 的 `target_ok` 在 `id=UNKNOWN` 时是
   `("UNKNOWN" == "UNKNOWN") and (queue_building == "UNKNOWN")` ——
   **这是一个恒真式的弱证明**，值得单独审：它可能把"某个建筑进队列"记成"这个建筑进队列"。
   这与"身份要有名"的整条设计方向相反，属于**需要单独一轮**的问题。
3. 花费（`10.42亿/5551万` 这类 have/need 对）有没有读取器？我没查到；
   若有，它是升级前更该看的一层。
