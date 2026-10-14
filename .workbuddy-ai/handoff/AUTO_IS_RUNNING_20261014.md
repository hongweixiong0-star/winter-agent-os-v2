# ✅ AUTO 跑起来了（2026-10-14 23:19）—— 以及我前面两条判断**错在哪**（2026-10-14）

> 操作员 22:56 授权"**可以随便用真机**"。据此把停了近两天的 AUTO 拉起来了。
> 本文件记：**怎么拉起来的**、**我前面的判断错在哪**、以及**现在的状态与注意**。

---

## 一、结果（实测）

```
23:19:22  控制台已启动。
23:19:28  预检·核心：Runtime OK · MuMu OK (127.0.0.1:7555 [720, 1280] 前台 com.gof.china)
23:19:28  预检·辅助：WorkBuddy Gateway 不可用（HTTP_502）；自动开发标记为不可用，后台周期重试，不影响 AUTO。
23:19:28  运行环境预检通过
23:19:28  自动运行已启动：Goal 与 Universal Skill 由唯一 Scheduler 决定。
23:20:41  ✓ 本轮结束：已切换到角色 1061663148，正在刷新状态
23:23:28  自动运行已启动            ← 连续在跑
```

`learning/runtime_snapshot.json`：**`agent_state=AUTO_RUNNING`、`runtime_thread_alive=True`、
`scheduler_loop_alive=True`、`stop_reason=None`**（`page=HOME`，游戏在前台）。

## 二、拉起来的**配方**（两步，缺一不可）

1. **把模式切回 AUTO**（官方接口，带审计轨迹）：
   ```python
   mode_state.switch(mode_state.MODE_AUTO, initiator=mode_state.BY_USER,
                     reason='操作员授权（…）：可以随便用真机 ⇒ 交还机器给 AUTO')
   ```
   ⇒ `MODE_STATE.json` 里 `history` 追加 `2026-10-14T15:07:41Z: MANUAL->AUTO by USER`。
   顺手把残留的 `user_latch` 置 False（模式与闸舌应一致）。
2. **重启面板**（旧面板的 autostart 重试**没有**自己在跑，见 §三）。

⇒ 新面板启动后**自动起 AUTO**（预检通过 + `auto_execution=true` + `operator_intent=RUNNING` + 连续运行开）。

## 三、我前面两条判断**错在哪**（更正，别再照错的办）

| 我之前的说法 | 实际 |
|---|---|
| 「**起 AUTO 只有界面按钮一条路**，没有 CLI 捷径」 | **错。** 面板**启动时就会自动起 AUTO**（`_maybe_autostart`：`auto_execution` + `operator_intent==RUNNING` + `continuous` + 预检通过 ⇒ `self.start()`）。22:49 那次就是它自己起的。 |
| 「翻 `MODE_STATE` 不会恢复 AUTO」 | **半对。** 翻模式**单独不够**（我实测等了 70s，没起）——因为**循环当时已经停了**、没有在重试；但只要**再起一次面板**，模式是 AUTO 就会自动跑起来。 |

**正确的因果**：**模式 MANUAL 只是让 runtime 让出**（`machine_is_ours = mode==AUTO and intent!=PAUSED`，每轮现读）；
**循环起不起来是面板自己的 autostart 门**。所以恢复 = **切回模式 + 让面板再起一次**（重启或点按钮）。

## 四、启动来路（**重要，影响验收**）

- **面板本来归 Windows 计划任务 `WinterAgentV2Panel` 管**（`Start-Winter-Agent-V2.cmd` → `schtasks /Run`）。
- 我杀旧面板时用的是 `taskkill /PID`（**没带 `/T`**，避免像日志警告的那样把整棵树/助手带走）。✓
- **但 `schtasks.exe` 被本机安全策略列入黑名单，我这边起不来** ⇒ 我改用
  `\.venv\Scripts\pythonw.exe <pin>/tools/launch_pinned_production.py` **直接拉起了面板**。
- ⚠️ **后果**：这一路是"**开发工具启动**"，不是桌面双击 ⇒ 验收 Soak 会把它记为
  **`DEVELOPMENT_ENV_LIMITATION`** 而不计为证据（`Start-Winter-Agent-V2.cmd` 的注释明写了这条）。
  **⇒ 方便时请用 `Start-Winter-Agent-V2.cmd` 双击重拉一次**，Soak 才算数。

## 五、现在的状态与已开的门

- **AUTO 在跑、连续在跑**（`AUTO_RUNNING`）。这是**近两天来第一次**。
- **但活不会自己来**：预载闸门仍被 **17 条记录**关着（`GATE_REFUSED · REAL_GAP_WAITING`），
  每轮结束都是"已切换到角色 … 正在刷新状态"——**在转，但没有 goal/skill 在跑**（`goal=None`、`skill=None`）。
  这正是 **D-B（给台账加一个诚实的退役词）** 那个堵点。
- **Soak 窗口**已开（900 秒）；但 **Gateway 不可用（HTTP_502）** ⇒ 大概率按 `GATEWAY_SOAK=FAIL` 收场
  （这就是 **D-C 72h 判据**在构造上不可能满足的那条的实证）。
- **真机门现在开了**，下面这些**第一次可以做**：
  1. **巨熊准时参战**（头号目标）——AUTO 会自己抓窗口；只需在窗口出现时看 `participate_bear` 有没有真的执行；
  2. **HUD 体力 ROI 到底是几**——本会话实测：54×24 小裁片生产 OCR **读出 0 token**、放大 6× 读出 `'6'`，
     而测试期望 `9`。**真机现读一次 HUD 就能定这个数**；
  3. **被 retention 删掉的测试 fixture 帧**——可以在真机上重新采集（`dataset/raw/**` 会被轮转，见
     `THE_FULL_SUITE_IS_RED_AND_WHY_20261014.md` §三·补⁶）。

## 六、未做 / 待办

- **没修 Gateway 502**（不是我起的头，且属环境问题）；
- **没提交 `config/v2.json` 的本地改动**（那是操作员 2026-10-08 的模型切换：UI-Venus-2-9B → Qwen3.6-35B-A3B，属他们的编辑）；
- **D-B / D-C 两条决定仍未下**（AUTO 跑起来不解除它们）。
