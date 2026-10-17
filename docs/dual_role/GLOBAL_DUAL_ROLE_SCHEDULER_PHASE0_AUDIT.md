# Global dual-role Scheduler V1 — Phase 0 status audit

Audit date: 2026-09-29 (Asia/Shanghai)

This is a delta audit of the current workspace and the clean pinned production runtime. It does not claim that dual-role production execution is complete.

## Current evidence

- The DEV root is on `main` at `7caf38c`, 16 commits behind `origin/main`, with extensive pre-existing modified and untracked files. It is not a safe production launch tree.
- The running production snapshot records a worker loaded from `E:\WinterAgent\.worktrees\prod\repo`; its latest snapshot at audit time is still single-role (`CLEAR_INTEL` / `DISPATCH_INTEL_BEAST`). No production restart or device input was performed for this audit.
- `Scheduler.select_next()` is the production call from `LiveRuntime.run()`. Its normal path receives the current frame's single `WorldState`. `select_global()` and `RoleObservation` exist in the dirty DEV source and have focused unit tests, but no runtime caller constructs a multi-role observation set.
- `tools/run_live.py` reads one current-role artifact through `TruthAudit` at process startup and passes that `role_id` into one `LiveRuntime`. The production worker does not enumerate configured roles or switch between them.
- `GoalStateStore` now writes a role-keyed `roles` map while retaining the legacy current-role board. This preserves observed goal boards; it does not create fresh inactive-role observations or authorize an action from cached state.
- `event_schedule` stores occurrences by role. Runtime event and goal discovery use the currently confirmed role scope. There is no single global wake coordinator across role workers.
- `ActiveRoleLiveState` invalidates page/frame/OCR/queue/rally/resource/event caches in DEV Scheduler code, but it is not wired to a role-switch transaction or production runtime.
- Role identity parsing and recording exist. A prior helper (`tools/switch_role.py`) failed because it assumed the wrong settings-page layout; it is not production code.
- A live role-manager exploration on 2026-09-29 confirms two selectable characters in kingdom 4298 and a reversible switch in both directions. Role A is account `1063040265`, `[ioi]零氪纯盾流`; Role B is account `1061663148`, `[DIW]xhw`. The observed path is profile avatar → 设置 → 角色管理 → select existing row → 登录 confirmation → loading → fresh profile identity read. Role A was restored before AUTO resumed.
- Historical account `1171757165` is not present in the current role-manager list and is not one of these two configured roles.
- This is live UI evidence, not yet a production capability: `ROLE_SWITCH` still has no registered Skill/verifier, and `Scheduler.select_global()` is not called by the pinned production runtime.
- `learning/runtime_snapshot.json` and the control panel show one active device owner and one AUTO worker. The device lease is shared by existing AUTO and development validation; no second input path was introduced.

## Answers to Phase 0

1. **Scheduler selects the next action from the current frame.** The production loop discovers the current frame's Goal board and picks a Skill; global scoring API code is present only in DEV and is not called by the runtime.
2. **Production currently processes one active role per worker cycle.** The worker has no configured-role iteration or global role arbitration loop.
3. **Role switching is not owned by production code.** Only an untracked, unsuccessful exploration script is present.
4. **No production switch hook currently invalidates every active UI cache.** A helper exists in dirty DEV scheduler code, but has no production caller.
5. **Cross-role state risk is reduced for goal snapshots and timed events, but not solved.** Goal boards and schedules are role-keyed; the active frame, observation cache, run meters, page hints, and current task are process-local and assume one role for the run.
6. **WAIT is local to the active-role run.** The global control panel may run another bounded cycle later, but it does not compare both roles before waiting.
7. **Episode and goal records can carry `role_id`; current goal storage preserves a role-keyed snapshot.** There is no global candidate identity including role key at the production dispatch boundary.
8. **Timed events are role-scoped.** There is no cross-role earliest-wakeup arbitration in production.
9. **Goal state is role-scoped in current DEV changes, with a legacy active-board view.** The role split has focused tests; no production rollout has been made from this dirty tree.
10. **Resources, stamina, queues, and activity state are observed for the active role only.** Other-role values, when present in historical artifacts, are not fresh execution state.
11. **Role-switch UI is now confirmed live in both directions.** Screenshots `dataset/raw/ui_exploration/multirole_20260929/role_explore_04_role_management.png`, `role_explore_05_role_b_select_dialog.png`, `role_explore_10_role_b_profile.png`, `role_explore_13_role_b_role_management.png`, `role_explore_14_role_a_select_dialog.png`, and `role_explore_19_dismiss_role_a_result.png` show the role list, confirmations, both profile identities, and return to Role A. The clicks used the existing leased device adapter; this does not yet prove a production MAA Skill.

## Implementation boundary

Safe to implement and test offline now: logical scheduler-state persistence, restart reconciliation rules, explainable bounded decision history, candidate scoring/de-duplication, and switch-transaction state transitions.

The live UI path and both target identities are now confirmed. Still required before production rollout: a MAA-backed role-switch action that targets only a catalogued role row, verifies the confirmation name, confirms the post-login account ID, persists the transaction, and forces a fresh WorldState observation before any task action. The pinned AUTO remains single-role until that action and global arbitration are wired and tested together.
