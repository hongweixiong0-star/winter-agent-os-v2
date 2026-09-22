# 空转：一趟运行在两个页面之间来回走（2026-09-23）

## 一句话

自 16:00Z 起 **75 个运行里有 18 个**（24%）从头到尾只是 `OPEN_MAP` / `OPEN_HOME` / `OPEN_MAP`：
去了地图、回了城、又去地图，什么也没观察到、什么也没改变。两个方向各自都对，合起来是个环。

## 链条（回放，不是推断）

`tools/replay_run_decisions.py` 用**生产视觉**从录下的帧重建世界，用**生产大脑**按运行顺序喂进**同一个
brain 实例**（它的计数器是运行内的状态机，所以每步都新建实例等于每步都重放第一步）。运行
`20260923_062948_568906` **3/3 精确复现**：

| 时刻 | 页面 | 技能 | 谁发的 | 理由 |
|---|---|---|---|---|
| 22:30:26 | HOME → MAP | OPEN_MAP | `brain.decide` | `first_ready_p0_skill` |
| 22:31:28 | MAP → HOME | OPEN_HOME | `runtime._deferral_replan` | `deferred_SPEND_STAMINA_ON_BEAST_left_nothing_to_do_here` |
| 22:31:58 | HOME → MAP | OPEN_MAP | `brain.decide` | `first_ready_p0_skill` |

第三步与第一步**逐字相同**，这就是缺陷本身。

为什么理由只能靠回放拿到：episode 流当时**不记 `decision.reason`**（已是 #104 的一部分修复），
而运行时日志只保留最近一轮。帧是唯一的幸存证人，而这三个理由在两个不同的层里。

`_replan_attempted` 的注释写着「so leaving cannot become a two-page ping-pong」——实测它做不到：
**只给双向环的一侧上界，环还在**。缺的不是第二个界，是记忆。

## 修法

`LiveRuntime._stop_instead_of_looking_again`：运行内记住「站过、且调度器什么都没给」的页面
（`_barren_pages`），一个**只为找目标而存在**的跳转（`PAGE_HOPS_THAT_ONLY_LOOK_FOR_GOALS`：
`OPEN_MAP`→MAP、`OPEN_HOME`→HOME），如果目的地已经在里面，就不是「去看看」，而是「把看过的地方
再看一遍」⇒ 换成 `SAFE_STOP`（`every_page_this_run_was_fruitless`）。

四条边界，各自有测试：只有**没有可选目标**的步骤才判（带目标的跳转原样返回）；只判那两个跳转
（INTEL 路由发的 `OPEN_MAP` 与此无关）；站着的页面**无论这一步是不是跳转**都记为荒页（在地图上读了
`CHECK_MARCH` 也是同一个发现）；答案是**停止**而不是另一个跳转。

## A/B（同一批真实帧，只切守卫这一个变量）

`tools/replay_run_decisions.py --limit 18`，18 个纯导航空转运行（16:00Z 起）、36 个记录步骤：

| | |
|---|---|
| 回放与语料一致的步骤 | **28 / 36**（不一致的 8 步是生产里当时**有**目标的步骤：本回放只重建无目标链，工具文档里写明了） |
| 加守卫前 | **36 步** |
| 加守卫后 | **27 步** |
| 提前结束的运行 | **7** |

两个方向都被命中，逐条可在 `console.txt` 核对：

```
run 20260923_000958_683601  4 步（4/4 复现）
  HOME->MAP OPEN_MAP  brain.decide            first_ready_p0_skill
  MAP->HOME OPEN_HOME runtime._deferral_replan deferred_..._left_nothing_to_do_here
  HOME->MAP OPEN_MAP  brain.decide            first_ready_p0_skill      ← 重复
  MAP->HOME CHECK_MARCH brain.decide
  ⇒ 守卫后：第 2 步即 SAFE_STOP（拒绝的是 OPEN_HOME / deferred_...）

run 20260923_000639_research  3 步
  MAP->HOME OPEN_HOME runtime._deferral_replan
  HOME->MAP OPEN_MAP  brain.decide            first_ready_p0_skill
  ⇒ 守卫后：第 2 步即 SAFE_STOP（拒绝的是 OPEN_MAP / first_ready_p0_skill）
```

语料侧的量：`learning/episodes.jsonl` 自 16:00Z 起 75 个运行 / 597 步，其中 18 个运行（36 步）全部只由
`OPEN_MAP` / `OPEN_HOME` / `CHECK_MARCH` 组成；`goal=AUTO_DISCOVERY` 的 91 步里 79 步是导航。

## 复算

```
E:\无尽冬日智能体\.venv\Scripts\python.exe -u tools/replay_run_decisions.py --limit 18
```

（约 4 分钟：每帧一次生产 OCR。帧本体不入 git，见 `.gitignore`；这里放的是指标与命令。）

## 边界 / 未做

* 只覆盖**无目标**链。有目标的跳转（INTEL 要地图、训练要回城）不受影响，也**没有**被验证过是否也会
  绕圈——那是另一个问题，需要各自的帧。
* 回放用的是**记录里的 before 帧**；某一步缺帧（如 `20260923_001936_231102` 的 #2）时，回放看不到那次
  跳转的结果，于是它那一轮的两个 `OPEN_MAP` 都通过了守卫——这是回放的限度，不是守卫的限度。
* 真机尚未跑到：`_stop_instead_of_looking_again` 的落点要在下一轮 AUTO 出现「无事可做」时，从
  `episodes.jsonl` 的 `decision_reason` 里看到 `every_page_this_run_was_fruitless` 才算 LIVE。
