# 出征按钮「花费变红」= 客户端拒绝付款，不是模板失效

**结论一句话**：那 4 条 `DISPATCH_INTEL_BEAST` 的 `SEMANTIC_TARGET_NOT_VERIFIED`
**不是「控件找不到」**。出征按钮一直在屏幕上；是**客户端把花费的 `10` 画成了红色**
（体力不足），红色数字叠在模板里那个白色数字上，把 ROI 的 pHash 推离模板 26 位
（阈值 8），于是解析器返回 `None`。

## 定量证据（全部来自 `learning/episodes.jsonl` 里的真实真机帧）

| 组 | n | pHash 距离 | 强红像素 | `unaffordable_cost_pixels` | 客户端含义 |
|---|---:|---:|---:|---|---|
| 成功 | 25 | **0**（25/25 全等） | **0**（25/25 全等） | `False` | 付得起 |
| 失败 | 4 | **26**（4/4 全等） | **452**（4/4 全等） | `True` | 付不起 |

- 模板：`dataset/candidate/templates/btn_beast_dispatch__live_beast_march_selection__2.png`
- ROI：`{x 0.56, y 0.914, w 0.405, h 0.07}`（取自 manifest 记录，未另写字面量）
- 阈值：`SemanticWorldVision` 默认 8
- 25 与 4 两组**各自内部完全一致**（0 / 26），所以这不是动画抖动或阈值临界，
  而是两种确定的不同画面。

红色像素的 **+415** 就是那个被改画成红色的数字：模板自身与 25 张成功帧都恰好
**102** 个强红像素（花费图标本身），4 张失败帧都是 **517**。

`unaffordable_cost_pixels()` 是最早就有的能力（`0av` 为营地面板写的，
见 `tests/test_cost_colour_verdict.py`），本目录**没有新增任何颜色判别代码**：
它在这 29 帧上给出的判决正好是 25×`False` / 4×`True`，零错分。

## 文件

- `01..04_unaffordable_*.png` —— **全部 4 张**记录的失败帧（唯一一批报
  `SEMANTIC_TARGET_NOT_VERIFIED` 的出征记录）
- `05..06_affordable_*.png` —— 最近 2 张成功帧
- `live_ab_records.json` —— 上述记录的结构化条目 + 测量值 + 出处

帧是从 `dataset/raw` **复制**过来的：`dataset/raw` 不进 git（机器本地），
而这些帧是测试的输入，必须随仓库走。

## 修复（本轮）

1. `ocr.HybridVision.observe`：在 `Page.MARCH` 上读出征控件的花费颜色，
   写入 `stamina.cost_affordable` / `cost_verdict_source = DISPATCH_COST_COLOUR`。
   （页面级证据；不覆盖营地面板自己的 `BUTTON_COST_COLOUR`。）
2. `brain.RuleBrain`：`MARCH` 页上 `cost_affordable is False` ⇒ `SAFE_STOP`
   `dispatch_unaffordable_for_stamina`，**不再产生那条误导性的 `SEMANTIC_TARGET_NOT_VERIFIED`**。

`is False` 是必须的写法：`None` 表示**没量到**，绝不能当成「红色」而拦下一个本来付得起的出征。

## 边界（不要读成比这更多）

- **真机只验证了「付得起」这一侧**：运行当下体力 ≫ 10，所以花费是白色，闸门不触发、
  出征照常 —— 这条回归路径有真机证据。**「红色 ⇒ 真的停下」只有回放证据**
  （4 张真实客户端帧 + 单测），**没有**真机触发过，因为要触发得先把体力花到 < 10。
- 红色变体**故意没有**加进模板：那只会让 agent 去点一个客户端已判定付不起的按钮，
  与 `0av` 的结论直接冲突。
- 拒绝时选择 `SAFE_STOP` 而不是绕路去取体力：免费体力路线跑在**世界地图**上
  （`0au`/`0e`），而从编队页按返回会去哪**没有测量过**，因此不发明未验证的导航。
- **`小队设置` 页（绿色「战斗」按钮）不受本闸门保护**：那是另一个控件，
  本 ROI 没有在它上面测过，所以闸门刻意放在该分支之后。
