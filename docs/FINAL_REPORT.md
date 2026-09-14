# Winter Agent OS V2 — Current Evidence Report

Updated: 2026-09-07. This report distinguishes live success, replay simulation, blocked state, and test coverage.

1. **Real WOS material:** official product/update/help material, community databases, Chinese guides, video/UI references, four automation repositories, legacy evidence, and 964 audited screenshots.
2. **Official:** Century Games/Whiteout Survival product, update, help, Beast, and Alliance material; used as priors, never substitutes for client verification.
3. **Wiki/database:** Whiteout Survival Wiki/Community and WOS Forge supplied system and workflow priors.
4. **Player guides:** TapTap and other Chinese guides enter only `STRATEGY_CANDIDATE` unless live evidence confirms them.
5. **Automation projects:** `AminulIslamSifat/wos`, `whiteout-project/bot`, `Shederator/wosbot`, and `batazor/whiteout-survival-autopilot`.
6. **Useful ideas:** template/OCR layering, normalized ROI, small capability flows, queue rereads, bounded retry, and state-change verification.
7. **Excluded:** whole external architectures, credentials, account data, fixed external coordinates, unknown-license production media, and payment automation.
8. **Knowledge Base:** 73 game/system entries, plus 70 provenance source records. It remains a growing seed.
9. **UI semantics:** 93.
10. **Templates:** 316 normalized ROI candidates; 0 Production.
11. **Icons:** 51 current-client visual semantics `VERIFIED`; 0 Production.
12. **Skills:** 42 in the single registry: 40 `VERIFIED`, 2 `BLOCKED`.
13. **Stable:** 0. Code or one success never means stable.
14. **Candidate:** remaining special Intel variants, remaining Daily variants, GIANT_BEAST, BEAR, generic EVENT, ARENA, PET, Exploration stage combat, and broader Alliance operations.
15. **Blocked:** `RESEARCH` (queue busy) and `ALLIANCE_HELP` (Auto Help active, no manual action). These are availability states, not execution failures.
16. **Vision:** explicitly tested live semantic subset now includes cross-tab Mail badge/reward/all-clear transitions and distinct ordinary Beast, Firebeast, Rescue Survivors, Hero Journey, and Master Bounty routing. Replay maps 110 labeled samples and is `SIMULATION`; this is not a general-game accuracy claim.
17. **OCR:** Hybrid Vision structures Research, Training, Alliance counters/rewards/gift badges, and Daily progress/activity. Live Ally Gift badge transitions were read independently; this is not yet a general OCR rate.
18. **GATHER_RESOURCE:** five completed natural live successes; acceptance attempts 6–8 are `3/3 SUCCESS`. The bounded runtime additionally completed nine verifier-clean unattended dispatch starts. These starts are not counted as additional completed natural cycles.
19. **BUILD:** 1 live success, Warehouse 26→27.
20. **RESEARCH:** 0 starts; correctly blocked on active `病房扩建VII 2/3`, freshly rechecked with `5天00:55:44` remaining.
21. **TRAIN:** 1 live Infantry T10 start; 806 troops, timer 10:03:12. Lancer/Marksman start variants remain unverified.
22. **Largest failure source:** general Vision/OCR coverage outside calibrated flows.
23. **Task switching:** Production evidence proves TRAIN→WOOD GATHERING, Alliance contributions→Daily claim, and Mail all-clear→Intel→Beast→reserved Gather fallback. Cross-page unattended endurance beyond bounded runs remains unproven.
24. **Recovery:** game-day reset was rejected, Alliance Gifts was reopened, and the bounded retry succeeded. List reorder and asynchronous alliance progress now have explicit verifier handling.
25. **Learning:** verified live actions and failures are now automatically written as Episodes, including before/after state, action, result, failure type, duration, and execution mode; proposals never self-promote directly.
26. **Cannot yet do:** broad OCR, general-event understanding, long endurance runs, multi-role isolation, or claim any skill `STABLE`.
27. **Best next work:** extend the verifier-gated reward sweep from Mail into Daily/Alliance/Exploration, consume full stamina through safe Beast/Intel tasks, then run a bounded endurance loop; re-attempt Research when its queue frees.

## Totals

| Metric | Count |
|---|---:|
| Provenance source records | 70 |
| External projects | 4 |
| Game knowledge entries | 73 |
| UI semantics | 93 |
| Raw screenshots | 964 |
| Candidates / duplicates / damaged | 583 / 381 / 0 |
| Candidate ROI templates | 316 |
| Verified visual semantics | 51 |
| Registered skills | 42 |
| Verified / blocked / stable | 40 / 2 / 0 |
| Tests passed / failed | 165 / 0 |
| Replay samples | 110 (`SIMULATION`) |
| Consecutive accepted gathers | 3 |

## Latest Production evidence

