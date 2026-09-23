# 关闭弹窗这块：一个坐标被当成"任何 POPUP 都适用"，以及 X 会动这件事

2026-09-23。issue #109。两份诊断 + 一处修复 + 一处能力恢复，全部可离线复算。

## 现场：每 63 秒死一轮，连死 8 轮以上

`09-23T05:23:10Z..05:51:42Z`，**82 次** `CLOSE_POPUP` 以 `POPUP_CLOSE_NOT_PROVEN` 结束，
`learning/executor_backend.jsonl` 里每一次的 `tap_point` 都是 **`[635, 456]`**，一次都没变。

逐帧看（`tools/frame_owner.py` 的口径：帧 ↔ 记录按**路径**配对）：

| | 值 |
|---|---|
| 帧上是什么 | 加成总览（`POPUP|POWER_OVERVIEW`）面板，顶部蓝条右端有一个 X |
| X 在哪 | 实测 **(666, 157)** ≈ norm (0.925, 0.123) |
| 点在哪 | **(635, 456)** —— 面板**中部**，落在它自己的数字列上 |
| 点完之后 | 后帧与 before 帧同一屏（`after_popup` 仍是 `POWER_OVERVIEW`） |

（`review_*.png` 是把两个点画在帧上的复核图，红圈=实际点的位置。）

## 根因：`POPUP` 不是"一个页面"，是一整类叠层；而台账按页面大类存坐标

`LiveRuntime._resolve_semantic_target` 的链条是：模板 → `_client_printed_control` → **
`_remembered_control_center`** → 字典提示。实测：

* 今天用生产 `find('BTN_CLOSE')` 跑这些帧 → **None**（四个 phash 记录全部超阈值：d=28/34/40/34，阈值 8）
  ⇒ 落点**不是模板**给的；
* 台账 `learning/control_experience.json` 里 `POPUP|BTN_CLOSE`：
  `position_norm=[0.8819444444444444, 0.35625]` → ×(720,1280) = **(635, 456)**，`attempts=97`，
  `known_change=NUMBER_CHANGED`
  ⇒ **落点是台账给的**。

那个 0.8819/0.3563 是**退出确认**弹窗的 X。看四个注册各自的父帧读出来是哪一屏
（`tools/probe_close_popup_target.py --survey`，用生产视觉读父帧）：

```
btn_close__purchase_popup_current__0   roi_center=[612,131]  parent reads as None（父帧已不在盘上）
btn_close__live_current__0             roi_center=[613,148]  parent reads as POPUP|PURCHASE_POPUP
btn_close__step_001_before__1          roi_center=[635,456]  parent reads as POPUP|EXIT_CONFIRM   ← 赢的那条
btn_close__alliance_chest_layer__0     roi_center=[682,38]   parent reads as ALLIANCE
```

而 `_remembered_control_center` 的键是 `control_key(page, semantic)` = **`POPUP|BTN_CLOSE`**。
语料实测，`POPUP` 底下有 **22 种**不同叠层，**2717/2717 条 POPUP 读数都带着是哪一种**，而台账把这
个字段整个丢掉了：

```
289 GET_MORE_STAMINA   281 GENERIC_REWARD   218 POWER_OVERVIEW   129 POWER_DETAILS
111 INTEL_MASTER_BOUNTY 110 INTEL_BEAST_MISSION  96 INTEL_REWARD  77 INTEL_HERO_JOURNEY
 57 EXIT_CONFIRM        45 HERO_BATTLE_VICTORY  17 INTEL_RESCUE…  16 REAL_MONEY_OFFER  …
```

⇒ 在**退出确认**弹窗上学到的 X 坐标，被交给了**加成总览**。这不是"阈值没调好"，是
"一个坐标是关于**一屏**的断言，而键里没有那一屏"。同一族里还有 `ALLIANCE`（section 342/233/11）、
`TRAINING`（营别 58/52/39）、`MAP`（53）。全部 13883 条读数里 **3507 条（25%）** 的屏身份被丢掉。

## 修法一：台账按"屏"存，而不是按页面大类

* `control_experience.control_key(page, control, screen="")` —— `screen` 是
  `state_signature`，**只有它比页面窄时才用它**：`POPUP|POWER_OVERVIEW|BTN_CLOSE`，而不是
  `POPUP|BTN_CLOSE`。页面自己就能描述屏幕时（HOME/MAP/…，57 条位置里的 49 条）**键一字节不变**。
* `ControlExperience.screen` —— 位置测在哪一屏上，**与 `position_norm` 在同一处写入**，两者不会走散。
* `control_experience.reusable_on_this_screen(entry, screen)` —— 第二道：键与记录的屏不一致时拒绝。
  主力是键（不同弹窗压根查不到），这道守门是防两者走散。
* 运行时三处调用点同步（写入、`ORDINARY_CONTROL` 去重查找、`_remembered_control_center`）。

**结果**：加成总览问的是 `POPUP|POWER_OVERVIEW|BTN_CLOSE`，台账里**没有这一条**（运行时随后
自己建了一条，`attempts=0`、无位置），于是**不再点 (635,456)**，改为诚实的
`SEMANTIC_TARGET_NOT_VERIFIED`——操作者那条"不得把旧截图的点击坐标直接用于变化后的页面"。

