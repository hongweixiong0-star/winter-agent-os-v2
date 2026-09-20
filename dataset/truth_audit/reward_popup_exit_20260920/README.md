# 「获得奖励」弹窗：落点与信号证据，含对 #64 的更正（2026-09-20）

对应 `04_OPEN_ISSUES.md` **#64**。本目录回答三个问题：
**这张弹窗靠什么被认出来、先前为什么点不中、以及点击之后还会遇到什么。**

> **更正声明**：#64 正文与补充里写的"`POPUP_GENERIC_REWARD_HEADER`（横幅）点了无效 / 点它并不能退出"
> —— **被本目录的第一手帧推翻**。横幅**不是**无效按钮：2026-09-20 13:09:49 那一步它**确实关掉了**
> 「获得奖励」（证据帧 `03_`）。真正的主因是**两个信号之间的距离差**，见第二节。
> 这个更正必须与代码里的注释、测试 docstring 一起改，否则记录里会留下一个我自己已经证伪的说法。

## 一、证据帧

| 文件 | 来源 | 说明 |
|---|---|---|
| `key/01_shared_reward_popup_step_001_before_20260920T124146.png` | `runtime_auto/20260920_204143_843357/…_step_001_before_…png` | 患者帧（720x1280）：横幅「获得奖励」+ 三格奖励 + 页脚「点击任意位置退出」。20:41 那一轮 `current_goal=AUTO_DISCOVERY` 停在 `generic_reward_without_goal_context` 就是它。 |
| `key/02_banner_18_footer_2_tap_could_not_resolve_20260919T052809.png` | `runtime_auto/20260919_132726_620764/…_step_004_before_…png` | 历史失败帧：横幅 **18**（门 16，NO MATCH）、页脚 **2**（门 8，MATCH）。这一步的 `failure_type = SEMANTIC_TARGET_NOT_VERIFIED`。 |
| `key/03_second_dialog_searchlight_upgrade_20260920T131016.png` | `runtime_auto/20260920_210417_958773/…_step_021_after_refresh_2_…png` | 13:10:26 失败步的 after 帧：点完横幅后**「获得奖励」已经不在了**，出现的是**第二个**弹窗「探照灯升级」（页脚写「点击任意位置**继续**」）。横幅 26 / 页脚 22，两者都在门外 ⇒ `observe` 报 `UNKNOWN`。 |
| `key/04_banner_was_tapped_popup_still_there_20260920T125159.png` | `runtime_auto/20260920_205148_722868/…_step_001_after_refresh_2_…png` | 12:52:01 那一步的 after 帧：横幅那一刻**解析成功**（before 帧 16 = 门）并且真的点了，**+8s 后弹窗仍在**（用户界面还在页脚「点击任意位置退出」）。 |
| `key/05_footer_target_after_intel_page_restored_20260920T131303.png` | `runtime_auto/20260920_211101_334048/…_step_009_after_…png` | 新目标的真机结果：`DISMISS_INTEL_GENERIC_REWARD` 改点页脚后，after = **INTEL**（conf 0.98），verifier **OK**。 |

放进 `key/` 并按 `.gitignore` 白名单发布，理由同 `march_formation_20260918`：这些数字读者要能自己复算，
而它们来自会被 retention 清理的运行目录。**复制到本目录也是为了不让测试依赖运行帧**（#46）。

## 二、主因：识别用的是"横幅 **或** 页脚"，点击用的**只有横幅**

`vision.py` 判这张弹窗的代码是 `if match("POPUP_GENERIC_REWARD_HEADER") or match("BTN_DISMISS_INTEL_REWARD")`
—— 两个信号**任一**命中就报 `POPUP/GENERIC_REWARD`，然后由 goal 上下文挑解除技能。
而五个 `DISMISS_*_GENERIC_REWARD` 的动作目标**只有横幅**。

两个信号在这张弹窗上的稳定度差一个量级（`dataset/candidate/template_manifest.json` 的 ROI × 项目自身 `phash/hamming`）：

