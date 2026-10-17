# 自动化记忆：UNKNOWN 问题通道消费（unknown_ai_worker.py --once）

任务：在项目目录执行 `.\.venv\Scripts\python.exe tools\unknown_ai_worker.py --once`
（结算在跑 job → 对可派发的问题各提交一个背景作答 job）。
约束：不改代码、不点设备、不跑 AUTO、不直接写 answers/。

## 执行历史

### 2026-09-22 19:00 (GMT+8) / 11:00 UTC
- 网关：up（可达）。
- reconcile: checked=1, done=0, failed=0, lost=0, **abandoned=1**
  → `unknown__control__23759997` 的 job `4f94548d` 因 "no result after 45 minutes" 被标记 ABANDONED 并尝试 cancel。
- submitted: 0。
- 原因（读码确认，非故障）：`unknown_dispatch.py` 的 `candidates()` 对"已 abandon 的记录"施加
  `DISPATCH_COOLDOWN_SECONDS = 900` 冷却，判据是 `_seconds_since(record.updated_at)`；
  abandon 事件刚刚刷新了 updated_at，所以本轮重试被冷却挡住（不计入 submitted 也不出现在 skipped 里，
  只有 `--state` / `--dry-run` 能看出来）。attempts 仍为 1/2，等待期过后可再试一次。
- 收尾状态：pending=1（`unknown__control__23759997`, goal=TRAIN, no job），answered=1
  （`unknown__control__b6546e80` 已有答案文件），in flight=none。

### 2026-09-22 20:01 (GMT+8) / 12:01 UTC
- 网关：up（可达）。
- reconcile: checked=0, done=0, failed=0, lost=0, abandoned=0（上轮无 in-flight job，故无可结算）。
- submitted: 1 —— `unknown__control__23759997` (goal=TRAIN) → job `33f0d3d7`, model=deepseek-v4.1-flash。
  这正是上轮被 900s 冷却挡下的那条；冷却已过期，本轮成功派发，attempts 升到 2/2。
- 收尾状态：gateway up, pending=1, answered=1, in flight=['33f0d3d7']，等待答案的就是 33f0d3d7。
- 注意：attempts 已到 2/2 上限，若本 job 再失败/丢失，该问题将不再自动重派，需要人工介入。

### 2026-09-22 21:02 (GMT+8) / 13:02 UTC
- 网关：up（可达）。
- reconcile: checked=0, done=0, failed=0, lost=0, abandoned=0。
  job `33f0d3d7` 已于 20:47 那轮（非本次）被结算为 ABANDONED（"no result after 45 minutes"），
  故本次无在飞 job 可结算。
- submitted: 0 —— 且**这次不是因为冷却**：`unknown__control__23759997` 的 attempts 已达 2/2，
  `unknown_dispatch.candidates()` 的 `record.attempts >= self.max_attempts` 直接把它排除，
  属**永久退出候选**。自动化通道对该问题已静默，只能人工介入。
- 收尾状态：pending=1、answered=1、in flight=none。另注意该记录 goal 由 TRAIN 变成 BEAST_HUNT
  （期间有其它进程改写）。
- 下次运行预期：仍为 submitted=0，除非人工重置该记录的 attempts 或新增别的 pending 问题。

### 2026-09-22 22:04 (GMT+8) / 14:04 UTC
- 网关：up（可达）。
- reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；submitted: 0，输出 "nothing to do"。
- 与上轮预判一致：`unknown__control__23759997` attempts=2/2 已永久退出候选，通道静默需人工介入。
  收尾：pending=1、answered=1、in flight=none。台账尾部仍停在 12:47 的那条 ABANDONED，无新事件。

### 2026-09-22 23:05 (GMT+8) / 15:05 UTC
- 网关：up（可达）。
- reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；submitted: 0，输出 "nothing to do"。
- 与连续两轮预判一致：`unknown__control__23759997` attempts=2/2 永久退出候选，通道静默。
  收尾：pending=1、answered=1、in flight=none。无新事件。
- 结论：该通道已进入**稳态静默**，后续自动化大概率持续输出 "nothing to do"，
  除非人工重置 attempts 或新增 pending 问题；建议减少巡检频率或改人工介入。

### 2026-09-23 00:05 (GMT+8) / 16:05 UTC
- 网关：up（可达）。
- reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；submitted: 0，输出 "nothing to do"。
- 与前三轮一致：`unknown__control__23759997` attempts=2/2 永久退出候选，通道静默。
  收尾：pending=1、answered=1、in flight=none。该记录 goal 又被其它进程改写为 RESEARCH
  （先后见过 TRAIN→BEAST_HUNT→RESEARCH），说明外部有进程在动态改这条问题。
- 判断：稳态静默持续第 3 轮，人工不重置 attempts 则后续仍为 0 提交。

### 2026-09-23 01:06 (GMT+8) / 17:06 UTC
- 网关：up（可达）。
- reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；submitted: 0，输出 "nothing to do"。
- 与前三轮完全一致：`unknown__control__23759997` attempts=2/2 永久退出候选，通道静默。
  收尾：pending=1、answered=1、in flight=none；该记录 goal 现为 RESEARCH。
- 稳态静默第 4 轮。已连续 4 次零结算零提交，建议将本自动化降频或暂停，改人工介入重置 attempts。

### 2026-09-23 02:07 (GMT+8) / 18:07 UTC
- 网关：up（可达）。
- reconcile: checked=1 done=0 failed=0 lost=0 abandoned=0；submitted: 0。
- **状态有变**：不再是零在飞。新增 pending 问题 `unknown__control__78694f1b`（goal=INTEL, screen=UNKNOWN::对战），
  其 job `86aaf32a` 于 01:47:29 GMT+8 被（上一轮或其它进程）派发，本次运行仍在 working，故 checked=1 但无可结算。
- 收尾：pending=2、answered=1、in flight=['86aaf32a']。
  等待答案的两个：78694f1b（有 job 在飞）、23759997（attempts 2/2，无 job，永久退出候选）。
- 本次 submitted=0 的原因：23759997 被封（attempts 上限）、78694f1b 已有在飞 job，候选为空。
- 下次预期：若 86aaf32a 在 45 分钟内落盘则记为 done；否则记 ABANDONED，且 78694f1b attempts 变 1/2。

