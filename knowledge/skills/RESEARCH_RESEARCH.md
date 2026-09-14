# RESEARCH — Just-in-Time Skill Research

Status: `BLOCKED` (live queue busy; capability not claimed as successful)

## External prior

- Whiteout Survival Wiki identifies the Research Center and its three branches: Growth, Economy, and Battle.
- Community strategy material is retained only as `STRATEGY_CANDIDATE`; it is not a hard-coded choice rule.
- The reviewed `AminulIslamSifat/wos` public capability list advertises Alliance Technology but not a general player Research task, so V2 records a capability gap rather than copying an implementation.

## Live-client facts (CN client, 720x1280)

- A stable navigation route was verified: top power value → `实力详情` → scroll to `科技实力` → `提升` → Research Center (`科研所`).
- The building is level 30 and displays a gold globe/planet structure.
- The technology page title is `科技研究` and the tabs are `发展`, `经济`, and `战斗`.
- The active Growth technology is `病房扩建VII`, progress `2/3`. A fresh 2026-09-04 recheck showed `5天00:55:44` remaining, confirming the queue is still active rather than relying on the prior `6天05:20:54` observation.
- An `加速` action is available. The selected-building view also exposed a 119,490-gem instant completion action; it was intentionally not used because a six-day queue does not justify that cost.

## Skill result

`RESEARCH` is `BLOCKED` with `QUEUE_BUSY`, not `FAILED` and not `UNKNOWN`. The Brain emits `SAFE_STOP/switch_task`; it does not retry the queue or guess-click another node. `verify_research_queue` proves the blocker using page + active node + visible timer + queue-unavailable state.

## Future unblock condition

When the queue becomes available, inspect a research node's prerequisite/cost screen, select a normal-resource candidate, start it, and require the transition `queue_available=true → IN_PROGRESS + timer + expected node` before promoting the Skill to `VERIFIED`.