| 帧 | 横幅（门 16） | 页脚（门 8） | `observe()` |
|---|---:|---:|---|
| 01（20:41 患者） | 16 | **2** | POPUP/GENERIC_REWARD |
| 02（2026-09-19 失败步） | 18 ✗ | **2** | POPUP/GENERIC_REWARD |
| 03（13:10 after） | 26 ✗ | 22 ✗ | **UNKNOWN**（第二个弹窗） |
| 04-a（12:52 before） | 16 | **2** | POPUP/GENERIC_REWARD |
| 04-b（12:52 after） | 20 ✗ | **2** | POPUP/GENERIC_REWARD |
| 05-a（13:13 before） | 14 | **0** | POPUP/GENERIC_REWARD |

⇒ **横幅 14/16/18/20 骑着它自己的容差跑**（按 #54 的判据，跨帧距离应当落在阈值空档内而不是擦边）；
**页脚 0~2，离门 8 有 4 倍余量**。于是出现一个纯粹由接线造成的失效：

> 页脚命中 ⇒ 弹窗被认出来 ⇒ 大脑选中解除技能 ⇒ 执行器去解析**横幅** ⇒ 横幅在门外 ⇒
> `SEMANTIC_TARGET_NOT_VERIFIED` ⇒ **一次点击都没发出去**。

`learning/episodes.jsonl` 全史统计，按**动作目标**分组（`DISMISS_*_GENERIC_REWARD` 全部）：

| 目标 | SUCCESS | FAILURE | 失败中 `SEMANTIC_TARGET_NOT_VERIFIED` |
|---|---:|---:|---:|
| `POPUP_GENERIC_REWARD_HEADER`（旧） | 68 | 51 | **45**（39 MAIL + 4 INTEL + 2 DAILY） |
| `BTN_DISMISS_INTEL_REWARD`（新） | **7** | **0** | 0 |

⇒ 旧目标 51 次失败里 **45 次是"点都没点出去"**，不是"点了没用"。这正是 #64 归因错的地方。

## 三、点击之后还会遇到什么（**未修**）

13:10:26 那一步的画面按顺序是：

```
13:09:48  INTEL_CLAIM_REWARDS        → after = POPUP/GENERIC_REWARD（「获得奖励」）
13:09:49  DISMISS_INTEL_GENERIC_REWARD  tap [360,326]（横幅）
13:10:03  after_refresh_1
13:10:16  after_refresh_2  → 见 key/03_：「获得奖励」已关，屏幕上是「探照灯升级」 ⇒ observe = UNKNOWN
          verifier INTEL_REWARD_DISMISS_NOT_PROVEN  ⇒ 整轮结束
```

⇒ **第一个弹窗确实被关掉了**，但**底下冒出第二个弹窗**，而它**识别不出**（横幅 26 / 页脚 22，双双在门外）。
「探照灯升级」的页脚是「点击任意位置**继续**」，与「获得奖励」的「点击任意位置**退出**」不是同一段字，
所以现有页脚模板在它身上不命中（22 > 8）。**这是另一个缺陷，本次没有修**，
下一次同类失败（"点完一个弹窗又露出一个不认识的页面"）仍然会让整轮结束。

另外 `04-b` 显示：横幅**解析成功**的那一次（12:52:01，before 帧 16 = 门），
点击发出后 **+8 秒弹窗仍在**。也就是说"横幅点得中"也**不保证关得掉**。
⇒ 换到页脚不只是换了一个更稳的落点，也是把落点换成弹窗**自己声明的退出面**。

## 四、本次已改 / 未改

**已改（真机已试）**：

1. 五个 `DISMISS_*_GENERIC_REWARD` 与新增的 goal 中立技能 `DISMISS_SHARED_REWARD`
   一律改点页脚退出带（`SHARED_REWARD_EXIT = BTN_DISMISS_INTEL_REWARD`，中心 (360,1197)）。
   执行器对 `TAP_SEMANTIC` 走 `SemanticWorldVision.find(...).center_norm`（`runtime.py:1098`），
   所以落点由技能点名的记录决定。
2. `brain.py`：goal 说不清页面的情况由 `SAFE_STOP` 改为 `DISMISS_SHARED_REWARD`
   （关掉一个自称「点击任意位置退出」的弹窗不是猜）。
