# DAILY — Just-in-Time Skill Research

Status: `VERIFIED` for three live claim cycles (3/3) across three task variants; not `STABLE`.

## External prior

- Century Games' help center states daily missions refresh at midnight UTC for the referenced mission system and that unclaimed rewards may be mailed. The live client countdown remains the operational source of truth.
- The current App Store update notes activity-point optimization for building, research, and Arena daily tasks, confirming that task values can change with updates.
- Public WOS automation projects include mission-reward collection and completion logs. V2 keeps only the useful decomposition: read progress → navigate to the exact task → execute an allowed action → return → claim → verify activity delta.

## Live verified task

At 270 activity, all milestone chests through 270 were already claimed and 325 was not available. The list showed `完成1次英雄招募 (0/1)`. `前往` opened Hero Recruitment with a green `招募1次 免费` control and five free recruits.

After one free recruitment:

- recruit reward feedback appeared;
- daily progress changed to `1/1` and became claimable;
- claiming returned 10 activity, 800 coal, and 200 iron;
- activity changed `270 → 280`;
- the claim control cleared and the next repeat task became `完成3次英雄招募 (1/3)`.

No key, gem, or real-money spend occurred. `verify_daily_hero_recruit` requires all six observed phases and the exact +10 activity delta.

## Live verified multi-claim

The Daily page showed three completed tasks at 0 activity: daily login, one Alliance Help, and training ten Infantry. The one-key claim produced a visible reward result (65 activity, 28,000 meat, 800 coal, and 200 iron), opened the 40-point milestone, and returned to Daily with activity `0 → 65` and no remaining claim controls.

`verify_daily_claim` requires the reward popup, a positive activity delta matching the displayed activity reward, and `claimable_count` changing from positive to zero. This also provides live cross-skill evidence that Alliance Help and Infantry Training updated Daily state. No premium currency or real-money action occurred.

## Alliance contribution task chain

At activity 65, Daily showed `完成联盟捐献5次 (3/5)`. The task route led to Alliance Technology. Two normal-resource contributions spent 20,000 Meat, reduced attempts `25→23`, produced visible +120 and critical +240 receipts, and changed personal contribution `49,680→50,040`. Returning to Daily showed `5/5 CLAIMABLE`; claiming awarded 5 activity and 4,000 Wood, changed activity `65→70`, cleared the claim, and advanced the repeat tier to `完成联盟捐献20次 (5/20)`.

`verify_alliance_daily_chain` requires both Alliance attempt/reward/counter transitions and both Daily progress/activity/tier transitions. This is Production evidence of one Skill making another Skill ready and the Scheduler-compatible follow-up completing it.