### 2026-09-23 03:08 (GMT+8) / 19:08 UTC
- 网关：up（可达）。
- reconcile: checked=1 done=0 failed=0 lost=0 abandoned=0；submitted: 0。
- 台账显示：`78694f1b` 的首个 job `86aaf32a` 已于 18:35:42 UTC（02:35 GMT+8）被记为 ABANDONED，
  随后 18:51:47 UTC（02:51 GMT+8）由**其它进程**派发重试 job `0600dfcb`（reason=retry 2），
  本次运行 reconcile 追到的正是这个仍 working 的 job（约 16 分钟，未过 45 分钟阈值），故无结算。
- submitted=0 原因：78694f1b 已有在飞 job；23759997 attempts=2/2 永久封死 → 候选为空。
- 收尾：pending=2、answered=1、in flight=['0600dfcb']；等待答案的是 78694f1b（在飞）与 23759997（无 job）。
- 注意：78694f1b attempts 已升到 2/2，若 `0600dfcb` 再失败/超时，该问题也将永久退出候选，需人工介入。

### 2026-09-23 04:08 (GMT+8) / 20:08 UTC
- 网关：up（可达）。
- reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；submitted: 0，输出 "nothing to do"。
- 在飞 job `0600dfcb` 已于 03:41:09 GMT+8（19:41:09 UTC）被**其它进程**结算为 ABANDONED
  （"no result after 45 minutes"），故本次无在飞 job 可结算，checked=0。
- **两个 pending 问题均已 attempts=2/2 永久退出候选**：
  `unknown__control__23759997`（goal 又被改写为 INTEL）与 `unknown__control__78694f1b`（goal=INTEL）。
  即"可自动重派"的问题归零，通道进入全面静默。
- 收尾：pending=2、answered=1、in flight=none。两条待答问题都无 job，只能人工介入重置 attempts。
- 关键教训：背景 job 反复 ABANDONED（45 分钟无落盘）→ attempts 迅速耗尽 → 通道永久静默。
  MAX_ATTEMPTS_PER_REQUEST=2 对"长时无应答"场景过于激进；建议人工介入时优先排查 job 侧为何不落盘
  （answer 写入失败 / advisor 侧异常），而非单纯重置 attempts。

### 2026-09-23 05:10 (GMT+8) / 21:10 UTC
- 网关：up（可达）。
- reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；submitted: 0，输出 "nothing to do"。
- 与上轮预判一致：两条 pending 问题 `23759997`、`78694f1b` 均 attempts=2/2 永久退出候选，
  且 in flight=none，故 checked=0、候选为空。
- 收尾：pending=2、answered=1、in flight=none；两条待答问题都无 job。
- 全面静默第 2 轮（04:08 起）。持续零产出，建议人工介入排查 job 侧为何不落盘。

### 2026-09-23 06:10 (GMT+8) / 22:10 UTC
- 网关：up（可达）。
- reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；submitted: 0，输出 "nothing to do"。
- 与上轮一致：pending=2、answered=1、in flight=none；`23759997` 与 `78694f1b` 均 attempts=2/2
  永久退出候选，两条待答问题都无 job。全面静默第 3 轮。
- 无新事件、无状态变化。

### 2026-09-23 07:11 (GMT+8) / 23:11 UTC
- 网关：up（可达）。
- reconcile: checked=1 done=0 failed=0 lost=0 abandoned=0；submitted=0，
  但**首次出现 skipped**：`unknown_i__control__b860b24a (in-flight limit reached)`。
- 原因：`MAX_IN_FLIGHT = 1`（全局同时在飞上限为 1），而在飞 job `67ddf456`
  属于另一个问题 `unknown_12_6__control__cb5386d4`（22:55:03 UTC 由其它进程派发，goal=TRAIN,
  screen=UNKNOWN::-12.6℃），本次 reconcile 追到的就是它（约 17 分钟，未过 45 分钟阈值）。
  配额被占满，故新问题 b860b24a（新出现，goal=MAIL, screen=UNKNOWN::跳过I）虽 pending 且
  attempts=0（未计入 attempts 字典即从未派发）仍被挡下。
- 收尾：pending=4、answered=1、in flight=['67ddf456']。
  待答 4 条：b860b24a（无 job，等配额）、cb5386d4（在飞）、23759997 与 78694f1b（均 attempts=2/2 永久封死）。
- 重要更正/细化：此前记录的"静默"结论已被打破——外部进程仍在持续新增 pending 问题，
  通道并未死；只是**调度是串行的**，有 job 在飞时新问题只能排队。判断"submit 0"时，
  除 attempts 上限与 900s 冷却外，还要考虑 **MAX_IN_FLIGHT=1 的配额占用**（skip 会明确打印原因）。
- 下次预期：若 67ddf456 在 45 分钟内落盘 → cb5386d4 记 done 并释放配额，b860b24a 有望被派发。

### 2026-09-23 08:12 (GMT+8) / 00:12 UTC
- 网关：up（可达）。
- reconcile: checked=1 done=0 failed=0 lost=0 abandoned=0；submitted: 0，
  skipped：`unknown_12_6__control__cb5386d4 (in-flight limit reached)`。
- 台账显示上轮的在飞 job `67ddf456`（cb5386d4）已于 23:40:36 UTC（07:40 GMT+8）被其它进程
  结算为 ABANDONED，并在同一时刻派发了新 job `f8290a98`（问题 `unknown_i__control__b860b24a`,
  goal=MAIL, screen=UNKNOWN::跳过I）。本次 reconcile 追到的正是这个仍 working 的 job
  （约 32 分钟，未过 45 分钟阈值），故无结算。
- submitted=0 原因：MAX_IN_FLIGHT=1 的配额被 f8290a98 占满；cb5386d4 已是候选（retry 2 就绪）被 skip。
- 收尾：pending=4、answered=1、in flight=['f8290a98']。
  待答 4 条：b860b24a（在飞）、cb5386d4（等配额，attempts=1）、23759997 与 78694f1b（均 attempts=2/2 永久封死）。
- 复现确认：`--state` 的 "would be submitted now" 会无视 MAX_IN_FLIGHT 配额，与实跑 skipped 不一致；
  判断真实可派发状态必须看实跑输出。

### 2026-09-23 09:22 (GMT+8) / 01:22 UTC
- 网关：up（可达）。
- reconcile: checked=1 done=0 failed=0 lost=0 abandoned=0；submitted: 0，
  skipped：`unknown__control__b2e886bd (in-flight limit reached)`。
