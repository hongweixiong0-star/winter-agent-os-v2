# 仓库拓扑：8 个 worktree 共享 main，HEAD 回退的成因（2026-10-03 第五轮末）

> 这解释了本会话两次"提交消失"，并给出后续提交策略。
> **不是丢工作** —— 两次都在对象库里，都快进恢复了。

---

## 一句话

`E:\无尽冬日智能体` 是 **8 个 worktree 共享的仓库**，`HEAD` 指向共享的 `refs/heads/main`。
另一个进程推进/回写了 `main` 的分支指针，本会话的 `HEAD` 就跟着回退。

---

## 一、实测证据

```
$ git worktree list
E:/无尽冬日智能体                                     05042268 [main]
C:/Users/xhw/.codex/worktrees/calendar-detail-liveness/…      aab14bb5 [codex/calendar-detail-liveness]
C:/Users/xhw/.codex/worktrees/global-multirole-integration/…   584b7da2 [codex/global-multirole-production-integration]
C:/Users/xhw/.codex/worktrees/global-multirole-live/…         015e4f2c (detached HEAD)
C:/Users/xhw/.codex/worktrees/global-multirole-v1/…           d23af681 [codex/global-multirole-v1]
C:/Users/xhw/.codex/worktrees/main-integration/…              0025a461 [codex/rally-engine-target-scope]
C:/Users/xhw/.codex/worktrees/winter-prod-pinned/…            79cb572c [codex/production-pin-recovery]
C:/Users/xhw/.codex/worktrees/winter-rally-generalize/…       ef971377 [codex/rally-target-parameterization]
```

`main` 的分支级 reflog —— **本会话的提交一直都在**：

```
$ git reflog show main
05042268 main@{0}
0ca3a161 main@{1}
4090f326 main@{2}
113c1a52 main@{3}
2b52c067 main@{4}
79cb572c main@{5}
```

也就是说：`git rev-parse HEAD` 曾返回 `0ca3a161`，而 `refs/heads/main` 已经是 `05042268`。
**两者不一致 ⇒ 有人用 `update-ref refs/heads/main <旧值>` 之类的操作回写了分支。**

已排除的可能：

| 假设 | 实测 | 结论 |
|---|---|---|
| git hook | `core.hooksPath` 未设，`.git/hooks` 下无自定义 hook | 排除 |
| `tools/control_panel.py` 动 git | `git grep update-ref` 无结果 | 排除 |
| `tools/repin_production.py` 动 dev HEAD | 无 `update-ref` | 排除 |
| 生产 worktree 被改 | 生产 pin 全程稳定在 `79cb572c` | 排除 |
| 提交丢失 | `git cat-file -t` 两次都返回 `commit` | **排除** |

---

## 二、两次"提交消失"的实际过程

**第一次**：HEAD 从 `4090f326` 退到 `113c1a52`，
`git status` 显示三份 handoff 为 `D`。
**第二次**：HEAD 从 `05042268` 退到 `0ca3a161`。

两次的判据相同（已写进 `2026-10-03` 记忆）：

```
1. git cat-file -t <sha>            # 提交仍在对象库
2. git reflog                        # 看到回退
3. 先比对生产 worktree HEAD           # 确认生产未受影响
4. git merge-base --is-ancestor       # 确认是快进才动 HEAD；非祖先则拒绝
5. git reset HEAD -- <path>          # 重读索引，不用 -hard
```

⚠ **`git status` 的 `D` 意思是"不在索引里"，不是"文件没了"。**
索引与 HEAD 不一致时，会出现"提交里有、磁盘上有、状态却显示删除"。

---

## 三、对后续工作的影响（策略变更）

**不要继续在 `main` 上提交。** 理由：

1. `main` 是共享分支，HEAD 会被其它 worktree 的进程回写；
2. `main` 同时是**生产 pin 的来源**（`repin_production.py --to <sha>`），
   在共享分支上推进 HEAD 会让"哪个提交在生产"变得难以断言；
3. 已经因此丢过一次工作现场（虽然可恢复）。

**改为**：

- 在**本会话专用分支**上提交（例如 `workbuddy/page-residency-20261003`），
  用 `git update-ref refs/heads/<branch> <commit>` 而不是移动 `HEAD`；
- 部署仍然用**显式 SHA**（`repin_production.py --to <sha>`），
  **不依赖分支名** —— 这一点本会话一直做对了；
- 每轮收尾时 `git rev-parse refs/heads/<branch>` 复核，
  而不是只看 `git log -1`（HEAD 可能已被别人动过）。

---

## 四、顺带澄清：一个名字相似的并行分支不是这件事

`codex/calendar-detail-liveness` 的最新提交：

```
aab14bb5 fix(calendar): bind detail observations to the current occurrence
  tests/test_calendar_detail_attribution.py | 110 +
  tests/test_event_calendar.py              |   3 +-
  winter_agent_v2/runtime.py                |  15 +-
```

日期 **2026-10-02 12:16**，改的是**网格行**的详情归属
（`event_schedule.py:678` 那段 `_row_carrying_the_details_dates` 的注释正是它留下的）。

**与本轮缺口无关**：
网格行那条链实测是好的（`EVENT_DETAIL` 里两个角色都记着网格活动 `盛会商铺`，
`calendar_origin=GRID_ENTRY`），而本轮断的是**横条活动**的识别。
名字相近容易误判为"已有人做过了"，特此写明。

---

## 五、当前状态

- dev `HEAD` = `05042268`（已恢复）
- 生产 pin = `79cb572c`（全程未变）
- AUTO 正常运行，`worker_exits` 19 未增长
- **本会话累计**：1 个真机确证的修复（`58dccc8b` 导航乒乓）+ 1 个记账修复（`79cb572c`）
  + 3 次自我纠正 + 1 个已定位到"识别缺失"的活锁缺口
