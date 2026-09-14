# Reward Claim Research

This research is deliberately just-in-time: it covers the reward surfaces observed in the current client, not every red dot in Whiteout Survival.

The live client proved that a red dot is only a notification prior. Mail attachments, Daily/Growth task controls, Alliance gift batches, event free-track controls, and the Exploration idle chest produced verifiable rewards. Alliance War, Territory migration, Pet Skills, Chief Orders, merchant refreshes, and event-entry actions were notifications or available actions rather than unclaimed rewards, so they were inspected and left untouched.

Official support states that unclaimed Daily Mission rewards may be delivered through Mail the next day. The current client is the operational truth: every mail tab is processed independently and attachment-bearing mail must show reward feedback. A report can be unread without carrying a reward.

Public WOS automation projects independently list Mail Rewards and Exploration Idle Income/Exploration Chests. V2 retains only the capability decomposition: recognize exact page → recognize enabled claim state → perform bounded claim → require reward feedback → require post-state change. Their architecture, coordinates, accounts, and assets are not imported.

Live mail evidence covered War, Alliance, System, and Report tabs. The initial batch included gems, shards, speedups, resources, and keys; an incremental Alliance mail yielded five Fire Crystals. All tab badges were then cleared. New mail can arrive during a run, so the loop is bounded rather than chasing a permanently moving global badge.

Live Exploration evidence covered a full nine-hour idle-income claim. The reward screen showed 29,000 Steel, 80,000 Hero EXP, and three gear items; re-entry showed a disabled claim control. This is one verified cycle, not a Stable skill.