- 在飞 job 为 `d66dcf16`（问题 `unknown_i__control__b860b24a`，goal=MAIL，08:45 GMT+8 由其它进程
  以 reason=retry 2 派发），本次追到时约 37 分钟，未过 45 分钟阈值 → 无结算。
  上一段空闲期的 job `f8290a98`、`30aa6e3a` 已在更早轮次结算（分别 ABANDONED / failed）。
- 收尾：pending=5、answered=1、in flight=['d66dcf16']。新增第 5 条 pending `unknown__control__b2e886bd`
  （UNKNOWN::探照灯升级, goal=ALLIANCE, attempts=0 即从未派发），因 MAX_IN_FLIGHT=1 配额被占而排队。
- attempts 现状：b6546e80=1（已答）；23759997=2、78694f1b=2、cb5386d4=2（failed）、b860b24a=2
  → 除新来的 b2e886bd 外，其余未答问题均已到 2/2 上限，仅 b860b24a 因在飞尚有最后一次机会。
- 下次预期：若 d66dcf16 落盘 → b860b24a 记 done 并释放配额，b2e886bd 有望被派发；
  若 45 分钟超时 → b860b24a 也永久退出候选，届时只剩 b2e886bd 一条可派发。

### 2026-09-23 10:29 (GMT+8) / 02:29 UTC
- 网关：up（可达）。
- reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；submitted: 0，输出 "nothing to do"。
- 台账尾部：问题 `unknown__control__b2e886bd`（探照灯升级, goal=ALLIANCE）的 job `5e4103d1`
  已于 02:22:41 UTC（10:22 GMT+8）被**其它进程**结算为 ABANDONED（"no result after 45 minutes"），
  距本次运行仅约 6.7 分钟，仍在 900s 冷却窗口内 → 属**临时冷却**型 submit 0，非永久封死。
- 收尾：pending=5、answered=1、in flight=none。attempts：b2e886bd=1（唯一未封死的未答问题，
  冷却过后可重试）、23759997/78694f1b/cb5386d4/b860b24a 均=2/2 永久退出候选。
- 下次预期：约 10:40 GMT+8 之后 b2e886bd 冷却解除，若届时无在飞 job（MAX_IN_FLIGHT=1）应会被派发。

### 2026-09-23 11:29 (GMT+8) / 03:29 UTC
- 网关：up（可达）。
- reconcile: checked=1 done=0 failed=0 lost=0 abandoned=1；submitted: 0，无 skipped。
- 本次结算的是 `unknown__control__b2e886bd`（探照灯升级, goal=ALLIANCE）的 job `40c95545`
  （02:41:54 UTC 由其它进程以 retry 2 派发），因 "no result after 45 minutes" 记 ABANDONED。
- 影响：b2e886bd attempts 由 1 升到 2/2 → **5 条 pending 问题全部 attempts=2/2 永久退出候选**，
  in flight=none，可自动重派的候选归零，通道重回全面静默（submit 0 属"永久封死"型，非冷却、非配额）。
- 收尾：pending=5、answered=1、in flight=none。台账尾部停在本次的 ABANDONED。
- 判断：背景 job 侧持续 45 分钟不落盘（连续 3 个 job 均 ABANDONED），是本通道失效的根因，
  单纯重跑自动化不再有产出，必须人工排查 job 侧写盘/advisor 异常或重置 attempts。

### 2026-09-23 12:30 (GMT+8) / 04:30 UTC
- 网关：up（可达）。
- reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；submitted: 0，输出 "nothing to do"。
- 台账尾部无新事件，仍停在 03:29:54 UTC 那条自己的 ABANDONED（b2e886bd / 40c95545），
  即本次与前两轮之间**外部进程也没有再派发任何 job**。
- 收尾：pending=5、answered=1、in flight=none。
  attempts：b2e886bd=2、23759997=2、78694f1b=2、cb5386d4=2、b860b24a=2（全部 2/2 永久退出候选）；
  b6546e80=1（已答）。5 条待答问题全部 "no job"。
- 判断：全面静默延续。submit 0 属**永久封死**型（非冷却、非配额），自动化重跑不再产生任何产出。

### 2026-09-23 13:31 (GMT+8) / 05:31 UTC
- 网关：up（可达）。
- reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；submitted: 0，输出 "nothing to do"。
- 台账尾部无新事件，仍停在 03:29:54 UTC 那条自己的 ABANDONED（b2e886bd / 40c95545），
  即连续两轮之间外部进程也没有再派发任何 job。
- 收尾：pending=5、answered=1、in flight=none；5 条待答问题全部 "no job"，
  attempts 全为 2/2（b2e886bd/23759997/78694f1b/cb5386d4/b860b24a），永久退出候选。
- 全面静默延续第 3 轮，submit 0 属永久封死型，自动化重跑无产出，需人工介入。

### 2026-09-23 14:32 (GMT+8) / 06:32 UTC
- 网关：up（可达）。
- reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；submitted: 0，输出 "nothing to do"。
- 台账尾部无新事件，仍停在 03:29:54 UTC 那条自己的 ABANDONED（b2e886bd / 40c95545），
  连续三轮之间外部进程也未再派发任何 job。
- 收尾：pending=5、answered=1、in flight=none；5 条待答问题全部 "no job"，
  attempts 全为 2/2（b2e886bd/23759997/78694f1b/cb5386d4/b860b24a），永久退出候选。
- 全面静默延续第 4 轮。自动化已无产出能力，强烈建议暂停本任务或改人工介入。

### 2026-09-23 15:33 (GMT+8) / 07:33 UTC
- 网关：up（可达）。
- reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；submitted: 0，输出 "nothing to do"。
- 台账尾部仍停在 03:29:54 UTC 那条 ABANDONED（b2e886bd / 40c95545），
  即连续四轮之间外部进程也未再派发任何 job。
- 收尾：pending=5、answered=1、in flight=none；5 条待答问题全部 "no job"，
  attempts 全为 2/2（b2e886bd/23759997/78694f1b/cb5386d4/b860b24a），永久退出候选。
- 全面静默延续第 5 轮。零结算零提交，自动化已无产出能力，需人工介入排查 job 侧落盘失败。

### 2026-09-23 16:36 (GMT+8) / 08:36 UTC
- 网关：up（可达）。
- reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；submitted: 0，输出 "nothing to do"。
- 台账尾部仍停在 03:29:54 UTC 那条 ABANDONED（b2e886bd / 40c95545），
  即连续五轮之间外部进程也未再派发任何 job。