## 修法二：X 会动，所以要**找**它，不是假设它在原位

上面那一步只让失败变诚实，弹窗**仍然关不掉**。语料里的 X 逐屏不同（用已复核的 X 模板 + 生产
`match_ccoeff` 全帧搜，score→distance = `round((1-score)*64)`）：

```
EXIT_CONFIRM 0.8819/0.3559   POWER_OVERVIEW 0.9236/0.1301   GET_MORE_STAMINA 0.9236/0.1129
POWER_DETAILS 0.9208/0.2277  WELCOME_BACK_OFFLINE 0.9194/0.2027  EXPLORATION_IDLE_DIALOG 0.8722/0.2379
```

这正是 `matchers.py` 存在的理由（"A ROI that is both 'where it is' and 'where to look' cannot
express that"）。于是给 `BTN_CLOSE` 加**一条** `ccoeff` + `search_band` 记录，复用**已有已复核**的
X 模板，band 由实测中心反推（x 0.80..1.00, y 0.07..0.43）。

**分离度（`tools/register_close_popup_band.py` 每次重算，不达标就拒绝写入）**：

```
画出 X 的: 8 帧，distance = [0, 0, 0, 0, 0, 1, 1, 1]        （最大 1）
没有 X 的: 10 帧，distance = [23, 27, 27, 27, 27, 29, 29, 30, 32, 35]（最小 23）
⇒ 阈值 8 落在空隙正中
```

阈值**没有动**：生产经 `SemanticWorldVision` 的默认 8，实测空隙 1..23，所以不需要新增
`semantic_max_distance` 条目，也不需要改任何默认值。

**解析结果**（`find('BTN_CLOSE')`）：

```
POWER_OVERVIEW   -> (0.9236, 0.1301)  d=1     ← 从"点面板中部"变成"点那个 X"
EXIT_CONFIRM     -> (0.8819, 0.3559)  d=0     ← 原位，没被弄坏
GET_MORE_STAMINA -> (0.9236, 0.1129)  d=1
GENERIC_REWARD   -> None                      ← 该帧 band 里确实没有 X
HOME / MAP       -> None                      ← 无误触发（非弹窗页实测 d=24..45）
```

## 回归

| 对照 | 基线 | 本树 |
|---|---|---|
| 9 个台账/调度文件（同一运行器，`learning/_ab_screen_key_plugin.py` 把键退回页面大类） | 15 failed / 212 passed | **8 failed / 219 passed** |
| 其中**新增失败** | — | **0** |
| 基线多出的 7 条 | 就是本轮新写的测试（无修时按设计失败 ⇒ 它们真的在测这个修复） | — |
| `BTN_CLOSE` 相关 11 文件 | — | 2 failed，与**摘掉新记录**时逐条相同（`AB_CLOSE_BAND=off`） |
| `tools/check_wiring.py` | 9 项 | 9 项，逐条相同 |

剩 8 条：`test_refusal_yields_the_cycle.py` 2 条 + `test_live_runtime.py` 6 条，两侧都有。

## 还没做 / 不知道的

* **05:54:23 的那次切换不是本轮的功劳**：失败类型从 `POPUP_CLOSE_NOT_PROVEN`（有点击）变成
  `SEMANTIC_TARGET_NOT_VERIFIED`（无点击）发生在 `05:54:23`，而本轮第一处编辑落盘在 `05:57:44`。
  台账条目现在仍在（`attempts=97`、`resolved`），按修复前的代码本应仍然给出那个点，所以这条
  **成因未定**，不认领。
* **弹窗是否真被关掉，要真机**：本轮只证到"解析给出的点是那个 X"。库里最新几帧仍是
  `SEMANTIC_TARGET_NOT_VERIFIED`（当时跑的是工作树里的半成品），下一轮真机应能看到
  `CLOSE_POPUP` 成功、后帧不再是 `POPUP`。
* 另外 21 种弹窗的同族问题：`POPUP|*` 下还有 7 条其它控件的位置（`BTN_OPEN_POWER_DETAILS`、
  `BTN_DISMISS_INTEL_REWARD`、`BTN_INTEL_VIEW_TARGET`…），它们的键本轮一并变窄了，但没有各自的
  band 记录——修法一让它们不再跨屏误用，修法二只补了 `BTN_CLOSE`。

## 复算

```bash
VENV=E:/无尽冬日智能体/.venv/Scripts/python.exe
$VENV tools/probe_close_popup_target.py --survey        # 四个注册各属哪一屏 + band 分离度 → survey.json
$VENV tools/probe_close_popup_target.py --limit 10 --band-search   # 逐帧：赢家/距离/落点 → probe.json
$VENV tools/register_close_popup_band.py --dry-run      # 重算分离度并给出判词（不写盘）
AB_SCREEN_KEY=page PYTHONPATH=learning $VENV -m pytest tests/test_control_experience.py \
    tests/test_remembered_control.py tests/test_live_runtime.py -q -p _ab_screen_key_plugin
AB_CLOSE_BAND=off PYTHONPATH=learning $VENV -m pytest tests/test_march_recall_and_stamina.py \
    -q -p _ab_screen_key_plugin
```