- Victory Loot gifts: 2 successes / 3 attempts; the reset-crossing attempt was rejected and recovered.
- Ally Gifts: 9/9 verified claims. Eight were executed by Brain → Scheduler → Skill → Executor; observed rewards included level-1 +30 and level-3 +120 chest points.
- Cleared-state smoke: Hybrid Vision reported badge 0 and `CLAIMED`; the production loop emitted `SAFE_STOP` and performed zero clicks.
- BACK: Production device action returned Alliance Gifts → Alliance → HOME and both transitions were re-observed by Vision.
- Unattended Gather start: nine verifier-clean bounded dispatches ran without intervention. The desktop control panel itself most recently observed `5/6`, executed four verifier-passing actions to reach `6/6`, then automatically ran the full-queue check, emitted `SAFE_STOP/no_idle_march` with zero clicks, and scheduled a 10-minute recheck.
- Search Vision recovery: one 5/6 map frame missed the search semantic and was safely blocked. The screenshot became a Replay sample/Candidate template, a narrowly scoped tolerance was added, and live retry passed.
- Live recovery learned that Android BACK on MAP opens an exit-confirmation popup. Vision now recognizes and closes it; `OPEN_HOME` is the correct map-to-city action.
- Dynamic march counts such as 3/6 and 4/6 are now OCR fields rather than fixed templates.
- The desktop task selector uses explicit states: green `✓ 已启用` executes, gray `○ 未启用` does not execute, and `◇ 待接入` cannot yet be selected. Gather and normal-Beast priority are wired into the panel; unsupported tasks remain unselectable.
- The panel now creates a timestamped screenshot directory for every unattended run. This fixed a real Windows `WinError 5` caused by reusing an old screenshot filename. The post-fix Production chain checked Intel, checked Beast, dispatched Wood gathering from 4/6→5/6 with four verifier passes, then performed a zero-click 5/6 guard and scheduled a 10-minute recheck while preserving one stamina march.
- A known intermediate resource-search frame now triggers observation-only refresh and never a duplicate click. The latest live validation wrote one safe semantic failure Episode followed by four verifier-passing action Episodes.
- Startup bootstrap now accepts only pages supported by the Gather route. It waits once on a transient UNKNOWN frame, backs out of persistent UNKNOWN or known unsupported pages within a fixed budget, and reports `BOOTSTRAP_PAGE_NOT_RECOVERED` instead of launching a guaranteed no-op run.
- Stamina-priority recovery: a 6/6 all-gathering state was corrected by recalling one march. A level-29 Snow Leopard was rejected on a red low-win warning; three level-9 Musk Ox hunts and one level-6 Arctic Wolf hunt passed green victory checks, dispatch, and natural return. Displayed committed cost was 40 stamina; exact numeric balance was not visible and is not claimed. Gather now stops at 5/6 with `reserved_march_for_stamina`; the panel checks normal Beast first and safely falls back to the reserved Gather state.
- Event minimum guarantee: the live `军备竞演` page established variant-specific rules and tiers. The Agent spent 80 Hero Gear Essence Stones (preserving speedups), verified 0→64,000 points, exceeded the 38,000 target, and claimed all four progress tiers.
- Intel Beast: ten live level-10 ordinary Beast Intel missions completed and claimed. Blue, purple, orange paw, and purple claw pins were confirmed as the same Beast mission family. The automatic chain selected the pin, opened the level-22 Great Horned Deer target, required `victory assured`, dispatched, returned, reopened Intel, reread stamina, claimed, and dismissed the reward overlay.
- Intel Firebeast: two `狩猎炽红巨兽 等级10` missions completed and claimed. The live target was level 20, recommendation 1,467,020, and displayed cost 10 stamina. Both runs passed target, victory, dispatch, claim, and reward-dismiss verification.
- Intel Rescue Survivors: one `营救幸存者 等级10` mission completed and claimed. The client displayed a 12-stamina cost; evidence records target, active exploration, claimable state, reward feedback, and cleared claim.
- Intel special missions: purple crossed axes were identified as `英雄之旅 等级10`; one Production attempt consumed the displayed 10 stamina and the live map reported `失败`, so it is `BLOCKED`, not complete. The orange rabbit was identified as `大师悬赏：20号`; its current recommendation was 189,295,920 versus observed chief power 56,089,968, so no dispatch was made. Title-first routing now prevents either task from entering the ordinary Beast chain.
- The alliance chest total moves asynchronously as other members act. Total progress alone is therefore insufficient; the Verifier also requires a personal badge, target-row, or exhausted-list transition.
- Reward audit: Mail, Daily/Growth, Alliance Gifts, four free event surfaces, and Exploration produced live rewards. The incremental Mail pass yielded 5 Fire Crystals and ended with all category badges clear.
- Mail sweep: the latest Production run cleared Report 10, Alliance 4, and System 5 badges. A subsequent unattended smoke verified zero-click all-clear, single execution-lane behavior, goal isolation, and continuation to the next enabled task.
- Desktop control-panel audit: Windows console-window leakage was traced to visible `python.exe`/ADB children. All runtime and ADB children now use background/no-window flags; a named single-instance guard rejects duplicate launches; refresh has a re-entry guard; Tk task choices are snapshotted before worker execution; chained task labels are normalized; and structured JSON stays in `latest.log` rather than flooding the GUI. A live restart, duplicate-launch probe, and Mail→Intel→Beast→Gather cycle passed with exactly one visible panel window.
- Red-dot classification: Alliance War, Territory migration, Pet Skills, Chief Orders, merchant refresh/purchases, Arms Race information, and Treasure Hunter actions are not counted as unclaimed rewards.
- Exploration idle income: one 9-hour claim produced 29,000 Steel, 80,000 Hero EXP, and three gear items; re-entry showed the claim control disabled.

Primary evidence is in `learning/`, `evidence/p0_gate.json`, `evidence/reward_claim_production.json`, `tests/replay/labels.json`, and the per-skill research reports.