- 收尾：pending=5、answered=1、in flight=none；5 条待答问题全部 "no job"，
  attempts 全为 2/2（b2e886bd/23759997/78694f1b/cb5386d4/b860b24a），永久退出候选。
- 全面静默延续第 6 轮。零结算零提交，自动化已无产出能力，需人工介入排查 job 侧落盘失败。

### 2026-09-23 17:37 (GMT+8) / 09:37 UTC
- 网关：up（可达）。
- reconcile: checked=1 done=0 failed=0 lost=0 abandoned=0；submitted: 0（无 skipped 打印）。
- **状态再次有变，静默被打破**：新增第 6 条 pending 问题 `unknown__control_1add7d8e`
  （UNKNOWN::欢迎回来, goal=ALLIANCE），其 job `4c224bf0` 于 09:36:30 UTC（17:36:30 GMT+8，
  距本次运行仅约 1 分钟）由**其它进程**派发，本次 reconcile 追到的就是这个仍 working 的 job，
  未过 45 分钟阈值 → 无结算。这也是 submitted=0 的直接原因（MAX_IN_FLIGHT=1 配额被占）。
- 收尾：pending=6、answered=1、in flight=['4c224bf0']。
  attempts：1add7d8e=1（在飞）、b2e886bd/23759997/78694f1b/cb5386d4/b860b24a=2（永久封死）、
  b6546e80=1（已答）。
- 待答 6 条：1add7d8e（在飞）、其余 5 条 "no job"。
- 下次预期：4c224bf0 若 45 分钟内落盘 → 1add7d8e 记 done；否则 ABANDONED 且 attempts→2/2。

### 2026-09-23 18:38 (GMT+8) / 10:38 UTC
- 网关：up（可达）。
- reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；submitted: 0，输出 "nothing to do"（无 skipped）。
- 台账尾部：上轮在飞 job `4c224bf0`（问题 `unknown__control_1add7d8e` / UNKNOWN::欢迎回来 / goal=ALLIANCE）
  已于 10:25:52 UTC（18:25:52 GMT+8）被**其它进程**结算为 ABANDONED（"no result after 45 minutes"），
  距本次运行仅约 13 分钟 → 仍在 900s 冷却窗口内，故本轮 candidates 为空（属**临时冷却**型 submit 0）。
- 收尾：pending=6、answered=1、in flight=none；6 条待答问题全部 "no job"。
  attempts：1add7d8e=1（唯一未封死者，冷却过后可重试）、其余 5 条（b2e886bd/23759997/78694f1b/cb5386d4/b860b24a）=2/2 永久退出候选。
- 下次预期：约 18:40:52 GMT+8 后 1add7d8e 冷却解除，若届时无在飞 job 应被派发为 retry 2（attempts→2/2）。

### 2026-09-23 19:40 (GMT+8) / 11:40 UTC
- 网关：up（可达）。
- reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；submitted: 0，输出 "nothing to do"（无 skipped）。
- 台账尾部：上轮在飞 job `d8904101`（问题 `unknown__control_1add7d8e`，11:26:12 UTC / 19:26:12 GMT+8
  由其它进程以 retry 2 派发后）已被**其它进程**结算为 ABANDONED（"no result after 45 minutes"），
  距本次运行约 13 分钟 → 仍在 900s 冷却窗口内，故本轮 candidates 为空。
- 但因 1add7d8e 的 attempts 已随这次派发升到 **2/2**，即使冷却过期也不会再被派发：
  本轮 submit 0 实为**永久封死**型（冷却只是叠加因素）。
- 收尾：pending=6、answered=1、in flight=none；6 条待答问题全部 "no job"，
  attempts 全为 2/2（1add7d8e/b2e886bd/23759997/78694f1b/cb5386d4/b860b24a）→ 候选归零。
- 判断：通道重回全面静默，自动化重跑无产出能力，需人工介入排查 job 侧 45 分钟不落盘的根因。

### 2026-09-23 20:40 (GMT+8) / 12:40 UTC
- 网关：up（可达）。
- reconcile: checked=1 done=0 failed=0 lost=0 abandoned=0；submitted: 0，
  skipped 两条（均为 `(in-flight limit reached)`）：`unknown__control_8cc661a7`、`unknown__control_23759997`。
- 在飞 job 为 `06066de6`（问题 `unknown__control_78694f1b` / UNKNOWN::对战 / goal=INTEL），
  12:17:56 UTC（20:17:56 GMT+8）由**其它进程**以 reason=retry 3 派发，本次追到时约 22 分钟 → 未过 45 分钟阈值，无结算。
- 收尾：pending=7、answered=1、in flight=['06066de6']。
  新增第 7 条 pending `unknown__control_8cc661a7`（UNKNOWN::平庸, goal=EXPLORATION, attempts=0 未派发）。
- **重要更正**：23759997 不再是"永久封死"——`--state` 显示其 attempts=2，但 dry-run 给出 `retry 3`，
  且本轮它是作为**有效候选**被 quota skip 的（说明外部进程重置/推进过其状态）。此前"全通道 attempts=2/2 永久静默"的结论已失效：
  目前除 78694f1b（attempts=3，在飞）外，8cc661a7、23759997 都是可派发候选，仅被 MAX_IN_FLIGHT=1 挡住。
- 下次预期：06066de6 落盘或超时结算后释放配额，8cc661a7 与 23759997 中应有一个被派发。

### 2026-09-23 21:41 (GMT+8) / 13:41 UTC
- 网关：up（可达）。
- reconcile: checked=1 done=0 failed=0 lost=0 abandoned=0；submitted: 0，
  skipped 一条：`unknown__control__23759997 (in-flight limit reached)`。
- 在飞 job 换成了 `64f2f709`（问题 `unknown__control_8cc661a7` / UNKNOWN::平庸 / goal=EXPLORATION），
  系其它进程派发；上轮在飞的 `06066de6`（78694f1b）已被更早结算，78694f1b attempts 升到 3。
  本次追到的 64f2f709 仍 working（未过 45 分钟），故无结算。
- 收尾：pending=7、answered=1、in flight=['64f2f709']。
  attempts：b6546e80=1（已答）、8cc661a7=1（在飞）、23759997=2、78694f1b=3、cb5386d4=2、
  b860b24a=2、b2e886bd=2、1add7d8e=2。
- 23759997 仍是有效候选（dry-run 给 retry 3），被 MAX_IN_FLIGHT=1 配额挡住（第三类 submit 0），非封死。
- 下次预期：64f2f709 落盘或超时释放配额后，23759997 应被派发为 retry 3。

