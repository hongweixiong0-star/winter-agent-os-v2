# 有界搜索停止规则：一个只"扫"不"找"的 hop

**记录于 2026-09-18。** 触发案例：升级
`SPEND_STAMINA_ON_BEAST|NO_GOAL_PROGRESS|SCAN_MAP_FOR_BEAST`
（goal `AVOID_STAMINA_WASTE`，condition `REPEATED_LIVE_FAILURE`，第二种失败形状）。

证据集：`dataset/truth_audit/beast_scan_pan_20260918/key/`（`finding.json` 是入口）。

## 症状形状

> 每一步都过了自己的 verifier，路线在跑，但 goal 自己的 meter 一步都没动。

这和 `VERIFIER_SHAPE_MISMATCH.md` 是**同一族**：verifier 证明的是「动作发生了」，
而不是「目标接近了」。区别在于本例里 verifier 没有说谎 —— 动作真的发生了 ——
问题在下游：**这个动作本身不可能把目标带过来。**

## 本案事实（都可复核）

| 事实 | 出处 |
|---|---|
| 536 条 `AVOID_STAMINA_WASTE` episode，其中 336 条是 `SCAN_MAP_FOR_BEAST`；记录 `goal_progress` 的 9 条里 9 条 false、0 条 true | `learning/episodes.jsonl` |
| `verify_beast_scan_observed` 只要求前后都还是"可读的 MAP 页" | `winter_agent_v2/verifier.py:732` |
| 扫描预算每轮 3 次，用完就 `SAFE_STOP verified_beast_target_not_visible` | `winter_agent_v2/brain.py:53,857-860` |
| 客户端表里唯一 `dispatchable=true` 的目标是 `MUSK_OX_9` | `knowledge/game/beasts.json` |
| 客户端**自带**的野兽搜索（世界地图 `搜索` 面板的野兽系页签）在 2026-09-06 已被人肉验证过：等级 5 → 镜头飞到 `等级5 猛犸象` | `dataset/raw/beast_search_exploration/beast5_found.png` |
| 那套模板至今是 CANDIDATE，且 `winter_agent_v2/`、`tools/`、`tests/`、生产 manifest 里**零引用** | `dataset/candidate/beast_search_v2_manifest.json` |

## 本轮被证伪的假设（重要，别改回去）

假设："`SCAN_MAP_FOR_BEAST` 的 swipe 是空操作，镜头根本没动，所以永远看不见目标。"

**证伪**：用生产 Executor 在真机上跑了 3 次，ADB 600 ms 与 1500 ms 都**真的平移了视野**
（`live_probe_side_by_side.png`；生产 episode 帧同样如此，`prod_run_side_by_side.png`）。
工具：`tools/probe_beast_scan_pan.py`。

⚠ **代价记录**：先用手写的"全局平均差最小位移"搜索量生产帧，得到 `(dy=0, dx=0)`
并差一点当成根因。世界地图是**透视渲染**，平移在不同屏幕位置不是同一个位移，
纯平移模型在那里会给出退化的极小值。**帧本身一看就否掉了它。**
教训：**几何测量在地图/3D 场景上不可信时，先看图，再下结论。**

## 规则（希望被下一个账号遵守）

1. **"找不到就扫一扫"的 hop 必须写出收敛条件**：扫到哪里为止、相机被留在哪里、
   下一轮从哪继续。若每轮的预算都从同一个起点重来，它就不是搜索，是抖动。
2. **verifier 要证明的是目标，不是动作的合法性**：`still on a readable MAP` 这种
   条件对"扫"和"找到了"是同一个值，就不能单独用来判定这个 capability 成功。
3. **客户端已经提供的导航（搜索/前往）优先于自家手势摸索**：本例里客户端能把镜头
   直接飞到野兽身上，而我们花了一整个 round 在盲扫。
4. 上报这类失败时，**"哪一半没做完"必须写出来**，不要用"路由已就绪"糊过去。

## 本案仍然未完成的（不要读成已修复）

- `SPEND_STAMINA_ON_BEAST` 没有取得任何 live episode；
- 野兽搜索这条 hop 没有接线（无 skill / 无 verifier / 无 brain 路由 / 无真机验证）；
- 没有做任何 lifecycle 变更，也没有提升任何能力状态。
