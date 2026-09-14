# Skill Catalog

`GATHER_RESOURCE`, `BUILDING_UPGRADE`, `TRAIN_TROOPS` (Infantry variant), `BEAST_HUNT`, the tested Intel flow, Daily claims, Alliance Technology contribution, Alliance Gifts, Mail rewards, and Exploration idle income are `VERIFIED`. `RESEARCH` remains queue-blocked. No skill is `STABLE` yet.

| Skill | Purpose | Current execution |
|---|---|---|
| CLOSE_POPUP | Close a blocking popup without accepting it | VERIFIED live |
| BACK | Return one game-navigation level without pixel coordinates | VERIFIED live; Alliance Gifts→Alliance→HOME |
| OPEN_MAP | Navigate from city to map | VERIFIED live |
| OPEN_HOME | Navigate from world map to city using the in-game control | VERIFIED live; replaces unsafe Android BACK-on-MAP behavior |
| SEARCH_RESOURCE | Open resource search | VERIFIED live through semantic Executor |
| SELECT_RESOURCE | Select requested resource | VERIFIED live for WOOD |
| SUBMIT_RESOURCE_SEARCH | Locate configured resource node | VERIFIED live through Scheduler |
| START_GATHER | Open march selection from available node | VERIFIED live through Scheduler |
| CHECK_MARCH | Observe march capacity | VERIFIED for current role calibration |
| DISPATCH_MARCH | Dispatch selected march | VERIFIED live through Scheduler |
| VERIFY_GATHERING | Confirm gathering/return lifecycle | VERIFIED live |
| GATHER_RESOURCE | Composite P0 capability | VERIFIED, 3/3 consecutive completed natural cycles; four bounded unattended dispatch starts verified; 6/6 queue guard passed |
| BUILDING_UPGRADE | Start a valid normal-resource building upgrade | VERIFIED live, Warehouse 26→27 |
| RESEARCH | Start a technology when its queue is available | BLOCKED: live Growth queue is running 病房扩建VII 2/3; rechecked with 5d00:55:44 remaining |
| TRAIN_TROOPS | Train/promote Infantry, Lancer, or Marksman | VERIFIED live for Infantry T10, 1/1; 806 units; timer 10:03:12 |
| OPEN_INTEL | Open Lighthouse Intel from world-map HUD | VERIFIED live |
| SELECT_INTEL_BEAST_MISSION | Select a current-client blue, purple, or orange paw Beast Intel pin | VERIFIED live, multiple colors and positions |
| SELECT_INTEL_FIREBEAST_MISSION | Select a current-client Firebeast Intel pin | VERIFIED live, 2/2 completed and claimed |
| SELECT_INTEL_RESCUE_SURVIVORS | Select a current-client Rescue Survivors Intel pin | VERIFIED live, 1/1 completed and claimed |
| OPEN_INTEL_RESCUE_SURVIVORS_TARGET | Open the reviewed Rescue Survivors target | VERIFIED live |
| EXECUTE_INTEL_RESCUE_SURVIVORS | Start Rescue Survivors after verifying its displayed 12-stamina cost | VERIFIED live |
| OPEN_INTEL_BEAST_TARGET | Open the reviewed Intel world target | VERIFIED live |
| INTEL_BEAST_START_MARCH | Open formation for the level-22 target | VERIFIED live; victory-assured gate required |
| DISPATCH_INTEL_BEAST | Dispatch verified Intel Beast formation | VERIFIED live |
| INTEL_CLAIM_REWARDS | Claim completed Lighthouse Intel rewards | VERIFIED live, 10 ordinary Beast, 2 Firebeast, and 1 Rescue Survivors claims plus prior claim evidence |
| DISMISS_INTEL_REWARD | Dismiss variable reward overlay and restore Intel page | VERIFIED live |
| INTEL | Type-specific Lighthouse task flow | VERIFIED for 10 ordinary Beast, 2 Firebeast, and 1 Rescue Survivors completions; Hero Journey and Master Bounty are correctly separated and blocked; not stable |
| BEAST_HUNT | Defeat a normal wilderness Beast | VERIFIED live; emergency stamina pass completed four low-level hunts, including one native V2 runtime dispatch; not stable |
| DAILY_HERO_RECRUIT | Complete and claim a free-recruit daily | VERIFIED live, 1/1; activity 270→280 |
| DAILY_CLAIM_REWARDS | Claim one or more completed Daily tasks | VERIFIED live, 3/3; includes Alliance task 3/5→5/5 and activity 65→70 |
| ALLIANCE_TECH_CONTRIBUTE | Contribute normal resources to recommended Alliance Technology | VERIFIED live, 5/5 across two sessions; Meat 50,000; contribution 49,080→50,040 |
| ALLIANCE_HELP | Help alliance members | BLOCKED/NOT_AVAILABLE: live Auto Help is active; this is not a failure |
| ALLIANCE_GIFTS | Claim free Victory Loot gifts | VERIFIED live, 2/3; one game-day reset interruption recovered |
| ALLIANCE_ALLY_GIFT_CLAIM | Claim existing free Ally Gifts | VERIFIED live, 9/9; eight actions used the Brain→Scheduler→Skill→Executor chain |
| MAIL_CLAIM_REWARDS | Read each mail tab and claim attached rewards | VERIFIED live; initial and incremental passes; latest attachment yielded 5 Fire Crystals; all tab badges cleared |
| OPEN_MAIL | Navigate from current-client Home to Mail | VERIFIED live through Scheduler |
| SELECT_MAIL_ALLIANCE_TAB | Select Alliance mail only when its red badge is detected | VERIFIED live |
| SELECT_MAIL_SYSTEM_TAB | Select System mail only when its red badge is detected | VERIFIED live |
| SELECT_MAIL_REPORT_TAB | Select Report mail only when its red badge is detected | VERIFIED live |
| DISMISS_MAIL_REWARD | Dismiss the verified Mail reward overlay | VERIFIED live |
| EXPLORATION_IDLE_CLAIM | Claim accumulated Exploration idle income | VERIFIED live, 1/1; 9-hour income; post-claim control disabled |

`SAFE_STOP` is a scheduler outcome, not a skill. The bounded `LiveRuntime` only executes allowlisted skills with an explicit post-action Verifier; current live-loop support starts with `ALLIANCE_ALLY_GIFT_CLAIM`. Intel's Beast variant and three DAILY claim cycles are verified; other variants remain candidate. Code existence alone never promotes a skill.