### 2026-09-23 22:42 (GMT+8) / 14:42 UTC
- 网关：up（可达）。
- reconcile: checked=1 done=0 failed=0 lost=0 abandoned=0；submitted: 0，
  skipped 一条：`unknown__control__23759997 (in-flight limit reached)`。
- 在飞 job 换成 `d1caa8e7`（问题 `unknown__control_8cc661a7` / UNKNOWN::平庸 / goal=INTEL），
  系其它进程派发；上轮在飞的 `64f2f709` 已结算，8cc661a7 attempts 升到 2。本次追到的 d1caa8e7 仍 working
  （未过 45 分钟）→ 无结算。
- 收尾：pending=7、answered=1、in flight=['d1caa8e7']；7 条待答问题中仅 8cc661a7 有 job，其余 6 条 "no job"。
- 23759997 仍是**有效候选**（`--state` 的 would-be-submitted 给出 retry 3），被 MAX_IN_FLIGHT=1 挡住
  → 第三类 submit 0（配额占用），非冷却、非封死。
- 下次预期：d1caa8e7 落盘或超时结算释放配额后，23759997 应被派发为 retry 3。

### 2026-09-23 23:42 (GMT+8) / 15:42 UTC
- 网关：up（可达）。
- reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；submitted: 0，输出 "nothing to do"（无 skipped）。
- 台账尾部（**其它进程**，发生在本轮之前）：`8cc661a7` 的 job `d1caa8e7` 于 15:22:45 UTC 记 ABANDONED，
  紧接着 15:22:46 UTC 派发 `23759997` 的 job `0c32a4bd`（retry 3，attempts→3），
  该 job 于 15:29:03 UTC 记 **failed**（"no answer written"）——**快速失败**，距本次运行约 14 分钟。
- 收尾：pending=7、answered=1、in flight=none。
  attempts：23759997=3、78694f1b=3、cb5386d4/b860b24a/b2e886bd/1add7d8e/8cc661a7=2、b6546e80=1（已答）。
- 新增观察：结算并非只有 45 分钟 ABANDONED 一种，**job 侧 "no answer written" 会在约 6 分钟内以 failed 快速结算**
  （区别于挂满 45 分钟的 ABANDONED）。另：23759997、78694f1b 的 attempts 已超 MAX_ATTEMPTS(2) 到 3，
  说明**外部进程会推进该上限**，此前"attempts≥2 即永久封死"的判据须以实跑 `skipped` 为准。
- 下次预期：23759997 在 900s 冷却过后（约 15:39 UTC 起）应可被派为 retry 4，等待配额与冷却均空闲时派发。

### 2026-09-24 00:44 (GMT+8) / 16:44 UTC
- 网关：up（可达）。
- reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；submitted: 0，输出 "nothing to do"（无 skipped）。
- 台账尾部（**其它进程**，发生在本轮之前）：`8cc661a7` 的 job `b25c1f12`（16:29:18 UTC 以 retry 3 派发）
  于 16:40:58 UTC 记 **failed**（"no answer written"，快速失败），距本次运行仅约 3 分钟
  → 仍在 900s 冷却窗口内 → 第四类 submit 0（干净 "nothing to do"）。
- 收尾：pending=7、answered=1、in flight=none；7 条待答问题全部 "no job"。
  attempts：23759997=3、78694f1b=3、8cc661a7=3、cb5386d4/b860b24a/b2e886bd/1add7d8e=2、b6546e80=1（已答）。
- 下次预期：约 16:55 UTC 后冷却解除，若配额空闲，8cc661a7/23759997 等应被派为 retry 4。

### 2026-09-24 01:44 (GMT+8) / 17:44 UTC
- 网关：**health 显示 up，但作业端点实际拒收**（见下）。reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；
  submitted: 0，输出 "nothing to do"（无 skipped）；dry-run 亦为 "nothing to submit"。
- 本次 submit 0 属**第四类（900s 冷却）**：台账末条为 17:34:47 UTC 的 `submit_failed`
  （`unknown__control__23759997`，note=HTTP 500 INTERNAL_ERROR + safe-delete BULK_CONFIRM），
  距本轮仅约 9.8 分钟 → 仍在冷却窗口内，故 candidates 为空。
  `unknown__control__8cc661a7` 的 `submit_failed` 在 17:25:41 UTC（HTTP 401 AUTH_REQUIRED），
  其后的 17:33:41 `reclassified` 也刷新过 updated_at → 同样在冷却内。
- **新发现（重要）**：派发失败的根因不在问题本身而在网关侧——17:25:41 得 **HTTP 401 AUTH_REQUIRED**
  （`POST /api/v1/jobs`），17:34:47 得 **HTTP 500 INTERNAL_ERROR**（safe-delete 需批量确认）。
  即 `--state` 的 "gateway up" 只探活，不代表 jobs 端点可用；自动化重跑能否派发取决于鉴权与网关内部状态。
- 另：17:33:41 两条 `reclassified` 把 `8cc661a7/b25c1f12` 与 `23759997/0c32a4bd` 的失败归类为
  **WORKER_DIED**（作业 worker 进程启动即崩溃，日志记录 `Cannot find module '../dist/codebuddy'`），
  明确"不由问题预算承担"——这解释了此前多轮 failed 并非顾问侧问题。
- 收尾：pending=7、answered=1、in flight=none；7 条待答问题**全部 no job**。
  attempts：b6546e80=1（已答）、23759997=3、78694f1b=3、8cc661a7=3、
  cb5386d4/b860b24a/b2e886bd/1add7d8e=2。
- 下次预期：约 17:49:47 UTC（01:49 GMT+8）后冷却解除；若届时网关鉴权已恢复，23759997/8cc661a7
  应被派为 retry 4，否则仍会 `submit_failed`。

### 2026-09-24 02:45 (GMT+8) / 18:45 UTC
- 网关：up（可达，`--state` 探活通过）。
- reconcile: checked=1 done=0 failed=0 lost=0 abandoned=0；submitted: 0（无 skipped，干净 "nothing to do"）。
- 在飞 job `a462d931`（问题 `unknown__control__23759997` / UNKNOWN / goal=EXPLORATION）由**其它进程**
  于 18:21:15 UTC 以 retry 4 派发，本次追到时约 24 分钟 → 未过超时阈值，无结算。
