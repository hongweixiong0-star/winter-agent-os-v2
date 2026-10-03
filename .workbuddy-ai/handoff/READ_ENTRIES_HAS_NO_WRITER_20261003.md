# 活锁的真正缺口：`read_entries` 只有读方，没有写方（2026-10-03 第四轮）

> 上一轮定位到泄漏分支是 `advertised_but_unread_activities`。
> 本轮按"先看真机帧、不写代码"的约定继续追查，**找到了缺失的那一半**。
> **本轮仍未改代码**——因为缺口是"缺一个动作"，不是"缺一个条件"，
> 而那个动作属于高风险（点击客户端活动入口），必须先确认边界。

---

## 一句话

`calendar_scan_due` 靠"打开被宣告的活动"来收敛，但**生产代码里没有任何地方记录"已打开"**。
`read_entries` 只有读方（`event_schedule.py:464`）和测试里的写方，**生产写入方从未存在过**。

---

## 一、真机帧确认（先看，再推断）

当前生产帧 `20261003_135523_543893_step_017_before_20261003T055852338256.png`（720×1280）
显示的就是 `常规活动` 页：

- 顶部横条（`ACTIVITY_STRIP_ROI`，y_norm 0.06–0.20）：日历图标 / **最强王国** / **峡谷会战** / 一个带红点的项
- 下方大时钟 `2026-10-03 13:58:55`
- 再下方是**日历网格**：`冰封的宝藏`（寻宝特训 / 冰封的宝藏 / 秘宝商行）与
  `辉煌盛世庆典`（庆典对碰撞 / 狮舞盛会 / 盛会商铺）……

**"最强王国"（`STATE_VS_STATE`）与"峡谷会战"（`CANYON_CLASH`）确实在横条上，
但确实不在网格里。** 这与账本完全一致：网格 5 行全部 `details_observed=True`，
横条 2 个 `details_observed=null`、`read_entries=0`。

---

## 二、这不是"打不开"，是"打开方式不是点网格"

`event_calendar.py` 里 `read_regular_event_activity_strip` 的 docstring 早就写明了
（作者在 2026-10-02 就发现了同一现象）：

> `ALLIANCE_MOBILIZATION`、`CANYON_CLASH` 和 `ARMAMENT_FACTORY_EVENT`
> 是**只出现在横条上、从不作为网格行**的已注册活动……

并且给出了两条硬约束：

- **横条不带时间窗**：`start`/`end` 保持 `None`，"预览永远不能变成战斗时钟"；
- **`tap_norm` 是当帧几何，随 token 过期**——"生产宪法第 2 条：坐标只能是当前帧识别的结果"。

所以路径是清楚的：**点横条上的活动图标 ⇒ 打开该活动详情页**，
而不是在日历网格里找一个不存在的行。

---

## 三、缺口：`read_entries` 的生产写入方不存在

```
$ git grep -n read_entries -- '*.py'
tests/test_calendar_scan_due_for_unobserved_activities.py:150   ← 测试里手写 JSON
winter_agent_v2/event_schedule.py:464                            ← 唯一的读方
```

历史也确认这不是回归：

```
$ git log --oneline -S read_entries -- winter_agent_v2/
5b7e9cd4  fix(schedule): an advertised activity nobody opened keeps the calendar due
```

**只有一个提交引入过它**，而那个提交同时写了两个测试：

```python
def test_a_strip_row_that_was_opened_closes_the_scan(tmp_path):
    """The fix must converge too, or it is the infinite loop the registry version was.

    Opening the advertised activity is what discharges the debt; nothing else does.
    """
    # 直接改 JSON 模拟"已打开"
    payload["calendar_observations"][ROLE]["ACTIVITY_STRIP"]["read_entries"] = [
        {"event_id": "CANYON_CLASH"}
    ]
```

**测试用"直接写文件"来验证收敛，生产里没有任何代码会写这个字段。**
这是一个教科书式的"读方存在、写方缺失"——测试绿了，机制在真机上从未运行。

---

## 四、完整因果链（每一环都已实测）

1. 客户端在横条宣告 `最强王国` / `峡谷会战`（有 `tap_norm`）；
2. 它们不在网格的 5 行里，打开网格进不到；
3. `advertised_but_unread_activities` 正确地判为"未读"（**它没错**）；
4. `read_entries` 在生产里永远是空 ⇒ 债务永不消；
5. ⇒ `calendar_scan_due` 永远 True；
6. ⇒ `DISCOVER_EVENT_CALENDAR` 在 HOME 上永远 `base=1000` 必胜；
7. ⇒ 每 **0.4 分钟**（中位，实测 213 次选择）重扫一次；
8. ⇒ 到 EVENT、打开网格、5 行全已读 ⇒ COMPLETE ⇒ 合理让位 ⇒ 回 HOME ⇒ 回到第 5 步。

**对照角色 `1061663148`：上次扫描在 1437 分钟前、`due=False`**
——它能收敛，是因为它那个角色当时**没有横条活动欠债**。
这证明判据本身能收敛，缺的只是消债的那一半。

---

## 五、下一步（不是改判据，仍是"先看"）

**不要改 `calendar_scan_due`**（放松它会丢掉两个真实活动的报名/开战时间；
它的注释里记录了两个被既有测试否掉的错误版本）。

该做的是补上"打开横条活动 ⇒ 记为已读"这条链，但**先回答三个只能看真机的问题**：

1. 点横条上 `最强王国`（约 x=0.466, y=0.133）会发生什么？
   是直接打开活动详情，还是先切到该活动的页签？
2. 打开后**哪个可观察量**证明"这个活动被读过了"？
   （活动详情页出现？某段文字被 OCR 读到？报名/开战时间被读到？）
   **这个量必须能写成 `read_entries`，否则实现了也白实现。**
3. 这个动作的风险等级：它是纯导航（进活动页），还是会触发报名/领奖/消耗？
   若是不可逆动作，Risk Gate 必须挡住，而"挡住"不能等于"不记已读"——
   否则又变成永久 due。

> **在看到真机帧之前不要写任何代码。** 这是本轮学到的最重要一条：
> 我已经连续两轮在没有落地观察的情况下改这个子系统，
> 两次都改错了方向（第一次改排序、第二次改记账）。

---

## 六、本轮状态

- **无代码改动。** 生产 pin 仍是 `79cb572c`，AUTO 正常运行。
- `served_by`（`79cb572c`）保留：它让完成的扫描能被记账，是真需求，
  但**与本活锁无关**，不要当成已修复。
- `page_residency`（`58dccc8b`）保留：它真机确证有效
  （导航步 17.8%→3.8%、反向 37%→0%），解决的是另一个乒乓。
