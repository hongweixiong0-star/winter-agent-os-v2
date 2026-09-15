# 免费体力检查首次执行 + 体力不足被记成成功（2026-09-15）

一次 `run_live.py --goal INTEL --max-actions 4`（真机，`2026-09-15T03:03:57Z`–`03:04:42Z`，
`stop_reason=MAX_ACTIONS_REACHED`，exit 0，**4/4 verifier OK**）同时产出了两条结论。

## 结论 1：`OPEN_STAMINA_SOURCES` 终于真的执行了（项目史上第一次）

`0i` 的根因是运行时对同一帧算了**两次**决策：第一次把 `stamina_panel_checked` 置 True 并返回
`OPEN_STAMINA_SOURCES`，第二次（被执行的）返回别的技能 —— 于是免费体力面板**从未被打开**，
而大脑已经把"本轮已检查"标成 True。修复后本轮实测：

```
step 3  OPEN_STAMINA_SOURCES  reason free_stamina_gift_not_yet_checked_this_run
        action TAP_SEMANTIC HUD_STAMINA_GAUGE   backend ADB
        before MAP  ->  after POPUP / GET_MORE_STAMINA
        verify True OK  {"before_page": "MAP", "after_popup": "GET_MORE_STAMINA"}
```

语料佐证：`learning/episodes.jsonl` 的 **1105 条** episode 里 `OPEN_STAMINA_SOURCES` 出现次数为
**0**；而 MAP 帧的体力读数可读率只有 **71/336**（`state_before.stamina.current` 非空）。

**诚实边界**：本次**只证明了"面板会被打开"**。面板打开时
`stamina.free_claim_available = false`（见 `02_...png`：`丰盛的招待 +150` 显示
`下次补给 00:56:02`，即补给还没到期），所以大脑随后正确地做了
`BACK / stamina_panel_without_a_free_gift`。**真正的领取动作仍未在真机上验证过。**

## 结论 2（新缺陷，已修）：体力不足被记成"战斗已开始"

同一次运行的 step 1 被判 **OK**，而它的 after 态是 `POPUP / GET_MORE_STAMINA`：

```
step 1  INTEL_HERO_START_MARCH  reason intel_hero_camp_panel  action BTN_HERO_CAMP_FIGHT
        before EXPLORATION (探险 💧10)  ->  after POPUP / GET_MORE_STAMINA
        verify True OK  {"camp_panel": true, "left_panel": true, "after_page": "POPUP"}
```

当时体力是 **9**，而面板标价 **10** —— 游戏**拒绝**了这次出征并弹出"获取更多"。
战斗根本没开始，却被记为成功。

根因：`verify_intel_hero_march_open` 的判据是
`before_ok and (after.page is not before.page)`，即"页面变了就算成功"。
`GET_MORE_STAMINA` 面板同样替换了营地面板，所以它**必然**通过。
文档里写的"a result popup"指的是战斗结果弹窗，不是"资源不足"弹窗。

已修：`GET_MORE_STAMINA` 单独判为拒绝，并使用**不同的 reason**
（`INTEL_HERO_MARCH_REFUSED_FOR_STAMINA`），与 `INTEL_HERO_MARCH_NOT_OPEN` 区分开 ——
按 `0n` 的原则，不同根因不得共用同一个 reason。证据字段新增 `refused_for_stamina`。

**证据等级：真机帧 + 单测回放（`tests/test_intel_verifier.py::
test_a_stamina_refusal_is_never_recorded_as_a_started_fight`），尚未做修复后的真机重跑。**

## 结论 3（需要操作者决策，未动代码）：面板里有一行"使用自有体力道具"

`02_...png` 里除了 `丰盛的招待`（免费但未到期）之外，还有一行：

```
领主体力   使用后恢复10点领主体力        [ 使用 ]     库存 1,007
```

即账上持有 **1,007 个 +10 体力道具**（合计约 10,070 体力），而当前体力只有 9。
该行**不是付费行**（付费行是 `购买并使用 💎300` / `超值月卡` / `礼包购买` / `英雄集结`），
但 `config/v2.json` 的 `stamina_policy.note` 明确写着"only `BTN_CLAIM_FREE_STAMINA` is a target"。

⇒ **这属于操作者策略决策，不是代码缺陷。** 在操作者明确之前，代码不得去点它。

## 文件

| 文件 | 内容 |
|---|---|
| `01_hero_camp_panel_before_live.png` | step 1 before：英雄之旅营地面板（探险 💧10） |
| `02_stamina_refusal_popup_after_live.png` | step 1 after：`获取更多` 面板，体力 9/200（拒绝证据） |
| `03_map_before_free_stamina_check_live.png` | step 3 before：世界地图（MAP_HUD 体力读数 = 9） |
| `04_stamina_panel_opened_live.png` | step 3 after：免费体力面板被打开（结论 1 的证据） |
| `live_run_records.json` | 该次运行 4 步的完整记录（含 before/after/verifier evidence） |

复现：

```
cd "E:/无尽冬日智能体" && "E:/dongri-mumu-bot/.venv/Scripts/python.exe" -u \
  tools/run_live.py --goal INTEL --max-actions 4
```