- candidates 为空的两个叠加原因（用只读脚本调 `candidates()/orphans()/health()` 判定，未改任何文件）：
  ① MAX_IN_FLIGHT=1 配额被 a462d931 占满；② `8cc661a7` 虽"欠一次 job"，但连续 2 次 WORKER_DIED 使
  冷却按 `900s × (1+2)` 放大到 **2700s**，其末事件 18:12:25 UTC 距本轮仅 ~33 分钟 → 仍在冷却内。
- **通道自评 DEGRADED**（`health()`：连续 2 次 worker 未启动，reason=WORKER_DIED）。
- orphans（预算已花光、需人工介入的 5 条）：78694f1b（answer 3/2）、1add7d8e（2/2）、
  b2e886bd（2/2）、cb5386d4（2/2）、b860b24a（帧文件已不存在，无法作答）。
- 收尾：pending=7、answered=1、in flight=['a462d931']；attempts 23759997=4、78694f1b=3、8cc661a7=3、
  cb5386d4/b860b24a/b2e886bd/1add7d8e=2、b6546e80=1（已答）。
- 下次预期：a462d931 落盘或超时结算后释放配额；8cc661a7 约 18:57 UTC（02:57 GMT+8）冷却解除才是候选。

### 2026-09-24 03:47 (GMT+8) / 19:47 UTC
- 网关：up（可达）。reconcile: checked=1 done=0 failed=0 lost=0 abandoned=0；submitted: 0，输出干净 "nothing to do"（无 skipped）。
- 在飞 job `9f3b53b8`（问题 `unknown__control__8cc661a7` / UNKNOWN::平庸 / goal=TRAIN, retry 4）由**其它进程**
  于 19:06:55 UTC 派发，本次追到时约 40 分钟 → 未过 45 分钟阈值，无结算。
- 用只读探测确认 **candidates=[]** 的真实理由：7 条 pending 中 6 条已是 orphan
  （23759997 answer 3/2+death 1/3、78694f1b 3/2、b2e886bd 2/2、cb5386d4 2/2、1add7d8e 2/2、b860b24a 帧文件已不存在），
  唯一未封死的 8cc661a7 因 `record.open`（已有在飞 job）被跳过 → 故既无候选也无 skipped。
- `health()` = **OK**（consecutive_worker_deaths=0），不再是上轮的 DEGRADED；说明 worker 起不来的环境故障已消失，
  当前瓶颈只剩"候选预算全部花光 + 唯一可派的一条占着 in-flight 槽"。
- 收尾：pending=7、answered=1、in flight=['9f3b53b8']；attempts 8cc661a7=4、23759997=4、78694f1b=3、其余 4 条=2。
- 下次预期：9f3b53b8 落盘则 8cc661a7 记 done（通道真正清零候选，需人工/外部新增问题）；
  若超时结算，则 attempts→5，届时**全部 7 条 pending 均为 orphan**，自动化彻底无产出。

### 2026-09-24 04:48 (GMT+8) / 20:48 UTC
- 网关：up（可达）。reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；submitted: 0，干净 "nothing to do"（无 skipped）。
- 候选为空的原因**不是冷却也不是配额**：in flight=none，且 7 条 pending **全部已是 orphan**（只读探测 candidates=[]、
  orphans 返回 7 条）。`health()`=OK（consecutive_worker_deaths=0），故障态已消退。
- 台账尾部：上轮在飞的 `9f3b53b8`（8cc661a7, retry 4）已于 19:54:40 UTC 记 ABANDONED（"no result after 45 minutes"），
  attempts→4，8cc661a7 随之进入 orphan 名单。
- 收尾：pending=7、answered=1（仅 b6546e80）、in flight=none；attempts 8cc661a7=4、23759997=4、78694f1b=3、其余 4 条=2。
- 判断：**自动化通道已彻底无产出能力**——无在飞 job、无候选、无冷却/quota 可等，全部预算花光（含 b860b24a 帧文件已不存在）。
  需人工重置预算或外部新增问题才能恢复。

### 2026-09-24 05:49 (GMT+8) / 21:49 UTC
- 网关：up（可达）。reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；submitted: 0，干净 "nothing to do"（无 skipped）。
- 与 04:48 轮判断完全一致：in flight=none，7 条 pending **全部 orphan**（只读探测 candidates=[]；orphans 7 条：
  23759997/8cc661a7 各 attempts 4（answer 3/2、death 1/3）、78694f1b 3（3/2）、cb5386d4/b2e886bd/1add7d8e 各 2（2/2）、
  b860b24a 帧文件已不存在）；`health()`=OK（consecutive_worker_deaths=0）。
- 收尾：pending=7、answered=1（仅 b6546e80）、in flight=none。
- 结论不变：自动化通道无产出能力，无冷却 / 无配额可等，需人工重置预算或外部新增问题才可能恢复。

### 2026-09-24 06:49 (GMT+8) / 22:49 UTC
- 网关：up（可达）。reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；submitted: 0，干净 "nothing to do"（无 skipped）。
- 与 04:48 / 05:49 两轮完全一致：in flight=none，7 条 pending **全部 orphan**（只读探测 candidates=[]；
  orphans 7 条：23759997/8cc661a7 各 attempts 4、78694f1b 3、cb5386d4/b2e886bd/1add7d8e 各 2、b860b24a 帧文件已不存在）；
  `health()`=OK（consecutive_worker_deaths=0）。
- 收尾：pending=7、answered=1（仅 b6546e80）、in flight=none。结论不变：无冷却 / 无配额可等，通道无产出能力，
  需人工重置预算或外部新增问题才可能恢复。

### 2026-09-24 07:51 (GMT+8) / 23:51 UTC(09-23)
- 网关：up（可达）。reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；submitted: 0，干净 "nothing to do"（无 skipped）。
- 与 04:48 / 05:49 / 06:49 三轮完全一致：in flight=none，7 条 pending **全部 orphan**（只读探测 candidates=[]；
  orphans 7 条：8cc661a7/23759997 各 attempts 4（answer 3/2、death 1/3）、78694f1b 3（3/2）、
  cb5386d4/b2e886bd/1add7d8e 各 2（2/2）、b860b24a 帧文件已不存在）；`health()`=OK（consecutive_worker_deaths=0）。
- 收尾：pending=7、answered=1（仅 b6546e80）、in flight=none。结论不变：无冷却 / 无配额可等，通道无产出能力，
  需人工重置预算或外部新增问题才可能恢复。