3. 守卫与测试同步（`tools/check_wiring.py` 三条 + 两个测试文件）。

**真机证据（当前这一轮，`20260920_211101_334048`）**：

```
13:13:12  DISMISS_INTEL_GENERIC_REWARD  target BTN_DISMISS_INTEL_REWARD  SUCCESS  after INTEL 0.98
13:14:34  DISMISS_INTEL_GENERIC_REWARD  target BTN_DISMISS_INTEL_REWARD  SUCCESS  after INTEL 0.98
13:16:04  DISMISS_INTEL_GENERIC_REWARD  target BTN_DISMISS_INTEL_REWARD  SUCCESS  after INTEL 0.98
```

**未改、也不许当成已完成**：

- **第二个弹窗「探照灯升级」**（第三节）。没有任何它被关掉的帧。
- **`SEMANTIC_TARGET_NOT_VERIFIED` 的另一条来源**：`20260920_120744_012719` 那一步选了解除技能，
  但 before 帧是**邮件收件箱**（横幅 24 / 页脚 36，两个信号都门外 ⇒ `observe` 本不该报弹窗）。
  那是第 5 次出现的"在非弹窗页面上跑弹窗技能"，本次未查。
- 新目标样本只有 **7 次**，且集中在最近几分钟 ⇒ 上表是**方向性证据，不是证明**。
- 旧目标 68 成功也不是零，两者还隔着时间窗 ⇒ **不构成受控对比**。

复现命令：

```bash
"E:/无尽冬日智能体/.venv/Scripts/python.exe" .probe_popup_landing.py
"E:/无尽冬日智能体/.venv/Scripts/python.exe" .probe_target_vs_recognition.py
```

## 五、`readings/`：验收要的两个读数（按 #64 第 5 条的口径）

| 文件 | 内容 |
|---|---|
| `readings/intel_page_20260920T131907.png` | 客户端停在**情报页**。可读：页头 情报；下次刷新 **02:40:54**；右上 **513**；左下等级 **7**、**5/90**；右下 **02:40:55 后开启**；板上 **9 个** pin 标记。 |
| `readings/map_hud_20260920T132136.png` | 客户端停在**地图**。帧上时间戳 09-20 21:21:36，左上体力表 **491**。 |

**同帧的 pin 计数争议（#68）**：项目自身的 `intel_pin_centers` 在情报帧上返回 **4**，
而图上数得出 **9**。原因是检测器只用 purple / blue / orange 三组 HSV 掩码，
而板上 5 个 pin 是**灰色或绿色**。⇒ Agent 眼中的"剩余情报"可能只有实际的一半。
未查清的是那些灰/绿 pin 是否真是可打任务；**不得**靠放宽 `min_area` 之类的方式"修"。

## 六、群体计数（`probe_announcement_dialogs.py`，65 张真机 before 帧）

`dataset/raw/control_panel/runtime_auto/` 最近 5 个 AUTO 轮次的**全部** before 帧（65 张），
用项目自身 OCR 只看横幅带与页脚带：

| 命中内容 | 帧数 |
|---|---:|
| 页脚「点击任意位置**退出**」（= 共用奖励弹窗） | **7** |
| 页脚「点击任意位置**继续**」（= 「探照灯升级」，#65） | **1** |

对照同一窗口的 episode：**新目标 `BTN_DISMISS_INTEL_REWARD` 的解除动作 7 次，7 次 verifier OK**。
⇒ 这 5 轮里**每一张**奖励弹窗都被新落点解析、点击并通过验证（7/7），
而群体计数给出的可打弹窗数也是 7 —— 两者对得上。

**#65 的群体**：5 轮 65 帧里只出现 **1 次**（13:10:16 的 after 帧与 13:11:04 的 before 帧是同一个实例，
它跨了两轮）。⇒ 现在**不足以**满足"≥3 独立正样本"的注册门槛，先记着、继续收帧。

复现：

```bash
"E:/无尽冬日智能体/.venv/Scripts/python.exe" .probe_announcement_dialogs.py 5
```