### 2026-09-24 08:53 (GMT+8) / 00:53 UTC
- 网关：up（可达）。reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；submitted: 0，干净 "nothing to do"（无 skipped）。
- 与 04:48 起的连续多轮完全一致：in flight=none，7 条 pending **全部 orphan**（只读探测 candidates=[]；orphans 7 条：
  8cc661a7/23759997 各 attempts 4（answer 3/2、death 1/3）、78694f1b 3（3/2）、cb5386d4/b2e886bd/1add7d8e 各 2（2/2）、
  b860b24a 帧文件已不存在）；`health()`=OK（consecutive_worker_deaths=0）。
- 收尾：pending=7、answered=1（仅 b6546e80）、in flight=none。结论不变：无冷却 / 无配额可等，通道无产出能力，
  需人工重置预算或外部新增问题才可能恢复。

### 2026-09-24 10:02 (GMT+8) / 02:02 UTC
- 网关：up（可达）。reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；submitted: 0，干净 "nothing to do"（无 skipped）。
- 与 04:48 起的连续多轮完全一致：in flight=none，7 条 pending **全部 orphan**（只读探测 candidates=[]；
  orphans 7 条：8cc661a7/23759997 各 attempts 4（answer 3/2、death 1/3）、78694f1b 3（3/2）、
  cb5386d4/b2e886bd/1add7d8e 各 2（2/2）、b860b24a 帧文件已不存在）；`health()`=OK（consecutive_worker_deaths=0）。
- 收尾：pending=7、answered=1（仅 b6546e80）、in flight=none。结论不变：无冷却 / 无配额可等，通道无产出能力，
  需人工重置预算或外部新增问题才可能恢复。

### 2026-09-24 11:04 (GMT+8) / 03:04 UTC —— 通道已被**正式退役**
- 网关：up（可达）。reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0。
- **submitted: 0，且原因不是冷却/配额/预算，而是配置级退役**：实跑首行输出
  `submitted   : 0 (WORKBUDDY_CHANNEL_RETIRED -- config/v2.json workbuddy_channel.enabled=false)`，
  并打印 `retired     : WORKBUDDY_CHANNEL_RETIRED` 与
  `note: answers are planned locally, inside the cycle (winter_agent_v2/ui_planner.py); this pass only reconciled.`
- `config/v2.json → workbuddy_channel` 现为：
  `enabled=false, retired_at=2026-09-25, auto_submit_jobs=false, auto_escalate=false, answer_production=LOCAL_QWEN`；
  note 引述"操作者指令 2026-09-25 第 1 节：自动 WorkBuddy 模型调用通道从生产链路退役，WorkBuddy 只作为人工手动驱动的工具"，
  代码（workbuddy_bridge / unknown_dispatch / gateway_service 及其测试）因被其它路径 import 而保留，
  失败记录另存 `knowledge/failure_patterns/integration/WORKBUDDY_CHANNEL_RETIRED.md`。
- 收尾：pending=7、answered=1（仅 b6546e80）、in flight=none；7 条待答问题全部 "no job"。
  attempts：23759997=4、8cc661a7=4、78694f1b=3、cb5386d4/b860b24a/b2e886bd/1add7d8e=2、b6546e80=1（已答）。
- **结论（重要）**：本自动化的任务本身已失效——派发在配置层被硬关闭，此后每轮必然 `submitted: 0` +
  `WORKBUDDY_CHANNEL_RETIRED`，只保留 reconcile（当前 in flight=none，连 reconcile 也无事可做）。
  建议**停用本自动化**，或改为纯 `--state` 巡检（若仍需盯 pending 台账）。回收配额/重置 attempts 已无意义。

### 2026-09-24 12:07 (GMT+8) / 04:07 UTC —— 退役后第 2 轮，纯复核
- 网关：可达。reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；submitted: 0，
  原因仍是配置级退役：首行 `WORKBUDDY_CHANNEL_RETIRED -- config/v2.json workbuddy_channel.enabled=false`，
  并打印 `retired     : WORKBUDDY_CHANNEL_RETIRED` 与 "this pass only reconciled"；末尾 "nothing to do"。
- 与 11:04 轮完全一致，无新事件、无在飞 job。收尾：pending=7、answered=1（仅 b6546e80）、in flight=none。
- 结论不变：本任务的派发能力已在配置层硬关闭，重跑只会复读退役标记，建议停用本自动化或改纯 `--state` 巡检。

### 2026-09-24 13:09 (GMT+8) / 05:09 UTC —— 退役后第 3 轮，纯复核
- 网关：可达。reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；submitted: 0，
  原因仍是配置级退役（`WORKBUDDY_CHANNEL_RETIRED -- config/v2.json workbuddy_channel.enabled=false`，
  note="this pass only reconciled"，末尾 "nothing to do"）。
- 与 11:04 / 12:07 两轮完全一致，无在飞 job、无新事件；收尾 pending=7、answered=1、in flight=none。
- 结论不变：派发能力已在配置层硬关闭，重跑只会复读退役标记；建议停用本自动化。

### 2026-09-24 14:09 (GMT+8) / 06:09 UTC —— 退役后第 4 轮，纯复核
- 网关：可达。reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；submitted: 0，
  原因仍是配置级退役（`WORKBUDDY_CHANNEL_RETIRED -- config/v2.json workbuddy_channel.enabled=false`，
  note="this pass only reconciled"，末尾 "nothing to do"）。
- 与 11:04 / 12:07 / 13:09 三轮完全一致，无在飞 job、无新事件；收尾 pending=7、answered=1、in flight=none。
- 结论不变：派发能力已在配置层硬关闭，重跑只会复读退役标记；建议停用本自动化。

### 2026-09-24 15:10 (GMT+8) / 07:10 UTC —— 退役后第 5 轮，纯复核
- 网关：可达。reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；submitted: 0，
  原因仍是配置级退役（`WORKBUDDY_CHANNEL_RETIRED -- config/v2.json workbuddy_channel.enabled=false`，
  note="this pass only reconciled"，末尾 "nothing to do"）。
- 与 11:04 / 12:07 / 13:09 / 14:09 四轮完全一致，无在飞 job、无新事件；
  收尾 pending=7、answered=1（仅 b6546e80）、in flight=none，7 条"no job"。
- 结论不变：派发能力已在配置层硬关闭，重跑只会复读退役标记；建议停用本自动化（已连续 5 轮零产出）。

### 2026-09-24 16:11 (GMT+8) / 08:11 UTC —— 退役后第 6 轮，纯复核
- 网关：可达。reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；submitted: 0，
  原因仍是配置级退役（`WORKBUDDY_CHANNEL_RETIRED -- config/v2.json workbuddy_channel.enabled=false`，
  note="this pass only reconciled"，末尾 "nothing to do"）。
- 与 11:04 起的五轮完全一致，无在飞 job、无新事件；收尾 pending=7、answered=1、in flight=none。
- 结论不变：派发能力已在配置层硬关闭，重跑只会复读退役标记；已连续 6 轮零产出，建议停用本自动化。

### 2026-09-24 17:12 (GMT+8) / 09:12 UTC —— 退役后第 7 轮，纯复核
- 网关：可达。reconcile: checked=0 done=0 failed=0 lost=0 abandoned=0；submitted: 0，
  原因仍是配置级退役（`WORKBUDDY_CHANNEL_RETIRED -- config/v2.json workbuddy_channel.enabled=false`，
  note="this pass only reconciled"，末尾 "nothing to do"）。
- 与 11:04 起的六轮完全一致，无在飞 job、无新事件、无 pending 变化；结论不变：
  派发能力已在配置层硬关闭，重跑只会复读退役标记；已连续 7 轮零产出。

### 2026-09-24 17:39 (GMT+8) —— **本自动化被停用（PAUSED）**
- 操作者要求清理"仍在周期性触发的旧 WorkBuddy 通道任务"。定位结论：**本自动化
  `404bbf18`（hourly）就是 `tools/unknown_ai_worker.py --once` 唯一周期性触发源。**
  排除：OS 计划任务只有 `WinterAgentV2Panel`（启动生产面板，非 worker）、启动夹只有 Ollama、
  `.git/hooks` 空、仓库内无任何脚本调用 `--loop`；面板进程内 tick 已是 reconcile-only
  （`worker(submit=_workbuddy_channel_enabled(root))`，且运行中的面板加载的是 09-24 10:22 后带门的代码）。
- 处置：置为 **PAUSED**（保留任务定义与 memory.md 历史，重启后不再触发）。
  **此后本 memory.md 不再新增轮次记录**；如需手工结算 UNKNOWN 旧账，改为人在终端跑
  `tools/unknown_ai_worker.py --state / --once`（能力完好保留）。
- 未答问题已由本地 Qwen 在周期内接手（`ui_planner.ManagedAdvisor`，`local_planner.enabled=true`，
  探活 REACHABLE）；`local_planner_steps.jsonl` 中 `UNKNOWN::平庸` 的首次本地决策
  （09-24T03:04:58Z）即退役后约 1 分钟。
- 遗留需人工决定（未处理）：升级队列两条能力终态 BLOCKED（`READ_DAILY_PROGRESS`、`SAFE_STOP`，
  repair budget 2/2 花光），对应 goal 在快照中 `BLOCKED|ESCALATION_QUEUE`。

## 复用要点
- 判断"提交 0 个"是真无事可做还是被限流：看 `--state` 的 attempts/in flight，再看台账
  `learning/unknown_dispatch.jsonl` 尾部事件的 `at` 时间与 900s 冷却的关系。
- **两种"submit 0"要分清**：`attempts >= MAX_ATTEMPTS_PER_REQUEST(2)` 是**永久封死**（改 attempts 才能救）；
  `failed_at` 在 900s 内是**临时冷却**（等即可）。仅看 --dry-run 的 "nothing to submit" 分不出这两者。
- reconcile 的 checked 计数只反映**本次运行时刻仍在追踪的 job**；job 若已被更早的一轮结算掉，
  本次会显示 checked=0，这属正常，不代表丢失。
- `--dry-run` 输出 "nothing to submit" 只表示 candidates 为空，不区分"已有答案"和"冷却中"，
  不要据此断言通道空闲。
- **第三种"submit 0"**：`MAX_IN_FLIGHT = 1` 是**全局**配额，任意一条问题有 job 在飞，
  其余候选就会被 skip 并打印 `(in-flight limit reached)`。这**不是**被限流/封死，等 job 结算即可。
  注意 `--dry-run` 的 "would be submitted now" 会无视配额把候选列出来，可能与实跑结果不一致，
  务必以实跑输出的 `skipped` 为准。
- **第四种"submit 0"（新增）**：900s 冷却会挡住"刚被结算"的问题，此时**连 `skipped` 都不打印**，
  表现为干净的 "nothing to do"。判断办法仍是比对台账尾事件的 `at` 与当前 UTC 时间的差值。
- **第五种"submit 0"（2026-09-24 新增，代码已改写）**：候选判据现在是"两本预算"制——
  `answer_failures < max_attempts + (重问 ? 1 : 0)` 或 `worker_deaths < MAX_WORKER_DEATH_ATTEMPTS`；
  且冷却为 `DISPATCH_COOLDOWN_SECONDS × (1 + consecutive_worker_deaths)`，连续 WORKER_DIED 会把
  900s 放大成 2700s（2 次）乃至更久。所以"末事件过去 900s"已不足以判定候选已就绪，必须乘以死亡次数。
- **`--state` / `--dry-run` 看不到候选被拒的真实理由**：直接跑只读脚本
  `UnknownDispatcher().orphans()`（列出预算花光、需人工介入的问题及原因）与 `.health()`
  （DEGRADED 表示 worker 起不来）才能定性。这两者纯读，不改文件。
- **结算有快慢两路**：`failed`（job 侧 "no answer written"，约 6 分钟内）与 `ABANDONED`（挂满 45 分钟）。
  前者会把 attempts 快速推高；且外部进程会重置/推进 MAX_ATTEMPTS，故 attempts 数值不能单独作为封死判据，
  必须以同轮实跑的 `skipped` 输出为准。
- **第六种"submit 0"（2026-09-24 03:47 新增）**：`candidates()` 为空且无 skipped 打印，**不代表在冷却**。
  只要每条 pending 要么 `record.open`（已有在飞 job）、要么已进 `orphans()`（预算花光 / 帧文件不存在），
  候选就为空。判定命令（纯只读，不改文件）：
  `python -c "from winter_agent_v2.unknown_dispatch import UnknownDispatcher as D; d=D(); print(d.candidates()); print([o[1] for o in d.orphans()]); print(d.health())"`
  —— `candidates()` 返回 `(UnknownRequest, why)` 元组列表；`orphans()` 同样是元组，第二项是可读的原因串。
